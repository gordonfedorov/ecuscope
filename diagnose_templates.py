#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_templates.py — справочник колонок ЭБУ (Bosch M7.9.7),
настройки отображения параметров и автономный HTML/CSS/JS-шаблон отчёта.
"""

COLUMNS = [
    "LogID", "LogEntryDate", "LogEntryTime", "LogEntrySeconds", "LogNotes",
    "Количество ошибок (-)", "Температура охлаждающей жидкости при пуске (°C)",
    "Температура охлаждающей жидкости (°C)", "Температура впускного воздуха (°C)",
    "Напряжение питания (В)", "Скорость автомобиля (км/ч)",
    "Угол открытия дроссельной заслонки (%)", "Обороты двигателя (об/мин)",
    "Массовый расход воздуха (кг/ч)", "Угол опережения зажигания (°П.К.В)",
    "Величина отскока УОЗ при детонации (°П.К.В)", "Параметр нагрузки (%)",
    "Рассчётная нагрузка (%)", "Фактор высотной коррекции (-)",
    "Длительность впрыска (мс)", "Желаемые обороты холостого хода (об/мин)",
    "Позиция шагового двигателя (шаг)", "Желаемый расход воздуха на холостом ходу (кг/ч)",
    "Параметр адаптации регулировки ХХ (%)", "Сигнал датчика кислорода до нейтрализатора (управляющего) (В)",
    "Текущий коэффициент коррекции длительности впрыска топлива (-)", "Заданное значение лямбда (-)",
    "Коэффициент продувки адсорбера (%)", "Нормализованный уровень сигнала датчика детонации (В)",
    "Среднее значение неравномерности вращения коленвала (об/с2)",
    "Парам. адаптации угл. погреш. зубьев венца демпфера (об/с2)",
    "Счетчик пропусков воспламенения. влияющих на токсичность, по цилиндру 1 (-)",
    "Счетчик пропусков воспламенения. влияющих на токсичность, по цилиндру 3 (-)",
    "Счетчик пропусков воспламенения. влияющих на токсичность, по цилиндру 4 (-)",
    "Счетчик пропусков воспламенения. влияющих на токсичность, по цилиндру 2 (-)",
    "Суммарный счетчик пропусков зажигания. влияющих на работоспособность нейтрализатора (-)",
    "Время с момента последнего сброса контроллера (ч:мин)", "Контрольная сумма (-)",
    "Расход топлива (л/ч)", "Проверка катал (бит)", "пров. клап. продувки адс. завершена (бит)",
    "пров. ДК завершена (бит)", "пров. нагревателя ДК завершена (бит)",
    "Потребность в моменте для регулирования ХХ: I-часть (%)",
    "Потребность в моменте для регулирования ХХ: PD-часть (%)",
    "Мультипликативная составляющая коррекции самообучением (-)",
    "Аддитивная составляющая коррекции самообучением (%)", "Флаг холостого хода (-)",
    "Флаг полной нагрузки (-)", "Флаг запроса на включение кондиционера (-)",
    "Флаг разрешения включения кондиционера (-)", "Флаг включения бензонасоса (-)",
    "Флаг включения реле вентилятора 1 (-)", "Флаг включения реле вентилятора 2 (-)",
    "Флаг включения лампы диагностики (-)", "Контроль детонации активен (-)",
    "Тип шасси основной/альтернативный (-)", "Пусковая характеристика (Европа/Россия) (-)",
    "Флаг обратной связи по датчику кислорода до катализатора (-)", "Отсечка топливоподачи (-)",
    "Готовность датчика О2 до катализатора (-)", "Базовая адаптация (-)",
    "Продувка адсорбера активирована (-)", "Обнаружение пропусков зажигания приостановлено (-)",
    "Плохая дорога для диагностики пропусков зажигания (-)",
    "Флаг обратной связи по датчику кислорода после катализатора (-)",
    "Готовность датчика О2 после катализатора (-)", "Обороты двигателя на холостом ходу (об/мин)",
    "Сигнал датчика кислорода после нейтрализатора (диагностического) (В)",
    "Период сигнала датчика кислорода до нейтрализатора (с)",
    "Интегральная часть задержки ОС по второму датчику (с)",
    "Корректированное среднее значение амплитуды датчика O2 после катализатора (приведенное к 1) (-)",
    "Сигнал датчика неровной дороги (вертикальное ускор.) (g)", "Загрузка форс (%)",
    "Цикловой расход воздуха (мг/такт)", "Мощность по ДМРВ (л.с.)", "момент по ДМРВ (Н/м)",
    "Напряжение бортовой сети (канал АЦП) (В)", "Напряж. с АЦП датчика температуры охлаж. жидкости (В)",
    "Напряжение с АЦП датчика массового расхода воздуха (В)",
    "Напряж. с АЦП датчика полож. дроссельной заслонки (В)",
    "Напряж. с АЦП датчика кислорода до нейтрализатора (В)",
    "Напряжение с АЦП датчика температуры воздуха во впускном коллекторе (В)",
    "Напряж. с АЦП датчика кислорода после нейтрализатора (В)",
    "Сопротивление датчика кислорода до нейтрализатора (Ом)",
    "Напряжение с АЦП датчика ускорения (g)", "Напряжение на клапан рециркуляции (В)",
    "Сопротивление датчика кислорода после нейтрализатора (Ом)"
]

STR_INDICES = {1, 2, 4}
INT_INDICES = {
    0, 5, 12, 20, 21,
    31, 32, 33, 34, 35, 37,
    39, 40, 41, 42,
    *range(47, 68),
}

DEFAULT_VISIBLE = [
    "Обороты двигателя (об/мин)",
    "Температура охлаждающей жидкости (°C)",
    "Массовый расход воздуха (кг/ч)",
    "Угол открытия дроссельной заслонки (%)",
]

# Стартовые множители масштаба (приводят все кривые к визуальной амплитуде ~100 ед.)
DEFAULT_SCALES = {
    "Обороты двигателя (об/мин)": 0.02,
    "Желаемые обороты холостого хода (об/мин)": 0.02,
    "Обороты двигателя на холостом ходу (об/мин)": 0.02,
    "Температура охлаждающей жидкости (°C)": 1.0,
    "Температура охлаждающей жидкости при пуске (°C)": 1.0,
    "Температура впускного воздуха (°C)": 1.0,
    "Массовый расход воздуха (кг/ч)": 2.0,
    "Желаемый расход воздуха на холостом ходу (кг/ч)": 2.0,
    "Длительность впрыска (мс)": 10.0,
    "Угол опережения зажигания (°П.К.В)": 2.0,
    "Величина отскока УОЗ при детонации (°П.К.В)": 5.0,
    "Угол открытия дроссельной заслонки (%)": 1.0,
    "Сигнал датчика кислорода до нейтрализатора (управляющего) (В)": 100.0,
    "Сигнал датчика кислорода после нейтрализатора (диагностического) (В)": 100.0,
    "Период сигнала датчика кислорода до нейтрализатора (с)": 20.0,
    "Интегральная часть задержки ОС по второму датчику (с)": 50.0,
    "Корректированное среднее значение амплитуды датчика O2 после катализатора (приведенное к 1) (-)": 100.0,
    "Текущий коэффициент коррекции длительности впрыска топлива (-)": 50.0,
    "Заданное значение лямбда (-)": 50.0,
    "Мультипликативная составляющая коррекции самообучением (-)": 50.0,
    "Аддитивная составляющая коррекции самообучением (%)": 5.0,
    "Фактор высотной коррекции (-)": 50.0,
    "Напряжение питания (В)": 5.0,
    "Скорость автомобиля (км/ч)": 1.0,
    "Параметр нагрузки (%)": 1.0,
    "Рассчётная нагрузка (%)": 1.0,
    "Загрузка форс (%)": 1.0,
    "Позиция шагового двигателя (шаг)": 1.0,
    "Параметр адаптации регулировки ХХ (%)": 5.0,
    "Потребность в моменте для регулирования ХХ: I-часть (%)": 2.0,
    "Потребность в моменте для регулирования ХХ: PD-часть (%)": 2.0,
    "Коэффициент продувки адсорбера (%)": 1.0,
    "Нормализованный уровень сигнала датчика детонации (В)": 20.0,
    "Среднее значение неравномерности вращения коленвала (об/с2)": 0.2,
    "Парам. адаптации угл. погреш. зубьев венца демпфера (об/с2)": 0.2,
    "Расход топлива (л/ч)": 10.0,
    "Цикловой расход воздуха (мг/такт)": 0.2,
    "Мощность по ДМРВ (л.с.)": 1.0,
    "момент по ДМРВ (Н/м)": 0.5,
    "Сигнал датчика неровной дороги (вертикальное ускор.) (g)": 100.0,
}

EXCLUDE_COLS = {"LogID", "LogEntryDate", "LogEntryTime", "LogEntrySeconds", "LogNotes"}

CATEGORY_ORDER = [
    "Двигатель, воздух и нагрузка",
    "Топливо и датчики кислорода",
    "Зажигание, детонация и пропуски",
    "Холостой ход (ХХ)",
    "Температуры, питание и ЭБУ",
    "Флаги и статусы",
]

FLAG_COLS = {
    "Контроль детонации активен (-)",
    "Тип шасси основной/альтернативный (-)",
    "Пусковая характеристика (Европа/Россия) (-)",
    "Отсечка топливоподачи (-)",
    "Готовность датчика О2 до катализатора (-)",
    "Базовая адаптация (-)",
    "Продувка адсорбера активирована (-)",
    "Обнаружение пропусков зажигания приостановлено (-)",
    "Плохая дорога для диагностики пропусков зажигания (-)",
    "Готовность датчика О2 после катализатора (-)",
}

BASE_COLORS = [
    "#00e5ff", "#ff4d4d", "#00e676", "#ffab00", "#d500f9",
    "#ffea00", "#ff6e40", "#40c4ff", "#b2ff59", "#ea80fc",
    "#18ffff", "#ff80ab", "#ffd740", "#69f0ae", "#82b1ff",
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    height: 100vh;
    overflow: hidden;
    background: #000000;
    color: #e6edf3;
  }
  #sidebar {
    width: 430px;
    background: #0d1117;
    border-right: 1px solid #21262d;
    display: flex;
    flex-direction: column;
    padding: 12px;
  }
  #search {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid #30363d;
    border-radius: 6px;
    font-size: 13px;
    margin-bottom: 8px;
    background: #161b22;
    color: #f0f6fc;
  }
  #search::placeholder { color: #8b949e; }
  #search:focus { outline: none; border-color: #58a6ff; }
  .btn-row { display: flex; gap: 6px; margin-bottom: 8px; }
  button {
    padding: 6px 9px;
    font-size: 12px;
    border: 1px solid #30363d;
    background: #161b22;
    color: #e6edf3;
    border-radius: 5px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }
  button:hover { background: #21262d; border-color: #8b949e; }
  #sidebar .btn-row button { flex: 1; }
  .btn-accent {
    border-color: #1f6feb !important;
    background: #13233a !important;
    color: #79c0ff !important;
    font-weight: 600;
  }
  .btn-accent:hover { background: #1c3354 !important; border-color: #58a6ff !important; }
  .btn-full {
    width: 100%;
    margin-bottom: 6px;
    padding: 7px 10px;
  }
  #param-list {
    flex: 1;
    overflow-y: auto;
    border-top: 1px solid #21262d;
    padding-top: 6px;
  }
  #param-list::-webkit-scrollbar { width: 8px; }
  #param-list::-webkit-scrollbar-track { background: #0d1117; }
  #param-list::-webkit-scrollbar-thumb { background: #30363d; border-radius: 4px; }
  .cat-group {
    margin-bottom: 6px;
    border: 1px solid #21262d;
    border-radius: 6px;
    background: #0d1117;
  }
  .cat-title {
    padding: 7px 10px;
    font-size: 12.5px;
    font-weight: 600;
    color: #f0f6fc;
    cursor: pointer;
    user-select: none;
    background: #161b22;
    border-radius: 5px;
  }
  .cat-count { font-weight: 400; color: #8b949e; }
  .cat-body { padding: 4px 6px; }
  .param-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    padding: 3px 4px;
    border-radius: 4px;
  }
  .param-row:hover { background: #1f242c; }
  .param-item {
    display: flex;
    align-items: flex-start;
    gap: 7px;
    flex: 1;
    min-width: 0;
    font-size: 12px;
    line-height: 1.3;
    cursor: pointer;
    color: #c9d1d9;
  }
  .param-row:hover .param-item { color: #ffffff; }
  .param-item input { margin-top: 2px; cursor: pointer; flex-shrink: 0; accent-color: #58a6ff; }
  .color-dot { width: 11px; height: 11px; border-radius: 3px; margin-top: 2px; flex-shrink: 0; }
  .scale-box {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
  }
  .scale-prefix {
    font-size: 11px;
    color: #8b949e;
    user-select: none;
  }
  .scale-input {
    width: 56px;
    padding: 2px 4px;
    font-size: 11px;
    text-align: right;
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #f0f6fc;
  }
  .scale-input:focus { outline: none; border-color: #58a6ff; }
  #main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100vh;
    min-width: 0;
    background: #000000;
  }
  #summary-panel {
    background: #0d1117;
    border-bottom: 1px solid #21262d;
    padding: 8px 16px;
  }
  .summary-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }
  .meta-badges {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .meta-badge {
    font-size: 12px;
    padding: 4px 9px;
    border-radius: 5px;
    background: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
  }
  .meta-badge b { color: #f0f6fc; }
  .checks-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 8px;
    margin-top: 8px;
    max-height: 230px;
    overflow-y: auto;
  }
  .checks-grid.collapsed { display: none; }
  .check-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-left: 11px solid #8b949e;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 11.5px;
    transition: transform 0.12s, box-shadow 0.12s, border-color 0.12s;
  }
  .check-card[data-focus] { cursor: pointer; }
  .check-card[data-focus]:hover {
    background: #1c222b;
    border-color: #58a6ff;
    transform: translateY(-1px);
  }
  .check-card.active {
    background: #13233a;
    border-color: #58a6ff;
    box-shadow: 0 0 0 1px #58a6ff;
  }
  .check-card.status-ok { border-left-color: #00e676; }
  .check-card.status-warn { border-left-color: #ffab00; }
  .check-card.status-bad { border-left-color: #ff4d4d; }
  .check-card.status-na { border-left-color: #6e7681; }
  .check-title {
    display: flex;
    justify-content: space-between;
    gap: 6px;
    font-weight: 600;
    color: #f0f6fc;
    margin-bottom: 2px;
  }
  .status-ok .check-title span:last-child { color: #00e676; }
  .status-warn .check-title span:last-child { color: #ffab00; }
  .status-bad .check-title span:last-child { color: #ff4d4d; }
  .status-na .check-title span:last-child { color: #8b949e; }
  .check-val {
    color: #e6edf3;
    margin-bottom: 2px;
    word-break: break-word;
  }
  .check-norm {
    color: #8b949e;
    font-size: 10.5px;
  }
  #nav-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: #0d1117;
    border-bottom: 1px solid #21262d;
    flex-wrap: wrap;
  }
  .nav-label { font-size: 12px; color: #8b949e; margin-right: 4px; }
  .focus-pill {
    display: none;
    align-items: center;
    gap: 6px;
    padding: 4px 9px;
    font-size: 12px;
    border-radius: 5px;
    background: #13233a;
    border: 1px solid #1f6feb;
    color: #79c0ff;
    margin-left: auto;
  }
  .focus-pill.visible { display: inline-flex; }
  .focus-pill button {
    padding: 1px 6px;
    font-size: 11px;
    border-color: #1f6feb;
    background: #0d1117;
    color: #79c0ff;
  }
  #chart-wrap { flex: 1; min-height: 0; width: 100%; }
  #chart { width: 100%; height: 100%; }
</style>
</head>
<body>
  <div id="sidebar">
    <input type="text" id="search" placeholder="Поиск параметра...">
    <button type="button" id="btn-normalize-side" class="btn-accent btn-full" title="Растянуть каждый включённый график на 0..100% по текущему видимому участку времени">📊 Авто-scale 0–100% (видимая область)</button>
    <div class="btn-row">
      <button type="button" id="btn-default">По умолчанию</button>
      <button type="button" id="btn-scale-reset" title="Сбросить все коэффициенты масштаба в x1">Scale x1</button>
      <button type="button" id="btn-clear">Снять все</button>
    </div>
    <div id="param-list">
      __GROUPS_HTML__
    </div>
  </div>
  <div id="main-area">
    <div id="summary-panel">
      __SUMMARY_HTML__
    </div>
    <div id="nav-toolbar">
      <span class="nav-label">Навигация:</span>
      <button type="button" id="nav-start">⏮ В начало</button>
      <button type="button" id="nav-left">◀ Сдвиг влево</button>
      <button type="button" id="nav-right">Сдвиг вправо ▶</button>
      <button type="button" id="nav-end">В конец ⏭</button>
      <button type="button" id="nav-zoom-in">➕ Приблизить</button>
      <button type="button" id="nav-zoom-out">➖ Отдалить</button>
      <button type="button" id="nav-reset">⟲ Весь график</button>
      <button type="button" id="btn-normalize-top" class="btn-accent" title="Растянуть каждый включённый график на 0..100% по текущему видимому участку времени">📊 Авто-scale 0–100% (видимое)</button>
      <span id="focus-pill" class="focus-pill">
        <span id="focus-pill-text"></span>
        <button type="button" id="btn-clear-focus" title="Сбросить выделение карточки и метку на графике">✕</button>
      </span>
    </div>
    <div id="chart-wrap">
      __PLOT_DIV__
    </div>
  </div>
<script>
  const defaultSet = new Set(__DEFAULT_JSON__);
  const rawTracesY = __RAW_TRACES_JSON__;
  const baseNames = __BASE_NAMES_JSON__;
  const chartEl = document.getElementById("chart");
  const checkboxes = document.querySelectorAll('#param-list input[type="checkbox"]');
  const scaleInputs = document.querySelectorAll('#param-list .scale-input');
  const scaleInputByIdx = {};
  scaleInputs.forEach(inp => { scaleInputByIdx[parseInt(inp.dataset.idx, 10)] = inp; });
  const minTime = __MIN_TIME__;
  const maxTime = __MAX_TIME__;

  const toggleSummaryBtn = document.getElementById("btn-toggle-summary");
  const checksWrap = document.getElementById("checks-wrap");
  if (toggleSummaryBtn && checksWrap) {
    toggleSummaryBtn.addEventListener("click", () => {
      const isCollapsed = checksWrap.classList.toggle("collapsed");
      toggleSummaryBtn.textContent = isCollapsed ? "Развернуть диагностику ▼" : "Свернуть диагностику ▲";
      setTimeout(() => {
        if (window.Plotly && chartEl) Plotly.Plots.resize(chartEl);
      }, 50);
    });
  }

  function applyTraceScale(idx, scaleVal) {
    const s = (isFinite(scaleVal) && scaleVal > 0) ? scaleVal : 1.0;
    const rawY = rawTracesY[idx];
    const scaledY = (s === 1.0) ? rawY : rawY.map(v => (v === null ? null : Number((v * s).toFixed(5))));
    const traceTitle = (s === 1.0) ? baseNames[idx] : `${baseNames[idx]} [x${s}]`;
    Plotly.restyle(chartEl, { y: [scaledY], customdata: [rawY], name: [traceTitle] }, [idx]);
  }

  scaleInputs.forEach(inp => {
    const handler = () => {
      const idx = parseInt(inp.dataset.idx, 10);
      let val = parseFloat(inp.value.replace(",", "."));
      if (!isFinite(val) || val <= 0) {
        val = 1.0;
        inp.value = "1";
      }
      applyTraceScale(idx, val);
    };
    inp.addEventListener("change", handler);
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handler();
      }
    });
  });

  checkboxes.forEach(cb => {
    cb.addEventListener("change", () => {
      const idx = parseInt(cb.dataset.idx, 10);
      Plotly.restyle(chartEl, { visible: cb.checked }, [idx]);
    });
  });

  function getXRange() {
    const r = chartEl.layout && chartEl.layout.xaxis && chartEl.layout.xaxis.range;
    return r ? [Number(r[0]), Number(r[1])] : [minTime, maxTime];
  }

  function normalizeVisibleTraces() {
    const [x0, x1] = getXRange();
    const indices = [];
    const newY = [];
    const newCustom = [];
    const newNames = [];

    checkboxes.forEach(cb => {
      if (!cb.checked) return;
      const idx = parseInt(cb.dataset.idx, 10);
      const rawY = rawTracesY[idx];
      const xArr = (chartEl.data && chartEl.data[idx] && chartEl.data[idx].x) ? chartEl.data[idx].x : null;

      let minV = Infinity;
      let maxV = -Infinity;

      for (let i = 0; i < rawY.length; i++) {
        if (xArr) {
          const tx = Number(xArr[i]);
          if (tx < x0 || tx > x1) continue;
        }
        const v = rawY[i];
        if (v !== null && isFinite(v)) {
          if (v < minV) minV = v;
          if (v > maxV) maxV = v;
        }
      }

      if (!isFinite(minV) || !isFinite(maxV)) {
        for (let i = 0; i < rawY.length; i++) {
          const v = rawY[i];
          if (v !== null && isFinite(v)) {
            if (v < minV) minV = v;
            if (v > maxV) maxV = v;
          }
        }
      }
      if (!isFinite(minV) || !isFinite(maxV)) return;

      const span = maxV - minV;
      let normY;
      let labelSuffix;
      if (span > 1e-9) {
        normY = rawY.map(v => (v === null ? null : Number((((v - minV) / span) * 100.0).toFixed(3))));
        labelSuffix = `[0–100%: ${minV}..${maxV}]`;
      } else {
        normY = rawY.map(v => (v === null ? null : 50.0));
        labelSuffix = `[50%: const ${minV}]`;
      }

      if (scaleInputByIdx[idx]) {
        scaleInputByIdx[idx].value = "";
      }

      indices.push(idx);
      newY.push(normY);
      newCustom.push(rawY);
      newNames.push(`${baseNames[idx]} ${labelSuffix}`);
    });

    if (indices.length) {
      Plotly.restyle(chartEl, { y: newY, customdata: newCustom, name: newNames }, indices);
      Plotly.relayout(chartEl, {
        "yaxis.title.text": "Нормализованное значение (0 – 100% по видимому окну)",
        "yaxis.range": [-4, 104],
        "yaxis.autorange": false
      });
    }
  }

  document.getElementById("btn-normalize-side").addEventListener("click", normalizeVisibleTraces);
  document.getElementById("btn-normalize-top").addEventListener("click", normalizeVisibleTraces);

  // --- Интерактивный переход из диагностических карточек на график ---
  const focusPill = document.getElementById("focus-pill");
  const focusPillText = document.getElementById("focus-pill-text");
  const clearFocusBtn = document.getElementById("btn-clear-focus");
  const checkCards = document.querySelectorAll(".check-card[data-focus]");

  function clearCardFocus() {
    checkCards.forEach(c => c.classList.remove("active"));
    if (focusPill) focusPill.classList.remove("visible");
    if (window.Plotly && chartEl) {
      Plotly.relayout(chartEl, { shapes: [] });
    }
  }

  if (clearFocusBtn) {
    clearFocusBtn.addEventListener("click", clearCardFocus);
  }

  checkCards.forEach(card => {
    card.addEventListener("click", () => {
      let focus = null;
      try {
        focus = JSON.parse(card.dataset.focus || "null");
      } catch (e) {
        return;
      }
      if (!focus) return;

      checkCards.forEach(c => c.classList.remove("active"));
      card.classList.add("active");

      const titleEl = card.querySelector(".check-title span");
      const cardTitle = titleEl ? titleEl.textContent.trim() : "Событие";

      if (Array.isArray(focus.traces) && focus.traces.length > 0) {
        const wanted = new Set(focus.traces);
        const indices = [];
        const visList = [];
        let matchedCount = 0;

        checkboxes.forEach(cb => {
          const idx = parseInt(cb.dataset.idx, 10);
          const show = wanted.has(baseNames[idx]);
          if (show) matchedCount++;
          indices.push(idx);
          visList.push(show);
        });

        if (matchedCount > 0) {
          checkboxes.forEach((cb, pos) => { cb.checked = visList[pos]; });
          Plotly.restyle(chartEl, { visible: visList }, indices);
        }
      }

      const relayoutPatch = {};
      const shapes = [];

      if (isFinite(focus.start_sec) && isFinite(focus.end_sec) && focus.end_sec > focus.start_sec) {
        const x0 = Math.max(minTime, Number(focus.start_sec));
        const x1 = Math.min(maxTime, Number(focus.end_sec));
        relayoutPatch["xaxis.range"] = [x0, x1];
        relayoutPatch["xaxis.autorange"] = false;
      } else {
        relayoutPatch["xaxis.autorange"] = true;
      }

      if (isFinite(focus.marker_sec)) {
        const mx = Math.max(minTime, Math.min(maxTime, Number(focus.marker_sec)));
        shapes.push({
          type: "line",
          xref: "x",
          yref: "paper",
          x0: mx,
          x1: mx,
          y0: 0,
          y1: 1,
          line: { color: "#ff4d4d", width: 2, dash: "dash" }
        });
      }
      relayoutPatch["shapes"] = shapes;

      Plotly.relayout(chartEl, relayoutPatch).then(() => {
        normalizeVisibleTraces();
      });

      if (focusPill && focusPillText) {
        const timeTag = isFinite(focus.marker_sec) ? ` (${Number(focus.marker_sec).toFixed(1)} с)` : "";
        focusPillText.textContent = `🎯 ${cardTitle}${timeTag}`;
        focusPill.classList.add("visible");
      }
    });
  });

  document.getElementById("search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    document.querySelectorAll(".cat-group").forEach(group => {
      let visibleInGroup = 0;
      group.querySelectorAll(".param-row").forEach(row => {
        const match = row.dataset.name.includes(q);
        row.style.display = match ? "flex" : "none";
        if (match) visibleInGroup++;
      });
      group.style.display = visibleInGroup > 0 ? "block" : "none";
      if (q.length > 0 && visibleInGroup > 0) group.open = true;
    });
  });

  document.getElementById("btn-clear").addEventListener("click", () => {
    const indices = [];
    checkboxes.forEach(cb => {
      if (cb.checked) {
        cb.checked = false;
        indices.push(parseInt(cb.dataset.idx, 10));
      }
    });
    if (indices.length) Plotly.restyle(chartEl, { visible: false }, indices);
  });

  document.getElementById("btn-scale-reset").addEventListener("click", () => {
    const indices = [];
    const newY = [];
    const newCustom = [];
    const newNames = [];
    scaleInputs.forEach(inp => {
      const idx = parseInt(inp.dataset.idx, 10);
      inp.value = "1";
      indices.push(idx);
      newY.push(rawTracesY[idx]);
      newCustom.push(rawTracesY[idx]);
      newNames.push(baseNames[idx]);
    });
    if (indices.length) {
      Plotly.restyle(chartEl, { y: newY, customdata: newCustom, name: newNames }, indices);
      Plotly.relayout(chartEl, {
        "yaxis.title.text": "Масштабированное значение",
        "yaxis.autorange": true
      });
    }
  });

  document.getElementById("btn-default").addEventListener("click", () => {
    clearCardFocus();
    const visList = [];
    const indices = [];
    const newY = [];
    const newCustom = [];
    const newNames = [];

    checkboxes.forEach(cb => {
      const idx = parseInt(cb.dataset.idx, 10);
      const name = baseNames[idx];
      const shouldShow = defaultSet.has(name);
      cb.checked = shouldShow;
      indices.push(idx);
      visList.push(shouldShow);
    });

    scaleInputs.forEach(inp => {
      const idx = parseInt(inp.dataset.idx, 10);
      const defScale = parseFloat(inp.dataset.defaultScale) || 1.0;
      inp.value = String(defScale);
      const rawY = rawTracesY[idx];
      const scaledY = (defScale === 1.0) ? rawY : rawY.map(v => (v === null ? null : Number((v * defScale).toFixed(5))));
      newY.push(scaledY);
      newCustom.push(rawY);
      newNames.push(defScale === 1.0 ? baseNames[idx] : `${baseNames[idx]} [x${defScale}]`);
    });

    Plotly.restyle(chartEl, { visible: visList, y: newY, customdata: newCustom, name: newNames }, indices);
    Plotly.relayout(chartEl, {
      "yaxis.title.text": "Масштабированное значение",
      "yaxis.autorange": true
    });
  });

  function panX(shiftRatio) {
    const [x0, x1] = getXRange();
    const span = x1 - x0;
    let new0 = x0 + span * shiftRatio;
    let new1 = x1 + span * shiftRatio;
    if (new0 < minTime) { new0 = minTime; new1 = Math.min(maxTime, minTime + span); }
    if (new1 > maxTime) { new1 = maxTime; new0 = Math.max(minTime, maxTime - span); }
    Plotly.relayout(chartEl, { "xaxis.range": [new0, new1] });
  }

  function zoomX(scaleFactor) {
    const [x0, x1] = getXRange();
    const center = (x0 + x1) / 2;
    const halfSpan = ((x1 - x0) * scaleFactor) / 2;
    const new0 = Math.max(minTime, center - halfSpan);
    const new1 = Math.min(maxTime, center + halfSpan);
    Plotly.relayout(chartEl, { "xaxis.range": [new0, new1] });
  }

  document.getElementById("nav-left").addEventListener("click", () => panX(-0.35));
  document.getElementById("nav-right").addEventListener("click", () => panX(0.35));
  document.getElementById("nav-start").addEventListener("click", () => {
    const [x0, x1] = getXRange();
    Plotly.relayout(chartEl, { "xaxis.range": [minTime, Math.min(maxTime, minTime + (x1 - x0))] });
  });
  document.getElementById("nav-end").addEventListener("click", () => {
    const [x0, x1] = getXRange();
    Plotly.relayout(chartEl, { "xaxis.range": [Math.max(minTime, maxTime - (x1 - x0)), maxTime] });
  });
  document.getElementById("nav-zoom-in").addEventListener("click", () => zoomX(0.5));
  document.getElementById("nav-zoom-out").addEventListener("click", () => zoomX(2.0));
  document.getElementById("nav-reset").addEventListener("click", () => {
    clearCardFocus();
    Plotly.relayout(chartEl, { "xaxis.autorange": true, "yaxis.autorange": true });
  });
</script>
</body>
</html>"""
