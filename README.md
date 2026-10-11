# Silu Programming Language

**English** | [简体中文](README_zh.md)

Silu (斯路) is a simple, AI-first programming language implemented in Python. It uses a Python-compatible syntax subset and is designed as a foundation for advanced AI reasoning capabilities: rigorous logical reasoning, symbolic execution, formal analysis, and native code generation.

## Why Silu

- **Python-compatible subset** — Silu reuses Python's parser, so most simple Python programs run unchanged. `silu check program.py` tells you exactly what is (and isn't) supported.
- **One IR, many backends** — Every program lowers to a small tuple-based intermediate representation that can be interpreted directly, converted back to source, symbolically analyzed, or compiled to native code via LLVM.
- **Symbolic execution built in** — Explore all execution paths of a function, generate path conditions with Z3, and produce concrete test inputs automatically.
- **Beyond Silu source** — The same IR and symbolic-execution toolchain also accepts **C programs** (via pycparser), enabling path analysis and test-case generation for existing C code.

## Vision & AI Roadmap

Silu aims to become a platform for developing AI systems that can:

- Combine rigorous logical reasoning with probabilistic reasoning
- Achieve self-bootstrapping and self-correction
- Conduct autonomous hypothesis testing and experimentation
- Discover inconsistencies and drive curiosity-based learning

Development stages:

- **2025–2028**: Logic mastery (CFG, data flow, SMT verification)
- **2028–2032**: Logic + probabilistic reasoning fusion
- **2032–2036**: Self-bootstrapping and self-correction
- **2036–2040**: Hypothesis-driven experimentation
- **2040+**: Inconsistency detection and curiosity-driven knowledge creation

See the [AI Development Plan](docs/plan.md) for the detailed roadmap and benchmarks.

## Installation

Requires Python 3.11+.

```bash
# Using pip
pip install -e .

# Using uv (recommended for development)
uv sync && uv pip install -e .
```

Runtime dependencies: `llvmlite`, `pycparser`, `z3-solver`, `loguru`, `mlir`.

## Quick Start

```bash
# Run a Silu program (interpretation)
silu hello.si

# Check if Python code is compatible with Silu
silu check program.py

# Interactive one-liner
silu interpret --source "print('Hello, World!')"
```

Hello world (`hello.si`):

```python
name = "Silu"
version = 1.0

print("Hello from", name, version)

def greet(person):
    return "Welcome to " + person + "!"

print(greet("Silu Programming"))
```

## Execution Modes

| Command | What it does |
|---|---|
| `silu program.si` | Interpret source directly |
| `silu check program.py` | Verify Python compatibility, with precise error reasons |
| `silu ir program.si --output program.ir.json` | Generate IR (JSON or Python-literal format) |
| `silu exec program.ir.json` | Execute IR directly |
| `silu to-source program.ir.json` | Convert IR back to readable source |
| `silu symbolic program.si` | Symbolic execution analysis |
| `silu llvm program.ir.json --output program.ll` | Lower IR to LLVM IR |

### Symbolic Execution

```bash
silu symbolic symbolic_demo.si
```

For each function the executor reports every feasible path: its conditions, return value, and concrete test inputs that reach it. With Z3 installed, path constraints are solved exactly; without it, the executor still runs with graceful degradation.

### Native Compilation

```bash
silu ir program.si --output program.ir.json   # Silu IR
silu llvm program.ir.json --output program.ll # LLVM IR
llc program.ll -o program.s                   # Assembly
clang program.s -o program                    # Executable
./program
```

Type annotations drive the native representation: annotated `int` /
`float` / `bool` scalars compile to unboxed machine values,
`list[int]` / `list[float]` to raw element arrays and
`dict[int, int]` / `dict[int, float]` to a machine-word hash dict —
no PyObject boxing on those paths. Unannotated scalars get the same
treatment when a conservative inference proves every assignment to a
name produces one same type. Across 11 benchmark programs (including
five Benchmarks Game classics) the compiled binaries average **1.0x
hand-written Rust and ~14x CPython**; see
[benchmarks/README.md](benchmarks/README.md) for the full table and
methodology.

### Analyzing C Programs (experimental)

The same IR and symbolic-execution toolchain can consume C source via pycparser:

```bash
# C source → Silu-format IR → symbolic paths / test cases
python get_ret_from_json.py my_program.c      # compare IR execution vs compiled C
python run_symbolic_tool.py my_program.c.ir.json
```

This is currently used to analyze embedded/automotive-style state machines (see the `car_*_core*.c` examples and `ir_generator_for_c.py`).

## Language Features

- **Data types**: int, float, str, bool, bytes, list, dict
- **Control flow**: if/elif/else, while, for (with `range()`), match/case with full structural pattern matching (value, sequence, mapping, or, guard, capture, star patterns)
- **Assignment**: simple, chained (`a = b = 1`), and tuple unpacking (`for key, value in d.items()`)
- **Functions**: user-defined functions, default arguments, and pure closures (read-only capture of the defining scope)
- **Built-ins**: `print`, `type`, `isinstance`, type conversions, `len`, dictionary methods (`.keys()`, `.values()`, `.items()`)
- **Safety**: built-in memory protection against runaway sequence multiplication and oversized `range()`/`extend()` operations

See the [Language Features guide](docs/language_features.md) for the complete syntax reference.

## Project Layout

```
silu/                    # The language implementation package
├── cli.py               # Unified command-line interface
├── interpreter.py       # AST interpreter
├── ir_generator.py      # AST → Silu IR
├── ir_interpreter.py    # Direct IR execution
├── ir_to_source.py      # IR → source (round-trip)
├── symbolic_executor.py # Symbolic execution engine (+ silu/symbolic/)
└── silu_ir_to_llvm.py   # Silu IR → LLVM IR
tests/                   # 340+ pytest tests
docs/                    # Technical documentation
examples/                # Demo programs
ir_generator_for_c.py    # C → Silu IR (pycparser-based)
```

## Documentation

- [AI Development Plan](docs/plan.md) — long-term reasoning roadmap and benchmarks
- [CLI Usage Guide](docs/cli_usage.md) — complete command-line reference
- [Language Features](docs/language_features.md) — syntax and examples
- [IR Design](docs/simple_ir_design.md) — intermediate representation format
- [Symbolic Execution](docs/symbolic_execution.md) — program analysis capabilities
- [LLVM IR Generation](docs/llvm_ir_generation.md) — native compilation via LLVM
- [Interpreter Specification](docs/interpreter_spec.md) — core implementation details
- [Development Guide](docs/development.md) — setup, testing, and contributing

## Development

```bash
uv sync && uv pip install -e .  # Setup

make test    # Run all tests
make cov     # Tests with coverage
make fmt     # Format with ruff
```

Contributions are welcome! See the [Development Guide](docs/development.md).

## License

MIT License — see [LICENSE](LICENSE).
