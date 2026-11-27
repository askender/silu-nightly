# Changelog

All notable changes, organized by version tag.

## v1.x — Self-Hosting Campaign (2026-10-16 → present)

### Unreleased (1.25.1)
Tuples became their own runtime type. They used to ride the tag-4 list
box, so the tag was the only place "this is a tuple" survived to
runtime and it did not: `print((1, 2))` came out as `[1, 2]`, nested
tuples inside lists and dicts lost their parens, `(1, 2) == [1, 2]`
answered True, and `isinstance(t, tuple)` could not mean anything.
A tag-9 box (same list struct) fixes all four - repr prints `(1, 2)`
with the one-element trailing comma `(1,)`, cross-type equality answers
False for == and raises on ordering like CPython, slices/concat/repeat
keep the tuple identity, and `isinstance` reads the real tag
(`_ISINSTANCE_TAGS["tuple"]` moved with the arm; the self-hosted twin's
own internal pairs are tuple literals compiled by this converter, so a
stale table there silently disabled the twin's statement-level rawstr
free - the ll gate caught it as conv-vs-pyll diffs on pop_clear and
dict_str). Pinned by four new semantic-gate cases (expected values from
real CPython).

Also in this round, from the four-plane differential battery
(CPython / interpret / siluc / pybuild / siluc1->clang, 130+ probes):
the self-hosted FE now parses Python's pow precedence (`-2 ** 2` is -4)
and loudly refuses f-string format specs/conversions and the debug form
(the reference FE already did); the interpreter refuses `global`,
`nonlocal` and the walrus operator at the shared parse gate instead of
silently dropping them (its `sorted` is Python's sorted - the old
"silently ignored" claim was wrong); the C backend copies str values on
dict and list element stores (`d[k] = s; s += "!"` once corrupted the
dict's entry through the shared pointer, str_add's in-place branch);
and the wasm backend traps loudly instead of declaring nameless globals
and evaluating unknown expressions to 0.

`str.find/rfind/index/startswith/endswith` gained CPython's start/end
arguments on all four planes: the boxed method map used to truncate
extra arguments silently (`"abcabc".find("c", 3)` answered 2 where
CPython answers 5, `str.index` with two arguments refused outright).
New range runtime (`rawstr_find_range`/`rawstr_rfind_range`/
`rawstr_starts_range`/`rawstr_ends_range`, plus `rawutf8_cp_count`
reuse): negatives count from the end then clamp at 0, beyond-length
clamps at the length, matches start only at code point boundaries, and
the answers stay in the absolute code point coordinate system
`len(s)`/`s[i]` use. ir2c grows the same helpers in C (typed str
receivers only; a dynamic receiver refuses loudly rather than emitting
wrong-type C). Two multibyte and clamping pins in the semantic gate.
`str.replace` with an empty pattern now interleave.new at every code
point boundary - the runtime returned the receiver, which the caller
frees after the call, so the answer dangled (len 0); ir2c's C version
returned s the same way, and its no-match path too.

### Unreleased (1.25.0)
A semantics round: compiled Silu agrees with CPython on a class of
programs that used to answer wrongly or crash while every byte gate was
green. `tests/test_semantics_vs_cpython.py` pins each case on both the
Python and the self-hosted plane (231 checks),
`tests/test_asan_runtime.py` runs the same programs under a real
AddressSanitizer, and `tests/test_asan_compiler.py` runs the compiler
itself under one.

- **iterating a container that changes under its own loop**. A typed
  dict loop hoisted its table/keys/vals pointers once, so a store in the
  body that reindexed the table left it walking freed arrays (values
  silently skipped, then a segfault), and it walked the hash table
  instead of the insertion order. Typed dicts now iterate, print and box
  in insertion order (reindex compacts in entry order; a value store
  never reindexes). Any insert, delete or reindex in the body is a
  `RuntimeError` at the next loop step - CPython's own rule, stricter for
  a delete paired with an insert. Dynamic dicts and sets are watched the
  same way; list loops read the live length (a worklist `for x in xs:
  xs.append(...)` now sees its own additions); a str loop whose body
  rebinds the iterated name walks a snapshot.
