"""Rust-shaped dict operations across every backend: get(k),
get(k, default), and items()/keys()/values() iteration (plus the
bare `for k in d` key walk).

Iteration order is implementation-defined (hash-slot order, like
Rust's HashMap::iter), so every program asserts order-independent
facts: sums, counts, sorted keys. items()/keys()/values() are only
supported in the for-loop header - no intermediate list is
materialized.
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = f"{REPO}/selfhost/silu_fe_main.si"
IR2C = f"{REPO}/selfhost/ir2c.si"

PROGRAMS = [
    # get with and without default, hits and misses
    (
        "d = {\"a\": 1, \"b\": 2}\n"
        "print(d.get(\"a\"))\n"
        "print(d.get(\"zz\"))\n"
        "print(d.get(\"zz\", 42))\n",
        "1\nNone\n42\n",
    ),
    # items() iteration over a boxed dict: order-independent sum
    (
        "d = {\"x\": 5, \"y\": 7, \"z\": 3}\n"
        "s = 0\n"
        "for k, v in d.items():\n"
        "    s += v\n"
        "print(s)\n"
        "n = 0\n"
        "for k2 in d.keys():\n"
        "    n += 1\n"
        "print(n)\n"
        "t = 0\n"
        "for v2 in d.values():\n"
        "    t += v2\n"
        "print(t)\n",
        "15\n3\n15\n",
    ),
    # raw dict[str, int]: annotated, so the typed backend keeps it raw
    (
        "def main() -> int:\n"
        "    d: dict[str, int] = {\"a\": 1, \"b\": 2, \"c\": 3}\n"
        "    total: int = 0\n"
        "    for k, v in d.items():\n"
        "        total += v\n"
        "    print(total)\n"
        "    print(d.get(\"b\"))\n"
        "    print(d.get(\"zz\", 99))\n"
        "    nk: int = 0\n"
        "    for k2 in d:\n"
        "        nk += 1\n"
        "    print(nk)\n"
        "    return 0\n",
        "6\n2\n99\n3\n",
    ),
    # raw dict[int, int] / dict[int, float]
    (
        "def main() -> int:\n"
        "    d: dict[int, int] = {10: 100, 20: 200}\n"
        "    s: int = 0\n"
        "    for k, v in d.items():\n"
        "        s += k + v\n"
        "    print(s)\n"
        "    print(d.get(10))\n"
        "    e: dict[int, float] = {1: 1.5, 2: 2.5}\n"
        "    t: float = 0.0\n"
        "    for k2, v2 in e.items():\n"
        "        t += v2\n"
        "    print(t)\n"
        "    return 0\n",
        "330\n100\n4.0\n",
    ),
    # raw dict[str, float] with the key used inside the loop
    (
        "def main() -> int:\n"
        "    d: dict[str, float] = {\"pi\": 3.5, \"e\": 2.5}\n"
        "    t: float = 0.0\n"
        "    names = \"\"\n"
        "    for k, v in d.items():\n"
        "        t += v\n"
        "        names = names + k\n"
        "    print(t)\n"
        "    print(len(names))\n"
        "    return 0\n",
        "6.0\n3\n",
    ),
    # keys picked up and reused after the loop (boxed dict)
    (
        "d = {\"one\": 1, \"two\": 2}\n"
        "ks = []\n"
        "for k in d.keys():\n"
        "    ks.append(k)\n"
        "print(len(ks))\n"
        "total = 0\n"
        "for k2 in ks:\n"
        "    total += len(k2)\n"
        "print(total)\n",
        "2\n6\n",
    ),
]


def _run_cpython(source: str) -> str:
    src = source + ("\nmain()\n" if "def main" in source else "")
    r = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_cpython(source, expected):
    assert _run_cpython(source) == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_ast_interpreter(source, expected):
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", "/dev/stdin"],
        input=source, capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_ir_interpreter(source, expected):
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
    assert r.returncode == 0, r.stderr
    # the IR interpreter echoes main()'s return value
    want = expected + ("0\n" if "def main" in source else "")
    assert r.stdout == want


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_typed_build(source, expected, tmp_path):
    path = str(tmp_path / "d.si")
    with open(path, "w") as h:
        h.write(source)
    binary = str(tmp_path / "d")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", path, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_frontend_parity(source, expected):
    """The self-hosted front end parses dict ops identically."""
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


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_dict_ops_ir2c_build(source, expected, tmp_path):
    """The pure-Silu C backend compiles dict iteration and get."""
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    ir2c = str(tmp_path / "ir2c")
    subprocess.run(
        [sys.executable, "-m", "silu", "build", IR2C, "-o", ir2c],
        check=True, capture_output=True, cwd=REPO,
    )
    c_file = str(tmp_path / "d.c")
    binary = str(tmp_path / "d")
    c = subprocess.run(
        [ir2c], input=ir, capture_output=True, text=True, timeout=120
    )
    assert c.returncode == 0, c.stderr
    with open(c_file, "w") as h:
        h.write(c.stdout)
    subprocess.run(["clang", "-O2", c_file, "-o", binary], check=True)
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected
