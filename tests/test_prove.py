"""silu prove: Z3 panic-free proofs (roadmap Phase 2, v1).

v1 scope: division/modulo by zero, intra-procedural. SOUND IN THE
SAFETY DIRECTION: a reachable abort is always reported (with a Z3
witness); a guarded divide may be flagged spuriously (the executor
evaluates on the linear path - branch-forked rebindings are v2).
"""

import subprocess
import sys

import pytest

from silu.verify import verify_source

REPO = "."
PY = sys.executable


def test_reachable_division_abort_with_witness():
    ok, rep = verify_source(
        "def f(x: int, y: int) -> int:\n    return 10 / x + 10 % y\n"
    )
    assert not ok
    text = "\n".join(rep)
    assert "division by zero" in text and "modulo by zero" in text
    assert "x=0" in text and "y=0" in text  # Z3 counterexamples


def test_provably_safe_divide():
    ok, rep = verify_source(
        "def safe_div(a: int, b: int) -> int:\n    return a / (b * b + 1)\n"
    )
    assert ok
    assert "proved safe" in rep[0]


def test_algebraically_zero_divisor():
    ok, rep = verify_source(
        "def risky(m: int, n: int) -> int:\n    return m / (n - n)\n"
    )
    assert not ok
    assert "division by zero" in rep[0]


def test_no_checked_operations():
    ok, rep = verify_source("def h(x: int) -> int:\n    return x + 1\n")
    assert ok
    assert "no checked operations" in rep[0]


def test_concrete_zero_divisor_is_definite():
    ok, rep = verify_source(
        "def d(x: int) -> int:\n    return x / 3 + 1 / 1\n"
    )
    assert ok  # concrete nonzero divisors: no obligations at all


def test_cli_exit_codes(tmp_path):
    safe = tmp_path / "safe.si"
    safe.write_text("def f(a: int, b: int) -> int:\n    return a / (b * b + 1)\n")
    r = subprocess.run([PY, "-m", "silu", "prove", str(safe)],
                       capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "proved safe" in r.stdout

    risky = tmp_path / "risky.si"
    risky.write_text("def f(x: int) -> int:\n    return 1 / x\n")
    r2 = subprocess.run([PY, "-m", "silu", "prove", str(risky)],
                        capture_output=True, text=True, cwd=REPO, timeout=120)
    assert r2.returncode == 1
    assert "POSSIBLE ABORT" in r2.stdout


def test_guarded_divide_false_positive_is_documented():
    """v1 is path-insensitive on branch rebindings: this guarded
    divide is flagged even though it cannot abort. The test pins the
    LIMITATION so v2's improvement flips it deliberately."""
    ok, _rep = verify_source(
        "def g(x: int) -> int:\n    if x == 0:\n        x = 1\n    return 10 / x\n"
    )
    assert not ok  # known v1 limitation; flip in v2 (path sensitivity)
