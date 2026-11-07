"""P6 content-addressed string global naming.

The global name for a string constant used to be
f'str_{len(module.globals)}' - a running counter over ALL module
globals, so any declaration reorder shifted every later string name.
P6 replaces it with an escaped form of the content itself. These
tests pin the escaping rules (injectivity above all), the duplicate
'~N' suffix, and the fact that the real llvmlite never sees a
duplicate name (it raises DuplicatedNameError before our suffix would
matter). Byte-level agreement with the Rust twin is enforced by the
ll-plane diff harness (18/18), not here.
"""

import pytest

llvmlite = pytest.importorskip("llvmlite.ir")

from silu.typed_codegen import TypedCodegen  # noqa: E402


class _T:
    """Bare host: only module + the converter methods under test."""

    _str_global_name = TypedCodegen._str_global_name
    _unique_str_global_name = TypedCodegen._unique_str_global_name
    _create_global_string_with_builder = (
        TypedCodegen._create_global_string_with_builder
    )


def esc(s):
    return _T()._str_global_name(s)


def test_safe_characters_pass_through():
    # NOTE: '_' is NOT in the safe set (injectivity), only letters,
    # digits and '.'
    assert esc("fibiter") == "str.fibiter"
    assert esc("fib_iter") == "str.fib_5fiter"
    assert esc("a.b.42") == "str.a.b.42"


def test_empty_and_single_specials():
    assert esc("") == "str."
    assert esc(" ") == "str._20"
    assert esc("%s") == "str._25s"
    assert esc("\n") == "str._0a"


def test_underscore_is_escaped_so_injective():
    # '_' must not pass through: otherwise the literal "a_b" and the
    # byte 0xff inside some other content could collide after escaping.
    assert esc("a_b") == "str.a_5fb"
    assert esc("a\nb") == "str.a_0ab"
    assert esc("a_b") != esc("a\nb")


def test_utf8_multibyte():
    # e-acute = C3 A9, 中 = E4 B8 AD, 𝄞 = F0 9D 84 9E
    assert esc("é") == "str._c3_a9"
    assert esc("中") == "str._e4_b8_ad"
    assert esc("𝄞") == "str._f0_9d_84_9e"


def test_escapes_match_reference_encoding():
    # cross-check the hand-rolled codepoint walk against Python's
    # encoder: same bytes in, same escaped name out
    for s in ["x", "ha llo", "é中", "𝄞~", "..", "_~_"]:
        out = "str."
        for b in s.encode("utf-8"):
            c = chr(b)
            if ("a" <= c <= "z" or "A" <= c <= "Z"
                    or "0" <= c <= "9" or c == "."):
                out += c
            else:
                out += "_%02x" % b
        assert esc(s) == out


def test_injectivity_adversarial():
    # every distinct byte string must produce a distinct name
    samples = ["", " ", "~", "_", ".", "a", "a~1", "a_5f", "a_5fb",
               "a\x7fb", "a\xffb", "é", "é", "~1", "str.", "s~1"]
    names = [esc(s) for s in samples]
    assert len(set(names)) == len(names)


def test_duplicate_contents_intern_not_duplicate():
    # P2: same content reuses the existing global (the P6-era '~N'
    # suffixes are gone); only ONE definition ever lands in the module
    import llvmlite.ir as ir

    m = ir.Module()
    f = ir.Function(m, ir.FunctionType(ir.IntType(64), [], False), "t")
    b = ir.IRBuilder(f.append_basic_block("entry"))
    t = _T()
    t.module = m
    t._create_global_string_with_builder("dup", b)
    t._create_global_string_with_builder("dup", b)
    t._create_global_string_with_builder("dup", b)
    # module.globals also holds functions (that is exactly why the old
    # len()-based numbering counted them) - filter to our names
    names = [k for k in m.globals if k.startswith("str.")]
    assert names == ["str.dup"]


def test_suffixed_name_cannot_collide_with_plain():
    # '~' is escaped in contents, so no escaped name contains '~'
    # outside the caller-added suffix
    assert "~" not in esc("a~b").replace("str.", "")
    assert esc("a~b") == "str.a_7eb"
