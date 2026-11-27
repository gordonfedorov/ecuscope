# ECUScope — Здоровье мотора

**ECUScope** — автономный диагностический анализатор логов ЭБУ (OpenDiag Mobile / ELM327 K-Line, в первую очередь **Bosch M7.9.7 / M7.9.7+** для автомобилей ВАЗ / Lada / Chevrolet Niva).

Программа парсит сырые HEX-логи обмена с ЭБУ, кэширует их в быстрый колоночный формат **Apache Parquet**, выполняет **27 автоматических диагностических проверок** по декларативным YAML-правилам и формирует автономный интерактивный HTML-отчёт с графиками **Plotly**.

---

## Основные возможности

- **Парсинг сырых логов OpenDiag (`2101`, `2105`, `1A90–1A92`):** автоматическое извлечение более 80 параметров двигателя, флагов, АЦП датчиков, идентификаторов ЭБУ и прошивки с сохранением в `.parquet`.
- **27 декларативных проверок здоровья мотора (`rules/*.yaml`):**
  - *Базовые (`base_checks.yaml`):* пуск и прокрутка стартером, напряжение сети, прогрев ДТОЖ, обороты ХХ, провалы оборотов, ДМРВ, расход топлива, время впрыска, УОЗ, коррекции `FR`, самообучение `FRA`/`RKAT`, счётчики ошибок и пропусков.
  - *Охлаждение и питание (`thermal_checks.yaml`):* термостат и вентилятор, сверка ДТОЖ/ДТВ на холодном старте, АКБ, генератор и детектор плохой массы датчиков по скачкам АЦП.
  - *Воздух и дроссель (`air_checks.yaml`):* ноль и АЦП ДПДЗ, отсечка ПХХ, шаг РХХ и подсос воздуха, АЦП покоя ДМРВ, а также **детектор подброса оборотов и подвисания РХХ при переключении передач**.
  - *Топливо и экология (`fuel_checks.yaml`):* амплитуда и период переключений ДК1, замкнутый контур (Closed Loop), клапан продувки адсорбера (КПА), баланс смеси `ХХ vs 1500+`, эффективность катализатора по ДК2, загрузка форсунок.
  - *Зажигание и динамика (`engine_checks.yaml`):* детонация и отскок УОЗ под нагрузкой, пропуски по цилиндрам 1–4, срывы сигнала ДПКВ, каскадный отклик на резкий газ (`ДПДЗ → ДМРВ → впрыск → обороты`).
  - *Сводный диагноз (`cross_diagnosis.yaml`):* сопоставление сработавших улик по всем узлам и выделение вероятной первопричины.
- **Интерактивная навигация по графику:**
  - **Клик по любой карточке диагностики** автоматически приближает нужный участок времени на графике, ставит вертикальный маркер события, включает релевантные датчики и выравнивает их масштаб.
  - Режим **«Авто-scale 0–100% (видимая область)»** растягивает каждый включённый график в пределах текущего окна просмотра.

---

## Структура проекта

```text
ecuscope/
├── diagnose.py              # Главный CLI-скрипт анализа логов и сборки HTML/JSON отчётов
├── parser.py                # Парсер сырых логов OpenDiag Mobile -> Apache Parquet
├── diagnose_utils.py        # Справочник каналов ЭБУ, режимов работы и форматирования
├── diagnose_templates.py    # Автономный тёмный HTML/CSS/JS-шаблон отчёта (Plotly)
├── diagnose_checks.py       # Единый диспетчер загрузки правил из rules/*.yaml
├── yaml_expr.py             # Безопасный AST-вычислитель выражений и шаблонов (без eval/exec)
├── yaml_rules_engine.py     # Движок 5 декларативных шаблонов (threshold, compare_modes, event_window, oscillation, cross_diagnosis)
├── rules/                   # Декларативные диагностические правила без Python-кода
│   ├── base_checks.yaml
│   ├── thermal_checks.yaml
│   ├── air_checks.yaml
│   ├── fuel_checks.yaml
│   ├── engine_checks.yaml
│   └── cross_diagnosis.yaml
├── test_report.py           # Автотест структуры и целостности HTML-отчёта
├── test_regression.py       # Регрессионный тест сравнения JSON-отчётов
├── test_run.sh              # Пакетный прогон всех логов из папки logs/
├── requirements.txt         # Зависимости Python (pyarrow, plotly, pyyaml)
└── CHANGELOG.md             # История версий
```

