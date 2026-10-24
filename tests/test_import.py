"""Cross-file imports (Rust `mod` shape) across every surface.

import foo / from foo import x: foo.si next to the importer is parsed,
its own imports expanded, and its top-level statements inlined at the
import position; foo.X references rewrite to X. Each file inlines
once; cycles and missing .si shadows are errors; imports that resolve
to no .si file (os, sys, ...) keep their node and stay inert.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = f"{REPO}/selfhost/silu_fe.si"
IR2C = f"{REPO}/selfhost/ir2c.si"


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _merged_source(main_path):
    """CPython reference input: the expanded single-file program."""
    sys.path.insert(0, REPO)
    from silu.importer import expand_imports_tree

    tree = expand_imports_tree(
        open(main_path).read(), os.path.dirname(os.path.abspath(main_path))
    )
    return ast.unparse(tree)


CASES = {
    "basic": {
        "mod_a.si": "def helper(x: int) -> int:\n    return x * 2\n",
        "main.si": (
            "import mod_a\n\n"
            "def main() -> int:\n"
            "    print(mod_a.helper(21))\n"
            "    return 0\n"
        ),
        "expected": "42\n",
    },
    "from_import": {
        "geom.si": (
            "PI: float = 3.25\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "from geom import PI, area\n\n"
            "def main() -> int:\n"
            "    print(area(2.0))\n"
            "    print(PI)\n"
            "    return 0\n"
        ),
        "expected": "13.0\n3.25\n",
    },
    "transitive": {
        "c.si": "def three() -> int:\n    return 3\n",
        "b.si": (
            "import c\n\n"
            "def two_times_c() -> int:\n"
            "    return 2 * c.three()\n"
        ),
        "main.si": (
            "import b\n\n"
            "def main() -> int:\n"
            "    print(b.two_times_c())\n"
            "    return 0\n"
        ),
        "expected": "6\n",
    },
    "diamond": {
        "a.si": "def one() -> int:\n    return 1\n",
        "b.si": "import a\n\ndef b_val() -> int:\n    return 10 + a.one()\n",
        "c.si": "import a\n\ndef c_val() -> int:\n    return 20 + a.one()\n",
        "main.si": (
            "import b\n"
            "import c\n\n"
            "def main() -> int:\n"
            "    print(b.b_val() + c.c_val())\n"
            "    return 0\n"
        ),
        "expected": "32\n",
    },
    "builtin_untouched": {
        "main.si": (
            "import sys\n\n"
            "def main() -> int:\n"
            "    print(\"ok\")\n"
            "    return 0\n"
        ),
        "expected": "ok\n",
    },
    # ---- imports nested inside function/class bodies hoist to
    # compile time (module inlines at module level, the in-body
    # statement becomes pass) on every surface
    "nested_from_import": {
        "geom.si": (
            "PI: float = 3.5\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "def use(n: float) -> float:\n"
            "    from geom import area\n"
            "    return area(n)\n\n"
            "def main() -> int:\n"
            "    print(use(2.0))\n"
            "    return 0\n"
        ),
        "expected": "14.0\n",
    },
    "nested_plain_import": {
        "geom.si": (
            "PI: float = 3.5\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "def use(n: float) -> float:\n"
            "    import geom\n"
            "    return geom.area(n) + geom.PI\n\n"
            "def main() -> int:\n"
            "    print(use(2.0))\n"
            "    return 0\n"
        ),
        "expected": "17.5\n",
    },
    "nested_in_class_method": {
        "geom.si": (
            "PI: float = 3.5\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "class Calc:\n"
            "    def area2(self, r: float) -> float:\n"
            "        from geom import area\n"
            "        return area(r)\n\n"
            "def main() -> int:\n"
            "    c = Calc()\n"
            "    print(c.area2(2.0))\n"
            "    return 0\n"
        ),
        "expected": "14.0\n",
    },
    "nested_deep_and_diamond": {
        "geom.si": (
            "PI: float = 3.5\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "def outer(n: float) -> float:\n"
            "    def inner(r: float) -> float:\n"
            "        from geom import area\n"
            "        return area(r)\n"
            "    return inner(n)\n\n"
            "def again(n: float) -> float:\n"
            "    from geom import area\n"
            "    return area(n)\n\n"
            "def main() -> int:\n"
            "    print(outer(2.0) + again(2.0))\n"
            "    return 0\n"
        ),
        "expected": "28.0\n",
    },
    "nested_import_only_body": {
        "geom.si": (
            "PI: float = 3.5\n\n"
            "def area(r: float) -> float:\n"
            "    return PI * r * r\n"
        ),
        "main.si": (
            "def noop() -> int:\n"
            "    from geom import area\n"
            "    return 0\n\n"
            "def main() -> int:\n"
            "    noop()\n"
            "    print(\"done\")\n"
            "    return 0\n"
        ),
        "expected": "done\n",
    },
    "nested_transitive": {
        "leafc.si": "def three() -> int:\n    return 3\n",
        "midc.si": (
            "def call_leaf() -> int:\n"
            "    from leafc import three\n"
            "    return three()\n"
        ),
        "main.si": (
            "import midc\n\n"
            "def main() -> int:\n"
            "    print(midc.call_leaf())\n"
            "    return 0\n"
        ),
        "expected": "3\n",
    },
}


@pytest.fixture(params=sorted(CASES))
def program(tmp_path, request):
    case = CASES[request.param]
    for name, text in case.items():
        if name != "expected":
            _write(tmp_path, name, text)
    return str(tmp_path / "main.si"), case["expected"], request.param


def test_import_cpython(program):
    main, expected, _ = program
    r = subprocess.run(
        [sys.executable, "-c", _merged_source(main) + "\nmain()\n"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_import_ast_interpreter(program):
    main, expected, _ = program
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", main],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected


def test_import_ir_interpreter(program):
    main, expected, _ = program
    r = subprocess.run(
        [sys.executable, "-m", "silu", "ir", main, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    with tempfile.NamedTemporaryFile("w", suffix=".ir.json", delete=False) as h:
        h.write(r.stdout)
        ir_path = h.name
    x = subprocess.run(
        [sys.executable, "-m", "silu", "exec", ir_path],
        capture_output=True, text=True, cwd=REPO,
    )
    os.unlink(ir_path)
    assert x.returncode == 0, x.stderr
    assert x.stdout == expected + "0\n"  # main()'s return echo


def test_import_typed_build(program, tmp_path):
    main, expected, _ = program
    binary = str(tmp_path / "prog")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", main, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected


def test_import_ir2c_build(program, tmp_path):
    main, expected, _ = program
    ir = subprocess.run(
        [sys.executable, "-m", "silu", "ir", main, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    ir2c = str(tmp_path / "ir2c")
    subprocess.run(
        [sys.executable, "-m", "silu", "build", IR2C, "-o", ir2c],
        check=True, capture_output=True, cwd=REPO,
    )
    c_file = str(tmp_path / "p.c")
    binary = str(tmp_path / "p")
    c = subprocess.run([ir2c], input=ir, capture_output=True, text=True, timeout=120)
    assert c.returncode == 0, c.stderr
    with open(c_file, "w") as h:
        h.write(c.stdout)
    subprocess.run(["clang", "-O2", c_file, "-o", binary], check=True)
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == expected


def test_import_frontend_parity(program):
    """The self-hosted front end expands imports identically."""
    main, _, _ = program
    from tests import ensure_fe_binary

    fe = ensure_fe_binary()
    ref = json.loads(subprocess.run(
        [sys.executable, "-m", "silu", "ir", main, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout)
    # the fe binary resolves imports relative to ITS cwd
    got = json.loads(subprocess.run(
        [fe], stdin=open(main), capture_output=True, text=True, timeout=120,
        cwd=os.path.dirname(main),
    ).stdout)
    assert got == ref


def test_import_cycle_rejected(tmp_path):
    _write(tmp_path, "x.si", "import y\n\ndef xv() -> int:\n    return 1\n")
    _write(tmp_path, "y.si", "import x\n\ndef yv() -> int:\n    return 2\n")
    main = _write(tmp_path, "main.si", "import x\n\nprint(x.xv())\n")
    r = subprocess.run(
        [sys.executable, "-m", "silu", "ir", main],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode != 0
    assert "cycle" in (r.stdout + r.stderr)


def test_import_cycle_rejected_frontend(tmp_path):
    _write(tmp_path, "x.si", "import y\n\ndef xv() -> int:\n    return 1\n")
    _write(tmp_path, "y.si", "import x\n\ndef yv() -> int:\n    return 2\n")
    main = _write(tmp_path, "main.si", "import x\n\nprint(x.xv())\n")
    from tests import ensure_fe_binary

    fe = ensure_fe_binary()
    r = subprocess.run(
        [fe], stdin=open(main), capture_output=True, text=True,
        cwd=os.path.dirname(main),
    )
    assert r.returncode != 0
    assert "cycle" in (r.stdout + r.stderr)


def test_class_import(tmp_path):
    _write(tmp_path, "shapes.si", (
        "class Box:\n"
        "    w: int\n\n"
        "    def area(self) -> int:\n"
        "        return self.w * self.w\n"
    ))
    main = _write(tmp_path, "main.si", (
        "import shapes\n\n"
        "def main() -> int:\n"
        "    b = shapes.Box(6)\n"
        "    print(b.area())\n"
        "    return 0\n"
    ))
    for dim in ("interpret",):
        r = subprocess.run(
            [sys.executable, "-m", "silu", dim, main],
            capture_output=True, text=True, cwd=REPO,
        )
        assert "36" in r.stdout, (dim, r.stderr)
    binary = str(tmp_path / "prog")
    subprocess.run(
        [sys.executable, "-m", "silu", "build", main, "-o", binary],
        check=True, capture_output=True, cwd=REPO,
    )
    r = subprocess.run([binary], capture_output=True, text=True)
    assert r.stdout == "36\n"


def _alias_module(tmp_path):
    _write(tmp_path, "leafx.si", (
        "SCALE: int = 7\n\n"
        "def scale(x: int) -> int:\n"
        "    return x * SCALE\n"
    ))


def test_import_as_alias(tmp_path):
    """`import m as a` binds a second alias for attribute rewriting
    (front end only: the self-hosted fe parser does not accept `as`)."""
    _alias_module(tmp_path)
    main = _write(tmp_path, "main.si", (
        "import leafx as lx\n\n"
        "def main() -> int:\n"
        "    print(lx.scale(6))\n"
        "    return 0\n"
    ))
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", main],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "42\n"


def test_import_as_alias_diamond(tmp_path):
    """The second import of an already-inlined module under a NEW
    alias must still register that alias (old bug: registered only on
    first load, so lx.X stayed unresolved)."""
    _alias_module(tmp_path)
    main = _write(tmp_path, "main.si", (
        "import leafx\n"
        "import leafx as lx\n\n"
        "def main() -> int:\n"
        "    print(lx.scale(6) + leafx.scale(1))\n"
        "    return 0\n"
    ))
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", main],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "49\n"
    binary = str(tmp_path / "prog")
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", main, "-o", binary],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([binary], capture_output=True, text=True, timeout=60)
    assert r.stdout == "49\n"


def test_nested_as_alias(tmp_path):
    """Same aliasing fix for imports hoisted out of function bodies."""
    _alias_module(tmp_path)
    main = _write(tmp_path, "main.si", (
        "import leafx\n\n"
        "def use(n: int) -> int:\n"
        "    import leafx as lx\n"
        "    return lx.scale(n)\n\n"
        "def main() -> int:\n"
        "    print(use(3))\n"
        "    return 0\n"
    ))
    r = subprocess.run(
        [sys.executable, "-m", "silu", "interpret", main],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "21\n"
