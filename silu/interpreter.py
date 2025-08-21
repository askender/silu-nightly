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


class BreakException(Exception):
    """Exception used to handle break statements in loops."""

    pass


class ContinueException(Exception):
    """Exception used to handle continue statements in loops."""

    pass


class LambdaFunction:
    """Represents a lambda function."""

    def __init__(self, params: List[str], body_node: ast.AST, env: "Environment"):
        self.params = params
        self.body_node = body_node
        self.env = env

    def __call__(self, *args):
        if len(args) != len(self.params):
            raise TypeError(
                f"Lambda takes {len(self.params)} arguments but {len(args)} were given"
            )

        # Create lambda environment with parameter bindings
        lambda_env = Environment(parent=self.env)
        for param, value in zip(self.params, args):
            lambda_env.set(param, value)

        # Evaluate lambda body
        interpreter = SiluInterpreter(env=lambda_env)
        return interpreter.visit(self.body_node)


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
        self.vars.update(
            {
                "print": lambda *args: print(*args),
                "type": type,
                "isinstance": self._isinstance,
                "int": int,
                "float": float,
                "str": str,
                "bool": bool,
                "list": list,
                "dict": dict,
                "len": len,
                "range": range,
                "int_type": int,
                "float_type": float,
                "str_type": str,
                "bool_type": bool,
                "MemoryError": MemoryError,
            }
        )

    def _isinstance(self, obj, cls) -> bool:
        """Built-in isinstance with type name support."""
        type_map = {"int": int, "float": float, "str": str, "bool": bool}

        # If cls is already a type object, use it directly
        if cls in type_map.values():
            return isinstance(obj, cls)

        # If cls has a name that's in our type map, use the mapped type
        if hasattr(cls, "__name__") and cls.__name__ in type_map:
            actual_type = type_map[cls.__name__]
            return isinstance(obj, actual_type)

        # For other cases, try direct isinstance
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

    def process_aug_assign(self, target: Any, op: str, value: Any) -> None:
        """Process augmented assignment operations (+=, -=, etc.)."""
        if isinstance(target, str):
            # Simple variable augmented assignment: x += value
            # target is variable name string (for interpreter)
            current_value = self.env.get(target)
            new_value = self.process_operation(op, current_value, value)
            self.env.set(target, new_value)
        elif isinstance(target, tuple) and len(target) == 2:
            # Subscript augmented assignment: obj[key] += value
            obj, key = target
            current_value = obj[key]
            new_value = self.process_operation(op, current_value, value)
            self.process_subscript_assign(obj, key, new_value)
        else:
            raise NotImplementedError(f"Unsupported augmented assignment target: {target}")

    def process_subscript_assign(self, obj: Any, key: Any, value: Any) -> None:
        """Handle subscript assignment (e.g., dict[key] = value)."""
        if isinstance(obj, dict):
            obj[key] = value
        elif isinstance(obj, list):
            if not isinstance(key, int):
                raise TypeError("list indices must be integers")
            if key < 0:
                key = len(obj) + key
            if key < 0 or key >= len(obj):
                raise IndexError("list index out of range")
            obj[key] = value
        else:
            raise TypeError(
                f"'{type(obj).__name__}' object does not support item assignment"
            )

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
            "+": lambda left, r: left + r,
            "-": lambda left, r: left - r,
            "*": lambda left, r: left * r,
            "/": lambda left, r: left / r,
            "//": lambda left, r: left // r,
            "%": lambda left, r: left % r,
            "**": lambda left, r: left**r,
        }
        comp_ops = {
            "==": lambda left, r: left == r,
            "!=": lambda left, r: left != r,
            "<": lambda left, r: left < r,
            "<=": lambda left, r: left <= r,
            ">": lambda left, r: left > r,
            ">=": lambda left, r: left >= r,
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
                    raise NotImplementedError(
                        f"Unsupported comparison operator: {op_str}"
                    )
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

        # Memory protection for potentially dangerous function calls
        if hasattr(func, '__name__'):
            func_name = func.__name__
        elif hasattr(func, '__class__') and hasattr(func.__class__, '__name__'):
            func_name = func.__class__.__name__
        else:
            func_name = str(func)

        # Protect against large range() calls
        if func_name == 'range' and args:
            if len(args) >= 1 and isinstance(args[0], int) and args[0] > 10000000:
                raise MemoryError(f"Memory protection: range({args[0]}) exceeds limit (10,000,000)")
            elif len(args) >= 2 and isinstance(args[1], int) and args[1] > 10000000:
                raise MemoryError(f"Memory protection: range(..., {args[1]}) exceeds limit (10,000,000)")

        # Protect against extend() with large iterables
        if func_name == 'extend' and args:
            # Check if the argument is a range or large iterable
            if len(args) >= 1:
                arg = args[0]
                if hasattr(arg, '__len__'):
                    try:
                        length = len(arg)
                        if length > 10000000:
                            raise MemoryError(f"Memory protection: extend() with {length} elements exceeds limit (10,000,000)")
                    except (TypeError, OverflowError):
                        # Some iterables like range might not have a reliable len()
                        # Check if it's a range with large values
                        if hasattr(arg, 'start') and hasattr(arg, 'stop'):
                            size = abs(arg.stop - arg.start)
                            if size > 10000000:
                                raise MemoryError(f"Memory protection: extend() with range of {size} elements exceeds limit (10,000,000)")

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
            try:
                while self.visit(kwargs["test_node"]):
                    try:
                        for stmt in kwargs["body"]:
                            self.visit(stmt)
                    except ContinueException:
                        continue
                    except BreakException:
                        break
            except BreakException:
                pass
        elif node_type == "for":
            if not isinstance(kwargs["target"], str):
                raise NotImplementedError(
                    "Only simple variable targets are supported in for loops"
                )
            try:
                for item in kwargs["iter"]:
                    self.env.set(kwargs["target"], item)
                    try:
                        for stmt in kwargs["body"]:
                            self.visit(stmt)
                    except ContinueException:
                        continue
                    except BreakException:
                        break
                else:
                    # Execute else clause if loop completed normally (no break)
                    if kwargs.get("orelse"):
                        for stmt in kwargs["orelse"]:
                            self.visit(stmt)
            except BreakException:
                pass

    def process_container(self, container_type: str, elements: List[Any]) -> Any:
        """Handle containers."""
        containers = {
            "list": lambda e: e,
            "tuple": lambda e: tuple(e),
            "dict": lambda e: {k: v for k, v in e},
            "module": lambda e: None,
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

    def process_break_continue(self, statement_type: str) -> Any:
        """Process break/continue statements."""
        if statement_type == "break":
            raise BreakException()
        elif statement_type == "continue":
            raise ContinueException()
        else:
            raise NotImplementedError(f"Unsupported statement type: {statement_type}")

    def process_assert(self, test: Any, msg: Any = None) -> Any:
        """Process assert statements."""
        if not test:
            if msg is not None:
                raise AssertionError(str(msg))
            else:
                raise AssertionError()
        return None

    def process_ann_assign(self, target: str, value: Any, annotation: Any) -> Any:
        """Process annotated assignment."""
        # For now, we ignore the annotation and just do the assignment
        # In a future version, we could use annotations for type checking
        if value is not None:
            self.env.set(target, value)
        # If no value is provided, we could initialize with a default based on annotation
        # but for simplicity, we'll just skip for now
        return None

    def process_lambda(self, params: List[str], body_node: ast.AST) -> Any:
        """Process lambda function."""
        return LambdaFunction(params, body_node, self.env)

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

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        """Handle conditional expressions (ternary operator): value if test else other_value"""
        test_result = self.visit(node.test)
        if test_result:
            return self.visit(node.body)
        else:
            return self.visit(node.orelse)
