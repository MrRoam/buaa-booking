"""Local credential entry and read-only verification. No reservation or payment calls."""
from __future__ import annotations

import argparse
import json
import queue
import threading
import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from buaa_booking.config import CHINA, load_config
from buaa_booking.journal import run_lock
from buaa_booking.notify import atomic_text
from buaa_booking.vault import Vault


class LoginWindow:
    def __init__(self, root: tk.Tk, config_path: Path):
        self.root = root
        self.config = load_config(config_path)
        self.directory = config_path.resolve().parent / "data"
        self.vault = Vault(self.directory)
        self.events = queue.Queue()
        self.checked = False
        self.saved = self.vault.read()
        from buaa_booking.login_layout import build
        build(self)
        root.after(100, self.poll)

    def display(self, message):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", message)
        self.output.configure(state="disabled")

    def show_availability(self):
        from buaa_booking.availability_ui import AvailabilityWindow
        AvailabilityWindow(ctk.CTkToplevel(self.root), self.config.path)

    def start(self):
        credentials = dict(self.saved)
        credentials.update({key: variable.get().strip() if key != "password" else variable.get()
                            for key, variable in self.values.items()})
        if not credentials.get("username") or not credentials.get("password"):
            self.status.set("请填写学工号和密码。")
            return
        if (credentials.get("username") != self.saved.get("username")
                or credentials.get("password") != self.saved.get("password")):
            credentials.update(cookie="", cg_authorization="")
        self.login_button.configure(state="disabled")
        self.save_button.configure(state="disabled", fg_color="#F4F7F6")
        self.status.set("正在验证，请稍候。没有请求创建订单。")
        threading.Thread(target=self.verify, args=(credentials,), daemon=True).start()

    def verify(self, credentials):
        class MemoryVault:
            def read(self):
                return dict(credentials)
            def write(self, values):
                credentials.update(values)
        try:
            from buaa_booking.adapter import LiveAdapter
            with run_lock(self.directory):
                adapter = LiveAdapter(self.config, MemoryVault())
                adapter.authenticate()
                info = adapter.query(datetime.now(CHINA).date().isoformat())
                if not credentials.get("phone") and info.order_param_view:
                    credentials["phone"] = info.order_param_view.phone
                self.vault.write(credentials)
                self.events.put(("ok", credentials, info))
        except Exception as exc:
            atomic_text(self.directory / "preflight.json", json.dumps({"ready": False, "authenticated": False,
                "read_only": True, "error_type": type(exc).__name__, "venue_site_id": self.config.venue_site_id,
                "checked_at": datetime.now(CHINA).isoformat()}))
            self.events.put(("error", type(exc).__name__))

    def save_details(self):
        try:
            with run_lock(self.directory):
                self.saved = self.vault.read()
                self.saved["phone"] = self.values["phone"].get().strip()
                self.saved["buddy_ids"] = self.values["buddy_ids"].get().strip()
                self.vault.write(self.saved)
        except RuntimeError:
            self.status.set("另一个验证或预约进程正在运行，请稍后保存。")
            return
        self.receipt(self.info)

    def receipt(self, info):
        from buaa_booking.adapter import LiveAdapter
        adapter = LiveAdapter(self.config, self.vault)
        ready = True
        try:
            adapter.validate_buddies(info)
            note = "账号和预约资料检查通过。请回到启动窗口设置或查看抢场任务。"
        except ValueError as exc:
            ready = False
            note = "登录和查场通过；" + str(exc)
        atomic_text(self.directory / "preflight.json", json.dumps({"ready": ready, "authenticated": True,
            "read_only": True, "venue_site_id": self.config.venue_site_id,
            "available_dates": list(info.space_schedules_by_date),
            "buddy_count": len(info.order_param_view.buddy_list) if info.order_param_view else 0,
            "checked_at": datetime.now(CHINA).isoformat()}, ensure_ascii=False, indent=2))
        self.status.set(note)

    def poll(self):
        try:
            event = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll)
            return
        self.login_button.configure(state="normal")
        if event[0] == "error":
            self.status.set(f"验证未通过（{event[1]}）。请检查校园网络和账号；如官方要求额外验证，请先在官方页面完成。")
        else:
            _, self.saved, self.info = event
            self.values["phone"].set(self.saved.get("phone", ""))
            site = self.info.site_param
            lines = [f"登录通过：{site.campus_name} / {site.venue_name} / {site.site_name}",
                     "返回日期：" + "、".join(self.info.space_schedules_by_date),
                     f"同伴要求：{site.buddy_num_min} 至 {site.buddy_num_max} 人"]
            from buaa_booking.login_layout import populate_buddies
            populate_buddies(self, self.info)
            lines.append("本次未获取预约验证码，未发送订单请求。")
            self.display("\n".join(lines))
            self.save_button.configure(state="normal", fg_color="#146C54")
            self.receipt(self.info)
        self.root.after(100, self.poll)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--smoke", action="store_true", help="创建并关闭界面，不读取账号或登录")
    args = parser.parse_args()
    root = ctk.CTk()
    LoginWindow(root, args.config)
    if args.smoke:
        root.update()
        root.destroy()
        print("Local verification UI OK; no network requests.")
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
