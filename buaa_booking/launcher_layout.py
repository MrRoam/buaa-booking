"""Layout for the task editor; booking actions live in launcher_ui."""
import os
import tkinter as tk
import webbrowser
from tkinter import ttk

import customtkinter as ctk

from buaa_booking.ui_theme import (
    ACCENT, BG, FONT, INK, LINE, MUTED, SIDEBAR, SOFT, TINT,
    DatePicker, button, entry, frame, label, segment, window,
)


def build(view):
    root = view.root
    window(root, "北航羽毛球 · 预约助手", "1160x800", (1080, 680))
    root.columnconfigure(1, weight=1)
    root.rowconfigure(0, weight=1)
    sidebar = frame(root, color=SIDEBAR, width=174)
    sidebar.grid(row=0, column=0, sticky="ns")
    sidebar.pack_propagate(False)
    label(sidebar, "北航羽毛球", size=20, weight="bold").pack(anchor="w", padx=22, pady=(30, 0))
    label(sidebar, "学院路 · 体育馆主馆", size=12, color=MUTED).pack(anchor="w", padx=22, pady=(3, 30))
    view.nav_buttons = []
    for text, command, active in (
        ("预约任务", lambda: None, True),
        ("查看余场", lambda: view.open_module("availability_ui"), False),
        ("账号与同伴", lambda: view.open_module("login_ui"), False),
        ("通知设置", view.notifications, False),
    ):
        control = button(sidebar, text, command, width=138, height=42, anchor="w")
        control.pack(fill="x", padx=14, pady=4)
        if active:
            control.configure(fg_color=TINT, text_color=ACCENT)
        view.nav_buttons.append(control)
    foot = frame(sidebar, width=140)
    foot.pack(side="bottom", fill="x", padx=14, pady=22)
    button(foot, "官方预约与订单  ↗", lambda: webbrowser.open("https://cgyy.buaa.edu.cn/venue/home"), kind="quiet", width=145, anchor="w").pack(fill="x", pady=3)
    button(foot, "使用说明  ↗", lambda: os.startfile(str(view.home / "开始使用.html")), kind="quiet", width=145, anchor="w").pack(fill="x", pady=3)
    frame(foot, color=LINE, height=1).pack(fill="x", pady=16)
    label(foot, "本机运行 · 手动付款", size=11, color=MUTED).pack(anchor="w", padx=9)

    body = frame(root)
    body.grid(row=0, column=1, sticky="nsew", padx=30, pady=(26, 24))
    head = frame(body)
    head.pack(fill="x")
    label(head, "预约任务", size=27, weight="bold").pack(side="left")
    view.badge = label(head, "●  自动抢场关闭", size=12, color=MUTED, fg_color=SOFT, corner_radius=7, width=150, height=31, anchor="center")
    view.badge.pack(side="right")
    label(body, "选择打球日期和时段，程序计算对应的抢场时间。", color=MUTED, size=13).pack(anchor="w", pady=(3, 16))
    view.screen_switch = segment(body, ["定时抢场", "立即预约"], command=view.change_screen)
    view.screen_switch.set("定时抢场")
    view.screen_switch.pack(anchor="w", pady=(0, 24))
    content = frame(body)
    content.pack(fill="both", expand=True)
    content.columnconfigure(0, weight=1)
    content.columnconfigure(1, minsize=280)
    content.rowconfigure(0, weight=1)
    editor_host = frame(content)
    editor_host.grid(row=0, column=0, sticky="nsew", padx=(0, 28))
    editor = ctk.CTkScrollableFrame(editor_host, fg_color=BG, corner_radius=0,
                                   scrollbar_button_color=LINE, scrollbar_button_hover_color=MUTED)
    view.schedule_dates = frame(editor)
    view.schedule_dates.pack(fill="x")
    label(view.schedule_dates, "打球日期", size=16, weight="bold").pack(anchor="w", pady=(0, 10))
    view.date_switch = segment(view.schedule_dates, ["指定日期", "每周重复"], command=view.change_date_mode)
    view.date_switch.pack(anchor="w", pady=(0, 12))
    view.date_picker = DatePicker(view.schedule_dates, view.dates, multiple=True, width=258)
    view.date_picker.body.pack(fill="x")
    view.dates_entry = view.date_picker.input
    view.week_row = frame(view.schedule_dates)
    view.day_checks = []
    for index, title in enumerate("一二三四五六日"):
        control = ctk.CTkCheckBox(view.week_row, text=title, variable=view.weekdays[index], width=48,
                                 checkbox_width=19, checkbox_height=19, corner_radius=5,
                                 fg_color=ACCENT, hover_color="#0D5743", text_color=INK, font=(FONT, 13))
        control.pack(side="left", padx=(0, 5))
        view.day_checks.append(control)
    view.date_hint = label(view.schedule_dates, "可选多天；填写的是打球日期。", size=12, color=MUTED)
    view.date_hint.pack(anchor="w", pady=(6, 0))

    view.instant_dates = frame(editor)
    label(view.instant_dates, "打球日期", size=16, weight="bold").pack(anchor="w", pady=(0, 10))
    manual_picker = DatePicker(view.instant_dates, view.manual_date, width=258)
    manual_picker.body.pack(fill="x")
    label(view.instant_dates, "只预约今天至后天已放出的场地。", size=12, color=MUTED).pack(anchor="w", pady=(6, 0))
    # Reserve the same date region when switching modes so the time controls stay put.
    separator = frame(editor, color=LINE, height=1)
    separator.pack(fill="x", pady=21)
    view.date_separator = separator
    label(editor, "打球时段", size=16, weight="bold").pack(anchor="w")
    label(editor, "按顺序尝试首选与备选，只预约一个方案。", size=12, color=MUTED).pack(anchor="w", pady=(2, 12))
    times = frame(editor)
    times.pack(fill="x")
    hours = [f"{hour:02}:00" for hour in range(7, 23)]
    for variable in (view.start, view.end):
        ctk.CTkComboBox(times, variable=variable, values=hours, width=106, height=39,
                        fg_color=SOFT, border_color=LINE, border_width=1, corner_radius=7,
                        button_color=SOFT, button_hover_color=TINT, dropdown_fg_color=BG,
                        dropdown_text_color=INK, text_color=INK, font=(FONT, 14)).pack(side="left", padx=(0, 10))
    button(times, "＋ 添加", view.add_range, width=85).pack(side="right")
    view.ranges = ttk.Treeview(editor, columns=("priority", "start", "end"), show="headings")
    view.preference_list = frame(editor)
    view.preference_list.pack(fill="x", pady=(12, 0))
    price_row = frame(editor)
    price_row.pack(fill="x", pady=(16, 0))
    label(price_row, "订单总价上限", size=14).pack(side="left")
    entry(price_row, view.price, width=115).pack(side="right")
    label(price_row, "¥", size=16).pack(side="right", padx=8)
    label(editor, "任意场地 · 连续 2 小时保持同一场地", size=12, color=MUTED).pack(anchor="w", pady=(9, 0))
    action_area = frame(editor_host)
    action_area.pack(side="bottom", fill="x", pady=(20, 0))
    editor.pack(fill="both", expand=True)
    view.schedule_actions = frame(action_area)
    view.schedule_actions.pack(fill="x")
    for text, command, kind in (("保存草稿", view.save, "secondary"), ("预览计划", view.preview, "secondary")):
        control = button(view.schedule_actions, text, command, width=98, kind=kind)
        control.pack(side="left", padx=(0, 9))
        view.buttons.append(control)
    control = button(view.schedule_actions, "启用定时抢场", view.activate, kind="primary", width=142)
    control.pack(side="right")
    view.buttons.append(control)
    view.instant_actions = frame(action_area)
    for text, execute, kind in (("只查匹配场地", False, "secondary"), ("立即预约", True, "primary")):
        control = button(view.instant_actions, text, lambda value=execute: view.manual(value), kind=kind, width=150)
        control.pack(side="left" if not execute else "right")
        view.buttons.append(control)

    plan = frame(content, color=SOFT, radius=12, width=280)
    plan.grid(row=0, column=1, sticky="nsew")
    plan.grid_propagate(False)
    label(plan, "执行计划", size=16, weight="bold").pack(anchor="w", padx=20, pady=(20, 8))
    view.output = ctk.CTkTextbox(plan, fg_color=SOFT, text_color=INK, wrap="word", height=210,
                               font=(FONT, 13), corner_radius=0, border_width=0,
                               scrollbar_button_color=LINE, scrollbar_button_hover_color=MUTED)
    note = frame(plan)
    note.pack(side="bottom", fill="x", padx=20, pady=(0, 20))
    frame(note, color=LINE, height=1).pack(fill="x", pady=(0, 15))
    label(note, "07:00 放场", size=15, weight="bold").pack(anchor="w")
    label(note, "提前两天 · 06:55 自动启动", size=12, color=MUTED).pack(anchor="w", pady=(2, 12))
    label(note, "下单后 1 分钟内手动付款", size=12, color=ACCENT).pack(anchor="w")
    button(note, "订单与付款入口  ↗", view.order, width=225).pack(fill="x", pady=(10, 0))
    view.output.pack(fill="both", expand=True, padx=14, pady=(0, 8))
    footer = frame(body)
    footer.pack(before=content, side="bottom", fill="x", pady=(16, 0))
    label(footer, textvariable=view.status, size=12, color=MUTED, wraplength=610, justify="left").pack(side="left", fill="x", expand=True)
    for title, callback in (("刷新状态", lambda: view.worker(view.inspect_schedule)), ("暂停抢场", view.pause)):
        control = button(footer, title, callback, kind="quiet", width=78, height=32)
        control.pack(side="right", padx=(6, 0))
        view.buttons.append(control)
