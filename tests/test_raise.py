"""raise X(msg) abort semantics (Rust panic! shape) across surfaces.

Compiled backends print "X: msg" to stdout and exit(1); the
interpreters propagate a real exception (message on stderr, exit 1).
raise SystemExit(n) keeps its existing exit-code semantics.
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = f"{REPO}/selfhost/silu_fe.si"
IR2C = f"{REPO}/selfhost/ir2c.si"

# (source, stdout_before_raise, exception line, exit_code)
PROGRAMS = [
    (
        "def check(x: int) -> int:\n"
        "    if x < 0:\n"
        "        raise ValueError(\"negative not allowed\")\n"
        "    return x\n\n"
        "def main() -> int:\n"
        "    print(check(5))\n"
        "    print(check(0 - 3))\n"
        "    return 0\n",
        "5\n",
        "ValueError: negative not allowed",
        1,
    ),
    # computed message
    (
        "n = 7\n"
        "print(\"start\")\n"
        "raise RuntimeError(\"code \" + str(n))\n",
        "start\n",
        "RuntimeError: code 7",
        1,
    ),
    # SystemExit keeps the exit code and prints nothing extra
    (
        "print(\"before\")\n"
        "raise SystemExit(3)\n",
        "before\n",
        None,
        3,
    ),
]


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_cpython(source, before, exc_line, code):
    src = source + ("\nmain()\n" if "def main" in source else "")
    r = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True
    )
    assert r.returncode == code
    assert r.stdout == before
    if exc_line is not None:
        assert r.stderr.strip().endswith(exc_line)


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_ast_interpreter(source, before, exc_line, code):
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", "/dev/stdin"],
        input=source, capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == code
    assert r.stdout == before
    if exc_line is not None:
        # interpreter wraps the message; the text survives
        assert exc_line.split(": ", 1)[1] in r.stderr


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_ir_interpreter(source, before, exc_line, code):
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".ir.json", delete=False) as h:
        h.write(ir)
        ir_path = h.name
    r = subprocess.run(
        [sys.executable, "-m", "silu", "exec", ir_path],
        capture_output=True, text=True, cwd=REPO,
    )
    os.unlink(ir_path)
    assert r.returncode == code
    assert r.stdout == before
    if exc_line is not None:
        assert exc_line.split(": ", 1)[1] in r.stderr


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_typed_build(source, before, exc_line, code, tmp_path):
    path = str(tmp_path / "r.si")
    with open(path, "w") as h:
        h.write(source)
    binary = str(tmp_path / "r")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", path, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.returncode == code
    want = before + ((exc_line + "\n") if exc_line else "")
    assert r.stdout == want


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_frontend_parity(source, before, exc_line, code):
    from tests import ensure_fe_binary

    fe = ensure_fe_binary()
    ref = json.loads(subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout)
    got = json.loads(subprocess.run(
        [fe], input=source, capture_output=True, text=True, timeout=120
    ).stdout)
    assert got == ref


@pytest.mark.parametrize("source,before,exc_line,code", PROGRAMS)
def test_raise_ir2c_build(source, before, exc_line, code, tmp_path):
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    ir2c = str(tmp_path / "ir2c")
    subprocess.run(
        [sys.executable, "-m", "silu", "build", IR2C, "-o", ir2c],
        check=True, capture_output=True, cwd=REPO,
    )
    c_file = str(tmp_path / "r.c")
    binary = str(tmp_path / "r")
    c = subprocess.run(
        [ir2c], input=ir, capture_output=True, text=True, timeout=120
    )
    assert c.returncode == 0, c.stderr
    with open(c_file, "w") as h:
        h.write(c.stdout)
    subprocess.run(["clang", "-O2", c_file, "-o", binary], check=True)
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.returncode == code
    want = before + ((exc_line + "\n") if exc_line else "")
    assert r.stdout == want
