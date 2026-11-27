#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ECUScope — генератор интерактивного HTML-отчёта, промежуточного JSON и диагностики логов ЭБУ."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
import re
import statistics
import sys
import webbrowser
from pathlib import Path

import plotly.graph_objects as go
import pyarrow as pa

from diagnose_checks import run_base_checks, run_extra_checks
from diagnose_templates import (
    BASE_COLORS,
    CATEGORY_ORDER,
    DEFAULT_SCALES,
    DEFAULT_VISIBLE,
    EXCLUDE_COLS,
    FLAG_COLS,
    HTML_TEMPLATE,
)
from diagnose_utils import (
    COL,
    IDLE_RPM_MAX,
    IDLE_RPM_MIN,
    IDLE_SPD_MAX,
    IDLE_TPS_MAX,
    WARM_ECT_C,
    col_vals,
    format_duration,
)
from parser import load_table, save_csv, save_parquet


def _deduplicate_table(table: pa.Table) -> pa.Table:
    """Удаляет дублирующиеся колонки из таблицы PyArrow с сохранением первого вхождения."""
    seen: set[str] = set()
    keep_indices: list[int] = []
    for idx, name in enumerate(table.column_names):
        if name not in seen:
            seen.add(name)
            keep_indices.append(idx)
    if len(keep_indices) == table.num_columns:
        return table
    return table.select(keep_indices)


