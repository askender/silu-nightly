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

## Language Features Summary

- **Data Types**: int, float, str, bool, bytes, list
- **Operations**: Arithmetic, boolean, comparison (including chained)
- **Control Flow**: if/elif/else, while/for loops, match/case statements
- **Assignment**: Simple assignment, multiple target assignment (a = b = 1), tuple unpacking
- **Functions**: User-defined with parameters and return values, closures
- **Built-ins**: print, type, isinstance, type conversions
- **Pattern Matching**: Full match/case support with value, sequence, mapping, or, guard, capture, and star patterns

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
- Enhanced symbolic execution with Z3 constraint generation and precise loop handling
- Shared conversion functions between IR-to-source converter and symbolic executor for consistent output
- Built-in memory protection mechanisms to prevent out-of-memory attacks
- Full closure support in IR interpreter with environment capture and nested closures
- Complete match/case statement support for structural pattern matching (Python 3.10+ syntax)
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

## Match Statement Support

The Silu IR generator now provides comprehensive support for Python's match/case statements (structural pattern matching) introduced in Python 3.10.

### Supported Pattern Types

1. **Value Patterns**: `case 42:`, `case "hello":`, `case 3.14:`
2. **Singleton Patterns**: `case True:`, `case False:`, `case None:`
3. **Sequence Patterns**: `case [1, 2, x]:`, `case [first, *rest]:`
4. **Mapping Patterns**: `case {"key": value}:`, `case {"name": n, **extra}:`
5. **Or Patterns**: `case 1 | 2 | 3:`
6. **Capture Patterns**: `case x:` (captures value)
7. **Wildcard Patterns**: `case _:` (matches anything)
8. **Guard Patterns**: `case x if x > 10:`
9. **Star Patterns**: `case [*items]`, `case [first, *rest]`

### IR Structure

Match statements are converted to IR with the following structure:
```python
("match", subject_ir, (case1_ir, case2_ir, ...))
```

Each case is represented as:
```python
("match_case", pattern_ir, guard_ir_or_None, (body_stmt1, body_stmt2, ...))
```

Patterns have specific IR representations:
- Value: `("match_value", value_ir)`
- Singleton: `("match_singleton", True|False|None)`
- Sequence: `("match_sequence", (pattern1, pattern2, ...))`
- Mapping: `("match_mapping", (key1, key2, ...), (pattern1, pattern2, ...), rest_name_or_None)`
- Or: `("match_or", (pattern1, pattern2, ...))`
- As/Capture: `("match_as", nested_pattern_or_None, capture_name_or_None)`
- Star: `("match_star", capture_name_or_None)`

### Example Usage

```python
# Input Silu code
def handle_data(data):
    match data:
        case {"type": "user", "name": name}:
            return f"User: {name}"
        case [first, *rest] if len(rest) > 0:
            return f"List: {first} + {len(rest)} more"
        case _:
            return "Unknown"

# Generates comprehensive IR for all pattern types
silu ir example.py --format json
```

### Testing

Match statement support is thoroughly tested in `tests/test_match_ir.py` with comprehensive coverage of:
- All pattern types and combinations
- Nested patterns and complex structures
- Guard conditions and multiple cases
- Integration with functions and other language features
- Edge cases like empty bodies and multiple statements per case

## IR Refactoring Progress (2024-08-28)

### Completed
1. **Fixed Symbolic Executor Bug**: Resolved tuple/string comparison error in `PathManager.finalize_paths()` that prevented symbolic execution of C-generated IR files
2. **Created IR Utilities Module** (`ir_utils.py`):
   - JSON to tuple conversion utilities
   - IR parsing from files and strings (supports both JSON and Python literal formats)
   - IR validation functions (node format, program structure)
   - IR analysis tools (opcode extraction, node counting, node searching)
   - File I/O operations with format detection
   - Comprehensive error handling
   - Full test coverage (42 tests in `test_ir_utils.py`)
3. **Integrated ir_utils Across All IR Processors** (2024-12-19):
   - Replaced duplicate JSON parsing code in `ir_interpreter.py` with `parse_ir_from_file` and `parse_ir_from_json_string`
   - Removed redundant `_json_to_tuples` and `_parse_ir_content` functions from `symbolic_executor.py`
   - Simplified `ir_to_source.py` by using shared parsing utilities
   - Updated `silu_ir_to_llvm.py` to use consistent IR parsing
   - All 531 tests pass after refactoring

### Next Steps
1. **Targeted Utility Functions**: Identify and extract specific shared utility functions that are used across multiple IR processors
2. **Simplified IR Node Dispatching**: Create a common node dispatching mechanism without introducing complex abstractions
3. **Balanced Refactoring**: Extract only code that provides clear benefits when shared, avoiding over-abstraction

