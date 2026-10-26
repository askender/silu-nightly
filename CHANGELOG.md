# Changelog

All notable changes, organized by version tag.

## v1.x — Self-Hosting Campaign (2026-10-16 → present)

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

## v0.x — Pre-Self-Hosting Foundation

Early development: interpreter, IR generator, symbolic executor,
typed backend construction, C analysis frontend. 53 tags from initial commit to v0.25.0.
