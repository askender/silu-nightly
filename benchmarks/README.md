# Benchmarks

Four-way speed comparison: the Silu tree-walking interpreter
(`silu interpret`, itself a Python program), **CPython running the
identical files directly** (Silu syntax is a Python subset, so no
translation is involved), the compiled native binaries
(`silu ir` -> `silu llvm` -> `clang`), and **hand-written Rust
mirrors** of the same programs (benchmarks/rust, checked for identical
output before timing).

## Usage

```bash
python benchmarks/run_benchmarks.py          # all programs, 3 runs each
python benchmarks/run_benchmarks.py --runs 5 # more repetitions
python benchmarks/run_benchmarks.py --filter fib
```

Each program is first verified: the compiled binary's output must match
the interpreter's output exactly, otherwise the row is marked MISMATCH
and should not be trusted for timing.

## Measured results (Apple Silicon, CPython 3.13 / Rust 1.89, 2026-10)

Binaries below are built with the default typed codegen
(SILU_CODEGEN=typed), where `int`/`float`/`bool` annotations compile
to unboxed i64/double/i1 stack values.

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 6.38s | 0.100s | 0.007s | 0.004s | 14.6x | 0.6x |
| fib(24) recursive calls | 2.17s | 0.043s | 0.004s | 0.004s | 11.5x | 0.9x |
| float (200k float ops) | 4.19s | 0.062s | 0.007s | 0.004s | 9.4x | 0.6x |
| list (30k append + iterate) | 0.66s | 0.040s | 0.010s | 0.004s | 4.1x | 0.4x |
| dict (20k writes + lookups) | 0.43s | 0.037s | 0.007s | 0.004s | 5.4x | 0.5x |
| string (3k concats) | 0.21s | 0.036s | 0.005s | 0.003s | 7.7x | 0.7x |

Geometric mean: **~200x vs silu-int, 8x vs CPython, 0.6x vs
hand-written Rust**. Startup baselines: silu-int ~0.18s, cpython
~0.03s, binary ~0.003s. All benchmark programs are written in
statically-typed style (`x: int = 0`, `def fib(n: int) -> int`), which
the compiler consumes without inference.

## Notes

- Under the dynamic backend the binary used to LOSE the scalar
  workloads to CPython (arith 0.8x, float 0.7x) because every
  intermediate value was a heap-allocated PyObject. The typed backend
  removes that malloc entirely: scalar loops now run 6-16x faster
  than CPython, and every workload is above it.
- Against hand-written Rust the typed backend reaches 0.9x on the
  fib recursion (effectively at parity) and 0.4-0.7x elsewhere. The
  remaining gap is structural: Python-semantics floor division and
  overflow/zero panics add checks Rust release builds omit, and
  container elements are still boxed PyObjects.
- The Rust mirrors follow Python semantics exactly (s = s + "x"
  allocates per step, not push_str) so the comparison is like-for-like.
