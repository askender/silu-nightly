# Silu Programming Language

**English** | [简体中文](README_zh.md)

**Python syntax in, native binaries out.** Silu (斯路) takes a
Python-compatible syntax subset and gives the same program three
runtimes: a reference interpreter, a Z3-backed symbolic executor, and
an LLVM compiler whose output runs at hand-written-Rust speed.

| program | CPython | silu binary | Rust |
|---|---|---|---|
| n-body (50k steps) | 0.21s | 0.0065s | 0.0075s |
| spectral-norm (n=300) | 0.29s | 0.0068s | 0.0056s |
| string (48k concats) | 0.049s | 0.0032s | 0.0031s |
| mandelbrot (80x24) | 0.044s | 0.0034s | 0.0033s |

Across 14 benchmarks (including five Benchmarks Game classics and
three real-world-flavored workloads) the
compiled binaries average **~1.0x hand-written Rust, ~16x CPython,
and ~600x the tree-walking interpreter** —
[benchmarks/README.md](benchmarks/README.md) has the full table and
methodology.

## Why Silu

- **Rust-speed native compilation** — Type annotations drive unboxed
  machine representations (`int`/`float`/`bool` scalars,
  `list[int]`/`list[float]` arrays, `dict[int, int]`/`dict[int, float]`
  hash maps, `str` as Rust-String-style owned buffers), and a
  conservative inference gives unannotated code the same treatment
  whenever it is provably safe. Python semantics are preserved
  everywhere the proof does not reach.
- **Symbolic execution built in** — Explore all execution paths of a
  function, generate path conditions with Z3, and produce concrete
  test inputs automatically. No other Python-subset compiler ships
  this combination of speed and formal analysis.
- **One IR, many backends** — Every program lowers to a small
  tuple-based IR that can be interpreted, converted back to source,
  symbolically analyzed, or compiled to native code via LLVM.
