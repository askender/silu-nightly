#!/usr/bin/env python3
"""
Script to execute the test.si file with the Silu interpreter.
"""

import ast
from silu.interpreter import SiluInterpreter


def execute_test_file():
    """Execute the test.si file."""
    # Read the test file
    with open("test.si", "r") as f:
        code = f.read()

    # Parse and execute the code
    tree = ast.parse(code)
    interpreter = SiluInterpreter()
    interpreter.visit(tree)


if __name__ == "__main__":
    execute_test_file()
