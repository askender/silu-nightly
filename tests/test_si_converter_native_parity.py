"""Native parity gate: the self-hosted converter (typed_codegen.py +
silu_ir_to_llvm.py flattened to typed_codegen_flat.si, compiled by clang
-O2, the same pipeline `silu build` uses) must emit byte-identical .ll
to the Python converter for every benchmark program.

This is the only gate that crosses the object-model boundary: the
interpreter-based parity gates all execute the .si converter under
CPython, where Python's object semantics mask native-plane divergence
(heap corruption, layout shifts, tag confusion). Here the converter runs
as a native binary, so its own dict/list/str/box machinery is exercised
exactly as compiled.
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
    """Flatten the converter and build it natively (once per module).

    The build is cached across runs in $TMPDIR, keyed on the content of
    the converter sources + the twin + the flatten tool - the ~25s
    flatten/ir/llvm/clang chain only reruns when one of them changes."""
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    import hashlib

    key_src = ""
    for path in (
        "silu/typed_codegen.py",
        "silu/typed_helpers.py",
        "silu/silu_ir_to_llvm.py",
        "silu/llvmlite_text.py",
        "selfhost/llvmlite.si",
        "tools/flatten_codegen.py",
        "tools/flatten_si_tail.si",
        "selfhost/silu_conv_main.si",
    ):
        with open(os.path.join(REPO, path), "rb") as handle:
            key_src += handle.read().decode("utf-8", "replace")
    digest = hashlib.sha256(key_src.encode("utf-8")).hexdigest()[:16]
    cached = os.path.join(
        os.environ.get("TMPDIR", "/tmp"), f"silu_native_conv_{digest}"
    )
    if os.path.exists(cached) and os.access(cached, os.X_OK):
        return cached

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
    # flat is main-free (siluc.si imports it inline); the runnable
    # converter is the thin wrapper, and the wrapper is its own source
    shutil.copy(os.path.join(REPO, "selfhost", "silu_conv_main.si"),
                tmp / "silu_conv_main.si")

    ir_json = tmp / "flat.ir.json"
    result = _run(
        [PY, "-m", "silu", "ir", str(tmp / "silu_conv_main.si"),
         "--format", "json", "--output", str(ir_json)]
    )
    assert result.returncode == 0, result.stderr
    conv_ll = tmp / "flat_conv.ll"
    result = _run(
        [PY, "-m", "silu", "llvm", str(ir_json), "--output", str(conv_ll)]
    )
    assert result.returncode == 0, result.stderr
    binary = tmp / "flat_conv"
    # -O2, the same optimization level `silu build` uses: the converter
    # must be sound under real optimization (the historical "O2
    # miscompiles the converter" symptom was a heap-overflow bug in the
    # generated runtime - list_insert leaving capacity stale - not a
    # clang issue)
    build = subprocess.run(
        ["clang", "-O2", str(conv_ll), "-lm", "-o", str(binary)],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    # atomic cache publish: a partial copy must never poison the cache
    tmp_cache = cached + "." + str(os.getpid()) + ".tmp"
    shutil.copy(str(binary), tmp_cache)
    os.replace(tmp_cache, cached)
    return cached


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