- **comprehensions**: a tuple target (`[n for n, s in rows]`) binds its
  names - it was skipped silently, and after a `for n, s in rows` loop
  the answer was `[2, 2]`. Targets are scoped to the comprehension: a
  shadowed name is restored, and a typed slot takes elements unboxed when
  the iterable states their kind. All three front ends parse tuple
  targets (two used to reject them).
- **`dict[str, str]` ownership**: an entry is the dict's buffer, so
  readers borrow it. `x = d[k]` copies (it aliased, and `x += "!"`
  wrote into the dict), and a `get`/`setdefault` left as a statement is
  no longer freed (that freed the dict's own value). `dict[str, str]`
  works as a parameter and return kind.
- **`del xs[i]`** on a typed or dynamic list shifts the tail and checks
  the bound (it boxed the list and popped the copy: SIGSEGV).
- **dict `==`** compares contents (boxes were compared: always False).
- **strbuf**: the non-constant constructor resolved `llvmlite` names
  through an unbound global (NameError regression).
- **IEEE-754 edge literals** (subnormals, -0.0, DBL_MAX, run-time
  infinity) no longer hang or mis-compile the self-hosted planes; an out
  of range float literal is rejected by all three front ends.
- **integer pow** is exact for runtime exponents; **`range` step** is
  honoured and `range` as a value is rejected loudly; **`count` /
  `index`** dispatch on the receiver's kind; **`print([None])`** prints
  None; **keyword arguments** bind by name; **`s += f()`** evaluates
  `f` once; shift counts and `int(float)` are range-checked.
- **rejected loudly** where the Python plane used to compile something
  else: default parameter values, `*args`, loop `else`, wrong arity,
  a comprehension target shadowing a slot with elements of another kind,
  a loop variable reused across two key kinds, and a name read before its
  first assignment in a function (Python's UnboundLocalError; the
  converter died with a bare `KeyError`).
- **front ends**: the self-hosted one crashed on a module-level
  attribute store (`h.n = 5`) and now gives the Python plane's messages
  for defaults and loop `else`.
- **gates**: the .ll parity harness verifies each corpus module with
  llvmlite (a non-dominating phi sat in the runtime prefix for a whole
  session - every plane emitted it, clang assembled it); `tools/gates.sh`
  keeps the full pytest log on failure; lint runs under pytest; the
  Rust oracle mirrors every converter change and its prefix snapshot is
  regenerated by `tools/regen_rust_prefix.py`.
- **C backend (ir2c)**: a str `+=` on a module-level name, concat into a
  borrowed buffer, and `dict[str, str]` reads hand out copies.
- **memory safety, under a real AddressSanitizer** (new gate
  `tests/test_asan_runtime.py`, 124 checks). Two runtime walkers read one
  byte past every exact-size string buffer (`pystr_cp_entry` and
  `rawstr_cp_off_at` came round once more for their sentinel offset), and
  `s = s + s` appended a buffer to itself through a realloc that could
  release the source under the copy (use-after-free, a corrupted tail).
  The first one crashed the compiler binary itself - five crash reports
  in one session, none of them on demand. Every earlier "asan clean"
  verdict in this repo was vacuous: clang instruments only the functions
  that carry `sanitize_address`, and a `.ll` input has none, so
  `clang -fsanitize=address x.ll` linked the runtime and checked nothing.
  `tools/asan_run.py` attributes the module first and proves the
  toolchain with a known over-read before any program counts as clean.
- **`str.find` / `rfind` / `index` answer code point positions** on
  multi-byte text too. They returned the BYTE offset, so `s[s.find(x)]`
  read the wrong character whenever a multi-byte character preceded the
  match. Pinned on four implementations: both converter planes, the
  Rust oracle and the C backend.
- **the self-hosted converter segfaulted on every attribute store to an
  instance read out of a typed list** (`it: Rec = items[i]` then
  `it.ret = v`) since 2026-10-25. `_field_slot` asked
  `str(inst_ptr.type) == "i64"`, which is never true in the native twin
  (its type records have no `__str__`), so the bare i64 word was used as
  a pointer. No corpus file had the shape; `selfhost/ir2c.si` does, and
  `siluc1` could not compile it at all. The check is the cached-type
  compare now, and the text renderer names a null operand instead of
  dereferencing it.
- **mutating methods answer None**: `r = d.clear()` stored the void
  call's result (invalid IR that clang rejected with an internal
  message), and `xs.append(x)` evaluated to the list itself. The boxed
  method table's `has_result` column had never been read - both branches
  of its return statement were identical - and it is False for
  `startswith`/`endswith` too (a raw i1 that gets boxed afterwards), so
  the decision is made by name (`_NONE_RESULT_METHODS`).