### Benefits Achieved
- **Eliminated ~100 lines of duplicate code** across 4 modules
- **Unified error handling**: Consistent error messages and exception types
- **Improved maintainability**: Single source of truth for IR parsing logic
- **Better testability**: Centralized utilities with comprehensive test coverage
- **Format flexibility**: Seamless support for both JSON and Python literal formats

### IR Refactoring Principles (2024-08-29)

#### Goals
- **Reduce code duplication**: Identify and extract common functionality without sacrificing readability
- **Maintain module independence**: Each IR processor should remain usable independently
- **Avoid over-abstraction**: Prefer concrete utility functions over complex abstract classes
- **Improve maintainability**: Changes to shared code should predictably affect all consumers

#### Target Areas for Shared Utilities
1. **IR Node Dispatching**: Common mechanism to route node types to their handlers
2. **Error Handling**: Consistent error reporting and validation across modules
3. **Common Node Processing**: Shared utilities for simple nodes like constants and primitives
4. **Debug/Logging Utilities**: Consistent debugging and tracing capabilities

#### Implementation Strategy
1. Start with small, well-defined utility functions that have clear purposes
2. Prioritize extraction of functions that are used identically across modules
3. Maintain consistent naming conventions across all shared utilities
4. Add comprehensive tests for each extracted utility function
5. Document each utility's purpose, expected inputs/outputs, and usage examples

#### Non-Goals
- Creating a complex inheritance hierarchy that forces modules to fit a rigid pattern
- Prematurely abstracting code that may evolve differently across modules
- Sacrificing readability or debuggability for the sake of code reduction
- Introducing dependencies between modules that should remain independent

### IR Common Module Implementation (2024-08-30)

A new `ir_common.py` module has been created to provide shared functionality across the four IR processing modules (interpreter, symbolic executor, IR-to-source converter, and LLVM converter) with the following features:

#### Key Components
1. **IR Node Dispatching**:
   - `dispatch_ir_node()`: Routes IR nodes to their appropriate handlers based on opcode
   - `create_handlers_map()`: Builds a mapping of opcodes to handler methods

2. **Debug and Logging**:
   - `log_ir_processing()`: Consistent logging format for IR node processing

3. **Error Handling**:
   - `handle_node_error()`: Unified error handling and reporting
   - `IRProcessingError`: Common exception type for IR processing errors

4. **Node Validation**:
   - `validate_node_args()`: Validates node structure, opcode, and argument count

5. **Common Node Processing**:
   - `process_ir_block()`: Process a block of IR statements
   - `extract_names_from_params()`: Extract parameter names from function definitions
   - `process_const_node()`: Extract value from constant nodes
   - `is_valid_identifier()`: Check if a string is a valid Python identifier

#### Benefits
- Reduces duplication in node validation and dispatching logic
- Provides consistent error handling across all IR processors
- Simplifies common processing patterns without imposing rigid structures
- Maintains module independence while sharing useful utilities

#### Usage Examples

Here are examples of how to use the common IR utilities in the four IR processing modules:

**1. Using the Node Dispatcher**

```python
from silu.ir_common import dispatch_ir_node, create_handlers_map

class IRInterpreter:
    def __init__(self):
        # Create handlers map from methods
        self.handlers = create_handlers_map(self)

    def execute(self, node):
        # Dispatch node to appropriate handler
        return dispatch_ir_node(node, self.handlers)

    def _process_const(self, node):
        return node[1]

    def _process_name(self, node):
        return self.get_variable(node[1])
```

**2. Error Handling**

```python
from silu.ir_common import handle_node_error, validate_node_args

class IRToSourceConverter:
    def _convert_binary_op(self, node):
        try:
            validate_node_args(node, "binary_op", 3, 3)
            left = self.convert(node[1])
            op = node[2]
            right = self.convert(node[3])
            return f"{left} {op} {right}"
        except Exception as e:
            handle_node_error(node, e, "converting binary op")
```

**3. Block Processing**

```python
from silu.ir_common import process_ir_block

class SymbolicExecutor:
    def _execute_block(self, statements):
        return process_ir_block(statements, self.execute, break_on_return=True)
```

**4. Validation and Debugging**

```python
from silu.ir_common import log_ir_processing, is_valid_identifier

class IRToLLVMConverter:
    def _convert_node(self, node):
        if self.debug:
            log_ir_processing(node[0], node[1:], "DEBUG")

        # Validate identifier if needed
        if node[0] == "name" and not is_valid_identifier(node[1]):
            raise IRProcessingError(f"Invalid identifier: {node[1]}")
```
