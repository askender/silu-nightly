#!/usr/bin/env python3
"""
M3 self-hosting milestone test (docs/selfhosting.md): selfhost/ir2c.si
compiles Silu IR (JSON) to C99. The bootstrap compiler pipeline is:
  source -> silu ir (JSON) -> [this Silu program] -> C -> clang -> binary
Each test compiles a program through the FULL pipeline and diffs against
CPython running the original source.
"""

import subprocess
import sys
import shutil
import tempfile

import pytest

REPO = __file__.rsplit("/tests/", 1)[0]
IR2C = f"{REPO}/selfhost/ir2c.si"

PROGRAMS = [
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
    ("a: int = 7\nb: int = 2\nprint(a // b)\nprint(a - b * 3)\nprint(a % b)\n",
     "3\n1\n1\n"),
    ("if 3 > 2:\n    print(1)\nelse:\n    print(2)\nif 1 > 2:\n    print(3)\nelse:\n    print(4)\n",
     "1\n4\n"),
]


@pytest.fixture(scope="module")
def ir2c_bin(tmp_path_factory):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    out = tmp_path_factory.mktemp("m3") / "ir2c"
    build = subprocess.run(
        [sys.executable, "-m", "silu", "build", IR2C, "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    return str(out)


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_m3_full_pipeline(ir2c_bin, source, expected):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(source)
        path = f.name
    ir_file = path + ".ir.json"
    c_file = path + ".c"
    bin_file = path + ".bin"

    # 1. front-end: source -> JSON IR
    gen = subprocess.run(
        [sys.executable, "-m", "silu", "ir", path, "--output", ir_file,
         "--format", "json"],
        capture_output=True, text=True,
    )
    assert gen.returncode == 0, gen.stderr

    # 2. the Silu-written compiler: JSON IR -> C
    with open(ir_file) as stdin_f, open(c_file, "w") as stdout_f:
        to_c = subprocess.run(
            [ir2c_bin], stdin=stdin_f, stdout=stdout_f,
            stderr=subprocess.PIPE, text=True, timeout=30,
        )
    assert to_c.returncode == 0, to_c.stderr

    # 3. system compiler: C -> binary
    cc = subprocess.run(
        ["clang", c_file, "-lm", "-o", bin_file],
        capture_output=True, text=True,
    )
    assert cc.returncode == 0, cc.stderr

    # 4. run and diff against CPython
    run = subprocess.run([bin_file], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert run.stdout == expected, (run.stdout, expected)
    py = subprocess.run([sys.executable, path], capture_output=True, text=True)
    assert py.stdout == expected


def test_m3_empty_module(ir2c_bin):
    import json
    doc = json.dumps(["module", []])
    run = subprocess.run(
        [ir2c_bin], input=doc, capture_output=True, text=True, timeout=10
    )
    assert run.returncode == 0
    assert "#include <stdio.h>" in run.stdout
    assert "int main(void)" in run.stdout
