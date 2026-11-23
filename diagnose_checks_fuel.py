#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks_fuel.py — диагностика топливной системы и экологии (Bosch M7.9.7):
  - Датчики кислорода: активность ДК1, период переключений, вход в Closed Loop и нагреватель;
  - Клапан продувки адсорбера (КПА) и влияние на коррекцию FR;
  - Эффективность катализатора по сигналу ДК2 и индексу амплитуды ЭБУ;
  - Загрузка форсунок (%) и оценка производительности топливного насоса под нагрузкой;
  - Дифференциальный баланс смеси: коррекция FR на ХХ против повышенных оборотов (1500+ об/мин).
"""

import statistics
import pyarrow as pa
from diagnose_utils import COL, col_vals, sub


def check_oxygen_sensors(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict | None:
    """
    Проверка датчиков кислорода:
      - амплитуда и период переключения управляющего ДК1;
      - контроль перехода в замкнутый цикл (Closed Loop) на прогретом моторе (>= 65 °C);
      - уровень диагностического ДК2 и сопротивление нагревателя ДК1.
    """
    o2_1_all = col_vals(table, COL["O2_1"])
    o2_2_all = col_vals(table, COL["O2_2"])
    o2_period_all = col_vals(table, COL["O2_PERIOD"])
    o2_fb_all = col_vals(table, COL["O2_FB1"])
    ect_all = col_vals(table, COL["ECT"])
    fr_all = col_vals(table, COL["FR"])
    o2_res1_all = col_vals(table, COL["O2_RES1"])

    o2_1 = sub(o2_1_all, hot_idle_idx) or sub(o2_1_all, run_idx)
    o2_2 = sub(o2_2_all, hot_idle_idx) or sub(o2_2_all, run_idx)
    if not o2_1:
        return None

    o1_min, o1_max = min(o2_1), max(o2_1)
    span1 = o1_max - o1_min

    # Контроль входа в Closed Loop на прогретом моторе (>= 65 °C)
    warm_run_idx = [
        i for i in run_idx
        if i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= 65.0
    ]
    cl_warm_cnt = sum(
        1 for i in warm_run_idx
        if i < len(o2_fb_all) and o2_fb_all[i] == 1
    )
    cl_pct = (cl_warm_cnt / len(warm_run_idx) * 100.0) if warm_run_idx else None

    cl_entry_ect = None
    for i in run_idx:
        if i < len(o2_fb_all) and o2_fb_all[i] == 1:
            if i < len(ect_all) and ect_all[i] is not None:
                cl_entry_ect = ect_all[i]
            break

    warm_frs = sub(fr_all, warm_run_idx)
    fr_frozen = bool(warm_frs) and max(abs(x - 1.0) for x in warm_frs) < 0.002

    # Оценка периода переключения ДК1 в замкнутом цикле
    cl_idle_idx = [
        i for i in hot_idle_idx
        if (not o2_fb_all or (i < len(o2_fb_all) and o2_fb_all[i] == 1))
        and i < len(o2_period_all) and o2_period_all[i] is not None and o2_period_all[i] > 0.05
    ]
    cl_warm_per_idx = [
        i for i in warm_run_idx
        if (not o2_fb_all or (i < len(o2_fb_all) and o2_fb_all[i] == 1))
        and i < len(o2_period_all) and o2_period_all[i] is not None and o2_period_all[i] > 0.05
    ]
    period_idxs = cl_idle_idx if len(cl_idle_idx) >= 10 else cl_warm_per_idx
    periods = [o2_period_all[i] for i in period_idxs]

    med_per = statistics.median(periods) if periods else None
    max_per = max(periods) if periods else None

    warm_res1 = [
        o2_res1_all[i] for i in warm_run_idx
        if i < len(o2_res1_all) and o2_res1_all[i] is not None and o2_res1_all[i] > 0
    ]
    med_res1 = statistics.median(warm_res1) if warm_res1 else None

    no_closed_loop = bool(o2_fb_all) and len(warm_run_idx) >= 20 and cl_warm_cnt == 0
    weak_closed_loop = bool(o2_fb_all) and len(warm_run_idx) >= 20 and cl_pct is not None and cl_pct < 35.0

    if no_closed_loop or (fr_frozen and len(warm_run_idx) >= 20):
        st, badge = "status-bad", "НЕТ CLOSED LOOP"
    elif span1 < 0.25 or (med_per is not None and med_per > 2.4):
        st, badge = "status-bad", "ВЯЛЫЙ / ОТРАВЛЕН" if (med_per is not None and med_per > 2.4) else "ЗАВИС"
    elif weak_closed_loop:
        st, badge = "status-warn", "СБОЙ CLOSED LOOP"
    elif (med_per is not None and med_per > 1.6) or span1 < 0.45 or o1_min > 0.25 or o1_max < 0.65:
        st, badge = "status-warn", "СТАРЕНИЕ ДК1" if (med_per is not None and med_per > 1.6) else "ВЯЛЫЙ"
    else:
        st, badge = "status-ok", "АКТИВЕН"

    per_txt = f" | период {med_per:.2f} с" if med_per is not None else ""
    cl_txt = f" | CL: {cl_pct:.0f}%" if cl_pct is not None else ""
    o2_txt = f" | ДК2: {statistics.median(o2_2):.2f} В" if o2_2 else ""

    tooltip_lines = [
        f"Диапазон ДК1: {o1_min:.2f} .. {o1_max:.2f} В (размах {span1:.2f} В)",
    ]
    if cl_pct is not None:
        entry_s = f", первый вход при ТОЖ {cl_entry_ect:.1f}°C" if cl_entry_ect is not None else ""
        tooltip_lines.append(
            f"Замкнутый цикл (Closed Loop) при ТОЖ ≥ 65°C: {cl_warm_cnt}/{len(warm_run_idx)} кадр. ({cl_pct:.1f}%){entry_s}"
        )
    if fr_frozen and warm_frs:
        tooltip_lines.append("Внимание: коэффициент FR на прогретом моторе замер на 1.000 (коррекция отключена).")
    if med_per is not None:
        src_lbl = "на прогретом ХХ" if len(cl_idle_idx) >= 10 else "в замкнутом цикле"
        tooltip_lines.append(
            f"Период переключения ДК1 ({src_lbl}, {len(periods)} кадр.): медиана {med_per:.2f} с, макс {max_per:.2f} с"
        )
    if med_res1 is not None:
        tooltip_lines.append(f"Сопротивление нагревателя ДК1 (прогрет): мед. {med_res1:.0f} Ом")
    if o2_2:
        tooltip_lines.append(
            f"Диагностический ДК2: медиана {statistics.median(o2_2):.2f} В ({min(o2_2):.2f}..{max(o2_2):.2f} В)"
        )

    return {
        "title": "Датчики кислорода",
        "badge": badge,
        "status": st,
        "val": f"ДК1: {o1_min:.2f}..{o1_max:.2f} В{per_txt}{cl_txt}{o2_txt}",
        "norm": "Норма ДК1: 0.10..0.85 В, период ≤ 1.6 с, CL > 70% на прогретом",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_purge_valve(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Анализирует работу клапана продувки адсорбера (КПА) и его влияние на коррекцию смеси FR."""
    purge_all = col_vals(table, COL["PURGE"])
    if not purge_all or not run_idx:
        return None

    ect_all = col_vals(table, COL["ECT"])
    purge_flag_all = col_vals(table, COL["PURGE_FLAG"])
    fr_all = col_vals(table, COL["FR"])
    o2_fb_all = col_vals(table, COL["O2_FB1"])

    warm_run_idx = [
        i for i in run_idx
        if i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= 65.0
        and i < len(purge_all) and purge_all[i] is not None
    ]
    if not warm_run_idx:
        return {
            "title": "Продувка адсорбера",
            "badge": "НЕ ПРОГРЕТ",
            "status": "status-na",
            "val": "Двигатель не прогрет до 65 °C (продувка закрыта)",
            "norm": "Активация при ТОЖ > 60 °C и замкнутой ОС по ДК1",
        }

    purge_vals = [purge_all[i] for i in warm_run_idx]
    max_purge = max(purge_vals)
    active_idx = [i for i in warm_run_idx if purge_all[i] > 2.0]
    closed_idx = [i for i in warm_run_idx if purge_all[i] <= 0.5]
    active_pct = (len(active_idx) / len(warm_run_idx)) * 100.0

    flag_active_cnt = sum(
        1 for i in warm_run_idx
        if i < len(purge_flag_all) and purge_flag_all[i] == 1
    )

    fr_closed = sub(fr_all, closed_idx)
    fr_active = sub(fr_all, active_idx)
    fr_heavy = [
        fr_all[i] for i in warm_run_idx
        if purge_all[i] >= 25.0 and i < len(fr_all) and fr_all[i] is not None
    ]

    o2_fb_ok = any(
        i < len(o2_fb_all) and o2_fb_all[i] == 1
        for i in warm_run_idx
    )

    if not active_idx and flag_active_cnt == 0:
        if not o2_fb_ok and o2_fb_all:
            return {
                "title": "Продувка адсорбера",
                "badge": "НЕТ ОС ДК1",
                "status": "status-warn",
                "val": "Продувка 0% (нет замкнутого цикла по ДК1)",
                "norm": "Для запуска продувки нужна активная ОС по ДК1",
            }
        return {
            "title": "Продувка адсорбера",
            "badge": "НЕ ВКЛЮЧАЛАСЬ",
            "status": "status-warn",
            "val": f"Макс. скважность 0% на прогретом моторе ({len(warm_run_idx)} кадр.)",
            "norm": "На прогретом моторе КПА должен периодически открываться",
        }

    med_active = statistics.median([purge_all[i] for i in active_idx]) if active_idx else 0.0
    fr_info = ""
    delta_fr = None
    min_fr_heavy = min(fr_heavy) if fr_heavy else None

    if fr_closed and fr_active:
        med_fr_c = statistics.median(fr_closed)
        med_fr_a = statistics.median(fr_active)
        delta_fr = med_fr_a - med_fr_c
        fr_info = f" | FR: {med_fr_c:.3f} → {med_fr_a:.3f} ({delta_fr:+.3f})"
    elif fr_active:
        med_fr_a = statistics.median(fr_active)
        fr_info = f" | FR при продувке: {med_fr_a:.3f}"

    if (delta_fr is not None and delta_fr > 0.10) or (min_fr_heavy is not None and min_fr_heavy < 0.76):
        st, badge = "status-bad", "СБОЙ СМЕСИ"
        note = "Подсос воздуха через КПА" if (delta_fr is not None and delta_fr > 0.10) else "Переобогащение парами бака"
        val_txt = f"Скважность: мед. {med_active:.0f}%, макс {max_purge:.0f}%{fr_info} ({note})"
    elif (delta_fr is not None and abs(delta_fr) > 0.06) or (min_fr_heavy is not None and min_fr_heavy < 0.82):
        st, badge = "status-warn", "ВЛИЯНИЕ НА FR"
        val_txt = f"Скважность: мед. {med_active:.0f}%, макс {max_purge:.0f}% ({active_pct:.0f}% вр.){fr_info}"
    else:
        st, badge = "status-ok", "НОРМА"
        val_txt = f"Скважность: мед. {med_active:.0f}%, макс {max_purge:.0f}% ({active_pct:.0f}% вр.){fr_info}"

    tooltip = (
        f"Кадров на прогретом моторе (≥65°C): {len(warm_run_idx)}\n"
        f"Продувка активна (>2%): {len(active_idx)} кадр. ({active_pct:.1f}%)\n"
        f"Максимальная скважность КПА: {max_purge:.1f}%\n"
        "Нормальная реакция: при продувке богатых паров FR плавно снижается в пределах -0.02..-0.08."
    )

    return {
        "title": "Продувка адсорбера",
        "badge": badge,
        "status": st,
        "val": val_txt,
        "norm": "Норма: циклическая работа КПА, сдвиг FR в пределах ±0.06",
        "tooltip": tooltip,
    }


