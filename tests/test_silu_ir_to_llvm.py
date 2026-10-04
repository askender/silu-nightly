"""
Unit tests for the Silu IR to LLVM IR converter.

Regression focus: IR parsed by ir_utils arrives as tuple structures,
while the converter's node dispatch expects lists. Without normalization
the whole program body was silently skipped, producing an empty main.
"""

import ast
import json

import llvmlite.binding as llvm

from silu.ir_generator import SiluIRGenerator
from silu.silu_ir_to_llvm import SiluToLLVMConverter


def _ir_json_from_source(source: str) -> str:
    """Generate Silu IR from source code and serialize it as JSON."""
    tree = ast.parse(source)
    ir_result = SiluIRGenerator().visit(tree)
    return json.dumps(ir_result)


def _convert(source: str) -> str:
    return SiluToLLVMConverter().convert(_ir_json_from_source(source))


class TestSiluToLLVMConverter:
    """Tests for the SiluToLLVMConverter class."""

    def test_module_level_statements_reach_main(self):
        """Top-level statements must generate code inside main.

        Regression: tuple IR nodes were skipped by list-only dispatch,
        leaving main as a bare `ret i32 0`.
        """
        llvm_ir = _convert('x = 5\ny = 3\nprint("Result:", x + y)\n')

        assert 'define i32 @"main"' in llvm_ir
        assert 'call void @"pyobj_print"' in llvm_ir

    def test_main_is_not_empty(self):
        """main must contain more than a return instruction."""
        llvm_ir = _convert("x = 5\nprint(x)\n")

        main_body = llvm_ir.split('define i32 @"main"')[1]
        assert "ret i32 0" in main_body
        assert "store" in main_body or "call" in main_body

    def test_generated_llvm_ir_parses(self):
        """Generated LLVM IR must be valid assembly."""
        llvm_ir = _convert('x = 5\nprint("Result:", x)\n')

        llvm.initialize()
        llvm.parse_assembly(llvm_ir)

    def test_user_function_generated_and_called(self):
        """User functions must be defined and calls emitted."""
        llvm_ir = _convert(
            "def add(a, b):\n    return a + b\n\nresult = add(2, 3)\nprint(result)\n"
        )

        assert 'define {i32, i8*}* @"add"' in llvm_ir
        assert 'call {i32, i8*}* @"add"' in llvm_ir

    def test_tuple_format_ir_string_also_converted(self):
        """Python-literal IR format (tuples) must convert too."""
        ir_literal = "('module', (('assign', 'x', ('const', 5), None), "
        ir_literal += "('call', ('name', 'print'), (('name', 'x'),), ())))"

        llvm_ir = SiluToLLVMConverter().convert(ir_literal)

        assert 'define i32 @"main"' in llvm_ir
        assert 'call void @"pyobj_print"' in llvm_ir

    def test_for_loop_converted(self):
        """For loops over range must produce loop basic blocks."""
        llvm_ir = _convert(
            "total = 0\nfor i in range(3):\n    total = total + i\nprint(total)\n"
        )

        assert "loop_cond:" in llvm_ir or "loop_body:" in llvm_ir

    def test_while_loop_converted(self):
        """While loops must produce condition/body/end basic blocks."""
        llvm_ir = _convert("i = 0\nwhile i < 5:\n    i = i + 1\nprint(i)\n")

        assert "while_cond:" in llvm_ir
        assert "while_body:" in llvm_ir
        assert "while_end:" in llvm_ir

    def test_comparison_operations_converted(self):
        """All six comparison operators must emit runtime calls."""
        llvm_ir = _convert(
            "a = 3\nb = 4\n"
            "print(a == b)\nprint(a != b)\nprint(a < b)\n"
            "print(a <= b)\nprint(a > b)\nprint(a >= b)\n"
        )

        for name in ("eq", "ne", "lt", "le", "gt", "ge"):
            assert f'call {{i32, i8*}}* @"pyobj_{name}"' in llvm_ir

    def test_arithmetic_operations_converted(self):
        """Subtraction and multiplication must emit runtime calls."""
        llvm_ir = _convert("a = 7 - 2\nb = a * 3\nprint(b)\n")

        assert 'call {i32, i8*}* @"pyobj_sub"' in llvm_ir
        assert 'call {i32, i8*}* @"pyobj_mul"' in llvm_ir

    def test_string_concat_runtime_present(self):
        """pyobj_add must contain the string concatenation path."""
        llvm_ir = _convert('a = "Hello " + "Silu"\n')

        assert "str_concat:" in llvm_ir
        assert 'call void @"llvm.memcpy' in llvm_ir

    def test_print_separator_emitted(self):
        """Multi-argument print must emit a space separator."""
        llvm_ir = _convert('print("Result:", 8)\n')

        assert 'c" \\00"' in llvm_ir

    def test_floordiv_and_mod_converted(self):
        """Floor division and modulo must emit runtime calls."""
        llvm_ir = _convert("a = 123 // 7\nb = 123 % 7\nprint(a + b)\n")

        assert 'call {i32, i8*}* @"pyobj_floordiv"' in llvm_ir
        assert 'call {i32, i8*}* @"pyobj_mod"' in llvm_ir

    def test_if_expr_converted(self):
        """Conditional expressions must produce a phi merge."""
        llvm_ir = _convert("x = 5\ny = 1 if x else 2\nprint(y)\n")

        assert "iexpr_merge:" in llvm_ir
        assert "phi" in llvm_ir

    def test_bool_constant_and_comparison_results(self):
        """Bool constants and comparison results must use create_bool."""
        llvm_ir = _convert("x = True\ny = 3 > 2\nprint(x, y)\n")

        assert 'call {i32, i8*}* @"create_bool"' in llvm_ir

    def test_none_printing_supported(self):
        """pyobj_print must handle null pointers as None."""
        llvm_ir = _convert("def f():\n    return\n\nprint(f())\n")

        assert "print_null:" in llvm_ir
        assert 'c"None\\00"' in llvm_ir
