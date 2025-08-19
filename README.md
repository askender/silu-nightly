# Silu Programming Language
# 斯路编程语言

A simple AI-first interpreted programming language with Python-like syntax.

## Quick Start

### Installation

```bash
# Using pip
pip install -e .

# Using uv (recommended for development)
uv sync && uv pip install -e .
```

### Basic Usage

```bash
# Run a Silu program
silu hello.si

# Interactive execution
silu interpret --source "print('Hello, World!')"
```

### Hello World Example

Create `hello.si`:
```silu
# Variables and basic operations
name = "Silu"
version = 1.0

print("Hello from", name, version)

# Functions
def greet(person):
    return "Welcome to " + person + "!"

message = greet("Silu Programming")
print(message)
```

Run it:
```bash
silu hello.si
```

## Key Features

- **Simple Syntax**: Python-like syntax that's easy to learn
- **Multiple Execution Modes**: 
  - Direct interpretation
  - IR (Intermediate Representation) generation and execution
  - Symbolic execution for program analysis
- **Built-in Functions**: `print()`, `type()`, `isinstance()`, type conversions
- **Control Flow**: if/elif/else, while loops, for loops with range()
- **Functions**: User-defined functions with parameters and return values
- **Data Types**: int, float, str, bool, lists

## Advanced Usage

### Generate Intermediate Representation
```bash
silu ir program.si --format json --output program.ir
```

### Symbolic Execution Analysis
```bash
silu symbolic program.si
```

### Execute IR Directly
```bash
silu exec program.ir
```

## Documentation

- **[CLI Usage Guide](docs/cli_usage.md)** - Complete command-line reference
- **[Language Features](docs/language_features.md)** - Syntax and examples  
- **[Development Guide](docs/development.md)** - Setup, testing, and contributing
- **[Symbolic Execution](docs/symbolic_execution.md)** - Program analysis capabilities
- **[IR Design](docs/simple_ir_design.md)** - Intermediate representation format
- **[Interpreter Specification](docs/interpreter_spec.md)** - Core implementation details

## Examples

### Demo Programs

The repository includes comprehensive demo programs showcasing all language features:

```bash
# Run the main demo (variables, functions, control flow)
silu demo.si

# Complex programming patterns
silu complex_example.si

# Symbolic execution analysis
silu symbolic symbolic_demo.si
```

### Performance Comparison

Compare different execution modes:
```bash
# Interpretation vs IR execution
time silu interpret demo.si
silu ir demo.si --output demo.ir.json --format json
time silu exec demo.ir.json
```

## Contributing

We welcome contributions! See the [Development Guide](docs/development.md) for setup instructions and coding guidelines.

## License

MIT License