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
| arith (300k loop, mod/floordiv) | 5.05s | 0.103s | 49x |
| fib(24) recursive calls | 1.70s | 0.027s | 64x |
| float (200k float ops) | 3.22s | 0.075s | 43x |
| list (30k append + iterate) | 0.52s | 0.011s | 47x |
| dict (20k writes + lookups) | 0.35s | 0.028s | 12x |
| string (3k concats) | 0.17s | 0.004s | 43x |

Geometric mean: **39x**. Startup baseline: interpreter ~0.14s
(Python process), binary ~0.003s.

## Notes

- The dict gap is small because the compiled runtime currently uses a
  linear-scan entry list; the interpreter uses Python's real hash tables.
  Replacing it with a hash table would widen the dict speedup further.
- The compiled runtime allocates a PyObject per intermediate value
  (tagged-union interpreter-style), so the ceiling is not yet native
  codegen quality; a future static-typing pass can lift arithmetic off
  the heap entirely.
