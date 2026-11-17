from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from buaa_booking.adapter import RetryableQueryError, SubmitOutcome
from buaa_booking.config import CHINA
from buaa_booking.demo import DemoAdapter, DemoClock
from buaa_booking.engine import Engine
from buaa_booking.journal import Journal, run_lock


@pytest.fixture
def runtime(config, target, tmp_path):
    clock = DemoClock(datetime(2026, 10, 16, 7, tzinfo=CHINA))
    adapter = DemoAdapter(str(target), clock)
    journal = Journal(tmp_path / "state")
    messages = []
    engine = Engine(config, adapter, journal, messages.append, clock)
    yield engine, adapter, journal, messages, clock
    journal.close()


def test_dry_run_never_loads_captcha_or_submits(runtime, target, monkeypatch):
    engine, adapter, journal, _, _ = runtime
    monkeypatch.setattr(adapter, "prepare", lambda *args: pytest.fail("dry-run called captcha"))
    result = engine.run(target)
    assert result["status"] == "dry_run"
    assert adapter.submissions == 0
    assert journal.latest() is None


def test_rehearsal_reaches_captcha_but_not_order(runtime, target):
    engine, adapter, journal, _, _ = runtime
    assert engine.run(target, rehearse=True)["status"] == "rehearsed"
    assert adapter.candidate is not None
    assert adapter.submissions == 0
    assert journal.latest() is None


def test_scheduled_verification_is_primed_before_release_but_order_is_not(runtime, target, monkeypatch):
    engine, adapter, _, _, clock = runtime
    release = clock.now()
    clock.current -= timedelta(minutes=5)
    events = []
    monkeypatch.setattr(adapter, 'prime_captcha', lambda: events.append(('prime', clock.now())), raising=False)
    original = adapter.submit
    def submit(payload):
        events.append(('submit', clock.now()))
        return original(payload)
    monkeypatch.setattr(adapter, 'submit', submit)
    assert engine.run(target, execute=True, scheduled=True)['status'] == 'pending_payment'
    assert events[0] == ('prime', release - timedelta(seconds=10))
    assert events[1][0] == 'submit' and events[1][1] >= release


def test_server_release_boundary_does_not_abort_the_booking(runtime, target, monkeypatch):
    from buaa_booking.adapter import ReleaseNotOpenError
    engine, adapter, _, _, clock = runtime
    original = adapter.query
    calls = []
    def query(value):
        calls.append(clock.monotonic())
        if len(calls) == 1:
            raise ReleaseNotOpenError('学校尚未放场')
        return original(value)
    monkeypatch.setattr(adapter, 'query', query)
    assert engine.run(target, execute=True, scheduled=True)['status'] == 'pending_payment'
    assert calls[1] - calls[0] == pytest.approx(.1)


def test_success_is_durable_before_order_query(runtime, target, monkeypatch):
    engine, adapter, journal, messages, _ = runtime
    original = adapter.confirm
    def confirm(trade, candidate):
        assert journal.latest()["status"] == "submitted"
        assert journal.latest()["trade_no"] == trade
        return original(trade, candidate)
    monkeypatch.setattr(adapter, "confirm", confirm)
    assert engine.run(target, execute=True)["status"] == "pending_payment"
    assert adapter.submissions == 1
    assert len(messages) == 1


def test_intent_is_fsynced_before_network_send(runtime, target, monkeypatch):
    engine, adapter, journal, _, _ = runtime
    original = adapter.submit
    def submit(payload):
        assert journal.latest()["status"] == "submitting"
        assert journal.latest()["attempts"] == 1
        assert journal.latest()["candidate"]["date"] == str(target)
        return original(payload)
    monkeypatch.setattr(adapter, "submit", submit)
    engine.run(target, execute=True)


def test_definite_conflict_switches_to_other_court(runtime, target):
    engine, adapter, _, _, _ = runtime
    adapter.scenario = "conflict"
    result = engine.run(target, execute=True)
    assert result["status"] == "pending_payment"
    assert result["candidate"]["choices"][0]["court"] == "2号"
    assert adapter.submissions == 2