def get_valid_indices(table: pa.Table) -> list[int]:
    """Возвращает индексы валидных кадров лога (отсекает мусор и обрывы связи)."""
    n = table.num_rows
    if n == 0:
        return []

    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    vbat_all = col_vals(table, COL["VBAT"])

    valid: list[int] = []
    for i in range(n):
        rpm = rpm_all[i] if i < len(rpm_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        vbat = vbat_all[i] if i < len(vbat_all) else None

        if rpm is None and ect is None and vbat is None:
            continue
        if rpm is not None and (rpm < 0 or rpm > 10000):
            continue
        if ect is not None and (ect < -45.0 or ect > 160.0):
            continue
        valid.append(i)

    return valid


_CARD_TRACES_RULES: list[tuple[tuple[str, ...], list[str]]] = [
    (("перекрёстный", "сводн"), ["RPM", "MAF", "TPS", "FR", "IAC"]),
    (("пуск", "прокрут"), ["RPM", "VBAT", "ECT", "ECT_START"]),
    (("напряжен", "акб", "генератор"), ["VBAT", "RPM", "ECT", "TPS"]),
    (("термостат", "вентилятор"), ["ECT", "FAN1", "SPD", "RPM"]),
    (("дтож и дтв", "на старте"), ["ECT", "IAT", "RPM"]),
    (("температура ож",), ["ECT", "IAT", "FAN1", "SPD"]),
    (("дпдз", "отсечка пхх"), ["TPS", "ADC_TPS", "INJ", "DFCO_FLAG", "RPM"]),
    (("рхх", "подсос"), ["IAC", "RPM", "RPM_DESIRED", "TPS"]),
    (("дмрв", "расход воздуха"), ["MAF", "ADC_MAF", "TPS", "RPM"]),
    (("резкий газ", "отклик"), ["TPS", "MAF", "INJ", "RPM"]),
    (("детонац", "отскок уоз"), ["RPM", "IGN", "KNOCK_RETARD", "LOAD"]),
    (("пропуск",), ["RPM", "MIS_CYL_1", "MIS_CYL_2", "MIS_CYL_3", "MIS_CYL_4", "CRANK_UNBAL"]),
    (("дпкв", "динамика уоз"), ["RPM", "IGN", "SPD", "CRANK_UNBAL"]),
    (("уоз",), ["IGN", "IAC", "RPM", "TPS"]),
    (("провал", "обороты хх"), ["RPM", "RPM_DESIRED", "IAC", "TPS"]),
    (("кислород", "дк1", "дк2"), ["O2_1", "O2_2", "FR", "O2_FB1", "RPM"]),
    (("катализатор",), ["O2_2", "O2_1", "CAT_AMP_IDX", "RPM"]),
    (("адсорбер", "кпа"), ["PURGE", "FR", "IAC", "RPM"]),
    (("баланс смеси", "коррекц", "адаптац"), ["FR", "FRA", "RKAT", "MAF", "RPM"]),
    (("форсунк", "топливоподач", "впрыск", "расход топлива"), ["INJ", "INJ_DUTY", "FR", "TPS", "RPM"]),
    (("ошибк",), ["ERR", "MIL", "RPM"]),
]


def _extract_event_timestamps(text: str) -> list[float]:
    """Извлекает отметки времени в секундах из текста/подсказки карточки (например '142.5с' или '142с (2:22)')."""
    found: list[float] = []
    for m in re.finditer(r"(?<![\d.,])(\d+(?:\.\d+)?)\s*с(?:\s*\(\d+:\d+\)|(?=[\s,.;:!?)\]]|$))", text):
        try:
            val = float(m.group(1))
            if 0.0 <= val <= 86400.0:
                found.append(val)
        except ValueError:
            continue
    return found


def _attach_card_focus(
    checks: list[dict],
    table: pa.Table,
    valid_idx: list[int],
    run_idx: list[int],
    hot_idle_idx: list[int],
) -> None:
    """Добавляет каждой карточке поле focus (интервал времени и целевые датчики для графика Plotly)."""
    if not valid_idx:
        return

    times_raw = col_vals(table, COL["TIME"])
    t_valid = [float(times_raw[i]) for i in valid_idx if i < len(times_raw) and times_raw[i] is not None]
    if not t_valid:
        return

    t_min, t_max = min(t_valid), max(t_valid)
    t_span = max(1.0, t_max - t_min)

    t_run = [float(times_raw[i]) for i in run_idx if i < len(times_raw) and times_raw[i] is not None]
    t_idle = [float(times_raw[i]) for i in hot_idle_idx if i < len(times_raw) and times_raw[i] is not None]

    avail_cols = set(table.column_names) - EXCLUDE_COLS

    for card in checks:
        title = str(card.get("title", ""))
        title_low = title.lower()
        combined_text = f"{card.get('val', '')}\n{card.get('tooltip', '')}"

        # 1. Подбор целевых датчиков
        col_keys = ["RPM", "MAF", "TPS", "ECT"]
        for keywords, keys in _CARD_TRACES_RULES:
            if any(kw in title_low for kw in keywords):
                col_keys = keys
                break

        traces: list[str] = []
        for k in col_keys:
            cname = COL.get(k, k)
            if cname in avail_cols and cname not in traces:
                traces.append(cname)
        if not traces:
            traces = [c for c in DEFAULT_VISIBLE if c in avail_cols]

        # 2. Определение временного интервала [start, end] и маркера события
        ts_list = _extract_event_timestamps(combined_text)
        event_t: float | None = None

        if ts_list:
            event_t = ts_list[0]
            half_win = min(25.0, max(12.0, t_span * 0.08))
            start_t = max(t_min, event_t - half_win)
            end_t = min(t_max, event_t + half_win)
        elif any(kw in title_low for kw in ("пуск", "на старте")):
            t0 = t_valid[0]
            start_t = t_min
            end_t = min(t_max, t0 + min(45.0, max(15.0, t_span * 0.25)))
            if t_run:
                event_t = t_run[0]
        elif any(kw in title_low for kw in ("хх", "подсос", "рхх")) and t_idle:
            mid_t = t_idle[len(t_idle) // 2]
            half_win = min(40.0, max(15.0, t_span * 0.15))
            start_t = max(t_min, mid_t - half_win)
            end_t = min(t_max, mid_t + half_win)
        else:
            start_t = t_min
            end_t = t_max

        if end_t - start_t < 2.0:
            start_t = t_min
            end_t = t_max

        card["focus"] = {
            "title": title,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
            "event_t": round(event_t, 3) if event_t is not None else None,
            "traces": traces,
        }


def analyze_log(table: pa.Table, source_name: str = "") -> dict:
    """Выполняет полный расчёт метрик поездки и запускает все диагностические проверки."""
    table = _deduplicate_table(table)
    valid_idx = get_valid_indices(table)
    if not valid_idx:
        return {
            "schema_version": "1.0",
            "source": source_name,
            "valid_count": 0,
            "summary": {
                "valid_frames": 0,
                "total_frames": table.num_rows,
                "total_sec": 0.0,
                "run_sec": 0.0,
                "idle_sec": 0.0,
                "distance_km": 0.0,
                "fuel_l": 0.0,
                "avg_consumption_l_100km": None,
            },
            "meta": [],
            "cards": [],
            "checks": [],
        }

    times_raw = col_vals(table, COL["TIME"])
    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    spd_all = col_vals(table, COL["SPD"])
    tps_all = col_vals(table, COL["TPS"])
    fuel_all = col_vals(table, COL["FUEL"])
    idle_flag = col_vals(table, COL["IDLE"])

    run_idx: list[int] = []
    hot_idle_idx: list[int] = []

    for i in valid_idx:
        rpm = rpm_all[i] if i < len(rpm_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        spd = spd_all[i] if i < len(spd_all) else None
        tps = tps_all[i] if i < len(tps_all) else None
        ifl = idle_flag[i] if i < len(idle_flag) else None

        if rpm is not None and rpm >= 450:
            run_idx.append(i)
            is_warm = ect is not None and ect >= WARM_ECT_C
            is_low_spd = spd is None or spd <= IDLE_SPD_MAX
            is_closed_tps = (tps is not None and tps <= IDLE_TPS_MAX) or (ifl == 1)
            is_idle_rpm = IDLE_RPM_MIN <= rpm <= IDLE_RPM_MAX
            if is_warm and is_low_spd and is_closed_tps and is_idle_rpm:
                hot_idle_idx.append(i)

    total_sec = 0.0
    run_sec = 0.0
    idle_sec = 0.0
    dist_km = 0.0
    fuel_l = 0.0

    for pos in range(len(valid_idx) - 1):
        i0 = valid_idx[pos]
        i1 = valid_idx[pos + 1]
        t0 = times_raw[i0] if i0 < len(times_raw) else None
        t1 = times_raw[i1] if i1 < len(times_raw) else None
        if t0 is None or t1 is None:
            continue
        dt = float(t1) - float(t0)
        if dt <= 0 or dt > 15.0:
            continue

        total_sec += dt
        rpm = rpm_all[i0] if i0 < len(rpm_all) else None
        spd = spd_all[i0] if i0 < len(spd_all) else None
        fl = fuel_all[i0] if i0 < len(fuel_all) else None

        if rpm is not None and rpm >= 450:
            run_sec += dt
            if spd is not None and spd > 0:
                dist_km += (spd * dt) / 3600.0
            else:
                idle_sec += dt
            if fl is not None and fl >= 0:
                fuel_l += (fl * dt) / 3600.0

    avg_cons = (fuel_l / dist_km) * 100.0 if dist_km >= 0.2 else None

    meta = [
        ("Кадров", f"{len(valid_idx)} / {table.num_rows}"),
        ("Время лога", format_duration(total_sec)),
        ("Работа ДВС", format_duration(run_sec)),
        ("Пробег", f"{dist_km:.2f} км"),
        ("Топливо", f"{fuel_l:.2f} л" + (f" ({avg_cons:.1f} л/100км)" if avg_cons is not None else "")),
        ("Простой / ХХ", format_duration(idle_sec)),
    ]

    base_checks = run_base_checks(table, valid_idx, run_idx, hot_idle_idx)
    extra_checks = run_extra_checks(table, valid_idx, run_idx, hot_idle_idx, base_results=base_checks)
    checks = list(base_checks) + list(extra_checks)
    _attach_card_focus(checks, table, valid_idx, run_idx, hot_idle_idx)

    summary = {
        "valid_frames": len(valid_idx),
        "total_frames": table.num_rows,
        "total_sec": round(total_sec, 3),
        "run_sec": round(run_sec, 3),
        "idle_sec": round(idle_sec, 3),
        "distance_km": round(dist_km, 4),
        "fuel_l": round(fuel_l, 4),
        "avg_consumption_l_100km": round(avg_cons, 2) if avg_cons is not None else None,
    }

    return {
        "schema_version": "1.0",
        "source": source_name,
        "valid_count": len(valid_idx),
        "summary": summary,
        "meta": meta,
        "cards": checks,
        "checks": checks,
    }


def save_report_json(report: dict, json_path: str | os.PathLike) -> None:
    """Сохраняет промежуточный отчёт диагностики в компактный JSON-файл."""
    serializable = {
        "schema_version": report.get("schema_version", "1.0"),
        "source": report.get("source", ""),
        "valid_count": report.get("valid_count", 0),
        "summary": report.get("summary", {}),
        "meta": [{"label": k, "value": v} for k, v in report.get("meta", [])],
        "cards": report.get("cards", report.get("checks", [])),
    }
    Path(json_path).write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


def render_summary_html(report: dict) -> str:
    """Формирует HTML-разметку верхней панели сводки и интерактивных карточек проверок."""
    meta_html = "".join(
        f'<span class="meta-badge">{html_lib.escape(k)}: <b>{html_lib.escape(v)}</b></span>'
        for k, v in report.get("meta", [])
    )

    checks = report.get("checks", [])
    bad_cnt = sum(1 for c in checks if c.get("status") == "status-bad")
    warn_cnt = sum(1 for c in checks if c.get("status") == "status-warn")

    stat_badges = []
    if bad_cnt:
        stat_badges.append(
            f'<span class="meta-badge" style="border-color:#ff4d4d;color:#ff8080">Ошибок: <b>{bad_cnt}</b></span>'
        )
    if warn_cnt:
        stat_badges.append(
            f'<span class="meta-badge" style="border-color:#ffab00;color:#ffd54f">Внимание: <b>{warn_cnt}</b></span>'
        )

    cards_html = []
    for c in checks:
        st = html_lib.escape(c.get("status", "status-na"))
        title = html_lib.escape(c.get("title", ""))
        badge = html_lib.escape(c.get("badge", ""))
        val = html_lib.escape(c.get("val", ""))
        norm = html_lib.escape(c.get("norm", ""))
        tip = c.get("tooltip")
        tip_attr = f' title="{html_lib.escape(tip)}"' if tip else ""
        focus = c.get("focus")
        focus_attr = (
            f" data-focus='{html_lib.escape(json.dumps(focus, ensure_ascii=False))}'"
            if focus
            else ""
        )
        cards_html.append(
            f'<div class="check-card {st}"{tip_attr}{focus_attr}>'
            f'<div class="check-title"><span>{title}</span><span>{badge}</span></div>'
            f'<div class="check-val">{val}</div>'
            f'<div class="check-norm">{norm}</div>'
            f"</div>"
        )

    return (
        '<div class="summary-header">'
        '<div class="meta-badges">'
        '<span class="meta-badge" style="border-color:#1f6feb;color:#79c0ff"><b>ECUScope — Здоровье мотора</b></span>'
        f"{meta_html}{''.join(stat_badges)}"
        "</div>"
        '<button type="button" id="btn-toggle-summary">Свернуть диагностику ▲</button>'
        "</div>"
        f'<div id="checks-wrap" class="checks-grid">{"".join(cards_html)}</div>'
    )


def _classify_column(col_name: str) -> str:
    """Распределяет канал ЭБУ по логическим группам левой панели."""
    low = col_name.lower()
    if col_name in FLAG_COLS or "флаг" in low or "(бит)" in low or "готовность" in low or "приостановлено" in low:
        return "Флаги и статусы"
    if "холост" in low or "шагового" in low or "регулирования хх" in low:
        return "Холостой ход (ХХ)"
    if "опережения" in low or "детонац" in low or "пропуск" in low or "неравномерност" in low or "демпфер" in low:
        return "Зажигание, детонация и пропуски"
    if (
        "впрыск" in low
        or "кислород" in low
        or "лямбда" in low
        or "коррекц" in low
        or "адсорбер" in low
        or "топлив" in low
        or "форс" in low
        or "катализатор" in low
    ):
        return "Топливо и датчики кислорода"
    if (
        "температур" in low
        or "напряж" in low
        or "ошибок" in low
        or "сброс" in low
        or "сумма" in low
        or "сопротивлен" in low
        or "ускорен" in low
        or "рециркуляц" in low
    ):
        return "Температуры, питание и ЭБУ"
    return "Двигатель, воздух и нагрузка"


def _fmt_scale(val: float) -> str:
    """Форматирует коэффициент масштаба для поля ввода."""
    if val == int(val):
        return str(int(val))
    return f"{val:g}"


def build_interactive_html(
    table: pa.Table,
    html_path: str | os.PathLike,
    default_visible: list[str],
    title: str | None = None,
    report: dict | None = None,
) -> None:
    """Генерирует автономный HTML-файл отчёта с панелью диагностики и графиком Plotly."""
    table = _deduplicate_table(table)
    valid_idx = get_valid_indices(table)
    if not valid_idx:
        raise ValueError("В таблице отсутствуют валидные кадры для построения графика.")

    if report is None:
        report = analyze_log(table)
    summary_html = render_summary_html(report)

    times_raw = col_vals(table, COL["TIME"])
    x_vals = [
        round(float(times_raw[i]), 3) if (i < len(times_raw) and times_raw[i] is not None) else float(pos)
        for pos, i in enumerate(valid_idx)
    ]
    min_time = min(x_vals) if x_vals else 0.0
    max_time = max(x_vals) if x_vals else 1.0

    default_set = set(default_visible)
    grouped: dict[str, list[tuple[int, str, str, float, bool]]] = {cat: [] for cat in CATEGORY_ORDER}

    fig = go.Figure()
    raw_traces_y: list[list[float | None]] = []
    base_names: list[str] = []
    default_indices: list[int] = []

    trace_idx = 0
    for col_name in table.column_names:
        if col_name in EXCLUDE_COLS:
            continue

        col_list = table[col_name].to_pylist()
        y_raw: list[float | None] = []
        has_numeric = False

        for i in valid_idx:
            v = col_list[i] if i < len(col_list) else None
            if v is None:
                y_raw.append(None)
            else:
                try:
                    fv = float(v)
                    if math.isnan(fv) or math.isinf(fv):
                        y_raw.append(None)
                    else:
                        y_raw.append(round(fv, 5))
                        has_numeric = True
                except (TypeError, ValueError):
                    y_raw.append(None)

        if not has_numeric:
            continue

        color = BASE_COLORS[trace_idx % len(BASE_COLORS)]
        scale = float(DEFAULT_SCALES.get(col_name, 1.0))
        is_vis = col_name in default_set

        if is_vis:
            default_indices.append(trace_idx)

        y_scaled = [
            None if v is None else (v if scale == 1.0 else round(v * scale, 5))
            for v in y_raw
        ]
        trace_name = col_name if scale == 1.0 else f"{col_name} [x{_fmt_scale(scale)}]"

        fig.add_trace(
            go.Scattergl(
                x=x_vals,
                y=y_scaled,
                customdata=y_raw,
                mode="lines",
                name=trace_name,
                line=dict(color=color, width=1.6),
                visible=True if is_vis else False,
                hovertemplate="%{fullData.name}: <b>%{customdata}</b><extra></extra>",
            )
        )

        raw_traces_y.append(y_raw)
        base_names.append(col_name)

        cat = _classify_column(col_name)
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append((trace_idx, col_name, color, scale, is_vis))
        trace_idx += 1

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#000000",
        plot_bgcolor="#080b10",
        margin=dict(l=52, r=20, t=28, b=38),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
        xaxis=dict(title="Время лога (с)", gridcolor="#1c2128", zeroline=False),
        yaxis=dict(title="Значение (с учётом масштаба)", gridcolor="#1c2128", zeroline=False),
    )

    plot_div = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        div_id="chart",
        config={"responsive": True, "displaylogo": False},
    )

    groups_blocks: list[str] = []
    ordered_cats = list(CATEGORY_ORDER) + [c for c in grouped if c not in CATEGORY_ORDER]
    for cat in ordered_cats:
        items = grouped.get(cat, [])
        if not items:
            continue
        rows_html: list[str] = []
        for idx, cname, color, scale, is_vis in items:
            checked_attr = " checked" if is_vis else ""
            esc_name = html_lib.escape(cname)
            sc_str = _fmt_scale(scale)
            rows_html.append(
                f'<div class="param-row" data-name="{esc_name.lower()}">'
                f'<label class="param-item">'
                f'<input type="checkbox" data-idx="{idx}"{checked_attr}>'
                f'<span class="color-dot" style="background:{color}"></span>'
                f"<span>{esc_name}</span>"
                f"</label>"
                f'<div class="scale-box">'
                f'<span class="scale-prefix">x</span>'
                f'<input type="text" class="scale-input" data-idx="{idx}" data-default-scale="{sc_str}" value="{sc_str}" title="Множитель масштаба">'
                f"</div>"
                f"</div>"
            )
        groups_blocks.append(
            f'<div class="cat-group">'
            f'<div class="cat-title">{html_lib.escape(cat)} <span class="cat-count">({len(items)})</span></div>'
            f'<div class="cat-body">{"".join(rows_html)}</div>'
            f"</div>"
        )

    page_title = title or f"ECUScope — {Path(html_path).stem}"
    final_html = (
        HTML_TEMPLATE.replace("__TITLE__", html_lib.escape(page_title))
        .replace("__SUMMARY_HTML__", summary_html)
        .replace("__GROUPS_HTML__", "\n".join(groups_blocks))
        .replace("__PLOT_DIV__", plot_div)
        .replace("__DEFAULT_JSON__", json.dumps(default_indices))
        .replace("__RAW_TRACES_JSON__", json.dumps(raw_traces_y))
        .replace("__BASE_NAMES_JSON__", json.dumps(base_names, ensure_ascii=False))
        .replace("__MIN_TIME__", str(min_time))
        .replace("__MAX_TIME__", str(max_time))
    )

    Path(html_path).write_text(final_html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ECUScope — диагностика логов OpenDiag (Bosch M7.9.7 / Torque PIDs) и интерактивный график."
    )
    parser.add_argument("input", help="Путь к логу OpenDiag (.log/.txt) или таблице (.parquet)")
    parser.add_argument("--html", help="Путь для сохранения HTML-отчёта (по умолчанию рядом с исходным файлом)")
    parser.add_argument("--parquet", help="Путь для сохранения Parquet (при чтении сырого лога)")
    parser.add_argument("--csv", help="Дополнительно экспортировать таблицу в CSV")
    parser.add_argument(
        "--json",
        nargs="?",
        const="",
        default=None,
        help="Сохранить промежуточный отчёт диагностики в JSON (по умолчанию <имя>.report.json)",
    )
    parser.add_argument(
        "--pid-file",
        default="pids/bosch_m797.csv",
        help="Путь к CSV-файлу формул в формате Torque Pro (по умолчанию pids/bosch_m797.csv)",
    )
    parser.add_argument("--title", help="Заголовок графика в отчёте")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать HTML-отчёт в браузере автоматически")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"Ошибка: файл не найден: {in_path}", file=sys.stderr)
        sys.exit(1)

    pid_path = Path(args.pid_file)
    if in_path.suffix.lower() != ".parquet" and not pid_path.exists():
        print(f"Ошибка: файл формул Torque не найден: {pid_path}", file=sys.stderr)
        sys.exit(1)

    table, was_raw = load_table(in_path, pid_file=pid_path)
    table = _deduplicate_table(table)

    if was_raw:
        pq_path = Path(args.parquet) if args.parquet else in_path.with_suffix(".parquet")
        save_parquet(table, pq_path)
        print(f"Сохранено в Parquet: {pq_path}")

    if args.csv:
        csv_path = Path(args.csv)
        save_csv(table, csv_path)
        print(f"Сохранено в CSV: {csv_path}")

    report = analyze_log(table, source_name=str(in_path))

    if args.json is not None:
        json_path = Path(args.json) if args.json else in_path.with_suffix(".report.json")
        save_report_json(report, json_path)
        print(f"Сохранено в JSON: {json_path}")

    html_path = Path(args.html) if args.html else in_path.with_suffix(".html")
    try:
        build_interactive_html(table, html_path, DEFAULT_VISIBLE, args.title, report=report)
    except ValueError as exc:
        print(f"Пропуск ({args.input}): {exc}")
        return
    print(f"HTML-отчёт готов: {html_path}")

    if not args.no_browser:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
