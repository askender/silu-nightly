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
        builtins = {
            # I/O functions
            "print": lambda *args: print(*args),
            # Type functions
            "type": type,
            "isinstance": self._isinstance,
            # Type constructors
            "int": lambda x=0: int(x),
            "float": lambda x=0.0: float(x),
            "str": lambda x="": str(x),
            "bool": lambda x=False: bool(x),
            "list": lambda x=None: [] if x is None else list(x),
            "range": range,
            # Type objects
            "int_type": int,
            "float_type": float,
            "str_type": str,
            "bool_type": bool,
        }
        self.vars.update(builtins)

    def _isinstance(self, obj, cls) -> bool:
        """Built-in isinstance with type name support."""
        type_map = {"int": int, "float": float, "str": str, "bool": bool}
        if cls in type_map.values():
            return isinstance(obj, cls)
        if hasattr(cls, "__name__") and cls.__name__ in type_map:
            return isinstance(obj, type_map[cls.__name__])
        try:
            return isinstance(obj, cls)
        except TypeError:
            # Handle invalid types gracefully
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
        if len(operands) == 1:  # Unary operation
            return self._process_unary(op, operands[0])
        elif op in ("and", "or"):  # Boolean operation
            return self._process_boolean(op, operands)
        elif len(operands) == 2:  # Binary operation
            return self._process_binary(op, operands[0], operands[1])
        elif op == "compare":  # Comparison operation
            return self._process_comparison(operands[0], operands[1], operands[2])
        else:  # Unknown operation
            raise NotImplementedError(f"Unsupported operation: {op}")

    def _process_unary(self, op: str, operand: Any) -> Any:
        """Process unary operations."""
        ops = {"+": lambda x: +x, "-": lambda x: -x, "not": lambda x: not x}
        if op in ops:
            return ops[op](operand)
        raise NotImplementedError(f"Unsupported unary operator: {op}")

    def _process_binary(self, op: str, left: Any, right: Any) -> Any:
        """Process binary operations with division by zero checking."""
        if op in ("/", "//", "%") and right == 0:
            raise ZeroDivisionError(
                "Division by zero" if op != "%" else "Modulo by zero"
            )

        ops = {
            "+": lambda left, right: left + right,
            "-": lambda left, right: left - right,
            "*": lambda left, right: left * right,
            "/": lambda left, right: left / right,
            "//": lambda left, right: left // right,
            "%": lambda left, right: left % right,
            "**": lambda left, right: left**right,
        }
        if op in ops:
            return ops[op](left, right)
        raise NotImplementedError(f"Unsupported binary operator: {op}")

    def _process_boolean(self, op: str, operands: tuple) -> Any:
        """Process boolean operations with short-circuit evaluation."""
        if op == "and":
            return all(operands)
        elif op == "or":
            return any(operands)
        raise NotImplementedError(f"Unsupported boolean operator: {op}")

    def _process_comparison(
        self, left: Any, ops: List[str], comparators: List[Any]
    ) -> Any:
        """Process comparison operations with chaining support."""
        # Validate that operators and comparators match
        if len(ops) != len(comparators):
            raise ValueError("Mismatch between comparators and operators")

        comp_ops = {
            "==": lambda left, right: left == right,
            "!=": lambda left, right: left != right,
            "<": lambda left, right: left < right,
            "<=": lambda left, right: left <= right,
            ">": lambda left, right: left > right,
            ">=": lambda left, right: left >= right,
        }

        # Handle chained comparisons
        current = left
        for op, comparator in zip(ops, comparators):
            if op not in comp_ops:
                raise NotImplementedError(f"Unsupported comparison operator: {op}")
            if not comp_ops[op](current, comparator):
                return False
            current = comparator
        return True

    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Any:
        """Execute function calls."""
        if not callable(func):
            raise TypeError(f"'{type(func).__name__}' object is not callable")
        return func(*args, **keywords) if keywords else func(*args)

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
            # Track if loop completed normally (not broken)
            loop_completed = True
            for item in kwargs["iter"]:
                if isinstance(kwargs["target"], str):
                    self.env.set(kwargs["target"], item)
                else:
                    raise NotImplementedError(
                        "Only simple variable targets are supported in for loops"
                    )
                for stmt in kwargs["body"]:
                    self.visit(stmt)

            # Execute else clause if loop completed normally and else clause exists
            if loop_completed and kwargs.get("orelse"):
                for stmt in kwargs["orelse"]:
                    self.visit(stmt)

    def process_container(self, container_type: str, elements: List[Any]) -> Any:
        """Handle containers."""
        if container_type == "list":
            return elements
        elif container_type == "module":
            return None  # Module execution is handled by statement processing

    def process_expr(self, value: Any) -> Any:
        """Process expression statements."""
        return value

    # ================== Special Node Handlers ==================

    def visit_Call(self, node: ast.Call) -> Any:
        """Handle method calls and regular function calls."""
        if isinstance(node.func, ast.Attribute):
            # Method call
            obj = self.visit(node.func.value)
            method_name = node.func.attr
            args = [self.visit(arg) for arg in node.args]

            # Special handling for common methods
            if isinstance(obj, list) and method_name == "append" and len(args) == 1:
                obj.append(args[0])
                return None

            method = getattr(obj, method_name)
            return method(*args)
        else:
            # Regular function call
            return super().visit_Call(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        """Handle indexing operations."""
        obj = self.visit(node.value)
        index = self.visit(node.slice)
        return obj[index]

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        """Handle attribute access."""
        obj = self.visit(node.value)
        return getattr(obj, node.attr)

    def visit_Dict(self, node: ast.Dict) -> Dict[Any, Any]:
        """Handle dictionary literals."""
        result = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = self.visit(key_node) if key_node else None
            value = self.visit(value_node)
            result[key] = value
        return result

    def visit_Tuple(self, node: ast.Tuple) -> tuple:
        """Handle tuple literals."""
        return tuple(self.visit(element) for element in node.elts)
