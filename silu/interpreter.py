"""
Silu Interpreter Module
"""

import ast
import sys
from typing import Any, Dict, List, Optional


class Environment:
    """
    Manages variable and function storage.
    For simplicity, starts with a single global environment.
    Can be extended to support nested scopes later.
    """
    def __init__(self, parent: Optional['Environment'] = None):
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


def main() -> None:
    """
    Entry point for the Silu interpreter.
    Currently just prints a greeting.
    """
    print("Hello from Silu!")


if __name__ == "__main__":
    main()