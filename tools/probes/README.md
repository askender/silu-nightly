# S0 probe: tagged vs pyobj value construction (RFC sum types)

Two self-contained .ll programs measuring the cost of constructing
3M values in the two representations:

- `probe_pyobj.ll` - the emitted `create_int` shape verbatim: two
  mallocs per value (16-byte {tag, ptr} box + 8-byte payload) + three
  stores.
- `probe_tagged.ll` - the RFC's `{i32 tag, i64 payload}` single
  block: one malloc + two stores.

Build & run:

    clang -O2 tools/probes/probe_pyobj.ll -o /tmp/pp && \
    clang -O2 tools/probes/probe_tagged.ll -o /tmp/pt

Result (2026-10-27, M-series, 11-run median): pyobj 93.4ms vs tagged
47.7ms = **1.96x**. Meets the RFC S0 go bar (>= 2x on the
construction loop itself).

CAVEAT from the same day's jsonparse attribution study (see
docs/benchmarks.md): construction is only ~12% of jsonparse's
runtime, so landing tagged unions alone moves jsonparse by ~0.9ms,
not the 5ms the RFC originally projected. The dominant cost there is
the per-character 1-byte str allocation of `ch = s[i]` (62ns/char x
87k chars ~= 5.4ms; the ord()-rewrite probe runs the same scan 2.7x
faster). Character-access zero-allocation (extending RAWCHAR_VIEW
emission to subscript reads) is the bigger lever.
