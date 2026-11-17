from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from buaa_booking.config import CHINA
from buaa_booking.timing import SchoolClock, TimeSample, estimate


class ReferenceTime:
    def __init__(self):
        self.tick = 100.0
        self.wall_jump = -600.0
        self.epoch = 1_800_000_000.0

    def monotonic(self):
        return self.tick

    def wall(self):
        return self.epoch + self.tick + self.wall_jump

    def sleep(self, seconds):
        self.tick += seconds

    def probe(self):
        sent = self.tick
        server_second = int(self.epoch + self.tick + .005)
        self.tick += .01
        return TimeSample(sent, self.tick, server_second)


def clock_for(source):
    return SchoolClock(probe=source.probe, wall_time=source.wall,
                       monotonic=source.monotonic, sleep=source.sleep)


def test_school_time_corrects_ten_minutes_of_local_clock_skew():
    source = ReferenceTime()
    clock = clock_for(source)
    receipt = clock.synchronize()
    assert abs(clock.now().timestamp() - (source.epoch + source.tick)) < .2
    assert abs(receipt['offset_ms'] - 600_000) < 200
    assert 0 < receipt['uncertainty_ms'] < 200
    assert receipt['samples'] == 8


def test_wall_clock_adjustments_do_not_move_the_release_timer():
    source = ReferenceTime()
    clock = clock_for(source)
    clock.synchronize()
    before = clock.now()
    source.wall_jump += 3600
    source.tick += 2
    assert (clock.now() - before).total_seconds() == pytest.approx(2)


def test_wait_finishes_at_target_instead_of_rounding_up_to_seconds():
    source = ReferenceTime()
    clock = clock_for(source)
    target = clock.now() + timedelta(seconds=.017)
    clock.wait_until(target)
    assert 0 <= (clock.now() - target).total_seconds() < .001


def test_inconsistent_or_missing_http_time_cannot_silently_use_local_time():
    with pytest.raises(RuntimeError):
        estimate([])
    with pytest.raises(RuntimeError):
        estimate([TimeSample(100, 100.01, 1000), TimeSample(101, 101.01, 1001), TimeSample(102, 102.01, 900)])


def test_signing_uses_the_same_calibrated_timestamp():
    from src.api.client import ApiClient
    from src.config.settings import ApiSettings, AuthSettings
    from src.utils.sign_utils import SignBuilder
    client = ApiClient(api_settings=ApiSettings(), auth_settings=AuthSettings('', ''),
                       sign_builder=SignBuilder(prefix='test'), timestamp_provider=lambda: 1234567890123)
    response = Mock()
    response.json.return_value = {'code': 200}
    client._request_with_retry = Mock(return_value=response)
    client.get('/api/example', {}, sign_parts=[])
    assert client._request_with_retry.call_args.kwargs['headers']['timestamp'] == '1234567890123'
    client.post('/api/example', {}, sign_parts=[])
    assert client._request_with_retry.call_args.kwargs['headers']['timestamp'] == '1234567890123'


def test_primed_captcha_is_fresh_one_use_and_does_not_repeat_ocr(monkeypatch):
    from buaa_booking.adapter import LiveAdapter
    adapter = LiveAdapter.__new__(LiveAdapter)
    adapter.config = SimpleNamespace(venue_site_id=38)
    adapter.warm = lambda: None
    adapter.validate_buddies = lambda info: None
    adapter.workflow = SimpleNamespace(
        _verify_captcha_with_retry=Mock(return_value=(SimpleNamespace(token='token'),
            SimpleNamespace(verification=SimpleNamespace(verify_json='verified')))),
        _resolve_buddy_ids=lambda info: '17')
    adapter.primed_captcha = None
    candidate = SimpleNamespace(venue_site_id=38, date='2026-10-26', choices=[SimpleNamespace(space_id=1, time_id=2)], price=50)
    adapter.prime_captcha()
    adapter.prepare(candidate, None)
    assert adapter.workflow._verify_captcha_with_retry.call_count == 1
    adapter.prepare(candidate, None)
    assert adapter.workflow._verify_captcha_with_retry.call_count == 2
    adapter.prime_captcha()
    timestamp, data, verification = adapter.primed_captcha
    adapter.primed_captcha = (timestamp - 16, data, verification)
    adapter.prepare(candidate, None)
    assert adapter.workflow._verify_captcha_with_retry.call_count == 4
