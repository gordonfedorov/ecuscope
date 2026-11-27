#!/usr/bin/env bash
# Тестовый прогон модулей ECUScope, YAML-правил и логов из папки logs/

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGS_DIR="logs"
OPEN_LAST=0
FORCE_RAW=0
TARGET_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --open|-o)
            OPEN_LAST=1
            shift
            ;;
        --raw|-r)
            FORCE_RAW=1
            shift
            ;;
        --file|-f)
            TARGET_FILE="${2:-}"
            shift 2
            ;;
        --help|-h)
            echo "Использование: ./test_run.sh [опции]"
            echo "  --open, -o          Открыть последний сгенерированный HTML в браузере"
            echo "  --raw, -r           Тестировать сырые .log/.txt даже при наличии .parquet"
            echo "  --file, -f <имя>    Запустить конкретный файл (из корня или из logs/)"
            exit 0
            ;;
        *)
            TARGET_FILE="$1"
            shift
            ;;
    esac
done

echo "=== 1. Проверка импортов модулей ECUScope и YAML-правил ==="
python3 - <<'PY'
import sys
from pathlib import Path

modules = [
    "diagnose_utils",
    "parser",
    "diagnose_templates",
    "yaml_rules_engine",
    "diagnose_checks",
    "diagnose",
]

failed = False
for m in modules:
    try:
        __import__(m)
        print(f"  [OK]   {m}")
    except Exception as exc:
        print(f"  [FAIL] {m}: {exc}")
        failed = True

rules_dir = Path("rules")
yaml_files = sorted(rules_dir.glob("*.yaml")) if rules_dir.exists() else []
if not yaml_files:
    print("  [FAIL] rules/*.yaml: не найдены файлы диагностических правил")
    failed = True
else:
    print(f"  [OK]   rules/*.yaml ({len(yaml_files)} шт.: {', '.join(f.name for f in yaml_files)})")

if failed:
    sys.exit(1)
PY

if [[ $? -ne 0 ]]; then
    echo "ОШИБКА: Сбой при проверке импортов или правил. Прогон логов остановлен."
    exit 1
fi

echo ""
echo "=== 2. Сбор файлов логов ==="

FILES=()
if [[ -n "$TARGET_FILE" ]]; then
    if [[ -f "$TARGET_FILE" ]]; then
        FILES+=("$TARGET_FILE")
    elif [[ -f "$LOGS_DIR/$TARGET_FILE" ]]; then
        FILES+=("$LOGS_DIR/$TARGET_FILE")
    else
        echo "Файл не найден: $TARGET_FILE (проверены текущая папка и $LOGS_DIR/)"
        exit 1
    fi
else
    if [[ ! -d "$LOGS_DIR" ]]; then
        echo "Папка $LOGS_DIR/ не найдена."
        exit 1
    fi

    shopt -s nullglob
    if [[ $FORCE_RAW -eq 1 ]]; then
        for f in "$LOGS_DIR"/*.log "$LOGS_DIR"/*.txt "$LOGS_DIR"/*.parquet; do
            FILES+=("$f")
        done
    else
        for f in "$LOGS_DIR"/*.parquet; do
            FILES+=("$f")
        done
        for f in "$LOGS_DIR"/*.log "$LOGS_DIR"/*.txt; do
            base="${f%.*}"
            if [[ ! -f "${base}.parquet" ]]; then
                FILES+=("$f")
            fi
        done
    fi
    shopt -u nullglob
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "В папке $LOGS_DIR/ не найдено файлов (.parquet, .log, .txt)."
    exit 0
fi

echo "Найдено файлов для проверки: ${#FILES[@]}"
echo ""
echo "=== 3. Тестовый запуск diagnose.py ==="

OK_CNT=0
FAIL_CNT=0
LAST_HTML=""

for f in "${FILES[@]}"; do
    echo "-> Обработка: $f"
    START_NS=$(date +%s%N)
    python3 diagnose.py "$f" --no-browser
    RC=$?
    END_NS=$(date +%s%N)
    ELAPSED_MS=$(( (END_NS - START_NS) / 1000000 ))

    if [[ $RC -eq 0 ]]; then
        echo "   [OK] Завершено за ${ELAPSED_MS} мс"
        OK_CNT=$((OK_CNT + 1))
        CAND_HTML="${f%.*}.html"
        if [[ -f "$CAND_HTML" ]]; then
            LAST_HTML="$CAND_HTML"
        fi
    else
        echo "   [FAIL] Код возврата: $RC (${ELAPSED_MS} мс)"
        FAIL_CNT=$((FAIL_CNT + 1))
    fi
done

echo ""
echo "=== Итог: успешно $OK_CNT, с ошибками $FAIL_CNT ==="

if [[ $OPEN_LAST -eq 1 && -n "$LAST_HTML" ]]; then
    echo "Открываю в браузере: $LAST_HTML"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$LAST_HTML" >/dev/null 2>&1 &
    elif command -v open >/dev/null 2>&1; then
        open "$LAST_HTML" >/dev/null 2>&1 &
    else
        echo "Не найдена утилита xdg-open/open. Откройте вручную: $LAST_HTML"
    fi
fi

[[ $FAIL_CNT -eq 0 ]]
