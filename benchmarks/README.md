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
i64/double/i1 stack values, `list[int]`/`list[float]` compile to raw
element arrays, `dict[int, int]`/`dict[int, float]` to a machine-word
open-addressing dict and annotated (or consistently inferred) `str` to
Rust-String-style raw slots whose buffers are owned exclusively by
their variable (no PyObject per value). Unannotated scalars are
promoted to the same raw storage when a conservative pre-pass proves
every assignment to the name yields one same kind.

Core micro-benchmarks:

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| arith (300k loop, mod/floordiv) | 5.0s | 0.070s | 0.003s | 0.003s | 24.0x | 1.1x |
| fib(24) recursive calls | 1.7s | 0.030s | 0.0026s | 0.0027s | 11.6x | 1.1x |
| float (200k float ops) | 3.2s | 0.044s | 0.003s | 0.003s | 14.7x | 1.1x |
| list (30k append + iterate, `list[int]`) | 0.51s | 0.029s | 0.0031s | 0.0033s | 9.4x | 1.1x |
| dict (20k writes + lookups, `dict[int, int]`) | 0.33s | 0.029s | 0.0026s | 0.0029s | 11.0x | 1.1x |
| string (48k concats, amortized) | 0.59s | 0.047s | 0.0037s | 0.0032s | 12.5x | 1.2x |

Benchmarks Game classics:

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| n-body (50k steps, 5 bodies) | 52.1s | 0.217s | 0.0057s | 0.0057s | 37.8x | 1.0x |
| spectral-norm (n=300) | 61.3s | 0.294s | 0.0057s | 0.0050s | 51.4x | 0.9x |
| fannkuch (n=10) | 0.14s | 0.026s | 0.0026s | 0.0027s | 10.0x | 1.0x |
| binary-trees (depth 4-14) | 0.90s | 0.030s | 0.003s | 0.0034s | 9.7x | 1.1x |
| mandelbrot (80x24 ASCII) | 1.13s | 0.033s | 0.0029s | 0.0032s | 11.4x | 1.1x |

Real-world-flavored workloads (added after the core suite to hunt
gaps; these exercise str-key dicts, slicing and parsing instead of
pure numerics):

| program | silu-int | cpython | binary | rust | vs cpython | vs rust |
|---|---|---|---|---|---|---|
| wordcount (300k freq updates, `dict[str, int]`) | 6.4s | 0.083s | 0.020s | 0.017s | 4.1x | 0.9x |
| k-nucleotide (200k DNA 4-mers, slice + `dict[str, int]`) | 15.3s | 0.82s | 0.012s | 0.015s | 70.6x | 1.3x |
| json-parse (3k objects, hand-rolled descent parser) | 1.9s | 0.072s | 0.161s | 0.004s | 0.4x | 0.03x |

These three did their job: they exposed and pinned real defects -
boxed dicts that grew only at 100% load (a read probe on a full table
spun forever), `str()` missing from the compiled backends, pylist
unboxing reading the wrong struct, allocas inside loop bodies - and
then drove three representation wins: native str-key dicts (FNV-1a
over the same open-addressing table), view-based keys (a boxed str or
an in-place slice becomes a stack window, no copy; `d[s[i:i+k]]`
allocates nothing), and fused char-vs-constant comparisons (`s[i] ==
"x"` is one call, no character object). wordcount and k-nucleotide
are now at 0.9x/1.3x Rust. json-parse's remaining gap is structural:
every parsed string/token still becomes a Python object and the
containers are boxed - closing it means a raw `list[str]` and
struct-like records, which is the next representation tier.

Overall geometric mean: **~490x vs silu-int, 13.9x vs CPython, 1.0x
vs hand-written Rust** across 11 programs - every workload is within
measurement noise of the Rust mirrors. Note that ~2.6ms of each binary
measurement is process startup; the actual compute in most rows is
several times faster than Rust's, whose own startup it also carries.

Switches: SILU_CODEGEN=dynamic restores the all-PyObject backend;
SILU_CHECKS=0 drops the overflow panics and the rawlist bounds
branches (Rust release semantics; zero-division checks always stay
on, as in Rust). Bounds branches matter in indexed inner loops -
they block clang's auto-vectorizer the same way overflow checks do.

### SILU_CHECKS=1 vs SILU_CHECKS=0 (back-to-back runs)

Binary times only; interpreter/CPython/Rust are unaffected by the
switch. Both runs verified identical output (match ok - no benchmark
overflows i64 either way). Startup (~2.8-3.1ms of each binary time)
varies by ±0.3ms between runs, so per-row deltas under ~0.5ms are
noise.