---

## Установка и запуск

### 1. Linux (Debian / Ubuntu / Astra Linux)

```bash
git clone https://github.com
cd ecuscope
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Запуск анализа лога:
```bash
python3 diagnose.py logs/appLog-2026-11-01-05-33-20.log
```

---

### 2. Windows 10 / 11 через WSL2 (рекомендуемый способ)

1. Откройте **PowerShell от имени администратора** и установите Ubuntu в WSL2:
   ```powershell
   wsl --install -d Ubuntu
   ```
   *(После установки перезагрузите ПК и задайте имя пользователя и пароль Linux.)*

2. Откройте терминал **Ubuntu (WSL)**, обновите пакеты и установите Python + утилиту `wslu` (нужна, чтобы HTML-отчёты автоматически открывались в браузере Windows):
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git wslu
   ```

3. Клонируйте проект в домашнюю директорию Linux (так парсинг Parquet работает в несколько раз быстрее, чем на диске `C:\`) и поставьте зависимости:
   ```bash
   git clone https://github.com ~/ecuscope
   cd ~/ecuscope
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Как передавать логи и открывать отчёты в WSL:**
   - Ваши диски Windows доступны в WSL по пути `/mnt/c/Users/<ИмяПользователя>/Downloads/`.
   - Папка Linux доступна из Проводника Windows по адресу `\\wsl$\Ubuntu\home\<пользователь>\ecuscope\`.
   - Скопируйте лог в папку `logs/` и запустите анализ:
     ```bash
     cp /mnt/c/Users/<ИмяПользователя>/Downloads/appLog-*.log ~/ecuscope/logs/
     python3 diagnose.py logs/appLog-2026-11-01-05-33-20.log
     ```
     Отчёт автоматически откроется в браузере Windows по умолчанию через `wslview`.

---

### 3. Нативный Windows (PowerShell)

```powershell
git clone https://github.com
cd ecuscope
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python diagnose.py logs\appLog-2026-11-01-05-33-20.log
```

---

## Полезные команды CLI и тестирование

| Команда | Назначение |
| :--- | :--- |
| `python3 diagnose.py logs/file.log` | Спарсить лог в `.parquet`, построить `.html` и открыть в браузере |
| `python3 diagnose.py logs/file.parquet --no-browser` | Быстро пересобрать отчёт из кэша `.parquet` без открытия браузера |
| `python3 diagnose.py logs/file.log --raw` | Принудительно перепарсить сырой `.log`, перезаписав `.parquet` |
| `python3 diagnose.py logs/file.log --json` | Дополнительно сохранить структурированный отчёт `.json` |
| `./test_run.sh` | Пакетно проверить импорты и прогнать все логи из папки `logs/` |
| `python3 test_report.py` | Проверить валидность HTML-разметки и элементов управления отчёта |

---

## Добавление своих правил диагностики (без кода на Python)

Любую новую проверку можно добавить в `rules/*.yaml` с помощью одного из 5 встроенных шаблонов (`threshold`, `compare_modes`, `event_window`, `oscillation`, `cross_diagnosis`):

```yaml
  - id: custom_vbat_min
    title: "Минимальное напряжение АКБ"
    type: threshold
    mode: running
    param: VBAT
    agg: min
    ok: [13.2, 14.8]
    warn: [12.5, 15.1]
    val_fmt: "{val:.2f} В"
    norm: "Норма при работе: 13.2 – 14.8 В"
    focus_traces: ["VBAT", "RPM"]
```
