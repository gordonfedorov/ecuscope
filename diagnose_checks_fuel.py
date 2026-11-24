"""Модуль расширенных диагностических проверок топливной системы и экологии Bosch M7.9.7."""

import statistics
from diagnose_utils import COL, col_vals, sub, format_duration

WARM_ECT_C = 75.0
IDLE_RPM_MIN = 680.0
IDLE_RPM_MAX = 1020.0


def _median(vals):
    return statistics.median(vals) if vals else 0.0


def _fmt_time(sec):
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m} мин {s:04.1f} с" if m > 0 else f"{s:.1f} с"


def check_oxygen_sensors(table_or_valid, valid_or_times=None, times=None):
    """Проверка ДК1 (размах, скорость переключения, Closed Loop и нагреватель) и ДК2."""
    if isinstance(table_or_valid, dict):
        table = table_or_valid
        valid_idx = list(valid_or_times) if valid_or_times is not None else []
        t_all = col_vals(table, COL["TIME"])
    else:
        return {
            "name": "Датчики кислорода (ДК1 / ДК2)",
            "value": "Н/Д",
            "status": "warn",
            "norm": "0.10–0.85 В; период ≤ 1.5 с",
            "desc": "Недостаточно данных таблицы для анализа датчиков кислорода.",
        }

    ect_all = col_vals(table, COL["ECT"])
    rpm_all = col_vals(table, COL["RPM"])
    o2_1_all = col_vals(table, COL["O2_1"])
    o2_2_all = col_vals(table, COL["O2_2"])
    fr_all = col_vals(table, COL["FR"])
    fb1_all = col_vals(table, COL["O2_FB1"])
    r_heat1_all = col_vals(table, COL["O2_HEAT1_R"])

    warm_run = [
        i for i in valid_idx
        if ect_all[i] >= 65.0 and rpm_all[i] >= 650.0
    ]
    if len(warm_run) < 20:
        return {
            "name": "Датчики кислорода (ДК1 / ДК2)",
            "value": "Мало данных",
            "status": "warn",
            "norm": "0.10–0.85 В; период ≤ 1.5 с",
            "desc": "Недостаточно кадров прогретого двигателя (ТОЖ ≥ 65 °C) для оценки ДК1 и Closed Loop.",
        }

    # Анализ входа в Closed Loop на прогретом моторе
    cl_flags = [fb1_all[i] for i in warm_run if fb1_all[i] is not None]
    cl_ratio = (sum(1 for f in cl_flags if f > 0.5) / len(cl_flags) * 100.0) if cl_flags else None
    fr_warm = [fr_all[i] for i in warm_run if fr_all[i] is not None and fr_all[i] > 0.1]
    fr_frozen = (len(fr_warm) >= 20 and max(fr_warm) - min(fr_warm) < 0.002 and abs(_median(fr_warm) - 1.0) < 0.002)

    cl_enter_temps = [ect_all[i] for i in valid_idx if fb1_all[i] is not None and fb1_all[i] > 0.5 and ect_all[i] > -30]
    min_cl_ect = min(cl_enter_temps) if cl_enter_temps else None

    r_heat_vals = [r_heat1_all[i] for i in warm_run if r_heat1_all[i] is not None and 0.1 < r_heat1_all[i] < 500.0]
    med_r_heat = _median(r_heat_vals) if r_heat_vals else None

    # Сигнал ДК1 в замкнутом контуре (или на прогретом моторе)
    cl_idx = [i for i in warm_run if (fb1_all[i] is None or fb1_all[i] > 0.5) and o2_1_all[i] is not None]
    if len(cl_idx) < 15:
        cl_idx = [i for i in warm_run if o2_1_all[i] is not None]

    o2_1_vals = [o2_1_all[i] for i in cl_idx]
    o2_min = min(o2_1_vals) if o2_1_vals else 0.0
    o2_max = max(o2_1_vals) if o2_1_vals else 0.0
    swing = o2_max - o2_min

    # Период переключений ДК1 через порог 0.45 В
    crossings_t = []
    prev_above = None
    prev_t = None
    for i in cl_idx:
        v = o2_1_all[i]
        t = t_all[i]
        if prev_t is not None and (t - prev_t) > 2.5:
            prev_above = None
        if v >= 0.55:
            cur_above = True
        elif v <= 0.35:
            cur_above = False
        else:
            prev_t = t
            continue
        if prev_above is not None and cur_above != prev_above:
            crossings_t.append(t)
        prev_above = cur_above
        prev_t = t

    half_periods = [
        crossings_t[k] - crossings_t[k - 1]
        for k in range(1, len(crossings_t))
        if 0.08 <= (crossings_t[k] - crossings_t[k - 1]) <= 6.0
    ]
    med_period = (_median(half_periods) * 2.0) if len(half_periods) >= 4 else None

    # Оценка ДК2
    o2_2_vals = [o2_2_all[i] for i in warm_run if o2_2_all[i] is not None and 0.0 < o2_2_all[i] < 1.5]
    med_o2_2 = _median(o2_2_vals) if o2_2_vals else None

    status = "ok"
    notes = []

    if cl_ratio is not None and cl_ratio < 15.0:
        status = "bad"
        notes.append("[НЕТ CLOSED LOOP]")
    elif fr_frozen:
        status = "bad"
        notes.append("[ЗАМЕР FR=1.000]")
    elif cl_ratio is not None and cl_ratio < 55.0:
        status = "warn"
        notes.append("[СБОЙ CLOSED LOOP]")

    if swing < 0.25:
        status = "bad"
        notes.append("[ЗАВИС ДК1]")
    elif swing < 0.50:
        if status == "ok":
            status = "warn"
        notes.append("[ВЯЛЫЙ ДК1]")

    if med_period is not None:
        if med_period > 2.4:
            status = "bad"
            notes.append("[СТАРЕНИЕ ДК1]")
        elif med_period > 1.5:
            if status == "ok":
                status = "warn"
            notes.append("[МЕДЛЕННЫЙ ДК1]")

    if med_r_heat is not None and med_r_heat > 35.0:
        if status == "ok":
            status = "warn"
        notes.append("[НАГРЕВ ДК1]")

    per_str = f"T={med_period:.2f}с" if med_period is not None else "T=н/д"
    val_str = f"{o2_min:.2f}–{o2_max:.2f} В ({per_str})"
    if notes:
        val_str = f"{notes[0]} {val_str}"

    desc_parts = [
        f"Размах ДК1: {o2_min:.2f}–{o2_max:.2f} В (амплитуда {swing:.2f} В).",
    ]
    if med_period is not None:
        desc_parts.append(f"Медианный период переключений ДК1: {med_period:.2f} с (норма ≤ 1.5 с).")
    if cl_ratio is not None:
        cl_info = f"Активность замкнутого цикла (Closed Loop) при ТОЖ ≥ 65 °C: {cl_ratio:.0f}%"
        if min_cl_ect is not None:
            cl_info += f" (вход с {min_cl_ect:.0f} °C)"
        desc_parts.append(cl_info + ".")
    if med_r_heat is not None:
        desc_parts.append(f"Сопротивление нагревателя ДК1: {med_r_heat:.1f} Ом.")
    if med_o2_2 is not None:
        desc_parts.append(f"Медианный сигнал ДК2 после катализатора: {med_o2_2:.2f} В.")

    return {
        "name": "Датчики кислорода (ДК1 / ДК2)",
        "value": val_str,
        "status": status,
        "norm": "0.10–0.85 В; период ≤ 1.5 с; CL > 70%",
        "desc": " ".join(desc_parts),
    }


