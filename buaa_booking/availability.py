"""Read-only court counts, grouped by date and actual contiguous playing time."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from buaa_booking.config import CHINA, minutes


def summarize_slots(info, target: str, now: datetime, hours: int = 1) -> list[dict]:
    if hours not in (1, 2):
        raise ValueError("仅支持一小时或连续两小时")
    slots = sorted(info.time_slots, key=lambda s: s.begin_time)
    periods: dict[tuple[str, str], dict[int, Decimal]] = defaultdict(dict)
    for start in range(len(slots)):
        window = []
        expected = slots[start].begin_time
        for slot in slots[start:]:
            if slot.begin_time != expected or minutes(slot.end_time) <= minutes(slot.begin_time):
                break
            window.append(slot)
            expected = slot.end_time
            elapsed = minutes(expected) - minutes(window[0].begin_time)
            if elapsed >= hours * 60:
                break
        if not window or minutes(window[-1].end_time) - minutes(window[0].begin_time) != hours * 60:
            continue
        begin, end = window[0].begin_time, window[-1].end_time
        if target == now.date().isoformat() and begin <= now.strftime("%H:%M"):
            continue
        for space in info.space_schedules_by_date.get(target, []):
            if not info.site_param or space.venue_site_id != info.site_param.venue_site_id:
                continue
            states = [space.slots.get(str(slot.id)) for slot in window]
            if not all(state is not None and state.is_available for state in states):
                continue
            try:
                fees = [Decimal(str(state.order_fee)) for state in states]
            except Exception:
                continue
            if not all(f.is_finite() and f >= 0 for f in fees):
                continue
            # Count one physical court once, including a two-hour window.
            periods[(begin, end)][space.space_id] = sum(fees, Decimal("0"))
    rows = []
    for (begin, end), courts in sorted(periods.items()):
        prices = list(courts.values())
        rows.append({"start": begin, "end": end, "remaining": len(courts),
                     "price_min": format(min(prices).normalize(), "f"),
                     "price_max": format(max(prices).normalize(), "f")})
    return rows


def fetch_board(adapter, now: datetime | None = None) -> dict:
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    adapter.authenticate()
    days = []
    for offset in range(3):
        target = (now.date() + timedelta(days=offset)).isoformat()
        try:
            info = adapter.query(target, include_order_params=False)
            if target not in info.space_schedules_by_date:
                days.append({"date": target, "state": "not_open", "one_hour": [], "two_hours": []})
                continue
            days.append({"date": target, "state": "ok",
                         "one_hour": summarize_slots(info, target, now, 1),
                         "two_hours": summarize_slots(info, target, now, 2)})
        except Exception as exc:
            # Only a safe exception type; no auth identifiers or server bodies.
            days.append({"date": target, "state": "error", "error_type": type(exc).__name__,
                         "one_hour": [], "two_hours": []})
    return {"schema_version": 1, "queried_at": now.isoformat(),
            "venue_site_id": adapter.config.venue_site_id, "days": days}


def date_label(value: str, today: date) -> str:
    day = date.fromisoformat(value)
    offset = (day - today).days
    relative = {0: "今天", 1: "明天", 2: "后天"}.get(offset, "")
    return f"{relative}  {day.month}月{day.day}日".strip()


def price_label(row: dict) -> str:
    if row["price_min"] == row["price_max"]:
        return "¥" + row["price_min"]
    return "¥" + row["price_min"] + "–" + row["price_max"]
