"""Regression: the self-hosted lexer / JSON reader used to be O(n^2)
on any source containing multibyte UTF-8.

Root cause: a rawstr subscript costs O(pos) once the string holds ANY
multibyte char (rawutf8_cp_offset walks from byte 0 to the i-th
codepoint; the ASCII fast path len==cp is what keeps pure-ASCII
sources linear). The lexer peeked src[pos] per char, JsonR subscripted
the IR JSON per char, and unescape/parse_fstring concatenated per char
- one U+00A7 inside a docstring was enough for siluc1 to spend minutes
before even reporting a parse error (corpus is 100% ASCII, so the
gates were blind to it).

The fix materializes each string once into a list[int] of codepoints
(silu_fe.si Lexer/unescape/parse_fstring + the JsonR tail) and
accumulates token text in strbufs. These tests pin the wall-clock
bound and the multibyte content round-trip.
"""

import importlib.util
import os
import subprocess
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "selfhost_build", os.path.join(REPO, "tools", "selfhost_build.py"))
shb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shb)


def _siluc1_compile(src_text, timeout=90):
    shb.ensure_siluc()
    return subprocess.run(
        [shb.SILUC1_BIN], input=src_text.encode("utf-8"),
        capture_output=True, timeout=timeout)


def test_nonascii_valid_program_compiles_fast():
    # 2000-line valid program whose only non-ASCII is one U+00A7 in a
    # string literal; the quadratic path needed >60s at 3000 lines
    pad = "\n".join(f"x{i} = {i}" for i in range(2000))
    src = 's: str = "semantics \u00a7 3"\n' + pad + "\nprint(len(s))\n"
    t0 = time.time()
    r = _siluc1_compile(src)
    dt = time.time() - t0
    assert r.returncode == 0, r.stdout[:300]
    assert dt < 30, f"non-ASCII compile took {dt:.1f}s (quadratic path back?)"


def test_nonascii_unterminated_docstring_errors_fast():
    # unterminated docstring swallows the padding: one giant token, the
    # old unescape concat alone burned ~30s here
    pad = "\n".join(f"# pad line {i}" for i in range(2000))
    src = 'def f() -> int:\n    """doc \u00a7 header\n' + pad + "\n"
    t0 = time.time()
    r = _siluc1_compile(src)
    dt = time.time() - t0
    assert dt < 30, f"non-ASCII docstring took {dt:.1f}s (quadratic path back?)"
    assert r.returncode in (0, 1)


def test_multibyte_literal_survives_selfhost_chain():
    # correctness: U+00A7 / U+4E2D ride the self-hosted front end into
    # content-addressed string globals (P6 naming: UTF-8 bytes as _xx)
    src = 's: str = "\u00a7\u4e2d"\nprint(len(s))\n'
    r = _siluc1_compile(src)
    assert r.returncode == 0, r.stdout[:300]
    ll = r.stdout
    assert b"str._c2_a7_e4_b8_ad" in ll, "multibyte literal not content-named"
    # the global carries the exact UTF-8 bytes, NUL-terminated
    assert rb'c"\c2\a7\e4\b8\ad\00"' in ll
