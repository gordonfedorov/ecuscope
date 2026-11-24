"""Диспетчер дополнительных проверок (охлаждение, воздух, топливо, зажигание и перекрёстный диагноз)."""

from __future__ import annotations

import inspect
from typing import Any

import pyarrow as pa

import diagnose_checks_air as _mod_air
import diagnose_checks_engine as _mod_engine
import diagnose_checks_fuel as _mod_fuel
import diagnose_checks_thermal as _mod_thermal
from diagnose_utils import COL, IDLE_RPM_MAX, IDLE_RPM_MIN, WARM_ECT_C, col_vals


def _pick_fn(mod: Any, *names: str):
    for name in names:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def _build_ctx(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict[str, Any]:
    times = col_vals(table, COL["TIME"])
    rpm = col_vals(table, COL["RPM"])
    ect = col_vals(table, COL["ECT"])
    iat = col_vals(table, COL["IAT"])
    vbat = col_vals(table, COL["VBAT"])
    spd = col_vals(table, COL["SPD"])
    tps = col_vals(table, COL["TPS"])
    maf = col_vals(table, COL["MAF"])
    ign = col_vals(table, COL["IGN"])
    inj = col_vals(table, COL["INJ"])
    fr = col_vals(table, COL["FR"])
    fra = col_vals(table, COL["FRA"])
    rkat = col_vals(table, COL["RKAT"])
    iac = col_vals(table, COL["IAC"])
    o2_1 = col_vals(table, COL["O2_1"])
    o2_2 = col_vals(table, COL["O2_2"])
    load = col_vals(table, COL["LOAD"])

    return {
        "table": table,
        "valid_idx": valid_idx,
        "valid": valid_idx,
        "run_idx": run_idx,
        "run": run_idx,
        "hot_idle_idx": hot_idle_idx,
        "hot_idle": hot_idle_idx,
        "idle_idx": hot_idle_idx,
        "times": times,
        "t": times,
        "rpm": rpm,
        "ect": ect,
        "iat": iat,
        "vbat": vbat,
        "spd": spd,
        "tps": tps,
        "maf": maf,
        "ign": ign,
        "inj": inj,
        "fr": fr,
        "fra": fra,
        "rkat": rkat,
        "iac": iac,
        "o2_1": o2_1,
        "o2_2": o2_2,
        "load": load,
        "warm_ect": WARM_ECT_C,
        "idle_rpm_min": IDLE_RPM_MIN,
        "idle_rpm_max": IDLE_RPM_MAX,
    }


def _call_check(
    fn: Any,
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    ctx: dict[str, Any],
) -> Any:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if not params:
        return fn()

    first_name = params[0].name
    base_args = [table, valid_idx, run_idx, hot_idle_idx]
    if first_name in ("table_or_valid", "valid_or_times"):
        req_or_pos = [
            p for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return fn(*base_args[: len(req_or_pos)])

    kwargs: dict[str, Any] = {}
    for idx_p, p in enumerate(params):
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if idx_p == 0 and p.name in ("table", "tbl", "df"):
            kwargs[p.name] = table
        elif p.name in ctx:
            kwargs[p.name] = ctx[p.name]
        elif p.default is inspect.Parameter.empty:
            if idx_p < len(base_args):
                kwargs[p.name] = base_args[idx_p]
            else:
                kwargs[p.name] = None
    return fn(**kwargs)


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


def _normalize_check(raw: dict[str, Any]) -> dict[str, Any]:
    """Приводит карточку проверки к точному формату render_summary_html в diagnose.py."""
    st_raw = str(raw.get("status") or "status-na").strip().lower()
    st_class, default_badge = _STATUS_MAP.get(st_raw, ("status-na", "НЕТ ДАННЫХ"))

    title = str(raw.get("title") or raw.get("name") or raw.get("label") or "Проверка").strip()
    badge = str(raw.get("badge") or default_badge).strip()
    val = str(raw.get("val") or raw.get("value") or "—").strip()
    norm = str(raw.get("norm") or raw.get("sub") or raw.get("subtitle") or "").strip()
    tooltip = raw.get("tooltip") or raw.get("detail") or raw.get("details") or raw.get("hint")
    tooltip_str = str(tooltip).strip() if tooltip else ""

    return {
        "status": st_class,
        "title": title,
        "badge": badge,
        "val": val,
        "norm": norm,
        "tooltip": tooltip_str,
    }


def _build_cross_diagnosis(all_checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Сопоставляет сработавшие отклонения по разным узлам и выделяет вероятную первопричину."""
    issues = [c for c in all_checks if c.get("status") in ("status-warn", "status-bad")]
    if not issues:
        return {
            "status": "status-ok",
            "title": "Перекрёстный диагноз",
            "badge": "НОРМА",
            "val": "Противоречий нет",
            "norm": "Все связки датчиков и систем согласованы",
            "tooltip": "Кросс-анализ 25 проверок не выявил системных противоречий между смесеобразованием, воздухом, охлаждением и зажиганием.",
        }

    blob = " | ".join(
        f"{c.get('title', '')} {c.get('val', '')} {c.get('norm', '')} {c.get('tooltip', '')}".lower()
        for c in issues
    )

    hypotheses: list[tuple[str, str, str]] = []

    has_leak_hint = any(k in blob for k in ("подсос", "зажат рхх", "малый шаг рхх"))
    has_lean = any(k in blob for k in ("бедная", "обеднен", "fr >", "fra >", "высокая коррекция", "дефицит топлива"))
    has_maf_issue = any(k in blob for k in ("дмрв", "ацп дмрв", "износ дмрв", "слабый отклик"))
    has_ground_issue = "плохая масса" in blob
    has_iac_hunt = any(k in blob for k in ("пиление хх", "заклинил рхх", "подклинивает рхх", "загрязн", "провал оборотов"))
    has_throttle_lag = "провал при газе" in blob
    has_knock = "детонац" in blob or "отскок уоз" in blob
    has_misfire = "пропуск" in blob
    has_o2_issue = any(k in blob for k in ("старение дк1", "завис", "вялый", "closed loop"))
    has_ckp_issue = "срыв дпкв" in blob or "сбои дпкв" in blob

    if has_ground_issue:
        hypotheses.append((
            "status-bad",
            "Плохая масса датчиков / питание ЭБУ",
            "Зафиксированы синхронные скачки показаний датчиков при просадке напряжения бортсети — проверьте обжимку масс жгута ЭБУ и клеммы АКБ.",
        ))

    if has_ckp_issue:
        hypotheses.append((
            "status-bad",
            "Нестабильный сигнал ДПКВ",
            "Обнаружены мгновенные срывы оборотов в 0 на ходу — проверьте разъём, проводку ДПКВ и биение задающего диска.",
        ))

    if has_leak_hint and has_lean:
        hypotheses.append((
            "status-bad",
            "Подсос воздуха за дросселем",
            "Совпали признаки неучтённого воздуха по РХХ/нагрузке и обеднение смеси на ХХ с выравниванием на оборотах — проверьте впускной тракт, ВУТ и уплотнения форсунок.",
        ))
    elif has_maf_issue and (has_lean or has_throttle_lag):
        hypotheses.append((
            "status-warn",
            "Деградация / загрязнение ДМРВ",
            "Отклонения АЦП покоя или отклика ДМРВ сопровождаются сдвигом топливных коррекций или провалом при резком газе.",
        ))
    elif has_lean and not has_leak_hint and not has_maf_issue:
        hypotheses.append((
            "status-warn",
            "Дефицит топливоподачи",
            "Обеднение смеси под нагрузкой при исправном воздушном тракте указывает на снижение давления топлива (насос, фильтр, РДТ) или загрязнение форсунок.",
        ))

    if has_iac_hunt:
        hypotheses.append((
            "status-warn",
            "Неисправность РХХ / дроссельного узла",
            "Выявлены автоколебания («пиление») оборотов ХХ, провалы при сбросе газа или отсутствие реакции оборотов на открытие РХХ.",
        ))

    if has_throttle_lag and not has_maf_issue:
        hypotheses.append((
            "status-warn",
            "Задержка отклика при резком газе",
            "Нарушена каскадная реакция ДПДЗ -> ДМРВ -> впрыск -> обороты при резком открытии дросселя (проверьте ДПДЗ, ДМРВ и давление в рампе).",
        ))

    if has_misfire:
        hypotheses.append((
            "status-bad",
            "Пропуски воспламенения",
            "Зафиксированы пропуски зажигания — проверьте свечи, индивидуальные катушки/модуль, компрессию и форсунки проблемного цилиндра.",
        ))

    if has_knock:
        hypotheses.append((
            "status-warn",
            "Детонация под нагрузкой",
            "Глубокий отскок УОЗ под нагрузкой — проверьте октановое число топлива, температуру воздуха на впуске и нагар в камере сгорания.",
        ))

    if has_o2_issue:
        hypotheses.append((
            "status-warn",
            "Сбой лямбда-регулирования (ДК1)",
            "Медленное переключение ДК1 или отсутствие перехода в Closed Loop искажает топливные коррекции.",
        ))

    if not hypotheses:
        first_titles = ", ".join(c.get("title", "") for c in issues[:3])
        worst = "status-bad" if any(c.get("status") == "status-bad" for c in issues) else "status-warn"
        return {
            "status": worst,
            "title": "Перекрёстный диагноз",
            "badge": "ПРОБЛЕМА" if worst == "status-bad" else "ВНИМАНИЕ",
            "val": f"Локальных отклонений: {len(issues)}",
            "norm": f"Проверьте: {first_titles}",
            "tooltip": "Системных конфликтов между узлами не выявлено, но есть локальные отклонения по отдельным карточкам.",
        }

    worst_status = "status-bad" if any(h[0] == "status-bad" for h in hypotheses) else "status-warn"
    primary_title = hypotheses[0][1]
    extra_cnt = len(hypotheses) - 1
    norm_text = (
        f"Также выявлено: {hypotheses[1][1]}" + (f" (+{extra_cnt - 1})" if extra_cnt > 1 else "")
        if extra_cnt > 0
        else "Вероятная первопричина по совокупности улик"
    )
    tip_lines = [f"• {h[1]}: {h[2]}" for h in hypotheses]

    return {
        "status": worst_status,
        "title": "Перекрёстный диагноз",
        "badge": "ПРОБЛЕМА" if worst_status == "status-bad" else "ВНИМАНИЕ",
        "val": primary_title,
        "norm": norm_text,
        "tooltip": "\n".join(tip_lines),
    }


def run_extra_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    base_results: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Запускает все дополнительные проверки и формирует сводную карточку перекрёстного диагноза."""
    ctx = _build_ctx(table, valid_idx, run_idx, hot_idle_idx)

    check_fns = [
        _pick_fn(_mod_thermal, "check_thermostat_and_fan"),
        _pick_fn(_mod_thermal, "check_cold_start_temps"),
        _pick_fn(_mod_thermal, "check_battery_and_alternator"),
        _pick_fn(_mod_air, "check_dfco_and_tps"),
        _pick_fn(_mod_air, "check_iac_and_air_leak"),
        _pick_fn(_mod_air, "check_maf_throttle_response"),
        _pick_fn(_mod_fuel, "check_oxygen_sensors"),
        _pick_fn(_mod_fuel, "check_purge_valve"),
        _pick_fn(_mod_fuel, "check_mixture_differential"),
        _pick_fn(_mod_fuel, "check_catalyst_efficiency"),
        _pick_fn(_mod_fuel, "check_injectors_and_fuel_supply"),
        _pick_fn(_mod_engine, "check_knock_and_retard"),
        _pick_fn(_mod_engine, "check_misfires_by_cylinder", "check_misfires_and_peak_maf", "check_misfires"),
        _pick_fn(_mod_engine, "check_ckp_and_ign_dynamics"),
        _pick_fn(_mod_engine, "check_throttle_cascade_response"),
    ]

    extra_results: list[dict[str, Any]] = []
    for fn in check_fns:
        if fn is None:
            continue
        res = _call_check(fn, table, valid_idx, run_idx, hot_idle_idx, ctx)
        if isinstance(res, list):
            for item in res:
                if isinstance(item, dict):
                    extra_results.append(_normalize_check(item))
        elif isinstance(res, dict):
            extra_results.append(_normalize_check(res))

    combined = list(base_results or []) + extra_results
    extra_results.append(_build_cross_diagnosis(combined))
    return extra_results
