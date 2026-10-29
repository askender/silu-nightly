"""The fixed-point gate: the self-hosted converter compiled natively
(flatten -> ir -> llvm -> clang -O2) converts ITS OWN IR and must
reproduce its own build .ll byte-for-byte - the compiler can rebuild
itself. This is the strongest possible self-hosting test: it exercises
the converter on its own 16MB-scale source, and any divergence in the
emission (even one byte) fails.
"""

import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, cwd=REPO, timeout=1800, **kw)


@pytest.fixture(scope="module")
def fixed_point_artifacts(tmp_path_factory):
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    tmp = tmp_path_factory.mktemp("fixed_point")

    flat_si = tmp / "typed_codegen_flat.si"
    gen = _run([PY, "tools/flatten_codegen.py", "--si"], text=True)
    assert gen.returncode == 0, gen.stderr
    flat_si.write_text(gen.stdout)
    shutil.copy(os.path.join(REPO, "selfhost", "llvmlite.si"), tmp / "llvmlite.si")
    # flat is main-free (siluc.si imports it inline); the runnable
    # converter is the thin wrapper, and that wrapper is its own source
    wrapper = tmp / "silu_conv_main.si"
    shutil.copy(os.path.join(REPO, "selfhost", "silu_conv_main.si"), wrapper)

    ir_json = tmp / "flat.ir.json"
    r = _run([PY, "-m", "silu", "ir", str(wrapper), "--format", "json",
              "--output", str(ir_json)])
    assert r.returncode == 0, r.stderr

    # the reference .ll (the converter's own build artifact)
    ref_ll = tmp / "flat_ref.ll"
    r = _run([PY, "-m", "silu", "llvm", str(ir_json), "--output", str(ref_ll)])
    assert r.returncode == 0, r.stderr

    binary = tmp / "flat_conv"
    build = subprocess.run(
        ["clang", "-O2", str(ref_ll), "-lm", "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stderr
    return str(binary), str(ir_json), str(ref_ll)


def test_fixed_point_self_conversion_identical(fixed_point_artifacts):
    binary, ir_json, ref_ll = fixed_point_artifacts
    with open(ir_json, "rb") as handle:
        r = subprocess.run([binary], stdin=handle, capture_output=True, timeout=1800)
    assert r.returncode == 0, (
        f"self-conversion crashed: {r.stderr[:400]}"
    )
    with open(ref_ll, "rb") as handle:
        ref = handle.read()
    assert r.stdout == ref, (
        f"self-conversion diverges: {len(r.stdout)} vs {len(ref)} bytes"
    )
