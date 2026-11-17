from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from buaa_booking.config import CHINA, Config
from buaa_booking.selection import Candidate
from buaa_booking.vault import Vault
from src.api.client import ApiClient
from src.api.reservation_api import ReservationApi
from src.auth.manager import AuthManager
from src.config.env_store import EnvStore
from src.config.settings import ApiSettings, AuthSettings, SsoSettings, UserSettings
from src.core.reservation_service import ReservationService
from src.utils.crypto_utils import AesCbcEncryptor
from src.utils.sign_utils import SignBuilder

OFFICIAL_HOME = "https://cgyy.buaa.edu.cn/venue/home"


class RetryableQueryError(RuntimeError):
    """A read-only request can be retried within the booking window."""


class ReleaseNotOpenError(RetryableQueryError):
    """The server still considers the requested booking day outside its open range."""


@dataclass(frozen=True)
class SubmitOutcome:
    status: str
    trade_no: str = ""
    message: str = ""
    server_code: str = ""


def safe_server_message(value: str, secrets=()) -> str:
    for secret in sorted((str(s) for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, "[资料已隐藏]")
    value = re.sub(r"https?://\S+", "[链接已隐藏]", value)
    value = re.sub(r"(?i)((?:token|password|cookie|authorization|secret|captchaVerification)\s*[=:：]\s*)[^\s,，;；]+",
                   r"\1[资料已隐藏]", value)
    value = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[令牌已隐藏]", value)
    value = re.sub(r"\d{5,}", "[号码已隐藏]", value)
    value = re.sub(r"<[^>]*>", "", value)
    return " ".join(value.split())[:240] or "服务端未提供具体原因"


def classify_submission(raw: dict, *, secrets=()) -> SubmitOutcome:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    code = str(raw.get("code", ""))
    code = code if re.fullmatch(r"\d{1,6}", code) else ""
    messages = [str(obj[key]) for obj in (raw, data) for key in ("message", "msg", "repMsg")
                if isinstance(obj.get(key), str) and obj[key]]
    message = "；".join(dict.fromkeys(messages))
    reason = safe_server_message(message, secrets)
    explanation = f"服务器回复（业务码 {code or '缺失'}）：{reason}"
    def outcome(status):
        return SubmitOutcome(status, message=explanation, server_code=code)
    if code == "200":
        if not data.get("tradeNo"):
            return outcome("unknown")
        return SubmitOutcome("submitted", str(data["tradeNo"]), "服务器已返回订单号", code)
    # Contradictory order data and generic server failures must never trigger a replay.
    if data.get("tradeNo") or not code or (code.startswith("5") and code != "511"):
        return outcome("unknown")
    # Official frontend HTTP_STATUS.NETWORK_AUTH=511 calls doVerify again.
    if code == "511":
        return outcome("captcha_invalid")
    if re.search(r"同伴|同行|身份|登录|Token|token|权限", message):
        return outcome("rejected")
    if re.search(r"验证码.{0,8}(?:失效|过期|错误|不正确|无效|校验失败|验证失败)", message):
        return outcome("captcha_invalid")
    if re.search(r"未到预约时间|尚未开放预约|尚未放场|未开放预约", message):
        return outcome("release_not_open")
    if re.search(r"已被预约|已被预订|已被预定|已被抢占|场地.*冲突|场地.*已.*预约", message):
        return outcome("conflict")
    if re.search(r"访问频繁|请求频繁|限流|限制访问|稍后再试", message):
        return outcome("rate_limited")
    return outcome("rejected")


def verify_detail(detail, candidate: Candidate) -> dict:
    expected = {(c.space_id, c.start, c.end) for c in candidate.choices}
    actual = {(s.venue_space_id, s.start_time.replace("T", " ").split(" ")[-1][:5],
               s.end_time.replace("T", " ").split(" ")[-1][:5]) for s in detail.space_list}
    expected_start = candidate.date + " " + candidate.choices[0].start
    expected_end = candidate.date + " " + candidate.choices[-1].end
    matches = (actual == expected and len(detail.space_list) == len(candidate.choices)
               and detail.start_date.replace("T", " ").startswith(expected_start)
               and detail.end_date.replace("T", " ").startswith(expected_end)
               and Decimal(str(detail.pay_fee)) == candidate.price)
    if not matches:
        return {"status": "needs_review", "message": "订单详情与所选场地、日期、时段或金额不一致，请人工核对"}
    # Official frontend PAY_STATUS: 1 unpaid, 2 paid, 3 refunding, 4 refunded, 5 refund failed.
    status = "needs_review"
    if detail.pay_status in (3, 4, 5) and detail.order_status in (1, 2):
        status = {3: "refunding", 4: "refunded", 5: "refund_failed"}[detail.pay_status]
    elif detail.order_status == 2:
        status = "cancelled"
    elif detail.order_status == 1 and detail.pay_status == 2:
        status = "paid"
    elif detail.order_status == 1 and detail.pay_status == 1:
        status = "pending_payment"
    return {"status": status, "order_id": detail.order_id, "expire_time": detail.expire_time,
            "amount": str(detail.pay_fee),
            "message": "订单详情已核对" if status != "needs_review" else "订单状态需人工核对"}


class LiveAdapter:
    def __init__(self, config: Config, vault: Vault):
        self.config = config
        self.vault = vault
        self.secrets = vault.read()
        username = self.secrets.get("username", "")
        if not username or not self.secrets.get("password"):
            raise ValueError("尚未登录。请在本机运行 login；不要把密码发到聊天中")
        self.account_id = hashlib.sha256(username.encode()).hexdigest()[:20]
        self.api_settings = ApiSettings(
            venue_site_id=config.venue_site_id, prefix="c640ca392cd45fb3a55b00a63a86c618",
            app_key="8fceb735082b5a529312040b58ea780b", aes_cbc_key="c1h2i5n6g2o2k4a7",
            aes_cbc_iv="C2H3I4N5G2O3K1E4", retry_count=2, captcha_refetch_count=3,
        )
        self.auth = AuthSettings(self.secrets.get("cookie", ""), self.secrets.get("cg_authorization", ""))
        sso = SsoSettings(enabled=True, username=username, password=self.secrets["password"], persist_to_env=False)
        self.auth_manager = AuthManager(self.api_settings, self.auth, sso, env_store=EnvStore(environ={}))
        self.user = UserSettings(phone=self.secrets.get("phone", ""),
                                 buddy_ids=self.secrets.get("buddy_ids", ""), reservation_type="-1")
        self.client = ApiClient(api_settings=self.api_settings, auth_settings=self.auth,
                                sign_builder=SignBuilder(prefix=self.api_settings.prefix), retry_count=2)
        self.api = ReservationApi(self.client, self.api_settings, self.user)
        self.service = ReservationService(self.api, self.api_settings, self.user,
                                          AesCbcEncryptor(key=self.api_settings.aes_cbc_key.encode(),
                                                          iv=self.api_settings.aes_cbc_iv.encode()))
        self.workflow = None
        self.primed_captcha = None
        self.fallback_adapter = None
        self.active_submission_adapter = None

    def query_available(self, target, attempted):
        from buaa_booking.selection import select_candidates
        info = self.query(target)
        candidates = [c for c in select_candidates(info, target, self.config) if c.key not in attempted]
        if candidates or not self.config.fallback_venue_site_id:
            return info, candidates
        if self.fallback_adapter is None:
            self.fallback_adapter = LiveAdapter(replace(self.config, venue_site_id=self.config.fallback_venue_site_id,
                                                       fallback_venue_site_id=None), self.vault)
            self.fallback_adapter.client.timestamp_provider = self.client.timestamp_provider
        other = self.fallback_adapter
        info = other.query(target)
        return info, [c for c in select_candidates(info, target, other.config) if c.key not in attempted]

    def booking_clock(self):
        from buaa_booking.timing import SchoolClock
        clock = SchoolClock(self.config.path.parent / "data")
        self.client.timestamp_provider = clock.timestamp_ms
        return clock

    def authenticate(self):
        self.auth_manager.ensure_cgyy_auth()
        self.secrets.update(cookie=self.auth.cookie, cg_authorization=self.auth.cg_authorization)
        self.vault.write(self.secrets)

    def query(self, target: str, _auth_refreshed: bool = False, *, include_order_params: bool = True):
        import requests
        from src.parsers.day_info import parse_info_response
        try:
            raw = self.api.get_info(target, has_reserve_info=include_order_params)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise RetryableQueryError("查询连接暂时不可用") from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status == 429 or status >= 500:
                raise RetryableQueryError("查询服务暂时繁忙") from exc
            raise
        ok, message, info = parse_info_response(raw)
        if not ok and re.search(r"Token.*失效|token.*失效|未登录|登录.*过期", message):
            if not _auth_refreshed:
                self.authenticate()
                return self.query(target, _auth_refreshed=True, include_order_params=include_order_params)
        if not ok and re.search(r"最多只能查看\d+天后的预约|尚未开放|未到预约时间|未开放预约", message):
            raise ReleaseNotOpenError("目标日期尚未开放，等待服务器放场")
        if not ok and re.search(r"访问频繁|请求频繁|限流|限制访问|稍后再试|系统繁忙", message):
            raise RetryableQueryError("查询服务要求稍后重试")
        if not ok or info is None:
            raise RuntimeError("查询未通过，请用 check 核对登录和系统规则")
        if info.site_param is None or info.site_param.venue_site_id != self.config.venue_site_id:
            raise ValueError("未取得匹配的场馆信息，暂停提交")
        return info

    def validate_buddies(self, info):
        site = info.site_param
        ids = [x.strip() for x in self.user.buddy_ids.split(",") if x.strip()]
        if len(ids) != len(set(ids)):
            raise ValueError("同伴 ID 重复")
        if site.buddy_num_min and not self.user.phone:
            raise ValueError("缺少预约手机号，请运行 login 补充")
        if len(ids) < site.buddy_num_min or (site.buddy_num_max and len(ids) > site.buddy_num_max):
            raise ValueError(f"场馆要求 {site.buddy_num_min} 至 {site.buddy_num_max} 名同伴，请配置 buddy_ids")
        known = {str(b.id) for b in info.order_param_view.buddy_list} if info.order_param_view else set()
        if ids and not set(ids).issubset(known):
            raise ValueError("配置的同伴 ID 未出现在当前账号的同伴列表中")

    def preflight(self):
        self.authenticate()
        info = self.query(datetime.now(CHINA).date().isoformat())
        self.validate_buddies(info)
        return info

    def warm(self):
        if self.workflow is not None:
            return
        # Read-only checks do not need to load the OCR models.
        from src.api.captcha_api import CaptchaApi
        from src.core.captcha_service import CaptchaService
        from src.core.workflow import ReservationWorkflow
        self.workflow = ReservationWorkflow(CaptchaService(CaptchaApi(self.client)), self.service,
                                            self.api_settings.captcha_delay_min, self.api_settings.captcha_delay_max,
                                            self.api_settings, self.user)
        # Shared across priming, preparation retries and authorized venue fallback.
        self.workflow.captcha_service.fetch_budget = 3

    def prepare(self, candidate: Candidate, info):
        if candidate.venue_site_id != self.config.venue_site_id:
            if self.fallback_adapter is None or candidate.venue_site_id != self.config.fallback_venue_site_id:
                raise ValueError("场馆未获授权")
            other = self.fallback_adapter
            # Share a still-unused primed challenge; it is consumed only once.
            other.workflow = self.workflow
            other.primed_captcha, self.primed_captcha = self.primed_captcha, None
            result = other.prepare(candidate, info)
            self.preparation_evidence = other.preparation_evidence
            self.active_submission_adapter = other
            return result
        self.active_submission_adapter = None
        self.validate_buddies(info)
        self.warm()
        cached, self.primed_captcha = self.primed_captcha, None
        age = time.monotonic() - cached[0] if cached else None
        if cached and 0 <= age <= 15:
            _, data, verification = cached
            self.preparation_evidence = {"captcha_source": "primed", "captcha_age_ms": round(age * 1000, 1)}
        else:
            data, verification = self.workflow._verify_captcha_with_retry()
            self.preparation_evidence = {"captcha_source": "fresh", "captcha_age_ms": 0}
        buddy_ids = self.workflow._resolve_buddy_ids(info)
        return dict(captcha_token=data.token, captcha_verification=verification.verification.verify_json,
                    reservation_date=candidate.date, week_start_date=candidate.date,
                    reservation_order_json=json.dumps([{"spaceId": str(c.space_id), "timeId": str(c.time_id)}
                                                       for c in candidate.choices], separators=(",", ":")),
                    buddy_ids=buddy_ids, order_price=int(candidate.price))

    def prime_captcha(self):
        self.warm()
        data, verification = self.workflow._verify_captcha_with_retry()
        self.primed_captcha = (time.monotonic(), data, verification)

    def submit(self, prepared: dict) -> SubmitOutcome:
        if getattr(self, "active_submission_adapter", None) is not None:
            return self.active_submission_adapter.submit(prepared)
        result = self.service.submit_reservation(**prepared)
        # Scrub actual local credential values in addition to generic patterns.
        private = [v for v in self.secrets.values() if isinstance(v, str) and len(v) >= 4]
        private += [prepared.get("captcha_token"), prepared.get("captcha_verification")]
        return classify_submission(result.raw, secrets=private)

    def confirm(self, trade_no: str, candidate: Candidate) -> dict:
        ok, _, detail = self.service.get_order_detail_parsed(trade_no)
        if not ok or detail is None:
            raise RuntimeError("暂时未能读取订单详情")
        return verify_detail(detail, candidate)

    def payment_link(self, trade_no: str) -> str:
        # Only creates a cashier page. Never calls cashier /transaction/pay.
        from src.parsers.order import parse_order_pay_response
        ok, _, parsed = parse_order_pay_response(self.api.create_order_payment(trade_no))
        return parsed.school_pay_url if ok and parsed else OFFICIAL_HOME
