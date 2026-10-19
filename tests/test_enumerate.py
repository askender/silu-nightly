"""enumerate() desugar regression tests (typed backend).

The desugar hides a counter variable; the increment must happen before
the body runs, because a `continue` in the body would otherwise skip a
trailing increment and pin every iteration at index 0 (the 2026-10-19
bug that mis-kinded every parameter of _generate_dynamic_function_body
in the self-hosted converter).
"""

import pytest

from tests.test_str_builtins import run_ir, run_mcjit


def check(source: str) -> str:
    expected = run_ir(source)
    assert run_mcjit(source) == expected
    return expected


class TestEnumerateCounter:
    def test_basic(self):
        assert check(
            "for i, x in enumerate(['a', 'b', 'c']):\n"
            "    print(i)\n"
            "    print(x)\n"
        ) == "0\na\n1\nb\n2\nc\n"

    def test_continue_advances_index(self):
        """continue must not stall the hidden counter."""
        assert check(
            "total = ''\n"
            "for i, x in enumerate(['a', 'b', 'c']):\n"
            "    if i == 1:\n"
            "        continue\n"
            "    total += str(i) + x\n"
            "print(total)\n"
        ) == "0a2c\n"

    def test_break_advances_until_break(self):
        assert check(
            "for i, x in enumerate(['a', 'b', 'c', 'd']):\n"
            "    if i == 2:\n"
            "        break\n"
            "    print(i)\n"
        ) == "0\n1\n"

    def test_counter_as_subscript(self):
        """the enumerate counter indexing another list (the converter's
        own param-loop pattern)."""
        assert check(
            "xs = [10, 20, 30]\n"
            "for i, p in enumerate(['a', 'b', 'c']):\n"
            "    print(xs[i])\n"
        ) == "10\n20\n30\n"
