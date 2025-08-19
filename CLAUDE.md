# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Guidelines

**Important**: Minimize creation of new documentation files. Key information should be consolidated into existing files:
- `CLAUDE.md`: Project overview, architecture, and development guidance
- `design.md`: Design decisions and technical specifications (if exists)
- `todo.md`: Future tasks and roadmap items (if exists)

Avoid creating redundant documentation files like `REFACTORING.md`, `SUMMARY.md`, etc. Instead, update relevant sections in the core documentation files.

## Project Overview

Silu is a simple AI programming language implemented in Python. It's an interpreted language that uses Python's AST (Abstract Syntax Tree) module for parsing and execution. The language supports basic programming constructs like variables, arithmetic operations, control flow (if statements, while loops), functions, and built-in types.

## Code Architecture

- `silu/`: Main package directory
  - `__main__.py`: Entry point that delegates to CLI
  - `cli.py`: Unified command-line interface supporting interpretation, IR generation, and symbolic execution
  - `ast_processor.py`: Abstract base class for AST processing with shared functionality
  - `interpreter.py`: Core interpreter that extends BaseASTProcessor for direct execution
  - `ir_generator.py`: IR generator that extends BaseASTProcessor for intermediate representation
  - `symbolic_executor.py`: Symbolic execution engine for path analysis and constraint generation
- `tests/`: Unit tests using pytest
- `demo*.si`: Example Silu programs

## Key Components

1. **CLI (`silu/cli.py`)**: Unified interface supporting interpretation, IR generation, and symbolic execution modes
2. **Base AST Processor (`silu/ast_processor.py`)**:
   - `BaseASTProcessor`: Abstract base class extending `ast.NodeVisitor`
   - Shared AST traversal logic and operator mappings
   - Common validation and utility methods
   - Factory functions for creating processors
3. **Interpreter (`silu/interpreter.py`)**: 
   - `SiluInterpreter`: Main interpreter class that extends `BaseASTProcessor`
   - `Environment`: Manages variable scope and built-in functions
   - `Function`: Represents user-defined functions
4. **IR Generator (`silu/ir_generator.py`)**:
   - `SiluIRGenerator`: Converts AST to intermediate representation tuples
   - Supports advanced Python features and comprehensive syntax coverage
5. **Symbolic Executor (`silu/symbolic_executor.py`)**:
   - `SymbolicExecutor`: Performs symbolic execution of IR programs
   - `SymbolicValue`: Represents symbolic values and expressions
   - `ExecutionPath`: Tracks execution paths with conditions and constraints
   - `PathCondition`: Represents branch conditions for path analysis
6. **Built-in Functions**: print, type, isinstance, int, float, str, bool

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
# Using uv (recommended)
uv sync                # Install dependencies
uv pip install -e .   # Install in development mode

# Using pip (alternative)
pip install -e .       # Install in development mode
```

### Running Tests
```bash
# Using make (recommended)
make test         # Run all tests
make cov          # Run tests with coverage report

# Using uv
uv run pytest tests/

# Using pytest directly
pytest tests/     # Alternative way to run tests
```

### Code Formatting
```bash
make fmt          # Format code with ruff
```

### Running Silu Programs
```bash
# Traditional usage (interpretation)
silu program.si

# Explicit interpretation mode
silu interpret program.si
silu interpret --source "x = 5; print(x)"
silu interpret program.si --debug

# IR generation mode
silu ir program.si                    # Pretty format (default)
silu ir program.si --format json     # JSON format
silu ir program.si --format compact  # Compact format
silu ir program.si --output file.ir  # Save to file
silu ir --source "x = 5"            # From source string

# IR execution mode
silu exec program.ir.json            # Execute IR directly
silu exec --source '("module", (("assign", "x", 42, null),))'
python -m silu exec demo.ir          # Alternative execution method

# Symbolic execution mode (NEW!)
silu symbolic program.si             # Symbolic analysis of Silu program
silu symbolic program.ir.json       # Symbolic analysis of IR
silu symbolic --source "if x > 5: y = 1 else: y = 2"  # Analyze source string
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

## Architecture Design

The system uses a unified AST processing architecture:

