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
├── ir_interpreter.py   # IR interpreter for executing IR directly
├── ir_to_source.py     # IR to source code converter
├── ir_utils.py         # Shared IR utilities (parsing, validation, analysis)
├── silu_ir_to_llvm.py  # IR to LLVM-IR converter
└── symbolic_executor.py # Symbolic execution engine
```

## Key Components

1. **CLI (`cli.py`)**: Unified interface supporting interpretation, IR generation, IR-to-source conversion, and symbolic execution modes
2. **BaseASTProcessor (`ast_processor.py`)**: Abstract base class with shared AST traversal logic
3. **SiluInterpreter (`interpreter.py`)**: Main interpreter with Environment and Function classes
4. **SiluIRGenerator (`ir_generator.py`)**: Converts AST to intermediate representation
5. **IRInterpreter (`ir_interpreter.py`)**: Directly executes IR without AST conversion
6. **IRToSourceConverter (`ir_to_source.py`)**: Converts IR back to readable source code with shared conversion utilities
7. **SymbolicExecutor (`symbolic_executor.py`)**: Enhanced symbolic program analysis with Z3 constraint generation and precise loop handling
8. **IRUtils (`ir_utils.py`)**: Shared utilities for IR processing (JSON parsing, validation, analysis)
9. **SiluToLLVMConverter (`silu_ir_to_llvm.py`)**: Converts Silu IR to LLVM-IR format

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
silu check program.py             # Check Python compatibility
silu interpret program.si --debug # Debug mode
silu ir program.si --format json  # Generate IR
silu exec program.ir.json         # Execute IR
silu to-source program.ir.json    # Convert IR back to source
silu symbolic program.si          # Symbolic analysis
```