def test_ambiguous_timeout_never_retries_even_after_process_restart(runtime, target):
    engine, adapter, journal, _, _ = runtime
    adapter.scenario = "timeout"
    assert engine.run(target, execute=True)["status"] == "unknown"
    assert engine.run(target, execute=True)["status"] == "unknown"
    assert adapter.submissions == 1
    assert journal.latest()["attempts"] == 1


def test_keyboard_interrupt_during_send_is_not_misclassified_as_rejected(runtime, target, monkeypatch):
    engine, adapter, journal, _, _ = runtime
    def crash(*args):
        raise KeyboardInterrupt
    monkeypatch.setattr(adapter, "submit", crash)
    with pytest.raises(KeyboardInterrupt):
        engine.run(target, execute=True)
    assert journal.latest()["status"] == "submitting"
    assert engine.run(target, execute=True)["status"] == "unknown"


def test_confirmed_order_is_not_submitted_twice(runtime, target):
    engine, adapter, _, _, _ = runtime
    engine.run(target, execute=True)
    engine.run(target, execute=True)
    assert adapter.submissions == 1


def test_failed_confirmation_retains_order_number_without_fallback(runtime, target, monkeypatch):
    engine, adapter, journal, _, _ = runtime
    def fail(*args):
        raise TimeoutError
    monkeypatch.setattr(adapter, "confirm", fail)
    assert engine.run(target, execute=True)["status"] == "submitted"
    assert journal.latest()["trade_no"]
    engine.run(target, execute=True)
    assert adapter.submissions == 1


def test_payment_link_failure_keeps_successful_reservation(runtime, target, monkeypatch):
    engine, adapter, _, _, _ = runtime
    monkeypatch.setattr(adapter, "payment_link", lambda *args: (_ for _ in ()).throw(TimeoutError()))
    result = engine.run(target, execute=True)
    assert result["status"] == "pending_payment"
    assert "cgyy.buaa.edu.cn" in result["payment_url"]
    assert adapter.submissions == 1


def test_disabled_configuration_refuses_execute(runtime, target):
    engine, adapter, _, _, _ = runtime
    engine.config = replace(engine.config, enabled=False)
    with pytest.raises(ValueError):
        engine.run(target, execute=True)
    assert adapter.submissions == 0


def test_unapproved_date_refuses_execute(runtime, target):
    engine, adapter, _, _, _ = runtime
    with pytest.raises(ValueError):
        engine.run(target + timedelta(days=1), execute=True)
    assert adapter.submissions == 0


def test_late_scheduled_start_does_not_login_or_submit(runtime, target, monkeypatch):
    engine, adapter, _, _, clock = runtime
    clock.sleep(61)
    monkeypatch.setattr(adapter, "preflight", lambda: pytest.fail("late job tried authentication"))
    assert engine.run(target, execute=True, scheduled=True)["status"] == "missed"
    assert adapter.submissions == 0


def test_waits_until_release_and_ocr_cannot_push_submission_outside_window(runtime, target, monkeypatch):
    engine, adapter, _, _, clock = runtime
    clock.current -= timedelta(minutes=5)
    original = adapter.prepare
    def slow_prepare(*args):
        clock.sleep(61)
        return original(*args)
    monkeypatch.setattr(adapter, "prepare", slow_prepare)
    assert engine.run(target, execute=True, scheduled=True)["status"] == "finished"
    assert adapter.submissions == 0


def test_rate_limits_have_global_submission_budget(runtime, target, monkeypatch):
    engine, adapter, _, _, clock = runtime
    calls = []
    def limit(*args):
        calls.append(clock.monotonic())
        return SubmitOutcome("rate_limited", message="slow down")
    monkeypatch.setattr(adapter, "submit", limit)
    result = engine.run(target, execute=True)
    assert result["status"] == "finished"
    assert len(calls) == 3
    assert calls[1] - calls[0] >= 2


