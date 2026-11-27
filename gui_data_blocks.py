#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_data_blocks.py — визуальные блоки настройки карточки ECUScope:
HeaderBlock, ThresholdBlock, EventWindowBlock, CompareModesBlock, OscillationBlock, FallbackBlock.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from gui_widgets import (
    AGGS_LIST,
    BG_CARD,
    CLR_COMPARE,
    CLR_HEADER,
    CLR_SENSOR,
    CLR_TRIGGER,
    MODES_LIST,
    RULE_TYPES,
    STATUSES_LIST,
    CBlock,
    make_btn,
    make_combo,
    make_entry,
    make_label,
)


def parse_csv(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def num_val(raw: str, default: float = 0.0) -> int | float:
    s = raw.strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return default


class HeaderBlock(CBlock):
    def __init__(self, parent: tk.Widget, rule: dict[str, Any], on_change: Callable[[], None]) -> None:
        super().__init__(parent, "КАРТОЧКА ПРОВЕРКИ (шапка)", CLR_HEADER)
        self.v_id = tk.StringVar(value=str(rule.get("id", "new_check")))
        self.v_title = tk.StringVar(value=str(rule.get("title", "Новая проверка")))
        self.v_type = tk.StringVar(value=str(rule.get("type", "threshold")))
        self.v_norm = tk.StringVar(value=str(rule.get("norm", "")))
        self.v_traces = tk.StringVar(value=", ".join(str(t) for t in (rule.get("focus_traces") or [])))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "id:").pack(side="left")
        make_entry(r1, self.v_id, width=22, mono=True).pack(side="left", padx=(4, 10))
        make_label(r1, "type:").pack(side="left")
        cb = make_combo(r1, self.v_type, RULE_TYPES, width=18)
        cb.pack(side="left", padx=(4, 10))
        make_label(r1, "focus_traces:").pack(side="left")
        make_entry(r1, self.v_traces, width=24, mono=True).pack(side="left", fill="x", expand=True, padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "title:").pack(side="left")
        make_entry(r2, self.v_title, width=32).pack(side="left", fill="x", expand=True, padx=(4, 10))
        make_label(r2, "norm:").pack(side="left")
        make_entry(r2, self.v_norm, width=32).pack(side="left", fill="x", expand=True, padx=4)

        for v in (self.v_id, self.v_title, self.v_norm, self.v_traces):
            v.trace_add("write", lambda *_: on_change())
        cb.bind("<<ComboboxSelected>>", lambda *_: on_change())

    def dump(self, target: dict[str, Any]) -> None:
        target["id"] = self.v_id.get().strip() or "new_check"
        target["title"] = self.v_title.get().strip() or target["id"]
        target["type"] = self.v_type.get().strip() or "threshold"
        if self.v_norm.get().strip():
            target["norm"] = self.v_norm.get().strip()
        traces = parse_csv(self.v_traces.get())
        if traces:
            target["focus_traces"] = traces


