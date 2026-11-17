"""Shared native desktop controls and visual tokens."""
from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import ttk
from buaa_booking.config import CHINA

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("green")

BG = "#FFFFFF"
SIDEBAR = "#F3F6F5"
SOFT = "#F4F7F6"
INK = "#162D28"
MUTED = "#576B65"
LINE = "#DFE7E3"
ACCENT = "#146C54"
HOVER = "#0D5743"
TINT = "#E5F2EB"
FONT = "Microsoft YaHei UI"


def frame(parent, *, color="transparent", radius=0, **kwargs):
    return ctk.CTkFrame(parent, fg_color=color, corner_radius=radius, **kwargs)


def label(parent, text="", *, size=14, weight="normal", color=INK, **kwargs):
    return ctk.CTkLabel(parent, text=text, font=(FONT, size, weight), text_color=color, anchor=kwargs.pop("anchor", "w"), **kwargs)


def button(parent, text, command, *, kind="secondary", width=120, height=38, **kwargs):
    primary = kind == "primary"
    quiet = kind == "quiet"
    result = ctk.CTkButton(parent, text=text, command=command, width=width, height=height,
                         corner_radius=8, border_width=0, font=(FONT, 13),
                         fg_color=ACCENT if primary else ("transparent" if quiet else SOFT),
                         hover_color=HOVER if primary else "#E6ECE8",
                         text_color="white" if primary else INK,
                         text_color_disabled="#64766E", **kwargs)
    # CTk renders the control; keyboard activation follows standard desktop behavior.
    tk.Frame.configure(result, takefocus=True)
    tk.Frame.bind(result, "<Return>", lambda event: result.invoke())
    tk.Frame.bind(result, "<space>", lambda event: result.invoke())
    tk.Frame.bind(result, "<FocusIn>", lambda event: result.configure(border_width=2, border_color="#377C65"))
    tk.Frame.bind(result, "<FocusOut>", lambda event: result.configure(border_width=0))
    return result


def entry(parent, variable, *, width=200, placeholder="", show=None):
    kwargs = {"show": show} if show is not None else {}
    return ctk.CTkEntry(parent, textvariable=variable, width=width, height=40,
                        fg_color=SOFT, border_color=LINE, border_width=1, corner_radius=7,
                        text_color=INK, placeholder_text_color=MUTED,
                        placeholder_text=placeholder, font=(FONT, 14), **kwargs)


def segment(parent, values, command=None):
    return ctk.CTkSegmentedButton(parent, values=values, command=command, height=36,
                                fg_color=SOFT, selected_color="#CFE8DB", selected_hover_color="#C1DFCF",
                                unselected_color=SOFT, unselected_hover_color="#E6ECE8",
                                text_color=INK, font=(FONT, 13),
                                corner_radius=8, border_width=3)


def window(root, title, geometry, minimum):
    root.title(title)
    root.geometry(geometry + "+40+40")
    root.minsize(*minimum)
    icon = Path(__file__).resolve().parents[1] / "assets/court.ico"
    if icon.exists():
        root.iconbitmap(str(icon))
    try:
        root.configure(fg_color=BG)
    except (tk.TclError, ValueError):
        root.configure(bg=BG)


def tree_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Modern.Treeview", font=(FONT, 11), rowheight=44, background=BG,
                    fieldbackground=BG, foreground=INK, borderwidth=0, relief="flat")
    style.configure("Modern.Treeview.Heading", font=(FONT, 10), background=SOFT,
                    foreground=MUTED, borderwidth=0, relief="flat", padding=(8, 10))
    style.layout("Modern.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.map("Modern.Treeview", background=[("selected", TINT)], foreground=[("selected", ACCENT)])


class DatePicker:
    def __init__(self, parent, variable, *, multiple=False, width=270):
        self.variable = variable
        self.multiple = multiple
        self.body = frame(parent)
        self.input = entry(self.body, variable, width=width, placeholder="YYYY-MM-DD")
        self.input.pack(side="left", fill="x", expand=True)
        self.choose = button(self.body, "选择日期", self.open, width=90)
        self.choose.pack(side="left", padx=(8, 0))
        self.dialog = None

    def state(self, value):
        self.input.configure(state=value)
        self.choose.configure(state=value)

    def open(self):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.focus()
            return
        self.dialog = ctk.CTkToplevel(self.body)
        self.dialog.title("选择打球日期")
        self.dialog.geometry("350x400")
        self.dialog.resizable(False, False)
        self.dialog.configure(fg_color=BG)
        self.month = datetime.now(CHINA).date().replace(day=1)
        try:
            self.month = date.fromisoformat(self.variable.get().split(",")[0].strip()).replace(day=1)
        except ValueError:
            pass
        self.calendar_body = frame(self.dialog)
        self.calendar_body.pack(fill="both", expand=True, padx=18, pady=18)
        self.draw()
        self.dialog.after(100, self.dialog.lift)

    def draw(self):
        for child in self.calendar_body.winfo_children():
            child.destroy()
        header = frame(self.calendar_body)
        header.pack(fill="x", pady=(0, 14))
        button(header, "‹", lambda: self.shift(-1), width=32).pack(side="left")
        label(header, f"{self.month:%Y 年 %m 月}", size=16, weight="bold", anchor="center").pack(side="left", expand=True)
        button(header, "›", lambda: self.shift(1), width=32).pack(side="right")
        grid = frame(self.calendar_body)
        grid.pack(fill="both", expand=True)
        for index, day in enumerate("一二三四五六日"):
            grid.columnconfigure(index, weight=1)
            label(grid, day, size=12, color=MUTED, anchor="center").grid(row=0, column=index, pady=(0, 8))
        selected = {x.strip() for x in self.variable.get().split(",")}
        for row_index, week in enumerate(calendar.monthcalendar(self.month.year, self.month.month), 1):
            for column, day in enumerate(week):
                if not day:
                    continue
                target = self.month.replace(day=day)
                b = button(grid, str(day), lambda value=target: self.select(value), width=37, height=34,
                           kind="primary" if target.isoformat() in selected else "quiet")
                b.grid(row=row_index, column=column, padx=1, pady=3)
                if target < datetime.now(CHINA).date():
                    b.configure(state="disabled")
        if self.multiple:
            label(self.calendar_body, "可选多天；再次点击取消选择。", size=12, color=MUTED).pack(anchor="w", pady=(10, 4))
            button(self.calendar_body, "完成", self.dialog.destroy, kind="primary").pack(fill="x")

    def shift(self, delta):
        index = self.month.year * 12 + self.month.month - 1 + delta
        self.month = self.month.replace(year=index // 12, month=index % 12 + 1)
        self.draw()

    def select(self, target):
        if self.multiple:
            values = {x.strip() for x in self.variable.get().split(",") if x.strip()}
            if target.isoformat() in values:
                values.remove(target.isoformat())
            else:
                values.add(target.isoformat())
            self.variable.set(", ".join(sorted(values)))
            self.draw()
        else:
            self.variable.set(target.isoformat())
            self.dialog.destroy()
