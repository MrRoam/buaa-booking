"""Native availability board. This screen has no order submission action."""
from __future__ import annotations

import argparse
import json
import logging
import queue
import threading
import time
import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

from buaa_booking.availability import date_label, fetch_board, price_label
from buaa_booking.config import CHINA, load_config
from buaa_booking.journal import run_lock
from buaa_booking.notify import atomic_text
from buaa_booking.vault import Vault

BG = "#ffffff"
INK = "#182b2a"
MUTED = "#52635f"
ACCENT = "#086553"


class AvailabilityWindow:
    def __init__(self, root, config_path: Path, *, auto_refresh: bool = True):
        self.root = root
        self.config = load_config(config_path)
        self.directory = self.config.path.parent / "data"
        self.events = queue.Queue()
        self.snapshot = None
        self.busy = False
        self.last_attempt = -10.0
        self.duration = tk.IntVar(value=1)
        self.status = tk.StringVar(value="正在读取余场…")
        self.panels = []
        from buaa_booking.availability_layout import build
        build(self)
        self.cache_path = self.directory / "availability-cache.json"
        if self.cache_path.exists():
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if cached.get("schema_version") == 1 and cached.get("venue_site_id") == self.config.venue_site_id:
                    self.snapshot = cached
                    self.render()
                    self.status.set("显示上次查询结果，正在刷新…" if auto_refresh else self.status.get())
            except (ValueError, KeyError, TypeError):
                self.snapshot = None
        root.after(100, self.poll)
        if auto_refresh:
            root.after(150, self.refresh)

    def render(self):
        if not self.snapshot:
            return
        today = datetime.now(CHINA).date()
        two_hours = self.duration.get() == 2
        self.price_note.set("价格为每片场地连续两小时的总价。" if two_hours else "价格为每片场地每小时；余量以刷新结果为准。")
        from buaa_booking.availability_layout import render_rows
        for index, (panel, day) in enumerate(zip(self.panels, self.snapshot["days"])):
            heading, weekday, tree, empty = panel
            heading.configure(text=date_label(day["date"], today))
            actual = datetime.fromisoformat(day["date"])
            weekday.configure(text="周" + "一二三四五六日"[actual.weekday()])
            tree.heading("price", text="总价 / 片" if two_hours else "单价 / 小时")
            tree.delete(*tree.get_children())
            rows = day["two_hours"] if two_hours else day["one_hour"]
            for row in rows:
                tree.insert("", "end", values=(row["start"] + "–" + row["end"], str(row["remaining"]) + " 片", price_label(row)))
            render_rows(self, index, rows)
            if rows:
                empty.place_forget()
            else:
                text = {"error": "暂时无法查询", "not_open": "尚未开放预约"}.get(day["state"],
                       "暂无连续两小时空场" if two_hours else "暂无可预约时段")
                empty.configure(text=text)
                empty.place(relx=0.5, rely=0.35, anchor="center")
        query = datetime.fromisoformat(self.snapshot["queried_at"]).astimezone(CHINA)
        prefix = "部分日期查询失败 · " if any(d["state"] == "error" for d in self.snapshot["days"]) else ""
        self.status.set(prefix + "查询于 " + query.strftime("%m/%d %H:%M:%S"))

    def refresh(self):
        if self.busy or time.monotonic() - self.last_attempt < 5:
            return
        self.busy = True
        self.last_attempt = time.monotonic()
        self.refresh_button.configure(state="disabled")
        self.status.set("正在刷新…")
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            from buaa_booking.adapter import LiveAdapter
            with run_lock(self.directory):
                snapshot = fetch_board(LiveAdapter(self.config, Vault(self.directory)))
                if all(d["state"] == "error" for d in snapshot["days"]):
                    raise RuntimeError("All date queries failed")
                atomic_text(self.cache_path, json.dumps(snapshot, ensure_ascii=False, indent=2))
                self.events.put(("ok", snapshot))
        except Exception as exc:
            self.events.put(("error", type(exc).__name__))

    def poll(self):
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            event = self.events.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll)
            return
        self.busy = False
        remaining = max(0, int((5 - (time.monotonic() - self.last_attempt)) * 1000))
        self.root.after(remaining, lambda: self.refresh_button.configure(state="normal"))
        if event[0] == "ok":
            self.snapshot = event[1]
            self.render()
        else:
            suffix = "；仍显示上次结果" if self.snapshot else "；请先完成账号验证"
            self.status.set("刷新失败" + suffix)
        self.root.after(100, self.poll)

    def show_rules(self):
        from buaa_booking.ui_theme import BG, MUTED, button, frame, label
        import webbrowser
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("付款与退订规则")
        dialog.geometry("520x360")
        dialog.configure(fg_color=BG)
        body = frame(dialog)
        body.pack(fill="both", expand=True, padx=28, pady=24)
        label(body, "付款与退订", size=23, weight="bold").pack(anchor="w", pady=(0, 20))
        for title, detail in (("1 分钟内付款", "超时未付款，订单会自动取消。"),
                              ("至少提前 3 小时退订", "已付款订单可按官方规则取消并退款。"),
                              ("留意违约记录", "未按规则付费计违约；一周两次会暂停预约权限一个月。")):
            label(body, title, size=14, weight="bold").pack(anchor="w")
            label(body, detail, size=12, color=MUTED, wraplength=460, justify="left").pack(anchor="w", pady=(2, 14))
        button(body, "官方预约须知  ↗", lambda: webbrowser.open("https://cgyy.buaa.edu.cn/venue/home"), kind="quiet").pack(side="left")
        button(body, "知道了", dialog.destroy, kind="primary", width=90).pack(side="right")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args(argv)
    logging.getLogger().addHandler(logging.NullHandler())
    logging.getLogger().setLevel(logging.CRITICAL)
    root = ctk.CTk()
    AvailabilityWindow(root, args.config, auto_refresh=not args.smoke)
    if args.smoke:
        root.update()
        root.destroy()
        print("Availability UI OK; no network requests.")
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
