from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from buaa_booking.adapter import LiveAdapter
from buaa_booking.demo import demo_info
from buaa_booking.selection import select_candidates


def verification(token):
    return SimpleNamespace(token=token), SimpleNamespace(verification=SimpleNamespace(verify_json='private-proof'))


@pytest.mark.parametrize('age,use_cached', [(10, True), (15, True), (15.01, False), (-1, False)])
def test_actual_adapter_consumes_only_recent_captcha_once(config, target, monkeypatch, age, use_cached):
    adapter = object.__new__(LiveAdapter)
    adapter.config = config
    adapter.validate_buddies = Mock()
    adapter.warm = Mock()
    adapter.workflow = SimpleNamespace(_verify_captcha_with_retry=Mock(return_value=verification('fresh')),
                                       _resolve_buddy_ids=Mock(return_value='buddy'))
    adapter.primed_captcha = (100 - age, *verification('cached'))
    monkeypatch.setattr('buaa_booking.adapter.time.monotonic', lambda: 100)
    info = demo_info(str(target))
    candidate = select_candidates(info, str(target), config)[0]
    first = adapter.prepare(candidate, info)
    assert first['captcha_token'] == ('cached' if use_cached else 'fresh')
    assert adapter.primed_captcha is None
    assert adapter.preparation_evidence['captcha_source'] == ('primed' if use_cached else 'fresh')
    second = adapter.prepare(candidate, info)
    assert second['captcha_token'] == 'fresh'
    assert adapter.workflow._verify_captcha_with_retry.call_count == (1 if use_cached else 2)


def test_actual_adapter_sanitizes_response_before_it_leaves_submit():
    adapter = object.__new__(LiveAdapter)
    adapter.secrets = {'password': 'short-secret', 'buddy_ids': '10001'}
    adapter.service = SimpleNamespace(submit_reservation=Mock(return_value=SimpleNamespace(raw={
        'code': 250, 'message': '同伴10001，password=short-secret captchaVerification=proof123 手机13800138000'})))
    outcome = adapter.submit({'captcha_token': 'a-token', 'captcha_verification': 'proof123'})
    for private in ['short-secret', '10001', 'proof123', '13800138000']:
        assert private not in outcome.message
    assert outcome.server_code == '250'
