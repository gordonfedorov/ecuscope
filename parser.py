#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parser.py — декодер сырых логов ЭБУ Bosch M7.9.7 / M7.9.7+ (протокол KWP2000: 61 01 и 61 03)
и конвертер в форматы Apache Parquet / CSV.
"""

import csv
import os
import re
from datetime import datetime, timedelta
from typing import Any

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq

from diagnose_templates import COLUMNS, INT_INDICES, STR_INDICES

# Карта 83 дескрипторов Bosch M7.9.7 (OpenDiag):
# (col_idx, req_id, byte_offset, mask, formula_code)
DESCRIPTORS: list[tuple[int, str, int, int, str]] = [
    (5, "2101", 0x00, 0x00, "FI"),
    (6, "2101", 0x01, 0x00, "bT"),
    (7, "2101", 0x02, 0x00, "bT"),
    (8, "2101", 0x03, 0x00, "bT"),
    (9, "2101", 0x04, 0x00, "b0"),
    (10, "2101", 0x05, 0x00, "b1"),
    (11, "2101", 0x06, 0x00, "F1"),
    (12, "2101", 0x07, 0x00, "V1"),
    (13, "2101", 0x08, 0x00, "V5"),
    (14, "2101", 0x0A, 0x00, "b2"),
    (15, "2101", 0x0B, 0x00, "b3"),
    (16, "2101", 0x0C, 0x00, "b4"),
    (17, "2101", 0x0E, 0x00, "b5"),
    (18, "2101", 0x0F, 0x00, "b6"),
    (19, "2101", 0x10, 0x00, "bI"),
    (20, "2101", 0x12, 0x00, "NC"),
    (21, "2101", 0x13, 0x00, "FI"),
    (22, "2101", 0x14, 0x00, "b9"),
    (23, "2101", 0x16, 0x00, "bA"),
    (24, "2101", 0x18, 0x00, "bB"),
    (25, "2101", 0x19, 0x00, "bC"),
    (26, "2101", 0x1B, 0x00, "XI"),
    (27, "2101", 0x1D, 0x00, "bM"),
    (28, "2101", 0x1E, 0x00, "bd"),
    (29, "2101", 0x20, 0x00, "bD"),
    (30, "2101", 0x22, 0x00, "BD"),
    (31, "2101", 0x24, 0x00, "F5"),
    (32, "2101", 0x26, 0x00, "F5"),
    (33, "2101", 0x28, 0x00, "F5"),
    (34, "2101", 0x2A, 0x00, "F5"),
    (35, "2101", 0x2C, 0x00, "F5"),
    (36, "2101", 0x2E, 0x00, "V5"),
    (37, "2101", 0x30, 0x00, "F5"),
    (38, "2101", 0x32, 0x00, "bE"),
    (39, "2101", 0x34, 0x08, "B8"),
    (40, "2101", 0x34, 0x0A, "B8"),
    (41, "2101", 0x34, 0x0C, "B8"),
    (42, "2101", 0x34, 0x0E, "B8"),
    (43, "2101", 0x35, 0x00, "bA"),
    (44, "2101", 0x37, 0x00, "bA"),
    (45, "2101", 0x39, 0x00, "bC"),
    (46, "2101", 0x3B, 0x00, "bF"),
    (47, "2101", 0x3E, 0x08, "B8"),
    (48, "2101", 0x3E, 0x09, "B8"),
    (49, "2101", 0x3E, 0x0A, "B8"),
    (50, "2101", 0x3E, 0x0B, "B8"),
    (51, "2101", 0x3E, 0x0C, "B8"),
    (52, "2101", 0x3E, 0x0D, "B8"),
    (53, "2101", 0x3E, 0x0E, "B8"),
    (54, "2101", 0x3E, 0x0F, "B8"),
    (55, "2101", 0x3F, 0x08, "B8"),
    (56, "2101", 0x3F, 0x09, "B8"),
    (57, "2101", 0x3F, 0x0A, "B8"),
    (58, "2101", 0x3F, 0x0B, "B8"),
    (59, "2101", 0x3F, 0x0C, "B8"),
    (60, "2101", 0x3F, 0x0D, "B8"),
    (61, "2101", 0x3F, 0x0E, "B8"),
    (62, "2101", 0x3F, 0x0F, "B8"),
    (63, "2101", 0x40, 0x08, "B8"),
    (64, "2101", 0x40, 0x09, "B8"),
    (65, "2101", 0x40, 0x0A, "B8"),
    (66, "2101", 0x40, 0x0B, "B8"),
    (67, "2101", 0x41, 0x00, "NC"),
    (68, "2101", 0x42, 0x00, "bB"),
    (69, "2101", 0x43, 0x00, "N6"),
    (70, "2101", 0x44, 0x00, "bG"),
    (71, "2101", 0x45, 0x00, "V0"),
    (72, "2101", 0x46, 0x00, "bH"),
    (73, "2101", 0x46, 0x10, "a1"),
    (74, "2101", 0x46, 0x20, "a2"),
    (75, "2101", 0x46, 0x30, "a3"),
    (76, "2101", 0x46, 0x40, "a4"),
    (77, "2103", 0x00, 0x00, "b7"),
    (78, "2103", 0x02, 0x00, "VA"),
    (79, "2103", 0x03, 0x00, "bJ"),
    (80, "2103", 0x05, 0x00, "VA"),
    (81, "2103", 0x07, 0x00, "bJ"),
    (82, "2103", 0x09, 0x00, "VA"),
    (83, "2103", 0x0A, 0x00, "bJ"),
    (84, "2103", 0x0C, 0x00, "bN"),
    (85, "2103", 0x0E, 0x00, "bL"),
    (86, "2103", 0x0F, 0x00, "bJ"),
    (87, "2103", 0x11, 0x00, "bN"),
]

DESCRIPTORS_2101 = [d for d in DESCRIPTORS if d[1] == "2101"]
DESCRIPTORS_2103 = [d for d in DESCRIPTORS if d[1] == "2103"]

_TS_FULL_RE = re.compile(
    r"(?:(?P<date>\d{2,4}[-./]\d{2}[-./]\d{2,4})\s+)?"
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})(?:[.,](?P<ms>\d{1,3}))?"
)
_RECV_RE = re.compile(r"(?:Receive|Recv|RX|Ответ)\s*[:=-]\s*(?P<hex>.+)$", re.IGNORECASE)
_HEX_BYTE_RE = re.compile(r"^[0-9A-Fa-f]{2}$")
_HEX_PAIR_STREAM_RE = re.compile(r"^[0-9A-Fa-f]{8,}$")
_FILENAME_DT_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[-_](\d{2})-(\d{2})-(\d{2})")


def _s8(val: int) -> int:
    return val - 256 if val >= 128 else val


def _s16(val: int) -> int:
    return val - 65536 if val >= 32768 else val


def _eval_formula(data: bytes, offset: int, mask: int, code: str) -> Any:
    n = len(data)
    if offset >= n:
        return None
    b = data[offset]
    w = ((b << 8) | data[offset + 1]) if (offset + 1) < n else None

    if code == "FI":
        return int(b)
    if code == "bT":
        return round(b * 0.75 - 48.0, 2)
    if code == "b0":
        return round(5.2 + b * 0.05, 3)
    if code == "b1":
        return int(b)
    if code == "F1":
        return round(b * 0.5, 2)
    if code == "V1":
        return int(b * 40)
    if code == "V5":
        if w is None:
            return None
        return round(w * 0.1, 2)
    if code == "b2":
        return round(_s8(b) * 0.75, 2)
    if code == "b3":
        return round(b * 0.75, 2)
    if code == "b4":
        if w is None:
            return None
        return round(w * 0.0015258789, 2)
    if code == "b5":
        return round(b * 0.390625, 2)
    if code == "b6":
        return round(b / 128.0, 4)
    if code == "bI":
        if w is None:
            return None
        return round(w * 0.0026666667, 3)
    if code == "NC":
        return int(b * 10)
    if code == "b9":
        if w is None:
            return None
        return round(w * 0.01, 2)
    if code == "bA":
        if w is None:
            return None
        return round(_s16(w) * 0.0030517578, 3)
    if code == "bB":
        return round((b - 128) * 0.0052125, 4)
    if code == "bC":
        if w is None:
            return None
        return round(w / 32768.0, 4)
    if code == "XI":
        if w is None:
            return None
        return round(w / 32768.0, 4)
    if code == "bM":
        return round(b * 0.390625, 2)
    if code == "bd":
        if w is None:
            return None
        return round(w * 0.0048828125, 4)
    if code == "bD":
        if w is None:
            return None
        return round(_s16(w) * 0.25, 2)
    if code == "BD":
        if w is None:
            return None
        return round(_s16(w) * 0.25, 2)
    if code == "F5":
        if w is None:
            return None
        return int(w)
    if code == "bE":
        if w is None:
            return None
        return round(w * 0.01, 2)
    if code == "B8":
        bit = mask & 0x07
        return 1 if (b & (1 << bit)) else 0
    if code == "bF":
        return round(_s8(b) * 0.015625, 3)
    if code == "N6":
        return round(b * 0.01, 3)
    if code == "bG":
        return round(_s8(b) * 0.001, 4)
    if code == "V0":
        return round(b * 0.00390625, 4)
    if code == "bH":
        return round(_s8(b) * 0.0005, 4)
    if code == "b7":
        if w is None:
            return None
        return round(w * 0.0001831055, 3)
    if code == "VA":
        return round(b * 0.01953125, 3)
    if code == "bJ":
        if w is None:
            return None
        return round(w * 0.0000762939, 3)
    if code == "bN":
        if w is None:
            return None
        return round(w * 0.1, 1)
    if code == "bL":
        return round((b - 128) * 0.01953125, 3)
    return None


def is_valid_packet(payload: bytes) -> bool:
    """Проверяет адекватность ответа ЭБУ 61 01 (отсекает байты-заглушки 0xDD при потере связи)."""
    if len(payload) < 55:
        return False
    err_cnt = payload[0x00]
    ect_raw = payload[0x02]
    rpm_raw = payload[0x07]
    if err_cnt == 0xDD and ect_raw == 0xDD and rpm_raw == 0xDD:
        return False
    if ect_raw == 0xFF or rpm_raw == 0xFF:
        return False
    return True


def decode_packet(payload: bytes, adc_payload: bytes | None = None) -> dict[int, Any] | None:
    """Декодирует полезную нагрузку ответа 61 01 (и опционально 61 03) в словарь {col_idx: val}."""
    if not is_valid_packet(payload):
        return None

    row: dict[int, Any] = {}
    for col_idx, _req, offset, mask, code in DESCRIPTORS_2101:
        if code.startswith("a"):
            continue
        val = _eval_formula(payload, offset, mask, code)
        if val is not None:
            row[col_idx] = int(round(val)) if col_idx in INT_INDICES else val

    # Виртуальные расчётные каналы a1..a4 (колонки 73..76)
    rpm = row.get(12)
    maf = row.get(13)
    inj = row.get(19)

    if rpm is not None and inj is not None and rpm > 0:
        cycle_ms = 120000.0 / rpm
        row[73] = round(min(150.0, (inj / cycle_ms) * 100.0), 2)
    else:
        row[73] = 0.0

    if rpm is not None and maf is not None and rpm > 0:
        row[74] = round((maf * 1000000.0) / (rpm * 120.0), 2)
    else:
        row[74] = 0.0

    if maf is not None:
        pwr_hp = maf / 3.25
        row[75] = round(pwr_hp, 2)
        if rpm is not None and rpm > 0:
            row[76] = round((pwr_hp * 7023.5) / rpm, 2)
        else:
            row[76] = 0.0

    # Декодирование блока АЦП 61 03 (колонки 77..87)
    if adc_payload and len(adc_payload) >= 18:
        for col_idx, _req, offset, mask, code in DESCRIPTORS_2103:
            val = _eval_formula(adc_payload, offset, mask, code)
            if val is not None:
                row[col_idx] = int(round(val)) if col_idx in INT_INDICES else val

    return row


def _parse_hex_tokens(text: str) -> list[int]:
    """Извлекает последовательность hex-байтов из хвоста строки."""
    raw_tokens = text.strip().split()
    out: list[int] = []
    for tok in raw_tokens:
        clean = tok.rstrip(",;")
        if _HEX_BYTE_RE.match(clean):
            out.append(int(clean, 16))
        elif _HEX_PAIR_STREAM_RE.match(clean) and len(clean) % 2 == 0 and not out:
            for j in range(0, len(clean), 2):
                out.append(int(clean[j : j + 2], 16))
            break
        else:
            if out:
                break
    return out


def _extract_kwp_service_payload(byte_seq: list[int]) -> tuple[int, bytes] | None:
    """
    Находит ответ KWP2000 0x61 (сервис 0x01 или 0x03) в байтовой последовательности
    с учётом различных вариантов заголовка (4-байтовый, 3-байтовый, F1 10 61 ... или чистый 61 ...).
    """
    n = len(byte_seq)
    for pos in range(min(n - 2, 10)):
        if byte_seq[pos] != 0x61:
            continue
        sub_id = byte_seq[pos + 1]
        if sub_id not in (0x01, 0x03):
            continue

        payload_start = pos + 2
        payload_end = n

        # Вариант 1: 4-байтовый заголовок KWP2000: [80/C0] [TGT] [SRC] [LEN] 61 SUB ... CRC
        if pos >= 4 and (byte_seq[pos - 4] & 0x3F) == 0 and byte_seq[pos - 4] in (0x80, 0xC0):
            kwp_len = byte_seq[pos - 1]
            if kwp_len >= 2:
                payload_end = min(n, pos + kwp_len)
        # Вариант 2: 3-байтовый заголовок KWP2000: [80+LEN/C0+LEN] [TGT] [SRC] 61 SUB ... CRC
        elif pos >= 3 and (byte_seq[pos - 3] & 0xC0) in (0x80, 0xC0) and (byte_seq[pos - 3] & 0x3F) >= 2:
            kwp_len = byte_seq[pos - 3] & 0x3F
            payload_end = min(n, pos + kwp_len)
        # Вариант 3: кадр с адресами без байта длины (F1 10 61 SUB ... CRC) — отрезаем 1 байт CRC в конце
        elif pos == 2 and byte_seq[0] in (0xF1, 0x10) and byte_seq[1] in (0x10, 0xF1):
            if n - payload_start > 55 or (sub_id == 0x03 and n - payload_start >= 19):
                payload_end = n - 1
        # Вариант 4: чистый ответ без заголовка (61 01 ... или 61 03 ...)
        elif pos == 0:
            # Если в конце присутствует байт контрольной суммы (например, 79 байт = 2 + 76 + 1 CRC)
            if sub_id == 0x01 and n == 79:
                payload_end = n - 1
            elif sub_id == 0x03 and n == 22:
                payload_end = n - 1

        payload = bytes(byte_seq[payload_start:payload_end])
        if sub_id == 0x01 and len(payload) >= 55:
            return (0x01, payload)
        if sub_id == 0x03 and len(payload) >= 18:
            return (0x03, payload)

    return None


def _parse_start_datetime(filepath: str, first_lines: list[str]) -> datetime | None:
    """Пытается определить дату/время начала сеанса из шапки лога или имени файла."""
    for line in first_lines[:30]:
        m = _TS_FULL_RE.search(line)
        if m and m.group("date"):
            d_raw = m.group("date").replace(".", "-").replace("/", "-")
            parts = d_raw.split("-")
            try:
                if len(parts[0]) == 4:
                    y, mo, d = int(parts[0]), int(parts[1]), int(parts[2])
                else:
                    d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
                    if y < 100:
                        y += 2000
                h, mi, s = int(m.group("h")), int(m.group("m")), int(m.group("s"))
                ms = int((m.group("ms") or "0").ljust(3, "0"))
                return datetime(y, mo, d, h, mi, s, ms * 1000)
            except ValueError:
                pass

    base = os.path.basename(filepath)
    m_fn = _FILENAME_DT_RE.search(base)
    if m_fn:
        try:
            return datetime(
                int(m_fn.group(1)),
                int(m_fn.group(2)),
                int(m_fn.group(3)),
                int(m_fn.group(4)),
                int(m_fn.group(5)),
                int(m_fn.group(6)),
            )
        except ValueError:
            pass
    return None


def load_raw_log(filepath: str | os.PathLike) -> pa.Table:
    """Читает текстовый лог OpenDiag (.log / .txt) и возвращает типизированную таблицу PyArrow."""
    path_str = os.fspath(filepath)
    raw_bytes = open(path_str, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw_bytes.decode("utf-8", errors="replace")

    lines = text.splitlines()
    start_dt = _parse_start_datetime(path_str, lines)

    base_sec: float | None = None
    last_sec: float = 0.0
    day_offset: float = 0.0
    step_sec: float = 0.25

    latest_adc: tuple[float, bytes] | None = None
    parsed_frames: list[tuple[float, str, str, bytes, bytes | None]] = []

    for line in lines:
        s_line = line.strip()
        if not s_line:
            continue

        # Извлекаем временную метку строки, если она есть
        cur_sec: float | None = None
        date_str = ""
        time_str = ""

        m_ts = _TS_FULL_RE.search(s_line)
        if m_ts:
            h, mi, s = int(m_ts.group("h")), int(m_ts.group("m")), int(m_ts.group("s"))
            ms = int((m_ts.group("ms") or "0").ljust(3, "0"))
            tod_sec = h * 3600.0 + mi * 60.0 + s + ms / 1000.0 + day_offset
            if base_sec is None:
                base_sec = tod_sec
            elif tod_sec < last_sec - 43200.0:
                day_offset += 86400.0
                tod_sec += 86400.0
            last_sec = tod_sec
            cur_sec = round(tod_sec - base_sec, 3)

            if m_ts.group("date"):
                date_str = m_ts.group("date")
            elif start_dt is not None:
                date_str = (start_dt + timedelta(seconds=cur_sec)).strftime("%Y-%m-%d")
            time_str = f"{h:02d}:{mi:02d}:{s:02d}.{ms:03d}"

        # Ищем hex-данные ответа ЭБУ (после Receive:/Recv: или в строке с 61 01 / 61 03)
        hex_part = None
        m_recv = _RECV_RE.search(s_line)
        if m_recv:
            hex_part = m_recv.group("hex")
        else:
            # Игнорируем строки отправки команд (Send: 2101 и т.п.)
            if re.match(r"^(?:Send|TX|Запрос)\s*[:=-]", s_line, re.IGNORECASE):
                continue
            if "61 01" in s_line or "61 03" in s_line or "6101" in s_line or "6103" in s_line:
                if m_ts:
                    hex_part = s_line[m_ts.end() :]
                else:
                    hex_part = s_line

        if not hex_part:
            continue

        byte_seq = _parse_hex_tokens(hex_part)
        if len(byte_seq) < 18:
            continue

        extracted = _extract_kwp_service_payload(byte_seq)
        if extracted is None:
            continue

        sub_id, payload = extracted

        # Если временных меток в файле нет, восстанавливаем ось времени с шагом 0.25 с
        if cur_sec is None:
            cur_sec = round(last_sec, 3)
            last_sec += step_sec
            if start_dt is not None:
                cur_dt = start_dt + timedelta(seconds=cur_sec)
                date_str = cur_dt.strftime("%Y-%m-%d")
                time_str = cur_dt.strftime("%H:%M:%S.%f")[:-3]

        if sub_id == 0x03:
            latest_adc = (cur_sec, payload)
        elif sub_id == 0x01:
            adc_to_attach = None
            if latest_adc is not None and abs(cur_sec - latest_adc[0]) <= 3.0:
                adc_to_attach = latest_adc[1]
            parsed_frames.append((cur_sec, date_str, time_str, payload, adc_to_attach))

    num_cols = len(COLUMNS)
    col_buffers: list[list[Any]] = [[] for _ in range(num_cols)]

    valid_count = 0
    for cur_sec, date_str, time_str, payload, adc_payload in parsed_frames:
        decoded = decode_packet(payload, adc_payload)
        if decoded is None:
            continue
        valid_count += 1
        col_buffers[0].append(valid_count)
        col_buffers[1].append(date_str)
        col_buffers[2].append(time_str)
        col_buffers[3].append(cur_sec)
        col_buffers[4].append("")

        for idx in range(5, num_cols):
            col_buffers[idx].append(decoded.get(idx, None))

    arrays = []
    fields = []
    for idx, col_name in enumerate(COLUMNS):
        if idx in STR_INDICES:
            pa_type = pa.string()
        elif idx in INT_INDICES:
            pa_type = pa.int64()
        else:
            pa_type = pa.float64()
        fields.append(pa.field(col_name, pa_type))
        arrays.append(pa.array(col_buffers[idx], type=pa_type))

    return pa.Table.from_arrays(arrays, schema=pa.schema(fields))


def save_parquet(table: pa.Table, filepath: str | os.PathLike) -> None:
    pq.write_table(table, os.fspath(filepath), compression="snappy")


def save_csv(table: pa.Table, filepath: str | os.PathLike) -> None:
    path_str = os.fspath(filepath)
    with open(path_str, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(table.column_names)
        cols = [table[c].to_pylist() for c in table.column_names]
        for row_idx in range(table.num_rows):
            writer.writerow(["" if cols[c_idx][row_idx] is None else cols[c_idx][row_idx] for c_idx in range(len(cols))])


def load_table(filepath: str | os.PathLike) -> tuple[pa.Table, bool]:
    """
    Загружает диагностический лог из .parquet, .csv или сырого текстового лога OpenDiag (.log/.txt).
    Возвращает кортеж (table, is_raw).
    """
    path_str = os.fspath(filepath)
    ext = os.path.splitext(path_str)[1].lower()

    if ext == ".parquet":
        return pq.read_table(path_str), False

    if ext == ".csv":
        read_opts = pa_csv.ReadOptions(encoding="utf-8-sig")
        parse_opts = pa_csv.ParseOptions(delimiter=";")
        try:
            tbl = pa_csv.read_csv(path_str, read_options=read_opts, parse_options=parse_opts)
            if tbl.num_columns > 5:
                return tbl, False
        except Exception:
            pass
        return pa_csv.read_csv(path_str), False

    return load_raw_log(path_str), True
