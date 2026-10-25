"""Comprehensions on every plane: the AST interpreter never supported
them (only pycompat/CPython did), the IR interpreter and the typed
backend only had list_comp. dict/set forms now work everywhere the
list form does, and silu_fe parses them with IR parity."""

import json
import os
import subprocess
import sys
import tempfile

from tests import REPO, ensure_fe_binary

PY = sys.executable


def check_all_planes(source: str, expected: str):
    r = subprocess.run(
        [PY, "-m", "silu", "interpret", "--source", source],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == expected

    ir = subprocess.run(
        [PY, "-m", "silu", "ir", "--source", source, "--format", "json"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert ir.returncode == 0, ir.stderr

    with tempfile.TemporaryDirectory() as td:
        ir_path = os.path.join(td, "p.ir.json")
        with open(ir_path, "w") as h:
            h.write(ir.stdout)
        x = subprocess.run(
            [PY, "-m", "silu", "exec", ir_path],
            capture_output=True, text=True, cwd=REPO,
        )
        assert x.returncode == 0, x.stderr
        assert x.stdout == expected

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

        # pycompat (CPython plane)
        pc = subprocess.run(
            [PY, os.path.join(REPO, "tools", "pycompat.py"), src],
            capture_output=True, text=True, cwd=REPO,
        )
        assert pc.returncode == 0, pc.stderr
        assert pc.stdout == expected

        # the self-hosted front end emits identical IR
        fe = ensure_fe_binary()
        fe_ir = subprocess.run(
            [fe], stdin=open(src), capture_output=True, text=True,
            cwd=os.path.dirname(src),
        )
        assert fe_ir.returncode == 0, fe_ir.stderr
        assert json.loads(fe_ir.stdout) == json.loads(ir.stdout)


def test_list_comp_still():
    check_all_planes(
        "xs = [1, 2, 3]\nys = [x * 2 for x in xs]\n"
        "print(ys[0], ys[1], ys[2])\n",
        "2 4 6\n",
    )


def test_dict_comp():
    check_all_planes(
        "xs = [1, 2, 3]\nd = {x: x * 2 for x in xs}\n"
        "print(d[2], len(d))\n",
        "4 3\n",
    )


def test_set_comp():
    check_all_planes(
        "s = {x % 2 for x in [1, 2, 3, 4]}\nprint(len(s))\n",
        "2\n",
    )


def test_dict_comp_with_condition():
    check_all_planes(
        "d = {x: x * x for x in range(6) if x % 2 == 0}\n"
        "print(d[4], len(d))\n",
        "16 3\n",
    )


def test_dict_comp_of_strings():
    check_all_planes(
        'ks = ["a", "b"]\nd = {k: len(k) for k in ks}\nprint(d["a"], d["b"])\n',
        "1 1\n",
    )
