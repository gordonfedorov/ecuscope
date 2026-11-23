#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks_air.py — диагностика воздушного тракта и режимов холостого хода (Bosch M7.9.7):
  - Калибровка нуля ДПДЗ, напряжение АЦП ДПДЗ в покое, износ/шум дорожек и отсечка на ПХХ;
  - Позиция шагового двигателя РХХ и диагностика подсоса воздуха / загрязнения дросселя;
  - Напряжение АЦП ДМРВ в покое (до пуска) и динамический отклик расхода воздуха по дросселю.
"""

import statistics
import pyarrow as pa
from diagnose_utils import COL, col_vals, sub


def check_dfco_and_tps(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict | None:
    """
    Проверка датчика положения дроссельной заслонки (ДПДЗ) и отсечки топливоподачи на ПХХ:
      - калибровка нуля ДПДЗ (%);
      - напряжение АЦП ДПДЗ при закрытой заслонке (норма 0.35–0.70 В);
      - детектор износа (резких провалов/шума) резистивных дорожек ДПДЗ при движении заслонки;
      - срабатывание отсечки топливоподачи на принудительном холостом ходу (ПХХ).
    """
    tps_all = col_vals(table, COL["TPS"])
    adc_tps_all = col_vals(table, COL["ADC_TPS"])
    rpm_all = col_vals(table, COL["RPM"])
    spd_all = col_vals(table, COL["SPD"])
    ect_all = col_vals(table, COL["ECT"])
    fcut_all = col_vals(table, COL["FCUT"])
    inj_all = col_vals(table, COL["INJ"])
    times_raw = col_vals(table, COL["TIME"])

    tps_vals = sub(tps_all, valid_idx)
    if not tps_vals:
        return None

    tps_min = min(tps_vals)
    tps_max = max(tps_vals)

    # 1. Напряжение АЦП ДПДЗ при закрытой заслонке
    closed_adc_vals = [
        adc_tps_all[i] for i in valid_idx
        if i < len(tps_all) and tps_all[i] is not None and tps_all[i] <= max(0.5, tps_min + 0.2)
        and i < len(adc_tps_all) and adc_tps_all[i] is not None and adc_tps_all[i] > 0.05
    ]
    adc_tps_med = statistics.median(closed_adc_vals) if closed_adc_vals else None

    # 2. Детектор шума / износа дорожек ДПДЗ (резкие локальные провалы "V" или пики "^" на 1 кадр)
    spike_events = []
    for k in range(1, len(valid_idx) - 1):
        i0, i1, i2 = valid_idx[k - 1], valid_idx[k], valid_idx[k + 1]
        if i2 >= len(tps_all):
            break
        v0, v1, v2 = tps_all[i0], tps_all[i1], tps_all[i2]
        if v0 is None or v1 is None or v2 is None:
            continue
        if i2 < len(times_raw) and times_raw[i0] is not None and times_raw[i2] is not None:
            if (times_raw[i2] - times_raw[i0]) > 2.5:
                continue
        # Если соседние кадры близки (разница < 4%), а средний резко провалился или выстрелил (> 7%)
        if abs(v2 - v0) <= 4.0:
            mid = 0.5 * (v0 + v2)
            dev = abs(v1 - mid)
            if dev >= 7.0 and max(v0, v1, v2) >= 3.0:
                t_s = times_raw[i1] if i1 < len(times_raw) else None
                spike_events.append((t_s, v0, v1, v2))

    # 3. Проверка отсечки топливоподачи на ПХХ
    episodes = []
    cur_ep = None

    for i in valid_idx:
        tps = tps_all[i] if i < len(tps_all) else None
        rpm = rpm_all[i] if i < len(rpm_all) else None
        spd = spd_all[i] if i < len(spd_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        fcut = fcut_all[i] if i < len(fcut_all) else 0
        inj = inj_all[i] if i < len(inj_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None

        is_dfco_cond = (
            tps is not None and tps <= max(0.5, tps_min + 0.4)
            and rpm is not None and rpm >= 2000
            and spd is not None and spd >= 15.0
            and ect is not None and ect >= 55.0
            and t_cur is not None
        )

        if is_dfco_cond:
            if cur_ep is None:
                cur_ep = {
                    "t0": t_cur,
                    "t_last": t_cur,
                    "max_rpm": rpm,
                    "fcut_hits": 1 if fcut == 1 else 0,
                    "frames": 1,
                    "min_inj": inj,
                }
            else:
                cur_ep["t_last"] = t_cur
                cur_ep["frames"] += 1
                if rpm > cur_ep["max_rpm"]:
                    cur_ep["max_rpm"] = rpm
                if fcut == 1:
                    cur_ep["fcut_hits"] += 1
                if inj is not None and (cur_ep["min_inj"] is None or inj < cur_ep["min_inj"]):
                    cur_ep["min_inj"] = inj
        else:
            if cur_ep is not None:
                dur = cur_ep["t_last"] - cur_ep["t0"]
                if dur >= 1.8 and cur_ep["frames"] >= 2:
                    cur_ep["dur"] = dur
                    episodes.append(cur_ep)
                cur_ep = None

    if cur_ep is not None:
        dur = cur_ep["t_last"] - cur_ep["t0"]
        if dur >= 1.8 and cur_ep["frames"] >= 2:
            cur_ep["dur"] = dur
            episodes.append(cur_ep)

    total_fcut_sec = 0.0
    fcut_injs = []
    for pos in range(len(valid_idx) - 1):
        i0 = valid_idx[pos]
        i1 = valid_idx[pos + 1]
        if i0 < len(fcut_all) and fcut_all[i0] == 1:
            if i0 < len(inj_all) and inj_all[i0] is not None:
                fcut_injs.append(inj_all[i0])
            if i0 < len(times_raw) and i1 < len(times_raw) and times_raw[i0] is not None and times_raw[i1] is not None:
                dt = times_raw[i1] - times_raw[i0]
                if 0.0 < dt < 5.0:
                    total_fcut_sec += dt

    triggered_eps = [ep for ep in episodes if ep["fcut_hits"] > 0 or (ep["min_inj"] is not None and ep["min_inj"] <= 0.1)]
    missed_eps = [ep for ep in episodes if ep not in triggered_eps]

    adc_bad = adc_tps_med is not None and (adc_tps_med < 0.25 or adc_tps_med > 0.85)
    adc_warn = adc_tps_med is not None and (adc_tps_med < 0.35 or adc_tps_med > 0.72)

    if tps_min > 1.2 or adc_bad:
        status, badge = "status-bad", "СБИТ НОЛЬ ДПДЗ"
    elif len(spike_events) >= 3:
        status, badge = "status-bad", "ИЗНОС ДПДЗ"
    elif tps_min > 0.45 or adc_warn:
        status, badge = "status-warn", "СДВИГ ДПДЗ"
    elif spike_events:
        status, badge = "status-warn", "ШУМ ДПДЗ"
    elif episodes and not triggered_eps:
        status, badge = "status-bad", "НЕТ ОТСЕЧКИ ПХХ"
    elif missed_eps:
        status, badge = "status-warn", "ЧАСТИЧНО ПХХ"
    else:
        status, badge = "status-ok", "НОРМА"

    if episodes:
        ep_str = f"ПХХ: {len(triggered_eps)}/{len(episodes)} ({total_fcut_sec:.1f} с)"
    elif total_fcut_sec > 0:
        ep_str = f"ПХХ: {total_fcut_sec:.1f} с"
    else:
        ep_str = "ПХХ: нет накатов"

    adc_str = f" | АЦП: {adc_tps_med:.2f} В" if adc_tps_med is not None else ""
    noise_str = f" | скачки: {len(spike_events)}" if spike_events else ""

    tooltip_lines = [
        f"Диапазон ДПДЗ: {tps_min:.2f}% .. {tps_max:.2f}%",
    ]
    if adc_tps_med is not None:
        tooltip_lines.append(
            f"Напряжение АЦП ДПДЗ при закрытой заслонке ({len(closed_adc_vals)} кадр.): мед. {adc_tps_med:.3f} В (норма 0.35–0.70 В)"
        )
    if spike_events:
        tooltip_lines.append(f"Обнаружены резкие выбросы сигнала ДПДЗ ({len(spike_events)} шт., признак износа дорожек):")
        for t_s, v0, v1, v2 in spike_events[:5]:
            t_lbl = f"{t_s:.1f} с" if t_s is not None else "?"
            tooltip_lines.append(f"  • {t_lbl}: {v0:.1f}% → {v1:.1f}% → {v2:.1f}%")
    tooltip_lines.append(f"Суммарное время в отсечке топлива: {total_fcut_sec:.1f} с")
    if fcut_injs:
        tooltip_lines.append(f"Медиана впрыска при отсечке: {statistics.median(fcut_injs):.2f} мс")
    for idx_e, ep in enumerate(episodes, 1):
        ok_lbl = "отсечка ВКЛ" if ep in triggered_eps else "НЕ сработала"
        inj_lbl = f", мин. впрыск {ep['min_inj']:.2f} мс" if ep["min_inj"] is not None else ""
        tooltip_lines.append(
            f"Накат #{idx_e} (на {ep['t0']:.1f} с, {ep['dur']:.1f} с, до {ep['max_rpm']} об/мин): {ok_lbl}{inj_lbl}"
        )

    return {
        "title": "ДПДЗ и отсечка ПХХ",
        "badge": badge,
        "status": status,
        "val": f"Ноль: {tps_min:.2f}%{adc_str}{noise_str} | {ep_str}",
        "norm": "Норма: ноль 0.00%, АЦП 0.35–0.70 В, без скачков, отсечка на ПХХ",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_iac_and_air_leak(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict | None:
    """
    Диагностика подсоса воздуха и загрязнения дроссельного узла по РХХ и адаптации ХХ.
    """
    iac_all = col_vals(table, COL["IAC"])
    if not iac_all:
        return None

    ect_all = col_vals(table, COL["ECT"])
    rpm_all = col_vals(table, COL["RPM"])
    tps_all = col_vals(table, COL["TPS"])
    idle_flag = col_vals(table, COL["IDLE"])
    fcut_flag = col_vals(table, COL["FCUT"])
    iac_adapt_all = col_vals(table, COL["IAC_ADAPT"])
    maf_all = col_vals(table, COL["MAF"])
    des_air_all = col_vals(table, COL["DES_AIR"])

    if hot_idle_idx is None:
        hot_idle_idx = [
            i for i in valid_idx
            if i < len(rpm_all) and rpm_all[i] is not None and 450 <= rpm_all[i] <= 1150
            and (i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= 75.0)
            and (i >= len(fcut_flag) or fcut_flag[i] != 1)
            and (
                (i < len(idle_flag) and idle_flag[i] == 1)
                or (i < len(tps_all) and tps_all[i] is not None and tps_all[i] < 1.5)
            )
        ]

    iac_idle = sub(iac_all, hot_idle_idx)
    if not iac_idle:
        return {
            "title": "РХХ и подсос воздуха",
            "badge": "НЕТ ДАННЫХ",
            "status": "status-na",
            "val": "Нет кадров прогретого ХХ (≥75 °C) для оценки РХХ",
            "norm": "Норма РХХ (прогрет): 25 – 52 шаг, адаптация ±5%",
        }

    iac_med = statistics.median(iac_idle)
    iac_min = min(iac_idle)
    iac_max = max(iac_idle)

    adapt_vals = sub(iac_adapt_all, hot_idle_idx) or sub(iac_adapt_all, valid_idx)
    adapt_last = adapt_vals[-1] if adapt_vals else None

    maf_idle = sub(maf_all, hot_idle_idx)
    des_idle = sub(des_air_all, hot_idle_idx)
    air_diff = None
    if maf_idle and des_idle:
        air_diff = statistics.median(maf_idle) - statistics.median(des_idle)

    if iac_med <= 18 or (adapt_last is not None and adapt_last <= -7.5):
        st, badge = "status-bad", "ПОДСОС ВОЗДУХА"
    elif iac_med >= 62 or (adapt_last is not None and adapt_last >= 7.5):
        st, badge = "status-bad", "ГРЯЗНЫЙ ДРОССЕЛЬ"
    elif iac_med <= 23 or (adapt_last is not None and adapt_last <= -4.5):
        st, badge = "status-warn", "ВОЗМОЖЕН ПОДСОС"
    elif iac_med >= 54 or (adapt_last is not None and adapt_last >= 4.5):
        st, badge = "status-warn", "ЗАГРЯЗНЕНИЕ ДУ"
    else:
        st, badge = "status-ok", "НОРМА"

    adapt_txt = f" | Адаптация ХХ: {adapt_last:+.1f}%" if adapt_last is not None else ""
    val_txt = f"РХХ на ХХ: {iac_med:.0f} шаг ({iac_min}..{iac_max}){adapt_txt}"

    tooltip_lines = [
        f"Позиция шагового двигателя РХХ на прогретом ХХ ({len(iac_idle)} кадр.): мед. {iac_med:.1f} шаг (диапазон {iac_min}..{iac_max})",
    ]
    if adapt_last is not None:
        tooltip_lines.append(f"Параметр адаптации регулировки ХХ: {adapt_last:+.2f}%")
    if air_diff is not None:
        tooltip_lines.append(
            f"Расход воздуха на ХХ: факт {statistics.median(maf_idle):.2f} кг/ч vs желаемый {statistics.median(des_idle):.2f} кг/ч ({air_diff:+.2f} кг/ч)"
        )
    tooltip_lines.append("Низкий шаг РХХ (<22) указывает на неучтённый подсос воздуха; высокий (>55) — на загрязнение дроссельного узла.")

    return {
        "title": "РХХ и подсос воздуха",
        "badge": badge,
        "status": st,
        "val": val_txt,
        "norm": "Норма РХХ (прогрет): 25 – 52 шаг, адаптация ±4.5%",
        "tooltip": "\n".join(tooltip_lines),
    }


def check_maf_throttle_response(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
) -> dict | None:
    """
    Проверка состояния ДМРВ по напряжению АЦП в покое (до пуска)
    и динамическому отклику расхода воздуха при открытии дросселя.
    """
    maf_all = col_vals(table, COL["MAF"])
    adc_maf_all = col_vals(table, COL["ADC_MAF"])
    tps_all = col_vals(table, COL["TPS"])
    rpm_all = col_vals(table, COL["RPM"])

    if not maf_all and not adc_maf_all:
        return None

    # 1. Напряжение АЦП ДМРВ в покое (при включённом зажигании до запуска двигателя)
    rest_adcs = []
    for i in valid_idx:
        rpm = rpm_all[i] if i < len(rpm_all) else None
        adc = adc_maf_all[i] if i < len(adc_maf_all) else None
        if rpm is None or adc is None:
            continue
        if rpm == 0 and adc > 0.1:
            rest_adcs.append(adc)
        elif rpm > 0:
            break

    adc_rest_med = statistics.median(rest_adcs) if rest_adcs else None

    # 2. Отклик расхода воздуха при открытии дросселя >= 20%
    open_tps_idx = [
        i for i in run_idx
        if i < len(tps_all) and tps_all[i] is not None and tps_all[i] >= 20.0
        and i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] >= 1500
        and i < len(maf_all) and maf_all[i] is not None
    ]
    open_mafs = [maf_all[i] for i in open_tps_idx]

    # Низкий расход воздуха при заметно открытом дросселе (>= 25%) и оборотах >= 2000
    sluggish_idx = [
        i for i in open_tps_idx
        if tps_all[i] >= 25.0 and rpm_all[i] >= 2000 and maf_all[i] < 35.0
    ]

    if adc_rest_med is None and not open_mafs:
        return None

    if adc_rest_med is not None and adc_rest_med >= 1.06:
        st, badge = "status-bad", "ИЗНОС ДМРВ"
    elif sluggish_idx and len(sluggish_idx) >= 3:
        st, badge = "status-bad", "СЛАБЫЙ ОТКЛИК"
    elif adc_rest_med is not None and adc_rest_med >= 1.035:
        st, badge = "status-warn", "СТАРЕНИЕ ДМРВ"
    elif sluggish_idx:
        st, badge = "status-warn", "ЗАНИЖЕН ДМРВ"
    else:
        st, badge = "status-ok", "НОРМА"

    parts = []
    if adc_rest_med is not None:
        parts.append(f"АЦП покой: {adc_rest_med:.3f} В")
    if open_mafs:
        parts.append(f"При ДПДЗ≥20%: мед. {statistics.median(open_mafs):.1f} кг/ч (пик {max(open_mafs):.1f})")

    tooltip_lines = []
    if adc_rest_med is not None:
        tooltip_lines.append(
            f"Напряжение АЦП ДМРВ до пуска ({len(rest_adcs)} кадр.): мед. {adc_rest_med:.3f} В (эталон Bosch HFM5: 0.996–1.020 В)"
        )
    else:
        tooltip_lines.append("Кадров в покое до пуска (0 об/мин) нет — АЦП покоя ДМРВ не зафиксирован.")
    if open_mafs:
        tooltip_lines.append(
            f"Расход воздуха при открытии дросселя ≥ 20% ({len(open_mafs)} кадр.): мед. {statistics.median(open_mafs):.1f} кг/ч, макс {max(open_mafs):.1f} кг/ч"
        )
    if sluggish_idx:
        tooltip_lines.append(f"Кадров с провалом расхода (<35 кг/ч при ДПДЗ ≥ 25% и ≥ 2000 об/мин): {len(sluggish_idx)}")

    return {
        "title": "Отклик ДМРВ и АЦП",
        "badge": badge,
        "status": st,
        "val": " | ".join(parts),
        "norm": "Норма: АЦП покоя 0.996–1.030 В; рост расхода при открытии ДПДЗ",
        "tooltip": "\n".join(tooltip_lines),
    }
