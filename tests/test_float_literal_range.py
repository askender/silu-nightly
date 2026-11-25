"""Non-finite float literals are not part of Silu.

`1e400` overflows to infinity. No plane could carry it: the python
front end wrote `Infinity` into the IR JSON, the self-hosted front end
wrote a bare `inf`, and downstream each plane failed its own way - the
python text layer's bit decomposition spun forever, and the self-hosted
converter's JSON parser returned a value WITHOUT advancing, so the
container reader re-parsed the same token forever. The shipped compiler
(`siluc`) hung for good on `print(1e400)`.

The rule is now pinned at each front end's literal choke point - all
three reject, with the same words. The self-hosted and Rust halves live
in tests/test_frontend_parity_corpus.py (they need the native binaries;
this file stays in the fast CI layer).
"""

import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MSG = "float literal out of range"


def _src(text):
    with tempfile.NamedTemporaryFile(suffix=".si", mode="w",
                                     delete=False) as h:
        h.write(text)
    return h.name


def _silu(mode, path):
    return subprocess.run([sys.executable, "-m", "silu", mode, path],
                          capture_output=True, text=True, cwd=REPO,
                          timeout=120)


def test_python_front_end_rejects_infinity_literal():
    p = _src("x = 1e400\nprint(x)\n")
    try:
        r = _silu("ir", p)
    finally:
        os.unlink(p)
    assert r.returncode != 0
    assert MSG in r.stderr + r.stdout


def test_negated_overflow_literal_rejected_too():
    # the unary minus is a separate node; the magnitude itself overflows
    p = _src("x = -1e999\n")
    try:
        r = _silu("ir", p)
    finally:
        os.unlink(p)
    assert r.returncode != 0
    assert MSG in r.stderr + r.stdout


def test_build_and_interpreter_reject():
    # one rule at the visitor every processor shares: the build path and
    # the reference interpreter refuse the same program
    p = _src("x = 1e400\nprint(x)\n")
    try:
        for mode in ("interpret", "build"):
            r = _silu(mode, p)
            assert r.returncode != 0, mode
            assert MSG in r.stderr + r.stdout, (mode, r.stderr[:200])
    finally:
        if os.path.exists(p):
            os.unlink(p)


def test_boundary_finite_literals_still_accepted():
    # DBL_MAX and the smallest subnormal are literals in range
    p = _src("a = 1.7976931348623157e308\nb = 5e-324\nc = -0.0\n"
             "print(a > 1e308, b > 0.0, c == 0.0)\n")
    try:
        r = _silu("build", p)
        assert r.returncode == 0, r.stderr[-300:]
    finally:
        os.unlink(p)


def test_infinity_from_arithmetic_is_fine():
    p = _src("inf = 1e308 * 10.0\nprint(inf, inf - inf)\n")
    try:
        r = _silu("build", p)
        assert r.returncode == 0, r.stderr[-300:]
    finally:
        os.unlink(p)
