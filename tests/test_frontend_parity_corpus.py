"""Corpus-wide front-end parity: the self-hosted front end (silu_fe)
must produce IR identical (parsed) to the Python front end for every
benchmark, both selfhost programs, and its own source. This is the
gap audit that governs front-end self-hosting: any construct where
the two front ends diverge shows up here first.
"""

import json
import os
import subprocess
import sys

from tests import REPO, ensure_fe_binary


def _corpus():
    files = sorted(
        os.path.join(REPO, "benchmarks", f)
        for f in os.listdir(os.path.join(REPO, "benchmarks"))
        if f.endswith(".si")
    )
    files += [
        os.path.join(REPO, "selfhost", "calc.si"),
        os.path.join(REPO, "selfhost", "ir_interp.si"),
        # the front end parses its own source - the strongest member
        os.path.join(REPO, "selfhost", "silu_fe.si"),
        # and the flattened converter: the largest Silu program there is
        # (the memory regression guard: the copy-into assign matcher
        # once leaked a whole-source copy per lookahead slice here)
        os.path.join(REPO, "selfhost", "typed_codegen_flat.si"),
        # IEEE-754 boundary literals (subnormals, -0.0, DBL_MAX)
        os.path.join(REPO, "selfhost", "float_edge.si"),
        # comprehension tuple targets + the scope of a target that
        # shadows (three front ends parse it alike)
        os.path.join(REPO, "selfhost", "comp_unpack.si"),
    ]
    return files


def _selfhost_build():
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import selfhost_build

    return selfhost_build


def test_non_finite_float_literal_rejected_by_every_front_end():
    """`1e400` is rejected at the literal choke point of all three front
    ends (the python half is tests/test_float_literal_range.py). Before
    the rule existed the self-hosted front end wrote a bare `inf` into
    the IR JSON and the converter's own parser returned a value without
    advancing - the shipped compiler spun forever on `print(1e400)`."""
    src = b"x = 1e400\nprint(x)\n"
    fe = ensure_fe_binary()
    sh = subprocess.run([fe], input=src, capture_output=True, timeout=120)
    assert sh.returncode != 0
    assert b"float literal out of range" in sh.stdout + sh.stderr

    rust = os.path.join(REPO, "reference", "rust", "target", "debug",
                        "silu-fe")
    if os.path.exists(rust):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".si", delete=False) as h:
            h.write(src)
            path = h.name
        try:
            rs = subprocess.run([rust, path], capture_output=True,
                                timeout=120)
        finally:
            os.unlink(path)
        assert rs.returncode != 0
        assert b"float literal out of range" in rs.stderr

    # the compiler monolith (siluc1: stdin .si -> stdout .ll) fails FAST
    # where it used to spin forever (a regression surfaces as
    # subprocess.TimeoutExpired)
    sb = _selfhost_build()
    sb.ensure_siluc()
    monolith = subprocess.run([sb.SILUC1_BIN], input=src,
                              capture_output=True, timeout=120)
    assert monolith.returncode != 0
    assert b"float literal out of range" in monolith.stdout + monolith.stderr


def test_converter_json_parser_bails_on_unknown_token():
    """A hand-written IR JSON with a token the parser does not know
    (bare `inf`) is a loud parse error, never a value returned without
    advancing the cursor - that zero-progress return made the container
    reader re-parse the same token forever."""
    conv = _selfhost_build().ensure_converter()
    bad = b'["module", [["line", 1], ["assign", "x", ["const", inf], null]]]'
    r = subprocess.run([conv], input=bad, capture_output=True, timeout=120)
    assert r.returncode != 0
    assert b"bad json number" in r.stdout + r.stderr


def test_frontend_corpus_parity():
    fe = ensure_fe_binary()
    checked = 0
    for path in _corpus():
        ref = subprocess.run(
            [sys.executable, "-m", "silu", "ir", path, "--format", "json"],
            capture_output=True, text=True, cwd=REPO,
        )
        assert ref.returncode == 0, (path, ref.stderr)
        got = subprocess.run(
            [fe], stdin=open(path), capture_output=True, text=True,
            cwd=os.path.dirname(path),
        )
        assert got.returncode == 0, (path, got.stdout + got.stderr)
        assert json.loads(got.stdout) == json.loads(ref.stdout), (
            f"front ends diverge on {path}"
        )
        checked += 1
    # 25 benchmarks (incl. the Json-sum jsonparse twin + match_int +
    # concat_chain + the P9 char-pair pin + list_ops + pop_clear +
    # dict_ops + record_global + dict_local + str_methods + dict_str
    # ) + calc + ir_interp + silu_fe + flat converter + float_edge
    # + comp_unpack
    assert checked == 31
