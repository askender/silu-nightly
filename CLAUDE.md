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
├── ir_to_source.py     # IR to source code converter
└── symbolic_executor.py # Symbolic execution engine
```

## Key Components

1. **CLI (`cli.py`)**: Unified interface supporting interpretation, IR generation, IR-to-source conversion, and symbolic execution modes
2. **BaseASTProcessor (`ast_processor.py`)**: Abstract base class with shared AST traversal logic
3. **SiluInterpreter (`interpreter.py`)**: Main interpreter with Environment and Function classes
4. **SiluIRGenerator (`ir_generator.py`)**: Converts AST to intermediate representation
5. **IRToSourceConverter (`ir_to_source.py`)**: Converts IR back to readable source code with shared conversion utilities
6. **SymbolicExecutor (`symbolic_executor.py`)**: Enhanced symbolic program analysis with Z3 constraint generation and precise loop handling

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

## Language Features Summary

- **Data Types**: int, float, str, bool, bytes, list
- **Operations**: Arithmetic, boolean, comparison (including chained)
- **Control Flow**: if/elif/else, while/for loops
- **Assignment**: Simple assignment, multiple target assignment (a = b = 1), tuple unpacking
- **Functions**: User-defined with parameters and return values, closures
- **Built-ins**: print, type, isinstance, type conversions

## Documentation Structure

- **README.md**: Quick start and basic usage
- **docs/language_features.md**: Complete syntax reference with examples
- **docs/cli_usage.md**: Detailed command-line interface guide
- **docs/development.md**: Setup, testing, and contribution guidelines
- **docs/interpreter_spec.md**: Core implementation details
- **docs/symbolic_execution.md**: Program analysis capabilities
- **docs/simple_ir_design.md**: Intermediate representation format
- **docs/ir_to_source.md**: IR to source conversion and round-trip workflow

## Development Notes

- Uses unified AST processing architecture to avoid code duplication
- Comprehensive test suite with 340+ tests using pytest
- Supports multiple execution modes (interpret, IR generation/execution, IR-to-source conversion, symbolic analysis)
- Enhanced symbolic execution with Z3 constraint generation and precise loop analysis
- Shared conversion functions between IR-to-source converter and symbolic executor for consistent output
- Built-in memory protection mechanisms to prevent out-of-memory attacks
- Full closure support in IR interpreter with environment capture and nested closures
- Package management with `uv` (recommended) or `pip`
- Code formatting with `ruff`

## IR to Source Conversion

## Python Compatibility Checking

The toolkit includes a `check` command to verify if Python programs are compatible with Silu's supported features:

### Features
- **Compatibility verification**: Test if Python code can be interpreted by Silu
- **Detailed error reporting**: Returns "filename ok" or "filename bad: specific reason" for precise feedback
- **Silent execution**: No program output during checking, only compatibility status
- **Comprehensive error handling**: Catches and categorizes syntax errors, runtime errors, and unsupported language features

### Error Message Types
- **syntax error**: Python syntax violations (missing colons, parentheses, etc.)
- **name error**: Undefined variables, unsupported imports, classes
- **runtime error**: Division by zero, execution failures
- **type error**: Type mismatches and incompatible operations
- **index error**: List/string index out of bounds
- **empty file**: No content or whitespace only
- **file not found**: File doesn't exist or permission denied

### Use Cases
- **Pre-flight validation**: Check Python files before attempting interpretation
- **Batch processing**: Validate multiple files for Silu compatibility with specific error reasons
- **CI/CD integration**: Automated testing of Python code compatibility
- **Educational tools**: Help users understand Silu's language subset and specific limitations

## Closure Support

The Silu interpreter now provides **pure closure** support, allowing functions to capture and read variables from their defining scope:

### Features
- **Environment Capture**: Functions automatically capture variable values from their enclosing scope
- **Pure Closures Only**: Closures can read but cannot modify captured variables (value copying, not reference sharing)
- **Multiple Closures**: Independent closure instances with separate captured environments
- **Nested Closures**: Support for multiple levels of nested function definitions
- **Variable Isolation**: Each closure call operates on its own copy of captured variables

### Examples
```python
def make_adder(n):
    def adder(x):
        return x + n  # 'n' captured from outer scope
    return adder

