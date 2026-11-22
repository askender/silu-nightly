"""Dynamic dict pop semantics: the 1-arg pop is the KeyError domain (a
miss panics, never silently None) and the 2-arg pop returns the default
on a miss - CPython parity against the reference interpreter, executed
through the compiled CLI plane. The rs oracle bails on dynamic dicts, so
this surface is py-plane only (probes dp2-dp5, oracle round 2026-11-22).

Runtime ABI (pyobj_runtime.dict_pop / dict_pop_def): the 1-arg pop pads
a null default and dict_pop panics KeyError on a miss; the 2-arg pop
routes through dict_pop_def, whose miss ALWAYS returns the default (any
value including null = None) - CPython's 2-arg pop never raises. The
converter itself relies on .pop(k, None) with miss-None semantics.
"""

import os
import subprocess
import sys

PY = sys.executable
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _build_and_run(source: str):
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "p.si")
        bin_ = os.path.join(td, "p")
        open(src, "w").write(source)
        r = subprocess.run(
            [PY, "-m", "silu", "build", src, "-o", bin_],
            capture_output=True, text=True, cwd=REPO, timeout=300,
        )
        assert r.returncode == 0, r.stderr
        run = subprocess.run(
            [bin_], capture_output=True, text=True, timeout=60
        )
        return run.returncode, run.stdout


def _interpret(source: str):
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "p.si")
        open(src, "w").write(source)
        r = subprocess.run(
            [PY, "-m", "silu", "interpret", src],
            capture_output=True, text=True, cwd=REPO, timeout=60,
        )
        return r.returncode, r.stdout + r.stderr


class TestDynamicDictPop:
    def test_two_arg_miss_returns_default(self):
        src = (
            'd = {}\nd["a"] = 1\nprint(d.pop("gone", 99))\n'
            'print(d.pop("a", 5))\nprint(len(d))\n'
        )
        rc, out = _build_and_run(src)
        irc, iout = _interpret(src)
        assert rc == 0 == irc
        assert out == iout == "99\n1\n0\n"

    def test_none_default_miss_returns_none(self):
        src = (
            'd = {}\nd["a"] = 1\nr = d.pop("gone", None)\n'
            "print(r)\nprint(len(d))\n"
        )
        rc, out = _build_and_run(src)
        irc, iout = _interpret(src)
        assert rc == 0 == irc
        assert out == iout == "None\n1\n"

    def test_one_arg_miss_panics_keyerror(self):
        # never silently None: the compiled plane panics KeyError and
        # exits nonzero; the interpreter raises for the same program
        src = 'd = {}\nd["a"] = 1\nprint(d.pop("gone"))\n'
        rc, out = _build_and_run(src)
        assert rc == 1
        assert "KeyError: key not found" in out
        irc, iout = _interpret(src)
        assert irc != 0
        # the interpreter's message is the key repr (Runtime Error:
        # 'gone'); the compiled plane's is the static KeyError string -
        # the parity is the loud nonzero failure on the miss
        assert "'gone'" in iout

    def test_del_missing_key_panics_keyerror(self):
        # del rides the same 1-arg domain (null default)
        src = 'd = {}\nd["a"] = 1\ndel d["a"]\ndel d["gone"]\n'
        rc, out = _build_and_run(src)
        assert rc == 1
        assert "KeyError: key not found" in out
