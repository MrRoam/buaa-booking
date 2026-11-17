from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from buaa_booking.adapter import LiveAdapter, SubmitOutcome
from buaa_booking.demo import demo_info
from buaa_booking.selection import select_candidates


def test_fallback_uses_only_authorized_other_venue_when_primary_exhausted(config, target):
    primary = demo_info(str(target))
    secondary = demo_info(str(target))
    secondary.site_param.venue_site_id = 39
    for space in secondary.space_schedules_by_date[str(target)]:
        space.venue_site_id = 39
        space.space_id += 100
    adapter = object.__new__(LiveAdapter)
    adapter.config = replace(config, fallback_venue_site_id=39)
    adapter.query = Mock(return_value=primary)
    other = SimpleNamespace(config=replace(config, venue_site_id=39), query=Mock(return_value=secondary),
                            prepare=Mock(return_value={'prepared': True}),
                            submit=Mock(return_value=SubmitOutcome('submitted','TEST')), preparation_evidence={})
    adapter.fallback_adapter = other
    _, first = adapter.query_available(str(target), set())
    assert first[0].venue_site_id == 38
    other.query.assert_not_called()
    exhausted = {c.key for c in select_candidates(primary, str(target), config)}
    info, candidates = adapter.query_available(str(target), exhausted)
    assert candidates and candidates[0].venue_site_id == 39
    adapter.workflow = object()
    adapter.primed_captcha = (123, 'data', 'proof')
    prepared = adapter.prepare(candidates[0], info)
    assert adapter.primed_captcha is None
    assert adapter.submit(prepared).trade_no == 'TEST'
    other.submit.assert_called_once_with(prepared)