def check_purge_valve(table_or_valid, valid_or_times=None, times=None):
    """Проверка клапана продувки адсорбера (КПА): сдвиг смеси, ранняя продувка и раскачка ХХ."""
    if not isinstance(table_or_valid, dict):
        return {
            "name": "Продувка адсорбера (КПА)",
            "value": "Н/Д",
            "status": "ok",
            "norm": "Прогретый ДВС; ΔFR ≤ 8%",
            "desc": "Недостаточно данных для оценки клапана продувки адсорбера.",
        }

    table = table_or_valid
    valid_idx = list(valid_or_times) if valid_or_times is not None else []
    t_all = col_vals(table, COL["TIME"])
    ect_all = col_vals(table, COL["ECT"])
    rpm_all = col_vals(table, COL["RPM"])
    spd_all = col_vals(table, COL["SPD"])
    fr_all = col_vals(table, COL["FR"])
    purge_all = col_vals(table, COL["PURGE"])
    purge_flag_all = col_vals(table, COL["PURGE_FLAG"])

    run_idx = [i for i in valid_idx if rpm_all[i] >= 600.0]
    if len(run_idx) < 20:
        return {
            "name": "Продувка адсорбера (КПА)",
            "value": "Мало данных",
            "status": "ok",
            "norm": "Прогретый ДВС; ΔFR ≤ 8%",
            "desc": "Слишком короткий лог работы двигателя для оценки продувки адсорбера.",
        }

    active_idx = []
    inactive_idx = []
    cold_active_idx = []

    for i in run_idx:
        p_duty = purge_all[i] if purge_all[i] is not None else 0.0
        p_flg = purge_flag_all[i] if purge_flag_all[i] is not None else 0.0
        is_active = (p_duty >= 5.0) or (p_flg > 0.5)
        if is_active:
            active_idx.append(i)
            if ect_all[i] < 55.0:
                cold_active_idx.append(i)
        else:
            if ect_all[i] >= 65.0:
                inactive_idx.append(i)

    if not active_idx:
        return {
            "name": "Продувка адсорбера (КПА)",
            "value": "Не включалась (0%)",
            "status": "ok",
            "norm": "Прогретый ДВС; ΔFR ≤ 8%",
            "desc": "За время записи клапан продувки адсорбера не активировался (норма для коротких или холодных поездок).",
        }

    max_duty = max((purge_all[i] for i in active_idx if purge_all[i] is not None), default=0.0)
    fr_act = [fr_all[i] for i in active_idx if fr_all[i] is not None and 0.5 < fr_all[i] < 1.6 and ect_all[i] >= 65.0]
    fr_inact = [fr_all[i] for i in inactive_idx if fr_all[i] is not None and 0.5 < fr_all[i] < 1.6]

    delta_fr_pct = 0.0
    if len(fr_act) >= 10 and len(fr_inact) >= 10:
        delta_fr_pct = (_median(fr_act) - _median(fr_inact)) * 100.0

    # Проверка раскачки оборотов на ХХ во время активной продувки
    idle_purge_rpm = [
        rpm_all[i] for i in active_idx
        if ect_all[i] >= 70.0 and spd_all[i] < 2.0 and IDLE_RPM_MIN <= rpm_all[i] <= 1250.0
    ]
    rpm_spread = (max(idle_purge_rpm) - min(idle_purge_rpm)) if len(idle_purge_rpm) >= 8 else 0.0

    status = "ok"
    tag = ""
    reasons = []

    if len(cold_active_idx) >= 4:
        status = "warn"
        tag = "[ПРОДУВКА НА ХОЛОДНУЮ] "
        min_cold_t = min(ect_all[i] for i in cold_active_idx)
        first_t = _fmt_time(t_all[cold_active_idx[0]])
        reasons.append(
            f"Обнаружена активность продувки на непрогретом моторе (от {min_cold_t:.0f} °C в {first_t}) — возможен подсос через подклинивающий клапан КПА."
        )

    if rpm_spread >= 75.0:
        if status == "ok":
            status = "warn"
        if not tag:
            tag = "[РАСКАЧКА ХХ ПРИ КПА] "
        reasons.append(
            f"При продувке на холостом ходу разброс оборотов составил {rpm_spread:.0f} об/мин (норма < 70 об/мин)."
        )

    if abs(delta_fr_pct) >= 11.0:
        status = "bad" if abs(delta_fr_pct) >= 15.0 else "warn"
        if not tag:
            tag = "[СДВИГ СМЕСИ КПА] "
        reasons.append(
            f"Сдвиг коррекции смеси FR при продувке составил {delta_fr_pct:+.1f}% (избыток паров топлива или подсос через магистраль КПА)."
        )

    val_str = f"{tag}макс {max_duty:.0f}%, ΔFR {delta_fr_pct:+.1f}%"
    desc = (
        f"Максимальная скважность КПА: {max_duty:.0f}% (активных кадров: {len(active_idx)}). "
        f"Изменение коррекции смеси при продувке: {delta_fr_pct:+.1f}%. "
    )
    if reasons:
        desc += " ".join(reasons)
    else:
        desc += "Продувка включается штатно на прогретом двигателе без раскачки ХХ и переобогащения."

    return {
        "name": "Продувка адсорбера (КПА)",
        "value": val_str,
        "status": status,
        "norm": "Прогретый ДВС; ΔFR ≤ 8%",
        "desc": desc,
    }


