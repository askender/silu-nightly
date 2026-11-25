"""Memory-safety gate: compiled programs under a REAL AddressSanitizer.

The parity gates prove the planes agree on bytes. This one proves the
bytes are memory-safe when they run, which no byte comparison can see.
In 2026-11 two runtime walkers read one byte past every exact-size
string buffer and `s = s + s` read freed memory - for weeks, with every
gate green. The crashes were real: ~/Library/Logs/DiagnosticReports
held five siluc1 reports from one session, none of them reproducible on
demand, because whether a stray byte lands on an unmapped page is up to
the allocator.

Two rules make the verdict mean something (tools/asan_run.py):

- the module is attributed first: clang instruments only functions that
  carry `sanitize_address`, and a `.ll` input has none. Plain
  `clang -fsanitize=address x.ll` links the runtime and checks NOTHING
- a KNOWN over-read is reported before any program counts as clean

The programs are the semantic gate's own sources (both converter planes:
they are not byte-pinned against each other) plus the memory shapes
below, each of which was wrong at least once - and the corpus files,
whose runtime part is byte-identical on every plane, through the
self-hosted toolchain that ships.
"""

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tests"))

import asan_run  # noqa: E402
import test_semantics_vs_cpython as sem  # noqa: E402

SILUC1 = os.path.join(REPO, "siluc1")
WORKERS = min(8, (os.cpu_count() or 2) * 3)
CORPUS = [
    "benchmarks/str_methods.si", "benchmarks/dict_str.si",
    "benchmarks/list_ops.si", "benchmarks/dict_ops.si",
    "benchmarks/record_global.si", "benchmarks/char_pair.si",
    "selfhost/utf8_probe.si", "selfhost/float_edge.si",
    "selfhost/comp_unpack.si",
]

