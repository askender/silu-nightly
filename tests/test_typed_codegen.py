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

        assert 'define internal i64 @\"add\"(i64' in llvm_ir
        assert "add i64" in llvm_ir

    def test_recursive_typed_function(self):
        """Recursion through a static signature works (fib)."""
        llvm_ir = _convert(
            "def fib(n: int) -> int:\n"
            "    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n\n"
            "print(fib(10))\n"
        )

        assert 'define internal i64 @\"fib\"(i64' in llvm_ir
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
        try:
            llvm.initialize()
        except RuntimeError:
            pass  # llvmlite >= 0.44 initializes automatically
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
        assert 'call void @"rawlist_set"' not in main  # set is inlined too
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

    def test_rawdict_del_statement(self):
        """del d[k] tombstones the entry and shrinks the live count."""
        source = (
            "d: dict[int, int] = {1: 10, 2: 20, 3: 30}\n"
            "del d[2]\n"
            "print(len(d), d[1], d[3])\n"
        )
        llvm_ir = _convert(source)

        assert 'call i64 @"rawdict_del"' in _main_body(llvm_ir)
        assert _run_main(llvm_ir) == "2 10 30\n"

    def test_rawdict_delete_reinsert_churn(self):
        """Delete/reinsert churn exercises tombstone reuse and the
        compacting rehash; contents must match a Python reference."""
        source = (
            "d: dict[int, int] = {}\n"
            "i: int = 0\nwhile i < 60:\n    d[i] = i * 2\n    i += 1\n"
            "i = 0\nwhile i < 40:\n    del d[i]\n    i += 1\n"
            "i = 0\nwhile i < 40:\n    d[i] = i + 1000\n    i += 1\n"
            "total: int = 0\n"
            "i = 0\nwhile i < 60:\n    total += d[i]\n    i += 1\n"
            "print(total, len(d))\n"
        )
        reference = {}
        for i in range(60):
            reference[i] = i * 2
        for i in range(40):
            del reference[i]
        for i in range(40):
            reference[i] = i + 1000
        expected = f"{sum(reference.values())} {len(reference)}\n"

        assert _run_main(_convert(source)) == expected

    def test_rawdict_pop_returns_value(self):
        """d.pop(k) on a raw dict removes the entry and returns its value."""
        source = (
            "d: dict[int, int] = {1: 10, 2: 20}\n"
            "v: int = d.pop(1)\n"
            "print(v, len(d), d[2])\n"
        )
        llvm_ir = _convert(source)

        assert 'call i64 @"rawdict_del"' in _main_body(llvm_ir)
        assert _run_main(llvm_ir) == "10 1 20\n"

    def test_rawdict_pop_float_value(self):
        """dict[int, float].pop bitcasts the removed bits back to f64."""
        source = (
            "f: dict[int, float] = {1: 0.5, 2: 2.5}\n"
            "v: float = f.pop(2)\n"
            "print(v, len(f))\n"
        )

        assert _run_main(_convert(source)) == "2.5 1\n"

    def test_rawdict_boxing_after_delete(self):
        """print(d) after del walks the index table, so deleted entries
        stay deleted across the PyObject boundary."""
        source = (
            "d: dict[int, int] = {1: 10, 2: 20, 3: 30}\n"
            "del d[2]\n"
            "print(d)\n"
        )

        assert _run_main(_convert(source)) == "{1: 10, 3: 30}\n"
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_dynamic_dict_del_statement(self):
        """Unannotated dicts delete through the boxed runtime."""
        source = 'd = {1: "a", 2: "b"}\ndel d[1]\nprint(d, len(d))\n'

        assert _run_main(_convert(source)) == "{2: 'b'} 1\n"
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawdict_get_pop_setdefault_clear(self):
        """The full raw dict method set runs natively (no boxing the
        whole dict per call), including two-arg defaults."""
        source = (
            "d: dict[int, int] = {1: 10, 2: 20}\n"
            "print(d.get(1), d.get(9), d.get(9, 99))\n"
            "print(d.pop(1), d.pop(9, -1))\n"
            "print(d.setdefault(3, 30), d.setdefault(3, 99))\n"
            "print(len(d))\n"
            "d.clear()\n"
            "print(len(d), 1 in d)\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i64 @"rawdict_get_or"' in main
        assert 'call i64 @"rawdict_pop_or"' in main
        assert 'call i64 @"rawdict_setdefault"' in main
        assert 'call void @"rawdict_clear"' in main
        assert 'call {i32, i8*}* @"rawdict_to_pydict' not in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawdict_float_methods(self):
        """dict[int, float] methods bitcast values through the raw
        runtime the same way subscripts do."""
        source = (
            "f: dict[int, float] = {1: 0.5}\n"
            "print(f.get(2, 9.5), f.setdefault(2, 1.5), f.pop(1))\n"
        )

        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawlist_clear(self):
        """list.clear() drops elements natively and keeps the list."""
        source = (
            "l: list[int] = [1, 2, 3]\n"
            "l.clear()\n"
            "print(len(l))\n"
            "l.append(4)\n"
            "print(l[0], len(l))\n"
        )

        assert _run_main(_convert(source)) == _run_interpreter(source)


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


class TestRawStr:
    def test_annotated_str_is_raw(self):
        """s: str builds a raw {len, cap, data} slot; appends skip the
        PyObject runtime entirely."""
        llvm_ir = _convert(
            's: str = "a"\ns = s + "b"\ns += "c"\n'
            "t: str = s\nprint(s, t, len(s))\n"
        )
        main = _main_body(llvm_ir)

        assert 'define void @"rawstr_append"' in llvm_ir
        assert 'call void @"rawstr_append"' in main
        assert 'call {i32, i8*}* @"pyobj_add"' not in main
        assert '@"s" = global i8*' in llvm_ir

    def test_str_semantics_execute(self):
        """Concat, aug-append, aliasing, len, truthiness and compare all
        match the interpreter."""
        source = (
            's: str = "a"\n'
            's = s + "b"\n'
            's += "c"\n'
            "t: str = s\n"
            's += "X"\n'
            "print(t, s, len(s))\n"
            "print(s == t, s != t)\n"
            'empty: str = ""\n'
            "if not empty:\n"
            '    print("falsy")\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_inferred_str_avoids_pyobj_add(self):
        """u = "" then u = u + "z" in a loop: the pre-pass promotes u to
        a raw slot and the self-append grows in place (amortized O(1),
        was quadratic PyObject concat)."""
        llvm_ir = _convert(
            'u = ""\ni: int = 0\nwhile i < 5:\n'
            '    u = u + "z"\n    i += 1\nprint(u, len(u))\n'
        )
        main = _main_body(llvm_ir)

        assert '@"u" = global i8*' in llvm_ir
        assert 'call void @"rawstr_append"' in main
        assert 'call {i32, i8*}* @"pyobj_add"' not in main
        assert _run_main(llvm_ir) == "zzzzz 5\n"

    def test_str_kind_conflict_keeps_dynamic(self):
        """x = "a" then x = 5 rebinds to int: the name must stay on
        PyObject storage."""
        llvm_ir = _convert('x = "a"\nx = 5\nprint(x)\n')
        main = _main_body(llvm_ir)

        assert 'call {i32, i8*}* @"create_int"' in main
        assert '@x = global i8*' not in llvm_ir

    def test_self_append_concatenates(self):
        """s = s + s must take the fresh-concat path (append's realloc
        would move the buffer under its own source)."""
        source = (
            's = "ab"\ni: int = 0\nwhile i < 3:\n'
            "    s = s + s\n    i += 1\nprint(s, len(s))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawstr_index_is_native(self):
        """s[i] reads one byte in place; the old path panicked with
        'object is not subscriptable' after boxing."""
        source = (
            's: str = "hello"\n'
            "a: str = s[1]\nb: str = s[-1]\n"
            "print(a, b, len(a))\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i8* @"rawstr_char_at"' in main
        assert 'call {i32, i8*}* @"pyobj_subscript"' not in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawstr_slice_is_native(self):
        """s[lo:hi] clamps bounds Python-style without boxing."""
        source = (
            's: str = "hello world"\n'
            "print(s[0:5], s[6:], s[:5], s[-5:], s[3:2])\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i8* @"rawstr_slice"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawstr_stepped_slice_falls_back(self):
        """s[::2] / s[::-1] go through the boxed slice helper and keep
        Python semantics (both step directions)."""
        source = (
            's: str = "hello world"\n'
            "print(s[::2], s[::-1], s[4:0:-1])\n"
        )
        llvm_ir = _convert(source)

        assert 'call {i32, i8*}* @"pyobj_str_slice"' in _main_body(llvm_ir)
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawstr_contains(self):
        """sub in s scans bytes; the empty needle is always contained."""
        source = (
            's: str = "hello world"\n'
            'print("wor" in s, "xyz" in s, "xyz" not in s)\n'
            'print("" in s, "hello world!" not in s)\n'
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i1 @"rawstr_contains"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawstr_for_loop(self):
        """for ch in s iterates bytes natively; the loop variable is a
        1-byte rawstr and never touches the PyObject runtime."""
        source = (
            's: str = "hello"\n'
            "count: int = 0\n"
            "for ch in s:\n"
            '    if ch == "l":\n'
            "        count += 1\n"
            "print(count)\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call void @"rawstr_free"' in main  # per-char slot drop
        assert 'call {i32, i8*}* @"list_length"' not in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_contains_rawdict_and_rawlist(self):
        """k in d probes the index table; x in l scans elements - both
        without boxing the container."""
        source = (
            "d: dict[int, int] = {1: 10, 2: 20}\n"
            "print(1 in d, 3 in d, 3 not in d)\n"
            "l: list[int] = [5, 6, 7]\n"
            "print(6 in l, 9 in l)\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i1 @"rawdict_has"' in main
        assert 'call i1 @"rawlist_contains_bits"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_contains_dynamic_fallback(self):
        """Unannotated containers route to pyobj_contains."""
        source = (
            'd = {1: "a"}\nprint(1 in d, 2 in d)\n'
            'l = ["x", "y"]\nprint("x" in l, "z" in l)\n'
            's = "abc"\nprint("b" in s)\n'
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i1 @"pyobj_contains"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rawstr_code_point_semantics(self):
        """len, indexing, negative indexing and slicing all count code
        points, matching the interpreter on multi-byte text."""
        source = (
            's: str = "你好世界"\n'
            "print(len(s), s[1], s[-1], s[1:3], s[:2], s[3:])\n"
            't: str = "hi 你好"\n'
            "print(len(t), t[3], t[-2:])\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawstr_code_point_iteration(self):
        """for ch in s walks code points (a byte-offset loop under the
        hood), and appended strings keep their code point count."""
        source = (
            's: str = "你好世界"\n'
            "count: int = 0\n"
            "for ch in s:\n"
            '    if ch == "好":\n'
            "        count += 1\n"
            "print(count)\n"
            'u: str = ""\n'
            "i: int = 0\n"
            "while i < 3:\n"
            '    u = u + "你"\n'
            "    i += 1\n"
            "print(u, len(u), u[2])\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawstr_utf8_equality_and_contains(self):
        """Byte-wise eq/cmp/contains already equal code point semantics
        on UTF-8 - pinned down for multi-byte text."""
        source = (
            's: str = "你好世界"\n'
            'print(s == "你好世界", s != "你好", s < "你好吗")\n'
            'print("好世" in s, "吗" in s, "" in s)\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawstr_reassign_drops_old_buffer(self):
        """t = "ab" + "cd" in a loop: the slot's previous buffer is
        dropped on every overwrite (Rust drop), so a reassignment loop
        runs in constant memory (was ~160 bytes leaked per iteration)."""
        source = (
            't: str = "x"\n'
            "i: int = 0\n"
            "while i < 100:\n"
            '    t = "ab" + "cd"\n'
            "    i += 1\n"
            "print(t, len(t))\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        # no pyobj round-trip for const-str concat, and both the concat
        # temporaries and the overwritten slot buffers are freed
        assert 'call {i32, i8*}* @"pyobj_add"' not in main
        assert 'call i8* @"rawstr_concat"' in main
        assert main.count('call void @"rawstr_free"') >= 2
        assert _run_main(llvm_ir) == "abcd 4\n"

    def test_rawstr_alias_assignment_still_copies(self):
        """t = s must copy (exclusive ownership): mutating t afterwards
        leaves s alone, and both buffers get dropped independently."""
        source = (
            's: str = "keep"\n'
            "t: str = s\n"
            't = t + "X"\n'
            "print(s, t)\n"
            'u: str = "a"\n'
            'u = "b" + u\n'
            "print(u)\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_rawstr_self_concat_fresh_path(self):
        """s = s + s takes the concat path and drops the old buffer
        only after the new one exists (no use-after-free)."""
        source = (
            's: str = "ab"\n'
            "i: int = 0\n"
            "while i < 3:\n"
            "    s = s + s\n"
            "    i += 1\n"
            "print(s, len(s))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_str_function_boundary(self):
        """rawstr params are copied at the call boundary and rawstr
        returns are copied at return, so callees cannot alias callers."""
        source = (
            "def shout(name: str) -> str:\n"
            '    return name + "!"\n'
            's: str = "bob"\n'
            "t: str = shout(s)\n"
            't += "?"\n'
            "print(s, t)\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_dynamic_str_compare_matches_python(self):
        """str <op> str for every comparison predicate used to return
        None for ordering ops (eq/ne only); now matches Python."""
        source = (
            'print("abc" == "abd", "abc" != "abd")\n'
            'print("abc" < "abd", "abd" < "abc")\n'
            'print("abc" <= "abc", "abc" >= "abc")\n'
            'print("" < "a", "a" < "")\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestCrossFunctionInference:
    def test_unannotated_numeric_function_gets_raw_abi(self):
        """def add(a, b): return a + b with all-int call sites promotes
        to i64 params and i64 return - no PyObject boxing anywhere."""
        llvm_ir = _convert(
            "def add(a, b):\n    return a + b\n\nprint(add(2, 3))\n"
        )

        assert 'define internal i64 @\"add\"(i64' in llvm_ir
        main = _main_body(llvm_ir)
        assert 'call i64 @"add"(i64 2, i64 3)' in main
        assert _run_main(llvm_ir) == "5\n"

    def test_unannotated_str_function_gets_raw_abi(self):
        """A str-concatenating helper infers rawstr param and return."""
        llvm_ir = _convert(
            'def greet(name):\n    return "hi " + name\n\n'
            'print(greet("silu"))\n'
        )

        assert 'define internal i8* @\"greet\"(i8*' in llvm_ir
        assert _run_main(llvm_ir) == "hi silu\n"

    def test_conflicting_call_sites_stay_dynamic(self):
        """mixed(1, 2) and mixed("x", "y"): one name, two kinds - the
        function must keep the PyObject ABI (Python rebinding)."""
        source = (
            "def mixed(a, b):\n    return a + b\n\n"
            'print(mixed(1, 2), mixed("x", "y"))\n'
        )
        llvm_ir = _convert(source)

        assert 'define internal {i32, i8*}* @"mixed"' in llvm_ir
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_rebound_param_stays_dynamic(self):
        """x = x + 1 inside the body rebinding-checks the parameter:
        call-site kinds alone are not proof enough."""
        source = (
            "def bump(x):\n    x = x + 1\n    return x\n\n"
            "print(bump(10))\n"
        )
        llvm_ir = _convert(source)

        assert 'define internal {i32, i8*}* @"bump"' in llvm_ir
        assert _run_main(llvm_ir) == "11\n"

    def test_dynamic_return_with_proven_raw_params(self):
        """A side-effecting helper (no return) keeps the boxed return
        but its proven parameter still arrives as a raw i64."""
        source = "def show(x):\n    print(x + 1)\n\nshow(5)\n"
        llvm_ir = _convert(source)

        assert 'define internal {i32, i8*}* @\"show\"(i64' in llvm_ir
        assert _run_main(llvm_ir) == "6\n"

    def test_inferred_return_kind_reaches_caller(self):
        """y = add(2, 3) learns i64 from the inferred signature, so the
        caller's arithmetic on y skips the PyObject runtime too."""
        llvm_ir = _convert(
            "def add(a, b):\n    return a + b\n\n"
            "y = add(2, 3)\nprint(y * 4)\n"
        )
        main = _main_body(llvm_ir)

        assert 'call {i32, i8*}* @"pyobj_mul"' not in main
        assert _run_main(llvm_ir) == "20\n"

    def test_rawlist_params_without_return_annotation(self):
        """def multiply(v: list[float], out: list[float]): ... has no
        return annotation: dynamic return ABI, but the raw list params
        must still get i8* (spectral-norm hits exactly this shape)."""
        source = (
            "def scale(v: list[float], out: list[float]):\n"
            "    out[0] = v[0] * 2.0\n\n"
            "src: list[float] = [1.5]\n"
            "dst: list[float] = [0.0]\n"
            "scale(src, dst)\n"
            "print(dst[0])\n"
        )
        llvm_ir = _convert(source)

        assert 'define internal {i32, i8*}* @\"scale\"(i8*' in llvm_ir
        assert _run_main(llvm_ir) == "3.0\n"

    def test_recursion_stays_conservative(self):
        """fib calls itself with n - 1, which the module-level resolver
        cannot see: the function keeps the dynamic ABI and still
        computes correctly."""
        source = (
            "def fib(n):\n"
            "    if n < 2:\n        return n\n"
            "    return fib(n - 1) + fib(n - 2)\n\n"
            "print(fib(15))\n"
        )

        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestRawStrDict:
    def test_str_key_annotation_is_raw(self):
        """dict[str, int] uses the str-key raw table, not PyObject."""
        llvm_ir = _convert(
            'd: dict[str, int] = {"a": 1}\nd["b"] = 2\n'
            'x: int = d["a"]\nprint(x, len(d))\n'
        )
        main = _main_body(llvm_ir)

        assert 'define void @"rawdict_str_set"' in llvm_ir
        assert 'call void @"rawdict_str_set"' in main
        assert 'call i64 @"rawdict_str_get"' in main
        assert 'call void @"pyobj_subscript_set"' not in main
        assert _run_main(llvm_ir) == "1 2\n"

    def test_str_key_full_semantics(self):
        """insert/overwrite/get/pop/setdefault/del/clear/in/len all
        match the interpreter, with rehashes forced by churn."""
        source = (
            'd: dict[str, int] = {"apple": 1, "banana": 2}\n'
            'd["cherry"] = 3\n'
            'print(d["banana"], len(d), "apple" in d, "fig" in d)\n'
            'print(d.get("fig", 99), d.get("apple"))\n'
            'print(d.pop("cherry"), len(d))\n'
            'd["apple"] = 100\n'
            'print(d["apple"])\n'
            'del d["banana"]\n'
            'print(len(d), "banana" in d)\n'
            'print(d.setdefault("fig", 7), d.setdefault("fig", 8))\n'
            "i: int = 0\n"
            "while i < 2000:\n"
            '    d["k" + str(i % 300)] = i\n'
            "    i += 1\n"
            "print(len(d))\n"
            'del d["k7"]\n'
            'print(len(d), d.get("k7", -1))\n'
            "d.clear()\n"
            "print(len(d))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_str_key_float_values(self):
        """dict[str, float] bitcasts values like the int-key family."""
        source = (
            'f: dict[str, float] = {"a": 0.5}\n'
            'f["b"] = 2.5\n'
            'f["a"] += 1.0\n'
            'print(f["a"], f["b"], len(f))\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_ascii_index_slice_fast_path(self):
        """byte_len == cp_len (pure ASCII) skips the code point walk
        entirely: s[i] and s[a:b] become O(1)/O(k) via a branch."""
        source = (
            's: str = "hello world"\n'
            "print(s[1], s[7:9])\n"
            't: str = "你好"\n'
            "print(t[1], t[0:1])\n"
        )
        llvm_ir = _convert(source)
        # the ascii/walk branch blocks exist in both functions
        assert 'rawstr_char_at' in llvm_ir
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_str_key_boxing_boundary(self):
        """print(d) on a str-key raw dict boxes through the table walk
        (deleted keys stay deleted)."""
        source = (
            'd: dict[str, int] = {"a": 1, "b": 2}\n'
            'del d["a"]\n'
            "print(len(d), d.get(\"a\", -1), d[\"b\"])\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestRawStrList:
    def test_str_list_annotation_is_raw(self):
        """list[str] uses the str-element raw array, not PyObject."""
        llvm_ir = _convert(
            'l: list[str] = ["a", "b"]\nl.append("c")\n'
            'x: str = l[0]\nprint(len(l), x, l[-1])\n'
        )
        main = _main_body(llvm_ir)

        assert 'define i64 @"rawlist_str_push"' in llvm_ir
        assert 'call i64 @"rawlist_str_push"' in main
        assert 'call i8* @"rawlist_str_get"' in main
        assert 'call void @"list_append"' not in main
        assert _run_main(llvm_ir) == _run_interpreter(
            'l: list[str] = ["a", "b"]\nl.append("c")\n'
            'x: str = l[0]\nprint(len(l), x, l[-1])\n'
        )

    def test_str_list_full_semantics(self):
        """append/index/negative/set/pop/in/for/clear/boxing all match
        the interpreter; reads copy (mutation isolation)."""
        source = (
            'words: list[str] = ["alpha", "beta"]\n'
            'words.append("gamma")\n'
            'print(len(words), words[0], words[-1])\n'
            "w: str = words[1]\n"
            'words[1] = "BETA"\n'
            "print(w, words[1])\n"
            'print("beta" in words, "BETA" in words)\n'
            "p: str = words.pop()\n"
            "print(p, len(words))\n"
            "total: int = 0\n"
            "for x in words:\n"
            "    total += len(x)\n"
            "print(total)\n"
            "print(words)\n"
            "words.clear()\n"
            "print(len(words))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_str_list_inferred_from_literal(self):
        """u = ["a", "b"] with every element a str constant infers the
        raw str list; a mixed literal stays boxed."""
        llvm_ir = _convert('u = ["a", "b"]\nu.append("c")\nprint(u[0])\n')
        main = _main_body(llvm_ir)

        assert 'call i64 @"rawlist_str_push"' in main
        assert _run_main(llvm_ir) == _run_interpreter(
            'u = ["a", "b"]\nu.append("c")\nprint(u[0])\n'
        )

    def test_str_list_element_as_dict_key(self):
        """d[l[i]] uses the borrowed pointer (no copy at the key)."""
        source = (
            'd: dict[str, int] = {}\n'
            'l: list[str] = ["k0", "k1", "k2"]\n'
            "i: int = 0\n"
            "while i < 3:\n"
            "    d[l[i]] = d.get(l[i], 0) + i\n"
            "    i += 1\n"
            'print(len(d), d["k1"])\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_str_list_multibyte(self):
        """CJK elements keep code point semantics end to end."""
        source = (
            'l: list[str] = ["你好", "世界"]\n'
            "print(len(l), l[0], l[1][1])\n"
            'l[1] = "斯路"\n'
            "print(l[1], len(l[1]))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestCharCompareFusion:
    def test_char_vs_const_never_allocates(self):
        """s[i] == "x" fuses to rawstr_at_eq_cstr: no rawstr per
        comparison (the old path allocated 2 objects per check). The
        for-ch loop variable has its own zero-copy path already."""
        source = (
            's: str = "hello world"\n'
            "count: int = 0\n"
            "i: int = 0\n"
            "while i < len(s):\n"
            '    if s[i] == "l":\n'
            "        count += 1\n"
            "    i += 1\n"
            "print(count)\n"
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i1 @"rawstr_at_eq_cstr"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_char_ordering_vs_const(self):
        """s[i] < "m" and friends fuse to rawstr_at_cmp_cstr with the
        direction flipped when the constant is on the left."""
        source = (
            's: str = "hello"\n'
            'print(s[0] < "m", s[1] >= "m", "a" < s[2], "z" <= s[0])\n'
            't: str = "abc"\n'
            'print(t[1] < "b", t[1] <= "b", t[1] > "b", t[1] >= "b")\n'
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call i64 @"rawstr_at_cmp_cstr"' in main
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_char_compare_semantics_match(self):
        """== and != on both sides, multi-byte text, negative and
        out-of-range indices all keep Python semantics."""
        source = (
            's: str = "你好世界"\n'
            'print(s[1] == "好", "好" == s[1], s[0] != "你", s[-1] == "界")\n'
            't: str = "abc"\n'
            'print(t[0] == "a", t[2] == "z", "b" != t[1])\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestStrKeyViews:
    def test_slice_key_is_a_view(self):
        """d[s[a:b]] never materializes the slice: rawstr_slice_parts
        hands the dict a borrowed (data, len) window."""
        source = (
            'd: dict[str, int] = {}\n'
            's: str = "aaxbbxcc"\n'
            "i: int = 0\n"
            "while i < 8:\n"
            "    d[s[i:i + 2]] = i\n"
            "    i += 2\n"
            'print(len(d), d["aa"], d["cc"])\n'
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        assert 'call {i8*, i64} @"rawstr_slice_parts"' in main
        assert 'call i8* @"rawstr_slice"' not in main
        expected = (
            "d: dict[str, int] = {}\n"
            's: str = "aaxbbxcc"\n'
            "i: int = 0\n"
            "while i < 8:\n"
            "    d[s[i:i + 2]] = i\n"
            "    i += 2\n"
            "print(len(d), d.get(\"aa\", -1), d.get(\"cc\", -1))\n"
        )
        assert _run_main(llvm_ir) == _run_interpreter(expected)

    def test_boxed_str_key_is_viewed_not_converted(self):
        """A PyObject str key is viewed through its buffer (tag-checked
        stack view), skipping pystr_to_rawstr entirely."""
        source = (
            'd: dict[str, int] = {"a": 1}\n'
            'k = "a"\n'
            'd[k] = d.get(k, 0) + 1\n'
            'print(d["a"])\n'
        )
        llvm_ir = _convert(source)
        main = _main_body(llvm_ir)

        # the only conversion is k's own initialization; the d[k]
        # operations view the rawstr slot directly
        assert main.count('call i8* @"pystr_to_rawstr"') == 1
        assert _run_main(llvm_ir) == _run_interpreter(source)

    def test_slice_view_nonascii_matches(self):
        """View keys keep code point semantics on multi-byte text."""
        source = (
            'd: dict[str, int] = {}\n'
            's: str = "你好世界你好"\n'
            'd[s[0:2]] = 1\n'
            'd[s[4:6]] = 2\n'
            'print(len(d), d["你好"], d.get("世界", -1))\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestDictEntryFusion:
    def test_counting_idiom_uses_entry(self):
        """d[k] = d.get(k, 0) + v compiles to one probe via
        rawdict_*_entry (Rust's entry().or_insert), not get+set."""
        for annotation, fn in (
            ("dict[str, int]", "rawdict_str_entry"),
            ("dict[int, int]", "rawdict_int_entry"),
        ):
            llvm_ir = _convert(
                f"d: {annotation} = {{}}\n"
                "i: int = 0\n"
                "while i < 100:\n"
                + (
                    '    k: str = "k" + str(i % 10)\n'
                    if annotation.startswith("dict[str")
                    else "    k: int = i % 10\n"
                )
                + "    d[k] = d.get(k, 0) + 1\n"
                "    i += 1\n"
                "print(len(d))\n"
            )
            main = _main_body(llvm_ir)
            assert f'call i8* @"{fn}"' in main

    def test_entry_idiom_matches_interpreter(self):
        source = (
            'd: dict[str, int] = {}\n'
            "i: int = 0\n"
            "while i < 1000:\n"
            '    w: str = "k" + str(i % 50)\n'
            "    d[w] = d.get(w, 0) + 1\n"
            "    i += 1\n"
            'print(len(d), d["k7"])\n'
            "e: dict[int, float] = {}\n"
            "i = 0\n"
            "while i < 100:\n"
            "    e[i % 10] = e.get(i % 10, 0.5) * 2.0\n"
            "    i += 1\n"
            "print(len(e), e[3])\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)

    def test_plain_set_still_plain(self):
        """d[k] = v (no get idiom) must NOT use entry()."""
        llvm_ir = _convert(
            'd: dict[str, int] = {}\nd["a"] = 5\nprint(d["a"])\n'
        )
        main = _main_body(llvm_ir)
        assert "rawdict_str_entry" not in main
        assert 'call void @"rawdict_str_set"' in main


class TestBoxedDictFullTable:
    def test_get_missing_on_full_boxed_dict(self):
        """dict_set used to grow only at 100% load, so a read-side
        probe on a full table never found an empty slot and spun
        forever. Repro: variable str keys, get+set in one statement."""
        source = (
            "vocab = []\n"
            "i = 0\n"
            "while i < 100:\n"
            '    vocab.append("w" + str(i))\n'
            "    i += 1\n"
            "d = {}\n"
            "i = 0\n"
            "while i < 300:\n"
            "    w = vocab[(i * 48271 + 11) % 100]\n"
            "    d[w] = d.get(w, 0) + 1\n"
            "    i += 1\n"
            'print(len(d), d["w5"])\n'
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestStrConversion:
    def test_str_of_scalars_matches_interpreter(self):
        """str(x) works for int/float/bool/str and coerces into rawstr
        context - it used to return None and crash the rawstr
        conversion on concat."""
        source = (
            "x: int = 42\n"
            's: str = "n" + str(x)\n'
            "print(s)\n"
            "print(str(1.5), str(True), str(False), str(None))\n"
            'l: list[str] = []\n'
            'l.append("a" + str(1))\n'
            "print(l[0])\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


class TestRawStrScopeDrops:
    def test_function_locals_and_params_dropped_at_exit(self):
        """A function's owned rawstr slots (params included) are freed
        on every return path - Rust scope-exit drop."""
        llvm_ir = _convert(
            "def shout(name):\n"
            '    t: str = "hi " + name\n'
            '    t = t + "!"\n'
            "    return t\n\n"
            'print(shout("silu"))\n'
        )
        shout_body = llvm_ir.split('define internal i8* @"shout"')[1]

        assert shout_body.count('call void @"rawstr_free"') >= 2
        assert _run_main(llvm_ir) == "hi silu!\n"

    def test_annotated_call_args_infer_raw_abi(self):
        """shout(n) with n: str at module level: the resolver must see
        annotated module names, not just inferred ones."""
        llvm_ir = _convert(
            "def shout(name):\n"
            '    return "hi " + name\n\n'
            'n: str = "x"\n'
            "print(shout(n))\n"
        )

        assert 'define internal i8* @\"shout\"(i8*' in llvm_ir
        assert _run_main(llvm_ir) == "hi x\n"

    def test_discarded_call_result_is_dropped(self):
        """shout(n) as an expression statement: the returned rawstr is
        a temporary and gets freed right after the call."""
        llvm_ir = _convert(
            "def shout(name):\n"
            '    return "hi " + name\n\n'
            'n: str = "x"\n'
            "i: int = 0\n"
            "while i < 3:\n"
            "    shout(n)\n"
            "    i += 1\n"
            'print("done")\n'
        )
        main = _main_body(llvm_ir)

        assert 'call void @"rawstr_free"' in main
        assert _run_main(llvm_ir) == "done\n"

    def test_assigned_call_result_is_not_dropped(self):
        """t = shout(n): the slot owns the result - freeing it would
        be a use-after-free."""
        source = (
            "def shout(name):\n"
            '    return "hi " + name\n\n'
            'n: str = "x"\n'
            "t: str = shout(n)\n"
            "print(t, len(t))\n"
        )
        assert _run_main(_convert(source)) == _run_interpreter(source)


def _run_interpreter(source: str) -> str:
    """Reference output from the tree-walking interpreter."""
    import os
    import subprocess
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile(
        "w", suffix=".si", delete=False
    ) as handle:
        handle.write(source)
        path = handle.name
    try:
        result = subprocess.run(
            [sys.executable, "-m", "silu", "interpret", path],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    finally:
        os.unlink(path)
