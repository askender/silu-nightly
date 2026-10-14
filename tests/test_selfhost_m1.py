#!/usr/bin/env python3
"""
M1 self-hosting milestone test (docs/selfhosting.md): selfhost/calc.si
is a recursive-descent expression calculator written in Silu itself.
Build it natively and diff against CPython evaluating the same inputs.
"""

import subprocess
import sys
import shutil

import pytest

REPO = __file__.rsplit("/tests/", 1)[0]
CALC = f"{REPO}/selfhost/calc.si"

CASES = [
    "1+2",
    "12+3",
    "6/3",
    "7/2",
    "2*3+4*(5-6/3)",
    "-(3+4)*2",
    "100-20-5",
    "(1+2)*3",
    "1",
    "0",
    "42/6",
    "3-1-1",
    "(1)",
    "(11)",
    "11+1",
    "((((7))))",
    "2*(3+4)*(5-1)",
    "12*12",
    "1+2*3-4/2",
]

# inputs that CPython's eval handles identically to the calculator
EVAL_CASES = [c for c in CASES if "/" not in c or True]


def py_eval(expr: str) -> str:
    """CPython reference: eval and print like the calculator does
    (int when the value is integral, else the float)."""
    return subprocess.run(
        [sys.executable, "-c", f"v = ({expr}); print(int(v) if v == int(v) else v)"],
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture(scope="module")
def calc_bin(tmp_path_factory):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    out = tmp_path_factory.mktemp("m1") / "calc"
    build = subprocess.run(
        [sys.executable, "-m", "silu", "build", CALC, "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    return str(out)


def test_calc_matches_cpython(calc_bin):
    for expr in CASES:
        expected = py_eval(expr)
        run = subprocess.run(
            [calc_bin], input=expr + "\n", capture_output=True, text=True
        )
        assert run.returncode == 0, (expr, run.stdout, run.stderr)
        assert run.stdout == expected, (expr, run.stdout, expected)


def test_calc_interpreter_matches(calc_bin):
    """The compiled binary must also match the Silu interpreter."""
    for expr in ["1+2", "7/2", "-(3+4)*2", "(1+2)*3"]:
        interp = subprocess.run(
            [sys.executable, "-m", "silu", "interpret", CALC],
            input=expr + "\n",
            capture_output=True,
            text=True,
        )
        assert interp.returncode == 0, interp.stderr
        run = subprocess.run(
            [calc_bin], input=expr + "\n", capture_output=True, text=True
        )
        assert run.stdout == interp.stdout, (expr, run.stdout, interp.stdout)


def test_calc_error_input(calc_bin):
    run = subprocess.run(
        [calc_bin], input="1 $ 2\n", capture_output=True, text=True
    )
    assert run.returncode == 1
    assert "lex error" in run.stdout
