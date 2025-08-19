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

The `SiluInterpreter` class implements handlers for:
- **Module Operations**: `visit_Module`, `visit_Expr`
- **Variables**: `visit_Assign`, `visit_Name`, `visit_Constant`
- **Operations**: `visit_BinOp`, `visit_UnaryOp`, `visit_BoolOp`, `visit_Compare`
- **Control Flow**: `visit_If`, `visit_While`, `visit_For`
- **Data Structures**: `visit_List`
- **Functions**: `visit_FunctionDef`, `visit_Return`, `visit_Call`

## Architecture Design

The system uses a unified AST processing architecture with multiple concrete implementations:

### SiluIRGenerator (Concrete Implementation)
The IR generator works by:
1. Extending BaseASTProcessor with IR generation implementations
2. Converting AST nodes to tuple-based intermediate representation
3. Supporting comprehensive Python syntax including advanced features
4. Maintaining structural information without execution

### SymbolicExecutor (Concrete Implementation)
The symbolic executor works by:
1. Analyzing IR programs symbolically without concrete values
2. Tracking all possible execution paths through control flow
3. Generating path conditions and constraints for each branch
4. Supporting symbolic values, expressions, and constraint solving

### Key AST Nodes Supported
- **Basic**: Module, Expr, Assign, Name, Constant
- **Operations**: BinOp, UnaryOp, BoolOp, Compare
- **Functions**: Call, FunctionDef, Return
- **Control Flow**: If, While, For
- **Containers**: List, Dict, Tuple, Subscript, Attribute

## Supported Language Features

### Data Types
- `int`: Integer numbers
- `float`: Floating-point numbers
- `str`: String literals
- `bool`: Boolean values (`True`, `False`)
- `list`: Ordered collections

### Variables and Assignment
```silu
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

## Error Handling

The interpreter implements proper error handling for:
- **Undefined variables** (NameError): When accessing variables that haven't been defined
- **Division by zero** (ZeroDivisionError): Mathematical division by zero operations
- **Unsupported operations** (NotImplementedError): Operations not yet implemented
- **Type errors** (TypeError): Invalid operations between incompatible types
- **Value errors** (ValueError): Invalid values for type conversion or operations

## Testing Structure

Tests are organized by component:
- `test_interpreter.py`: Core interpreter functionality
- `test_cli.py`: Command-line interface tests
- `test_main.py`: Main module tests

Test coverage includes:
- AST node visiting and execution
- Built-in functions and type operations
- Control flow constructs (if/while/for)
- Error handling and edge cases
- End-to-end program execution

## Execution Flow
1. Source code is parsed into AST using `ast.parse()`
2. `SiluInterpreter` instance is created with global environment
3. AST is traversed via `interpreter.visit(tree)`
4. Each node is processed by corresponding `visit_*` method
5. Results are computed and stored in environment

## Security
The interpreter only executes a predefined set of AST nodes, making it safe from arbitrary code execution. Dangerous operations like imports are not supported.