# (id, source, stdin). Every shape is a place where the runtime had a
# stray read or write; the exact-size buffers are what make ASan see it.
SHAPES = [
    # boxed s[i] is an exact-size malloc; len() of it walks the cp cache
    ("boxed_exact_size_buffer",
     "def slen(o: object) -> int:\n    return len(o)\n\n"
     "def char_at(o: object, i: int) -> object:\n    return o[i]\n\n"
     "def tail(o: object, a: int, b: int) -> object:\n    return o[a:b]\n\n"
     's: object = "héllo wörld"\nc: object = char_at(s, 1)\nprint(slen(c), c)\n'
     "t: object = tail(s, 1, 6)\nprint(slen(t), t)\n", b""),
    ("boxed_unicode_family",
     "def upper(o: object) -> object:\n    return o.upper()\n\n"
     "def cut(o: object, a: int, b: int, st: int) -> object:\n    return o[a:b:st]\n\n"
     "def each(o: object) -> int:\n    n: int = 0\n    for ch in o:\n"
     "        n += ord(ch)\n    return n\n\n"
     's: object = "aé中bñc"\nprint(len(s), s[2], s[-1], s[-3])\n'
     "print(cut(s, 1, 6, 2), cut(s, 6, 0, -2))\n"
     'print(upper(s), s + "!", "x" + s, s == "aé中bñc", s != "y")\n'
     'print(s.find("中"), s.startswith("aé"), s.endswith("c"), "中" in s)\n'
     "print(each(s))\n", b""),
    ("boxed_from_values",
     "def L(o: object) -> int:\n    return len(o)\n\n"
     "a: object = str(12345)\nb: object = str(2.5)\nprint(L(a), a, L(b), b)\n"
     "c: object = a + b\nprint(L(c), c)\nd: object = c[1:4]\nprint(L(d), d)\n"
     "e: object = str(d) + str(False)\nprint(L(e), e, e[6])\n", b""),
    ("boxed_concat_growth",
     "def L(o: object) -> int:\n    return len(o)\n\n"
     'acc: object = "x"\nfor i in range(60):\n    acc = acc + "ab"\n'
     "print(L(acc), acc[0], acc[119], acc[-1])\n"
     "piece: object = acc[10:70]\nprint(L(piece), piece[0], piece[-1])\n"
     "grown: object = piece\nfor i in range(20):\n    grown = grown + piece\n"
     "print(L(grown), grown[0], grown[1259])\n", b""),
    ("dynamic_lists",
     'xs: object = [1, "two", 3.5, [4, 5]]\nxs.append("six")\n'
     "print(len(xs), xs[1], xs[-1], xs[3][0])\n"
     "ys: object = xs + [7, 8]\nprint(len(ys), ys[-2], ys[-1])\n"
     "print(xs[1:4], xs[0:2], xs[2:])\n"
     'xs[0] = "zero"\nprint(xs)\nfor x in xs[3]:\n    print(x)\n', b""),
    ("dynamic_dicts",
     'd: object = {}\nfor i in range(200):\n    d["k" + str(i)] = i\n'
     'print(len(d), d["k7"], d["k199"])\nn: int = 0\nfor k in d:\n    n += len(k)\n'
     'print(n)\nd.pop("k5")\nd.pop("k199")\nprint(len(d), "k5" in d, "k6" in d)\n'
     "total: int = 0\nfor k in d:\n    total += d[k]\nprint(total)\n"
     'd["k7"] = "seven"\nprint(d["k7"])\n', b""),
    # s = s + s appends the buffer to itself: realloc used to release
    # the source under the copy
    ("typed_self_append",
     's: str = "ab"\nfor i in range(12):\n    s = s + s\n'
     "print(len(s), s[0], s[-1], s[1000])\n"
     't: str = "xy"\nfor i in range(10):\n    t += t\nprint(len(t), t)\n\n'
     "def f() -> str:\n    v = \"ab\"\n    return v\n\n"
     "a = f()\nb = a\na += \"c\"\nprint(a, b)\n"
     "c = f()\nd = c\nc = c + c\nprint(c, d)\n"
     'e: str = "q"\nfor i in range(14):\n    e = e + e[0:1] + e\nprint(len(e), e)\n'
     'g: str = "hello"\ng = g + g.upper()\nprint(g)\n'
     'h: str = "ab"\nfor i in range(8):\n    h = h + h + h[1:]\n'
     "print(len(h), h[0], h[-1])\n", b""),
    # rawstr_new_copy hands out an exact-size buffer; the cp-offset
    # cache walked one byte past its end
    ("rawstr_cp_offset_cache",
     "def buf_build(first: str, second: str, n: int) -> str:\n"
     "    b: strbuf = strbuf()\n    i: int = 0\n    while i < n:\n"
     "        b.push(first)\n        b.push(second)\n        i += 1\n"
     "    return b.to_str()\n\n"
     "def walk(s: str, target: int) -> int:\n    i: int = 0\n    total: int = 0\n"
     "    n: int = len(s)\n    while i < n:\n        if ord(s[i]) == target:\n"
     "            total += 1\n        i += 1\n    return total\n\n"
     "s: str = buf_build(chr(167), chr(20013), 40)\n"
     "print(len(s), walk(s, 167), walk(s, 20013))\n"
     "print(s[0:3], len(s[1:79:2]), s[-1], s[79])\n"
     "t: str = s[3:97]\nprint(len(t), walk(t, 20013), t[0:5], len(t[0:40:3]))\n"
     "u: str = s + t\nprint(len(u), walk(u, 167), u[156], u[150:156])\n"
     'v: str = "plain ascii suffix"\nw: str = t + v\nprint(len(w), w[90:100], w[-7:])\n',
     b""),
    # read_line grows its buffer by realloc; multi-byte lines
    ("input_lines",
     "def count_lines() -> int:\n    n: int = 0\n    total: int = 0\n"
     "    line: str = input()\n    while line != \"\":\n        n += 1\n"
     "        total += len(line)\n        line = input()\n"
     "    return n * 1000 + total\n\nprint(count_lines())\n",
     "héllo\n中文 mix\nlast\n\n".encode("utf-8")),
    ("strbuf",
     "def build(parts: list[str], times: int) -> str:\n"
     "    b: strbuf = strbuf()\n    i: int = 0\n    while i < times:\n"
     "        for p in parts:\n            b.push(p)\n        i += 1\n"
     "    return b.to_str()\n\n"
     'a: str = build(["a", "é中", "xyz"], 33)\n'
     "print(len(a), a[0], a[1], a[-1], a[197])\n"
     'c: str = "seed"\nb: strbuf = strbuf(c)\nb.push(a)\n'
     "out: str = b.to_str()\nprint(len(out), out[0:4], out[-3:])\n", b""),
    ("rawlist_str_family",
     "def rev(words: list[str]) -> list[str]:\n    out: list[str] = []\n"
     "    i: int = len(words) - 1\n    while i >= 0:\n"
     '        out.append(words[i] + "!")\n        i -= 1\n    return out\n\n'
     "words: list[str] = []\nfor i in range(40):\n"
     '    words.append("w" + str(i) + "é")\n'
     "last: str = words[39]\nprint(len(words), last, words[0])\n"
     "r: list[str] = rev(words)\nprint(len(r), r[0], r[39])\n"
     'joined: str = ""\nfor w in r:\n    joined = joined + w\n'
     "print(len(joined), joined[0:6], joined[-4:])\n"
     'words[5] = "replaced中"\nprint(words[5], len(words[5]), words[5][8])\n'
     "del words[0]\ndel words[1]\nprint(len(words), words[0], words[1])\n", b""),
]


