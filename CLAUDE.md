# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Silu is a simple AI programming language implemented in Python. It's an interpreted language that uses Python's AST (Abstract Syntax Tree) module for parsing and execution. The language supports basic programming constructs like variables, arithmetic operations, control flow (if statements, while loops), functions, and built-in types.

## Code Architecture

- `silu/`: Main package directory
  - `__main__.py`: Entry point that delegates to CLI
  - `cli.py`: Command-line interface that parses `.si` files and executes them
  - `interpreter.py`: Core interpreter that visits AST nodes and executes code
- `tests/`: Unit tests using pytest
- `demo*.si`: Example Silu programs

## Key Components

1. **CLI (`silu/cli.py`)**: Handles command-line arguments and file execution
2. **Interpreter (`silu/interpreter.py`)**: 
   - `SiluInterpreter`: Main interpreter class that extends `ast.NodeVisitor`
   - `Environment`: Manages variable scope and built-in functions
   - `Function`: Represents user-defined functions
3. **Built-in Functions**: print, type, isinstance, int, float, str, bool

## Language Features

Silu supports the following programming constructs:

1. **Variables and Assignments**: `x = 10`
2. **Arithmetic Operations**: `+`, `-`, `*`, `/`, `//`, `%`, `**`
3. **Unary Operations**: `+`, `-`, `not`
4. **Boolean Operations**: `and`, `or`
5. **Comparison Operations**: `==`, `!=`, `<`, `<=`, `>`, `>=`
6. **Chained Comparisons**: `3 < 5 < 7`
7. **Control Flow**: 
   - If statements with elif and else clauses
   - While loops
   - For loops with range() and lists
8. **Functions**: 
   - Function definitions with parameters
   - Return statements
   - Function calls
9. **Built-in Types**: int, float, str, bool
10. **Type Conversion**: int(), float(), str(), bool()
11. **Type Checking**: isinstance(), type()

## Common Development Tasks

### Building and Installing
```bash
pip install -e .  # Install in development mode
```

### Running Tests
```bash
make test         # Run all tests
make cov          # Run tests with coverage report
pytest tests/     # Alternative way to run tests
```

### Code Formatting
```bash
make fmt          # Format code with ruff
```

### Running Silu Programs
```bash
silu program.si   # Execute a Silu program
```

### Cleaning
```bash
make rm           # Remove cache files
```

## Testing Structure

Tests are written using pytest and organized by component:
- `test_interpreter.py`: Core interpreter functionality
- `test_cli.py`: Command-line interface tests
- `test_main.py`: Main module tests

Tests cover:
- AST node visiting
- Built-in functions
- Control flow
- Error handling
- End-to-end program execution

## Interpreter Design

The interpreter works by:
1. Parsing Silu source code into Python AST using `ast.parse()`
2. Visiting each AST node with custom handlers in `SiluInterpreter`
3. Managing variable scope through `Environment` objects
4. Supporting function definitions and calls with `Function` objects

Key AST nodes supported:
- Module, Expr, Assign, Name, Constant
- BinOp, UnaryOp, BoolOp, Compare
- Call, FunctionDef, Return
- If, While

## Error Handling

The interpreter implements proper error handling for:
- Undefined variables (NameError)
- Division by zero (ZeroDivisionError)
- Unsupported operations (NotImplementedError)
- Type errors (TypeError)
- Value errors (ValueError)

## Demo Programs

The repository includes several demo programs that showcase language features:
- `demo.si`: Comprehensive demo of basic operations
- `demo_control_flow.si`: If statements and while loops
- `demo_functions.si`: Function definitions and calls
- `demo_types.si`: Data types and type conversion