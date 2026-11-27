#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_rule_blocks.py — визуальные блоки веток правил (when / default)
и правил перекрёстного диагноза (diagnoses) для ECUScope.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from gui_data_blocks import parse_csv
from gui_widgets import (
    BG_CARD,
    CLR_CONDITION,
    CLR_DIAG,
    STATUSES_LIST,
    CBlock,
    make_combo,
    make_entry,
    make_label,
)


class BranchBlock(CBlock):
    """Жёлтый C-блок ветки условия when или default."""

    def __init__(
        self,
        parent: tk.Widget,
        branch: dict[str, Any],
        is_default: bool,
        on_change: Callable[[], None],
        on_delete: Callable[[], None],
    ) -> None:
        title = "ИНАЧЕ (default)" if is_default else "ЕСЛИ (when)"
        super().__init__(parent, title, CLR_CONDITION, on_delete=on_delete)
        self.is_default = is_default
        self._default_val = branch.get("default", None)

        self.v_when = tk.StringVar(value=str(branch.get("when", "")))
        self.v_status = tk.StringVar(value=str(branch.get("status", "status-ok" if is_default else "status-warn")))
        self.v_badge = tk.StringVar(value=str(branch.get("badge", "НОРМА" if is_default else "ОТКЛОНЕНИЕ")))
        self.v_tags = tk.StringVar(value=", ".join(str(t) for t in (branch.get("tags") or [])))
        self.v_val = tk.StringVar(value=str(branch.get("val", "")))
        self.v_tip = tk.StringVar(value=str(branch.get("tip", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        if not is_default:
            make_label(r1, "when:").pack(side="left")
            make_entry(r1, self.v_when, width=36, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 8))
        make_label(r1, "status:").pack(side="left")
        cb = make_combo(r1, self.v_status, STATUSES_LIST, width=11)
        cb.pack(side="left", padx=(4, 8))
        make_label(r1, "badge:").pack(side="left")
        make_entry(r1, self.v_badge, width=18).pack(side="left", padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "val:").pack(side="left")
        make_entry(r2, self.v_val, width=34, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 8))
        make_label(r2, "tags:").pack(side="left")
        make_entry(r2, self.v_tags, width=22, mono=True).pack(side="left", padx=4)

        r3 = tk.Frame(self.body, bg=BG_CARD)
        r3.pack(fill="x", pady=2)
        make_label(r3, "tip:").pack(side="left")
        make_entry(r3, self.v_tip, width=56).pack(side="left", fill="x", expand=True, padx=4)

        for v in (self.v_when, self.v_status, self.v_badge, self.v_tags, self.v_val, self.v_tip):
            v.trace_add("write", lambda *_: on_change())
        cb.bind("<<ComboboxSelected>>", lambda *_: on_change())

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.is_default:
            out["default"] = self._default_val
        else:
            out["when"] = self.v_when.get().strip() or "True"
        out["status"] = self.v_status.get().strip() or "status-warn"
        if self.v_badge.get().strip():
            out["badge"] = self.v_badge.get().strip()
        tags = parse_csv(self.v_tags.get())
        if tags:
            out["tags"] = tags
        if self.v_val.get().strip():
            out["val"] = self.v_val.get().strip()
        if self.v_tip.get().strip():
            out["tip"] = self.v_tip.get().strip()
        return out


class CrossDiagBlock(CBlock):
    """Пурпурный C-блок правила из списка diagnoses (cross_diagnosis.yaml)."""

    def __init__(
        self,
        parent: tk.Widget,
        diag: dict[str, Any],
        on_change: Callable[[], None],
        on_delete: Callable[[], None],
    ) -> None:
        super().__init__(parent, "СВОДНЫЙ ДИАГНОЗ (diagnoses)", CLR_DIAG, on_delete=on_delete)

        self.v_id = tk.StringVar(value=str(diag.get("id", "diag_id")))
        self.v_status = tk.StringVar(value=str(diag.get("status", "warn")))
        self.v_title = tk.StringVar(value=str(diag.get("title", "Название диагноза")))
        self.v_all = tk.StringVar(value=", ".join(str(t) for t in (diag.get("all_tags") or [])))
        self.v_any = tk.StringVar(value=", ".join(str(t) for t in (diag.get("any_tags") or [])))
        self.v_none = tk.StringVar(value=", ".join(str(t) for t in (diag.get("none_tags") or [])))
        self.v_norm = tk.StringVar(value=str(diag.get("norm", "")))
        self.v_tip = tk.StringVar(value=str(diag.get("tip", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "id:").pack(side="left")
        make_entry(r1, self.v_id, width=20, mono=True).pack(side="left", padx=(4, 8))
        make_label(r1, "status:").pack(side="left")
        cb = make_combo(r1, self.v_status, STATUSES_LIST, width=10)
        cb.pack(side="left", padx=(4, 8))
        make_label(r1, "title:").pack(side="left")
        make_entry(r1, self.v_title, width=28).pack(side="left", fill="x", expand=True, padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "all_tags:").pack(side="left")
        make_entry(r2, self.v_all, width=18, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 6))
        make_label(r2, "any_tags:").pack(side="left")
        make_entry(r2, self.v_any, width=22, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 6))
        make_label(r2, "none_tags:").pack(side="left")
        make_entry(r2, self.v_none, width=16, mono=True).pack(side="left", padx=4)

        r3 = tk.Frame(self.body, bg=BG_CARD)
        r3.pack(fill="x", pady=2)
        make_label(r3, "norm:").pack(side="left")
        make_entry(r3, self.v_norm, width=24).pack(side="left", padx=(4, 8))
        make_label(r3, "tip:").pack(side="left")
        make_entry(r3, self.v_tip, width=36).pack(side="left", fill="x", expand=True, padx=4)

        for v in (self.v_id, self.v_status, self.v_title, self.v_all, self.v_any, self.v_none, self.v_norm, self.v_tip):
            v.trace_add("write", lambda *_: on_change())
        cb.bind("<<ComboboxSelected>>", lambda *_: on_change())

    def dump(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.v_id.get().strip() or "diag_id",
            "status": self.v_status.get().strip() or "warn",
            "title": self.v_title.get().strip() or "Диагноз",
        }
        if parse_csv(self.v_all.get()):
            out["all_tags"] = parse_csv(self.v_all.get())
        if parse_csv(self.v_any.get()):
            out["any_tags"] = parse_csv(self.v_any.get())
        if parse_csv(self.v_none.get()):
            out["none_tags"] = parse_csv(self.v_none.get())
        if self.v_norm.get().strip():
            out["norm"] = self.v_norm.get().strip()
        if self.v_tip.get().strip():
            out["tip"] = self.v_tip.get().strip()
        return out
