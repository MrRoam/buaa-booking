from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from buaa_booking.availability import fetch_board, price_label, summarize_slots
from buaa_booking.config import CHINA
from buaa_booking.demo import demo_info

NOW = datetime(2026, 10, 16, 13, 30, tzinfo=CHINA)
TARGET = "2026-10-18"


def test_one_hour_counts_without_exposing_court_numbers():
    rows = summarize_slots(demo_info(TARGET), TARGET, NOW)
    assert rows == [{"start": "19:00", "end": "20:00", "remaining": 2, "price_min": "25", "price_max": "25"},
                    {"start": "20:00", "end": "21:00", "remaining": 2, "price_min": "25", "price_max": "25"}]
    assert all("court" not in row and "space_id" not in row for row in rows)


def test_two_hours_count_intersection_of_same_courts_and_show_total_price():
    info = demo_info(TARGET)
    info.space_schedules_by_date[TARGET][0].slots["2"].is_available = False
    assert summarize_slots(info, TARGET, NOW, 2) == [
        {"start": "19:00", "end": "21:00", "remaining": 1, "price_min": "50", "price_max": "50"}]


def test_two_hours_never_assume_different_courts_can_be_combined():
    info = demo_info(TARGET)
    a, b = info.space_schedules_by_date[TARGET]
    a.slots["1"].is_available = False
    b.slots["2"].is_available = False
    assert summarize_slots(info, TARGET, NOW, 2) == []


def test_real_gaps_and_duplicate_space_rows_do_not_inflate_counts():
    assert summarize_slots(demo_info(TARGET, gap=True), TARGET, NOW, 2) == []
    info = demo_info(TARGET)
    info.space_schedules_by_date[TARGET].append(info.space_schedules_by_date[TARGET][0])
    assert summarize_slots(info, TARGET, NOW)[0]["remaining"] == 2


def test_unavailable_slots_are_excluded_and_price_range_is_honest():
    info = demo_info(TARGET)
    info.space_schedules_by_date[TARGET][0].slots["1"].order_fee = 35
    row = summarize_slots(info, TARGET, NOW)[0]
    assert row["remaining"] == 2
    assert price_label(row) == "¥25–35"
    info.space_schedules_by_date[TARGET][0].slots["1"].is_available = False
    row = summarize_slots(info, TARGET, NOW)[0]
    assert row["remaining"] == 1
    assert price_label(row) == "¥25"


def test_today_hides_started_time_slots():
    now = NOW.replace(hour=19, minute=1)
    rows = summarize_slots(demo_info("2026-10-16"), "2026-10-16", now)
    assert len(rows) == 1
    assert rows[0]["start"] == "20:00"


def test_board_only_uses_read_only_queries_without_order_parameters(config):
    calls = []
    class Adapter:
        def __init__(self):
            self.config = config
        def authenticate(self):
            calls.append("authenticate")
        def query(self, target, *, include_order_params):
            assert include_order_params is False
            calls.append(target)
            return demo_info(target)
    board = fetch_board(Adapter(), NOW)
    assert calls == ["authenticate", "2026-10-16", "2026-10-17", "2026-10-18"]
    assert len(board["days"]) == 3
    assert all(d["state"] == "ok" for d in board["days"])


def test_failed_day_is_not_reported_as_zero_availability(config):
    class Adapter:
        def __init__(self):
            self.config = config
        def authenticate(self):
            pass
        def query(self, target, **kwargs):
            if target.endswith("17"):
                raise TimeoutError("not written into UI or cache")
            return demo_info(target)
    board = fetch_board(Adapter(), NOW)
    assert [d["state"] for d in board["days"]] == ["ok", "error", "ok"]
    assert "not written" not in str(board)


def test_unreleased_day_has_a_distinct_state(config):
    class Adapter:
        def __init__(self):
            self.config = config
        def authenticate(self):
            pass
        def query(self, target, **kwargs):
            info = demo_info(target)
            info.space_schedules_by_date.clear()
            return info
    assert all(d["state"] == "not_open" for d in fetch_board(Adapter(), NOW)["days"])
