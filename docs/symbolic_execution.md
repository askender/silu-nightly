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

## Usage

### Basic Usage

```bash
# Analyze a Silu program
silu symbolic program.si

# Analyze IR directly
silu symbolic program.ir.json

# Analyze source code string
silu symbolic --source "if x > 5: y = 1 else: y = 2"
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

## Applications

### Test Case Generation
Path conditions can be used to generate test inputs:
- `x > 10` → test with `x = 15`
- `0 < x ≤ 10` → test with `x = 5`
- `x ≤ 0` → test with `x = -1`

### Code Coverage Analysis
- Identify all possible execution paths
- Ensure test suites cover all branches
- Detect unreachable code

### Program Verification
- Find contradictory conditions
- Analyze boundary cases
- Verify function behavior across all inputs

## Implementation Details

The symbolic executor operates on Silu's intermediate representation (IR) and uses:

- **Path Explosion Prevention**: Configurable limits to prevent infinite analysis
- **Environment Management**: Tracks symbolic variables and function scopes
- **Constraint Solving**: Basic satisfiability checking for path conditions

## Supported Language Features

- ✅ If/elif/else statements
- ✅ While loops (simplified analysis)
- ✅ Function definitions and calls
- ✅ Arithmetic and comparison operations
- ✅ Built-in functions (print, type conversions, etc.)
- ✅ Variable assignments and references
- ✅ Nested control structures

## Limitations

- **Loop Analysis**: Currently performs simplified loop analysis (single iteration)
- **Function Calls**: User-defined functions create symbolic return values
- **Complex Expressions**: Some advanced expressions may be approximated

For more details on implementation and architecture, see the main project documentation.