def check_mixture_differential(table_or_valid, valid_or_times=None, times=None):
    """Дифференциальный тест смеси: сравнение FR на прогретом ХХ против 1500+ об/мин."""
    if not isinstance(table_or_valid, dict):
        return {
            "name": "Баланс смеси: ХХ vs 1500+",
            "value": "Н/Д",
            "status": "ok",
            "norm": "FR 0.93–1.07 на всех режимах",
            "desc": "Недостаточно данных для дифференциального анализа смеси.",
        }

    table = table_or_valid
    valid_idx = list(valid_or_times) if valid_or_times is not None else []
    ect_all = col_vals(table, COL["ECT"])
    rpm_all = col_vals(table, COL["RPM"])
    spd_all = col_vals(table, COL["SPD"])
    tps_all = col_vals(table, COL["TPS"])
    fr_all = col_vals(table, COL["FR"])
    fb1_all = col_vals(table, COL["O2_FB1"])

    idle_fr = []
    cruise_fr = []

    for i in valid_idx:
        if ect_all[i] < WARM_ECT_C:
            continue
        if fb1_all[i] is not None and fb1_all[i] < 0.5:
            continue
        fr = fr_all[i]
        if fr is None or not (0.65 <= fr <= 1.45):
            continue

        rpm = rpm_all[i]
        spd = spd_all[i]
        tps = tps_all[i]

        if IDLE_RPM_MIN <= rpm <= IDLE_RPM_MAX and spd < 2.0 and tps < 2.0:
            idle_fr.append(fr)
        elif 1500.0 <= rpm <= 3200.0 and 3.0 <= tps <= 45.0:
            cruise_fr.append(fr)

    if len(idle_fr) < 15 or len(cruise_fr) < 15:
        return {
            "name": "Баланс смеси: ХХ vs 1500+",
            "value": "Мало режимов",
            "status": "ok",
            "norm": "FR 0.93–1.07 на всех режимах",
            "desc": "В логе недостаточно совместных участков прогретого ХХ и движения на 1500–3200 об/мин для сравнения.",
        }

    med_idle = _median(idle_fr)
    med_cruise = _median(cruise_fr)
    diff = med_idle - med_cruise

    status = "ok"
    tag = ""
    if med_idle >= 1.07 and diff >= 0.045 and med_cruise < 1.06:
        status = "warn" if med_idle < 1.12 else "bad"
        tag = "[ПОДСОС НА ХХ] "
        diagnosis = (
            "На холостом ходу ЭБУ вынужден обогащать смесь, а при подъёме оборотов до 1500+ коррекция возвращается к норме — "
            "характерный признак подсоса неучтённого воздуха во впускной тракт."
        )
    elif med_idle >= 1.07 and med_cruise >= 1.08:
        status = "bad" if max(med_idle, med_cruise) >= 1.13 else "warn"
        tag = "[ДЕФИЦИТ ТОПЛИВА] "
        diagnosis = (
            "Обеднение смеси сохраняется и на холостом ходу, и на повышенных оборотах — вероятна нехватка давления топлива "
            "(бензонасос, фильтр, РДТ), загрязнение форсунок или занижение показаний ДМРВ."
        )
    elif med_cruise >= 1.09 and med_idle < 1.06:
        status = "warn" if med_cruise < 1.14 else "bad"
        tag = "[БЕДНАЯ ПОД НАГРУЗКОЙ] "
        diagnosis = (
            "На холостом ходу смесь в норме, но на оборотах 1500+ уходит в бедную — проверьте производительность бензонасоса, "
            "топливный фильтр и расходомер воздуха под нагрузкой."
        )
    elif med_idle <= 0.91 and med_cruise <= 0.91:
        status = "warn" if min(med_idle, med_cruise) > 0.86 else "bad"
        tag = "[БОГАТАЯ СМЕСЬ] "
        diagnosis = (
            "Устойчивое переобогащение на всех режимах — проверьте герметичность форсунок, регулятор давления топлива, "
            "клапан адсорбера или завышение показаний ДМРВ/ДТОЖ."
        )
    else:
        diagnosis = "Коррекция топливоподачи на холостом ходу и на повышенных оборотах сбалансирована и укладывается в допуск."

    val_str = f"{tag}ХХ {med_idle:.3f} / 1500+ {med_cruise:.3f}"
    desc = (
        f"Медианный коэффициент FR на прогретом ХХ: {med_idle:.3f} ({(med_idle - 1.0)*100:+.1f}%), "
        f"на оборотах 1500–3200 об/мин: {med_cruise:.3f} ({(med_cruise - 1.0)*100:+.1f}%). {diagnosis}"
    )

    return {
        "name": "Баланс смеси: ХХ vs 1500+",
        "value": val_str,
        "status": status,
        "norm": "FR 0.93–1.07 на всех режимах",
        "desc": desc,
    }


