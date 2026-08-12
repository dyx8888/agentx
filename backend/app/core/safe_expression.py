"""Small, safe boolean expression evaluator for config-driven rules."""

from __future__ import annotations

import ast
import operator
from collections.abc import Mapping
from typing import Any


class SafeExpressionError(ValueError):
    """Raised when an expression uses unsupported or unsafe syntax."""


_UNARY_OPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}

_MAX_EXPRESSION_LENGTH = 500
_MAX_AST_NODES = 80


def safe_eval_bool(expression: str, variables: Mapping[str, Any] | None = None) -> bool:
    """Evaluate a limited config expression and return it as a boolean.

    Supported syntax intentionally covers simple rule conditions only: names,
    literals, comparisons, boolean operators, numeric arithmetic, indexing, and
    ``mapping.get(key, default)`` calls.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise SafeExpressionError("Expression must be a non-empty string")
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise SafeExpressionError("Expression is too long")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeExpressionError("Expression has invalid syntax") from exc

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > _MAX_AST_NODES:
        raise SafeExpressionError("Expression is too complex")

    evaluator = _SafeEvaluator(dict(variables or {}))
    return bool(evaluator.visit(tree.body))


class _SafeEvaluator(ast.NodeVisitor):
    def __init__(self, variables: dict[str, Any]):
        self._variables = variables

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, str | int | float | bool | type(None)):
            return node.value
        raise SafeExpressionError("Unsupported literal")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self._variables:
            return self._variables[node.id]
        raise SafeExpressionError(f"Unknown variable: {node.id}")

    def visit_List(self, node: ast.List) -> list[Any]:
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        return tuple(self.visit(item) for item in node.elts)

    def visit_Dict(self, node: ast.Dict) -> dict[Any, Any]:
        return {
            self.visit(key): self.visit(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        }

    def visit_BoolOp(self, node: ast.BoolOp) -> bool:
        if isinstance(node.op, ast.And):
            return all(bool(self.visit(value)) for value in node.values)
        if isinstance(node.op, ast.Or):
            return any(bool(self.visit(value)) for value in node.values)
        raise SafeExpressionError("Unsupported boolean operator")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise SafeExpressionError("Unsupported unary operator")
        return op(self.visit(node.operand))

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op = _BINARY_OPS.get(type(node.op))
        if op is None:
            raise SafeExpressionError("Unsupported binary operator")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        for op_node, comparator in zip(node.ops, node.comparators, strict=True):
            op = _COMPARE_OPS.get(type(op_node))
            if op is None:
                raise SafeExpressionError("Unsupported comparison operator")
            right = self.visit(comparator)
            if not op(left, right):
                return False
            left = right
        return True

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        target = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return target[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise SafeExpressionError("Invalid subscript access") from exc

    def visit_Call(self, node: ast.Call) -> Any:
        if node.keywords:
            raise SafeExpressionError("Keyword arguments are not supported")
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
            raise SafeExpressionError("Only mapping.get(...) calls are supported")

        target = self.visit(node.func.value)
        if not isinstance(target, Mapping):
            raise SafeExpressionError("Only mappings can use get(...)")
        if not 1 <= len(node.args) <= 2:
            raise SafeExpressionError("mapping.get(...) requires one or two arguments")

        key = self.visit(node.args[0])
        default = self.visit(node.args[1]) if len(node.args) == 2 else None
        return target.get(key, default)

    def generic_visit(self, node: ast.AST) -> Any:
        raise SafeExpressionError(f"Unsupported syntax: {node.__class__.__name__}")
