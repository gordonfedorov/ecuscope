"""
ECUScope — Здоровье мотора: проверки воздушного тракта, дросселя и холостого хода.
"""

from __future__ import annotations

import statistics
import pyarrow as pa

from diagnose_utils import COL, col_vals, sub


def _make_card(title: str, status: str, badge: str, val: str, norm: str, tooltip: str = "") -> dict:
    return {
        "title": title,
        "status": status,
        "badge": badge,
        "val": val,
        "norm": norm,
        "tooltip": tooltip,
    }


def check_dfco_and_tps(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """Проверка нуля ДПДЗ, АЦП покоя, износа дорожек и отсечки топливоподачи на ПХХ."""
    tps_all = col_vals(table, COL["TPS"])
    adc_tps_all = col_vals(table, COL["ADC_TPS"])
    rpm_all = col_vals(table, COL["RPM"])
    spd_all = col_vals(table, COL["SPD"])
    inj_all = col_vals(table, COL["INJ"])
    dfco_all = col_vals(table, COL["DFCO_FLAG"])
    idle_flag_all = col_vals(table, COL["IDLE_FLAG"])
    time_all = col_vals(table, COL["TIME"])

    tps_valid = sub(tps_all, valid_idx)
    if not tps_valid:
        return _make_card(
            "ДПДЗ и отсечка ПХХ",
            "status-na",
            "НЕТ ДАННЫХ",
            "Нет данных ДПДЗ",
            "Норма нуля: 0% | ПХХ: впрыск 0 мс",
        )

    tps_min = min(tps_valid)
    tps_max = max(tps_valid)

    # 1. Напряжение АЦП ДПДЗ на закрытом дросселе
    closed_adc = [
        adc_tps_all[i]
        for i in valid_idx
        if i < len(tps_all)
        and tps_all[i] is not None
        and tps_all[i] <= 0.5
        and i < len(adc_tps_all)
        and adc_tps_all[i] is not None
        and 0.05 <= adc_tps_all[i] <= 4.95
    ]
    adc_med = statistics.median(closed_adc) if closed_adc else None

    # 2. Детектор шума/провалов дорожек ДПДЗ (резкие однокадровые иголки)
    spike_events: list[str] = []
    for k in range(1, len(valid_idx) - 1):
        i_prev, i_cur, i_next = valid_idx[k - 1], valid_idx[k], valid_idx[k + 1]
        if i_next >= len(tps_all):
            break
        v0, v1, v2 = tps_all[i_prev], tps_all[i_cur], tps_all[i_next]
        if v0 is None or v1 is None or v2 is None:
            continue
        t_cur = time_all[i_cur] if i_cur < len(time_all) and time_all[i_cur] is not None else float(k)
        # Иголка: резкий уход от соседей более чем на 6% и возврат обратно
        if abs(v1 - v0) >= 6.0 and abs(v1 - v2) >= 6.0 and abs(v2 - v0) <= 3.5:
            spike_events.append(f"{t_cur:.1f}с ({v0:.1f}%->{v1:.1f}%->{v2:.1f}%)")

    # 3. Проверка флага ХХ при отпущенном дросселе
    closed_cnt = 0
    no_idle_flag_cnt = 0
    for i in valid_idx:
        tps = tps_all[i] if i < len(tps_all) else None
        idl = idle_flag_all[i] if i < len(idle_flag_all) else None
        if tps is not None and tps <= 0.2:
            closed_cnt += 1
            if idl is not None and idl < 0.5:
                no_idle_flag_cnt += 1

    # 4. Проверка отсечки ПХХ (торможение двигателем: ДПДЗ=0, скорость > 15 км/ч, обороты > 1700)
    coasting_cnt = 0
    dfco_active_cnt = 0
    for i in run_idx:
        tps = tps_all[i] if i < len(tps_all) else None
        rpm = rpm_all[i] if i < len(rpm_all) else None
        spd = spd_all[i] if i < len(spd_all) else None
        inj = inj_all[i] if i < len(inj_all) else None
        dfco = dfco_all[i] if i < len(dfco_all) else None
        if tps is not None and tps <= 0.5 and rpm is not None and rpm >= 1750 and spd is not None and spd >= 15.0:
            coasting_cnt += 1
            if (dfco is not None and dfco >= 0.5) or (inj is not None and inj <= 0.05):
                dfco_active_cnt += 1

    issues: list[str] = []
    warns: list[str] = []
    tips: list[str] = [
        f"Диапазон ДПДЗ: {tps_min:.1f}% .. {tps_max:.1f}%.",
    ]

    if tps_min > 1.0:
        issues.append(f"ДПДЗ не падает в 0% (мин. {tps_min:.1f}%)")
    elif tps_min > 0.2:
        warns.append(f"Сбит ноль ДПДЗ ({tps_min:.1f}%)")

    if adc_med is not None:
        tips.append(f"АЦП закрытого ДПДЗ: {adc_med:.3f} В (эталон 0.35–0.70 В).")
        if adc_med < 0.25 or adc_med > 0.85:
            issues.append(f"АЦП ДПДЗ вне нормы ({adc_med:.2f} В)")
        elif adc_med < 0.35 or adc_med > 0.72:
            warns.append(f"Сдвиг АЦП ДПДЗ ({adc_med:.2f} В)")

    if len(spike_events) >= 3:
        issues.append(f"Шум дорожек ДПДЗ ({len(spike_events)} скачков)")
        tips.append("Скачки ДПДЗ: " + ", ".join(spike_events[:5]))
    elif len(spike_events) >= 1:
        warns.append(f"Дребезг ДПДЗ ({len(spike_events)} раз)")
        tips.append("Скачки ДПДЗ: " + ", ".join(spike_events[:5]))

    if closed_cnt >= 20 and (no_idle_flag_cnt / closed_cnt) > 0.35:
        warns.append("ЭБУ не видит признак ХХ при ДПДЗ=0%")

    if coasting_cnt >= 8:
        dfco_pct = (dfco_active_cnt / coasting_cnt) * 100.0
        tips.append(f"Торможение двигателем (>1750 об/мин): {coasting_cnt} кадров, ПХХ сработала в {dfco_pct:.0f}%.")
        if dfco_pct < 20.0:
            warns.append("Не включается отсечка ПХХ")
    else:
        tips.append("Участков длительного торможения двигателем (>1750 об/мин) в логе мало.")

    adc_str = f" | АЦП {adc_med:.2f} В" if adc_med is not None else ""
    val_str = f"Мин. {tps_min:.1f}%{adc_str}"

    if issues:
        return _make_card(
            "ДПДЗ и отсечка ПХХ",
            "status-bad",
            "ПРОБЛЕМА",
            f"{val_str} [{issues[0]}]",
            "Норма нуля: 0% | АЦП: 0.35–0.70 В",
            " ".join(tips),
        )
    if warns:
        return _make_card(
            "ДПДЗ и отсечка ПХХ",
            "status-warn",
            "ВНИМАНИЕ",
            f"{val_str} [{warns[0]}]",
            "Норма нуля: 0% | АЦП: 0.35–0.70 В",
            " ".join(tips),
        )

    pkh_note = f" | ПХХ {int((dfco_active_cnt / coasting_cnt) * 100)}%" if coasting_cnt >= 8 else ""
    return _make_card(
        "ДПДЗ и отсечка ПХХ",
        "status-ok",
        "НОРМА",
        f"{val_str}{pkh_note}",
        "Норма нуля: 0% | АЦП: 0.35–0.70 В",
        " ".join(tips),
    )


def check_iac_and_air_leak(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """Проверка РХХ, подсоса воздуха, целевых оборотов, подхвата при сбросе и пиления ХХ."""
    iac_all = col_vals(table, COL["IAC"])
    rpm_all = col_vals(table, COL["RPM"])
    rpm_des_all = col_vals(table, COL["RPM_DESIRED"])
    tps_all = col_vals(table, COL["TPS"])
    spd_all = col_vals(table, COL["SPD"])
    ect_all = col_vals(table, COL["ECT"])
    time_all = col_vals(table, COL["TIME"])

    iac_hot = sub(iac_all, hot_idle_idx)
    rpm_hot = sub(rpm_all, hot_idle_idx)
    rpm_des_hot = sub(rpm_des_all, hot_idle_idx)

    if len(iac_hot) < 10 or len(rpm_hot) < 10:
        return _make_card(
            "РХХ и подсос воздуха",
            "status-na",
            "НЕТ ДАННЫХ",
            "Мало прогретого ХХ",
            "Норма РХХ на ХХ: 25–48 шагов",
            "Для анализа РХХ и стабильности ХХ нужен прогретый двигатель (>= 75 °C) на холостом ходу.",
        )

    iac_med = statistics.median(iac_hot)
    rpm_med = statistics.median(rpm_hot)
    rpm_des_med = statistics.median(rpm_des_hot) if len(rpm_des_hot) >= 5 else None

    # 1. Сверка фактических и желаемых оборотов ХХ
    rpm_diff = (rpm_med - rpm_des_med) if rpm_des_med is not None else 0.0

    # 2. Детектор циклического «пиления» ХХ (автоколебания вверх-вниз на непрерывном ХХ)
    hot_set = set(hot_idle_idx)
    saw_cycles = 0
    max_swing = 0.0
    saw_time_str = ""

    # Разбиваем прогретый ХХ на непрерывные сегменты
    segments: list[list[int]] = []
    cur_seg: list[int] = []
    for idx in valid_idx:
        if idx in hot_set:
            cur_seg.append(idx)
        else:
            if len(cur_seg) >= 12:
                segments.append(cur_seg)
            cur_seg = []
    if len(cur_seg) >= 12:
        segments.append(cur_seg)

    for seg in segments:
        extrema: list[tuple[float, float]] = []  # (time, rpm)
        direction = 0
        anchor_rpm = rpm_all[seg[0]]
        anchor_t = time_all[seg[0]] if seg[0] < len(time_all) and time_all[seg[0]] is not None else 0.0
        for idx in seg[1:]:
            r = rpm_all[idx]
            t = time_all[idx] if idx < len(time_all) and time_all[idx] is not None else 0.0
            if r is None or anchor_rpm is None:
                continue
            delta = r - anchor_rpm
            if direction >= 0:
                if r > anchor_rpm:
                    anchor_rpm, anchor_t = r, t
                elif delta <= -45.0:
                    extrema.append((anchor_t, anchor_rpm))
                    direction = -1
                    anchor_rpm, anchor_t = r, t
            if direction <= 0:
                if r < anchor_rpm:
                    anchor_rpm, anchor_t = r, t
                elif delta >= 45.0:
                    extrema.append((anchor_t, anchor_rpm))
                    direction = 1
                    anchor_rpm, anchor_t = r, t
        if len(extrema) >= 4:
            cycles = len(extrema) // 2
            if cycles > saw_cycles:
                saw_cycles = cycles
                swings = [abs(extrema[j][1] - extrema[j - 1][1]) for j in range(1, len(extrema))]
                max_swing = max(swings) if swings else 0.0
                saw_time_str = f"{extrema[0][0]:.0f}–{extrema[-1][0]:.0f}с"

    # 3. Контроль подхвата РХХ при сбросе газа на стоянке
    drop_events: list[str] = []
    last_drop_t = -999.0
    for k in range(2, len(valid_idx)):
        i_cur = valid_idx[k]
        rpm = rpm_all[i_cur] if i_cur < len(rpm_all) else None
        tps = tps_all[i_cur] if i_cur < len(tps_all) else None
        spd = spd_all[i_cur] if i_cur < len(spd_all) else None
        ect = ect_all[i_cur] if i_cur < len(ect_all) else None
        t_cur = time_all[i_cur] if i_cur < len(time_all) and time_all[i_cur] is not None else float(k)
        if rpm is None or tps is None or ect is None:
            continue
        if ect >= 70.0 and tps <= 0.5 and (spd is None or spd <= 3.0) and 450.0 <= rpm <= 695.0:
            # Проверяем, были ли обороты >= 1450 за последние ~3 секунды (12 кадров)
            lookback = valid_idx[max(0, k - 14):k]
            prev_rpms = [rpm_all[j] for j in lookback if j < len(rpm_all) and rpm_all[j] is not None]
            if prev_rpms and max(prev_rpms) >= 1450.0 and (t_cur - last_drop_t) >= 4.0:
                iac_now = iac_all[i_cur] if i_cur < len(iac_all) and iac_all[i_cur] is not None else 0.0
                drop_events.append(f"{t_cur:.1f}с (провал до {rpm:.0f} об/мин, РХХ {iac_now:.0f} шаг)")
                last_drop_t = t_cur

    issues: list[str] = []
    warns: list[str] = []
    tips: list[str] = [
        f"Медиана РХХ на прогретом ХХ: {iac_med:.0f} шаг (норма 25–48).",
    ]
    if rpm_des_med is not None:
        tips.append(f"Обороты ХХ: факт {rpm_med:.0f} vs цель {rpm_des_med:.0f} об/мин (разница {rpm_diff:+.0f}).")

    # Проверка заклинивания РХХ / загрязнения канала / подсоса
    if iac_med >= 52.0 and rpm_des_med is not None and rpm_diff <= -45.0:
        issues.append(f"ЗАКЛИНИЛ РХХ? ({iac_med:.0f} шаг, об. {rpm_diff:+.0f})")
        tips.append("ЭБУ максимально открывает РХХ, но обороты ниже заданных — проверьте шток РХХ и канал ХХ.")
    elif iac_med <= 18.0:
        issues.append(f"ПОДСОС ВОЗДУХА (РХХ {iac_med:.0f} шаг)")
        tips.append("РХХ зажат ниже 19 шагов — двигатель сосёт воздух мимо дросселя.")
    elif iac_med <= 23.0:
        warns.append(f"Возможен подсос (РХХ {iac_med:.0f} шаг)")
    elif iac_med >= 58.0:
        issues.append(f"Забит дроссель/РХХ ({iac_med:.0f} шаг)")
    elif iac_med >= 50.0:
        warns.append(f"Повышен шаг РХХ ({iac_med:.0f} шаг)")

    if saw_cycles >= 3:
        issues.append(f"ПИЛЕНИЕ ХХ ({saw_cycles} циклов, размах {max_swing:.0f})")
        tips.append(f"Обнаружены автоколебания ХХ на участке {saw_time_str} с амплитудой до {max_swing:.0f} об/мин.")
    elif saw_cycles == 2:
        warns.append(f"Раскачка ХХ (размах {max_swing:.0f} об/мин)")

    if rpm_des_med is not None and not issues:
        if abs(rpm_diff) >= 75.0:
            issues.append(f"Сбой оборотов ХХ ({rpm_diff:+.0f} от цели)")
        elif abs(rpm_diff) >= 45.0:
            warns.append(f"Отклонение ХХ ({rpm_diff:+.0f} от цели)")

    if len(drop_events) >= 2:
        warns.append(f"Слабый подхват РХХ ({len(drop_events)} провала)")
        tips.append("Провалы при сбросе газа: " + "; ".join(drop_events[:4]))
    elif len(drop_events) == 1:
        tips.append("Единичный провал при сбросе газа: " + drop_events[0])

    val_str = f"РХХ {iac_med:.0f} шаг | ХХ {rpm_med:.0f} об/мин"

    if issues:
        return _make_card(
            "РХХ и подсос воздуха",
            "status-bad",
            "ПРОБЛЕМА",
            f"{val_str} [{issues[0]}]",
            "Норма РХХ: 25–48 шаг | Цель: ±40 об/мин",
            " ".join(tips),
        )
    if warns:
        return _make_card(
            "РХХ и подсос воздуха",
            "status-warn",
            "ВНИМАНИЕ",
            f"{val_str} [{warns[0]}]",
            "Норма РХХ: 25–48 шаг | Цель: ±40 об/мин",
            " ".join(tips),
        )
    return _make_card(
        "РХХ и подсос воздуха",
        "status-ok",
        "НОРМА",
        val_str,
        "Норма РХХ: 25–48 шаг | Цель: ±40 об/мин",
        " ".join(tips),
    )


def check_maf_throttle_response(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """Проверка напряжения АЦП ДМРВ в покое (до пуска) и отклика расхода воздуха по дросселю."""
    maf_all = col_vals(table, COL["MAF"])
    adc_maf_all = col_vals(table, COL["ADC_MAF"])
    tps_all = col_vals(table, COL["TPS"])
    rpm_all = col_vals(table, COL["RPM"])

    # 1. АЦП покоя ДМРВ при включённом зажигании (0 об/мин)
    rest_adc = [
        adc_maf_all[i]
        for i in valid_idx
        if i < len(rpm_all)
        and rpm_all[i] is not None
        and rpm_all[i] == 0
        and i < len(adc_maf_all)
        and adc_maf_all[i] is not None
        and 0.80 <= adc_maf_all[i] <= 1.35
    ]
    adc_rest_med = statistics.median(rest_adc) if rest_adc else None

    # 2. Отклик расхода воздуха при открытии дросселя (ДПДЗ >= 22%, обороты >= 1800)
    open_throttle_maf: list[float] = []
    sluggish_cnt = 0
    for i in run_idx:
        tps = tps_all[i] if i < len(tps_all) else None
        rpm = rpm_all[i] if i < len(rpm_all) else None
        maf = maf_all[i] if i < len(maf_all) else None
        if tps is None or rpm is None or maf is None:
            continue
        if tps >= 22.0 and rpm >= 1800.0:
            open_throttle_maf.append(maf)
            if tps >= 25.0 and rpm >= 2000.0 and maf < 34.0:
                sluggish_cnt += 1

    if adc_rest_med is None and not open_throttle_maf:
        return _make_card(
            "Отклик ДМРВ и АЦП",
            "status-na",
            "НЕТ ДАННЫХ",
            "Нет кадров покоя / газа",
            "АЦП покоя: 0.996–1.020 В",
            "Для проверки АЦП ДМРВ нужны кадры с включённым зажиганием до пуска (0 об/мин), а для отклика — открытие дросселя >= 22%.",
        )

    issues: list[str] = []
    warns: list[str] = []
    tips: list[str] = []

    if adc_rest_med is not None:
        tips.append(f"АЦП ДМРВ в покое ({len(rest_adc)} кадров): {adc_rest_med:.3f} В (новый Bosch HFM5: 0.996–1.015 В).")
        if adc_rest_med >= 1.060:
            issues.append(f"ИЗНОС ДМРВ (АЦП {adc_rest_med:.3f} В)")
        elif adc_rest_med >= 1.035:
            warns.append(f"Уставший ДМРВ (АЦП {adc_rest_med:.3f} В)")
        elif adc_rest_med < 0.960:
            warns.append(f"Занижен АЦП ДМРВ ({adc_rest_med:.3f} В)")

    if open_throttle_maf:
        med_open = statistics.median(open_throttle_maf)
        max_open = max(open_throttle_maf)
        tips.append(f"При дросселе >= 22% ({len(open_throttle_maf)} кадров): медиана {med_open:.1f} кг/ч, пик {max_open:.1f} кг/ч.")
        if len(open_throttle_maf) >= 6 and (sluggish_cnt / len(open_throttle_maf)) > 0.35:
            issues.append("Слабый рост ДМРВ при газе")
        elif sluggish_cnt >= 3:
            warns.append("Пониженный расход при газе")

    parts: list[str] = []
    if adc_rest_med is not None:
        parts.append(f"АЦП {adc_rest_med:.3f} В")
    if open_throttle_maf:
        parts.append(f"газ {statistics.median(open_throttle_maf):.0f} кг/ч")
    val_str = " | ".join(parts)

    if issues:
        return _make_card(
            "Отклик ДМРВ и АЦП",
            "status-bad",
            "ПРОБЛЕМА",
            f"{val_str} [{issues[0]}]",
            "АЦП покоя: 0.996–1.020 В",
            " ".join(tips),
        )
    if warns:
        return _make_card(
            "Отклик ДМРВ и АЦП",
            "status-warn",
            "ВНИМАНИЕ",
            f"{val_str} [{warns[0]}]",
            "АЦП покоя: 0.996–1.020 В",
            " ".join(tips),
        )
    return _make_card(
        "Отклик ДМРВ и АЦП",
        "status-ok",
        "НОРМА",
        val_str,
        "АЦП покоя: 0.996–1.020 В",
        " ".join(tips),
    )
