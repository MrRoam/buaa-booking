import json
import os
from datetime import date, datetime
from unittest.mock import Mock

import pytest

from buaa_booking.config import CHINA, load_config
from buaa_booking.notify import Notifier, desktop_notification, safe_payment_url, write_order_page
from buaa_booking.vault import Vault


def test_release_date_uses_playing_weekday_not_execution_weekday(config):
    assert config.release_at(date(2026, 10, 18)).isoformat() == "2026-10-16T07:00:00+08:00"
    assert config.today_target(datetime(2026, 10, 16, 6, 55, tzinfo=CHINA)) == date(2026, 10, 18)


@pytest.mark.parametrize("key,value", [("enabled", "false"), ("same_court", "true"),
                                       ("poll_seconds", 0.01), ("max_submissions", 100),
                                       ("max_total_price", "NaN"), ("weekdays", [0]), ("venue_site_id", 57)])
def test_invalid_config_never_enables_reservations(config_file, key, value):
    raw = json.loads(config_file.read_text())
    raw[key] = value
    config_file.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(config_file)


def test_empty_dates_allowed_only_for_disabled_profile(config_file):
    raw = json.loads(config_file.read_text())
    raw.update(dates=[], weekdays=[], preferences=[], enabled=False)
    config_file.write_text(json.dumps(raw))
    assert not load_config(config_file).enabled
    raw["enabled"] = True
    config_file.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load_config(config_file)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://buaa.edu.cn.evil.test/pay", "//evil.test",
                                 "https://user:password@cgyy.buaa.edu.cn/", "https://evil.test/",
                                 "https://cgyy.buaa.edu.cn:1234/"])
def test_order_page_accepts_only_official_https_payment_origins(url):
    assert safe_payment_url(url) == "https://cgyy.buaa.edu.cn/venue/home"


def test_html_escapes_server_text_and_marks_demo(tmp_path):
    write_order_page(tmp_path, {"status": "unknown", "message": '<script>alert("x")</script>',
                              "payment_url": "javascript:alert(1)", "demo": True})
    page = (tmp_path / "latest-order.html").read_text(encoding="utf-8")
    assert '<script>alert("x")</script>' not in page
    assert "&lt;script&gt;" in page
    assert 'href="javascript:' not in page
    assert "离线演示，不是真实订单" in page


def test_notification_failure_cannot_erase_success_or_trigger_reservation(tmp_path, monkeypatch):
    notifier = Notifier(tmp_path, {"desktop": True, "bark": True, "email": True})
    calls = []
    def send(channel, *args):
        calls.append(channel)
        if channel == "bark":
            raise TimeoutError("must not write this secret to disk")
        return True
    monkeypatch.setattr(notifier, "send", send)
    notifier({"status": "pending_payment", "trade_no": "D123"})
    result = json.loads((tmp_path / "notification-status.json").read_text())
    assert calls == ["desktop", "bark", "email"]
    assert result == {"desktop": "sent", "bark": "failed:TimeoutError", "email": "sent"}
    assert json.loads((tmp_path / "latest-result.json").read_text())["trade_no"] == "D123"
    assert "secret" not in (tmp_path / "notification-status.json").read_text()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_windows_vault_roundtrip_and_no_plaintext_password(tmp_path):
    vault = Vault(tmp_path)
    secrets = {"username": "OFFLINE-TEST", "password": "fake-test-password-not-a-real-account",
               "cookie": "offline-test-cookie"}
    vault.write(secrets)
    assert vault.read() == secrets
    assert secrets["password"].encode() not in vault.path.read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="Windows Toast")
def test_toast_treats_content_as_data_not_shell_code(monkeypatch):
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("buaa_booking.notify.subprocess.run", run)
    payload = "' ; Write-Output 'injected' ; #"
    assert desktop_notification(payload, payload)
    assert payload not in " ".join(run.call_args.args[0])
    assert run.call_args.kwargs["env"]["BUAA_TOAST_TITLE"] == payload


def test_actual_bark_transport_shape_without_network(tmp_path, monkeypatch):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value.json.return_value = {"code": 200}
    monkeypatch.setattr("requests.Session", lambda: session)
    notifier = Notifier(tmp_path, {"bark": True}, {"bark_key": "fake-device-key"})
    assert notifier.send("bark", "标题", "内容", "")
    assert session.post.call_args.args[0] == "https://api.day.app/push"
    assert session.post.call_args.kwargs["json"]["device_key"] == "fake-device-key"


def test_actual_email_transport_shape_without_sending(tmp_path, monkeypatch):
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("buaa_booking.notify.smtplib.SMTP_SSL", lambda *a, **k: connection)
    notifier = Notifier(tmp_path, {"email": True}, {"smtp_host": "example.test", "smtp_username": "from@example.test",
        "smtp_password": "fake-app-password", "email_to": "to@example.test"})
    assert notifier.send("email", "标题", "内容", "")
    assert connection.login.call_args.args == ("from@example.test", "fake-app-password")
    assert connection.send_message.call_args.args[0]["To"] == "to@example.test"
