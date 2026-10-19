"""Native parity gate: the self-hosted converter (typed_codegen.py +
silu_ir_to_llvm.py flattened to typed_codegen_flat.si, compiled by clang
-O0) must emit byte-identical .ll to the Python converter for every
benchmark program.

This is the only gate that crosses the object-model boundary: the
interpreter-based parity gates all execute the .si converter under
CPython, where Python's object semantics mask native-plane divergence
(heap corruption, layout shifts, tag confusion). Here the converter runs
as a native binary, so its own dict/list/str/box machinery is exercised
exactly as compiled.

Known non-goal: the converter binary is built at -O0; clang -O2
miscompiles it (tracked separately in docs/selfhost_todo.md).
"""

import glob
import os
import shutil
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

PROGRAMS = sorted(glob.glob(os.path.join(REPO, "benchmarks", "*.si"))) + [
    os.path.join(REPO, "selfhost", "calc.si"),
    os.path.join(REPO, "selfhost", "ir_interp.si"),
]


def _run(cmd, **kw):
    result = subprocess.run(
        cmd, capture_output=True, cwd=REPO, timeout=600, **kw
    )
    return result


@pytest.fixture(scope="module")
def native_converter(tmp_path_factory):
    """Flatten the converter and build it natively (once per module)."""
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    tmp = tmp_path_factory.mktemp("native_parity")
    flat_si = tmp / "typed_codegen_flat.si"
    gen = subprocess.run(
        [PY, "tools/flatten_codegen.py", "--si"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert gen.returncode == 0, gen.stderr
    flat_si.write_text(gen.stdout)
    # the flat source does `import llvmlite`, resolved next to itself
    shutil.copy(os.path.join(REPO, "selfhost", "llvmlite.si"), tmp / "llvmlite.si")

    ir_json = tmp / "flat.ir.json"
    result = _run(
        [PY, "-m", "silu", "ir", str(flat_si), "--format", "json",
         "--output", str(ir_json)]
    )
    assert result.returncode == 0, result.stderr
    conv_ll = tmp / "flat_conv.ll"
    result = _run(
        [PY, "-m", "silu", "llvm", str(ir_json), "--output", str(conv_ll)]
    )
    assert result.returncode == 0, result.stderr
    binary = tmp / "flat_conv"
    # -O0 on purpose: the -O2 miscompile of the converter is a known
    # open issue; the parity property holds at -O0
    build = subprocess.run(
        ["clang", "-O0", str(conv_ll), "-o", str(binary)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    return str(binary)


@pytest.mark.parametrize("program", PROGRAMS, ids=[os.path.basename(p) for p in PROGRAMS])
def test_native_converter_parity(native_converter, program, tmp_path):
    ir_json = tmp_path / "prog.ir.json"
    result = _run(
        [PY, "-m", "silu", "ir", program, "--format", "json",
         "--output", str(ir_json)]
    )
    assert result.returncode == 0, result.stderr

    ref_ll = tmp_path / "ref.ll"
    result = _run(
        [PY, "-m", "silu", "llvm", str(ir_json), "--output", str(ref_ll)]
    )
    assert result.returncode == 0, result.stderr

    with open(ir_json, "rb") as handle:
        native = subprocess.run(
            [native_converter],
            stdin=handle,
            capture_output=True,
            timeout=600,
        )
    assert native.returncode == 0, (
        f"native converter crashed on {program}: {native.stderr[:400]}"
    )
    ref = ref_ll.read_bytes()
    assert native.stdout == ref, (
        f"native .ll diverges for {program}: "
        f"{len(native.stdout)} vs {len(ref)} bytes"
    )
