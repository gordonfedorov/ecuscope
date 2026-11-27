#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rule_gui_app.py — главный модуль системного блочного конструктора правил ECUScope.
Запуск: python3 rule_gui_app.py
"""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from gui_backend import (
    collect_all_sensors,
    collect_all_tags,
    dump_yaml_text,
    list_log_files,
    list_yaml_files,
    load_yaml_file,
    save_yaml_file,
    test_rule_on_log,
)
from gui_data_blocks import (
    CompareModesBlock,
    EventWindowBlock,
    FallbackBlock,
    HeaderBlock,
    OscillationBlock,
    ThresholdBlock,
)
from gui_panels import LeftPalette, RightInspector
from gui_rule_blocks import BranchBlock, CrossDiagBlock
from gui_widgets import BG_MAIN, BG_PANEL, TEXT, make_btn, make_label


class RuleBuilderApp(tk.Tk):
    """Главное окно системного блочного конструктора правил ECUScope."""

    def __init__(self) -> None:
        super().__init__()
        self.title("ECUScope — Блочный конструктор проверок")
        self.geometry("1380x840")
        self.configure(bg=BG_MAIN)

        self._setup_ttk_style()

        self.sensors = collect_all_sensors()
        self.all_tags = collect_all_tags()
        self.logs = list_log_files()
        self.yaml_files = list_yaml_files()

        self.current_file: str = ""
        self.doc_data: dict[str, Any] = {"checks": []}
        self.checks_ref: list[dict[str, Any]] = []
        self.cur_idx: int = 0
        self._loading: bool = False

        self.blk_header: HeaderBlock | None = None
        self.blk_cfg: Any = None
        self.blk_fallbacks: list[FallbackBlock] = []
        self.blk_branches: list[BranchBlock] = []
        self.blk_diags: list[CrossDiagBlock] = []

        self._build_topbar()
        self._build_workspace()

        if self.yaml_files:
            self.v_file.set(self.yaml_files[0])
            self.open_yaml(self.yaml_files[0])
        else:
            self._new_empty_doc()

    def _setup_ttk_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG_PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background="#232a3d", foreground=TEXT, padding=[10, 4])
        style.map("TNotebook.Tab", background=[("selected", "#364466")])

    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=BG_PANEL, height=40, padx=8, pady=5)
        bar.pack(fill="x", side="top")

        make_label(bar, "Файл:", bold=True).pack(side="left")
        self.v_file = tk.StringVar()
        self.cb_file = ttk.Combobox(bar, textvariable=self.v_file, values=self.yaml_files, width=24, state="readonly")
        self.cb_file.pack(side="left", padx=(4, 6))
        self.cb_file.bind("<<ComboboxSelected>>", lambda *_: self.open_yaml(self.v_file.get()))

        make_btn(bar, "+ Файл", self.create_new_file).pack(side="left", padx=(0, 12))

        make_label(bar, "Карточка:", bold=True).pack(side="left")
        self.v_check = tk.StringVar()
        self.cb_check = ttk.Combobox(bar, textvariable=self.v_check, width=38, state="readonly")
        self.cb_check.pack(side="left", padx=(4, 6))
        self.cb_check.bind("<<ComboboxSelected>>", lambda *_: self.select_check(self.cb_check.current()))

        make_btn(bar, "+ Карточка", self.add_check).pack(side="left", padx=2)
        make_btn(bar, "Копия", self.duplicate_check).pack(side="left", padx=2)
        make_btn(bar, "Удалить", self.delete_check, bg="#4a222b").pack(side="left", padx=2)

        make_btn(bar, "💾 Сохранить YAML", self.save_current_file, bg="#2563eb").pack(side="right", padx=2)

    def _build_workspace(self) -> None:
        main = tk.Frame(self, bg=BG_MAIN)
        main.pack(fill="both", expand=True)

        callbacks = {
            "add_threshold": lambda: self._set_cfg_block("threshold"),
            "add_event": lambda: self._set_cfg_block("event_window"),
            "add_compare": lambda: self._set_cfg_block("compare_modes"),
            "add_osc": lambda: self._set_cfg_block("oscillation"),
            "add_if_empty": lambda: self._add_fallback("if_empty"),
            "add_if_clean": lambda: self._add_fallback("if_clean"),
            "add_when": lambda: self._add_branch(is_default=False),
            "add_default": lambda: self._add_branch(is_default=True),
            "add_diag": self._add_diag,
        }
        self.palette = LeftPalette(main, self.sensors, self.all_tags, callbacks)
        self.palette.pack(side="left", fill="y")

        self.inspector = RightInspector(main, self.logs, self.run_live_test)
        self.inspector.pack(side="right", fill="y")

        center = tk.Frame(main, bg=BG_MAIN)
        center.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(center, bg=BG_MAIN, highlightthickness=0)
        sb = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        self.blocks_frame = tk.Frame(self.canvas, bg=BG_MAIN)

        self.blocks_frame.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.win_id = self.canvas.create_window((0, 0), window=self.blocks_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win_id, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"))

    def _extract_checks_ref(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(data.get("checks"), list):
            return data["checks"]
        if isinstance(data.get("sections"), list):
            for sec in data["sections"]:
                if isinstance(sec, dict) and isinstance(sec.get("checks"), list):
                    return sec["checks"]
        data["checks"] = []
        return data["checks"]

    def _new_empty_doc(self) -> None:
        self.current_file = "custom_rules.yaml"
        self.doc_data = {"checks": [{"id": "new_check", "title": "Новая проверка", "type": "threshold", "mode": "running", "param": "RPM", "agg": "median", "rules": [{"when": "val > 1000", "status": "status-warn", "badge": "ОТКЛОНЕНИЕ"}, {"default": None, "status": "status-ok", "badge": "НОРМА"}]}]}
        self.checks_ref = self._extract_checks_ref(self.doc_data)
        self.select_check(0)

    def open_yaml(self, filename: str) -> None:
        try:
            self.doc_data = load_yaml_file(filename)
            self.current_file = filename
            self.checks_ref = self._extract_checks_ref(self.doc_data)
            if not self.checks_ref:
                self.checks_ref.append({"id": "new_check", "title": "Новая проверка", "type": "threshold", "rules": []})
            self._refresh_check_combo(0)
            self.select_check(0)
        except Exception as exc:
            messagebox.showerror("Ошибка открытия YAML", str(exc))

    def _refresh_check_combo(self, idx: int) -> None:
        labels = [f"{i + 1}. {c.get('id', 'no_id')} — {c.get('title', '')}" for i, c in enumerate(self.checks_ref)]
        self.cb_check["values"] = labels
        if labels:
            self.cb_check.current(max(0, min(idx, len(labels) - 1)))

    def select_check(self, idx: int) -> None:
        if not self.checks_ref:
            return
        self.cur_idx = max(0, min(idx, len(self.checks_ref) - 1))
        self._refresh_check_combo(self.cur_idx)
        self._render_rule_blocks(self.checks_ref[self.cur_idx])

    def _render_rule_blocks(self, rule: dict[str, Any]) -> None:
        self._loading = True
        for child in self.blocks_frame.winfo_children():
            child.destroy()

        self.blk_header = HeaderBlock(self.blocks_frame, rule, self._on_blocks_edited)
        self.blk_cfg = None
        self.blk_fallbacks = []
        self.blk_branches = []
        self.blk_diags = []

        rtype = str(rule.get("type", "threshold"))
        if rtype == "event_window" or "trigger" in rule or "window" in rule:
            self.blk_cfg = EventWindowBlock(self.blocks_frame, rule, self._on_blocks_edited, self._remove_cfg)
        elif rtype == "compare_modes" or "inputs" in rule:
            self.blk_cfg = CompareModesBlock(self.blocks_frame, rule, self.sensors, self._on_blocks_edited, self._remove_cfg)
        elif rtype == "oscillation" or "high_threshold" in rule:
            self.blk_cfg = OscillationBlock(self.blocks_frame, rule, self.sensors, self._on_blocks_edited, self._remove_cfg)
        elif rtype != "cross_diagnosis":
            self.blk_cfg = ThresholdBlock(self.blocks_frame, rule, self.sensors, self._on_blocks_edited, self._remove_cfg)

        if isinstance(rule.get("if_empty"), dict):
            self._mount_fallback("if_empty", rule["if_empty"])
        if isinstance(rule.get("if_clean"), dict):
            self._mount_fallback("if_clean", rule["if_clean"])

        for br in rule.get("rules") or []:
            if isinstance(br, dict):
                self._mount_branch(br, is_default=("default" in br))

        for dg in rule.get("diagnoses") or []:
            if isinstance(dg, dict):
                self._mount_diag(dg)

        self._loading = False
        self._on_blocks_edited()

    def _remove_cfg(self) -> None:
        if self.blk_cfg is not None:
            self.blk_cfg.destroy()
            self.blk_cfg = None
            self._on_blocks_edited()

    def _set_cfg_block(self, kind: str) -> None:
        cur = self._collect_current_rule()
        cur["type"] = kind
        self._render_rule_blocks(cur)

    def _mount_fallback(self, kind: str, data: dict[str, Any]) -> None:
        def _del() -> None:
            blk.destroy()
            self.blk_fallbacks.remove(blk)
            self._on_blocks_edited()

        blk = FallbackBlock(self.blocks_frame, kind, data, self._on_blocks_edited, _del)
        self.blk_fallbacks.append(blk)

    def _add_fallback(self, kind: str) -> None:
        if any(f.kind == kind for f in self.blk_fallbacks):
            messagebox.showinfo("Заглушка", f"Блок {kind} уже добавлен в эту карточку.")
            return
        sample = {"status": "status-na", "badge": "НЕТ ДАННЫХ", "val": "Нет данных"} if kind == "if_empty" else {"badge": "НОРМА", "val": "Противоречий нет"}
        self._mount_fallback(kind, sample)
        self._on_blocks_edited()

    def _mount_branch(self, data: dict[str, Any], is_default: bool) -> None:
        def _del() -> None:
            blk.destroy()
            self.blk_branches.remove(blk)
            self._on_blocks_edited()

        blk = BranchBlock(self.blocks_frame, data, is_default, self._on_blocks_edited, _del)
        self.blk_branches.append(blk)

    def _add_branch(self, is_default: bool) -> None:
        sample = {"default": None, "status": "status-ok", "badge": "НОРМА", "tip": "Параметр в норме"} if is_default else {"when": "val > 1000", "status": "status-warn", "badge": "ОТКЛОНЕНИЕ", "tip": "Описание"}
        self._mount_branch(sample, is_default=is_default)
        self._on_blocks_edited()

    def _mount_diag(self, data: dict[str, Any]) -> None:
        def _del() -> None:
            blk.destroy()
            self.blk_diags.remove(blk)
            self._on_blocks_edited()

        blk = CrossDiagBlock(self.blocks_frame, data, self._on_blocks_edited, _del)
        self.blk_diags.append(blk)

    def _add_diag(self) -> None:
        if self.blk_header:
            self.blk_header.v_type.set("cross_diagnosis")
        self._mount_diag({"id": f"diag_{len(self.blk_diags) + 1}", "status": "warn", "title": "Новый диагноз", "any_tags": ["tag_1"]})
        self._on_blocks_edited()

    def _collect_current_rule(self) -> dict[str, Any]:
        rule: dict[str, Any] = {}
        if self.blk_header:
            self.blk_header.dump(rule)
        if self.blk_cfg is not None:
            self.blk_cfg.dump(rule)
        for fb in self.blk_fallbacks:
            fb.dump(rule)

        if self.blk_branches:
            rule["rules"] = [b.dump() for b in self.blk_branches]
        elif rule.get("type") != "cross_diagnosis":
            rule["rules"] = []

        if self.blk_diags:
            rule["diagnoses"] = [d.dump() for d in self.blk_diags]
        return rule

    def _on_blocks_edited(self) -> None:
        if self._loading or not self.checks_ref:
            return
        rule = self._collect_current_rule()
        self.checks_ref[self.cur_idx] = rule
        self._refresh_check_combo(self.cur_idx)
        self.inspector.set_yaml_preview(dump_yaml_text(rule))

    def run_live_test(self, log_path: str) -> None:
        if not log_path:
            self.inspector.show_test_error("В папке logs/ не найдено файлов логов.")
            return
        try:
            rule = self._collect_current_rule()
            card, ms = test_rule_on_log(rule, log_path)
            self.inspector.show_test_result(card, ms)
        except Exception as exc:
            self.inspector.show_test_error(str(exc))

    def add_check(self) -> None:
        new_rule = {"id": f"check_{len(self.checks_ref) + 1}", "title": "Новая проверка", "type": "threshold", "mode": "running", "param": "RPM", "agg": "median", "min_samples": 5, "rules": [{"when": "val > 1000", "status": "status-warn", "badge": "ОТКЛОНЕНИЕ"}, {"default": None, "status": "status-ok", "badge": "НОРМА"}]}
        self.checks_ref.append(new_rule)
        self.select_check(len(self.checks_ref) - 1)

    def duplicate_check(self) -> None:
        if not self.checks_ref:
            return
        dup = copy.deepcopy(self.checks_ref[self.cur_idx])
        dup["id"] = f"{dup.get('id', 'check')}_copy"
        self.checks_ref.insert(self.cur_idx + 1, dup)
        self.select_check(self.cur_idx + 1)

    def delete_check(self) -> None:
        if len(self.checks_ref) <= 1:
            messagebox.showwarning("Удаление", "В файле должна остаться хотя бы одна карточка.")
            return
        if messagebox.askyesno("Удаление карточки", "Удалить текущую карточку проверки?"):
            self.checks_ref.pop(self.cur_idx)
            self.select_check(max(0, self.cur_idx - 1))

    def create_new_file(self) -> None:
        name = simpledialog.askstring("Новый YAML-файл", "Введите имя файла (например: my_checks.yaml):")
        if not name:
            return
        if not name.endswith(".yaml"):
            name += ".yaml"
        self.current_file = name
        self.doc_data = {"checks": [{"id": "new_check", "title": "Новая проверка", "type": "threshold", "rules": []}]}
        self.checks_ref = self._extract_checks_ref(self.doc_data)
        self.save_current_file()
        self.yaml_files = list_yaml_files()
        self.cb_file["values"] = self.yaml_files
        self.v_file.set(name)
        self.select_check(0)

    def save_current_file(self) -> None:
        try:
            self._on_blocks_edited()
            saved = save_yaml_file(self.current_file or "custom_rules.yaml", self.doc_data)
            self.all_tags = collect_all_tags()
            messagebox.showinfo("Сохранено", f"Файл rules/{saved} сохранён (резервная копия .bak создана).")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))


if __name__ == "__main__":
    app = RuleBuilderApp()
    app.mainloop()