def test_reminder_sent_once_then_payment_completion(runtime, target, monkeypatch):
    engine, adapter, _, messages, clock = runtime
    result = engine.run(target, execute=True)
    result["expire_time"] = (clock.now() + timedelta(seconds=50)).isoformat()
    before = clock.monotonic()
    original = adapter.confirm
    def confirm(*args):
        data = original(*args)
        if clock.monotonic() - before >= 15:
            data["status"] = "paid"
        return data
    monkeypatch.setattr(adapter, "confirm", confirm)
    assert engine.watch(result)["status"] == "paid"
    assert sum("一分钟" in r.get("message", "") for r in messages) == 1


def test_two_runners_cannot_hold_same_account_lock(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RuntimeError):
            with run_lock(tmp_path):
                pytest.fail("second runner acquired the lock")
    with run_lock(tmp_path):
        pass


def test_deadline_reminder_still_fires_when_order_queries_fail(runtime, target, monkeypatch):
    engine, adapter, _, messages, clock = runtime
    result = engine.run(target, execute=True)
    result["expire_time"] = (clock.now() + timedelta(seconds=15)).isoformat()
    def disconnected(*args):
        raise TimeoutError
    monkeypatch.setattr(adapter, "confirm", disconnected)
    assert engine.watch(result)["status"] == "deadline_passed"
    assert sum("一分钟" in r.get("message", "") for r in messages) == 1
    assert messages[-1]["status"] == "deadline_passed"


def test_temporary_query_limit_backs_off_before_first_submission(runtime, target, monkeypatch):
    engine, adapter, _, _, clock = runtime
    calls = []
    def query(*args):
        calls.append(clock.monotonic())
        if len(calls) == 1:
            raise RetryableQueryError("rate limit")
        return adapter.info
    monkeypatch.setattr(adapter, "query", query)
    assert engine.run(target, execute=True)["status"] == "pending_payment"
    assert adapter.submissions == 1
    assert calls[1] - calls[0] >= 2


@pytest.mark.parametrize('refusal', [
    {'code': 511, 'message': '请重新验证'},
    {'code': 250, 'message': '验证码已失效，请重新验证'},
    {'code': 250, 'message': '未到预约时间'},
    {'code': 250, 'data': {'repMsg': '场地已被预约'}},
])
def test_explicit_server_refusal_recovers_through_real_classifier(runtime, target, monkeypatch, refusal):
    from buaa_booking.adapter import classify_submission
    engine, adapter, journal, _, clock = runtime
    prepared = []
    original_prepare = adapter.prepare
    def prepare(candidate, info):
        prepared.append(candidate.key)
        return original_prepare(candidate, info)
    monkeypatch.setattr(adapter, 'prepare', prepare)
    def submit(payload):
        adapter.submissions += 1
        return classify_submission(refusal if adapter.submissions == 1 else
                                   {'code': 200, 'data': {'tradeNo': 'DEMO-ORDER-NOT-REAL'}})
    monkeypatch.setattr(adapter, 'submit', submit)
    assert engine.run(target, execute=True)['status'] == 'pending_payment'
    assert adapter.submissions == 2
    assert len(prepared) == 2
    if refusal.get('data'):
        assert prepared[0] != prepared[1]
    else:
        assert prepared[0] == prepared[1]
    evidence = journal.diagnostics()
    assert len([e for e in evidence if e['stage'] == 'submit_result']) == 2
    assert any(e.get('server_code') == str(refusal['code']) for e in evidence)


def test_repeated_captcha_refusal_stops_at_global_budget(runtime, target, monkeypatch):
    from buaa_booking.adapter import classify_submission
    engine, adapter, journal, _, _ = runtime
    def submit(payload):
        adapter.submissions += 1
        return classify_submission({'code': 511, 'message': '请重新验证'})
    monkeypatch.setattr(adapter, 'submit', submit)
    assert engine.run(target, execute=True)['status'] == 'finished'
    assert adapter.submissions == 3
    assert journal.latest()['attempts'] == 3


def test_generic_250_is_not_blindly_retried(runtime, target, monkeypatch):
    from buaa_booking.adapter import classify_submission
    engine, adapter, _, _, _ = runtime
    def submit(payload):
        adapter.submissions += 1
        return classify_submission({'code': 250, 'message': '业务处理失败'})
    monkeypatch.setattr(adapter, 'submit', submit)
    assert engine.run(target, execute=True)['status'] == 'rejected'
    assert engine.run(target, execute=True)['status'] == 'rejected'
    assert adapter.submissions == 1


