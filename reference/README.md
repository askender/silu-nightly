# Rust Reference Implementation (snapshot)

An INDEPENDENT implementation of the Silu compiler front end (and later
the typed converter) in Rust, pinned to a fixed version of the
language's behavior. It exists to answer three questions with data:

1. **Differential oracle** - a fully independent parse->IR->emit chain
   (the four existing planes share one frontend; this one shares
   nothing). Any output divergence on the corpus is a bug on at least
   one side.
2. **Expressiveness calibration** - per-component line counts and
   verbosity hotspots in both directions (where Rust's enums/match win,
   where its ownership/error plumbing costs).
3. **Implicit-spec recovery** - re-implementation under a strict type
   system surfaces everything the current code relies on "dynamic
   behavior that happens to hold".

## Contract

- **Pinned version**: silu 1.16.2, commit 87df40f. The Rust code
  implements THIS behavior, not whatever main does later. No tracking
  obligation: divergences from future Silu are expected and fine.
- **Corpus**: the 19-file parity corpus (15 benchmarks + calc +
  ir_interp + silu_fe + typed_codegen_flat) for IR comparison; the
  same minus the flat converter for .ll comparison (python plane too
  slow on it).
- **Comparison discipline**: IR JSON must be BYTE-identical; .ll must
  be byte-identical on the corpus (the existing gates already hold the
  two current planes to this bar - the Rust plane joins the same bar).
  A divergence is triaged to exactly one of: Rust bug / Silu bug /
  corpus program outside the pinned subset.
- **Fixed runtime prefix**: the ~350KB pyobj runtime in every emitted
  .ll is a strict prefix constant (the siluc driver already caches it
  as such). The Rust converter embeds it verbatim from
  `rt.ll` - the 4.8k-line runtime emitters are NOT reimplemented.

## Non-goals (deliberate)

- NOT the product compiler; NOT a bootstrap dependency.
- NOT kept in sync with Silu evolution.
- NOT shipped in any release artifact.

## Layout

- `diff_harness.py` - plane-vs-plane differential runner. Planes are
  commands; the harness predates the Rust code and self-validates by
  comparing the two existing planes (which must be byte-identical -
  the same bar the CI gates enforce).
- `rust/` - the Rust implementation (from R1 onward).

## Stages

- R0 (this): contract + harness, self-validated on existing planes.
- R1: Rust front end; IR byte-parity on the 19-file corpus.
- R2: Rust typed converter + embedded runtime prefix; .ll byte-parity.
- R3: calibration report (line counts per component, verbosity
  hotspots, found-bug list, language-design recommendations).

## R2 groundwork (verified anatomy of the pinned build)

The full .ll layout, confirmed constant-across-corpus by cross-file
common-prefix extraction:

    [ const 365,264 bytes: module header + 27 extern declares +
      __silu_line + ALL runtime functions and runtime string globals ]
    [ variable: user function defines, main, user string globals ]

- `rust/const_prefix.ll` is the constant (regenerate for a new pin by
  compiling two different corpus files and taking the common prefix).
- User string globals continue the module-wide counter (fib starts at
  str_298 for this pin; runtime consumed 0..297).
- Naming rules that byte-parity depends on (llvmlite_text layer):
  per-function NameScope; unnamed values dedupe as ".N"; block names
  dedupe with ".N" suffix on repeat within the function; empty-name
  registrations still consume a ".N" slot (a function with no args
  still burns 3 slots before its first visible value); instruction
  formatting keeps llvmlite's trailing separator spaces, rstripped
  only at line end.
- Promoted static functions compile `internal ... alwaysinline` with
  raw-ABI params (fib: `define internal i64 @"fib"(i64 %".1")`).
