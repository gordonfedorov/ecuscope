#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui_backend.py — работа с rules/*.yaml, кэшем логов Parquet и живым тестом карточек ECUScope.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

from diagnose_utils import COL, col_vals
from yaml_expr import SafeExprEvaluator
from yaml_rules_engine import evaluate_rule

BASE_DIR = Path(__file__).resolve().parent
RULES_DIR = BASE_DIR / "rules"
LOGS_DIR = BASE_DIR / "logs"

_TABLE_CACHE: dict[str, tuple[Any, dict[str, list[int]]]] = {}


def compute_modes(table: Any) -> dict[str, list[int]]:
    n = table.num_rows
    rpm = col_vals(table, COL["RPM"])
    ect = col_vals(table, COL["ECT"])
    spd = col_vals(table, COL["SPD"])
    tps = col_vals(table, COL["TPS"])

    valid_idx, run_idx, hot_idle_idx = [], [], []
    for i in range(n):
        r = rpm[i] if i < len(rpm) else None
        e = ect[i] if i < len(ect) else None
        s = spd[i] if i < len(spd) else None
        tp = tps[i] if i < len(tps) else None
        if r is None and e is None:
            continue
        valid_idx.append(i)
        if r is not None and r >= 550.0:
            run_idx.append(i)
            if (
                e is not None and e >= 75.0
                and 650.0 <= r <= 1050.0
                and (s is None or s < 2.0)
                and (tp is None or tp <= 1.5)
            ):
                hot_idle_idx.append(i)
    return {"valid": valid_idx, "running": run_idx, "hot_idle": hot_idle_idx}


def list_yaml_files() -> list[str]:
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    return [f.name for f in sorted(RULES_DIR.glob("*.yaml"))]


def list_log_files() -> list[str]:
    if not LOGS_DIR.exists():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for ext in ("*.parquet", "*.log", "*.txt"):
        for f in sorted(LOGS_DIR.glob(ext)):
            if f.stem not in seen:
                seen.add(f.stem)
                out.append(f"logs/{f.name}")
    return out


def collect_all_sensors() -> list[str]:
    extra = {
        "RPM", "ECT", "VBAT", "MAF", "MAP", "TPS", "INJ", "INJ_DUTY", "FUEL",
        "IGN", "IAC", "IAC_ADAPT", "FR", "FRA", "RKAT", "O2_1", "O2_2", "O2_FB1",
        "PURGE", "PURGE_FLAG", "KNOCK_RETARD", "KNOCK_V", "LOAD", "SPD",
        "MIS_CYL_1", "MIS_CYL_2", "MIS_CYL_3", "MIS_CYL_4", "MIS_SUM", "CAT_AMP_IDX", "ERR", "FAN1"
    }
    return sorted(set(COL.keys()) | extra)


def collect_all_tags() -> list[str]:
    tags: set[str] = set()
    if not RULES_DIR.exists():
        return []
    for yf in sorted(RULES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        checks = list(data.get("checks") or [])
        for sec in data.get("sections") or []:
            if isinstance(sec, dict):
                checks.extend(sec.get("checks") or [])
        for chk in checks:
            if not isinstance(chk, dict):
                continue
            tags.update(str(t) for t in (chk.get("tags") or []))
            for br in chk.get("rules") or []:
                if isinstance(br, dict):
                    tags.update(str(t) for t in (br.get("tags") or []))
            for dg in chk.get("diagnoses") or []:
                if isinstance(dg, dict):
                    for k in ("all_tags", "any_tags", "none_tags"):
                        tags.update(str(t) for t in (dg.get(k) or []))
    return sorted(tags)


def load_yaml_file(name: str) -> dict[str, Any]:
    target = (RULES_DIR / name).resolve()
    if target.parent != RULES_DIR.resolve() or not target.exists():
        raise FileNotFoundError(f"Файл не найден: {name}")
    data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Корневой элемент YAML должен быть словарём")
    return data


def dump_yaml_text(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def save_yaml_file(name: str, data: dict[str, Any]) -> str:
    if not name.endswith(".yaml"):
        name += ".yaml"
    target = (RULES_DIR / name).resolve()
    if target.parent != RULES_DIR.resolve():
        raise ValueError("Недопустимое имя файла")
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(".yaml.bak"))
    target.write_text(dump_yaml_text(data), encoding="utf-8")
    return name


def test_rule_on_log(rule: dict[str, Any], rel_log_path: str) -> tuple[dict[str, Any] | None, float]:
    target = (BASE_DIR / rel_log_path).resolve()
    if not str(target).startswith(str(BASE_DIR)) or not target.exists():
        raise FileNotFoundError(f"Лог не найден: {rel_log_path}")

    pq_path = target if target.suffix.lower() == ".parquet" else target.with_suffix(".parquet")
    if not pq_path.exists():
        from parser import parse_log_to_parquet
        parse_log_to_parquet(target, pq_path)

    key = f"{pq_path}:{pq_path.stat().st_mtime}"
    if key not in _TABLE_CACHE:
        table = pq.read_table(pq_path)
        _TABLE_CACHE.clear()
        _TABLE_CACHE[key] = (table, compute_modes(table))

    table, modes = _TABLE_CACHE[key]
    t0 = time.perf_counter()
    evaluator = SafeExprEvaluator(table, modes)
    card = evaluate_rule(rule, table, modes, evaluator, {}, [])
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return card, elapsed_ms
