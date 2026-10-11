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

    def test_rawlist_int_annotation(self):
        """list[int] builds a raw i64 container, no boxing on push/get."""
        llvm_ir = _convert(
            "l: list[int] = []\ni: int = 0\n"
            "while i < 5:\n    l.append(i * 10)\n    i += 1\n"
            "x: int = l[2]\nl[1] = 7\n"
            "total: int = 0\nfor v in l:\n    total += v\n"
            "print(x, len(l), total)\n"
        )
        main = _main_body(llvm_ir)

        assert 'define i8* @"rawlist_new"' in llvm_ir
        assert 'call i64 @"rawlist_push"' in main
        assert 'rawlist' in llvm_ir  # get is now inlined
        assert 'call void @"rawlist_set"' in main
        assert 'call {i32, i8*}* @"list_append"' not in main

    def test_rawlist_float_annotation(self):
        """list[float] stores raw doubles."""
        llvm_ir = _convert(
            "f: list[float] = [1.5, 2.5]\nf.append(3.5)\nprint(f[0] + f[2])\n"
        )
        main = _main_body(llvm_ir)

        # the fadd itself is raw; create_float only appears once, at the
        # print boundary (boxing the result for display)
        assert "fadd double" in main
        assert main.count('call {i32, i8*}* @"create_float"') == 1

    def test_mixed_list_still_dynamic(self):
        """Plain list annotations keep PyObject storage (mixed types)."""
        llvm_ir = _convert('m: list = [1, "x"]\nprint(m)\n')

        assert 'call {i32, i8*}* @"list_append"' in llvm_ir

    def test_silu_checks_env_disables_overflow(self):
        """SILU_CHECKS=0 emits plain add instead of the checked intrinsic."""
        import os

        from silu.ir_generator import SiluIRGenerator as Gen

        source = "a: int = 1\nb: int = 2\nprint(a + b)\n"
        ir_json = json.dumps(Gen().visit(ast.parse(source)))
        old = os.environ.get("SILU_CHECKS")
        try:
            os.environ["SILU_CHECKS"] = "0"
            unchecked = _main_body(TypedCodegen().convert(ir_json))
            os.environ["SILU_CHECKS"] = "1"
            checked = _main_body(TypedCodegen().convert(ir_json))
        finally:
            if old is None:
                os.environ.pop("SILU_CHECKS", None)
            else:
                os.environ["SILU_CHECKS"] = old

        assert "with.overflow" not in unchecked
        assert "add i64" in unchecked
        assert "with.overflow" in checked

    def test_rawlist_mixed_int_vars_safe(self):
        """for-range over a previously-dynamic variable keeps it dynamic."""
        llvm_ir = _convert(
            "i = \"init\"\nfor i in range(3):\n    pass\nprint(i)\n"
        )
        main = _main_body(llvm_ir)

        # counter is raw, the named variable gets a boxed copy per loop
        assert "phi i64" in llvm_ir or "icmp slt i64" in llvm_ir
        assert 'call {i32, i8*}* @"create_int"' in main


def _run_main(llvm_ir: str) -> str:
    """Execute the module through MCJIT and capture stdout."""
    import ctypes
    import os
    import tempfile

    from llvmlite import binding as llvm

    module = llvm.parse_assembly(llvm_ir)
    module.verify()
    target = llvm.Target.from_default_triple()
    engine = llvm.create_mcjit_compiler(
        module, target.create_target_machine()
    )
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


