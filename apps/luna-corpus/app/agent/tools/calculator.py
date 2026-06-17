"""Calculator tool for mathematical expressions."""
import ast
import operator
from app.agent.tool import tool


# Supported operations
OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}


class _EvalVisitor(ast.NodeVisitor):
    """AST visitor to evaluate mathematical expressions safely."""

    def visit_Expression(self, node):
        """Visit the top-level expression node."""
        return self.visit(node.body)

    def visit_BinOp(self, node):
        """Visit binary operation."""
        left = self.visit(node.left)
        right = self.visit(node.right)
        return OPS[type(node.op)](left, right)

    def visit_Constant(self, node):
        """Visit constant (number)."""
        return node.value

    def visit_UnaryOp(self, node):
        """Visit unary operation."""
        operand = self.visit(node.operand)
        return OPS[type(node.op)](operand)


def safe_eval(expression: str) -> float:
    """Safely evaluate a mathematical expression.

    Args:
        expression: Mathematical expression (e.g., "2 + 3 * 4")

    Returns:
        Result of the expression

    Raises:
        ValueError: If the expression contains unsupported operations
    """
    try:
        node = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"Invalid mathematical expression: {e}") from e

    visitor = _EvalVisitor()
    return visitor.visit(node)


calculator_tool = tool(
    name="calculator",
    description=(
        "Calculate a mathematical expression. Supports +, -, *, /, **, % "
        "and parentheses. Example: '2 + 3 * 4' or '(10 + 5) / 3'"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": (
                    "Mathematical expression to calculate, e.g., '2 + 3 * 4'"
                ),
            },
        },
        "required": ["expression"],
    },
)(safe_eval)
