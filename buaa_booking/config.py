from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

CHINA = timezone(timedelta(hours=8), "Asia/Shanghai")


def minutes(value: str) -> int:
    parsed = time.fromisoformat(value)
    if parsed.second or parsed.microsecond or parsed.tzinfo or len(value) != 5:
        raise ValueError("时段必须使用 HH:MM 格式")
    return parsed.hour * 60 + parsed.minute


@dataclass(frozen=True)
class Preference:
    start: str
    end: str
    courts: tuple[str, ...] = ()
    allow_other_courts: bool = False


@dataclass(frozen=True)
class Config:
    path: Path
    enabled: bool
    venue_site_id: int
    dates: tuple[date, ...]
    weekdays: tuple[int, ...]
    release_lead_days: int
    release_time: time
    window_seconds: int
    poll_seconds: float
    max_submissions: int
    max_total_price: Decimal
    same_court: bool
    preferences: tuple[Preference, ...]
    notifications: dict
    fallback_venue_site_id: int | None = None

    def eligible(self, target: date) -> bool:
        return target in self.dates or target.isoweekday() in self.weekdays

    def release_at(self, target: date) -> datetime:
        return datetime.combine(target - timedelta(days=self.release_lead_days), self.release_time, CHINA)

    def today_target(self, now: datetime) -> date:
        return now.astimezone(CHINA).date() + timedelta(days=self.release_lead_days)

    def upcoming(self, now: datetime, days: int = 14) -> list[tuple[date, datetime]]:
        result = []
        for offset in range(days):
            target = self.today_target(now) + timedelta(days=offset)
            release = self.release_at(target)
            if self.eligible(target) and release + timedelta(seconds=self.window_seconds) >= now:
                result.append((target, release))
        return result


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    allowed = {"enabled", "venue_site_id", "dates", "weekdays", "release_lead_days", "release_time",
               "window_seconds", "poll_seconds", "max_submissions", "max_total_price", "same_court",
               "preferences", "notifications", "fallback_venue_site_id"}
    if data.keys() - allowed:
        raise ValueError(f"未知配置字段: {', '.join(sorted(data.keys() - allowed))}")
    for name in ("enabled", "same_court"):
        if type(data.get(name, False if name == "enabled" else True)) is not bool:
            raise ValueError(f"{name} 必须为 true 或 false")
    prefs = []
    for p in data.get("preferences", []):
        if p.keys() - {"start", "end", "courts", "allow_other_courts"}:
            raise ValueError("时段偏好中存在未知字段")
        duration = minutes(p["end"]) - minutes(p["start"])
        if duration not in (60, 120):
            raise ValueError("首版支持连续一小时或两小时，请明确起止时间")
        if type(p.get("allow_other_courts", False)) is not bool or not isinstance(p.get("courts", []), list):
            raise ValueError("courts 应为数组，allow_other_courts 应为布尔值")
        courts = tuple(str(c) for c in p.get("courts", []))
        prefs.append(Preference(p["start"], p["end"], courts, p.get("allow_other_courts", False)))
    if len(prefs) > 20:
        raise ValueError("最多配置 20 个有序时段偏好")
    site = data.get("venue_site_id", 38)
    lead = data.get("release_lead_days", 2)
    window = data.get("window_seconds", 60)
    submissions = data.get("max_submissions", 3)
    weekdays = tuple(data.get("weekdays", []))
    if type(site) is not int or site not in (38, 39):
        raise ValueError("学院路主馆用 38，副馆用 39")
    fallback = data.get("fallback_venue_site_id")
    if fallback is not None and (type(fallback) is not int or fallback not in (38, 39) or fallback == site):
        raise ValueError("备选馆必须为另一个学院路羽毛球馆")
    if type(lead) is not int or not 0 <= lead <= 7:
        raise ValueError("release_lead_days 必须为 0 至 7 的整数；上线前核对放场规则")
    if type(window) is not int or not 5 <= window <= 300:
        raise ValueError("window_seconds 应为 5 至 300 秒")
    if type(submissions) is not int or not 1 <= submissions <= 5:
        raise ValueError("max_submissions 应为 1 至 5")
    if any(type(w) is not int or not 1 <= w <= 7 for w in weekdays):
        raise ValueError("weekdays 使用 1=周一 至 7=周日，指打球日期")
    poll = float(data.get("poll_seconds", 1.0))
    price = Decimal(str(data.get("max_total_price", "100")))
    if not 0.5 <= poll <= 60 or not price.is_finite() or price <= 0:
        raise ValueError("轮询至少间隔 0.5 秒；最高总金额必须为正数")
    release = time.fromisoformat(data.get("release_time", "07:00:00"))
    if release.tzinfo or release.microsecond:
        raise ValueError("release_time 使用北京时间 HH:MM:SS")
    dates = tuple(date.fromisoformat(d) for d in data.get("dates", []))
    enabled = data.get("enabled", False)
    if enabled and (not prefs or not (dates or weekdays)):
        raise ValueError("启用自动预约前必须填写日期规则和时段偏好")
    notifications = data.get("notifications", {"desktop": True, "bark": False, "email": False})
    if not isinstance(notifications, dict) or notifications.keys() - {"desktop", "bark", "email"}:
        raise ValueError("notifications 仅支持 desktop、bark、email")
    if any(type(v) is not bool for v in notifications.values()):
        raise ValueError("通知开关必须为 true 或 false")
    return Config(path.resolve(), enabled, site, dates, weekdays, lead, release, window, poll,
                  submissions, price, data.get("same_court", True), tuple(prefs), notifications, fallback)