- **the compiler binary itself is under the sanitizer too**
  (`tests/test_asan_compiler.py`, slow layer): the instrumented
  compiler must bring every corpus file, `selfhost/ir2c.si` and its own
  converter through with no report, exit 0 and the same bytes as the
  normal binary.
- **documented boundaries**: `upper()` and `lower()` map ASCII letters
  only; `print(a, b)` evaluates and writes its arguments one at a time,
  so a later argument that mutates an earlier one prints differently
  from CPython (docs/semantics.md §2 and §3.6).

### v1.24.0
The oracle shape round: the Rust reference gains the 2-arg `get`/`pop`/
`setdefault` family on str-valued dicts, augmented subscript on both
dict families, non-empty dict literals, and dynamic `pop` semantics
(1-arg miss panics, 2-arg miss returns the default, None included). The
round caught invalid IR shared by every plane (a str value passed as a
bare pointer) and fixed the strbuf constructor's double-pop side effect.
The dead `cp_offset` walk retires from the runtime prefix.

### v1.23.0
The str method family across all four planes: `strip`, `split`,
`replace`, `lower`, `upper`, `find`, `index`, `startswith`, `endswith`
and the predicates, byte-identical with CPython (`index` on a miss
raises instead of answering -1). Local dict slots and the inter-function
blank-line rule are fixed.

### v1.22.0
The dict/list/instance-global capability expansion: membership, `pop`/
`clear`, local dicts, module-level record instances with method calls,
str-key stores and boxed joins. Six capability pins join the corpus.

### v1.21.0
P9 concat ownership: the converter tracks temporaries across concat
chains so a 300k-link `+=` holds constant memory (6.1MB -> 1.15MB).

### v1.20.0
Match dispatches, an optional compile daemon, and a faster twin VM.

- **match int-literal cases dispatch (P8)**: an all-int-literal match
  lowers to an LLVM switch (byte-identical across the three
  converters) and a wasm br_table; the wildcard body lives outside the
  match block and the assembler emits the index bytes before 0x0E.
  Non-eligible matches keep the icmp chain. New corpus
  benchmarks/match_int.si: ir 22/22, ll 21/21, wat2wasm 34/34,
  wasm corpus 16/16, compile 21/21.
- **siluc daemon (optional)**: `siluc --serve` + `SILUC_DAEMON=1`
  forwards transparently; content-keyed build cache makes repeat
  compiles ~0ms (vs ~160ms); fork-isolated requests, direct path
  unchanged. Protocol: diagnostics stream before an EOF-delimited
  verdict line; request children reset SIGCHLD.
- **irvm twin speedup**: inline hot dispatch arms, frequency-ordered
  opcode chain, pc/end/sbase in locals with frame lists touched only
  at switches - fib(28) 115ms -> 60ms, beating monty (~88ms exec) and
  within 1.2x of the hand-written Rust VM.
- **ir_interp loud depth caps**: 300k-deep JSON nesting and
  f(200000)-deep user recursion used to SIGSEGV; both bail with
  "ir_interp bail: ..." + exit 3 now.

### v1.19.0
The self-hosted compiler ships to the browser (the WASM workflow).

- **wasm_backend.si**: IR JSON -> WAT. The corpus (15/15) runs
  byte-identical to CPython through the browser pipeline: int/float/
  bool arithmetic, lists, str-keyed and int-keyed dicts, list[float],
  str ABI v2 (16-byte [blen][clen] prefix, O(1) len, value semantics,
  in-place narrow-window extend), flat record classes with match
  narrowing, and the Json tagged-union layer ($jbox).
