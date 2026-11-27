# ECUScope — Контекст проекта для ИИ-помощника (v1.5.0)

## 1. Назначение и предметная область
**ECUScope** — автономный диагностический анализатор логов ЭБУ двигателя (преимущественно **Bosch M7.9.7 / M7.9.7+**, ВАЗ / Lada / Chevrolet Niva), записанных в **OpenDiag Mobile** (ELM327 / K-Line, запросы `2101`, `2105`, `1A90–1A92`).

Программа:
1. Парсит сырые HEX-логи (`.log`, `.txt`) и кэширует их в колоночный формат **Apache Parquet** (`.parquet`).
2. Выполняет **27 автоматических диагностических проверок** по чистым декларативным YAML-правилам (`rules/*.yaml`) без использования `eval()`/`exec()`.
3. Генерирует автономный тёмный интерактивный HTML-отчёт с графиками **Plotly** (`.html`) и опциональный структурированный JSON-отчёт (`.json`).

---

## 2. Поток обработки данных (Data Pipeline)

```text
Сырой лог (.log/.txt)
   │
   ▼ parser.py (парсинг HEX-пакетов 2101/2105/1A9x, дедупликация колонок)
Кэш Apache Parquet (.parquet)
   │
   ▼ diagnose.py (выделение индексов режимов: valid_idx, run_idx, hot_idle_idx)
   │
   ▼ diagnose_checks.py (последовательный прогон rules/*.yaml по полю order)
   │   ├── yaml_rules_engine.py (5 декларативных шаблонов проверок)
   │   └── yaml_expr.py (безопасный AST-вычислитель формул и строковых шаблонов)
   │
   ▼ diagnose.py (_attach_card_focus -> привязка датчиков и таймкодов событий к карточкам)
   │
   ├──► JSON-отчёт (--json) ──► test_regression.py
   └──► HTML-отчёт (diagnose_templates.py + Plotly) ──► test_report.py / браузер (xdg-open / wslview)
```

---

## 3. Структура репозитория

| Файл / Каталог | Назначение |
| :--- | :--- |
| `diagnose.py` | Главный CLI-оркестратор: загрузка `.log`/`.parquet`, расчёт режимов ДВС, запуск проверок, привязка `focus` к карточкам, рендер HTML и сохранение `--json`. |
| `parser.py` | Парсер сырых логов OpenDiag Mobile (80+ параметров, битовые флаги, АЦП датчиков, ID ЭБУ и прошивки) в `pyarrow.Table` -> `.parquet`. |
| `diagnose_utils.py` | Словарь `COL` (маппинг коротких ключей `RPM`, `ECT`, `FR` и др. на русские имена столбцов), хелперы `col_vals`, `sub`, `make_card`, `fmt_sec`, константы режимов (`WARM_ECT_C`, `IDLE_RPM_MIN`, `IDLE_RPM_MAX`). |
| `diagnose_checks.py` | Единый тонкий диспетчер проверок. Читает все файлы из `rules/*.yaml`, сортирует по `order`, передаёт накопленные карточки (`prior_cards`) в следующие секции. *(Заменил собой 5 старых файлов `diagnose_checks_{base,thermal,air,fuel,engine}.py` — их создавать не нужно.)* |
| `yaml_expr.py` | Безопасный AST-вычислитель выражений (`SafeExprEvaluator`) и шаблонизатор строк (`format_template`). Поддерживает поэлементную арифметику и сравнения списков (`_broadcast_binop`, `_broadcast_cmp`), операторы `is not None`, `in`, агрегаторы (`median`, `mean`, `min`, `max`, `first`, `last`, `sum`, `count`, `spread`, `p10_p90`), переменные начала/конца окна `<PARAM>_start`, `<PARAM>_end`. |
| `yaml_rules_engine.py` | Исполнитель 5 декларативных шаблонов правил (`threshold`, `compare_modes`, `event_window`, `oscillation`, `cross_diagnosis`). |
| `diagnose_templates.py` | Автономный HTML/CSS/JS-шаблон отчёта с Plotly, поиском каналов, множителями масштаба, кнопкой **«Авто-scale 0–100%»** и интерактивной навигацией при клике по карточке. |
| `rules/*.yaml` | Наборы декларативных правил без Python-кода: `base_checks.yaml`, `thermal_checks.yaml`, `air_checks.yaml`, `fuel_checks.yaml`, `engine_checks.yaml`, `cross_diagnosis.yaml`. |
| `test_report.py` | Автотест целостности сгенерированного HTML-отчёта (проверка DOM-элементов, JS-обработчиков, отсутствия пустых заглушек). |
| `test_regression.py` | Регрессионный тест сравнения JSON-отчётов. |
| `test_run.sh` | Пакетный прогон проверки импортов и всех логов из папки `logs/`. |

---

## 4. Справочник коротких ключей датчиков (`COL` в `diagnose_utils.py`)

