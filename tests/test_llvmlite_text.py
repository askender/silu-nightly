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


def test_flatten_si_output_checks(tmp_path):
    """The --si emission of the flatten script is valid Silu (and its
    module-level code, with the inlined llvmlite twin, executes under
    the AST interpreter)."""
    r = subprocess.run(
        [sys.executable, f"{REPO}/tools/flatten_codegen.py", "--si"],
        capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, r.stderr
    # the import resolves against selfhost/llvmlite.si
    out = tmp_path / "typed_codegen_flat.si"
    out.write_text(r.stdout)
    llvmlite_twin = (tmp_path / "llvmlite.si")
    llvmlite_twin.write_text(open(f"{REPO}/selfhost/llvmlite.si").read())
    c = subprocess.run(
        [sys.executable, "-m", "silu", "check", str(out)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert c.returncode == 0, c.stdout + c.stderr
    assert c.stdout.strip().endswith("ok")


def test_si_converter_interpreter_parity():
    """The full milestone gate: the flattened .si converter (with the
    llvmlite.si twin) runs under the Silu AST interpreter and its .ll
    output is byte-identical to the Python+llvmlite converter."""
    import tempfile

    flat = subprocess.run(
        [sys.executable, f"{REPO}/tools/flatten_codegen.py", "--si"],
        capture_output=True, text=True, timeout=600,
    )
    assert flat.returncode == 0, flat.stderr
    with tempfile.TemporaryDirectory() as td:
        flat_path = os.path.join(td, "typed_codegen_flat.si")
        with open(flat_path, "w") as h:
            h.write(flat.stdout)
        # module resolution: llvmlite.si must sit next to the flat
        # file, and the entry is the thin wrapper (flat is main-free)
        with open(os.path.join(td, "llvmlite.si"), "w") as h:
            h.write(open(f"{REPO}/selfhost/llvmlite.si").read())
        wrapper_path = os.path.join(td, "silu_conv_main.si")
        with open(wrapper_path, "w") as h:
            h.write(open(f"{REPO}/selfhost/silu_conv_main.si").read())

        def one(program, index):
            ir = subprocess.run(
                [sys.executable, "-m", "silu", "ir", program,
                 "--format", "json"],
                capture_output=True, text=True, cwd=REPO, timeout=600,
            ).stdout
            ir_path = os.path.join(td, f"p{index}.ir.json")
            ref_path = os.path.join(td, f"ref{index}.ll")
            with open(ir_path, "w") as h:
                h.write(ir)
            real = subprocess.run(
                [sys.executable, "-m", "silu", "llvm", ir_path,
                 "--output", ref_path],
                capture_output=True, text=True, cwd=REPO,
                timeout=600,
            )
            assert real.returncode == 0, real.stderr
            silu = subprocess.run(
                [sys.executable, "-m", "silu", "interpret", wrapper_path],
                input=ir, capture_output=True, text=True, cwd=REPO,
                timeout=600,
            )
            assert silu.returncode == 0, (program, silu.stderr[-300:])
            assert silu.stdout == open(ref_path).read(), program

        # the per-program work is independent subprocesses; parallelize
        # (16 sequential AST-interpreter conversions cost ~90s)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(one, program, index)
                for index, program in enumerate(PROGRAMS)
            ]
            for future in futures:
                future.result()


BITWISE_PROGRAMS = [
    ("print(0xC0 | 5)\nprint(0xFF & 0x0F)\n", "197\n15\n"),
    ("print(5 ^ 3)\nprint(1 << 10)\nprint(1024 >> 3)\n", "6\n1024\n128\n"),
    (
        "def mix(a, b):\n"
        "    return (a | b) & (a ^ b)\n\n"
        "print(mix(12, 10))\n",
        str((12 | 10) & (12 ^ 10)) + "\n",
    ),
]


@pytest.mark.parametrize("src,want", BITWISE_PROGRAMS)
def test_bitwise_typed_build(src, want, tmp_path):
    p = tmp_path / "b.si"
    p.write_text(src)
    b = subprocess.run(
        [sys.executable, "-m", "silu", "build", str(p),
         "-o", str(tmp_path / "b")],
        capture_output=True, text=True, cwd=REPO, timeout=300,
    )
    assert b.returncode == 0, b.stderr
    r = subprocess.run([str(tmp_path / "b")], capture_output=True, text=True)
    assert r.stdout == want


@pytest.mark.parametrize("src,want", BITWISE_PROGRAMS)
def test_bitwise_cpython(src, want):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True)
    assert r.stdout == want
