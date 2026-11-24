"""ECUScope — Здоровье мотора: проверки системы охлаждения, пусковых температур и электропитания."""

from __future__ import annotations

import statistics
import pyarrow as pa

from diagnose_utils import COL, col_vals, fmt_sec, make_card, sub


def check_thermostat_and_fan(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """1. Контроль прогрева, зависания ДТОЖ, просадки термостата и срабатывания вентилятора."""
    times = col_vals(table, COL["TIME"])
    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    spd_all = col_vals(table, COL["SPD"])
    fan1_all = col_vals(table, COL["FAN1"])

    ect_valid = sub(ect_all, valid_idx)
    if not ect_valid:
        return make_card(
            "Термостат и вентилятор",
            "Нет данных",
            "Термостат ≥ 80 °C | Вентилятор ~99–103 °C",
            status="status-na",
            tooltip="В логе отсутствует канал температуры охлаждающей жидкости.",
        )

    ect_min = min(ect_valid)
    ect_max = max(ect_valid)

    # 1. Проверка зависания показаний ДТОЖ на работающем моторе
    stuck_sec = 0.0
    if len(run_idx) >= 20:
        cur_ect = None
        cur_t0 = None
        for idx in run_idx:
            e = ect_all[idx] if idx < len(ect_all) else None
            t = times[idx] if idx < len(times) else None
            if e is None or t is None:
                continue
            if cur_ect is None or abs(e - cur_ect) > 0.1:
                cur_ect = e
                cur_t0 = t
            else:
                stuck_sec = max(stuck_sec, float(t) - float(cur_t0))

    # 2. Просадка термостата после выхода на рабочую температуру (>= 82 °C)
    reached_warm = False
    thermo_sags: list[tuple[float, float, float]] = []
    for idx in run_idx:
        e = ect_all[idx] if idx < len(ect_all) else None
        s = spd_all[idx] if idx < len(spd_all) else 0.0
        t = times[idx] if idx < len(times) else 0.0
        if e is None:
            continue
        if e >= 82.0:
            reached_warm = True
        elif reached_warm and e < 77.0:
            thermo_sags.append((float(t), float(e), float(s or 0.0)))

    # 3. Циклы включения / выключения вентилятора 1
    fan_on_temps: list[float] = []
    fan_off_temps: list[float] = []
    prev_fan = None
    for idx in valid_idx:
        f = fan1_all[idx] if idx < len(fan1_all) else None
        e = ect_all[idx] if idx < len(ect_all) else None
        if f is None or e is None:
            continue
        f_on = int(round(float(f))) > 0
        if prev_fan is not None:
            if not prev_fan and f_on:
                fan_on_temps.append(float(e))
            elif prev_fan and not f_on:
                fan_off_temps.append(float(e))
        prev_fan = f_on

    # 4. Темп прогрева с холодного пуска (< 45 °C)
    warmup_note = ""
    if ect_min < 45.0 and len(run_idx) >= 10:
        t_start = None
        e_start = None
        t_80 = None
        for idx in run_idx:
            e = ect_all[idx] if idx < len(ect_all) else None
            t = times[idx] if idx < len(times) else None
            if e is None or t is None:
                continue
            if t_start is None:
                t_start, e_start = float(t), float(e)
            if e >= 80.0:
                t_80 = float(t)
                break
        if t_start is not None and t_80 is not None and t_80 > t_start:
            dur_min = (t_80 - t_start) / 60.0
            gain_rate = (80.0 - e_start) / dur_min
            warmup_note = f"Прогрев {e_start:.0f}→80 °C за {dur_min:.1f} мин ({gain_rate:.1f} °C/мин)."

    status = "status-ok"
    val_parts = [f"{ect_min:.0f}..{ect_max:.0f} °C"]
    norm_parts = ["Термостат ≥ 80 °C"]
    tips = [f"Диапазон ДТОЖ за поездку: {ect_min:.1f}..{ect_max:.1f} °C."]
    if warmup_note:
        tips.append(warmup_note)

    if fan_on_temps:
        on_med = statistics.median(fan_on_temps)
        off_str = f" / выкл {statistics.median(fan_off_temps):.0f}°C" if fan_off_temps else ""
        norm_parts.append(f"Вент: вкл {on_med:.0f}°C{off_str}")
        tips.append(
            f"Вентилятор 1: включений {len(fan_on_temps)}, медиана вкл {on_med:.1f} °C"
            + (f", выкл {statistics.median(fan_off_temps):.1f} °C." if fan_off_temps else ".")
        )
        if on_med > 106.0:
            status = "status-bad"
            val_parts.append("[ПОЗДНИЙ ВЕНТ]")
        elif on_med < 93.0:
            status = "status-warn"
            val_parts.append("[РАННИЙ ВЕНТ]")
    else:
        norm_parts.append("Вентилятор не включался")
        tips.append("Вентилятор охлаждения за поездку не включался (норма: вкл ~99–103 °C).")

    if thermo_sags:
        worst_t, worst_e, worst_s = min(thermo_sags, key=lambda x: x[1])
        if worst_e < 73.0:
            status = "status-bad"
        elif status == "status-ok":
            status = "status-warn"
        val_parts.append(f"[ПРОСАДКА {worst_e:.0f}°C]")
        norm_parts[0] = f"Просадка после 82°C до {worst_e:.0f}°C"
        tips.append(
            f"После прогрева ≥ 82 °C зафиксировано падение ДТОЖ до {worst_e:.1f} °C "
            f"на {fmt_sec(worst_t)} (скорость {worst_s:.0f} км/ч) — термостат недозакрывается."
        )

    if stuck_sec >= 240.0 and ect_max < 75.0:
        status = "status-bad"
        val_parts.append("[ЗАВИС ДТОЖ]")
        tips.append(f"Показания ДТОЖ не менялись {stuck_sec:.0f} с при работающем ДВС — проверьте датчик/проводку.")

    if ect_max >= 108.0:
        status = "status-bad"
        val_parts.append("[ПЕРЕГРЕВ]")
        tips.append(f"Критическая температура ОЖ {ect_max:.1f} °C — риск перегрева двигателя.")

    return make_card(
        "Термостат и вентилятор",
        " ".join(val_parts),
        " | ".join(norm_parts),
        status=status,
        tooltip=" ".join(tips),
    )


def check_cold_start_temps(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """2. Сверка ДТОЖ и ДТВ на старте (до пуска двигателя)."""
    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    iat_all = col_vals(table, COL["IAT"])

    pre_idx = [i for i in valid_idx if i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] < 100]
    if not pre_idx and valid_idx:
        pre_idx = valid_idx[: min(5, len(valid_idx))]

    ect_pre = sub(ect_all, pre_idx)
    iat_pre = sub(iat_all, pre_idx)

    if not ect_pre or not iat_pre:
        return make_card(
            "ДТОЖ и ДТВ на старте",
            "Нет данных",
            "Норма расхождения на холодную ≤ 6 °C",
            status="status-na",
            tooltip="Отсутствуют показания ДТОЖ или ДТВ в начале лога.",
        )

    ect0 = statistics.median(ect_pre)
    iat0 = statistics.median(iat_pre)
    diff = abs(iat0 - ect0)

    if ect0 <= 35.0:
        norm_txt = f"ДТОЖ {ect0:.0f}°C / ДТВ {iat0:.0f}°C (норма Δ ≤ 6°C)"
        if diff <= 6.0:
            status, tag = "status-ok", f"Δ {diff:.1f} °C (НОРМА)"
            msg = f"Холодный старт: ДТОЖ {ect0:.1f} °C, ДТВ {iat0:.1f} °C — датчики согласованы."
        elif diff <= 11.0:
            status, tag = "status-warn", f"СДВИГ Δ {diff:.1f} °C"
            msg = (
                f"Холодный старт: ДТОЖ {ect0:.1f} °C, ДТВ {iat0:.1f} °C (разница {diff:.1f} °C) — "
                "небольшой дрейф одного из температурных датчиков."
            )
        else:
            status, tag = "status-bad", f"РАСХОЖДЕНИЕ {diff:.0f} °C"
            msg = (
                f"Холодный старт: ДТОЖ {ect0:.1f} °C, ДТВ {iat0:.1f} °C (разница {diff:.1f} °C) — "
                "один из датчиков врёт, возможны проблемы с пусковой смесью."
            )
    else:
        norm_txt = f"ДТОЖ {ect0:.0f}°C / ДТВ {iat0:.0f}°C (горячий старт)"
        if iat0 > 75.0 or (iat0 - ect0) > 25.0:
            status, tag = "status-warn", f"ДТВ {iat0:.0f} °C [ЖАР ВПУСК]"
            msg = f"Горячий старт: ДТОЖ {ect0:.1f} °C, ДТВ {iat0:.1f} °C — сильный прогрев впускного тракта."
        else:
            status, tag = "status-ok", f"{ect0:.0f} / {iat0:.0f} °C"
            msg = f"Тёплый/горячий пуск: ДТОЖ {ect0:.1f} °C, ДТВ {iat0:.1f} °C."

    return make_card(
        "ДТОЖ и ДТВ на старте",
        tag,
        norm_txt,
        status=status,
        tooltip=msg,
    )


def check_battery_and_alternator(
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> dict:
    """3. Напряжение АКБ до пуска, зарядка генератора и проверка масс датчиков при просадке U."""
    times = col_vals(table, COL["TIME"])
    rpm_all = col_vals(table, COL["RPM"])
    vbat_all = col_vals(table, COL["VBAT"])
    ect_all = col_vals(table, COL["ECT"])
    tps_all = col_vals(table, COL["TPS"])

    vbat_run = sub(vbat_all, run_idx)
    if not vbat_run:
        return make_card(
            "АКБ и генератор",
            "Нет данных",
            "АКБ ≥ 12.2 В | Зарядка 13.6–14.6 В",
            status="status-na",
            tooltip="Канал напряжения питания ЭБУ пуст.",
        )

    pre_idx = [i for i in valid_idx if i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] < 100]
    vbat_pre = sub(vbat_all, pre_idx)

    v_med = statistics.median(vbat_run)
    v_min = min(vbat_run)
    v_max = max(vbat_run)

    # Поиск синхронных скачков ДТОЖ/ДПДЗ при просадке напряжения (плохая масса датчиков ЭБУ)
    ground_glitches: list[str] = []
    for k in range(1, len(run_idx)):
        i0, i1 = run_idx[k - 1], run_idx[k]
        u0 = vbat_all[i0] if i0 < len(vbat_all) else None
        u1 = vbat_all[i1] if i1 < len(vbat_all) else None
        if u0 is None or u1 is None:
            continue
        if (u0 - u1) >= 0.45:
            e0 = ect_all[i0] if i0 < len(ect_all) else None
            e1 = ect_all[i1] if i1 < len(ect_all) else None
            d0 = tps_all[i0] if i0 < len(tps_all) else None
            d1 = tps_all[i1] if i1 < len(tps_all) else None
            t1 = times[i1] if i1 < len(times) else 0.0
            if e0 is not None and e1 is not None and (e1 - e0) >= 3.0:
                ground_glitches.append(f"{fmt_sec(t1)}: ΔU -{u0 - u1:.2f}В → ДТОЖ +{e1 - e0:.1f}°C")
            elif d0 is not None and d1 is not None and d0 <= 0.5 and d1 >= 1.5:
                ground_glitches.append(f"{fmt_sec(t1)}: ΔU -{u0 - u1:.2f}В → ДПДЗ {d1:.1f}%")

    status = "status-ok"
    val_parts = [f"{v_med:.2f} В"]
    norm_parts = []
    tips = [f"Напряжение при работе ДВС: медиана {v_med:.2f} В (диапазон {v_min:.2f}..{v_max:.2f} В)."]

    if vbat_pre:
        u_pre = statistics.median(vbat_pre)
        norm_parts.append(f"АКБ до пуска {u_pre:.2f}В")
        tips.append(f"АКБ до запуска двигателя: {u_pre:.2f} В (норма ≥ 12.2 В).")
        if u_pre < 11.8:
            status = "status-warn"
            val_parts.append("[СЛАБАЯ АКБ]")
    else:
        norm_parts.append("Зарядка 13.6–14.6 В")

    norm_parts.append(f"Мин {v_min:.2f}В")

    if v_med < 13.1 or v_max > 15.1:
        status = "status-bad"
        val_parts.append("[СБОЙ ЗАРЯДКИ]")
        tips.append("Критическое отклонение напряжения зарядки — проверьте генератор и регулятор напряжения.")
    elif v_med < 13.5 or v_min < 12.7:
        if status == "status-ok":
            status = "status-warn"
        val_parts.append("[ПРОСАДКА U]")
        tips.append("Просадка напряжения под нагрузкой — проверьте натяжение ремня, щётки генератора и силовые массы.")

    if ground_glitches:
        if status == "status-ok":
            status = "status-warn"
        val_parts.append("[ПЛОХАЯ МАССА?]")
        tips.append(
            "Обнаружены синхронные скачки датчиков при просадке напряжения (признак плохой массы ЭБУ): "
            + "; ".join(ground_glitches[:3])
        )

    return make_card(
        "АКБ и генератор",
        " ".join(val_parts),
        " | ".join(norm_parts),
        status=status,
        tooltip=" ".join(tips),
    )
