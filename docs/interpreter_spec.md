# Silu Interpreter Specification

## Overview
Silu is a simple interpreted programming language that implements a subset of Python syntax. The interpreter uses Python's `ast` module to parse source code and execute it through a custom AST visitor.

## Architecture
The interpreter consists of three main components:

1. **Parser**: Uses `ast.parse()` to convert Silu source code into Python AST
2. **Environment**: Manages variable scope and built-in functions
3. **Interpreter**: Custom `ast.NodeVisitor` that executes AST nodes

## Core Components

### Environment
- Manages variable storage with parent/child scope relationships
- Provides built-in functions: `print`, `type`, `isinstance`, `int`, `float`, `str`, `bool`
- Handles type conversion and type checking operations

### Interpreter
The `SiluInterpreter` class extends `ast.NodeVisitor` and implements handlers for:

- **Module Operations**: `visit_Module`, `visit_Expr`
- **Variables**: `visit_Assign`, `visit_Name`, `visit_Constant`
- **Operations**: `visit_BinOp`, `visit_UnaryOp`, `visit_BoolOp`, `visit_Compare`
- **Control Flow**: `visit_If`, `visit_While`, `visit_For`
- **Data Structures**: `visit_List`
- **Functions**: `visit_FunctionDef`, `visit_Return`, `visit_Call`

## Supported Language Features

### Data Types
- `int`: Integer numbers
- `float`: Floating-point numbers
- `str`: String literals
- `bool`: Boolean values (`True`, `False`)
- `list`: Ordered collections

### Variables and Assignment
```
x = 10
name = "Silu"
is_active = True
```

### Arithmetic Operations
- Addition (`+`), Subtraction (`-`)
- Multiplication (`*`), Division (`/`)
- Floor Division (`//`), Modulo (`%`)
- Exponentiation (`**`)

### Boolean and Comparison Operations
- Logical: `and`, `or`, `not`
- Comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`
- Chained comparisons: `1 < x < 10`

### Control Flow
```silu
# If statements
if x > 0:
    print("positive")
elif x < 0:
    print("negative")
else:
    print("zero")

# While loops
while i < 10:
    print(i)
    i = i + 1

# For loops
for item in list([1, 2, 3]):
    print(item)
```

### Functions
```silu
# Function definition
def greet(name):
    return "Hello, " + name

# Function call
message = greet("World")
```

## Built-in Functions
- `print(*args)`: Output values to console
- `type(obj)`: Return the type of an object
- `isinstance(obj, cls)`: Check if object is instance of type
- `int()`, `float()`, `str()`, `bool()`: Type conversion
- `list(iterable)`: Create list from iterable
- `range(stop)`: Generate sequence of numbers

## Execution Flow
1. Source code is parsed into AST using `ast.parse()`
2. `SiluInterpreter` instance is created with global environment
3. AST is traversed via `interpreter.visit(tree)`
4. Each node is processed by corresponding `visit_*` method
5. Results are computed and stored in environment

## Security
The interpreter only executes a predefined set of AST nodes, making it safe from arbitrary code execution. Dangerous operations like imports are not supported.