# Benchmarks

Speed comparison between the Silu tree-walking interpreter (`silu
interpret`, itself a Python program) and the same programs compiled
to native binaries (`silu ir` -> `silu llvm` -> `clang`).

## Usage

```bash
python benchmarks/run_benchmarks.py          # all programs, 3 runs each
python benchmarks/run_benchmarks.py --runs 5 # more repetitions
python benchmarks/run_benchmarks.py --filter fib
```

Each program is first verified: the compiled binary's output must match
the interpreter's output exactly, otherwise the row is marked MISMATCH
and should not be trusted for timing.

## Measured results (Apple Silicon, macOS, 2026-10)

| program | interpreter | binary | speedup |
|---|---|---|---|
| arith (300k loop, mod/floordiv) | 4.75s | 0.101s | 47x |
| fib(24) recursive calls | 1.60s | 0.025s | 65x |
| float (200k float ops) | 3.11s | 0.074s | 42x |
| list (30k append + iterate) | 0.48s | 0.012s | 39x |
| dict (20k writes + lookups) | 0.32s | 0.007s | 47x |
| string (3k concats) | 0.15s | 0.003s | 44x |

Geometric mean: **46x** (was 39x before the hash-table dict runtime;
the dict workload alone went from 12x to 47x). Startup baseline:
interpreter ~0.12s (Python process), binary ~0.002s. All benchmark
programs are written in statically-typed style (`x: int = 0`,
`def fib(n: int) -> int`), which the compiler accepts without
inference.

## Notes

- The compiled runtime allocates a PyObject per intermediate value
  (tagged-union interpreter-style), so the ceiling is not yet native
  codegen quality; a future static-typing pass can lift arithmetic off
  the heap entirely.
