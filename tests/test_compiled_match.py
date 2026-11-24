#!/usr/bin/env python3
"""
Tests for compiled match statements (typed backend). The reference is
the IR interpreter (the AST interpreter has no match support; `silu
verify` therefore cannot check match programs - pre-existing gap).

Supported in compiled code: value literals (incl. enum members),
or-patterns, capture, wildcard, guards. Subjects: int/float/bool/str
(annotated). Sequence/mapping/class patterns are compile-time errors.
"""

import pytest

from silu.ir_generator import SiluIRGenerator
from silu.typed_codegen import TypedCodegen
from tests.test_str_builtins import run_ir, run_mcjit
import ast
import json


def check(source: str) -> str:
    expected = run_ir(source)
    assert run_mcjit(source) == expected
    return expected


class TestCompiledMatchScalars:
    def test_int_first_match_wins(self):
        assert check(
            "x: int = 2\n"
            "match x:\n"
            "    case 1:\n"
            '        print("one")\n'
            "    case 2 | 3:\n"
            '        print("few")\n'
            "    case _:\n"
            '        print("other")\n'
        ) == "few\n"

    def test_no_match_is_noop(self):
        assert check(
            "x: int = 99\n"
            "match x:\n"
            "    case 1:\n"
            '        print("one")\n'
            'print("after")\n'
        ) == "after\n"

    def test_capture_with_guard(self):
        assert check(
            "x: int = 42\n"
            "match x:\n"
            "    case 0:\n"
            '        print("zero")\n'
            "    case n if n > 10:\n"
            '        print("big", n)\n'
            "    case _:\n"
            '        print("small")\n'
        ) == "big 42\n"

    def test_capture_falls_through_when_guard_fails(self):
        assert check(
            "x: int = 5\n"
            "match x:\n"
            "    case n if n > 10:\n"
            '        print("big", n)\n'
            "    case n:\n"
            '        print("any", n)\n'
        ) == "any 5\n"

    def test_float_subject(self):
        assert check(
            "f: float = 2.5\n"
            "match f:\n"
            "    case 1.5:\n"
            '        print("one half")\n'
            "    case 2.5:\n"
            '        print("two half")\n'
            "    case _:\n"
            '        print("other")\n'
        ) == "two half\n"

    def test_bool_subject(self):
        assert check(
            "b: bool = False\n"
            "match b:\n"
            "    case True:\n"
            '        print("yes")\n'
            "    case False:\n"
            '        print("no")\n'
        ) == "no\n"


class TestCompiledMatchStrings:
    def test_str_literal_cases(self):
        assert check(
            's: str = "hello"\n'
            "match s:\n"
            '    case "bye":\n'
            '        print("bye")\n'
            '    case "hello":\n'
            '        print("hi there")\n'
            "    case _:\n"
            '        print("?")\n'
        ) == "hi there\n"

    def test_str_capture(self):
        assert check(
            's: str = "abc"\n'
            "match s:\n"
            '    case "":\n'
            '        print("empty")\n'
            "    case w:\n"
            '        print("got", w, len(w))\n'
        ) == "got abc 3\n"

    def test_str_multibyte(self):
        assert check(
            's: str = "世界"\n'
            "match s:\n"
            '    case "你好":\n'
            '        print("hello")\n'
            '    case "世界":\n'
            '        print("world")\n'
            "    case _:\n"
            '        print("?")\n'
        ) == "world\n"


class TestCompiledMatchEnum:
    def test_enum_member_patterns(self):
        assert check(
            "class Kind(Enum):\n"
            "    NUM\n"
            "    IDENT\n"
            "    PLUS\n"
            "t: int = Kind.IDENT\n"
            "match t:\n"
            "    case Kind.NUM:\n"
            '        print("num")\n'
            "    case Kind.IDENT | Kind.PLUS:\n"
            '        print("word")\n'
            "    case _:\n"
            '        print("?")\n'
        ) == "word\n"

    def test_match_in_method(self):
        assert check(
            "class Kind(Enum):\n"
            "    NUM\n"
            "    IDENT\n"
            "class Token:\n"
            "    kind: Kind\n"
            "    text: str\n"
            "    def describe(self) -> str:\n"
            "        match self.kind:\n"
            "            case Kind.NUM:\n"
            '                return "num"\n'
            "            case _:\n"
            '                return self.text\n'
            't = Token(Kind.NUM, "x")\n'
            "print(t.describe())\n"
            't2 = Token(Kind.IDENT, "abc")\n'
            "print(t2.describe())\n"
        ) == "num\nabc\n"


