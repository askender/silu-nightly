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

Binaries are built with the default typed codegen (SILU_CODEGEN=typed,
clang -O2), where `int`/`float`/`bool` annotations compile to unboxed
i64/double/i1 stack values and `list[int]`/`list[float]` compile to
raw element arrays (no PyObject per element).

Core micro-benchmarks:

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 4.91s | 0.079s | 0.003s | 0.003s | 30.6x | 1.1x |
| fib(24) recursive calls | 1.65s | 0.032s | 0.0025s | 0.003s | 12.7x | 1.1x |
| float (200k float ops) | 3.27s | 0.048s | 0.003s | 0.003s | 16.3x | 1.1x |
| list (30k append + iterate, `list[int]`) | 0.51s | 0.029s | 0.004s | 0.003s | 7.6x | 0.7x |
| dict (20k writes + lookups) | 0.33s | 0.027s | 0.004s | 0.003s | 7.1x | 0.8x |
| string (3k concats) | 0.15s | 0.025s | 0.003s | 0.003s | 8.4x | 0.9x |

Benchmarks Game classics:

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| n-body (50k steps, 5 bodies) | 52.0s | 0.283s | 0.021s | 0.006s | 13.6x | 0.3x |
| spectral-norm (n=300) | 61.3s | 0.332s | 0.006s | 0.004s | 59.1x | 0.7x |
| fannkuch (n=10) | 0.14s | 0.026s | 0.002s | 0.003s | 10.9x | 1.2x |
| binary-trees (depth 4-14) | 0.87s | 0.030s | 0.002s | 0.003s | 12.2x | 1.4x |
| mandelbrot (80x24 ASCII) | 1.12s | 0.034s | 0.009s | 0.003s | 3.9x | 0.4x |

Overall geometric mean: **~413x vs silu-int, 12.5x vs CPython, 0.8x
vs hand-written Rust** across 11 programs. Six workloads are at or
above Rust parity (arith 1.1x, fib 1.1x, float 1.1x, fannkuch 1.2x,
binary-trees 1.4x, and dict/string within 20%).

Switches: SILU_CODEGEN=dynamic restores the all-PyObject backend;
SILU_CHECKS=0 drops the overflow panics (Rust release semantics;
zero-division checks always stay on, as in Rust).

## Notes

- Under the dynamic backend the binary used to LOSE the scalar
  workloads to CPython (arith 0.8x, float 0.7x) because every
  intermediate value was a heap-allocated PyObject. The typed backend
  removes that malloc entirely: scalar loops now run 6-16x faster
  than CPython, and every workload is above it.
- Rust parity came from four changes: clang -O2 in the pipeline (the
  biggest single win - earlier runs were accidentally -O0), unboxed
  i64/double arithmetic, raw-element lists for
  `list[int]`/`list[float]`, and a by-value rawlist_push with one
  capacity check (the first version round-tripped every element
  through a stack slot + memcpy + a redundant second grow check).
  Fixing that also uncovered a real bug: GEP on an i8* with an
  element index advances BY BYTES, so element 1 landed at offset 1 -
  list reads returned garbage that the sum-based benchmark masked.
  All rawlist addressing now bitcasts to i64* first.
- Remaining deliberate differences: zero-division panics (Rust has
  them too), optional overflow panics (SILU_CHECKS=0), Python floor
  division (negative-operand semantics only).
- // stays Python floor division: it only differs from Rust's
  truncating / on negative operands, and matching Rust there would
  break the language's Python semantics for zero benchmark gain.
- The Rust mirrors follow Python semantics exactly (s = s + "x"
  allocates per step, not push_str) so the comparison is like-for-like.
