"""Translate the task form into the existing booking configuration."""
from __future__ import annotations

import json
import re
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from buaa_booking.config import CHINA, load_config, minutes
from buaa_booking.notify import atomic_text


def task_payload(base, *, mode, dates_text, weekdays, ranges, max_price, today=None):
    today = today or datetime.now(CHINA).date()
    if mode not in {"dates", "weekly"}:
        raise ValueError("请选择指定日期或每周重复")
    dates = []
    if mode == "dates":
        for value in re.split(r"[\s,，;；]+", dates_text.strip()):
            if not value:
                continue
            try:
                target = date.fromisoformat(value)
            except ValueError:
                raise ValueError("打球日期请填写 YYYY-MM-DD，多天用逗号分隔") from None
            if target < today:
                raise ValueError("打球日期不能早于今天")
            dates.append(target.isoformat())
        if not dates:
            raise ValueError("请先填写想打球的日期")
    elif not weekdays or any(type(d) is not int or d not in range(1, 8) for d in weekdays):
        raise ValueError("请至少选择一个打球的星期")
    if not ranges:
        raise ValueError("请添加至少一个打球时段")
    preferences = []
    for start, end in ranges:
        try:
            duration = minutes(end) - minutes(start)
        except ValueError:
            raise ValueError("时段请填写 HH:MM") from None
        if duration not in (60, 120):
            raise ValueError("每个时段需为连续 1 小时或 2 小时")
        item = {"start": start, "end": end, "courts": []}
        if item in preferences:
            raise ValueError("时段重复，请删除重复项")
        preferences.append(item)
    if len(preferences) > 20:
        raise ValueError("最多添加 20 个备选时段")
    try:
        price = Decimal(max_price)
    except InvalidOperation:
        raise ValueError("价格上限请填写正数金额") from None
    if not price.is_finite() or price <= 0:
        raise ValueError("价格上限请填写正数金额")
    return base | {"enabled": False, "venue_site_id": 38,
                   "dates": sorted(set(dates)),
                   "weekdays": sorted(set(weekdays)) if mode == "weekly" else [],
                   "preferences": preferences, "same_court": True,
                   "release_lead_days": 2, "release_time": "07:00:00",
                   "max_total_price": str(price)}


def validated_write(path: Path, payload: dict):
    """Validate a staging file before replacing the working configuration."""
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".check-", suffix=".json", delete=False) as file:
        staging = Path(file.name)
        file.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    try:
        load_config(staging)
        atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    finally:
        staging.unlink(missing_ok=True)


def plan_lines(payload, *, now=None, limit=8):
    now = now or datetime.now(CHINA)
    targets = {date.fromisoformat(value) for value in payload["dates"]}
    for offset in range(370):
        target = now.date() + timedelta(days=offset)
        if target.isoweekday() in payload["weekdays"]:
            targets.add(target)
    lines = []
    for target in sorted(targets):
        if target < now.date():
            continue
        release = datetime.combine(target - timedelta(days=2), datetime.min.time(), CHINA).replace(hour=7)
        if release <= now:
            note = "已放场，可用下方“立即预约”尝试余场"
        else:
            note = f"{release:%m-%d} 07:00 抢场（06:55 启动）"
        lines.append(f"打球 {target:%Y-%m-%d}  →  {note}")
        if len(lines) >= limit:
            break
    return lines