- **wat2wasm.si**: a pure-Silu WAT -> wasm64 binary assembler -
  tokenizer, structure pass, canonical LEB128, type dedup, folded-WAT
  post-order emission, exact decimal->binary64 (dec_bits, 13k-vector
  differential vs CPython). 33/33 corpus files byte-identical to the
  wabt CLI; 19ms per fib. The playground drops the 0.66MB wabt.js.
- **str temp lifetime**: one-expression subscripts no longer leak the
  whole-source element copy - rawlist_str_get/slice results register
  as owned (keyed by the SSA value's NAME string) and the char view's
  RAWSTR coercion frees the parent; function boundaries clear the
  tracking (llvmlite names restart per function). Both codegen planes
  aligned: one field-store copy, after the base load.
- **ir_interp loud-fail**: a two-pass pre-check bails with
  "ir_interp bail: <reason>" + exit 3 outside the int-only subset
  (the float-const parse hang root cause fixed); the interpret plane
  maps main()'s return to the process exit code.
- **playground live** at https://silu.askender.xyz/playground/ - 18
  inline examples, real .wasm compilation through the self-hosted
  wat2wasm (no wabt dependency), morphing WASM run button; deployment
  is one command (tools/deploy_playground.py).
- **CI**: a wasm gate job (shim/run/backend/corpus/wat2wasm/compile)
  with pinned wasi-sdk 34.0 + wabt 1.0.42.

### v1.18.1
Runtime: code point offsets get a side cache; the dynamic layer goes
code-point correct.

- `rawstr_cp_off_at`: a 1024-slot hint table caches each non-ASCII
  string's full codepoint->byte offset array (keyed by struct pointer,
  validated by len+cp, purged on free; ASCII keeps the O(1) fast
  path). Per-char loops over non-ASCII strings drop from O(n^2) to
  O(n) - a 50K-code-point loop went from minutes to 0.3s.
- Dynamic-layer str semantics fixed to code points (CPython parity):
  `len()` counts code points (was byte length), `s[i]` indexes and
  bounds-checks by code point and copies the whole UTF-8 sequence
  (was a single byte), `s[a:b:c]` clamps and steps in code points.
  Evidence: `len(chr(0xa7))` compiled to 2, now 1; `ord(s[0])`
  compiled to 128, now 167.
- Self-contained walkers (pyobj_utf8_cp_count/offset) for the early
  runtime creators; oracle user-part char-view rewired to the cached
  accessor. const/tagged prefixes re-pinned; oracle ll 19/19.

### v1.18.0
strbuf: an explicit, reference-semantics growable buffer (P1 / 1b-lite)

- str semantics and emission untouched; the acceptance for the
  landing commit was the ll gate staying byte-identical on all
  pre-existing corpora. The new type fills the measured hole: the
  same-concatenation spelling through an instance field or a
  function boundary degraded ~1100x (34.9s vs 0.03s for 3M pushes,
  reference/P1_STRING_RESEARCH.md); with a buffer it is 0.07s in
  ANY context.
- API: b: strbuf = strbuf() / strbuf(x) (ctor always copies; alias
  is b = a); b.push(s) appends in place O(1) amortized anywhere;
  b.to_str() snapshots as an immutable str; len(b) reads code
  points; assignment/passing/returns share the i8* pointer like
  list/dict (a buf parameter selects the dynamic function ABI).
  v1 relaxation: b[0] / b == s / for ch in b / print(b) read the
  content snapshot instead of failing (documented in the RFC).
- front ends needed ZERO changes (annotations pass through as
  strings); the Rust oracle is fully synced: selfhost/strbuf_probe.si
  is the 19th ll corpus file, conv vs rustconv 19/19 byte-identical.
- self-host sources deliberately NOT migrated: a census of
  silu_fe.si shows every concatenation is the local `x = x + t`
  shape already inside the in-place window (18 unescape table sites
  + 3 lexer sites) - no field/cross-function hot loop exists to fix
  (the batch-2 premise; recorded in the research note).

### v1.17.0
string globals are content-addressed and interned, booleans are singletons (proposals P6+P2+P5) - .ll output changes, semantics unchanged

- global names for string constants switch from
  `str_{len(module.globals)}` (a running counter over ALL module
  globals, so any declaration reorder shifted every later string name)
  to an escaped form of the content: `str.<safe bytes>` with every
  other UTF-8 byte as `_xx` hex, e.g. `@"str.OverflowError_3a_20integer_20overflow_20in_20add"`
