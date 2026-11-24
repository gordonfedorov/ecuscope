"""Парсер диагностических логов OpenDiag Mobile с поддержкой внешних профилей Torque Pro."""

from __future__ import annotations

import ast
import csv
import math
import operator
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from diagnose_templates import COLUMNS

DEFAULT_PID_FILE = "pids/bosch_m797.csv"

_TS_LINE_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{1,3})")
_DATE_LINE_RE = re.compile(r"(\d{4})[-./](\d{2})[-./](\d{2})|(\d{2})[-./](\d{2})[-./](\d{4})")
_FILENAME_DT_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[-_](\d{2})-(\d{2})-(\d{2})")
_RECV_RE = re.compile(r"(?:Receive|Recv|RX|Ответ)\s*[:=-]\s*(?P<hex>.+)$", re.IGNORECASE)
_HEX_BYTE_RE = re.compile(r"^[0-9A-Fa-f]{2}$")
_HEX_PAIR_STREAM_RE = re.compile(r"^[0-9A-Fa-f]{8,}$")


def _col_to_index(letters: str) -> int:
    """Переводит буквенное обозначение байта Torque (A..Z, AA..ZZ) в 0-индекс."""
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _s8(val: int) -> int:
    v = int(val) & 0xFF
    return v - 256 if v >= 128 else v


def _s16(val_or_hi: int, lo: int | None = None) -> int:
    if lo is not None:
        v = ((int(val_or_hi) & 0xFF) << 8) | (int(lo) & 0xFF)
    else:
        v = int(val_or_hi) & 0xFFFF
    return v - 65536 if v >= 32768 else v


def _bit(val: int, bit_idx: int) -> int:
    return 1 if (int(val) & (1 << int(bit_idx))) else 0


_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
}

_SAFE_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Invert: operator.invert,
}

_SAFE_FUNCS = {
    "SIGNED": _s8,
    "S8": _s8,
    "S16": _s16,
    "BIT": _bit,
    "ABS": abs,
    "MIN": min,
    "MAX": max,
    "ROUND": round,
    "INT": int,
    "FLOAT": float,
}


def _preprocess_torque_expr(expr: str) -> str:
    """Преобразует синтаксис Torque Pro ({A:0}, [SHORT_NAME], ^) в валидный Python-выражение для AST."""
    s = expr.strip()
    s = re.sub(r"\{([A-Za-z]{1,2})\s*:\s*(\d+)\}", r"BIT(\1, \2)", s)
    s = re.sub(r"\[([A-Za-z0-9_]+)\]", r"_VAR_\1", s)
    s = s.replace("^", "**")
    return s


def compile_torque_equation(equation: str) -> ast.Expression | None:
    """Компилирует формулу Torque Pro в безопасное AST-дерево (без eval)."""
    if not equation or not str(equation).strip():
        return None
    py_expr = _preprocess_torque_expr(str(equation))
    try:
        return ast.parse(py_expr, mode="eval")
    except SyntaxError:
        return None


def _eval_ast_node(node: ast.AST, data: bytes, vars_map: dict[str, float]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body, data, vars_map)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Недопустимая константа")

    if isinstance(node, ast.Name):
        ident = node.id
        if ident.startswith("_VAR_"):
            vkey = ident[5:].upper()
            if vkey not in vars_map or vars_map[vkey] is None:
                raise KeyError(vkey)
            return vars_map[vkey]
        if re.fullmatch(r"[A-Za-z]{1,2}", ident):
            b_idx = _col_to_index(ident)
            if 0 <= b_idx < len(data):
                return data[b_idx]
            raise IndexError(b_idx)
        raise NameError(ident)

    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name):
            kind = node.value.id.upper()
            idx_val = int(_eval_ast_node(node.slice, data, vars_map))
            if kind == "B":
                if 0 <= idx_val < len(data):
                    return data[idx_val]
                raise IndexError(idx_val)
            if kind == "W":
                if 0 <= idx_val + 1 < len(data):
                    return (data[idx_val] << 8) | data[idx_val + 1]
                raise IndexError(idx_val)
            if kind == "SW":
                if 0 <= idx_val + 1 < len(data):
                    return _s16((data[idx_val] << 8) | data[idx_val + 1])
                raise IndexError(idx_val)
        raise ValueError("Неподдерживаемая индексация")

    if isinstance(node, ast.UnaryOp):
        op_fn = _SAFE_UNARYOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError("Недопустимый унарный оператор")
        return op_fn(_eval_ast_node(node.operand, data, vars_map))

    if isinstance(node, ast.BinOp):
        op_fn = _SAFE_BINOPS.get(type(node.op))
        if op_fn is None:
            raise ValueError("Недопустимый бинарный оператор")
        left = _eval_ast_node(node.left, data, vars_map)
        right = _eval_ast_node(node.right, data, vars_map)
        return op_fn(left, right)

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            fn = _SAFE_FUNCS.get(node.func.id.upper())
            if fn is None:
                raise ValueError(f"Неизвестная функция: {node.func.id}")
            args = [_eval_ast_node(a, data, vars_map) for a in node.args]
            return fn(*args)
        raise ValueError("Недопустимый вызов")

    raise ValueError(f"Недопустимый узел AST: {type(node).__name__}")


