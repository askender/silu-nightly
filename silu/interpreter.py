"""
Silu Interpreter Module
"""

import ast
from typing import Any, Dict, List, Optional


class Function:
    """Represents a user-defined function."""

    def __init__(
        self, name: str, args: List[ast.arg], body: List[ast.stmt], env: "Environment"
    ):
        self.name = name
        self.args = args
        self.body = body
        self.env = env

    def __call__(self, *args):
        # Create a new environment for the function execution
        # with the function's environment as parent
        func_env = Environment(parent=self.env)

        # Bind arguments to their values
        for arg, value in zip(self.args, args):
            func_env.set(arg.arg, value)

        # Create a new interpreter instance for the function execution
        interpreter = SiluInterpreter(env=func_env)

        # Execute the function body
        for stmt in self.body:
            if isinstance(stmt, ast.Return):
                return interpreter.visit(stmt)
            interpreter.visit(stmt)
        
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

            # Type objects
            self.vars["int_type"] = int
            self.vars["float_type"] = float
            self.vars["str_type"] = str
            self.vars["bool_type"] = bool

    def _print(self, *args) -> None:
        """Built-in print function."""
        print(*args)

    def _type(self, obj) -> type:
        """Built-in type function."""
        return type(obj)

    def _isinstance(self, obj, cls) -> bool:
        """Built-in isinstance function."""
        # Handle direct type objects
        if cls is int:
            return isinstance(obj, int)
        elif cls is float:
            return isinstance(obj, float)
        elif cls is str:
            return isinstance(obj, str)
        elif cls is bool:
            return isinstance(obj, bool)
        
        # Handle type objects referenced by name from vars
        if hasattr(cls, "__name__"):
            cls_name = cls.__name__
            if cls_name == "int":
                return isinstance(obj, int)
            elif cls_name == "float":
                return isinstance(obj, float)
            elif cls_name == "str":
                return isinstance(obj, str)
            elif cls_name == "bool":
                return isinstance(obj, bool)
        
        raise NotImplementedError(f"isinstance not implemented for {cls}")

    def _int(self, value=None) -> int:
        """Built-in int function."""
        if value is None:
            return 0
        elif isinstance(value, bool):
            return int(value)
        elif isinstance(value, int):
            return value
        elif isinstance(value, float):
            return int(value)
        elif isinstance(value, str):
            return int(value)
        else:
            raise NotImplementedError(f"int() not implemented for {type(value)}")

    def _float(self, value=None) -> float:
        """Built-in float function."""
        if value is None:
            return 0.0
        elif isinstance(value, bool):
            return float(value)
        elif isinstance(value, float):
            return value
        elif isinstance(value, int):
            return float(value)
        elif isinstance(value, str):
            return float(value)
        else:
            raise NotImplementedError(f"float() not implemented for {type(value)}")

    def _str(self, value=None) -> str:
        """Built-in str function."""
        if value is None:
            return ""
        return str(value)

    def _bool(self, value=None) -> bool:
        """Built-in bool function."""
        if value is None:
            return False
        return bool(value)

    def get(self, name: str) -> Any:
        """
        Get the value of a variable or function.
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
    """A simple interpreter for a subset of Python syntax."""

    def __init__(self, env: Optional[Environment] = None):
        self.env = env if env is not None else Environment()

    def visit_Module(self, node: ast.Module) -> None:
        """Visit the root module node and execute its statements."""
        for stmt in node.body:
            self.visit(stmt)

    def visit_Expr(self, node: ast.Expr) -> Any:
        """Visit an expression node."""
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

        # Map operators to their corresponding operations
        operators = {
            ast.Add: lambda x, y: x + y,
            ast.Sub: lambda x, y: x - y,
            ast.Mult: lambda x, y: x * y,
            ast.Div: lambda x, y: x / y,
            ast.FloorDiv: lambda x, y: x // y,
            ast.Mod: lambda x, y: x % y,
            ast.Pow: lambda x, y: x ** y,
        }

        if type(node.op) in operators:
            return operators[type(node.op)](left, right)

        raise NotImplementedError(f"Unsupported binary operator: {type(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """
        Visit a unary operation node.
        """
        operand = self.visit(node.operand)

        # Map operators to their corresponding operations
        operators = {
            ast.UAdd: lambda x: +x,
            ast.USub: lambda x: -x,
            ast.Not: lambda x: not x,
        }

        if type(node.op) in operators:
            return operators[type(node.op)](operand)

        raise NotImplementedError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """
        Visit a boolean operation node.
        """
        values = [self.visit(value) for value in node.values]

        # Handle short-circuit evaluation
        if isinstance(node.op, ast.And):
            for value in values:
                if not value:
                    return False
            return True
            
        if isinstance(node.op, ast.Or):
            for value in values:
                if value:
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

        # Map operators to their corresponding operations
        operator_map = {
            ast.Eq: lambda x, y: x == y,
            ast.NotEq: lambda x, y: x != y,
            ast.Lt: lambda x, y: x < y,
            ast.LtE: lambda x, y: x <= y,
            ast.Gt: lambda x, y: x > y,
            ast.GtE: lambda x, y: x >= y,
        }

        # For chained comparisons, we need to evaluate each pair
        for i, (comparator, op) in enumerate(zip(comparators, ops)):
            # For chained comparisons, the right side of one comparison
            # becomes the left side of the next
            left_val = left if i == 0 else comparators[i - 1]

            # Apply the comparison operation
            if type(op) not in operator_map:
                raise NotImplementedError(f"Unsupported comparison operator: {type(op)}")
            
            result = operator_map[type(op)](left_val, comparator)
            
            if not result:  # Short-circuit evaluation
                return False

        return True

    def visit_Call(self, node: ast.Call) -> Any:
        """
        Visit a function call node.
        """
        # Get the function object
        func = self.visit(node.func)

        # Evaluate all arguments
        args = [self.visit(arg) for arg in node.args]

        # Call the function
        if isinstance(func, Function):
            return func(*args)
        elif callable(func):
            return func(*args)
        else:
            raise TypeError(f"'{type(func).__name__}' object is not callable")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """
        Visit a function definition node.
        """
        # Create a Function object
        func = Function(node.name, node.args.args, node.body, self.env)

        # Store the function in the environment
        self.env.set(node.name, func)

    def visit_Return(self, node: ast.Return) -> Any:
        """
        Visit a return statement node.
        """
        if node.value:
            return self.visit(node.value)
        return None

    def visit_If(self, node: ast.If) -> None:
        """
        Visit an if statement node.
        """
        # Evaluate the condition
        condition = self.visit(node.test)

        # Execute the appropriate block
        block = node.body if condition else node.orelse
        for stmt in block:
            self.visit(stmt)

    def visit_While(self, node: ast.While) -> None:
        """
        Visit a while loop node.
        """
        # While the condition is true, execute the body
        while self.visit(node.test):
            for stmt in node.body:
                self.visit(stmt)


def main() -> None:
    """
    Entry point for the Silu interpreter.
    """
    print("Hello from Silu!")


if __name__ == "__main__":
    main()
