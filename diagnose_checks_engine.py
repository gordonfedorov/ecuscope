"""Модуль проверок зажигания, детонации, пропусков, ДПКВ и динамики отклика ДВС."""

from __future__ import annotations

import statistics
import pyarrow as pa

from diagnose_utils import COL, col_vals, fmt_sec, sub


def _make_card(
    title: str,
    val: str,
    norm: str,
    status: str = "status-ok",
    badge: str | None = None,
    tooltip: str = "",
) -> dict:
    if badge is None:
        badge_map = {
            "status-ok": "НОРМА",
            "status-warn": "ВНИМАНИЕ",
            "status-bad": "ПРОБЛЕМА",
            "status-na": "НЕТ ДАННЫХ",
        }
        badge = badge_map.get(status, "ИНФО")
    return {
        "title": title,
        "badge": badge,
        "val": val,
        "norm": norm,
        "status": status,
        "tooltip": tooltip,
    }


def check_knock_and_retard(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict:
    """Проверка детонации и глубины отскока УОЗ под нагрузкой."""
    idx_pool = run_idx if run_idx else valid_idx
    retard_all = col_vals(table, COL["KNOCK_RETARD"])
    knock_v_all = col_vals(table, COL["KNOCK_V"])
    rpm_all = col_vals(table, COL["RPM"])
    load_all = col_vals(table, COL["LOAD"])
    iat_all = col_vals(table, COL["IAT"])
    time_all = col_vals(table, COL["TIME"])

    ret_sub = sub(retard_all, idx_pool)
    if not ret_sub:
        return _make_card(
            title="Детонация и отскок УОЗ",
            val="Нет данных",
            norm="Отскок УОЗ под нагрузкой ≤ 4.0 °ПКВ",
            status="status-na",
            tooltip="В логе отсутствует канал отскока УОЗ по детонации.",
        )

    episodes = []
    for i in idx_pool:
        r = retard_all[i] if i < len(retard_all) else None
        if r is not None and r > 0.5:
            rpm = rpm_all[i] if i < len(rpm_all) else 0
            load = load_all[i] if i < len(load_all) else 0
            iat = iat_all[i] if i < len(iat_all) else None
            t = time_all[i] if i < len(time_all) else 0.0
            episodes.append((r, t, rpm, load, iat))

    max_ret = max(ret_sub)
    deep_cnt = sum(1 for r, *_ in episodes if r >= 4.5)
    kv_sub = sub(knock_v_all, idx_pool)
    max_kv = max(kv_sub) if kv_sub else None

    if max_ret >= 7.5 or deep_cnt >= 15:
        status = "status-bad"
        badge = "ДЕТОНАЦИЯ"
    elif max_ret >= 4.5 or deep_cnt >= 5:
        status = "status-warn"
        badge = "ОТБИВКА УОЗ"
    else:
        status = "status-ok"
        badge = "НОРМА"

    val = f"Макс. отскок {max_ret:.1f}°"
    if episodes:
        val += f" ({len(episodes)} кадр.)"
    norm = "Норма ≤ 4.0°" + (f" | Пик ДД: {max_kv:.2f} В" if max_kv is not None else "")

    tip_lines = [
        f"Кадров с отскоком УОЗ (>0.5°): {len(episodes)}, глубоких (≥4.5°): {deep_cnt}.",
    ]
    if episodes:
        top = sorted(episodes, key=lambda x: x[0], reverse=True)[:4]
        for r, t, rpm, load, iat in top:
            iat_s = f", ДТВ {iat:.0f}°C" if iat is not None else ""
            tip_lines.append(
                f"• {fmt_sec(t)}: отскок {r:.1f}° при {rpm:.0f} об/мин, нагрузка {load:.0f}%{iat_s}"
            )
    else:
        tip_lines.append("Детонационной коррекции УОЗ не зафиксировано.")

    return _make_card(
        title="Детонация и отскок УОЗ",
        val=val,
        norm=norm,
        status=status,
        badge=badge,
        tooltip="\n".join(tip_lines),
    )


def check_misfire_and_peak_maf(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict:
    """Детализация пропусков воспламенения по цилиндрам 1-4 и пиковый расход ДМРВ."""
    idx_pool = run_idx if run_idx else valid_idx
    cyl_keys = ["MIS_CYL_1", "MIS_CYL_2", "MIS_CYL_3", "MIS_CYL_4"]
    cyl_max = []
    for idx_c, key in enumerate(cyl_keys, start=1):
        vals = sub(col_vals(table, COL[key]), idx_pool)
        cyl_max.append((idx_c, int(max(vals)) if vals else 0))

    mis_sum_vals = sub(col_vals(table, COL["MIS_SUM"]), idx_pool)
    sum_max = int(max(mis_sum_vals)) if mis_sum_vals else sum(v for _, v in cyl_max)

    maf_vals = sub(col_vals(table, COL["MAF"]), idx_pool)
    rpm_vals = sub(col_vals(table, COL["RPM"]), idx_pool)
    peak_maf = max(maf_vals) if maf_vals else None
    peak_rpm = max(rpm_vals) if rpm_vals else None

    worst_cyl, worst_cnt = max(cyl_max, key=lambda x: x[1])
    total_cyl = sum(v for _, v in cyl_max)

    if worst_cnt >= 15 or total_cyl >= 25 or sum_max >= 25:
        status = "status-bad"
        badge = f"ПРОПУСКИ Ц{worst_cyl}"
    elif worst_cnt >= 3 or total_cyl >= 5 or sum_max >= 5:
        status = "status-warn"
        badge = "ЕСТЬ ПРОПУСКИ"
    else:
        status = "status-ok"
        badge = "НОРМА"

    if total_cyl > 0:
        cyl_str = "/".join(str(v) for _, v in cyl_max)
        val = f"Ц1-4: {cyl_str}"
    else:
        val = "Пропусков: 0"
        if peak_maf is not None:
            val += f" | Пик {peak_maf:.0f} кг/ч"

    norm = (
        f"Пик ДМРВ: {peak_maf:.1f} кг/ч (до {peak_rpm:.0f} об/мин)"
        if (peak_maf is not None and peak_rpm is not None)
        else "Норма: 0 пропусков по цилиндрам"
    )

    tip_lines = [
        "Макс. счётчики пропусков по цилиндрам: "
        + ", ".join(f"Ц{c}={v}" for c, v in cyl_max)
        + f" (общий счётчик: {sum_max}).",
    ]
    if peak_maf is not None and peak_rpm is not None:
        tip_lines.append(
            f"Пиковый расход воздуха ДМРВ: {peak_maf:.1f} кг/ч при макс. оборотах {peak_rpm:.0f} об/мин."
        )

    return _make_card(
        title="Пропуски и пик ДМРВ",
        val=val,
        norm=norm,
        status=status,
        badge=badge,
        tooltip="\n".join(tip_lines),
    )


check_misfires_by_cylinder = check_misfire_and_peak_maf


def check_ckp_and_ign_dynamics(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict:
    """Проверка стабильности сигнала ДПКВ (отсутствие срывов в 0) и динамики УОЗ."""
    rpm_all = col_vals(table, COL["RPM"])
    ign_all = col_vals(table, COL["IGN"])
    spd_all = col_vals(table, COL["SPD"])
    time_all = col_vals(table, COL["TIME"])
    unbal_all = col_vals(table, COL["CRANK_UNBAL"])

    dropouts = []
    for pos in range(1, len(valid_idx) - 1):
        i_prev = valid_idx[pos - 1]
        i_curr = valid_idx[pos]
        i_next = valid_idx[pos + 1]
        r_prev = rpm_all[i_prev] if i_prev < len(rpm_all) else None
        r_curr = rpm_all[i_curr] if i_curr < len(rpm_all) else None
        r_next = rpm_all[i_next] if i_next < len(rpm_all) else None
        if (
            r_prev is not None
            and r_curr is not None
            and r_next is not None
            and r_prev >= 1100
            and r_curr == 0
            and r_next >= 900
        ):
            t = time_all[i_curr] if i_curr < len(time_all) else 0.0
            spd = spd_all[i_curr] if i_curr < len(spd_all) else 0.0
            dropouts.append((t, r_prev, spd))

    idx_pool = run_idx if run_idx else valid_idx
    ign_sub = sub(ign_all, idx_pool)
    unbal_sub = sub(unbal_all, idx_pool)

    if not ign_sub and not dropouts:
        return _make_card(
            title="ДПКВ и динамика УОЗ",
            val="Нет данных",
            norm="Без срывов ДПКВ | Размах УОЗ > 5°",
            status="status-na",
        )

    ign_span = (max(ign_sub) - min(ign_sub)) if len(ign_sub) >= 10 else None
    ign_min = min(ign_sub) if ign_sub else 0.0
    ign_max = max(ign_sub) if ign_sub else 0.0
    max_unbal = max(unbal_sub) if unbal_sub else None

    if dropouts:
        status = "status-bad"
        badge = "СБОЙ ДПКВ"
        val = f"Срывов ДПКВ: {len(dropouts)}"
    elif ign_span is not None and len(ign_sub) >= 40 and ign_span < 4.5:
        status = "status-warn"
        badge = "ЗАЛИП УОЗ"
        val = f"Размах УОЗ {ign_span:.1f}°"
    else:
        status = "status-ok"
        badge = "НОРМА"
        val = (
            f"УОЗ {ign_min:.0f}..{ign_max:.0f}°"
            if ign_sub
            else "Сигнал ДПКВ ровный"
        )

    norm = "Срывов ДПКВ: 0"
    if max_unbal is not None:
        norm += f" | Макс. неравном.: {max_unbal:.2f}"

    tip_lines = [
        f"Мгновенных срывов оборотов в 0 на ходу (ДПКВ): {len(dropouts)}.",
    ]
    if dropouts:
        for t, rp, sp in dropouts[:5]:
            tip_lines.append(
                f"• {fmt_sec(t)}: провал оборотов с {rp:.0f} до 0 об/мин (скорость {sp:.0f} км/ч)"
            )
    if ign_sub:
        tip_lines.append(
            (f"Рабочий диапазон УОЗ: от {ign_min:.1f}° до {ign_max:.1f}° (размах {ign_span:.1f}°)." if ign_span is not None else "Данные УОЗ на рабочем участке отсутствуют.")
        )

    return _make_card(
        title="ДПКВ и динамика УОЗ",
        val=val,
        norm=norm,
        status=status,
        badge=badge,
        tooltip="\n".join(tip_lines),
    )


def check_throttle_cascade_response(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int] | None = None,
    hot_idle_idx: list[int] | None = None,
) -> dict:
    """Каскадная проверка отклика на резкий газ: ДПДЗ -> ДМРВ -> Впрыск -> Обороты."""
    tps_all = col_vals(table, COL["TPS"])
    maf_all = col_vals(table, COL["MAF"])
    inj_all = col_vals(table, COL["INJ"])
    rpm_all = col_vals(table, COL["RPM"])
    time_all = col_vals(table, COL["TIME"])

    if not tps_all or not rpm_all or len(valid_idx) < 15:
        return _make_card(
            title="Отклик на резкий газ",
            val="Нет данных",
            norm="Цепочка ДПДЗ → ДМРВ → Впрыск → Обороты",
            status="status-na",
        )

    events = []
    anomalies = []
    last_event_t = -10.0

    for pos in range(1, len(valid_idx) - 2):
        i0 = valid_idx[pos - 1]
        i1 = valid_idx[pos]
        t0 = time_all[i0] if i0 < len(time_all) and time_all[i0] is not None else float(pos - 1)
        t1 = time_all[i1] if i1 < len(time_all) and time_all[i1] is not None else float(pos)
        if t1 - last_event_t < 2.0 or (t1 - t0) > 1.0:
            continue

        tps0 = tps_all[i0] if i0 < len(tps_all) else None
        tps1 = tps_all[i1] if i1 < len(tps_all) else None
        rpm0 = rpm_all[i0] if i0 < len(rpm_all) else None
        if tps0 is None or tps1 is None or rpm0 is None:
            continue

        # Резкое открытие дросселя от малых углов на работающем двигателе
        if rpm0 >= 650 and rpm0 <= 3800 and tps0 <= 22.0 and (tps1 - tps0) >= 14.0:
            last_event_t = t1
            maf0 = maf_all[i0] if i0 < len(maf_all) else None
            inj0 = inj_all[i0] if i0 < len(inj_all) else None

            win_maf = []
            win_inj = []
            win_rpm = []
            for p2 in range(pos, len(valid_idx)):
                j = valid_idx[p2]
                tj = time_all[j] if j < len(time_all) and time_all[j] is not None else float(p2)
                if tj - t1 > 1.3:
                    break
                if j < len(maf_all) and maf_all[j] is not None:
                    win_maf.append(maf_all[j])
                if j < len(inj_all) and inj_all[j] is not None:
                    win_inj.append(inj_all[j])
                if j < len(rpm_all) and rpm_all[j] is not None:
                    win_rpm.append(rpm_all[j])

            if not win_rpm:
                continue

            min_rpm = min(win_rpm)
            max_rpm = max(win_rpm)
            rpm_dip = rpm0 - min_rpm
            rpm_gain = max_rpm - rpm0

            maf_ok = True
            if maf0 is not None and win_maf:
                maf_gain = max(win_maf) - maf0
                if maf_gain < max(5.0, maf0 * 0.20):
                    maf_ok = False

            inj_ok = True
            if inj0 is not None and win_inj:
                inj_gain = max(win_inj) - inj0
                if inj_gain < max(0.8, inj0 * 0.15):
                    inj_ok = False

            events.append((t1, tps0, tps1, rpm0, max_rpm, rpm_dip, maf_ok, inj_ok))

            reasons = []
            if rpm_dip >= 75:
                reasons.append(f"провал -{rpm_dip:.0f} об/мин")
            if not maf_ok:
                reasons.append("слабый прирост ДМРВ")
            if not inj_ok:
                reasons.append("нет обогащения впрыска")
            if rpm_gain < 90 and rpm_dip < 75:
                reasons.append(f"вялый набор (+{rpm_gain:.0f} об/мин)")

            if reasons:
                anomalies.append((t1, tps0, tps1, ", ".join(reasons)))

    if not events:
        return _make_card(
            title="Отклик на резкий газ",
            val="Нет резких нажатий",
            norm="Не было резкого открытия ДПДЗ (≥14%)",
            status="status-na",
            tooltip="В логе не зафиксировано резких открытий дроссельной заслонки с малых углов.",
        )

    bad_ratio = len(anomalies) / len(events)
    if len(anomalies) >= 2 and bad_ratio >= 0.5:
        status = "status-warn"
        badge = "ПРОВАЛ ПРИ ГАЗЕ"
        val = f"Сбоев: {len(anomalies)} из {len(events)}"
    elif anomalies:
        status = "status-ok"
        badge = "НОРМА"
        val = f"Чётко: {len(events) - len(anomalies)} из {len(events)}"
    else:
        status = "status-ok"
        badge = "НОРМА"
        val = f"Все {len(events)} нажатий чётко"

    norm = "Цепочка ДПДЗ → ДМРВ → Впрыск → Обороты"
    tip_lines = [
        f"Проанализировано резких открытий дросселя (≥14%): {len(events)}.",
    ]
    if anomalies:
        tip_lines.append("Зафиксированы задержки/провалы отклика:")
        for t, a0, a1, rsn in anomalies[:5]:
            tip_lines.append(f"• {fmt_sec(t)} (ДПДЗ {a0:.0f}%→{a1:.0f}%): {rsn}")
    else:
        for t, a0, a1, r0, rmax, *_ in events[:4]:
            tip_lines.append(
                f"• {fmt_sec(t)} (ДПДЗ {a0:.0f}%→{a1:.0f}%): отклик оборотов {r0:.0f} → {rmax:.0f} об/мин"
            )

    return _make_card(
        title="Отклик на резкий газ",
        val=val,
        norm=norm,
        status=status,
        badge=badge,
        tooltip="\n".join(tip_lines),
    )
