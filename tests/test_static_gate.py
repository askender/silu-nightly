"""The --static gate: programs whose compiled code touches the dynamic
(pyobj) runtime are refused with a loud error naming the offending
symbols. Without the flag the same programs compile fine - the typed
backend silently falls back to PyObject storage, and this gate exists
to turn that silence into an error.

Static by this gate's definition: scalars (silu_panic/float_repr/
view_ord whitelisted) plus TYPED str/list/dict (the rawstr/rawlist/
rawdict native families). Boxing (create_*), dynamic dispatch
(pyobj_*), unboxing and the boxed method families are forbidden.
"""

import os
import subprocess
import sys

import pytest

from tests import REPO

PY = sys.executable


def _silu_build(source, out, static=True):
    cmd = [PY, "-m", "silu", "build", source, "-o", out]
    if static:
        cmd.append("--static")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def _selfhost_build(source, out, static=True):
    cmd = [PY, "tools/selfhost_build.py", source, "-o", out]
    if static:
        cmd.append("--static")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)


def test_fib_is_pure_static(tmp_path):
    """fib references exactly one runtime symbol (silu_panic) - the
    gate passes on both build planes."""
    for build in (_silu_build, _selfhost_build):
        out = str(tmp_path / "fib")
        r = build(f"{REPO}/benchmarks/fib.si", out)
        assert r.returncode == 0, r.stderr
        run = subprocess.run([out], capture_output=True, text=True)
        assert run.stdout == "46368\n"


@pytest.mark.parametrize(
    "program,first_line",
    [
        ("nbody.si", "0.0136"),   # typed float lists -> rawlist_*
        ("list.si", None),        # typed lists throughout
        ("dict.si", None),        # typed dicts -> rawdict_*
        ("spectral.si", None),
        ("trees.si", None),
    ],
)
def test_typed_containers_are_static(tmp_path, program, first_line):
    """The rawlist_*/rawdict_*/rawstr_* native families serve TYPED
    containers - static by this gate's definition; only BOXING
    (create_*/pyobj_*) is the dynamic world."""
    out = str(tmp_path / "prog")
    r = _silu_build(f"{REPO}/benchmarks/{program}", out)
    assert r.returncode == 0, r.stderr
    if first_line is not None:
        run = subprocess.run([out], capture_output=True, text=True)
        assert run.stdout.startswith(first_line)


def test_float_printing_allowed(tmp_path):
    """float_repr is whitelisted (scalar printing)."""
    out = str(tmp_path / "float")
    r = _silu_build(f"{REPO}/benchmarks/float.si", out)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize(
    "program,expect_symbol",
    [
        ("mandelbrot.si", "create_str"),   # untyped string building
        ("jsonparse.si", "pyobj_"),        # fully dynamic
        ("knucleotide.si", "create_"),     # dict of counters, untyped
        ("string.si", "create_str"),
    ],
)
def test_dynamic_programs_refused(tmp_path, program, expect_symbol):
    out = str(tmp_path / "prog")
    r = _silu_build(f"{REPO}/benchmarks/{program}", out)
    assert r.returncode != 0, f"{program} passed the static gate"
    assert "--static" in r.stderr and "pyobj" in r.stderr
    assert expect_symbol in r.stderr
    assert not os.path.exists(out)


def test_the_point_silent_fallback_becomes_loud(tmp_path):
    """THE demonstration: rebinding a name across types silently
    compiles to pyobj without the flag - the gate names the exact
    boxing symbols instead."""
    src = tmp_path / "rebind.si"
    src.write_text('x = 1\nx = "s"\nprint(x)\n')

    # without --static: silent fallback, builds and runs
    plain = _silu_build(str(src), str(tmp_path / "plain"), static=False)
    assert plain.returncode == 0, plain.stderr
    run = subprocess.run([str(tmp_path / "plain")], capture_output=True, text=True)
    assert run.stdout == "s\n"

    # with --static: loud, specific, non-zero exit
    strict = _silu_build(str(src), str(tmp_path / "strict"))
    assert strict.returncode != 0
    assert "create_int" in strict.stderr
    assert "create_str" in strict.stderr
    assert "pyobj_print" in strict.stderr
    assert not os.path.exists(str(tmp_path / "strict"))


def test_selfhost_gate_rejects(tmp_path):
    out = str(tmp_path / "jp")
    r = _selfhost_build(f"{REPO}/benchmarks/jsonparse.si", out)
    assert r.returncode != 0
    assert "--static" in (r.stdout + r.stderr)
    assert "create_dict" in (r.stdout + r.stderr)
