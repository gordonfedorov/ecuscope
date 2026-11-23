#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose.py — ECUScope — Здоровье мотора.
Главный модуль CLI: загрузка логов OpenDiag / Parquet, расчёт метрик поездки,
сборка сводной панели диагностики и генерация интерактивного HTML-графика Plotly.
"""

import argparse
import html as html_lib
import json
import math
import os
import statistics
import sys
import webbrowser
from pathlib import Path

import plotly.graph_objects as go
import pyarrow as pa

from diagnose_checks import run_extra_checks
from diagnose_checks_base import run_base_checks
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
    WARM_ECT_C,
    col_vals,
    format_duration,
)
from parser import load_table, save_csv, save_parquet


def get_valid_indices(table: pa.Table) -> list[int]:
    """Возвращает индексы валидных кадров без заглушек 0xDD при потере связи с ЭБУ."""
    n = table.num_rows
    if n == 0:
        return []

    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    err_all = col_vals(table, COL["ERR"])

    valid = []
    for i in range(n):
        rpm = rpm_all[i] if i < len(rpm_all) else None
        ect = ect_all[i] if i < len(ect_all) else None
        err = err_all[i] if i < len(err_all) else None

        if err == 221 and (rpm is None or rpm >= 8800) and (ect is None or ect >= 220.0):
            continue
        if rpm is not None and rpm > 8500:
            continue
        if ect is not None and (ect < -45.0 or ect > 160.0):
            continue
        valid.append(i)

    return valid


def analyze_log(table: pa.Table) -> dict:
    """Выполняет полный расчёт метрик поездки и запускает все диагностические проверки."""
    valid_idx = get_valid_indices(table)
    if not valid_idx:
        return {"valid_count": 0, "meta": [], "checks": []}

    times_raw = col_vals(table, COL["TIME"])
    rpm_all = col_vals(table, COL["RPM"])
    ect_all = col_vals(table, COL["ECT"])
    spd_all = col_vals(table, COL["SPD"])
    tps_all = col_vals(table, COL["TPS"])
    fuel_all = col_vals(table, COL["FUEL"])
    idle_flag = col_vals(table, COL["IDLE"])
    fcut_flag = col_vals(table, COL["FCUT"])

    run_idx = [
        i for i in valid_idx
        if i < len(rpm_all) and rpm_all[i] is not None and rpm_all[i] >= 450
    ]

    hot_idle_idx = [
        i for i in run_idx
        if IDLE_RPM_MIN <= rpm_all[i] <= IDLE_RPM_MAX
        and (i < len(ect_all) and ect_all[i] is not None and ect_all[i] >= WARM_ECT_C)
        and (i >= len(fcut_flag) or fcut_flag[i] != 1)
        and (
            (i < len(idle_flag) and idle_flag[i] == 1)
            or (i < len(tps_all) and tps_all[i] is not None and tps_all[i] < 1.5)
        )
    ]

    # Интегрирование длительности, пробега и расхода топлива
    total_sec = 0.0
    run_sec = 0.0
    idle_sec = 0.0
    dist_km = 0.0
    fuel_l = 0.0

    for pos in range(len(valid_idx) - 1):
        i0 = valid_idx[pos]
        i1 = valid_idx[pos + 1]
        if i0 >= len(times_raw) or i1 >= len(times_raw):
            continue
        t0, t1 = times_raw[i0], times_raw[i1]
        if t0 is None or t1 is None:
            continue
        dt = t1 - t0
        if dt <= 0.0 or dt > 10.0:
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

    checks = []
    checks.extend(run_base_checks(table, valid_idx, run_idx, hot_idle_idx))
    checks.extend(run_extra_checks(table, valid_idx, run_idx, hot_idle_idx))

    return {
        "valid_count": len(valid_idx),
        "meta": meta,
        "checks": checks,
    }


def render_summary_html(report: dict) -> str:
    """Формирует HTML-разметку верхней панели сводки и карточек проверок."""
    meta_html = "".join(
        f'<span class="meta-badge">{html_lib.escape(k)}: <b>{html_lib.escape(v)}</b></span>'
        for k, v in report.get("meta", [])
    )

    checks = report.get("checks", [])
    bad_cnt = sum(1 for c in checks if c.get("status") == "status-bad")
    warn_cnt = sum(1 for c in checks if c.get("status") == "status-warn")

    stat_badges = []
    if bad_cnt:
        stat_badges.append(f'<span class="meta-badge" style="border-color:#ff4d4d;color:#ff8080">Ошибок: <b>{bad_cnt}</b></span>')
    if warn_cnt:
        stat_badges.append(f'<span class="meta-badge" style="border-color:#ffab00;color:#ffd54f">Внимание: <b>{warn_cnt}</b></span>')

    cards_html = []
    for c in checks:
        st = html_lib.escape(c.get("status", "status-na"))
        title = html_lib.escape(c.get("title", ""))
        badge = html_lib.escape(c.get("badge", ""))
        val = html_lib.escape(c.get("val", ""))
        norm = html_lib.escape(c.get("norm", ""))
        tip = c.get("tooltip")
        tip_attr = f' title="{html_lib.escape(tip)}"' if tip else ""
        cards_html.append(
            f'<div class="check-card {st}"{tip_attr}>'
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
    if "впрыск" in low or "кислород" in low or "лямбда" in low or "коррекц" in low or "адсорбер" in low or "топлив" in low or "форс" in low or "катализатор" in low:
        return "Топливо и датчики кислорода"
    if "температур" in low or "напряж" in low or "ошибок" in low or "сброс" in low or "сумма" in low or "сопротивлен" in low or "ускорен" in low or "рециркуляц" in low:
        return "Температуры, питание и ЭБУ"
    return "Двигатель, воздух и нагрузка"


def build_interactive_html(
    table: pa.Table,
    html_path: str | os.PathLike,
    default_visible: list[str],
    title: str | None = None,
) -> None:
    """Генерирует автономный HTML-файл отчёта с панелью диагностики и графиком Plotly."""
    valid_idx = get_valid_indices(table)
    if not valid_idx:
        raise ValueError("В таблице отсутствуют валидные кадры для построения графика.")

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

    trace_idx = 0
    for col_name in table.column_names:
        if col_name in EXCLUDE_COLS:
            continue

        col_list = table[col_name].to_pylist()
        raw_y: list[float | None] = []
        has_numeric = False

        for i in valid_idx:
            val = col_list[i] if i < len(col_list) else None
            if val is None:
                raw_y.append(None)
            elif isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val):
                raw_y.append(round(float(val), 5))
                has_numeric = True
            else:
                raw_y.append(None)

        if not has_numeric:
            continue

        color = BASE_COLORS[trace_idx % len(BASE_COLORS)]
        def_scale = float(DEFAULT_SCALES.get(col_name, 1.0))
        is_vis = col_name in default_set

        scaled_y = (
            raw_y
            if def_scale == 1.0
            else [None if v is None else round(v * def_scale, 5) for v in raw_y]
        )
        trace_name = col_name if def_scale == 1.0 else f"{col_name} [x{def_scale:g}]"

        fig.add_trace(
            go.Scattergl(
                x=x_vals,
                y=scaled_y,
                customdata=raw_y,
                name=trace_name,
                mode="lines",
                line=dict(color=color, width=1.6),
                visible=True if is_vis else False,
                hovertemplate="%{fullData.name}: <b>%{customdata}</b><extra></extra>",
            )
        )

        cat = _classify_column(col_name)
        grouped.setdefault(cat, []).append((trace_idx, col_name, color, def_scale, is_vis))
        raw_traces_y.append(raw_y)
        base_names.append(col_name)
        trace_idx += 1

    groups_html_parts = []
    for cat in CATEGORY_ORDER:
        items = grouped.get(cat, [])
        if not items:
            continue
        rows = []
        for idx, name, color, def_scale, is_vis in items:
            checked_attr = " checked" if is_vis else ""
            esc_name = html_lib.escape(name)
            esc_lower = html_lib.escape(name.lower())
            rows.append(
                f'<div class="param-row" data-name="{esc_lower}">'
                f'<label class="param-item">'
                f'<input type="checkbox" data-idx="{idx}"{checked_attr}>'
                f'<span class="color-dot" style="background:{color}"></span>'
                f"<span>{esc_name}</span>"
                f"</label>"
                f'<div class="scale-box">'
                f'<span class="scale-prefix">x</span>'
                f'<input type="text" class="scale-input" data-idx="{idx}" '
                f'data-default-scale="{def_scale:g}" value="{def_scale:g}">'
                f"</div>"
                f"</div>"
            )
        open_attr = " open" if any(it[4] for it in items) else ""
        groups_html_parts.append(
            f'<details class="cat-group"{open_attr}>'
            f'<summary class="cat-title">{html_lib.escape(cat)} '
            f'<span class="cat-count">({len(items)})</span></summary>'
            f'<div class="cat-body">{"".join(rows)}</div>'
            f"</details>"
        )

    chart_title = title or f"ECUScope — Здоровье мотора ({Path(html_path).stem})"
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#000000",
        plot_bgcolor="#05070a",
        title=dict(text=chart_title, font=dict(size=14, color="#e6edf3"), x=0.01),
        margin=dict(l=55, r=20, t=42, b=42),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1.0, font=dict(size=11)),
        xaxis=dict(
            title="Время (с)",
            gridcolor="#161b22",
            zerolinecolor="#30363d",
            range=[min_time, max_time],
        ),
        yaxis=dict(
            title="Масштабированное значение",
            gridcolor="#161b22",
            zerolinecolor="#30363d",
        ),
    )

    plot_div = fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        div_id="chart",
        config={"responsive": True, "displaylogo": False},
    )

    out_html = HTML_TEMPLATE
    out_html = out_html.replace("__GROUPS_HTML__", "\n".join(groups_html_parts))
    out_html = out_html.replace("__SUMMARY_HTML__", summary_html)
    out_html = out_html.replace("__PLOT_DIV__", plot_div)
    out_html = out_html.replace("__DEFAULT_JSON__", json.dumps(default_visible, ensure_ascii=False))
    out_html = out_html.replace("__RAW_TRACES_JSON__", json.dumps(raw_traces_y))
    out_html = out_html.replace("__BASE_NAMES_JSON__", json.dumps(base_names, ensure_ascii=False))
    out_html = out_html.replace("__MIN_TIME__", str(min_time))
    out_html = out_html.replace("__MAX_TIME__", str(max_time))

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(out_html)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ECUScope — Здоровье мотора: анализ диагностических логов ЭБУ Bosch M7.9.7 / M7.9.7+."
    )
    parser.add_argument("input", help="Путь к логу OpenDiag (.log/.txt) или таблице (.parquet)")
    parser.add_argument("--html", help="Путь для сохранения HTML-отчёта (по умолчанию рядом с исходным файлом)")
    parser.add_argument("--parquet", help="Путь для сохранения Parquet (при чтении сырого лога)")
    parser.add_argument("--csv", help="Дополнительно экспортировать таблицу в CSV")
    parser.add_argument("--title", help="Заголовок графика в отчёте")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать HTML-отчёт в браузере автоматически")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Ошибка: файл не найден: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        table, is_raw = load_table(input_path)
    except Exception as exc:
        print(f"Ошибка загрузки файла {input_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if table.num_rows == 0:
        print(f"Пропуск: в файле {input_path} отсутствуют кадры диагностики (только инициализация или нет ответа ЭБУ).")
        sys.exit(0)

    valid_idx = get_valid_indices(table)
    if not valid_idx:
        print(f"Пропуск: в файле {input_path} отсутствуют рабочие кадры (только заглушки или нет связи с ЭБУ).")
        sys.exit(0)

    if is_raw:
        pq_path = Path(args.parquet) if args.parquet else input_path.with_suffix(".parquet")
        save_parquet(table, pq_path)
        print(f"Сохранено в Parquet: {pq_path}")

    if args.csv:
        csv_path = Path(args.csv)
        save_csv(table, csv_path)
        print(f"Сохранено в CSV: {csv_path}")

    html_path = Path(args.html) if args.html else input_path.with_suffix(".html")
    try:
        build_interactive_html(table, html_path, DEFAULT_VISIBLE, args.title)
    except ValueError as exc:
        print(f"Пропуск {input_path}: {exc}")
        sys.exit(0)

    print(f"Отчёт сохранён: {html_path}")

    if not args.no_browser:
        webbrowser.open(html_path.resolve().as_uri())


if __name__ == "__main__":
    main()
