#!/usr/bin/env python3
"""
M2 self-hosting milestone test (docs/selfhosting.md): selfhost/ir_interp.si
is a tree-walking interpreter for a Silu IR subset, written in Silu itself.
It reads JSON IR on stdin, parses it to instance trees, and executes.
Diff against CPython running the original source programs.
"""

import json
import subprocess
import sys
import shutil
import tempfile

import pytest

REPO = __file__.rsplit("/tests/", 1)[0]
INTERP = f"{REPO}/selfhost/ir_interp.si"

PROGRAMS = [
    # (source, expected stdout)
    ("x: int = 3\ny = x * 4\ntotal: int = 0\ni = 0\n"
     "while i < y:\n"
     "    if i % 2 == 0:\n"
     "        total += i\n"
     "    i += 1\n"
     "print(total)\nprint(x + y)\n", "30\n15\n"),
    ("n: int = 10\nfib: int = 1\ni: int = 2\n"
     "while i <= n:\n    fib = fib * i\n    i += 1\nprint(fib)\n",
     "3628800\n"),
    ("total: int = 0\ni = 0\nwhile i < 100:\n"
     "    if i % 3 == 0:\n        total += i\n    i += 1\nprint(total)\n",
     "1683\n"),
    ("a: int = 7\nb: int = 2\nprint(a // b)\nprint(a - b * 3)\n",
     "3\n1\n"),
]


@pytest.fixture(scope="module")
def m2_bin(tmp_path_factory):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    out = tmp_path_factory.mktemp("m2") / "ir_interp"
    build = subprocess.run(
        [sys.executable, "-m", "silu", "build", INTERP, "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    return str(out)


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_m2_runs_programs(m2_bin, source, expected):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(source)
        path = f.name
    ir_file = path + ".ir.json"
    gen = subprocess.run(
        [sys.executable, "-m", "silu", "ir", path, "--output", ir_file,
         "--format", "json"],
        capture_output=True, text=True,
    )
    assert gen.returncode == 0, gen.stderr
    run = subprocess.run(
        [m2_bin], stdin=open(ir_file), capture_output=True, text=True,
        timeout=30,
    )
    assert run.returncode == 0, (run.stdout, run.stderr)
    assert run.stdout == expected, (run.stdout, expected)
    # CPython cross-check
    py = subprocess.run([sys.executable, path], capture_output=True, text=True)
    assert py.stdout == expected


def test_m2_empty_module(m2_bin):
    doc = json.dumps(["module", []])
    run = subprocess.run(
        [m2_bin], input=doc, capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0
    assert run.stdout == ""
