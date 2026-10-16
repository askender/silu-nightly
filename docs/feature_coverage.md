# Feature coverage matrix

Every new language feature must run on all surfaces before it is called
done. This is the checklist for the two features landed after v0.14.0.

## Surfaces

| # | Surface | How exercised |
|---|---------|---------------|
| 1 | CPython reference | `python3 -c` on the source (Silu→CPython shim for auto `__init__`) |
| 2 | AST interpreter | `python3 -m silu interpret` |
| 3 | IR interpreter | `python3 -m silu ir` + `silu exec` |
| 4 | Typed LLVM backend | `silu build` (typed_codegen.py) |
| 5 | Self-hosted front end | `silu_fe.si` binary must produce byte-identical IR to `ir_generator.py` |
| 6 | Self-hosted C backend | `ir2c.si` binary compiles the IR, clang builds, output matches |

## f-string (desugared to a single `fmt(...)` call)

Both front ends desugar `f"{a} x {b}"` into one `fmt(a, " x ", b)`
call node; nothing downstream knows f-strings ever existed.

| Surface | Status | Notes |
|---------|--------|-------|
| CPython | done | reference semantics |
| AST interp | done | fmt builtin joins str()s |
| IR interp | done | same builtin |
| typed LLVM | done | folds into pyobj_str_conv + pyobj_add |
| silu_fe parity | done | byte-identical fmt node |
| ir2c -> C | done | str_add over pstr_of(...)->s |

Tests: `tests/test_fstrings.py`, 8 programs x 6 dimensions.

## nested def + lambda (Rust nested-item semantics)

Both front ends hoist nested defs and lambdas to module level with a
mangled path name (`Class__outer__inner`, lambdas numbered `__L1...`).
Closure capture is a compile error; the single exception is `self` —
a hoisted function mentioning self gets a leading self parameter and
call sites thread it through by fixpoint. A lambda becomes a hoisted
def plus a `funcref` node at its use site.

| Surface | Status | Notes |
|---------|--------|-------|
| CPython | done | reference semantics (native closures) |
| AST interp | done | native closures too |
| IR interp | done | funcref evaluates to the function name |
| typed LLVM | done | `_funcref_var` static dispatch; slot never allocated |
| silu_fe parity | done | byte-identical hoisted IR |
| ir2c -> C | done | static dispatch to `fn_<mangled>`; slot never emitted |

Tests: `tests/test_nested_defs.py`, 6 programs x 6 dimensions plus a
capture-rejection case.

## Bug fixes that came out of this work

- ir2c: declaration dedup when sibling loops reuse a variable name
- ir2c: `x: object = <scalar/None>` now boxes the initializer (was a
  raw 0 -> SEGV on first PObj access)
- ir2c: empty-list literal assigned to an unannotated local is a PObj
  (`plist(list_new())`), and the typed-backend HG constructor field
  pattern (`list[str]` from `[]`) needed `hg_empty_strs()` to stay in
  typed land on both sides
- typed LLVM: null-safe `pyobj_eq`/`isinstance` (null PyObject == None)
