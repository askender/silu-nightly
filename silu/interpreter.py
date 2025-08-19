"""
Silu Interpreter Module

Simplified interpreter that extends BaseASTProcessor for direct execution of Silu programs.
"""

import ast
from typing import Any, Dict, List, Optional

from .ast_processor import BaseASTProcessor


class ReturnException(Exception):
    """Exception used to handle return statements in functions."""

    def __init__(self, value):
        self.value = value


class Function:
    """Represents a user-defined function."""

    def __init__(
        self, name: str, args: List[str], body: List[ast.stmt], env: "Environment"
    ):
        self.name = name
        self.args = args
        self.body = body
        self.env = env

    def __call__(self, *args):
        # Create function environment with argument bindings
        func_env = Environment(parent=self.env)
        for arg, value in zip(self.args, args):
            func_env.set(arg, value)

        # Execute function body
        interpreter = SiluInterpreter(env=func_env)
        try:
            for stmt in self.body:
                interpreter.visit(stmt)
        except ReturnException as ret:
            return ret.value
        return None


class Environment:
    """Manages variable and function storage with built-in functions."""

    def __init__(self, parent: Optional["Environment"] = None):
        self.vars: Dict[str, Any] = {}
        self.parent = parent
        if parent is None:  # Global environment gets built-ins
            self._register_builtins()

    def _register_builtins(self):
        """Register all built-in functions and types."""
        self.vars.update({
            "print": lambda *args: print(*args),
            "type": type,
            "isinstance": self._isinstance,
            "int": lambda x=0: int(x),
            "float": lambda x=0.0: float(x),
            "str": lambda x="": str(x),
            "bool": lambda x=False: bool(x),
            "list": lambda x=None: [] if x is None else list(x),
            "range": range,
            "int_type": int,
            "float_type": float,
            "str_type": str,
            "bool_type": bool,
        })

    def _isinstance(self, obj, cls) -> bool:
        """Built-in isinstance with type name support."""
        type_map = {"int": int, "float": float, "str": str, "bool": bool}
        if cls in type_map.values() or (hasattr(cls, "__name__") and cls.__name__ in type_map):
            actual_type = type_map.get(cls.__name__, cls)
            return isinstance(obj, actual_type)
        try:
            return isinstance(obj, cls)
        except TypeError:
            return False

    def get(self, name: str) -> Any:
        """Get variable value, checking parent environments."""
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Name '{name}' is not defined")

    def set(self, name: str, value: Any) -> None:
        """Set variable value."""
        self.vars[name] = value


class SiluInterpreter(BaseASTProcessor):
    """Simplified Silu interpreter."""

    def __init__(self, env: Optional[Environment] = None):
        self.env = env if env is not None else Environment()

    # ================== Abstract Method Implementations ==================

    def process_assign(self, target: str, value: Any) -> None:
        """Set variable in environment."""
        self.env.set(target, value)

    def process_name(self, name: str, context: ast.AST) -> Any:
        """Handle variable lookup or return name for assignment."""
        if isinstance(context, ast.Load):
            return self.env.get(name)
        elif isinstance(context, ast.Store):
            return name
        raise NotImplementedError(f"Unsupported name context: {type(context)}")

    def process_constant(self, value: Any) -> Any:
        """Return constant value."""
        return value

    def process_operation(self, op: str, *operands) -> Any:
        """Handle all operations using consolidated logic."""
        # Define all operation mappings
        unary_ops = {"+": lambda x: +x, "-": lambda x: -x, "not": lambda x: not x}
        binary_ops = {
            "+": lambda l, r: l + r, "-": lambda l, r: l - r, "*": lambda l, r: l * r,
            "/": lambda l, r: l / r, "//": lambda l, r: l // r, "%": lambda l, r: l % r,
            "**": lambda l, r: l ** r
        }
        comp_ops = {
            "==": lambda l, r: l == r, "!=": lambda l, r: l != r, "<": lambda l, r: l < r,
            "<=": lambda l, r: l <= r, ">": lambda l, r: l > r, ">=": lambda l, r: l >= r
        }

        if len(operands) == 1:  # Unary
            if op not in unary_ops:
                raise NotImplementedError(f"Unsupported unary operator: {op}")
            return unary_ops[op](operands[0])
        elif op in ("and", "or"):  # Boolean
            return all(operands) if op == "and" else any(operands)
        elif len(operands) == 2:  # Binary
            if op not in binary_ops:
                raise NotImplementedError(f"Unsupported binary operator: {op}")
            self.validate_operation(op, operands[0], operands[1])
            return binary_ops[op](operands[0], operands[1])
        elif op == "compare":  # Comparison
            left, ops, comparators = operands
            if len(ops) != len(comparators):
                raise ValueError("Mismatch between comparators and operators")
            current = left
            for op_str, comparator in zip(ops, comparators):
                if op_str not in comp_ops:
                    raise NotImplementedError(f"Unsupported comparison operator: {op_str}")
                if not comp_ops[op_str](current, comparator):
                    return False
                current = comparator
            return True
        else:
            raise NotImplementedError(f"Unsupported operation: {op}")

    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Any:
        """Execute function calls."""
        if not callable(func):
            raise TypeError(f"'{type(func).__name__}' object is not callable")
        return func(*args, **keywords)

    def process_control_flow(self, node_type: str, **kwargs) -> Any:
        """Handle control flow statements."""
        if node_type == "function_def":
            func = Function(kwargs["name"], kwargs["args"], kwargs["body"], self.env)
            self.env.set(kwargs["name"], func)
        elif node_type == "return":
            raise ReturnException(kwargs["value"])
        elif node_type == "if":
            if kwargs["test"]:
                for stmt in kwargs["body"]:
                    self.visit(stmt)
            elif kwargs["orelse"]:
                for stmt in kwargs["orelse"]:
                    self.visit(stmt)
        elif node_type == "while":
            while self.visit(kwargs["test_node"]):
                for stmt in kwargs["body"]:
                    self.visit(stmt)
        elif node_type == "for":
            if not isinstance(kwargs["target"], str):
                raise NotImplementedError("Only simple variable targets are supported in for loops")
            for item in kwargs["iter"]:
                self.env.set(kwargs["target"], item)
                for stmt in kwargs["body"]:
                    self.visit(stmt)
            # Execute else clause if exists
            if kwargs.get("orelse"):
                for stmt in kwargs["orelse"]:
                    self.visit(stmt)

    def process_container(self, container_type: str, elements: List[Any]) -> Any:
        """Handle containers."""
        containers = {
            "list": lambda e: e,
            "tuple": lambda e: tuple(e),
            "dict": lambda e: {k: v for k, v in e},
            "module": lambda e: None
        }
        return containers[container_type](elements)

    def process_expr(self, value: Any) -> Any:
        """Process expression statements."""
        return value

    def process_attribute(self, obj: Any, attr: str) -> Any:
        """Process attribute access."""
        return getattr(obj, attr)

    def process_subscript(self, obj: Any, index: Any) -> Any:
        """Process subscript operation."""
        return obj[index]

    # ================== Special Node Handlers ==================

    def visit_Call(self, node: ast.Call) -> Any:
        """Handle method calls and regular function calls."""
        if isinstance(node.func, ast.Attribute):
            # Method call
            obj = self.visit(node.func.value)
            method_name = node.func.attr
            args = [self.visit(arg) for arg in node.args]

            method = getattr(obj, method_name)
            return method(*args)
        else:
            # Regular function call
            return super().visit_Call(node)
