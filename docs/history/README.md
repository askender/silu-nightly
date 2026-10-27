# History

Superseded planning snapshots and milestone reports, kept verbatim for
the record. Nothing here describes the current state of the compiler.

- `m4_frontend.md`, `m4_perf.md`, `m4_status.md` — the M4 front-end
  self-hosting campaign (completed 2026-10-15; the live gates are
  `tests/test_frontend_parity_corpus.py` and the pipeline fixed point)
- `m5_backend.md` — the M5 typed-backend plan, absorbed into what is
  now `silu/typed_codegen.py` and the mixin family
- `progress_2026_10_16.md` — the 16/16 corpus + fixed-point report at
  the moment full self-hosting landed (v1.0.0)
- `selfhost_todo.md` — the post-v1.1.0 roadmap; superseded by
  `CHANGELOG.md` (v1.x entries)
- `selfhost_semantic_divergence.md` — the dual-valid divergence log
  from the early self-hosting period; the lessons now live in the
  commit messages of the respective fixes
- `install_mlir.sh` — installer for the `mlir` dependency, which was
  removed from `pyproject.toml` in v1.11.1 (zero imports anywhere)

For current material see `docs/README-referenced pages`
(`benchmarks.md`, `interop.md`, `memory.md`, `plan.md`) and
`CHANGELOG.md`.
