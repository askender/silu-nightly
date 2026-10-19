"""Function-reference (funcref) tests for the typed backend.

funcref values ride the tag-7 box + silu_fn_table dispatch: dynamic
functions enter the table directly, mixed-ABI functions get per-param
unboxing in the dispatch arm, and fully static (raw-ABI) functions ride
as PObj-ABI thunks. All forms must agree with the interpreter, which
passes function objects natively.
"""

import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

CASES = [
    # dynamic funcref: unannotated function as a value
    (
        "dyn_value",
        "def add1(x):\n    return x + 1\nf = add1\nprint(f(41))\n",
        "42\n",
    ),
    # mixed ABI: some params raw (int), some boxed
    (
        "mixed_abi",
        "def sh(x, n: int) -> int:\n    return n * 2\n"
        "g = sh\nprint(g(\"ignored\", 21))\n",
        "42\n",
    ),
    # funcref as an argument, called inside another function
    (
        "apply_pattern",
        "def add1(x: int) -> int:\n    return x + 1\n"
        "def apply(f, v: int) -> int:\n    return f(v)\n"
        "print(apply(add1, 41))\n",
        "42\n",
    ),
    # fully static function as a value (PObj-ABI thunk)
    (
        "static_thunk",
        "def add1(x: int) -> int:\n    return x + 1\n"
        "f = add1\nprint(f(41))\n",
        "42\n",
    ),
    # static thunk with a float in/out
    (
        "static_thunk_float",
        "def halve(x: float) -> float:\n    return x / 2.0\n"
        "g = halve\nprint(g(21.0))\n",
        "10.5\n",
    ),
    # static thunk with a str param
    (
        "static_thunk_str",
        "def shout(s: str) -> str:\n    return s + \"!\"\n"
        "h = shout\nprint(h(\"hi\"))\n",
        "hi!\n",
    ),
    # two aliases of one function share the table entry
    (
        "alias_pair",
        "def double(n: int) -> int:\n    return n * 2\n"
        "a = double\nb = double\nprint(a(10) + b(11))\n",
        "42\n",
    ),
]


def _build_and_run(source, out_path):
    si_path = out_path + ".si"
    with open(si_path, "w") as handle:
        handle.write(source)
    build = subprocess.run(
        [PY, "-m", "silu", "build", si_path, "-o", out_path],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [out_path], capture_output=True, text=True, timeout=60
    )
    return run.stdout


@pytest.mark.parametrize("source,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_funcref_matches(source, expected, tmp_path):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    out = _build_and_run(source, str(tmp_path / "prog"))
    assert out == expected
