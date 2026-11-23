#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_checks_base.py — базовые диагностические проверки ЭБУ Bosch M7.9.7
для проекта ECUScope — Здоровье мотора.
"""

import statistics
import pyarrow as pa
from diagnose_utils import COL, col_vals as _col_vals, sub as _sub


def analyze_engine_starts(
    valid_idx: list[int],
    times_raw: list,
    rpm_all: list,
    ect_all: list,
    ect_start_all: list,
    vbat_all: list,
) -> dict | None:
    """
    Выделяет реальные попытки пуска (прокрутка стартером 40..440 об/мин из остановленного состояния),
    игнорируя просто включённое зажигание (0 об/мин) и выбег коленвала при глушении двигателя.
    """
    starts = []
    crank_start_t = None
    last_crank_t = None
    min_vbat_crank = None
    start_ect_val = None
    cur_ect_val = None
    crank_frames = 0
    engine_was_running = False

    def _reset_crank() -> None:
        nonlocal crank_start_t, last_crank_t, min_vbat_crank, start_ect_val, cur_ect_val, crank_frames
        crank_start_t = None
        last_crank_t = None
        min_vbat_crank = None
        start_ect_val = None
        cur_ect_val = None
        crank_frames = 0

    for i in valid_idx:
        rpm = rpm_all[i] if i < len(rpm_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None
        ect = ect_all[i] if i < len(ect_all) else None
        ect_s = ect_start_all[i] if i < len(ect_start_all) else None
        vbat = vbat_all[i] if i < len(vbat_all) else None

        if rpm is None or t_cur is None:
            continue

        if rpm == 0:
            if crank_start_t is not None:
                end_t = last_crank_t if last_crank_t is not None else t_cur
                dur = max(0.0, end_t - crank_start_t)
                if crank_frames >= 2 or (min_vbat_crank is not None and min_vbat_crank < 11.8):
                    starts.append({
                        "t0": crank_start_t,
                        "dur": dur,
                        "success": False,
                        "ect_start": start_ect_val,
                        "ect_cur": cur_ect_val,
                        "min_vbat": min_vbat_crank,
                        "frames": crank_frames,
                    })
                _reset_crank()
            engine_was_running = False
            continue

        if 40 <= rpm <= 440:
            if engine_was_running:
                continue

            if crank_start_t is None:
                crank_start_t = t_cur
                min_vbat_crank = vbat
                start_ect_val = ect_s if ect_s is not None else ect
                cur_ect_val = ect
                crank_frames = 1
            else:
                crank_frames += 1
                if vbat is not None and (min_vbat_crank is None or vbat < min_vbat_crank):
                    min_vbat_crank = vbat
                if start_ect_val is None and ect_s is not None:
                    start_ect_val = ect_s
                if cur_ect_val is None and ect is not None:
                    cur_ect_val = ect
            last_crank_t = t_cur
            continue

        if rpm >= 480:
            if crank_start_t is not None:
                dur = max(0.0, t_cur - crank_start_t)
                starts.append({
                    "t0": crank_start_t,
                    "dur": dur,
                    "success": True,
                    "ect_start": start_ect_val,
                    "ect_cur": cur_ect_val,
                    "min_vbat": min_vbat_crank,
                    "frames": crank_frames,
                })
                _reset_crank()
            engine_was_running = True

    if not starts:
        return None

    max_dur = max(s["dur"] for s in starts)
    failed_cnt = sum(1 for s in starts if not s["success"])
    first = starts[0]
    ect_s = first["ect_start"]
    ect_c = first["ect_cur"]
    ect_diff = abs(ect_s - ect_c) if (ect_s is not None and ect_c is not None) else 0.0

    min_vbats = [s["min_vbat"] for s in starts if s["min_vbat"] is not None]
    worst_vbat = min(min_vbats) if min_vbats else None

    if failed_cnt > 0 or max_dur > 4.0 or (worst_vbat is not None and worst_vbat < 8.8):
        st, badge = "status-bad", "ТЯЖЁЛЫЙ ПУСК"
    elif max_dur > 2.0 or ect_diff > 4.0 or (worst_vbat is not None and worst_vbat < 9.5):
        st, badge = "status-warn", "ЗАТЯЖНОЙ"
    else:
        st, badge = "status-ok", "НОРМА"

    t_parts = []
    if ect_s is not None:
        t_parts.append(f"ДТОЖ пуск {ect_s:.1f}°C")
    if ect_c is not None and ect_diff > 1.5:
        t_parts.append(f"тек. {ect_c:.1f}°C")
    t_str = f" | {', '.join(t_parts)}" if t_parts else ""
    v_str = f" | АКБ мин {worst_vbat:.1f}В" if worst_vbat is not None else ""
    attempts_str = f" ({len(starts)} поп., неудач: {failed_cnt})" if (len(starts) > 1 or failed_cnt > 0) else ""

    tooltip_lines = []
    for idx_s, s in enumerate(starts, 1):
        res_lbl = "запуск" if s["success"] else "не завёлся"
        es_txt = f"{s['ect_start']:.1f}°C" if s["ect_start"] is not None else "?"
        vb_txt = f"{s['min_vbat']:.2f}В" if s["min_vbat"] is not None else "?"
        tooltip_lines.append(
            f"Попытка #{idx_s} (на {s['t0']:.1f} с): {s['dur']:.2f} с ({res_lbl}) | "
            f"ДТОЖ пуск: {es_txt} | АКБ мин: {vb_txt}"
        )

    return {
        "title": "Пуск и прокрутка",
        "badge": badge,
        "status": st,
        "val": f"Прокрутка: {max_dur:.2f} с{attempts_str}{t_str}{v_str}",
        "norm": "Норма прокрутки: ≤ 2.0 с; АКБ при пуске ≥ 9.5 В",
        "tooltip": "\n".join(tooltip_lines),
    }


def analyze_ecu_adaptations(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict | None:
    """
    Отдельная карточка «Адаптации ЭБУ»:
      - мультипликативная топливная адаптация FRA в процентах ((FRA - 1) * 100%);
      - аддитивная топливная адаптация RKAT (%);
      - адаптация регулировки холостого хода (%);
      - статус базовой адаптации и параметр адаптации зубьев венца демпфера.
    """
    fra_all = _col_vals(table, COL.get("fra", "Мультипликативная составляющая коррекции самообучением (-)"))
    rkat_all = _col_vals(table, COL.get("rkat", "Аддитивная составляющая коррекции самообучением (%)"))
    iac_adapt_all = _col_vals(table, COL.get("iac_adapt", "Параметр адаптации регулировки ХХ (%)"))
    base_adapt_all = _col_vals(table, COL.get("base_adapt", "Базовая адаптация (-)"))
    damper_all = _col_vals(table, COL.get("damper_adapt", "Парам. адаптации угл. погреш. зубьев венца демпфера (об/с2)"))

    fras = _sub(fra_all, valid_idx)
    rkats = _sub(rkat_all, valid_idx)
    iac_ads = _sub(iac_adapt_all, hot_idle_idx) or _sub(iac_adapt_all, valid_idx)
    base_ads = _sub(base_adapt_all, valid_idx)
    dampers = _sub(damper_all, valid_idx)

    if not fras and not rkats and not iac_ads and not base_ads:
        return None

    fra_first = fras[0] if fras else None
    fra_last = fras[-1] if fras else None
    fra_pct_last = ((fra_last - 1.0) * 100.0) if fra_last is not None else None
    fra_pct_first = ((fra_first - 1.0) * 100.0) if fra_first is not None else None

    rkat_first = rkats[0] if rkats else None
    rkat_last = rkats[-1] if rkats else None

    iac_ad_last = iac_ads[-1] if iac_ads else None
    base_done = any(v == 1 for v in base_ads) if base_ads else None
    damper_last = dampers[-1] if dampers else None

    st = "status-ok"
    badge = "ОБУЧЕН"

    if (
        (fra_pct_last is not None and abs(fra_pct_last) > 15.0)
        or (rkat_last is not None and abs(rkat_last) > 8.0)
        or (iac_ad_last is not None and abs(iac_ad_last) > 7.5)
    ):
        st, badge = "status-bad", "ПРЕДЕЛ АДАПТ."
    elif (
        (fra_pct_last is not None and abs(fra_pct_last) > 8.0)
        or (rkat_last is not None and abs(rkat_last) > 4.5)
        or (iac_ad_last is not None and abs(iac_ad_last) > 4.5)
    ):
        st, badge = "status-warn", "СМЕЩЕНИЕ"
    elif base_done is False:
        st, badge = "status-warn", "ИДЁТ ОБУЧЕНИЕ"

    parts = []
    if fra_pct_last is not None:
        parts.append(f"FRA {fra_pct_last:+.1f}%")
    if rkat_last is not None:
        parts.append(f"RKAT {rkat_last:+.1f}%")
    if iac_ad_last is not None:
        parts.append(f"ХХ {iac_ad_last:+.1f}%")
    if base_done is not None:
        parts.append("Баз.: ОК" if base_done else "Баз.: нет")

    tooltip_lines = []
    if fra_last is not None:
        dyn_fra = (
            f" (за поездку: {fra_pct_first:+.1f}% → {fra_pct_last:+.1f}%)"
            if fra_pct_first is not None and abs(fra_pct_last - fra_pct_first) >= 0.2
            else ""
        )
        tooltip_lines.append(f"Мультипликативная адаптация FRA: {fra_pct_last:+.2f}% (коэф. {fra_last:.3f}){dyn_fra}")
    if rkat_last is not None:
        dyn_rkat = (
            f" (за поездку: {rkat_first:+.2f}% → {rkat_last:+.2f}%)"
            if rkat_first is not None and abs(rkat_last - rkat_first) >= 0.2
            else ""
        )
        tooltip_lines.append(f"Аддитивная адаптация RKAT (ХХ): {rkat_last:+.2f}%{dyn_rkat}")
    if iac_ad_last is not None:
        tooltip_lines.append(f"Адаптация регулятора ХХ: {iac_ad_last:+.2f}%")
    if base_done is not None:
        tooltip_lines.append(f"Флаг завершения базовой адаптации: {'завершена (1)' if base_done else 'не завершена (0)'}")
    if damper_last is not None:
        tooltip_lines.append(f"Адаптация зубьев демпфера КВ: {damper_last:+.2f} об/с²")

    return {
        "title": "Адаптации ЭБУ",
        "badge": badge,
        "status": st,
        "val": " | ".join(parts),
        "norm": "Норма: FRA ±8%, RKAT ±4.5%, адаптация ХХ ±4.5%",
        "tooltip": "\n".join(tooltip_lines),
    }


def run_base_checks(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> list[dict]:
    """Выполняет набор базовых диагностических проверок Bosch M7.9.7."""
    times_raw = _col_vals(table, COL.get("time", "LogEntrySeconds"))
    rpm_all = _col_vals(table, COL.get("rpm", "Обороты двигателя (об/мин)"))
    ect_all = _col_vals(table, COL.get("ect", "Температура охлаждающей жидкости (°C)"))
    ect_start_all = _col_vals(table, COL.get("ect_start", "Температура охлаждающей жидкости при пуске (°C)"))
    vbat_all = _col_vals(table, COL.get("vbat", "Напряжение питания (В)"))
    maf_all = _col_vals(table, COL.get("maf", "Массовый расход воздуха (кг/ч)"))
    fuel_all = _col_vals(table, COL.get("fuel_rate", "Расход топлива (л/ч)"))
    inj_all = _col_vals(table, COL.get("inj", "Длительность впрыска (мс)"))
    ign_all = _col_vals(table, COL.get("ign", "Угол опережения зажигания (°П.К.В)"))
    iac_all = _col_vals(table, COL.get("iac", "Позиция шагового двигателя (шаг)"))
    fr_all = _col_vals(table, COL.get("fr", "Текущий коэффициент коррекции длительности впрыска топлива (-)"))
    fra_all = _col_vals(table, COL.get("fra", "Мультипликативная составляющая коррекции самообучением (-)"))
    rkat_all = _col_vals(table, COL.get("rkat", "Аддитивная составляющая коррекции самообучением (%)"))
    err_all = _col_vals(table, COL.get("errors", "Количество ошибок (-)"))
    mis_all = _col_vals(
        table,
        COL.get("misfire_sum", "Суммарный счетчик пропусков зажигания. влияющих на работоспособность нейтрализатора (-)"),
    )

    checks: list[dict] = []

    # 1. Пуск двигателя: время прокрутки стартером, пусковая температура ДТОЖ и просадка АКБ
    start_check = analyze_engine_starts(valid_idx, times_raw, rpm_all, ect_all, ect_start_all, vbat_all)
    if start_check is not None:
        checks.append(start_check)
    elif valid_idx:
        rpms_all_valid = _sub(rpm_all, valid_idx)
        max_rpm_seen = max(rpms_all_valid) if rpms_all_valid else 0
        es_vals = _sub(ect_start_all, valid_idx[:5])
        ec_vals = _sub(ect_all, valid_idx[:5])
        es0 = es_vals[0] if es_vals else (ec_vals[0] if ec_vals else None)
        t_note = f" | ДТОЖ: {es0:.1f}°C" if es0 is not None else ""
        if max_rpm_seen < 480:
            checks.append({
                "title": "Пуск и ДТОЖ", "badge": "БЕЗ СТАРТЕРА", "status": "status-na",
                "val": f"Включено только зажигание (прокрутки не было){t_note}",
                "norm": "Норма прокрутки: ≤ 2.0 с; АКБ при пуске ≥ 9.5 В",
            })
        else:
            checks.append({
                "title": "Пуск и ДТОЖ", "badge": "БЕЗ ПРОКРУТКИ", "status": "status-na",
                "val": f"Запись начата на работающем двигателе{t_note}",
                "norm": "Норма прокрутки: ≤ 2.0 с; АКБ при пуске ≥ 9.5 В",
            })

    # 2. Напряжение бортовой сети (при работающем двигателе > 450 об/мин)
    vbats = _sub(vbat_all, run_idx)
    if vbats:
        v_med = statistics.median(vbats)
        v_min, v_max = min(vbats), max(vbats)
        if 13.4 <= v_med <= 14.7 and v_min >= 12.8:
            st, badge = "status-ok", "НОРМА"
        elif 12.5 <= v_med <= 15.0:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        else:
            st, badge = "status-bad", "КРИТИЧНО"
        checks.append({
            "title": "Напряжение сети", "badge": badge, "status": st,
            "val": f"{v_med:.2f} В (мин {v_min:.2f}, макс {v_max:.2f})",
            "norm": "Норма при работе: 13.5 – 14.6 В",
        })

    # 3. Температура охлаждающей жидкости (ДТОЖ)
    ects = _sub(ect_all, valid_idx)
    if ects:
        t_min, t_max = min(ects), max(ects)
        if t_max > 108.0:
            st, badge = "status-bad", "ПЕРЕГРЕВ"
        elif t_max < 78.0:
            st, badge = "status-warn", "НЕДОГРЕВ"
        elif t_max > 104.0:
            st, badge = "status-warn", "ВЫСОКАЯ"
        else:
            st, badge = "status-ok", "НОРМА"
        checks.append({
            "title": "Температура ОЖ (ДТОЖ)", "badge": badge, "status": st,
            "val": f"от {t_min:.1f} до {t_max:.1f} °C",
            "norm": "Рабочая норма: 82 – 103 °C",
        })

    # 4. Обороты на прогретом ХХ
    rpms_idle = _sub(rpm_all, hot_idle_idx)
    if rpms_idle:
        r_med = statistics.median(rpms_idle)
        if 760 <= r_med <= 880:
            st, badge = "status-ok", "НОРМА"
        elif 700 <= r_med <= 950:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        else:
            st, badge = "status-bad", "ВНЕ НОРМЫ"
        checks.append({
            "title": "Обороты ХХ (прогрет)", "badge": badge, "status": st,
            "val": f"{r_med:.0f} об/мин ({min(rpms_idle)}..{max(rpms_idle)})",
            "norm": "Норма ХХ: 780 – 860 об/мин",
        })
    else:
        checks.append({
            "title": "Обороты ХХ (прогрет)", "badge": "НЕТ ДАННЫХ", "status": "status-na",
            "val": "Нет кадров прогретого ХХ (≥75 °C)",
            "norm": "Норма ХХ: 780 – 860 об/мин",
        })

    # 5. Критическое падение оборотов
    dip_cases = []
    current_dip = None
    stall_times = []
    was_running_hot = False
    n_valid = len(valid_idx)

    for pos, i in enumerate(valid_idx):
        rpm = rpm_all[i] if i < len(rpm_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        t_cur = times_raw[i] if i < len(times_raw) else None
        if rpm is None or ect is None:
            continue

        if ect >= 70.0 and rpm >= 720:
            was_running_hot = True
            if current_dip is not None:
                dip_cases.append(current_dip)
                current_dip = None

        if rpm < 440:
            current_dip = None
        elif ect >= 70.0 and 440 <= rpm <= 680:
            if current_dip is None:
                current_dip = {"min_rpm": rpm, "min_t": t_cur, "frames": 1}
            else:
                current_dip["frames"] += 1
                if rpm < current_dip["min_rpm"]:
                    current_dip["min_rpm"] = rpm
                    current_dip["min_t"] = t_cur

        if was_running_hot and rpm == 0:
            later_rpms = [
                rpm_all[valid_idx[k]]
                for k in range(pos + 1, n_valid)
                if valid_idx[k] < len(rpm_all) and rpm_all[valid_idx[k]] is not None
            ]
            if any(lr >= 600 for lr in later_rpms):
                if not stall_times or (t_cur is not None and t_cur - stall_times[-1] > 5.0):
                    stall_times.append(t_cur if t_cur is not None else 0.0)
                was_running_hot = False

    if stall_times or dip_cases:
        worst_case = min(dip_cases, key=lambda c: c["min_rpm"]) if dip_cases else None
        dip_times_list = [f"{c['min_t']:.1f}с" for c in dip_cases if c["min_t"] is not None]
        if len(dip_times_list) <= 6:
            times_inline = ", ".join(dip_times_list)
        else:
            times_inline = ", ".join(dip_times_list[:6]) + f" и ещё {len(dip_times_list) - 6}"

        tooltip_lines = []
        if stall_times:
            tooltip_lines.append("Остановки (0 об/мин): " + ", ".join(f"{t:.1f} с" for t in stall_times))
        for idx_c, c in enumerate(dip_cases, 1):
            t_str = f"{c['min_t']:.1f} с" if c["min_t"] is not None else "?"
            tooltip_lines.append(f"Случай #{idx_c}: {t_str} -> мин. {c['min_rpm']} об/мин ({c['frames']} кадр.)")
        tooltip_text = "\n".join(tooltip_lines)

        if stall_times:
            st, badge = "status-bad", "ЗАГЛОХ"
            t_list = ", ".join(f"{t:.1f}с" for t in stall_times)
            extra = (
                f" | провалов <680: {len(dip_cases)} сл. ({times_inline}, мин. {worst_case['min_rpm']} об/мин)"
                if worst_case else ""
            )
            val_txt = f"Остановок: {len(stall_times)} сл. ({t_list}){extra}"
        else:
            min_dip_rpm = worst_case["min_rpm"]
            st, badge = ("status-bad", "КРИТИЧНО") if min_dip_rpm <= 560 else ("status-warn", "ПРОСАДКИ")
            t_block = f" [{times_inline}]" if times_inline else ""
            val_txt = f"Случаев: {len(dip_cases)}{t_block} | мин. {min_dip_rpm} об/мин"

        checks.append({
            "title": "Провалы оборотов", "badge": badge, "status": st,
            "val": val_txt,
            "norm": "Порог риска заглохнуть: < 560 об/мин (наведите для списка)",
            "tooltip": tooltip_text,
        })
    elif valid_idx:
        checks.append({
            "title": "Провалы оборотов", "badge": "НОРМА", "status": "status-ok",
            "val": "Случаев провала ниже 680 об/мин: 0",
            "norm": "Порог риска заглохнуть: < 560 об/мин",
        })

    # 6. Массовый расход воздуха (ДМРВ на прогретом ХХ)
    mafs_idle = _sub(maf_all, hot_idle_idx)
    if mafs_idle:
        m_med = statistics.median(mafs_idle)
        if 7.5 <= m_med <= 11.5:
            st, badge = "status-ok", "НОРМА"
        elif 6.5 <= m_med <= 13.0:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        else:
            st, badge = "status-bad", "ВНЕ НОРМЫ"
        checks.append({
            "title": "ДМРВ на прогретом ХХ", "badge": badge, "status": st,
            "val": f"{m_med:.1f} кг/ч ({min(mafs_idle):.1f}..{max(mafs_idle):.1f})",
            "norm": "Норма ХХ (1.5/1.6л): 8.0 – 11.0 кг/ч",
        })

    # 7. Расход топлива на прогретом ХХ
    fuels_idle = _sub(fuel_all, hot_idle_idx)
    if fuels_idle:
        f_med = statistics.median(fuels_idle)
        if 0.65 <= f_med <= 0.98:
            st, badge = "status-ok", "НОРМА"
        elif 0.50 <= f_med <= 1.25:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        else:
            st, badge = "status-bad", "ВНЕ НОРМЫ"
        checks.append({
            "title": "Расход топлива на ХХ", "badge": badge, "status": st,
            "val": f"{f_med:.2f} л/ч ({min(fuels_idle):.2f}..{max(fuels_idle):.2f})",
            "norm": "Норма ХХ (прогрет): 0.65 – 0.95 л/ч",
        })

    # 8. Длительность впрыска на прогретом ХХ
    injs_idle = _sub(inj_all, hot_idle_idx)
    if injs_idle:
        i_med = statistics.median(injs_idle)
        if 2.4 <= i_med <= 4.4:
            st, badge = "status-ok", "НОРМА"
        elif 2.0 <= i_med <= 5.0:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        else:
            st, badge = "status-bad", "ВНЕ НОРМЫ"
        checks.append({
            "title": "Впрыск на прогретом ХХ", "badge": badge, "status": st,
            "val": f"{i_med:.2f} мс ({min(injs_idle):.2f}..{max(injs_idle):.2f})",
            "norm": "Норма ХХ: 2.5 – 4.3 мс (фаз./попарн.)",
        })

    # 9. УОЗ и РХХ на прогретом ХХ
    igns_idle = _sub(ign_all, hot_idle_idx)
    iacs_idle = _sub(iac_all, hot_idle_idx)
    if igns_idle:
        u_med = statistics.median(igns_idle)
        iac_txt = f" | РХХ: {statistics.median(iacs_idle):.0f} шаг" if iacs_idle else ""
        if 6.0 <= u_med <= 17.0:
            st, badge = "status-ok", "НОРМА"
        else:
            st, badge = "status-warn", "ОТКЛОНЕНИЕ"
        checks.append({
            "title": "УОЗ и РХХ на ХХ", "badge": badge, "status": st,
            "val": f"УОЗ {u_med:.1f}°{iac_txt}",
            "norm": "Норма: УОЗ 7..16°, РХХ 25..55 шаг",
        })

    # 10. Текущие коррекции смеси (FR, FRA, RKAT)
    frs = _sub(fr_all, run_idx)
    fras = _sub(fra_all, valid_idx)
    rkats = _sub(rkat_all, valid_idx)
    if frs:
        fr_med = statistics.median(frs)
        fra_last = fras[-1] if fras else 1.0
        rkat_last = rkats[-1] if rkats else 0.0
        if 0.90 <= fr_med <= 1.10 and 0.90 <= fra_last <= 1.10 and abs(rkat_last) <= 5.0:
            st, badge = "status-ok", "НОРМА"
        elif 0.82 <= fr_med <= 1.18 and 0.85 <= fra_last <= 1.15 and abs(rkat_last) <= 8.0:
            st, badge = "status-warn", "СМЕЩЕНИЕ"
        else:
            st, badge = "status-bad", "БЕДНАЯ/БОГАТАЯ"
        checks.append({
            "title": "Коррекции смеси", "badge": badge, "status": st,
            "val": f"FR {fr_med:.3f} | FRA {fra_last:.3f} | RKAT {rkat_last:+.1f}%",
            "norm": "Норма: FR/FRA 0.92..1.08, RKAT ±4%",
        })

    # 11. Отдельная карточка «Адаптации ЭБУ» (процент адаптации FRA/RKAT/ХХ и флаг базовой адаптации)
    adapt_card = analyze_ecu_adaptations(table, valid_idx, run_idx, hot_idle_idx)
    if adapt_card is not None:
        checks.append(adapt_card)

    # 12. Ошибки ЭБУ и пропуски воспламенения
    errs = _sub(err_all, valid_idx)
    miss = _sub(mis_all, valid_idx)
    if errs or miss:
        e_max = max(errs) if errs else 0
        m_max = max(miss) if miss else 0
        if e_max == 0 and m_max == 0:
            st, badge = "status-ok", "ЧИСТО"
        elif e_max == 0 and m_max <= 5:
            st, badge = "status-warn", "ЕДИНИЧНЫЕ"
        else:
            st, badge = "status-bad", "ВНИМАНИЕ"
        checks.append({
            "title": "Ошибки и пропуски", "badge": badge, "status": st,
            "val": f"Ошибок ЭБУ: {e_max} | Пропусков: {m_max}",
            "norm": "Норма: 0 ошибок и 0 пропусков",
        })

    return checks
