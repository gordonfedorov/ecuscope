#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks.py — тонкий универсальный диспетчер диагностических проверок ECUScope.
Не содержит зашитых проверок, порогов или описаний: читает секции из YAML-файлов
в папке rules/ (или из единого профиля) и выполняет их в цикле.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any

import pyarrow as pa
import yaml

from yaml_rules_engine import run_yaml_rules

_BASE_DIR = Path(__file__).resolve().parent
_DEFAULT_RULES_DIR = _BASE_DIR / "rules"

_STATUS_MAP = {
    "status-ok": ("status-ok", "НОРМА"),
    "ok": ("status-ok", "НОРМА"),
    "good": ("status-ok", "НОРМА"),
    "status-warn": ("status-warn", "ВНИМАНИЕ"),
    "warn": ("status-warn", "ВНИМАНИЕ"),
    "warning": ("status-warn", "ВНИМАНИЕ"),
    "status-bad": ("status-bad", "ПРОБЛЕМА"),
    "bad": ("status-bad", "ПРОБЛЕМА"),
    "err": ("status-bad", "ПРОБЛЕМА"),
    "error": ("status-bad", "ПРОБЛЕМА"),
    "status-na": ("status-na", "НЕТ ДАННЫХ"),
    "na": ("status-na", "НЕТ ДАННЫХ"),
    "none": ("status-na", "НЕТ ДАННЫХ"),
}


def _normalize_card(raw: dict[str, Any]) -> dict[str, Any]:
    """Приводит карточку из YAML к единому контракту HTML-отчёта."""
    st_raw = str(raw.get("status") or "status-na").strip().lower()
    st_class, default_badge = _STATUS_MAP.get(st_raw, ("status-na", "НЕТ ДАННЫХ"))
    tooltip = raw.get("tooltip") or raw.get("detail") or raw.get("details") or raw.get("hint")
    card: dict[str, Any] = {
        "status": st_class,
        "title": str(raw.get("title") or raw.get("name") or "Проверка").strip(),
        "badge": str(raw.get("badge") or default_badge).strip(),
        "val": str(raw.get("val") or raw.get("value") or "—").strip(),
        "norm": str(raw.get("norm") or raw.get("sub") or "").strip(),
        "tooltip": str(tooltip).strip() if tooltip else "",
    }
    if raw.get("focus"):
        card["focus"] = raw["focus"]
    return card


def _read_order(yaml_path: Path) -> tuple[int, str]:
    """Возвращает (order, имя_файла) для детерминированной сортировки YAML-секций."""
    try:
        spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        return (int(spec.get("order", 50)), yaml_path.name)
    except Exception:
        return (50, yaml_path.name)


def _exec_yaml_file(
    yaml_path: Path,
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    prior_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Вызывает движок YAML для одного файла с передачей накопленных карточек."""
    sig = inspect.signature(run_yaml_rules)
    kwargs: dict[str, Any] = {}
    if "prior_cards" in sig.parameters:
        kwargs["prior_cards"] = prior_cards
    raw_cards = run_yaml_rules(yaml_path, table, valid_idx, run_idx, hot_idle_idx, **kwargs)
    return [_normalize_card(c) for c in raw_cards if isinstance(c, dict)]


def run_all_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    rules_dir: str | os.PathLike | None = None,
) -> list[dict[str, Any]]:
    """Загружает все *.yaml из каталога правил, сортирует по order и выполняет в цикле."""
    target = Path(rules_dir or os.environ.get("ECUSCOPE_RULES_DIR") or _DEFAULT_RULES_DIR)
    if not target.exists():
        raise FileNotFoundError(f"Каталог YAML-правил не найден: {target}")

    yaml_files = sorted(target.glob("*.yaml"), key=_read_order) if target.is_dir() else [target]
    results: list[dict[str, Any]] = []
    for yp in yaml_files:
        results.extend(_exec_yaml_file(yp, table, valid_idx, run_idx, hot_idle_idx, results))
    return results


def run_base_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    rules_dir: str | os.PathLike | None = None,
) -> list[dict[str, Any]]:
    """Выполняет базовую секцию (base_checks.yaml) для совместимости с diagnose.py."""
    target = Path(rules_dir or os.environ.get("ECUSCOPE_RULES_DIR") or _DEFAULT_RULES_DIR)
    base_file = target / "base_checks.yaml" if target.is_dir() else target
    if not base_file.exists():
        return []
    return _exec_yaml_file(base_file, table, valid_idx, run_idx, hot_idle_idx, [])


def run_extra_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    base_results: list[dict[str, Any]] | None = None,
    rules_dir: str | os.PathLike | None = None,
) -> list[dict[str, Any]]:
    """В цикле выполняет все остальные YAML-секции из rules/ по порядку order."""
    target = Path(rules_dir or os.environ.get("ECUSCOPE_RULES_DIR") or _DEFAULT_RULES_DIR)
    if not target.is_dir():
        return []

    accumulated = list(base_results or [])
    extra_results: list[dict[str, Any]] = []
    yaml_files = sorted(
        (p for p in target.glob("*.yaml") if p.name != "base_checks.yaml"),
        key=_read_order,
    )
    for yp in yaml_files:
        cards = _exec_yaml_file(yp, table, valid_idx, run_idx, hot_idle_idx, accumulated)
        extra_results.extend(cards)
        accumulated.extend(cards)
    return extra_results
