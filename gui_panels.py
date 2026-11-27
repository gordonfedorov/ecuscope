#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_panels.py — левая палитра (блоки, функции, датчики, теги)
и правая панель (живой тест на логе + предпросмотр YAML).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from gui_widgets import (
    BG_CARD,
    BG_INPUT,
    BG_PANEL,
    BORDER,
    CLR_COMPARE,
    CLR_CONDITION,
    CLR_DIAG,
    CLR_SENSOR,
    CLR_TRIGGER,
    FONT_BOLD,
    FONT_MONO,
    FONT_UI,
    MUTED,
    TEXT,
    insert_into_active,
    make_btn,
    make_combo,
    make_entry,
    make_label,
)

FUNC_SNIPPETS = [
    ("median('S', 'mode')", "median('RPM', 'running')"),
    ("mean('S', 'mode')", "mean('VBAT', 'running')"),
    ("min('S', 'mode')", "min('VBAT', 'running')"),
    ("max('S', 'mode')", "max('ECT', 'valid')"),
    ("last('S', 'mode')", "last('FRA', 'valid')"),
    ("count(cond)", "count(stalled)"),
    ("abs(x)", "abs(val)"),
    ("and / or / not", " and "),
]


class LeftPalette(tk.Frame):
    """Левая панель: добавление блоков, вставка функций, датчиков и тегов."""

    def __init__(
        self,
        parent: tk.Widget,
        sensors: list[str],
        tags: list[str],
        callbacks: dict[str, Callable[[], None]],
    ) -> None:
        super().__init__(parent, bg=BG_PANEL, width=250)
        self.pack_propagate(False)
        self.sensors = sensors
        self.tags = tags

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        tab_blocks = tk.Frame(nb, bg=BG_PANEL)
        tab_funcs = tk.Frame(nb, bg=BG_PANEL)
        tab_sens = tk.Frame(nb, bg=BG_PANEL)
        tab_tags = tk.Frame(nb, bg=BG_PANEL)

        nb.add(tab_blocks, text="Блоки")
        nb.add(tab_funcs, text="Функции")
        nb.add(tab_sens, text="Датчики")
        nb.add(tab_tags, text="Теги")

        self._build_blocks_tab(tab_blocks, callbacks)
        self._build_funcs_tab(tab_funcs)
        self._build_search_tab(tab_sens, self.sensors, append_comma=False)
        self._build_search_tab(tab_tags, self.tags, append_comma=True)

    def _build_blocks_tab(self, parent: tk.Frame, cb: dict[str, Callable[[], None]]) -> None:
        make_label(parent, "Настройки замера:", bold=True).pack(fill="x", padx=8, pady=(6, 2))
        cfg_items = [
            ("+ Порог (threshold)", CLR_SENSOR, cb["add_threshold"]),
            ("+ Событие (event_window)", CLR_TRIGGER, cb["add_event"]),
            ("+ Сравнение (compare_modes)", CLR_COMPARE, cb["add_compare"]),
            ("+ Колебания (oscillation)", CLR_SENSOR, cb["add_osc"]),
            ("+ Заглушка if_empty", CLR_COMPARE, cb["add_if_empty"]),
            ("+ Заглушка if_clean", CLR_COMPARE, cb["add_if_clean"]),
        ]
        for label, color, fn in cfg_items:
            tk.Button(
                parent, text=label, command=fn, bg=color, fg="#10131c",
                activebackground="#ffffff", relief="flat", anchor="w",
                padx=10, pady=4, font=FONT_BOLD, cursor="hand2"
            ).pack(fill="x", padx=8, pady=2)

        make_label(parent, "Правила и диагнозы:", bold=True).pack(fill="x", padx=8, pady=(8, 2))
        br_items = [
            ("+ Условие (when)", CLR_CONDITION, cb["add_when"]),
            ("+ Иначе (default)", CLR_CONDITION, cb["add_default"]),
            ("+ Сводный диагноз", CLR_DIAG, cb["add_diag"]),
        ]
        for label, color, fn in br_items:
            tk.Button(
                parent, text=label, command=fn, bg=color, fg="#10131c",
                activebackground="#ffffff", relief="flat", anchor="w",
                padx=10, pady=4, font=FONT_BOLD, cursor="hand2"
            ).pack(fill="x", padx=8, pady=2)

    def _build_funcs_tab(self, parent: tk.Frame) -> None:
        make_label(parent, "Вставить в активное поле:", bold=True).pack(fill="x", padx=8, pady=(8, 4))
        for title, snippet in FUNC_SNIPPETS:
            make_btn(parent, title, lambda s=snippet: insert_into_active(s, False), bg=BG_CARD).pack(fill="x", padx=8, pady=2)

    def _build_search_tab(self, parent: tk.Frame, items: list[str], append_comma: bool) -> None:
        q_var = tk.StringVar()
        make_entry(parent, q_var, width=22, mono=True).pack(fill="x", padx=6, pady=(6, 4))

        lb = tk.Listbox(
            parent, bg=BG_INPUT, fg=TEXT, selectbackground="#324675",
            relief="flat", highlightthickness=1, highlightbackground=BORDER, font=FONT_MONO
        )
        lb.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        def _refresh(*_: Any) -> None:
            q = q_var.get().strip().lower()
            lb.delete(0, tk.END)
            for it in items:
                if not q or q in it.lower():
                    lb.insert(tk.END, it)

        def _on_pick(_e: Any) -> None:
            sel = lb.curselection()
            if sel:
                insert_into_active(lb.get(sel[0]), append_comma=append_comma)

        q_var.trace_add("write", _refresh)
        lb.bind("<Double-Button-1>", _on_pick)
        lb.bind("<Return>", _on_pick)
        _refresh()