- `_` is escaped too, so distinct contents always map to distinct
  names; duplicate contents keep deterministic `~N` suffixes until
  constant interning lands (P2)
- benefits: output diffs and incremental compilation no longer
  renumber unrelated strings; third implementations stop needing the
  "global slot model" (STR_BASE/TAGGED_SLOTS/function-method-capture
  counting) - the Rust twin deleted that entire accounting
- all planes re-verified byte-identical: ll 18/18, IR 19/19,
  full pytest suite, and the self-hosting fixed point
- constant interning (P2): a hit on the bare content name reuses the
  existing global instead of emitting a second definition - the '~N'
  duplicate suffixes vanish and constants collapse to one definition
  per content. silu_fe's output drops 1,137 constants (263 unique,
  71% redundant bytes) to 262 unique / 0 redundant; total .ll shrinks
  ~51.5KB on that corpus file. The explicitly named runtime panic
  globals (str_keyerr/str_idxerr/json_typeerr) are ABI-shaped single
  instances and stay named as-is (recorded residue, not interned).
- interning exposed a latent bug in BOTH runtime/user split
  synthesizers (python runtime_cache.py and the C driver siluc_main.c):
  their prefix-symbol scans only matched `= global`, never
  `= constant` - unreachable before because the two halves never
  shared a constant name. Both now synthesize `external constant`
  declarations; the C scanner also gained within-line keyword bounds
  and bracket-type termination (an initializer could leak into the
  external declaration). Regression tests added on both sides.
- boolean singletons (P5): @silu_true/@silu_false are two immortal
  constant boxes (tag 3, private payload); create_bool became a bare
  select (zero allocations) and `x is True/False` a single pointer
  compare replacing the old 11-opcode
  and(non_null, and(tag==3, payload==want)) walk - null covered for
  free, semantics aligned with CPython's bool identity. Runtime
  contract: any future recursive pyobj release must exempt tag-3 from
  free; audited that nothing but create_bool constructs a tag-3 box.
  This work also fixed a text-layer llvmlite bug (struct constant
  initializers double-wrapped pre-adopted Constant elements and
  printed object reprs - the singletons are the first non-zero struct
  initializer), taught the self-hosted llvmlite.si the gv_const_bitcast
  twin the Python layers already had, and hardened BOTH split
  synthesizers once more: struct-typed constants ({i32, i8*}) contain
  a comma, and a comma-terminated type capture truncated the external
  declaration (`external constant {i32`) - bracket pairing now takes
  precedence over the comma cut on both sides.

### v1.16.2
large-file frontend memory regression fixed - full self-hosting CI restored

- root cause: v1.15.0's copy-into assign wiring converted the subscript
  BASE eagerly for any `x = <subscript>` with a str target and used it
  only for list[str] bases - every other shape (the lexer's
  self.src[a:b] lookahead slices) leaked a whole-source rawstr_copy per
  iteration: the self-hosted front end needed >15GB (OOM-killed) on its
  own ~12k-line converter; the matcher now requires a statically-known
  list[str] name before emitting anything
- measured: full flat.si through the self-hosted front end 20GB/OOM ->
  1.0GB, rc=0, IR byte-identical to the python plane
- companion fixes for the restored full-corpus parity: nested functions
  in the flattened converter no longer capture the ir module (Rust
  no-capture semantics) - rawdict value boxing and is-None constants
  route through self; three module-capture lambdas removed
- typed_codegen_flat.si returns to the frontend parity corpus (19
  files) and test_pipeline_fixed_point returns to the release gates;
  regression guards added (no dead base copy in the .ll, AST scan for
  module captures in nested functions, end-to-end flat.si parse)

### v1.16.1
release readiness: reproducible CI and a relocatable binary toolchain

- pin the lint contract and use project dependencies in CI; manual
  self-hosting gates are now actually dispatchable
- installed-wheel bootstrap generates sources and native tools in a
  per-user cache, never in the package installation directory
- portable native linking and target triples for Linux and x86_64;
  cold driver cache creation and artifact packaging fixed
