"""Exercise real form controls with order and scheduler transports replaced."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from buaa_booking.config import CHINA
from buaa_booking.task_setup import validated_write

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows desktop UI")


@pytest.fixture(scope="module")
def desktop_root():
    import customtkinter as ctk
    root = ctk.CTk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def window(tmp_path, desktop_root):
    import customtkinter as ctk
    from buaa_booking.launcher_ui import BookingWindow
    path = tmp_path / "config.json"
    base = json.loads((Path(__file__).parents[1] / "config.example.json").read_text())
    validated_write(path, base)
    root = ctk.CTkToplevel(desktop_root)
    root.withdraw()
    view = BookingWindow(root, path)
    view.dates.set((datetime.now(CHINA).date() + timedelta(days=3)).isoformat())
    view.add_range()
    yield view
    root.destroy()


def test_preview_uses_form_without_saving(window):
    before = window.path.read_bytes()
    window.preview()
    assert "07:00" in window.output.get("1.0", "end")
    assert window.path.read_bytes() == before


def test_save_from_enabled_config_always_disables_it(window):
    validated_write(window.path, window.payload() | {"enabled": True})
    window.save()
    saved = json.loads(window.path.read_text())
    assert saved["enabled"] is False
    assert saved["dates"] == [window.dates.get()]


def test_failed_account_check_never_installs_scheduler(window, monkeypatch):
    def fail(*args):
        raise RuntimeError("account check failed")
    monkeypatch.setattr(window, "command", fail)
    monkeypatch.setattr(window, "powershell", lambda *args: pytest.fail("must not install"))
    with pytest.raises(RuntimeError, match="account check failed"):
        window.enable_schedule(window.payload())
    assert json.loads(window.path.read_text())["enabled"] is False


def test_failed_task_install_rolls_back_enabled_config(window, monkeypatch):
    monkeypatch.setattr(window, "command", lambda *args: "account ready")
    def fail(*args):
        assert json.loads(window.path.read_text())["enabled"] is True
        raise RuntimeError("task install failed")
    monkeypatch.setattr(window, "powershell", fail)
    with pytest.raises(RuntimeError, match="task install failed"):
        window.enable_schedule(window.payload())
    assert json.loads(window.path.read_text())["enabled"] is False


@pytest.mark.parametrize("execute", [False, True])
def test_manual_booking_has_isolated_rules_and_shared_ledger(window, monkeypatch, execute):
    from buaa_booking import launcher_ui
    before = window.path.read_bytes()
    target = datetime.now(CHINA).date() + timedelta(days=1)
    window.manual_date.set(target.isoformat())
    monkeypatch.setattr(launcher_ui.messagebox, "askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr(window, "worker", lambda operation: operation())
    def inspect(arguments):
        manual_path = Path(arguments[arguments.index("--config") + 1])
        assert manual_path.parent == window.path.parent
        rules = json.loads(manual_path.read_text())
        assert rules["enabled"] is execute
        assert rules["dates"] == [target.isoformat()]
        assert rules["weekdays"] == []
        assert ("--execute" in arguments) is execute
        assert ("--watch" in arguments) is execute
        assert window.path.read_bytes() == before
        return "transport mocked; no order"
    monkeypatch.setattr(window, "command", inspect)
    window.manual(execute)
    assert window.path.read_bytes() == before
    assert not list(window.home.glob(".manual-*"))


def test_reorder_and_delete_preferences_changes_actual_booking_priority(window):
    window.start.set("20:00")
    window.end.set("22:00")
    window.add_range()
    second = window.ranges.get_children()[1]
    window.move_range(second)
    assert window.range_values() == [("20:00", "22:00"), ("19:00", "21:00")]
    window.delete_range(second)
    assert window.range_values() == [("19:00", "21:00")]


def test_switching_screens_keeps_unsaved_rule_and_never_saves(window):
    before = window.path.read_bytes()
    original = window.range_values()
    window.change_screen("立即预约")
    window.change_date_mode("每周重复")
    window.change_screen("定时抢场")
    assert window.range_values() == original
    assert window.mode.get() == "weekly"
    assert window.path.read_bytes() == before


def test_calendar_toggles_dates_without_saving_a_task(window):
    before = window.path.read_bytes()
    target = datetime.now(CHINA).date() + timedelta(days=4)
    window.dates.set("")
    window.date_picker.open()
    window.date_picker.select(target)
    assert window.dates.get() == target.isoformat()
    window.date_picker.select(target)
    assert window.dates.get() == ""
    window.date_picker.dialog.destroy()
    assert window.path.read_bytes() == before


def test_named_companion_selection_stores_internal_id(window):
    from types import SimpleNamespace
    from buaa_booking.login_layout import populate_buddies, update_selection
    import customtkinter as ctk
    import tkinter as tk
    container = ctk.CTkFrame(window.root)
    fake = SimpleNamespace(buddy_area=container, values={"buddy_ids": tk.StringVar(master=window.root, value="17")})
    info = SimpleNamespace(order_param_view=SimpleNamespace(buddy_list=[
        SimpleNamespace(id=17, name="测试同伴甲"), SimpleNamespace(id=29, name="测试同伴乙")]))
    populate_buddies(fake, info)
    assert fake.buddy_checks[0][1].get() is True
    fake.buddy_checks[0][1].set(False)
    fake.buddy_checks[1][1].set(True)
    update_selection(fake)
    assert fake.values["buddy_ids"].get() == "29"
    container.destroy()


def test_notification_settings_preserve_account_and_send_nothing(window, monkeypatch):
    import customtkinter as ctk
    from buaa_booking.notifications_ui import NotificationWindow
    root = ctk.CTkToplevel(window.root)
    root.withdraw()
    form = NotificationWindow(root, window.path)
    values = {"username": "test-account", "password": "test-password", "buddy_ids": "17"}
    monkeypatch.setattr(form.vault, "read", lambda: dict(values))
    monkeypatch.setattr(form.vault, "write", lambda new: values.update(new))
    form.values["bark_key"].set("test-device-key")
    form.values["smtp_port"].set("465")
    form.save()
    assert values["username"] == "test-account" and values["buddy_ids"] == "17"
    assert values["bark_key"] == "test-device-key"
    assert not (window.home / "data/notification-test").exists()
    root.destroy()
