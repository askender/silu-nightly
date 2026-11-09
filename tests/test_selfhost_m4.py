"""M4 self-hosting milestone test (docs/m4_frontend.md): selfhost/silu_fe.si.

A Silu front end (lexer + recursive-descent parser + JSON emitter)
written in Silu itself. Verified on three axes:

1. IR parity: for every selfhost program (including silu_fe.si itself -
   the self-hosting closure), the compiled front end emits JSON that
   equals `silu ir --format json` byte-for-byte.
2. End-to-end via M2: M4 IR -> selfhost/ir_interp.si -> CPython parity.
3. End-to-end via M3: M4 IR -> selfhost/ir2c.si -> C -> clang -> parity.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = f"{REPO}/selfhost/silu_fe_main.si"
M2_INTERP = f"{REPO}/selfhost/ir_interp.si"
M3_IR2C = f"{REPO}/selfhost/ir2c.si"

SELFHOST_SOURCES = [
    f"{REPO}/selfhost/calc.si",
    f"{REPO}/selfhost/ir_interp.si",
    f"{REPO}/selfhost/ir2c.si",
    # silu_fe.si parsing itself is the bootstrap closure
    FRONTEND,
]

CORE_PROGRAMS = [
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
    ("if 3 > 2:\n    print(1)\nelse:\n    print(2)\n"
     "if 1 > 2:\n    print(3)\nelse:\n    print(4)\n",
     "1\n4\n"),
]


def _build(source, out):
    """Build a .si source path (or inline source text) to a binary."""
    if "\n" in source or not os.path.exists(source):
        path = out + ".si"
        with open(path, "w") as handle:
            handle.write(source)
        source = path
    result = subprocess.run(
        [sys.executable, "-m", "silu", "build", source, "-o", out],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="module")
def fe_bin(tmp_path_factory):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    return _build(
        FRONTEND, str(tmp_path_factory.mktemp("m4") / "silu_fe")
    )


@pytest.fixture(scope="module")
def m2_bin(tmp_path_factory):
    return _build(
        M2_INTERP, str(tmp_path_factory.mktemp("m4m2") / "ir_interp")
    )


@pytest.fixture(scope="module")
def m3_bin(tmp_path_factory):
    return _build(M3_IR2C, str(tmp_path_factory.mktemp("m4m3") / "ir2c"))


def _reference_ir(source_path):
    result = subprocess.run(
        [sys.executable, "-m", "silu", "ir", source_path, "--format", "json"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _fe_ir(fe_binary, source_path):
    with open(source_path) as handle:
        result = subprocess.run(
            [fe_binary], stdin=handle, capture_output=True, text=True,
            # stdin sources resolve imports against the cwd; the
            # reference front end uses the file's own directory
            cwd=os.path.dirname(os.path.abspath(source_path)),
            timeout=120,
        )
    assert result.returncode == 0, (result.stdout, result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("source", SELFHOST_SOURCES)
def test_m4_ir_parity(fe_bin, source):
    """The compiled Silu front end reproduces `silu ir --format json`
    exactly - including for its own source (bootstrap closure)."""
    assert _fe_ir(fe_bin, source) == _reference_ir(source)


def test_m4_small_inputs(fe_bin):
    """Spot inputs keep working after any front end change."""
    for text, expected in [
        ("x\n", ["module", [["line", 1], ["name", "x"]]]),
        ("1\n", ["module", [["line", 1], ["const", 1]]]),
    ]:
        result = subprocess.run(
            [fe_bin], input=text, capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("source,expected", CORE_PROGRAMS)
def test_m4_to_m2_end_to_end(fe_bin, m2_bin, source, expected):
    """M4 front end -> M2 (Silu-written IR interpreter) -> stdout."""
    ir = subprocess.run(
        [fe_bin], input=source, capture_output=True, text=True, timeout=30
    )
    assert ir.returncode == 0, ir.stderr
    run = subprocess.run(
        [m2_bin], input=ir.stdout, capture_output=True, text=True, timeout=60
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == expected


@pytest.mark.parametrize("source,expected", CORE_PROGRAMS)
def test_m4_to_m3_end_to_end(fe_bin, m3_bin, source, expected):
    """M4 front end -> M3 (Silu-written ir2c) -> C -> clang -> stdout."""
    ir = subprocess.run(
        [fe_bin], input=source, capture_output=True, text=True, timeout=30
    )
    assert ir.returncode == 0, ir.stderr
    c_src = subprocess.run(
        [m3_bin], input=ir.stdout, capture_output=True, text=True, timeout=60
    )
    assert c_src.returncode == 0, c_src.stderr
    with tempfile.TemporaryDirectory() as tmpdir:
        binary = os.path.join(tmpdir, "prog")
        c_file = os.path.join(tmpdir, "prog.c")
        with open(c_file, "w") as handle:
            handle.write(c_src.stdout)
        build = subprocess.run(
            ["clang", "-O2", c_file, "-o", binary],
            capture_output=True,
            text=True,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=30
        )
        assert run.returncode == 0, run.stderr
        assert run.stdout == expected


# ---- language surface the M4 front end relies on ----
# These compiler features were added to make silu_fe.si self-host;
# each is checked against CPython semantics via compiled output.

FEATURE_PROGRAMS = [
    # x is True is identity, not truthiness ("s" is True -> False)
    (
        "def main() -> int:\n"
        "    s = \"hello\"\n"
        "    print(s is True, s is not True)\n"
        "    t = True\n"
        "    print(t is True, t is False)\n"
        "    n = None\n"
        "    print(n is True, n is False)\n"
        "    i = 1\n"
        "    print(i is True)\n"
        "    return 0\n",
        "False True\nTrue False\nFalse False\nFalse\n",
    ),
    # isinstance with builtin names and type tuples
    (
        "def box(v) -> object:\n"
        "    return v\n\n"
        "def main() -> int:\n"
        "    x = box(7)\n"
        "    y = box(\"hi\")\n"
        "    z = box([1])\n"
        "    b = box(True)\n"
        "    print(isinstance(x, int), isinstance(x, str))\n"
        "    print(isinstance(y, (str, int)), isinstance(y, (list, tuple)))\n"
        "    print(isinstance(z, list), isinstance(z, tuple))\n"
        "    print(isinstance(b, bool), isinstance(b, int))\n"
        "    print(isinstance(3, int), isinstance(3.5, float), isinstance(\"s\", str))\n"
        "    return 0\n",
        "True False\nTrue False\nTrue True\nTrue True\nTrue True True\n",
    ),
    # enumerate over lists and strings
    (
        "def main() -> int:\n"
        "    total: int = 0\n"
        "    for i, v in enumerate([10, 20, 30]):\n"
        "        total += i * v\n"
        "    print(total)\n"
        "    parts: list[str] = []\n"
        "    for i, ch in enumerate(\"abc\"):\n"
        "        parts.append(str(i) + ch)\n"
        "    print(parts[0], parts[1], parts[2])\n"
        "    return 0\n",
        "80\n0a 1b 2c\n",
    ),
    # raise SystemExit(code) terminates with the status
    (
        "def die(code: int):\n"
        "    print(\"dying\")\n"
        "    raise SystemExit(code)\n\n"
        "def main() -> int:\n"
        "    die(3)\n"
        "    print(\"unreachable\")\n"
        "    return 0\n",
        "dying\n",
    ),
    # int(s, base) for hex/binary/octal text
    (
        "def main() -> int:\n"
        "    print(int(\"ff\", 16))\n"
        "    print(int(\"0x20\", 16))\n"
        "    print(int(\"101\", 2))\n"
        "    print(int(\"17\", 8))\n"
        "    return 0\n",
        "255\n32\n5\n15\n",
    ),
    # sep.join(parts) on a raw str list
    (
        "def main() -> int:\n"
        "    parts: list[str] = []\n"
        "    parts.append('a')\n"
        "    parts.append('bb')\n"
        "    parts.append('ccc')\n"
        "    print(','.join(parts))\n"
        "    print(''.join(parts))\n"
        "    print('--'.join(parts))\n"
        "    empty: list[str] = []\n"
        "    print('x'.join(empty))\n"
        "    single: list[str] = []\n"
        "    single.append('only')\n"
        "    print('|'.join(single))\n"
        "    return 0\n",
        "a,bb,ccc\nabbccc\na--bb--ccc\n\nonly\n",
    ),
    # str predicates on dynamic (boxed) receivers
    (
        "def box(v) -> object:\n"
        "    return v\n\n"
        "def main() -> int:\n"
        "    a = box(\"7\")\n"
        "    b = box(\"w\")\n"
        "    c = box(\" \")\n"
        "    print(a.isdigit(), a.isalpha())\n"
        "    print(b.isalpha(), b.isdigit())\n"
        "    print(c.isspace(), c.isalpha())\n"
        "    return 0\n",
        "True False\nTrue False\nTrue False\n",
    ),
]


@pytest.mark.parametrize("source,expected_stdout", FEATURE_PROGRAMS)
def test_m4_language_surface(tmp_path, source, expected_stdout):
    """Compiler features needed by silu_fe.si, differential vs CPython."""
    binary = _build(source, str(tmp_path / "feat"))
    run = subprocess.run(
        [binary], capture_output=True, text=True, timeout=30
    )
    assert run.stdout == expected_stdout


@pytest.mark.parametrize(
    "source,expected_code",
    [
        ("def main() -> int:\n    raise SystemExit(3)\n", 3),
        ("def main() -> int:\n    raise SystemExit(0)\n", 0),
    ],
)
def test_system_exit_code(tmp_path, source, expected_code):
    binary = _build(source, str(tmp_path / "exitcode"))
    run = subprocess.run(
        [binary], capture_output=True, text=True, timeout=30
    )
    assert run.returncode == expected_code


# ---- dual-stack: the same .si source also runs under CPython ----

PYCOMPAT = f"{REPO}/tools/pycompat.py"


@pytest.mark.parametrize("source", SELFHOST_SOURCES)
def test_pycompat_silu_fe_matches(fe_bin, source):
    """silu_fe.si via tools/pycompat.py (CPython) emits the same IR as
    the compiled binary - one source, two execution stacks."""
    with open(source) as handle:
        cpython = subprocess.run(
            [sys.executable, PYCOMPAT, FRONTEND],
            stdin=handle, capture_output=True, text=True, timeout=300,
            # fe_compile resolves the INPUT's imports against the cwd
            cwd=os.path.dirname(os.path.abspath(source)),
        )
    assert cpython.returncode == 0, cpython.stderr[-400:]
    assert json.loads(cpython.stdout) == _fe_ir(fe_bin, source)


def test_pycompat_ir_interp_runs():
    """ir_interp.si under CPython executes the M2 program set with the
    same output as the compiled M2 binary."""
    for source, expected in CORE_PROGRAMS:
        ir_json = subprocess.run(
            [sys.executable, "-m", "silu", "ir", "--source", source,
             "--format", "json"],
            capture_output=True, text=True, cwd=REPO,
        )
        assert ir_json.returncode == 0, ir_json.stderr
        out_p = subprocess.run(
            [sys.executable, PYCOMPAT, M2_INTERP],
            input=ir_json.stdout, capture_output=True, text=True, timeout=300,
        )
        assert out_p.returncode == 0, out_p.stderr[-400:]
        assert out_p.stdout == expected


# ---- source round-trip: silu -> IR -> silu is an IR fixed point ----

def _round_trip(source_path):
    """source -> IR (repr) -> to-source -> source'. Returns the path."""
    ir_repr = subprocess.run(
        [sys.executable, "-m", "silu", "ir", source_path],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir_repr.returncode == 0, ir_repr.stderr
    ir_file = source_path + ".roundtrip.ir"
    with open(ir_file, "w") as handle:
        handle.write(ir_repr.stdout)
    out_file = source_path + ".roundtrip.si"
    conv = subprocess.run(
        [sys.executable, "-m", "silu", "to-source", ir_file, "-o", out_file],
        capture_output=True, text=True, cwd=REPO,
    )
    for path in (ir_file,):
        os.remove(path)
    assert conv.returncode == 0, conv.stderr
    return out_file


# import-bearing sources (the wrapper) cannot round-trip: expansion
# carries line numbers from OTHER files, which a regenerated single
# file cannot reproduce - the self-contained fe source covers the
# bootstrap-closure member instead
SELFCONTAINED_SOURCES = sorted(
    glob.glob(f"{REPO}/benchmarks/*.si")
) + [f for f in SELFHOST_SOURCES if f != FRONTEND] + [
    f"{REPO}/selfhost/silu_fe.si"
]


@pytest.mark.parametrize(
    "source", SELFCONTAINED_SOURCES, ids=[os.path.basename(f) for f in SELFCONTAINED_SOURCES]
)
def test_round_trip_ir_fixed_point(source):
    """IR(source) == IR(to_source(IR(source))) - byte-identical, for
    every selfhost program including the front end itself. Import-
    bearing sources (the wrapper) are excluded: expansion carries line
    numbers from OTHER files, which a regenerated single file cannot
    reproduce."""
    regenerated = _round_trip(source)
    a = subprocess.run(
        [sys.executable, "-m", "silu", "ir", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    b = subprocess.run(
        [sys.executable, "-m", "silu", "ir", regenerated, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    ).stdout
    os.remove(regenerated)
    assert a == b


def test_round_trip_semantics(tmp_path):
    """The regenerated calculator compiles and answers like the original."""
    regenerated = _round_trip(f"{REPO}/selfhost/calc.si")
    binary = _build(regenerated, str(tmp_path / "calc_rt"))
    for expr in ["1+2", "7/2", "(1+2)*3", "-(3+4)*2"]:
        run = subprocess.run(
            [binary], input=expr + "\n", capture_output=True, text=True,
            timeout=30,
        )
        expected = subprocess.run(
            [sys.executable, "-c", f"v=({expr}); print(int(v) if v==int(v) else v)"],
            capture_output=True, text=True,
        ).stdout
        assert run.stdout == expected, (expr, run.stdout, expected)


# ---- strict compile-time errors (no silent nulls) ----

@pytest.mark.parametrize(
    "source,fragment",
    [
        # undefined name must fail at build time, not at runtime
        (
            "def f() -> int:\n    return totally_undefined_name\n\n"
            "def main() -> int:\n    print(f())\n    return 0\n",
            "totally_undefined_name",
        ),
        # a missing method inside an attribute chain (x.m().f) is
        # caught even though the outer attribute intercepts the call
        (
            "class TokKind(Enum):\n    NAME = 0\n\n"
            "class Token:\n    kind: TokKind\n    text: str\n\n"
            "class Parser:\n    toks: list[Token]\n    pos: int\n\n"
            "    def parse(self) -> object:\n"
            "        name = self.expect_kind(TokKind.NAME).text\n"
            "        return None\n\n"
            "def main() -> int:\n    return 0\n",
            "expect_kind",
        ),
    ],
)
def test_strict_compile_errors(tmp_path, source, fragment):
    path = str(tmp_path / "strict.si")
    with open(path, "w") as handle:
        handle.write(source)
    build = subprocess.run(
        [sys.executable, "-m", "silu", "build", path, "-o", str(tmp_path / "x")],
        capture_output=True, text=True, timeout=60, cwd=REPO,
    )
    assert build.returncode != 0
    assert fragment in build.stderr


# ---- M5 stage 1: the Silu-written back end compiles calc.si ----

@pytest.fixture(scope="module")
def ir2c_bin(tmp_path_factory):
    return _build(
        M3_IR2C, str(tmp_path_factory.mktemp("m5") / "ir2c")
    )


def test_m5_ir2c_compiles_calc(fe_bin, ir2c_bin):
    """calc.si (classes/enums/match/strings/floats) through the pure
    Silu pipeline: silu_fe -> ir2c -> C -> clang, verified against
    CPython on the M1 expression set."""
    ir = subprocess.run(
        [fe_bin], stdin=open(f"{REPO}/selfhost/calc.si"),
        capture_output=True, text=True, timeout=60,
    )
    assert ir.returncode == 0, ir.stderr
    c_src = subprocess.run(
        [ir2c_bin], input=ir.stdout, capture_output=True, text=True, timeout=120,
    )
    assert c_src.returncode == 0, c_src.stderr
    assert "fn_tokenize" in c_src.stdout
    with tempfile.TemporaryDirectory() as tmpdir:
        c_file = os.path.join(tmpdir, "calc.c")
        binary = os.path.join(tmpdir, "calc")
        with open(c_file, "w") as handle:
            handle.write(c_src.stdout)
        build = subprocess.run(
            ["clang", "-O2", c_file, "-o", binary],
            capture_output=True, text=True,
        )
        assert build.returncode == 0, build.stderr
        for expr in [
            "1+2", "7/2", "(1+2)*3", "-(3+4)*2", "2*3+4",
            "10/4", "3-8", "2*(3+4)", "8/2/2",
            "1+2*3", "100/7", "9*9", "6-2-1", "(1+2)*(3+4)", "7-2*3",
        ]:
            run = subprocess.run(
                [binary], input=expr + "\n", capture_output=True, text=True,
                timeout=30,
            )
            expected = subprocess.run(
                [sys.executable, "-c",
                 f"v=({expr}); print(int(v) if v==int(v) else v)"],
                capture_output=True, text=True,
            ).stdout
            assert run.stdout == expected, (expr, run.stdout, expected)
        # error path: lexer failure exits 1 with the message
        bad = subprocess.run(
            [binary], input="1 $ 2\n", capture_output=True, text=True, timeout=30
        )
        assert bad.returncode == 1
        assert "lex error" in bad.stdout


# ---- M5 complete: the whole toolchain compiles itself ----

def test_m5_self_hosted_toolchain(fe_bin, ir2c_bin):
    """The front end binary (compiled from silu_fe.si by ir2c) parses
    silu_fe.si; the IR goes back through ir2c to C; the resulting binary
    matches `silu ir --format json` on every selfhost program. The
    toolchain can rebuild itself without the Python back end."""
    fe_ir = subprocess.run(
        [fe_bin], stdin=open(FRONTEND),
        capture_output=True, text=True, timeout=300,
        cwd=os.path.dirname(os.path.abspath(FRONTEND)),
    )
    assert fe_ir.returncode == 0, fe_ir.stderr
    c_src = subprocess.run(
        [ir2c_bin], input=fe_ir.stdout, capture_output=True, text=True, timeout=300,
    )
    assert c_src.returncode == 0, c_src.stderr
    with tempfile.TemporaryDirectory() as tmpdir:
        c_file = os.path.join(tmpdir, "fe.c")
        binary = os.path.join(tmpdir, "fe")
        with open(c_file, "w") as handle:
            handle.write(c_src.stdout)
        build = subprocess.run(
            ["clang", "-O2", c_file, "-o", binary],
            capture_output=True, text=True,
        )
        assert build.returncode == 0, build.stderr
        # ir2c's dynamic slots are untyped int64 - dynamic STRINGS
        # (the front end's import-expansion path) cannot ride in them
        # yet, so the loop keeps its selfhost scope with the wrapper
        # swapped for the self-contained fe source
        for f in [x for x in SELFHOST_SOURCES if x != FRONTEND] + [
            f"{REPO}/selfhost/silu_fe.si"
        ]:
            ref = subprocess.run(
                [sys.executable, "-m", "silu", "ir", f, "--format", "json"],
                capture_output=True, text=True, cwd=REPO,
            ).stdout
            run = subprocess.run(
                [binary], stdin=open(f), capture_output=True, text=True,
                timeout=600, cwd=os.path.dirname(os.path.abspath(f)),
            )
            assert run.returncode == 0, (f, run.stderr[-200:])
            assert json.loads(run.stdout) == json.loads(ref), f


# ---- M5 coverage: benchmarks through the Silu-written backend ----

BENCHMARK_SKIP = {
    "jsonparse.si",  # heterogeneous dynamic program, known gap
    # Json sum-type twin: the json_* builtins are not in the ir2c
    # plane (C runtime has no tagged-block library); its four-plane
    # verification lives in tests/test_json_type.py instead
    "jsonparse_json.si",
}


def test_m5_benchmarks_match_cpython(ir2c_bin):
    """Every benchmark (minus the known-gap file) compiles through the
    pure-Silu ir2c and its output matches running the same file under
    CPython."""
    import glob as _glob
    files = sorted(
        f for f in _glob.glob(f"{REPO}/benchmarks/*.si")
        if os.path.basename(f) not in BENCHMARK_SKIP
    )
    assert len(files) >= 13
    for f in files:
        ir = subprocess.run(
            [sys.executable, "-m", "silu", "ir", f, "--format", "json"],
            capture_output=True, text=True, cwd=REPO,
        ).stdout
        c = subprocess.run(
            [ir2c_bin], input=ir, capture_output=True, text=True, timeout=120
        )
        assert c.returncode == 0, (f, c.stdout[:200])
        with tempfile.TemporaryDirectory() as td:
            cf = os.path.join(td, "x.c"); bf = os.path.join(td, "x")
            with open(cf, "w") as h:
                h.write(c.stdout)
            # generated benchmark C uses pow (nbody); Linux needs -lm
            # at link time, on macOS libm lives in libSystem
            link = ["clang", "-O2", cf, "-o", bf]
            if sys.platform != "darwin":
                link.append("-lm")
            b = subprocess.run(link, capture_output=True, text=True)
            assert b.returncode == 0, (f, b.stderr[:300])
            run = subprocess.run([bf], capture_output=True, text=True, timeout=300)
            exp = subprocess.run(
                [sys.executable, f], capture_output=True, text=True, timeout=300
            ).stdout
            assert run.stdout == exp, (f, run.stdout[:80], exp[:80])
