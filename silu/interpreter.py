"""
Silu Interpreter Module

This module provides the main interpreter implementation that extends BaseASTProcessor
for direct execution of Silu programs.
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
        # Create a new environment for the function execution
        func_env = Environment(parent=self.env)

        # Bind arguments to their values
        for arg, value in zip(self.args, args):
            func_env.set(arg, value)

        # Create a new interpreter instance for the function execution
        interpreter = SiluInterpreter(env=func_env)

        # Execute the function body
        try:
            for stmt in self.body:
                interpreter.visit(stmt)
        except ReturnException as ret:
            return ret.value

        # Implicit return None if no explicit return statement
        return None


class Environment:
    """Manages variable and function storage."""

    def __init__(self, parent: Optional["Environment"] = None):
        self.vars: Dict[str, Any] = {}
        self.parent = parent
        # Add built-in functions and types
        if parent is None:  # Only add built-ins to the global environment
            self.vars["print"] = self._print
            self.vars["type"] = self._type
            self.vars["isinstance"] = self._isinstance

            # Type conversion functions
            self.vars["int"] = self._int
            self.vars["float"] = self._float
            self.vars["str"] = self._str
            self.vars["bool"] = self._bool

            # Built-in types
            self.vars["list"] = self._list
            self.vars["range"] = range

    def _list(self, iterable=None) -> list:
        """Built-in list function."""
        if iterable is None:
            return []
        return list(iterable)

    def _print(self, *args) -> None:
        """Built-in print function."""
        print(*args)

    def _type(self, obj) -> type:
        """Built-in type function."""
        return type(obj)

    def _isinstance(self, obj, cls) -> bool:
        """Built-in isinstance function."""
        type_map = {"int": int, "float": float, "str": str, "bool": bool}
        if cls in type_map.values():
            return isinstance(obj, cls)
        if hasattr(cls, "__name__") and cls.__name__ in type_map:
            return isinstance(obj, type_map[cls.__name__])
        raise NotImplementedError(f"isinstance not implemented for {cls}")

    def _int(self, value=None) -> int:
        """Built-in int function."""
        if value is None:
            return 0
        return int(value)

    def _float(self, value=None) -> float:
        """Built-in float function."""
        if value is None:
            return 0.0
        return float(value)

    def _str(self, value=None) -> str:
        """Built-in str function."""
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return str(type(value).__name__)

    def _bool(self, value=None) -> bool:
        """Built-in bool function."""
        if value is None:
            return False
        return bool(value)

    def get(self, name: str) -> Any:
        """Get the value of a variable or function."""
        if name in self.vars:
            return self.vars[name]
        if self.parent:
            return self.parent.get(name)
        raise NameError(f"Name '{name}' is not defined")

    def set(self, name: str, value: Any) -> None:
        """Set the value of a variable."""
        self.vars[name] = value


class SiluInterpreter(BaseASTProcessor):
    """A Silu interpreter that executes code directly."""

    def __init__(self, env: Optional[Environment] = None):
        super().__init__()
        self.env = env if env is not None else Environment()

    # ================== Implementation of Abstract Methods ==================

    def process_module(self, statements: List[Any]) -> None:
        """Process a module - statements are already executed during traversal."""
        return None

    def process_assign(self, target: Any, value: Any) -> None:
        """Process an assignment by setting the variable in the environment."""
        if isinstance(target, str):
            self.env.set(target, value)
        else:
            raise NotImplementedError("Only simple variable assignments are supported")

    def process_name(self, name: str, context: ast.AST) -> Any:
        """Process a name by looking it up in the environment or returning the name."""
        if isinstance(context, ast.Load):
            return self.env.get(name)
        elif isinstance(context, ast.Store):
            return name
        else:
            raise NotImplementedError(f"Unsupported context for name: {type(context)}")

    def process_constant(self, value: Any) -> Any:
        """Process a constant by returning its value."""
        return value

    def process_binop(self, op: str, left: Any, right: Any) -> Any:
        """Process a binary operation by applying the operator."""
        # Check for division by zero operations
        if op in ("/", "//", "%") and right == 0:
            if op == "%":
                raise ZeroDivisionError("Modulo by zero")
            raise ZeroDivisionError("Division by zero")

        # Apply the operation
        operations = {
            "+": lambda left, right: left + right,
            "-": lambda left, right: left - right,
            "*": lambda left, right: left * right,
            "/": lambda left, right: left / right,
            "//": lambda left, right: left // right,
            "%": lambda left, right: left % right,
            "**": lambda left, right: left**right,
        }

        if op in operations:
            return operations[op](left, right)
        else:
            raise NotImplementedError(f"Unsupported binary operator: {op}")

    def process_unaryop(self, op: str, operand: Any) -> Any:
        """Process a unary operation by applying the operator."""
        operations = {
            "+": lambda x: +x,
            "-": lambda x: -x,
            "not": lambda x: not x,
        }

        if op in operations:
            return operations[op](operand)
        else:
            raise NotImplementedError(f"Unsupported unary operator: {op}")

    def process_boolop(self, op: str, values: List[Any]) -> Any:
        """Process a boolean operation with short-circuit evaluation."""
        if op == "and":
            for value in values:
                if not value:
                    return False
            return True
        elif op == "or":
            for value in values:
                if value:
                    return True
            return False
        else:
            raise NotImplementedError(f"Unsupported boolean operator: {op}")

    def process_compare(self, left: Any, ops: List[str], comparators: List[Any]) -> Any:
        """Process comparison operations with support for chained comparisons."""
        if len(comparators) != len(ops):
            raise ValueError("Mismatch between comparators and operators")

        operations = {
            "==": lambda left, right: left == right,
            "!=": lambda left, right: left != right,
            "<": lambda left, right: left < right,
            "<=": lambda left, right: left <= right,
            ">": lambda left, right: left > right,
            ">=": lambda left, right: left >= right,
        }

        # For chained comparisons, we need to evaluate each pair
        for i, (comparator, op) in enumerate(zip(comparators, ops)):
            # For chained comparisons, the right side of one comparison
            # becomes the left side of the next
            left_val = left if i == 0 else comparators[i - 1]

            # Apply the comparison operation
            if op not in operations:
                raise NotImplementedError(f"Unsupported comparison operator: {op}")

            result = operations[op](left_val, comparator)
            if not result:  # Short-circuit evaluation
                return False

        return True

    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Any:
        """Process a function call by invoking the function."""
        if isinstance(func, Function):
            return func(*args)
        elif callable(func):
            return func(*args)
        else:
            raise TypeError(f"'{type(func).__name__}' object is not callable")

    def process_functiondef(self, name: str, args: List[str], body: List[Any]) -> None:
        """This is not used - we override visit_FunctionDef instead."""
        pass

    def process_return(self, value: Any) -> Any:
        """Process a return statement by raising a ReturnException."""
        raise ReturnException(value if value is not None else None)

    def process_if(self, test: Any, body: List[Any], orelse: List[Any]) -> None:
        """This is not used - we override visit_If instead."""
        pass

    def process_while(self, test: Any, body: List[Any]) -> None:
        """This is not used - we override visit_While instead."""
        pass

    def process_for(self, target: Any, iter_: Any, body: List[Any]) -> None:
        """This is not used - we override visit_For instead."""
        pass

    def process_list(self, elements: List[Any]) -> List[Any]:
        """Process a list literal by returning the list of elements."""
        return elements

    def process_expr(self, value: Any) -> Any:
        """Process an expression statement by returning the value."""
        return value

    # ================== Override specific visit methods for proper execution ==================

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a function definition node."""
        name = node.name
        args = [arg.arg for arg in node.args.args]
        body = node.body  # Keep original AST nodes
        func = Function(name, args, body, self.env)
        self.env.set(name, func)

    def visit_Return(self, node: ast.Return) -> None:
        """Visit a return statement node."""
        value = self.visit(node.value) if node.value else None
        raise ReturnException(value)

    def visit_If(self, node: ast.If) -> None:
        """Visit an if statement node."""
        condition = self.visit(node.test)
        if condition:
            for stmt in node.body:
                self.visit(stmt)
        elif node.orelse:
            for stmt in node.orelse:
                self.visit(stmt)

    def visit_While(self, node: ast.While) -> None:
        """Visit a while loop node."""
        while self.visit(node.test):
            for stmt in node.body:
                self.visit(stmt)

    def visit_For(self, node: ast.For) -> None:
        """Visit a for loop node."""
        iterable = self.visit(node.iter)
        for item in iterable:
            if isinstance(node.target, ast.Name):
                self.env.set(node.target.id, item)
            else:
                raise NotImplementedError(
                    "Only simple variable targets are supported in for loops"
                )

            for stmt in node.body:
                self.visit(stmt)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        """Visit an attribute access node."""
        obj = self.visit(node.value)
        return getattr(obj, node.attr)

    def visit_Call(self, node: ast.Call) -> Any:
        """Visit a function call node with special handling for method calls."""
        # Special handling for methods on built-in types
        if isinstance(node.func, ast.Attribute):
            # Get the object that the method is being called on
            obj = self.visit(node.func.value)
            method_name = node.func.attr

            # Evaluate all arguments
            args = [self.visit(arg) for arg in node.args]

            # Handle list methods
            if isinstance(obj, list) and method_name == "append":
                if len(args) == 1:
                    obj.append(args[0])
                    return None  # append() returns None
                else:
                    raise TypeError(
                        f"append() takes exactly one argument ({len(args)} given)"
                    )

            # For other methods, get the method and call it
            method = getattr(obj, method_name)
            return method(*args)
        else:
            # Regular function call - use the base class implementation
            return super().visit_Call(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        """Visit a subscript node for indexing."""
        obj = self.visit(node.value)
        index = self.visit(node.slice)
        return obj[index]

    def visit_Dict(self, node: ast.Dict) -> Dict[Any, Any]:
        """Visit a dictionary literal node."""
        result = {}
        for key_node, value_node in zip(node.keys, node.values):
            key = self.visit(key_node) if key_node else None
            value = self.visit(value_node)
            result[key] = value
        return result

    def visit_Tuple(self, node: ast.Tuple) -> tuple:
        """Visit a tuple literal node."""
        elements = [self.visit(element) for element in node.elts]
        return tuple(elements)


def main() -> None:
    """Entry point for the Silu interpreter."""
    print("Hello from Silu!")


if __name__ == "__main__":
    main()
