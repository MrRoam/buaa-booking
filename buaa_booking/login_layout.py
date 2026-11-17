"""Account form with companion selection by name."""
import tkinter as tk
import webbrowser

import customtkinter as ctk

from buaa_booking.ui_theme import ACCENT, BG, FONT, INK, LINE, MUTED, SOFT, TINT, button, entry, frame, label, window


def build(view):
    root = view.root
    window(root, "账号与同伴 · 北航羽毛球", "650x790", (610, 700))
    shell = frame(root)
    shell.pack(fill="both", expand=True, padx=30, pady=26)
    body = ctk.CTkScrollableFrame(shell, fg_color=BG, corner_radius=0,
                                  scrollbar_button_color=LINE, scrollbar_button_hover_color=MUTED)
    label(body, "账号与同伴", size=26, weight="bold").pack(anchor="w")
    label(body, "验证登录和预约资料，不创建订单。", size=13, color=MUTED).pack(anchor="w", pady=(3, 20))
    view.values = {}
    for key, title, masked in (("username", "北航学工号", False), ("password", "统一认证密码", True), ("phone", "预约手机号", False)):
        label(body, title, size=13).pack(anchor="w", pady=(0, 6))
        variable = tk.StringVar(value=view.saved.get(key, ""))
        view.values[key] = variable
        entry(body, variable, show="*" if masked else None).pack(fill="x", pady=(0, 14))
    view.values["buddy_ids"] = tk.StringVar(value=view.saved.get("buddy_ids", ""))
    view.login_button = button(body, "验证账号并读取同伴", view.start, kind="primary", height=40)
    view.login_button.pack(fill="x", pady=(0, 18))
    row = frame(body)
    row.pack(fill="x")
    label(row, "预约同伴", size=16, weight="bold").pack(side="left")
    button(row, "官方添加同伴  ↗", lambda: webbrowser.open("https://cgyy.buaa.edu.cn/venue/mobileBuddies"), kind="quiet", width=140, height=30).pack(side="right")
    label(body, "选择实际同行的人。主馆至少 1 名；查余场可跳过。", size=12, color=MUTED).pack(anchor="w", pady=(2, 10))
    view.buddy_area = frame(body, color=SOFT, radius=8)
    view.buddy_area.pack(fill="x")
    label(view.buddy_area, "验证账号后显示同伴列表。", size=13, color=MUTED).pack(anchor="w", padx=8, pady=12)
    footer = frame(shell)
    footer.pack(side="bottom", fill="x", pady=(12, 0))
    view.save_button = button(footer, "保存预约资料", view.save_details, kind="primary", width=170)
    view.save_button.configure(state="disabled", fg_color=SOFT)
    view.save_button.pack(side="left")
    button(footer, "查看余场", view.show_availability, width=120).pack(side="right")
    view.status = tk.StringVar(value="资料由当前 Windows 账户加密保存。")
    label(shell, textvariable=view.status, size=12, color=MUTED, wraplength=550, justify="left").pack(side="bottom", anchor="w", pady=(12, 6))
    view.output = ctk.CTkTextbox(shell, height=60, wrap="word", fg_color=BG, text_color=MUTED,
                               font=(FONT, 12), corner_radius=0)
    view.output.pack(side="bottom", fill="x")
    body.pack(fill="both", expand=True)
    view.output.configure(state="disabled")


def populate_buddies(view, info):
    for child in view.buddy_area.winfo_children():
        child.destroy()
    selected = set(view.values["buddy_ids"].get().split(","))
    view.buddy_checks = []
    buddies = info.order_param_view.buddy_list if info.order_param_view else []
    if not buddies:
        label(view.buddy_area, "暂无同伴。请先在官方页面用学号添加，再验证账号。", size=12, color=MUTED, wraplength=490).pack(anchor="w", padx=8, pady=12)
    for buddy in buddies:
        variable = tk.BooleanVar(value=str(buddy.id) in selected)
        view.buddy_checks.append((str(buddy.id), variable))
        ctk.CTkCheckBox(view.buddy_area, text=buddy.name or "未命名同伴", variable=variable,
                        command=lambda: update_selection(view), checkbox_width=20, checkbox_height=20,
                        fg_color=ACCENT, hover_color="#0D5743", text_color=INK,
                        corner_radius=5, font=(FONT, 14)).pack(anchor="w", padx=10, pady=10)


def update_selection(view):
    view.values["buddy_ids"].set(",".join(key for key, variable in view.buddy_checks if variable.get()))
