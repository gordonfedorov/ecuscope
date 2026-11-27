#!/usr/bin/env python3
"""Автотест целостности сгенерированного HTML-отчёта ECUScope."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class ReportDOMParser(HTMLParser):
    """Собирает ключевые элементы и атрибуты из HTML-отчёта."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.cat_groups = 0
        self.color_dots = 0
        self.checkbox_indices: list[str] = []
        self.scale_indices: list[str] = []
        self.external_urls: list[str] = []

        self.cards: list[dict] = []
        self._in_card = False
        self._card_depth = 0
        self._current_card: dict = {}
        self._capture_field: str | None = None
        self._buf: list[str] = []

        self.meta_badges: list[str] = []
        self._in_badge = False
        self._badge_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        el_id = attr_map.get("id")
        if el_id:
            self.ids.add(el_id)

        classes = set((attr_map.get("class") or "").split())

        # Проверка внешних ссылок в script/link (нарушение автономности)
        if tag == "script" and attr_map.get("src", "").startswith(("http://", "https://")):
            self.external_urls.append(attr_map["src"] or "")
        if tag == "link" and attr_map.get("href", "").startswith(("http://", "https://")):
            self.external_urls.append(attr_map["href"] or "")

        if "cat-group" in classes:
            self.cat_groups += 1
        if "color-dot" in classes:
            self.color_dots += 1

        if tag == "input":
            inp_type = attr_map.get("type", "")
            idx = attr_map.get("data-idx")
            if inp_type == "checkbox" and idx is not None:
                self.checkbox_indices.append(idx)
            elif "scale-input" in classes and idx is not None:
                self.scale_indices.append(idx)

        if "meta-badge" in classes:
            self._in_badge = True
            self._badge_buf = []

        if "check-card" in classes:
            self._in_card = True
            self._card_depth = 1
            status = next((c for c in classes if c.startswith("status-")), "unknown")
            self._current_card = {"status": status, "title": "", "val": "", "norm": ""}
            return

        if self._in_card:
            if tag == "div":
                self._card_depth += 1
            if "check-title" in classes:
                self._capture_field = "title"
                self._buf = []
            elif "check-val" in classes:
                self._capture_field = "val"
                self._buf = []
            elif "check-norm" in classes:
                self._capture_field = "norm"
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._in_badge:
            self._badge_buf.append(data)
        if self._in_card and self._capture_field:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_badge and tag == "div":
            self.meta_badges.append("".join(self._badge_buf).strip())
            self._in_badge = False

        if self._in_card:
            if self._capture_field and tag == "div":
                text = " ".join("".join(self._buf).split())
                self._current_card[self._capture_field] = text
                self._capture_field = None
            if tag == "div":
                self._card_depth -= 1
                if self._card_depth <= 0:
                    self.cards.append(self._current_card)
                    self._in_card = False