def check_catalyst_efficiency(table_or_valid, valid_or_times=None, times=None):
    """Оценка эффективности катализатора по сигналу ДК2 и индексу амплитуды."""
    if not isinstance(table_or_valid, dict):
        return {
            "name": "Катализатор (по ДК2)",
            "value": "Н/Д",
            "status": "ok",
            "norm": "ДК2 0.55–0.80 В; размах ≤ 0.25 В",
            "desc": "Недостаточно данных для оценки катализатора.",
        }

    table = table_or_valid
    valid_idx = list(valid_or_times) if valid_or_times is not None else []
    ect_all = col_vals(table, COL["ECT"])
    rpm_all = col_vals(table, COL["RPM"])
    o2_2_all = col_vals(table, COL["O2_2"])
    amp_idx_all = col_vals(table, COL["CAT_AMP_IDX"])
    ready2_all = col_vals(table, COL["O2_READY2"])

    warm_idx = [
        i for i in valid_idx
        if ect_all[i] >= 75.0 and rpm_all[i] >= 700.0
    ]
    o2_2_vals = [o2_2_all[i] for i in warm_idx if o2_2_all[i] is not None and 0.02 < o2_2_all[i] < 1.3]

    if len(o2_2_vals) < 20:
        return {
            "name": "Катализатор (по ДК2)",
            "value": "Нет сигнала ДК2",
            "status": "ok",
            "norm": "ДК2 0.55–0.80 В; размах ≤ 0.25 В",
            "desc": "Сигнал второго датчика кислорода отсутствует или датчик программно отключён (Евро-2).",
        }

    # Если напряжение ДК2 замерло на опорном ~0.45 В (прошивка Евро-2 без ДК2)
    if max(o2_2_vals) - min(o2_2_vals) < 0.03 and 0.40 <= _median(o2_2_vals) <= 0.50:
        return {
            "name": "Катализатор (по ДК2)",
            "value": "Отключён (Евро-2)",
            "status": "ok",
            "norm": "ДК2 0.55–0.80 В; размах ≤ 0.25 В",
            "desc": f"Напряжение ДК2 стабильно на опорном уровне {_median(o2_2_vals):.2f} В (конфигурация без диагностики катализатора).",
        }

    med_v = _median(o2_2_vals)
    sorted_v = sorted(o2_2_vals)
    p10 = sorted_v[int(len(sorted_v) * 0.10)]
    p90 = sorted_v[int(len(sorted_v) * 0.90)]
    span = p90 - p10

    amp_vals = [amp_idx_all[i] for i in warm_idx if amp_idx_all[i] is not None and amp_idx_all[i] > 0]
    med_amp = _median(amp_vals) if amp_vals else None

    ready_vals = [ready2_all[i] for i in warm_idx if ready2_all[i] is not None]
    is_ready = (sum(1 for r in ready_vals if r > 0.5) / len(ready_vals) > 0.3) if ready_vals else True

    status = "ok"
    tag = ""
    if is_ready and (span > 0.45 or (med_amp is not None and med_amp > 0.65)):
        status = "bad"
        tag = "[НИЗКАЯ ЭФФЕКТИВНОСТЬ] "
    elif is_ready and (span > 0.28 or (med_amp is not None and med_amp > 0.45)):
        status = "warn"
        tag = "[СНИЖЕНИЕ РЕСУРСА] "

    val_str = f"{tag}{med_v:.2f} В (размах {span:.2f} В)"
    desc = (
        f"Медианное напряжение ДК2 на прогретом двигателе: {med_v:.2f} В, рабочий размах (P10–P90): {span:.2f} В. "
    )
    if med_amp is not None:
        desc += f"Индекс амплитуды катализатора ЭБУ: {med_amp:.2f}. "
    if status == "ok":
        desc += "Задний датчик стабилен — нейтрализатор эффективно дожигает остаточный кислород."
    else:
        desc += "Сигнал ДК2 повторяет колебания первого датчика — снижена кислородная ёмкость катализатора (либо есть негерметичность выпуска)."

    return {
        "name": "Катализатор (по ДК2)",
        "value": val_str,
        "status": status,
        "norm": "ДК2 0.55–0.80 В; размах ≤ 0.25 В",
        "desc": desc,
    }