def gate_programs():
    """(id, source bytes, stdin, planes) for every program of the gate."""
    out = []
    for table in (sem.MATCH_CPYTHON, sem.MATCH_INTERPRETER):
        for case in table:
            out.append(("sem/" + case[0], case[1].encode("utf-8"), b"",
                        ("conv", "pyll")))
    for pid, src, stdin in SHAPES:
        out.append(("shape/" + pid, src.encode("utf-8"), stdin, ("conv", "pyll")))
    for rel in CORPUS:
        with open(os.path.join(REPO, rel), "rb") as h:
            out.append(("corpus/" + rel, h.read(), b"", ("conv",)))
    return out


def _python_plane_ll(src_bytes):
    """The Python converter's module: IR JSON, then real llvmlite."""
    with tempfile.TemporaryDirectory() as td:
        si = os.path.join(td, "p.si")
        js = os.path.join(td, "p.json")
        with open(si, "wb") as h:
            h.write(src_bytes)
        a = subprocess.run([sys.executable, "-m", "silu", "ir", si, "-o", js],
                           capture_output=True, cwd=REPO, timeout=600)
        if a.returncode != 0:
            raise RuntimeError((a.stderr + a.stdout).decode("utf-8", "replace")[-200:])
        b = subprocess.run([sys.executable, "-m", "silu", "llvm", js],
                           capture_output=True, cwd=REPO, timeout=1800)
        if b.returncode != 0 or not b.stdout:
            raise RuntimeError((b.stderr + b.stdout).decode("utf-8", "replace")[-200:])
        return b.stdout.decode("utf-8", "replace")


def _selfhosted_plane_ll(src_bytes):
    r = subprocess.run([SILUC1], input=src_bytes, capture_output=True,
                       cwd=REPO, timeout=1800)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError((r.stdout + r.stderr).decode("utf-8", "replace")[-200:])
    return r.stdout.decode("utf-8", "replace")


def _build_one(job):
    pid, plane, src, _stdin = job
    work = tempfile.mkdtemp(prefix="silu_asan_")
    try:
        ll = {"conv": _selfhosted_plane_ll,
              "pyll": _python_plane_ll}[plane](src)
        return asan_run.build(ll, work), None
    except Exception as exc:  # named by the test that needs this binary
        return None, "%s: %s" % (type(exc).__name__, str(exc).strip()[:300])


@pytest.fixture(scope="module")
def built():
    """Every ASan binary, compiled once for the whole module."""
    sem._ensure_siluc1()
    jobs = [(pid, plane, src, stdin)
            for pid, src, stdin, planes in gate_programs() for plane in planes]
    binaries, failures = {}, {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for job, (binary, error) in zip(jobs, ex.map(_build_one, jobs)):
            key = (job[0], job[1])
            if error is not None:
                failures[key] = error
            else:
                binaries[key] = binary
    yield binaries, failures
    for binary in binaries.values():
        for stale in (binary, binary + ".ll"):
            try:
                os.remove(stale)
            except OSError:
                pass
        try:
            os.rmdir(os.path.dirname(binary))
        except OSError:
            pass


def test_known_overread_is_reported():
    """The control: a one-byte read past malloc(2). Anything but
    heap-buffer-overflow means ASan is not instrumenting here."""
    assert asan_run.control() == "heap-buffer-overflow"


GATE = gate_programs()
STDIN = {pid: stdin for pid, _s, stdin, _p in GATE}
CASES = [(pid, plane) for pid, _s, _i, planes in GATE for plane in planes]


@pytest.mark.parametrize("pid,plane", CASES, ids=[p + "[" + pl + "]" for p, pl in CASES])
def test_program_is_memory_safe(built, pid, plane):
    binaries, failures = built
    key = (pid, plane)
    assert key not in failures, "could not build %s: %s" % (
        key, failures.get(key))
    result = asan_run.run(binaries[key], STDIN[pid])
    assert result.kind is None, "%s: %s\n%s" % (
        key, result.summary, result.stderr[-3000:])
    assert result.returncode == 0, "%s exited %s\n%s" % (
        key, result.returncode, result.stderr[-2000:])