def check_catalyst_efficiency(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Оценка эффективности катализатора по сигналу ДК2 и встроенному индексу амплитуды ЭБУ."""
    o2_2_all = col_vals(table, COL["O2_2"])
    amp_idx_all = col_vals(table, COL["CAT_AMP_IDX"])
    if not o2_2_all and not amp_idx_all:
        return None

    ect_all = col_vals(table, COL["ECT"])
    ready2_all = col_vals(table, COL["O2_READY2"])
    fb2_all = col_vals(table, COL["O2_FB2"])

    warm_idx = [
        i for i in run_idx
        if i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= 70.0
    ]
    target_idx = warm_idx if warm_idx else run_idx
    if not target_idx:
        return None

    o2_2 = sub(o2_2_all, target_idx)
    amps = sub(amp_idx_all, target_idx)
    if not o2_2 and not amps:
        return None

    ready2_any = any(i < len(ready2_all) and ready2_all[i] == 1 for i in target_idx)
    fb2_any = any(i < len(fb2_all) and fb2_all[i] == 1 for i in target_idx)

    o2_min = min(o2_2) if o2_2 else None
    o2_max = max(o2_2) if o2_2 else None
    o2_med = statistics.median(o2_2) if o2_2 else None
    span2 = (o2_max - o2_min) if (o2_min is not None and o2_max is not None) else 0.0
    last_amp = amps[-1] if amps else None
    max_amp = max(amps) if amps else None

    if not ready2_any and not fb2_any and span2 < 0.08 and o2_med is not None and 0.40 <= o2_med <= 0.50:
        return {
            "title": "Эффективность катализатора",
            "badge": "ЕВРО-2 / НЕТ ДК2",
            "status": "status-na",
            "val": f"ДК2 на опорном уровне {o2_med:.2f} В (диагностика отключена)",
            "norm": "Прошивка без контроля катализатора или ДК2 не активен",
        }

    if (last_amp is not None and last_amp >= 0.72) or (span2 >= 0.55 and (o2_min is not None and o2_min < 0.25)):
        st, badge = "status-bad", "ИЗНОС КАТ."
    elif (last_amp is not None and last_amp >= 0.52) or span2 >= 0.36:
        st, badge = "status-warn", "СНИЖЕНИЕ"
    else:
        st, badge = "status-ok", "НОРМА"

    parts = []
    if o2_min is not None and o2_max is not None:
        parts.append(f"ДК2: {o2_min:.2f}..{o2_max:.2f} В (мед. {o2_med:.2f} В)")
    if last_amp is not None:
        parts.append(f"Индекс ампл.: {last_amp:.2f}")

    tooltip_lines = []
    if o2_med is not None:
        tooltip_lines.append(f"Напряжение ДК2 на прогретом моторе: мед. {o2_med:.3f} В, размах {span2:.3f} В")
    if last_amp is not None:
        tooltip_lines.append(f"Индекс амплитуды ЭБУ (приведённый к 1): текущ. {last_amp:.3f}, пик {max_amp:.3f}")
    tooltip_lines.append(f"Готовность ДК2: {'да' if ready2_any else 'нет'} | ОС по ДК2: {'активна' if fb2_any else 'нет'}")

    return {
        "title": "Эффективность катализатора",
        "badge": badge,
        "status": st,
        "val": " | ".join(parts),
        "norm": "Норма: ДК2 0.55–0.80 В (размах ≤ 0.35 В), индекс < 0.50",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_injectors_and_fuel_supply(table: pa.Table, valid_idx: list[int], run_idx: list[int]) -> dict | None:
    """Проверка загрузки форсунок (%) и косвенная оценка давления топлива по FR под нагрузкой."""
    duty_all = col_vals(table, COL["INJ_DUTY"])
    fr_all = col_vals(table, COL["FR"])
    tps_all = col_vals(table, COL["TPS"])
    rpm_all = col_vals(table, COL["RPM"])
    full_load_all = col_vals(table, COL["FULL_LOAD"])
    times_raw = col_vals(table, COL["TIME"])

    if not duty_all or not run_idx:
        return None

    duties = sub(duty_all, run_idx)
    if not duties:
        return None

    peak_duty = max(duties)
    med_duty = statistics.median(duties)

    best_i = max(
        (i for i in run_idx if i < len(duty_all) and duty_all[i] is not None),
        key=lambda idx: duty_all[idx],
    )
    peak_rpm = rpm_all[best_i] if best_i < len(rpm_all) and rpm_all[best_i] is not None else None
    peak_tps = tps_all[best_i] if best_i < len(tps_all) and tps_all[best_i] is not None else None
    peak_t = times_raw[best_i] if best_i < len(times_raw) and times_raw[best_i] is not None else None
    peak_fr = fr_all[best_i] if best_i < len(fr_all) and fr_all[best_i] is not None else None

    high_load_idx = [
        i for i in run_idx
        if (
            (i < len(full_load_all) and full_load_all[i] == 1)
            or (
                i < len(tps_all) and tps_all[i] is not None and tps_all[i] >= 55.0
                and i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] >= 2500
            )
        )
    ]
    load_frs = sub(fr_all, high_load_idx)
    med_load_fr = statistics.median(load_frs) if load_frs else None
    max_load_fr = max(load_frs) if load_frs else None

    if peak_duty >= 90.0 or (med_load_fr is not None and med_load_fr >= 1.15):
        st, badge = "status-bad", "ДЕФИЦИТ ТОПЛИВА" if (med_load_fr is not None and med_load_fr >= 1.15) else "ПЕРЕГРУЗ ФОРС."
    elif peak_duty >= 80.0 or (med_load_fr is not None and med_load_fr >= 1.09):
        st, badge = "status-warn", "ВЫСОКАЯ ЗАГР."
    else:
        st, badge = "status-ok", "НОРМА"

    fr_load_txt = f" | FR под нагр.: {med_load_fr:.3f}" if med_load_fr is not None else ""
    val_txt = f"Пик загрузки форс: {peak_duty:.1f}% (мед. {med_duty:.1f}%){fr_load_txt}"

    tooltip_lines = [
        f"Максимальная загрузка форсунок: {peak_duty:.1f}% (на {peak_t:.1f} с)" if peak_t is not None else f"Максимальная загрузка форсунок: {peak_duty:.1f}%",
    ]
    ctx_parts = []
    if peak_rpm is not None:
        ctx_parts.append(f"обороты {peak_rpm} об/мин")
    if peak_tps is not None:
        ctx_parts.append(f"дроссель {peak_tps:.0f}%")
    if peak_fr is not None:
        ctx_parts.append(f"FR {peak_fr:.3f}")
    if ctx_parts:
        tooltip_lines.append("Условия на пике: " + ", ".join(ctx_parts))
    if load_frs:
        tooltip_lines.append(
            f"Коррекция FR под нагрузкой ({len(load_frs)} кадр.): мед. {med_load_fr:.3f}, макс. {max_load_fr:.3f}"
        )

    return {
        "title": "Форсунки и топливоподача",
        "badge": badge,
        "status": st,
        "val": val_txt,
        "norm": "Норма: пик загрузки ≤ 80%, FR под нагрузкой 0.92–1.08",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_mixture_differential(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict | None:
    """
    Дифференциальный баланс смеси: сравнение коррекции FR на прогретом ХХ
    против повышенных оборотов (1500..3200 об/мин) для разделения подсоса воздуха и нехватки топлива.
    """
    fr_all = col_vals(table, COL["FR"])
    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    fcut_all = col_vals(table, COL["FCUT"])
    o2_fb_all = col_vals(table, COL["O2_FB1"])
    full_load_all = col_vals(table, COL["FULL_LOAD"])

    if not fr_all or not run_idx:
        return None

    idle_cl_idx = [
        i for i in hot_idle_idx
        if i < len(fr_all) and fr_all[i] is not None
        and (not o2_fb_all or (i < len(o2_fb_all) and o2_fb_all[i] == 1))
    ]
    mid_rpm_idx = [
        i for i in run_idx
        if i < len(fr_all) and fr_all[i] is not None
        and i < len(rpm_all) and rpm_all[i] is not None and 1500 <= rpm_all[i] <= 3200
        and i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= 70.0
        and (i >= len(fcut_all) or fcut_all[i] != 1)
        and (i >= len(full_load_all) or full_load_all[i] != 1)
        and (not o2_fb_all or (i < len(o2_fb_all) and o2_fb_all[i] == 1))
    ]

    if len(idle_cl_idx) < 5 or len(mid_rpm_idx) < 5:
        return {
            "title": "Баланс смеси: ХХ vs 1500+",
            "badge": "МАЛО ДАННЫХ",
            "status": "status-na",
            "val": f"Кадров в замкнутом цикле: ХХ={len(idle_cl_idx)}, 1500+={len(mid_rpm_idx)}",
            "norm": "Норма: FR на ХХ и при 1500+ об/мин в пределах 0.94–1.06",
        }

    fr_idle_med = statistics.median([fr_all[i] for i in idle_cl_idx])
    fr_mid_med = statistics.median([fr_all[i] for i in mid_rpm_idx])
    diff = fr_mid_med - fr_idle_med

    if fr_idle_med >= 1.10 and diff <= -0.055 and fr_mid_med <= 1.065:
        st, badge = "status-bad", "ПОДСОС НА ХХ"
    elif fr_idle_med >= 1.07 and diff <= -0.045 and fr_mid_med <= 1.065:
        st, badge = "status-warn", "ПОДСОС НА ХХ"
    elif fr_mid_med >= 1.11 and fr_idle_med >= 1.06:
        st, badge = "status-bad", "ДЕФИЦИТ ТОПЛИВА"
    elif fr_mid_med >= 1.08 and fr_idle_med >= 1.05:
        st, badge = "status-warn", "ДЕФИЦИТ ТОПЛИВА"
    elif fr_idle_med <= 0.90 and fr_mid_med <= 0.91:
        st, badge = "status-bad", "БОГАТАЯ СМЕСЬ"
    elif fr_idle_med <= 0.93 and fr_mid_med <= 0.93:
        st, badge = "status-warn", "БОГАТАЯ СМЕСЬ"
    else:
        st, badge = "status-ok", "СБАЛАНСИРОВАН"

    tooltip_lines = [
        f"Медиана FR на прогретом ХХ ({len(idle_cl_idx)} кадр.): {fr_idle_med:.3f} ({(fr_idle_med - 1.0) * 100.0:+.1f}%)",
        f"Медиана FR при 1500–3200 об/мин ({len(mid_rpm_idx)} кадр.): {fr_mid_med:.3f} ({(fr_mid_med - 1.0) * 100.0:+.1f}%)",
        f"Сдвиг FR при переходе с ХХ на обороты: {diff:+.3f}",
        "Интерпретация: падение завышенного FR на 1500+ об/мин указывает на подсос воздуха; сохранение высокого FR — на нехватку топлива или занижение ДМРВ.",
    ]

    return {
        "title": "Баланс смеси: ХХ vs 1500+",
        "badge": badge,
        "status": st,
        "val": f"FR ХХ: {fr_idle_med:.3f} → 1500+: {fr_mid_med:.3f} ({diff:+.3f})",
        "norm": "Норма: FR 0.94–1.06 на обоих режимах (перепад < 0.045)",
        "tooltip": "\n".join(tooltip_lines),
    }
