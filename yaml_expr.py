#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yaml_expr.py — безопасный AST-вычислитель выражений, агрегаций и строковых шаблонов
для декларативного движка YAML-правил ECUScope (строго без eval и exec).
"""

from __future__ import annotations

import ast
import operator
import re
import statistics
from typing import Any, Callable

import pyarrow as pa

from diagnose_utils import COL, col_vals, sub

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARYOPS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_CMPOPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: (a in b) if b is not None else False,
    ast.NotIn: lambda a, b: (a not in b) if b is not None else True,
}

_COL_ALIASES: dict[str, str] = {
    "FUEL_RATE": "FUEL",
    "MISFIRE_SUM": "MIS_SUM",
    "ERRORS": "ERR_CNT",
    "IDLE_RPM": "RPM_IDLE",
}


def resolve_col_name(key: str) -> str:
    """Возвращает реальное имя столбца Parquet по короткому ключу COL в любом регистре."""
    if key in COL:
        return COL[key]
    up = key.upper()
    if up in COL:
        return COL[up]
    lo = key.lower()
    if lo in COL:
        return COL[lo]
    alias = _COL_ALIASES.get(up)
    if alias:
        if alias in COL:
            return COL[alias]
        if alias.lower() in COL:
            return COL[alias.lower()]
    return key


def is_known_param(key: str) -> bool:
    """Проверяет, является ли идентификатор известным датчиком или каналом ЭБУ."""
    up = key.upper()
    lo = key.lower()
    return (
        key in COL
        or up in COL
        or lo in COL
        or up in _COL_ALIASES
    )


def agg_values(vals: list[Any], agg: str) -> float | None:
    """Вычисляет агрегат по списку числовых значений (игнорируя None)."""
    nums = [float(v) for v in vals if v is not None]
    if not nums:
        return None
    if agg == "median":
        return float(statistics.median(nums))
    if agg == "mean":
        return float(statistics.mean(nums))
    if agg == "min":
        return float(min(nums))
    if agg == "max":
        return float(max(nums))
    if agg == "first":
        return float(nums[0])
    if agg == "last":
        return float(nums[-1])
    if agg == "sum":
        return float(sum(nums))
    if agg == "count":
        return float(len(nums))
    if agg == "spread":
        return float(max(nums) - min(nums))
    if agg == "p10_p90":
        s = sorted(nums)
        p10 = s[int(len(s) * 0.10)]
        p90 = s[min(len(s) - 1, int(len(s) * 0.90))]
        return float(p90 - p10)
    raise ValueError(f"Неизвестный агрегатор: {agg}")


def _safe_any(val: Any) -> bool:
    if isinstance(val, (list, tuple)):
        return any(bool(x) for x in val if x is not None)
    return bool(val)


def _safe_all(val: Any) -> bool:
    if isinstance(val, (list, tuple)):
        items = [x for x in val if x is not None]
        return all(bool(x) for x in items) if items else False
    return bool(val)


def _broadcast_binop(op_fn: Callable[[Any, Any], Any], left: Any, right: Any) -> Any:
    if isinstance(left, list) and isinstance(right, list):
        return [
            None if (a is None or b is None) else op_fn(a, b)
            for a, b in zip(left, right)
        ]
    if isinstance(left, list):
        return [None if (a is None or right is None) else op_fn(a, right) for a in left]
    if isinstance(right, list):
        return [None if (left is None or b is None) else op_fn(left, b) for b in right]
    if left is None or right is None:
        return None
    return op_fn(left, right)


def _broadcast_cmp(op_fn: Callable[[Any, Any], bool], left: Any, right: Any) -> Any:
    is_identity = op_fn in (operator.is_, operator.is_not)
    if isinstance(left, list) and isinstance(right, list):
        return [
            bool(op_fn(a, b)) if (is_identity or (a is not None and b is not None)) else False
            for a, b in zip(left, right)
        ]
    if isinstance(left, list):
        return [
            bool(op_fn(a, right)) if (is_identity or (a is not None and right is not None)) else False
            for a in left
        ]
    if isinstance(right, list):
        return [
            bool(op_fn(left, b)) if (is_identity or (left is not None and b is not None)) else False
            for b in right
        ]
    if not is_identity and (left is None or right is None):
        return False
    return bool(op_fn(left, right))


class SafeExprEvaluator:
    """Безопасный вычислитель выражений YAML через AST (строго без eval)."""

    def __init__(self, table: pa.Table, modes: dict[str, list[int]]) -> None:
        self.table = table
        self.modes = modes
        self.active_mode: str = "valid"
        self._col_cache: dict[str, list] = {}
        self.base_funcs: dict[str, Callable[..., Any]] = {
            "median": lambda p, m=None: self._metric("median", p, m),
            "mean": lambda p, m=None: self._metric("mean", p, m),
            "min": lambda p, m=None: self._metric("min", p, m),
            "max": lambda p, m=None: self._metric("max", p, m),
            "first": lambda p, m=None: self._metric("first", p, m),
            "last": lambda p, m=None: self._metric("last", p, m),
            "count": lambda p, m=None: self._metric("count", p, m),
            "spread": lambda p, m=None: self._metric("spread", p, m),
            "p10_p90": lambda p, m=None: self._metric("p10_p90", p, m),
            "any": _safe_any,
            "all": _safe_all,
            "abs": lambda x: abs(x) if x is not None else None,
            "round": round,
            "min_val": min,
            "max_val": max,
            "len": len,
        }

    def set_active_mode(self, mode_name: str) -> None:
        self.active_mode = mode_name or "valid"

    def get_col(self, key: str) -> list:
        col_name = resolve_col_name(key)
        if col_name not in self._col_cache:
            if col_name in self.table.column_names:
                self._col_cache[col_name] = col_vals(self.table, col_name)
            else:
                self._col_cache[col_name] = [None] * self.table.num_rows
        return self._col_cache[col_name]

    def get_mode_series(self, key: str, mode: str | None = None) -> list:
        m = mode or self.active_mode or "valid"
        idx = self.modes.get(m, [])
        return sub(self.get_col(key), idx)

    def _metric(self, agg: str, param_or_vals: Any, mode: str | None = None) -> float | None:
        if isinstance(param_or_vals, list):
            return agg_values(param_or_vals, agg)
        if param_or_vals is None:
            return None
        vals = self.get_mode_series(str(param_or_vals), mode)
        return agg_values(vals, agg)

    def eval(
        self,
        expr: str,
        extra_vars: dict[str, Any] | None = None,
        local_funcs: dict[str, Callable[..., Any]] | None = None,
    ) -> Any:
        tree = ast.parse(str(expr).strip(), mode="eval")
        env = extra_vars or {}
        lfuncs = local_funcs or {}
        return self._eval_node(tree.body, env, lfuncs)

    def _resolve_name(self, name: str, env: dict[str, Any]) -> Any:
        if name in env:
            return env[name]
        up = name.upper()
        if up in env:
            return env[up]
        lo = name.lower()
        if lo in env:
            return env[lo]

        if name in ("None", "null"):
            return None
        if name in ("True", "true"):
            return True
        if name in ("False", "false"):
            return False

        # Автоматическое разрешение <PARAM>_start и <PARAM>_end из серии окна или режима
        if up.endswith("_START") or up.endswith("_END"):
            is_start = up.endswith("_START")
            base = name[:-6] if is_start else name[:-4]
            series = None
            if base in env and isinstance(env[base], list):
                series = env[base]
            elif base.upper() in env and isinstance(env[base.upper()], list):
                series = env[base.upper()]
            elif base.lower() in env and isinstance(env[base.lower()], list):
                series = env[base.lower()]
            elif is_known_param(base):
                series = self.get_mode_series(base)
            if series is not None:
                valid_items = [v for v in series if v is not None]
                if not valid_items:
                    return None
                return valid_items[0] if is_start else valid_items[-1]

        if is_known_param(name):
            return self.get_mode_series(name)

        raise ValueError(f"Неизвестная переменная в выражении: {name}")

    def _eval_node(
        self,
        node: ast.AST,
        env: dict[str, Any],
        lfuncs: dict[str, Callable[..., Any]],
    ) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            return self._resolve_name(node.id, env)

        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left = self._eval_node(node.left, env, lfuncs)
            right = self._eval_node(node.right, env, lfuncs)
            return _broadcast_binop(_BINOPS[type(node.op)], left, right)

        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
            val = self._eval_node(node.operand, env, lfuncs)
            op_fn = _UNARYOPS[type(node.op)]
            if isinstance(val, list):
                return [None if v is None else op_fn(v) for v in val]
            if val is None and not isinstance(node.op, ast.Not):
                return None
            return op_fn(val)

        if isinstance(node, ast.BoolOp):
            vals = [self._eval_node(v, env, lfuncs) for v in node.values]
            if any(isinstance(v, list) for v in vals):
                length = max(len(v) for v in vals if isinstance(v, list))
                normed = [v if isinstance(v, list) else [v] * length for v in vals]
                if isinstance(node.op, ast.And):
                    return [all(bool(col[i]) for col in normed) for i in range(length)]
                return [any(bool(col[i]) for col in normed) for i in range(length)]
            if isinstance(node.op, ast.And):
                return all(bool(v) for v in vals)
            return any(bool(v) for v in vals)

        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, env, lfuncs)
            acc: Any = None
            for op, comp in zip(node.ops, node.comparators):
                if type(op) not in _CMPOPS:
                    raise ValueError(f"Неподдерживаемый оператор сравнения: {type(op).__name__}")
                right = self._eval_node(comp, env, lfuncs)
                step = _broadcast_cmp(_CMPOPS[type(op)], left, right)
                if acc is None:
                    acc = step
                elif isinstance(acc, list) or isinstance(step, list):
                    la = acc if isinstance(acc, list) else [acc] * len(step)
                    lb = step if isinstance(step, list) else [step] * len(acc)
                    acc = [bool(a) and bool(b) for a, b in zip(la, lb)]
                else:
                    acc = bool(acc) and bool(step)
                left = right
            return acc

        if isinstance(node, ast.IfExp):
            cond = self._eval_node(node.test, env, lfuncs)
            return self._eval_node(node.body if cond else node.orelse, env, lfuncs)

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            fn = lfuncs.get(fname) or self.base_funcs.get(fname)
            if fn is None:
                raise ValueError(f"Запрещённый вызов функции: {fname}")
            args = [self._eval_node(a, env, lfuncs) for a in node.args]
            kwargs = {kw.arg: self._eval_node(kw.value, env, lfuncs) for kw in node.keywords if kw.arg}
            return fn(*args, **kwargs)

        raise ValueError(f"Неподдерживаемая конструкция AST: {type(node).__name__}")


_TPL_RE = re.compile(r"\{([^{}:]+?)(?::([^{}]+))?\}")


def format_template(
    tpl: str,
    evaluator: SafeExprEvaluator,
    env: dict[str, Any],
    local_funcs: dict[str, Callable[..., Any]] | None = None,
) -> str:
    """Подставляет формулы {expr} или {expr:.2f} в текстовые шаблоны YAML."""
    if not tpl or "{" not in tpl:
        return tpl

    def _repl(match: re.Match[str]) -> str:
        expr_str = match.group(1).strip()
        fmt_spec = match.group(2)
        val = evaluator.eval(expr_str, env, local_funcs)
        if val is None:
            return "—"
        if fmt_spec:
            return format(val, fmt_spec)
        return str(val)

    return _TPL_RE.sub(_repl, tpl)