class ThresholdBlock(CBlock):
    def __init__(self, parent: tk.Widget, rule: dict[str, Any], sensors: list[str], on_change: Callable[[], None], on_delete: Callable[[], None]) -> None:
        super().__init__(parent, "ПОРОГОВЫЙ ЗАМЕР (threshold)", CLR_SENSOR, on_delete=on_delete)
        self.v_mode = tk.StringVar(value=str(rule.get("mode", "running")))
        self.v_param = tk.StringVar(value=str(rule.get("param", "")))
        self.v_agg = tk.StringVar(value=str(rule.get("agg", "median")))
        self.v_expr = tk.StringVar(value=str(rule.get("expr", "")))
        self.v_min = tk.StringVar(value=str(rule.get("min_samples", 5)))
        self.v_fmt = tk.StringVar(value=str(rule.get("val_fmt", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "mode:").pack(side="left")
        make_combo(r1, self.v_mode, MODES_LIST, width=10).pack(side="left", padx=(4, 8))
        make_label(r1, "param:").pack(side="left")
        make_combo(r1, self.v_param, [""] + sensors, width=14).pack(side="left", padx=(4, 8))
        make_label(r1, "agg:").pack(side="left")
        make_combo(r1, self.v_agg, AGGS_LIST, width=10).pack(side="left", padx=(4, 8))
        make_label(r1, "min_samples:").pack(side="left")
        make_entry(r1, self.v_min, width=5, mono=True).pack(side="left", padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "expr (вместо param):").pack(side="left")
        make_entry(r2, self.v_expr, width=30, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 8))
        make_label(r2, "val_fmt:").pack(side="left")
        make_entry(r2, self.v_fmt, width=26, mono=True).pack(side="left", fill="x", expand=True, padx=4)

        for v in (self.v_mode, self.v_param, self.v_agg, self.v_expr, self.v_min, self.v_fmt):
            v.trace_add("write", lambda *_: on_change())

    def dump(self, target: dict[str, Any]) -> None:
        target["mode"] = self.v_mode.get().strip() or "running"
        if self.v_expr.get().strip():
            target["expr"] = self.v_expr.get().strip()
        elif self.v_param.get().strip():
            target["param"] = self.v_param.get().strip()
            target["agg"] = self.v_agg.get().strip() or "median"
        ms = self.v_min.get().strip()
        if ms.isdigit() and int(ms) > 0:
            target["min_samples"] = int(ms)
        if self.v_fmt.get().strip():
            target["val_fmt"] = self.v_fmt.get().strip()


class EventWindowBlock(CBlock):
    def __init__(self, parent: tk.Widget, rule: dict[str, Any], on_change: Callable[[], None], on_delete: Callable[[], None]) -> None:
        super().__init__(parent, "ОКНО СОБЫТИЯ (event_window)", CLR_TRIGGER, on_delete=on_delete)
        self.on_change = on_change
        tr = rule.get("trigger") or {}
        wn = rule.get("window") or {}

        self.v_mode = tk.StringVar(value=str(rule.get("mode", "")))
        self.v_fmetric = tk.StringVar(value=str(rule.get("focus_metric", "")))
        self.v_where = tk.StringVar(value=str(tr.get("where", "")))
        self.v_trans = tk.StringVar(value=str(tr.get("transition", "")))
        self.v_cool = tk.StringVar(value=str(tr.get("cooldown_sec", 1.5)))
        self.v_dur = tk.StringVar(value=str(wn.get("duration_sec", 1.0)))
        self.v_until = tk.StringVar(value=str(wn.get("until", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "mode:").pack(side="left")
        make_combo(r1, self.v_mode, [""] + MODES_LIST, width=10).pack(side="left", padx=(4, 8))
        make_label(r1, "where:").pack(side="left")
        make_entry(r1, self.v_where, width=28, mono=True).pack(side="left", fill="x", expand=True, padx=(4, 8))
        make_label(r1, "cooldown_sec:").pack(side="left")
        make_entry(r1, self.v_cool, width=6, mono=True).pack(side="left", padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "transition:").pack(side="left")
        make_entry(r2, self.v_trans, width=22, mono=True).pack(side="left", padx=(4, 8))
        make_label(r2, "duration_sec:").pack(side="left")
        make_entry(r2, self.v_dur, width=6, mono=True).pack(side="left", padx=(4, 8))
        make_label(r2, "until:").pack(side="left")
        make_entry(r2, self.v_until, width=20, mono=True).pack(side="left", fill="x", expand=True, padx=4)

        self.metrics_frame = tk.Frame(self.body, bg=BG_CARD)
        self.metrics_frame.pack(fill="x", pady=(4, 0))
        self.metric_rows: list[tuple[tk.Frame, tk.StringVar, tk.StringVar]] = []

        bar = tk.Frame(self.body, bg=BG_CARD)
        bar.pack(fill="x", pady=(4, 0))
        make_btn(bar, "+ Метрика окна (metrics)", lambda: self.add_metric("min_vbat", "min(VBAT)")).pack(side="left")

        for k, v in (wn.get("metrics") or {}).items():
            self.add_metric(str(k), str(v), silent=True)

        for v in (self.v_mode, self.v_fmetric, self.v_where, self.v_trans, self.v_cool, self.v_dur, self.v_until):
            v.trace_add("write", lambda *_: on_change())

    def add_metric(self, k: str, expr: str, silent: bool = False) -> None:
        rf = tk.Frame(self.metrics_frame, bg=BG_CARD)
        rf.pack(fill="x", pady=1)
        vk = tk.StringVar(value=k)
        ve = tk.StringVar(value=expr)
        make_entry(rf, vk, width=16, mono=True).pack(side="left", padx=(0, 4))
        make_label(rf, "=").pack(side="left")
        make_entry(rf, ve, width=40, mono=True).pack(side="left", fill="x", expand=True, padx=4)
        item = (rf, vk, ve)
        self.metric_rows.append(item)

        def _del() -> None:
            rf.destroy()
            self.metric_rows.remove(item)
            self.on_change()

        make_btn(rf, "✕", _del, bg="#3a2028", padx=5).pack(side="right")
        vk.trace_add("write", lambda *_: self.on_change())
        ve.trace_add("write", lambda *_: self.on_change())
        if not silent:
            self.on_change()

    def dump(self, target: dict[str, Any]) -> None:
        if self.v_mode.get().strip():
            target["mode"] = self.v_mode.get().strip()
        if self.v_fmetric.get().strip():
            target["focus_metric"] = self.v_fmetric.get().strip()
        trig: dict[str, Any] = {}
        if self.v_where.get().strip():
            trig["where"] = self.v_where.get().strip()
        if self.v_trans.get().strip():
            trig["transition"] = self.v_trans.get().strip()
        trig["cooldown_sec"] = num_val(self.v_cool.get(), 1.5)
        target["trigger"] = trig

        win: dict[str, Any] = {"duration_sec": num_val(self.v_dur.get(), 1.0)}
        if self.v_until.get().strip():
            win["until"] = self.v_until.get().strip()
        metrics = {vk.get().strip(): ve.get().strip() for _, vk, ve in self.metric_rows if vk.get().strip()}
        if metrics:
            win["metrics"] = metrics
        target["window"] = win


class CompareModesBlock(CBlock):
    def __init__(self, parent: tk.Widget, rule: dict[str, Any], sensors: list[str], on_change: Callable[[], None], on_delete: Callable[[], None]) -> None:
        super().__init__(parent, "СРАВНЕНИЕ РЕЖИМОВ (compare_modes)", CLR_COMPARE, on_delete=on_delete)
        self.sensors = sensors
        self.on_change = on_change
        self.v_req = tk.StringVar(value="true" if rule.get("require_all") else "false")
        self.v_min = tk.StringVar(value=str(rule.get("min_samples", 5)))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "require_all:").pack(side="left")
        make_combo(r1, self.v_req, ["false", "true"], width=8).pack(side="left", padx=(4, 10))
        make_label(r1, "min_samples:").pack(side="left")
        make_entry(r1, self.v_min, width=6, mono=True).pack(side="left", padx=4)

        self.inputs_frame = tk.Frame(self.body, bg=BG_CARD)
        self.inputs_frame.pack(fill="x", pady=(4, 0))
        self.input_rows: list[dict[str, Any]] = []

        self.comp_frame = tk.Frame(self.body, bg=BG_CARD)
        self.comp_frame.pack(fill="x", pady=(4, 0))
        self.comp_rows: list[tuple[tk.Frame, tk.StringVar, tk.StringVar]] = []

        bar = tk.Frame(self.body, bg=BG_CARD)
        bar.pack(fill="x", pady=(4, 0))
        make_btn(bar, "+ Вход (inputs)", lambda: self.add_input("med_idle", {"mode": "running", "param": "FR", "agg": "median"})).pack(side="left", padx=(0, 6))
        make_btn(bar, "+ Формула (compute)", lambda: self.add_compute("diff", "0")).pack(side="left")

        for k, spec in (rule.get("inputs") or {}).items():
            if isinstance(spec, dict):
                self.add_input(str(k), spec, silent=True)
        for k, expr in (rule.get("compute") or {}).items():
            self.add_compute(str(k), str(expr), silent=True)

        self.v_req.trace_add("write", lambda *_: on_change())
        self.v_min.trace_add("write", lambda *_: on_change())

    def add_input(self, name: str, spec: dict[str, Any], silent: bool = False) -> None:
        rf = tk.Frame(self.inputs_frame, bg=BG_CARD)
        rf.pack(fill="x", pady=1)
        vn = tk.StringVar(value=name)
        vm = tk.StringVar(value=str(spec.get("mode", "running")))
        vp = tk.StringVar(value=str(spec.get("param", "FR")))
        va = tk.StringVar(value=str(spec.get("agg", "median")))
        vms = tk.StringVar(value=str(spec.get("min_samples", "")))
        vw = tk.StringVar(value=str(spec.get("where", "")))

        make_entry(rf, vn, width=12, mono=True).pack(side="left", padx=(0, 3))
        make_combo(rf, vm, MODES_LIST, width=8).pack(side="left", padx=2)
        make_combo(rf, vp, self.sensors, width=11).pack(side="left", padx=2)
        make_combo(rf, va, AGGS_LIST, width=8).pack(side="left", padx=2)
        make_entry(rf, vms, width=4, mono=True).pack(side="left", padx=2)
        make_entry(rf, vw, width=22, mono=True).pack(side="left", fill="x", expand=True, padx=3)

        item = {"f": rf, "n": vn, "m": vm, "p": vp, "a": va, "ms": vms, "w": vw}
        self.input_rows.append(item)

        def _del() -> None:
            rf.destroy()
            self.input_rows.remove(item)
            self.on_change()

        make_btn(rf, "✕", _del, bg="#3a2028", padx=5).pack(side="right")
        for v in (vn, vm, vp, va, vms, vw):
            v.trace_add("write", lambda *_: self.on_change())
        if not silent:
            self.on_change()

    def add_compute(self, name: str, expr: str, silent: bool = False) -> None:
        rf = tk.Frame(self.comp_frame, bg=BG_CARD)
        rf.pack(fill="x", pady=1)
        vn = tk.StringVar(value=name)
        ve = tk.StringVar(value=expr)
        make_entry(rf, vn, width=14, mono=True).pack(side="left", padx=(0, 4))
        make_label(rf, "=").pack(side="left")
        make_entry(rf, ve, width=40, mono=True).pack(side="left", fill="x", expand=True, padx=4)
        item = (rf, vn, ve)
        self.comp_rows.append(item)

        def _del() -> None:
            rf.destroy()
            self.comp_rows.remove(item)
            self.on_change()

        make_btn(rf, "✕", _del, bg="#3a2028", padx=5).pack(side="right")
        vn.trace_add("write", lambda *_: self.on_change())
        ve.trace_add("write", lambda *_: self.on_change())
        if not silent:
            self.on_change()

    def dump(self, target: dict[str, Any]) -> None:
        target["require_all"] = self.v_req.get().strip().lower() == "true"
        ms = self.v_min.get().strip()
        if ms.isdigit() and int(ms) > 0:
            target["min_samples"] = int(ms)
        inputs: dict[str, Any] = {}
        for r in self.input_rows:
            k = r["n"].get().strip()
            if not k:
                continue
            spec: dict[str, Any] = {
                "mode": r["m"].get().strip() or "running",
                "param": r["p"].get().strip(),
                "agg": r["a"].get().strip() or "median",
            }
            ims = r["ms"].get().strip()
            if ims.isdigit() and int(ims) > 0:
                spec["min_samples"] = int(ims)
            if r["w"].get().strip():
                spec["where"] = r["w"].get().strip()
            inputs[k] = spec
        if inputs:
            target["inputs"] = inputs
        comp = {vn.get().strip(): ve.get().strip() for _, vn, ve in self.comp_rows if vn.get().strip()}
        if comp:
            target["compute"] = comp


class OscillationBlock(CBlock):
    def __init__(self, parent: tk.Widget, rule: dict[str, Any], sensors: list[str], on_change: Callable[[], None], on_delete: Callable[[], None]) -> None:
        super().__init__(parent, "КОЛЕБАНИЯ ДАТЧИКА (oscillation)", CLR_SENSOR, on_delete=on_delete)
        self.v_mode = tk.StringVar(value=str(rule.get("mode", "running")))
        self.v_param = tk.StringVar(value=str(rule.get("param", "O2_1")))
        self.v_hi = tk.StringVar(value=str(rule.get("high_threshold", 0.55)))
        self.v_lo = tk.StringVar(value=str(rule.get("low_threshold", 0.35)))
        self.v_gap = tk.StringVar(value=str(rule.get("max_gap_sec", 2.5)))
        self.v_min = tk.StringVar(value=str(rule.get("min_samples", 20)))
        self.v_where = tk.StringVar(value=str(rule.get("where", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        make_label(r1, "mode:").pack(side="left")
        make_combo(r1, self.v_mode, MODES_LIST, width=10).pack(side="left", padx=(4, 8))
        make_label(r1, "param:").pack(side="left")
        make_combo(r1, self.v_param, sensors, width=12).pack(side="left", padx=(4, 8))
        make_label(r1, "where:").pack(side="left")
        make_entry(r1, self.v_where, width=26, mono=True).pack(side="left", fill="x", expand=True, padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        make_label(r2, "high_th:").pack(side="left")
        make_entry(r2, self.v_hi, width=7, mono=True).pack(side="left", padx=(4, 8))
        make_label(r2, "low_th:").pack(side="left")
        make_entry(r2, self.v_lo, width=7, mono=True).pack(side="left", padx=(4, 8))
        make_label(r2, "max_gap_sec:").pack(side="left")
        make_entry(r2, self.v_gap, width=7, mono=True).pack(side="left", padx=(4, 8))
        make_label(r2, "min_samples:").pack(side="left")
        make_entry(r2, self.v_min, width=6, mono=True).pack(side="left", padx=4)

        for v in (self.v_mode, self.v_param, self.v_hi, self.v_lo, self.v_gap, self.v_min, self.v_where):
            v.trace_add("write", lambda *_: on_change())

    def dump(self, target: dict[str, Any]) -> None:
        target["mode"] = self.v_mode.get().strip() or "running"
        if self.v_where.get().strip():
            target["where"] = self.v_where.get().strip()
        target["param"] = self.v_param.get().strip() or "O2_1"
        target["high_threshold"] = num_val(self.v_hi.get(), 0.55)
        target["low_threshold"] = num_val(self.v_lo.get(), 0.35)
        target["max_gap_sec"] = num_val(self.v_gap.get(), 2.5)
        ms = self.v_min.get().strip()
        if ms.isdigit() and int(ms) > 0:
            target["min_samples"] = int(ms)


class FallbackBlock(CBlock):
    """Блок if_empty или if_clean."""

    def __init__(self, parent: tk.Widget, kind: str, data: dict[str, Any], on_change: Callable[[], None], on_delete: Callable[[], None]) -> None:
        super().__init__(parent, f"ЗАГЛУШКА ({kind})", CLR_COMPARE, on_delete=on_delete)
        self.kind = kind
        self.v_status = tk.StringVar(value=str(data.get("status", "status-na")))
        self.v_badge = tk.StringVar(value=str(data.get("badge", "НЕТ ДАННЫХ")))
        self.v_val = tk.StringVar(value=str(data.get("val", "")))
        self.v_norm = tk.StringVar(value=str(data.get("norm", "")))
        self.v_tip = tk.StringVar(value=str(data.get("tip", "")))

        r1 = tk.Frame(self.body, bg=BG_CARD)
        r1.pack(fill="x", pady=2)
        if kind == "if_empty":
            make_label(r1, "status:").pack(side="left")
            make_combo(r1, self.v_status, STATUSES_LIST, width=12).pack(side="left", padx=(4, 8))
        make_label(r1, "badge:").pack(side="left")
        make_entry(r1, self.v_badge, width=18).pack(side="left", padx=(4, 8))
        make_label(r1, "val:").pack(side="left")
        make_entry(r1, self.v_val, width=28).pack(side="left", fill="x", expand=True, padx=4)

        r2 = tk.Frame(self.body, bg=BG_CARD)
        r2.pack(fill="x", pady=2)
        if kind == "if_clean":
            make_label(r2, "norm:").pack(side="left")
            make_entry(r2, self.v_norm, width=24).pack(side="left", padx=(4, 8))
        make_label(r2, "tip:").pack(side="left")
        make_entry(r2, self.v_tip, width=44).pack(side="left", fill="x", expand=True, padx=4)

        for v in (self.v_status, self.v_badge, self.v_val, self.v_norm, self.v_tip):
            v.trace_add("write", lambda *_: on_change())

    def dump(self, target: dict[str, Any]) -> None:
        out: dict[str, Any] = {}
        if self.kind == "if_empty":
            out["status"] = self.v_status.get().strip() or "status-na"
        if self.v_badge.get().strip():
            out["badge"] = self.v_badge.get().strip()
        if self.v_val.get().strip():
            out["val"] = self.v_val.get().strip()
        if self.kind == "if_clean" and self.v_norm.get().strip():
            out["norm"] = self.v_norm.get().strip()
        if self.v_tip.get().strip():
            out["tip"] = self.v_tip.get().strip()
        target[self.kind] = out
