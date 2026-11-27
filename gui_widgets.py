#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_widgets.py — цветовая палитра, константные списки и базовые виджеты C-блоков для ECUScope.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

BG_MAIN = "#12151f"
BG_PANEL = "#181d2b"
BG_CARD = "#1e2436"
BG_INPUT = "#10131c"
BORDER = "#2d354d"
TEXT = "#e6eaf5"
MUTED = "#8c96b2"

CLR_HEADER = "#4c97ff"     # Шапка карточки
CLR_SENSOR = "#9966ff"     # Настройки замера / inputs / compute
CLR_TRIGGER = "#ff8c1a"    # Событие event_window
CLR_COMPARE = "#0fbd8c"    # Сравнение режимов / oscillation / if_empty
CLR_CONDITION = "#ffab19"  # Ветки правил when / default
CLR_DIAG = "#cf63cf"       # Перекрёстный диагноз cross_diagnosis

FONT_UI = ("TkDefaultFont", 9)
FONT_BOLD = ("TkDefaultFont", 9, "bold")
FONT_MONO = ("TkFixedFont", 9)

RULE_TYPES = ["threshold", "event_window", "compare_modes", "oscillation", "cross_diagnosis"]
MODES_LIST = ["running", "hot_idle", "valid"]
AGGS_LIST = ["median", "mean", "min", "max", "last", "first", "count", "spread", "p10_p90"]
STATUSES_LIST = ["status-ok", "status-warn", "status-bad", "status-na", "ok", "warn", "bad"]

ACTIVE_ENTRY: tk.Entry | None = None


def track_focus(widget: tk.Entry) -> tk.Entry:
    def _on_focus(_event: Any) -> None:
        global ACTIVE_ENTRY
        ACTIVE_ENTRY = widget

    widget.bind("<FocusIn>", _on_focus, add="+")
    return widget


def insert_into_active(text: str, append_comma: bool = False) -> bool:
    w = ACTIVE_ENTRY
    if w is None:
        return False
    try:
        if not w.winfo_exists():
            return False
        cur = w.get()
        if append_comma and cur.strip() and not cur.rstrip().endswith(","):
            w.insert(tk.END, f", {text}")
        else:
            w.insert(tk.INSERT, text)
        w.focus_set()
        return True
    except tk.TclError:
        return False


def make_label(parent: tk.Widget, text: str, fg: str = MUTED, bold: bool = False) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=parent.cget("bg"),
        fg=fg,
        font=FONT_BOLD if bold else FONT_UI,
        anchor="w",
    )


def make_entry(parent: tk.Widget, var: tk.StringVar, width: int = 20, mono: bool = False) -> tk.Entry:
    ent = tk.Entry(
        parent,
        textvariable=var,
        width=width,
        bg=BG_INPUT,
        fg=TEXT,
        insertbackground=TEXT,
        relief="flat",
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=CLR_HEADER,
        font=FONT_MONO if mono else FONT_UI,
    )
    return track_focus(ent)


def make_combo(parent: tk.Widget, var: tk.StringVar, values: list[str], width: int = 16) -> ttk.Combobox:
    return ttk.Combobox(parent, textvariable=var, values=values, width=width, state="normal")


def make_btn(
    parent: tk.Widget,
    text: str,
    cmd: Callable[[], None],
    bg: str = "#262f47",
    fg: str = TEXT,
    padx: int = 8,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=cmd,
        bg=bg,
        fg=fg,
        activebackground="#364263",
        activeforeground="#ffffff",
        relief="flat",
        bd=0,
        padx=padx,
        pady=3,
        font=FONT_BOLD,
        cursor="hand2",
    )


class CBlock(tk.Frame):
    """Каркас визуального C-блока с цветным левым корешком."""

    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        color: str,
        on_delete: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        self.pack(fill="x", padx=6, pady=4)

        stripe = tk.Frame(self, bg=color, width=6)
        stripe.pack(side="left", fill="y")

        right = tk.Frame(self, bg=BG_CARD)
        right.pack(side="left", fill="both", expand=True)

        hdr = tk.Frame(right, bg=color, height=24)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text=f"  {title}", bg=color, fg="#10131c", font=FONT_BOLD, anchor="w").pack(side="left", fill="y")

        if on_delete is not None:
            tk.Button(
                hdr,
                text="✕",
                command=on_delete,
                bg=color,
                fg="#10131c",
                activebackground="#ff5c5c",
                relief="flat",
                bd=0,
                padx=7,
                font=FONT_BOLD,
                cursor="hand2",
            ).pack(side="right", fill="y")

        self.body = tk.Frame(right, bg=BG_CARD, padx=8, pady=6)
        self.body.pack(fill="x")
