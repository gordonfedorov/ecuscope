#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks.py — диспетчер дополнительных диагностических проверок ЭБУ (Bosch M7.9.7)
для проекта ECUScope — Здоровье мотора.
"""

import inspect
import pyarrow as pa
from diagnose_utils import COL, col_vals
from diagnose_checks_thermal import (
    check_thermostat_and_fan,
    check_battery_and_alternator,
    check_cold_start_temps,
)
from diagnose_checks_air import (
    check_dfco_and_tps,
    check_iac_and_air_leak,
    check_maf_throttle_response,
)
from diagnose_checks_fuel import (
    check_oxygen_sensors,
    check_purge_valve,
    check_catalyst_efficiency,
    check_injectors_and_fuel_supply,
    check_mixture_differential,
)
from diagnose_checks_engine import (
    check_knock_and_retard,
    check_misfires_and_peak_maf,
    check_ckp_and_ign_dynamics,
)


def _build_ctx(table: pa.Table, valid_idx: list[int], run_idx: list[int], hot_idle_idx: list[int]) -> dict:
    """Формирует общий контекст колонок для совместимости со всеми сигнатурами проверок."""
    return {
        "table": table,
        "valid_idx": valid_idx,
        "run_idx": run_idx,
        "hot_idle_idx": hot_idle_idx,
        "times_raw": col_vals(table, COL["TIME"]),
        "ect_all": col_vals(table, COL["ECT"]),
        "iat_all": col_vals(table, COL["IAT"]),
        "load_all": col_vals(table, COL["LOAD"]) or col_vals(table, COL["CALC_LOAD"]),
        "spd_all": col_vals(table, COL["SPD"]),
        "rpm_all": col_vals(table, COL["RPM"]),
        "tps_all": col_vals(table, COL["TPS"]),
        "fcut_all": col_vals(table, COL["FCUT"]),
        "inj_all": col_vals(table, COL["INJ"]),
        "fan1_all": col_vals(table, COL["FAN1"]),
        "fan2_all": col_vals(table, COL["FAN2"]),
        "o2_fb_all": col_vals(table, COL["O2_FB1"]),
        "o2_1_all": col_vals(table, COL["O2_1"]),
        "o2_2_all": col_vals(table, COL["O2_2"]),
        "o2_period_all": col_vals(table, COL["O2_PERIOD"]),
    }


def _call_check(
    fn,
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
    ctx: dict,
) -> dict | None:
    """Универсальный вызов функции проверки с автоподбором позиционных или именованных аргументов."""
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if not params:
        return fn()

    first_name = params[0].name
    if first_name in ("table", "table_or_valid"):
        base_args = [table, valid_idx, run_idx, hot_idle_idx]
        req_or_pos = [
            p for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        return fn(*base_args[: len(req_or_pos)])

    kwargs = {}
    for p in params:
        if p.name in ctx:
            kwargs[p.name] = ctx[p.name]
    return fn(**kwargs)


def run_extra_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> list[dict]:
    """Точка входа для всех дополнительных диагностических проверок."""
    ctx = _build_ctx(table, valid_idx, run_idx, hot_idle_idx)

    check_pipeline = [
        # Охлаждение и питание
        check_cold_start_temps,
        check_thermostat_and_fan,
        check_battery_and_alternator,
        # Воздух, дроссель и ХХ
        check_dfco_and_tps,
        check_iac_and_air_leak,
        check_maf_throttle_response,
        # Топливо и экология
        check_oxygen_sensors,
        check_mixture_differential,
        check_purge_valve,
        check_catalyst_efficiency,
        check_injectors_and_fuel_supply,
        # Зажигание, ДПКВ и механика
        check_ckp_and_ign_dynamics,
        check_knock_and_retard,
        check_misfires_and_peak_maf,
    ]

    cards = []
    for fn in check_pipeline:
        res = _call_check(fn, table, valid_idx, run_idx, hot_idle_idx, ctx)
        if res is not None:
            cards.append(res)

    return cards
