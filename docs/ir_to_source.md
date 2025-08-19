# IR to Source Conversion

This document describes the IR to source code conversion functionality in Silu, which allows converting Intermediate Representation (IR) back to readable source code.

## Overview

The IR to source conversion feature enables bidirectional transformation between Silu source code and its intermediate representation. This is useful for:

- **Code analysis workflows**: Convert source → IR for analysis → source for human review
- **IR debugging**: Generate readable code from complex IR structures
- **Tool integration**: Bridge between IR-based analysis tools and source editors
- **Round-trip validation**: Verify IR generation accuracy through reconstruction

## Architecture

### Core Components

1. **IRToSourceConverter**: Main conversion class that transforms IR tuples to source code
2. **Shared utilities**: Functions used by both IR-to-source converter and symbolic executor
3. **CLI integration**: `silu to-source` command for batch processing
4. **Format support**: Handles both JSON and Python literal IR formats

### Design Principles

- **Context-aware conversion**: Distinguishes between identifiers and string literals based on context
- **Syntax preservation**: Maintains proper indentation, operator precedence, and Python syntax
- **Extensibility**: Modular design allows easy addition of new IR node types
- **Error handling**: Graceful handling of malformed or unsupported IR structures

## Usage

### Command Line Interface

```bash
# Convert IR file to source code (output to stdout)
silu to-source program.ir.json

# Convert IR file and save to specific output file
silu to-source program.ir.json --output reconstructed.si

# Convert IR string directly
silu to-source --source '["assign", "x", 42, null]'
```

### Programmatic API

```python
from silu.ir_to_source import IRToSourceConverter, convert_ir_file_to_source

# Using the converter class
converter = IRToSourceConverter(indent_size=4)
ir_tuple = ("assign", "x", 42, None)
source_code = converter.convert_to_source(ir_tuple)
print(source_code)  # Output: x = 42

# Using convenience functions
source_code = convert_ir_file_to_source("program.ir.json", "output.si")
```

## IR Format Support

### JSON Format
```json
[
  "module",
  [
    ["assign", "x", 10, null],
    ["if", [">", "x", 5],
      [["call", "print", ["large"], []]],
      [["call", "print", ["small"], []]]
    ]
  ]
]
```

### Python Literal Format
```python
("module", (
    ("assign", "x", 10, None),
    ("if", (">", "x", 5),
        (("call", "print", ("large",), ()),),
        (("call", "print", ("small",), ()),)
    )
))
```

## Conversion Examples

### Basic Statements

| IR Tuple | Generated Source |
|----------|------------------|
| `("assign", "x", 42, None)` | `x = 42` |
| `("call", "print", ("hello",), ())` | `print('hello')` |
| `("return", ("*", "a", "b"))` | `return a * b` |

### Control Flow

**If Statement:**
```python
# IR
("if", (">", "x", 0),
    (("assign", "result", "positive", None),),
    (("assign", "result", "negative", None),)
)

# Generated Source
if x > 0:
    result = 'positive'
else:
    result = 'negative'
```

**While Loop:**
```python
# IR
("while", (">", "i", 0),
    (("assign", "i", ("-", "i", 1), None),)
)

# Generated Source
while i > 0:
    i = i - 1
```

### Data Structures

**Lists:**
```python
# IR: ("list", (1, 2, 3))
# Source: [1, 2, 3]
```

**Dictionaries:**
```python
# IR: ("dict", (("name", "Alice"), ("age", 30)))
# Source: {'name': 'Alice', 'age': 30}
```

### Functions

**Function Definition:**
```python
# IR
("func_def", "add", ("a", "b"),
    (("return", ("+", "a", "b")),)
)

# Generated Source
def add(a, b):
    return a + b
```

## Advanced Features

### Operator Precedence

The converter automatically handles operator precedence and adds parentheses when needed:

```python
# IR: ("+", ("*", 2, 3), 4)
# Source: 2 * 3 + 4

# IR: ("*", ("+", 2, 3), 4)
# Source: (2 + 3) * 4
```

### Chained Comparisons

```python
# IR: ("chained_compare", (("<", 1, "x"), ("<", "x", 10)))
# Source: 1 < x < 10
```

### Context-Aware String Handling

The converter distinguishes between identifiers and string literals:

```python
# Variable names remain unquoted
"x" -> x

# Non-identifier strings are quoted
"hello world" -> 'hello world'

# In assignment context, values are typically quoted
("assign", "msg", "hello", None) -> msg = 'hello'
```

## Integration with Symbolic Executor

The IR to source converter shares utility functions with the symbolic executor for consistent output formatting:

```python
from silu.ir_to_source import make_expression_readable, simplify_value_display

# These functions are used by both components
expr = ("+", "x", ("*", "y", 2))
readable = make_expression_readable(expr)  # "x + y * 2"
```

## Complete Workflow Example

Here's a complete round-trip example:

```python
import ast
from silu.ir_generator import SiluIRGenerator
from silu.ir_to_source import IRToSourceConverter
from silu.interpreter import SiluInterpreter

# Original source code
original = """
def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

result = factorial(5)
print("Result:", result)
"""

# Step 1: Parse to AST
tree = ast.parse(original)

# Step 2: Generate IR
ir_generator = SiluIRGenerator()
ir_result = ir_generator.visit(tree)

# Step 3: Convert IR back to source
converter = IRToSourceConverter()
reconstructed = converter.convert_to_source(ir_result)

print("Reconstructed source:")
print(reconstructed)

# Step 4: Verify it works
reconstructed_tree = ast.parse(reconstructed)
interpreter = SiluInterpreter()
interpreter.visit(reconstructed_tree)
```

## Limitations and Considerations

### Current Limitations

1. **Comments**: Lost during AST parsing (not stored in IR)
2. **Whitespace**: Original formatting and blank lines are not preserved
3. **String quotes**: Always uses single quotes in output (Python's repr() default)
4. **Complex expressions**: Some deeply nested expressions may need parentheses

### Best Practices

1. **Validate output**: Always check that reconstructed code has valid syntax
2. **Test functionality**: Execute both original and reconstructed code to verify correctness
3. **Handle errors**: Wrap conversion in try-catch blocks for malformed IR
4. **Use appropriate context**: Choose between identifier and literal conversion based on usage

## Error Handling

The converter provides helpful error messages for common issues:

```python
# Invalid IR format
try:
    convert_ir_string_to_source("invalid ir")
except ValueError as e:
    print(f"Conversion failed: {e}")

# Unsupported node types
try:
    converter.convert_to_source(("unsupported_node", "data"))
except Exception as e:
    print(f"Unsupported IR node: {e}")
```

## Testing

The conversion functionality is thoroughly tested:

- **Unit tests**: Individual IR node conversion
- **Integration tests**: Complete program round-trips
- **Edge cases**: Malformed IR, complex expressions, nested structures
- **Compatibility tests**: JSON vs Python literal formats

Run tests with:
```bash
python -m pytest tests/test_ir_to_source.py -v
```

## Future Enhancements

Potential improvements for future versions:

1. **Comment preservation**: Store and reconstruct comments
2. **Formatting options**: Configurable code style (spaces, quotes, etc.)
3. **Source maps**: Track mapping between original and reconstructed code
4. **Optimization hints**: Detect and preserve optimization-relevant patterns
5. **Custom node handlers**: Plugin system for domain-specific IR extensions

## Conclusion

The IR to source conversion feature provides a robust foundation for bidirectional code transformation in Silu. It enables sophisticated analysis workflows while maintaining code readability and correctness. The shared utility functions ensure consistency across the toolkit, making it a valuable component for both interactive development and automated tooling.