"""
Silu Interpreter Module
"""

import ast
from typing import Any, Dict, Optional


class Environment:
    """
    Manages variable and function storage.
    """

    def __init__(self, parent: Optional["Environment"] = None):
        self.vars: Dict[str, Any] = {}
        self.parent = parent

    def get(self, name: str) -> Any:
        """
        Get the value of a variable.
        """
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Name '{name}' is not defined")

    def set(self, name: str, value: Any) -> None:
        """
        Set the value of a variable.
        """
        self.vars[name] = value


class SiluInterpreter(ast.NodeVisitor):
    """
    A simple interpreter for a subset of Python syntax.
    """

    def __init__(self, env: Optional[Environment] = None):
        self.env = env if env is not None else Environment()

    def visit_Module(self, node: ast.Module) -> None:
        """
        Visit the root module node and execute its statements.
        """
        for stmt in node.body:
            self.visit(stmt)

    def visit_Expr(self, node: ast.Expr) -> Any:
        """
        Visit an expression node.
        """
        return self.visit(node.value)

    def visit_Assign(self, node: ast.Assign) -> None:
        """
        Visit an assignment node.
        """
        # For simplicity, we only handle single target assignments (e.g., x = 10)
        if len(node.targets) != 1:
            raise NotImplementedError("Only single target assignments are supported")

        target = node.targets[0]
        if not isinstance(target, ast.Name):
            raise NotImplementedError("Only simple variable assignments are supported")

        value = self.visit(node.value)
        self.env.set(target.id, value)

    def visit_Name(self, node: ast.Name) -> Any:
        """
        Visit a name node.
        """
        if isinstance(node.ctx, ast.Load):
            return self.env.get(node.id)
        elif isinstance(node.ctx, ast.Store):
            # This case is handled by visit_Assign
            pass
        else:
            raise NotImplementedError(f"Unsupported context for name: {type(node.ctx)}")

    def visit_Constant(self, node: ast.Constant) -> Any:
        """
        Visit a constant node.
        """
        return node.value

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        """
        Visit a binary operation node.
        """
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Check for division by zero operations
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            if isinstance(node.op, ast.Mod):
                raise ZeroDivisionError("Modulo by zero")
            raise ZeroDivisionError("Division by zero")

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left**right

        raise NotImplementedError(f"Unsupported binary operator: {type(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """
        Visit a unary operation node.
        """
        operand = self.visit(node.operand)

        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.Not):
            return not operand

        raise NotImplementedError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """
        Visit a boolean operation node.
        """
        values = [self.visit(value) for value in node.values]

        if isinstance(node.op, ast.And):
            for value in values:
                if not value:  # Short-circuit evaluation
                    return False
            return True
        if isinstance(node.op, ast.Or):
            for value in values:
                if value:  # Short-circuit evaluation
                    return True
            return False

        raise NotImplementedError(f"Unsupported boolean operator: {type(node.op)}")

    def visit_Compare(self, node: ast.Compare) -> Any:
        """
        Visit a comparison node.
        """
        left = self.visit(node.left)
        comparators = [self.visit(comparator) for comparator in node.comparators]
        ops = node.ops

        if len(comparators) != len(ops):
            raise ValueError("Mismatch between comparators and operators")

        # For chained comparisons, we need to evaluate each pair
        for i, (comparator, op) in enumerate(zip(comparators, ops)):
            # For chained comparisons, the right side of one comparison
            # becomes the left side of the next
            left_val = left if i == 0 else comparators[i - 1]

            if isinstance(op, ast.Eq):
                result = left_val == comparator
            elif isinstance(op, ast.NotEq):
                result = left_val != comparator
            elif isinstance(op, ast.Lt):
                result = left_val < comparator
            elif isinstance(op, ast.LtE):
                result = left_val <= comparator
            elif isinstance(op, ast.Gt):
                result = left_val > comparator
            elif isinstance(op, ast.GtE):
                result = left_val >= comparator
            else:
                raise NotImplementedError(
                    f"Unsupported comparison operator: {type(op)}"
                )

            if not result:  # Short-circuit evaluation
                return False

        return True


def main() -> None:
    """
    Entry point for the Silu interpreter.
    """
    print("Hello from Silu!")


if __name__ == "__main__":
    main()
