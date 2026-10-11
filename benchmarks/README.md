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

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 6.40s | 0.099s | 0.004s | 0.004s | 27.0x | 1.1x |
| fib(24) recursive calls | 2.18s | 0.043s | 0.004s | 0.004s | 11.9x | 1.0x |
| float (200k float ops) | 4.16s | 0.062s | 0.004s | 0.004s | 15.9x | 1.1x |
| list (30k append + iterate, `list[int]`) | 0.66s | 0.039s | 0.007s | 0.004s | 5.7x | 0.5x |
| dict (20k writes + lookups) | 0.43s | 0.037s | 0.005s | 0.004s | 7.2x | 0.8x |
| string (3k concats) | 0.21s | 0.033s | 0.004s | 0.004s | 8.2x | 0.9x |

Geometric mean: **~278x vs silu-int, 10.9x vs CPython, 0.9x vs
hand-written Rust** - the scalar workloads (arith, fib, float) are at
parity with Rust, string/dict within 10-20%, list trails because the
workload is append+iterate dominated (push path still re-checks
capacity; growth is 2x amortized like Rust's Vec).

Switches: SILU_CODEGEN=dynamic restores the all-PyObject backend;
SILU_CHECKS=0 drops the overflow panics (Rust release semantics;
zero-division checks always stay on, as in Rust).

## Notes

- Under the dynamic backend the binary used to LOSE the scalar
  workloads to CPython (arith 0.8x, float 0.7x) because every
  intermediate value was a heap-allocated PyObject. The typed backend
  removes that malloc entirely: scalar loops now run 6-16x faster
  than CPython, and every workload is above it.
- The scalar workloads reached parity with hand-written Rust after
  three changes: clang -O2 in the pipeline (the biggest single win -
  the earlier runs were accidentally -O0), unboxed i64/double
  arithmetic, and raw-element lists for `list[int]`/`list[float]`.
  Remaining checks we keep deliberately: zero-division panics (Rust
  checks these too) and optional overflow panics (SILU_CHECKS=0 to
  match Rust release exactly).
- // stays Python floor division: it only differs from Rust's
  truncating / on negative operands, and matching Rust there would
  break the language's Python semantics for zero benchmark gain.
- The Rust mirrors follow Python semantics exactly (s = s + "x"
  allocates per step, not push_str) so the comparison is like-for-like.
