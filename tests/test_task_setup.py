import json
from datetime import date, datetime

import pytest

from buaa_booking.config import CHINA, load_config
from buaa_booking.task_setup import plan_lines, task_payload, validated_write


def build(**changes):
    values = dict(base={"enabled": True, "notifications": {"desktop": True}}, mode="dates",
                  dates_text="2026-10-19", weekdays=[], ranges=[("19:00", "21:00")],
                  max_price="100", today=date(2026, 10, 16))
    return task_payload(**(values | changes))


def test_form_never_preserves_enabled_or_old_dates():
    result = build(base={"enabled": True, "weekdays": [2], "dates": ["2026-01-01"]})
    assert result["enabled"] is False
    assert result["dates"] == ["2026-10-19"]
    assert result["weekdays"] == []
    assert result["preferences"][0]["courts"] == []
    assert result["same_court"] is True


def test_weekly_mode_discards_date_text_and_sorts_days():
    result = build(mode="weekly", weekdays=[4, 2, 4], dates_text="bad unused text")
    assert result["dates"] == [] and result["weekdays"] == [2, 4]


@pytest.mark.parametrize("changes", [
    {"dates_text": ""}, {"dates_text": "2026-10-15"}, {"dates_text": "tomorrow"},
    {"mode": "weekly", "weekdays": []}, {"ranges": []},
    {"ranges": [("19:00", "22:00")]}, {"ranges": [("21:00", "19:00")]},
    {"ranges": [("19:00", "21:00"), ("19:00", "21:00")]},
    {"max_price": "NaN"}, {"max_price": "-1"}, {"max_price": "abc"},
])
def test_invalid_form_cannot_produce_a_task(changes):
    with pytest.raises(ValueError):
        build(**changes)


def test_release_preview_uses_play_date_minus_two_days():
    lines = plan_lines(build(), now=datetime(2026, 10, 16, 18, tzinfo=CHINA))
    assert "2026-10-19" in lines[0]
    assert "10-17 07:00" in lines[0]
    assert "06:55" in lines[0]


def test_already_released_dates_route_to_manual_booking():
    lines = plan_lines(build(dates_text="2026-10-18"), now=datetime(2026, 10, 16, 18, tzinfo=CHINA))
    assert "已放场" in lines[0] and "立即预约" in lines[0]


def test_invalid_staging_does_not_overwrite_working_config(tmp_path):
    path = tmp_path / "config.json"
    validated_write(path, build())
    before = path.read_bytes()
    with pytest.raises(ValueError):
        validated_write(path, build() | {"enabled": True, "preferences": []})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".check-*"))
    assert load_config(path).enabled is False


def test_one_off_payload_does_not_modify_daily_task(tmp_path):
    path = tmp_path / "config.json"
    validated_write(path, build(mode="weekly", weekdays=[2, 4]))
    before = path.read_bytes()
    manual = build(base=json.loads(before), dates_text="2026-10-17")
    assert manual["weekdays"] == [] and manual["dates"] == ["2026-10-17"]
    assert path.read_bytes() == before