class TestRawDict:
    def test_rawdict_int_annotation_is_raw(self):
        """dict[int, int] uses the machine-word dict, not PyObject slots."""
        llvm_ir = _convert(
            "d: dict[int, int] = {1: 2}\nd[3] = 4\n"
            "x: int = d[1]\nd[1] = 10\nprint(x, len(d))\n"
        )
        main = _main_body(llvm_ir)

        assert 'define i8* @"rawdict_new"' in llvm_ir
        assert "call void @\"rawdict_set\"" in main
        assert 'call i64 @"rawdict_get"' in main
        assert 'call void @"pyobj_subscript_set"' not in main

    def test_rawdict_executes_rehash_and_len(self):
        """2000 inserts over 100 keys force several rehashes; sums match
        a Python reference and len reads the live count."""
        source = (
            "d: dict[int, int] = {}\n"
            "i: int = 0\nwhile i < 2000:\n    d[i % 100] = i\n    i += 1\n"
            "total: int = 0\n"
            "i = 0\nwhile i < 100:\n    total += d[i]\n    i += 1\n"
            "print(total, len(d))\n"
        )
        reference = {}
        for i in range(2000):
            reference[i % 100] = i
        expected = f"{sum(reference.values())} {len(reference)}\n"

        assert _run_main(_convert(source)) == expected

    def test_rawdict_float_annotation(self):
        """dict[int, float] stores values as f64 bit patterns."""
        llvm_ir = _convert(
            "f: dict[int, float] = {1: 0.5}\nf[2] = 2.5\nf[1] += 10.0\n"
            "print(f[1], f[2], len(f))\n"
        )
        main = _main_body(llvm_ir)

        assert "call void @\"rawdict_set\"" in main
        assert _run_main(llvm_ir) == "10.5 2.5 2\n"

    def test_plain_dict_still_dynamic(self):
        """Unparameterized dict annotations keep PyObject storage."""
        llvm_ir = _convert('d: dict = {}\nd[1] = "x"\nprint(d)\n')

        assert 'call void @"pyobj_subscript_set"' in _main_body(llvm_ir)


class TestLenWithoutBoxing:
    def test_len_on_rawlist_reads_length_field(self):
        """len(list[int]) must not materialize a boxed copy (nbody's
        advance() used to allocate every element just to ask for len)."""
        llvm_ir = _convert(
            "l: list[int] = [1, 2, 3]\nn: int = len(l)\nprint(n)\n"
        )
        main = _main_body(llvm_ir)

        assert 'call i64 @"rawlist_len"' in main
        assert 'call {i32, i8*}* @"rawlist_to_pylist"' not in main
        assert 'call {i32, i8*}* @"pyobj_len"' not in main

    def test_len_on_rawdict_reads_count_field(self):
        llvm_ir = _convert(
            "d: dict[int, int] = {5: 1, 6: 2}\nprint(len(d))\n"
        )
        main = _main_body(llvm_ir)

        assert 'call {i32, i8*}* @"pyobj_len"' not in main
        assert _run_main(llvm_ir) == "2\n"


class TestInferredScalarKinds:
    def test_consistent_unannotated_assignment_is_unboxed(self):
        """zr2 = z_re * z_re with annotated z_re: the target takes the
        raw double slot (mandelbrot's inner loop malloc'd per iteration
        before inference)."""
        llvm_ir = _convert(
            "z_re: float = 0.5\nzr2 = z_re * z_re\nzi2 = z_re * z_re\n"
            "i: int = 0\nwhile i < 3:\n"
            "    zr2 = zr2 + zi2\n    i += 1\n"
            "print(zr2)\n"
        )
        main = _main_body(llvm_ir)

        assert '@"zr2" = global double' in llvm_ir
        assert '@"zi2" = global double' in llvm_ir
        # the only boxing is the print() display boundary
        assert main.count('call {i32, i8*}* @"create_float"') == 1

    def test_kind_conflict_keeps_dynamic(self):
        """x = 7 then x = x / 2 rebinds to float: the name must stay on
        PyObject storage so both types flow."""
        llvm_ir = _convert('x = 7\nx = x / 2\nprint(x)\n')
        main = _main_body(llvm_ir)

        assert 'call {i32, i8*}* @"create_int"' in main
        assert '@x = global double' not in llvm_ir

    def test_function_local_shadows_module_global(self):
        """A function declaring the same name as an inferred module
        variable must not clobber the caller's counter (nbody hung in an
        infinite loop when advance()'s local i reused the global slot)."""
        source = (
            "i = 0\n"
            "def bump() -> int:\n"
            "    i: int = 5\n"
            "    while i < 8:\n"
            "        i += 1\n"
            "    return i\n"
            "j = 0\n"
            "while j < 3:\n"
            "    bump()\n"
            "    j += 1\n"
            "print(i, j)\n"
        )

        assert _run_main(_convert(source)) == "0 3\n"
