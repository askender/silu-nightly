# Symbolic Execution in Silu

This document describes the symbolic execution capabilities of the Silu programming language, which enables comprehensive program analysis and automated test case generation.

## Overview

Symbolic execution is a program analysis technique that explores all possible execution paths through a program by using symbolic values instead of concrete values. The Silu symbolic executor can analyze functions and generate path conditions for each possible execution branch.

## Key Features

### Path Analysis
- **Complete Coverage**: Discovers all possible execution paths through functions
- **Branch Analysis**: Handles if/elif/else statements, while loops, and nested control structures  
- **Constraint Generation**: Creates path conditions showing when each branch is taken

### Symbolic Values
- **Symbolic Variables**: Function parameters become symbolic values (e.g., `x`, `y`)
- **Symbolic Expressions**: Operations create symbolic expressions (e.g., `x > 10`, `(a + b)`)
- **Path Conditions**: Each execution path has conditions that must be satisfied

### Report Generation
- **JSON Output**: Detailed analysis reports in structured format
- **Path Information**: Conditions, statements, variables, and return values for each path
- **Satisfiability**: Automatic detection of contradictory path conditions

### Debugging and Exception Handling
- **Debug Mode**: Enhanced diagnostic output for troubleshooting analysis issues
- **Robust Error Handling**: Graceful fallbacks when complex operations fail
- **Specific Exception Catching**: Targeted exception handling for improved reliability

## Usage

### Basic Usage

```bash
# Basic symbolic execution
silu symbolic program.si

# Generate test cases with Z3 solver
silu symbolic program.si --solve

# Simplify path conditions
silu symbolic program.si --simplify

# Combined: solve and simplify
silu symbolic program.si --solve --simplify

# Performance mode for faster analysis
silu symbolic program.si --performance-mode

# Include function paths (compatibility mode)
silu symbolic program.si --include-function-paths

# Enable debug mode for diagnostic output
silu symbolic program.si --debug
```

### Debug Mode

Debug mode provides detailed diagnostic information when analysis encounters issues:

```bash
# Enable debug mode
silu symbolic program.si --debug

# Debug mode with Z3 solver
silu symbolic program.si --solve --debug
```

When debug mode is enabled, you'll see informative messages about:
- Z3 constraint generation failures
- Expression conversion issues
- Fallback behaviors being used

Example debug output:
```
Debug: Z3 expression creation failed for +: unsupported operand type(s) for +: 'str' and 'int'
Debug: Condition readability conversion failed: 'dict' object has no attribute 'op'
```

### Example Analysis

Given this Silu function:

```python
def classify(x):
    if x > 10:
        return "large"
    elif x > 0:
        return "small"
    else:
        return "zero_or_negative"
```

The symbolic executor discovers 3 execution paths:

1. **Path 1**: `x > 10` → returns `"large"`
2. **Path 2**: `x ≤ 10 AND x > 0` → returns `"small"`  
3. **Path 3**: `x ≤ 0` → returns `"zero_or_negative"`

### Sample Output

```json
{
  "function_analyses": {
    "classify": {
      "total_paths": 3,
      "paths": [
        {
          "conditions": ["(x > 10)"],
          "return_value": "large"
        },
        {
          "conditions": ["not (x > 10)", "(x > 0)"],
          "return_value": "small"
        },
        {
          "conditions": ["not (x > 10)", "not (x > 0)"],
          "return_value": "zero_or_negative"
        }
      ]
    }
  }
}
```

## Z3 Solver Integration

The `--solve` option integrates the Z3 SMT solver for automatic test case generation:

### Installation
```bash
# Install Z3 solver
uv pip install z3-solver  # or: pip install z3-solver
```

### Features
- **Automatic Test Cases**: Generates concrete inputs for each execution path
- **Satisfiability Checking**: Identifies impossible (dead code) paths
- **Constraint Solving**: Handles complex logical conditions

### Example with Test Generation
```bash
silu symbolic classify_number.si --solve
```

For a function like:
```python
def classify_number(x):
    if x > 100:
        return "large"
    elif x > 0:
        return "small"
    else:
        return "zero_or_negative"
```

Generates:
```json
{
  "paths": [
    {
      "conditions": ["(x > 100)"],
      "test_inputs": {"x": 101},
      "expected_outputs": {"return_value": "large"}
    },
    {
      "conditions": ["not (x > 100)", "(x > 0)"],
      "test_inputs": {"x": 1},
      "expected_outputs": {"return_value": "small"}
    }
  ]
}
```

## Advanced Features

### Path Simplification
The `--simplify` option reduces complex conditions:
- Merges redundant constraints
- Simplifies boolean expressions
- Improves readability

### Performance Options
- `--performance-mode`: Faster analysis with reduced depth
- `--include-function-paths`: Include function internal paths in main collection

## Applications

### Automated Testing
- Generate comprehensive test suites automatically
- Ensure all code paths are tested
- Identify edge cases and boundary conditions

### Code Quality
- Detect unreachable (dead) code
- Find contradictory conditions
- Verify program logic across all inputs

## CLI Options Summary

| Option | Description |
|--------|-------------|
| `--solve` | Generate test cases using Z3 solver |
| `--simplify` | Simplify and merge path conditions |
| `--performance-mode` | Enable faster analysis with reduced depth |
| `--include-function-paths` | Include function internal paths |
| `--debug` | Enable diagnostic output for troubleshooting |
| `--format json\|pretty` | Output format selection |
| `--output FILE` | Save results to file |

## Supported Language Features

- ✅ If/elif/else statements
- ✅ While loops (simplified analysis)
- ✅ Function definitions and calls
- ✅ Arithmetic and comparison operations
- ✅ Built-in functions (print, type conversions, etc.)
- ✅ Variable assignments and references
- ✅ Nested control structures

## Error Handling and Robustness

The symbolic executor includes robust exception handling to ensure reliable analysis:

### Exception Handling Strategy
- **Specific Exception Types**: Catches only expected exceptions (TypeError, AttributeError, ValueError)
- **Graceful Fallbacks**: Continues analysis when complex operations fail
- **Debug Information**: Optional diagnostic output to help identify issues

### Common Fallback Scenarios
- **Z3 Expression Failures**: Falls back to symbolic representation when Z3 constraint generation fails
- **Type Conversion Issues**: Uses string representation when complex expression conversion fails
- **Attribute Access Errors**: Continues with alternative display formats

### Best Practices
- Use `--debug` flag when analysis produces unexpected results
- Complex programs may have some paths approximated due to expression complexity
- The executor prioritizes completeness over perfect precision for robustness

## Limitations

- **Loop Analysis**: Currently performs simplified loop analysis (single iteration)
- **Function Calls**: User-defined functions create symbolic return values
- **Complex Expressions**: Some advanced expressions may be approximated

For more details on implementation and architecture, see the main project documentation.