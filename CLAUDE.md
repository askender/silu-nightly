# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Guidelines

**Important**: Minimize creation of new documentation files. Key information should be consolidated into existing files:
- `CLAUDE.md`: Project overview and development guidance for AI assistants
- `README.md`: User-facing project introduction and quick start
- `docs/`: Detailed technical documentation
- `design.md`: Design decisions and technical specifications (if exists)
- `todo.md`: Future tasks and roadmap items (if exists)

Avoid creating redundant documentation files like `REFACTORING.md`, `SUMMARY.md`, etc. Instead, update relevant sections in the core documentation files.

## Project Overview

Silu is a simple AI programming language implemented in Python. It's an interpreted language that uses Python's AST (Abstract Syntax Tree) module for parsing and execution. The language supports basic programming constructs like variables, arithmetic operations, control flow, functions, and built-in types.

## Code Architecture

```
silu/
├── __main__.py          # Entry point that delegates to CLI
├── cli.py              # Unified command-line interface
├── ast_processor.py    # Abstract base class for AST processing
├── interpreter.py      # Core interpreter (extends BaseASTProcessor)
├── ir_generator.py     # IR generator (extends BaseASTProcessor)
└── symbolic_executor.py # Symbolic execution engine
```

## Key Components

1. **CLI (`cli.py`)**: Unified interface supporting interpretation, IR generation, and symbolic execution modes
2. **BaseASTProcessor (`ast_processor.py`)**: Abstract base class with shared AST traversal logic
3. **SiluInterpreter (`interpreter.py`)**: Main interpreter with Environment and Function classes
4. **SiluIRGenerator (`ir_generator.py`)**: Converts AST to intermediate representation
5. **SymbolicExecutor (`symbolic_executor.py`)**: Performs symbolic program analysis

## Common Development Commands

```bash
# Development setup
uv sync && uv pip install -e .

# Testing
make test              # Run all tests
make cov               # Tests with coverage

# Code quality
make fmt               # Format with ruff

# Running Silu programs
silu program.si                    # Default interpretation
silu interpret program.si --debug # Debug mode
silu ir program.si --format json  # Generate IR
silu exec program.ir.json         # Execute IR
silu symbolic program.si          # Symbolic analysis
```

## Language Features Summary

- **Data Types**: int, float, str, bool, list
- **Operations**: Arithmetic, boolean, comparison (including chained)
- **Control Flow**: if/elif/else, while/for loops
- **Functions**: User-defined with parameters and return values
- **Built-ins**: print, type, isinstance, type conversions

## Documentation Structure

- **README.md**: Quick start and basic usage
- **docs/language_features.md**: Complete syntax reference with examples
- **docs/cli_usage.md**: Detailed command-line interface guide
- **docs/development.md**: Setup, testing, and contribution guidelines
- **docs/interpreter_spec.md**: Core implementation details
- **docs/symbolic_execution.md**: Program analysis capabilities
- **docs/simple_ir_design.md**: Intermediate representation format

## Development Notes

- Uses unified AST processing architecture to avoid code duplication
- Comprehensive test suite with 175+ tests using pytest
- Supports multiple execution modes (interpret, IR generation/execution, symbolic analysis)
- Package management with `uv` (recommended) or `pip`
- Code formatting with `ruff`
