# Changelog

All notable changes, organized by version tag.

## v1.x — Self-Hosting Campaign (2026-10-16 → present)

### v1.11.4
single-code-point cache: s[i] stops mallocing (CPython latin-1 model)

- 256-entry lazy pool + cap=-1 immortal sentinel (rawstr_free
  skips), rebinding-safe; multi-byte code points keep the copy path
- llvmlite_text: aggregate None constant now spells
  zeroinitializer (was invalid IR); si twin synced
- jsonparse attribution revised by measurement: construction is
  only 12% of runtime, the per-char 1-byte str allocation was the
  real 5.4ms - pool removes it (9.8 -> 9.0ms official); residual
  is three non-inlined runtime calls per char, recorded as the
  next layer
- S0 probe (sum-type RFC): tagged construction 1.96x vs pyobj
  (tools/probes/), meets the go bar on construction; RFC outcome
  section revised with the 12% finding

### v1.11.3
subscript type inference + sum-type RFC + symbolic phase 1

- type inference: element/value kinds for subscript reads of
  annotated containers (list[int][i] is an int, xs[1:] is a
  container, s[i] a 1-byte str); int/dict paths lose the pyobj box;
  honest negative: the str-element path got slower (0.66x -> 0.61x
  on wordcount) because it exposed rawlist_str_get's copy semantics
  - two heap ops vs one; root fix is borrowed reads / buffer reuse,
  folded into the RFC
- rfc: docs/rfc_sum_types.md - tagged unions for heterogeneous
  containers (16-byte single-block values, rawlist/rawdict tagged
  element families, v1.7.1 borrow discipline generalized), staged
  S0-S4 with a >=2x go/no-go probe
- symbolic phase 1 (roadmap): invariant proofs for the raw families
  - rawstr_append capacity (incl. cap0==0 bootstrap), rawdict slot
  discipline (in-table first probe at every width, 3:2 load trigger
  with doubling, sentinel-safe encoding), utf8 cp bounds; mutation-
  checked

### v1.11.2
quality pass: dead code, docs archive, symbolic roadmap, subprocess coverage, _convert_call split

- dead code: 24 verified-unreferenced functions removed (AST-precise
  scan; visit_*/_execute_* protocol families and llvmlite_text's
  .si-plane references correctly exempted)
- docs: 8 superseded snapshots -> docs/history/; symbolic execution
  kept by decision with docs/symbolic_roadmap.md (Phase 1 raw-family
  invariant proofs, Phase 2 'silu verify', Phase 3 transform
  equivalence)
- coverage: subprocess measurement wired through gates (conftest sets
  COVERAGE_PROCESS_START, repo-root sitecustomize.py) -
  static_gate 0->100%, llvmlite_text 0->84%, runtime_cache 0->72%
- modularization: _convert_call 961 -> 61 lines + 4 _call_* methods
  (byte-identical; fall-through branches via None sentinel)

### v1.11.1
quality pass six-pack: emitters split, metadata, CI layers

- modularization: both runtime emitters split byte-identical
  (_create_raw_list_runtime 3480 -> 30 + 12 _emit_* families,
  _create_dict_runtime 1536 -> 8; panic-string globals promoted to
  self attributes, pure-type constants reconstructed per emitter)
- metadata: pyproject 0.10.0 -> 1.11.0, silu.__version__, silu
  --version, dead mlir dependency dropped
- negative finding: llvmlite_text.py is byte-locked to
  selfhost/llvmlite.si WITHOUT flattening - return annotations enter
  the IR there (func_def slot 6) and the typed backend gives them
  real semantics; the fixed point caught a 3.6KB numbering drift.
  Converter sources are safe (flatten strips annotations). Locked
  copies must stay unannotated.
- negative finding: typed_call <-> typed_codegen clone windows are
  emission idioms, not logic duplication - deliberately not harvested
- interpreter.process_control_flow complexity 52 -> 23 (class/enum
  definition and the for-loop variants extracted)
- repo hygiene: 115 untracked scratch files -> .attic/, build
  artifacts gitignored; working tree clean
- ci: two-layer workflow (fast 1133 tests / gates on dispatch), ruff
  baseline F403/F405 pinned in pyproject - 'ruff check' genuinely
  green

