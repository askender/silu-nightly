# Silu: A simple AI programming language
# 斯路：一个简单的AI编程语言

## Features

*   **Simplicity**: Designed to be easy to learn and use.
*   **AI-First**: Built-in support for common AI tasks.
*   **Interpreted**: Runs directly from source code.

## Installation

To install Silu, you need to have Python 3.6 or later installed. Then, you can install Silu using pip:

```bash
pip install .
```

Or, if you want to install it in development mode:

```bash
pip install -e .
```

## Usage

The Silu CLI provides multiple modes of operation:

### Traditional Usage (Interpretation)

To run a Silu program, save your code in a file with a `.si` extension and then run it using the `silu` command:

```bash
silu your_program.si
```

### Explicit Interpretation Mode

You can explicitly specify the interpretation mode:

```bash
# Interpret a Silu file
silu interpret your_program.si

# Interpret source code directly
silu interpret --source "x = 5; print(x)"

# Enable debug mode
silu interpret your_program.si --debug
```

### IR Generation Mode

Generate intermediate representation (IR) from Silu programs:

```bash
# Generate IR in pretty format (default)
silu ir your_program.si

# Generate IR in JSON format
silu ir your_program.si --format json

# Generate IR in compact format
silu ir your_program.si --format compact

# Save IR to a file
silu ir your_program.si --output program.ir.json --format json

# Generate IR from source code directly
silu ir --source "x = 5; print(x)"
```

### Symbolic Execution Mode

Perform symbolic analysis to discover all possible execution paths:

```bash
# Analyze a Silu program
silu symbolic your_program.si

# Analyze IR directly
silu symbolic program.ir.json

# Analyze source code directly
silu symbolic --source "if x > 5: y = 1 else: y = 2"
```

For detailed information about symbolic execution capabilities, see [docs/symbolic_execution.md](docs/symbolic_execution.md).

### Help and Documentation

```bash
# Show general help
silu --help

# Show help for specific commands
silu interpret --help
silu ir --help
silu symbolic --help
```

## Examples

### Basic Silu Program

Here is a simple "Hello, World!" program in Silu:

```silu
print("Hello, World!")
```

### Demo Program

The repository includes a comprehensive demo program (`demo.si`) that showcases all language features:

```bash
# Run the demo
silu demo.si

# Generate IR for the demo
silu ir demo.si --format json
```

### Language Features Example

```silu
# Variables and types
x = 42
name = "Silu"
flag = True

# Control flow
if x > 30:
    print("Large number")
else:
    print("Small number")

# Functions
def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

result = factorial(5)
print("Result:", result)
```

## Contributing

Contributions are welcome! Please read our [contributing guidelines](CONTRIBUTING.md) for more information.

## Documentation

For detailed information about Silu's features and implementation:

- [Symbolic Execution](docs/symbolic_execution.md) - Program analysis and path exploration
- [Simple IR Design](docs/simple_ir_design.md) - Intermediate representation format
- [Interpreter Specification](docs/interpreter_spec.md) - Core interpreter details

## License

Silu is licensed under the MIT License. See [LICENSE](LICENSE) for more information.