- funcref tables now emit constant-expression bitcasts for their i8*
  elements: newer clang silently accepted the raw signatured function
  reference, Apple Clang 16 rejected it as an array element type
  mismatch (dual-valid FormattedConstant + fn_const_bitcast on both
  planes, plus a .ll-shape regression test)
- split-module runtime declarations now carry real signatures (balanced
  -paren extraction) instead of vararg `(...)` placeholders, which Apple
  Clang 16 rejected against the runtime's fixed-signature definitions
- public binary archives, examples and bilingual release documentation;
  all four platforms (macOS ARM64/x86_64, Linux ARM64/x86_64) are
  published on silu-lang Releases - Intel-Mac pins llvmlite 0.45.1
  (newest Intel-Mac wheel) and builds on macos-15-intel
- known follow-up: a large-file front-end memory regression (the
  self-hosted front end needs >15GB to parse the ~12k-line flattened
  converter directly) is documented in docs/distribution.md; the
  oversized single-file case is excluded from frontend_parity_corpus
  and the pipeline fixed point runs on the dev machine until it is fixed

### v1.16.0
interprocedural contracts: require() - modular proof composition

- require(cond): a no-op in every runtime plane, proof-time only;
  the typed backend compiles it to constant true
- a function's proof stands ALONE under its declared domain - no
  caller narrowing, removing a caller never invalidates anything;
  call sites are separately verified against the contract
  (fresh-name instantiation, caller path conditions)
- spectral with require goes green end to end: a() proves safe
  under i>=0,j>=0; the loop-bound call sites satisfy the contract;
  safe_div(10, x-x) is a CONTRACT VIOLATION with witness
- and/or in the Z3 expression converter; empty domains are
  vacuously safe (pinned); prove suite 7 -> 24

### v1.15.2
distribution + prove v2 + transform equivalence: the roadmap closes

- silu bootstrap: one command builds the zero-Python toolchain from
  the package's own sources (mtime-incremental); prebuilt binaries
  ship on GitHub Releases (4 platforms), NOT pip'd; tools/ +
  selfhost/ join the wheel - clean-venv end-to-end verified
- prove v2 path sensitivity: obligations carry direction-applied
  path conditions + live env bindings; gcd's guarded a%b went
  false-positive -> PROVED SAFE; over-suppression checked both ways
- transform-equivalence proofs (roadmap Phase 3): borrowed-str
  callee contract + rawlist writeback guard discharged over Z3,
  mutation-verified - the three-phase symbolic roadmap is fully
  delivered
- legacy bare-word CLI layer now knows all subcommands (bootstrap
  was being eaten as a filename)

### v1.15.1
prove v1.1: real-code ready + release smoke

- assignment visibility: Silu assign/ann_assign fell through the
  executor's C-style AssignmentHandler - checked operations inside
  assignments were invisible; now evaluated and recorded everywhere
- loop-condition crash fixed: tuple-tree conditions converted back
  to infix before ast.parse; unparseable conditions skipped
  (conservative direction)
- two new abort families: subscript bounds (statically-known
  lengths, witness i=-1 / proved-safe i%3) and literal KeyError
- parse_number (the real jsonparse scanner) analyzes cleanly and
  proves ok - roadmap Phase 2 exit criterion material; prove suite
  7 -> 16
- release: clean-venv pip smoke (interpret/ir/prove/build), version
  drift fixed (1.15.0 everywhere), README gains the prove row

### v1.15.0
performance parity + panic-free proofs: copy-into endgame, silu prove

- P1 copy-semantics endgame: rawlist_str_copy_into (dst.cap >=
  src.byte_len verdict, geometric grow, null-dst allocate); wordcount
  24.8 -> 8.8ms = 1.74x vs Rust; suite geomean 1.0x vs Rust.
  Negative-index underflow bug in rawlist_str_get fixed en route
- P2 silu prove (Phase 2 v1): Z3 panic-free proofs for division/
  modulo; reachable aborts carry witness parameter values;
  a/(b*b+1) proved safe by algebraic reasoning; sound-in-safety-
  direction with the guard limitation pinned by test
- P3: exec plane json_* builtins (last plane gap closed); CI gates
  weekly; runtime slimming closed by LTO+dead_strip evidence