### BaseASTProcessor (Abstract Base Class)
- Extends `ast.NodeVisitor` for AST traversal
- Provides shared operator mappings and validation logic
- Defines abstract methods for customizable behavior
- Handles common nodes: Module, Expr, Assign, Name, Constant, BinOp, UnaryOp, BoolOp, Compare, Call, etc.

### SiluInterpreter (Concrete Implementation)
The interpreter works by:
1. Parsing Silu source code into Python AST using `ast.parse()`
2. Extending BaseASTProcessor with execution-specific implementations
3. Managing variable scope through `Environment` objects
4. Supporting function definitions and calls with `Function` objects

### SiluIRGenerator (Concrete Implementation)
The IR generator works by:
1. Extending BaseASTProcessor with IR generation implementations
2. Converting AST nodes to tuple-based intermediate representation
3. Supporting comprehensive Python syntax including advanced features
4. Maintaining structural information without execution

### IRInterpreter (Concrete Implementation)
The IR interpreter works by:
1. Directly executing IR tuples without AST traversal
2. Providing better performance through flatter instruction execution
3. Supporting all language features through IR instruction dispatch
4. Enabling modular architecture for future compiler backends

### SymbolicExecutor (NEW - Concrete Implementation)
The symbolic executor works by:
1. Analyzing IR programs symbolically without concrete values
2. Tracking all possible execution paths through control flow
3. Generating path conditions and constraints for each branch
4. Supporting symbolic values, expressions, and constraint solving

Key AST nodes supported by both processors:
- Basic: Module, Expr, Assign, Name, Constant
- Operations: BinOp, UnaryOp, BoolOp, Compare
- Functions: Call, FunctionDef, Return
- Control Flow: If, While, For
- Containers: List, Dict, Tuple, Subscript, Attribute

## Error Handling

The interpreter implements proper error handling for:
- Undefined variables (NameError)
- Division by zero (ZeroDivisionError)
- Unsupported operations (NotImplementedError)
- Type errors (TypeError)
- Value errors (ValueError)

## Recent Implementations (Completed)

### Symbolic Execution Engine Implementation ✅ (Latest)
Successfully implemented a complete symbolic execution engine with the following features:
- **Path Analysis**: Generates all possible execution paths through control flow
- **Constraint Generation**: Creates path conditions for each branch decision
- **Symbolic Values**: Supports symbolic variables and expressions
- **Branch Coverage**: Analyzes if/else statements, while loops, and function calls
- **Report Generation**: Provides comprehensive analysis reports in JSON format

### IR Interpreter Implementation ✅
Successfully implemented a complete IR interpreter with the following features:
- **Direct IR Execution**: Can execute IR tuples without AST interpretation
- **Complete Language Support**: All Silu features work through IR execution
- **Performance Benefits**: Faster execution through flatter instruction execution
- **Modular Architecture**: Clean separation between IR generation and execution

### Architecture Refactoring (Previously Completed) ✅
The codebase was refactored to eliminate code duplication:
- **Code Deduplication**: Removed ~60 lines of duplicate AST traversal logic
- **Unified Architecture**: Single base class for all AST processing
- **Improved Maintainability**: Shared logic only needs updates in one place
- **Enhanced Extensibility**: Easy to add new processors (compiler, optimizer, etc.)
- **Consistent Behavior**: All modes handle syntax identically

### Development Environment
- **Package Manager**: Using `uv` for fast dependency management and virtual environment handling
- **Testing**: Comprehensive test suite with 175+ passing tests
- **CLI**: Unified command-line interface supporting interpret, ir, and exec modes

## Demo Programs

The repository includes comprehensive demo programs:
- `demo.si`: Consolidated demo showcasing all core language features including variables, arithmetic, control flow, functions, type conversion, lambda expressions, and loop control
- `symbolic_demo.si`: Demonstrates various control flow patterns for symbolic execution analysis

Example usage:
```bash
# Run the demo (interpretation)
silu demo.si

# Generate IR for the demo
silu ir demo.si --format json

# Save demo IR to file and execute it
silu ir demo.si --output demo.ir --format json
silu exec demo.ir

# Symbolic execution analysis
silu symbolic demo.si
silu symbolic symbolic_demo.si

# Compare performance (interpretation vs IR execution)
time silu interpret demo.si
time python -m silu exec demo.ir
```