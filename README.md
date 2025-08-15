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

To run a Silu program, save your code in a file with a `.si` extension and then run it using the `silu` command:

```bash
silu your_program.si
```

## Examples

Here is a simple "Hello, World!" program in Silu:

```
print("Hello, World!")
```

For now, the interpreter just prints a default message. You can modify `silu/__main__.py` to add parsing and execution logic for `.si` files.

## Contributing

Contributions are welcome! Please read our [contributing guidelines](CONTRIBUTING.md) for more information.

## License

Silu is licensed under the MIT License. See [LICENSE](LICENSE) for more information.