def test_recovery_cannot_submit_after_window_and_trace_does_not_change_order_state(runtime, target, monkeypatch):
    from buaa_booking.adapter import classify_submission
    engine, adapter, journal, _, clock = runtime
    original_prepare = adapter.prepare
    calls = []
    def prepare(candidate, info):
        calls.append(1)
        if len(calls) == 2:
            clock.sleep(61)
        return original_prepare(candidate, info)
    monkeypatch.setattr(adapter, 'prepare', prepare)
    def submit(payload):
        adapter.submissions += 1
        return classify_submission({'code': 511, 'message': '请重新验证'})
    monkeypatch.setattr(adapter, 'submit', submit)
    assert engine.run(target, execute=True)['status'] == 'finished'
    assert adapter.submissions == 1
    latest = journal.latest()
    assert latest['attempts'] == 1
    journal.trace(latest['job_key'], 'check', payload='secret', headers='secret', token='secret')
    assert journal.latest() == latest
    assert 'secret' not in str(journal.diagnostics())


def test_captcha_preparation_failure_recovers_before_sending_any_order(runtime, target, monkeypatch):
    from src.core.exceptions import CaptchaError
    engine, adapter, journal, _, _ = runtime
    original = adapter.prepare
    calls = []
    def prepare(*args):
        calls.append(1)
        if len(calls) == 1:
            assert adapter.submissions == 0
            raise CaptchaError('本地拒识')
        return original(*args)
    monkeypatch.setattr(adapter, 'prepare', prepare)
    assert engine.run(target, execute=True)['status'] == 'pending_payment'
    assert len(calls) == 2
    assert adapter.submissions == 1
    assert any(e['stage'] == 'prepare_failed' and e['error_type'] == 'CaptchaError'
               for e in journal.diagnostics())


def test_persistent_captcha_preparation_failure_has_a_separate_bounded_budget(runtime, target, monkeypatch):
    from src.core.exceptions import CaptchaError
    engine, adapter, journal, _, _ = runtime
    calls = []
    def prepare(*args):
        calls.append(1)
        raise CaptchaError('本地拒识')
    monkeypatch.setattr(adapter, 'prepare', prepare)
    assert engine.run(target, execute=True)['status'] == 'finished'
    assert len(calls) == 3
    assert adapter.submissions == 0
    assert journal.latest()['attempts'] == 0


def test_captcha_server_limit_ends_run_without_outer_retry(runtime, target, monkeypatch):
    from src.core.exceptions import CaptchaLimitError
    engine, adapter, journal, _, _ = runtime
    calls = []
    def limited(*args):
        calls.append(1)
        raise CaptchaLimitError('学校验证码限流')
    monkeypatch.setattr(adapter, 'prepare', limited)
    assert engine.run(target, execute=True)['status'] == 'finished'
    assert len(calls) == 1
    assert adapter.submissions == 0
    assert journal.latest()['attempts'] == 0


def test_multiple_release_boundary_and_transient_query_retries_stay_fast(runtime, target, monkeypatch):
    from buaa_booking.adapter import ReleaseNotOpenError, TransientQueryError
    engine, adapter, _, _, clock = runtime
    original = adapter.query
    calls = []
    def query(value):
        calls.append(clock.monotonic())
        if len(calls) <= 3:
            raise ReleaseNotOpenError('学校尚未放场')
        if len(calls) == 4:
            raise TransientQueryError('连接抖动')
        return original(value)
    monkeypatch.setattr(adapter, 'query', query)
    assert engine.run(target, execute=True, scheduled=True)['status'] == 'pending_payment'
    assert calls[1] - calls[0] == pytest.approx(.1)
    assert calls[2] - calls[1] == pytest.approx(.1)
    assert calls[3] - calls[2] == pytest.approx(.1)
    assert calls[4] - calls[3] == pytest.approx(.2)
