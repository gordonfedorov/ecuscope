#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks_engine.py — проверки механики и зажигания ЭБУ (Bosch M7.9.7):
  - Детонация и величина отскока УОЗ под нагрузкой;
  - Детализация пропусков воспламенения по цилиндрам 1-4 и пиковый расход воздуха ДМРВ;
  - Стабильность сигнала ДПКВ (мгновенные срывы оборотов в 0 на ходу) и динамика УОЗ.
"""

import statistics
import pyarrow as pa
from diagnose_utils import COL, col_vals, sub


def check_knock_and_retard(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Анализ детонации и величины отскока УОЗ под нагрузкой."""
    retard_all = col_vals(table, COL["KNOCK_RETARD"])
    knock_v_all = col_vals(table, COL["KNOCK_V"])
    if not retard_all and not knock_v_all:
        return None

    times_raw = col_vals(table, COL["TIME"])
    rpm_all = col_vals(table, COL["RPM"])
    load_all = col_vals(table, COL["LOAD"]) or col_vals(table, COL["CALC_LOAD"])
    iat_all = col_vals(table, COL["IAT"])

    target_idx = run_idx if run_idx else valid_idx
    if not target_idx:
        return None

    retards = sub(retard_all, target_idx)
    knock_vs = sub(knock_v_all, target_idx)
    if not retards and not knock_vs:
        return None

    max_ret = max(retards) if retards else 0.0
    active_ret_idx = [
        i for i in target_idx
        if i < len(retard_all) and retard_all[i] is not None and retard_all[i] > 0.1
    ]
    heavy_ret_idx = [
        i for i in target_idx
        if i < len(retard_all) and retard_all[i] is not None and retard_all[i] >= 4.5
    ]

    max_kv = max(knock_vs) if knock_vs else None
    med_kv = statistics.median(knock_vs) if knock_vs else None

    if max_ret >= 7.5 or len(heavy_ret_idx) >= 15:
        st, badge = "status-bad", "СИЛЬНЫЙ ОТСКОК"
    elif max_ret >= 3.8 or len(active_ret_idx) > max(10, int(len(target_idx) * 0.08)):
        st, badge = "status-warn", "ДЕТОНАЦИЯ"
    else:
        st, badge = "status-ok", "НОРМА"

    kv_txt = f" | ДД: мед. {med_kv:.2f} В (пик {max_kv:.2f} В)" if (med_kv is not None and max_kv is not None) else ""
    pct_ret = (len(active_ret_idx) / len(target_idx)) * 100.0 if target_idx else 0.0
    val_txt = f"Макс. отскок: {max_ret:.1f}° (кадров: {len(active_ret_idx)}, {pct_ret:.1f}%){kv_txt}"

    tooltip_lines = [
        f"Кадров с отскоком УОЗ > 0°: {len(active_ret_idx)} из {len(target_idx)}",
        f"Кадров с глубоким отскоком ≥ 4.5°: {len(heavy_ret_idx)}",
    ]
    if active_ret_idx:
        top_idx = sorted(active_ret_idx, key=lambda idx: retard_all[idx], reverse=True)[:5]
        tooltip_lines.append("Топ эпизодов отскока УОЗ:")
        for idx in top_idx:
            t_s = f"{times_raw[idx]:.1f} с" if idx < len(times_raw) and times_raw[idx] is not None else "?"
            rpm_s = f"{rpm_all[idx]} об/мин" if idx < len(rpm_all) and rpm_all[idx] is not None else "?"
            ld_s = f"нагр. {load_all[idx]:.0f}%" if idx < len(load_all) and load_all[idx] is not None else ""
            iat_s = f"ДТВ {iat_all[idx]:.0f}°C" if idx < len(iat_all) and iat_all[idx] is not None else ""
            extra = ", ".join(p for p in (rpm_s, ld_s, iat_s) if p)
            tooltip_lines.append(f"  • {t_s}: -{retard_all[idx]:.1f}° ({extra})")

    return {
        "title": "Детонация и отскок УОЗ",
        "badge": badge,
        "status": st,
        "val": val_txt,
        "norm": "Норма: единичные отскоки до 3.0–3.5° при резком разгоне",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_misfires_and_peak_maf(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Детализация пропусков воспламенения по цилиндрам 1-4 и пиковый расход воздуха ДМРВ."""
    cyl_cols = [
        ("Цил. 1", COL["MIS_CYL_1"]),
        ("Цил. 2", COL["MIS_CYL_2"]),
        ("Цил. 3", COL["MIS_CYL_3"]),
        ("Цил. 4", COL["MIS_CYL_4"]),
    ]

    maf_all = col_vals(table, COL["MAF"])
    cycle_air_all = col_vals(table, COL["CYCLE_AIR"])
    rpm_all = col_vals(table, COL["RPM"])
    tps_all = col_vals(table, COL["TPS"])
    times_raw = col_vals(table, COL["TIME"])

    cyl_max: dict[str, int] = {}
    for label, col_name in cyl_cols:
        vals = sub(col_vals(table, col_name), valid_idx)
        if vals:
            cyl_max[label] = int(max(vals))

    sum_vals = sub(col_vals(table, COL["MIS_SUM"]), valid_idx)
    total_mis = max(sum_vals) if sum_vals else sum(cyl_max.values())

    target_idx = run_idx if run_idx else valid_idx
    mafs = sub(maf_all, target_idx)
    c_airs = sub(cycle_air_all, target_idx)

    if not cyl_max and not mafs:
        return None

    peak_maf = max(mafs) if mafs else None
    peak_c_air = max(c_airs) if c_airs else None

    peak_maf_info = ""
    if mafs:
        best_i = max(
            (i for i in target_idx if i < len(maf_all) and maf_all[i] is not None),
            key=lambda idx: maf_all[idx],
        )
        p_rpm = rpm_all[best_i] if best_i < len(rpm_all) and rpm_all[best_i] is not None else None
        p_tps = tps_all[best_i] if best_i < len(tps_all) and tps_all[best_i] is not None else None
        p_t = times_raw[best_i] if best_i < len(times_raw) and times_raw[best_i] is not None else None
        parts = []
        if p_rpm is not None:
            parts.append(f"{p_rpm} об/мин")
        if p_tps is not None:
            parts.append(f"ДПДЗ {p_tps:.0f}%")
        if p_t is not None:
            parts.append(f"на {p_t:.1f} с")
        if parts:
            peak_maf_info = f" ({', '.join(parts)})"

    wot_idx = [
        i for i in target_idx
        if i < len(tps_all) and tps_all[i] is not None and tps_all[i] >= 65.0
        and i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] >= 4000
        and i < len(maf_all) and maf_all[i] is not None
    ]
    wot_peak_maf = max(maf_all[i] for i in wot_idx) if wot_idx else None

    bad_cyls = [f"{lbl}={cnt}" for lbl, cnt in cyl_max.items() if cnt > 0]

    if total_mis > 5 or any(cnt > 3 for cnt in cyl_max.values()):
        st, badge = "status-bad", "ПРОПУСКИ"
    elif total_mis > 0 or bad_cyls:
        st, badge = "status-warn", "ЕДИНИЧНЫЕ"
    elif wot_peak_maf is not None and wot_peak_maf < 155.0:
        st, badge = "status-warn", "СЛАБЫЙ ПИК ДМРВ"
    else:
        st, badge = "status-ok", "НОРМА"

    cyl_str = f"Пропуски: {', '.join(bad_cyls)}" if bad_cyls else f"Пропуски по цил.: 0 (сумма {total_mis})"
    maf_str = ""
    if peak_maf is not None:
        ca_txt = f", {peak_c_air:.0f} мг/такт" if peak_c_air is not None else ""
        maf_str = f" | Пик ДМРВ: {peak_maf:.1f} кг/ч{ca_txt}"

    tooltip_lines = ["Счётчики пропусков по цилиндрам:"]
    if cyl_max:
        tooltip_lines.append("  " + ", ".join(f"{k}: {v}" for k, v in cyl_max.items()))
    tooltip_lines.append(f"  Суммарный счётчик ЭБУ: {total_mis}")
    if peak_maf is not None:
        tooltip_lines.append(f"Максимальный расход воздуха: {peak_maf:.1f} кг/ч{peak_maf_info}")
    if peak_c_air is not None:
        tooltip_lines.append(f"Максимальное цикловое наполнение: {peak_c_air:.1f} мг/такт (норма 1.5/1.6л: 330–430 мг/такт)")
    if wot_peak_maf is not None:
        tooltip_lines.append(f"Пик ДМРВ при полном газе (≥4000 об/мин, ДПДЗ ≥65%): {wot_peak_maf:.1f} кг/ч")

    return {
        "title": "Цилиндры и пик ДМРВ",
        "badge": badge,
        "status": st,
        "val": f"{cyl_str}{maf_str}",
        "norm": "Норма: 0 пропусков; пик ДМРВ 1.5/1.6л: 200–280 кг/ч",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_ckp_and_ign_dynamics(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """
    Проверка стабильности сигнала ДПКВ (мгновенные срывы оборотов в 0 при движении/работе)
    и динамического диапазона регулирования УОЗ под нагрузкой и оборотами.
    """
    rpm_all = col_vals(table, COL["RPM"])
    ign_all = col_vals(table, COL["IGN"])
    spd_all = col_vals(table, COL["SPD"])
    times_raw = col_vals(table, COL["TIME"])
    crank_std_all = col_vals(table, COL["CRANK_STD"])

    if not rpm_all and not ign_all:
        return None

    # 1. Детектор кратковременных провалов оборотов до 0 на ходу (признак сбоя ДПКВ / проводки)
    ckp_glitches = []
    for pos in range(1, len(valid_idx) - 1):
        i_prev = valid_idx[pos - 1]
        i_cur = valid_idx[pos]
        i_next = valid_idx[pos + 1]
        if i_cur >= len(rpm_all) or i_prev >= len(rpm_all) or i_next >= len(rpm_all):
            continue
        r_prev = rpm_all[i_prev]
        r_cur = rpm_all[i_cur]
        r_next = rpm_all[i_next]
        spd_cur = spd_all[i_cur] if i_cur < len(spd_all) and spd_all[i_cur] is not None else 0.0
        t_cur = times_raw[i_cur] if i_cur < len(times_raw) else None
        t_prev = times_raw[i_prev] if i_prev < len(times_raw) else None
        t_next = times_raw[i_next] if i_next < len(times_raw) else None

        dt_span = (t_next - t_prev) if (t_next is not None and t_prev is not None) else 1.0
        if (
            r_cur == 0
            and r_prev is not None and r_prev >= 1100
            and r_next is not None and r_next >= 1100
            and dt_span <= 3.0
        ):
            ckp_glitches.append((t_cur, r_prev, r_next, spd_cur))

    # 2. Рабочий диапазон УОЗ при работающем двигателе
    target_idx = run_idx if run_idx else valid_idx
    igns = sub(ign_all, target_idx)
    ign_min = min(igns) if igns else None
    ign_max = max(igns) if igns else None
    ign_span = (ign_max - ign_min) if (ign_min is not None and ign_max is not None) else None

    crank_stds = sub(crank_std_all, target_idx)
    max_crank_std = max(crank_stds) if crank_stds else None

    ign_stuck = (ign_span is not None and len(igns) >= 30 and ign_span < 4.5)

    if len(ckp_glitches) >= 2:
        st, badge = "status-bad", "СБОЙ ДПКВ"
    elif len(ckp_glitches) == 1:
        st, badge = "status-warn", "ПРОВАЛ ДПКВ"
    elif ign_stuck:
        st, badge = "status-warn", "ЗАЛИП УОЗ"
    else:
        st, badge = "status-ok", "НОРМА"

    ckp_txt = (
        f"Срывов ДПКВ: {len(ckp_glitches)}"
        if ckp_glitches
        else "Сигнал ДПКВ: стабилен (0 срывов)"
    )
    ign_txt = (
        f" | УОЗ: {ign_min:.1f}..{ign_max:.1f}° (размах {ign_span:.1f}°)"
        if ign_span is not None
        else ""
    )

    tooltip_lines = [
        f"Обнаружено мгновенных срывов оборотов в 0 на ходу: {len(ckp_glitches)}",
    ]
    for idx_g, (tg, rp, rn, sp) in enumerate(ckp_glitches[:5], 1):
        t_s = f"{tg:.1f} с" if tg is not None else "?"
        sp_s = f", скорость {sp:.0f} км/ч" if sp > 0 else ""
        tooltip_lines.append(f"  • Срыв #{idx_g} на {t_s}: {rp} → 0 → {rn} об/мин{sp_s}")
    if ign_span is not None:
        tooltip_lines.append(
            f"Диапазон УОЗ при работе двигателя ({len(igns)} кадр.): {ign_min:.1f} .. {ign_max:.1f} °ПКВ (размах {ign_span:.1f}°)"
        )
    if max_crank_std is not None:
        tooltip_lines.append(f"Макс. неравномерность вращения коленвала: {max_crank_std:.1f} об/с²")

    return {
        "title": "ДПКВ и динамика УОЗ",
        "badge": badge,
        "status": st,
        "val": f"{ckp_txt}{ign_txt}",
        "norm": "Норма: 0 срывов ДПКВ; рабочий размах УОЗ ≥ 8–15 °ПКВ",
        "tooltip": "\n".join(tooltip_lines),
    }
