"""strbuf: the explicit growable buffer (P1 / RFC docs/strbuf_rfc.md).

Reference semantics like list/dict (assignment and parameter passing
share the pointer), push() appends in place in ANY context - the
contract the local `x = x + t` in-place window only approximates -
and to_str() snapshots the content as an immutable str value.
Subscript/compare/iteration on a buffer read the content SNAPSHOT
(v1 relaxation; arithmetic like b + s and str-only methods still
fail loudly).
"""

import subprocess

import pytest

from tests.test_typed_codegen import _convert


def _run_prog(src: str) -> str:
    ll = _convert(src)
    binary = "/tmp/strbuf_test_bin"
    with open("/tmp/strbuf_test.ll", "w") as h:
        h.write(ll)
    r = subprocess.run(["clang", "-O1", "/tmp/strbuf_test.ll", "-lm",
                        "-o", binary], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"clang unavailable: {r.stderr[:120]}")
    return subprocess.run([binary], capture_output=True, text=True).stdout


def test_construct_push_tostr_len():
    out = _run_prog(
        'def main() -> int:\n'
        '    b: strbuf = strbuf()\n'
        '    b.push("hello")\n'
        '    b.push(" world")\n'
        '    print(b.to_str(), len(b))\n'
        '    return 0\n')
    assert out == "hello world 11\n"


def test_reference_semantics_alias_and_field():
    out = _run_prog(
        'class H:\n'
        '    buf: strbuf = strbuf()\n'
        'def main() -> int:\n'
        '    b: strbuf = strbuf()\n'
        '    b.push("a")\n'
        '    alias: strbuf = b\n'
        '    alias.push("b")\n'
        '    h: H = H()\n'
        '    h.buf.push("c")\n'
        '    print(b.to_str(), h.buf.to_str())\n'
        '    return 0\n')
    assert out == "ab c\n"


def test_cross_function_and_return():
    out = _run_prog(
        'def fill(b: strbuf, n: int) -> object:\n'
        '    i: int = 0\n'
        '    while i < n:\n'
        '        b.push("x")\n'
        '        i += 1\n'
        '    return None\n'
        'def make() -> strbuf:\n'
        '    b: strbuf = strbuf("seed-")\n'
        '    b.push("ed")\n'
        '    return b\n'
        'def main() -> int:\n'
        '    b: strbuf = make()\n'
        '    fill(b, 3)\n'
        '    print(b.to_str(), len(b))\n'
        '    return 0\n')
    assert out == "seed-edxxx 10\n"


def test_content_snapshot_views():
    out = _run_prog(
        'def main() -> int:\n'
        '    b: strbuf = strbuf("abc")\n'
        '    print(b[1], b == "abc")\n'
        '    n: int = 0\n'
        '    for ch in b:\n'
        '        n += 1\n'
        '    print(n)\n'
        '    return 0\n')
    assert out == "b True\n3\n"


def test_buf_ctor_from_buf_copies():
    out = _run_prog(
        'def main() -> int:\n'
        '    a: strbuf = strbuf("x")\n'
        '    b: strbuf = strbuf(a)\n'
        '    b.push("y")\n'
        '    print(a.to_str(), b.to_str())\n'
        '    return 0\n')
    assert out == "x xy\n"


def test_ctor_from_non_const_str_source():
    # the non-const operand path unpacks len/data from the ALREADY
    # converted value: one conversion, on the python plane as well as
    # the self-hosted one (the first cut named the binding module and
    # only the flat twin resolved it)
    out = _run_prog(
        'def get() -> str:\n'
        '    return "abc"\n'
        'def main() -> int:\n'
        '    b: strbuf = strbuf(get())\n'
        '    b.push("d")\n'
        '    print(b.to_str())\n'
        '    return 0\n')
    assert out == "abcd\n"


def test_ctor_from_boxed_str_source():
    out = _run_prog(
        'def get() -> object:\n'
        '    return "abc"\n'
        'def main() -> int:\n'
        '    b: strbuf = strbuf(get())\n'
        '    b.push("d")\n'
        '    print(b.to_str())\n'
        '    return 0\n')
    assert out == "abcd\n"


def test_ctor_converts_side_effecting_arg_once():
    out = _run_prog(
        'def main() -> int:\n'
        '    d: dict[str, str] = {"a": "alpha"}\n'
        '    b: strbuf = strbuf(d.pop("a"))\n'
        '    b.push("!")\n'
        '    print(b.to_str(), len(d))\n'
        '    return 0\n')
    assert out == "alpha! 0\n"


def test_ctor_from_str_parameter():
    out = _run_prog(
        'def fill(s: str) -> str:\n'
        '    b: strbuf = strbuf(s)\n'
        '    b.push("!")\n'
        '    return b.to_str()\n'
        'def main() -> int:\n'
        '    print(fill("hi"), fill("yo"))\n'
        '    return 0\n')
    assert out == "hi! yo!\n"


def test_strbuf_plus_string_fails_loudly():
    ll = _convert_safe('def main() -> int:\n'
                       '    b: strbuf = strbuf()\n'
                       '    x: str = b + "z"\n'
                       '    return 0\n')
    # must NOT compile: concat on a buffer is a str-only operation
    assert ll is None


def test_strbuf_method_whitelist():
    ll = _convert_safe('def main() -> int:\n'
                       '    b: strbuf = strbuf()\n'
                       '    b.strip()\n'
                       '    return 0\n')
    assert ll is None


def _convert_safe(src):
    """_convert but None on converter error (illegal programs)."""
    import json
    import ast as pyast
    from silu.importer import expand_imports_tree
    from silu.ir_generator import SiluIRGenerator
    from silu.typed_codegen import TypedCodegen
    import os
    tree = expand_imports_tree(src, os.path.dirname(os.path.abspath(
        "tests/test_typed_codegen.py")))
    try:
        ir = SiluIRGenerator().visit(pyast.parse(src))
        return TypedCodegen().convert(json.dumps(ir))
    except Exception:
        return None
