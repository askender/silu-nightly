"""Statically-typed LLVM code generation for Silu (no PyObject boxing).

Static type annotations drive the representation:

    int   -> i64 on the stack
    float -> double on the stack
    bool  -> i1 on the stack
    str / list / dict / unannotated -> PyObject* (the dynamic runtime)

Unannotated names stay on PyObject storage unless a conservative
pre-pass proves that every assignment to the name in one scope yields
the same raw scalar kind (literals, annotated names, and outer kinds
only - no method calls, no cross-scope analysis); any conflict keeps
the dynamic slot so rebinding a name to another type still works.
Expression kinds propagate by Python's own numeric semantics
(int+float promotes to float, ``/`` always yields float, range
variables are always int) - that is semantic propagation, not
guesswork. Values cross between the static and dynamic worlds at
explicit boundaries (print, containers, dynamic variables and calls)
through box/unbox steps.

Arithmetic follows the project panic policy: i64 add/sub/mul use the
llvm.s*.with.overflow intrinsics and division/modulo check for zero
divisors; both abort with a message instead of failing silently.

Select this backend with SILU_CODEGEN=typed (the default); set
SILU_CODEGEN=dynamic to restore the fully-dynamic PyObject backend.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from llvmlite import ir

from .silu_ir_to_llvm import SiluToLLVMConverter

I64 = "i64"
F64 = "f64"
I1 = "i1"
OBJ = "obj"

ANNOTATION_KINDS = {"int": I64, "float": F64, "bool": I1}
RAWLIST_I = "rawlist_i64"  # list[int]: Vec<i64>-style raw element array
RAWLIST_F = "rawlist_f64"  # list[float]
RAWLIST_KINDS = {RAWLIST_I: I64, RAWLIST_F: F64}
RAWDICT_II = "rawdict_ii"  # dict[int, int]: machine-word open addressing
RAWDICT_IF = "rawdict_if"  # dict[int, float] (values as f64 bit patterns)
RAWDICT_KINDS = {RAWDICT_II: I64, RAWDICT_IF: F64}  # kind -> value kind
RAWSTR = "rawstr"  # str: {len, cap, data} with exclusive slot ownership
RAW_STORAGE_KINDS = {**RAWLIST_KINDS, **RAWDICT_KINDS, RAWSTR: RAWSTR}
LLVM_KIND_TYPES = {
    I64: ir.IntType(64),
    F64: ir.DoubleType(),
    I1: ir.IntType(1),
    RAWSTR: ir.PointerType(ir.IntType(8)),  # rawstr passes as i8* in ABIs
    RAWLIST_I: ir.PointerType(ir.IntType(8)),
    RAWLIST_F: ir.PointerType(ir.IntType(8)),
    RAWDICT_II: ir.PointerType(ir.IntType(8)),
    RAWDICT_IF: ir.PointerType(ir.IntType(8)),
}


class TypedCodegen(SiluToLLVMConverter):
    """LLVM backend with unboxed scalars driven by source annotations."""

    def __init__(self):
        super().__init__()
        # Overflow/precision panics and rawlist bounds branches follow
        # Rust's release profile: set SILU_CHECKS=0 to disable them
        # (values wrap, out-of-range access is UB). Zero-division
        # checks always stay on - Rust also always checks those.
        self.checks = os.environ.get("SILU_CHECKS", "1") != "0"
        # kind of every named variable in the current scope
        self.var_kinds: Dict[str, str] = {}
        # unannotated names promoted to raw storage by the assignment
        # pre-pass (only when every assignment provably yields the same
        # raw scalar kind); empty while converting dynamic code
        self._inferred_kinds: Dict[str, str] = {}
        # name -> (param_kinds, return_kind, llvm.Function) for
        # fully-annotated numeric functions (raw machine ABI)
        self.static_funcs: Dict[str, Tuple[List[str], Optional[str], ir.Function]] = {}
        self.current_ret_kind: Optional[str] = None
        # module statements and per-function signatures from the
        # cross-function inference pre-pass (run at declaration time)
        self._module_stmt_list: list = []
        self._inferred_sigs: Dict[str, Tuple[List[str], Optional[str]]] = {}
        # dynamic-ABI functions with raw-typed proven parameters
        self._dyn_func_kinds: Dict[str, List[str]] = {}

        # math intrinsics / libc used by ** (sqrt fast path, general pow)
        sqrt_ty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()])
        self.sqrt_f64 = ir.Function(self.module, sqrt_ty, name="llvm.sqrt.f64")
        pow_ty = ir.FunctionType(
            ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()]
        )
        self.pow_f64 = ir.Function(self.module, pow_ty, name="pow")

        self._create_unbox_runtime()
        self._create_raw_list_runtime()

        # PyObject* pyobj_pow(PyObject* base, PyObject* exp) via libc pow
        i32t = ir.IntType(32)
        i64t = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.Constant(i32t, 0)
        one32 = ir.Constant(i32t, 1)
        self.pyobj_pow = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="pyobj_pow",
        )
        entry = self.pyobj_pow.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        base_arg, exp_arg = self.pyobj_pow.args
        base_tag = builder.load(builder.gep(base_arg, [zero32, zero32]))
        exp_tag = builder.load(builder.gep(exp_arg, [zero32, zero32]))
        base_f64 = self._load_number_as_f64(builder, base_arg)
        exp_f64 = self._load_number_as_f64(builder, exp_arg)
        result = builder.call(self.pow_f64, [base_f64, exp_f64])
        # int ** int with non-negative int result stays int (Python semantics
        # for the common integer case); anything else is float
        base_is_intish = builder.or_(
            builder.icmp_signed("==", base_tag, zero32),
            builder.icmp_signed("==", base_tag, ir.Constant(i32t, 3)),
        )
        exp_is_int = builder.or_(
            builder.icmp_signed("==", exp_tag, zero32),
            builder.icmp_signed("==", exp_tag, ir.Constant(i32t, 3)),
        )
        both_int = builder.and_(base_is_intish, exp_is_int)
        as_i64 = builder.fptosi(result, i64t)
        roundtrip = builder.sitofp(as_i64, ir.DoubleType())
        is_integral = builder.fcmp_ordered("==", result, roundtrip)
        keep_int = builder.and_(both_int, is_integral)
        int_obj = builder.call(self.create_int, [as_i64])
        float_obj = builder.call(self.create_float, [result])
        out = builder.select(keep_int, int_obj, float_obj)
        builder.ret(out)

    # ================== runtime additions ==================

    def _create_raw_list_runtime(self):
        """Lists with unboxed elements: list[int] -> i64, list[float] -> double.

        Layout: {i64 length, i64 capacity, i8* items} where items is a
        raw array of machine values. Element values cross the boundary
        as pointers to stack slots so one runtime serves both widths.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        zero32 = ir.Constant(i32, 0)
        zero64 = ir.Constant(i64, 0)
        one64 = ir.Constant(i64, 1)

        self.raw_list_struct_type = ir.LiteralStructType([i64, i64, i8p])

        def field(builder, struct_ptr, index):
            return builder.gep(struct_ptr, [zero32, ir.Constant(i32, index)])

        # i8* rawlist_new(i64 elem_size)
        self.rawlist_new = ir.Function(
            self.module, ir.FunctionType(i8p, [i64]), name="rawlist_new"
        )
        builder = ir.IRBuilder(self.rawlist_new.append_basic_block("entry"))
        (elem_size,) = self.rawlist_new.args
        struct_ptr = builder.call(self.malloc, [ir.Constant(i64, 24)])
        struct_ptr = builder.bitcast(
            struct_ptr, ir.PointerType(self.raw_list_struct_type)
        )
        initial = builder.call(
            self.malloc, [builder.mul(elem_size, ir.Constant(i64, 4))]
        )
        builder.store(ir.Constant(i64, 0), field(builder, struct_ptr, 0))
        builder.store(ir.Constant(i64, 4), field(builder, struct_ptr, 1))
        builder.store(initial, field(builder, struct_ptr, 2))
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # i64 rawlist_push(i8* list, <elem-width * elem_value>) -> new length
        # Element passed BY VALUE; call sites use the i64 flavor (double
        # values are bitcast - both are 8 bytes). One capacity check per
        # call, in-place element store, no temporary buffers.
        self.rawlist_push = ir.Function(
            self.module,
            ir.FunctionType(i64, [i8p, i64]),
            name="rawlist_push",
        )
        entry = self.rawlist_push.append_basic_block("entry")
        grow_block = self.rawlist_push.append_basic_block("grow")
        copy_block = self.rawlist_push.append_basic_block("grow_copy")
        do_push = self.rawlist_push.append_basic_block("do_push")
        builder = ir.IRBuilder(entry)
        list_arg, elem_arg = self.rawlist_push.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(field(builder, struct_ptr, 0))
        capacity = builder.load(field(builder, struct_ptr, 1))
        needs_grow = builder.icmp_signed("==", length, capacity)
        builder.cbranch(needs_grow, grow_block, do_push)

        builder.position_at_end(grow_block)
        # capacity doubles; entries are fixed 8 bytes
        new_capacity = builder.mul(capacity, ir.Constant(i64, 2))
        fresh = builder.call(
            self.malloc,
            [builder.mul(new_capacity, ir.Constant(i64, 8))],
        )
        has_old = builder.icmp_signed(">", length, zero64)
        builder.cbranch(has_old, copy_block, do_push)

        builder.position_at_end(copy_block)
        old_items = builder.load(field(builder, struct_ptr, 2))
        builder.call(
            self.memcpy,
            [
                fresh,
                old_items,
                builder.mul(length, ir.Constant(i64, 8)),
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.store(new_capacity, field(builder, struct_ptr, 1))
        builder.store(fresh, field(builder, struct_ptr, 2))
        builder.branch(do_push)

        builder.position_at_end(do_push)
        items = builder.load(field(builder, struct_ptr, 2))
        length_now = builder.load(field(builder, struct_ptr, 0))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [length_now])
        builder.store(elem_arg, slot)
        new_length = builder.add(length_now, one64)
        builder.store(new_length, field(builder, struct_ptr, 0))
        builder.ret(new_length)

        # i64 rawlist_pop(i8* list) - remove and return the last element
        self.rawlist_pop = ir.Function(
            self.module, ir.FunctionType(i64, [i8p]), name="rawlist_pop"
        )
        entry = self.rawlist_pop.append_basic_block("entry")
        empty_block = self.rawlist_pop.append_basic_block("pop_empty")
        ok_block = self.rawlist_pop.append_basic_block("pop_ok")
        builder = ir.IRBuilder(entry)
        struct_ptr = builder.bitcast(
            self.rawlist_pop.args[0], ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(field(builder, struct_ptr, 0))
        is_empty = builder.icmp_signed("==", length, zero64)
        builder.cbranch(is_empty, empty_block, ok_block)

        builder.position_at_end(empty_block)
        msg = self._create_global_string_with_builder(
            "IndexError: pop from empty list\n", builder
        )
        builder.call(self.printf, [msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        items = builder.load(field(builder, struct_ptr, 2))
        last_index = builder.sub(length, one64)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [last_index])
        value = builder.load(slot)
        builder.store(zero64, field(builder, struct_ptr, 0))
        builder.ret(value)

        # PyObject* rawlist_to_pylist(i8* list, i64 length)
        # box every element for the dynamic boundary
        self.rawlist_to_pylist = ir.Function(
            self.module,
            ir.FunctionType(ir.PointerType(self.pyobj.pyobj_type), [i8p, i64]),
            name="rawlist_to_pylist",
        )
        entry = self.rawlist_to_pylist.append_basic_block("entry")
        loop_check = self.rawlist_to_pylist.append_basic_block("cvt_check")
        loop_body = self.rawlist_to_pylist.append_basic_block("cvt_body")
        loop_done = self.rawlist_to_pylist.append_basic_block("cvt_done")
        builder = ir.IRBuilder(entry)
        list_arg, length_arg = self.rawlist_to_pylist.args
        src_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        items = builder.load(field(builder, src_struct, 2))
        result = builder.call(self.create_list, [])
        idx_ptr = builder.alloca(i64, name="cvt_i")
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        more = builder.icmp_signed("<", i_val, length_arg)
        builder.cbranch(more, loop_body, loop_done)

        builder.position_at_end(loop_body)
        elem_ptr = builder.gep(items, [i_val])
        elem_bits = builder.load(builder.bitcast(elem_ptr, ir.PointerType(i64)))
        boxed = builder.call(self.create_int, [elem_bits])
        builder.call(self.list_append, [result, boxed])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(result)

        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32b = ir.Constant(ir.IntType(32), 0)
        one32b = ir.Constant(ir.IntType(32), 1)

        # i8* pylist_to_rawlist(PyObject* list) - unbox each element into
        # a fresh raw array (ints only; other element types become 0)
        self.pylist_to_rawlist = ir.Function(
            self.module, ir.FunctionType(i8p, [pyobj_ptr]), name="pylist_to_rawlist"
        )
        entry = self.pylist_to_rawlist.append_basic_block("entry")
        loop_check = self.pylist_to_rawlist.append_basic_block("p2r_check")
        loop_body = self.pylist_to_rawlist.append_basic_block("p2r_body")
        loop_done = self.pylist_to_rawlist.append_basic_block("p2r_done")
        builder = ir.IRBuilder(entry)
        (list_arg,) = self.pylist_to_rawlist.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.list_struct_type)
        )
        length = builder.load(field(builder, struct_ptr, 0))
        items = builder.load(field(builder, struct_ptr, 2))
        raw = builder.call(self.rawlist_new, [ir.Constant(i64, 8)])
        idx_ptr = builder.alloca(i64, name="p2r_i")
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        more = builder.icmp_signed("<", i_val, length)
        builder.cbranch(more, loop_body, loop_done)

        builder.position_at_end(loop_body)
        elem = builder.load(builder.gep(items, [i_val]))
        elem_tag = builder.load(
            builder.gep(elem, [zero32b, zero32b])
        )
        elem_data = builder.load(
            builder.gep(elem, [zero32b, one32b])
        )
        elem_i64 = builder.load(builder.bitcast(elem_data, ir.PointerType(i64)))
        builder.call(self.rawlist_push, [raw, elem_i64])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(raw)

        # i64 rawlist_len(i8* list)
        self.rawlist_len = ir.Function(
            self.module, ir.FunctionType(i64, [i8p]), name="rawlist_len"
        )
        builder = ir.IRBuilder(self.rawlist_len.append_basic_block("entry"))
        struct_ptr = builder.bitcast(
            self.rawlist_len.args[0], ir.PointerType(self.raw_list_struct_type)
        )
        builder.ret(builder.load(field(builder, struct_ptr, 0)))

        # ---- raw dicts: dict[int, int] / dict[int, float] ----
        # {i64 count, i64 filled, i64 entries_cap, i64 mask,
        #  i64* index_table, i64* keys, i64* values}
        # Open addressing with linear probing on machine words; index
        # slots hold entry_index+1 and 0 means empty. Entries are
        # append-only (no deletion in this first cut), so tombstones
        # never exist and the first empty slot ends every probe.
        self.raw_dict_struct_type = ir.LiteralStructType(
            [
                i64,
                i64,
                i64,
                i64,
                ir.PointerType(i64),
                ir.PointerType(i64),
                ir.PointerType(i64),
            ]
        )

        def dfield(b, struct_ptr, index):
            return b.gep(struct_ptr, [zero32, ir.Constant(i32, index)])

        def panic_string(data: bytes, label: str) -> ir.GlobalVariable:
            gv = ir.GlobalVariable(
                self.module,
                ir.ArrayType(ir.IntType(8), len(data)),
                name=label,
            )
            gv.global_constant = True
            gv.initializer = ir.Constant(
                ir.ArrayType(ir.IntType(8), len(data)), bytearray(data)
            )
            return gv

        key_error_msg = panic_string(b"KeyError: key not found\n\0", "str_keyerr")
        str_index_error_msg = panic_string(
            b"IndexError: string index out of range\n\0", "str_idxerr"
        )

        # void rawdict_reindex(i8* d, i64 new_size)
        # Rebuilds the index table at new_size and compacts the entries
        # arrays: live entries (table slot > 0) are copied to fresh
        # keys/values arrays, dead (deleted) entries are dropped, and
        # filled is reset to the live count.
        self.rawdict_reindex = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64]),
            name="rawdict_reindex",
        )
        entry = self.rawdict_reindex.append_basic_block("entry")
        scan_cond = self.rawdict_reindex.append_basic_block("scan_cond")
        scan_body = self.rawdict_reindex.append_basic_block("scan_body")
        place_start = self.rawdict_reindex.append_basic_block("place_start")
        place_probe = self.rawdict_reindex.append_basic_block("place_probe")
        place_store = self.rawdict_reindex.append_basic_block("place_store")
        place_step = self.rawdict_reindex.append_basic_block("place_step")
        scan_step = self.rawdict_reindex.append_basic_block("scan_step")
        scan_done = self.rawdict_reindex.append_basic_block("scan_done")
        builder = ir.IRBuilder(entry)
        dict_arg, new_size_arg = self.rawdict_reindex.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        old_mask = builder.load(dfield(builder, struct_ptr, 3))
        old_size = builder.add(old_mask, one64)
        old_table = builder.load(dfield(builder, struct_ptr, 4))
        old_keys = builder.load(dfield(builder, struct_ptr, 5))
        old_vals = builder.load(dfield(builder, struct_ptr, 6))
        entries_cap = builder.load(dfield(builder, struct_ptr, 2))
        new_mask = builder.sub(new_size_arg, one64)
        fresh_table = builder.bitcast(
            builder.call(self.calloc, [new_size_arg, ir.Constant(i64, 8)]),
            ir.PointerType(i64),
        )
        cap_bytes = builder.mul(entries_cap, ir.Constant(i64, 8))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        builder.store(new_mask, dfield(builder, struct_ptr, 3))
        builder.store(fresh_table, dfield(builder, struct_ptr, 4))
        builder.store(fresh_keys, dfield(builder, struct_ptr, 5))
        builder.store(fresh_vals, dfield(builder, struct_ptr, 6))
        idx_ptr = builder.alloca(i64, name="re_i")
        live_ptr = builder.alloca(i64, name="re_live")
        slot_ptr = builder.alloca(i64, name="re_slot")
        builder.store(zero64, idx_ptr)
        builder.store(zero64, live_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, old_size)
        builder.cbranch(more, scan_body, scan_done)

        builder.position_at_end(scan_body)
        slot_entry = builder.load(builder.gep(old_table, [idx]))
        is_live = builder.icmp_signed(">", slot_entry, zero64)
        builder.cbranch(is_live, place_start, scan_step)

        builder.position_at_end(place_start)
        entry_index = builder.sub(slot_entry, one64)
        key_val = builder.load(builder.gep(old_keys, [entry_index]))
        val_val = builder.load(builder.gep(old_vals, [entry_index]))
        live = builder.load(live_ptr)
        builder.store(key_val, builder.gep(fresh_keys, [live]))
        builder.store(val_val, builder.gep(fresh_vals, [live]))
        builder.store(builder.and_(key_val, new_mask), slot_ptr)
        builder.branch(place_probe)

        builder.position_at_end(place_probe)
        slot_now = builder.load(slot_ptr)
        taken = builder.load(builder.gep(fresh_table, [slot_now]))
        is_taken = builder.icmp_signed("!=", taken, zero64)
        builder.cbranch(is_taken, place_step, place_store)

        builder.position_at_end(place_store)
        builder.store(
            builder.add(live, one64), builder.gep(fresh_table, [slot_now])
        )
        builder.store(builder.add(live, one64), live_ptr)
        builder.branch(scan_step)

        builder.position_at_end(place_step)
        stepped = builder.and_(builder.add(slot_now, one64), new_mask)
        builder.store(stepped, slot_ptr)
        builder.branch(place_probe)

        builder.position_at_end(scan_step)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_done)
        builder.store(builder.load(live_ptr), dfield(builder, struct_ptr, 1))
        builder.call(self.free, [builder.bitcast(old_table, i8p)])
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.ret_void()

        # i8* rawdict_new()
        self.rawdict_new = ir.Function(
            self.module, ir.FunctionType(i8p, []), name="rawdict_new"
        )
        builder = ir.IRBuilder(self.rawdict_new.append_basic_block("entry"))
        struct_ptr = builder.bitcast(
            builder.call(self.malloc, [ir.Constant(i64, 56)]),
            ir.PointerType(self.raw_dict_struct_type),
        )
        builder.store(ir.Constant(i64, 0), dfield(builder, struct_ptr, 0))
        builder.store(ir.Constant(i64, 0), dfield(builder, struct_ptr, 1))
        builder.store(ir.Constant(i64, 8), dfield(builder, struct_ptr, 2))
        builder.store(ir.Constant(i64, 7), dfield(builder, struct_ptr, 3))
        builder.store(
            builder.bitcast(
                builder.call(
                    self.calloc, [ir.Constant(i64, 8), ir.Constant(i64, 8)]
                ),
                ir.PointerType(i64),
            ),
            dfield(builder, struct_ptr, 4),
        )
        builder.store(
            builder.bitcast(
                builder.call(self.malloc, [ir.Constant(i64, 64)]),
                ir.PointerType(i64),
            ),
            dfield(builder, struct_ptr, 5),
        )
        builder.store(
            builder.bitcast(
                builder.call(self.malloc, [ir.Constant(i64, 64)]),
                ir.PointerType(i64),
            ),
            dfield(builder, struct_ptr, 6),
        )
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # void rawdict_set(i8* d, i64 key, i64 value_bits)
        self.rawdict_set = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i64]),
            name="rawdict_set",
        )
        entry = self.rawdict_set.append_basic_block("entry")
        rehash_block = self.rawdict_set.append_basic_block("rehash")
        size_check = self.rawdict_set.append_basic_block("size_check")
        size_grow = self.rawdict_set.append_basic_block("size_grow")
        size_done = self.rawdict_set.append_basic_block("size_done")
        start_block = self.rawdict_set.append_basic_block("probe_start")
        probe_test = self.rawdict_set.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_set.append_basic_block("probe_tomb")
        tomb_note = self.rawdict_set.append_basic_block("tomb_note")
        tomb_store = self.rawdict_set.append_basic_block("tomb_store")
        match_check = self.rawdict_set.append_basic_block("probe_match")
        overwrite = self.rawdict_set.append_basic_block("overwrite")
        probe_step = self.rawdict_set.append_basic_block("probe_step")
        insert = self.rawdict_set.append_basic_block("insert")
        grow_block = self.rawdict_set.append_basic_block("grow")
        do_insert = self.rawdict_set.append_basic_block("do_insert")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg, val_arg = self.rawdict_set.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        filled = builder.load(dfield(builder, struct_ptr, 1))
        mask = builder.load(dfield(builder, struct_ptr, 3))
        index_size = builder.add(mask, one64)
        load_would_exceed = builder.icmp_signed(
            ">",
            builder.mul(builder.add(filled, one64), ir.Constant(i64, 3)),
            builder.mul(index_size, ir.Constant(i64, 2)),
        )
        slot_ptr = builder.alloca(i64, name="rd_slot")
        tomb_ptr = builder.alloca(i64, name="rd_tomb")
        size_ptr = builder.alloca(i64, name="rd_size")
        builder.cbranch(load_would_exceed, rehash_block, start_block)

        # Resize to the smallest power of two (>= 8) that keeps the live
        # count under the 2/3 load factor. Compaction in reindex drops
        # tombstones, so churn without growth does not grow the table.
        builder.position_at_end(rehash_block)
        live_count = builder.load(dfield(builder, struct_ptr, 0))
        builder.store(ir.Constant(i64, 8), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_check)
        size_now = builder.load(size_ptr)
        need_more = builder.icmp_signed(
            ">",
            builder.mul(builder.add(live_count, one64), ir.Constant(i64, 3)),
            builder.mul(size_now, ir.Constant(i64, 2)),
        )
        builder.cbranch(need_more, size_grow, size_done)

        builder.position_at_end(size_grow)
        builder.store(builder.mul(size_now, ir.Constant(i64, 2)), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_done)
        builder.call(self.rawdict_reindex, [dict_arg, builder.load(size_ptr)])
        builder.branch(start_block)

        builder.position_at_end(start_block)
        builder.store(ir.Constant(i64, -1), tomb_ptr)
        mask_now = builder.load(dfield(builder, struct_ptr, 3))
        builder.store(builder.and_(key_arg, mask_now), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(dfield(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, insert, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.Constant(i64, -1))
        builder.cbranch(is_tomb, tomb_note, match_check)

        builder.position_at_end(tomb_note)
        tomb_seen = builder.load(tomb_ptr)
        none_yet = builder.icmp_signed("==", tomb_seen, ir.Constant(i64, -1))
        builder.cbranch(none_yet, tomb_store, probe_step)

        builder.position_at_end(tomb_store)
        builder.store(slot_now, tomb_ptr)
        builder.branch(probe_step)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(dfield(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, overwrite, probe_step)

        builder.position_at_end(overwrite)
        vals_now = builder.load(dfield(builder, struct_ptr, 6))
        builder.store(val_arg, builder.gep(vals_now, [entry_index]))
        builder.ret_void()

        builder.position_at_end(probe_step)
        mask_step = builder.load(dfield(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(insert)
        # reuse the first tombstone slot seen while probing, if any
        tomb_seen = builder.load(tomb_ptr)
        has_tomb = builder.icmp_signed("!=", tomb_seen, ir.Constant(i64, -1))
        target_slot = builder.select(has_tomb, tomb_seen, builder.load(slot_ptr))
        builder.store(target_slot, slot_ptr)
        filled_now = builder.load(dfield(builder, struct_ptr, 1))
        entries_cap = builder.load(dfield(builder, struct_ptr, 2))
        needs_room = builder.icmp_signed("==", filled_now, entries_cap)
        builder.cbranch(needs_room, grow_block, do_insert)

        builder.position_at_end(grow_block)
        new_cap = builder.mul(entries_cap, ir.Constant(i64, 2))
        byte_room = builder.mul(new_cap, ir.Constant(i64, 8))
        old_keys = builder.load(dfield(builder, struct_ptr, 5))
        old_vals = builder.load(dfield(builder, struct_ptr, 6))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        copy_bytes = builder.mul(filled_now, ir.Constant(i64, 8))
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_keys, i8p),
                builder.bitcast(old_keys, i8p),
                copy_bytes,
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_vals, i8p),
                builder.bitcast(old_vals, i8p),
                copy_bytes,
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.store(new_cap, dfield(builder, struct_ptr, 2))
        builder.store(fresh_keys, dfield(builder, struct_ptr, 5))
        builder.store(fresh_vals, dfield(builder, struct_ptr, 6))
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.branch(do_insert)

        builder.position_at_end(do_insert)
        slot_free = builder.load(slot_ptr)
        keys_final = builder.load(dfield(builder, struct_ptr, 5))
        vals_final = builder.load(dfield(builder, struct_ptr, 6))
        builder.store(key_arg, builder.gep(keys_final, [filled_now]))
        builder.store(val_arg, builder.gep(vals_final, [filled_now]))
        table_final = builder.load(dfield(builder, struct_ptr, 4))
        builder.store(
            builder.add(filled_now, one64), builder.gep(table_final, [slot_free])
        )
        builder.store(builder.add(filled_now, one64), dfield(builder, struct_ptr, 1))
        count = builder.load(dfield(builder, struct_ptr, 0))
        builder.store(builder.add(count, one64), dfield(builder, struct_ptr, 0))
        builder.ret_void()

        # i64 rawdict_get(i8* d, i64 key) - panics KeyError when missing
        self.rawdict_get = ir.Function(
            self.module, ir.FunctionType(i64, [i8p, i64]), name="rawdict_get"
        )
        entry = self.rawdict_get.append_basic_block("entry")
        probe_test = self.rawdict_get.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_get.append_basic_block("probe_tomb")
        match_check = self.rawdict_get.append_basic_block("probe_match")
        found = self.rawdict_get.append_basic_block("found")
        probe_step = self.rawdict_get.append_basic_block("probe_step")
        missing = self.rawdict_get.append_basic_block("key_error")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg = self.rawdict_get.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(dfield(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, name="rdg_slot")
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(dfield(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.Constant(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(dfield(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, found, probe_step)

        builder.position_at_end(found)
        vals_now = builder.load(dfield(builder, struct_ptr, 6))
        builder.ret(builder.load(builder.gep(vals_now, [entry_index])))

        builder.position_at_end(probe_step)
        mask_step = builder.load(dfield(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(missing)
        msg_ptr = builder.gep(key_error_msg, [zero32, zero32])
        builder.call(self.printf, [msg_ptr])
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        # i64 rawdict_del(i8* d, i64 key) - tombstones the slot, returns the
        # removed value's bits; panics KeyError when missing (Python del).
        self.rawdict_del = ir.Function(
            self.module, ir.FunctionType(i64, [i8p, i64]), name="rawdict_del"
        )
        entry = self.rawdict_del.append_basic_block("entry")
        probe_test = self.rawdict_del.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_del.append_basic_block("probe_tomb")
        match_check = self.rawdict_del.append_basic_block("probe_match")
        found = self.rawdict_del.append_basic_block("found")
        probe_step = self.rawdict_del.append_basic_block("probe_step")
        missing = self.rawdict_del.append_basic_block("key_error")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg = self.rawdict_del.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(dfield(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, name="rdd_slot")
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(dfield(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.Constant(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(dfield(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, found, probe_step)

        builder.position_at_end(found)
        builder.store(
            ir.Constant(i64, -1), builder.gep(table_now, [slot_now])
        )
        count = builder.load(dfield(builder, struct_ptr, 0))
        builder.store(builder.sub(count, one64), dfield(builder, struct_ptr, 0))
        vals_now = builder.load(dfield(builder, struct_ptr, 6))
        builder.ret(builder.load(builder.gep(vals_now, [entry_index])))

        builder.position_at_end(probe_step)
        mask_step = builder.load(dfield(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(missing)
        msg_ptr = builder.gep(key_error_msg, [zero32, zero32])
        builder.call(self.printf, [msg_ptr])
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        # PyObject* rawdict_to_pydict_ii/if(i8* d) - dynamic boundary
        for tag, make_value in (
            ("ii", lambda b, bits: b.call(self.create_int, [bits])),
            (
                "if",
                lambda b, bits: b.call(
                    self.create_float, [b.bitcast(bits, ir.DoubleType())]
                ),
            ),
        ):
            func = ir.Function(
                self.module,
                ir.FunctionType(
                    ir.PointerType(self.pyobj.pyobj_type), [i8p]
                ),
                name=f"rawdict_to_pydict_{tag}",
            )
            entry = func.append_basic_block("entry")
            loop_check = func.append_basic_block("cvt_check")
            loop_body = func.append_basic_block("cvt_body")
            emit_block = func.append_basic_block("cvt_emit")
            loop_step = func.append_basic_block("cvt_step")
            loop_done = func.append_basic_block("cvt_done")
            builder = ir.IRBuilder(entry)
            (dict_arg,) = func.args
            struct_ptr = builder.bitcast(
                dict_arg, ir.PointerType(self.raw_dict_struct_type)
            )
            # walk the index table: entries arrays hold dead slots after
            # deletions, live entries are exactly the slots > 0
            mask = builder.load(dfield(builder, struct_ptr, 3))
            table_size = builder.add(mask, one64)
            result = builder.call(self.create_dict, [])
            idx_ptr = builder.alloca(i64, name="cvt_i")
            builder.store(zero64, idx_ptr)
            builder.branch(loop_check)

            builder.position_at_end(loop_check)
            idx = builder.load(idx_ptr)
            more = builder.icmp_signed("<", idx, table_size)
            builder.cbranch(more, loop_body, loop_done)

            builder.position_at_end(loop_body)
            table_now = builder.load(dfield(builder, struct_ptr, 4))
            slot_entry = builder.load(builder.gep(table_now, [idx]))
            is_live = builder.icmp_signed(">", slot_entry, zero64)
            builder.cbranch(is_live, emit_block, loop_step)

            builder.position_at_end(emit_block)
            entry_index = builder.sub(slot_entry, one64)
            keys_now = builder.load(dfield(builder, struct_ptr, 5))
            vals_now = builder.load(dfield(builder, struct_ptr, 6))
            key_box = builder.call(
                self.create_int,
                [builder.load(builder.gep(keys_now, [entry_index]))],
            )
            val_box = make_value(
                builder, builder.load(builder.gep(vals_now, [entry_index]))
            )
            builder.call(self.dict_set, [result, key_box, val_box])
            builder.branch(loop_step)

            builder.position_at_end(loop_step)
            builder.store(builder.add(idx, one64), idx_ptr)
            builder.branch(loop_check)

            builder.position_at_end(loop_done)
            builder.ret(result)
            setattr(self, f"rawdict_to_pydict_{tag}", func)
        # {i64 len, i64 cap, i8* data}. Every slot owns its buffer
        # exclusively (assignment copies), so appends may realloc in
        # place and grow amortized like Rust's String.
        self.rawstr_struct_type = ir.LiteralStructType([i64, i64, i8p])

        self.realloc = ir.Function(
            self.module, ir.FunctionType(i8p, [i8p, i64]), name="realloc"
        )

        def sfield(b, struct_ptr, index):
            return b.gep(struct_ptr, [zero32, ir.Constant(i32, index)])

        def load_len(b, struct_ptr):
            return b.load(sfield(b, struct_ptr, 0))

        def load_data(b, struct_ptr):
            return b.load(sfield(b, struct_ptr, 2))

        type_error_msg = panic_string(
            b"TypeError: expected str\n\0", "str_typeerr"
        )

        def build_rawstr(header_len, data_len, data_value):
            """Shared prologue: fresh struct + data buffer, fields set."""
            fresh = builder.bitcast(
                builder.call(self.malloc, [ir.Constant(i64, 24)]),
                ir.PointerType(self.rawstr_struct_type),
            )
            builder.store(header_len, sfield(builder, fresh, 0))
            builder.store(header_len, sfield(builder, fresh, 1))
            builder.store(data_value, sfield(builder, fresh, 2))
            return fresh

        # i8* rawstr_new_copy(i8* data, i64 len)
        self.rawstr_new_copy = ir.Function(
            self.module,
            ir.FunctionType(i8p, [i8p, i64]),
            name="rawstr_new_copy",
        )
        builder = ir.IRBuilder(self.rawstr_new_copy.append_basic_block("entry"))
        data_arg, len_arg = self.rawstr_new_copy.args
        buffer = builder.call(self.malloc, [len_arg])
        builder.call(
            self.memcpy,
            [buffer, data_arg, len_arg, ir.Constant(ir.IntType(1), 0)],
        )
        struct_ptr = build_rawstr(len_arg, len_arg, buffer)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # i8* rawstr_copy(i8* src) - eager copy keeps slots exclusive
        self.rawstr_copy = ir.Function(
            self.module, ir.FunctionType(i8p, [i8p]), name="rawstr_copy"
        )
        builder = ir.IRBuilder(self.rawstr_copy.append_basic_block("entry"))
        (src_arg,) = self.rawstr_copy.args
        src_struct = builder.bitcast(
            src_arg, ir.PointerType(self.rawstr_struct_type)
        )
        src_len = load_len(builder, src_struct)
        src_data = load_data(builder, src_struct)
        fresh_data = builder.call(self.malloc, [src_len])
        builder.call(
            self.memcpy,
            [fresh_data, src_data, src_len, ir.Constant(ir.IntType(1), 0)],
        )
        struct_ptr = builder.bitcast(
            builder.call(self.malloc, [ir.Constant(i64, 24)]),
            ir.PointerType(self.rawstr_struct_type),
        )
        builder.store(src_len, sfield(builder, struct_ptr, 0))
        builder.store(src_len, sfield(builder, struct_ptr, 1))
        builder.store(fresh_data, sfield(builder, struct_ptr, 2))
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # i8* rawstr_concat(i8* a, i8* b) - fresh result, inputs untouched
        self.rawstr_concat = ir.Function(
            self.module,
            ir.FunctionType(i8p, [i8p, i8p]),
            name="rawstr_concat",
        )
        builder = ir.IRBuilder(self.rawstr_concat.append_basic_block("entry"))
        a_arg, b_arg = self.rawstr_concat.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = load_len(builder, a_struct)
        b_len = load_len(builder, b_struct)
        total = builder.add(a_len, b_len)
        buffer = builder.call(self.malloc, [total])
        builder.call(
            self.memcpy,
            [buffer, load_data(builder, a_struct), a_len, ir.Constant(ir.IntType(1), 0)],
        )
        b_dst = builder.gep(buffer, [a_len])
        builder.call(
            self.memcpy,
            [b_dst, load_data(builder, b_struct), b_len, ir.Constant(ir.IntType(1), 0)],
        )
        struct_ptr = build_rawstr(total, total, buffer)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # void rawstr_append(i8* s, i8* data, i64 len)
        # Grow in place with doubling; caller guarantees `data` does not
        # point into s's buffer (self-append goes through rawstr_concat).
        self.rawstr_append = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i8p, i64]),
            name="rawstr_append",
        )
        entry = self.rawstr_append.append_basic_block("entry")
        grow_block = self.rawstr_append.append_basic_block("grow")
        copy_block = self.rawstr_append.append_basic_block("do_append")
        builder = ir.IRBuilder(entry)
        s_arg, data_arg, add_len_arg = self.rawstr_append.args
        struct_ptr = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        old_len = load_len(builder, struct_ptr)
        old_cap = builder.load(sfield(builder, struct_ptr, 1))
        new_len = builder.add(old_len, add_len_arg)
        needs_room = builder.icmp_signed(">", new_len, old_cap)
        builder.cbranch(needs_room, grow_block, copy_block)

        builder.position_at_end(grow_block)
        doubled = builder.mul(old_cap, ir.Constant(i64, 2))
        enough = builder.icmp_signed(">=", doubled, new_len)
        new_cap = builder.select(enough, doubled, new_len)
        old_data = load_data(builder, struct_ptr)
        grown = builder.call(
            self.realloc,
            [old_data, new_cap],
        )
        builder.store(new_cap, sfield(builder, struct_ptr, 1))
        builder.store(grown, sfield(builder, struct_ptr, 2))
        builder.branch(copy_block)

        builder.position_at_end(copy_block)
        data_now = load_data(builder, struct_ptr)
        len_now = load_len(builder, struct_ptr)
        dst = builder.gep(data_now, [len_now])
        builder.call(
            self.memcpy,
            [dst, data_arg, add_len_arg, ir.Constant(ir.IntType(1), 0)],
        )
        builder.store(new_len, sfield(builder, struct_ptr, 0))
        builder.ret_void()

        # i1 rawstr_eq(i8* a, i8* b)
        self.rawstr_eq = ir.Function(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i8p]), name="rawstr_eq"
        )
        entry = self.rawstr_eq.append_basic_block("entry")
        eq_ok = self.rawstr_eq.append_basic_block("len_ok")
        eq_out = self.rawstr_eq.append_basic_block("eq_out")
        builder = ir.IRBuilder(entry)
        a_arg, b_arg = self.rawstr_eq.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = load_len(builder, a_struct)
        b_len = load_len(builder, b_struct)
        same_len = builder.icmp_signed("==", a_len, b_len)
        builder.cbranch(same_len, eq_ok, eq_out)

        builder.position_at_end(eq_ok)
        same = builder.call(
            self.memcmp,
            [load_data(builder, a_struct), load_data(builder, b_struct), a_len],
        )
        is_zero = builder.icmp_signed("==", same, ir.Constant(i32, 0))
        builder.branch(eq_out)

        builder.position_at_end(eq_out)
        result = builder.phi(ir.IntType(1))
        result.add_incoming(ir.Constant(ir.IntType(1), 0), entry)
        result.add_incoming(is_zero, eq_ok)
        builder.ret(result)

        # i64 rawstr_cmp(i8* a, i8* b) - memcmp sign (UTF-8 byte order
        # equals code point order, same as Python's str ordering)
        self.rawstr_cmp = ir.Function(
            self.module, ir.FunctionType(i64, [i8p, i8p]), name="rawstr_cmp"
        )
        builder = ir.IRBuilder(self.rawstr_cmp.append_basic_block("entry"))
        a_arg, b_arg = self.rawstr_cmp.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = load_len(builder, a_struct)
        b_len = load_len(builder, b_struct)
        prefix_len = builder.select(
            builder.icmp_signed("<", a_len, b_len), a_len, b_len
        )
        memcmp_result = builder.call(
            self.memcmp,
            [load_data(builder, a_struct), load_data(builder, b_struct), prefix_len],
        )
        memcmp_i64 = builder.sext(memcmp_result, i64)
        is_equal = builder.icmp_signed("==", memcmp_i64, zero64)
        # equal prefixes: the shorter string sorts first
        length_diff = builder.sub(a_len, b_len)
        builder.ret(builder.select(is_equal, length_diff, memcmp_i64))

        # i8* rawstr_char_at(i8* s, i64 index) - s[i] as a 1-byte rawstr.
        # Byte semantics: for ASCII this equals Python's code-point
        # indexing; negative indices adjust by the byte length.
        self.rawstr_char_at = ir.Function(
            self.module, ir.FunctionType(i8p, [i8p, i64]), name="rawstr_char_at"
        )
        entry = self.rawstr_char_at.append_basic_block("entry")
        ok_block = self.rawstr_char_at.append_basic_block("ok")
        err_block = self.rawstr_char_at.append_basic_block("index_error")
        builder = ir.IRBuilder(entry)
        s_arg, index_arg = self.rawstr_char_at.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = load_len(builder, s_struct)
        is_neg = builder.icmp_signed("<", index_arg, zero64)
        index_eff = builder.select(is_neg, builder.add(index_arg, s_len), index_arg)
        below = builder.icmp_signed(">=", index_eff, zero64)
        above = builder.icmp_signed("<", index_eff, s_len)
        builder.cbranch(builder.and_(below, above), ok_block, err_block)

        builder.position_at_end(err_block)
        msg_ptr = builder.gep(str_index_error_msg, [zero32, zero32])
        builder.call(self.printf, [msg_ptr])
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        s_data = load_data(builder, s_struct)
        byte_ptr = builder.gep(s_data, [index_eff])
        char_buf = builder.call(self.malloc, [one64])
        builder.store(builder.load(byte_ptr), char_buf)
        char_struct = build_rawstr(one64, one64, char_buf)
        builder.ret(builder.bitcast(char_struct, i8p))

        # i8* rawstr_slice(i8* s, i64 lo, i64 hi) - s[lo:hi] with Python's
        # clamping (negative bounds adjust, out-of-range clamps, an
        # inverted range yields the empty string)
        self.rawstr_slice = ir.Function(
            self.module, ir.FunctionType(i8p, [i8p, i64, i64]),
            name="rawstr_slice",
        )
        builder = ir.IRBuilder(self.rawstr_slice.append_basic_block("entry"))
        s_arg, lo_arg, hi_arg = self.rawstr_slice.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = load_len(builder, s_struct)
        s_data = load_data(builder, s_struct)

        def clamp_bound(b, bound):
            adjusted = b.select(
                b.icmp_signed("<", bound, zero64), b.add(bound, s_len), bound
            )
            floored = b.select(
                b.icmp_signed("<", adjusted, zero64), zero64, adjusted
            )
            return b.select(b.icmp_signed(">", floored, s_len), s_len, floored)

        lo_eff = clamp_bound(builder, lo_arg)
        hi_eff = clamp_bound(builder, hi_arg)
        span = builder.sub(hi_eff, lo_eff)
        out_len = builder.select(
            builder.icmp_signed(">", span, zero64), span, zero64
        )
        # malloc(0) may return null; keep the buffer valid for memcpy
        alloc_len = builder.select(
            builder.icmp_signed(">", out_len, zero64), out_len, one64
        )
        out_buf = builder.call(self.malloc, [alloc_len])
        builder.call(
            self.memcpy,
            [
                out_buf,
                builder.gep(s_data, [lo_eff]),
                out_len,
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        slice_struct = build_rawstr(out_len, out_len, out_buf)
        builder.ret(builder.bitcast(slice_struct, i8p))

        # i1 rawstr_contains(i8* haystack, i8* needle) - substring scan;
        # the empty needle is contained (Python: "" in s is True)
        self.rawstr_contains = ir.Function(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i8p]),
            name="rawstr_contains",
        )
        entry = self.rawstr_contains.append_basic_block("entry")
        len_check = self.rawstr_contains.append_basic_block("len_check")
        scan_cond = self.rawstr_contains.append_basic_block("contains_cond")
        scan_body = self.rawstr_contains.append_basic_block("contains_body")
        scan_step = self.rawstr_contains.append_basic_block("contains_step")
        hit_block = self.rawstr_contains.append_basic_block("contains_hit")
        miss_block = self.rawstr_contains.append_basic_block("contains_miss")
        builder = ir.IRBuilder(entry)
        hay_arg, needle_arg = self.rawstr_contains.args
        hay_struct = builder.bitcast(hay_arg, ir.PointerType(self.rawstr_struct_type))
        needle_struct = builder.bitcast(
            needle_arg, ir.PointerType(self.rawstr_struct_type)
        )
        hay_len = load_len(builder, hay_struct)
        needle_len = load_len(builder, needle_struct)
        hay_data = load_data(builder, hay_struct)
        needle_data = load_data(builder, needle_struct)
        scan_idx_ptr = builder.alloca(i64, name="rsc_i")
        builder.store(zero64, scan_idx_ptr)
        needle_empty = builder.icmp_signed("==", needle_len, zero64)
        builder.cbranch(needle_empty, hit_block, len_check)

        builder.position_at_end(len_check)
        too_long = builder.icmp_signed(">", needle_len, hay_len)
        builder.cbranch(too_long, miss_block, scan_cond)

        builder.position_at_end(scan_cond)
        # i scans 0..hay_len-needle_len inclusive, so the limit is a
        # strict-less-than against last_start+1
        idx = builder.load(scan_idx_ptr)
        last_start = builder.sub(hay_len, needle_len)
        keep_going = builder.icmp_signed("<=", idx, last_start)
        builder.cbranch(keep_going, scan_body, miss_block)

        builder.position_at_end(scan_body)
        same = builder.icmp_signed(
            "==",
            builder.call(
                self.memcmp,
                [builder.gep(hay_data, [idx]), needle_data, needle_len],
            ),
            ir.Constant(ir.IntType(32), 0),
        )
        builder.cbranch(same, hit_block, scan_step)

        builder.position_at_end(scan_step)
        builder.store(builder.add(idx, one64), scan_idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(hit_block)
        builder.ret(ir.Constant(ir.IntType(1), 1))

        builder.position_at_end(miss_block)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        # i1 rawdict_has(i8* d, i64 key) - probe without the KeyError panic
        self.rawdict_has = ir.Function(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i64]),
            name="rawdict_has",
        )
        entry = self.rawdict_has.append_basic_block("entry")
        probe_test = self.rawdict_has.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_has.append_basic_block("probe_tomb")
        match_check = self.rawdict_has.append_basic_block("probe_match")
        has_found = self.rawdict_has.append_basic_block("found")
        probe_step = self.rawdict_has.append_basic_block("probe_step")
        has_missing = self.rawdict_has.append_basic_block("missing")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg = self.rawdict_has.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(dfield(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, name="rdh_slot")
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(dfield(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, has_missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.Constant(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(dfield(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, has_found, probe_step)

        builder.position_at_end(has_found)
        builder.ret(ir.Constant(ir.IntType(1), 1))

        builder.position_at_end(probe_step)
        mask_step = builder.load(dfield(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(has_missing)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        def emit_rawdict_probe(name, ret_type, arg_types, on_hit, on_miss):
            """Shared tombstone-skipping probe for rawdict helpers.

            on_hit(builder, func, entry_index) and on_miss(builder, func)
            receive a positioned builder and must ret.
            """
            func = ir.Function(
                self.module,
                ir.FunctionType(ret_type, arg_types),
                name=name,
            )
            entry = func.append_basic_block("entry")
            probe_test = func.append_basic_block("probe_test")
            tomb_or_match = func.append_basic_block("probe_tomb")
            match_check = func.append_basic_block("probe_match")
            hit_block = func.append_basic_block("hit")
            probe_step = func.append_basic_block("probe_step")
            miss_block = func.append_basic_block("miss")
            b = ir.IRBuilder(entry)
            dict_arg, key_arg = func.args[0], func.args[1]
            struct_ptr = b.bitcast(
                dict_arg, ir.PointerType(self.raw_dict_struct_type)
            )
            mask = b.load(dfield(b, struct_ptr, 3))
            probe_slot = b.alloca(i64, name="probe_slot")
            b.store(b.and_(key_arg, mask), probe_slot)
            b.branch(probe_test)

            b.position_at_end(probe_test)
            table_now = b.load(dfield(b, struct_ptr, 4))
            slot_now = b.load(probe_slot)
            slot_entry = b.load(b.gep(table_now, [slot_now]))
            is_empty = b.icmp_signed("==", slot_entry, zero64)
            b.cbranch(is_empty, miss_block, tomb_or_match)

            b.position_at_end(tomb_or_match)
            is_tomb = b.icmp_signed("==", slot_entry, ir.Constant(i64, -1))
            b.cbranch(is_tomb, probe_step, match_check)

            b.position_at_end(match_check)
            entry_index = b.sub(slot_entry, one64)
            keys_now = b.load(dfield(b, struct_ptr, 5))
            stored_key = b.load(b.gep(keys_now, [entry_index]))
            is_match = b.icmp_signed("==", stored_key, key_arg)
            b.cbranch(is_match, hit_block, probe_step)

            b.position_at_end(hit_block)
            hit_slot = table_now
            # on_hit may need the probe slot for tombstoning (pop)
            on_hit(b, func, entry_index, slot_now, hit_slot)

            b.position_at_end(probe_step)
            mask_step = b.load(dfield(b, struct_ptr, 3))
            b.store(b.and_(b.add(slot_now, one64), mask_step), probe_slot)
            b.branch(probe_test)

            b.position_at_end(miss_block)
            on_miss(b, func)
            return func

        def probe_struct(b, func):
            return b.bitcast(
                func.args[0], ir.PointerType(self.raw_dict_struct_type)
            )

        def load_value_at(b, func, entry_index):
            vals_now = b.load(dfield(b, probe_struct(b, func), 6))
            return b.load(b.gep(vals_now, [entry_index]))

        # i64 rawdict_get_or(i8* d, i64 key, i64 default_bits)
        self.rawdict_get_or = emit_rawdict_probe(
            "rawdict_get_or",
            i64,
            [i8p, i64, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                load_value_at(b, func, entry_index)
            ),
            lambda b, func: b.ret(func.args[2]),
        )

        # i64 rawdict_pop_or(i8* d, i64 key, i64 default_bits)
        def pop_or_hit(b, func, entry_index, slot_now, table_now):
            b.store(ir.Constant(i64, -1), b.gep(table_now, [slot_now]))
            struct_ptr = probe_struct(b, func)
            count = b.load(dfield(b, struct_ptr, 0))
            b.store(b.sub(count, one64), dfield(b, struct_ptr, 0))
            b.ret(load_value_at(b, func, entry_index))

        self.rawdict_pop_or = emit_rawdict_probe(
            "rawdict_pop_or",
            i64,
            [i8p, i64, i64],
            pop_or_hit,
            lambda b, func: b.ret(func.args[2]),
        )

        # i64 rawdict_setdefault(i8* d, i64 key, i64 value_bits)
        def setdefault_miss(b, func):
            b.call(self.rawdict_set, [func.args[0], func.args[1], func.args[2]])
            b.ret(func.args[2])

        self.rawdict_setdefault = emit_rawdict_probe(
            "rawdict_setdefault",
            i64,
            [i8p, i64, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                load_value_at(b, func, entry_index)
            ),
            setdefault_miss,
        )

        # void rawdict_clear(i8* d) - keep the table, drop every entry
        self.rawdict_clear = ir.Function(
            self.module, ir.FunctionType(ir.VoidType(), [i8p]),
            name="rawdict_clear",
        )
        builder = ir.IRBuilder(self.rawdict_clear.append_basic_block("entry"))
        (clear_arg,) = self.rawdict_clear.args
        clear_ptr = builder.bitcast(
            clear_arg, ir.PointerType(self.raw_dict_struct_type)
        )
        builder.store(zero64, dfield(builder, clear_ptr, 0))
        builder.store(zero64, dfield(builder, clear_ptr, 1))
        clear_mask = builder.load(dfield(builder, clear_ptr, 3))
        builder.call(
            self.memset,
            [
                builder.bitcast(
                    builder.load(dfield(builder, clear_ptr, 4)), i8p
                ),
                ir.Constant(ir.IntType(8), 0),
                builder.mul(builder.add(clear_mask, one64), ir.Constant(i64, 8)),
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.ret_void()

        # void rawlist_clear(i8* list) - keep capacity, drop elements
        self.rawlist_clear = ir.Function(
            self.module, ir.FunctionType(ir.VoidType(), [i8p]),
            name="rawlist_clear",
        )
        builder = ir.IRBuilder(self.rawlist_clear.append_basic_block("entry"))
        (rl_arg,) = self.rawlist_clear.args
        rl_ptr = builder.bitcast(
            rl_arg, ir.PointerType(self.raw_list_struct_type)
        )
        builder.store(
            zero64, builder.gep(rl_ptr, [zero32, ir.Constant(i32, 0)])
        )
        builder.ret_void()

        # i1 rawlist_contains_bits(i8* list, i64 elem_bits) - linear scan
        # over the machine-word elements (f64 elements compare as bits)
        self.rawlist_contains_bits = ir.Function(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i64]),
            name="rawlist_contains_bits",
        )
        entry = self.rawlist_contains_bits.append_basic_block("entry")
        scan_cond = self.rawlist_contains_bits.append_basic_block("scan_cond")
        scan_body = self.rawlist_contains_bits.append_basic_block("scan_body")
        scan_step = self.rawlist_contains_bits.append_basic_block("scan_step")
        found_block = self.rawlist_contains_bits.append_basic_block("found")
        miss_block = self.rawlist_contains_bits.append_basic_block("miss")
        builder = ir.IRBuilder(entry)
        list_arg, bits_arg = self.rawlist_contains_bits.args
        list_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        list_len = builder.load(
            builder.gep(list_struct, [zero32, ir.Constant(i32, 0)])
        )
        items = builder.bitcast(
            builder.load(builder.gep(list_struct, [zero32, ir.Constant(i32, 2)])),
            ir.PointerType(i64),
        )
        idx_ptr = builder.alloca(i64, name="rlc_i")
        builder.store(zero64, idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(more, scan_body, miss_block)

        builder.position_at_end(scan_body)
        elem = builder.load(builder.gep(items, [idx]))
        is_match = builder.icmp_signed("==", elem, bits_arg)
        builder.cbranch(is_match, found_block, scan_step)

        builder.position_at_end(scan_step)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(found_block)
        builder.ret(ir.Constant(ir.IntType(1), 1))

        builder.position_at_end(miss_block)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        # PyObject* rawstr_to_pystr(i8* s) - boundary box (data copied)
        self.rawstr_to_pystr = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [i8p]),
            name="rawstr_to_pystr",
        )
        builder = ir.IRBuilder(self.rawstr_to_pystr.append_basic_block("entry"))
        (s_arg,) = self.rawstr_to_pystr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = load_len(builder, s_struct)
        s_data = load_data(builder, s_struct)
        box_buffer = builder.call(self.malloc, [s_len])
        builder.call(
            self.memcpy,
            [box_buffer, s_data, s_len, ir.Constant(ir.IntType(1), 0)],
        )
        box_len = builder.trunc(s_len, ir.IntType(32))
        builder.ret(builder.call(self.create_str, [box_buffer, box_len]))

        # i8* pystr_to_rawstr(PyObject* obj) - boundary unbox (copies)
        self.pystr_to_rawstr = ir.Function(
            self.module, ir.FunctionType(i8p, [pyobj_ptr]), name="pystr_to_rawstr"
        )
        entry = self.pystr_to_rawstr.append_basic_block("entry")
        ok_block = self.pystr_to_rawstr.append_basic_block("ok")
        error_block = self.pystr_to_rawstr.append_basic_block("type_error")
        builder = ir.IRBuilder(entry)
        (obj_arg,) = self.pystr_to_rawstr.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_str = builder.icmp_signed("==", tag, ir.Constant(i32, 2))
        builder.cbranch(is_str, ok_block, error_block)

        builder.position_at_end(ok_block)
        inner = builder.load(builder.gep(obj_arg, [zero32, one32b]))
        str_struct = builder.bitcast(inner, ir.PointerType(self.pyobj.string_type))
        box_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        box_data = builder.load(builder.gep(str_struct, [zero32, one32b]))
        wide_len = builder.sext(box_len, i64)
        raw_buffer = builder.call(self.malloc, [wide_len])
        builder.call(
            self.memcpy,
            [raw_buffer, box_data, wide_len, ir.Constant(ir.IntType(1), 0)],
        )
        struct_ptr = build_rawstr(wide_len, wide_len, raw_buffer)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        builder.position_at_end(error_block)
        msg_ptr = builder.gep(type_error_msg, [zero32, zero32])
        builder.call(self.printf, [msg_ptr])
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        # void rawlist_get(i8* list, i64 index, i8* out_ptr, i64 elem_size)
        # Bounds are checked; OOB aborts like list_get.
        self.rawlist_get = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i8p, i64]),
            name="rawlist_get",
        )
        entry = self.rawlist_get.append_basic_block("entry")
        bounds_block = self.rawlist_get.append_basic_block("bounds")
        negative_block = self.rawlist_get.append_basic_block("negative")
        ok_block = self.rawlist_get.append_basic_block("ok")
        error_block = self.rawlist_get.append_basic_block("index_error")
        builder = ir.IRBuilder(entry)
        list_arg, index_arg, out_arg, size_arg = self.rawlist_get.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(field(builder, struct_ptr, 0))
        is_negative = builder.icmp_signed("<", index_arg, zero64)
        builder.cbranch(is_negative, negative_block, bounds_block)

        builder.position_at_end(negative_block)
        adjusted = builder.add(index_arg, length)
        builder.branch(bounds_block)

        builder.position_at_end(bounds_block)
        adj_phi = builder.phi(i64)
        adj_phi.add_incoming(index_arg, entry)
        adj_phi.add_incoming(adjusted, negative_block)
        in_range = builder.icmp_signed("<", adj_phi, length)
        if self.checks:
            builder.cbranch(in_range, ok_block, error_block)
        else:
            builder.branch(ok_block)

        builder.position_at_end(error_block)
        msg = self._create_global_string_with_builder(
            "IndexError: list index out of range\n", builder
        )
        builder.call(self.printf, [msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        items = builder.load(field(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [adj_phi])
        builder.store(builder.load(slot), builder.bitcast(out_arg, ir.PointerType(i64)))
        builder.ret_void()

        # void rawlist_set(i8* list, i64 index, i8* elem_ptr, i64 elem_size)
        self.rawlist_set = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i8p, i64]),
            name="rawlist_set",
        )
        entry = self.rawlist_set.append_basic_block("entry")
        neg_block = self.rawlist_set.append_basic_block("negative")
        bounds_block = self.rawlist_set.append_basic_block("bounds")
        ok_block = self.rawlist_set.append_basic_block("ok")
        error_block = self.rawlist_set.append_basic_block("index_error")
        builder = ir.IRBuilder(entry)
        list_arg, index_arg, elem_arg, size_arg = self.rawlist_set.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(field(builder, struct_ptr, 0))
        builder.cbranch(
            builder.icmp_signed("<", index_arg, zero64), neg_block, bounds_block
        )

        builder.position_at_end(neg_block)
        adjusted = builder.add(index_arg, length)
        builder.branch(bounds_block)

        builder.position_at_end(bounds_block)
        adj_phi = builder.phi(i64)
        adj_phi.add_incoming(index_arg, entry)
        adj_phi.add_incoming(adjusted, neg_block)
        in_range = builder.icmp_signed("<", adj_phi, length)
        if self.checks:
            builder.cbranch(in_range, ok_block, error_block)
        else:
            builder.branch(ok_block)

        builder.position_at_end(error_block)
        msg = self._create_global_string_with_builder(
            "IndexError: list assignment index out of range\n", builder
        )
        builder.call(self.printf, [msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        items = builder.load(field(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [adj_phi])
        elem_bits = builder.load(builder.bitcast(elem_arg, ir.PointerType(i64)))
        builder.store(elem_bits, slot)
        builder.ret_void()

    def _create_unbox_runtime(self):
        """unbox helpers for the typed -> dynamic -> typed boundary."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)

        def emit_unbox(name, out_type, message, convert_payload):
            func = ir.Function(
                self.module, ir.FunctionType(out_type, [pyobj_ptr]), name=name
            )
            entry = func.append_basic_block("entry")
            ok_block = func.append_basic_block("unbox_ok")
            bad_block = func.append_basic_block("unbox_bad")
            builder = ir.IRBuilder(entry)
            (obj_arg,) = func.args
            is_null = builder.icmp_signed("==", obj_arg, ir.Constant(pyobj_ptr, None))
            builder.cbranch(is_null, bad_block, ok_block)

            builder.position_at_end(ok_block)
            tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
            # int and bool payloads both feed i64 conversion
            data = builder.load(builder.gep(obj_arg, [zero32, one32]))
            as_i64 = builder.load(builder.bitcast(data, ir.PointerType(i64)))
            builder.ret(convert_payload(builder, tag, as_i64, data))

            builder.position_at_end(bad_block)
            msg = self._create_global_string_with_builder(message, builder)
            builder.call(self.printf, [msg])
            builder.call(self.exit_func, [ir.Constant(i32, 1)])
            builder.unreachable()
            return func

        self.unbox_int = emit_unbox(
            "unbox_int",
            i64,
            "TypeError: expected an int value\n",
            lambda b, tag, as_i64, data: as_i64,
        )
        self.unbox_float = emit_unbox(
            "unbox_float",
            ir.DoubleType(),
            "TypeError: expected a float value\n",
            lambda b, tag, as_i64, data: b.select(
                b.icmp_signed("==", tag, ir.Constant(i32, 1)),
                b.load(b.bitcast(data, ir.PointerType(ir.DoubleType()))),
                b.sitofp(as_i64, ir.DoubleType()),
            ),
        )
        self.unbox_bool = emit_unbox(
            "unbox_bool",
            ir.IntType(1),
            "TypeError: expected a bool value\n",
            lambda b, tag, as_i64, data: b.icmp_signed(
                "!=", as_i64, ir.Constant(i64, 0)
            ),
        )

    # ================== value plumbing ==================

    @staticmethod
    def _kind_of_llvm_type(kind: str) -> ir.Type:
        if kind == OBJ:
            return ir.PointerType(ir.IntType(8))  # placeholder, unused
        return LLVM_KIND_TYPES[kind]

    def _const_kind(self, value: Any) -> Optional[str]:
        if isinstance(value, bool):
            return I1
        if isinstance(value, int):
            return I64
        if isinstance(value, float):
            return F64
        return None

    def _box(self, tv: Tuple[str, Any]) -> Any:
        """TypedValue -> PyObject* (dynamic world boundary)."""
        kind, value = tv
        if kind == OBJ:
            return value
        if kind in RAWLIST_KINDS:
            return self.current_builder.call(
                self.rawlist_to_pylist,
                [value, self.current_builder.call(self.rawlist_len, [value])],
            )
        if kind in RAWDICT_KINDS:
            converter = (
                self.rawdict_to_pydict_ii
                if kind == RAWDICT_II
                else self.rawdict_to_pydict_if
            )
            return self.current_builder.call(converter, [value])
        if kind == RAWSTR:
            return self.current_builder.call(self.rawstr_to_pystr, [value])
        if kind == I64:
            return self.current_builder.call(self.create_int, [value])
        if kind == F64:
            return self.current_builder.call(self.create_float, [value])
        if kind == I1:
            return self.current_builder.call(self.create_bool, [value])
        raise ValueError(f"unknown kind {kind}")

    def _unbox(self, obj: Any, kind: str) -> Any:
        """PyObject* -> raw value of `kind` (panics on type mismatch)."""
        if kind == I64:
            return self.current_builder.call(self.unbox_int, [obj])
        if kind == F64:
            return self.current_builder.call(self.unbox_float, [obj])
        if kind == I1:
            return self.current_builder.call(self.unbox_bool, [obj])
        if kind == RAWSTR:
            return self.current_builder.call(self.pystr_to_rawstr, [obj])
        raise ValueError(f"cannot unbox into {kind}")

    def _coerce(self, tv: Tuple[str, Any], target: str) -> Tuple[str, Any]:
        """Convert a TypedValue to the target kind."""
        kind, value = tv
        if kind == target:
            if kind == RAWSTR:
                # rawstr slots own their buffers exclusively: storing the
                # same buffer into a second slot would let an in-place
                # append alias, so assignment eagerly copies (Rust String
                # move semantics expressed as value copy)
                return (
                    RAWSTR,
                    self.current_builder.call(self.rawstr_copy, [value]),
                )
            return tv
        if target == OBJ and kind in RAW_STORAGE_KINDS:
            boxed = self._box(tv)
            return (OBJ, boxed)
        if target == OBJ:
            return (OBJ, self._box(tv))
        if kind == OBJ:
            return (target, self._unbox(value, target))
        if kind == I1 and target == I64:
            return (I64, self.current_builder.zext(value, ir.IntType(64)))
        if kind == I64 and target == F64:
            return (F64, self.current_builder.sitofp(value, ir.DoubleType()))
        if kind == F64 and target == I64:
            checked = self.current_builder.fptosi(value, ir.IntType(64))
            if self.checks:
                roundtrip = self.current_builder.sitofp(checked, ir.DoubleType())
                exact = self.current_builder.fcmp_ordered("==", value, roundtrip)
                self._panic_if(exact, "TypeError: float cannot be used as int\n")
            return (I64, checked)
        if kind == I64 and target == I1:
            return (
                I1,
                self.current_builder.icmp_signed(
                    "!=", value, ir.Constant(ir.IntType(64), 0)
                ),
            )
        raise ValueError(f"cannot coerce {kind} to {target}")

    def _panic_if(self, condition: Any, message: str):
        """Abort with message when condition holds."""
        func = self.current_function
        bad_block = func.append_basic_block("panic_bad")
        ok_block = func.append_basic_block("panic_ok")
        self.current_builder.cbranch(condition, bad_block, ok_block)

        self.current_builder.position_at_end(bad_block)
        msg = self._create_global_string_with_builder(message, self.current_builder)
        self.current_builder.call(self.printf, [msg])
        self.current_builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        self.current_builder.unreachable()
        self.current_builder.position_at_end(ok_block)

    def _rawstr_append_operand(self, rhs_node: Any) -> Tuple[Any, Any]:
        """(data_ptr, byte_len) for rawstr_append.

        String literals stream straight from their global constant;
        rawstr values pass their own buffer (append's realloc never
        moves a foreign buffer); anything dynamic is boxed and copied
        out through the unbox boundary first.
        """
        if (
            isinstance(rhs_node, list)
            and len(rhs_node) >= 2
            and rhs_node[0] == "const"
            and isinstance(rhs_node[1], str)
        ):
            text = rhs_node[1]
            return (
                self._create_global_string(text),
                ir.Constant(ir.IntType(64), len(text.encode("utf-8"))),
            )
        tv = self._coerce(self._convert_node(rhs_node), RAWSTR)
        struct_ptr = self.current_builder.bitcast(
            tv[1], ir.PointerType(self.rawstr_struct_type)
        )
        length = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        data = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)],
            )
        )
        return data, length

    def _to_i1_cond(self, tv: Tuple[str, Any]) -> Any:
        """Condition value -> i1 (direct, or Python truthiness for obj)."""
        kind, value = tv
        if kind == I1:
            return value
        if kind == I64:
            return self.current_builder.icmp_signed(
                "!=", value, ir.Constant(ir.IntType(64), 0)
            )
        if kind == F64:
            return self.current_builder.fcmp_ordered(
                "!=", value, ir.Constant(ir.DoubleType(), 0.0)
            )
        if kind == RAWSTR:
            # Python truthiness: the empty string is false
            struct_ptr = self.current_builder.bitcast(
                value, ir.PointerType(self.rawstr_struct_type)
            )
            length = self.current_builder.load(
                self.current_builder.gep(
                    struct_ptr,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
                )
            )
            return self.current_builder.icmp_signed(
                "!=", length, ir.Constant(ir.IntType(64), 0)
            )
        return self._emit_truthiness(value)

    # ================== variables ==================

    def _declare_var(self, name: str, kind: str):
        current_kind = self.var_kinds.get(name)
        if name in self.variables:
            # inside a function, declaring a name that is a module-level
            # global must always shadow it with a fresh alloca - Python
            # makes any assignment a local regardless of type, and reusing
            # the same-kind global slot lets the function clobber a
            # caller's loop counter (same kind does not mean same scope)
            if (
                current_kind == kind
                and (
                    self.current_function is None
                    or self.current_function.name == "main"
                    or name not in getattr(self, "_module_vars", ())
                )
            ):
                return
            # same name, different representation (e.g. a function-local
            # `i: int` shadowing a module-level dynamic `i`): inside a
            # function the local shadows the global with a fresh alloca
            if self.current_function is not None and self.current_function.name != "main":
                del self.variables[name]
            else:
                return
        if self.current_function is not None and self.current_function.name == "main":
            # module scope: names are true globals so functions can see
            # them (Silu has no declarations; top-level assignments are
            # the global definitions)
            if kind == OBJ:
                gv = ir.GlobalVariable(
                    self.module, ir.PointerType(self.pyobj.pyobj_type), name=name
                )
                gv.initializer = ir.Constant(
                    ir.PointerType(self.pyobj.pyobj_type), None
                )
            elif kind in RAW_STORAGE_KINDS:
                gv = ir.GlobalVariable(
                    self.module, ir.PointerType(ir.IntType(8)), name=name
                )
                gv.initializer = ir.Constant(ir.PointerType(ir.IntType(8)), None)
            else:
                gv = ir.GlobalVariable(
                    self.module, LLVM_KIND_TYPES[kind], name=name
                )
                gv.initializer = ir.Constant(LLVM_KIND_TYPES[kind], 0)
            self.variables[name] = gv
        elif kind == OBJ:
            self.variables[name] = self.current_builder.alloca(
                ir.PointerType(self.pyobj.pyobj_type), name=name
            )
        elif kind in RAW_STORAGE_KINDS:
            self.variables[name] = self.current_builder.alloca(
                ir.PointerType(ir.IntType(8)), name=name
            )
        else:
            self.variables[name] = self.current_builder.alloca(
                LLVM_KIND_TYPES[kind], name=name
            )
        self.var_kinds[name] = kind

    def _load_var(self, name: str) -> Tuple[str, Any]:
        if name in self.var_kinds:
            kind = self.var_kinds[name]
            return (kind, self.current_builder.load(self.variables[name]))
        if name in self.variables:
            return (OBJ, self.current_builder.load(self.variables[name]))
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    # ================== arithmetic ==================

    def _promote_pair(self, left: Tuple[str, Any], right: Tuple[str, Any], target: str):
        return self._coerce(left, target), self._coerce(right, target)

    def _typed_binop(self, op: str, left: Tuple[str, Any], right: Tuple[str, Any]):
        if op == "+" and (left[0] == RAWSTR or right[0] == RAWSTR):
            # string concatenation on raw slots: fresh buffer, inputs
            # untouched (t = s + "x" must not disturb s). Raw operands
            # are only read, so they skip the eager-copy coercion.
            def as_rawstr(tv: Tuple[str, Any]):
                if tv[0] == RAWSTR:
                    return tv[1]
                return self._coerce(tv, RAWSTR)[1]

            return (
                RAWSTR,
                self.current_builder.call(
                    self.rawstr_concat, [as_rawstr(left), as_rawstr(right)]
                ),
            )
        if left[0] == OBJ or right[0] == OBJ:
            l_obj = self._box(left)
            r_obj = self._box(right)
            runtime = {
                "+": self.pyobj_add,
                "-": self.pyobj_sub,
                "*": self.pyobj_mul,
                "/": self.pyobj_truediv,
                "//": self.pyobj_floordiv,
                "%": self.pyobj_mod,
            }[op]
            result = self.current_builder.call(runtime, [l_obj, r_obj])
            return (OBJ, result)

        if left[0] == F64 or right[0] == F64:
            (l_kind, l_val), (r_kind, r_val) = self._promote_pair(left, right, F64)
            if op == "+":
                return (F64, self.current_builder.fadd(l_val, r_val))
            if op == "-":
                return (F64, self.current_builder.fsub(l_val, r_val))
            if op == "*":
                return (F64, self.current_builder.fmul(l_val, r_val))
            if op == "/":
                self._panic_if(
                    self.current_builder.fcmp_ordered(
                        "==", r_val, ir.Constant(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero\n",
                )
                return (F64, self.current_builder.fdiv(l_val, r_val))
            if op == "//":
                self._panic_if(
                    self.current_builder.fcmp_ordered(
                        "==", r_val, ir.Constant(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero\n",
                )
                quotient = self.current_builder.fdiv(l_val, r_val)
                return (
                    F64,
                    self.current_builder.call(self.floor_f64, [quotient]),
                )
            if op == "%":
                self._panic_if(
                    self.current_builder.fcmp_ordered(
                        "==", r_val, ir.Constant(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero\n",
                )
                remainder = self.current_builder.frem(l_val, r_val)
                zero = ir.Constant(ir.DoubleType(), 0.0)
                r_ne_zero = self.current_builder.fcmp_ordered("!=", remainder, zero)
                r_negative = self.current_builder.fcmp_ordered("<", remainder, zero)
                right_negative = self.current_builder.fcmp_ordered("<", r_val, zero)
                signs_differ = self.current_builder.xor(r_negative, right_negative)
                adjust = self.current_builder.and_(r_ne_zero, signs_differ)
                return (
                    F64,
                    self.current_builder.select(
                        adjust,
                        self.current_builder.fadd(remainder, r_val),
                        remainder,
                    ),
                )

        # integer path (bools promote to i64)
        (l_kind, l_val), (r_kind, r_val) = self._promote_pair(left, right, I64)
        i64 = ir.IntType(64)
        if op == "+":
            if not self.checks:
                return (I64, self.current_builder.add(l_val, r_val))
            pair = self.current_builder.call(self.sadd_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "add"))
        if op == "-":
            if not self.checks:
                return (I64, self.current_builder.sub(l_val, r_val))
            pair = self.current_builder.call(self.ssub_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "sub"))
        if op == "*":
            if not self.checks:
                return (I64, self.current_builder.mul(l_val, r_val))
            pair = self.current_builder.call(self.smul_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "mul"))
        if op == "/":
            self._panic_if(
                self.current_builder.icmp_signed("==", r_val, ir.Constant(i64, 0)),
                "ZeroDivisionError: division by zero\n",
            )
            l_f = self.current_builder.sitofp(l_val, ir.DoubleType())
            r_f = self.current_builder.sitofp(r_val, ir.DoubleType())
            return (F64, self.current_builder.fdiv(l_f, r_f))
        if op == "//":
            self._panic_if(
                self.current_builder.icmp_signed("==", r_val, ir.Constant(i64, 0)),
                "ZeroDivisionError: division by zero\n",
            )
            return (I64, self._floor_div_inline(l_val, r_val))
        if op == "%":
            self._panic_if(
                self.current_builder.icmp_signed("==", r_val, ir.Constant(i64, 0)),
                "ZeroDivisionError: division by zero\n",
            )
            return (I64, self._py_mod_inline(l_val, r_val))
        raise NotImplementedError(f"typed binop {op}")

    @staticmethod
    def _extract_i64_const(value: Any) -> Optional[int]:
        if isinstance(value, ir.Constant) and isinstance(
            value.type, ir.IntType
        ) and value.type.width == 64:
            return int(value.constant)
        return None

    def _typed_pow(self, left: Tuple[str, Any], right: Tuple[str, Any]):
        """x ** y: int ** int stays int (repeated multiply), float ** 0.5
        takes the sqrt fast path, everything else goes through libc pow."""
        if left[0] == OBJ or right[0] == OBJ:
            boxed_l = self._box(left)
            boxed_r = self._box(right)
            return (OBJ, self.current_builder.call(self.pyobj_pow, [boxed_l, boxed_r]))
        if left[0] == I64 and right[0] == I64:
            # exponentiation by squaring on i64 with overflow check
            i64 = ir.IntType(64)
            builder = self.current_builder
            exp = self._extract_i64_const(right[1])
            if exp is not None and 0 <= exp <= 64:
                result = ir.Constant(i64, 1)
                base = left[1]
                while exp > 0:
                    if exp & 1:
                        pair = builder.call(self.smul_overflow, [result, base])
                        result = self._overflow_checked(pair, "mul")
                    exp >>= 1
                    if exp:
                        pair = builder.call(self.smul_overflow, [base, base])
                        base = self._overflow_checked(pair, "mul")
                if not self.checks:
                    pass
                return (I64, result)
            # general integer pow via libc pow + exactness check
            lf = self._coerce(left, F64)
            rf = self._coerce(right, F64)
            result = builder.call(self.pow_f64, [lf[1], rf[1]])
            as_i64 = builder.fptosi(result, i64)
            roundtrip = builder.sitofp(as_i64, ir.DoubleType())
            exact = builder.fcmp_ordered("==", result, roundtrip)
            self._panic_if(exact, "TypeError: int pow result not exact\n")
            return (I64, as_i64)
        lf = self._coerce(left, F64)
        rf = self._coerce(right, F64)
        is_half = isinstance(right[1], ir.Constant) and float(
            right[1].constant
        ) == 0.5
        if is_half:
            return (F64, self.current_builder.call(self.sqrt_f64, [lf[1]]))
        # general pow via libc
        return (F64, self.current_builder.call(self.pow_f64, [lf[1], rf[1]]))

    def _overflow_checked(self, pair: Any, op: str) -> Any:
        result = self.current_builder.extract_value(pair, 0)
        overflowed = self.current_builder.extract_value(pair, 1)
        self._panic_if(overflowed, f"OverflowError: integer overflow in {op}\n")
        return result

    def _floor_div_inline(self, left: Any, right: Any) -> Any:
        i64 = ir.IntType(64)
        builder = self.current_builder
        quotient = builder.sdiv(left, right)
        remainder = builder.srem(left, right)
        r_ne_zero = builder.icmp_signed("!=", remainder, ir.Constant(i64, 0))
        r_negative = builder.icmp_signed("<", remainder, ir.Constant(i64, 0))
        right_negative = builder.icmp_signed("<", right, ir.Constant(i64, 0))
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adjustment = builder.select(adjust, ir.Constant(i64, -1), ir.Constant(i64, 0))
        return builder.add(quotient, adjustment)

    def _py_mod_inline(self, left: Any, right: Any) -> Any:
        i64 = ir.IntType(64)
        builder = self.current_builder
        remainder = builder.srem(left, right)
        r_ne_zero = builder.icmp_signed("!=", remainder, ir.Constant(i64, 0))
        r_negative = builder.icmp_signed("<", remainder, ir.Constant(i64, 0))
        right_negative = builder.icmp_signed("<", right, ir.Constant(i64, 0))
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adjustment = builder.select(adjust, right, ir.Constant(i64, 0))
        return builder.add(remainder, adjustment)

    def _typed_compare(self, op: str, left: Tuple[str, Any], right: Tuple[str, Any]):
        if left[0] == RAWSTR or right[0] == RAWSTR:
            # raw string comparisons: memcmp semantics, which on UTF-8
            # bytes equals Python's code point ordering
            def as_rawstr(tv: Tuple[str, Any]):
                if tv[0] == RAWSTR:
                    return tv[1]
                return self._coerce(tv, RAWSTR)[1]

            a_ptr = as_rawstr(left)
            b_ptr = as_rawstr(right)
            if op == "==":
                return (I1, self.current_builder.call(self.rawstr_eq, [a_ptr, b_ptr]))
            if op == "!=":
                eq = self.current_builder.call(self.rawstr_eq, [a_ptr, b_ptr])
                return (I1, self.current_builder.not_(eq))
            order = self.current_builder.call(self.rawstr_cmp, [a_ptr, b_ptr])
            zero = ir.Constant(ir.IntType(64), 0)
            return (I1, self.current_builder.icmp_signed(op, order, zero))

        if left[0] == OBJ or right[0] == OBJ:
            l_obj = self._box(left)
            r_obj = self._box(right)
            runtime = {
                "==": self.pyobj_eq,
                "!=": self.pyobj_ne,
                "<": self.pyobj_lt,
                "<=": self.pyobj_le,
                ">": self.pyobj_gt,
                ">=": self.pyobj_ge,
            }[op]
            return (OBJ, self.current_builder.call(runtime, [l_obj, r_obj]))

        target = F64 if left[0] == F64 or right[0] == F64 else I64
        (l_kind, l_val), (r_kind, r_val) = self._promote_pair(left, right, target)
        if target == F64:
            if op == "!=":
                return (I1, self.current_builder.fcmp_unordered("!=", l_val, r_val))
            return (I1, self.current_builder.fcmp_ordered(op, l_val, r_val))
        return (I1, self.current_builder.icmp_signed(op, l_val, r_val))

    def _unsupported_raw_method(self, raw_kind: str, method_name: str):
        """Fail loudly for a method the raw container does not implement:
        the old fallback boxed the whole container and mutated the copy,
        silently discarding the mutation (Rust: no such method)."""
        func = self.current_builder.function
        err_block = func.append_basic_block("raw_method_err")
        cont_block = func.append_basic_block("raw_method_cont")
        self.current_builder.branch(err_block)
        self.current_builder.position_at_end(err_block)
        msg = self._create_global_string_with_builder(
            f"AttributeError: raw {raw_kind} has no method '{method_name}'\n",
            self.current_builder,
        )
        self.current_builder.call(self.printf, [msg])
        self.current_builder.call(
            self.exit_func, [ir.Constant(ir.IntType(32), 1)]
        )
        self.current_builder.unreachable()
        self.current_builder.position_at_end(cont_block)
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    def _typed_contains(self, op: str, item_node: Any, container_node: Any):
        """item in container: native scans for raw containers, boxed
        pyobj_contains for everything else. Result is always i1."""
        container_tv = self._convert_node(container_node)
        if container_tv[0] == RAWSTR:
            needle = self._coerce(self._convert_node(item_node), RAWSTR)
            result = self.current_builder.call(
                self.rawstr_contains, [container_tv[1], needle[1]]
            )
        elif container_tv[0] in RAWDICT_KINDS:
            key = self._coerce(self._convert_node(item_node), I64)[1]
            result = self.current_builder.call(
                self.rawdict_has, [container_tv[1], key]
            )
        elif container_tv[0] in RAWLIST_KINDS:
            elem_kind = RAWLIST_KINDS[container_tv[0]]
            elem = self._coerce(self._convert_node(item_node), elem_kind)
            elem_bits = elem[1]
            if elem_kind == F64:
                # bit-compare: a same-payload NaN matches (CPython's
                # identity shortcut agrees); distinct NaNs compare equal
                # here where CPython would say False
                elem_bits = self.current_builder.bitcast(
                    elem[1], ir.IntType(64)
                )
            result = self.current_builder.call(
                self.rawlist_contains_bits, [container_tv[1], elem_bits]
            )
        else:
            container = self._box(container_tv)
            item = self._box(self._convert_node(item_node))
            result = self.current_builder.call(
                self.pyobj_contains, [container, item]
            )
        if op == "not in":
            result = self.current_builder.not_(result)
        return (I1, result)

    # ================== declarations ==================

    def _annotation_kind(self, node: Any) -> Optional[str]:
        """('name', 'int') -> 'i64'; list[int]/list[float] -> raw lists.

        Returns None for unknown annotations (dynamic PyObject storage).
        """
        if (
            isinstance(node, list)
            and len(node) >= 2
            and node[0] == "name"
            and isinstance(node[1], str)
        ):
            if ANNOTATION_KINDS.get(node[1]) is not None:
                return ANNOTATION_KINDS[node[1]]
            if node[1] == "str":
                # annotated str: raw {len, cap, data} slot (Rust String's
                # ownership model - assignment copies, append grows in
                # place, so Python's immutable-value semantics hold)
                return RAWSTR
            return None
        if (
            isinstance(node, list)
            and len(node) >= 3
            and node[0] == "subscript"
            and isinstance(node[1], list)
            and len(node[1]) >= 2
            and node[1][0] == "name"
            and node[1][1] == "list"
            and isinstance(node[2], list)
            and len(node[2]) >= 2
            and node[2][0] == "name"
        ):
            element = ANNOTATION_KINDS.get(node[2][1])
            if element == I64:
                return RAWLIST_I
            if element == F64:
                return RAWLIST_F
        if (
            isinstance(node, list)
            and len(node) >= 3
            and node[0] == "subscript"
            and isinstance(node[1], list)
            and len(node[1]) >= 2
            and node[1][0] == "name"
            and node[1][1] == "dict"
            and isinstance(node[2], list)
            and node[2][0] == "tuple"
            and len(node[2][1]) == 2
            and all(
                isinstance(part, list)
                and len(part) >= 2
                and part[0] == "name"
                for part in node[2][1]
            )
        ):
            key_annotation, value_annotation = (part[1] for part in node[2][1])
            if key_annotation == "int" and value_annotation == "int":
                return RAWDICT_II
            if key_annotation == "int" and value_annotation == "float":
                return RAWDICT_IF
        return None

    @staticmethod
    def _rawlist_elem_size(kind: str) -> int:
        return 8  # both i64 and double elements are 8 bytes

    # ================== conservative kind inference ==================

    def _kind_resolver(
        self,
        annotations: Dict[str, str],
        candidates: Dict[str, Optional[str]],
        func_ret: Dict[str, str],
    ):
        """Build a resolve() closure over the given name environments.

        Resolution uses only literals, annotated names, names already
        inferred earlier, and outer-scope kinds - never method calls or
        other dynamic values.
        """

        def merge_arith(left: Optional[str], right: Optional[str]) -> Optional[str]:
            if left is None or right is None or left == OBJ or right == OBJ:
                return None
            if left == RAWSTR or right == RAWSTR:
                # concatenation: str + str stays str, anything mixed with
                # a number keeps the name dynamic
                return RAWSTR if left == right else None
            if F64 in (left, right):
                return F64
            return I64  # i1 operands promote like bool arithmetic

        def resolve(node: Any) -> Optional[str]:
            if not isinstance(node, list) or not node:
                return None
            op = node[0]
            if op == "const":
                value = node[1]
                if isinstance(value, bool):
                    return I1
                if isinstance(value, int):
                    return I64
                if isinstance(value, float):
                    return F64
                if isinstance(value, str):
                    return RAWSTR
                return None
            if op == "name":
                name = node[1]
                if name in annotations:
                    return annotations[name]
                if name in candidates:
                    return candidates[name]
                return self.var_kinds.get(name)
            if op == "-" and len(node) == 2:
                return resolve(node[1])
            if op in ("+", "-", "*", "**") and len(node) >= 3:
                return merge_arith(resolve(node[1]), resolve(node[2]))
            if op in ("/", "//", "%") and len(node) >= 3:
                left, right = resolve(node[1]), resolve(node[2])
                if left is None or right is None or OBJ in (left, right):
                    return None
                if op == "/":
                    return F64  # truediv always rebinds to float
                return F64 if F64 in (left, right) else I64
            if op in ("==", "!=", "<", "<=", ">", ">=", "not", "in", "not in"):
                return I1  # comparisons produce a bool whatever the operands
            if op in ("and", "or") and len(node) >= 3:
                left, right = resolve(node[1]), resolve(node[2])
                return left if left == right else None
            if op == "if_expr" and len(node) >= 4:
                then_kind, else_kind = resolve(node[2]), resolve(node[3])
                return then_kind if then_kind == else_kind else None
            if op == "call" and isinstance(node[1], list) and node[1][0] == "name":
                callee = node[1][1]
                if callee == "len":
                    return I64
                return func_ret.get(callee)
            if (
                op == "subscript"
                and isinstance(node[1], list)
                and node[1][0] == "name"
            ):
                base_kind = resolve(node[1])
                if base_kind == RAWLIST_I:
                    return I64
                if base_kind == RAWLIST_F:
                    return F64
                if base_kind == RAWSTR:
                    return RAWSTR  # s[i] / s[a:b] both yield str
            return None

        return resolve

    def _infer_assign_kinds(
        self, stmts: list, param_kinds: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """Kinds for unannotated names whose every assignment in this
        scope provably yields one and the same raw scalar kind.

        Resolution uses only literals, annotated names, names already
        inferred earlier in the walk, and outer-scope kinds - never
        method calls or other dynamic values. Any unknown operand or
        kind conflict marks the name as PyObject storage, so Python's
        rebind-a-name-to-any-type behaviour stays untouched (e.g.
        ``x = 7`` then ``x = x / 2`` must keep x dynamic because the
        truediv rebinding produces a float).
        """
        annotations: Dict[str, str] = dict(param_kinds or {})
        candidates: Dict[str, Optional[str]] = {}
        func_ret: Dict[str, str] = {}
        for func_name, func_def in self.function_defs.items():
            ret_kind = (
                self._annotation_kind(func_def[5]) if len(func_def) > 5 else None
            )
            if ret_kind:
                func_ret[func_name] = ret_kind
        # functions promoted to a raw ABI by cross-function inference
        # return raw values too
        for func_name, (_params, ret_kind, _func) in self.static_funcs.items():
            if ret_kind:
                func_ret[func_name] = ret_kind

        resolve = self._kind_resolver(annotations, candidates, func_ret)

        def add(name: str, kind: Optional[str]):
            if name in annotations:
                return  # declared kind always wins
            if kind not in (I64, F64, I1, RAWSTR):
                kind = None
            if name not in candidates:
                candidates[name] = kind
            elif candidates[name] != kind:
                candidates[name] = None  # conflict: keep it dynamic

        def is_range_call(iter_node: Any) -> bool:
            return (
                isinstance(iter_node, list)
                and len(iter_node) >= 3
                and iter_node[0] == "call"
                and isinstance(iter_node[1], list)
                and len(iter_node[1]) >= 2
                and iter_node[1][0] == "name"
                and iter_node[1][1] == "range"
            )

        def walk(stmt_list: list):
            for stmt in stmt_list if isinstance(stmt_list, list) else []:
                if not isinstance(stmt, list) or not stmt:
                    continue
                op = stmt[0]
                if op == "assign" and isinstance(stmt[1], str):
                    add(stmt[1], resolve(stmt[2]))
                elif op == "ann_assign" and isinstance(stmt[1], str):
                    kind = self._annotation_kind(stmt[3])
                    if kind:
                        annotations[stmt[1]] = kind
                elif op == "aug_assign" and isinstance(stmt[1], str):
                    current = annotations.get(stmt[1])
                    if current is None:
                        current = candidates.get(
                            stmt[1], self.var_kinds.get(stmt[1])
                        )
                    if current == resolve(stmt[3]):
                        add(stmt[1], current)
                    else:
                        add(stmt[1], None)
                elif op == "for":
                    iter_kind = I64 if is_range_call(stmt[2]) else None
                    if iter_kind is None:
                        resolved = resolve(stmt[2])
                        if resolved == RAWLIST_I:
                            iter_kind = I64
                        elif resolved == RAWLIST_F:
                            iter_kind = F64
                        elif resolved == RAWSTR:
                            iter_kind = RAWSTR  # for ch in s: 1-byte str
                    # the IR spells assign targets as bare names but for
                    # targets as name nodes; accept both
                    if isinstance(stmt[1], str):
                        target_name = stmt[1]
                    elif (
                        isinstance(stmt[1], list)
                        and len(stmt[1]) >= 2
                        and stmt[1][0] == "name"
                    ):
                        target_name = stmt[1][1]
                    else:
                        target_name = None
                    if target_name is not None:
                        # None (dynamic iteration) must also register:
                        # the loop rebinds the target and blocks inference
                        add(target_name, iter_kind)
                    walk(stmt[3])
                elif op == "if" and len(stmt) >= 4:
                    walk(stmt[2])
                    walk(stmt[3])
                elif op == "while" and len(stmt) >= 3:
                    walk(stmt[2])
                # func_def bodies are separate scopes; other statements
                # introduce no assignments in this scope

        walk(stmts)
        return {
            name: kind for name, kind in candidates.items() if kind is not None
        }

    def _collect_function_defs(self, node):
        """Also stash the module statement list for signature inference."""
        if isinstance(node, list) and len(node) >= 2 and node[0] == "module":
            self._module_stmt_list = node[1]
        super()._collect_function_defs(node)

    def _infer_function_signatures(self):
        """Two-pass cross-function kind propagation.

        Pass 1: an unannotated parameter that is never rebound in the
        body takes the raw kind when every call site in the module
        passes one and the same raw scalar kind for it.
        Pass 2: an unannotated return takes the raw kind when every
        return expression resolves to one and the same kind (params +
        locals inferred). Resolution never uses other functions'
        inferred returns, so recursion and call order stay harmless.
        """
        annotated_ret: Dict[str, str] = {}
        for name, func_def in self.function_defs.items():
            ret_annotation = func_def[5] if len(func_def) > 5 else None
            kind = self._annotation_kind(ret_annotation)
            if kind:
                annotated_ret[name] = kind

        module_kinds = self._infer_assign_kinds(self._module_stmt_list)
        module_resolver = self._kind_resolver({}, dict(module_kinds), annotated_ret)

        # every call to a known function, scanning into nested
        # expressions (x = f(1) + 2) and all function bodies
        calls: Dict[str, list] = {name: [] for name in self.function_defs}

        def scan(node: Any):
            if not isinstance(node, (list, tuple)):
                return
            if (
                len(node) >= 3
                and node[0] == "call"
                and isinstance(node[1], (list, tuple))
                and len(node[1]) >= 2
                and node[1][0] == "name"
                and node[1][1] in calls
            ):
                keywords = node[3] if len(node) > 3 else ()
                calls[node[1][1]].append((node[2], keywords))
            for child in node:
                scan(child)

        scan(self._module_stmt_list)
        for func_def in self.function_defs.values():
            scan(func_def[3] if len(func_def) > 3 else [])

        def rebound_names(stmts: list, sink: set):
            for stmt in stmts if isinstance(stmts, list) else []:
                if not isinstance(stmt, (list, tuple)) or not stmt:
                    continue
                op = stmt[0]
                if op in ("assign", "ann_assign", "aug_assign"):
                    if isinstance(stmt[1], str):
                        sink.add(stmt[1])
                elif op == "for" and len(stmt) >= 4:
                    target = stmt[1]
                    if isinstance(target, str):
                        sink.add(target)
                    elif (
                        isinstance(target, (list, tuple))
                        and len(target) >= 2
                        and target[0] == "name"
                    ):
                        sink.add(target[1])
                    rebound_names(stmt[3], sink)
                elif op == "if" and len(stmt) >= 4:
                    rebound_names(stmt[2], sink)
                    rebound_names(stmt[3], sink)
                elif op == "while" and len(stmt) >= 3:
                    rebound_names(stmt[2], sink)
                elif op == "func_def":
                    # a nested def rebinds its own name here; its body
                    # is a separate scope
                    if len(stmt) >= 2 and isinstance(stmt[1], str):
                        sink.add(stmt[1])

        def find_returns(stmts: list, sink: list):
            for stmt in stmts if isinstance(stmts, list) else []:
                if not isinstance(stmt, (list, tuple)) or not stmt:
                    continue
                if stmt[0] == "return":
                    sink.append(stmt[1] if len(stmt) > 1 else None)
                elif stmt[0] == "if" and len(stmt) >= 4:
                    find_returns(stmt[2], sink)
                    find_returns(stmt[3], sink)
                elif stmt[0] == "while" and len(stmt) >= 3:
                    find_returns(stmt[2], sink)
                elif stmt[0] == "for" and len(stmt) >= 4:
                    find_returns(stmt[3], sink)

        sigs: Dict[str, Tuple[List[str], Optional[str]]] = {}
        for name, func_def in self.function_defs.items():
            params = func_def[2] if len(func_def) > 2 else []
            param_annotations = func_def[4] if len(func_def) > 4 else ()
            body = func_def[3] if len(func_def) > 3 else []

            rebound: set = set()
            rebound_names(body, rebound)

            param_kinds: List[str] = []
            for index, pname in enumerate(params):
                annotation = (
                    param_annotations[index]
                    if index < len(param_annotations)
                    else None
                )
                kind = self._annotation_kind(annotation)
                if kind is None and pname not in rebound and calls[name]:
                    inferred: Optional[str] = None
                    ok = True
                    for args, keywords in calls[name]:
                        if keywords or len(args) != len(params):
                            ok = False
                            break
                        arg_kind = module_resolver(args[index])
                        if arg_kind not in (I64, F64, I1, RAWSTR):
                            ok = False
                            break
                        if inferred is None:
                            inferred = arg_kind
                        elif inferred != arg_kind:
                            ok = False
                            break
                    if ok and inferred is not None:
                        kind = inferred
                param_kinds.append(kind if kind is not None else OBJ)

            ret_kind = annotated_ret.get(name)
            if ret_kind is None:
                param_env = {
                    p: k for p, k in zip(params, param_kinds) if k != OBJ
                }
                local_kinds = self._infer_assign_kinds(body, param_env)
                body_resolver = self._kind_resolver(
                    param_env, dict(local_kinds), annotated_ret
                )
                returns: list = []
                find_returns(body, returns)
                inferred_ret: Optional[str] = None
                ok = bool(returns)
                for rexpr in returns:
                    if rexpr is None:
                        ok = False  # bare return yields None
                        break
                    rk = body_resolver(rexpr)
                    if rk is None:
                        ok = False
                        break
                    if inferred_ret is None:
                        inferred_ret = rk
                    elif inferred_ret != rk:
                        ok = False
                        break
                if ok and inferred_ret is not None:
                    ret_kind = inferred_ret

            sigs[name] = (param_kinds, ret_kind)
        return sigs

    def _dynamic_param_kinds(self, func_def: list) -> List[str]:
        """Parameter kinds for an unannotated function: annotations on
        individual parameters (list[int] etc.) still apply."""
        param_annotations = func_def[4] if len(func_def) > 4 else ()
        kinds = []
        for index, _param in enumerate(func_def[2]):
            annotation = (
                param_annotations[index] if index < len(param_annotations) else None
            )
            kind = self._annotation_kind(annotation)
            if kind is None:
                kind = OBJ
            kinds.append(kind)
        return kinds

    def _static_signature(self, func_def: list):
        """Return (param_kinds, ret_kind) when fully annotated numeric."""
        param_annotations = func_def[4] if len(func_def) > 4 else ()
        ret_annotation = func_def[5] if len(func_def) > 5 else None
        params = func_def[2]
        kinds = []
        for index, _param in enumerate(params):
            annotation = (
                param_annotations[index] if index < len(param_annotations) else None
            )
            kind = self._annotation_kind(annotation)
            if kind is None:
                return None, None
            kinds.append(kind)
        if ret_annotation is None:
            return None, None
        ret_kind = self._annotation_kind(ret_annotation)
        if ret_kind is None:
            return None, None
        return kinds, ret_kind

    def _create_function_declarations(self):
        """Create raw-ABI functions for annotated ones, PyObject otherwise.

        Cross-function inference (call sites + return expressions) can
        promote an unannotated function to the raw ABI the same way
        written annotations do; a function that stays dynamic-return
        still gets raw-typed parameters when inference proves them.
        """
        self._inferred_sigs = self._infer_function_signatures()
        for func_name, func_def in self.function_defs.items():
            # sigs merge written annotations with inference results
            param_kinds, ret_kind = self._inferred_sigs[func_name]
            if ret_kind is not None and all(kind != OBJ for kind in param_kinds):
                param_types = [LLVM_KIND_TYPES[k] for k in param_kinds]
                func_ty = ir.FunctionType(LLVM_KIND_TYPES[ret_kind], param_types)
                func = ir.Function(self.module, func_ty, name=func_name)
                self.static_funcs[func_name] = (param_kinds, ret_kind, func)
            else:
                dyn_kinds = param_kinds
                self._dyn_func_kinds[func_name] = dyn_kinds
                param_types = []
                for kind in dyn_kinds:
                    if kind != OBJ:
                        param_types.append(LLVM_KIND_TYPES[kind])
                    else:
                        param_types.append(
                            ir.PointerType(self.pyobj.pyobj_type)
                        )
                func_ty = ir.FunctionType(
                    ir.PointerType(self.pyobj.pyobj_type), param_types
                )
                func = ir.Function(self.module, func_ty, name=func_name)
                self.functions[func_name] = func

    def _generate_function_bodies(self):
        for func_name, func_def in self.function_defs.items():
            if func_name in self.static_funcs:
                param_kinds, ret_kind, func = self.static_funcs[func_name]
                self._generate_typed_function_body(
                    func, func_def, param_kinds, ret_kind
                )
            else:
                func = self.functions[func_name]
                self._generate_dynamic_function_body(func, func_def)

    def _generate_typed_function_body(
        self,
        func: ir.Function,
        func_def: list,
        param_kinds: List[str],
        ret_kind: str,
    ):
        entry_block = func.append_basic_block("entry")
        old_function = self.current_function
        old_builder = self.current_builder
        old_variables = self.variables.copy()
        old_kinds = dict(self.var_kinds)
        old_ret = self.current_ret_kind
        old_inferred = self._inferred_kinds

        self.current_function = func
        self.current_builder = ir.IRBuilder(entry_block)
        self.current_ret_kind = ret_kind
        self._inferred_kinds = self._infer_assign_kinds(
            func_def[3],
            {
                name: kind
                for name, kind in zip(func_def[2], param_kinds)
                if kind != OBJ
            },
        )
        # keep module-level variables visible (they act as globals);
        # remember which names are function-local so we can pop them on
        # exit - a local kind must never leak into other functions
        self._scope_depth = getattr(self, "_scope_depth", 0) + 1
        if self._scope_depth == 1:
            self._module_vars = set(self.variables.keys())
            self._module_kinds = set(self.var_kinds.keys())
        self.variables = dict(self.variables)
        self.var_kinds = dict(self.var_kinds)

        for index, param_name in enumerate(func_def[2]):
            kind = param_kinds[index]
            # parameters always shadow: delete any inherited entry so
            # _declare_var allocates a fresh function-local slot
            self.variables.pop(param_name, None)
            self.var_kinds.pop(param_name, None)
            self._declare_var(param_name, kind)
            self.current_builder.store(func.args[index], self.variables[param_name])

        for stmt in func_def[3]:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            if ret_kind == RAWSTR:
                # missing return: an empty owned string, never a null
                # pointer (slots must stay dereferenceable)
                empty_ptr = self._create_global_string("")
                self.current_builder.ret(
                    self.current_builder.call(
                        self.rawstr_new_copy,
                        [empty_ptr, ir.Constant(ir.IntType(64), 0)],
                    )
                )
            else:
                zero = {
                    I64: ir.Constant(ir.IntType(64), 0),
                    F64: ir.Constant(ir.DoubleType(), 0.0),
                    I1: ir.Constant(ir.IntType(1), 0),
                }[ret_kind]
                self.current_builder.ret(zero)

        self.current_function = old_function
        self.current_builder = old_builder
        self.variables = old_variables
        self.var_kinds = old_kinds
        self.current_ret_kind = old_ret
        self._inferred_kinds = old_inferred
        self._scope_depth = getattr(self, "_scope_depth", 1) - 1

    def _generate_dynamic_function_body(self, func: ir.Function, func_def: list):
        """PyObject-ABI function body (unannotated functions)."""
        entry_block = func.append_basic_block("entry")
        old_function = self.current_function
        old_builder = self.current_builder
        old_variables = self.variables.copy()
        old_kinds = dict(self.var_kinds)
        old_ret = self.current_ret_kind
        old_inferred = self._inferred_kinds

        self.current_function = func
        self.current_builder = ir.IRBuilder(entry_block)
        self.current_ret_kind = None
        self._scope_depth = getattr(self, "_scope_depth", 0) + 1
        if self._scope_depth == 1:
            self._module_vars = set(self.variables.keys())
            self._module_kinds = set(self.var_kinds.keys())
        self.variables = dict(self.variables)
        self.var_kinds = dict(self.var_kinds)

        param_kinds_dyn = self._dyn_func_kinds.get(
            func_def[1], self._dynamic_param_kinds(func_def)
        )
        self._inferred_kinds = self._infer_assign_kinds(
            func_def[3],
            {
                name: kind
                for name, kind in zip(func_def[2], param_kinds_dyn)
            },
        )
        for index, param_name in enumerate(func_def[2]):
            if index < len(func.args):
                kind = param_kinds_dyn[index]
                if kind != OBJ:
                    # raw-ABI parameter: store the value in a typed alloca
                    param_alloca = self.current_builder.alloca(
                        LLVM_KIND_TYPES[kind], name=param_name
                    )
                    self.current_builder.store(func.args[index], param_alloca)
                    self.variables[param_name] = param_alloca
                    self.var_kinds[param_name] = kind
                    continue
                param_alloca = self.current_builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type), name=param_name
                )
                self.current_builder.store(func.args[index], param_alloca)
                self.variables[param_name] = param_alloca
                self.var_kinds[param_name] = OBJ

        for stmt in func_def[3]:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            null_val = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
            self.current_builder.ret(null_val)

        self.current_function = old_function
        self.current_builder = old_builder
        self.variables = old_variables
        self.var_kinds = old_kinds
        self.current_ret_kind = old_ret
        self._inferred_kinds = old_inferred
        self._scope_depth = getattr(self, "_scope_depth", 1) - 1

    # ================== statement / expression dispatch ==================

    def _convert_node(self, node: Any, skip_func_defs: bool = False) -> Tuple[str, Any]:
        """Convert an IR node, returning a TypedValue (kind, llvm value)."""
        if not isinstance(node, list) or len(node) == 0:
            return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        op = node[0]
        null_obj = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)

        if op == "module":
            self._inferred_kinds = self._infer_assign_kinds(
                node[1] if len(node) > 1 else []
            )
            for stmt in node[1] if len(node) > 1 else []:
                self._convert_node(stmt, skip_func_defs)
            return (OBJ, null_obj)

        if op == "const":
            value = node[1]
            if value is None:
                return (OBJ, null_obj)
            kind = self._const_kind(value)
            if kind is None and isinstance(value, (tuple, list, dict)):
                # (), [] and {} literals-as-constants degrade to the
                # dynamic runtime constructors
                if isinstance(value, dict):
                    obj = self.current_builder.call(self.create_dict, [])
                    for k, v in value.items():
                        key_tv = self._convert_node(["const", k])
                        val_tv = self._convert_node(["const", v])
                        self.current_builder.call(
                            self.dict_set,
                            [obj, self._box(key_tv), self._box(val_tv)],
                        )
                    return (OBJ, obj)
                obj = self.current_builder.call(self.create_list, [])
                for element in value:
                    elem_tv = self._convert_node(["const", element])
                    self.current_builder.call(
                        self.list_append, [obj, self._box(elem_tv)]
                    )
                return (OBJ, obj)
            if kind == I1:
                return (I1, ir.Constant(ir.IntType(1), value))
            if kind == I64:
                return (I64, ir.Constant(ir.IntType(64), value))
            if kind == F64:
                return (F64, ir.Constant(ir.DoubleType(), value))
            str_len = len(value.encode('utf-8'))  # bytes, matches the utf-8 global
            str_ptr = self._create_global_string(value)
            return (
                OBJ,
                self.current_builder.call(
                    self.create_str, [str_ptr, ir.Constant(ir.IntType(32), str_len)]
                ),
            )

        if op == "name":
            return self._load_var(node[1])

        if op in ("assign", "ann_assign"):
            target = node[1]
            value_node = node[2]
            if op == "ann_assign" and value_node is None:
                return (OBJ, null_obj)
            if op == "ann_assign":
                annotation_kind = self._annotation_kind(node[3]) or OBJ
            else:
                annotation_kind = self.var_kinds.get(target)
            if annotation_kind is None and target not in self.var_kinds:
                # unannotated rebinding: raw storage only when the
                # pre-pass proved every assignment yields one same kind
                annotation_kind = self._inferred_kinds.get(target) or OBJ
            if (
                annotation_kind == RAWSTR
                and isinstance(target, str)
                and isinstance(value_node, list)
                and len(value_node) >= 3
                and value_node[0] == "+"
                and isinstance(value_node[1], list)
                and value_node[1][0] == "name"
                and value_node[1][1] == target
            ):
                # s = s + rhs: the slot owns its buffer and the old value
                # dies here, so append in place (amortized O(1)) instead
                # of a fresh quadratic copy. A rhs naming s itself goes
                # through rawstr_concat: append's realloc could move the
                # buffer out from under its own source.
                data_ptr, byte_len = self._rawstr_append_operand(value_node[2])
                slot_value = self._load_var(target)[1]
                self.current_builder.call(
                    self.rawstr_append, [slot_value, data_ptr, byte_len]
                )
                self._declare_var(target, RAWSTR)
                return (RAWSTR, slot_value)
            if (
                annotation_kind in RAWLIST_KINDS
                and isinstance(value_node, list)
                and len(value_node) >= 3
                and value_node[0] == "*"
                and isinstance(value_node[1], list)
                and value_node[1][0] == "list"
            ):
                # [init] * count into a rawlist variable: constant counts
                # expand at compile time, runtime counts use a fill loop
                elem_nodes = value_node[1][1] if len(value_node[1]) > 1 else []
                count_tv = self._convert_node(value_node[2])
                count_const = self._extract_i64_const(count_tv[1])
                if count_const is not None:
                    expanded: list = []
                    for _ in range(count_const):
                        expanded.extend(elem_nodes)
                    raw = self._build_raw_list(expanded, annotation_kind)
                    self._declare_var(target, annotation_kind)
                    self.current_builder.store(raw[1], self.variables[target])
                    return raw
                # runtime count: create the list then push in a loop
                raw = self.current_builder.call(
                    self.rawlist_new, [ir.Constant(ir.IntType(64), 8)]
                )
                count_i64 = self._coerce(count_tv, I64)[1]
                raw_ptr = self.current_builder.alloca(
                    ir.PointerType(ir.IntType(8)), name="fill_list"
                )
                self.current_builder.store(raw, raw_ptr)
                fill_idx = self.current_builder.alloca(
                    ir.IntType(64), name="fill_i"
                )
                self.current_builder.store(ir.Constant(ir.IntType(64), 0), fill_idx)
                fill_cond = self.current_function.append_basic_block("fill_cond")
                fill_body = self.current_function.append_basic_block("fill_body")
                fill_end = self.current_function.append_basic_block("fill_end")
                self.current_builder.branch(fill_cond)

                self.current_builder.position_at_end(fill_cond)
                fill_i = self.current_builder.load(fill_idx)
                fill_more = self.current_builder.icmp_signed("<", fill_i, count_i64)
                self.current_builder.cbranch(fill_more, fill_body, fill_end)

                self.current_builder.position_at_end(fill_body)
                for element_node in elem_nodes:
                    elem = self._coerce(
                        self._convert_node(element_node), RAWLIST_KINDS[annotation_kind]
                    )
                    elem_bits = elem[1]
                    if RAWLIST_KINDS[annotation_kind] == F64:
                        elem_bits = self.current_builder.bitcast(
                            elem[1], ir.IntType(64)
                        )
                    self.current_builder.call(
                        self.rawlist_push,
                        [
                            self.current_builder.load(raw_ptr),
                            elem_bits,
                        ],
                    )
                self.current_builder.store(
                    self.current_builder.add(fill_i, ir.Constant(ir.IntType(64), 1)),
                    fill_idx,
                )
                self.current_builder.branch(fill_cond)

                self.current_builder.position_at_end(fill_end)
                self._declare_var(target, annotation_kind)
                self.current_builder.store(raw, self.variables[target])
                return (annotation_kind, raw)
            if (
                annotation_kind in RAWLIST_KINDS
                and isinstance(value_node, list)
                and len(value_node) >= 1
                and value_node[0] == "list"
            ):
                raw = self._build_raw_list(value_node[1], annotation_kind)
                self._declare_var(target, annotation_kind)
                self.current_builder.store(raw[1], self.variables[target])
                return raw
            if (
                annotation_kind in RAWDICT_KINDS
                and isinstance(value_node, list)
                and len(value_node) >= 1
                and value_node[0] == "dict"
            ):
                raw_ptr = self.current_builder.call(self.rawdict_new, [])
                value_kind = RAWDICT_KINDS[annotation_kind]
                for pair_node in value_node[1]:
                    key_tv = self._coerce(
                        self._convert_node(pair_node[0]), I64
                    )
                    val_tv = self._coerce(
                        self._convert_node(pair_node[1]), value_kind
                    )
                    val_bits = val_tv[1]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            val_tv[1], ir.IntType(64)
                        )
                    self.current_builder.call(
                        self.rawdict_set,
                        [raw_ptr, key_tv[1], val_bits],
                    )
                self._declare_var(target, annotation_kind)
                self.current_builder.store(raw_ptr, self.variables[target])
                return (annotation_kind, raw_ptr)
            value = self._convert_node(value_node)
            if isinstance(target, str) and value[1] is not None:
                coerced = self._coerce(value, annotation_kind)
                self._declare_var(target, annotation_kind)
                self.current_builder.store(coerced[1], self.variables[target])
                return coerced
            return (OBJ, null_obj)

        if op == "aug_assign":
            bin_op = node[2][:-1]  # "+=" -> "+"
            target_node = node[1]
            right_tv = self._convert_node(node[3])

            # subscript target: obj[i] <op>= value
            if (
                isinstance(target_node, list)
                and len(target_node) >= 3
                and target_node[0] == "subscript"
            ):
                obj_tv = self._convert_node(target_node[1])
                key_tv = self._convert_node(target_node[2])
                if obj_tv[0] in RAWLIST_KINDS:
                    elem_kind = RAWLIST_KINDS[obj_tv[0]]
                    index = self._coerce(key_tv, I64)[1]
                    # read-modify-write on the raw element
                    items = self.current_builder.load(
                        self.current_builder.gep(
                            self.current_builder.bitcast(
                                obj_tv[1],
                                ir.PointerType(self.raw_list_struct_type),
                            ),
                            [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), 2),
                            ],
                        )
                    )
                    items_i64 = self.current_builder.bitcast(
                        items, ir.PointerType(ir.IntType(64))
                    )
                    slot = self.current_builder.gep(items_i64, [index])
                    current = (elem_kind, self.current_builder.load(slot))
                    if elem_kind == F64:
                        current = (
                            F64,
                            self.current_builder.bitcast(current[1], ir.DoubleType()),
                        )
                    result = self._typed_binop(bin_op, current, right_tv)
                    coerced = self._coerce(result, elem_kind)
                    stored = coerced[1]
                    if elem_kind == F64:
                        stored = self.current_builder.bitcast(
                            stored, ir.IntType(64)
                        )
                    self.current_builder.store(stored, slot)
                    return coerced
                if obj_tv[0] in RAWDICT_KINDS:
                    # d[k] <op>= v: lookup, combine, store back
                    value_kind = RAWDICT_KINDS[obj_tv[0]]
                    key = self._coerce(key_tv, I64)[1]
                    current_bits = self.current_builder.call(
                        self.rawdict_get, [obj_tv[1], key]
                    )
                    if value_kind == F64:
                        current_tv = (
                            F64,
                            self.current_builder.bitcast(
                                current_bits, ir.DoubleType()
                            ),
                        )
                    else:
                        current_tv = (value_kind, current_bits)
                    result = self._typed_binop(bin_op, current_tv, right_tv)
                    coerced = self._coerce(result, value_kind)
                    stored_bits = coerced[1]
                    if value_kind == F64:
                        stored_bits = self.current_builder.bitcast(
                            coerced[1], ir.IntType(64)
                        )
                    self.current_builder.call(
                        self.rawdict_set, [obj_tv[1], key, stored_bits]
                    )
                    return coerced
                obj = self._box(obj_tv)
                key = self._box(key_tv)
                current_obj = self.current_builder.call(
                    self.pyobj_subscript, [obj, key]
                )
                result = self._typed_binop(
                    bin_op, (OBJ, current_obj), right_tv
                )
                value = self._box(result)
                self.current_builder.call(
                    self.pyobj_subscript_set, [obj, key, value]
                )
                return (OBJ, value)

            # plain variable target
            target_name = target_node[1]
            if target_name not in self.var_kinds and target_name not in self.variables:
                return (OBJ, null_obj)
            if self.var_kinds.get(target_name) == RAWSTR:
                # s += rhs grows the owned buffer in place; a rhs naming
                # s itself must take the fresh-concat path (append's
                # realloc would move the buffer under its own source)
                if isinstance(node[3], list) and node[3][:2] == ["name", target_name]:
                    current = self._load_var(target_name)
                    result = self._typed_binop("+", current, right_tv)
                    coerced = self._coerce(result, RAWSTR)
                    self.current_builder.store(
                        coerced[1], self.variables[target_name]
                    )
                    return coerced
                data_ptr, byte_len = self._rawstr_append_operand(node[3])
                slot_value = self._load_var(target_name)[1]
                self.current_builder.call(
                    self.rawstr_append, [slot_value, data_ptr, byte_len]
                )
                return (RAWSTR, slot_value)
            current = self._load_var(target_name)
            result = self._typed_binop(bin_op, current, right_tv)
            coerced = self._coerce(result, self.var_kinds[target_name])
            self.current_builder.store(coerced[1], self.variables[target_name])
            return coerced

        if op == "-" and len(node) == 2:
            # unary minus (checked before the binary dispatch)
            operand = self._convert_node(node[1])
            if operand[0] == OBJ:
                boxed = self._box(operand)
                return (OBJ, self._create_unary_minus(boxed))
            if operand[0] == F64:
                return (
                    F64,
                    self.current_builder.fsub(
                        ir.Constant(ir.DoubleType(), 0.0), operand[1]
                    ),
                )
            _, value = self._coerce(operand, I64)
            if not self.checks:
                return (
                    I64,
                    self.current_builder.sub(ir.Constant(ir.IntType(64), 0), value),
                )
            pair = self.current_builder.call(
                self.ssub_overflow,
                [
                    ir.Constant(ir.IntType(64), 0),
                    value,
                ],
            )
            return (I64, self._overflow_checked(pair, "sub"))

        if op == "**" and len(node) >= 3:
            return self._typed_pow(
                self._convert_node(node[1]), self._convert_node(node[2])
            )

        if op in ("+", "-", "*", "/", "//", "%") and len(node) >= 3:
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])
            return self._typed_binop(op, left, right)

        if op in ("==", "!=", "<", "<=", ">", ">="):
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])
            return self._typed_compare(op, left, right)

        if op in ("in", "not in") and len(node) >= 3:
            return self._typed_contains(op, node[1], node[2])

        if op == "not":
            operand = self._convert_node(node[1])
            cond = self._to_i1_cond(operand)
            return (I1, self.current_builder.not_(cond))

        if op in ("and", "or"):
            return self._convert_bool_chain(op, node[1:])

        if op == "if_expr":
            cond = self._to_i1_cond(self._convert_node(node[1]))
            then_block = self.current_function.append_basic_block("iexpr_then")
            else_block = self.current_function.append_basic_block("iexpr_else")
            merge_block = self.current_function.append_basic_block("iexpr_merge")
            self.current_builder.cbranch(cond, then_block, else_block)

            self.current_builder.position_at_end(then_block)
            then_val = self._convert_node(node[2])
            if not self.current_builder.block.is_terminated:
                self.current_builder.branch(merge_block)

            self.current_builder.position_at_end(else_block)
            else_val = self._convert_node(node[3])
            if not self.current_builder.block.is_terminated:
                self.current_builder.branch(merge_block)

            self.current_builder.position_at_end(merge_block)
            common = (
                then_val[0]
                if then_val[0] == else_val[0]
                else (F64 if F64 in (then_val[0], else_val[0]) else OBJ)
            )
            then_v = self._coerce(then_val, common)[1]
            else_v = self._coerce(else_val, common)[1]
            phi_type = (
                LLVM_KIND_TYPES[common]
                if common != OBJ
                else ir.PointerType(self.pyobj.pyobj_type)
            )
            phi = self.current_builder.phi(phi_type)
            phi.add_incoming(then_v, then_block)
            phi.add_incoming(else_v, else_block)
            return (common, phi)

        if op == "call":
            return self._convert_call(node)

        if op == "if":
            if len(node) >= 4:
                cond = self._to_i1_cond(self._convert_node(node[1]))
                then_block = self.current_function.append_basic_block("if_then")
                else_block = self.current_function.append_basic_block("if_else")
                merge_block = self.current_function.append_basic_block("if_merge")
                self.current_builder.cbranch(cond, then_block, else_block)

                self.current_builder.position_at_end(then_block)
                for stmt in node[2]:
                    self._convert_node(stmt)
                    if self.current_builder.block.is_terminated:
                        break
                if not self.current_builder.block.is_terminated:
                    self.current_builder.branch(merge_block)

                self.current_builder.position_at_end(else_block)
                for stmt in node[3]:
                    self._convert_node(stmt)
                    if self.current_builder.block.is_terminated:
                        break
                if not self.current_builder.block.is_terminated:
                    self.current_builder.branch(merge_block)

                self.current_builder.position_at_end(merge_block)
            return (OBJ, null_obj)

        if op == "while":
            if len(node) >= 3:
                cond_block = self.current_function.append_basic_block("while_cond")
                body_block = self.current_function.append_basic_block("while_body")
                end_block = self.current_function.append_basic_block("while_end")
                self.current_builder.branch(cond_block)

                self.current_builder.position_at_end(cond_block)
                cond = self._to_i1_cond(self._convert_node(node[1]))
                self.current_builder.cbranch(cond, body_block, end_block)

                self.loop_break_blocks.append(end_block)
                self.loop_continue_blocks.append(cond_block)
                self.current_builder.position_at_end(body_block)
                for stmt in node[2]:
                    self._convert_node(stmt)
                    if self.current_builder.block.is_terminated:
                        break
                self.loop_break_blocks.pop()
                self.loop_continue_blocks.pop()
                if not self.current_builder.block.is_terminated:
                    self.current_builder.branch(cond_block)

                self.current_builder.position_at_end(end_block)
            return (OBJ, null_obj)

        if op == "break":
            if self.loop_break_blocks:
                self.current_builder.branch(self.loop_break_blocks[-1])
            return (OBJ, null_obj)

        if op == "continue":
            if self.loop_continue_blocks:
                self.current_builder.branch(self.loop_continue_blocks[-1])
            return (OBJ, null_obj)

        if op == "for":
            if len(node) >= 4:
                return self._convert_for(node)
            return (OBJ, null_obj)

        if op == "func_def":
            return (OBJ, null_obj)

        if op == "return":
            if self.current_ret_kind is not None:
                value = self._convert_node(node[1]) if len(node) > 1 else None
                if value is None:
                    if self.current_ret_kind == RAWSTR:
                        empty_ptr = self._create_global_string("")
                        self.current_builder.ret(
                            self.current_builder.call(
                                self.rawstr_new_copy,
                                [empty_ptr, ir.Constant(ir.IntType(64), 0)],
                            )
                        )
                        return (RAWSTR, null_obj)
                    zero = {
                        I64: ir.Constant(ir.IntType(64), 0),
                        F64: ir.Constant(ir.DoubleType(), 0.0),
                        I1: ir.Constant(ir.IntType(1), 0),
                    }[self.current_ret_kind]
                    self.current_builder.ret(zero)
                    return (OBJ, null_obj)
                coerced = self._coerce(value, self.current_ret_kind)
                self.current_builder.ret(coerced[1])
                return coerced
            # dynamic function: box and return the PyObject
            if len(node) > 1 and node[1] is not None:
                value = self._convert_node(node[1])
                self.current_builder.ret(self._box(value))
            else:
                self.current_builder.ret(null_obj)
            return (OBJ, null_obj)

        if op == "list":
            list_obj = self.current_builder.call(self.create_list, [])
            for elem_node in node[1] if len(node) > 1 else []:
                elem = self._convert_node(elem_node)
                self.current_builder.call(self.list_append, [list_obj, self._box(elem)])
            return (OBJ, list_obj)

        if op == "dict":
            dict_obj = self.current_builder.call(self.create_dict, [])
            for pair_node in node[1] if len(node) > 1 else []:
                key = self._convert_node(pair_node[0])
                value = self._convert_node(pair_node[1])
                self.current_builder.call(
                    self.dict_set, [dict_obj, self._box(key), self._box(value)]
                )
            return (OBJ, dict_obj)

        if op == "tuple":
            # same runtime representation as the dynamic backend
            tuple_obj = self.current_builder.call(self.create_list, [])
            for elem_node in node[1] if len(node) > 1 else []:
                elem = self._convert_node(elem_node)
                self.current_builder.call(
                    self.list_append, [tuple_obj, self._box(elem)]
                )
            return (OBJ, tuple_obj)

        if op == "subscript":
            if len(node) >= 3:
                obj_tv = self._convert_node(node[1])
                key_tv = self._convert_node(node[2])
                if obj_tv[0] in RAWLIST_KINDS:
                    elem_kind = RAWLIST_KINDS[obj_tv[0]]
                    index = self._coerce(key_tv, I64)[1]
                    # inline load: negative indices adjust by +length
                    # (Python semantics), out-of-range still panics via
                    # the bounds branch below. No function call keeps the
                    # surrounding loop vectorizable.
                    struct_ptr = self.current_builder.bitcast(
                        obj_tv[1], ir.PointerType(self.raw_list_struct_type)
                    )
                    length = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), 0),
                            ],
                        )
                    )
                    items = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), 2),
                            ],
                        )
                    )
                    is_negative = self.current_builder.icmp_signed(
                        "<", index, ir.Constant(ir.IntType(64), 0)
                    )
                    adjusted = self.current_builder.add(index, length)
                    index_eff = self.current_builder.select(
                        is_negative, adjusted, index
                    )
                    in_range = self.current_builder.icmp_signed(
                        "<", index_eff, length
                    )
                    if self.checks:
                        ok_block = self.current_function.append_basic_block("get_ok")
                        err_block = self.current_function.append_basic_block("get_err")
                        self.current_builder.cbranch(in_range, ok_block, err_block)

                        self.current_builder.position_at_end(err_block)
                        msg = self._create_global_string_with_builder(
                            "IndexError: list index out of range\n",
                            self.current_builder,
                        )
                        self.current_builder.call(self.printf, [msg])
                        self.current_builder.call(
                            self.exit_func, [ir.Constant(ir.IntType(32), 1)]
                        )
                        self.current_builder.unreachable()

                        self.current_builder.position_at_end(ok_block)
                    items_i64 = self.current_builder.bitcast(
                        items, ir.PointerType(ir.IntType(64))
                    )
                    element = self.current_builder.load(
                        self.current_builder.gep(items_i64, [index_eff])
                    )
                    if elem_kind == F64:
                        element = self.current_builder.bitcast(
                            element, ir.DoubleType()
                        )
                    return (elem_kind, element)
                if obj_tv[0] in RAWDICT_KINDS:
                    # machine-word lookup; rawdict_get panics KeyError
                    # on a missing key (Python raises, Rust panics)
                    key = self._coerce(key_tv, I64)[1]
                    val_bits = self.current_builder.call(
                        self.rawdict_get, [obj_tv[1], key]
                    )
                    value_kind = RAWDICT_KINDS[obj_tv[0]]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            val_bits, ir.DoubleType()
                        )
                    return (value_kind, val_bits)
                if obj_tv[0] == RAWSTR:
                    key_node = node[2]
                    if (
                        isinstance(key_node, list)
                        and len(key_node) >= 4
                        and key_node[0] == "slice"
                    ):
                        lower_node, upper_node, step_node = (
                            key_node[1],
                            key_node[2],
                            key_node[3],
                        )
                        if step_node is not None:
                            is_one = (
                                isinstance(step_node, list)
                                and len(step_node) >= 2
                                and step_node[0] == "const"
                                and step_node[1] == 1
                            )
                            if not is_one:
                                # stepped str slices: box the string and
                                # use the PyObject slice helper (it owns
                                # both step directions and the bounds
                                # defaults)
                                i64t = ir.IntType(64)
                                has_lo = ir.Constant(
                                    ir.IntType(1), lower_node is not None
                                )
                                has_hi = ir.Constant(
                                    ir.IntType(1), upper_node is not None
                                )
                                lo = (
                                    ir.Constant(i64t, 0)
                                    if lower_node is None
                                    else self._coerce(
                                        self._convert_node(lower_node), I64
                                    )[1]
                                )
                                hi = (
                                    ir.Constant(i64t, 0)
                                    if upper_node is None
                                    else self._coerce(
                                        self._convert_node(upper_node), I64
                                    )[1]
                                )
                                step = self._coerce(
                                    self._convert_node(step_node), I64
                                )[1]
                                boxed = self._box(obj_tv)
                                return (
                                    OBJ,
                                    self.current_builder.call(
                                        self.pyobj_str_slice,
                                        [boxed, lo, hi, step, has_lo, has_hi],
                                    ),
                                )
                        struct_ptr = self.current_builder.bitcast(
                            obj_tv[1],
                            ir.PointerType(self.rawstr_struct_type),
                        )
                        str_len = self.current_builder.load(
                            self.current_builder.gep(
                                struct_ptr,
                                [
                                    ir.Constant(ir.IntType(32), 0),
                                    ir.Constant(ir.IntType(32), 0),
                                ],
                            )
                        )
                        lo = (
                            ir.Constant(ir.IntType(64), 0)
                            if lower_node is None
                            else self._coerce(
                                self._convert_node(lower_node), I64
                            )[1]
                        )
                        hi = (
                            str_len
                            if upper_node is None
                            else self._coerce(
                                self._convert_node(upper_node), I64
                            )[1]
                        )
                        return (
                            RAWSTR,
                            self.current_builder.call(
                                self.rawstr_slice, [obj_tv[1], lo, hi]
                            ),
                        )
                    index = self._coerce(key_tv, I64)[1]
                    return (
                        RAWSTR,
                        self.current_builder.call(
                            self.rawstr_char_at, [obj_tv[1], index]
                        ),
                    )
                obj = self._box(obj_tv)
                key = self._box(key_tv)
                return (
                    OBJ,
                    self.current_builder.call(self.pyobj_subscript, [obj, key]),
                )
            return (OBJ, null_obj)

        if op == "subscript_assign":
            if len(node) >= 4:
                obj_tv = self._convert_node(node[1])
                if obj_tv[0] in RAWLIST_KINDS:
                    elem_kind = RAWLIST_KINDS[obj_tv[0]]
                    index = self._coerce(self._convert_node(node[2]), I64)[1]
                    value = self._coerce(self._convert_node(node[3]), elem_kind)
                    # inline store: negative indices adjust by +length
                    # (Python semantics); the bounds branch is emitted
                    # only under SILU_CHECKS. No call keeps the
                    # surrounding loop vectorizable (spectral-norm
                    # writes out[i] in its inner loop).
                    struct_ptr = self.current_builder.bitcast(
                        obj_tv[1], ir.PointerType(self.raw_list_struct_type)
                    )
                    length = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), 0),
                            ],
                        )
                    )
                    items = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), 2),
                            ],
                        )
                    )
                    is_negative = self.current_builder.icmp_signed(
                        "<", index, ir.Constant(ir.IntType(64), 0)
                    )
                    adjusted = self.current_builder.add(index, length)
                    index_eff = self.current_builder.select(
                        is_negative, adjusted, index
                    )
                    if self.checks:
                        in_range = self.current_builder.icmp_signed(
                            "<", index_eff, length
                        )
                        ok_block = self.current_function.append_basic_block("set_ok")
                        err_block = self.current_function.append_basic_block("set_err")
                        self.current_builder.cbranch(in_range, ok_block, err_block)

                        self.current_builder.position_at_end(err_block)
                        msg = self._create_global_string_with_builder(
                            "IndexError: list assignment index out of range\n",
                            self.current_builder,
                        )
                        self.current_builder.call(self.printf, [msg])
                        self.current_builder.call(
                            self.exit_func, [ir.Constant(ir.IntType(32), 1)]
                        )
                        self.current_builder.unreachable()

                        self.current_builder.position_at_end(ok_block)
                    items_i64 = self.current_builder.bitcast(
                        items, ir.PointerType(ir.IntType(64))
                    )
                    elem_bits = value[1]
                    if elem_kind == F64:
                        elem_bits = self.current_builder.bitcast(
                            value[1], ir.IntType(64)
                        )
                    self.current_builder.store(
                        elem_bits,
                        self.current_builder.gep(items_i64, [index_eff]),
                    )
                    return (OBJ, null_obj)
                if obj_tv[0] in RAWDICT_KINDS:
                    key = self._coerce(self._convert_node(node[2]), I64)[1]
                    value_kind = RAWDICT_KINDS[obj_tv[0]]
                    value = self._coerce(self._convert_node(node[3]), value_kind)
                    val_bits = value[1]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            value[1], ir.IntType(64)
                        )
                    self.current_builder.call(
                        self.rawdict_set, [obj_tv[1], key, val_bits]
                    )
                    return (OBJ, null_obj)
                obj = self._box(obj_tv)
                key = self._box(self._convert_node(node[2]))
                value = self._box(self._convert_node(node[3]))
                self.current_builder.call(self.pyobj_subscript_set, [obj, key, value])
            return (OBJ, null_obj)

        if op == "delete":
            # del obj[key]: raw dicts tombstone natively; everything else
            # goes through the dynamic dict_pop (KeyError when missing,
            # matching Python's del)
            if len(node) >= 3:
                obj_tv = self._convert_node(node[1])
                if obj_tv[0] in RAWDICT_KINDS:
                    key = self._coerce(self._convert_node(node[2]), I64)[1]
                    self.current_builder.call(
                        self.rawdict_del, [obj_tv[1], key]
                    )
                    return (OBJ, null_obj)
                obj = self._box(obj_tv)
                key = self._box(self._convert_node(node[2]))
                popped = self.current_builder.call(self.dict_pop, [obj, key])
                is_null = self.current_builder.icmp_signed(
                    "==",
                    self.current_builder.ptrtoint(popped, ir.IntType(64)),
                    ir.Constant(ir.IntType(64), 0),
                )
                ok_block = self.current_builder.function.append_basic_block(
                    "del_ok"
                )
                err_block = self.current_builder.function.append_basic_block(
                    "del_keyerr"
                )
                self.current_builder.cbranch(is_null, err_block, ok_block)
                self.current_builder.position_at_end(err_block)
                err_msg = self._create_global_string("KeyError: key not found\n")
                self.current_builder.call(self.printf, [err_msg])
                self.current_builder.call(
                    self.exit_func, [ir.Constant(ir.IntType(32), 1)]
                )
                self.current_builder.unreachable()
                self.current_builder.position_at_end(ok_block)
            return (OBJ, null_obj)

        if op == "tuple_assign":
            if len(node) >= 3:
                targets = node[1]
                value_node = node[2]
                if (
                    isinstance(value_node, list)
                    and len(value_node) >= 2
                    and value_node[0] == "tuple"
                ):
                    elements = value_node[1] if len(value_node) > 1 else []
                    evaluated = [self._convert_node(e) for e in elements]
                    for index, target in enumerate(targets):
                        if index >= len(evaluated) or not isinstance(target, str):
                            continue
                        kind = self.var_kinds.get(target, OBJ)
                        coerced = self._coerce(evaluated[index], kind)
                        self._declare_var(target, kind)
                        self.current_builder.store(coerced[1], self.variables[target])
            return (OBJ, null_obj)

        # unknown op: degrade to dynamic null
        return (OBJ, null_obj)

    def _convert_bool_chain(self, op: str, operand_nodes: list) -> Tuple[str, Any]:
        """N-ary short-circuit and/or over TypedValues."""
        is_and = op == "and"
        operand_kinds = [self._static_kind_of(n) for n in operand_nodes]
        all_i1 = all(k == I1 for k in operand_kinds)

        result_ptr = self.current_builder.alloca(
            ir.IntType(1) if all_i1 else ir.PointerType(self.pyobj.pyobj_type),
            name="sc_result",
        )
        end_block = self.current_function.append_basic_block("sc_end")

        for index, operand_node in enumerate(operand_nodes):
            value = self._convert_node(operand_node)
            last = index == len(operand_nodes) - 1
            if last:
                stored = self._coerce(value, I1 if all_i1 else OBJ)
                self.current_builder.store(stored[1], result_ptr)
                self.current_builder.branch(end_block)
                break
            truthy = self._to_i1_cond(value)
            finish_block = self.current_function.append_basic_block("sc_finish")
            next_block = self.current_function.append_basic_block("sc_next")
            if is_and:
                self.current_builder.cbranch(truthy, next_block, finish_block)
            else:
                self.current_builder.cbranch(truthy, finish_block, next_block)

            self.current_builder.position_at_end(finish_block)
            stored = self._coerce(value, I1 if all_i1 else OBJ)
            self.current_builder.store(stored[1], result_ptr)
            self.current_builder.branch(end_block)
            self.current_builder.position_at_end(next_block)

        self.current_builder.position_at_end(end_block)
        result = self.current_builder.load(result_ptr)
        return (I1 if all_i1 else OBJ, result)

    def _static_kind_of(self, node: Any) -> str:
        """Best-effort static kind of an expression node (no inference:
        only annotations, names already declared, and literal types)."""
        if not isinstance(node, list) or len(node) == 0:
            return OBJ
        if node[0] == "const":
            return self._const_kind(node[1]) or OBJ
        if node[0] == "name" and node[1] in self.var_kinds:
            return self.var_kinds[node[1]]
        return OBJ

    def _convert_for(self, node: list) -> Tuple[str, Any]:
        target_node, iter_node, body_stmts = node[1], node[2], node[3]

        is_range_iter = (
            isinstance(iter_node, list)
            and len(iter_node) >= 3
            and iter_node[0] == "call"
            and isinstance(iter_node[1], list)
            and len(iter_node[1]) >= 2
            and iter_node[1][0] == "name"
            and iter_node[1][1] == "range"
        )

        if not is_range_iter:
            return self._convert_list_for_loop(target_node, iter_node, body_stmts)

        args_node = iter_node[2] if len(iter_node) > 2 else []
        if len(args_node) == 1:
            start = ir.Constant(ir.IntType(64), 0)
            stop = self._coerce(self._convert_node(args_node[0]), I64)[1]
        elif len(args_node) >= 2:
            start = self._coerce(self._convert_node(args_node[0]), I64)[1]
            stop = self._coerce(self._convert_node(args_node[1]), I64)[1]
        else:
            start = ir.Constant(ir.IntType(64), 0)
            stop = ir.Constant(ir.IntType(64), 10)

        i64 = ir.IntType(64)
        loop_init = self.current_function.append_basic_block("loop_init")
        loop_cond = self.current_function.append_basic_block("loop_cond")
        loop_body = self.current_function.append_basic_block("loop_body")
        loop_end = self.current_function.append_basic_block("loop_end")
        incr_block = self.current_function.append_basic_block("loop_incr")

        counter_ptr = self.current_builder.alloca(i64, name="range_counter")
        self.current_builder.store(start, counter_ptr)
        self.current_builder.branch(loop_init)
        # loop_init kept for block ordering parity with the dynamic backend
        self.current_builder.position_at_end(loop_init)
        self.current_builder.branch(loop_cond)

        self.current_builder.position_at_end(loop_cond)
        counter = self.current_builder.load(counter_ptr)
        cond = self.current_builder.icmp_signed("<", counter, stop)
        self.current_builder.cbranch(cond, loop_body, loop_end)

        self.loop_break_blocks.append(loop_end)
        self.loop_continue_blocks.append(incr_block)
        self.current_builder.position_at_end(loop_body)

        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            if var_name in self.var_kinds and self.var_kinds[var_name] not in (
                I64,
                I1,
            ):
                # existing dynamic variable (e.g. i = "init" earlier):
                # box the counter into its PyObject slot per iteration
                boxed = self.current_builder.call(self.create_int, [counter])
                self.current_builder.store(boxed, self.variables[var_name])
            else:
                self._declare_var(var_name, I64)
                self.current_builder.store(counter, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.Constant(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(loop_cond)

        self.current_builder.position_at_end(loop_end)
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    def _convert_rawlist_for_loop(
        self, target_node: Any, list_tv: Tuple[str, Any], body_stmts: list
    ) -> Tuple[str, Any]:
        """for x in raw_list: x loads as an unboxed element."""
        i64 = ir.IntType(64)
        elem_kind = RAWLIST_KINDS[list_tv[0]]
        list_ptr = list_tv[1]

        cond_block = self.current_function.append_basic_block("riter_cond")
        body_block = self.current_function.append_basic_block("riter_body")
        incr_block = self.current_function.append_basic_block("riter_incr")
        end_block = self.current_function.append_basic_block("riter_end")

        counter_ptr = self.current_builder.alloca(i64, name="riter_idx")
        self.current_builder.store(ir.Constant(i64, 0), counter_ptr)
        list_len = self.current_builder.call(self.rawlist_len, [list_ptr])
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(cond_block)
        index = self.current_builder.load(counter_ptr)
        more = self.current_builder.icmp_signed("<", index, list_len)
        self.current_builder.cbranch(more, body_block, end_block)

        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(incr_block)

        self.current_builder.position_at_end(body_block)
        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            # items/length snapshots are loop-invariant here (body may read
            # but this fast path assumes no list mutation during iteration,
            # matching Python's de-facto contract); a hoistable load lets
            # clang vectorize the surrounding loop
            struct_ptr = self.current_builder.bitcast(
                list_ptr, ir.PointerType(self.raw_list_struct_type)
            )
            items = self.current_builder.load(
                self.current_builder.gep(
                    struct_ptr,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)],
                )
            )
            items_i64 = self.current_builder.bitcast(
                items, ir.PointerType(ir.IntType(64))
            )
            element = self.current_builder.load(
                self.current_builder.gep(items_i64, [index])
            )
            if elem_kind == F64:
                element = self.current_builder.bitcast(element, ir.DoubleType())
            self._declare_var(var_name, elem_kind)
            self.current_builder.store(element, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.Constant(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    def _convert_rawstr_for_loop(
        self, target_node: Any, str_tv: Tuple[str, Any], body_stmts: list
    ) -> Tuple[str, Any]:
        """for ch in raw_str: ch is a fresh 1-byte rawstr per iteration
        (byte semantics - ASCII equals Python's code-point iteration)."""
        i64 = ir.IntType(64)
        str_ptr = str_tv[1]

        cond_block = self.current_function.append_basic_block("siter_cond")
        body_block = self.current_function.append_basic_block("siter_body")
        incr_block = self.current_function.append_basic_block("siter_incr")
        end_block = self.current_function.append_basic_block("siter_end")

        counter_ptr = self.current_builder.alloca(i64, name="siter_idx")
        self.current_builder.store(ir.Constant(i64, 0), counter_ptr)
        struct_ptr = self.current_builder.bitcast(
            str_ptr, ir.PointerType(self.rawstr_struct_type)
        )
        str_len = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(cond_block)
        index = self.current_builder.load(counter_ptr)
        more = self.current_builder.icmp_signed("<", index, str_len)
        self.current_builder.cbranch(more, body_block, end_block)

        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(incr_block)

        self.current_builder.position_at_end(body_block)
        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            ch = self.current_builder.call(
                self.rawstr_char_at, [str_ptr, index]
            )
            self._declare_var(var_name, RAWSTR)
            self.current_builder.store(ch, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.Constant(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    def _build_raw_list(self, element_nodes: list, kind: str) -> Tuple[str, Any]:
        """[a, b, c] literal stored into a rawlist-typed variable."""
        i8p = ir.PointerType(ir.IntType(8))
        elem_kind = RAWLIST_KINDS[kind]
        elem_size = self._rawlist_elem_size(kind)
        list_ptr = self.current_builder.call(
            self.rawlist_new,
            [ir.Constant(ir.IntType(64), elem_size)],
        )
        for element_node in element_nodes:
            elem = self._coerce(self._convert_node(element_node), elem_kind)
            elem_bits = elem[1]
            if elem_kind == F64:
                elem_bits = self.current_builder.bitcast(elem[1], ir.IntType(64))
            self.current_builder.call(self.rawlist_push, [list_ptr, elem_bits])
        return (kind, list_ptr)

    def _convert_list_for_loop(
        self, target_node: Any, iter_node: Any, body_stmts: list
    ) -> Tuple[str, Any]:
        i64 = ir.IntType(64)
        iter_tv = self._convert_node(iter_node)
        if iter_tv[0] in RAWLIST_KINDS:
            return self._convert_rawlist_for_loop(target_node, iter_tv, body_stmts)
        if iter_tv[0] == RAWSTR:
            return self._convert_rawstr_for_loop(target_node, iter_tv, body_stmts)
        list_obj = self._box(iter_tv)
        if list_obj is None:
            return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        cond_block = self.current_function.append_basic_block("iter_cond")
        body_block = self.current_function.append_basic_block("iter_body")
        incr_block = self.current_function.append_basic_block("iter_incr")
        end_block = self.current_function.append_basic_block("iter_end")

        counter_ptr = self.current_builder.alloca(i64, name="iter_idx")
        self.current_builder.store(ir.Constant(i64, 0), counter_ptr)
        list_len = self.current_builder.call(self.list_length, [list_obj])
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(cond_block)
        index = self.current_builder.load(counter_ptr)
        more = self.current_builder.icmp_signed("<", index, list_len)
        self.current_builder.cbranch(more, body_block, end_block)

        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(incr_block)

        self.current_builder.position_at_end(body_block)
        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            item = self.current_builder.call(
                self.list_get,
                [list_obj, self.current_builder.call(self.create_int, [index])],
            )
            if var_name in self.var_kinds and self.var_kinds[var_name] != OBJ:
                existing = self.var_kinds[var_name]
                coerced = self._coerce((OBJ, item), existing)
                self.current_builder.store(coerced[1], self.variables[var_name])
            else:
                self._declare_var(var_name, OBJ)
                self.current_builder.store(item, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.Constant(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

    def _convert_call(self, node: list) -> Tuple[str, Any]:
        func_node = node[1]
        args_node = node[2] if len(node) > 2 else []

        # method calls stay fully dynamic
        if (
            isinstance(func_node, list)
            and len(func_node) >= 3
            and func_node[0] == "attribute"
        ):
            method_name = func_node[2]
            raw_obj_tv = self._convert_node(func_node[1])
            raw_kind = raw_obj_tv[0]
            if raw_kind in RAWLIST_KINDS:
                elem_kind = RAWLIST_KINDS[raw_kind]
                elem_size = self._rawlist_elem_size(raw_kind)
                list_ptr = raw_obj_tv[1]
                if method_name == "append" and args_node:
                    elem = self._coerce(self._convert_node(args_node[0]), elem_kind)
                    elem_bits = elem[1]
                    if elem_kind == F64:
                        # doubles travel as their bit pattern (8 bytes)
                        elem_bits = self.current_builder.bitcast(
                            elem[1], ir.IntType(64)
                        )
                    self.current_builder.call(
                        self.rawlist_push,
                        [list_ptr, elem_bits],
                    )
                    return (raw_kind, list_ptr)
                if method_name == "len":
                    return (
                        I64,
                        self.current_builder.call(self.rawlist_len, [list_ptr]),
                    )
                if method_name == "pop" and not args_node:
                    return (
                        elem_kind,
                        self.current_builder.call(self.rawlist_pop, [list_ptr]),
                    )
                if method_name == "clear" and not args_node:
                    self.current_builder.call(self.rawlist_clear, [list_ptr])
                    return (OBJ, ir.Constant(
                        ir.PointerType(self.pyobj.pyobj_type), None
                    ))
                return self._unsupported_raw_method(raw_kind, method_name)
            if raw_kind in RAWDICT_KINDS:
                value_kind = RAWDICT_KINDS[raw_kind]

                def dict_value_bits(value_node):
                    value = self._coerce(self._convert_node(value_node), value_kind)
                    bits = value[1]
                    if value_kind == F64:
                        bits = self.current_builder.bitcast(
                            value[1], ir.IntType(64)
                        )
                    return bits

                def bits_to_value(bits):
                    if value_kind == F64:
                        return (
                            F64,
                            self.current_builder.bitcast(bits, ir.DoubleType()),
                        )
                    return (I64, bits)

                if method_name == "pop" and args_node:
                    key = self._coerce(self._convert_node(args_node[0]), I64)[1]
                    if len(args_node) == 1:
                        # pop(k): rawdict_del panics KeyError when missing
                        bits = self.current_builder.call(
                            self.rawdict_del, [raw_obj_tv[1], key]
                        )
                    elif len(args_node) == 2:
                        bits = self.current_builder.call(
                            self.rawdict_pop_or,
                            [
                                raw_obj_tv[1],
                                key,
                                dict_value_bits(args_node[1]),
                            ],
                        )
                    else:
                        bits = None
                    if bits is not None:
                        return bits_to_value(bits)
                if method_name == "get" and args_node:
                    key = self._coerce(self._convert_node(args_node[0]), I64)[1]
                    if len(args_node) == 2:
                        bits = self.current_builder.call(
                            self.rawdict_get_or,
                            [
                                raw_obj_tv[1],
                                key,
                                dict_value_bits(args_node[1]),
                            ],
                        )
                        return bits_to_value(bits)
                    if len(args_node) == 1:
                        # get(k): value when present, None (null) otherwise
                        present = self.current_builder.call(
                            self.rawdict_has, [raw_obj_tv[1], key]
                        )
                        func = self.current_builder.function
                        hit_block = func.append_basic_block("get_hit")
                        miss_block = func.append_basic_block("get_miss")
                        merge_block = func.append_basic_block("get_merge")
                        self.current_builder.cbranch(
                            present, hit_block, miss_block
                        )
                        self.current_builder.position_at_end(hit_block)
                        bits = self.current_builder.call(
                            self.rawdict_get, [raw_obj_tv[1], key]
                        )
                        boxed_hit = self._box(bits_to_value(bits))
                        self.current_builder.branch(merge_block)
                        self.current_builder.position_at_end(miss_block)
                        self.current_builder.branch(merge_block)
                        self.current_builder.position_at_end(merge_block)
                        result = self.current_builder.phi(
                            ir.PointerType(self.pyobj.pyobj_type)
                        )
                        result.add_incoming(boxed_hit, hit_block)
                        result.add_incoming(
                            ir.Constant(
                                ir.PointerType(self.pyobj.pyobj_type), None
                            ),
                            miss_block,
                        )
                        return (OBJ, result)
                if method_name == "setdefault" and len(args_node) == 2:
                    key = self._coerce(self._convert_node(args_node[0]), I64)[1]
                    bits = self.current_builder.call(
                        self.rawdict_setdefault,
                        [raw_obj_tv[1], key, dict_value_bits(args_node[1])],
                    )
                    return bits_to_value(bits)
                if method_name == "clear" and not args_node:
                    self.current_builder.call(
                        self.rawdict_clear, [raw_obj_tv[1]]
                    )
                    return (OBJ, ir.Constant(
                        ir.PointerType(self.pyobj.pyobj_type), None
                    ))
                return self._unsupported_raw_method(raw_kind, method_name)
            obj = self._box(raw_obj_tv)
            method_map = {
                "append": (self.list_append, 1, True),
                "reverse": (self.list_reverse, 0, True),
                "insert": (self.list_insert, 2, True),
                "count": (self.list_count, 1, True),
                "copy": (self.list_copy, 0, True),
                "clear": (self.pyobj_clear, 0, False),
                "upper": (self.str_upper, 0, True),
                "lower": (self.str_lower, 0, True),
                "find": (self.str_find, 1, True),
                "rfind": (self.str_rfind, 1, True),
                "get": (self.dict_get_or, 2, True),
                "setdefault": (self.dict_setdefault, 2, True),
                "pop": (self.dict_pop, 1, True),
                "__getitem__": (self.dict_get_or, 2, True),
                "__setitem__": (self.dict_set, 2, False),
                "__delitem__": (self.dict_pop, 1, False),
            }
            entry = method_map.get(method_name)
            if obj is not None and entry:
                func, arg_count, has_result = entry
                arg_vals = [
                    self._box(self._convert_node(arg)) for arg in args_node[:arg_count]
                ]
                while len(arg_vals) < arg_count:
                    arg_vals.append(
                        ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
                    )
                if len(arg_vals) == arg_count and all(arg_vals):
                    result = self.current_builder.call(func, [obj] + arg_vals)
                    return (OBJ, result) if has_result else (OBJ, result)
            return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        if (
            isinstance(func_node, list)
            and len(func_node) >= 2
            and func_node[0] == "name"
        ):
            func_name = func_node[1]

            if func_name == "print":
                if args_node:
                    for index, arg_node in enumerate(args_node):
                        if index > 0:
                            sep = self._create_global_string(" ")
                            self.current_builder.call(self.printf, [sep])
                        boxed = self._box(self._convert_node(arg_node))
                        if boxed is not None:
                            self.current_builder.call(self.pyobj_print, [boxed])
                newline_fmt = self._create_global_string("\n")
                self.current_builder.call(self.printf, [newline_fmt])
                return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

            if func_name == "len":
                if args_node:
                    arg_tv = self._convert_node(args_node[0])
                    if arg_tv[0] in RAWLIST_KINDS:
                        # raw list: the length field is the answer; boxing
                        # the whole list to ask pyobj_len would allocate
                        # every element on each call
                        return (
                            I64,
                            self.current_builder.call(self.rawlist_len, [arg_tv[1]]),
                        )
                    if arg_tv[0] in RAWDICT_KINDS:
                        # same story for raw dicts: read the count field
                        return (
                            I64,
                            self.current_builder.load(
                                self.current_builder.gep(
                                    self.current_builder.bitcast(
                                        arg_tv[1],
                                        ir.PointerType(self.raw_dict_struct_type),
                                    ),
                                    [
                                        ir.Constant(ir.IntType(32), 0),
                                        ir.Constant(ir.IntType(32), 0),
                                    ],
                                )
                            ),
                        )
                    if arg_tv[0] == RAWSTR:
                        # raw string: length lives in the slot header
                        struct_ptr = self.current_builder.bitcast(
                            arg_tv[1],
                            ir.PointerType(self.rawstr_struct_type),
                        )
                        return (
                            I64,
                            self.current_builder.load(
                                self.current_builder.gep(
                                    struct_ptr,
                                    [
                                        ir.Constant(ir.IntType(32), 0),
                                        ir.Constant(ir.IntType(32), 0),
                                    ],
                                )
                            ),
                        )
                    boxed = self._box(arg_tv)
                    # len(()) and len({}) compile to pyobj_len on real
                    # objects; null constants (unsupported exprs) degrade
                    if not isinstance(boxed, ir.Constant):
                        return (
                            OBJ,
                            self.current_builder.call(self.pyobj_len, [boxed]),
                        )
                    return (
                        OBJ,
                        self.current_builder.call(
                            self.create_int, [ir.Constant(ir.IntType(64), 0)]
                        ),
                    )
                return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

            if func_name == "sum":
                if args_node:
                    boxed = self._box(self._convert_node(args_node[0]))
                    if boxed is not None:
                        return (
                            OBJ,
                            self.current_builder.call(self.list_sum, [boxed]),
                        )
                return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

            if func_name == "dict":
                dict_obj = self.current_builder.call(self.create_dict, [])
                for arg_node in args_node:
                    boxed = self._box(self._convert_node(arg_node))
                    if boxed is not None:
                        self.current_builder.call(self.dict_update, [dict_obj, boxed])
                for kw_name, kw_value_node in node[3] if len(node) > 3 else []:
                    key = self._convert_node(["const", kw_name])
                    value = self._convert_node(kw_value_node)
                    self.current_builder.call(
                        self.dict_set, [dict_obj, self._box(key), self._box(value)]
                    )
                return (OBJ, dict_obj)

            if func_name == "range":
                # bare range() expression degrades to the dynamic view
                if len(args_node) >= 2:
                    boxed_stop = self._box(self._convert_node(args_node[1]))
                    return (OBJ, boxed_stop)
                if len(args_node) == 1:
                    return (OBJ, self._box(self._convert_node(args_node[0])))
                return (
                    OBJ,
                    self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 0)]
                    ),
                )

            if func_name in self.static_funcs:
                param_kinds, ret_kind, func = self.static_funcs[func_name]
                raw_args = []
                for index, arg_node in enumerate(args_node):
                    kind = (
                        param_kinds[index]
                        if index < len(param_kinds)
                        else param_kinds[-1]
                    )
                    raw_args.append(self._coerce(self._convert_node(arg_node), kind)[1])
                if len(raw_args) == len(param_kinds):
                    return (ret_kind, self.current_builder.call(func, raw_args))
                return (
                    ret_kind,
                    ir.Constant(
                        LLVM_KIND_TYPES[ret_kind], False if ret_kind == I1 else 0
                    ),
                )

            if func_name in self.functions:
                func = self.functions[func_name]
                callee_def = self.function_defs.get(func_name)
                callee_kinds = (
                    self._dyn_func_kinds.get(func_name)
                    or (
                        self._dynamic_param_kinds(callee_def)
                        if callee_def
                        else []
                    )
                )
                boxed_args = []
                for arg_index, arg_node in enumerate(args_node):
                    arg_tv = self._convert_node(arg_node)
                    expected = (
                        callee_kinds[arg_index]
                        if arg_index < len(callee_kinds)
                        else OBJ
                    )
                    if expected == OBJ:
                        boxed_args.append(self._box(arg_tv))
                    elif expected in RAWLIST_KINDS:
                        if arg_tv[0] in RAWLIST_KINDS:
                            boxed_args.append(arg_tv[1])
                        else:
                            boxed_args.append(
                                self.current_builder.call(
                                    self.pylist_to_rawlist,
                                    [self._box(arg_tv)],
                                )
                            )
                    else:
                        # proven raw scalar/str parameter: coerce in place
                        # (str coercion copies at the boundary)
                        boxed_args.append(
                            self._coerce(arg_tv, expected)[1]
                        )
                if len(boxed_args) == len(func.args):
                    result = self.current_builder.call(func, boxed_args)
                    return (OBJ, result)
                return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))
