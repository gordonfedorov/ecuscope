#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks_thermal.py — проверки системы охлаждения и электропитания (Bosch M7.9.7):
  - Термостат, адаптивный прогрев, детектор зависания ДТОЖ и работа вентилятора охлаждения 1;
  - Напряжение АКБ в покое (до пуска) и просадка генератора под нагрузкой вентилятора;
  - Сверка датчиков температуры ДТОЖ и ДТВ при холодном старте двигателя.
"""

import statistics
import pyarrow as pa
from diagnose_utils import col_vals, sub, COL


def check_thermostat_and_fan(table: pa.Table, valid_idx: list[int]) -> dict | None:
    """
    Проверка динамики прогрева (с учётом начальной температуры/ДТВ и нагрузки на двигатель),
    детектор «зависания» ДТОЖ, работа термостата в движении и циклы включения вентилятора 1.
    """
    times_raw = col_vals(table, COL["TIME"])
    ect_all = col_vals(table, COL["ECT"])
    iat_all = col_vals(table, COL["IAT"])
    load_all = col_vals(table, COL["LOAD"]) or col_vals(table, COL["CALC_LOAD"])
    spd_all = col_vals(table, COL["SPD"])
    rpm_all = col_vals(table, COL["RPM"])
    fan1_all = col_vals(table, COL["FAN1"])

    if not ect_all or not valid_idx:
        return None

    first_ect = None
    first_t = None
    first_iat = None
    warmup_dur = None
    reached_80 = False
    warmup_loads = []
    warmup_spds = []

    for i in valid_idx:
        ect = ect_all[i] if i < len(ect_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None
        iat = iat_all[i] if i < len(iat_all) else None
        ld = load_all[i] if i < len(load_all) else None
        spd = spd_all[i] if i < len(spd_all) else None
        if ect is None or t_cur is None:
            continue
        if first_ect is None:
            first_ect = ect
            first_t = t_cur
            first_iat = iat
        if first_ect < 55.0 and not reached_80:
            if ld is not None:
                warmup_loads.append(ld)
            if spd is not None:
                warmup_spds.append(spd)
            if ect >= 80.0:
                warmup_dur = max(0.0, t_cur - first_t)
                reached_80 = True
                break

    expected_warmup_sec = None
    avg_warmup_load = statistics.mean(warmup_loads) if warmup_loads else None
    avg_warmup_spd = statistics.mean(warmup_spds) if warmup_spds else None
    ambient_ref = None
    if first_ect is not None and first_iat is not None:
        ambient_ref = min(first_ect, first_iat)
    elif first_ect is not None:
        ambient_ref = first_ect

    if warmup_dur is not None and first_ect is not None:
        delta_t = max(10.0, 80.0 - first_ect)
        base_sec = delta_t * 7.5
        if ambient_ref is not None and ambient_ref < 10.0:
            base_sec += (10.0 - ambient_ref) * 6.0

        load_factor = 1.0
        if avg_warmup_load is not None:
            if avg_warmup_load < 20.0:
                load_factor = 1.55 if (avg_warmup_spd is not None and avg_warmup_spd > 25.0) else 1.35
            elif avg_warmup_load < 26.0:
                load_factor = 1.25
            elif avg_warmup_load > 40.0:
                load_factor = 0.85

        expected_warmup_sec = max(480.0, base_sec * load_factor)

    # Детектор «зависания» ДТОЖ при работающем двигателе в зоне прогрева (< 82 °C)
    max_stuck_dur = 0.0
    stuck_ect = None
    stuck_t0 = None
    cur_stuck_ect = None
    cur_stuck_t0 = None

    for i in valid_idx:
        ect = ect_all[i] if i < len(ect_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None
        rpm = rpm_all[i] if i < len(rpm_all) else None
        if ect is None or t_cur is None or rpm is None or rpm < 450:
            cur_stuck_ect = None
            cur_stuck_t0 = None
            continue
        if ect < 82.0:
            if cur_stuck_ect is not None and abs(ect - cur_stuck_ect) < 0.05:
                dur = t_cur - cur_stuck_t0
                if dur > max_stuck_dur:
                    max_stuck_dur = dur
                    stuck_ect = ect
                    stuck_t0 = cur_stuck_t0
            else:
                cur_stuck_ect = ect
                cur_stuck_t0 = t_cur
        else:
            cur_stuck_ect = None
            cur_stuck_t0 = None

    was_warm_82 = False
    thermostat_drop_ect = None
    thermostat_drop_t = None
    highway_cold_frames = 0

    for i in valid_idx:
        ect = ect_all[i] if i < len(ect_all) else None
        spd = spd_all[i] if i < len(spd_all) else 0.0
        t_cur = times_raw[i] if i < len(times_raw) else None
        if ect is None:
            continue
        if ect >= 82.0:
            was_warm_82 = True
        if was_warm_82 and ect < 78.0 and (spd is not None and spd >= 50.0):
            highway_cold_frames += 1
            if thermostat_drop_ect is None or ect < thermostat_drop_ect:
                thermostat_drop_ect = ect
                thermostat_drop_t = t_cur

    fan_cycles = []
    cur_fan = None
    for i in valid_idx:
        fan = fan1_all[i] if i < len(fan1_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None
        if fan is None:
            continue
        if fan == 1:
            if cur_fan is None:
                cur_fan = {"t_on": t_cur, "ect_on": ect, "t_last": t_cur, "ect_last": ect}
            else:
                cur_fan["t_last"] = t_cur
                if ect is not None:
                    cur_fan["ect_last"] = ect
        else:
            if cur_fan is not None:
                dur = max(0.0, (cur_fan["t_last"] - cur_fan["t_on"])) if (cur_fan["t_last"] is not None and cur_fan["t_on"] is not None) else 0.0
                fan_cycles.append({**cur_fan, "dur": dur, "ect_off": ect if ect is not None else cur_fan["ect_last"]})
                cur_fan = None

    if cur_fan is not None:
        dur = max(0.0, (cur_fan["t_last"] - cur_fan["t_on"])) if (cur_fan["t_last"] is not None and cur_fan["t_on"] is not None) else 0.0
        fan_cycles.append({**cur_fan, "dur": dur, "ect_off": cur_fan["ect_last"]})

    issues = []
    status = "status-ok"
    badge = "НОРМА"

    if highway_cold_frames >= 5 and thermostat_drop_ect is not None:
        status = "status-warn"
        badge = "ТЕРМОСТАТ"
        issues.append(f"падение на ходу до {thermostat_drop_ect:.1f}°C")

    if max_stuck_dur >= 240.0 and stuck_ect is not None:
        if status == "status-ok":
            status = "status-warn"
            badge = "ЗАВИСАНИЕ ДТОЖ"
        issues.append(f"плато {stuck_ect:.1f}°C ({max_stuck_dur / 60.0:.1f} мин)")

    if warmup_dur is not None and expected_warmup_sec is not None and warmup_dur > expected_warmup_sec:
        if status == "status-ok":
            status = "status-warn"
            badge = "ДОЛГИЙ ПРОГРЕВ"
        issues.append(f"порог {expected_warmup_sec / 60.0:.1f} мин")

    fan_on_temps = [c["ect_on"] for c in fan_cycles if c["ect_on"] is not None]
    if fan_cycles:
        on_med = statistics.median(fan_on_temps) if fan_on_temps else 0.0
        fan_str = f"Вент.1: {len(fan_cycles)} вкл. (~{on_med:.1f}°C)"
    else:
        fan_str = "Вент.1: не вкл."

    if warmup_dur is not None:
        load_note = f", нагр. {avg_warmup_load:.0f}%" if avg_warmup_load is not None else ""
        warm_str = f"Прогрев до 80°C: {warmup_dur / 60.0:.1f} мин{load_note}"
    elif first_ect is not None:
        warm_str = f"Старт с {first_ect:.1f}°C"
    else:
        warm_str = "ТОЖ в норме"

    val_parts = [warm_str, fan_str]
    if issues:
        val_parts.append(" | ".join(issues))

    tooltip_lines = []
    if first_ect is not None:
        iat_txt = f", ДТВ на старте: {first_iat:.1f} °C" if first_iat is not None else ""
        tooltip_lines.append(f"Начальная ТОЖ: {first_ect:.1f} °C{iat_txt}")
    if warmup_dur is not None:
        exp_txt = f" (адаптивный порог: {expected_warmup_sec / 60.0:.1f} мин)" if expected_warmup_sec is not None else ""
        ld_txt = f" | ср. нагрузка: {avg_warmup_load:.1f}%" if avg_warmup_load is not None else ""
        sp_txt = f", ср. скорость: {avg_warmup_spd:.0f} км/ч" if avg_warmup_spd is not None else ""
        tooltip_lines.append(
            f"Прогрев с {first_ect:.1f} °C до 80 °C: {warmup_dur:.0f} с ({warmup_dur / 60.0:.1f} мин){exp_txt}{ld_txt}{sp_txt}"
        )
    if max_stuck_dur >= 90.0 and stuck_ect is not None:
        t_st = f" с {stuck_t0:.1f} с" if stuck_t0 is not None else ""
        tooltip_lines.append(f"Макс. плато ДТОЖ в зоне прогрева: {stuck_ect:.1f} °C в течение {max_stuck_dur:.0f} с{t_st}")
    if thermostat_drop_ect is not None:
        t_info = f" на {thermostat_drop_t:.1f} с" if thermostat_drop_t is not None else ""
        tooltip_lines.append(f"Просадка ТОЖ на скорости ≥50 км/ч: до {thermostat_drop_ect:.1f} °C{t_info} ({highway_cold_frames} кадр.)")
    for idx_f, fc in enumerate(fan_cycles, 1):
        t_on_s = f"{fc['t_on']:.1f} с" if fc["t_on"] is not None else "?"
        e_on_s = f"{fc['ect_on']:.1f}°C" if fc["ect_on"] is not None else "?"
        e_off_s = f"{fc['ect_off']:.1f}°C" if fc["ect_off"] is not None else "?"
        tooltip_lines.append(f"Вент.1 #{idx_f} ({t_on_s}): {e_on_s} → {e_off_s} ({fc['dur']:.1f} с)")

    norm_hint = (
        f"Порог прогрева с учётом T и нагрузки: ≤ {expected_warmup_sec / 60.0:.1f} мин; вент.1 ~101–103°C"
        if expected_warmup_sec is not None
        else "Норма: без просадок <78°C на ходу; вент.1 ~101–103°C"
    )

    return {
        "title": "Термостат и вентилятор",
        "badge": badge,
        "status": status,
        "val": " | ".join(val_parts),
        "norm": norm_hint,
        "tooltip": "\n".join(tooltip_lines) if tooltip_lines else None,
    }


def check_battery_and_alternator(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Проверка напряжения АКБ в покое (до пуска) и просадки генератора под нагрузкой вентилятора."""
    vbat_all = col_vals(table, COL["VBAT"])
    rpm_all = col_vals(table, COL["RPM"])
    fan1_all = col_vals(table, COL["FAN1"])
    fan2_all = col_vals(table, COL["FAN2"])

    if not vbat_all or not valid_idx:
        return None

    pre_start_vbats = []
    for i in valid_idx:
        rpm = rpm_all[i] if i < len(rpm_all) else None
        vb = vbat_all[i] if i < len(vbat_all) else None
        if rpm is None or vb is None:
            continue
        if rpm == 0:
            pre_start_vbats.append(vb)
        else:
            break

    fan_on_vbats = []
    fan_off_vbats = []
    for i in run_idx:
        vb = vbat_all[i] if i < len(vbat_all) else None
        if vb is None:
            continue
        f1 = fan1_all[i] if i < len(fan1_all) and fan1_all[i] is not None else 0
        f2 = fan2_all[i] if i < len(fan2_all) and fan2_all[i] is not None else 0
        if f1 == 1 or f2 == 1:
            fan_on_vbats.append(vb)
        else:
            fan_off_vbats.append(vb)

    if not pre_start_vbats and not fan_on_vbats:
        return None

    akb_med = statistics.median(pre_start_vbats) if pre_start_vbats else None
    fan_med = statistics.median(fan_on_vbats) if fan_on_vbats else None
    fan_min = min(fan_on_vbats) if fan_on_vbats else None
    base_med = statistics.median(fan_off_vbats) if fan_off_vbats else None
    drop = (base_med - fan_med) if (base_med is not None and fan_med is not None) else None

    if (akb_med is not None and akb_med < 11.8) or (fan_min is not None and fan_min < 12.7):
        st, badge = "status-bad", "ПРОСАДКА ГЕН."
    elif (akb_med is not None and akb_med < 12.2) or (fan_med is not None and fan_med < 13.2) or (drop is not None and drop > 0.65):
        st, badge = "status-warn", "ПРОСАДКА СЕТИ"
    else:
        st, badge = "status-ok", "НОРМА"

    parts = []
    if akb_med is not None:
        parts.append(f"АКБ до пуска: {akb_med:.2f} В")
    if fan_med is not None:
        drop_txt = f" (-{drop:.2f} В)" if (drop is not None and drop > 0.02) else ""
        parts.append(f"Под вентилятором: {fan_med:.2f} В{drop_txt}")

    tooltip_lines = []
    if akb_med is not None:
        tooltip_lines.append(
            f"Напряжение АКБ при включённом зажигании до стартера ({len(pre_start_vbats)} кадр.): "
            f"мед. {akb_med:.2f} В (мин. {min(pre_start_vbats):.2f} В)"
        )
    if fan_on_vbats:
        tooltip_lines.append(
            f"Напряжение сети при включённом вентиляторе ({len(fan_on_vbats)} кадр.): "
            f"мед. {fan_med:.2f} В, мин. {fan_min:.2f} В"
        )
        if base_med is not None:
            tooltip_lines.append(f"Напряжение без вентилятора: мед. {base_med:.2f} В")

    return {
        "title": "АКБ и генератор (нагр.)",
        "badge": badge,
        "status": st,
        "val": " | ".join(parts),
        "norm": "Норма: АКБ покой 12.3–12.8 В; под нагрузкой ≥ 13.3 В",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_cold_start_temps(table: pa.Table, valid_idx: list[int]) -> dict | None:
    """
    Сверка датчиков температуры охлаждающей жидкости (ДТОЖ) и впускного воздуха (ДТВ)
    на первых кадрах при запуске (оценка на холодном и тёплом двигателе).
    """
    ect_all = col_vals(table, COL["ECT"])
    iat_all = col_vals(table, COL["IAT"])
    rpm_all = col_vals(table, COL["RPM"])
    times_raw = col_vals(table, COL["TIME"])

    if not ect_all or not iat_all or not valid_idx:
        return None

    # Собираем первые кадры до пуска (rpm == 0) или первые 5 валидных кадров записи
    pre_pairs = []
    for i in valid_idx:
        ect = ect_all[i] if i < len(ect_all) else None
        iat = iat_all[i] if i < len(iat_all) else None
        rpm = rpm_all[i] if i < len(rpm_all) else None
        if ect is None or iat is None:
            continue
        if rpm is not None and rpm == 0:
            pre_pairs.append((ect, iat))
        else:
            break

    mode_lbl = "до пуска"
    if not pre_pairs:
        for i in valid_idx[:5]:
            ect = ect_all[i] if i < len(ect_all) else None
            iat = iat_all[i] if i < len(iat_all) else None
            if ect is not None and iat is not None:
                pre_pairs.append((ect, iat))
        mode_lbl = "на старте записи"

    if not pre_pairs:
        return None

    ect_start = statistics.median([p[0] for p in pre_pairs])
    iat_start = statistics.median([p[1] for p in pre_pairs])
    diff = iat_start - ect_start
    abs_diff = abs(diff)

    ect_start_col = col_vals(table, COL["ECT_START"])
    ect_ecu_start = next((v for v in sub(ect_start_col, valid_idx)), None)

    if ect_start <= 35.0:
        # Холодный двигатель: ДТОЖ и ДТВ должны быть близки к температуре окружающей среды
        if abs_diff >= 12.0:
            st, badge = "status-bad", "РАСХОЖДЕНИЕ T°"
        elif abs_diff >= 7.0:
            st, badge = "status-warn", "СДВИГ ДТВ/ДТОЖ"
        else:
            st, badge = "status-ok", "СОГЛАСОВАНЫ"
        norm_txt = "Норма (холодный мотор ≤35 °C): разница |ДТВ − ДТОЖ| ≤ 6 °C"
    else:
        # Тёплый/горячий повторный пуск: ДТОЖ выше ДТВ, но ДТВ не должен уходить в аномалию
        if iat_start > ect_start + 12.0 or iat_start < -35.0 or iat_start > 85.0:
            st, badge = "status-warn", "АНОМАЛИЯ ДТВ"
        else:
            st, badge = "status-ok", "ТЁПЛЫЙ ПУСК"
        norm_txt = "Норма (тёплый пуск >35 °C): ДТОЖ выше ДТВ, адекватный ДТВ"

    tooltip_lines = [
        f"Замер ({mode_lbl}, {len(pre_pairs)} кадр.): ДТОЖ = {ect_start:.1f} °C, ДТВ = {iat_start:.1f} °C",
        f"Разница (ДТВ − ДТОЖ): {diff:+.1f} °C",
    ]
    if ect_ecu_start is not None:
        tooltip_lines.append(f"Зафиксированная ЭБУ ТОЖ при пуске: {ect_ecu_start:.1f} °C")
    tooltip_lines.append(
        "На остывшем автомобиле показания ДТОЖ и ДТВ должны совпадать с точностью до 5–6 °C; "
        "большой разброс указывает на деградацию термистора или плохой контакт в разъёме."
    )

    return {
        "title": "ДТОЖ и ДТВ на старте",
        "badge": badge,
        "status": st,
        "val": f"ДТОЖ: {ect_start:.1f}°C | ДТВ: {iat_start:.1f}°C (Δ {diff:+.1f}°C)",
        "norm": norm_txt,
        "tooltip": "\n".join(tooltip_lines),
    }
