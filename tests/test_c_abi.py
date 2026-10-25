"""The C ABI: @export lifts Silu functions to external linkage and
`--object` emits a linkable .o plus a generated C header. Static
scalar functions map 1:1 (int->int64_t, float->double, bool->bool);
dynamic functions pass the stable PObj box pointer. C and Rust hosts
link and call them.
"""

import os
import subprocess
import sys
import tempfile

import pytest

from tests import REPO

PY = sys.executable
DRIVER = os.path.join(REPO, "siluc")


def _build_driver(src: str, out: str, extra=()):
    r = subprocess.run(
        [DRIVER, src, "-o", out, *extra],
        capture_output=True, text=True, cwd=REPO, timeout=600,
    )
    assert r.returncode == 0, r.stderr
    return out


LIB_SRC = (
    "@export\n"
    "def fib(n: int) -> int:\n"
    "    if n < 2:\n"
    "        return n\n"
    "    return fib(n - 1) + fib(n - 2)\n"
    "\n"
    "@export\n"
    "def circle_area(r: float) -> float:\n"
    "    return 3.14159 * r * r\n"
    "\n"
    "@export\n"
    "def safe_mul(a: int, b: int) -> int:\n"
    "    return a * b\n"
)


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    d = tmp_path_factory.mktemp("cab")
    src = d / "lib.si"
    src.write_text(LIB_SRC)
    obj = str(d / "lib.o")
    _build_driver(str(src), obj, ["--object"])
    return obj, str(d)


def test_object_and_header_exist(lib):
    obj, d = lib
    assert os.path.exists(obj)
    assert os.path.exists(obj + ".h")
    syms = subprocess.run(
        ["nm", obj], capture_output=True, text=True
    ).stdout
    assert " T _fib" in syms
    assert " T _circle_area" in syms
    assert " T _safe_mul" in syms
    # non-exported runtime stays present but that is fine; the
    # exported names must be GLOBAL (T), not local (t)
    hdr = open(obj + ".h").read()
    assert "int64_t fib(int64_t)" in hdr
    assert "double circle_area(double)" in hdr


def test_c_host(lib):
    obj, d = lib
    host = os.path.join(str(d), "host.c")
    open(host, "w").write(
        '#include <stdio.h>\n#include <stdint.h>\n#include "lib.o.h"\n'
        "int main(void) {\n"
        '    printf("%lld %.5f %lld\\n",'
        " (long long)fib(24), circle_area(2.0), (long long)safe_mul(6, 7));\n"
        "    return 0;\n}\n"
    )
    exe = os.path.join(str(d), "host")
    r = subprocess.run(
        ["clang", "-O2", "-I", d, host, obj, "-o", exe],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out = subprocess.run([exe], capture_output=True, text=True)
    assert out.stdout == "46368 12.56636 42\n"


def test_rust_host(lib):
    obj, d = lib
    dylib = os.path.join(str(d), "libsilu_ffi.dylib")
    r = subprocess.run(
        ["clang", "-shared", obj, "-o", dylib],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    rs = os.path.join(str(d), "host.rs")
    open(rs, "w").write(
        "use std::os::raw::c_longlong;\n"
        'extern "C" { fn fib(n: c_longlong) -> c_longlong; }\n'
        "fn main() { unsafe { println!(\"{}\", fib(24)); } }\n"
    )
    exe = os.path.join(str(d), "host_rs")
    r = subprocess.run(
        [os.path.expanduser("~/.cargo/bin/rustc"),
         "-C", "opt-level=3", rs, "-o", exe,
         "-C", f"link-arg=-L{os.path.dirname(dylib)}",
         "-C", "link-arg=-lsilu_ffi"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out = subprocess.run([exe], capture_output=True, text=True)
    assert out.stdout == "46368\n"


def test_export_through_all_planes():
    """The @export decorator is accepted on every plane (interpreter
    ignores it; the compiled planes honor the linkage lift)."""
    src = (
        "@export\n"
        "def double(x: int) -> int:\n"
        "    return x * 2\n\n"
        "print(double(21))\n"
    )
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", src],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "42\n"
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "p.si")
        open(p, "w").write(src)
        b = subprocess.run(
            [PY, "-m", "silu", "build", p, "-o", os.path.join(td, "p")],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run([os.path.join(td, "p")], capture_output=True, text=True)
        assert run.stdout == "42\n"


EXTERN_SRC = (
    "from c import sqrt, floor, pow\n\n"
    "x: float = sqrt(2.0)\n"
    "print(x)\n"
    "print(floor(3.7))\n"
    "print(pow(2.0, 10.0))\n"
)


def test_extern_all_planes():
    expected = "1.4142135623730951\n3.0\n1024.0\n"
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", EXTERN_SRC],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "p.si")
        open(p, "w").write(EXTERN_SRC)
        b = subprocess.run(
            [PY, "-m", "silu", "build", p, "-o", os.path.join(td, "p")],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run([os.path.join(td, "p")], capture_output=True, text=True)
        assert run.stdout == expected
        pc = subprocess.run(
            [PY, os.path.join(REPO, "tools", "pycompat.py"), p],
            capture_output=True, text=True, cwd=REPO,
        )
        assert pc.returncode == 0, pc.stderr
        assert pc.stdout == expected


def test_extern_strlen():
    src = (
        'from c import strlen\n\n'
        's: str = "hello"\nprint(strlen(s))\n'
    )
    expected = "5\n"
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", src],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "p.si")
        open(p, "w").write(src)
        b = subprocess.run(
            [PY, "-m", "silu", "build", p, "-o", os.path.join(td, "p")],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run([os.path.join(td, "p")], capture_output=True, text=True)
        assert run.stdout == expected


def test_extern_rejects_dynamic_args():
    src = (
        "from c import sqrt\n\n"
        "x = input()\n"
        "print(sqrt(x))\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "p.si")
        open(p, "w").write(src)
        b = subprocess.run(
            [PY, "-m", "silu", "build", p, "-o", os.path.join(td, "p")],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode != 0
        assert "int/float/bool/str" in b.stderr or "extern" in b.stderr
