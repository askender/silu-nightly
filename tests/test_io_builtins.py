#!/usr/bin/env python3
"""
Tests for the read_file / read_stdin builtins across all three backends
(AST interpreter, IR interpreter, typed compiler). These are the
self-hosting prerequisites (docs/selfhosting.md): a compiler must be
able to read its source.
"""

import ast
import io
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

import pytest

from silu.interpreter import SiluInterpreter
from silu.ir_generator import SiluIRGenerator
from silu.ir_interpreter import IRInterpreter


def run_ast(source: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        SiluInterpreter().visit(ast.parse(source))
    return buf.getvalue()


def run_ir(source: str, stdin_text: str = "") -> str:
    ir = SiluIRGenerator().visit(ast.parse(source))
    buf = io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        with redirect_stdout(buf):
            IRInterpreter().execute_program(ir)
    finally:
        sys.stdin = old_stdin
    return buf.getvalue()


def run_compiled(source: str, stdin_text: str = "") -> str:
    """Build with clang and run (MCJIT would die on panic paths)."""
    if shutil.which("clang") is None:
        pytest.skip("clang not available")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".si", delete=False
    ) as handle:
        handle.write(source)
        src_path = handle.name
    bin_path = src_path + ".bin"
    build = subprocess.run(
        [sys.executable, "-m", "silu", "build", src_path, "-o", bin_path],
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    return subprocess.run(
        [bin_path], input=stdin_text, capture_output=True, text=True
    ).stdout


class TestReadFile:
    def test_all_backends(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("hello 世界\nsecond line\n")
            path = handle.name

        source = (
            f's: str = read_file("{path}")\n'
            "print(len(s))\n"
            "print(s[0])\n"
            "print(s[6])\n"
            "print(s[-2])\n"
        )
        expected = run_ir(source)
        assert run_ast(source) == expected
        assert run_compiled(source) == expected

    def test_missing_file_panics_compiled(self):
        if shutil.which("clang") is None:
            pytest.skip("clang not available")
        with tempfile.NamedTemporaryFile(
            "w", suffix=".si", delete=False
        ) as handle:
            handle.write('s: str = read_file("/nonexistent/_nope_")\n')
            src_path = handle.name
        bin_path = src_path + ".bin"
        build = subprocess.run(
            [sys.executable, "-m", "silu", "build", src_path, "-o", bin_path],
            capture_output=True,
            text=True,
        )
        assert build.returncode == 0, build.stderr
        run = subprocess.run([bin_path], capture_output=True, text=True)
        assert run.returncode == 1
        assert "OSError" in run.stdout

    def test_missing_file_raises_in_interpreters(self):
        source = 's = read_file("/nonexistent/_nope_")\n'
        with pytest.raises(OSError):
            run_ir(source)
        with pytest.raises(OSError):
            run_ast(source)


class TestReadStdin:
    def test_read_all_keeps_newlines(self):
        source = (
            "s: str = read_stdin()\n"
            "print(len(s))\n"
            "print(s)\n"
        )
        payload = "line one\nline two 世界\n"
        # IR interpreter (stdin patched) vs compiled binary (real stdin)
        expected = run_ir(source, stdin_text=payload)
        assert expected == f"{len(payload)}\n{payload}\n"
        assert run_compiled(source, stdin_text=payload) == expected

    def test_read_stdin_ast(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".si", delete=False
        ) as handle:
            handle.write("s = read_stdin()\nprint(len(s))\n")
            src_path = handle.name
        run = subprocess.run(
            [sys.executable, "-m", "silu", "interpret", src_path],
            input="abc\n",
            capture_output=True,
            text=True,
        )
        assert run.stdout == "4\n"