### v1.0.0
COMPLETE SELF-HOSTING: fixed point byte-identical


### v1.1.0
root-cause hardening: loud panics, flatten guards, scoped funcref table, boundary suite


### v1.2.0
modularization step A: runtime-emission methods -> silu/pyobj_runtime.py

- docs: post-self-hosting roadmap - P1 quality depth (scope audit CI, symbolic-execution invariants), P2 modularization plan (four byte-identical steps), P3 language gaps; trap list consolidated
- scope-discipline CI audit: static AST checks, mutation-tested

### v1.3.0
symbolic invariant proofs for the pyobj container runtime


### v1.4.0
runtime .o cache: silu build 0.72s -> 0.32s (2.2x), opt-in via SILU_RUNTIME_CACHE=1

- bench harness: three-toolchain timing (interp / silu build / rustc), converter stage isolated both planes

### v1.5.0
docs: post-self-hosting engineering summary - v1.1.0 through v1.5.0 (hardening, modularization step A, symbolic proofs, 2.2x compile cache, pyobj-free static print); three-plane speed table; pyobj consumption census

- print specialisation: static scalars/strings print without pyobj boxes
- docs: RFC on compiler staticisation - measured 1% raw-param potential today, three-tier value ranking, sum-type path deferred

### v1.5.1
lazy CLI imports + Silu in-body import syntax (v1.5.1)

- bench: four-pipeline compile comparison + rustc cache verdict

### v1.6.0
full-pipeline self-hosting: front-end completion + pipeline fixed point (v1.6.0)

- silu_fe: fold subscript aug-assign into aug_assign with subscript target
- silu_fe: parse 'import x as y' and register the alias (fe_register_alias)

### v1.6.1
siluc: the monolithic self-hosted compiler - one process, source to LLVM IR (v1.6.1)

- benchmarks: C twins for fib/mandelbrot (clang plane for language comparisons)

### v1.6.2
link-time dead_strip: binaries keep only referenced runtime functions


### v1.6.3
static gate: --static turns silent pyobj fallback into a loud error


### v1.7.0
match class patterns with narrowing: the cheap sum-type route (v1.7.0)


### v1.7.1
borrowed str parameters: jsonparse 78.7ms -> 8.3ms (9.5x, rust 1.9x)


### v1.8.0
siluc: a C driver - one command, zero Python, rustc-shaped (v1.8.0)

- benchmarks: fresh four-plane report - silu native 0.9x vs rust (geomean)
- ir interpreter: subscript/attribute aug-assign targets, n-ary and/or
- subset completion: set.discard + dict/set comprehensions on all planes
- typed backend: rawlist call aliasing writeback + instance-word locals
- daemon: measured a wash, removed; negative result recorded
- benchmarks: post-P0..P3 four-plane report

### v1.9.0
C ABI: @export + from c import - Silu calls C, C/Rust call Silu (v1.9.0)


### v1.9.1
quality: ruff-clean (F401/F841), tools/attic split

- docs: C interop + siluc usage in README (en/zh) and docs/interop.md
- docs: speed benchmarks page - run + compile tables, evolution, methodology
- docs: memory management - two disciplines, measured, and why no borrow checker
- docs: Rust vs Silu memory-safety comparison table in memory.md
- modularization step B: typed_expr.py mixin split (byte-identical)

### v1.10.0
quality: ruff tail + return-type annotations on the mixin families

- modularization step C: typed_match.py + typed_call.py (byte-identical)

### v1.11.0
modularization step D: _convert_node_scoped dispatch extraction (byte-identical)

- _convert_node_scoped 1891 -> 762 lines: the five largest branches
  (assign/ann_assign 386, subscript 309, aug_assign 170,
  subscript_assign 170, comprehension 98) extracted to _conv_* methods
  with one-line delegations; dynamic-getattr dispatch rejected (typed
  backend does not lower getattr calls; sequential delegation is fully
  inside the verified .si subset)
- acceptance: 16-program corpus .ll byte-identical across the refactor,
  converter + pipeline fixed points re-established, native parity green

## v0.x — Pre-Self-Hosting Foundation

Early development: interpreter, IR generator, symbolic executor,
typed backend construction, C analysis frontend. 53 tags from initial commit to v0.25.0.