add5 = make_adder(5)
result = add5(3)  # Returns 8
```

### Implementation Details
- **IR Interpreter**: Enhanced with closure-aware function calling and environment management
- **Value Copying**: Functions store copies of captured variable values (not references)
- **Closure IDs**: Unique identifiers generated for each closure instance
- **Memory Safety**: No shared mutable state between closures and their defining scope

### Design Philosophy
- **Pure Functional**: Encourages functional programming practices by preventing side effects
- **Predictable Behavior**: No hidden state mutations make code easier to reason about
- **Thread Safety**: Pure closures are inherently thread-safe
- **Simplicity**: Avoids complex memory management and variable aliasing issues

### Testing
- Comprehensive test suite including basic closures, multiple variables, and nested scenarios
- Regression tests to ensure pure closure behavior is maintained (no accidental non-pure support)
- All closure functionality verified through both unit tests and integration tests
- Compatible with existing IR generation and execution workflows

## IR to Source Conversion

The toolkit now includes bidirectional conversion between source code and IR:

### Features
- **Round-trip conversion**: Source → IR → Source with syntax preservation
- **Format support**: JSON and Python literal IR formats
- **CLI integration**: `silu to-source` command for batch processing
- **Shared utilities**: Common conversion functions used by symbolic executor for readable output
- **Full validation**: Automatic syntax checking of reconstructed code

### Use Cases
- **Code analysis**: Convert programs to IR for analysis, then back to readable form
- **IR debugging**: Generate human-readable source from complex IR structures
- **Tool integration**: Bridge between IR-based tools and source code editors
- **Round-trip testing**: Verify IR generation accuracy through reconstruction

## Symbolic Execution Enhancements

The symbolic executor has been significantly enhanced with advanced capabilities:

### Enhanced Features
- **Z3 Constraint Generation**: Automatic Z3 constraint generation for path conditions and loop bounds
- **Precise Loop Analysis**: Advanced range loop analysis with exact iteration constraint modeling
- **Extended AST Support**: Comprehensive AST-to-Z3 conversion supporting subscripts, built-ins, and complex expressions
- **Path Satisfiability**: Real-time constraint satisfiability checking for path pruning
- **Enhanced Reporting**: Detailed constraint analysis and path complexity metrics

### Technical Improvements
- **Advanced Loop Handling**: Special handling for `range()` loops with symbolic bounds and step values
- **Constraint Simplification**: Automatic Z3 expression simplification for better performance
- **Binary Operation Enhancement**: Z3-aware binary operation processing with constraint propagation
- **Improved Path Management**: Unified path handling with automatic constraint validation
- **Graceful Degradation**: Full functionality with or without Z3 solver installed

## Memory Protection

The Silu interpreter includes built-in memory protection mechanisms to prevent out-of-memory conditions that could crash the system or consume excessive resources.

### Protection Mechanisms

1. **Sequence Multiplication Limits**
   - Prevents multiplication of lists, tuples, or strings by numbers larger than 1,000,000
   - Prevents operations that would result in more than 10,000,000 total elements
   - Examples that are blocked: `[1, 2, 3] * 1000001`, `"x" * 2000000`

2. **Range Function Limits**
   - Prevents `range()` calls with arguments larger than 10,000,000
   - Applies to both single argument (`range(n)`) and multi-argument (`range(start, stop)`) forms
   - Examples that are blocked: `range(10000001)`, `range(0, 10000001)`

3. **Container Extension Limits**
   - Prevents `extend()` operations with iterables containing more than 10,000,000 elements
   - Automatically detects and blocks extension with large ranges
   - Example that is blocked: `[].extend(range(10000001))`

### Error Messages

When memory protection is triggered, the interpreter raises a `MemoryError` with descriptive messages:
- `"Memory protection: Cannot multiply sequence by X (limit: 1,000,000)"`
- `"Memory protection: Result would have X elements (limit: 10,000,000)"`  
- `"Memory protection: range(X) exceeds limit (10,000,000)"`
- `"Memory protection: extend() with X elements exceeds limit (10,000,000)"`

### Normal Operations

The protection mechanisms are designed to allow normal programming operations while preventing abuse:
- Small list/string multiplications work normally: `[1, 2] * 100`
- Reasonable range operations work: `range(1000000)` 
- Normal container operations work: `list.extend(range(10000))`

### Testing

Memory protection is thoroughly tested with dedicated test cases in `tests/test_memory_protection.py` covering:
- Boundary value testing at exact limits
- Different sequence types (lists, tuples, strings)
- Both directions of multiplication operations
- Range function protection
- Container extension protection
- Verification that normal operations still work