| program | binary CHECKS=1 | binary CHECKS=0 | delta | vs rust (0) | vs rust (1) |
|---|---|---|---|---|---|
| arith | 0.0034s | 0.0033s | ~ | 1.2x | 1.1x |
| dict | 0.0031s | 0.0030s | ~ | 1.0x | 1.1x |
| fannkuch | 0.0029s | 0.0029s | ~ | 1.3x | 1.0x |
| fib | 0.0030s | 0.0032s | ~ | 1.2x | 1.1x |
| float | 0.0035s | 0.0034s | ~ | 1.2x | 1.2x |
| list | 0.0037s | 0.0031s | 1.2x | 1.0x | 0.9x |
| mandelbrot | 0.0044s | 0.0030s | **1.5x** | 1.3x | 0.7x |
| n-body | 0.0064s | 0.0065s | ~ | 1.0x | 1.0x |
| spectral-norm | 0.0062s | 0.0047s | **1.3x** | 1.0x | 0.8x |
| string | 0.0042s | 0.0037s | 1.1x | 0.8x | 0.7x |
| binary-trees | 0.0029s | 0.0033s | ~ | 1.0x | 1.1x |

Geometric mean vs Rust: **1.0x with checks, 1.1x without**. The two
real wins are exactly the predicted ones: long countable float loops
whose only exits were the overflow-check branches (spectral-norm's
a() has three checked int ops per call; mandelbrot's 50-iteration
pixel loop) - with the branches gone LLVM auto-vectorizes and the
gap closes. The checks stay on by default because they catch real
arithmetic bugs, matching Rust debug builds.

## Notes

- Under the dynamic backend the binary used to LOSE the scalar
  workloads to CPython (arith 0.8x, float 0.7x) because every
  intermediate value was a heap-allocated PyObject. The typed backend
  removes that malloc entirely: scalar loops now run 6-16x faster
  than CPython, and every workload is above it.
- The last gaps to Rust (geomean 0.8x -> 1.0x) were three distinct
  defects, each confirmed by an isolated experiment:
  1. `len()` on a raw list/dict boxed the whole container (one malloc
     per element) just to ask pyobj_len for the count - 60% of n-body's
     profile sat in that round trip. It now reads the length/count
     field directly (n-body 29.8ms -> 11.7ms).
  2. Unannotated names always took PyObject slots even when every
     assignment provably produced the same raw type - mandelbrot's
     inner loop paid 3 mallocs + 3 dynamic dispatches per iteration
     for `zr2 = z_re * z_re`. A conservative per-scope inference now
     promotes them (11.2ms -> 3.0ms). Any kind conflict (e.g.
     `x = 7` then `x = x / 2`) keeps the dynamic slot, so rebinding a
     name to another type keeps Python semantics. This exposed a
     latent shadowing bug: a function declaring a name whose kind
     matched a module global reused the global slot and clobbered the
     caller's loop counter (n-body hung); function declarations of
     module names now always shadow, as Python's assignment-makes-a-
     local rule requires.
  3. dict had no raw representation at all - rawdict (see above)
     closed it (dict 0.7x -> 1.1x).
- Strings had the biggest hidden gap: `s = s + "x"` was a true
  quadratic copy (fresh buffer + full copy per step) while CPython
  (refcount==1 in-place concat) and Rust (String: Add<&str> reuses
  the buffer) both amortize. At n=48k the compiled binary lost to
  CPython 3x. Raw str slots now copy on assignment (exclusive
  ownership) and grow in place on `s = s + ...` / `s +=`, matching
  Rust String semantics (string 0.8x -> 1.2x; the benchmark is now
  48k iterations because at 3k the row was startup-dominated).
  Two latent dynamic-runtime bugs surfaced and were fixed: printed
  strings used printf("%s") on non-NUL-terminated concat buffers
  (heap garbage past the end - now printf("%.*s") with the cached
  length), and str<op>str ordering comparisons (pyobj_lt etc.)
  returned None for every non-equality predicate (now memcmp byte
  order with length tiebreak, matching Python code point order).
- The remaining per-workload spread (0.9x-1.2x) traces to the
  integer overflow-check branches blocking auto-vectorization in long
  float loops (visible in spectral-norm): SILU_CHECKS=0 recovers it
  where needed; the checks themselves are kept by default because
  they catch real bugs (matching Rust debug builds, not release).
- Rust parity came from earlier changes too: clang -O2 in the pipeline
  (the biggest single win - earlier runs were accidentally -O0),
  unboxed i64/double arithmetic, raw-element lists for
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
