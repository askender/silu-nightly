"""f-strings: one fmt(...) call across every backend, and front-end parity
(the self-hosted front end must desugar identically to ir_generator)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROGRAMS = [
    # (source, expected stdout)
    ('x: int = 7\nname = "silu"\nprint(f"{x} + {name} = 10")\n',
     "7 + silu = 10\n"),
    ('print(f"no exprs")\nprint(f"")\n', "no exprs\n\n"),
    ('x = 5\nprint(f"{x}")\n', "5\n"),
    ('print(f"a{{b}}c")\n', "a{b}c\n"),
    ('a = 2\nb = 3\nprint(f"{a * b} items")\n', "6 items\n"),
    ('v = 3.5\nprint(f"got {v}")\n', "got 3.5\n"),
    ('flag = True\nprint(f"[{flag}]")\n', "[True]\n"),
    ("data = {'k': 1}\nprint(f'k={data[\"k\"]}')\n", "k=1\n"),
]


def _py_eval(src):
    return subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True
    ).stdout


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_cpython_semantics(source, expected):
    # CPython defines the semantics (no specs/conversions allowed here)
    assert _py_eval(source) == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_ast_interpreter(source, expected):
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", "/dev/stdin"],
        input=source, capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_ir_interpreter(source, expected):
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ir.json", delete=False
    ) as h:
        h.write(ir)
        ir_path = h.name
    r = subprocess.run(
        [sys.executable, "-m", "silu", "exec", ir_path],
        capture_output=True, text=True, cwd=REPO,
    )
    os.unlink(ir_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_typed_build(source, expected, tmp_path):
    path = str(tmp_path / "fs.si")
    with open(path, "w") as h:
        h.write(source)
    binary = str(tmp_path / "fs")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", path, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=30)
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_frontend_parity(source, expected, tmp_path):
    """The self-hosted front end desugars f-strings identically."""
    sys.path.insert(0, REPO)
    from tests import ensure_fe_binary

    fe = ensure_fe_binary()
    ref = json.loads(subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout)
    got = json.loads(subprocess.run(
        [fe], input=source, capture_output=True, text=True, timeout=60
    ).stdout)
    assert got == ref


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_fstring_ir2c_build(source, expected, tmp_path):
    """The pure-Silu C backend runs the fmt() desugar."""
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    ir2c = str(tmp_path / "ir2c")
    subprocess.run(
        [sys.executable, "-m", "silu", "build",
         os.path.join(REPO, "selfhost/ir2c.si"), "-o", ir2c],
        check=True, capture_output=True, cwd=REPO,
    )
    c_file = str(tmp_path / "fs.c")
    binary = str(tmp_path / "fs")
    c = subprocess.run(
        [ir2c], input=ir, capture_output=True, text=True, timeout=120
    )
    assert c.returncode == 0, c.stderr
    with open(c_file, "w") as h:
        h.write(c.stdout)
    subprocess.run(["clang", "-O2", c_file, "-o", binary], check=True)
    r = subprocess.run([binary], capture_output=True, text=True, timeout=30)
    assert r.stdout == expected
