"""
Tests for the statically-typed LLVM backend (typed_codegen).

Focus: unboxed scalars from written annotations, boundary boxing,
Python numeric semantics with panics, and clean fallback to the
dynamic runtime for unannotated code.
"""

import ast
import json

from silu.ir_generator import SiluIRGenerator
from silu.typed_codegen import TypedCodegen


def _convert(source: str) -> str:
    tree = ast.parse(source)
    ir_result = SiluIRGenerator().visit(tree)
    return TypedCodegen().convert(json.dumps(ir_result))


def _main_body(llvm_ir: str) -> str:
    """The main() body only - the runtime library legitimately calls
    pyobj_* functions internally (list_sum, pyobj_add itself, ...)."""
    return llvm_ir.split('define i32 @"main"')[1]


class TestTypedCodegen:
    def test_annotated_ints_are_unboxed(self):
        """Annotated int arithmetic must not call pyobj runtime functions."""
        llvm_ir = _convert(
            "total: int = 0\ni: int = 0\n"
            "while i < 5:\n    total += i % 3\n    i += 1\n"
            "print(total)\n"
        )

        main = _main_body(llvm_ir)
        assert 'call {i32, i8*}* @"pyobj_add"' not in main
        assert 'call {i32, i8*}* @"pyobj_mod"' not in main
        assert "srem i64" in main
        # boxing only at the print boundary
        assert 'call {i32, i8*}* @"create_int"' in llvm_ir

    def test_annotated_floats_use_raw_doubles(self):
        """Float annotations produce fadd/fmul, not runtime calls."""
        llvm_ir = _convert("acc: float = 1.0\nacc = acc + 2.5 * 3.0\n")

        main = _main_body(llvm_ir)
        assert "fadd double" in main
        assert "fmul double" in main
        assert 'call {i32, i8*}* @"pyobj_add"' not in main

    def test_int_float_promotion(self):
        """int + float promotes to double (Python semantics)."""
        llvm_ir = _convert("a: int = 2\nb: float = 0.5\nprint(a + b)\n")

        assert "sitofp i64" in llvm_ir
        assert "fadd double" in llvm_ir

    def test_true_division_always_float(self):
        """Annotated int '/' promotes both sides and yields float."""
        llvm_ir = _convert("a: int = 7\nb: int = 2\nprint(a / b)\n")

        assert "sitofp" in llvm_ir
        assert "fdiv double" in llvm_ir

    def test_overflow_panics_inlined(self):
        """Unboxed add/sub/mul use with.overflow intrinsics and panic."""
        llvm_ir = _convert(
            "a: int = 1\nb: int = 2\nprint(a + b)\nprint(a - b)\nprint(a * b)\n"
        )

        assert 'call {i64, i1} @"llvm.sadd.with.overflow.i64"' in llvm_ir
        assert 'call {i64, i1} @"llvm.ssub.with.overflow.i64"' in llvm_ir
        assert 'call {i64, i1} @"llvm.smul.with.overflow.i64"' in llvm_ir
        assert llvm_ir.count("OverflowError: integer overflow") >= 3

    def test_zero_division_panic_inlined(self):
        """Unboxed //, % and / check zero divisors."""
        llvm_ir = _convert(
            "a: int = 7\nb: int = 2\nc: float = 2.0\n"
            "print(a // b)\nprint(a % b)\nprint(a / b)\nprint(a / c)\n"
        )

        assert llvm_ir.count("ZeroDivisionError: division by zero") >= 4

    def test_static_function_raw_abi(self):
        """Fully annotated functions get raw-typed signatures."""
        llvm_ir = _convert(
            "def add(a: int, b: int) -> int:\n    return a + b\n\n"
            "x: int = add(2, 3)\nprint(x)\n"
        )

        assert 'define i64 @"add"(i64' in llvm_ir
        assert "add i64" in llvm_ir

    def test_recursive_typed_function(self):
        """Recursion through a static signature works (fib)."""
        llvm_ir = _convert(
            "def fib(n: int) -> int:\n"
            "    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n\n"
            "print(fib(10))\n"
        )

        assert 'define i64 @"fib"(i64' in llvm_ir
        assert 'call i64 @"fib"' in llvm_ir

    def test_dynamic_fallback_for_unannotated(self):
        """Unannotated code falls back to the PyObject runtime calls."""
        llvm_ir = _convert("x = 5\ny = 3\nprint(x + y)\n")

        assert 'call {i32, i8*}* @"pyobj_add"' in llvm_ir

    def test_boundary_boxing_for_containers(self):
        """Typed scalars are boxed when stored into containers."""
        llvm_ir = _convert("x: int = 5\nl = [x]\nprint(l)\n")

        assert 'call {i32, i8*}* @"create_int"' in llvm_ir
        assert 'call {i32, i8*}* @"list_append"' in llvm_ir

    def test_range_counter_is_raw_i64(self):
        """for-range loops count in a raw i64 without boxing per iteration."""
        llvm_ir = _convert(
            "total: int = 0\nfor i in range(10):\n    total += i\nprint(total)\n"
        )

        assert (
            'call {i32, i8*}* @"create_int"'
            not in llvm_ir.split('define i32 @"main"')[1]
            .split('call void @"pyobj_print"')[0]
            .rsplit("getelementptr", 1)[0]
            or "phi" in llvm_ir
        )
        assert "icmp slt i64" in llvm_ir

    def test_float_to_int_coercion_panics(self):
        """Assigning an unboxed float to an int variable aborts."""
        llvm_ir = _convert("a: float = 1.5\nb: int = 2\nb = a\nprint(b)\n")

        assert "TypeError: float cannot be used as int" in llvm_ir

    def test_generated_ir_parses(self):
        """Typed output must be valid LLVM assembly."""
        import llvmlite.binding as llvm

        llvm_ir = _convert('x: int = 5\ns = "hi"\nprint(x, s)\n')
        llvm.initialize()
        llvm.parse_assembly(llvm_ir)

    def test_and_or_chain_on_unboxed_bools(self):
        """Short-circuit chains over i1 stay unboxed."""
        llvm_ir = _convert("a: bool = True\nb: bool = False\nprint(a and not b)\n")

        assert "xor i1" in llvm_ir