def eval_torque_ast(
    compiled: ast.Expression | None,
    data: bytes = b"",
    vars_map: dict[str, float] | None = None,
) -> int | float | None:
    """Безопасно вычисляет скомпилированную формулу Torque Pro."""
    if compiled is None:
        return None
    try:
        res = _eval_ast_node(compiled, data, vars_map or {})
        if res is None or (isinstance(res, float) and (math.isnan(res) or math.isinf(res))):
            return None
        if isinstance(res, int):
            return res
        return round(float(res), 4)
    except Exception:
        return None


def load_pid_profile(pid_file: str | os.PathLike | None = None) -> list[dict[str, Any]]:
    """Загружает профиль формул из CSV в формате Torque Pro."""
    target = pid_file or os.environ.get("ECUSCOPE_PID_FILE") or DEFAULT_PID_FILE
    p = Path(target)
    if not p.exists():
        alt = Path(__file__).resolve().parent / target
        if alt.exists():
            p = alt
        else:
            raise FileNotFoundError(f"Файл формул Torque не найден: {target}")

    entries: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            if not name or name.startswith("#"):
                continue
            short = (row.get("ShortName") or "").strip()
            mode_pid = (row.get("ModeAndPID") or "").strip().upper().replace(" ", "")
            eq = (row.get("Equation") or "").strip()
            entries.append(
                {
                    "name": name,
                    "short": short.upper(),
                    "mode_pid": mode_pid,
                    "equation": eq,
                    "compiled": compile_torque_equation(eq),
                }
            )
    return entries


def is_valid_packet(payload: bytes) -> bool:
    """Проверяет адекватность ответа ЭБУ 61 01 (отсекает байты-заглушки 0xDD при потере связи)."""
    if len(payload) < 55:
        return False
    body = payload[2:55]
    if all(b == 0xDD for b in body) or all(b == 0xFF for b in body):
        return False
    return True


