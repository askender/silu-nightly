"""runtime_cache.split: user-side references to PREFIX constants.

Since P6/P2 (content-addressed, interned string globals) the user part
of a converter output legitimately references string constants whose
definitions live in the runtime prefix - interning reuses the prefix's
global instead of emitting a second copy. split() must then emit an
`external constant` declaration for them. This regressed silently
before: the rt_globals scan only matched `= global`, so a constant
reference produced an undefined symbol at clang time (only reachable
once interning crossed the runtime/user boundary, e.g. building the
self-hosted converter whose sources call `object.clear()`).
"""

from silu import runtime_cache as rc


def _runtime_text():
    # minimal prefix shape: one constant (string), one plain global,
    # one function; header lines like a real module
    return (
        '; ModuleID = "silu_module"\n'
        'target triple = "arm64-apple-darwin24.6.0"\n'
        'target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"\n'
        "\n"
        '@"str.hello_20world" = constant [13 x i8] c"hello world\\00"\n'
        "@\"__silu_line\" = global i64 0\n"
        'define void @"rt_a"(i64 %".1")\n{\nret void\n}\n'
    )


def test_split_declares_prefix_constants_as_external_constant():
    full = _runtime_text() + (
        "\n"
        'define i32 @"main"()\n{\nentry:\n'
        '  %".1" = getelementptr [13 x i8], [13 x i8]* '
        '@"str.hello_20world", i32 0, i32 0\n'
        '  %".2" = load i64, i64* @"__silu_line"\n'
        '  call void @"rt_a"(i64 %".2")\n'
        "  ret i32 0\n}\n"
    )
    rt_ll, user_ll = rc.split(full, rt_text=_runtime_text())
    assert '@"str.hello_20world" = external constant [13 x i8]' in user_ll
    assert '@"__silu_line" = external global i64' in user_ll
    # declare for the referenced runtime function must carry the
    # signature (pre-existing behavior, kept honest here)
    assert 'declare void @"rt_a"(i64 %".1")' in user_ll
    # and the prefix itself stays intact in the runtime part
    assert '@"str.hello_20world" = constant [13 x i8]' in rt_ll


def test_split_prefix_invariant_still_guards():
    import pytest

    bad = _runtime_text().replace(
        '@"str.hello_20world" = constant',
        '@"str.other" = constant',
    )
    with pytest.raises(RuntimeError, match="prefix invariant"):
        rc.split(bad, rt_text=_runtime_text())
