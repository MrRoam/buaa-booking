"""Single desktop entry point for booking setup, scheduling and manual booking."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import customtkinter as ctk
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

from buaa_booking.config import CHINA, load_config
from buaa_booking.journal import run_lock
from buaa_booking.task_setup import plan_lines, task_payload, validated_write

OFFICIAL = "https://cgyy.buaa.edu.cn/venue/home"
TASK_NAME = "BUAA-Badminton-Booking"


class BookingWindow:
    def __init__(self, root, config_path):
        self.root = root
        self.path = config_path.resolve()
        self.home = self.path.parent
        self.events = queue.Queue()
        self.busy = False
        self.mode = tk.StringVar(value="dates")
        self.dates = tk.StringVar()
        self.price = tk.StringVar()
        self.start = tk.StringVar(value="19:00")
        self.end = tk.StringVar(value="21:00")
        self.manual_date = tk.StringVar()
        self.weekdays = [tk.BooleanVar() for _ in range(7)]
        self.status = tk.StringVar(value="自动预约关闭；请先选日期和时段。")
        self.buttons = []
        from buaa_booking.launcher_layout import build
        build(self)
        self.load()
        self.render_ranges()
        self.show("还没有设置预约任务。\n\n先选择打球日期和时段，再点击“预览计划”。\n\n保存草稿不会下单。")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.poll)

    def load(self):
        base = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.mode.set("weekly" if base["weekdays"] else "dates")
        self.dates.set(", ".join(base["dates"]))
        self.price.set(base["max_total_price"])
        for index, variable in enumerate(self.weekdays):
            variable.set(index + 1 in base["weekdays"])
        for item in base["preferences"]:
            self.ranges.insert("", "end", values=(len(self.ranges.get_children()) + 1, item["start"], item["end"]))
        self.status.set("自动预约已开启；点击“刷新任务状态”核对 Windows 定时任务。" if base["enabled"] else "自动预约关闭；保存设置不会下单。")
        self.sync_mode()
        self.refresh_badge()

    def sync_mode(self):
        weekly = self.mode.get() == "weekly"
        self.date_switch.set("每周重复" if weekly else "指定日期")
        self.date_picker.body.pack_forget()
        self.week_row.pack_forget()
        if weekly:
            self.week_row.pack(before=self.date_hint, fill="x", pady=(3, 8))
        else:
            self.date_picker.body.pack(before=self.date_hint, fill="x")
        self.date_hint.configure(text="选择打球的星期。" if weekly else "可选多天；填写的是打球日期。")

    def add_range(self):
        from buaa_booking.config import minutes
        try:
            if minutes(self.end.get().strip()) - minutes(self.start.get().strip()) not in (60, 120):
                raise ValueError("每个时段需为连续 1 小时或 2 小时")
            values = (self.start.get().strip(), self.end.get().strip())
            if values in self.range_values():
                raise ValueError("该时段已添加")
            self.ranges.insert("", "end", values=(len(self.ranges.get_children()) + 1, *values))
            self.render_ranges()
        except ValueError as exc:
            messagebox.showerror("请检查时段", str(exc), parent=self.root)

    def remove_range(self):
        for item in self.ranges.selection():
            self.ranges.delete(item)
        for index, item in enumerate(self.ranges.get_children(), 1):
            self.ranges.set(item, "priority", index)
        self.render_ranges()

    def range_values(self):
        return [tuple(self.ranges.item(item, "values")[1:]) for item in self.ranges.get_children()]

    def change_date_mode(self, value):
        self.mode.set("weekly" if value == "每周重复" else "dates")
        self.sync_mode()

    def change_screen(self, value):
        scheduled = value == "定时抢场"
        self.schedule_dates.pack_forget()
        self.instant_dates.pack_forget()
        (self.schedule_dates if scheduled else self.instant_dates).pack(before=self.date_separator, fill="x")
        self.schedule_actions.pack_forget()
        self.instant_actions.pack_forget()
        (self.schedule_actions if scheduled else self.instant_actions).pack(fill="x")
        self.show("还没有设置预约任务。\n\n选择打球日期和时段，然后预览计划。" if scheduled else
                  "预约已放出的场地。\n\n先选择今天至后天的打球日期，再添加时段。\n\n“只查匹配场地”不会下单。")

    def refresh_badge(self):
        from buaa_booking.ui_theme import ACCENT, MUTED, SOFT, TINT
        enabled = load_config(self.path).enabled
        self.badge.configure(text="●  自动抢场已启用" if enabled else "●  自动抢场关闭",
                             text_color=ACCENT if enabled else MUTED, fg_color=TINT if enabled else SOFT)

    def render_ranges(self):
        from buaa_booking.ui_theme import ACCENT, INK, MUTED, SOFT, button, frame, label
        for child in self.preference_list.winfo_children():
            child.destroy()
        items = self.ranges.get_children()
        if not items:
            label(self.preference_list, "添加你想打球的时段", size=13, color=MUTED).pack(anchor="w", pady=18, padx=8)
        for index, item in enumerate(items):
            values = self.ranges.item(item, "values")
            row = frame(self.preference_list, color=SOFT, radius=7)
            row.pack(fill="x", pady=(0, 7))
            label(row, "首选" if index == 0 else f"备选 {index}", size=12, color=ACCENT if index == 0 else MUTED, width=56).pack(side="left", padx=(12, 8), pady=8)
            label(row, values[1] + "  –  " + values[2], size=17, weight="bold").pack(side="left")
            button(row, "×", lambda key=item: self.delete_range(key), kind="quiet", width=30, height=30).pack(side="right", padx=(0, 6))
            if index:
                button(row, "↑", lambda key=item: self.move_range(key), kind="quiet", width=28, height=30).pack(side="right")

    def delete_range(self, item):
        self.ranges.selection_set(item)
        self.remove_range()

    def move_range(self, item):
        index = self.ranges.index(item)
        self.ranges.move(item, "", max(0, index - 1))
        for index, key in enumerate(self.ranges.get_children(), 1):
            self.ranges.set(key, "priority", index)
        self.render_ranges()

    def payload(self, target=None):
        base = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return task_payload(base, mode="dates" if target else self.mode.get(),
                            dates_text=target.isoformat() if target else self.dates.get(),
                            weekdays=[i + 1 for i, value in enumerate(self.weekdays) if value.get()],
                            ranges=self.range_values(), max_price=self.price.get().strip())

    def show(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def preview(self):
        try:
            payload = self.payload()
            self.show("\n".join(plan_lines(payload)) + "\n\n时段顺序：" + " → ".join(f"{p['start']}–{p['end']}" for p in payload["preferences"]) + f"；任意场地；每单不超过 ¥{payload['max_total_price']}。")
        except ValueError as exc:
            messagebox.showerror("请补充预约规则", str(exc), parent=self.root)

    def save(self):
        try:
            with run_lock(self.home / "data"):
                validated_write(self.path, self.payload())
            self.status.set("设置已保存，自动预约关闭。要执行未来任务，请点击“启用定时抢场”。")
            self.preview()
            self.refresh_badge()
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("设置未保存", str(exc), parent=self.root)

    def command(self, arguments):
        env = os.environ.copy() | {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(arguments, cwd=self.home, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode:
            raise RuntimeError(output or "操作未完成，请检查本地日志")
        return output

    def python(self, *arguments):
        return [str(self.home / ".venv/Scripts/python.exe"), "-m", "buaa_booking", "--config", str(self.path), *arguments]

    def powershell(self, script, *arguments):
        return self.command(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.home / "scripts" / script), *arguments])

    def activate(self):
        try:
            payload = self.payload()
            now = datetime.now(CHINA)
            if not payload["weekdays"] and not any(datetime.combine(date.fromisoformat(value) - timedelta(days=2), datetime.min.time(), CHINA).replace(hour=7) > now for value in payload["dates"]):
                raise ValueError("这些日期均已放场，请用下方“立即预约”；定时任务用于未来的放场时间。")
        except ValueError as exc:
            messagebox.showerror("暂不能启用", str(exc), parent=self.root)
            return
        summary = "\n".join(plan_lines(payload, limit=4))
        summary += "\n时段：" + " → ".join(f"{p['start']}–{p['end']}" for p in payload["preferences"])
        if not messagebox.askyesno("启用定时抢场", summary + f"\n任意场地，每单上限 ¥{payload['max_total_price']}。\n\n到时将自动创建待支付订单，需要你在 1 分钟内付款。启用吗？", parent=self.root):
            return
        self.worker(lambda: self.enable_schedule(payload))

    def enable_schedule(self, payload):
        with run_lock(self.home / "data"):
            validated_write(self.path, payload)
        checked = self.command(self.python("check"))
        try:
            with run_lock(self.home / "data"):
                validated_write(self.path, payload | {"enabled": True})
            installed = self.powershell("Install-Task.ps1", "-Enable", "-Update")
        except Exception:
            validated_write(self.path, payload)
            raise
        return checked + "\n\n" + installed

    def pause(self):
        def operation():
            payload = json.loads(self.path.read_text(encoding="utf-8-sig")) | {"enabled": False}
            validated_write(self.path, payload)
            return self.powershell("Uninstall-Task.ps1") + "\n后续自动抢场已关闭。已开始的运行和已有订单请在官方页面核对。"
        self.worker(operation)

    def manual(self, execute):
        try:
            target = date.fromisoformat(self.manual_date.get().strip())
            today = datetime.now(CHINA).date()
            if not today <= target <= today + timedelta(days=2):
                raise ValueError("立即预约仅用于今天至后天的已开放日期；未来放场请设置定时任务")
            payload = self.payload(target)
        except ValueError as exc:
            messagebox.showerror("请检查打球日期和时段", str(exc), parent=self.root)
            return
        if execute:
            times = " → ".join(f"{p['start']}–{p['end']}" for p in payload["preferences"])
            if not messagebox.askyesno("立即创建预约订单", f"打球日期：{target}\n时段顺序：{times}\n学院路主馆，任意场地；上限 ¥{payload['max_total_price']}。\n\n将立即尝试预约，并需要你在 1 分钟内付款。继续吗？", parent=self.root):
                return
        def operation():
            # A one-off request uses the shared order ledger, without enabling the daily configuration.
            with tempfile.NamedTemporaryFile(dir=self.home, prefix=".manual-", suffix=".json", delete=False) as file:
                temporary = Path(file.name)
                file.write(json.dumps(payload | {"enabled": execute}).encode("utf-8"))
            try:
                arguments = self.python("run", "--date", target.isoformat())
                arguments[arguments.index("--config") + 1] = str(temporary)
                if execute:
                    arguments += ["--execute", "--watch"]
                return self.command(arguments)
            finally:
                temporary.unlink(missing_ok=True)
        self.worker(operation)

    def worker(self, operation):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        self.status.set("正在处理，请稍候。预约成功会通过已配置的渠道提醒。")
        def work():
            try:
                self.events.put((True, operation()))
            except Exception as exc:
                self.events.put((False, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            okay, text = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            enabled = load_config(self.path).enabled
            self.status.set(("操作完成。" if okay else "操作未完成；请查看下方原因。") + ("自动预约已开启。" if enabled else "自动预约关闭。"))
            self.show(text)
            self.refresh_badge()
        self.root.after(100, self.poll)

    def inspect_schedule(self):
        return self.powershell("Task-Status.ps1")

    def open_module(self, name):
        subprocess.Popen([str(self.home / ".venv/Scripts/pythonw.exe"), "-m", "buaa_booking." + name, "--config", str(self.path)], cwd=self.home, creationflags=subprocess.CREATE_NO_WINDOW)

    def notifications(self):
        self.open_module("notifications_ui")

    def order(self):
        page = self.home / "data/latest-order.html"
        if page.exists():
            os.startfile(str(page))
        else:
            self.worker(lambda: self.command(self.python("status")))

    def close(self):
        if self.busy:
            messagebox.showinfo("操作正在进行", "请等本次操作结束后关闭。定时任务启用后，关闭窗口不影响它运行。", parent=self.root)
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    root = ctk.CTk()
    BookingWindow(root, args.config)
    if args.smoke:
        root.update()
        root.destroy()
        print("Launcher UI OK; no login, schedule installation or order submission.")
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
