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

| program | silu-int | cpython | binary | vs silu-int | vs cpython |
|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 4.95s | 0.080s | 0.102s | 48x | 0.8x |
| fib(24) recursive calls | 1.70s | 0.035s | 0.027s | 64x | 1.3x |
| float (200k float ops) | 3.30s | 0.050s | 0.076s | 44x | 0.7x |
| list (30k append + iterate) | 0.52s | 0.031s | 0.011s | 45x | 2.7x |
| dict (20k writes + lookups) | 0.34s | 0.029s | 0.008s | 45x | 3.9x |
| string (3k concats) | 0.17s | 0.028s | 0.004s | 41x | 6.8x |

Geometric mean: **48x vs silu-int, 1.9x vs CPython**. Startup
baselines: silu-int ~0.14s, cpython ~0.03s, binary ~0.003s. All
benchmark programs are written in statically-typed style
(`x: int = 0`, `def fib(n: int) -> int`), which the compiler accepts
without inference.

## Notes

- Against CPython 3.13 the binary wins on container/string workloads
  (dict 3.9x, string 6.8x, list 2.7x) but LOSES on scalar arithmetic
  (arith 0.8x, float 0.7x): CPython's specializing bytecode keeps
  small ints and floats unboxed in its eval loop, while our runtime
  heap-allocates a PyObject for every intermediate value.
- This is exactly what the written static annotations unlock next:
  consuming `x: int` / `acc: float` declarations to emit unboxed i64 /
  double arithmetic would remove the per-operation malloc and pull the
  scalar workloads above CPython.
