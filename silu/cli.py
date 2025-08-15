#!/usr/bin/env python3
"""
Command line interface for the Silu interpreter.
"""

import sys
import ast
from silu.interpreter import SiluInterpreter


def main():
    """Main entry point for the Silu interpreter."""
    if len(sys.argv) != 2:
        print("Usage: silu <file.si>")
        sys.exit(1)

    filename = sys.argv[1]

    try:
        # Read the Silu source file
        with open(filename, "r") as f:
            code = f.read()

        # Parse and execute the code
        tree = ast.parse(code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)

    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error executing '{filename}': {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
