"""Local notification settings. Opening or saving this window sends nothing."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from buaa_booking.config import load_config
from buaa_booking.journal import run_lock
from buaa_booking.ui_theme import BG, MUTED, SOFT, button, entry, frame, label, segment, window
from buaa_booking.vault import Vault


class NotificationWindow:
    def __init__(self, root, config_path):
        self.root = root
        self.config = load_config(config_path)
        self.directory = self.config.path.parent / "data"
        self.vault = Vault(self.directory)
        self.saved = self.vault.read()
        self.events = queue.Queue()
        self.values = {}
        self.busy = False
        window(root, "通知设置 · 北航羽毛球", "610x800", (570, 690))
        body = frame(root)
        body.pack(fill="both", expand=True, padx=30, pady=26)
        label(body, "通知设置", size=26, weight="bold").pack(anchor="w")
        label(body, "抢场成功后提醒你付款。", size=13, color=MUTED).pack(anchor="w", pady=(3, 22))
        desktop = frame(body, color=SOFT, radius=8)
        desktop.pack(fill="x", pady=(0, 22))
        label(desktop, "桌面提醒", size=14, weight="bold").pack(anchor="w", padx=16, pady=(12, 2))
        label(desktop, "使用当前 Windows 会话，无需额外账号。", size=12, color=MUTED).pack(anchor="w", padx=16, pady=(0, 12))
        self.switch = segment(body, ["Bark 手机提醒", "邮件提醒"], command=self.change)
        self.switch.set("Bark 手机提醒")
        self.switch.pack(anchor="w", pady=(0, 20))
        self.area = ctk.CTkScrollableFrame(body, fg_color=BG, corner_radius=0,
                                          scrollbar_button_color="#DFE7E3", scrollbar_button_hover_color=MUTED)
        self.bark = frame(self.area)
        self.email = frame(self.area)
        for parent, fields in ((self.bark, [("bark_key", "Bark Device Key", True)]),
                               (self.email, [("smtp_host", "SMTP 服务器", False),
                                             ("smtp_port", "SMTP 端口", False),
                                             ("smtp_username", "发件邮箱", False),
                                             ("smtp_password", "邮箱授权码", True),
                                             ("email_to", "收件邮箱", False)])):
            for key, title, secret in fields:
                label(parent, title, size=13).pack(anchor="w", pady=(0, 5))
                value = tk.StringVar(value=str(self.saved.get(key, "465" if key == "smtp_port" else "")))
                self.values[key] = value
                entry(parent, value, show="*" if secret else None).pack(fill="x", pady=(0, 10))
        label(self.bark, "在 iPhone 的 Bark App 中复制 Device Key。\n密钥会加密保存在本机。", size=13, color=MUTED, justify="left").pack(anchor="w", pady=10)
        self.bark.pack(fill="x")
        self.status = tk.StringVar(value="打开和保存此窗口不会发送消息。")
        actions = frame(body)
        actions.pack(side="bottom", fill="x")
        label(body, textvariable=self.status, size=12, color=MUTED, wraplength=530, justify="left").pack(side="bottom", anchor="w", pady=(8, 12))
        self.area.pack(fill="both", expand=True)
        self.save_button = button(actions, "保存设置", self.save, kind="primary", width=170)
        self.save_button.pack(side="left")
        self.test_button = button(actions, "测试已保存的提醒", self.test, width=180)
        self.test_button.pack(side="right")
        root.after(100, self.poll)

    def change(self, value):
        self.bark.pack_forget()
        self.email.pack_forget()
        (self.email if value == "邮件提醒" else self.bark).pack(fill="x")

    def save(self):
        try:
            port = int(self.values["smtp_port"].get().strip() or "465")
            if not 1 <= port <= 65535:
                raise ValueError("SMTP 端口需为 1 至 65535")
            with run_lock(self.directory):
                values = self.vault.read()
                values.update({key: value.get().strip() for key, value in self.values.items()})
                values["smtp_port"] = port
                self.vault.write(values)
            self.status.set("通知资料已加密保存，未发送消息。可点击右侧按钮测试。")
        except (ValueError, RuntimeError) as exc:
            self.status.set(str(exc))

    def test(self):
        if self.busy:
            return
        self.busy = True
        self.test_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status.set("正在测试已保存的提醒…")
        def operation():
            try:
                from buaa_booking.notify import Notifier
                # A test must never overwrite the actual booking payment page.
                test_dir = self.directory / "notification-test"
                with run_lock(self.directory):
                    Notifier(test_dir, self.config.notifications, self.vault.read())(
                        {"status": "test", "message": "北航预约提醒测试，没有创建订单。"})
                statuses = json.loads((test_dir / "notification-status.json").read_text(encoding="utf-8"))
                names = {"desktop": "桌面", "bark": "Bark", "email": "邮件"}
                results = {"sent": "已发送", "disabled": "已关闭", "not_configured_or_unavailable": "未配置或暂不可用"}
                self.events.put("\n".join(names[key] + "：" + results.get(value, "发送失败，请检查配置和网络") for key, value in statuses.items()))
            except Exception:
                self.events.put("测试未完成，请稍后重试或检查网络。")
        threading.Thread(target=operation, daemon=True).start()

    def poll(self):
        try:
            text = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.status.set(text)
            self.test_button.configure(state="normal")
            self.save_button.configure(state="normal")
        self.root.after(100, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    root = ctk.CTk()
    NotificationWindow(root, args.config)
    if args.smoke:
        root.update()
        root.destroy()
        print("Notification UI OK; no notifications sent.")
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