### v1.14.0
S4: sum-type ownership settled - reference model, explicit frees, Z3 pairing proofs

- ownership audit (RFC 8b): construction = owned, y = x = shared
  reference, container reads = borrowed; per-slot compiler drops
  formally rejected as unsound; json_free ships as move discipline
- static census pins every tagged_free to json_free or the
  recursive trio; probes cover pool-sentinel sharing, deep-tree
  teardown, borrowed-read survival
- Z3 pairing proofs: list walk frees exactly the pushed slots,
  dict walk exactly the live entries (tombstones never fire),
  dispatch routes each tag to exactly its own teardown -
  mutation-verified (the S1 dispatch-bug shape goes red)
- json_* argument paths and _build_raw_list route through the
  single-evaluation helper (str-constant elements were boxing);
  m4/ir2c plane skips the Json twin - closing the S3 round's
  'phantom' full-suite failure (it was this, not a race)
- full suite 1268 passed, zero failures

### v1.13.1
S3: jsonparse over the Json sum type, four planes agree

- the id/name WIP bug solved: tagged_dict_free read field 4 (the
  open-addressing table - small entry indices) as the value array;
  vals is field 6; freeing table entries as pointers segfaults on
  two-live-key dicts
- benchmarks/jsonparse_json.si: full parser on tagged blocks, all
  four planes (incl. the Rust twin) byte-agree on the 87KB doc
- measured honestly: Json twin 10.1ms vs class twin 8.9ms - net
  1.2ms SLOWER; per-read tag dispatch + checked unwrap outweigh
  the construction saving (RFC 7c); inline tag checks are the
  optional follow-up

### v1.13.0
S2: the built-in Json sum type lands on every plane

- `x: Json` / `list[Json]` / `dict[str, Json]` annotations: tagged
  blocks ride the raw container slots as pointer bits (no new
  container runtime); literal build, subscript read/write, append,
  for-iteration all channel through
- json_tag/int/float/bool/str/free builtins with checked unwrappers
  (loud TypeError on wrong member, the abort policy), fully
  open-coded emission (.si Rust nested-item semantics)
- interpreter + CPython planes agree byte-for-byte with the typed
  binary; S1 benefit measurement had revised the jsonparse
  projection to ~0.3-0.4ms (construction only 1.20x mixed) - this
  lands for expressive completeness
- two cross-plane bugs fixed en route: value re-evaluation in the
  coercion helper (read_stdin called twice -> silent empty output)
  and a nested-function capture violation

### v1.12.0
sum-type runtime, stage S1: the tagged emitters land (lazy, byte-identical)

- _emit_tagged_core/_emit_tagged_frees: 8 functions over the
  16-byte {tag, payload} block; three-tag dispatch frees; recursive
  list/dict teardowns modeled on rawdict_str_clear
- storage reuses rawlist/rawdict slots element-wise (8-byte
  patterns) - the RFC's rawlist_tagged family collapses to two
  free-walks
- lazy _ensure_tagged_runtime with a base-__init__ sentinel
  (getattr is not dual-valid); corpus 16/16 unchanged
- probe tests build/read/tear-down int+str+list trees and a dict
  tree; the probe caught a dispatch-chain bug (missing dict check
  segfaulted scalar frees) before any gate could

### v1.11.5
view materialization pooled: s[i] at parity with hand-written ord()

- v1.11.4 correction: the char pool sat on rawstr_char_at, a dead
  emitter (zero call sites; the dead-code scan's .si-text exclusion
  had masked it) - its 0.8ms was noise. Real hot path: the
  view->RAWSTR materialization (2 mallocs + memcpy + SIMD cp count
  per char)
- rawstr_char1(data, seq): one-byte code points from the shared
  pool, longer ones copy, one call at the expression site;
  rawstr_char_at deleted; phi dominance bug caught by llvm verify
  and fixed
- inline strategy measured and rejected: clang -O2 already inlines
  the small runtime fns; alwaysinline on char1 is negative
- jsonparse 9.8 -> 8.0-8.5ms (0.6x); scan probe at parity with the
  ord() idiom (~5ns/char). Residual gap == construction cost:
  sum-type RFC promoted to the closing move (share 12% -> ~24%)

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
