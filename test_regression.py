#!/usr/bin/env python3
"""Регрессионное тестирование расчётов ECUScope по эталонным промежуточным отчётам (.report.json)."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_GOLDEN_DIR = ROOT_DIR / "tests" / "golden"
DEFAULT_SAMPLE = ROOT_DIR / "examples" / "sample_bosch_m797.log"


def run_diagnose_json(input_path: Path, out_json_path: Path) -> dict:
    """Запускает diagnose.py с выгрузкой промежуточного отчёта в JSON."""
    cmd = [
        sys.executable,
        str(ROOT_DIR / "diagnose.py"),
        str(input_path),
        "--json",
        str(out_json_path),
        "--no-browser",
    ]
    res = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Ошибка выполнения diagnose.py для {input_path} (код {res.returncode}):\n"
            f"STDOUT: {res.stdout}\nSTDERR: {res.stderr}"
        )
    if not out_json_path.exists():
        raise FileNotFoundError(f"Промежуточный JSON-отчёт не был создан: {out_json_path}")
    return json.loads(out_json_path.read_text(encoding="utf-8"))


def _compare_numbers(a: float | None, b: float | None, tol: float) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def compare_reports(golden: dict, actual: dict, tol: float = 0.05) -> list[str]:
    """Сравнивает эталонный и текущий JSON-отчёты. Возвращает список расхождений."""
    diffs: list[str] = []

    g_sum = golden.get("summary", {})
    a_sum = actual.get("summary", {})

    int_fields = ["valid_frames", "total_frames"]
    for key in int_fields:
        if g_sum.get(key) != a_sum.get(key):
            diffs.append(f"summary.{key}: эталон={g_sum.get(key)!r} != текущее={a_sum.get(key)!r}")

    float_fields = ["total_sec", "run_sec", "idle_sec", "distance_km", "fuel_l", "avg_consumption_l_100km"]
    for key in float_fields:
        gv = g_sum.get(key)
        av = a_sum.get(key)
        if not _compare_numbers(gv, av, tol):
            diffs.append(f"summary.{key}: эталон={gv!r} != текущее={av!r} (допуск ±{tol})")

    g_cards = {c.get("title", f"#{idx}"): c for idx, c in enumerate(golden.get("cards", []))}
    a_cards = {c.get("title", f"#{idx}"): c for idx, c in enumerate(actual.get("cards", []))}

    if len(g_cards) != len(a_cards):
        diffs.append(f"Количество карточек изменилось: эталон={len(g_cards)}, текущее={len(a_cards)}")

    for title, gc in g_cards.items():
        if title not in a_cards:
            diffs.append(f"Карточка исчезла: '{title}'")
            continue
        ac = a_cards[title]
        for field in ("status", "badge", "val"):
            if gc.get(field) != ac.get(field):
                diffs.append(
                    f"Карточка '{title}' [{field}]: эталон={gc.get(field)!r} != текущее={ac.get(field)!r}"
                )

    for title in a_cards:
        if title not in g_cards:
            diffs.append(f"Появилась новая карточка (нет в эталоне): '{title}'")

    return diffs


def collect_inputs(paths: list[str]) -> list[Path]:
    """Собирает список файлов логов (.log, .txt, .parquet) из переданных путей."""
    if not paths:
        return [DEFAULT_SAMPLE] if DEFAULT_SAMPLE.exists() else []

    result: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = (ROOT_DIR / p).resolve()
        if p.is_dir():
            for ext in ("*.log", "*.txt", "*.parquet"):
                result.extend(sorted(p.glob(ext)))
        elif p.exists():
            result.append(p)
        else:
            print(f"[WARN] Путь не найден и пропущен: {raw}", file=sys.stderr)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Регрессионный тест расчётов ECUScope (сравнение .report.json с эталонами)."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Пути к логам или директориям (по умолчанию examples/sample_bosch_m797.log)",
    )
    parser.add_argument(
        "--golden-dir",
        default=str(DEFAULT_GOLDEN_DIR),
        help="Директория для хранения эталонных .report.json (по умолчанию tests/golden)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Обновить (перезаписать) эталонные .report.json текущими результатами расчёта",
    )
    parser.add_argument(
        "--tol",
        type=float,
        default=0.05,
        help="Абсолютный допуск сравнения числовых метрик в summary (по умолчанию 0.05)",
    )
    args = parser.parse_args()

    inputs = collect_inputs(args.inputs)
    if not inputs:
        print("[FAIL] Не найдено ни одного входного лога для тестирования.", file=sys.stderr)
        sys.exit(1)

    golden_dir = Path(args.golden_dir)
    if not golden_dir.is_absolute():
        golden_dir = (ROOT_DIR / golden_dir).resolve()

    if args.update:
        golden_dir.mkdir(parents=True, exist_ok=True)
        for inp in inputs:
            target = golden_dir / f"{inp.stem}.report.json"
            data = run_diagnose_json(inp, target)
            cards_cnt = len(data.get("cards", []))
            print(f"[UPDATED] {target.relative_to(ROOT_DIR) if target.is_relative_to(ROOT_DIR) else target} (карточек: {cards_cnt})")
        print(f"\nЭталоны обновлены ({len(inputs)} шт.).")
        sys.exit(0)

    failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for inp in inputs:
            golden_file = golden_dir / f"{inp.stem}.report.json"
            if not golden_file.exists():
                print(f"[FAIL] Нет эталона для {inp.name}: ожидался {golden_file}")
                print("       Запустите скрипт с флагом --update для создания эталона.")
                failed += 1
                continue

            actual_file = tmp_path / f"{inp.stem}.report.json"
            try:
                actual_data = run_diagnose_json(inp, actual_file)
            except Exception as exc:
                print(f"[FAIL] {inp.name}: {exc}")
                failed += 1
                continue

            golden_data = json.loads(golden_file.read_text(encoding="utf-8"))
            diffs = compare_reports(golden_data, actual_data, tol=args.tol)

            if diffs:
                print(f"[FAIL] Расхождения в {inp.name} ({len(diffs)}):")
                for d in diffs:
                    print(f"   - {d}")
                failed += 1
            else:
                cards_cnt = len(actual_data.get("cards", []))
                print(f"[OK] {inp.name} — эталон подтверждён (карточек: {cards_cnt})")

    if failed:
        print(f"\nИТОГ: ПРОВАЛЕНО ({failed} из {len(inputs)})")
        sys.exit(1)

    print(f"\nИТОГ: [OK] Регрессия не обнаружена ({len(inputs)} из {len(inputs)})")
    sys.exit(0)


if __name__ == "__main__":
    main()