class RightInspector(tk.Frame):
    """Правая панель: живой тест карточки на логе и текст итогового YAML."""

    def __init__(self, parent: tk.Widget, logs: list[str], on_test: Callable[[str], None]) -> None:
        super().__init__(parent, bg=BG_PANEL, width=350)
        self.pack_propagate(False)

        top = tk.Frame(self, bg=BG_PANEL)
        top.pack(fill="x", padx=8, pady=(8, 4))
        make_label(top, "Живой тест на логе:", bold=True).pack(anchor="w")

        row = tk.Frame(self, bg=BG_PANEL)
        row.pack(fill="x", padx=8, pady=2)
        self.v_log = tk.StringVar(value=logs[0] if logs else "")
        make_combo(row, self.v_log, logs, width=22).pack(side="left", fill="x", expand=True, padx=(0, 4))
        make_btn(row, "▶ Тест", lambda: on_test(self.v_log.get()), bg="#1f7a4c").pack(side="right")

        self.card_box = tk.Frame(self, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1, padx=8, pady=6)
        self.card_box.pack(fill="x", padx=8, pady=6)

        self.lbl_status = tk.Label(self.card_box, text="Нажмите «▶ Тест» для проверки", bg=BG_CARD, fg=MUTED, font=FONT_BOLD, anchor="w", justify="left")
        self.lbl_status.pack(fill="x")
        self.lbl_detail = tk.Label(self.card_box, text="", bg=BG_CARD, fg=TEXT, font=FONT_UI, anchor="w", justify="left", wraplength=315)
        self.lbl_detail.pack(fill="x", pady=(4, 0))

        make_label(self, "Предпросмотр YAML карточки:", bold=True).pack(fill="x", padx=8, pady=(6, 2))
        self.txt_yaml = tk.Text(
            self, bg=BG_INPUT, fg="#a8d8ff", relief="flat",
            highlightthickness=1, highlightbackground=BORDER, font=FONT_MONO, wrap="none"
        )
        self.txt_yaml.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def set_yaml_preview(self, text: str) -> None:
        self.txt_yaml.delete("1.0", tk.END)
        self.txt_yaml.insert("1.0", text)

    def show_test_result(self, card: dict[str, Any] | None, elapsed_ms: float) -> None:
        if card is None:
            self.lbl_status.config(text=f"SKIP / Не применимо ({elapsed_ms} мс)", fg=MUTED)
            self.lbl_detail.config(text="Правило пропущено.")
            return

        st = str(card.get("status") or card.get("severity") or "status-ok").lower()
        if "bad" in st or "crit" in st:
            clr = "#ff5c5c"
        elif "warn" in st:
            clr = "#ffab19"
        elif "na" in st:
            clr = MUTED
        else:
            clr = "#3ddc84"

        badge = card.get("badge") or st.upper()
        title = card.get("title", "")
        val_txt = card.get("val") or card.get("summary") or ""
        tip_txt = card.get("tip") or card.get("detail") or ""
        tags = ", ".join(card.get("tags") or [])

        self.lbl_status.config(text=f"[{badge}] {title} ({elapsed_ms} мс)", fg=clr)
        lines = [x for x in (val_txt, tip_txt, f"Теги: {tags}" if tags else "") if x]
        self.lbl_detail.config(text="\n".join(lines))

    def show_test_error(self, msg: str) -> None:
        self.lbl_status.config(text="Ошибка проверки", fg="#ff5c5c")
        self.lbl_detail.config(text=msg)
