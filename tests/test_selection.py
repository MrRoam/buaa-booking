from dataclasses import replace
from decimal import Decimal

from buaa_booking.config import Preference
from buaa_booking.demo import demo_info
from buaa_booking.selection import select_candidates


def test_exact_requested_date_even_if_server_lists_another_date_first(config, target):
    info = demo_info(str(target))
    info.reservation_date_list.insert(0, "2026-10-17")
    result = select_candidates(info, str(target), config)
    assert len(result) == 2
    assert all(c.date == str(target) for c in result)


def test_adjacent_array_entries_with_a_real_time_gap_are_rejected(config, target):
    assert select_candidates(demo_info(str(target), gap=True), str(target), config) == []


def test_never_silently_switch_courts_midway(config, target):
    info = demo_info(str(target))
    a, b = info.space_schedules_by_date[str(target)]
    a.slots["2"].is_available = False
    b.slots["1"].is_available = False
    assert select_candidates(info, str(target), config) == []
    choices = select_candidates(info, str(target), replace(config, same_court=False))
    assert len(choices) == 1
    assert len({c.space_id for c in choices[0].choices}) == 2


def test_exact_court_restrictions_and_fallback_priority(config, target):
    info = demo_info(str(target))
    preferred = replace(config, preferences=(Preference("19:00", "21:00", ("2号",)),))
    assert [c.choices[0].court for c in select_candidates(info, str(target), preferred)] == ["2号"]
    fallback = replace(config, preferences=(Preference("19:00", "21:00", ("2号",), True),))
    assert [c.choices[0].court for c in select_candidates(info, str(target), fallback)] == ["2号", "1号"]


def test_budget_is_for_entire_order_and_no_implicit_shorter_duration(config, target):
    assert select_candidates(demo_info(str(target)), str(target), replace(config, max_total_price=Decimal("49.99"))) == []
    info = demo_info(str(target))
    for space in info.space_schedules_by_date[str(target)]:
        space.slots["2"].is_available = False
    assert select_candidates(info, str(target), config) == []


def test_priority_between_whole_time_preferences(config, target):
    prefs = (Preference("20:00", "21:00"), Preference("19:00", "20:00"))
    choices = select_candidates(demo_info(str(target)), str(target), replace(config, preferences=prefs))
    assert [c.preference for c in choices] == [0, 0, 1, 1]


def test_missing_target_does_not_book_first_available_day(config, target):
    assert select_candidates(demo_info("2026-10-17"), str(target), config) == []


def test_price_is_not_rounded_to_a_different_amount(config, target):
    info = demo_info(str(target))
    for space in info.space_schedules_by_date[str(target)]:
        space.slots["1"].order_fee = 25.5
    assert select_candidates(info, str(target), config) == []
