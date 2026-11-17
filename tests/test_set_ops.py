"""set.discard across all planes: remove-by-value if present, no error
when absent. The two-set ownership idiom in the converter source
needed it (previously worked around with an additive owned set)."""

import subprocess
import sys

from tests import REPO

PY = sys.executable


def check_all_planes(source: str, expected: str):
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", source],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected
    import tempfile
    import os

    ir = subprocess.run(
        [PY, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir.returncode == 0, ir.stderr
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
        assert run.stdout == expected


def test_discard_basic():
    check_all_planes(
        "s = {1, 2, 3}\ns.discard(2)\nprint(len(s))\nprint(2 in s)\n"
        "print(1 in s)\n",
        "2\nFalse\nTrue\n",
    )


def test_discard_absent_no_error():
    check_all_planes(
        "s = {1}\ns.discard(99)\nprint(len(s))\n",
        "1\n",
    )


def test_discard_strings():
    check_all_planes(
        's = {"a", "b"}\ns.discard("a")\nprint(len(s))\nprint("b" in s)\n',
        "1\nTrue\n",
    )


def test_discard_then_add():
    check_all_planes(
        "s = {1, 2}\ns.discard(1)\ns.add(5)\ns.discard(2)\n"
        "print(len(s))\nprint(5 in s)\n",
        "1\nTrue\n",
    )
