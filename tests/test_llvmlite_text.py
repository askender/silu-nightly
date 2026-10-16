"""The llvmlite text layer: byte-identical .ll against real llvmlite.

silu/llvmlite_text.py is dual-valid source (valid Python and valid
Silu - `silu check selfhost/llvmlite.si` proves the second). The same
converter runs against real llvmlite and against the text layer
(SILU_LLVM_IR=text); every program's .ll must be byte-identical.
selfhost/llvmlite.si is a locked copy of the shared core.
"""

import glob
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROGRAMS = sorted(glob.glob(f"{REPO}/benchmarks/*.si")) + [
    f"{REPO}/selfhost/calc.si",
    f"{REPO}/selfhost/ir_interp.si",
]


def _gen(ir_path, out_path, text_mode):
    env = dict(os.environ)
    if text_mode:
        env["SILU_LLVM_IR"] = "text"
    else:
        env.pop("SILU_LLVM_IR", None)
    r = subprocess.run(
        [sys.executable, "-m", "silu", "llvm", ir_path, "--output", out_path],
        capture_output=True, text=True, cwd=REPO, env=env, timeout=600,
    )
    assert r.returncode == 0, r.stderr
    return open(out_path).read()


@pytest.mark.parametrize("program", PROGRAMS, ids=os.path.basename)
def test_text_layer_matches_llvmlite(program, tmp_path):
    ir = tmp_path / "p.ir.json"
    r = subprocess.run(
        [sys.executable, "-m", "silu", "ir", program,
         "--format", "json", "--output", str(ir)],
        capture_output=True, text=True, cwd=REPO, timeout=600,
    )
    assert r.returncode == 0, r.stderr
    real = _gen(str(ir), str(tmp_path / "real.ll"), False)
    text = _gen(str(ir), str(tmp_path / "text.ll"), True)
    assert text == real


def test_shared_core_is_valid_silu():
    r = subprocess.run(
        [sys.executable, "-m", "silu", "check",
         f"{REPO}/selfhost/llvmlite.si"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_si_copy_locked_to_core():
    core = open(f"{REPO}/silu/llvmlite_text.py").read()
    twin = open(f"{REPO}/selfhost/llvmlite.si").read()
    assert twin == core


def test_flattened_converter_matches(tmp_path):
    """The inheritance-flattened single class (tools/flatten_codegen.py)
    produces byte-identical .ll to the original two-class converter."""
    import importlib

    flat_src = subprocess.run(
        [sys.executable, f"{REPO}/tools/flatten_codegen.py"],
        capture_output=True, text=True, timeout=300,
    )
    assert flat_src.returncode == 0, flat_src.stderr
    flat_path = f"{REPO}/silu/_flat_test_codegen.py"
    with open(flat_path, "w") as h:
        h.write(flat_src.stdout)
    try:
        flat = importlib.import_module("silu._flat_test_codegen")
        from silu.typed_codegen import TypedCodegen

        for program in PROGRAMS:
            ir = subprocess.run(
                [sys.executable, "-m", "silu", "ir", program,
                 "--format", "json"],
                capture_output=True, text=True, cwd=REPO, timeout=600,
            ).stdout
            assert TypedCodegen().convert(ir) == \
                flat.TypedCodegen().convert(ir), program
    finally:
        os.unlink(flat_path)