class TestCompiledMatchNesting:
    def test_match_in_loop(self):
        assert check(
            "total: int = 0\n"
            "i: int = 0\n"
            "while i < 5:\n"
            "    match i:\n"
            "        case 0 | 2 | 4:\n"
            "            total += 10\n"
            "        case _:\n"
            "            total += 1\n"
            "    i += 1\n"
            "print(total)\n"
        ) == "32\n"

    def test_match_in_function(self):
        assert check(
            "def classify(x: int) -> int:\n"
            "    match x:\n"
            "        case 0:\n"
            "            return 100\n"
            "        case n if n < 0:\n"
            "            return -1\n"
            "        case _:\n"
            "            return 1\n"
            "print(classify(0), classify(-5), classify(7))\n"
        ) == "100 -1 1\n"


class TestCompiledMatchUnsupported:
    def _convert(self, source: str):
        TypedCodegen().convert(
            json.dumps(SiluIRGenerator().visit(ast.parse(source)))
        )

    def test_sequence_pattern_rejected(self):
        with pytest.raises(NotImplementedError, match="match"):
            self._convert(
                "x: int = 1\n"
                "match x:\n"
                "    case [1, 2]:\n"
                '        print("seq")\n'
            )

    def test_dynamic_subject_rejected(self):
        # a dynamic (boxed) subject supports class patterns, captures
        # and wildcards; matching VALUES against it still requires a
        # statically typed subject
        with pytest.raises(NotImplementedError, match="annotate"):
            # a genuinely dynamic subject: the 1-arg dict get's boxed
            # phi (input() is statically str since the g-#10 inference
            # round, so it no longer exercises this path)
            self._convert(
                "d = {}\n"
                "x = d.get(\"k\")\n"
                "match x:\n"
                "    case 1:\n"
                '        print("one")\n'
            )


class TestMatchSwitchLowering:
    """P8: all-int-literal matches lower to an LLVM switch instead of
    the icmp chain (reference/PROPOSALS.md P8); everything else keeps
    the chain. The Rust twin must stay byte-identical - that contract
    is gated by reference/diff_harness.py ll on benchmarks/match_int.si."""

    def _ll(self, source: str) -> str:
        return TypedCodegen().convert(
            json.dumps(SiluIRGenerator().visit(ast.parse(source)))
        )

    def test_int_literals_lower_to_switch(self):
        ll = self._ll(
            "x: int = 2\n"
            "match x:\n"
            "    case 1:\n"
            "        print(10)\n"
            "    case 2:\n"
            "        print(20)\n"
            "    case _:\n"
            "        print(42)\n"
        )
        assert "switch i64" in ll
        assert 'label %"match_default"' in ll
        assert 'label %"match_case"' in ll
        # the chain shape is gone for this program
        assert "case_body" not in ll

    def test_guard_keeps_chain(self):
        ll = self._ll(
            "x: int = 12\n"
            "match x:\n"
            "    case 0:\n"
            "        print(10)\n"
            "    case n if n > 10:\n"
            "        print(20)\n"
            "    case _:\n"
            "        print(42)\n"
        )
        assert "switch i64" not in ll
        assert "case_body" in ll

    def test_str_subject_keeps_chain(self):
        ll = self._ll(
            's: str = "hello"\n'
            "match s:\n"
            '    case "bye":\n'
            "        print(1)\n"
            '    case "hello":\n'
            "        print(2)\n"
            "    case _:\n"
            "        print(3)\n"
        )
        assert "switch i64" not in ll

    def test_duplicate_values_keep_chain(self):
        # duplicate int values would be invalid LLVM switch cases;
        # first-match-wins semantics stay on the icmp chain
        ll = self._ll(
            "x: int = 1\n"
            "match x:\n"
            "    case 1:\n"
            "        print(10)\n"
            "    case 1:\n"
            "        print(20)\n"
            "    case _:\n"
            "        print(42)\n"
        )
        assert "switch i64" not in ll

    def test_wildcard_body_runs_via_default(self):
        assert check(
            "x: int = 7\n"
            "match x:\n"
            "    case 1:\n"
            "        print(10)\n"
            "    case _:\n"
            "        print(42)\n"
        ) == "42\n"