def decode_packet(
    payload: bytes,
    adc_payload: bytes | None = None,
    profile: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Декодирует один кадр 61 01 (и последний известный 61 03) по профилю Torque Pro."""
    if not is_valid_packet(payload):
        return None

    prof = profile if profile is not None else load_pid_profile()
    data_2101 = payload[2:]
    data_2103 = adc_payload[2:] if (adc_payload and len(adc_payload) > 2) else b""

    out: dict[str, Any] = {}
    vars_map: dict[str, float] = {}

    for item in prof:
        mp = item["mode_pid"]
        if mp == "CALC":
            continue
        src = data_2101 if mp == "2101" else (data_2103 if mp == "2103" else b"")
        val = eval_torque_ast(item["compiled"], src, vars_map) if src else None
        out[item["name"]] = val
        if item["short"] and val is not None:
            vars_map[item["short"]] = float(val)

    for item in prof:
        if item["mode_pid"] == "CALC":
            val = eval_torque_ast(item["compiled"], b"", vars_map)
            out[item["name"]] = val
            if item["short"] and val is not None:
                vars_map[item["short"]] = float(val)

    return out


def _parse_hex_tokens(text: str) -> list[int]:
    tokens = text.strip().split()
    out: list[int] = []
    for tok in tokens:
        if _HEX_BYTE_RE.match(tok):
            out.append(int(tok, 16))
        elif _HEX_PAIR_STREAM_RE.match(tok) and len(tok) % 2 == 0:
            for j in range(0, len(tok), 2):
                out.append(int(tok[j : j + 2], 16))
    return out


def _extract_kwp_service_payload(byte_seq: list[int]) -> tuple[int, bytes] | None:
    for i in range(len(byte_seq) - 2):
        if byte_seq[i] == 0x61 and byte_seq[i + 1] in (0x01, 0x03):
            return byte_seq[i + 1], bytes(byte_seq[i:])
    return None


def _parse_start_datetime(filepath: str, first_lines: list[str]) -> datetime | None:
    for line in first_lines[:40]:
        dm = _DATE_LINE_RE.search(line)
        tm = _TS_LINE_RE.search(line)
        if dm and tm:
            if dm.group(1):
                y, mo, d = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
            else:
                d, mo, y = int(dm.group(4)), int(dm.group(5)), int(dm.group(6))
            hh, mm, ss = int(tm.group(1)), int(tm.group(2)), int(tm.group(3))
            ms = int(tm.group(4).ljust(3, "0"))
            try:
                return datetime(y, mo, d, hh, mm, ss, ms * 1000)
            except ValueError:
                pass

    fm = _FILENAME_DT_RE.search(Path(filepath).name)
    if fm:
        y, mo, d, hh, mm, ss = map(int, fm.groups())
        try:
            return datetime(y, mo, d, hh, mm, ss)
        except ValueError:
            pass
    return None


def load_raw_log(filepath: str | os.PathLike, pid_file: str | os.PathLike | None = None) -> pa.Table:
    """Читает текстовый лог OpenDiag Mobile (.log/.txt) и возвращает PyArrow Table."""
    path_str = str(filepath)
    profile = load_pid_profile(pid_file)

    with open(path_str, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    start_dt = _parse_start_datetime(path_str, lines)
    base_date = start_dt.date() if start_dt else datetime(2000, 1, 1).date()

    first_ts_sec: float | None = None
    last_line_ts_sec: float | None = None
    day_offset_sec = 0.0
    prev_tod_sec: float | None = None

    last_adc_payload: bytes | None = None
    records: list[dict[str, Any]] = []

    for line in lines:
        tm = _TS_LINE_RE.search(line)
        if tm:
            hh, mm, ss = int(tm.group(1)), int(tm.group(2)), int(tm.group(3))
            ms = int(tm.group(4).ljust(3, "0"))
            tod = hh * 3600.0 + mm * 60.0 + ss + ms / 1000.0
            if prev_tod_sec is not None and tod + 3600.0 < prev_tod_sec:
                day_offset_sec += 86400.0
            prev_tod_sec = tod
            last_line_ts_sec = day_offset_sec + tod
            if first_ts_sec is None:
                first_ts_sec = last_line_ts_sec

        rm = _RECV_RE.search(line)
        if not rm:
            continue

        byte_seq = _parse_hex_tokens(rm.group("hex"))
        extracted = _extract_kwp_service_payload(byte_seq)
        if extracted is None:
            continue

        svc_id, payload = extracted
        if svc_id == 0x03:
            last_adc_payload = payload
            continue

        decoded = decode_packet(payload, last_adc_payload, profile=profile)
        if decoded is None:
            continue

        frame_idx = len(records)
        if last_line_ts_sec is not None and first_ts_sec is not None:
            rel_sec = round(last_line_ts_sec - first_ts_sec, 3)
            cur_dt = datetime.combine(base_date, datetime.min.time()) + timedelta(seconds=last_line_ts_sec)
        else:
            rel_sec = round(frame_idx * 0.25, 3)
            cur_dt = (start_dt or datetime(2000, 1, 1)) + timedelta(seconds=rel_sec)

        row: dict[str, Any] = {
            "LogID": frame_idx + 1,
            "LogEntryDate": cur_dt.strftime("%Y-%m-%d"),
            "LogEntryTime": cur_dt.strftime("%H:%M:%S.%f")[:-3],
            "LogEntrySeconds": rel_sec,
            "LogNotes": "",
        }
        for col in COLUMNS:
            if col not in row:
                row[col] = decoded.get(col)
        for item in profile:
            cname = item["name"]
            if cname not in row:
                row[cname] = decoded.get(cname)

        records.append(row)

    all_cols = list(COLUMNS)
    for item in profile:
        if item["name"] not in all_cols:
            all_cols.append(item["name"])

    if not records:
        empty_arrays = [pa.array([], type=pa.float64()) for _ in all_cols]
        return pa.Table.from_arrays(empty_arrays, names=all_cols)

    col_arrays = []
    for col in all_cols:
        vals = [r.get(col) for r in records]
        if col in ("LogEntryDate", "LogEntryTime", "LogNotes"):
            col_arrays.append(pa.array([str(v) if v is not None else "" for v in vals], type=pa.string()))
        elif col == "LogID":
            col_arrays.append(pa.array([int(v) if v is not None else 0 for v in vals], type=pa.int64()))
        else:
            col_arrays.append(pa.array(vals, type=pa.float64()))

    return pa.Table.from_arrays(col_arrays, names=all_cols)


def save_parquet(table: pa.Table, filepath: str | os.PathLike) -> None:
    pq.write_table(table, str(filepath), compression="snappy")


def save_csv(table: pa.Table, filepath: str | os.PathLike) -> None:
    pa_csv.write_csv(table, str(filepath))


def load_table(filepath: str | os.PathLike, pid_file: str | os.PathLike | None = None) -> tuple[pa.Table, bool]:
    """Загружает таблицу из .parquet/.csv либо разбирает сырой лог OpenDiag."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext == ".parquet":
        return pq.read_table(str(p)), False
    if ext == ".csv":
        return pa_csv.read_csv(str(p)), False
    return load_raw_log(p, pid_file=pid_file), True
