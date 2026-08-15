"""Whitelist Qlib expression compiler for D-34 composed proposals.

The LLM may propose a factor as a Qlib expression instead of picking one of
the five catalog operators. This module is the only implementation authority
for that string: parse, bound, and render both the Qlib form and a pandas
``BaseFactor`` body. Anything outside the whitelist is a hard failure.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Final

MAX_DEPTH: Final = 6
MAX_NODES: Final = 24
MIN_WINDOW: Final = 1
MAX_WINDOW: Final = 252

FIELDS: Final = frozenset({"close", "open", "high", "low", "volume"})
UNARY_FUNCS: Final = frozenset({"Abs", "Log", "Sign"})
WINDOW_FUNCS: Final = frozenset({"Ref", "Mean", "Std", "Sum", "Max", "Min", "Delta", "EMA", "Rank"})
BINOPS: Final = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
}


class QlibExprError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class CompiledExpr:
    qlib: str
    pandas_body: str
    node_count: int
    depth: int


_TOKEN_RE = re.compile(
    r"""
    \s+
    | \$[A-Za-z]+
    | [A-Za-z_][A-Za-z0-9_]*
    | \d+
    | [()+\-*/,]
    """,
    re.VERBOSE,
)


def compile_qlib_expr(raw: str) -> CompiledExpr:
    source = raw.strip()
    if not source or len(source) > 400:
        raise QlibExprError("d34_qlib_expr_invalid", "expression is empty or too long")
    pythonish = _to_python_expr(source)
    try:
        tree = ast.parse(pythonish, mode="eval")
    except SyntaxError as exc:
        raise QlibExprError("d34_qlib_expr_invalid", "expression is not parseable") from exc
    qlib, pandas_body, nodes, depth = _compile_node(tree.body, depth=1)
    if nodes > MAX_NODES or depth > MAX_DEPTH:
        raise QlibExprError("d34_qlib_expr_too_complex", "expression exceeds node or depth bounds")
    return CompiledExpr(qlib=qlib, pandas_body=pandas_body, node_count=nodes, depth=depth)


def _to_python_expr(source: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(source):
        match = _TOKEN_RE.match(source, index)
        if match is None:
            raise QlibExprError("d34_qlib_expr_invalid", f"illegal token at {index}")
        token = match.group(0)
        index = match.end()
        if token.isspace():
            continue
        if token.startswith("$"):
            name = token[1:].lower()
            if name not in FIELDS:
                raise QlibExprError("d34_qlib_expr_invalid", f"unknown field {token}")
            pieces.append(f"field_{name}")
            continue
        pieces.append(token)
    return " ".join(pieces)


def _compile_node(node: ast.AST, *, depth: int) -> tuple[str, str, int, int]:
    if depth > MAX_DEPTH:
        raise QlibExprError("d34_qlib_expr_too_complex", "expression exceeds depth bounds")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        qlib, pandas_body, nodes, child_depth = _compile_node(node.operand, depth=depth + 1)
        return f"-({qlib})", f"-({pandas_body})", nodes + 1, max(depth, child_depth)
    if isinstance(node, ast.BinOp) and type(node.op) in BINOPS:
        symbol = BINOPS[type(node.op)]
        left_q, left_p, left_n, left_d = _compile_node(node.left, depth=depth + 1)
        right_q, right_p, right_n, right_d = _compile_node(node.right, depth=depth + 1)
        return (
            f"({left_q}{symbol}{right_q})",
            f"({left_p} {symbol} {right_p})",
            left_n + right_n + 1,
            max(depth, left_d, right_d),
        )
    if isinstance(node, ast.Name):
        if not node.id.startswith("field_") or node.id[6:] not in FIELDS:
            raise QlibExprError("d34_qlib_expr_invalid", f"unknown name {node.id}")
        field = node.id[6:]
        return f"${field}", f'frame["{field}"]', 1, depth
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        if not MIN_WINDOW <= node.value <= MAX_WINDOW:
            raise QlibExprError("d34_qlib_expr_window_invalid", "window is out of bounds")
        return str(node.value), str(node.value), 1, depth
    if isinstance(node, ast.Call):
        return _compile_call(node, depth=depth)
    raise QlibExprError("d34_qlib_expr_invalid", f"unsupported syntax {type(node).__name__}")


def _compile_call(node: ast.Call, *, depth: int) -> tuple[str, str, int, int]:
    if not isinstance(node.func, ast.Name) or node.keywords:
        raise QlibExprError("d34_qlib_expr_invalid", "only named whitelist functions are allowed")
    name = node.func.id
    if name in UNARY_FUNCS:
        if len(node.args) != 1:
            raise QlibExprError("d34_qlib_expr_invalid", f"{name} takes one argument")
        inner_q, inner_p, nodes, child_d = _compile_node(node.args[0], depth=depth + 1)
        pandas = {
            "Abs": f"({inner_p}).abs()",
            "Log": f"np.log(({inner_p}).clip(lower=1e-12))",
            "Sign": f"np.sign({inner_p})",
        }[name]
        return f"{name}({inner_q})", pandas, nodes + 1, max(depth, child_d)
    if name in WINDOW_FUNCS:
        if len(node.args) != 2:
            raise QlibExprError("d34_qlib_expr_invalid", f"{name} takes an expression and a window")
        inner_q, inner_p, nodes, child_d = _compile_node(node.args[0], depth=depth + 1)
        window_q, window_p, window_n, window_d = _compile_node(node.args[1], depth=depth + 1)
        if not window_p.isdigit():
            raise QlibExprError("d34_qlib_expr_window_invalid", f"{name} window must be an integer")
        window = int(window_p)
        pandas = _pandas_window(name, inner_p, window)
        return (
            f"{name}({inner_q},{window_q})",
            pandas,
            nodes + window_n + 1,
            max(depth, child_d, window_d),
        )
    raise QlibExprError("d34_qlib_expr_invalid", f"function {name} is not on the whitelist")


def _pandas_window(name: str, inner: str, window: int) -> str:
    grouped = f'({inner}).groupby(frame["symbol"], sort=False)'
    if name == "Ref":
        return f"{grouped}.shift({window})"
    if name == "Delta":
        return f"{grouped}.diff({window})"
    if name == "Rank":
        return (
            f'({inner}).groupby(frame["date"] if "date" in frame.columns else '
            f'frame.index, sort=False).rank(pct=True)'
        )
    rolling = f"{grouped}.transform(lambda values: values.rolling({window}, min_periods={window})"
    method = {
        "Mean": ".mean())",
        "Std": ".std(ddof=0))",
        "Sum": ".sum())",
        "Max": ".max())",
        "Min": ".min())",
        "EMA": f".ewm(span={window}, adjust=False).mean())",
    }[name]
    return rolling + method
