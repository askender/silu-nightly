"""Aliasing and instance-element fixes: rawlist-to-dynamic call
writeback (Python semantics - callee mutations must be visible) and
instance-list element locals (t = self.toks[0]; t.kind / t.double() -
the local used to misbox the word and crash while inline forms always
worked)."""

import os
import subprocess
import sys
import tempfile

from tests import REPO

PY = sys.executable


def check(source: str, expected: str):
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", source],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "p.si")
        bin_ = os.path.join(td, "p")
        with open(src, "w") as h:
            h.write(source)
        b = subprocess.run(
            [PY, "-m", "silu", "build", src, "-o", bin_],
            capture_output=True, text=True, cwd=REPO,
        )
        assert b.returncode == 0, b.stderr
        run = subprocess.run([bin_], capture_output=True, text=True)
        assert run.stdout == expected, (run.stdout, expected)


def test_str_list_mutation_visible():
    check(
        'def fill(xs) -> int:\n    xs.append("z")\n    return len(xs)\n\n'
        "items: list[str] = []\nfill(items)\n"
        "print(len(items), items[0])\n",
        "1 z\n",
    )


def test_int_list_mutation_visible():
    check(
        "def filli(xs) -> int:\n    xs.append(7)\n    return 0\n\n"
        "ints: list[int] = []\nfilli(ints)\nprint(ints[0])\n",
        "7\n",
    )


def test_float_list_mutation_visible():
    check(
        "def fillf(xs) -> int:\n    xs.append(2.5)\n    return 0\n\n"
        "fs: list[float] = []\nfillf(fs)\nprint(fs[0])\n",
        "2.5\n",
    )


def test_read_only_call_unaffected():
    check(
        "def first(xs):\n    return xs[0]\n\n"
        'ys: list[str] = ["a", "b"]\nprint(first(ys), len(ys))\n',
        "a 2\n",
    )


def test_anonymous_temp_no_writeback_needed():
    check(
        "def first(xs):\n    return xs[0]\n\n"
        'print(first(["q", "r"]))\n',
        "q\n",
    )


def test_method_call_writeback():
    check(
        "class Box:\n    items: list\n\n"
        "    def add(self, xs) -> int:\n"
        '        xs.append("m")\n        return 0\n\n'
        "b = Box(0)\n"
        "data: list[str] = []\n"
        "b.add(data)\n"
        "print(len(data), data[0])\n",
        "1 m\n",
    )


def test_instance_list_element_local_roundtrip():
    """t2 = self.toks[0]; t2.kind - the local used to misbox the
    instance pointer as an int (dynamic getattr panic) while the
    inline self.toks[0].kind always worked."""
    check(
        "class Token:\n    kind: int\n    text: str\n\n"
        "class P:\n    toks: list[Token]\n\n"
        "    def probe_inline(self) -> int:\n"
        "        return self.toks[0].kind\n\n"
        "    def probe_local(self) -> int:\n"
        "        t2 = self.toks[0]\n        return t2.kind\n\n"
        'p = P([Token(3, "x")])\n'
        "print(p.probe_inline())\nprint(p.probe_local())\n",
        "3\n3\n",
    )


def test_instance_list_element_local_method():
    """Word-ABI element + recorded class: both the method call and the
    field read must work through the local."""
    check(
        "class Tok:\n    n: int\n\n"
        "    def double(self) -> int:\n"
        "        return self.n * 2\n\n"
        "class Holder:\n    toks: list[Tok]\n\n"
        "    def run(self) -> int:\n"
        "        t = self.toks[0]\n"
        "        return t.double() + t.n\n\n"
        "h = Holder([Tok(5)])\nprint(h.run())\n",
        "15\n",
    )
