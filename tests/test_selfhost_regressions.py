"""Regression guards for the large-file frontend memory blowup.

v1.15.0's copy-into wiring converted the subscript BASE eagerly for any
`x = <subscript>` assignment with a str target, then used it only when
the base was a list[str] - for every other shape (self.src[a:b] field
lookahead slices in the lexer) the conversion became a leaked
whole-source rawstr_copy per iteration, making the self-hosted front
end need >15GB on its own ~12k-line source. The companion guard below
keeps nested functions in the flattened converter free of ir-module
captures (Rust no-capture semantics), which is what lets the front end
parse the flattened converter at all.
"""

import ast
import pathlib
import re
import subprocess
import sys

import pytest

from tests import REPO

PY = sys.executable
CONVERTER_SOURCES = [
    "silu/typed_codegen.py", "silu/pyobj_runtime.py",
    "silu/silu_ir_to_llvm.py", "silu/typed_helpers.py",
    "silu/typed_expr.py", "silu/typed_match.py", "silu/typed_call.py",
]


def _ll_for(source: str, tmp_path) -> str:
    si = tmp_path / "p.si"
    si.write_text(source)
    ir_json = tmp_path / "p.ir.json"
    ll = tmp_path / "p.ll"
    r = subprocess.run(
        [PY, "-m", "silu", "ir", str(si), "-o", str(ir_json)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        [PY, "-m", "silu", "llvm", str(ir_json), "-o", str(ll)],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    return ll.read_text()


def test_field_slice_assign_has_no_dead_base_copy(tmp_path):
    """`t = self.src[a:b]` must slice the borrowed field - the assign
    matcher may not materialize a copy-on-read of the whole base. The
    slice RESULT may still be copied once (slot-ownership semantics);
    the regression copied the whole base before ever slicing."""
    source = (
        "class L:\n"
        "    src: str\n"
        "    def take(self, a: int, b: int) -> str:\n"
        "        t: str = self.src[a:b]\n"
        "        return t\n"
        "l = L(\"hello world\")\n"
        "print(l.take(2, 5))\n"
    )
    text = _ll_for(source, tmp_path)
    fn = text.split('@"L__take"')[1].split("\ndefine")[0]
    assert 'rawstr_slice' in fn, "expected the field slice"
    defs = {}
    for line in fn.splitlines():
        m = re.match(r'\s*(%"[^"]+") = (.+)', line)
        if m:
            defs[m.group(1)] = m.group(2)
    for line in fn.splitlines():
        m = re.search(r'call i8\* @"rawstr_copy"\((%"[^"]+")\)', line)
        if m:
            origin = defs.get(m.group(1), "")
            assert "getelementptr" not in origin and "load" not in origin, (
                f"rawstr_copy of a field/base load returned ({origin[:80]}) "
                "- the whole-source leak that made the self-hosted front "
                "end quadratic on large files"
            )


def test_list_str_assign_still_uses_copy_into(tmp_path):
    """The optimization itself must survive the narrower matcher."""
    source = (
        "w: list[str] = [\"aa\", \"bb\", \"cc\"]\n"
        "t: str = w[1]\n"
        "print(t)\n"
    )
    text = _ll_for(source, tmp_path)
    assert "rawlist_str_copy_into" in text


def test_converter_nested_functions_do_not_capture_the_ir_module():
    """Rust no-capture semantics: a nested function/lambda in the
    flattened converter sources referencing the ir module breaks the
    front end's import hoister when it parses its own converter."""
    offenders = []
    for rel in CONVERTER_SOURCES:
        tree = ast.parse(pathlib.Path(REPO, rel).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.FunctionDef, ast.Lambda)):
                    src = ast.unparse(child)
                    if "ir." in src or "llvmlite." in src:
                        label = getattr(child, "name", "<lambda>")
                        offenders.append(f"{rel}: {node.name} -> {label}")
    assert not offenders, (
        "nested functions must not reference the ir module (route "
        "types/constants through self): " + "; ".join(offenders)
    )


@pytest.mark.skipif(
    not pathlib.Path(REPO, "selfhost", "typed_codegen_flat.si").exists(),
    reason="flattened converter not generated yet",
)
def test_flattened_converter_parses_in_its_own_front_end(tmp_path):
    """End-to-end memory guard: the self-hosted front end must parse
    the largest Silu program (its own converter) in bounded memory -
    the regression had it OOM-killed at >15GB."""
    import os

    if subprocess.run(["clang", "--version"], capture_output=True).returncode != 0:
        pytest.skip("clang not available")
    import tools.selfhost_build as shb

    fe = shb.ensure_frontend()
    flat = os.path.join(REPO, "selfhost", "typed_codegen_flat.si")
    r = subprocess.run(
        [fe], stdin=open(flat, "r"), capture_output=True,
        cwd=os.path.dirname(flat), timeout=600,
    )
    assert r.returncode == 0, r.stderr[:300]
    assert len(r.stdout) > 1_000_000, (
        f"expected the ~1.8MB IR, got {len(r.stdout)} bytes"
    )
