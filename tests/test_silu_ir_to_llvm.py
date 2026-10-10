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

    def test_float_constants_and_arithmetic(self):
        """Float constants must create float objects; ops use float paths."""
        llvm_ir = _convert("x = 1.5\ny = x + 2.5\nprint(y)\n")

        assert 'call {i32, i8*}* @"create_float"' in llvm_ir
        assert "float_add:" in llvm_ir

    def test_true_division_emits_truediv(self):
        """'/' must emit the always-float truediv runtime call."""
        llvm_ir = _convert("print(7 / 2)\n")

        assert 'call {i32, i8*}* @"pyobj_truediv"' in llvm_ir

    def test_float_repr_runtime_present(self):
        """The Python-style float repr helper must be generated."""
        llvm_ir = _convert("print(4.0)\n")

        assert 'define i8* @"float_repr"' in llvm_ir
        assert 'c"%.15g\\00"' in llvm_ir

    def test_float_comparison_uses_fcmp(self):
        """Comparisons with floats must take the fcmp path."""
        llvm_ir = _convert("x = 1.5\nprint(x < 2)\n")

        assert "float_op:" in llvm_ir
        assert "fcmp olt" in llvm_ir

    def test_float_floor_div_and_mod(self):
        """Float floor division must use llvm.floor.f64."""
        llvm_ir = _convert("print(-10.0 // 3)\nprint(10.5 % 3)\n")

        assert 'call double @"llvm.floor.f64"' in llvm_ir
        assert "frem" in llvm_ir

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

    def test_break_and_continue_in_loops(self):
        """break/continue must branch to loop exit and increment blocks."""
        llvm_ir = _convert(
            "for i in range(5):\n"
            "    if i == 2:\n"
            "        break\n"
            "    if i == 1:\n"
            "        continue\n"
            "    print(i)\n"
        )

        assert "loop_incr:" in llvm_ir
        assert "loop_end:" in llvm_ir

    def test_aug_assign_converted(self):
        """Augmented assignment must desugar to load-op-store."""
        llvm_ir = _convert("n = 10\nn += 3\nn -= 1\nn *= 2\nprint(n)\n")

        assert 'call {i32, i8*}* @"pyobj_add"' in llvm_ir
        assert 'call {i32, i8*}* @"pyobj_sub"' in llvm_ir
        assert 'call {i32, i8*}* @"pyobj_mul"' in llvm_ir

    def test_list_literal_and_subscript(self):
        """List literals, subscript read/write, and negative index."""
        llvm_ir = _convert(
            "l = [1, 2, 3]\nprint(l[0])\nprint(l[-1])\nl[1] = 9\nprint(l)\n"
        )

        assert 'define {i32, i8*}* @"create_list"' in llvm_ir
        assert 'call {i32, i8*}* @"list_get"' in llvm_ir
        assert 'call void @"list_set"' in llvm_ir

    def test_list_append_and_len(self):
        """append method and len() builtin must emit runtime calls."""
        llvm_ir = _convert("l = [1]\nl.append(2)\nprint(len(l))\n")

        assert 'call {i32, i8*}* @"list_append"' in llvm_ir
        assert 'call {i32, i8*}* @"pyobj_len"' in llvm_ir

    def test_for_loop_over_list(self):
        """Non-range for loops must iterate lists via iter blocks."""
        llvm_ir = _convert("for e in [10, 20]:\n    print(e)\n")

        assert "iter_cond:" in llvm_ir
        assert "iter_body:" in llvm_ir
        assert 'call {i32, i8*}* @"list_get"' in llvm_ir

    def test_list_print_runtime(self):
        """pyobj_print must handle list objects."""
        llvm_ir = _convert("print([1, 2])\n")

        assert "print_list:" in llvm_ir
        assert 'c"[\\00"' in llvm_ir

    def test_list_methods(self):
        """reverse/insert/count/copy/clear runtime calls must be emitted."""
        llvm_ir = _convert(
            "l = [3, 1, 2]\nl.append(5)\nl.insert(0, 9)\nl.reverse()\n"
            "n = l.count(1)\nm = l.copy()\nl.clear()\nprint(n, m)\n"
        )

        assert 'call {i32, i8*}* @"list_insert"' in llvm_ir
        assert 'call {i32, i8*}* @"list_reverse"' in llvm_ir
        assert 'call {i32, i8*}* @"list_count"' in llvm_ir
        assert 'call {i32, i8*}* @"list_copy"' in llvm_ir
        assert 'call void @"list_clear"' in llvm_ir

    def test_list_concatenation(self):
        """list + list must take the list_concat path in pyobj_add."""
        llvm_ir = _convert("c = [1, 2] + [3]\nprint(c)\n")

        assert "list_concat:" in llvm_ir

    def test_string_methods(self):
        """upper/lower/find/rfind runtime calls must be emitted."""
        llvm_ir = _convert(
            's = "Hello"\nprint(s.upper())\nprint(s.lower())\n'
            'print(s.find("l"))\nprint(s.rfind("l"))\n'
        )

        assert 'call {i32, i8*}* @"str_upper"' in llvm_ir
        assert 'call {i32, i8*}* @"str_lower"' in llvm_ir
        assert 'call {i32, i8*}* @"str_find"' in llvm_ir
        assert 'call {i32, i8*}* @"str_rfind"' in llvm_ir

    def test_string_multiplication_and_equality(self):
        """str*int repetition and str==str memcmp path must exist."""
        llvm_ir = _convert(
            'a = "ab" * 3\nb = "a" == "a"\nc = "a" != "b"\nprint(a, b, c)\n'
        )

        assert 'call {i32, i8*}* @"str_repeat"' in llvm_ir
        assert "str_op:" in llvm_ir
        assert 'call i32 @"memcmp"' in llvm_ir

    def test_deep_equality_runtime(self):
        """list_count must use structural deep equality."""
        llvm_ir = _convert("print([1, 2].count(1))\n")

        assert 'call i1 @"pyobj_deep_eq"' in llvm_ir

    def test_not_operator(self):
        """not must call pyobj_truthy and negate into a bool."""
        llvm_ir = _convert("print(not 0)\nprint(not 1)\n")

        assert 'call i1 @"pyobj_truthy"' in llvm_ir
        assert 'call {i32, i8*}* @"create_bool"' in llvm_ir

    def test_and_or_short_circuit_chain(self):
        """N-ary and/or must chain through sc blocks with truthiness."""
        llvm_ir = _convert("y = 0 or [] or 7\nprint(y)\n")

        assert "sc_finish:" in llvm_ir
        assert "sc_next:" in llvm_ir
        assert 'call i1 @"pyobj_truthy"' in llvm_ir

    def test_truthiness_runtime(self):
        """pyobj_truthy must dispatch on int/float/str/list tags."""
        llvm_ir = _convert("if 0:\n    print(1)\nif []:\n    print(2)\n")

        assert 'define i1 @"pyobj_truthy"' in llvm_ir
        assert "truthy_list:" in llvm_ir
        assert "truthy_str:" in llvm_ir