В YAML-правилах используются короткие имена каналов (автоматически резолвятся в полные русские заголовки колонок Parquet):
- **Основные:** `TIME`, `RPM`, `RPM_DESIRED`, `SPD`, `TPS`, `LOAD`, `CALC_LOAD`, `ECT`, `ECT_START`, `IAT`, `VBAT`, `ERR_CNT`.
- **Воздух и ХХ:** `MAF`, `MAF_CYCLE`, `IAC`, `IAC_DES_AIR`, `IAC_ADAPT`, `IDLE_FLAG`.
- **Топливо и ДК:** `INJ`, `INJ_DUTY`, `FUEL`, `FR`, `LAMBDA_REQ`, `FRA`, `RKAT`, `O2_1`, `O2_2`, `O2_FB1`, `O2_FB2`, `O2_READY1`, `O2_READY2`, `O2_PERIOD1`, `O2_HEAT1_R`, `CAT_AMP_IDX`, `PURGE`, `PURGE_FLAG`, `DFCO_FLAG`.
- **Зажигание и пропуски:** `IGN`, `KNOCK_RETARD`, `KNOCK_V`, `KNOCK_ACTIVE`, `CRANK_UNBAL`, `CRANK_ADAPT`, `MIS_CYL_1`..`MIS_CYL_4`, `MIS_SUM`.
- **Каналы АЦП:** `ADC_VBAT`, `ADC_ECT`, `ADC_MAF`, `ADC_TPS`, `ADC_O2_1`, `ADC_IAT`, `ADC_O2_2`.

Индексы режимов, передаваемые в движок: `valid` (все валидные кадры), `running` (ДВС работает), `hot_idle` (прогретый холостой ход).

---

## 5. Спецификация декларативного YAML-движка (`rules/*.yaml`)

Каждая карточка формируется одним из **5 типов правил (`type:`)**:

1. **`type: threshold`** — агрегирует `param` по `mode` (`agg: median|min|max|...`) или вычисляет `expr`, затем оценивает по границам `ok: [lo, hi]`, `warn: [lo, hi]` либо по списку веток `rules: [{when: "...", status: "ok|warn|bad", badge: "...", val: "...", tip: "..."}]`.
2. **`type: compare_modes`** — собирает несколько входных метрик в блоке `inputs:` (каждая со своим `param`, `mode`, `where`, `agg`), вычисляет производные формулы в `compute:` и выбирает ветку в `rules:`.
3. **`type: event_window`** — ищет кадры-триггеры по `trigger.where` и/или переходу `trigger.transition` (например, `"TPS: >= 12 -> <= 0.5"`) с защитой от дребезга `cooldown_sec`. Собирает окно кадров длиной `window.duration_sec` (до условия `window.until`), вычисляет метрики окна (`window.metrics`, где доступны массивы канала `RPM` и скаляры `RPM_start`/`RPM_end`), агрегирует по всем найденным событиям (`count(cond)`, `max(metric)`, `min(metric)`, `times(cond)`) и автоматически ставит `focus` на время события с максимумом по `focus_metric`.
4. **`type: oscillation`** — считает переходы сигнала через гистерезис `low_threshold` / `high_threshold` с разрывом при паузе `max_gap_sec`; отдаёт переменные `min`, `max`, `median`, `swing`, `p10_p90`, `cycles`, `period`.
5. **`type: cross_diagnosis`** — собирает список `tags` со всех карточек, получивших статус `status-warn` или `status-bad`, и сопоставляет их с матрицей диагнозов `diagnoses:` (`all_tags`, `any_tags`, `none_tags`), наследуя `focus` от первопричины.

### Формат выходной карточки
```python
{
    "title": str,       # Заголовок карточки
    "status": str,      # "status-ok" | "status-warn" | "status-bad" | "status-na"
    "badge": str,       # Короткий статус-бейдж ("НОРМА", "ВНИМАНИЕ", "ПРОБЛЕМА", и т.д.)
    "val": str,         # Основное измеренное значение
    "norm": str,        # Эталонный диапазон / подпись
    "tooltip": str,     # Подробная расшифровка при наведении
    "tags": list[str],  # Семантические теги для cross_diagnosis (опционально)
    "focus": {          # Координаты авто-зума графика Plotly при клике по карточке
        "traces": list[str],       # Полные русские имена кривых
        "range": [float, float],   # [t_start, t_end] в секундах (опционально)
        "marker": float,           # Точка события в секундах (опционально)
    },
}
```

---

## 6. Правила работы для ИИ-помощника
1. **Никакого Python-кода в YAML:** новые проверки писать исключительно на 5 декларативных шаблонах `yaml_rules_engine.py`. Не использовать `script:` с Python-кодом.
2. **Безопасность:** в `yaml_expr.py` и `yaml_rules_engine.py` запрещены `eval()` и `exec()`. Любые новые операторы или агрегаторы добавлять только через AST-узлы в `yaml_expr.py`.
3. **Связка с перекрёстным диагнозом:** при добавлении новой проверки обязательно задавать ей семантические `tags:` (например, `shift_flare`, `no_dfco`, `air_leak`, `lean_mix`) и `focus_traces:`, чтобы работали и сводный диагноз, и авто-зум графика по клику.
4. **Сохранение обратной совместимости:** не менять DOM-идентификаторы (`#chart`, `#param-list`, `#summary-panel`, `.check-card`, `#btn-normalize-side`, `#btn-normalize-top`) и CLI-флаги (`--no-browser`, `--raw`, `--json`), проверяемые в `test_report.py` и `test_regression.py`.
5. **Формат выдачи изменений:** при правке нескольких файлов выдавать изменения по одному файлу за шаг и обязательно проверять синтаксис (`py_compile` / `ast.parse`).

---

## 7. Основные команды запуска и проверки
```bash
# Анализ сырого лога + сохранение JSON + открытие отчёта в браузере (Linux / WSL2)
python3 diagnose.py logs/appLog-2026-11-01-05-33-20.log --json

# Быстрый пересчёт из кэша Parquet без открытия браузера
python3 diagnose.py logs/appLog-2026-11-01-05-33-20.parquet --no-browser

# Автотесты и пакетный прогон всех логов
python3 test_report.py
python3 test_regression.py
./test_run.sh
```
