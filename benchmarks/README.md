# Benchmarks

Three-way speed comparison on the same programs: the Silu tree-walking
interpreter (`silu interpret`, itself a Python program), **CPython
running the identical files directly** (Silu syntax is a Python subset,
so no translation is involved), and the compiled native binaries
(`silu ir` -> `silu llvm` -> `clang`).

## Usage

```bash
python benchmarks/run_benchmarks.py          # all programs, 3 runs each
python benchmarks/run_benchmarks.py --runs 5 # more repetitions
python benchmarks/run_benchmarks.py --filter fib
```

Each program is first verified: the compiled binary's output must match
the interpreter's output exactly, otherwise the row is marked MISMATCH
and should not be trusted for timing.

## Measured results (Apple Silicon, CPython 3.13, 2026-10)

Binaries below are built with the default typed codegen
(SILU_CODEGEN=typed), where `int`/`float`/`bool` annotations compile
to unboxed i64/double/i1 stack values.

| program | silu-int | cpython | binary | vs silu-int | vs cpython |
|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 5.01s | 0.078s | 0.005s | 1021x | 15.9x |
| fib(24) recursive calls | 1.72s | 0.034s | 0.003s | 588x | 11.5x |
| float (200k float ops) | 3.29s | 0.050s | 0.008s | 398x | 6.0x |
| list (30k append + iterate) | 0.52s | 0.031s | 0.009s | 57x | 3.4x |
| dict (20k writes + lookups) | 0.35s | 0.030s | 0.006s | 60x | 5.3x |
| string (3k concats) | 0.17s | 0.028s | 0.005s | 38x | 6.3x |

Geometric mean: **177x vs silu-int, 7.1x vs CPython**. With the older
all-PyObject backend (SILU_CODEGEN=dynamic) the same programs measure
48x / 1.9x. Startup baselines: silu-int ~0.14s, cpython ~0.03s,
binary ~0.003s. All benchmark programs are written in
statically-typed style (`x: int = 0`, `def fib(n: int) -> int`), which
the compiler consumes without inference.

## Notes

- Under the dynamic backend the binary used to LOSE the scalar
  workloads to CPython (arith 0.8x, float 0.7x) because every
  intermediate value was a heap-allocated PyObject. The typed backend
  removes that malloc entirely: scalar loops now run 6-16x faster
  than CPython, and every workload is above it.
- The remaining ceiling: containers still box every element, and
  strings are byte arrays without unicode semantics.
