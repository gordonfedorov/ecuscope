#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yaml_rules_engine.py — декларативный движок выполнения YAML-правил ECUScope.
Поддерживает 5 типовых диагностических шаблонов без Python-кода в YAML:
  1. threshold      — агрегация по режиму (или AST-выражение) + ветки правил / пороги ok/warn.
  2. compare_modes  — сравнение метрик между двумя режимами работы мотора.
  3. event_window   — поиск события/перехода и замер реакции датчиков в окне времени.
  4. oscillation    — анализ циклов, размаха и периода колебаний сигнала.
  5. cross_diagnosis — сводный перекрёстный диагноз по тегам сработавших карточек.
Также сохраняет обратную совместимость с legacy-блоками script: и handler:.
"""

from __future__ import annotations

import math
import re
import statistics
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa

try:
    import yaml
except ImportError as exc:
    yaml = None  # type: ignore[assignment]
    _YAML_IMPORT_ERR = exc
else:
    _YAML_IMPORT_ERR = None

from diagnose_utils import COL, make_card, sub
from yaml_expr import SafeExprEvaluator, agg_values, format_template

_STATUS_CLASS_MAP = {
    "ok": "status-ok",
    "status-ok": "status-ok",
    "warn": "status-warn",
    "status-warn": "status-warn",
    "bad": "status-bad",
    "status-bad": "status-bad",
    "na": "status-na",
    "status-na": "status-na",
}

_DEFAULT_BADGE_MAP = {
    "status-ok": "НОРМА",
    "status-warn": "ВНИМАНИЕ",
    "status-bad": "ПРОБЛЕМА",
    "status-na": "НЕТ ДАННЫХ",
}


def _norm_status(raw: str | None) -> str:
    return _STATUS_CLASS_MAP.get(str(raw or "status-na").strip().lower(), "status-na")


def _build_card_from_branch(
    rule: dict,
    branch: dict,
    evaluator: SafeExprEvaluator,
    env: dict[str, Any],
    lfuncs: dict[str, Callable[..., Any]],
    focus_t: float | None = None,
) -> dict[str, Any]:
    title = rule["title"]
    norm_tpl = branch.get("norm", rule.get("norm", ""))
    norm = format_template(str(norm_tpl), evaluator, env, lfuncs)

    st = _norm_status(branch.get("status", "status-ok"))
    badges = rule.get("badges", {})
    default_badge = badges.get(st.replace("status-", ""), _DEFAULT_BADGE_MAP.get(st, "ИНФО"))
    badge_tpl = branch.get("badge", default_badge)
    badge = format_template(str(badge_tpl), evaluator, env, lfuncs)

    val_tpl = (
        branch.get("val")
        or branch.get("value")
        or branch.get("val_fmt")
        or rule.get("val")
        or rule.get("value")
        or rule.get("val_fmt")
        or "—"
    )
    val = format_template(str(val_tpl), evaluator, env, lfuncs)

    tip_tpl = branch.get("tip", branch.get("tooltip", rule.get("tooltip", "")))
    tooltip = format_template(str(tip_tpl), evaluator, env, lfuncs) if tip_tpl else ""

    card = make_card(title, val, norm, status=st, badge=badge, tooltip=tooltip)

    tags = list(rule.get("tags", [])) + list(branch.get("tags", []))
    if tags:
        card["tags"] = list(dict.fromkeys(str(t) for t in tags))

    focus_traces = branch.get("focus_traces") or rule.get("focus_traces")
    if focus_traces:
        resolved_traces = [COL.get(str(k), str(k)) for k in focus_traces]
        focus_obj: dict[str, Any] = {"traces": resolved_traces}
        if focus_t is not None and math.isfinite(focus_t):
            pad_before = float(rule.get("focus_pad_before", 8.0))
            pad_after = float(rule.get("focus_pad_after", 12.0))
            focus_obj["range"] = [max(0.0, round(focus_t - pad_before, 2)), round(focus_t + pad_after, 2)]
            focus_obj["marker"] = round(focus_t, 2)
        card["focus"] = focus_obj

    return card


def _eval_branches(
    rule: dict,
    evaluator: SafeExprEvaluator,
    env: dict[str, Any],
    lfuncs: dict[str, Callable[..., Any]],
    focus_t: float | None = None,
) -> dict[str, Any] | None:
    branches = rule.get("rules", [])
    for br in branches:
        if "default" in br or br.get("when") in (None, True, "default", "else"):
            return _build_card_from_branch(rule, br, evaluator, env, lfuncs, focus_t)
        cond = evaluator.eval(str(br["when"]), env, lfuncs)
        if bool(cond):
            return _build_card_from_branch(rule, br, evaluator, env, lfuncs, focus_t)
    return None


def _make_empty_card(rule: dict, evaluator: SafeExprEvaluator, env: dict[str, Any]) -> dict[str, Any] | None:
    emp = rule.get("if_empty")
    if not emp:
        return None
    if isinstance(emp, str):
        emp = {"val": emp, "status": "status-na"}
    return _build_card_from_branch(rule, emp, evaluator, env, {})


def _set_mode_safe(evaluator: SafeExprEvaluator, mode_name: str) -> None:
    if hasattr(evaluator, "set_active_mode"):
        evaluator.set_active_mode(mode_name)
    elif hasattr(evaluator, "active_mode"):
        evaluator.active_mode = mode_name


# ---------------------------------------------------------------------------
# 1. Шаблон threshold (и expr)
# ---------------------------------------------------------------------------

def _eval_threshold(rule: dict, modes: dict[str, list[int]], evaluator: SafeExprEvaluator) -> dict[str, Any] | None:
    mode_name = rule.get("mode", "valid")
    _set_mode_safe(evaluator, mode_name)

    env: dict[str, Any] = {}
    vals: list[float] = []

    for m_name, m_expr in (rule.get("metrics") or {}).items():
        env[m_name] = evaluator.eval(str(m_expr), env)

    if "expr" in rule:
        val = evaluator.eval(str(rule["expr"]), env)
        env["val"] = val
        env.setdefault("v", val)
        env.setdefault("med", val)
        env.setdefault("value", val)
    elif "param" in rule:
        idx = modes.get(mode_name, [])
        raw_vals = sub(evaluator.get_col(str(rule["param"])), idx)
        vals = [float(v) for v in raw_vals if v is not None]
        if len(vals) < int(rule.get("min_samples", 1)):
            return _make_empty_card(rule, evaluator, env)
        val = agg_values(vals, rule.get("agg", "median"))
        env["val"] = val
        env.setdefault("v", val)
        env.setdefault("med", val)
        env.setdefault("value", val)
        env["min"] = min(vals)
        env["max"] = max(vals)
        env["count"] = len(vals)
    else:
        val = env.get("val")

    if "rules" in rule:
        if val is None and "param" in rule and not vals:
            return _make_empty_card(rule, evaluator, env)
        return _eval_branches(rule, evaluator, env, {})

    if val is None:
        return _make_empty_card(rule, evaluator, env)

    ok_lo, ok_hi = rule["ok"]
    warn_lo, warn_hi = rule.get("warn", (ok_lo, ok_hi))
    badges = rule.get("badges", {})

    if ok_lo <= val <= ok_hi:
        st, badge = "status-ok", badges.get("ok", "НОРМА")
    elif warn_lo <= val <= warn_hi:
        st = "status-warn"
        badge = badges.get("warn_low", badges.get("warn", "ОТКЛОНЕНИЕ")) if val < ok_lo else badges.get("warn_high", badges.get("warn", "ОТКЛОНЕНИЕ"))
    else:
        st = "status-bad"
        badge = badges.get("bad_low", badges.get("bad", "ВНЕ НОРМЫ")) if val < ok_lo else badges.get("bad_high", badges.get("bad", "ВНЕ НОРМЫ"))

    branch = {
        "status": st,
        "badge": badge,
        "val": rule.get("val_fmt", "{val:.2f}"),
        "tip": rule.get("tooltip", ""),
    }
    return _build_card_from_branch(rule, branch, evaluator, env, {})


# ---------------------------------------------------------------------------
# 2. Шаблон compare_modes
# ---------------------------------------------------------------------------

def _eval_compare_modes(rule: dict, modes: dict[str, list[int]], evaluator: SafeExprEvaluator) -> dict[str, Any] | None:
    _set_mode_safe(evaluator, rule.get("mode", "valid"))
    env: dict[str, Any] = {}
    min_samples = int(rule.get("min_samples", 1))

    for var_name, spec in (rule.get("inputs") or {}).items():
        if isinstance(spec, str):
            env[var_name] = evaluator.eval(spec, env)
            continue
        mode_name = spec.get("mode", "valid")
        idx = modes.get(mode_name, [])
        if spec.get("where"):
            where_s = str(spec["where"])
            idx = [i for i in idx if bool(evaluator.eval(where_s, _row_env(evaluator, i)))]
        raw_vals = sub(evaluator.get_col(str(spec["param"])), idx)
        nums = [float(v) for v in raw_vals if v is not None]
        env[f"{var_name}_count"] = len(nums)
        if len(nums) < int(spec.get("min_samples", min_samples)):
            env[var_name] = None
        else:
            env[var_name] = agg_values(nums, spec.get("agg", "median"))

    for c_name, c_expr in (rule.get("compute") or {}).items():
        env[c_name] = evaluator.eval(str(c_expr), env)

    if rule.get("require_all", True):
        for var_name in (rule.get("inputs") or {}):
            if env.get(var_name) is None:
                return _make_empty_card(rule, evaluator, env)

    return _eval_branches(rule, evaluator, env, {})


# ---------------------------------------------------------------------------
# 3. Шаблон event_window
# ---------------------------------------------------------------------------

_TRANS_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*->\s*(.+?)\s*$")


def _row_env(evaluator: SafeExprEvaluator, idx: int) -> dict[str, Any]:
    env: dict[str, Any] = {}
    for k in COL:
        arr = evaluator.get_col(k)
        env[k] = arr[idx] if idx < len(arr) else None
    return env


def _eval_event_window(rule: dict, modes: dict[str, list[int]], evaluator: SafeExprEvaluator) -> dict[str, Any] | None:
    pool_mode = rule.get("mode", "valid")
    _set_mode_safe(evaluator, pool_mode)
    pool = modes.get(pool_mode, [])
    if len(pool) < 2:
        return _make_empty_card(rule, evaluator, {"total_events": 0})

    times_all = evaluator.get_col("TIME")
    trig = rule.get("trigger") or {}
    where_expr = trig.get("where")
    cooldown = float(trig.get("cooldown_sec", 0.0))

    trans_param: str | None = None
    trans_from_expr: str | None = None
    trans_to_expr: str | None = None
    if trig.get("transition"):
        m = _TRANS_RE.match(str(trig["transition"]))
        if not m:
            raise ValueError(f"Некорректный формат transition: {trig['transition']}")
        trans_param, from_cond, to_cond = m.group(1), m.group(2), m.group(3)
        trans_from_expr = f"val {from_cond}" if from_cond[0] in "<>=!" else from_cond
        trans_to_expr = f"val {to_cond}" if to_cond[0] in "<>=!" else to_cond

    win_cfg = rule.get("window") or {}
    win_dur = float(win_cfg.get("duration_sec", 1.5))
    until_expr = win_cfg.get("until")
    metrics_cfg = win_cfg.get("metrics") or {}

    events: list[dict[str, Any]] = []
    last_ev_t = -1e9

    for pos in range(len(pool)):
        i1 = pool[pos]
        t1 = float(times_all[i1]) if (i1 < len(times_all) and times_all[i1] is not None) else float(pos)
        if (t1 - last_ev_t) < cooldown:
            continue

        r1 = _row_env(evaluator, i1)
        r1["t"] = t1

        if trans_param is not None:
            if pos == 0:
                continue
            i0 = pool[pos - 1]
            t0 = float(times_all[i0]) if (i0 < len(times_all) and times_all[i0] is not None) else float(pos - 1)
            if (t1 - t0) > float(trig.get("max_step_sec", 1.5)):
                continue
            arr = evaluator.get_col(trans_param)
            v0 = arr[i0] if i0 < len(arr) else None
            v1 = arr[i1] if i1 < len(arr) else None
            if v0 is None or v1 is None:
                continue
            if not bool(evaluator.eval(trans_from_expr, {"val": v0})):
                continue
            if not bool(evaluator.eval(trans_to_expr, {"val": v1})):
                continue

        if where_expr and not bool(evaluator.eval(str(where_expr), r1)):
            continue

        win_indices: list[int] = []
        for p2 in range(pos, len(pool)):
            j = pool[p2]
            tj = float(times_all[j]) if (j < len(times_all) and times_all[j] is not None) else float(p2)
            if (tj - t1) > win_dur:
                break
            rj = _row_env(evaluator, j)
            rj["t"] = tj
            if p2 > pos and until_expr and bool(evaluator.eval(str(until_expr), rj)):
                break
            win_indices.append(j)

        if len(win_indices) < int(win_cfg.get("min_frames", 1)):
            continue

        last_ev_t = t1
        r_end = _row_env(evaluator, win_indices[-1])
        win_env: dict[str, Any] = {"t": t1, "duration": 0.0}
        t_end = float(times_all[win_indices[-1]]) if times_all[win_indices[-1]] is not None else t1
        win_env["duration"] = max(0.0, t_end - t1)

        for k in COL:
            arr = evaluator.get_col(k)
            win_env[k] = [arr[j] for j in win_indices if j < len(arr)]
            win_env[f"{k}_start"] = r1.get(k)
            win_env[f"{k}_end"] = r_end.get(k)

        ev_record: dict[str, Any] = {"t": t1, "duration": win_env["duration"]}
        for m_name, m_expr in metrics_cfg.items():
            val_m = evaluator.eval(str(m_expr), win_env)
            win_env[m_name] = val_m
            ev_record[m_name] = val_m
        events.append(ev_record)

    if not events:
        return _make_empty_card(rule, evaluator, {"total_events": 0})

    def _ev_filter(cond_str: Any) -> list[dict[str, Any]]:
        if isinstance(cond_str, list):
            return [ev for ev, flag in zip(events, cond_str) if flag]
        return [ev for ev in events if bool(evaluator.eval(str(cond_str), ev))]

    def _ev_count(cond_str: Any = True) -> int:
        if cond_str is True:
            return len(events)
        return len(_ev_filter(cond_str))

    def _ev_agg(agg_name: str, metric_name: Any) -> float | None:
        if isinstance(metric_name, list):
            return agg_values(metric_name, agg_name)
        vals = [ev.get(str(metric_name)) for ev in events if ev.get(str(metric_name)) is not None]
        return agg_values(vals, agg_name)

    def _ev_times(cond_str: Any = True, limit: int = 5) -> str:
        matched = _ev_filter(cond_str)
        if not matched:
            return "—"
        parts = [f"{ev['t']:.1f}с" for ev in matched[:limit]]
        if len(matched) > limit:
            parts.append(f"и ещё {len(matched) - limit}")
        return ", ".join(parts)

    lfuncs: dict[str, Callable[..., Any]] = {
        "count": _ev_count,
        "max": lambda m: _ev_agg("max", m),
        "min": lambda m: _ev_agg("min", m),
        "mean": lambda m: _ev_agg("mean", m),
        "median": lambda m: _ev_agg("median", m),
        "sum": lambda m: _ev_agg("sum", m),
        "times": _ev_times,
    }

    env: dict[str, Any] = {"total_events": len(events), "first_t": events[0]["t"]}
    for m_name in metrics_cfg:
        env[m_name] = [ev.get(m_name) for ev in events]

    focus_t: float | None = events[0]["t"]
    focus_metric = rule.get("focus_metric")
    if focus_metric:
        scored = [(ev.get(focus_metric), ev["t"]) for ev in events if ev.get(focus_metric) is not None]
        if scored:
            focus_t = max(scored, key=lambda x: float(x[0]))[1]

    return _eval_branches(rule, evaluator, env, lfuncs, focus_t=focus_t)


# ---------------------------------------------------------------------------
# 4. Шаблон oscillation
# ---------------------------------------------------------------------------

def _eval_oscillation(rule: dict, modes: dict[str, list[int]], evaluator: SafeExprEvaluator) -> dict[str, Any] | None:
    mode_name = rule.get("mode", "valid")
    _set_mode_safe(evaluator, mode_name)
    idx = modes.get(mode_name, [])
    if rule.get("where"):
        where_s = str(rule["where"])
        idx = [i for i in idx if bool(evaluator.eval(where_s, _row_env(evaluator, i)))]

    param = str(rule["param"])
    vals_arr = evaluator.get_col(param)
    times_arr = evaluator.get_col("TIME")
    vals = [float(vals_arr[i]) for i in idx if i < len(vals_arr) and vals_arr[i] is not None]

    if len(vals) < int(rule.get("min_samples", 10)):
        return _make_empty_card(rule, evaluator, {"count": len(vals)})

    high_thr = float(rule.get("high_threshold", 0.55))
    low_thr = float(rule.get("low_threshold", 0.35))
    max_gap = float(rule.get("max_gap_sec", 2.5))

    crossings_t: list[float] = []
    prev_above: bool | None = None
    prev_t: float | None = None

    for pos, i in enumerate(idx):
        v = vals_arr[i] if i < len(vals_arr) else None
        t = float(times_arr[i]) if (i < len(times_arr) and times_arr[i] is not None) else float(pos)
        if v is None:
            continue
        if prev_t is not None and (t - prev_t) > max_gap:
            prev_above = None
        if v >= high_thr:
            cur_above = True
        elif v <= low_thr:
            cur_above = False
        else:
            prev_t = t
            continue
        if prev_above is not None and cur_above != prev_above:
            crossings_t.append(t)
        prev_above = cur_above
        prev_t = t

    half_periods = [
        crossings_t[k] - crossings_t[k - 1]
        for k in range(1, len(crossings_t))
        if 0.08 <= (crossings_t[k] - crossings_t[k - 1]) <= 6.0
    ]
    period_med = (float(statistics.median(half_periods)) * 2.0) if len(half_periods) >= 4 else None

    env: dict[str, Any] = {
        "min": min(vals),
        "max": max(vals),
        "median": float(statistics.median(vals)),
        "swing": max(vals) - min(vals),
        "p10_p90": agg_values(vals, "p10_p90"),
        "cycles": len(crossings_t) // 2,
        "period": period_med,
        "count": len(vals),
    }
    focus_t = crossings_t[0] if crossings_t else None
    return _eval_branches(rule, evaluator, env, {}, focus_t=focus_t)


# ---------------------------------------------------------------------------
# 5. Шаблон cross_diagnosis
# ---------------------------------------------------------------------------

def _eval_cross_diagnosis(rule: dict, prior_cards: list[dict[str, Any]], evaluator: SafeExprEvaluator) -> dict[str, Any]:
    issues = [c for c in prior_cards if c.get("status") in ("status-warn", "status-bad")]
    active_tags: set[str] = set()
    tag_focus: dict[str, dict[str, Any]] = {}

    for c in issues:
        for t in c.get("tags", []):
            active_tags.add(str(t))
            if str(t) not in tag_focus and c.get("focus"):
                tag_focus[str(t)] = c["focus"]

    matched: list[dict[str, Any]] = []
    for diag in rule.get("diagnoses", []):
        req_all = set(diag.get("all_tags", []))
        req_any = set(diag.get("any_tags", []))
        forbid = set(diag.get("none_tags", []))
        if req_all and not req_all.issubset(active_tags):
            continue
        if req_any and not (req_any & active_tags):
            continue
        if forbid and (forbid & active_tags):
            continue
        matched.append(diag)

    if not matched:
        if not issues:
            ok_cfg = rule.get("if_clean", {})
            return make_card(
                rule["title"],
                ok_cfg.get("val", "Противоречий нет"),
                ok_cfg.get("norm", "Все связки датчиков и систем согласованы"),
                status="status-ok",
                badge=ok_cfg.get("badge", "НОРМА"),
                tooltip=ok_cfg.get("tip", ""),
            )
        worst = "status-bad" if any(c.get("status") == "status-bad" for c in issues) else "status-warn"
        titles = ", ".join(c.get("title", "") for c in issues[:3])
        return make_card(
            rule["title"],
            f"Локальных отклонений: {len(issues)}",
            f"Проверьте: {titles}",
            status=worst,
            badge="ПРОБЛЕМА" if worst == "status-bad" else "ВНИМАНИЕ",
            tooltip="Системных конфликтов между узлами не выявлено, но есть локальные отклонения по отдельным карточкам.",
        )

    worst_st = "status-bad" if any(_norm_status(d.get("status")) == "status-bad" for d in matched) else "status-warn"
    primary = matched[0]
    extra = len(matched) - 1
    norm_txt = (
        f"Также выявлено: {matched[1]['title']}" + (f" (+{extra - 1})" if extra > 1 else "")
        if extra > 0
        else primary.get("norm", "Вероятная первопричина по совокупности улик")
    )
    tip_lines = [f"• {d['title']}: {d.get('tip', '')}" for d in matched]
    card = make_card(
        rule["title"],
        primary["title"],
        norm_txt,
        status=worst_st,
        badge="ПРОБЛЕМА" if worst_st == "status-bad" else "ВНИМАНИЕ",
        tooltip="\n".join(tip_lines),
    )
    for t in list(primary.get("all_tags", [])) + list(primary.get("any_tags", [])):
        if t in tag_focus:
            card["focus"] = tag_focus[t]
            break
    return card


# ---------------------------------------------------------------------------
# Совместимость со старыми script-блоками (до завершения перевода всех YAML)
# ---------------------------------------------------------------------------

def _run_legacy_script(
    script_src: str,
    rule: dict,
    table: pa.Table,
    modes: dict[str, list[int]],
    evaluator: SafeExprEvaluator,
    prior_cards: list[dict[str, Any]],
) -> dict[str, Any] | None:
    safe_builtins = {
        "None": None, "True": True, "False": False,
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "float": float, "int": int, "len": len,
        "list": list, "max": max, "min": min, "range": range, "round": round,
        "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    }
    sandbox: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "title": rule.get("title", ""),
        "norm": rule.get("norm", ""),
        "params": rule.get("params", {}),
        "table": table,
        "modes": modes,
        "valid_idx": modes.get("valid", []),
        "run_idx": modes.get("running", []),
        "hot_idle_idx": modes.get("hot_idle", []),
        "prior_cards": prior_cards,
        "all_checks": prior_cards,
        "col": evaluator.get_col,
        "sub": sub,
        "median": statistics.median,
        "mean": statistics.mean,
        "math": math,
        "make_card": make_card,
        "card": None,
    }
    exec(compile(script_src, f"<yaml:{rule.get('id', 'rule')}>", "exec"), sandbox, sandbox)
    return sandbox.get("card")


# ---------------------------------------------------------------------------
# Главная точка входа выполнения YAML-правил
# ---------------------------------------------------------------------------

def evaluate_rule(
    rule: dict,
    table: pa.Table,
    modes: dict[str, list[int]],
    evaluator: SafeExprEvaluator,
    handlers: dict[str, Callable[..., dict | None]],
    prior_cards: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if "handler" in rule:
        fn = handlers.get(rule["handler"])
        if fn is None:
            raise KeyError(f"Не зарегистрирован обработчик YAML: {rule['handler']}")
        return fn(table, modes, rule)

    if "script" in rule:
        return _run_legacy_script(rule["script"], rule, table, modes, evaluator, prior_cards)

    rtype = str(rule.get("type", "threshold")).strip().lower()
    if rtype == "threshold":
        return _eval_threshold(rule, modes, evaluator)
    if rtype == "compare_modes":
        return _eval_compare_modes(rule, modes, evaluator)
    if rtype == "event_window":
        return _eval_event_window(rule, modes, evaluator)
    if rtype == "oscillation":
        return _eval_oscillation(rule, modes, evaluator)
    if rtype == "cross_diagnosis":
        return _eval_cross_diagnosis(rule, prior_cards, evaluator)
    raise ValueError(f"Неизвестный тип правила YAML: {rtype}")


def run_yaml_rules(
    yaml_path: str | Path,
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    handlers: dict[str, Callable[..., dict | None]] | None = None,
    prior_cards: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if yaml is None:
        raise RuntimeError(
            f"Для работы YAML-профилей требуется пакет PyYAML (pip install pyyaml). Ошибка импорта: {_YAML_IMPORT_ERR}"
        )

    path = Path(yaml_path)
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    modes: dict[str, list[int]] = {
        "valid": valid_idx,
        "running": run_idx,
        "hot_idle": hot_idle_idx,
    }
    evaluator = SafeExprEvaluator(table, modes)
    reg_handlers = handlers or {}
    accumulated: list[dict[str, Any]] = list(prior_cards or [])
    new_cards: list[dict[str, Any]] = []

    sections = spec.get("sections")
    if isinstance(sections, list):
        for sec in sorted(sections, key=lambda s: int(s.get("order", 50))):
            for rule in sec.get("checks", []):
                card = evaluate_rule(rule, table, modes, evaluator, reg_handlers, accumulated)
                if card is not None:
                    new_cards.append(card)
                    accumulated.append(card)
    else:
        for rule in spec.get("checks", []):
            card = evaluate_rule(rule, table, modes, evaluator, reg_handlers, accumulated)
            if card is not None:
                new_cards.append(card)
                accumulated.append(card)

    return new_cards
