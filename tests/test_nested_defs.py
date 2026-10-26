"""Nested def + lambda with Rust nested-item semantics, across every
backend and with front-end parity (the self-hosted front end must hoist
identically to ir_generator)."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = f"{REPO}/selfhost/silu_fe_main.si"


def _silu_to_cpython(source: str) -> str:
    # Silu synthesizes __init__ from annotated fields; give the CPython
    # reference the equivalent by inserting it after the field block
    lines = source.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.startswith("class ") and line.rstrip().endswith(":"):
            j = i + 1
            fields = []
            while (
                j < len(lines)
                and lines[j].startswith("    ")
                and not lines[j].lstrip().startswith("def ")
            ):
                stripped = lines[j].strip()
                if stripped and ":" in stripped and "=" not in stripped:
                    fields.append(stripped.split(":")[0].strip())
                out.append(lines[j])
                j += 1
            if fields:
                params = ", ".join(fields)
                out.append(f"    def __init__(self, {params}):")
                for f in fields:
                    out.append(f"        self.{f} = {f}")
            i = j
            continue
        i += 1
    return "\n".join(out)

PROGRAMS = [
    # (source, expected stdout)
    # plain nested def, direct call
    (
        "def outer(x: int) -> int:\n"
        "    def inner(y: int) -> int:\n"
        "        return y * 2\n"
        "    return inner(x) + inner(x + 1)\n\n"
        "print(outer(5))\n",
        "22\n",
    ),
    # lambda as a value, called through the local
    (
        "def md() -> int:\n"
        "    g = lambda x: x * 2\n"
        "    return g(21)\n\n"
        "print(md())\n",
        "42\n",
    ),
    # nested def touching self: gets self prepended
    (
        "class Counter:\n"
        "    n: int\n\n"
        "    def bump_twice(self) -> int:\n"
        "        def helper(k: int) -> int:\n"
        "            return self.n + k\n"
        "        return helper(1) + helper(2)\n\n"
        "    def plain(self, v: int) -> int:\n"
        "        def pure(a: int) -> int:\n"
        "            return a * 3\n"
        "        return pure(v)\n\n"
        "def main() -> int:\n"
        "    c = Counter(100)\n"
        "    print(c.bump_twice())\n"
        "    print(c.plain(7))\n"
        "    return 0\n",
        "203\n21\n",
    ),
    # chained nesting; transitive self need (step calls half, half uses self)
    (
        "class W:\n"
        "    base: int\n\n"
        "    def calc(self, v: int) -> int:\n"
        "        def step(x: int) -> int:\n"
        "            def half(y: int) -> int:\n"
        "                return self.base + y\n"
        "            return half(x) + half(x + 1)\n"
        "        return step(v) + step(v * 2)\n\n"
        "    def nop(self, v: int) -> int:\n"
        "        def stat(a: int) -> int:\n"
        "            return a - 1\n"
        "        return stat(v)\n\n"
        "def main() -> int:\n"
        "    w = W(10)\n"
        "    print(w.calc(3))\n"
        "    print(w.nop(5))\n"
        "    return 0\n",
        "60\n4\n",
    ),
    # lambda + class in the same module (the crash combo during bring-up)
    (
        "class C:\n"
        "    n: int\n\n"
        "def md() -> int:\n"
        "    g = lambda x: x * 2\n"
        "    return g(21)\n\n"
        "print(C(4).n + md())\n",
        "46\n",
    ),
    # nested def referring only to module globals (no capture)
    (
        "K: int = 10\n\n"
        "def f(v: int) -> int:\n"
        "    def g(a: int) -> int:\n"
        "        return a + K\n"
        "    return g(v)\n\n"
        "print(f(5))\n",
        "15\n",
    ),
]


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_nested_cpython_semantics(source, expected):
    # CPython doesn't auto-call main() - append the call like Silu does
    source = _silu_to_cpython(source)
    r = subprocess.run(
        [sys.executable, "-c", source + "\nmain()\n"
         if "def main" in source else source],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_nested_ast_interpreter(source, expected):
    # native closures define the semantics
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", "/dev/stdin"],
        input=source, capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_nested_ir_interpreter(source, expected):
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
    # the IR interpreter echoes main()'s return value as the module result
    want = expected + ("0\n" if "def main" in source else "")
    assert r.stdout == want


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_nested_typed_build(source, expected, tmp_path):
    path = str(tmp_path / "nd.si")
    with open(path, "w") as h:
        h.write(source)
    binary = str(tmp_path / "nd")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", path, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected


@pytest.mark.parametrize("source,expected", PROGRAMS)
def test_nested_frontend_parity(source, expected):
    """The self-hosted front end hoists identically to ir_generator."""
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
def test_nested_ir2c_build(source, expected, tmp_path):
    """The pure-Silu C backend compiles hoisted defs and lambda
    funcrefs: silu ir -> ir2c.si -> C -> clang."""
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    ir2c = str(tmp_path / "ir2c")
    subprocess.run(
        [sys.executable, "-m", "silu", "build", f"{REPO}/selfhost/ir2c.si", "-o", ir2c],
        check=True, capture_output=True, cwd=REPO,
    )
    c_file = str(tmp_path / "nd.c")
    binary = str(tmp_path / "nd")
    c = subprocess.run(
        [ir2c], input=ir, capture_output=True, text=True, timeout=120
    )
    assert c.returncode == 0, c.stderr
    with open(c_file, "w") as h:
        h.write(c.stdout)
    subprocess.run(["clang", "-O2", c_file, "-o", binary], check=True)
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected


def test_capture_rejected(tmp_path):
    """Rust nested-item semantics: capturing an enclosing local errors."""
    path = str(tmp_path / "cap.si")
    with open(path, "w") as h:
        h.write(
            "def outer(base: int) -> int:\n"
            "    def inner(x: int) -> int:\n"
            "        return x + base\n"
            "    return inner(5)\n"
        )
    r = subprocess.run(
        [sys.executable, "-m", "silu", "ir", path],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode != 0
    assert "captures" in r.stderr
