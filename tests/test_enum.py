#!/usr/bin/env python3
"""
Tests for simple enums (class Color(Enum): RED = 1) across all three
backends. Silu enums are bare int discriminants (Rust-style), not
Python's wrapped member objects.
"""

import ast
import io
import json
from contextlib import redirect_stdout

import pytest

from silu.interpreter import SiluInterpreter
from silu.ir_generator import SiluIRGenerator
from silu.ir_interpreter import IRInterpreter
from silu.typed_codegen import TypedCodegen

from tests.test_str_builtins import run_ast, run_ir, run_mcjit


def check_all(source: str) -> str:
    expected = run_ast(source)
    assert run_ir(source) == expected
    assert run_mcjit(source) == expected
    return expected


class TestEnumBasics:
    def test_explicit_values(self):
        assert check_all(
            "class Color(Enum):\n    RED = 1\n    GREEN = 2\n    BLUE = 5\n"
            "print(Color.RED, Color.GREEN, Color.BLUE)\n"
        ) == "1 2 5\n"

    def test_auto_numbering(self):
        assert check_all(
            "class TokenKind(Enum):\n    NUM\n    IDENT\n    PLUS\n"
            "print(TokenKind.NUM, TokenKind.IDENT, TokenKind.PLUS)\n"
        ) == "0 1 2\n"

    def test_auto_continues_from_explicit(self):
        assert check_all(
            "class E(Enum):\n    A = 10\n    B\n    C\n"
            "print(E.A, E.B, E.C)\n"
        ) == "10 11 12\n"

    def test_negative_value(self):
        assert check_all(
            "class E(Enum):\n    ERR = -1\n    OK\n"
            "print(E.ERR, E.OK)\n"
        ) == "-1 0\n"

    def test_enum_typed_variable(self):
        assert check_all(
            "class Color(Enum):\n    RED = 1\n    GREEN = 2\n"
            "c: Color = Color.GREEN\n"
            "print(c == Color.GREEN, c == Color.RED)\n"
        ) == "True False\n"

    def test_enum_arithmetic_and_compare(self):
        assert check_all(
            "class Color(Enum):\n    RED = 1\n    BLUE = 5\n"
            "print(Color.RED + Color.BLUE, Color.BLUE > Color.RED)\n"
        ) == "6 True\n"

    def test_enum_in_class_field(self):
        assert check_all(
            "class Kind(Enum):\n    NUM\n    IDENT\n"
            "class Token:\n    kind: Kind\n    text: str\n"
            "t = Token(Kind.NUM, \"42\")\n"
            "print(t.kind, t.text)\n"
        ) == "0 42\n"

    def test_enum_field_method_dispatch(self):
        assert check_all(
            "class Kind(Enum):\n    NUM\n    IDENT\n"
            "class Token:\n    kind: Kind\n"
            "    def is_num(self) -> bool:\n"
            "        return self.kind == Kind.NUM\n"
            "t = Token(Kind.NUM)\n"
            "print(t.is_num())\n"
        ) == "True\n"


class TestEnumErrors:
    def test_non_int_member_rejected(self):
        with pytest.raises(Exception, match="must be an int|integer constant"):
            run_ir("class E(Enum):\n    A = \"x\"\n")

    def test_non_int_member_rejected_compiled(self):
        with pytest.raises(NotImplementedError, match="integer constant"):
            TypedCodegen().convert(
                json.dumps(
                    SiluIRGenerator().visit(
                        ast.parse('class E(Enum):\n    A = "x"\n')
                    )
                )
            )

    def test_unknown_member_compiled(self):
        with pytest.raises(AttributeError, match="has no member"):
            TypedCodegen().convert(
                json.dumps(
                    SiluIRGenerator().visit(
                        ast.parse(
                            "class E(Enum):\n    A = 1\nprint(E.B)\n"
                        )
                    )
                )
            )

    def test_other_inheritance_still_rejected(self):
        with pytest.raises(NotImplementedError, match="inheritance"):
            SiluIRGenerator().visit(
                ast.parse("class A(Base):\n    x: int\n")
            )
