#!/usr/bin/env python3
"""
Tests for lexer-oriented string/char builtins (docs/selfhosting.md):
ord/chr, split, strip, startswith/endswith, isdigit/isalpha/isspace -
differential across AST interpreter, IR interpreter and the typed
compiler, plus the panic paths (compiled binaries via clang).
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
from silu.typed_codegen import TypedCodegen
import json


def run_ast(source: str) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        SiluInterpreter().visit(ast.parse(source))
    return buf.getvalue()


def run_ir(source: str) -> str:
    ir = SiluIRGenerator().visit(ast.parse(source))
    buf = io.StringIO()
    with redirect_stdout(buf):
        IRInterpreter().execute_program(ir)
    return buf.getvalue()


def run_mcjit(source: str) -> str:
    """Typed compiler through MCJIT (no panics expected)."""
    import ctypes
    import os

    from llvmlite import binding as llvm

    llvm_ir = TypedCodegen().convert(
        json.dumps(SiluIRGenerator().visit(ast.parse(source)))
    )
    module = llvm.parse_assembly(llvm_ir)
    module.verify()
    target = llvm.Target.from_default_triple()
    engine = llvm.create_mcjit_compiler(module, target.create_target_machine())
    engine.finalize_object()
    main_ptr = engine.get_function_address("main")
    output = tempfile.TemporaryFile()
    saved = os.dup(1)
    os.dup2(output.fileno(), 1)
    try:
        ctypes.CFUNCTYPE(ctypes.c_int)(main_ptr)()
        ctypes.CDLL(None).fflush(None)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    output.seek(0)
    return output.read().decode()


def run_compiled(source: str):
    """Build+run via clang (for panic paths; MCJIT would kill pytest)."""
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
    return subprocess.run([bin_path], capture_output=True, text=True)


def check_all(source: str) -> str:
    expected = run_ast(source)
    assert run_ir(source) == expected
    assert run_mcjit(source) == expected
    return expected


class TestOrdChr:
    def test_ascii(self):
        assert check_all('print(ord("A"))\nprint(ord("z"))\n') == "65\n122\n"

    def test_multibyte_codepoint(self):
        out = check_all('print(ord("世"))\nc: str = chr(19990)\nprint(c)\n')
        assert out == "19990\n世\n"

    def test_roundtrip(self):
        out = check_all(
            'i: int = 65\n'
            'while i < 91:\n'
            '    print(ord(chr(i)))\n'
            '    i += 1\n'
        )
        assert out.split() == [str(n) for n in range(65, 91)]

    def test_chr_4byte(self):
        assert check_all('print(ord(chr(128512)))\n') == "128512\n"

    def test_ord_rejects_long_string(self):
        run = run_compiled('print(ord("ab"))\n')
        assert run.returncode == 1
        assert "ord() expected a character" in run.stdout

    def test_chr_out_of_range(self):
        run = run_compiled("print(chr(1114112))\n")
        assert run.returncode == 1
        assert "chr() arg out of range" in run.stdout


class TestSplit:
    def test_sep_basic(self):
        assert check_all('print("a,b,,c".split(","))\n') == (
            "['a', 'b', '', 'c']\n"
        )

    def test_sep_edges(self):
        assert check_all('print(",a,".split(","))\n') == "['', 'a', '']\n"
        assert check_all('print("aaa".split("aa"))\n') == "['', 'a']\n"

    def test_sep_multibyte(self):
        assert check_all('print("甲、乙、丙".split("、"))\n') == (
            "['甲', '乙', '丙']\n"
        )

    def test_whitespace_default(self):
        assert check_all('print(" one  two\\tthree\\n".split())\n') == (
            "['one', 'two', 'three']\n"
        )
        assert check_all('print("   ".split())\n') == "[]\n"
        assert check_all('print("".split())\n') == "[]\n"

    def test_split_into_annotated_list(self):
        out = check_all(
            'w: list[str] = "a,b,c".split(",")\n'
            "print(len(w))\n"
            "print(w[1])\n"
        )
        assert out == "3\nb\n"

    def test_empty_sep_panics(self):
        run = run_compiled('s: str = "abc"\nprint(s.split(""))\n')
        assert run.returncode == 1
        assert "empty separator" in run.stdout


class TestStripAndAffix:
    def test_strip(self):
        assert check_all('s: str = "  hi \\n"\nprint(s.strip())\n') == "hi\n"
        assert check_all('s: str = "   "\nprint(len(s.strip()))\n') == "0\n"
        assert check_all('s: str = "abc"\nprint(s.strip())\n') == "abc\n"

    def test_strip_multibyte_untouched(self):
        assert check_all('s: str = " 你好 "\nprint(s.strip())\n') == "你好\n"

    def test_startswith_endswith(self):
        out = check_all(
            's: str = "hello world"\n'
            'print(s.startswith("hello"), s.startswith("world"))\n'
            'print(s.endswith("world"), s.endswith("hello"))\n'
            'print(s.startswith(""), s.endswith(""))\n'
            'print(s.startswith("hello world!"))\n'
        )
        assert out == "True False\nTrue False\nTrue True\nFalse\n"

    def test_affix_on_literal_and_view(self):
        out = check_all(
            'print("abc".startswith("ab"))\n'
            's: str = "xyz"\n'
            'print(s[0] == "x", "xyz".endswith("z"))\n'
        )
        assert out == "True\nTrue True\n"


class TestCharClasses:
    def test_digit_alpha_space(self):
        out = check_all(
            'd: str = "x9 \\u4e16"\n'
            "print(d[0].isalpha(), d[0].isdigit(), d[0].isspace())\n"
            "print(d[1].isalpha(), d[1].isdigit())\n"
            "print(d[2].isspace(), d[2].isalpha())\n"
            "print(d[3].isalpha(), d[3].isdigit())\n"
        )
        assert out == "True False False\nFalse True\nTrue False\nTrue False\n"

    def test_empty_string_is_false(self):
        assert check_all('print("".isdigit(), "".isalpha(), "".isspace())\n') == (
            "False False False\n"
        )

    def test_lexer_loop(self):
        """A tiny tokenizer: the M1 shape from docs/selfhosting.md."""
        src = (
            'src: str = "a1 + 23"\n'
            "i: int = 0\n"
            "n: int = len(src)\n"
            "while i < n:\n"
            "    ch = src[i]\n"
            "    if ch.isspace():\n"
            "        i += 1\n"
            "    elif ch.isdigit():\n"
            '        print("num", ch)\n'
            "        i += 1\n"
            "    elif ch.isalpha():\n"
            '        print("ident", ch)\n'
            "        i += 1\n"
            "    else:\n"
            '        print("op", ch)\n'
            "        i += 1\n"
        )
        assert check_all(src) == (
            "ident a\nnum 1\nop +\nnum 2\nnum 3\n"
        )


class TestOrdEdgeCases:
    def test_ord_view_of_multibyte(self):
        assert check_all('s: str = "你好"\nprint(ord(s[1]))\n') == "22909\n"
