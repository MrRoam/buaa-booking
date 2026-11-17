"""Availability presentation grouped by day, with quantity and total price."""
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from buaa_booking.availability import price_label
from buaa_booking.ui_theme import ACCENT, BG, INK, LINE, MUTED, SOFT, TINT, button, frame, label, segment, window


def build(view):
    root = view.root
    window(root, "主馆余场 · 北航羽毛球", "1120x690", (1020, 580))
    body = frame(root)
    body.pack(fill="both", expand=True, padx=30, pady=26)
    header = frame(body)
    header.pack(fill="x")
    label(header, "主馆余场", size=27, weight="bold").pack(side="left")
    view.refresh_button = button(header, "刷新余场", view.refresh, kind="primary", width=118)
    view.refresh_button.pack(side="right")
    label(body, "学院路 · 体育馆主馆 · 羽毛球", size=13, color=MUTED).pack(anchor="w", pady=(3, 24))
    controls = frame(body)
    controls.pack(fill="x", pady=(0, 24))
    duration = segment(controls, ["1 小时", "连续 2 小时"], command=lambda value: change_duration(view, value))
    duration.set("1 小时")
    duration.pack(side="left")
    label(controls, textvariable=view.status, size=12, color=MUTED).pack(side="right")
    bottom = frame(body)
    bottom.pack(side="bottom", fill="x", pady=(18, 0))
    view.price_note = tk.StringVar(value="显示每片场地的价格；余量以刷新结果为准。")
    label(bottom, textvariable=view.price_note, size=12, color=MUTED).pack(side="left")
    button(bottom, "付款与退订规则", view.show_rules, kind="quiet", width=132).pack(side="right")
    calendar = frame(body)
    calendar.pack(fill="both", expand=True)
    calendar.rowconfigure(0, weight=1)
    view.row_frames = []
    for index in range(3):
        calendar.columnconfigure(index, weight=1, uniform="day")
        day = frame(calendar)
        day.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 15, 15 if index < 2 else 0))
        heading = label(day, "—", size=21, weight="bold")
        heading.pack(anchor="w")
        weekday = label(day, "", color=MUTED, size=12)
        weekday.pack(anchor="w", pady=(2, 18))
        columns = frame(day, color=SOFT, radius=7)
        columns.pack(fill="x", pady=(0, 4))
        label(columns, "时段", color=MUTED, size=12).pack(side="left", padx=12, pady=7)
        label(columns, "价格 / 片", color=MUTED, size=12, width=77, anchor="e").pack(side="right", padx=(0, 12))
        label(columns, "剩余", color=MUTED, size=12, width=58, anchor="center").pack(side="right")
        area = frame(day)
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(area, columns=("time", "count", "price"), show="headings")
        # The existing data model remains available to read-only UI verification.
        for key in ("time", "count", "price"):
            tree.heading(key, text=key)
        rows = ctk.CTkScrollableFrame(area, fg_color=BG, corner_radius=0,
                                     scrollbar_button_color=LINE, scrollbar_button_hover_color=MUTED)
        rows.pack(fill="both", expand=True)
        view.row_frames.append(rows)
        empty = label(area, "等待查询", size=13, color=MUTED, anchor="center")
        empty.place(relx=0.5, rely=0.35, anchor="center")
        view.panels.append((heading, weekday, tree, empty))


def change_duration(view, value):
    view.duration.set(2 if value == "连续 2 小时" else 1)
    view.render()


def render_rows(view, index, rows):
    target = view.row_frames[index]
    for child in target.winfo_children():
        child.destroy()
    for row in rows:
        line = frame(target)
        line.pack(fill="x")
        label(line, row["start"] + "–" + row["end"], size=14, weight="bold").pack(side="left", padx=(6, 0), pady=17)
        label(line, price_label(row), size=14, width=68, anchor="e").pack(side="right", padx=(0, 4))
        label(line, str(row["remaining"]) + " 片", size=13, color=ACCENT, fg_color=TINT,
              corner_radius=6, width=48, height=28, anchor="center").pack(side="right", padx=(8, 8))
        frame(target, color=LINE, height=1).pack(fill="x", padx=6)
