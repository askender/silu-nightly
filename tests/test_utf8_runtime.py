"""Execution-level UTF-8 semantics guards (1.18.1).

The corpus probe (selfhost/utf8_probe.si) pins the byte shape; these
tests pin RUNTIME BEHAVIOR of the codepoint semantics and the
cp-offset side caches - the layers that caught three shipped bugs
(byte-vs-cp len/subscript, O(n^2) walks, cache thrash):
  - dynamic len/subscript/slice/iteration over multibyte strings
    (CPython parity, incl. stepped slices)
  - the free-reuse trap: purged cp-offset cache vs a reallocated
    rawstr with IDENTICAL len/cp but different byte layout
  - perf bound: a 150K-codepoint per-char walk must stay seconds,
    not minutes (the quadratic path was ~1000x slower)
"""

import importlib.util
import os
import subprocess
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_spec = importlib.util.spec_from_file_location(
    "selfhost_build", os.path.join(REPO, "tools", "selfhost_build.py"))
shb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shb)


def _run_program(src):
    shb.ensure_siluc()
    with tempfile.NamedTemporaryFile(suffix=".si", mode="w",
                                     delete=False) as h:
        h.write(src)
        path = h.name
    try:
        exe = path + ".out"
        build = subprocess.run([os.path.join(REPO, "siluc"), path, "-o", exe],
                               capture_output=True, text=True, timeout=300,
                               cwd=REPO)
        assert build.returncode == 0, build.stderr[-400:]
        run = subprocess.run([exe], capture_output=True, text=True,
                             timeout=120)
        assert run.returncode == 0, run.stderr[-300:]
        return run.stdout
    finally:
        os.unlink(path)
        if os.path.exists(exe):
            os.unlink(exe)


def test_dynamic_codepoint_ops_match_cpython():
    src = (
        "def main() -> int:\n"
        '    t = chr(167) + chr(20013) + "x"\n'
        "    print(len(t))\n"
        "    print(ord(t[0]))\n"
        "    print(ord(t[1]))\n"
        "    w = t[0:2]\n"
        "    print(len(w))\n"
        "    print(ord(w[1]))\n"
        "    z = t[0:3:2]\n"
        "    print(len(z))\n"
        "    print(ord(z[0]))\n"
        "    return 0\n"
    )
    out = _run_program(src).split()
    expect = ["3", "167", "20013", "2", "20013", "2", "167"]
    assert out == expect, (out, expect)


def test_free_reuse_trap_purges_cache():
    # identical byte len + cp count, DIFFERENT layout: a stale cache
    # entry would answer with the freed string's offsets
    src = (
        "def build2(x: str, y: str, n: int) -> str:\n"
        "    b: strbuf = strbuf()\n"
        "    i: int = 0\n"
        "    while i < n:\n"
        "        b.push(x)\n"
        "        b.push(y)\n"
        "        i += 1\n"
        "    return b.to_str()\n"
        "def main() -> int:\n"
        "    a: str = build2(chr(167), chr(20013), 25000)\n"
        "    print(ord(a[1]))\n"
        "    a = build2(chr(20013), chr(167), 25000)\n"
        "    print(ord(a[1]))\n"
        "    print(len(a))\n"
        "    return 0\n"
    )
    out = _run_program(src).split()
    assert out == ["20013", "167", "50000"], out


def test_nonascii_walk_stays_linear():
    src = (
        "def main() -> int:\n"
        "    b: strbuf = strbuf()\n"
        "    i: int = 0\n"
        "    while i < 50000:\n"
        '        b.push(chr(167))\n'
        "        i += 1\n"
        "    s: str = b.to_str()\n"
        "    total: int = 0\n"
        "    i = 0\n"
        "    n: int = len(s)\n"
        "    while i < n:\n"
        "        if ord(s[i]) == 167:\n"
        "            total += 1\n"
        "        i += 1\n"
        "    print(total)\n"
        "    return 0\n"
    )
    t0 = time.time()
    out = _run_program(src).split()
    dt = time.time() - t0
    assert out == ["50000"], out
    assert dt < 30, f"non-ASCII walk took {dt:.1f}s (quadratic path back?)"
