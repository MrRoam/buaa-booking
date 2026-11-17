from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from buaa_booking.config import CHINA, Config
from buaa_booking.adapter import ReleaseNotOpenError, RetryableQueryError, TransientQueryError, safe_server_message
from src.core.exceptions import CaptchaError, CaptchaLimitError
from buaa_booking.journal import Journal, RETRYABLE_REFUSALS
from buaa_booking.selection import Candidate, Choice, select_candidates


class Clock:
    def now(self):
        return datetime.now(CHINA)

    def monotonic(self):
        return time.monotonic()

    def sleep(self, seconds):
        time.sleep(seconds)

    def wait_until(self, target):
        while (remaining := (target - self.now()).total_seconds()) > 0:
            self.sleep(min(30, remaining))


def candidate_from_dict(raw: dict) -> Candidate:
    return Candidate(raw["date"], raw["venue_site_id"], raw["preference"],
                     tuple(Choice(**c) for c in raw["choices"]))


@dataclass
class Engine:
    config: Config
    adapter: object
    journal: Journal
    notify: object
    clock: object = None

    def __post_init__(self):
        self.clock = self.clock or (self.adapter.booking_clock() if hasattr(self.adapter, "booking_clock") else Clock())

    def trace(self, key, stage, **fields):
        self.journal.trace(key, stage, school_time=self.clock.now().isoformat(),
                           tick=self.clock.monotonic(), **fields)

    def run(self, target: date, *, execute: bool = False, scheduled: bool = False,
            rehearse: bool = False) -> dict:
        if execute and rehearse:
            raise ValueError("演练与真实提交不能同时开启")
        if not self.config.preferences:
            raise ValueError("尚未配置打球时段。check 可先验证登录和查场")
        if execute and (not self.config.enabled or not self.config.eligible(target)):
            raise ValueError("真实提交需要 enabled=true，且目标日期符合 dates 或 weekdays")
        if scheduled and hasattr(self.clock, "synchronize"):
            self.clock.synchronize()
        if target < self.clock.now().date():
            raise ValueError("目标日期已经过去")
        release = self.config.release_at(target) if scheduled else self.clock.now()
        deadline = release + timedelta(seconds=self.config.window_seconds)
        if scheduled and self.clock.now() >= deadline:
            result = {"status": "missed", "message": "已错过本次抢场窗口，未提交订单"}
            self.notify(result)
            return result
        key = f"{self.adapter.account_id}:{target.isoformat()}"
        if execute and scheduled and getattr(self.clock, "receipt", None):
            self.trace(key, "clock_synchronized", **self.clock.receipt)
        existing = self.journal.get(key) if execute else None
        if existing:
            if existing["status"] == "submitting":
                existing = self.journal.save(key, "unknown", message="上次进程在提交期间退出，请先在官方页面核对订单")
            if existing["status"] in {"submitted", "pending_payment"} and existing.get("trade_no"):
                self.adapter.authenticate()
                return self.confirm(key, existing["trade_no"], candidate_from_dict(existing["candidate"]))
            if existing["status"] not in RETRYABLE_REFUSALS:
                result = existing | {"message": "该目标已有执行记录，未再次下单。" + existing.get("message", "")}
                self.notify(result)
                return result
        if execute:
            self.trace(key, "preflight_start")
        try:
            self.adapter.preflight()
        except Exception as exc:
            if execute:
                self.trace(key, "preflight_failed", error_type=type(exc).__name__)
            raise
        if execute or rehearse:
            self.adapter.warm()
        if execute:
            self.trace(key, "preflight_ready")
        if scheduled:
            if hasattr(self.clock, "synchronize"):
                self.clock.wait_until(release - timedelta(seconds=25))
                self.clock.synchronize()
                if execute:
                    self.trace(key, "clock_resynchronized", **(getattr(self.clock, "receipt", None) or {}))
            if execute and hasattr(self.adapter, "prime_captcha"):
                self.clock.wait_until(release - timedelta(seconds=10))
                try:
                    self.trace(key, "captcha_prime_start")
                    self.adapter.prime_captcha()
                    self.trace(key, "captcha_prime_ready")
                except CaptchaLimitError as exc:
                    self.trace(key, "captcha_limit_stop", error_type=type(exc).__name__)
                    result = self.journal.save(key, "finished", message=str(exc))
                    self.notify(result)
                    return result
                except Exception as exc:
                    self.trace(key, "captcha_prime_failed", error_type=type(exc).__name__)
            self.clock.wait_until(release)
        end_tick = self.clock.monotonic() + max(0, (deadline - self.clock.now()).total_seconds())
        attempted = set()
        release_boundary_retries = 0
        preparations = existing.get("attempts", 0) if existing else 0
        last_failure = ""
        if existing and existing.get("candidate"):
            attempted.add(candidate_from_dict(existing["candidate"]).key)
        while self.clock.now() < deadline and self.clock.monotonic() < end_tick:
            if execute and preparations >= self.config.max_submissions:
                break
            try:
                if execute:
                    self.trace(key, "query_start")
                available = self.adapter.query_available(target.isoformat(), attempted) if hasattr(self.adapter, "query_available") else None
                info = available[0] if available is not None else self.adapter.query(target.isoformat())
            except RetryableQueryError as exc:
                if not execute:
                    raise
                self.trace(key, "query_retry", error_type=type(exc).__name__)
                if isinstance(exc, ReleaseNotOpenError):
                    delay = .1 if release_boundary_retries < 5 else max(.5, self.config.poll_seconds)
                    release_boundary_retries += 1
                elif isinstance(exc, TransientQueryError):
                    delay = .2
                else:
                    delay = 2.0
                self.clock.sleep(min(delay, max(0, (deadline - self.clock.now()).total_seconds())))
                continue
            except Exception as exc:
                if execute:
                    self.trace(key, "query_failed", error_type=type(exc).__name__)
                raise
            candidates = available[1] if available is not None else [c for c in select_candidates(info, target.isoformat(), self.config) if c.key not in attempted]
            if execute:
                self.trace(key, "query_result", candidate_count=len(candidates))
            if not candidates:
                if not execute:
                    return {"status": "no_availability", "message": "当前没有符合配置的空场，未提交订单"}
                poll_delay = min(.5, self.config.poll_seconds) if scheduled and self.clock.now() < release + timedelta(seconds=5) else self.config.poll_seconds
                self.clock.sleep(min(poll_delay, max(0, (deadline - self.clock.now()).total_seconds())))
                continue
            candidate = candidates[0]
            if not execute:
                if rehearse:
                    self.adapter.prepare(candidate, info)
                return {"status": "rehearsed" if rehearse else "dry_run", "candidate": candidate.to_dict(),
                        "message": "已校验验证码，未发送订单请求" if rehearse else "已查到可选方案，未发送订单请求"}
            prior = self.journal.get(key) or {"attempts": 0}
            if prior["attempts"] >= self.config.max_submissions:
                break
            self.trace(key, "prepare_start")
            preparations += 1
            try:
                prepared = self.adapter.prepare(candidate, info)
            except CaptchaLimitError as exc:
                last_failure = str(exc)
                self.trace(key, "captcha_limit_stop", error_type=type(exc).__name__, message=last_failure)
                break
            except CaptchaError as exc:
                last_failure = "验证码准备未通过"
                self.trace(key, "prepare_failed", error_type=type(exc).__name__,
                           message=safe_server_message(str(exc)))
                self.clock.sleep(min(2.0, max(0, (deadline - self.clock.now()).total_seconds())))
                continue
            except Exception as exc:
                self.trace(key, "prepare_failed", error_type=type(exc).__name__)
                raise
            self.trace(key, "prepare_ready", **getattr(self.adapter, "preparation_evidence", {}))
            # OCR and requests may take time. Do not submit past the deadline.
            if self.clock.now() >= deadline or self.clock.monotonic() >= end_tick:
                break
            self.journal.begin_submission(key, candidate.to_dict(), self.config.max_submissions)
            submit_tick = self.clock.monotonic()
            self.trace(key, "submit_start", attempt=prior["attempts"] + 1)
            try:
                outcome = self.adapter.submit(prepared)
            except Exception as exc:
                self.trace(key, "submit_unknown", error_type=type(exc).__name__,
                           duration_ms=round((self.clock.monotonic() - submit_tick) * 1000, 1))
                result = self.journal.save(key, "unknown", message=f"提交响应不明确（{type(exc).__name__}），请先核对官方订单；不会自动重发")
                self.notify(result)
                return result
            self.trace(key, "submit_result", status=outcome.status, server_code=outcome.server_code,
                       message=outcome.message, duration_ms=round((self.clock.monotonic() - submit_tick) * 1000, 1))
            if outcome.status == "submitted":
                self.journal.save(key, "submitted", trade_no=outcome.trade_no, message=outcome.message)
                return self.confirm(key, outcome.trade_no, candidate)
            result = self.journal.save(key, outcome.status, message=outcome.message, server_code=outcome.server_code)
            last_failure = outcome.message
            if outcome.status not in RETRYABLE_REFUSALS:
                self.notify(result)
                return result
            if outcome.status == "conflict":
                attempted.add(candidate.key)
            if outcome.status == "release_not_open":
                delay = .1 if release_boundary_retries < 5 else 2.0
                release_boundary_retries += 1
            else:
                delay = 2.0
            self.clock.sleep(min(delay, max(0, (deadline - self.clock.now()).total_seconds())))
        result = self.journal.save(key, "finished", message="窗口结束或已达准备/提交次数上限，未确认成功订单"
                                   + ("；最后原因：" + last_failure if last_failure else ""))
        self.notify(result)
        return result

    def confirm(self, key: str, trade_no: str, candidate: Candidate) -> dict:
        try:
            details = self.adapter.confirm(trade_no, candidate)
        except Exception as exc:
            record = self.journal.save(key, "submitted", trade_no=trade_no,
                                       message=f"已取得订单号，详情暂时无法核对（{type(exc).__name__}）；请立即检查官方订单")
            self.notify(record)
            return record
        status = details.pop("status")
        record = self.journal.save(key, status, **details)
        if status == "pending_payment" and not record.get("payment_url"):
            try:
                record = self.journal.save(key, status, payment_url=self.adapter.payment_link(trade_no))
            except Exception:
                record = self.journal.save(key, status, payment_url="https://cgyy.buaa.edu.cn/venue/home",
                                           message="订单已核对；付款入口生成失败，请从官方“我的订单”付款")
        self.notify(record)
        return record

    def watch(self, record: dict, max_seconds: int = 1200):
        if record.get("status") != "pending_payment":
            return record
        try:
            expire = datetime.fromisoformat(record["expire_time"].replace("Z", "+00:00"))
            expire = expire.replace(tzinfo=CHINA) if expire.tzinfo is None else expire
        except (ValueError, KeyError):
            return record
        stop = self.clock.monotonic() + max_seconds
        reminded = False
        while self.clock.monotonic() < stop:
            self.clock.sleep(5)
            remaining = (expire - self.clock.now()).total_seconds()
            try:
                details = self.adapter.confirm(record["trade_no"], candidate_from_dict(record["candidate"]))
            except Exception:
                if remaining <= 0:
                    record = self.journal.save(record["job_key"], "deadline_passed",
                                               message="付款截止时间已过，暂无法刷新状态；请检查官方订单")
                    self.notify(record)
                    return record
                if remaining <= 60 and not reminded:
                    self.notify(record | {"message": "付款剩余不足一分钟，暂无法刷新订单状态，请检查官方订单"})
                    reminded = True
                continue
            status = details.pop("status")
            record = self.journal.save(record["job_key"], status, **details)
            if status != "pending_payment":
                self.notify(record)
                return record
            if remaining <= 0:
                record = self.journal.save(record["job_key"], "deadline_passed",
                                           message="付款截止时间已过，请以官方订单状态为准")
                self.notify(record)
                return record
            if remaining <= 60 and not reminded:
                self.notify(record | {"message": "付款剩余不足一分钟，请及时处理"})
                reminded = True
        return record