- **Python-compatible subset** — Silu reuses Python's parser, so most
  simple Python programs run unchanged. `silu check program.py` tells
  you exactly what is (and isn't) supported.
- **Beyond Silu source** — The same IR and symbolic-execution
  toolchain also accepts **C programs** (via pycparser), enabling
  path analysis and test-case generation for existing C code.

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
| `silu build program.si -o program` | One-command native executable |
| `silu verify program.si` | Diff compiled output against the interpreter |

### Symbolic Execution

```bash
silu symbolic symbolic_demo.si
```

For each function the executor reports every feasible path: its
conditions, return value, and concrete test inputs that reach it.
With Z3 installed, path constraints are solved exactly; without it,
the executor still runs with graceful degradation.

### Native Compilation

```bash
silu build program.si -o program   # one command: IR -> LLVM -> clang
./program
```

(the step-by-step pipeline - `silu ir`, `silu llvm`, `llc`, `clang` -
remains available for inspecting each stage)

Type annotations drive the native representation: annotated `int` /
`float` / `bool` scalars compile to unboxed machine values,
`list[int]` / `list[float]` to raw element arrays,
`dict[int, int]` / `dict[int, float]` to a machine-word hash dict
(open addressing with tombstones; `del d[k]` / `d.pop(k)` run
natively and a load-factor rehash compacts deleted entries) and
annotated `str` to Rust-String-style owned buffers (assignment
copies, append grows in place, overwrite frees the old buffer) — no
PyObject boxing on those paths. Unannotated scalars get the same
treatment when a conservative inference proves every assignment to a
name produces one same type, and a two-pass signature analysis
promotes whole functions: a parameter that is never rebound and
receives one raw type at every call site arrives unboxed, and a
return whose expressions all resolve to one raw type returns unboxed
(conflicts keep the dynamic ABI, so Python rebinding semantics are
preserved). Strings follow Python's code point semantics throughout —
`len`, `s[i]`, `s[a:b]` (stepped slices included), `sub in s` and
`for ch in s` all run natively and agree with CPython on multi-byte
text. `SILU_CHECKS=0` switches overflow and bounds panics to the
Rust release profile for the last few percent in indexed inner loops.

### Analyzing C Programs (experimental)

The same IR and symbolic-execution toolchain can consume C source via pycparser:

```bash
# C source → Silu-format IR → symbolic paths / test cases
python get_ret_from_json.py my_program.c      # compare IR execution vs compiled C
python run_symbolic_tool.py my_program.c.ir.json
```

This is currently used to analyze embedded/automotive-style state machines (see the `car_*_core*.c` examples and `ir_generator_for_c.py`).

## Language Features

- **Data types**: int, float, str (full code point semantics), bool, bytes, list, dict
- **Control flow**: if/elif/else, while, for (with `range()`), match/case (interpreters: full structural patterns; compiled: value/or/capture/wildcard/guard), enums (`class Color(Enum): RED = 1` - bare int discriminants, Rust-style)
- **Assignment**: simple, chained (`a = b = 1`), tuple unpacking (`for key, value in d.items()`), subscript delete (`del d[k]`)
- **Operators**: arithmetic/comparison/bitwise, membership `in` / `not in` (strings, lists, dicts), string indexing and slicing with steps
- **Functions**: user-defined functions, default arguments, and pure closures (read-only capture of the defining scope)
- **Classes**: every `class` is a record type with dataclass semantics (the Rust `struct` + `impl` analog) — annotated fields, positional/keyword construction with defaults, methods with `self`; compiles to a flat 8-byte-slot heap block with direct field-offset access (no vtable, no boxing)
- **Built-ins**: `print`, `type`, `isinstance`, type conversions, `len`, `ord`/`chr`, `input`, `read_file`/`read_stdin`, dict methods (`.keys()`, `.values()`, `.items()`, `.get()`, `.pop()`, `.setdefault()`, `.clear()`), list methods (`.append()`, `.pop()`, `.clear()`), string methods (`.split()`, `.strip()`, `.startswith()`, `.endswith()`, `.isdigit()`, `.isalpha()`, `.isspace()`)
- **Safety**: bounds/overflow/zero-division panics by default (Rust debug profile), optional release profile via `SILU_CHECKS=0`, plus memory protection against runaway sequence multiplication and oversized `range()`/`extend()` operations

See the [Language Features guide](docs/language_features.md) for the complete syntax reference.

## Project Layout

```
silu/                    # The language implementation package
├── cli.py               # Unified command-line interface
├── interpreter.py       # AST interpreter (reference semantics)
├── ir_generator.py      # AST → Silu IR
├── ir_interpreter.py    # Direct IR execution
├── ir_to_source.py      # IR → source (round-trip)
├── symbolic_executor.py # Symbolic execution engine (+ silu/symbolic/)
├── typed_codegen.py     # Silu IR → LLVM IR (typed backend, main)
└── silu_ir_to_llvm.py   # Silu IR → LLVM IR (dynamic base runtime)
tests/                   # 630+ pytest tests
benchmarks/              # 14-program suite vs CPython and Rust mirrors
docs/                    # Technical documentation
examples/                # Demo programs
ir_generator_for_c.py    # C → Silu IR (pycparser-based)
```

## Documentation

- [AI Development Plan](docs/plan.md) — long-term reasoning roadmap and benchmarks
- [CLI Usage Guide](docs/cli_usage.md) — complete command-line reference
- [Language Features](docs/language_features.md) — syntax and examples
- [Semantics Contract](docs/semantics.md) — where Silu matches Python and where it deliberately differs (i64, ownership, checks)
- [IR Design](docs/simple_ir_design.md) — intermediate representation format
- [Symbolic Execution](docs/symbolic_execution.md) — program analysis capabilities
- [LLVM IR Generation](docs/llvm_ir_generation.md) — native compilation via LLVM
- [Interpreter Specification](docs/interpreter_spec.md) — core implementation details
- [Development Guide](docs/development.md) — setup, testing, and contributing

## Vision & AI Roadmap

Silu's long-term bet is that rigorous logical reasoning and learned
probabilistic reasoning belong in one language runtime. The concrete
foundation is already in place — a control-flow-graph IR, an SMT-backed
symbolic executor, and a native compiler whose output is trustworthy
enough to verify against the reference interpreter. On top of that the
roadmap layers probabilistic reasoning, self-correction, and
hypothesis-driven experimentation; see the
[AI Development Plan](docs/plan.md) for the staged milestones and how
each stage reuses the verification toolchain below it.

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