def check_injectors_and_fuel_supply(table_or_valid, valid_or_times=None, times=None):
    """Проверка загрузки форсунок и дефицита топливоподачи под нагрузкой."""
    if not isinstance(table_or_valid, dict):
        return {
            "name": "Форсунки и топливоподача",
            "value": "Н/Д",
            "status": "ok",
            "norm": "Загрузка ≤ 80%; FR ≤ 1.08",
            "desc": "Недостаточно данных для проверки топливоподачи под нагрузкой.",
        }

    table = table_or_valid
    valid_idx = list(valid_or_times) if valid_or_times is not None else []
    rpm_all = col_vals(table, COL["RPM"])
    tps_all = col_vals(table, COL["TPS"])
    inj_all = col_vals(table, COL["INJ"])
    duty_all = col_vals(table, COL["INJ_DUTY"])
    fr_all = col_vals(table, COL["FR"])
    ect_all = col_vals(table, COL["ECT"])

    run_idx = [i for i in valid_idx if rpm_all[i] >= 650.0 and ect_all[i] >= 60.0]
    if len(run_idx) < 15:
        return {
            "name": "Форсунки и топливоподача",
            "value": "Мало данных",
            "status": "ok",
            "norm": "Загрузка ≤ 80%; FR ≤ 1.08",
            "desc": "Недостаточно кадров прогретого двигателя для оценки топливоподачи.",
        }

    duties = []
    for i in run_idx:
        d = duty_all[i]
        if d is None or d <= 0.0:
            # Расчёт загрузки форсунок по оборотам и времени впрыска (4-тактный ДВС: цикл 120000 / RPM мс)
            if rpm_all[i] > 0 and inj_all[i] > 0:
                d = (inj_all[i] * rpm_all[i]) / 1200.0
        if d is not None and 0.0 < d <= 120.0:
            duties.append(d)

    max_duty = max(duties) if duties else 0.0

    # Проверка коррекции FR при повышенной нагрузке (TPS >= 35% и RPM >= 2500)
    load_fr = [
        fr_all[i] for i in run_idx
        if tps_all[i] >= 35.0 and rpm_all[i] >= 2500.0 and fr_all[i] is not None and 0.65 <= fr_all[i] <= 1.45
    ]
    med_load_fr = _median(load_fr) if len(load_fr) >= 5 else None

    status = "ok"
    tag = ""
    if max_duty >= 90.0:
        status = "bad"
        tag = "[ПЕРЕГРУЗ ФОРСУНОК] "
    elif max_duty >= 82.0:
        status = "warn"
        tag = "[ВЫСОКАЯ ЗАГРУЗКА] "

    if med_load_fr is not None:
        if med_load_fr >= 1.13:
            status = "bad"
            tag = "[НЕХВАТКА ТОПЛИВА] "
        elif med_load_fr >= 1.08 and status == "ok":
            status = "warn"
            tag = "[БЕДНО ПОД НАГРУЗКОЙ] "

    fr_part = f", FR нагр. {med_load_fr:.3f}" if med_load_fr is not None else ""
    val_str = f"{tag}пик {max_duty:.1f}%{fr_part}"

    desc = f"Максимальная загрузка форсунок за поездку: {max_duty:.1f}% (норма ≤ 80%). "
    if med_load_fr is not None:
        desc += f"Медианная коррекция FR под нагрузкой (ДПДЗ ≥ 35%, ≥ 2500 об/мин): {med_load_fr:.3f}. "
    if status == "ok":
        desc += "Производительности форсунок и давления в топливной рампе достаточно во всех режимах."
    else:
        desc += "Высокая загрузка или сильное обогащение под нагрузкой указывают на падение давления топлива (насос, фильтр, РДТ) либо загрязнение форсунок."

    return {
        "name": "Форсунки и топливоподача",
        "value": val_str,
        "status": status,
        "norm": "Загрузка ≤ 80%; FR ≤ 1.08",
        "desc": desc,
    }


def run_fuel_checks(table, valid_idx, run_idx=None, hot_idle_idx=None):
    """Запуск всех проверок топливной системы и экологии."""
    t_all = col_vals(table, COL["TIME"])
    return [
        check_oxygen_sensors(table, valid_idx, t_all),
        check_purge_valve(table, valid_idx, t_all),
        check_mixture_differential(table, valid_idx, t_all),
        check_catalyst_efficiency(table, valid_idx, t_all),
        check_injectors_and_fuel_supply(table, valid_idx, t_all),
    ]
