"""The siluc C driver: `./siluc file.si -o prog` - one command, zero
Python between the user and the compilers. Must produce binaries
whose output matches the python-plane build for every benchmark."""

import os
import subprocess
import sys

import pytest

from tests import REPO

PY = sys.executable
DRIVER = os.path.join(REPO, "siluc")
DRIVER_SRC = os.path.join(REPO, "tools", "siluc_main.c")
SILUC1_SRC = os.path.join(REPO, "selfhost", "siluc.si")


@pytest.fixture(scope="module")
def driver():
    # The driver locates siluc1 beside itself, so build the pair in the
    # repository rather than copying just the launcher into tmp_path.
    import tools.selfhost_build as shb

    return shb.ensure_siluc()


BENCH = [
    "fib", "arith", "float", "list", "dict", "mandelbrot", "nbody",
    "spectral", "trees", "string", "knucleotide", "fannkuch",
    "wordcount",
]


@pytest.mark.parametrize("prog", BENCH)
def test_driver_output_matches_python_build(tmp_path, driver, prog):
    si = os.path.join(REPO, "benchmarks", f"{prog}.si")
    py_bin = str(tmp_path / "py")
    b = subprocess.run(
        [PY, "-m", "silu", "build", si, "-o", py_bin],
        capture_output=True, text=True, cwd=REPO,
    )
    assert b.returncode == 0, b.stderr
    dv_bin = str(tmp_path / "dv")
    d = subprocess.run(
        [driver, si, "-o", dv_bin],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    assert d.returncode == 0, d.stderr + d.stdout
    a = subprocess.run([py_bin], capture_output=True, text=True, timeout=120)
    c = subprocess.run([dv_bin], capture_output=True, text=True, timeout=120)
    assert a.stdout == c.stdout, prog
    assert a.returncode == c.returncode, prog


def test_driver_jsonparse_with_stdin(tmp_path, driver):
    gen = os.path.join(REPO, "scripts", "gen_json_input.py")
    doc = subprocess.run([PY, gen], capture_output=True, text=True)
    assert doc.returncode == 0
    dv_bin = str(tmp_path / "jp")
    d = subprocess.run(
        [driver, os.path.join(REPO, "benchmarks", "jsonparse.si"),
         "-o", dv_bin],
        capture_output=True, text=True, cwd=REPO,
    )
    assert d.returncode == 0, d.stderr
    r = subprocess.run(
        [dv_bin], input=doc.stdout, capture_output=True, text=True
    )
    total, count, checksum, names = r.stdout.split()
    assert (int(count), int(names), int(checksum)) == (3000, 3000, 22890)


def test_driver_cold_cache_creates_parents(tmp_path, driver):
    """A released binary must work with no pre-existing cache at all."""
    import tools.selfhost_build as shb

    if any(shb._newer(d, shb.SILUC_BIN) for d in [DRIVER_SRC, shb.SILUC1_BIN]):
        shb.ensure_siluc()
    env = dict(os.environ)
    env["XDG_CACHE_HOME"] = str(tmp_path / "nested" / "cache")
    out = str(tmp_path / "fib")
    result = subprocess.run(
        [driver, os.path.join(REPO, "benchmarks", "fib.si"), "-o", out],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert subprocess.run([out], capture_output=True, text=True).returncode == 0


def test_driver_compile_speed():
    """The whole point: ~0.13s per build (the python pipeline was
    0.17s; rustc parity 0.12s). The gate is order-of-magnitude: a
    quadratic-class regression shows up in seconds, not percent. 0.50
    gives headroom for the slower macos-15 CI image (measured median
    0.29 there, vs 0.13 local) while still failing anything quadratic."""
    import statistics
    import time

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        r = subprocess.run(
            [DRIVER, os.path.join(REPO, "benchmarks", "fib.si"),
             "-o", "/tmp/siluc_speed_probe"],
            capture_output=True, cwd=REPO,
        )
        assert r.returncode == 0
        times.append(time.perf_counter() - t0)
    assert statistics.median(times) < 0.50