def validate_html(html_path: Path, strict_sample_checks: bool = True) -> bool:
    errors: list[str] = []
    warnings: list[str] = []

    if not html_path.exists():
        print(f"[FAIL] Файл отчёта не найден: {html_path}")
        return False

    size_kb = html_path.stat().st_size / 1024
    if size_kb < 50:
        errors.append(f"Слишком маленький размер HTML ({size_kb:.1f} КБ) — возможно, не встроился Plotly.")

    html = html_path.read_text(encoding="utf-8")

    # 1. Нераскрытые плейсхолдеры шаблона
    placeholders = sorted(set(re.findall(r"__[A-Z0-9_]{3,}__", html)))
    if placeholders:
        errors.append(f"Остались нераскрытые плейсхолдеры шаблона: {', '.join(placeholders)}")

    # 2. Разбор DOM
    dom = ReportDOMParser()
    dom.feed(html)

    if dom.external_urls:
        errors.append(f"Обнаружены внешние сетевые ресурсы (нарушение офлайн-режима): {dom.external_urls}")

    required_ids = {"sidebar", "param-list", "summary-panel", "chart", "btn-normalize-side", "btn-scale-reset"}
    missing_ids = required_ids - dom.ids
    if missing_ids:
        errors.append(f"Отсутствуют обязательные элементы интерфейса (id): {', '.join(sorted(missing_ids))}")

    if dom.cat_groups < 3:
        errors.append(f"Сломана группировка параметров в левой панели (найдено групп: {dom.cat_groups})")

    if dom.color_dots == 0 or len(dom.color_dots if isinstance(dom.color_dots, list) else range(dom.color_dots)) != len(dom.checkbox_indices):
        errors.append(f"Несовпадение цветных меток ({dom.color_dots}) и чекбоксов ({len(dom.checkbox_indices)})")

    if len(dom.checkbox_indices) != len(dom.scale_indices) or not dom.checkbox_indices:
        errors.append(f"Сломаны поля множителя масштаба: чекбоксов={len(dom.checkbox_indices)}, полей scale={len(dom.scale_indices)}")

    # 3. Проверка JSON-данных графика
    m_traces = re.search(r"const\s+rawTracesY\s*=\s*(\[.*?\]);\s*\n", html, re.DOTALL)
    m_names = re.search(r"const\s+baseNames\s*=\s*(\[.*?\]);\s*\n", html, re.DOTALL)
    if not m_traces or not m_names:
        errors.append("Не найдены JS-массивы данных графика (rawTracesY / baseNames).")
    else:
        try:
            traces = json.loads(m_traces.group(1))
            names = json.loads(m_names.group(1))
            if len(traces) != len(names) or len(traces) != len(dom.checkbox_indices):
                errors.append(
                    f"Рассинхрон индексов графика: traces={len(traces)}, names={len(names)}, checkboxes={len(dom.checkbox_indices)}"
                )
        except json.JSONDecodeError as exc:
            errors.append(f"Повреждён JSON данных графика: {exc}")

    if "Plotly.newPlot" not in html:
        errors.append("В отчёте отсутствует вызов инициализации графика Plotly.newPlot.")

    # 4. Проверка шапки поездки и карточек диагностики
    if not dom.meta_badges:
        errors.append("Отсутствуют бейджи сводки поездки (.meta-badge).")
    else:
        meta_text = " | ".join(dom.meta_badges)
        if "Время лога: 0 с" in meta_text:
            errors.append("Время лога определилось как 0 с — проверьте парсинг меток времени.")

    if len(dom.cards) < 20:
        errors.append(f"Слишком мало диагностических карточек: {len(dom.cards)} (ожидается >= 20).")

    empty_norms = [c["title"] for c in dom.cards if not c["norm"]]
    if empty_norms:
        warnings.append(f"Карточки без серого примечания (.check-norm): {', '.join(empty_norms)}")

    if strict_sample_checks:
        must_have_data = ["ДПДЗ", "РХХ", "Термостат", "ДТОЖ", "АКБ", "ДМРВ", "УОЗ", "Детонац"]
        for kw in must_have_data:
            matched = [c for c in dom.cards if kw.lower() in c["title"].lower()]
            if not matched:
                errors.append(f"Не найдена обязательная карточка по ключу '{kw}'.")
            elif any(c["status"] == "status-na" for c in matched):
                errors.append(f"Карточка '{matched[0]['title']}' вернула НЕТ ДАННЫХ на эталонном логе!")

    # Вывод отчёта
    print(f"=== Проверка HTML-отчёта: {html_path.name} ({size_kb:.1f} КБ) ===")
    print(f"Параметров в панели: {len(dom.checkbox_indices)} | Групп: {dom.cat_groups} | Карточек: {len(dom.cards)}")
    if dom.meta_badges:
        print("Сводка:", " | ".join(dom.meta_badges))

    for w in warnings:
        print(f"[WARN] {w}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        print("\nИТОГ: ОТЧЁТ СЛОМАН")
        return False

    print("\nИТОГ: [OK] Все проверки целостности HTML-отчёта пройдены успешно!")
    return True


def main() -> None:
    root = Path(__file__).resolve().parent
    if len(sys.argv) > 1:
        ok = validate_html(Path(sys.argv[1]), strict_sample_checks=False)
        sys.exit(0 if ok else 1)

    sample_log = root / "examples" / "sample_bosch_m797.log"
    if not sample_log.exists():
        print(f"[FAIL] Эталонный лог не найден: {sample_log}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_html = Path(tmpdir) / "test_report.html"
        cmd = [sys.executable, str(root / "diagnose.py"), str(sample_log), "--html", str(out_html), "--no-browser"]
        res = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if res.returncode != 0:
            print("[FAIL] Ошибка запуска diagnose.py:")
            print(res.stdout)
            print(res.stderr)
            sys.exit(1)
        ok = validate_html(out_html, strict_sample_checks=True)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
