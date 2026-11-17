import pytest

from buaa_booking.notify import Notifier


def test_checkout_opens_before_channels_and_only_once_per_order(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr('webbrowser.open', lambda url: events.append('open'))
    notifier = Notifier(tmp_path, {'desktop': True}, open_payment=True)
    monkeypatch.setattr(notifier, 'send', lambda *args: events.append('send') or True)
    record = {'status': 'pending_payment', 'trade_no': 'DTEST',
              'payment_url': 'https://cashier.cc-pay.cn/example'}
    notifier(record)
    notifier(record)
    assert events == ['open', 'send', 'send']


@pytest.mark.parametrize('record,external', [
    ({'status': 'pending_payment', 'trade_no': 'DTEST'}, False),
    ({'status': 'pending_payment', 'trade_no': 'DTEST', 'demo': True}, True),
    ({'status': 'paid', 'trade_no': 'DTEST'}, True),
    ({'status': 'needs_review', 'trade_no': 'DTEST'}, True),
])
def test_no_checkout_for_preview_demo_or_unverified_order(tmp_path, monkeypatch, record, external):
    monkeypatch.setattr('webbrowser.open', lambda url: pytest.fail('must not open checkout'))
    Notifier(tmp_path, {}, open_payment=True)(record, external=external)


def test_browser_failure_still_sends_the_notification(tmp_path, monkeypatch):
    def fail(url):
        raise OSError('No browser')
    monkeypatch.setattr('webbrowser.open', fail)
    notifier = Notifier(tmp_path, {'desktop': True}, open_payment=True)
    sent = []
    monkeypatch.setattr(notifier, 'send', lambda *args: sent.append(True) or True)
    notifier({'status': 'pending_payment', 'trade_no': 'DTEST'})
    assert sent == [True]
