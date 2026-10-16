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

from silu.ir_iface import ir

from .silu_ir_to_llvm import SiluToLLVMConverter


def _dict_loop_names(target_node: Any, mode: str) -> Tuple[Any, Any]:
    """(key_name, value_name) for the loop target; None where the
    mode does not bind that side."""
    if (
        isinstance(target_node, (list, tuple))
        and len(target_node) >= 2
        and target_node[0] == "tuple_unpack"
        and len(target_node[1]) == 2
    ):
        k_name, v_name = target_node[1]
        if mode == "keys":
            return k_name, None
        if mode == "values":
            return None, v_name
        return k_name, v_name
    if (
        isinstance(target_node, (list, tuple))
        and len(target_node) >= 2
        and target_node[0] == "name"
    ):
        name = target_node[1]
    elif isinstance(target_node, str):
        name = target_node
    else:
        return None, None
    if mode == "values":
        return None, name
    return name, None


def _const_int_of(node: Any) -> Optional[int]:
    """Compile-time int for ('const', n) and unary minus thereof."""
    if (
        isinstance(node, list)
        and len(node) >= 2
        and node[0] == "const"
        and isinstance(node[1], int)
        and not isinstance(node[1], bool)
    ):
        return node[1]
    if (
        isinstance(node, list)
        and len(node) == 2
        and node[0] == "-"
        and isinstance(node[1], list)
        and len(node[1]) >= 2
        and node[1][0] == "const"
        and isinstance(node[1][1], int)
        and not isinstance(node[1][1], bool)
    ):
        return -node[1][1]
    return None


def _rawlist_elem_size(kind: str) -> int:
    return 8  # both i64 and double elements are 8 bytes


def _rawdict_call_fn(kind: str, int_fn: Any, str_fn: Any):
    return str_fn if kind in RAWDICT_STR_KINDS else int_fn


def _extract_i64_const(value: Any) -> Optional[int]:
    if isinstance(value, ir.Constant) and isinstance(
        value.type, ir.IntType
    ) and value.type.width == 64:
        return int(value.constant)
    return None


def _kind_of_llvm_type(kind: str) -> ir.Type:
    if kind == OBJ:
        return ir.PointerType(ir.IntType(8))  # placeholder, unused
    return LLVM_KIND_TYPES[kind]


def _targets_parent(target_node, parent_names):
    if isinstance(target_node, str):
        return target_node in parent_names
    if (
        isinstance(target_node, (list, tuple))
        and len(target_node) >= 2
        and target_node[0] == "name"
        and isinstance(target_node[1], str)
    ):
        return target_node[1] in parent_names
    if (
        isinstance(target_node, (list, tuple))
        and len(target_node) >= 3
        and target_node[0] == "subscript"
        and isinstance(target_node[1], (list, tuple))
        and len(target_node[1]) >= 2
        and target_node[1][0] == "name"
    ):
        return target_node[1][1] in parent_names
    return False


def _all_name_parts(parts):
    for part in parts:
        if not (
            isinstance(part, list) and len(part) >= 2 and part[0] == "name"
        ):
            return False
    return True


def _all_of_kind(kinds, want):
    for k in kinds:
        if k != want:
            return False
    return True


def _all_non_obj(kinds):
    for k in kinds:
        if k == OBJ:
            return False
    return True


def _all_str(names):
    for name in names:
        if not isinstance(name, str):
            return False
    return True


def _non_obj_param_env(params, param_kinds, keep_obj):
    env = {}
    for name, kind in zip(params, param_kinds):
        if keep_obj or kind != OBJ:
            env[name] = kind
    return env


def _clamp_str_bound(b, bound, s_cp):
    """Python slice-index clamp: negatives count from s_cp."""
    i64 = ir.IntType(64)
    zero64 = ir.const_(i64, 0)
    adjusted = b.select(
        b.icmp_signed("<", bound, zero64), b.add(bound, s_cp), bound
    )
    floored = b.select(
        b.icmp_signed("<", adjusted, zero64), zero64, adjusted
    )
    return b.select(b.icmp_signed(">", floored, s_cp), s_cp, floored)


def _is_ws_byte(b, byte):
    """ASCII whitespace: space, \\t \\n \\v \\f \\r. UTF-8
    continuation/lead bytes (>= 0x80) are never whitespace."""
    b8 = ir.IntType(8)
    return b.or_(
        b.icmp_signed("==", byte, ir.const_(b8, 32)),
        b.and_(
            b.icmp_signed(">=", byte, ir.const_(b8, 9)),
            b.icmp_signed("<=", byte, ir.const_(b8, 13)),
        ),
    )


def _pred_digit(b, byte):
    b8 = ir.IntType(8)
    return b.and_(
        b.icmp_signed(">=", byte, ir.const_(b8, 0x30)),
        b.icmp_signed("<=", byte, ir.const_(b8, 0x39)),
    )


def _pred_alpha(b, byte):
    b8 = ir.IntType(8)
    lowered = b.or_(byte, ir.const_(b8, 0x20))
    ascii_alpha = b.and_(
        b.icmp_signed(">=", lowered, ir.const_(b8, 0x61)),
        b.icmp_signed("<=", lowered, ir.const_(b8, 0x7A)),
    )
    # i8 is signed: test the high bit, not >= 0x80 (which is -128)
    non_ascii = b.icmp_signed(
        "!=", b.and_(byte, ir.const_(b8, 0x80)), ir.const_(b8, 0)
    )
    return b.or_(ascii_alpha, non_ascii)


def _load_byte(builder, data, offset):
    i64 = ir.IntType(64)
    return builder.zext(
        builder.load(builder.gep(data, [ir.const_(i64, offset)])),
        i64,
    )


def _chr_store(builder, chr_buf, offset, value):
    b8 = ir.IntType(8)
    i32 = ir.IntType(32)
    builder.store(
        builder.trunc(value, b8),
        builder.gep(chr_buf, [ir.const_(i32, offset)]),
    )


def _struct_gep(builder, struct_ptr, index):
    """builder.gep(struct_ptr, [0, index]) - field address in a struct."""
    return builder.gep(
        struct_ptr,
        [
            ir.const_(ir.IntType(32), 0),
            ir.const_(ir.IntType(32), index),
        ],
    )


def _rawstr_load_len(b, struct_ptr):
    return b.load(_struct_gep(b, struct_ptr, 0))


def _rawstr_load_data(b, struct_ptr):
    return b.load(_struct_gep(b, struct_ptr, 2))


def _rawstr_load_cp(b, struct_ptr):
    return b.load(_struct_gep(b, struct_ptr, 3))


I64 = "i64"
F64 = "f64"
I1 = "i1"
OBJ = "obj"

ANNOTATION_KINDS = {"int": I64, "float": F64, "bool": I1}
RAWLIST_I = "rawlist_i64"  # list[int]: Vec<i64>-style raw element array
RAWLIST_F = "rawlist_f64"  # list[float]
RAWSTR = "rawstr"  # str: {len, cap, data} with exclusive slot ownership
# transient: a borrowed {i8* data, i64 seq} window into a parent
# rawstr (SSA struct value, no allocation). Lives inside one
# expression; any consumer needing an owned string coerces to
# RAWSTR (a copy).
RAWCHAR_VIEW = "rawchar_view"
RAWLIST_S = "rawlist_str"  # list[str]: slots own a copy of each element
RAWLIST_KINDS = {RAWLIST_I: I64, RAWLIST_F: F64, RAWLIST_S: RAWSTR}
RAWDICT_II = "rawdict_ii"  # dict[int, int]: machine-word open addressing
RAWDICT_IF = "rawdict_if"  # dict[int, float] (values as f64 bit patterns)
RAWDICT_SI = "rawdict_si"  # dict[str, int]: same table, rawstr keys
RAWDICT_SF = "rawdict_sf"  # dict[str, float]
RAWDICT_KINDS = {
    RAWDICT_II: I64,
    RAWDICT_IF: F64,
    RAWDICT_SI: I64,
    RAWDICT_SF: F64,
}  # kind -> value kind
RAWDICT_STR_KINDS = (RAWDICT_SI, RAWDICT_SF)  # kinds with rawstr keys
# class instance: an opaque heap block of 8-byte field slots (the
# class name lives in the compile-time _var_class side table, never
# in the object itself - Rust struct layout, no vtable, no header)
INSTANCE = "instance"
RAW_STORAGE_KINDS = {}
for _k in RAWLIST_KINDS:
    RAW_STORAGE_KINDS[_k] = RAWLIST_KINDS[_k]
for _k in RAWDICT_KINDS:
    RAW_STORAGE_KINDS[_k] = RAWDICT_KINDS[_k]
RAW_STORAGE_KINDS[RAWSTR] = RAWSTR
RAW_STORAGE_KINDS[INSTANCE] = INSTANCE
LLVM_KIND_TYPES = {
    I64: ir.IntType(64),
    F64: ir.DoubleType(),
    I1: ir.IntType(1),
    RAWSTR: ir.PointerType(ir.IntType(8)),  # rawstr passes as i8* in ABIs
    RAWLIST_I: ir.PointerType(ir.IntType(8)),
    RAWLIST_F: ir.PointerType(ir.IntType(8)),
    RAWLIST_S: ir.PointerType(ir.IntType(8)),
    RAWDICT_II: ir.PointerType(ir.IntType(8)),
    RAWDICT_IF: ir.PointerType(ir.IntType(8)),
    RAWDICT_SI: ir.PointerType(ir.IntType(8)),
    RAWDICT_SF: ir.PointerType(ir.IntType(8)),
    INSTANCE: ir.PointerType(ir.IntType(8)),
}


class TypedCodegen(SiluToLLVMConverter):
    """LLVM backend with unboxed scalars driven by source annotations."""

    def __init__(self):
        super().__init__()
        self._char_idxerr = None
        self._module_kinds = set()
        self._module_vars: set = set()
        self._scope_depth = 0
        self.rawdict_to_pydict: Dict[str, Any] = {}
        # Overflow/precision panics and rawlist bounds branches follow
        # Rust's release profile: set SILU_CHECKS=0 to disable them
        # (values wrap, out-of-range access is UB). Zero-division
        # checks always stay on - Rust also always checks those.
        self.checks = os.environ.get("SILU_CHECKS", "1") != "0"
        # scalar cursor promotion (SILU_SCALARS=0 disables): a
        # list[int] used only as x[0] in a scope becomes a local i64
        self.scalar_cursors = os.environ.get("SILU_SCALARS", "1") != "0"
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
        # scope-local scalar cursor promotions: name -> element kind
        # (empty when SILU_SCALARS=0; per-scope, see the inference walk)
        self.cursor_kinds: Dict[str, str] = {}
        self._cursor_slots: Dict[Any, Any] = {}
        # char-view aliases (scope-local, see _char_alias_* methods):
        # alias name -> (parent str name, str TypedValue, index node).
        # Reads of an aliased name replay the view; any invalidating
        # statement materializes the copy first. Failure mode is the
        # plain boxed path.
        self._char_aliases: Dict[str, Any] = {}

        # class layouts (dataclass semantics): class name ->
        # {"fields": [(fname, kind, default_node, field_class)], "methods": ...};
        # _var_class is the scope-local variable -> class name side table
        # (INSTANCE kind says "some class", this says which one)
        self._class_layouts: Dict[str, Dict[str, Any]] = {}
        self._var_class: Dict[str, str] = {}
        # instance-element lists: variable -> element class
        # (toks: list[Token]); lets `for t in toks` bind t as INSTANCE
        self._list_elem_class: Dict[str, str] = {}
        # container FIELDS' element classes: (class, field) -> elem class
        # (class Node: children: list[Node])
        self._field_elem_class: Dict[Tuple[str, str], str] = {}
        # function name -> class when every return expression is a
        # constructor of that one class (lets elem(node, i).s resolve)
        self._call_ret_class: Dict[str, str] = {}
        # name of the list a for-loop is currently iterating (see
        # _convert_list_for_loop)
        self._current_for_iter_name: Optional[str] = None
        # mangled method name -> owning class (self param binding)
        self._method_class: Dict[str, str] = {}
        # function-reference locals: var name -> mangled function name
        self._funcref_var: Dict[str, str] = {}
        self._enum_ctr_seq = 0
        # enums (class Color(Enum): RED = 1): name -> {member: int}
        # members fold to i64 constants at compile time
        self._enums: Dict[str, Dict[str, int]] = {}

        # math intrinsics / libc used by ** (sqrt fast path, general pow)
        sqrt_ty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()], False)
        self.sqrt_f64 = ir.func_(self.module, sqrt_ty, 'llvm.sqrt.f64')
        pow_ty = ir.FunctionType(
            ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()], False
        )
        self.pow_f64 = ir.func_(self.module, pow_ty, 'pow')

        self._create_unbox_runtime()
        self._create_raw_list_runtime()

        # PyObject* pyobj_pow(PyObject* base, PyObject* exp) via libc pow
        i32t = ir.IntType(32)
        i64t = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32t, 0)
        one32 = ir.const_(i32t, 1)
        self.pyobj_pow = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'pyobj_pow',

        )
        entry = self.pyobj_pow.append_basic_block("entry")
        builder = ir.builder_(entry)
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
            builder.icmp_signed("==", base_tag, ir.const_(i32t, 3)),
        )
        exp_is_int = builder.or_(
            builder.icmp_signed("==", exp_tag, zero32),
            builder.icmp_signed("==", exp_tag, ir.const_(i32t, 3)),
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
        zero32 = ir.const_(i32, 0)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)

        self.raw_list_struct_type = ir.LiteralStructType([i64, i64, i8p])


        # i8* rawlist_new(i64 elem_size)
        self.rawlist_new = ir.func_(
            self.module, ir.FunctionType(i8p, [i64], False), 'rawlist_new'
        )
        builder = ir.builder_(self.rawlist_new.append_basic_block("entry"))
        (elem_size,) = self.rawlist_new.args
        struct_ptr = builder.call(self.malloc, [ir.const_(i64, 24)])
        struct_ptr = builder.bitcast(
            struct_ptr, ir.PointerType(self.raw_list_struct_type)
        )
        initial = builder.call(
            self.malloc, [builder.mul(elem_size, ir.const_(i64, 4))]
        )
        builder.store(ir.const_(i64, 0), _struct_gep(builder, struct_ptr, 0))
        builder.store(ir.const_(i64, 4), _struct_gep(builder, struct_ptr, 1))
        builder.store(initial, _struct_gep(builder, struct_ptr, 2))
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # i64 rawlist_push(i8* list, <elem-width * elem_value>) -> new length
        # Element passed BY VALUE; call sites use the i64 flavor (double
        # values are bitcast - both are 8 bytes). One capacity check per
        # call, in-place element store, no temporary buffers.
        self.rawlist_push = ir.func_(
            self.module,
            ir.FunctionType(i64, [i8p, i64], False), 'rawlist_push',

        )
        entry = self.rawlist_push.append_basic_block("entry")
        grow_block = self.rawlist_push.append_basic_block("grow")
        copy_block = self.rawlist_push.append_basic_block("grow_copy")
        do_push = self.rawlist_push.append_basic_block("do_push")
        builder = ir.builder_(entry)
        list_arg, elem_arg = self.rawlist_push.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        capacity = builder.load(_struct_gep(builder, struct_ptr, 1))
        needs_grow = builder.icmp_signed("==", length, capacity)
        builder.cbranch(needs_grow, grow_block, do_push)

        builder.position_at_end(grow_block)
        # capacity doubles; entries are fixed 8 bytes
        new_capacity = builder.mul(capacity, ir.const_(i64, 2))
        fresh = builder.call(
            self.malloc,
            [builder.mul(new_capacity, ir.const_(i64, 8))],
        )
        has_old = builder.icmp_signed(">", length, zero64)
        builder.cbranch(has_old, copy_block, do_push)

        builder.position_at_end(copy_block)
        old_items = builder.load(_struct_gep(builder, struct_ptr, 2))
        builder.call(
            self.memcpy,
            [
                fresh,
                old_items,
                builder.mul(length, ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.store(new_capacity, _struct_gep(builder, struct_ptr, 1))
        builder.store(fresh, _struct_gep(builder, struct_ptr, 2))
        builder.branch(do_push)

        builder.position_at_end(do_push)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        length_now = builder.load(_struct_gep(builder, struct_ptr, 0))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [length_now])
        builder.store(elem_arg, slot)
        new_length = builder.add(length_now, one64)
        builder.store(new_length, _struct_gep(builder, struct_ptr, 0))
        builder.ret(new_length)

        # i64 rawlist_pop(i8* list) - remove and return the last element
        self.rawlist_pop = ir.func_(
            self.module, ir.FunctionType(i64, [i8p], False), 'rawlist_pop'
        )
        entry = self.rawlist_pop.append_basic_block("entry")
        empty_block = self.rawlist_pop.append_basic_block("pop_empty")
        ok_block = self.rawlist_pop.append_basic_block("pop_ok")
        builder = ir.builder_(entry)
        struct_ptr = builder.bitcast(
            self.rawlist_pop.args[0], ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        is_empty = builder.icmp_signed("==", length, zero64)
        builder.cbranch(is_empty, empty_block, ok_block)

        builder.position_at_end(empty_block)
        msg = self._create_global_string_with_builder(
            "IndexError: pop from empty list", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        last_index = builder.sub(length, one64)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [last_index])
        value = builder.load(slot)
        builder.store(zero64, _struct_gep(builder, struct_ptr, 0))
        builder.ret(value)

        # PyObject* rawlist_to_pylist(i8* list, i64 length)
        # box every element for the dynamic boundary
        self.rawlist_to_pylist = ir.func_(
            self.module,
            ir.FunctionType(ir.PointerType(self.pyobj.pyobj_type), [i8p, i64], False), 'rawlist_to_pylist',

        )
        entry = self.rawlist_to_pylist.append_basic_block("entry")
        loop_check = self.rawlist_to_pylist.append_basic_block("cvt_check")
        loop_body = self.rawlist_to_pylist.append_basic_block("cvt_body")
        loop_done = self.rawlist_to_pylist.append_basic_block("cvt_done")
        builder = ir.builder_(entry)
        list_arg, length_arg = self.rawlist_to_pylist.args
        src_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        items = builder.load(_struct_gep(builder, src_struct, 2))
        result = builder.call(self.create_list, [])
        idx_ptr = builder.alloca(i64, None, 'cvt_i')
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        more = builder.icmp_signed("<", i_val, length_arg)
        builder.cbranch(more, loop_body, loop_done)

        builder.position_at_end(loop_body)
        # elements are 8 bytes: gep over i64*, not the i8* byte pointer
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        elem_bits = builder.load(builder.gep(items_i64, [i_val]))
        boxed = builder.call(self.create_int, [elem_bits])
        builder.call(self.list_append, [result, boxed])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(result)

        # PyObject* rawlist_to_pylist_f64(i8* list, i64 length) - same
        # walk, but elements are f64 bit patterns boxed as floats
        self.rawlist_to_pylist_f64 = ir.func_(
            self.module,
            ir.FunctionType(ir.PointerType(self.pyobj.pyobj_type), [i8p, i64], False), 'rawlist_to_pylist_f64',

        )
        entry = self.rawlist_to_pylist_f64.append_basic_block("entry")
        loop_check = self.rawlist_to_pylist_f64.append_basic_block("cvt_check")
        loop_body = self.rawlist_to_pylist_f64.append_basic_block("cvt_body")
        loop_done = self.rawlist_to_pylist_f64.append_basic_block("cvt_done")
        builder = ir.builder_(entry)
        list_arg, length_arg = self.rawlist_to_pylist_f64.args
        src_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        items = builder.load(_struct_gep(builder, src_struct, 2))
        result = builder.call(self.create_list, [])
        idx_ptr = builder.alloca(i64, None, 'cvt_i')
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        more = builder.icmp_signed("<", i_val, length_arg)
        builder.cbranch(more, loop_body, loop_done)

        builder.position_at_end(loop_body)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        elem_bits = builder.load(builder.gep(items_i64, [i_val]))
        boxed = builder.call(
            self.create_float,
            [builder.bitcast(elem_bits, ir.DoubleType())],
        )
        builder.call(self.list_append, [result, boxed])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(result)

        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32b = ir.const_(ir.IntType(32), 0)
        one32b = ir.const_(ir.IntType(32), 1)

        # i8* pylist_to_rawlist(PyObject* list) - unbox each element into
        # a fresh raw array (ints only; other element types become 0)
        self.pylist_to_rawlist = ir.func_(
            self.module, ir.FunctionType(i8p, [pyobj_ptr], False), 'pylist_to_rawlist'
        )
        entry = self.pylist_to_rawlist.append_basic_block("entry")
        loop_check = self.pylist_to_rawlist.append_basic_block("p2r_check")
        loop_body = self.pylist_to_rawlist.append_basic_block("p2r_body")
        loop_done = self.pylist_to_rawlist.append_basic_block("p2r_done")
        builder = ir.builder_(entry)
        (list_arg,) = self.pylist_to_rawlist.args
        # the list struct lives behind the PyObject's data field
        struct_ptr = builder.bitcast(
            builder.load(builder.gep(list_arg, [zero32b, one32b])),
            ir.PointerType(self.list_struct_type),
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        raw = builder.call(self.rawlist_new, [ir.const_(i64, 8)])
        idx_ptr = builder.alloca(i64, None, 'p2r_i')
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
        self.rawlist_len = ir.func_(
            self.module, ir.FunctionType(i64, [i8p], False), 'rawlist_len'
        )
        builder = ir.builder_(self.rawlist_len.append_basic_block("entry"))
        struct_ptr = builder.bitcast(
            self.rawlist_len.args[0], ir.PointerType(self.raw_list_struct_type)
        )
        builder.ret(builder.load(_struct_gep(builder, struct_ptr, 0)))

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


        def panic_string(data: bytes, label: str) -> ir.GlobalVariable:
            gv = ir.gvar_(
                self.module,
                ir.ArrayType(ir.IntType(8), len(data)), label,

            )
            gv.global_constant = True
            gv.initializer = ir.const_(
                ir.ArrayType(ir.IntType(8), len(data)), bytearray(data)
            )
            return gv

        self._key_error_msg = panic_string(b"KeyError: key not found\0", "str_keyerr")
        key_error_msg = self._key_error_msg
        str_index_error_msg = panic_string(
            b"IndexError: string index out of range\0", "str_idxerr"
        )

        # void rawdict_reindex(i8* d, i64 new_size)
        # Rebuilds the index table at new_size and compacts the entries
        # arrays: live entries (table slot > 0) are copied to fresh
        # keys/values arrays, dead (deleted) entries are dropped, and
        # filled is reset to the live count.
        self.rawdict_reindex = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64], False), 'rawdict_reindex',

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
        builder = ir.builder_(entry)
        dict_arg, new_size_arg = self.rawdict_reindex.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        old_mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        old_size = builder.add(old_mask, one64)
        old_table = builder.load(_struct_gep(builder, struct_ptr, 4))
        old_keys = builder.load(_struct_gep(builder, struct_ptr, 5))
        old_vals = builder.load(_struct_gep(builder, struct_ptr, 6))
        entries_cap = builder.load(_struct_gep(builder, struct_ptr, 2))
        new_mask = builder.sub(new_size_arg, one64)
        fresh_table = builder.bitcast(
            builder.call(self.calloc, [new_size_arg, ir.const_(i64, 8)]),
            ir.PointerType(i64),
        )
        cap_bytes = builder.mul(entries_cap, ir.const_(i64, 8))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        builder.store(new_mask, _struct_gep(builder, struct_ptr, 3))
        builder.store(fresh_table, _struct_gep(builder, struct_ptr, 4))
        builder.store(fresh_keys, _struct_gep(builder, struct_ptr, 5))
        builder.store(fresh_vals, _struct_gep(builder, struct_ptr, 6))
        idx_ptr = builder.alloca(i64, None, 're_i')
        live_ptr = builder.alloca(i64, None, 're_live')
        slot_ptr = builder.alloca(i64, None, 're_slot')
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
        builder.store(builder.load(live_ptr), _struct_gep(builder, struct_ptr, 1))
        builder.call(self.free, [builder.bitcast(old_table, i8p)])
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.ret_void()

        # i8* rawdict_new()
        self.rawdict_new = ir.func_(
            self.module, ir.FunctionType(i8p, [], False), 'rawdict_new'
        )
        builder = ir.builder_(self.rawdict_new.append_basic_block("entry"))
        struct_ptr = builder.bitcast(
            builder.call(self.malloc, [ir.const_(i64, 56)]),
            ir.PointerType(self.raw_dict_struct_type),
        )
        builder.store(ir.const_(i64, 0), _struct_gep(builder, struct_ptr, 0))
        builder.store(ir.const_(i64, 0), _struct_gep(builder, struct_ptr, 1))
        builder.store(ir.const_(i64, 8), _struct_gep(builder, struct_ptr, 2))
        builder.store(ir.const_(i64, 7), _struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.bitcast(
                builder.call(
                    self.calloc, [ir.const_(i64, 8), ir.const_(i64, 8)]
                ),
                ir.PointerType(i64),
            ),
            _struct_gep(builder, struct_ptr, 4),
        )
        builder.store(
            builder.bitcast(
                builder.call(self.malloc, [ir.const_(i64, 64)]),
                ir.PointerType(i64),
            ),
            _struct_gep(builder, struct_ptr, 5),
        )
        builder.store(
            builder.bitcast(
                builder.call(self.malloc, [ir.const_(i64, 64)]),
                ir.PointerType(i64),
            ),
            _struct_gep(builder, struct_ptr, 6),
        )
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # void rawdict_set(i8* d, i64 key, i64 value_bits)
        self.rawdict_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i64], False), 'rawdict_set',

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
        builder = ir.builder_(entry)
        dict_arg, key_arg, val_arg = self.rawdict_set.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        filled = builder.load(_struct_gep(builder, struct_ptr, 1))
        mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        index_size = builder.add(mask, one64)
        load_would_exceed = builder.icmp_signed(
            ">",
            builder.mul(builder.add(filled, one64), ir.const_(i64, 3)),
            builder.mul(index_size, ir.const_(i64, 2)),
        )
        slot_ptr = builder.alloca(i64, None, 'rd_slot')
        tomb_ptr = builder.alloca(i64, None, 'rd_tomb')
        size_ptr = builder.alloca(i64, None, 'rd_size')
        builder.cbranch(load_would_exceed, rehash_block, start_block)

        # Resize to the smallest power of two (>= 8) that keeps the live
        # count under the 2/3 load factor. Compaction in reindex drops
        # tombstones, so churn without growth does not grow the table.
        builder.position_at_end(rehash_block)
        live_count = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.store(ir.const_(i64, 8), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_check)
        size_now = builder.load(size_ptr)
        need_more = builder.icmp_signed(
            ">",
            builder.mul(builder.add(live_count, one64), ir.const_(i64, 3)),
            builder.mul(size_now, ir.const_(i64, 2)),
        )
        builder.cbranch(need_more, size_grow, size_done)

        builder.position_at_end(size_grow)
        builder.store(builder.mul(size_now, ir.const_(i64, 2)), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_done)
        builder.call(self.rawdict_reindex, [dict_arg, builder.load(size_ptr)])
        builder.branch(start_block)

        builder.position_at_end(start_block)
        builder.store(ir.const_(i64, -1), tomb_ptr)
        mask_now = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(builder.and_(key_arg, mask_now), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, insert, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        builder.cbranch(is_tomb, tomb_note, match_check)

        builder.position_at_end(tomb_note)
        tomb_seen = builder.load(tomb_ptr)
        none_yet = builder.icmp_signed("==", tomb_seen, ir.const_(i64, -1))
        builder.cbranch(none_yet, tomb_store, probe_step)

        builder.position_at_end(tomb_store)
        builder.store(slot_now, tomb_ptr)
        builder.branch(probe_step)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, overwrite, probe_step)

        builder.position_at_end(overwrite)
        vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
        builder.store(val_arg, builder.gep(vals_now, [entry_index]))
        builder.ret_void()

        builder.position_at_end(probe_step)
        mask_step = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(insert)
        # reuse the first tombstone slot seen while probing, if any
        tomb_seen = builder.load(tomb_ptr)
        has_tomb = builder.icmp_signed("!=", tomb_seen, ir.const_(i64, -1))
        target_slot = builder.select(has_tomb, tomb_seen, builder.load(slot_ptr))
        builder.store(target_slot, slot_ptr)
        filled_now = builder.load(_struct_gep(builder, struct_ptr, 1))
        entries_cap = builder.load(_struct_gep(builder, struct_ptr, 2))
        needs_room = builder.icmp_signed("==", filled_now, entries_cap)
        builder.cbranch(needs_room, grow_block, do_insert)

        builder.position_at_end(grow_block)
        new_cap = builder.mul(entries_cap, ir.const_(i64, 2))
        byte_room = builder.mul(new_cap, ir.const_(i64, 8))
        old_keys = builder.load(_struct_gep(builder, struct_ptr, 5))
        old_vals = builder.load(_struct_gep(builder, struct_ptr, 6))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        copy_bytes = builder.mul(filled_now, ir.const_(i64, 8))
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_keys, i8p),
                builder.bitcast(old_keys, i8p),
                copy_bytes,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_vals, i8p),
                builder.bitcast(old_vals, i8p),
                copy_bytes,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.store(new_cap, _struct_gep(builder, struct_ptr, 2))
        builder.store(fresh_keys, _struct_gep(builder, struct_ptr, 5))
        builder.store(fresh_vals, _struct_gep(builder, struct_ptr, 6))
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.branch(do_insert)

        builder.position_at_end(do_insert)
        slot_free = builder.load(slot_ptr)
        keys_final = builder.load(_struct_gep(builder, struct_ptr, 5))
        vals_final = builder.load(_struct_gep(builder, struct_ptr, 6))
        builder.store(key_arg, builder.gep(keys_final, [filled_now]))
        builder.store(val_arg, builder.gep(vals_final, [filled_now]))
        table_final = builder.load(_struct_gep(builder, struct_ptr, 4))
        builder.store(
            builder.add(filled_now, one64), builder.gep(table_final, [slot_free])
        )
        builder.store(builder.add(filled_now, one64), _struct_gep(builder, struct_ptr, 1))
        count = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.store(builder.add(count, one64), _struct_gep(builder, struct_ptr, 0))
        builder.ret_void()

        # i64 rawdict_get(i8* d, i64 key) - panics KeyError when missing
        self.rawdict_get = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i64], False), 'rawdict_get'
        )
        entry = self.rawdict_get.append_basic_block("entry")
        probe_test = self.rawdict_get.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_get.append_basic_block("probe_tomb")
        match_check = self.rawdict_get.append_basic_block("probe_match")
        found = self.rawdict_get.append_basic_block("found")
        probe_step = self.rawdict_get.append_basic_block("probe_step")
        missing = self.rawdict_get.append_basic_block("key_error")
        builder = ir.builder_(entry)
        dict_arg, key_arg = self.rawdict_get.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, None, 'rdg_slot')
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, found, probe_step)

        builder.position_at_end(found)
        vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
        builder.ret(builder.load(builder.gep(vals_now, [entry_index])))

        builder.position_at_end(probe_step)
        mask_step = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(missing)
        msg_ptr = builder.gep(key_error_msg, [zero32, zero32])
        self._emit_panic(builder, msg_ptr)

        # i64 rawdict_del(i8* d, i64 key) - tombstones the slot, returns the
        # removed value's bits; panics KeyError when missing (Python del).
        self.rawdict_del = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i64], False), 'rawdict_del'
        )
        entry = self.rawdict_del.append_basic_block("entry")
        probe_test = self.rawdict_del.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_del.append_basic_block("probe_tomb")
        match_check = self.rawdict_del.append_basic_block("probe_match")
        found = self.rawdict_del.append_basic_block("found")
        probe_step = self.rawdict_del.append_basic_block("probe_step")
        missing = self.rawdict_del.append_basic_block("key_error")
        builder = ir.builder_(entry)
        dict_arg, key_arg = self.rawdict_del.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, None, 'rdd_slot')
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, found, probe_step)

        builder.position_at_end(found)
        builder.store(
            ir.const_(i64, -1), builder.gep(table_now, [slot_now])
        )
        count = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.store(builder.sub(count, one64), _struct_gep(builder, struct_ptr, 0))
        vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
        builder.ret(builder.load(builder.gep(vals_now, [entry_index])))

        builder.position_at_end(probe_step)
        mask_step = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(missing)
        msg_ptr = builder.gep(key_error_msg, [zero32, zero32])
        self._emit_panic(builder, msg_ptr)

        # PyObject* rawdict_to_pydict_{ii,if,si,sf}(i8* d) - boundary
        def box_int_key(b, bits):
            return b.call(self.create_int, [bits])

        for tag, make_key, make_value in (
            ("ii", box_int_key, lambda b, bits: b.call(self.create_int, [bits])),
            (
                "if",
                box_int_key,
                lambda b, bits: b.call(
                    self.create_float, [b.bitcast(bits, ir.DoubleType())]
                ),
            ),
        ):
            func = ir.func_(
                self.module,
                ir.FunctionType(
                    ir.PointerType(self.pyobj.pyobj_type), [i8p], False
                ), f'rawdict_to_pydict_{tag}',

            )
            entry = func.append_basic_block("entry")
            loop_check = func.append_basic_block("cvt_check")
            loop_body = func.append_basic_block("cvt_body")
            emit_block = func.append_basic_block("cvt_emit")
            loop_step = func.append_basic_block("cvt_step")
            loop_done = func.append_basic_block("cvt_done")
            builder = ir.builder_(entry)
            (dict_arg,) = func.args
            struct_ptr = builder.bitcast(
                dict_arg, ir.PointerType(self.raw_dict_struct_type)
            )
            # walk the index table: entries arrays hold dead slots after
            # deletions, live entries are exactly the slots > 0
            mask = builder.load(_struct_gep(builder, struct_ptr, 3))
            table_size = builder.add(mask, one64)
            result = builder.call(self.create_dict, [])
            idx_ptr = builder.alloca(i64, None, 'cvt_i')
            builder.store(zero64, idx_ptr)
            builder.branch(loop_check)

            builder.position_at_end(loop_check)
            idx = builder.load(idx_ptr)
            more = builder.icmp_signed("<", idx, table_size)
            builder.cbranch(more, loop_body, loop_done)

            builder.position_at_end(loop_body)
            table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
            slot_entry = builder.load(builder.gep(table_now, [idx]))
            is_live = builder.icmp_signed(">", slot_entry, zero64)
            builder.cbranch(is_live, emit_block, loop_step)

            builder.position_at_end(emit_block)
            entry_index = builder.sub(slot_entry, one64)
            keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
            vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
            key_box = make_key(
                builder, builder.load(builder.gep(keys_now, [entry_index]))
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
            self.rawdict_to_pydict[tag] = func
        # {i64 byte_len, i64 cap, i8* data, i64 cp_len}. Every slot owns
        # its buffer exclusively (assignment copies), so appends may
        # realloc in place and grow amortized like Rust's String.
        # byte_len/cap are bytes; cp_len is the code point count - len(),
        # s[i], s[a:b] and for-iteration are all code point semantics
        # (Python); eq/cmp/contains stay byte-wise, which on UTF-8
        # equals code point semantics.
        self.rawstr_struct_type = ir.LiteralStructType([i64, i64, i8p, i64])

        if self.realloc is None:
            self.realloc = ir.func_(
                self.module, ir.FunctionType(i8p, [i8p, i64], False), 'realloc'
            )





        type_error_msg = panic_string(
            b"TypeError: expected str\0", "str_typeerr"
        )

        # i64 rawutf8_cp_count(i8* data, i64 len) - code points = bytes
        # that are not continuation bytes ((b & 0xC0) != 0x80)
        self.rawutf8_cp_count = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i64], False), 'rawutf8_cp_count',

        )
        entry = self.rawutf8_cp_count.append_basic_block("entry")
        count_cond = self.rawutf8_cp_count.append_basic_block("count_cond")
        count_body = self.rawutf8_cp_count.append_basic_block("count_body")
        count_done = self.rawutf8_cp_count.append_basic_block("count_done")
        builder = ir.builder_(entry)
        data_arg, len_arg = self.rawutf8_cp_count.args
        idx_ptr = builder.alloca(i64, None, 'cpc_i')
        total_ptr = builder.alloca(i64, None, 'cpc_n')
        builder.store(zero64, idx_ptr)
        builder.store(zero64, total_ptr)
        builder.branch(count_cond)

        builder.position_at_end(count_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, len_arg)
        builder.cbranch(more, count_body, count_done)

        builder.position_at_end(count_body)
        byte = builder.load(builder.gep(data_arg, [idx]))
        masked = builder.and_(byte, ir.const_(ir.IntType(8), 0xC0))
        is_lead = builder.icmp_signed(
            "!=", masked, ir.const_(ir.IntType(8), 0x80)
        )
        total_now = builder.load(total_ptr)
        bumped = builder.select(
            is_lead, builder.add(total_now, one64), total_now
        )
        builder.store(bumped, total_ptr)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(count_cond)

        builder.position_at_end(count_done)
        builder.ret(builder.load(total_ptr))

        # i8* rawstr_new_copy(i8* data, i64 len)
        self.rawstr_new_copy = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i64], False), 'rawstr_new_copy',

        )
        builder = ir.builder_(self.rawstr_new_copy.append_basic_block("entry"))
        data_arg, len_arg = self.rawstr_new_copy.args
        buffer = builder.call(self.malloc, [len_arg])
        builder.call(
            self.memcpy,
            [buffer, data_arg, len_arg, ir.const_(ir.IntType(1), 0)],
        )
        cp_count = builder.call(self.rawutf8_cp_count, [data_arg, len_arg])
        struct_ptr = self._build_rawstr(builder, len_arg, len_arg, buffer, cp_count)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # i8* rawstr_copy(i8* src) - eager copy keeps slots exclusive
        self.rawstr_copy = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p], False), 'rawstr_copy'
        )
        builder = ir.builder_(self.rawstr_copy.append_basic_block("entry"))
        (src_arg,) = self.rawstr_copy.args
        src_struct = builder.bitcast(
            src_arg, ir.PointerType(self.rawstr_struct_type)
        )
        src_len = _rawstr_load_len(builder, src_struct)
        src_data = _rawstr_load_data(builder, src_struct)
        src_cp = _rawstr_load_cp(builder, src_struct)
        fresh_data = builder.call(self.malloc, [src_len])
        builder.call(
            self.memcpy,
            [fresh_data, src_data, src_len, ir.const_(ir.IntType(1), 0)],
        )
        struct_ptr = builder.bitcast(
            builder.call(self.malloc, [ir.const_(i64, 32)]),
            ir.PointerType(self.rawstr_struct_type),
        )
        builder.store(src_len, _struct_gep(builder, struct_ptr, 0))
        builder.store(src_len, _struct_gep(builder, struct_ptr, 1))
        builder.store(fresh_data, _struct_gep(builder, struct_ptr, 2))
        builder.store(src_cp, _struct_gep(builder, struct_ptr, 3))
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # void rawstr_free(i8* s) - drop a slot's buffer on overwrite
        # (Rust drop). Slots are null-initialized, so free skips null.
        self.rawstr_free = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'rawstr_free',

        )
        entry = self.rawstr_free.append_basic_block("entry")
        free_block = self.rawstr_free.append_basic_block("do_free")
        builder = ir.builder_(entry)
        (free_arg,) = self.rawstr_free.args
        is_null = builder.icmp_signed(
            "==",
            builder.ptrtoint(free_arg, i64),
            zero64,
        )
        done_block = self.rawstr_free.append_basic_block("free_done")
        builder.cbranch(is_null, done_block, free_block)

        builder.position_at_end(free_block)
        free_struct = builder.bitcast(
            free_arg, ir.PointerType(self.rawstr_struct_type)
        )
        builder.call(self.free, [_rawstr_load_data(builder, free_struct)])
        builder.call(self.free, [free_arg])
        builder.branch(done_block)

        builder.position_at_end(done_block)
        builder.ret_void()

        # i8* rawstr_concat(i8* a, i8* b) - fresh result, inputs untouched
        self.rawstr_concat = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i8p], False), 'rawstr_concat',

        )
        builder = ir.builder_(self.rawstr_concat.append_basic_block("entry"))
        a_arg, b_arg = self.rawstr_concat.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = _rawstr_load_len(builder, a_struct)
        b_len = _rawstr_load_len(builder, b_struct)
        total = builder.add(a_len, b_len)
        total_cp = builder.add(
            _rawstr_load_cp(builder, a_struct), _rawstr_load_cp(builder, b_struct)
        )
        buffer = builder.call(self.malloc, [total])
        builder.call(
            self.memcpy,
            [buffer, _rawstr_load_data(builder, a_struct), a_len, ir.const_(ir.IntType(1), 0)],
        )
        b_dst = builder.gep(buffer, [a_len])
        builder.call(
            self.memcpy,
            [b_dst, _rawstr_load_data(builder, b_struct), b_len, ir.const_(ir.IntType(1), 0)],
        )
        struct_ptr = self._build_rawstr(builder, total, total, buffer, total_cp)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        # void rawstr_append(i8* s, i8* data, i64 len)
        # Grow in place with doubling; caller guarantees `data` does not
        # point into s's buffer (self-append goes through rawstr_concat).
        self.rawstr_append = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i8p, i64], False), 'rawstr_append',

        )
        entry = self.rawstr_append.append_basic_block("entry")
        grow_block = self.rawstr_append.append_basic_block("grow")
        copy_block = self.rawstr_append.append_basic_block("do_append")
        builder = ir.builder_(entry)
        s_arg, data_arg, add_len_arg = self.rawstr_append.args
        struct_ptr = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        old_len = _rawstr_load_len(builder, struct_ptr)
        old_cap = builder.load(_struct_gep(builder, struct_ptr, 1))
        new_len = builder.add(old_len, add_len_arg)
        needs_room = builder.icmp_signed(">", new_len, old_cap)
        builder.cbranch(needs_room, grow_block, copy_block)

        builder.position_at_end(grow_block)
        doubled = builder.mul(old_cap, ir.const_(i64, 2))
        enough = builder.icmp_signed(">=", doubled, new_len)
        new_cap = builder.select(enough, doubled, new_len)
        old_data = _rawstr_load_data(builder, struct_ptr)
        grown = builder.call(
            self.realloc,
            [old_data, new_cap],
        )
        builder.store(new_cap, _struct_gep(builder, struct_ptr, 1))
        builder.store(grown, _struct_gep(builder, struct_ptr, 2))
        builder.branch(copy_block)

        builder.position_at_end(copy_block)
        data_now = _rawstr_load_data(builder, struct_ptr)
        len_now = _rawstr_load_len(builder, struct_ptr)
        dst = builder.gep(data_now, [len_now])
        builder.call(
            self.memcpy,
            [dst, data_arg, add_len_arg, ir.const_(ir.IntType(1), 0)],
        )
        builder.store(new_len, _struct_gep(builder, struct_ptr, 0))
        add_cp = builder.call(
            self.rawutf8_cp_count, [data_arg, add_len_arg]
        )
        old_cp = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.add(old_cp, add_cp), _struct_gep(builder, struct_ptr, 3)
        )
        builder.ret_void()

        # i1 rawstr_eq(i8* a, i8* b)
        self.rawstr_eq = ir.func_(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i8p], False), 'rawstr_eq'
        )
        entry = self.rawstr_eq.append_basic_block("entry")
        eq_ok = self.rawstr_eq.append_basic_block("len_ok")
        eq_out = self.rawstr_eq.append_basic_block("eq_out")
        builder = ir.builder_(entry)
        a_arg, b_arg = self.rawstr_eq.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = _rawstr_load_len(builder, a_struct)
        b_len = _rawstr_load_len(builder, b_struct)
        same_len = builder.icmp_signed("==", a_len, b_len)
        builder.cbranch(same_len, eq_ok, eq_out)

        builder.position_at_end(eq_ok)
        same = builder.call(
            self.memcmp,
            [_rawstr_load_data(builder, a_struct), _rawstr_load_data(builder, b_struct), a_len],
        )
        is_zero = builder.icmp_signed("==", same, ir.const_(i32, 0))
        builder.branch(eq_out)

        builder.position_at_end(eq_out)
        result = builder.phi(ir.IntType(1))
        result.add_incoming(ir.const_(ir.IntType(1), 0), entry)
        result.add_incoming(is_zero, eq_ok)
        builder.ret(result)

        # i64 rawstr_cmp(i8* a, i8* b) - memcmp sign (UTF-8 byte order
        # equals code point order, same as Python's str ordering)
        self.rawstr_cmp = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i8p], False), 'rawstr_cmp'
        )
        builder = ir.builder_(self.rawstr_cmp.append_basic_block("entry"))
        a_arg, b_arg = self.rawstr_cmp.args
        a_struct = builder.bitcast(a_arg, ir.PointerType(self.rawstr_struct_type))
        b_struct = builder.bitcast(b_arg, ir.PointerType(self.rawstr_struct_type))
        a_len = _rawstr_load_len(builder, a_struct)
        b_len = _rawstr_load_len(builder, b_struct)
        prefix_len = builder.select(
            builder.icmp_signed("<", a_len, b_len), a_len, b_len
        )
        memcmp_result = builder.call(
            self.memcmp,
            [_rawstr_load_data(builder, a_struct), _rawstr_load_data(builder, b_struct), prefix_len],
        )
        memcmp_i64 = builder.sext(memcmp_result, i64)
        is_equal = builder.icmp_signed("==", memcmp_i64, zero64)
        # equal prefixes: the shorter string sorts first
        length_diff = builder.sub(a_len, b_len)
        builder.ret(builder.select(is_equal, length_diff, memcmp_i64))

        # i1 rawstr_eq_cstr(i8* s, i8* data, i64 len) - compare against
        # a constant buffer without materializing a rawstr for it.
        # memcmp only over the SHARED prefix: comparing s_len bytes when
        # the literal is shorter would read past the global (the length
        # mismatch already decides the result)
        self.rawstr_eq_cstr = ir.func_(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i8p, i64], False), 'rawstr_eq_cstr',

        )
        eq_entry = self.rawstr_eq_cstr.append_basic_block("entry")
        eq_bytes = self.rawstr_eq_cstr.append_basic_block("eq_bytes")
        eq_out = self.rawstr_eq_cstr.append_basic_block("eq_out")
        builder = ir.builder_(eq_entry)
        s_arg, cdata_arg, clen_arg = self.rawstr_eq_cstr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = _rawstr_load_len(builder, s_struct)
        len_eq = builder.icmp_signed("==", s_len, clen_arg)
        builder.cbranch(len_eq, eq_bytes, eq_out)

        builder = ir.builder_(eq_bytes)
        bytes_eq = builder.icmp_signed(
            "==",
            builder.call(
                self.memcmp,
                [_rawstr_load_data(builder, s_struct), cdata_arg, clen_arg],
            ),
            ir.const_(ir.IntType(32), 0),
        )
        builder.branch(eq_out)

        builder = ir.builder_(eq_out)
        result = builder.phi(ir.IntType(1))
        result.add_incoming(ir.const_(ir.IntType(1), 0), eq_entry)
        result.add_incoming(bytes_eq, eq_bytes)
        builder.ret(result)

        # i64 rawstr_cmp_cstr(i8* s, i8* data, i64 len) - ordering vs a
        # constant buffer (memcmp prefix, length breaks ties)
        self.rawstr_cmp_cstr = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i8p, i64], False), 'rawstr_cmp_cstr',

        )
        builder = ir.builder_(self.rawstr_cmp_cstr.append_basic_block("entry"))
        s_arg, cdata_arg, clen_arg = self.rawstr_cmp_cstr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = _rawstr_load_len(builder, s_struct)
        prefix = builder.select(
            builder.icmp_signed("<", s_len, clen_arg), s_len, clen_arg
        )
        mem = builder.call(
            self.memcmp, [_rawstr_load_data(builder, s_struct), cdata_arg, prefix]
        )
        mem64 = builder.sext(mem, i64)
        is_eq = builder.icmp_signed("==", mem64, zero64)
        builder.ret(
            builder.select(is_eq, builder.sub(s_len, clen_arg), mem64)
        )

        # i64 rawutf8_cp_offset(i8* data, i64 cp_index) - byte offset of
        # the cp_index-th code point (callers clamp cp_index, so the
        # walk always stays inside the buffer)
        self.rawutf8_cp_offset = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i64], False), 'rawutf8_cp_offset',

        )
        entry = self.rawutf8_cp_offset.append_basic_block("entry")
        scan_cond = self.rawutf8_cp_offset.append_basic_block("off_cond")
        scan_body = self.rawutf8_cp_offset.append_basic_block("off_body")
        scan_done = self.rawutf8_cp_offset.append_basic_block("off_done")
        builder = ir.builder_(entry)
        data_arg, cp_index_arg = self.rawutf8_cp_offset.args
        off_ptr = builder.alloca(i64, None, 'cpo_off')
        seen_ptr = builder.alloca(i64, None, 'cpo_seen')
        builder.store(zero64, off_ptr)
        builder.store(zero64, seen_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        seen = builder.load(seen_ptr)
        more = builder.icmp_signed("<", seen, cp_index_arg)
        builder.cbranch(more, scan_body, scan_done)

        builder.position_at_end(scan_body)
        off = builder.load(off_ptr)
        lead = builder.load(builder.gep(data_arg, [off]))
        seq = self._emit_seq_len(builder, lead)
        builder.store(builder.add(off, seq), off_ptr)
        builder.store(builder.add(seen, one64), seen_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_done)
        builder.ret(builder.load(off_ptr))

        # i1 rawstr_at_eq_cstr(i8* s, i64 index, i8* cdata, i64 clen) -
        # s[index] == "<const>" without materializing the character:
        # code point offset, sequence length, then one memcmp
        self.rawstr_at_eq_cstr = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [i8p, i64, i8p, i64], False), 'rawstr_at_eq_cstr',

        )
        entry = self.rawstr_at_eq_cstr.append_basic_block("entry")
        ok_block = self.rawstr_at_eq_cstr.append_basic_block("ok")
        err_block = self.rawstr_at_eq_cstr.append_basic_block("index_error")
        ascii_block = self.rawstr_at_eq_cstr.append_basic_block("ascii")
        walk_block = self.rawstr_at_eq_cstr.append_basic_block("walk")
        join_block = self.rawstr_at_eq_cstr.append_basic_block("join")
        cmp_block = self.rawstr_at_eq_cstr.append_basic_block("cmp")
        neq_block = self.rawstr_at_eq_cstr.append_basic_block("neq")
        builder = ir.builder_(entry)
        s_arg, index_arg, cdata_arg, clen_arg = self.rawstr_at_eq_cstr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_cp = _rawstr_load_cp(builder, s_struct)
        is_neg = builder.icmp_signed("<", index_arg, zero64)
        index_eff = builder.select(is_neg, builder.add(index_arg, s_cp), index_arg)
        below = builder.icmp_signed(">=", index_eff, zero64)
        above = builder.icmp_signed("<", index_eff, s_cp)
        builder.cbranch(builder.and_(below, above), ok_block, err_block)

        builder.position_at_end(err_block)
        self._emit_panic(
            builder, builder.gep(str_index_error_msg, [zero32, zero32])
        )

        builder.position_at_end(ok_block)
        s_data = _rawstr_load_data(builder, s_struct)
        s_len = _rawstr_load_len(builder, s_struct)
        is_ascii = builder.icmp_signed("==", s_len, s_cp)
        builder.cbranch(is_ascii, ascii_block, walk_block)

        builder.position_at_end(ascii_block)
        builder.branch(join_block)

        builder.position_at_end(walk_block)
        walked_off = builder.call(
            self.rawutf8_cp_offset, [s_data, index_eff]
        )
        builder.branch(join_block)

        builder.position_at_end(join_block)
        char_off = builder.phi(i64)
        char_off.add_incoming(index_eff, ascii_block)
        char_off.add_incoming(walked_off, walk_block)
        lead = builder.load(builder.gep(s_data, [char_off]))
        seq = builder.select(is_ascii, one64, self._emit_seq_len(builder, lead))
        same_len = builder.icmp_signed("==", seq, clen_arg)
        builder.cbranch(same_len, cmp_block, neq_block)

        builder.position_at_end(cmp_block)
        bytes_eq = builder.icmp_signed(
            "==",
            builder.call(
                self.memcmp,
                [builder.gep(s_data, [char_off]), cdata_arg, clen_arg],
            ),
            ir.const_(ir.IntType(32), 0),
        )
        builder.ret(bytes_eq)

        builder.position_at_end(neq_block)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # i64 rawstr_at_cmp_cstr(i8* s, i64 index, i8* cdata, i64 clen)
        # - ordering for s[i] <op> "<const>": -1/0/1 style memcmp sign
        # clamped by the sequence-vs-constant length
        self.rawstr_at_cmp_cstr = ir.func_(
            self.module,
            ir.FunctionType(i64, [i8p, i64, i8p, i64], False), 'rawstr_at_cmp_cstr',

        )
        entry = self.rawstr_at_cmp_cstr.append_basic_block("entry")
        ok_block = self.rawstr_at_cmp_cstr.append_basic_block("ok")
        err_block = self.rawstr_at_cmp_cstr.append_basic_block("index_error")
        ascii_block = self.rawstr_at_cmp_cstr.append_basic_block("ascii")
        walk_block = self.rawstr_at_cmp_cstr.append_basic_block("walk")
        join_block = self.rawstr_at_cmp_cstr.append_basic_block("join")
        builder = ir.builder_(entry)
        s_arg, index_arg, cdata_arg, clen_arg = self.rawstr_at_cmp_cstr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_cp = _rawstr_load_cp(builder, s_struct)
        is_neg = builder.icmp_signed("<", index_arg, zero64)
        index_eff = builder.select(is_neg, builder.add(index_arg, s_cp), index_arg)
        below = builder.icmp_signed(">=", index_eff, zero64)
        above = builder.icmp_signed("<", index_eff, s_cp)
        builder.cbranch(builder.and_(below, above), ok_block, err_block)

        builder.position_at_end(err_block)
        self._emit_panic(
            builder, builder.gep(str_index_error_msg, [zero32, zero32])
        )

        builder.position_at_end(ok_block)
        s_data = _rawstr_load_data(builder, s_struct)
        s_len = _rawstr_load_len(builder, s_struct)
        is_ascii = builder.icmp_signed("==", s_len, s_cp)
        builder.cbranch(is_ascii, ascii_block, walk_block)

        builder.position_at_end(ascii_block)
        builder.branch(join_block)

        builder.position_at_end(walk_block)
        walked_off = builder.call(
            self.rawutf8_cp_offset, [s_data, index_eff]
        )
        builder.branch(join_block)

        builder.position_at_end(join_block)
        char_off = builder.phi(i64)
        char_off.add_incoming(index_eff, ascii_block)
        char_off.add_incoming(walked_off, walk_block)
        lead = builder.load(builder.gep(s_data, [char_off]))
        seq = builder.select(is_ascii, one64, self._emit_seq_len(builder, lead))
        # memcmp over the shared prefix, longer sequence sorts after
        prefix = builder.select(
            builder.icmp_signed("<", seq, clen_arg), seq, clen_arg
        )
        mem = builder.call(
            self.memcmp,
            [builder.gep(s_data, [char_off]), cdata_arg, prefix],
        )
        mem64 = builder.sext(mem, i64)
        is_eq = builder.icmp_signed("==", mem64, zero64)
        builder.ret(
            builder.select(is_eq, builder.sub(seq, clen_arg), mem64)
        )


        # i8* rawstr_char_at(i8* s, i64 index) - s[i] as a one-code-point
        # rawstr. Negative indices adjust by the code point count; the
        # code point walk makes indexing O(n) like Rust's chars().nth().
        self.rawstr_char_at = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p, i64], False), 'rawstr_char_at'
        )
        entry = self.rawstr_char_at.append_basic_block("entry")
        ok_block = self.rawstr_char_at.append_basic_block("ok")
        err_block = self.rawstr_char_at.append_basic_block("index_error")
        builder = ir.builder_(entry)
        s_arg, index_arg = self.rawstr_char_at.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_cp = _rawstr_load_cp(builder, s_struct)
        is_neg = builder.icmp_signed("<", index_arg, zero64)
        index_eff = builder.select(is_neg, builder.add(index_arg, s_cp), index_arg)
        below = builder.icmp_signed(">=", index_eff, zero64)
        above = builder.icmp_signed("<", index_eff, s_cp)
        builder.cbranch(builder.and_(below, above), ok_block, err_block)

        builder.position_at_end(err_block)
        msg_ptr = builder.gep(str_index_error_msg, [zero32, zero32])
        self._emit_panic(builder, msg_ptr)

        builder.position_at_end(ok_block)
        s_data = _rawstr_load_data(builder, s_struct)
        # ASCII fast path: when every byte is a code point, the index
        # IS the byte offset - skip the code point walk entirely
        is_ascii = builder.icmp_signed(
            "==", _rawstr_load_len(builder, s_struct), s_cp
        )
        ascii_block = self.rawstr_char_at.append_basic_block("ascii")
        walk_block = self.rawstr_char_at.append_basic_block("walk")
        join_block = self.rawstr_char_at.append_basic_block("join")
        builder.cbranch(is_ascii, ascii_block, walk_block)

        builder.position_at_end(ascii_block)
        builder.branch(join_block)

        builder.position_at_end(walk_block)
        walked_off = builder.call(
            self.rawutf8_cp_offset, [s_data, index_eff]
        )
        builder.branch(join_block)

        builder.position_at_end(join_block)
        char_off = builder.phi(i64)
        char_off.add_incoming(index_eff, ascii_block)
        char_off.add_incoming(walked_off, walk_block)
        lead = builder.load(builder.gep(s_data, [char_off]))
        seq = builder.select(is_ascii, one64, self._emit_seq_len(builder, lead))
        char_buf = builder.call(self.malloc, [seq])
        builder.call(
            self.memcpy,
            [
                char_buf,
                builder.gep(s_data, [char_off]),
                seq,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        char_struct = self._build_rawstr(builder, seq, seq, char_buf, one64)
        builder.ret(builder.bitcast(char_struct, i8p))

        # i8* rawstr_slice(i8* s, i64 lo, i64 hi) - s[lo:hi] in code
        # points with Python's clamping (negative bounds adjust,
        # out-of-range clamps, an inverted range yields the empty string)
        self.rawstr_slice = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p, i64, i64], False), 'rawstr_slice',

        )
        builder = ir.builder_(self.rawstr_slice.append_basic_block("entry"))
        s_arg, lo_arg, hi_arg = self.rawstr_slice.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_cp = _rawstr_load_cp(builder, s_struct)
        s_data = _rawstr_load_data(builder, s_struct)

        lo_eff = _clamp_str_bound(builder, lo_arg, s_cp)
        hi_eff = _clamp_str_bound(builder, hi_arg, s_cp)
        span_cp = builder.sub(hi_eff, lo_eff)
        out_cp = builder.select(
            builder.icmp_signed(">", span_cp, zero64), span_cp, zero64
        )
        # ASCII fast path: code point index == byte offset - skip the
        # code point walks entirely
        is_ascii = builder.icmp_signed(
            "==", _rawstr_load_len(builder, s_struct), s_cp
        )
        ascii_block = self.rawstr_slice.append_basic_block("ascii")
        walk_block = self.rawstr_slice.append_basic_block("walk")
        join_block = self.rawstr_slice.append_basic_block("join")
        builder.cbranch(is_ascii, ascii_block, walk_block)

        builder.position_at_end(ascii_block)
        builder.branch(join_block)

        builder.position_at_end(walk_block)
        walked_lo = builder.call(self.rawutf8_cp_offset, [s_data, lo_eff])
        walked_hi = builder.call(self.rawutf8_cp_offset, [s_data, hi_eff])
        builder.branch(join_block)

        builder.position_at_end(join_block)
        off_lo = builder.phi(i64)
        off_lo.add_incoming(lo_eff, ascii_block)
        off_lo.add_incoming(walked_lo, walk_block)
        off_hi = builder.phi(i64)
        off_hi.add_incoming(hi_eff, ascii_block)
        off_hi.add_incoming(walked_hi, walk_block)
        # an inverted range is the empty string: off_lo may sit past
        # off_hi, so clamp the byte span by the code point span
        raw_span = builder.sub(off_hi, off_lo)
        out_len = builder.select(
            builder.icmp_signed(">", out_cp, zero64), raw_span, zero64
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
                builder.gep(s_data, [off_lo]),
                out_len,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        slice_struct = self._build_rawstr(builder, out_len, out_len, out_buf, out_cp)
        builder.ret(builder.bitcast(slice_struct, i8p))

        # {i8*, i64} rawstr_slice_parts(i8* s, i64 lo, i64 hi) - the
        # slice's (data, len) without allocating anything; for
        # immediately-consumed positions (dict keys)
        self.rawstr_slice_parts = ir.func_(
            self.module,
            ir.FunctionType(
                ir.LiteralStructType([i8p, i64]), [i8p, i64, i64], False
            ), 'rawstr_slice_parts',

        )
        entry = self.rawstr_slice_parts.append_basic_block("entry")
        ascii_block = self.rawstr_slice_parts.append_basic_block("ascii")
        walk_block = self.rawstr_slice_parts.append_basic_block("walk")
        join_block = self.rawstr_slice_parts.append_basic_block("join")
        builder = ir.builder_(entry)
        s_arg, lo_arg, hi_arg = self.rawstr_slice_parts.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_cp = _rawstr_load_cp(builder, s_struct)
        s_data = _rawstr_load_data(builder, s_struct)

        lo_eff = _clamp_str_bound(builder, lo_arg, s_cp)
        hi_eff = _clamp_str_bound(builder, hi_arg, s_cp)
        is_ascii = builder.icmp_signed(
            "==", _rawstr_load_len(builder, s_struct), s_cp
        )
        builder.cbranch(is_ascii, ascii_block, walk_block)

        builder.position_at_end(ascii_block)
        builder.branch(join_block)

        builder.position_at_end(walk_block)
        walked_lo = builder.call(self.rawutf8_cp_offset, [s_data, lo_eff])
        walked_hi = builder.call(self.rawutf8_cp_offset, [s_data, hi_eff])
        builder.branch(join_block)

        builder.position_at_end(join_block)
        off_lo = builder.phi(i64)
        off_lo.add_incoming(lo_eff, ascii_block)
        off_lo.add_incoming(walked_lo, walk_block)
        off_hi = builder.phi(i64)
        off_hi.add_incoming(hi_eff, ascii_block)
        off_hi.add_incoming(walked_hi, walk_block)
        span_cp = builder.sub(hi_eff, lo_eff)
        has_span = builder.icmp_signed(">", span_cp, zero64)
        raw_span = builder.sub(off_hi, off_lo)
        out_len = builder.select(has_span, raw_span, zero64)
        out_data = builder.select(
            has_span, builder.gep(s_data, [off_lo]), s_data
        )
        result = ir.const_(ir.LiteralStructType([i8p, i64]), ir.Undefined)
        result = builder.insert_value(result, out_data, 0)
        result = builder.insert_value(result, out_len, 1)
        builder.ret(result)

        # i1 rawstr_contains(i8* haystack, i8* needle) - substring scan;
        # the empty needle is contained (Python: "" in s is True)
        self.rawstr_contains = ir.func_(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i8p], False), 'rawstr_contains',

        )
        entry = self.rawstr_contains.append_basic_block("entry")
        len_check = self.rawstr_contains.append_basic_block("len_check")
        scan_cond = self.rawstr_contains.append_basic_block("contains_cond")
        scan_body = self.rawstr_contains.append_basic_block("contains_body")
        scan_step = self.rawstr_contains.append_basic_block("contains_step")
        hit_block = self.rawstr_contains.append_basic_block("contains_hit")
        miss_block = self.rawstr_contains.append_basic_block("contains_miss")
        builder = ir.builder_(entry)
        hay_arg, needle_arg = self.rawstr_contains.args
        hay_struct = builder.bitcast(hay_arg, ir.PointerType(self.rawstr_struct_type))
        needle_struct = builder.bitcast(
            needle_arg, ir.PointerType(self.rawstr_struct_type)
        )
        hay_len = _rawstr_load_len(builder, hay_struct)
        needle_len = _rawstr_load_len(builder, needle_struct)
        hay_data = _rawstr_load_data(builder, hay_struct)
        needle_data = _rawstr_load_data(builder, needle_struct)
        scan_idx_ptr = builder.alloca(i64, None, 'rsc_i')
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
            ir.const_(ir.IntType(32), 0),
        )
        builder.cbranch(same, hit_block, scan_step)

        builder.position_at_end(scan_step)
        builder.store(builder.add(idx, one64), scan_idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(hit_block)
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(miss_block)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # i1 rawdict_has(i8* d, i64 key) - probe without the KeyError panic
        self.rawdict_has = ir.func_(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i64], False), 'rawdict_has',

        )
        entry = self.rawdict_has.append_basic_block("entry")
        probe_test = self.rawdict_has.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_has.append_basic_block("probe_tomb")
        match_check = self.rawdict_has.append_basic_block("probe_match")
        has_found = self.rawdict_has.append_basic_block("found")
        probe_step = self.rawdict_has.append_basic_block("probe_step")
        has_missing = self.rawdict_has.append_basic_block("missing")
        builder = ir.builder_(entry)
        dict_arg, key_arg = self.rawdict_has.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        slot_ptr = builder.alloca(i64, None, 'rdh_slot')
        builder.store(builder.and_(key_arg, mask), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, has_missing, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        builder.cbranch(is_tomb, probe_step, match_check)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
        stored_key = builder.load(builder.gep(keys_now, [entry_index]))
        is_match = builder.icmp_signed("==", stored_key, key_arg)
        builder.cbranch(is_match, has_found, probe_step)

        builder.position_at_end(has_found)
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(probe_step)
        mask_step = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(has_missing)
        builder.ret(ir.const_(ir.IntType(1), 0))


        # i64 rawdict_get_or(i8* d, i64 key, i64 default_bits)
        self.rawdict_get_or = self._emit_rawdict_probe(
            "rawdict_get_or",
            i64,
            [i8p, i64, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                self._rawdict_load_value_at(b, func, entry_index)
            ),
            lambda b, func: b.ret(func.args[2]),
        )

        # i64 rawdict_pop_or(i8* d, i64 key, i64 default_bits)
        self.rawdict_pop_or = self._emit_rawdict_probe(
            "rawdict_pop_or",
            i64,
            [i8p, i64, i64],
            self._rawdict_pop_or_hit,
            lambda b, func: b.ret(func.args[2]),
        )

        # i64 rawdict_setdefault(i8* d, i64 key, i64 value_bits)
        self.rawdict_setdefault = self._emit_rawdict_probe(
            "rawdict_setdefault",
            i64,
            [i8p, i64, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                self._rawdict_load_value_at(b, func, entry_index)
            ),
            self._rawdict_setdefault_miss,
        )

        # i8* rawdict_int_slotof(i8* d, i64 key) - pointer to the
        # value's storage slot (must exist; entry() guarantees it)
        self.rawdict_int_slotof = self._emit_rawdict_probe(
            "rawdict_int_slotof", i8p, [i8p, i64], self._rawdict_slotof_hit, self._rawdict_slotof_miss
        )

        # i8* rawdict_int_entry(i8* d, i64 key, i64 default_bits) -
        # Rust's entry().or_insert(): one probe on the hit path; the
        # miss path inserts the default and re-probes (misses are the
        # rare first sighting of each key)
        self.rawdict_int_entry = self._emit_rawdict_probe(
            "rawdict_int_entry", i8p, [i8p, i64, i64],
            self._rawdict_slotof_hit, self._rawdict_int_entry_miss,
        )

        # void rawdict_clear(i8* d) - keep the table, drop every entry
        self.rawdict_clear = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'rawdict_clear',

        )
        builder = ir.builder_(self.rawdict_clear.append_basic_block("entry"))
        (clear_arg,) = self.rawdict_clear.args
        clear_ptr = builder.bitcast(
            clear_arg, ir.PointerType(self.raw_dict_struct_type)
        )
        builder.store(zero64, _struct_gep(builder, clear_ptr, 0))
        builder.store(zero64, _struct_gep(builder, clear_ptr, 1))
        clear_mask = builder.load(_struct_gep(builder, clear_ptr, 3))
        builder.call(
            self.memset,
            [
                builder.bitcast(
                    builder.load(_struct_gep(builder, clear_ptr, 4)), i8p
                ),
                ir.const_(ir.IntType(8), 0),
                builder.mul(builder.add(clear_mask, one64), ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.ret_void()

        # void rawlist_clear(i8* list) - keep capacity, drop elements
        self.rawlist_clear = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'rawlist_clear',

        )
        builder = ir.builder_(self.rawlist_clear.append_basic_block("entry"))
        (rl_arg,) = self.rawlist_clear.args
        rl_ptr = builder.bitcast(
            rl_arg, ir.PointerType(self.raw_list_struct_type)
        )
        builder.store(
            zero64, builder.gep(rl_ptr, [zero32, ir.const_(i32, 0)])
        )
        builder.ret_void()

        # ---- str lists: list[str] ----
        # Same element-array layout as list[int] (8-byte slots holding
        # rawstr pointers). The LIST owns a copy of every element
        # (rawstr_copy on push/set); readers receive their own copy
        # (an element read out is owned by the reading slot), so
        # overwrite and scope drops free exactly what the list owns.

        # void rawlist_str_push(i8* list, i8* s) - copies the string in
        self.rawlist_str_push = ir.func_(
            self.module,
            ir.FunctionType(i64, [i8p, i8p], False), 'rawlist_str_push',

        )
        entry = self.rawlist_str_push.append_basic_block("entry")
        grow_block = self.rawlist_str_push.append_basic_block("grow")
        copy_block = self.rawlist_str_push.append_basic_block("grow_copy")
        do_push = self.rawlist_str_push.append_basic_block("do_push")
        builder = ir.builder_(entry)
        list_arg, elem_arg = self.rawlist_str_push.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        capacity = builder.load(_struct_gep(builder, struct_ptr, 1))
        builder.cbranch(
            builder.icmp_signed("==", length, capacity), grow_block, do_push
        )

        builder.position_at_end(grow_block)
        new_capacity = builder.mul(capacity, ir.const_(i64, 2))
        fresh = builder.call(
            self.malloc,
            [builder.mul(new_capacity, ir.const_(i64, 8))],
        )
        builder.cbranch(
            builder.icmp_signed(">", length, zero64), copy_block, do_push
        )

        builder.position_at_end(copy_block)
        old_items = builder.load(_struct_gep(builder, struct_ptr, 2))
        builder.call(
            self.memcpy,
            [
                fresh,
                old_items,
                builder.mul(length, ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.store(new_capacity, _struct_gep(builder, struct_ptr, 1))
        builder.store(fresh, _struct_gep(builder, struct_ptr, 2))
        builder.branch(do_push)

        builder.position_at_end(do_push)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        length_now = builder.load(_struct_gep(builder, struct_ptr, 0))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        owned = builder.call(self.rawstr_copy, [elem_arg])
        builder.store(
            builder.ptrtoint(owned, i64), builder.gep(items_i64, [length_now])
        )
        new_length = builder.add(length_now, one64)
        builder.store(new_length, _struct_gep(builder, struct_ptr, 0))
        builder.ret(new_length)

        # i8* rawlist_str_join(i8* list, i8* sep) - one allocation for
        # sep.join(parts); two passes: size, then copy
        self.rawlist_str_join = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i8p], False), 'rawlist_str_join',

        )
        f_join = self.rawlist_str_join
        join_entry = f_join.append_basic_block("entry")
        join_size_cond = f_join.append_basic_block("join_size_cond")
        join_size = f_join.append_basic_block("join_size")
        join_alloc = f_join.append_basic_block("join_alloc")
        join_copy_cond = f_join.append_basic_block("join_copy_cond")
        join_body = f_join.append_basic_block("join_body")
        join_done = f_join.append_basic_block("join_done")
        jb = ir.builder_(join_entry)
        join_list, join_sep = f_join.args
        join_struct = jb.bitcast(
            join_list, ir.PointerType(self.raw_list_struct_type)
        )
        join_count = jb.load(_struct_gep(jb, join_struct, 0))
        sep_struct = jb.bitcast(join_sep, ir.PointerType(self.rawstr_struct_type))
        sep_len = jb.load(_struct_gep(jb, sep_struct, 0))
        sep_data = jb.load(_struct_gep(jb, sep_struct, 2))
        size_ptr = jb.alloca(i64, None, 'join_total')
        jb.store(zero64, size_ptr)
        size_i_ptr = jb.alloca(i64, None, 'join_si')
        jb.store(zero64, size_i_ptr)
        out_ptr = jb.alloca(i8p, None, 'join_out')
        jb.branch(join_size_cond)

        jb.position_at_end(join_size_cond)
        si = jb.load(size_i_ptr)
        jb.cbranch(jb.icmp_signed("<", si, join_count), join_size, join_alloc)

        jb.position_at_end(join_size)
        item_struct = jb.bitcast(
            self._join_item_at(jb, join_struct, si), ir.PointerType(self.rawstr_struct_type)
        )
        item_len = jb.load(_struct_gep(jb, item_struct, 0))
        total_now = jb.load(size_ptr)
        with_sep = jb.add(total_now, item_len)
        not_last = jb.icmp_signed("<", jb.add(si, one64), join_count)
        with_sep = jb.select(not_last, jb.add(with_sep, sep_len), with_sep)
        jb.store(with_sep, size_ptr)
        jb.store(jb.add(si, one64), size_i_ptr)
        jb.branch(join_size_cond)

        jb.position_at_end(join_alloc)
        join_total = jb.load(size_ptr)
        join_buf = jb.call(self.malloc, [join_total])
        jb.store(join_buf, out_ptr)
        jb.store(zero64, size_i_ptr)
        jb.branch(join_copy_cond)

        jb.position_at_end(join_copy_cond)
        ci = jb.load(size_i_ptr)
        jb.cbranch(jb.icmp_signed("<", ci, join_count), join_body, join_done)

        jb.position_at_end(join_body)
        c_not_first = jb.icmp_signed(">", ci, zero64)
        write_at = jb.load(out_ptr)
        write_at = jb.select(
            c_not_first, jb.gep(write_at, [sep_len]), write_at
        )
        sep_blk = f_join.append_basic_block("join_sepblk")
        item_blk = f_join.append_basic_block("join_itemblk")
        jb.cbranch(c_not_first, sep_blk, item_blk)
        jb.position_at_end(sep_blk)
        jb.call(
            self.memcpy,
            [jb.load(out_ptr), sep_data, sep_len, ir.const_(ir.IntType(1), 0)],
        )
        jb.branch(item_blk)
        jb.position_at_end(item_blk)
        c_item = jb.bitcast(
            self._join_item_at(jb, join_struct, ci), ir.PointerType(self.rawstr_struct_type)
        )
        c_item_data = jb.load(_struct_gep(jb, c_item, 2))
        c_item_len = jb.load(_struct_gep(jb, c_item, 0))
        jb.call(
            self.memcpy,
            [write_at, c_item_data, c_item_len, ir.const_(ir.IntType(1), 0)],
        )
        jb.store(jb.gep(write_at, [c_item_len]), out_ptr)
        jb.store(jb.add(ci, one64), size_i_ptr)
        jb.branch(join_copy_cond)

        jb.position_at_end(join_done)
        cp_total = jb.call(self.rawutf8_cp_count, [join_buf, join_total])
        join_mem = jb.call(self.malloc, [ir.const_(i64, 32)])
        join_result = jb.bitcast(
            join_mem, ir.PointerType(self.rawstr_struct_type)
        )
        jb.store(join_total, _struct_gep(jb, join_result, 0))
        jb.store(join_total, _struct_gep(jb, join_result, 1))
        jb.store(join_buf, _struct_gep(jb, join_result, 2))
        jb.store(cp_total, _struct_gep(jb, join_result, 3))
        jb.ret(jb.bitcast(join_result, i8p))

        # i8* rawlist_str_pop(i8* list) - drops the slot and returns a
        # fresh copy (the popped value outlives the list)
        self.rawlist_str_pop = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p], False), 'rawlist_str_pop'
        )
        entry = self.rawlist_str_pop.append_basic_block("entry")
        empty_block = self.rawlist_str_pop.append_basic_block("pop_empty")
        ok_block = self.rawlist_str_pop.append_basic_block("pop_ok")
        builder = ir.builder_(entry)
        struct_ptr = builder.bitcast(
            self.rawlist_str_pop.args[0], ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.cbranch(
            builder.icmp_signed("==", length, zero64), empty_block, ok_block
        )

        builder.position_at_end(empty_block)
        msg = self._create_global_string_with_builder(
            "IndexError: pop from empty list", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        last_index = builder.sub(length, one64)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [last_index])
        bits = builder.load(slot)
        copy = builder.call(
            self.rawstr_copy, [builder.inttoptr(bits, i8p)]
        )
        builder.call(self.rawstr_free, [builder.inttoptr(bits, i8p)])
        builder.store(zero64, slot)
        builder.store(last_index, _struct_gep(builder, struct_ptr, 0))
        builder.ret(copy)

        # ---------- lexer-oriented string builtins (self-hosting) ----------

        b8 = ir.IntType(8)

        # i64 rawstr_ord(i8* s) - code point of a one-character string
        self.rawstr_ord = ir.func_(
            self.module, ir.FunctionType(i64, [i8p], False), 'rawstr_ord'
        )
        f = self.rawstr_ord
        entry = f.append_basic_block("entry")
        ord_panic = f.append_basic_block("ord_panic")
        ord_ok = f.append_basic_block("ord_ok")
        ord_ascii = f.append_basic_block("ord_ascii")
        ord_multi = f.append_basic_block("ord_multi")
        ord_two = f.append_basic_block("ord_two")
        ord_more = f.append_basic_block("ord_more")
        ord_three = f.append_basic_block("ord_three")
        ord_four = f.append_basic_block("ord_four")
        ord_join = f.append_basic_block("ord_join")
        builder = ir.builder_(entry)
        (ord_s,) = f.args
        ord_struct = builder.bitcast(ord_s, ir.PointerType(self.rawstr_struct_type))
        builder.cbranch(
            builder.icmp_signed("==", _rawstr_load_cp(builder, ord_struct), one64),
            ord_ok,
            ord_panic,
        )

        builder.position_at_end(ord_panic)
        ord_msg = self._create_global_string_with_builder(
            "TypeError: ord() expected a character", builder
        )
        self._emit_panic(builder, ord_msg)

        builder.position_at_end(ord_ok)
        ord_data = _rawstr_load_data(builder, ord_struct)
        b0_8 = builder.load(builder.gep(ord_data, [zero64]))
        b0 = builder.zext(b0_8, i64)
        builder.cbranch(
            builder.icmp_signed("<", b0, ir.const_(i64, 0x80)),
            ord_ascii,
            ord_multi,
        )

        builder.position_at_end(ord_ascii)
        builder.ret(b0)

        builder.position_at_end(ord_multi)
        seq = self._emit_seq_len(builder, b0_8)
        builder.cbranch(
            builder.icmp_signed("==", seq, ir.const_(i64, 2)),
            ord_two,
            ord_more,
        )

        builder.position_at_end(ord_two)
        cp2 = builder.or_(
            builder.shl(builder.and_(b0, ir.const_(i64, 0x1F)), ir.const_(i64, 6)),
            builder.and_(_load_byte(builder, ord_data, 1), ir.const_(i64, 0x3F)),
        )
        builder.branch(ord_join)

        builder.position_at_end(ord_more)
        builder.cbranch(
            builder.icmp_signed("==", seq, ir.const_(i64, 3)),
            ord_three,
            ord_four,
        )

        builder.position_at_end(ord_three)
        cp3 = builder.or_(
            builder.or_(
                builder.shl(
                    builder.and_(b0, ir.const_(i64, 0x0F)),
                    ir.const_(i64, 12),
                ),
                builder.shl(
                    builder.and_(_load_byte(builder, ord_data, 1), ir.const_(i64, 0x3F)),
                    ir.const_(i64, 6),
                ),
            ),
            builder.and_(_load_byte(builder, ord_data, 2), ir.const_(i64, 0x3F)),
        )
        builder.branch(ord_join)

        builder.position_at_end(ord_four)
        cp4 = builder.or_(
            builder.or_(
                builder.shl(
                    builder.and_(b0, ir.const_(i64, 0x07)),
                    ir.const_(i64, 18),
                ),
                builder.shl(
                    builder.and_(_load_byte(builder, ord_data, 1), ir.const_(i64, 0x3F)),
                    ir.const_(i64, 12),
                ),
            ),
            builder.or_(
                builder.shl(
                    builder.and_(_load_byte(builder, ord_data, 2), ir.const_(i64, 0x3F)),
                    ir.const_(i64, 6),
                ),
                builder.and_(_load_byte(builder, ord_data, 3), ir.const_(i64, 0x3F)),
            ),
        )
        builder.branch(ord_join)

        builder.position_at_end(ord_join)
        ord_result = builder.phi(i64)
        ord_result.add_incoming(cp2, ord_two)
        ord_result.add_incoming(cp3, ord_three)
        ord_result.add_incoming(cp4, ord_four)
        builder.ret(ord_result)

        # i64 view_ord(i8* data, i64 seq) - decode the UTF-8 sequence a
        # char view points at; seq is the sequence length, no allocation
        self.view_ord = ir.func_(
            self.module, ir.FunctionType(i64, [i8p, i64], False), 'view_ord'
        )
        f = self.view_ord
        v_entry = f.append_basic_block("entry")
        v_one = f.append_basic_block("v_one")
        v_two = f.append_basic_block("v_two")
        v_more = f.append_basic_block("v_more")
        v_three = f.append_basic_block("v_three")
        v_four = f.append_basic_block("v_four")
        v_join = f.append_basic_block("v_join")
        vb = ir.builder_(v_entry)
        (v_data, v_seq) = f.args

        vb.cbranch(
            vb.icmp_signed("==", v_seq, one64), v_one, v_two
        )
        vb.position_at_end(v_one)
        vb.ret(_load_byte(vb, v_data, 0))
        vb.position_at_end(v_two)
        v_b0 = _load_byte(vb, v_data, 0)
        v_c1 = vb.and_(_load_byte(vb, v_data, 1), ir.const_(i64, 0x3F))
        v_cp2 = vb.or_(
            vb.shl(vb.and_(v_b0, ir.const_(i64, 0x1F)), ir.const_(i64, 6)),
            v_c1,
        )
        vb.cbranch(
            vb.icmp_signed("==", v_seq, ir.const_(i64, 2)), v_join, v_more
        )
        vb.position_at_end(v_more)
        v_c2 = vb.and_(_load_byte(vb, v_data, 2), ir.const_(i64, 0x3F))
        v_cp3 = vb.or_(
            vb.or_(
                vb.shl(vb.and_(v_b0, ir.const_(i64, 0x0F)), ir.const_(i64, 12)),
                vb.shl(v_c1, ir.const_(i64, 6)),
            ),
            v_c2,
        )
        vb.cbranch(
            vb.icmp_signed("==", v_seq, ir.const_(i64, 3)), v_three, v_four
        )
        vb.position_at_end(v_three)
        vb.branch(v_join)
        vb.position_at_end(v_four)
        v_cp4 = vb.or_(
            vb.or_(
                vb.shl(vb.and_(v_b0, ir.const_(i64, 0x07)), ir.const_(i64, 18)),
                vb.shl(v_c1, ir.const_(i64, 12)),
            ),
            vb.or_(
                vb.shl(v_c2, ir.const_(i64, 6)),
                vb.and_(_load_byte(vb, v_data, 3), ir.const_(i64, 0x3F)),
            ),
        )
        vb.branch(v_join)
        vb.position_at_end(v_join)
        v_phi = vb.phi(i64)
        v_phi.add_incoming(v_cp2, v_two)
        v_phi.add_incoming(v_cp3, v_three)
        v_phi.add_incoming(v_cp4, v_four)
        vb.ret(v_phi)

        # i8* rawstr_chr(i64 cp) - one-character string from a code point
        self.rawstr_chr = ir.func_(
            self.module, ir.FunctionType(i8p, [i64], False), 'rawstr_chr'
        )
        f = self.rawstr_chr
        entry = f.append_basic_block("entry")
        chr_panic = f.append_basic_block("chr_panic")
        chr_ok = f.append_basic_block("chr_ok")
        chr_one = f.append_basic_block("chr_one")
        chr_more1 = f.append_basic_block("chr_more1")
        chr_two = f.append_basic_block("chr_two")
        chr_more2 = f.append_basic_block("chr_more2")
        chr_three = f.append_basic_block("chr_three")
        chr_four = f.append_basic_block("chr_four")
        chr_make = f.append_basic_block("chr_make")
        builder = ir.builder_(entry)
        (chr_cp,) = f.args
        in_range = builder.and_(
            builder.icmp_signed(">=", chr_cp, zero64),
            builder.icmp_signed("<=", chr_cp, ir.const_(i64, 0x10FFFF)),
        )
        builder.cbranch(in_range, chr_ok, chr_panic)

        builder.position_at_end(chr_panic)
        chr_msg = self._create_global_string_with_builder(
            "ValueError: chr() arg out of range", builder
        )
        self._emit_panic(builder, chr_msg)

        builder.position_at_end(chr_ok)
        chr_buf = builder.alloca(b8, ir.const_(i32, 4), 'chr_buf')
        builder.cbranch(
            builder.icmp_signed("<", chr_cp, ir.const_(i64, 0x80)),
            chr_one,
            chr_more1,
        )

        builder.position_at_end(chr_one)
        _chr_store(builder, chr_buf, 0, chr_cp)
        builder.branch(chr_make)

        builder.position_at_end(chr_more1)
        builder.cbranch(
            builder.icmp_signed("<", chr_cp, ir.const_(i64, 0x800)),
            chr_two,
            chr_more2,
        )

        builder.position_at_end(chr_two)
        _chr_store(builder, chr_buf, 0, builder.or_(ir.const_(i64, 0xC0), builder.lshr(chr_cp, ir.const_(i64, 6))))
        _chr_store(builder, chr_buf, 1, builder.or_(ir.const_(i64, 0x80), builder.and_(chr_cp, ir.const_(i64, 0x3F))))
        builder.branch(chr_make)

        builder.position_at_end(chr_more2)
        builder.cbranch(
            builder.icmp_signed("<", chr_cp, ir.const_(i64, 0x10000)),
            chr_three,
            chr_four,
        )

        builder.position_at_end(chr_three)
        _chr_store(builder, chr_buf, 0, builder.or_(ir.const_(i64, 0xE0), builder.lshr(chr_cp, ir.const_(i64, 12))))
        _chr_store(builder, chr_buf, 1, builder.or_(ir.const_(i64, 0x80), builder.and_(builder.lshr(chr_cp, ir.const_(i64, 6)), ir.const_(i64, 0x3F))))
        _chr_store(builder, chr_buf, 2, builder.or_(ir.const_(i64, 0x80), builder.and_(chr_cp, ir.const_(i64, 0x3F))))
        builder.branch(chr_make)

        builder.position_at_end(chr_four)
        _chr_store(builder, chr_buf, 0, builder.or_(ir.const_(i64, 0xF0), builder.lshr(chr_cp, ir.const_(i64, 18))))
        _chr_store(builder, chr_buf, 1, builder.or_(ir.const_(i64, 0x80), builder.and_(builder.lshr(chr_cp, ir.const_(i64, 12)), ir.const_(i64, 0x3F))))
        _chr_store(builder, chr_buf, 2, builder.or_(ir.const_(i64, 0x80), builder.and_(builder.lshr(chr_cp, ir.const_(i64, 6)), ir.const_(i64, 0x3F))))
        _chr_store(builder, chr_buf, 3, builder.or_(ir.const_(i64, 0x80), builder.and_(chr_cp, ir.const_(i64, 0x3F))))
        builder.branch(chr_make)

        builder.position_at_end(chr_make)
        chr_n = builder.phi(i64)
        chr_n.add_incoming(one64, chr_one)
        chr_n.add_incoming(ir.const_(i64, 2), chr_two)
        chr_n.add_incoming(ir.const_(i64, 3), chr_three)
        chr_n.add_incoming(ir.const_(i64, 4), chr_four)
        builder.ret(builder.call(self.rawstr_new_copy, [chr_buf, chr_n]))

        # i8* rawstr_strip(i8* s) - trim ASCII whitespace at both ends
        self.rawstr_strip = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p], False), 'rawstr_strip'
        )
        f = self.rawstr_strip
        entry = f.append_basic_block("entry")
        lo_cond = f.append_basic_block("strip_lo_cond")
        lo_body = f.append_basic_block("strip_lo_body")
        hi_cond = f.append_basic_block("strip_hi_cond")
        hi_body = f.append_basic_block("strip_hi_body")
        strip_done = f.append_basic_block("strip_done")
        builder = ir.builder_(entry)
        (strip_s,) = f.args
        strip_struct = builder.bitcast(strip_s, ir.PointerType(self.rawstr_struct_type))
        strip_data = _rawstr_load_data(builder, strip_struct)
        strip_len = _rawstr_load_len(builder, strip_struct)
        lo_ptr = builder.alloca(i64, None, 'strip_lo')
        hi_ptr = builder.alloca(i64, None, 'strip_hi')
        builder.store(zero64, lo_ptr)
        builder.store(strip_len, hi_ptr)
        builder.branch(lo_cond)

        builder.position_at_end(lo_cond)
        lo = builder.load(lo_ptr)
        hi = builder.load(hi_ptr)
        lo_in = builder.icmp_signed("<", lo, hi)
        lo_byte = builder.load(builder.gep(strip_data, [lo]))
        lo_ws = _is_ws_byte(builder, lo_byte)
        builder.cbranch(builder.and_(lo_in, lo_ws), lo_body, hi_cond)

        builder.position_at_end(lo_body)
        builder.store(builder.add(lo, one64), lo_ptr)
        builder.branch(lo_cond)

        builder.position_at_end(hi_cond)
        hi = builder.load(hi_ptr)
        lo = builder.load(lo_ptr)
        hi_in = builder.icmp_signed(">", hi, lo)
        hi_byte = builder.load(
            builder.gep(strip_data, [builder.sub(hi, one64)])
        )
        hi_ws = _is_ws_byte(builder, hi_byte)
        builder.cbranch(builder.and_(hi_in, hi_ws), hi_body, strip_done)

        builder.position_at_end(hi_body)
        builder.store(builder.sub(hi, one64), hi_ptr)
        builder.branch(hi_cond)

        builder.position_at_end(strip_done)
        lo = builder.load(lo_ptr)
        hi = builder.load(hi_ptr)
        builder.ret(
            builder.call(
                self.rawstr_new_copy,
                [builder.gep(strip_data, [lo]), builder.sub(hi, lo)],
            )
        )

        # i1 rawstr_starts_with / rawstr_ends_with(i8* s, i8* p, i64 plen)
        self.rawstr_starts_with = self._emit_affix("rawstr_starts_with", True)
        self.rawstr_ends_with = self._emit_affix("rawstr_ends_with", False)

        # i1 rawstr_isdigit / rawstr_isalpha / rawstr_isspace(i8* s):
        # Python semantics = non-empty and every byte qualifies. ASCII is
        # precise; bytes >= 0x80 (non-ASCII code points) count as alpha.
        self.rawstr_isdigit = self._emit_classify("rawstr_isdigit", _pred_digit)
        self.rawstr_isalpha = self._emit_classify("rawstr_isalpha", _pred_alpha)
        self.rawstr_isspace = self._emit_classify("rawstr_isspace", _is_ws_byte)

        # i8* rawstr_split_ws(i8* s) -> rawlist - whitespace-run split
        # with empty-string suppression (Python s.split())
        self.rawstr_split_ws = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p], False), 'rawstr_split_ws'
        )
        f = self.rawstr_split_ws
        entry = f.append_basic_block("entry")
        sw_cond = f.append_basic_block("sw_cond")
        sw_body = f.append_basic_block("sw_body")
        sw_ws = f.append_basic_block("sw_ws")
        sw_push = f.append_basic_block("sw_push")
        sw_skip = f.append_basic_block("sw_skip")
        sw_adv = f.append_basic_block("sw_adv")
        sw_tail = f.append_basic_block("sw_tail")
        sw_tail_push = f.append_basic_block("sw_tail_push")
        sw_done = f.append_basic_block("sw_done")
        builder = ir.builder_(entry)
        (sw_s,) = f.args
        sw_struct = builder.bitcast(sw_s, ir.PointerType(self.rawstr_struct_type))
        sw_data = _rawstr_load_data(builder, sw_struct)
        sw_len = _rawstr_load_len(builder, sw_struct)
        sw_result = builder.call(self.rawlist_new, [ir.const_(i64, 8)])
        i_ptr = builder.alloca(i64, None, 'sw_i')
        start_ptr = builder.alloca(i64, None, 'sw_start')
        builder.store(zero64, i_ptr)
        builder.store(zero64, start_ptr)
        builder.branch(sw_cond)

        builder.position_at_end(sw_cond)
        builder.cbranch(
            builder.icmp_signed("<", builder.load(i_ptr), sw_len),
            sw_body,
            sw_tail,
        )

        builder.position_at_end(sw_body)
        i_val = builder.load(i_ptr)
        byte = builder.load(builder.gep(sw_data, [i_val]))
        builder.cbranch(_is_ws_byte(builder, byte), sw_ws, sw_adv)

        builder.position_at_end(sw_ws)
        # token ends here iff it is non-empty
        builder.cbranch(
            builder.icmp_signed("<", builder.load(start_ptr), i_val),
            sw_push,
            sw_skip,
        )

        builder.position_at_end(sw_push)
        token = builder.call(
            self.rawstr_new_copy,
            [
                builder.gep(sw_data, [builder.load(start_ptr)]),
                builder.sub(i_val, builder.load(start_ptr)),
            ],
        )
        builder.call(self.rawlist_str_push, [sw_result, token])
        builder.call(self.rawstr_free, [token])
        builder.branch(sw_skip)

        builder.position_at_end(sw_skip)
        builder.store(builder.add(i_val, one64), i_ptr)
        builder.store(builder.add(i_val, one64), start_ptr)
        builder.branch(sw_cond)

        builder.position_at_end(sw_adv)
        builder.store(builder.add(i_val, one64), i_ptr)
        builder.branch(sw_cond)

        builder.position_at_end(sw_tail)
        tail_start = builder.load(start_ptr)
        builder.cbranch(
            builder.icmp_signed("<", tail_start, sw_len),
            sw_tail_push,
            sw_done,
        )

        builder.position_at_end(sw_tail_push)
        tail_token = builder.call(
            self.rawstr_new_copy,
            [
                builder.gep(sw_data, [tail_start]),
                builder.sub(sw_len, tail_start),
            ],
        )
        builder.call(self.rawlist_str_push, [sw_result, tail_token])
        builder.call(self.rawstr_free, [tail_token])
        builder.branch(sw_done)

        builder.position_at_end(sw_done)
        builder.ret(sw_result)

        # i8* rawstr_split_sep(i8* s, i8* sep, i64 slen) -> rawlist -
        # literal separator split (Python s.split(sep)); empty sep panics
        self.rawstr_split_sep = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i8p, i64], False), 'rawstr_split_sep',

        )
        f = self.rawstr_split_sep
        entry = f.append_basic_block("entry")
        ss_panic = f.append_basic_block("ss_panic")
        ss_cond = f.append_basic_block("ss_cond")
        ss_try = f.append_basic_block("ss_try")
        ss_mcond = f.append_basic_block("ss_mcond")
        ss_mbody = f.append_basic_block("ss_mbody")
        ss_mcmp = f.append_basic_block("ss_mcmp")
        ss_mnext = f.append_basic_block("ss_mnext")
        ss_match = f.append_basic_block("ss_match")
        ss_adv = f.append_basic_block("ss_adv")
        ss_tail = f.append_basic_block("ss_tail")
        builder = ir.builder_(entry)
        ss_s, sep_data, sep_len = f.args
        ss_struct = builder.bitcast(ss_s, ir.PointerType(self.rawstr_struct_type))
        ss_data = _rawstr_load_data(builder, ss_struct)
        ss_len = _rawstr_load_len(builder, ss_struct)
        builder.cbranch(
            builder.icmp_signed("==", sep_len, zero64), ss_panic, ss_cond
        )

        builder.position_at_end(ss_panic)
        ss_msg = self._create_global_string_with_builder(
            "ValueError: empty separator", builder
        )
        self._emit_panic(builder, ss_msg)

        builder.position_at_end(ss_cond)
        ss_result = builder.call(self.rawlist_new, [ir.const_(i64, 8)])
        i_ptr = builder.alloca(i64, None, 'ss_i')
        start_ptr = builder.alloca(i64, None, 'ss_start')
        j_ptr = builder.alloca(i64, None, 'ss_j')
        builder.store(zero64, i_ptr)
        builder.store(zero64, start_ptr)
        builder.branch(ss_try)

        # while i + slen <= len: try a match at i; else finish
        builder.position_at_end(ss_try)
        i_val = builder.load(i_ptr)
        can_match = builder.icmp_signed(
            "<=", builder.add(i_val, sep_len), ss_len
        )
        builder.cbranch(can_match, ss_mcond, ss_tail)

        builder.position_at_end(ss_mcond)
        builder.store(zero64, j_ptr)
        builder.branch(ss_mbody)

        builder.position_at_end(ss_mbody)
        j_val = builder.load(j_ptr)
        builder.cbranch(
            builder.icmp_signed("<", j_val, sep_len), ss_mcmp, ss_match
        )

        builder.position_at_end(ss_mcmp)
        my_byte = builder.load(
            builder.gep(ss_data, [builder.add(builder.load(i_ptr), j_val)])
        )
        sep_byte = builder.load(builder.gep(sep_data, [j_val]))
        builder.cbranch(
            builder.icmp_signed("==", my_byte, sep_byte), ss_mnext, ss_adv
        )

        builder.position_at_end(ss_mnext)
        builder.store(builder.add(j_val, one64), j_ptr)
        builder.branch(ss_mbody)

        builder.position_at_end(ss_match)
        # token [start, i); resume after the separator
        i_now = builder.load(i_ptr)
        token = builder.call(
            self.rawstr_new_copy,
            [
                builder.gep(ss_data, [builder.load(start_ptr)]),
                builder.sub(i_now, builder.load(start_ptr)),
            ],
        )
        builder.call(self.rawlist_str_push, [ss_result, token])
        builder.call(self.rawstr_free, [token])
        past = builder.add(i_now, sep_len)
        builder.store(past, i_ptr)
        builder.store(past, start_ptr)
        builder.branch(ss_try)

        builder.position_at_end(ss_adv)
        builder.store(builder.add(builder.load(i_ptr), one64), i_ptr)
        builder.branch(ss_try)

        builder.position_at_end(ss_tail)
        tail_token = builder.call(
            self.rawstr_new_copy,
            [
                builder.gep(ss_data, [builder.load(start_ptr)]),
                builder.sub(ss_len, builder.load(start_ptr)),
            ],
        )
        builder.call(self.rawlist_str_push, [ss_result, tail_token])
        builder.call(self.rawstr_free, [tail_token])
        builder.ret(ss_result)

        # void rawlist_str_set(i8* list, i64 index, i8* s) - bounds
        # checked under SILU_CHECKS; frees the old element, stores a copy
        self.rawlist_str_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i8p], False), 'rawlist_str_set',

        )
        entry = self.rawlist_str_set.append_basic_block("entry")
        neg_block = self.rawlist_str_set.append_basic_block("negative")
        bounds_block = self.rawlist_str_set.append_basic_block("bounds")
        ok_block = self.rawlist_str_set.append_basic_block("ok")
        error_block = self.rawlist_str_set.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg, elem_arg = self.rawlist_str_set.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
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
            "IndexError: list assignment index out of range", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [adj_phi])
        old_bits = builder.load(slot)
        is_dead = builder.icmp_signed("==", old_bits, zero64)
        dead_block = self.rawlist_str_set.append_basic_block("set_dead")
        live_block = self.rawlist_str_set.append_basic_block("set_live")
        store_block = self.rawlist_str_set.append_basic_block("set_store")
        builder.cbranch(is_dead, dead_block, live_block)

        builder.position_at_end(dead_block)
        builder.branch(store_block)

        builder.position_at_end(live_block)
        builder.call(self.rawstr_free, [builder.inttoptr(old_bits, i8p)])
        builder.branch(store_block)

        builder.position_at_end(store_block)
        owned = builder.call(self.rawstr_copy, [elem_arg])
        builder.store(builder.ptrtoint(owned, i64), slot)
        builder.ret_void()

        # i8* rawlist_str_get(i8* list, i64 index) - returns a fresh copy
        # (the slot keeps its own); bounds like rawlist_str_set
        self.rawlist_str_get = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i64], False), 'rawlist_str_get',

        )
        entry = self.rawlist_str_get.append_basic_block("entry")
        neg_block = self.rawlist_str_get.append_basic_block("negative")
        bounds_block = self.rawlist_str_get.append_basic_block("bounds")
        ok_block = self.rawlist_str_get.append_basic_block("ok")
        error_block = self.rawlist_str_get.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg = self.rawlist_str_get.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
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
            "IndexError: list index out of range", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        bits = builder.load(builder.gep(items_i64, [adj_phi]))
        copy = builder.call(
            self.rawstr_copy, [builder.inttoptr(bits, i8p)]
        )
        builder.ret(copy)

        # i8* rawlist_str_ptr(i8* list, i64 index) - borrowed pointer for
        # view positions (dict keys); no copy, no bounds re-check beyond
        # the caller's
        self.rawlist_str_ptr = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i64], False), 'rawlist_str_ptr',

        )
        builder = ir.builder_(self.rawlist_str_ptr.append_basic_block("entry"))
        list_arg, index_arg = self.rawlist_str_ptr.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        bits = builder.load(builder.gep(items_i64, [index_arg]))
        builder.ret(builder.inttoptr(bits, i8p))

        # i1 rawlist_str_contains(i8* list, i8* s) - rawstr_eq scan
        self.rawlist_str_contains = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [i8p, i8p], False), 'rawlist_str_contains',

        )
        entry = self.rawlist_str_contains.append_basic_block("entry")
        scan_cond = self.rawlist_str_contains.append_basic_block("scan_cond")
        scan_body = self.rawlist_str_contains.append_basic_block("scan_body")
        scan_step = self.rawlist_str_contains.append_basic_block("scan_step")
        found_block = self.rawlist_str_contains.append_basic_block("found")
        miss_block = self.rawlist_str_contains.append_basic_block("miss")
        builder = ir.builder_(entry)
        list_arg, elem_arg = self.rawlist_str_contains.args
        list_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        list_len = builder.load(
            builder.gep(list_struct, [zero32, ir.const_(i32, 0)])
        )
        items = builder.load(
            builder.gep(list_struct, [zero32, ir.const_(i32, 2)])
        )
        idx_ptr = builder.alloca(i64, None, 'rlsc_i')
        builder.store(zero64, idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        idx = builder.load(idx_ptr)
        builder.cbranch(
            builder.icmp_signed("<", idx, list_len), scan_body, miss_block
        )

        builder.position_at_end(scan_body)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        bits = builder.load(builder.gep(items_i64, [idx]))
        is_match = builder.call(
            self.rawstr_eq,
            [builder.inttoptr(bits, i8p), elem_arg],
        )
        builder.cbranch(is_match, found_block, scan_step)

        builder.position_at_end(scan_step)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(found_block)
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(miss_block)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # void rawlist_str_clear(i8* list) - free every element, keep cap
        self.rawlist_str_clear = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'rawlist_str_clear',

        )
        entry = self.rawlist_str_clear.append_basic_block("entry")
        clear_cond = self.rawlist_str_clear.append_basic_block("clear_cond")
        clear_body = self.rawlist_str_clear.append_basic_block("clear_body")
        clear_skip = self.rawlist_str_clear.append_basic_block("clear_skip")
        clear_done = self.rawlist_str_clear.append_basic_block("clear_done")
        builder = ir.builder_(entry)
        (clear_arg,) = self.rawlist_str_clear.args
        clear_ptr = builder.bitcast(
            clear_arg, ir.PointerType(self.raw_list_struct_type)
        )
        clear_len = builder.load(_struct_gep(builder, clear_ptr, 0))
        clear_items = builder.load(_struct_gep(builder, clear_ptr, 2))
        clear_i = builder.alloca(i64, None, 'rlcl_i')
        builder.store(zero64, clear_i)
        builder.branch(clear_cond)

        builder.position_at_end(clear_cond)
        idx = builder.load(clear_i)
        builder.cbranch(
            builder.icmp_signed("<", idx, clear_len), clear_body, clear_done
        )

        builder.position_at_end(clear_body)
        clear_items_i64 = builder.bitcast(clear_items, ir.PointerType(i64))
        bits = builder.load(builder.gep(clear_items_i64, [idx]))
        is_dead = builder.icmp_signed("==", bits, zero64)
        dead_block = self.rawlist_str_clear.append_basic_block("cl_dead")
        live_block = self.rawlist_str_clear.append_basic_block("cl_live")
        builder.cbranch(is_dead, dead_block, live_block)

        builder.position_at_end(dead_block)
        builder.branch(clear_skip)

        builder.position_at_end(live_block)
        builder.call(self.rawstr_free, [builder.inttoptr(bits, i8p)])
        builder.store(zero64, builder.gep(clear_items_i64, [idx]))
        builder.branch(clear_skip)

        builder.position_at_end(clear_skip)
        builder.store(builder.add(idx, one64), clear_i)
        builder.branch(clear_cond)

        builder.position_at_end(clear_done)
        builder.store(zero64, _struct_gep(builder, clear_ptr, 0))
        builder.ret_void()




        # i1 rawlist_contains_bits(i8* list, i64 elem_bits) - linear scan
        # over the machine-word elements (f64 elements compare as bits)
        self.rawlist_contains_bits = ir.func_(
            self.module, ir.FunctionType(ir.IntType(1), [i8p, i64], False), 'rawlist_contains_bits',

        )
        entry = self.rawlist_contains_bits.append_basic_block("entry")
        scan_cond = self.rawlist_contains_bits.append_basic_block("scan_cond")
        scan_body = self.rawlist_contains_bits.append_basic_block("scan_body")
        scan_step = self.rawlist_contains_bits.append_basic_block("scan_step")
        found_block = self.rawlist_contains_bits.append_basic_block("found")
        miss_block = self.rawlist_contains_bits.append_basic_block("miss")
        builder = ir.builder_(entry)
        list_arg, bits_arg = self.rawlist_contains_bits.args
        list_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        list_len = builder.load(
            builder.gep(list_struct, [zero32, ir.const_(i32, 0)])
        )
        items = builder.bitcast(
            builder.load(builder.gep(list_struct, [zero32, ir.const_(i32, 2)])),
            ir.PointerType(i64),
        )
        idx_ptr = builder.alloca(i64, None, 'rlc_i')
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
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(miss_block)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # PyObject* rawstr_to_pystr(i8* s) - boundary box (data copied)
        self.rawstr_to_pystr = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [i8p], False), 'rawstr_to_pystr',

        )
        builder = ir.builder_(self.rawstr_to_pystr.append_basic_block("entry"))
        (s_arg,) = self.rawstr_to_pystr.args
        s_struct = builder.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = _rawstr_load_len(builder, s_struct)
        s_data = _rawstr_load_data(builder, s_struct)
        box_buffer = builder.call(self.malloc, [s_len])
        builder.call(
            self.memcpy,
            [box_buffer, s_data, s_len, ir.const_(ir.IntType(1), 0)],
        )
        box_len = builder.trunc(s_len, ir.IntType(32))
        builder.ret(builder.call(self.create_str, [box_buffer, box_len]))

        # i8* pystr_to_rawstr(PyObject* obj) - boundary unbox (copies)
        self.pystr_to_rawstr = ir.func_(
            self.module, ir.FunctionType(i8p, [pyobj_ptr], False), 'pystr_to_rawstr'
        )
        entry = self.pystr_to_rawstr.append_basic_block("entry")
        ok_block = self.pystr_to_rawstr.append_basic_block("ok")
        error_block = self.pystr_to_rawstr.append_basic_block("type_error")
        builder = ir.builder_(entry)
        (obj_arg,) = self.pystr_to_rawstr.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_str = builder.icmp_signed("==", tag, ir.const_(i32, 2))
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
            [raw_buffer, box_data, wide_len, ir.const_(ir.IntType(1), 0)],
        )
        wide_cp = builder.call(self.rawutf8_cp_count, [box_data, wide_len])
        struct_ptr = self._build_rawstr(builder, wide_len, wide_len, raw_buffer, wide_cp)
        builder.ret(builder.bitcast(struct_ptr, i8p))

        builder.position_at_end(error_block)
        msg_ptr = builder.gep(type_error_msg, [zero32, zero32])
        self._emit_panic(builder, msg_ptr)


        # ---- str-key raw dicts: dict[str, int] / dict[str, float] ----
        # Same open-addressing layout as the int-key family, but the
        # keys array holds rawstr pointers (as i64). The dict owns a
        # copy of every key (rawstr_copy on insert, rawstr_free on
        # del/clear), so caller-side drops never dangle a key.

        # i8* rawstr_to_cstr(i8* s) - NUL-terminated copy for libc
        # (strtod/strtol); the caller frees the result
        self.rawstr_to_cstr = ir.func_(
            self.module, ir.FunctionType(i8p, [i8p], False), 'rawstr_to_cstr'
        )
        strtol_ty = ir.FunctionType(
            i64, [i8p, ir.PointerType(i8p), i32], False
        )
        self.strtol = ir.func_(self.module, strtol_ty, 'strtol')
        builder = ir.builder_(self.rawstr_to_cstr.append_basic_block("entry"))
        (cstr_arg,) = self.rawstr_to_cstr.args
        cstr_struct = builder.bitcast(
            cstr_arg, ir.PointerType(self.rawstr_struct_type)
        )
        cstr_len = _rawstr_load_len(builder, cstr_struct)
        cstr_data = _rawstr_load_data(builder, cstr_struct)
        cstr_buf = builder.call(self.malloc, [builder.add(cstr_len, one64)])
        builder.call(
            self.memcpy,
            [cstr_buf, cstr_data, cstr_len, ir.const_(ir.IntType(1), 0)],
        )
        builder.store(
            ir.const_(ir.IntType(8), 0), builder.gep(cstr_buf, [cstr_len])
        )
        builder.ret(cstr_buf)

        # i64 rawstr_fnv(i8* s) - FNV-1a over the byte buffer
        self.rawstr_fnv = ir.func_(
            self.module, ir.FunctionType(i64, [i8p], False), 'rawstr_fnv'
        )
        entry = self.rawstr_fnv.append_basic_block("entry")
        fnv_cond = self.rawstr_fnv.append_basic_block("fnv_cond")
        fnv_body = self.rawstr_fnv.append_basic_block("fnv_body")
        fnv_done = self.rawstr_fnv.append_basic_block("fnv_done")
        builder = ir.builder_(entry)
        (fnv_arg,) = self.rawstr_fnv.args
        fnv_struct = builder.bitcast(
            fnv_arg, ir.PointerType(self.rawstr_struct_type)
        )
        fnv_len = builder.load(_struct_gep(builder, fnv_struct, 0))
        fnv_data = builder.load(_struct_gep(builder, fnv_struct, 2))
        fnv_i = builder.alloca(i64, None, 'fnv_i')
        fnv_h = builder.alloca(i64, None, 'fnv_h')
        builder.store(zero64, fnv_i)
        builder.store(ir.const_(i64, 1469598103934665603), fnv_h)
        builder.branch(fnv_cond)

        builder.position_at_end(fnv_cond)
        fnv_idx = builder.load(fnv_i)
        builder.cbranch(
            builder.icmp_signed("<", fnv_idx, fnv_len), fnv_body, fnv_done
        )

        builder.position_at_end(fnv_body)
        fnv_byte = builder.load(builder.gep(fnv_data, [fnv_idx]))
        fnv_byte64 = builder.zext(fnv_byte, i64)
        fnv_hash = builder.load(fnv_h)
        builder.store(
            builder.mul(
                builder.xor(fnv_hash, fnv_byte64),
                ir.const_(i64, 1099511628211),
            ),
            fnv_h,
        )
        builder.store(builder.add(fnv_idx, one64), fnv_i)
        builder.branch(fnv_cond)

        builder.position_at_end(fnv_done)
        builder.ret(builder.load(fnv_h))

        # i64 rawdict_str_get(i8* d, i8* key) - KeyError when missing
        self.rawdict_str_get = self._emit_rawdict_str_probe(
            "rawdict_str_get",
            i64,
            [i8p, i8p],
            lambda b, func, entry_index, _slot, _table: b.ret(
                self._rawdict_load_value_at(b, func, entry_index)
            ),
            self._rawdict_str_key_error,
        )

        # i64 rawdict_str_del(i8* d, i8* key) - tombstones, frees the
        # dict's key copy, returns the value bits
        self.rawdict_str_del = self._emit_rawdict_str_probe(
            "rawdict_str_del", i64, [i8p, i8p], self._rawdict_str_del_hit, self._rawdict_str_key_error
        )

        # i1 rawdict_str_has(i8* d, i8* key)
        self.rawdict_str_has = self._emit_rawdict_str_probe(
            "rawdict_str_has",
            ir.IntType(1),
            [i8p, i8p],
            lambda b, func, entry_index, _slot, _table: b.ret(
                ir.const_(ir.IntType(1), 1)
            ),
            lambda b, func: b.ret(ir.const_(ir.IntType(1), 0)),
        )

        # i64 rawdict_str_get_or(i8* d, i8* key, i64 default_bits)
        self.rawdict_str_get_or = self._emit_rawdict_str_probe(
            "rawdict_str_get_or",
            i64,
            [i8p, i8p, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                self._rawdict_load_value_at(b, func, entry_index)
            ),
            lambda b, func: b.ret(func.args[2]),
        )

        # i64 rawdict_str_pop_or(i8* d, i8* key, i64 default_bits)
        self.rawdict_str_pop_or = self._emit_rawdict_str_probe(
            "rawdict_str_pop_or", i64, [i8p, i8p, i64], self._rawdict_str_del_hit,
            lambda b, func: b.ret(func.args[2]),
        )

        # void rawdict_str_reindex(i8* d, i64 new_size) - compacting
        # rebuild; key pointers move to fresh arrays (ownership stays
        # with the dict, no copies)
        self.rawdict_str_reindex = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64], False), 'rawdict_str_reindex',

        )
        entry = self.rawdict_str_reindex.append_basic_block("entry")
        scan_cond = self.rawdict_str_reindex.append_basic_block("scan_cond")
        scan_body = self.rawdict_str_reindex.append_basic_block("scan_body")
        place_start = self.rawdict_str_reindex.append_basic_block("place_start")
        place_probe = self.rawdict_str_reindex.append_basic_block("place_probe")
        place_store = self.rawdict_str_reindex.append_basic_block("place_store")
        place_step = self.rawdict_str_reindex.append_basic_block("place_step")
        scan_step = self.rawdict_str_reindex.append_basic_block("scan_step")
        scan_done = self.rawdict_str_reindex.append_basic_block("scan_done")
        builder = ir.builder_(entry)
        dict_arg, new_size_arg = self.rawdict_str_reindex.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        old_mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        old_size = builder.add(old_mask, one64)
        old_table = builder.load(_struct_gep(builder, struct_ptr, 4))
        old_keys = builder.load(_struct_gep(builder, struct_ptr, 5))
        old_vals = builder.load(_struct_gep(builder, struct_ptr, 6))
        entries_cap = builder.load(_struct_gep(builder, struct_ptr, 2))
        new_mask = builder.sub(new_size_arg, one64)
        fresh_table = builder.bitcast(
            builder.call(self.calloc, [new_size_arg, ir.const_(i64, 8)]),
            ir.PointerType(i64),
        )
        cap_bytes = builder.mul(entries_cap, ir.const_(i64, 8))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [cap_bytes]), ir.PointerType(i64)
        )
        builder.store(new_mask, _struct_gep(builder, struct_ptr, 3))
        builder.store(fresh_table, _struct_gep(builder, struct_ptr, 4))
        builder.store(fresh_keys, _struct_gep(builder, struct_ptr, 5))
        builder.store(fresh_vals, _struct_gep(builder, struct_ptr, 6))
        idx_ptr = builder.alloca(i64, None, 'sre_i')
        live_ptr = builder.alloca(i64, None, 'sre_live')
        slot_ptr = builder.alloca(i64, None, 'sre_slot')
        builder.store(zero64, idx_ptr)
        builder.store(zero64, live_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        idx = builder.load(idx_ptr)
        builder.cbranch(
            builder.icmp_signed("<", idx, old_size), scan_body, scan_done
        )

        builder.position_at_end(scan_body)
        slot_entry = builder.load(builder.gep(old_table, [idx]))
        is_live = builder.icmp_signed(">", slot_entry, zero64)
        builder.cbranch(is_live, place_start, scan_step)

        builder.position_at_end(place_start)
        entry_index = builder.sub(slot_entry, one64)
        key_bits = builder.load(builder.gep(old_keys, [entry_index]))
        val_val = builder.load(builder.gep(old_vals, [entry_index]))
        live = builder.load(live_ptr)
        builder.store(key_bits, builder.gep(fresh_keys, [live]))
        builder.store(val_val, builder.gep(fresh_vals, [live]))
        key_ptr = builder.inttoptr(key_bits, i8p)
        key_hash = builder.call(self.rawstr_fnv, [key_ptr])
        builder.store(builder.and_(key_hash, new_mask), slot_ptr)
        builder.branch(place_probe)

        builder.position_at_end(place_probe)
        slot_now = builder.load(slot_ptr)
        taken = builder.load(builder.gep(fresh_table, [slot_now]))
        builder.cbranch(
            builder.icmp_signed("!=", taken, zero64), place_step, place_store
        )

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
        builder.store(builder.load(live_ptr), _struct_gep(builder, struct_ptr, 1))
        builder.call(self.free, [builder.bitcast(old_table, i8p)])
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.ret_void()

        # void rawdict_str_set(i8* d, i8* key, i64 value_bits)
        # On insert the dict stores its own rawstr_copy of the key.
        self.rawdict_str_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i8p, i64], False), 'rawdict_str_set',

        )
        entry = self.rawdict_str_set.append_basic_block("entry")
        rehash_block = self.rawdict_str_set.append_basic_block("rehash")
        size_check = self.rawdict_str_set.append_basic_block("size_check")
        size_grow = self.rawdict_str_set.append_basic_block("size_grow")
        size_done = self.rawdict_str_set.append_basic_block("size_done")
        start_block = self.rawdict_str_set.append_basic_block("probe_start")
        probe_test = self.rawdict_str_set.append_basic_block("probe_test")
        tomb_or_match = self.rawdict_str_set.append_basic_block("probe_tomb")
        tomb_note = self.rawdict_str_set.append_basic_block("tomb_note")
        tomb_store = self.rawdict_str_set.append_basic_block("tomb_store")
        match_check = self.rawdict_str_set.append_basic_block("probe_match")
        overwrite = self.rawdict_str_set.append_basic_block("overwrite")
        probe_step = self.rawdict_str_set.append_basic_block("probe_step")
        insert = self.rawdict_str_set.append_basic_block("insert")
        grow_block = self.rawdict_str_set.append_basic_block("grow")
        do_insert = self.rawdict_str_set.append_basic_block("do_insert")
        builder = ir.builder_(entry)
        dict_arg, key_arg, val_arg = self.rawdict_str_set.args
        struct_ptr = builder.bitcast(dict_arg, ir.PointerType(self.raw_dict_struct_type))
        filled = builder.load(_struct_gep(builder, struct_ptr, 1))
        mask = builder.load(_struct_gep(builder, struct_ptr, 3))
        index_size = builder.add(mask, one64)
        load_would_exceed = builder.icmp_signed(
            ">",
            builder.mul(builder.add(filled, one64), ir.const_(i64, 3)),
            builder.mul(index_size, ir.const_(i64, 2)),
        )
        slot_ptr = builder.alloca(i64, None, 'rds_slot')
        tomb_ptr = builder.alloca(i64, None, 'rds_tomb')
        size_ptr = builder.alloca(i64, None, 'rds_size')
        builder.cbranch(load_would_exceed, rehash_block, start_block)

        builder.position_at_end(rehash_block)
        live_count = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.store(ir.const_(i64, 8), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_check)
        size_now = builder.load(size_ptr)
        need_more = builder.icmp_signed(
            ">",
            builder.mul(builder.add(live_count, one64), ir.const_(i64, 3)),
            builder.mul(size_now, ir.const_(i64, 2)),
        )
        builder.cbranch(need_more, size_grow, size_done)

        builder.position_at_end(size_grow)
        builder.store(builder.mul(size_now, ir.const_(i64, 2)), size_ptr)
        builder.branch(size_check)

        builder.position_at_end(size_done)
        builder.call(
            self.rawdict_str_reindex, [dict_arg, builder.load(size_ptr)]
        )
        builder.branch(start_block)

        builder.position_at_end(start_block)
        builder.store(ir.const_(i64, -1), tomb_ptr)
        mask_now = builder.load(_struct_gep(builder, struct_ptr, 3))
        key_hash = builder.call(self.rawstr_fnv, [key_arg])
        builder.store(builder.and_(key_hash, mask_now), slot_ptr)
        builder.branch(probe_test)

        builder.position_at_end(probe_test)
        table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
        slot_now = builder.load(slot_ptr)
        slot_entry = builder.load(builder.gep(table_now, [slot_now]))
        is_empty = builder.icmp_signed("==", slot_entry, zero64)
        builder.cbranch(is_empty, insert, tomb_or_match)

        builder.position_at_end(tomb_or_match)
        is_tomb = builder.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        builder.cbranch(is_tomb, tomb_note, match_check)

        builder.position_at_end(tomb_note)
        tomb_seen = builder.load(tomb_ptr)
        none_yet = builder.icmp_signed("==", tomb_seen, ir.const_(i64, -1))
        builder.cbranch(none_yet, tomb_store, probe_step)

        builder.position_at_end(tomb_store)
        builder.store(slot_now, tomb_ptr)
        builder.branch(probe_step)

        builder.position_at_end(match_check)
        entry_index = builder.sub(slot_entry, one64)
        keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
        stored_key = builder.inttoptr(
            builder.load(builder.gep(keys_now, [entry_index])), i8p
        )
        is_match = builder.call(self.rawstr_eq, [stored_key, key_arg])
        builder.cbranch(is_match, overwrite, probe_step)

        builder.position_at_end(overwrite)
        vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
        builder.store(val_arg, builder.gep(vals_now, [entry_index]))
        builder.ret_void()

        builder.position_at_end(probe_step)
        mask_step = builder.load(_struct_gep(builder, struct_ptr, 3))
        builder.store(
            builder.and_(builder.add(slot_now, one64), mask_step), slot_ptr
        )
        builder.branch(probe_test)

        builder.position_at_end(insert)
        tomb_seen = builder.load(tomb_ptr)
        has_tomb = builder.icmp_signed("!=", tomb_seen, ir.const_(i64, -1))
        target_slot = builder.select(has_tomb, tomb_seen, builder.load(slot_ptr))
        builder.store(target_slot, slot_ptr)
        filled_now = builder.load(_struct_gep(builder, struct_ptr, 1))
        entries_cap = builder.load(_struct_gep(builder, struct_ptr, 2))
        needs_room = builder.icmp_signed("==", filled_now, entries_cap)
        builder.cbranch(needs_room, grow_block, do_insert)

        builder.position_at_end(grow_block)
        new_cap = builder.mul(entries_cap, ir.const_(i64, 2))
        byte_room = builder.mul(new_cap, ir.const_(i64, 8))
        old_keys = builder.load(_struct_gep(builder, struct_ptr, 5))
        old_vals = builder.load(_struct_gep(builder, struct_ptr, 6))
        fresh_keys = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        fresh_vals = builder.bitcast(
            builder.call(self.malloc, [byte_room]), ir.PointerType(i64)
        )
        copy_bytes = builder.mul(filled_now, ir.const_(i64, 8))
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_keys, i8p),
                builder.bitcast(old_keys, i8p),
                copy_bytes,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.call(
            self.memcpy,
            [
                builder.bitcast(fresh_vals, i8p),
                builder.bitcast(old_vals, i8p),
                copy_bytes,
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.store(new_cap, _struct_gep(builder, struct_ptr, 2))
        builder.store(fresh_keys, _struct_gep(builder, struct_ptr, 5))
        builder.store(fresh_vals, _struct_gep(builder, struct_ptr, 6))
        builder.call(self.free, [builder.bitcast(old_keys, i8p)])
        builder.call(self.free, [builder.bitcast(old_vals, i8p)])
        builder.branch(do_insert)

        builder.position_at_end(do_insert)
        slot_free = builder.load(slot_ptr)
        keys_final = builder.load(_struct_gep(builder, struct_ptr, 5))
        vals_final = builder.load(_struct_gep(builder, struct_ptr, 6))
        key_copy = builder.call(self.rawstr_copy, [key_arg])
        builder.store(
            builder.ptrtoint(key_copy, i64),
            builder.gep(keys_final, [filled_now]),
        )
        builder.store(val_arg, builder.gep(vals_final, [filled_now]))
        table_final = builder.load(_struct_gep(builder, struct_ptr, 4))
        builder.store(
            builder.add(filled_now, one64), builder.gep(table_final, [slot_free])
        )
        builder.store(builder.add(filled_now, one64), _struct_gep(builder, struct_ptr, 1))
        count = builder.load(_struct_gep(builder, struct_ptr, 0))
        builder.store(builder.add(count, one64), _struct_gep(builder, struct_ptr, 0))
        builder.ret_void()

        # i64 rawdict_str_setdefault(i8* d, i8* key, i64 value_bits)
        self.rawdict_str_setdefault = self._emit_rawdict_str_probe(
            "rawdict_str_setdefault",
            i64,
            [i8p, i8p, i64],
            lambda b, func, entry_index, _slot, _table: b.ret(
                self._rawdict_load_value_at(b, func, entry_index)
            ),
            self._rawdict_str_setdefault_miss,
        )

        # i8* rawdict_str_slotof(i8* d, i8* key) - value slot pointer
        self.rawdict_str_slotof = self._emit_rawdict_str_probe(
            "rawdict_str_slotof", i8p, [i8p, i8p], self._rawdict_slotof_hit,
            self._rawdict_str_key_error,
        )

        # i8* rawdict_str_entry(i8* d, i8* key, i64 default_bits)
        self.rawdict_str_entry = self._emit_rawdict_str_probe(
            "rawdict_str_entry", i8p, [i8p, i8p, i64],
            self._rawdict_slotof_hit, self._rawdict_str_entry_miss,
        )

        # void rawdict_str_clear(i8* d) - free every key copy, keep table
        self.rawdict_str_clear = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'rawdict_str_clear',

        )
        entry = self.rawdict_str_clear.append_basic_block("entry")
        clear_cond = self.rawdict_str_clear.append_basic_block("clear_cond")
        clear_body = self.rawdict_str_clear.append_basic_block("clear_body")
        clear_done = self.rawdict_str_clear.append_basic_block("clear_done")
        builder = ir.builder_(entry)
        (clear_arg,) = self.rawdict_str_clear.args
        clear_ptr = builder.bitcast(
            clear_arg, ir.PointerType(self.raw_dict_struct_type)
        )
        clear_filled = builder.load(_struct_gep(builder, clear_ptr, 1))
        clear_keys = builder.load(_struct_gep(builder, clear_ptr, 5))
        clear_i = builder.alloca(i64, None, 'rdc_i')
        builder.store(zero64, clear_i)
        builder.branch(clear_cond)

        builder.position_at_end(clear_cond)
        idx = builder.load(clear_i)
        builder.cbranch(
            builder.icmp_signed("<", idx, clear_filled), clear_body, clear_done
        )

        builder.position_at_end(clear_body)
        key_bits = builder.load(builder.gep(clear_keys, [idx]))
        # deleted entries were freed by rawdict_str_del and nulled
        is_dead = builder.icmp_signed("==", key_bits, zero64)
        skip_block = self.rawdict_str_clear.append_basic_block("clear_skip")
        free_block = self.rawdict_str_clear.append_basic_block("clear_free")
        builder.cbranch(is_dead, skip_block, free_block)

        builder.position_at_end(free_block)
        builder.call(self.rawstr_free, [builder.inttoptr(key_bits, i8p)])
        builder.branch(skip_block)

        builder.position_at_end(skip_block)
        builder.store(builder.add(idx, one64), clear_i)
        builder.branch(clear_cond)

        builder.position_at_end(clear_done)
        builder.call(self.rawdict_clear, [clear_arg])
        builder.ret_void()

        # PyObject* rawdict_to_pydict_{si,sf}(i8* d) - str keys box
        # through rawstr_to_pystr; built here because it needs the
        # rawstr runtime (forward reference from the dict section)
        for tag, make_value in (
            ("si", lambda b, bits: b.call(self.create_int, [bits])),
            (
                "sf",
                lambda b, bits: b.call(
                    self.create_float, [b.bitcast(bits, ir.DoubleType())]
                ),
            ),
        ):
            func = ir.func_(
                self.module,
                ir.FunctionType(
                    ir.PointerType(self.pyobj.pyobj_type), [i8p], False
                ), f'rawdict_to_pydict_{tag}',

            )
            entry = func.append_basic_block("entry")
            loop_check = func.append_basic_block("cvt_check")
            loop_body = func.append_basic_block("cvt_body")
            emit_block = func.append_basic_block("cvt_emit")
            loop_step = func.append_basic_block("cvt_step")
            loop_done = func.append_basic_block("cvt_done")
            builder = ir.builder_(entry)
            (dict_arg,) = func.args
            struct_ptr = builder.bitcast(
                dict_arg, ir.PointerType(self.raw_dict_struct_type)
            )
            mask = builder.load(_struct_gep(builder, struct_ptr, 3))
            table_size = builder.add(mask, one64)
            result = builder.call(self.create_dict, [])
            idx_ptr = builder.alloca(i64, None, 'cvt_i')
            builder.store(zero64, idx_ptr)
            builder.branch(loop_check)

            builder.position_at_end(loop_check)
            idx = builder.load(idx_ptr)
            more = builder.icmp_signed("<", idx, table_size)
            builder.cbranch(more, loop_body, loop_done)

            builder.position_at_end(loop_body)
            table_now = builder.load(_struct_gep(builder, struct_ptr, 4))
            slot_entry = builder.load(builder.gep(table_now, [idx]))
            is_live = builder.icmp_signed(">", slot_entry, zero64)
            builder.cbranch(is_live, emit_block, loop_step)

            builder.position_at_end(emit_block)
            entry_index = builder.sub(slot_entry, one64)
            keys_now = builder.load(_struct_gep(builder, struct_ptr, 5))
            vals_now = builder.load(_struct_gep(builder, struct_ptr, 6))
            key_bits = builder.load(builder.gep(keys_now, [entry_index]))
            key_box = builder.call(
                self.rawstr_to_pystr, [builder.inttoptr(key_bits, i8p)]
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
            self.rawdict_to_pydict[tag] = func

        # PyObject* rawlist_str_to_pylist(i8* list, i64 length)
        self.rawlist_str_to_pylist = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [i8p, i64], False), 'rawlist_str_to_pylist',

        )
        entry = self.rawlist_str_to_pylist.append_basic_block("entry")
        loop_check = self.rawlist_str_to_pylist.append_basic_block("cvt_check")
        loop_body = self.rawlist_str_to_pylist.append_basic_block("cvt_body")
        loop_done = self.rawlist_str_to_pylist.append_basic_block("cvt_done")
        builder = ir.builder_(entry)
        list_arg, length_arg = self.rawlist_str_to_pylist.args
        src_struct = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        items = builder.load(_struct_gep(builder, src_struct, 2))
        result = builder.call(self.create_list, [])
        idx_ptr = builder.alloca(i64, None, 'cvt_i')
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        builder.cbranch(
            builder.icmp_signed("<", i_val, length_arg), loop_body, loop_done
        )

        builder.position_at_end(loop_body)
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        bits = builder.load(builder.gep(items_i64, [i_val]))
        boxed = builder.call(
            self.rawstr_to_pystr, [builder.inttoptr(bits, i8p)]
        )
        builder.call(self.list_append, [result, boxed])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(result)

        # i8* pylist_to_rawlist_str(PyObject* list) - box -> raw, copying
        # each element (tag check: non-str elements panic)
        self.pylist_to_rawlist_str = ir.func_(
            self.module,
            ir.FunctionType(i8p, [pyobj_ptr], False), 'pylist_to_rawlist_str',

        )
        entry = self.pylist_to_rawlist_str.append_basic_block("entry")
        loop_check = self.pylist_to_rawlist_str.append_basic_block("p2s_check")
        loop_body = self.pylist_to_rawlist_str.append_basic_block("p2s_body")
        loop_done = self.pylist_to_rawlist_str.append_basic_block("p2s_done")
        builder = ir.builder_(entry)
        (list_arg,) = self.pylist_to_rawlist_str.args
        struct_ptr = builder.bitcast(
            builder.load(builder.gep(list_arg, [zero32b, one32b])),
            ir.PointerType(self.list_struct_type),
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        raw = builder.call(self.rawlist_new, [ir.const_(i64, 8)])
        idx_ptr = builder.alloca(i64, None, 'p2s_i')
        builder.store(zero64, idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        i_val = builder.load(idx_ptr)
        builder.cbranch(
            builder.icmp_signed("<", i_val, length), loop_body, loop_done
        )

        builder.position_at_end(loop_body)
        elem = builder.load(builder.gep(items, [i_val]))
        raw_elem = builder.call(self.pystr_to_rawstr, [elem])
        builder.call(self.rawlist_str_push, [raw, raw_elem])
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret(raw)

        # void rawlist_get(i8* list, i64 index, i8* out_ptr, i64 elem_size)
        # Bounds are checked; OOB aborts like list_get.
        self.rawlist_get = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i8p, i64], False), 'rawlist_get',

        )
        entry = self.rawlist_get.append_basic_block("entry")
        bounds_block = self.rawlist_get.append_basic_block("bounds")
        negative_block = self.rawlist_get.append_basic_block("negative")
        ok_block = self.rawlist_get.append_basic_block("ok")
        error_block = self.rawlist_get.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg, out_arg, size_arg = self.rawlist_get.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
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
            "IndexError: list index out of range", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [adj_phi])
        builder.store(builder.load(slot), builder.bitcast(out_arg, ir.PointerType(i64)))
        builder.ret_void()

        # void rawlist_set(i8* list, i64 index, i8* elem_ptr, i64 elem_size)
        self.rawlist_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [i8p, i64, i8p, i64], False), 'rawlist_set',

        )
        entry = self.rawlist_set.append_basic_block("entry")
        neg_block = self.rawlist_set.append_basic_block("negative")
        bounds_block = self.rawlist_set.append_basic_block("bounds")
        ok_block = self.rawlist_set.append_basic_block("ok")
        error_block = self.rawlist_set.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg, elem_arg, size_arg = self.rawlist_set.args
        struct_ptr = builder.bitcast(
            list_arg, ir.PointerType(self.raw_list_struct_type)
        )
        length = builder.load(_struct_gep(builder, struct_ptr, 0))
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
            "IndexError: list assignment index out of range", builder
        )
        self._emit_panic(builder, msg)

        builder.position_at_end(ok_block)
        items = builder.load(_struct_gep(builder, struct_ptr, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        slot = builder.gep(items_i64, [adj_phi])
        elem_bits = builder.load(builder.bitcast(elem_arg, ir.PointerType(i64)))
        builder.store(elem_bits, slot)
        builder.ret_void()

    def _emit_rawdict_probe(self, name, ret_type, arg_types, on_hit, on_miss):
        """Shared tombstone-skipping probe for rawdict helpers.

        on_hit(builder, func, entry_index) and on_miss(builder, func)
        receive a positioned builder and must ret.
        """
        i64 = ir.IntType(64)
        one64 = ir.const_(i64, 1)
        zero64 = ir.const_(i64, 0)
        func = ir.func_(
            self.module,
            ir.FunctionType(ret_type, arg_types, False), name,

        )
        entry = func.append_basic_block("entry")
        probe_test = func.append_basic_block("probe_test")
        tomb_or_match = func.append_basic_block("probe_tomb")
        match_check = func.append_basic_block("probe_match")
        hit_block = func.append_basic_block("hit")
        probe_step = func.append_basic_block("probe_step")
        miss_block = func.append_basic_block("miss")
        b = ir.builder_(entry)
        dict_arg, key_arg = func.args[0], func.args[1]
        struct_ptr = b.bitcast(
            dict_arg, ir.PointerType(self.raw_dict_struct_type)
        )
        mask = b.load(_struct_gep(b, struct_ptr, 3))
        probe_slot = b.alloca(i64, None, 'probe_slot')
        b.store(b.and_(key_arg, mask), probe_slot)
        b.branch(probe_test)

        b.position_at_end(probe_test)
        table_now = b.load(_struct_gep(b, struct_ptr, 4))
        slot_now = b.load(probe_slot)
        slot_entry = b.load(b.gep(table_now, [slot_now]))
        is_empty = b.icmp_signed("==", slot_entry, zero64)
        b.cbranch(is_empty, miss_block, tomb_or_match)

        b.position_at_end(tomb_or_match)
        is_tomb = b.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        b.cbranch(is_tomb, probe_step, match_check)

        b.position_at_end(match_check)
        entry_index = b.sub(slot_entry, one64)
        keys_now = b.load(_struct_gep(b, struct_ptr, 5))
        stored_key = b.load(b.gep(keys_now, [entry_index]))
        is_match = b.icmp_signed("==", stored_key, key_arg)
        b.cbranch(is_match, hit_block, probe_step)

        b.position_at_end(hit_block)
        hit_slot = table_now
        # on_hit may need the probe slot for tombstoning (pop)
        on_hit(b, func, entry_index, slot_now, hit_slot)

        b.position_at_end(probe_step)
        mask_step = b.load(_struct_gep(b, struct_ptr, 3))
        b.store(b.and_(b.add(slot_now, one64), mask_step), probe_slot)
        b.branch(probe_test)

        b.position_at_end(miss_block)
        on_miss(b, func)
        return func

    def _rawdict_probe_struct(self, b, func):
        return b.bitcast(
            func.args[0], ir.PointerType(self.raw_dict_struct_type)
        )

    def _rawdict_load_value_at(self, b, func, entry_index):
        vals_now = b.load(_struct_gep(b, self._rawdict_probe_struct(b, func), 6))
        return b.load(b.gep(vals_now, [entry_index]))

    def _rawdict_pop_or_hit(self, b, func, entry_index, slot_now, table_now):
        i64 = ir.IntType(64)
        b.store(ir.const_(i64, -1), b.gep(table_now, [slot_now]))
        struct_ptr = self._rawdict_probe_struct(b, func)
        count = b.load(_struct_gep(b, struct_ptr, 0))
        b.store(
            b.sub(count, ir.const_(i64, 1)), _struct_gep(b, struct_ptr, 0)
        )
        b.ret(self._rawdict_load_value_at(b, func, entry_index))

    def _rawdict_setdefault_miss(self, b, func):
        b.call(self.rawdict_set, [func.args[0], func.args[1], func.args[2]])
        b.ret(func.args[2])

    def _rawdict_slotof_hit(self, b, func, entry_index, _slot, _table):
        vals_now = b.load(_struct_gep(b, self._rawdict_probe_struct(b, func), 6))
        b.ret(
            b.bitcast(
                b.gep(vals_now, [entry_index]),
                ir.PointerType(ir.IntType(8)),
            )
        )

    def _rawdict_slotof_miss(self, b, func):
        zero32 = ir.const_(ir.IntType(32), 0)
        self._emit_panic(b, b.gep(self._key_error_msg, [zero32, zero32]))

    def _rawdict_int_entry_miss(self, b, func):
        b.call(
            self.rawdict_set,
            [func.args[0], func.args[1], func.args[2]],
        )
        b.ret(
            b.call(
                self.rawdict_int_slotof, [func.args[0], func.args[1]]
            )
        )

    def _emit_rawdict_str_probe(self, name, ret_type, arg_types, on_hit, on_miss):
        """Tombstone-skipping probe over str keys (FNV-1a hash,
        rawstr_eq match). on_hit(builder, func, entry_index,
        slot_now, table_now) / on_miss(builder, func) must ret."""
        i64 = ir.IntType(64)
        one64 = ir.const_(i64, 1)
        zero64 = ir.const_(i64, 0)
        i8p = ir.PointerType(ir.IntType(8))
        func = ir.func_(
            self.module,
            ir.FunctionType(ret_type, arg_types, False), name,

        )
        entry = func.append_basic_block("entry")
        probe_test = func.append_basic_block("probe_test")
        tomb_or_match = func.append_basic_block("probe_tomb")
        match_check = func.append_basic_block("probe_match")
        hit_block = func.append_basic_block("hit")
        probe_step = func.append_basic_block("probe_step")
        miss_block = func.append_basic_block("miss")
        b = ir.builder_(entry)
        dict_arg, key_arg = func.args[0], func.args[1]
        struct_ptr = b.bitcast(
            dict_arg, ir.PointerType(self.raw_dict_struct_type)
        )
        mask = b.load(_struct_gep(b, struct_ptr, 3))
        probe_slot = b.alloca(i64, None, 'sprobe_slot')
        b.store(
            b.and_(b.call(self.rawstr_fnv, [key_arg]), mask),
            probe_slot,
        )
        b.branch(probe_test)

        b.position_at_end(probe_test)
        table_now = b.load(_struct_gep(b, struct_ptr, 4))
        slot_now = b.load(probe_slot)
        slot_entry = b.load(b.gep(table_now, [slot_now]))
        is_empty = b.icmp_signed("==", slot_entry, zero64)
        b.cbranch(is_empty, miss_block, tomb_or_match)

        b.position_at_end(tomb_or_match)
        is_tomb = b.icmp_signed("==", slot_entry, ir.const_(i64, -1))
        b.cbranch(is_tomb, probe_step, match_check)

        b.position_at_end(match_check)
        entry_index = b.sub(slot_entry, one64)
        keys_now = b.load(_struct_gep(b, struct_ptr, 5))
        stored_bits = b.load(b.gep(keys_now, [entry_index]))
        stored_key = b.inttoptr(stored_bits, i8p)
        is_match = b.call(self.rawstr_eq, [stored_key, key_arg])
        b.cbranch(is_match, hit_block, probe_step)

        b.position_at_end(hit_block)
        on_hit(b, func, entry_index, slot_now, table_now)

        b.position_at_end(probe_step)
        mask_step = b.load(_struct_gep(b, struct_ptr, 3))
        b.store(b.and_(b.add(slot_now, one64), mask_step), probe_slot)
        b.branch(probe_test)

        b.position_at_end(miss_block)
        on_miss(b, func)
        return func

    def _rawdict_str_key_error(self, b, func):
        zero32 = ir.const_(ir.IntType(32), 0)
        self._emit_panic(b, b.gep(self._key_error_msg, [zero32, zero32]))

    def _rawdict_str_del_hit(self, b, func, entry_index, slot_now, table_now):
        i64 = ir.IntType(64)
        zero64 = ir.const_(i64, 0)
        i8p = ir.PointerType(ir.IntType(8))
        keys_now = b.load(_struct_gep(b, self._rawdict_probe_struct(b, func), 5))
        key_bits = b.load(b.gep(keys_now, [entry_index]))
        b.call(self.rawstr_free, [b.inttoptr(key_bits, i8p)])
        # null the entry so rawdict_str_clear skips it (the entries
        # array still holds the dangling pointer otherwise)
        b.store(zero64, b.gep(keys_now, [entry_index]))
        b.store(ir.const_(i64, -1), b.gep(table_now, [slot_now]))
        struct_ptr = self._rawdict_probe_struct(b, func)
        count = b.load(_struct_gep(b, struct_ptr, 0))
        b.store(
            b.sub(count, ir.const_(i64, 1)), _struct_gep(b, struct_ptr, 0)
        )
        b.ret(self._rawdict_load_value_at(b, func, entry_index))

    def _rawdict_str_setdefault_miss(self, b, func):
        b.call(
            self.rawdict_str_set,
            [func.args[0], func.args[1], func.args[2]],
        )
        b.ret(func.args[2])

    def _rawdict_str_entry_miss(self, b, func):
        b.call(
            self.rawdict_str_set,
            [func.args[0], func.args[1], func.args[2]],
        )
        b.ret(
            b.call(
                self.rawdict_str_slotof, [func.args[0], func.args[1]]
            )
        )

    def _emit_seq_len(self, b, byte_value):
        """UTF-8 sequence length from a lead byte (invalid -> 1)."""
        i64 = ir.IntType(64)
        one64 = ir.const_(i64, 1)
        b8 = ir.IntType(8)
        two = b.icmp_signed(
            "==",
            b.and_(byte_value, ir.const_(b8, 0xE0)),
            ir.const_(b8, 0xC0),
        )
        three = b.icmp_signed(
            "==",
            b.and_(byte_value, ir.const_(b8, 0xF0)),
            ir.const_(b8, 0xE0),
        )
        four = b.icmp_signed(
            "==",
            b.and_(byte_value, ir.const_(b8, 0xF8)),
            ir.const_(b8, 0xF0),
        )
        len2 = b.select(four, ir.const_(i64, 4), one64)
        len3 = b.select(three, ir.const_(i64, 3), len2)
        return b.select(two, ir.const_(i64, 2), len3)

    def _build_rawstr(self, builder, header_len, data_len, data_value, cp_len):
        """Shared prologue: fresh struct + data buffer, fields set."""
        i64 = ir.IntType(64)
        fresh = builder.bitcast(
            builder.call(self.malloc, [ir.const_(i64, 32)]),
            ir.PointerType(self.rawstr_struct_type),
        )
        builder.store(header_len, _struct_gep(builder, fresh, 0))
        builder.store(header_len, _struct_gep(builder, fresh, 1))
        builder.store(data_value, _struct_gep(builder, fresh, 2))
        builder.store(cp_len, _struct_gep(builder, fresh, 3))
        return fresh

    def _join_item_at(self, builder, join_struct, index):
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        items = builder.load(_struct_gep(builder, join_struct, 2))
        items_i64 = builder.bitcast(items, ir.PointerType(i64))
        return builder.inttoptr(
            builder.load(builder.gep(items_i64, [index])), i8p
        )

    def _emit_affix(self, fn_name, is_prefix):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        func = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [i8p, i8p, i64], False), fn_name,

        )
        entry = func.append_basic_block("entry")
        cmp_blk = func.append_basic_block("affix_cmp")
        false_blk = func.append_basic_block("affix_false")
        join_blk = func.append_basic_block("affix_join")
        b = ir.builder_(entry)
        s_arg, p_arg, plen_arg = func.args
        s_struct = b.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = _rawstr_load_len(b, s_struct)
        fits = b.icmp_signed("<=", plen_arg, s_len)
        b.cbranch(fits, cmp_blk, false_blk)

        b.position_at_end(cmp_blk)
        s_data = _rawstr_load_data(b, s_struct)
        if not is_prefix:
            s_data = b.gep(s_data, [b.sub(s_len, plen_arg)])
        cmp_r = b.call(self.memcmp, [s_data, p_arg, plen_arg])
        eq = b.icmp_signed("==", cmp_r, ir.const_(i32, 0))
        b.branch(join_blk)

        b.position_at_end(false_blk)
        b.branch(join_blk)

        b.position_at_end(join_blk)
        res = b.phi(ir.IntType(1))
        res.add_incoming(eq, cmp_blk)
        res.add_incoming(ir.const_(ir.IntType(1), 0), false_blk)
        b.ret(res)
        return func


    def _emit_classify(self, fn_name, pred):
        i64 = ir.IntType(64)
        one64 = ir.const_(i64, 1)
        zero64 = ir.const_(i64, 0)
        i8p = ir.PointerType(ir.IntType(8))
        func = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [i8p], False), fn_name,

        )
        entry = func.append_basic_block("entry")
        cond = func.append_basic_block("cls_cond")
        body = func.append_basic_block("cls_body")
        fail_blk = func.append_basic_block("cls_fail")
        done_blk = func.append_basic_block("cls_done")
        b = ir.builder_(entry)
        (s_arg,) = func.args
        s_struct = b.bitcast(s_arg, ir.PointerType(self.rawstr_struct_type))
        s_len = _rawstr_load_len(b, s_struct)
        s_data = _rawstr_load_data(b, s_struct)
        idx_ptr = b.alloca(i64, None, 'cls_i')
        b.store(zero64, idx_ptr)
        b.cbranch(b.icmp_signed("==", s_len, zero64), fail_blk, cond)

        b.position_at_end(cond)
        idx = b.load(idx_ptr)
        b.cbranch(b.icmp_signed("<", idx, s_len), body, done_blk)

        b.position_at_end(body)
        byte = b.load(b.gep(s_data, [idx]))
        ok_blk = func.append_basic_block("cls_ok")
        b.cbranch(pred(b, byte), ok_blk, fail_blk)

        b.position_at_end(ok_blk)
        b.store(b.add(idx, one64), idx_ptr)
        b.branch(cond)

        b.position_at_end(fail_blk)
        b.ret(ir.const_(ir.IntType(1), 0))

        b.position_at_end(done_blk)
        b.ret(ir.const_(ir.IntType(1), 1))
        return func


    def _emit_unbox(self, name, out_type, message, convert_payload):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        func = ir.func_(
            self.module, ir.FunctionType(out_type, [pyobj_ptr], False), name
        )
        entry = func.append_basic_block("entry")
        ok_block = func.append_basic_block("unbox_ok")
        bad_block = func.append_basic_block("unbox_bad")
        builder = ir.builder_(entry)
        (obj_arg,) = func.args
        is_null = builder.icmp_signed("==", obj_arg, ir.const_(pyobj_ptr, None))
        builder.cbranch(is_null, bad_block, ok_block)

        builder.position_at_end(ok_block)
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        # int and bool payloads both feed i64 conversion
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        as_i64 = builder.load(builder.bitcast(data, ir.PointerType(i64)))
        builder.ret(convert_payload(builder, tag, as_i64, data))

        builder.position_at_end(bad_block)
        msg = self._create_global_string_with_builder(message, builder)
        self._emit_panic(builder, msg)
        return func

    def _dict_value_bits(self, value_node, value_kind):
        value = self._coerce(self._convert_node(value_node), value_kind)
        bits = value[1]
        if value_kind == F64:
            bits = self.current_builder.bitcast(
                value[1], ir.IntType(64)
            )
        return bits

    def _dict_bits_to_value(self, bits, value_kind):
        if value_kind == F64:
            return (
                F64,
                self.current_builder.bitcast(bits, ir.DoubleType()),
            )
        return (I64, bits)

    def _match_pattern_parts(self, pattern, subject_kind, subject_tv):
        """(condition_or_None, capture_name_or_None). A None condition
        means the pattern always matches (capture/wildcard)."""
        if not isinstance(pattern, (list, tuple)) or not pattern:
            raise NotImplementedError("unsupported match pattern")
        kind_tag = pattern[0]
        if kind_tag == "match_value":
            return self._match_value_condition(pattern[1], subject_kind, subject_tv), None
        if kind_tag == "match_or":
            cond = None
            for alt in pattern[1]:
                alt_cond, capture = self._match_pattern_parts(alt, subject_kind, subject_tv)
                if capture is not None:
                    raise NotImplementedError(
                        "capture inside an or-pattern is not supported "
                        "in compiled code"
                    )
                cond = (
                    alt_cond
                    if cond is None
                    else self.current_builder.or_(cond, alt_cond)
                )
            return cond, None
        if kind_tag == "match_singleton":
            # True / False (None stays interpreter-only)
            value = pattern[1]
            if not isinstance(value, bool):
                raise NotImplementedError(
                    "compiled match does not support None patterns"
                )
            return self._match_value_condition(["const", int(value)], subject_kind, subject_tv), None
        if kind_tag == "match_as":
            nested, capture = pattern[1], pattern[2]
            if nested is not None:
                raise NotImplementedError(
                    "compiled match does not support nested capture "
                    "patterns"
                )
            return None, capture  # capture may be None (wildcard)
        raise NotImplementedError(
            f"compiled match does not support '{kind_tag}' patterns "
            "(value / or / capture / wildcard / guard only)"
        )


    def _match_value_condition(self, value_node, subject_kind, subject_tv):
        """i1 condition: subject == the pattern's value."""
        if subject_kind == RAWSTR:
            if (
                isinstance(value_node, list)
                and len(value_node) >= 2
                and value_node[0] == "const"
                and isinstance(value_node[1], str)
            ):
                text = value_node[1]
                return self.current_builder.call(
                    self.rawstr_eq_cstr,
                    [
                        subject_tv[1],
                        self._create_global_string(text),
                        ir.const_(
                            ir.IntType(64), len(text.encode("utf-8"))
                        ),
                    ],
                )
            value_tv = self._coerce(self._convert_node(value_node), RAWSTR)
            cond = self.current_builder.call(
                self.rawstr_eq, [subject_tv[1], value_tv[1]]
            )
            self.current_builder.call(self.rawstr_free, [value_tv[1]])
            return cond
        target_kind = I64 if subject_kind == I1 else subject_kind
        value_tv = self._coerce(
            self._convert_node(value_node), target_kind
        )
        if subject_kind == F64:
            return self.current_builder.fcmp_ordered(
                "==", subject_tv[1], value_tv[1]
            )
        if subject_kind == I1:
            subject_i64 = self.current_builder.zext(
                subject_tv[1], ir.IntType(64)
            )
            return self.current_builder.icmp_signed(
                "==", subject_i64, value_tv[1]
            )
        return self.current_builder.icmp_signed(
            "==", subject_tv[1], value_tv[1]
        )


    def _count_scalar_uses(self, node, scalar_uses, other_uses):
        if not isinstance(node, (list, tuple)):
            return
        if (
            len(node) >= 3
            and node[0] == "subscript"
            and isinstance(node[1], (list, tuple))
            and len(node[1]) >= 2
            and node[1][0] == "name"
            and isinstance(node[2], (list, tuple))
            and len(node[2]) >= 2
            and node[2][0] == "const"
            and node[2][1] == 0
        ):
            name = node[1][1]
            scalar_uses[name] = scalar_uses.get(name, 0) + 1
            return  # the index expression belongs to other names
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 2
            and node[0] == "name"
            and isinstance(node[1], str)
        ):
            name = node[1]
            other_uses[name] = other_uses.get(name, 0) + 1
            return
        for child in node:
            self._count_scalar_uses(child, scalar_uses, other_uses)

    def _scan_calls(self, node: Any, calls: Dict[str, list]):
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
            self._scan_calls(child, calls)

    def _rawstr_finish(self, temp, result):
        if temp is not None:
            self.current_builder.call(self.rawstr_free, [temp])
        return result

    def _create_unbox_runtime(self):
        """unbox helpers for the typed -> dynamic -> typed boundary."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)

        self.unbox_int = self._emit_unbox(
            "unbox_int",
            i64,
            "TypeError: expected an int value",
            lambda b, tag, as_i64, data: as_i64,
        )
        self.unbox_float = self._emit_unbox(
            "unbox_float",
            ir.DoubleType(),
            "TypeError: expected a float value",
            lambda b, tag, as_i64, data: b.select(
                b.icmp_signed("==", tag, ir.const_(ir.IntType(32), 1)),
                b.load(b.bitcast(data, ir.PointerType(ir.DoubleType()))),
                b.sitofp(as_i64, ir.DoubleType()),
            ),
        )
        self.unbox_bool = self._emit_unbox(
            "unbox_bool",
            ir.IntType(1),
            "TypeError: expected a bool value",
            lambda b, tag, as_i64, data: b.icmp_signed(
                "!=", as_i64, ir.const_(ir.IntType(64), 0)
            ),
        )

    # ================== value plumbing ==================

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
        if kind == RAWCHAR_VIEW:
            return self._box(self._coerce(tv, RAWSTR))
        if kind == OBJ:
            return value
        if kind in RAWLIST_KINDS:
            if kind == RAWLIST_S:
                converter = self.rawlist_str_to_pylist
            elif kind == RAWLIST_F:
                converter = self.rawlist_to_pylist_f64
            else:
                converter = self.rawlist_to_pylist
            return self.current_builder.call(
                converter,
                [value, self.current_builder.call(self.rawlist_len, [value])],
            )
        if kind in RAWDICT_KINDS:
            converter = self.rawdict_to_pydict[
                {RAWDICT_II: "ii", RAWDICT_IF: "if",
                 RAWDICT_SI: "si", RAWDICT_SF: "sf"}[kind]
            ]
            return self.current_builder.call(converter, [value])
        if kind == RAWSTR:
            return self.current_builder.call(self.rawstr_to_pystr, [value])
        if kind == I64:
            return self.current_builder.call(self.create_int, [value])
        if kind == F64:
            return self.current_builder.call(self.create_float, [value])
        if kind == I1:
            return self.current_builder.call(self.create_bool, [value])
        if kind == INSTANCE:
            raise NotImplementedError(
                "class instances cannot be boxed yet "
                "(print a field, not the instance)"
            )
        raise ValueError(f"unknown kind {kind}")

    def _unbox(self, obj: Any, kind: str) -> Any:
        """PyObject* -> raw value of `kind` (panics on type mismatch)."""
        if kind == INSTANCE:
            # the None literal coercing to an instance is the null
            # pointer - same model `x is None` already uses
            return self.current_builder.bitcast(
                obj, LLVM_KIND_TYPES[INSTANCE]
            )
        if kind == RAWLIST_S:
            return self.current_builder.call(
                self.pylist_to_rawlist_str, [obj]
            )
        if kind == RAWLIST_I:
            return self.current_builder.call(self.pylist_to_rawlist, [obj])
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
        if kind == RAWCHAR_VIEW:
            # a borrowed window coerces to an owned string (copy) or to
            # its i64 sequence length; anything else is a type error
            if target == RAWSTR:
                data = self.current_builder.extract_value(value, 0)
                seq = self.current_builder.extract_value(value, 1)
                return (
                    RAWSTR,
                    self.current_builder.call(
                        self.rawstr_new_copy, [data, seq]
                    ),
                )
            if target == I64:
                return (I64, self.current_builder.extract_value(value, 1))
            raise ValueError(f"cannot coerce {kind} to {target}")
        if kind == OBJ:
            return (target, self._unbox(value, target))
        if kind == I1 and target == I64:
            return (I64, self.current_builder.zext(value, ir.IntType(64)))
        if kind == I64 and target == INSTANCE:
            # list[Token] element read: the stored word is the pointer
            return (
                INSTANCE,
                self.current_builder.inttoptr(
                    value, LLVM_KIND_TYPES[INSTANCE]
                ),
            )
        if kind == INSTANCE and target == I64:
            # list[Token] append path: the pointer rides as a word
            return (
                I64,
                self.current_builder.ptrtoint(value, ir.IntType(64)),
            )
        if kind == I64 and target == F64:
            return (F64, self.current_builder.sitofp(value, ir.DoubleType()))
        if kind == F64 and target == I64:
            checked = self.current_builder.fptosi(value, ir.IntType(64))
            if self.checks:
                # lossy truncation panics (Python int(2.5) would silently
                # truncate; Silu's int() on a non-integral float is an
                # error, matching the annotation contract for x: int = f)
                roundtrip = self.current_builder.sitofp(checked, ir.DoubleType())
                exact = self.current_builder.fcmp_ordered("==", value, roundtrip)
                self._panic_if(
                    self.current_builder.not_(exact),
                    "TypeError: float cannot be used as int",
                )
            return (I64, checked)
        if kind == I64 and target == I1:
            return (
                I1,
                self.current_builder.icmp_signed(
                    "!=", value, ir.const_(ir.IntType(64), 0)
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
        self._emit_panic(self.current_builder, msg)
        self.current_builder.position_at_end(ok_block)

    def _rawstr_append_operand(self, rhs_node: Any) -> Tuple[Any, Any, Any]:
        """(data_ptr, byte_len, temp) for rawstr_append.

        String literals stream straight from their global constant;
        rawstr values pass their own buffer (append's realloc never
        moves a foreign buffer); anything dynamic is boxed and copied
        out through the unbox boundary first - that copy is a temporary
        the caller frees after the append (Rust end-of-statement drop).
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
                ir.const_(ir.IntType(64), len(text.encode("utf-8"))),
                None,
            )
        rhs_tv = self._convert_node(rhs_node)
        temp = None
        if rhs_tv[0] == RAWSTR:
            raw_ptr = rhs_tv[1]
        else:
            raw_ptr = self._coerce(rhs_tv, RAWSTR)[1]
            temp = raw_ptr
        struct_ptr = self.current_builder.bitcast(
            raw_ptr, ir.PointerType(self.rawstr_struct_type)
        )
        length = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        data = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 2)],
            )
        )
        return data, length, temp

    def _rawstr_operand(self, tv: Tuple[str, Any]) -> Tuple[Any, Any]:
        """(ptr, temp) for one-shot rawstr consumers (binop, compare,
        contains): a slot's buffer is borrowed, a coerced value is a
        temporary the caller frees after the consuming call."""
        if tv[0] == RAWSTR:
            return tv[1], None
        raw_ptr = self._coerce(tv, RAWSTR)[1]
        return raw_ptr, raw_ptr

    def _to_i1_cond(self, tv: Tuple[str, Any]) -> Any:
        """Condition value -> i1 (direct, or Python truthiness for obj)."""
        kind, value = tv
        if kind == I1:
            return value
        if kind == I64:
            return self.current_builder.icmp_signed(
                "!=", value, ir.const_(ir.IntType(64), 0)
            )
        if kind == F64:
            return self.current_builder.fcmp_ordered(
                "!=", value, ir.const_(ir.DoubleType(), 0.0)
            )
        if kind == RAWSTR:
            # Python truthiness: the empty string is false
            struct_ptr = self.current_builder.bitcast(
                value, ir.PointerType(self.rawstr_struct_type)
            )
            length = self.current_builder.load(
                self.current_builder.gep(
                    struct_ptr,
                    [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
                )
            )
            return self.current_builder.icmp_signed(
                "!=", length, ir.const_(ir.IntType(64), 0)
            )
        return self._emit_truthiness(value)

    def _is_bool_singleton(self, tv: Tuple[str, Any], want: bool) -> Any:
        """`x is True` / `x is False`: identity with the bool singleton.

        Truthiness is wrong here - `"s" is True` is False in Python. A
        boxed object matches only when its tag is bool (3) and the payload
        equals the wanted constant; an unboxed I1 compares directly; any
        other representation is never the singleton."""
        builder = self.current_builder
        if tv[0] == I1:
            return builder.icmp_signed(
                "==", tv[1], ir.const_(ir.IntType(1), int(want))
            )
        if tv[0] == OBJ:
            boxed = tv[1]
            non_null = builder.icmp_signed(
                "!=", boxed, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
            )
            tag_ptr = builder.gep(
                boxed, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
            )
            tag = builder.load(tag_ptr)
            is_bool = builder.icmp_signed(
                "==", tag, ir.const_(ir.IntType(32), 3)
            )
            data_ptr_field = builder.gep(
                boxed, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
            )
            data_ptr = builder.bitcast(
                builder.load(data_ptr_field), ir.PointerType(ir.IntType(64))
            )
            payload = builder.load(data_ptr)
            value_eq = builder.icmp_signed(
                "==", payload, ir.const_(ir.IntType(64), int(want))
            )
            return builder.and_(non_null, builder.and_(is_bool, value_eq))
        return ir.const_(ir.IntType(1), 0)

    # pyobj type tags: 0=int 1=float 2=str 3=bool 4=list 5=dict;
    # bool is an int subclass, and Silu tuples ARE lists
    _ISINSTANCE_TAGS = {
        "int": (0, 3),
        "float": (1,),
        "str": (2,),
        "bool": (3,),
        "list": (4,),
        "tuple": (4,),
        "dict": (5,),
    }

    def _emit_isinstance(self, value_node, type_node) -> Any:
        """isinstance(x, T) / isinstance(x, (T1, T2)) -> i1.

        Statically-known kinds answer at compile time; boxed values
        compare the runtime tag against every accepted tag."""
        names = []
        if (
            isinstance(type_node, (list, tuple))
            and len(type_node) >= 2
            and type_node[0] == "name"
        ):
            names.append(type_node[1])
        elif (
            isinstance(type_node, (list, tuple))
            and len(type_node) >= 2
            and type_node[0] == "tuple"
        ):
            for element in type_node[1]:
                if (
                    isinstance(element, (list, tuple))
                    and len(element) >= 2
                    and element[0] == "name"
                ):
                    names.append(element[1])
        tags: set = set()
        for name in names:
            tags.update(self._ISINSTANCE_TAGS.get(name, ()))
        if not tags:
            raise NotImplementedError(
                f"isinstance type must be builtin names, got {names!r}"
            )

        kind = self._convert_node(value_node)
        static_yes = {
            I64: tags <= {0, 3} and 0 in tags,
            I1: 3 in tags or (0 in tags and tags <= {0, 3}),
            F64: tags == {1},
            RAWSTR: tags == {2},
        }.get(kind[0])
        if static_yes is not None:
            return ir.const_(ir.IntType(1), int(static_yes))
        if kind[0] in RAWLIST_KINDS:
            return ir.const_(ir.IntType(1), int(tags == {4}))
        if kind[0] in RAWDICT_KINDS:
            return ir.const_(ir.IntType(1), int(tags == {5}))

        boxed = self._box(kind)
        builder = self.current_builder
        # a null PyObject is the None literal - an instance of none of
        # the builtin type names; the tag load must not dereference it
        result = ir.const_(ir.IntType(1), 0)
        if kind[0] == OBJ:
            non_null = builder.icmp_signed(
                "!=", boxed, ir.const_(
                    ir.PointerType(self.pyobj.pyobj_type), None
                )
            )
            func = self.current_function
            entry_block = builder.block
            tags_block = func.append_basic_block("isa_tags")
            merge_block = func.append_basic_block("isa_merge")
            builder.cbranch(non_null, tags_block, merge_block)
            builder.position_at_end(tags_block)
            for tag in sorted(tags):
                tag_ptr = builder.gep(
                    boxed,
                    [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
                )
                tag_val = builder.load(tag_ptr)
                matches = builder.icmp_signed(
                    "==", tag_val, ir.const_(ir.IntType(32), tag)
                )
                result = builder.or_(result, matches)
            builder.branch(merge_block)
            builder.position_at_end(merge_block)
            phi = builder.phi(ir.IntType(1))
            phi.add_incoming(result, tags_block)
            phi.add_incoming(ir.const_(ir.IntType(1), 0), entry_block)
            return phi
        for tag in sorted(tags):
            tag_ptr = builder.gep(
                boxed, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
            )
            tag_val = builder.load(tag_ptr)
            matches = builder.icmp_signed(
                "==", tag_val, ir.const_(ir.IntType(32), tag)
            )
            result = builder.or_(result, matches)
        return result

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
                    or name not in self._module_vars
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
                gv = ir.gvar_(
                    self.module, ir.PointerType(self.pyobj.pyobj_type), name
                )
                gv.initializer = ir.const_(
                    ir.PointerType(self.pyobj.pyobj_type), None
                )
            elif kind in RAW_STORAGE_KINDS:
                gv = ir.gvar_(
                    self.module, ir.PointerType(ir.IntType(8)), name
                )
                gv.initializer = ir.const_(ir.PointerType(ir.IntType(8)), None)
            else:
                gv = ir.gvar_(
                    self.module, LLVM_KIND_TYPES[kind], name
                )
                gv.initializer = ir.const_(LLVM_KIND_TYPES[kind], 0)
            self.variables[name] = gv
        else:
            # locals are always allocated in the entry block: an alloca
            # inside a loop body would run once per iteration (stack
            # growth) and fail dominance on the loop back-edge
            alloca_type = (
                ir.PointerType(self.pyobj.pyobj_type)
                if kind == OBJ
                else ir.PointerType(ir.IntType(8))
                if kind in RAW_STORAGE_KINDS
                else LLVM_KIND_TYPES[kind]
            )
            # one builder, save/restore: two builders over one block
            # track insertion indices independently and corrupt order
            saved_block = self.current_builder.block
            self.current_builder.position_at_start(
                self.current_function.entry_basic_block
            )
            self.variables[name] = self.current_builder.alloca(
                alloca_type, None, name
            )
            if kind == RAWSTR:
                # null-init IN THE ENTRY BLOCK, right after the alloca:
                # a branch-local declaration never executes on other
                # paths, but function-exit drops free every RAWSTR slot -
                # an uninitialized alloca there would free garbage
                self.current_builder.store(
                    ir.const_(ir.PointerType(ir.IntType(8)), None),
                    self.variables[name],
                )
            self.current_builder.position_at_end(saved_block)
        self.var_kinds[name] = kind

    def _check_receiver_methods(self, node: Any) -> None:
        """Existence check for method calls nested inside an attribute
        chain (x.m(...).f): the outer attribute intercepts the call
        before the method-call emitter can reject a missing method.
        Purely static - emits nothing."""
        if not (
            isinstance(node, (list, tuple))
            and len(node) >= 3
            and node[0] == "call"
            and isinstance(node[1], (list, tuple))
            and len(node[1]) >= 3
            and node[1][0] == "attribute"
        ):
            return
        recv_node, method_name = node[1][1], node[1][2]
        cls = self._class_of_node(recv_node)
        if cls is None:
            return
        methods = self._class_layouts[cls]["methods"]
        if method_name not in methods:
            raise AttributeError(
                f"'{cls}' object has no attribute '{method_name}'"
            )

    def _load_var(self, name: str) -> Tuple[str, Any]:
        if name in self.var_kinds:
            kind = self.var_kinds[name]
            return (kind, self.current_builder.load(self.variables[name]))
        if name in self.variables:
            return (OBJ, self.current_builder.load(self.variables[name]))
        if (
            name in self.functions
            or name in self.function_defs
            or name in self._enums
            or name in self._class_layouts
        ):
            # a bare class/function/enum name is only meaningful at a
            # call or attribute site; as a value there is nothing to load
            raise NotImplementedError(
                f"'{name}' used as a value (call it or access a member)"
            )
        # a silent null here becomes a far-away runtime crash; fail now
        raise NameError(f"name '{name}' is not defined")

    def _cursor_slot(self, name: str):
        """The i64 slot backing a promoted scalar cursor (created once
        per scope in the entry block; seeded from the boxed list)."""
        slot_key = ("cursor", name)
        if slot_key in self._cursor_slots:
            return self._cursor_slots[slot_key]
        saved_block = self.current_builder.block
        builder = self.current_builder
        entry = self.current_function.entry_basic_block
        # the slot alloca sits with the other entry allocas; the one-time
        # seed sits at the END of the entry block (before its terminator)
        # - a seed emitted at the first *use* would re-run every loop
        # iteration and clobber the cursor with the boxed list's stale [0]
        builder.position_at_start(entry)
        slot = builder.alloca(ir.IntType(64), None, f'{name}_cur')
        builder.position_at_end(saved_block)
        if entry.is_terminated:
            builder.position_before(entry.terminator)
        else:
            builder.position_at_end(entry)
        boxed = builder.load(self.variables[name])
        out = builder.alloca(ir.IntType(64))
        builder.call(
            self.rawlist_get,
            [boxed, ir.const_(ir.IntType(64), 0),
             builder.bitcast(out, ir.PointerType(ir.IntType(8))),
             ir.const_(ir.IntType(64), 8)],
        )
        builder.store(builder.load(out), slot)
        builder.position_at_end(saved_block)
        self._cursor_slots[slot_key] = slot
        return slot

    def _char_alias_invalidate_before(self, stmt: Any):
        """Kill aliases an upcoming statement would invalidate: any
        call (conservative - the callee may write the parent), any
        write whose target names a parent string, any new char view
        creation (ch2 = s2[j]). Materializes affected aliases into
        their slots first, so later reads still see the old value.

        A compound statement (if/while/for/...) containing a call
        anywhere in its body also kills: a kill inside one branch would
        materialize the slot only on that path, leaving the other arms
        reading an unwritten slot. Killing before the branch dominates
        every arm."""
        if not self._char_aliases:
            return
        op = stmt[0] if isinstance(stmt, (list, tuple)) and stmt else None

        parent_names = set()
        for entry in self._char_aliases.values():
            parent_names.add(entry[0])

        def contains_call(node):
            if isinstance(node, (list, tuple)):
                if len(node) >= 2 and node[0] == "call":
                    return True
                for child in node[1:]:
                    if contains_call(child):
                        return True
                return False
            return False

        if op == "call" or (
            op in (
                "assign", "ann_assign", "aug_assign", "subscript_assign",
                "subscript_aug_assign", "delete",
            )
            and _targets_parent(stmt[1], parent_names)
        ) or (
            op in ("if", "while", "for", "c_for", "try", "with", "match")
            and contains_call(stmt)
        ):
            self._char_alias_kill_all()

    def _char_alias_kill_all(self):
        """Materialize every live alias into its named slot (copy) and
        clear the table - called on any statement that could invalidate
        the borrowed windows (writes to the parent string, any call,
        another char view creation shares nothing but stays simple)."""
        for name, (str_name, _str_tv, index_node) in list(
            self._char_aliases.items()
        ):
            # re-load the parent slot HERE (dominates: this block runs
            # on every path; the cached creation-time load would sit in
            # a loop body block and violate dominance when the loop
            # runs zero times)
            str_tv = self._load_var(str_name)
            index = self.current_builder.load(index_node)
            view = self._emit_char_view(str_tv[1], index)
            coerced = self._coerce(view, RAWSTR)
            self._declare_var(name, RAWSTR)
            self._store_rawstr(name, coerced[1])
        self._char_aliases.clear()

    def _char_alias_read(self, name: str):
        """Replay a live alias as a fresh view (re-runs bounds check and
        offset arithmetic - register work, no allocation)."""
        str_tv, index_node = self._char_aliases[name]
        return self._emit_char_view(str_tv[1], index_node)

    def _entry_alloca(self, ty: Any, name: str):
        """Allocate in the function entry block (a mid-block alloca in a
        loop would grow the stack per iteration)."""
        saved_block = self.current_builder.block
        self.current_builder.position_at_start(
            self.current_function.entry_basic_block
        )
        slot = self.current_builder.alloca(ty, None, name)
        self.current_builder.position_at_end(saved_block)
        return slot

    def _store_rawstr(self, name: str, new_ptr: Any):
        """Drop the slot's previous buffer (Rust drop on overwrite), then
        store the new one. Ownership is exclusive, so freeing the old
        buffer is always safe; slots are null-initialized."""
        old_ptr = self.current_builder.load(self.variables[name])
        self.current_builder.call(self.rawstr_free, [old_ptr])
        self.current_builder.store(new_ptr, self.variables[name])

    def _emit_local_rawstr_drops(self):
        """Rust scope-exit drop for a function's owned rawstr slots.

        Rawstr slots are always exclusively owned (name assignment,
        parameter passing and returns all copy), so freeing every
        function-local slot at each exit is safe; module globals are
        excluded (their names are recorded in _module_kinds)."""
        if self.current_function is None or self.current_function.name == "main":
            return
        module_kinds = self._module_kinds
        for name, kind in list(self.var_kinds.items()):
            if (
                kind == RAWSTR
                and name not in module_kinds
                and name in self.variables
            ):
                self.current_builder.call(
                    self.rawstr_free,
                    [self.current_builder.load(self.variables[name])],
                )

    # statement ops whose returned TypedValue aliases slot storage -
    # their results must never be freed as temporaries
    _STORAGE_ALIASING_STMT_OPS = {
        "assign", "ann_assign", "aug_assign", "tuple_assign",
        "subscript_assign", "subscript_aug_assign", "delete", "return",
        "for", "while", "if", "if_expr", "func_def", "class_def",
        "line", "break", "continue", "pass", "assert", "raise", "try",
        "with", "import", "from_import", "match",
    }

    def _convert_statement(self, stmt: Any):
        return self._convert_statement_scoped(stmt, False)

    def _convert_statement_scoped(self, stmt: Any, skip_func_defs: bool):
        """Convert one statement; a discarded rawstr expression result
        (e.g. shout("x") as a statement) is a temporary and is dropped
        like Rust's end-of-statement temporary drop. Assignment-family
        statements return values that alias slot storage - never freed."""
        self._char_alias_invalidate_before(stmt)
        result = self._convert_node_scoped(stmt, skip_func_defs)
        if (
            isinstance(result, tuple)
            and len(result) == 2
            and result[0] == RAWSTR
            and isinstance(stmt, (list, tuple))
            and stmt
            and stmt[0] not in self._STORAGE_ALIASING_STMT_OPS
        ):
            self.current_builder.call(self.rawstr_free, [result[1]])
        return result

    # ================== arithmetic ==================

    def _promote_pair(self, left: Tuple[str, Any], right: Tuple[str, Any], target: str):
        return self._coerce(left, target), self._coerce(right, target)

    def _typed_binop(self, op: str, left: Tuple[str, Any], right: Tuple[str, Any]):
        if op == "+" and (left[0] == RAWSTR or right[0] == RAWSTR):
            # string concatenation on raw slots: fresh buffer, inputs
            # untouched (t = s + "x" must not disturb s). Raw operands
            # are only read, so they skip the eager-copy coercion;
            # coerced temporaries are dropped after the call.
            a_ptr, a_temp = self._rawstr_operand(left)
            b_ptr, b_temp = self._rawstr_operand(right)
            result = self.current_builder.call(
                self.rawstr_concat, [a_ptr, b_ptr]
            )
            for temp in (a_temp, b_temp):
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
            return (RAWSTR, result)
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
                        "==", r_val, ir.const_(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero",
                )
                return (F64, self.current_builder.fdiv(l_val, r_val))
            if op == "//":
                self._panic_if(
                    self.current_builder.fcmp_ordered(
                        "==", r_val, ir.const_(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero",
                )
                quotient = self.current_builder.fdiv(l_val, r_val)
                return (
                    F64,
                    self.current_builder.call(self.floor_f64, [quotient]),
                )
            if op == "%":
                self._panic_if(
                    self.current_builder.fcmp_ordered(
                        "==", r_val, ir.const_(ir.DoubleType(), 0.0)
                    ),
                    "ZeroDivisionError: division by zero",
                )
                remainder = self.current_builder.frem(l_val, r_val)
                zero = ir.const_(ir.DoubleType(), 0.0)
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
                self.current_builder.icmp_signed("==", r_val, ir.const_(i64, 0)),
                "ZeroDivisionError: division by zero",
            )
            l_f = self.current_builder.sitofp(l_val, ir.DoubleType())
            r_f = self.current_builder.sitofp(r_val, ir.DoubleType())
            return (F64, self.current_builder.fdiv(l_f, r_f))
        if op == "//":
            self._panic_if(
                self.current_builder.icmp_signed("==", r_val, ir.const_(i64, 0)),
                "ZeroDivisionError: division by zero",
            )
            return (I64, self._floor_div_inline(l_val, r_val))
        if op == "%":
            self._panic_if(
                self.current_builder.icmp_signed("==", r_val, ir.const_(i64, 0)),
                "ZeroDivisionError: division by zero",
            )
            return (I64, self._py_mod_inline(l_val, r_val))
        raise NotImplementedError(f"typed binop {op}")

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
            exp = _extract_i64_const(right[1])
            if exp is not None and 0 <= exp <= 64:
                result = ir.const_(i64, 1)
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
            self._panic_if(exact, "TypeError: int pow result not exact")
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
        self._panic_if(overflowed, f"OverflowError: integer overflow in {op}")
        return result

    def _floor_div_inline(self, left: Any, right: Any) -> Any:
        i64 = ir.IntType(64)
        builder = self.current_builder
        quotient = builder.sdiv(left, right)
        remainder = builder.srem(left, right)
        r_ne_zero = builder.icmp_signed("!=", remainder, ir.const_(i64, 0))
        r_negative = builder.icmp_signed("<", remainder, ir.const_(i64, 0))
        right_negative = builder.icmp_signed("<", right, ir.const_(i64, 0))
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adjustment = builder.select(adjust, ir.const_(i64, -1), ir.const_(i64, 0))
        return builder.add(quotient, adjustment)

    def _py_mod_inline(self, left: Any, right: Any) -> Any:
        i64 = ir.IntType(64)
        builder = self.current_builder
        remainder = builder.srem(left, right)
        r_ne_zero = builder.icmp_signed("!=", remainder, ir.const_(i64, 0))
        r_negative = builder.icmp_signed("<", remainder, ir.const_(i64, 0))
        right_negative = builder.icmp_signed("<", right, ir.const_(i64, 0))
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adjustment = builder.select(adjust, right, ir.const_(i64, 0))
        return builder.add(remainder, adjustment)

    def _rawstr_cstr_operands(self, left, right, left_node, right_node, op):
        """(raw_ptr, cdata, clen, flipped) when one side is a rawstr and
        the other a string constant - the constant compares straight
        out of its global with no allocation. Ordering ops flip when
        the constant is on the left."""
        const_node = raw_tv = None
        flipped = False
        if (
            isinstance(left_node, (list, tuple))
            and len(left_node) >= 2
            and left_node[0] == "const"
            and isinstance(left_node[1], str)
            and right[0] == RAWSTR
        ):
            const_node, raw_tv, flipped = left_node, right, True
        elif (
            isinstance(right_node, (list, tuple))
            and len(right_node) >= 2
            and right_node[0] == "const"
            and isinstance(right_node[1], str)
            and left[0] == RAWSTR
        ):
            const_node, raw_tv = right_node, left
        if const_node is None:
            return None
        text = const_node[1]
        data_ptr = self._create_global_string(text)
        return (
            raw_tv[1],
            data_ptr,
            ir.const_(ir.IntType(64), len(text.encode("utf-8"))),
            flipped,
        )

    def _rawstr_at_eq_fusion(
        self, op, left, right, left_node, right_node
    ):
        """s[i] == "c" (any order, == or !=) fused to one runtime call:
        code point offset + length check + memcmp, no char allocation.
        Returns an (I1, value) TypedValue or None when not applicable."""
        if op not in ("==", "!=", "<", "<=", ">", ">="):
            return None

        def const_side(node):
            return (
                isinstance(node, (list, tuple))
                and len(node) >= 2
                and node[0] == "const"
                and isinstance(node[1], str)
            )

        def index_side_node(node):
            return (
                isinstance(node, (list, tuple))
                and len(node) >= 3
                and node[0] == "subscript"
                and isinstance(node[1], (list, tuple))
                and node[1][0] == "name"
                and not (
                    isinstance(node[2], list)
                    and len(node[2]) >= 4
                    and node[2][0] == "slice"
                )
            )

        def index_side(tv, node):
            return tv[0] == RAWSTR and index_side_node(node)

        left_is_index = left is not None and index_side(left, left_node)
        right_is_index = right is not None and index_side(right, right_node)
        if left_node is None:
            # lazy mode: decide from the nodes alone
            left_is_index = index_side_node(left_node)
            right_is_index = index_side_node(right_node)
        if left_is_index and const_side(right_node):
            sub_node, const_node = left_node, right_node
            text, flip = right_node[1], False
        elif right_is_index and const_side(left_node):
            sub_node, const_node = right_node, left_node
            text, flip = left_node[1], True
        else:
            return None

        base_tv = self._convert_node(sub_node[1])
        if base_tv[0] != RAWSTR:
            return None
        index = self._coerce(self._convert_node(sub_node[2]), I64)[1]
        data_ptr = self._create_global_string(text)
        clen = ir.const_(ir.IntType(64), len(text.encode("utf-8")))
        if op in ("==", "!="):
            eq = self.current_builder.call(
                self.rawstr_at_eq_cstr,
                [base_tv[1], index, data_ptr, clen],
            )
            if op == "!=":
                eq = self.current_builder.not_(eq)
            return (I1, eq)
        if flip:
            op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[op]
        order = self.current_builder.call(
            self.rawstr_at_cmp_cstr, [base_tv[1], index, data_ptr, clen]
        )
        return (
            I1,
            self.current_builder.icmp_signed(
                op, order, ir.const_(ir.IntType(64), 0)
            ),
        )

    def _typed_compare(self, op: str, left: Tuple[str, Any], right: Tuple[str, Any], left_node: Any, right_node: Any):
        if left[0] == RAWCHAR_VIEW or right[0] == RAWCHAR_VIEW:
            # view <op> view / const / rawstr: wrap each side in a
            # stack header (borrowed, no allocation) and memcmp.
            # Non-string operands: coerce views to owned and fall
            # through to the generic paths below.
            def view_parts(tv):
                if tv[0] == RAWCHAR_VIEW:
                    return (
                        self.current_builder.extract_value(tv[1], 0),
                        self.current_builder.extract_value(tv[1], 1),
                    )
                return None, None

            l_data, l_seq = view_parts(left)
            r_data, r_seq = view_parts(right)
            if l_data is not None:
                left = (
                    RAWSTR,
                    self._rawstr_stack_view(l_data, l_seq),
                )
            if r_data is not None:
                right = (
                    RAWSTR,
                    self._rawstr_stack_view(r_data, r_seq),
                )
        if left[0] == RAWSTR or right[0] == RAWSTR:
            # raw string comparisons: memcmp semantics, which on UTF-8
            # bytes equals Python's code point ordering; coerced
            # temporaries are dropped after the call. A string constant
            # compares straight out of its global - no allocation.
            # s[i] <op> "<const>" never materializes the character.
            fused = self._rawstr_at_eq_fusion(
                op, left, right, left_node, right_node
            )
            if fused is not None:
                return fused
            if op in ("==", "!="):
                pair = self._rawstr_cstr_operands(left, right, left_node, right_node, op)
                if pair is not None:
                    raw_ptr, cdata, clen, _flipped = pair
                    eq = self.current_builder.call(
                        self.rawstr_eq_cstr, [raw_ptr, cdata, clen]
                    )
                    return (I1, eq if op == "==" else self.current_builder.not_(eq))
            else:
                pair = self._rawstr_cstr_operands(left, right, left_node, right_node, op)
                if pair is not None:
                    raw_ptr, cdata, clen, flipped = pair
                    if flipped:
                        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}[op]
                    order = self.current_builder.call(
                        self.rawstr_cmp_cstr, [raw_ptr, cdata, clen]
                    )
                    return (
                        I1,
                        self.current_builder.icmp_signed(
                            op, order, ir.const_(ir.IntType(64), 0)
                        ),
                    )
            a_ptr, a_temp = self._rawstr_operand(left)
            b_ptr, b_temp = self._rawstr_operand(right)
            if op in ("==", "!="):
                eq = self.current_builder.call(self.rawstr_eq, [a_ptr, b_ptr])
                result = eq if op == "==" else self.current_builder.not_(eq)
            else:
                order = self.current_builder.call(self.rawstr_cmp, [a_ptr, b_ptr])
                result = self.current_builder.icmp_signed(
                    op, order, ir.const_(ir.IntType(64), 0)
                )
            for temp in (a_temp, b_temp):
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
            return (I1, result)

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
            f"AttributeError: raw {raw_kind} has no method '{method_name}'",
            self.current_builder,
        )
        self._emit_panic(self.current_builder, msg)
        self.current_builder.position_at_end(cont_block)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _rawstr_method_call(
        self, obj_tv: Tuple[str, Any], method_name: str, args_node: list
    ) -> Optional[Tuple[str, Any]]:
        """Native rawstr methods (lexer-oriented, see docs/selfhosting.md).
        Returns None for methods that still go through the boxed fallback.
        The receiver may be a slot borrow (RAWSTR), a char view, or a
        boxed string - the latter two arrive as owned copies that this
        call frees (Rust end-of-statement temporary drop)."""
        s_ptr, temp = self._rawstr_operand(obj_tv)

        if method_name == "strip" and not args_node:
            return self._rawstr_finish(temp, 
                (RAWSTR, self.current_builder.call(self.rawstr_strip, [s_ptr]))
            )
        if method_name == "split":
            if not args_node:
                # whitespace runs, empty strings suppressed (Python)
                return self._rawstr_finish(temp, 
                    (
                        RAWLIST_S,
                        self.current_builder.call(self.rawstr_split_ws, [s_ptr]),
                    )
                )
            if len(args_node) == 1:
                data, length, sep_temp = self._rawstr_append_operand(args_node[0])
                result = self.current_builder.call(
                    self.rawstr_split_sep, [s_ptr, data, length]
                )
                if sep_temp is not None:
                    self.current_builder.call(self.rawstr_free, [sep_temp])
                return self._rawstr_finish(temp, (RAWLIST_S, result))
            return self._rawstr_finish(temp, None)
        if method_name in ("startswith", "endswith") and len(args_node) == 1:
            data, length, arg_temp = self._rawstr_append_operand(args_node[0])
            fn = (
                self.rawstr_starts_with
                if method_name == "startswith"
                else self.rawstr_ends_with
            )
            result = self.current_builder.call(fn, [s_ptr, data, length])
            if arg_temp is not None:
                self.current_builder.call(self.rawstr_free, [arg_temp])
            return self._rawstr_finish(temp, (I1, result))
        if method_name in ("isdigit", "isalpha", "isspace") and not args_node:
            fn = {
                "isdigit": self.rawstr_isdigit,
                "isalpha": self.rawstr_isalpha,
                "isspace": self.rawstr_isspace,
            }[method_name]
            return self._rawstr_finish(temp, (I1, self.current_builder.call(fn, [s_ptr])))
        if method_name == "join" and len(args_node) == 1:
            # sep.join(parts): one allocation instead of n appends
            parts_tv = self._convert_node(args_node[0])
            if parts_tv[0] == RAWLIST_S:
                joined = self.current_builder.call(
                    self.rawlist_str_join, [parts_tv[1], s_ptr]
                )
                return self._rawstr_finish(temp, (RAWSTR, joined))
        return self._rawstr_finish(temp, None)

    def _rawdict_key_from_tv(self, kind: str, key_tv: Tuple[str, Any]):
        """Dict key materialization: rawstr pointer for str keys (the
        set path copies it into the dict), machine word for int keys."""
        if kind in RAWDICT_STR_KINDS:
            return self._coerce(key_tv, RAWSTR)[1]
        return self._coerce(key_tv, I64)[1]

    def _rawstr_stack_view(self, data_ptr: Any, byte_len: Any):
        """A stack rawstr struct pointing at borrowed bytes - heap-free
        for dict key operations (the dict only reads, or copies on
        insert). Allocated in the entry block so loops reuse the slot."""
        view = self._entry_alloca(self.rawstr_struct_type, "str_view")
        for field_index, field_value in (
            (0, byte_len),
            (1, byte_len),
            (3, byte_len),  # cp_len unused by dict ops; keep it sane
        ):
            self.current_builder.store(
                field_value,
                self.current_builder.gep(
                    view,
                    [
                        ir.const_(ir.IntType(32), 0),
                        ir.const_(ir.IntType(32), field_index),
                    ],
                ),
            )
        self.current_builder.store(
            data_ptr,
            self.current_builder.gep(
                view,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 2)],
            ),
        )
        return self.current_builder.bitcast(view, ir.PointerType(ir.IntType(8)))

    def _rawstr_key_view_node(self, key_node: Any):
        """(ptr, temp) for a str-dict key position. A slice with
        explicit bounds becomes a view of the parent's bytes (no
        allocation); a boxed str is viewed through its PyObject buffer
        (no conversion); a rawstr is borrowed; anything else coerces
        (pystr_to_rawstr) and is freed by the caller."""
        # d[s[lo:hi]]: view into s, never materializing the slice
        if (
            isinstance(key_node, list)
            and len(key_node) >= 3
            and key_node[0] == "subscript"
            and isinstance(key_node[2], list)
            and len(key_node[2]) >= 4
            and key_node[2][0] == "slice"
            and key_node[2][1] is not None
            and key_node[2][2] is not None
            and (
                key_node[2][3] is None
                or (
                    isinstance(key_node[2][3], list)
                    and key_node[2][3][:2] == ["const", 1]
                )
            )
        ):
            base_tv = self._convert_node(key_node[1])
            if base_tv[0] == RAWSTR:
                lo = self._coerce(
                    self._convert_node(key_node[2][1]), I64
                )[1]
                hi = self._coerce(
                    self._convert_node(key_node[2][2]), I64
                )[1]
                parts = self.current_builder.call(
                    self.rawstr_slice_parts, [base_tv[1], lo, hi]
                )
                data = self.current_builder.extract_value(parts, 0)
                length = self.current_builder.extract_value(parts, 1)
                return self._rawstr_stack_view(data, length), None

        return self._rawstr_key_view_tv(self._convert_node(key_node))

    def _rawstr_key_view_tv(self, key_tv):
        """(ptr, temp) view/borrow for an already-evaluated key value."""
        if key_tv[0] == RAWSTR:
            return key_tv[1], None
        if key_tv[0] == OBJ:
            # view the boxed string's buffer in place; tag-checked so a
            # non-str key fails with the same TypeError as a conversion
            obj = key_tv[1]
            tag = self.current_builder.load(
                self.current_builder.gep(
                    obj, [ir.const_(ir.IntType(32), 0),
                          ir.const_(ir.IntType(32), 0)]
                )
            )
            is_str = self.current_builder.icmp_signed(
                "==", tag, ir.const_(ir.IntType(32), 2)
            )
            func = self.current_builder.function
            ok_block = func.append_basic_block("key_str_ok")
            err_block = func.append_basic_block("key_str_err")
            self.current_builder.cbranch(is_str, ok_block, err_block)

            self.current_builder.position_at_end(err_block)
            msg = self._create_global_string_with_builder(
                "TypeError: expected str key", self.current_builder
            )
            self._emit_panic(self.current_builder, msg)

            self.current_builder.position_at_end(ok_block)
            str_struct = self.current_builder.bitcast(
                self.current_builder.load(
                    self.current_builder.gep(
                        obj, [ir.const_(ir.IntType(32), 0),
                              ir.const_(ir.IntType(32), 1)]
                    )
                ),
                ir.PointerType(self.pyobj.string_type),
            )
            chars = self.current_builder.load(
                self.current_builder.gep(
                    str_struct, [ir.const_(ir.IntType(32), 0),
                                 ir.const_(ir.IntType(32), 1)]
                )
            )
            box_len = self.current_builder.load(
                self.current_builder.gep(
                    str_struct, [ir.const_(ir.IntType(32), 0),
                                 ir.const_(ir.IntType(32), 0)]
                )
            )
            wide_len = self.current_builder.sext(box_len, ir.IntType(64))
            return self._rawstr_stack_view(chars, wide_len), None
        coerced = self._coerce(key_tv, RAWSTR)
        return coerced[1], coerced[1]

    def _rawdict_key_call(
        self,
        kind: str,
        dict_ptr: Any,
        key_node: Any,
        int_fn: Any,
        str_fn: Any,
        tail_args: tuple,
    ):
        """Call a rawdict key operation; a coerced key temporary is
        freed right after the call."""
        if kind in RAWDICT_STR_KINDS:
            key, temp = self._rawstr_key_view_node(key_node)
        else:
            key = self._coerce(self._convert_node(key_node), I64)[1]
            temp = None
        result = self.current_builder.call(
            _rawdict_call_fn(kind, int_fn, str_fn),
            [dict_ptr, key] + list(tail_args),
        )
        if temp is not None:
            self.current_builder.call(self.rawstr_free, [temp])
        return result

    def _rawdict_key_call_tv(
        self,
        kind: str,
        dict_ptr: Any,
        key_tv: Tuple[str, Any],
        int_fn: Any,
        str_fn: Any,
        tail_args: tuple,
    ):
        """Like _rawdict_key_call but for an already-evaluated key
        (the caller converted it to share with sibling branches)."""
        if kind in RAWDICT_STR_KINDS:
            key, temp = self._rawstr_key_view_tv(key_tv)
        else:
            key = self._coerce(key_tv, I64)[1]
            temp = None
        result = self.current_builder.call(
            _rawdict_call_fn(kind, int_fn, str_fn),
            [dict_ptr, key] + list(tail_args),
        )
        if temp is not None:
            self.current_builder.call(self.rawstr_free, [temp])
        return result

    def _typed_contains(self, op: str, item_node: Any, container_node: Any):
        """item in container: native scans for raw containers, boxed
        pyobj_contains for everything else. Result is always i1."""
        container_tv = self._convert_node(container_node)
        if container_tv[0] == RAWSTR:
            needle_ptr, needle_temp = self._rawstr_operand(
                self._convert_node(item_node)
            )
            result = self.current_builder.call(
                self.rawstr_contains, [container_tv[1], needle_ptr]
            )
            if needle_temp is not None:
                self.current_builder.call(self.rawstr_free, [needle_temp])
        elif container_tv[0] in RAWDICT_KINDS:
            result = self._rawdict_key_call(
                container_tv[0], container_tv[1],
                item_node,
                self.rawdict_has, self.rawdict_str_has,
            (),
            )
        elif container_tv[0] == RAWLIST_S:
            elem = self._coerce(self._convert_node(item_node), RAWSTR)
            result = self.current_builder.call(
                self.rawlist_str_contains, [container_tv[1], elem[1]]
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
            if node[1] in self._class_layouts:
                # `st: JointState` - instance pointer, layout from the table
                return INSTANCE
            if node[1] in self._enums:
                # `kind: Color` - enum-typed slots are i64 discriminants
                return I64
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
            if node[2][1] == "str":
                return RAWLIST_S
            if node[2][1] in self._class_layouts:
                # list[Token]: raw pointer array; elements are instance
                # pointers stored as 8-byte words (read back via a
                # class-annotated name or an attribute chain)
                return RAWLIST_I
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
            and _all_name_parts(node[2][1])
        ):
            dict_pair = node[2][1]
            key_annotation = dict_pair[0][1]
            value_annotation = dict_pair[1][1]
            if key_annotation == "int" and value_annotation == "int":
                return RAWDICT_II
            if key_annotation == "int" and value_annotation == "float":
                return RAWDICT_IF
            if key_annotation == "str" and value_annotation == "int":
                return RAWDICT_SI
            if key_annotation == "str" and value_annotation == "float":
                return RAWDICT_SF
        return None

    # ================== conservative kind inference ==================
    def _resolve_kind(
        self,
        node: Any,
        annotations: Dict[str, str],
        candidates: Dict[str, Optional[str]],
        func_ret: Dict[str, str],
    ) -> Optional[str]:
        """Resolve one expression's kind under the given environments.

        Uses only literals, annotated names, names already inferred
        earlier, and outer-scope kinds - never method calls or other
        dynamic values.
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
            return self._resolve_kind(node[1], annotations, candidates, func_ret)
        if op in ("+", "-", "*", "**") and len(node) >= 3:
            return merge_arith(self._resolve_kind(node[1], annotations, candidates, func_ret), self._resolve_kind(node[2], annotations, candidates, func_ret))
        if op in ("/", "//", "%") and len(node) >= 3:
            left, right = self._resolve_kind(node[1], annotations, candidates, func_ret), self._resolve_kind(node[2], annotations, candidates, func_ret)
            if left is None or right is None or OBJ in (left, right):
                return None
            if op == "/":
                return F64  # truediv always rebinds to float
            return F64 if F64 in (left, right) else I64
        if op in ("==", "!=", "<", "<=", ">", ">=", "not", "in", "not in", "is", "is not"):
            return I1  # comparisons produce a bool whatever the operands
        if op in ("and", "or") and len(node) >= 3:
            left, right = self._resolve_kind(node[1], annotations, candidates, func_ret), self._resolve_kind(node[2], annotations, candidates, func_ret)
            return left if left == right else None
        if op == "if_expr" and len(node) >= 4:
            then_kind, else_kind = self._resolve_kind(node[2], annotations, candidates, func_ret), self._resolve_kind(node[3], annotations, candidates, func_ret)
            return then_kind if then_kind == else_kind else None
        if op == "list":
            # [str, str, ...] literal: raw str list when every
            # element resolves to rawstr (a non-constant element
            # resolves dynamically and keeps the list boxed)
            elements = node[1] if len(node) >= 2 else []
            if not elements:
                return None
            kinds = []
            for e in elements:
                kinds.append(self._resolve_kind(e, annotations, candidates, func_ret))
            if kinds and _all_of_kind(kinds, RAWSTR):
                return RAWLIST_S
            return None
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
            base_kind = self._resolve_kind(node[1], annotations, candidates, func_ret)
            if base_kind == RAWLIST_I:
                return I64
            if base_kind == RAWLIST_F:
                return F64
            if base_kind == RAWSTR:
                return RAWSTR  # s[i] / s[a:b] both yield str
        return None


    def _param_shared_names(self) -> set:
        """Names that appear as a parameter of more than one function:
        their boxed list is shared across frames, so per-function slot
        promotion would fork the cursor."""
        seen: Dict[str, int] = {}
        for func_def in self.function_defs.values():
            for param in func_def[2] if len(func_def) > 2 else ():
                seen[param] = seen.get(param, 0) + 1
        repeated = set()
        for name, count in seen.items():
            if count > 1:
                repeated.add(name)
        return repeated

    def _infer_cursors(
        self, stmts: list, shared: set,
        annotations: Dict[str, str],
    ) -> Dict[str, str]:
        annotations = annotations or {}
        """Scalar cursor promotion for one scope (SILU_SCALARS=0 off).

        pos: list[int] whose EVERY occurrence in this scope is the
        one-element subscript pos[0] (read or write) behaves as a
        plain scalar slot; the codegen keeps it in a local i64. Any
        other use of the name - passing pos itself, len(pos), a
        different index, pos = ... (rebind), a for-target - kills the
        candidate. Failure mode is the ordinary boxed path, never
        wrong code. One flat walk, no statement-type dispatch. The
        result is scoped to the caller (no instance state)."""
        if not self.scalar_cursors:
            return {}
        scalar_uses: Dict[str, int] = {}
        other_uses: Dict[str, int] = {}

        self._count_scalar_uses(stmts, scalar_uses, other_uses)
        # only int-element lists promote in this first cut: the slot is
        # an i64 and f64 slots need bit-pattern care end to end
        promoted: Dict[str, str] = {}
        for name, sc in scalar_uses.items():
            if (
                sc > 0
                and other_uses.get(name, 0) == 0
                and name not in shared
                and annotations.get(name) == RAWLIST_I
            ):
                promoted[name] = RAWLIST_I
        return promoted

    def _infer_assign_kinds(
        self, stmts: list, param_kinds: Optional[Dict[str, str]]
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

        self._walk_assign_kinds(stmts, annotations, candidates, func_ret)

        resolved: Dict[str, str] = {}
        for name, kind in candidates.items():
            if kind is not None:
                resolved[name] = kind
        return resolved


    def _add_kind_candidate(self, name: str, kind: Optional[str], annotations: Dict[str, str], candidates: Dict[str, Optional[str]]):
        if name in annotations:
            return  # declared kind always wins
        if kind not in (I64, F64, I1, RAWSTR, RAWLIST_S):
            kind = None
        if name not in candidates:
            candidates[name] = kind
        elif candidates[name] != kind:
            candidates[name] = None  # conflict: keep it dynamic


    def _walk_assign_kinds(self, stmt_list: list, annotations: Dict[str, str], candidates: Dict[str, Optional[str]], func_ret: Dict[str, str]):
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

        for stmt in stmt_list if isinstance(stmt_list, list) else []:
            if not isinstance(stmt, list) or not stmt:
                continue
            op = stmt[0]
            if op == "assign" and isinstance(stmt[1], str):
                self._add_kind_candidate(
                    stmt[1],
                    self._resolve_kind(stmt[2], annotations, candidates, func_ret),
                    annotations, candidates,
                )
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
                if current == self._resolve_kind(stmt[3], annotations, candidates, func_ret):
                    self._add_kind_candidate(stmt[1], current, annotations, candidates)
                else:
                    self._add_kind_candidate(stmt[1], None, annotations, candidates)
            elif op == "for":
                iter_kind = I64 if is_range_call(stmt[2]) else None
                if iter_kind is None:
                    resolved = self._resolve_kind(stmt[2], annotations, candidates, func_ret)
                    if resolved == RAWLIST_I:
                        iter_kind = I64
                    elif resolved == RAWLIST_F:
                        iter_kind = F64
                    elif resolved == RAWLIST_S:
                        iter_kind = RAWSTR  # a copy per iteration
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
                    self._add_kind_candidate(target_name, iter_kind, annotations, candidates)
                self._walk_assign_kinds(stmt[3], annotations, candidates, func_ret)
            elif op == "if" and len(stmt) >= 4:
                self._walk_assign_kinds(stmt[2], annotations, candidates, func_ret)
                self._walk_assign_kinds(stmt[3], annotations, candidates, func_ret)
            elif op == "while" and len(stmt) >= 3:
                self._walk_assign_kinds(stmt[2], annotations, candidates, func_ret)
            # func_def bodies are separate scopes; other statements
            # introduce no assignments in this scope



    def _collect_function_defs(self, node):
        """Also stash the module statement list for signature inference,
        and register class layouts + methods (dataclass semantics)."""
        if isinstance(node, list) and len(node) >= 2 and node[0] == "module":
            self._module_stmt_list = node[1]
            # enums first: member values fold to constants everywhere
            for stmt in node[1]:
                if (
                    isinstance(stmt, list)
                    and len(stmt) >= 3
                    and stmt[0] == "enum_def"
                ):
                    self._register_enum(stmt)
            # pass 1: skeletons, so field annotations resolve class names
            # regardless of definition order (forward/self references)
            for stmt in node[1]:
                if (
                    isinstance(stmt, list)
                    and len(stmt) >= 4
                    and stmt[0] == "class_def"
                ):
                    self._class_layouts.setdefault(
                        stmt[1], {"fields": [], "methods": {}}
                    )
            # pass 2: fill layouts and register methods
            for stmt in node[1]:
                if (
                    isinstance(stmt, list)
                    and len(stmt) >= 4
                    and stmt[0] == "class_def"
                ):
                    self._register_class(stmt)
        if isinstance(node, list) and node and node[0] == "class_def":
            # methods were registered under mangled names by
            # _register_class; the generic walk must not also collect
            # them as top-level functions
            return
        super()._collect_function_defs(node)

    def _register_enum(self, node: list):
        """class Color(Enum): RED = 1 / GREEN - members are i64 constants
        (Rust bare discriminants), folded at compile time."""
        name, members = node[1], node[2]
        table: Dict[str, int] = {}
        next_value = 0
        for member_name, value_node in members:
            if value_node is None:
                value = next_value
            else:
                value = _const_int_of(value_node)
                if value is None:
                    raise NotImplementedError(
                        f"enum '{name}': member '{member_name}' must be an "
                        "integer constant"
                    )
            table[member_name] = value
            next_value = value + 1
        self._enums[name] = table

    def _register_class(self, node: list):
        """Build the compile-time layout table for one class and register
        its methods as ordinary functions under mangled names
        (``JointState.is_moving`` -> ``JointState__is_moving``) with a
        synthesized ``self`` annotation, so the existing signature
        machinery types them like any other function."""
        name, bases, body = node[1], node[2], node[3]
        if bases:
            raise NotImplementedError(
                f"class '{name}': inheritance is not supported"
            )
        fields = []  # [(field_name, kind, default_node_or_None)]
        methods = {}
        seen_default = False
        for stmt in body:
            if not isinstance(stmt, list) or not stmt:
                continue
            op = stmt[0]
            if op == "line":
                continue
            if op == "ann_assign" and len(stmt) >= 4:
                field_name, default_node, annotation = stmt[1], stmt[2], stmt[3]
                kind = self._annotation_kind(annotation)
                if kind is None:
                    raise NotImplementedError(
                        f"class '{name}': unsupported field type for "
                        f"'{field_name}'"
                    )
                # instance fields (a class as the annotation) are pointer
                # slots with reference semantics, like containers
                field_class = None
                if kind == INSTANCE:
                    field_class = (
                        annotation[1]
                        if isinstance(annotation, list)
                        and len(annotation) >= 2
                        and annotation[0] == "name"
                        else None
                    )
                    if default_node is not None:
                        raise NotImplementedError(
                            f"class '{name}': instance field '{field_name}' "
                            "cannot have a default (pass it explicitly)"
                        )
                # container fields keep their element class so
                # `holder.arr[0].s` (field -> subscript -> attribute)
                # resolves through _class_of_node
                if kind in RAWLIST_KINDS and (
                    isinstance(annotation, list)
                    and len(annotation) >= 3
                    and annotation[0] == "subscript"
                    and isinstance(annotation[2], list)
                    and len(annotation[2]) >= 2
                    and annotation[2][0] == "name"
                ):
                    elem_name = annotation[2][1]
                    if elem_name in self._class_layouts:
                        self._field_elem_class[(name, field_name)] = elem_name
                has_default = default_node is not None
                if seen_default and not has_default:
                    raise TypeError(
                        f"class '{name}': field '{field_name}' without default "
                        "follows a field with a default"
                    )
                seen_default = seen_default or has_default
                fields.append((field_name, kind, default_node, field_class))
            elif op == "func_def" and len(stmt) >= 6:
                method_name = stmt[1]
                params, mbody = stmt[2], stmt[3]
                if method_name == "__init__":
                    raise TypeError(
                        f"class '{name}': __init__ is not supported; "
                        "construction assigns fields in declaration order"
                    )
                if not params:
                    raise TypeError(
                        f"class '{name}': method '{method_name}' must take 'self'"
                    )
                mangled = f"{name}__{method_name}"
                param_annotations = stmt[4] if len(stmt) > 4 else ()
                # self carries the class name as its annotation, which
                # _annotation_kind maps to the INSTANCE kind (replace
                # self's own slot - params already include self)
                new_annotations = tuple(
                    [["name", name]] + list(param_annotations)[1:]
                )
                self.function_defs[mangled] = [
                    "func_def", mangled, params, mbody,
                    new_annotations, stmt[5] if len(stmt) > 5 else None,
                ]
                self._method_class[mangled] = name
                methods[method_name] = mangled
            elif op == "assign":
                raise TypeError(
                    f"class '{name}': fields must be annotated "
                    "(class variables are not supported)"
                )
            else:
                raise TypeError(
                    f"class '{name}': unsupported statement '{op}' in class body"
                )
        self._class_layouts[name] = {"fields": fields, "methods": methods}

    def _class_of_node(self, node: Any) -> Optional[str]:
        """Class name of an instance-typed expression: a name bound to an
        instance, or a chain through instance fields (a.inner.x) and
        instance-list elements (toks[i] on a list[Token])."""
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 2
            and node[0] == "name"
        ):
            return self._var_class.get(node[1])
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 3
            and node[0] == "attribute"
        ):
            parent_class = self._class_of_node(node[1])
            if parent_class is None:
                return None
            for field_name, kind, _default, field_class in (
                self._class_layouts[parent_class]["fields"]
            ):
                if field_name == node[2]:
                    return field_class if kind == INSTANCE else None
            return None
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 3
            and node[0] == "subscript"
        ):
            # an instance-list element: toks[i] where the base is a
            # list[Token] variable, or holder.arr[i] where arr is a
            # container FIELD with an element class on record
            base = node[1]
            if (
                isinstance(base, (list, tuple))
                and len(base) >= 2
                and base[0] == "name"
            ):
                return self._list_elem_class.get(base[1])
            if (
                isinstance(base, (list, tuple))
                and len(base) >= 3
                and base[0] == "attribute"
            ):
                parent_class = self._class_of_node(base[1])
                if parent_class is not None:
                    key = (parent_class, base[2])
                    if key in self._field_elem_class:
                        return self._field_elem_class[key]
                    return None
                return None
            return self._class_of_node(base)
        if (
            isinstance(node, (list, tuple))
            and len(node) >= 2
            and node[0] == "call"
        ):
            # a constructor call yields its class; a plain function's
            # INSTANCE return class is recorded at signature-inference
            # time (return expressions that are constructors / bound
            # names carry the class there)
            callee = node[1]
            if (
                isinstance(callee, (list, tuple))
                and len(callee) >= 2
                and callee[0] == "name"
            ):
                if callee[1] in self._class_layouts:
                    return callee[1]
                return self._call_ret_class.get(callee[1])
            if (
                isinstance(callee, (list, tuple))
                and len(callee) >= 3
                and callee[0] == "attribute"
            ):
                # method call: the mangled method's return class, same
                # bookkeeping as plain functions (self.cur() -> Token)
                recv_class = self._class_of_node(callee[1])
                if recv_class is None:
                    return None
                mangled = self._class_layouts[recv_class]["methods"].get(
                    callee[2]
                )
                if mangled is None:
                    return None
                return self._call_ret_class.get(mangled)
            return None
        return None

    def _constructor_call_class(self, value_node: Any) -> Optional[str]:
        """Class name when value_node is a `P(...)` construction call."""
        if (
            isinstance(value_node, list)
            and len(value_node) >= 2
            and value_node[0] == "call"
            and isinstance(value_node[1], list)
            and len(value_node[1]) >= 2
            and value_node[1][0] == "name"
            and value_node[1][1] in self._class_layouts
        ):
            return value_node[1][1]
        return None

    def _field_slot(self, inst_ptr: Any, index: int, kind: str):
        """Address of field `index` in an instance block (8-byte slots)."""
        raw = self.current_builder.gep(
            inst_ptr, [ir.const_(ir.IntType(64), index * 8)]
        )
        return self.current_builder.bitcast(
            raw, ir.PointerType(LLVM_KIND_TYPES[kind])
        )

    def _emit_field_read(self, obj_node: Any, attr: str) -> Tuple[str, Any]:
        """obj.attr where obj is a class instance: offset load. str fields
        copy on read (the instance keeps owning its slot's buffer);
        list/dict fields return the shared pointer - containers are
        reference semantics everywhere in Silu (semantics.md §3), fields
        included."""
        cls = self._class_of_node(obj_node)
        fields = self._class_layouts[cls]["fields"]
        for index, (field_name, kind, _default, _fclass) in enumerate(fields):
            if field_name == attr:
                inst_tv = self._convert_node(obj_node)
                inst_ptr = inst_tv[1]
                if inst_tv[0] == I64:
                    # element read off an instance list (toks[i]): the
                    # word is the pointer
                    inst_ptr = self.current_builder.inttoptr(
                        inst_ptr, LLVM_KIND_TYPES[INSTANCE]
                    )
                slot = self._field_slot(inst_ptr, index, kind)
                value = self.current_builder.load(slot)
                if kind == RAWSTR:
                    # copy-on-read: the field slot stays the sole owner
                    value = self.current_builder.call(self.rawstr_copy, [value])
                return (kind, value)
        raise AttributeError(f"'{cls}' object has no attribute '{attr}'")

    def _emit_field_write(self, obj_node: Any, attr: str, value_tv: Tuple[str, Any]):
        """obj.attr = value: coerce to the field kind and store. str
        fields drop the old buffer and copy the new one in (the
        RAWSTR->RAWSTR coerce already copies). Container fields store
        the pointer (reference semantics) and never free: rawlist/rawdict
        buffers are process-lifetime everywhere in Silu. A dynamic
        (OBJ) value coerces through the boundary, which copies."""
        cls = self._class_of_node(obj_node)
        fields = self._class_layouts[cls]["fields"]
        for index, (field_name, kind, _default, _fclass) in enumerate(fields):
            if field_name == attr:
                inst_tv = self._convert_node(obj_node)
                value_tv = self._coerce(value_tv, kind)
                slot = self._field_slot(inst_tv[1], index, kind)
                if kind == RAWSTR:
                    old = self.current_builder.load(slot)
                    self.current_builder.call(self.rawstr_free, [old])
                self.current_builder.store(value_tv[1], slot)
                return
        raise AttributeError(f"'{cls}' object has no field '{attr}'")

    def _node_contains_call(self, node: Any) -> bool:
        if not isinstance(node, (list, tuple)):
            return False
        if node and node[0] == "call":
            return True
        for child in node[1:]:
            if isinstance(child, (list, tuple)):
                if self._node_contains_call(child):
                    return True
        return False

    def _borrowed_field_str(
        self, base_node: Any, key_node: Any
    ) -> Optional[Tuple[str, Any]]:
        """(RAWSTR, ptr) borrowed from an instance str field for a
        read-only subscript/len within one expression - skips the
        copy-on-read. Only when the key expression is call-free: a call
        could reassign the field (freeing the buffer) mid-expression.
        The borrow never escapes as an owned RAWSTR: the subscript
        paths consume it as a view base or slice source, both of which
        only read it."""
        if not (
            isinstance(base_node, (list, tuple))
            and len(base_node) >= 3
            and base_node[0] == "attribute"
        ):
            return None
        cls = self._class_of_node(base_node[1])
        if cls is None:
            return None
        attr = base_node[2]
        fields = self._class_layouts[cls]["fields"]
        for index, (fname, kind, _default, _fclass) in enumerate(fields):
            if fname == attr and kind == RAWSTR:
                if key_node is not None and self._node_contains_call(key_node):
                    return None
                inst_tv = self._convert_node(base_node[1])
                slot = self._field_slot(inst_tv[1], index, kind)
                return (RAWSTR, self.current_builder.load(slot))
        return None

    def _emit_construct(
        self, class_name: str, args_node: list, kwargs_node: list
    ) -> Tuple[str, Any]:
        """P(a, b) / P(x=a): malloc the field block and store each
        argument coerced to its field kind (dataclass construction:
        positional in declaration order, keywords by name, defaults)."""
        fields = self._class_layouts[class_name]["fields"]
        if len(args_node) > len(fields):
            raise TypeError(
                f"{class_name}() takes at most {len(fields)} arguments "
                f"but {len(args_node)} given"
            )
        bound: Dict[str, Any] = {}
        for (field_name, _kind, _d, _fc), arg_node in zip(fields, args_node):
            bound[field_name] = arg_node
        for kw_name, kw_value_node in kwargs_node or ():
            field_names = set()
            for f in fields:
                field_names.add(f[0])
            if kw_name not in field_names:
                raise TypeError(
                    f"{class_name}() got an unexpected keyword argument "
                    f"'{kw_name}'"
                )
            if kw_name in bound:
                raise TypeError(
                    f"{class_name}() got multiple values for argument "
                    f"'{kw_name}'"
                )
            bound[kw_name] = kw_value_node

        inst_ptr = self.current_builder.call(
            self.malloc, [ir.const_(ir.IntType(64), 8 * len(fields))]
        )
        for index, (field_name, kind, default_node, _fc) in enumerate(fields):
            value_node = bound.get(field_name, default_node)
            if value_node is None:
                raise TypeError(
                    f"{class_name}() missing required argument: '{field_name}'"
                )
            value_tv = self._convert_field_value(kind, value_node)
            self.current_builder.store(
                value_tv[1], self._field_slot(inst_ptr, index, kind)
            )
        return (INSTANCE, inst_ptr)

    def _field_kind_of(self, obj_node: Any, attr: str) -> str:
        """The declared kind of a field (raises AttributeError if absent)."""
        cls = self._class_of_node(obj_node)
        for field_name, kind, _default, _fc in self._class_layouts[cls]["fields"]:
            if field_name == attr:
                return kind
        raise AttributeError(f"'{cls}' object has no field '{attr}'")

    def _convert_field_value(
        self, kind: str, value_node: Any
    ) -> Tuple[str, Any]:
        """Convert a field value node to the field kind. Container
        literals ([1, 2] / {"a": 1}) build raw storage directly - the
        dynamic unbox boundary only covers scalars and str."""
        if (
            kind in RAWLIST_KINDS
            and isinstance(value_node, list)
            and len(value_node) >= 1
            and value_node[0] == "list"
        ):
            return self._build_raw_list(value_node[1], kind)
        if (
            kind in RAWDICT_KINDS
            and isinstance(value_node, list)
            and len(value_node) >= 1
            and value_node[0] == "dict"
        ):
            raw_ptr = self.current_builder.call(self.rawdict_new, [])
            value_kind = RAWDICT_KINDS[kind]
            for pair_node in value_node[1]:
                val_tv = self._coerce(
                    self._convert_node(pair_node[1]), value_kind
                )
                val_bits = val_tv[1]
                if value_kind == F64:
                    val_bits = self.current_builder.bitcast(
                        val_tv[1], ir.IntType(64)
                    )
                self._rawdict_key_call(
                    kind, raw_ptr,
                    pair_node[0],
                    self.rawdict_set, self.rawdict_str_set,
                    (val_bits,),
                )
            return (kind, raw_ptr)
        # None into a pointer-kind slot (instance/str/container): the
        # null pointer (`is None` checks it at use sites)
        is_none_node = value_node is None or (
            isinstance(value_node, list)
            and len(value_node) >= 2
            and value_node[:2] == ["const", None]
        )
        if is_none_node and (
            kind == INSTANCE
            or kind == RAWSTR
            or kind in RAWLIST_KINDS
            or kind in RAWDICT_KINDS
        ):
            return (kind, ir.const_(LLVM_KIND_TYPES[kind], None))
        return self._coerce(self._convert_node(value_node), kind)

    def _emit_method_call(
        self, obj_node: Any, method_name: str, args_node: list
    ) -> Tuple[str, Any]:
        """st.m(a) -> P__m(st, a): the instance pointer is the raw first
        argument; the rest follows the callee's ABI (static or dynamic)."""
        cls = self._class_of_node(obj_node)
        mangled = self._class_layouts[cls]["methods"].get(method_name)
        if mangled is None:
            raise AttributeError(
                f"'{cls}' object has no attribute '{method_name}'"
            )
        inst_tv = self._convert_node(obj_node)
        if mangled in self.static_funcs:
            param_kinds, ret_kind, func = self.static_funcs[mangled]
            if len(args_node) != len(param_kinds) - 1:
                raise TypeError(
                    f"{cls}.{method_name}() takes "
                    f"{len(param_kinds) - 1} arguments but "
                    f"{len(args_node)} given"
                )
            raw_args = [inst_tv[1]]
            for index, arg_node in enumerate(args_node):
                raw_args.append(
                    self._coerce(
                        self._convert_node(arg_node), param_kinds[index + 1]
                    )[1]
                )
            return (ret_kind, self.current_builder.call(func, raw_args))
        func = self.functions[mangled]
        callee_def = self.function_defs[mangled]
        callee_kinds = (
            self._dyn_func_kinds.get(mangled)
            or self._dynamic_param_kinds(callee_def)
        )
        if len(args_node) != len(callee_kinds) - 1:
            raise TypeError(
                f"{cls}.{method_name}() takes {len(callee_kinds) - 1} "
                f"arguments but {len(args_node)} given"
            )
        call_args = [inst_tv[1]]
        for index, arg_node in enumerate(args_node):
            expected = callee_kinds[index + 1]
            arg_tv = self._convert_node(arg_node)
            if expected == OBJ:
                call_args.append(self._box(arg_tv))
            else:
                call_args.append(self._coerce(arg_tv, expected)[1])
        return (OBJ, self.current_builder.call(func, call_args))

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

        def collect_annotations(stmts: list, sink: Dict[str, str]):
            """ann_assign kinds in a scope (the inference return value
            only carries inferred candidates, so annotated names would
            otherwise be invisible to the resolver)."""
            for stmt in stmts if isinstance(stmts, list) else []:
                if not isinstance(stmt, (list, tuple)) or not stmt:
                    continue
                if (
                    stmt[0] == "ann_assign"
                    and isinstance(stmt[1], str)
                    and len(stmt) >= 4
                ):
                    kind = self._annotation_kind(stmt[3])
                    if kind:
                        sink[stmt[1]] = kind
                elif stmt[0] == "if" and len(stmt) >= 4:
                    collect_annotations(stmt[2], sink)
                    collect_annotations(stmt[3], sink)
                elif stmt[0] == "while" and len(stmt) >= 3:
                    collect_annotations(stmt[2], sink)
                elif stmt[0] == "for" and len(stmt) >= 4:
                    collect_annotations(stmt[3], sink)

        module_annotations: Dict[str, str] = {}
        collect_annotations(self._module_stmt_list, module_annotations)
        module_kinds = self._infer_assign_kinds(self._module_stmt_list, None)
        module_candidates = dict(module_kinds)

        # every call to a known function, scanning into nested
        # expressions (x = f(1) + 2) and all function bodies
        calls: Dict[str, list] = {}
        for name in self.function_defs:
            calls[name] = []

        self._scan_calls(self._module_stmt_list, calls)
        for func_def in self.function_defs.values():
            self._scan_calls(func_def[3] if len(func_def) > 3 else [], calls)

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
                        arg_kind = self._resolve_kind(args[index], module_annotations, module_candidates, annotated_ret)
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
                param_env = _non_obj_param_env(params, param_kinds, False)
                body_annotations: Dict[str, str] = {}
                collect_annotations(body, body_annotations)
                local_kinds = self._infer_assign_kinds(body, param_env)
                body_env = {}
                for _k in param_env:
                    body_env[_k] = param_env[_k]
                for _k in body_annotations:
                    body_env[_k] = body_annotations[_k]
                body_candidates = dict(local_kinds)
                returns: list = []
                find_returns(body, returns)
                inferred_ret: Optional[str] = None
                ok = bool(returns)
                for rexpr in returns:
                    if rexpr is None:
                        ok = False  # bare return yields None
                        break
                    rk = self._resolve_kind(rexpr, body_env, body_candidates, annotated_ret)
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

    def _collect_ctor_returns(self):
        """Record functions whose every return expression is a
        constructor of one same class - their call results then resolve
        class chains like elem(node, 1).s."""

        def ctor_class_of(expr, depth, param_class):
            param_class = param_class or {}
            if not isinstance(expr, (list, tuple)) or depth > 8:
                return None
            if (
                isinstance(expr, (list, tuple))
                and len(expr) >= 2
                and expr[0] == "name"
                and isinstance(expr[1], str)
                and expr[1] in param_class
            ):
                return param_class[expr[1]]
            if (
                len(expr) >= 2
                and expr[0] == "call"
                and isinstance(expr[1], (list, tuple))
                and len(expr[1]) >= 2
                and expr[1][0] == "name"
                and expr[1][1] in self._class_layouts
            ):
                return expr[1][1]
            if len(expr) >= 3 and expr[0] == "subscript":
                base_cls = ctor_class_of(expr[1], depth + 1, None)
                if base_cls is None:
                    # a list[Token] variable base
                    if (
                        isinstance(expr[1], (list, tuple))
                        and len(expr[1]) >= 2
                        and expr[1][0] == "name"
                    ):
                        return self._list_elem_class.get(expr[1][1])
                    return None
                # any container field holding instances records its
                # element class; try each container field name
                for (cls_name, fname), elem in self._field_elem_class.items():
                    if cls_name == base_cls:
                        return elem
                return None
            if len(expr) >= 3 and expr[0] == "attribute":
                base_cls = ctor_class_of(expr[1], depth + 1, None)
                if base_cls is None:
                    return None
                for fname, fkind, _d, fclass in self._class_layouts[base_cls][
                    "fields"
                ]:
                    if fname == expr[2]:
                        return fclass if fkind == INSTANCE else None
                return None
            return None

        def find_returns(stmts, sink):
            for stmt in stmts if isinstance(stmts, (list, tuple)) else []:
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

        for func_name, func_def in self.function_defs.items():
            # a written return annotation naming a class wins outright
            # (def elem(node: JValue, i: int) -> JValue)
            ret_ann = func_def[5] if len(func_def) > 5 else None
            if (
                isinstance(ret_ann, (list, tuple))
                and len(ret_ann) >= 2
                and ret_ann[0] == "name"
                and ret_ann[1] in self._class_layouts
            ):
                self._call_ret_class[func_name] = ret_ann[1]
                continue
            returns: list = []
            find_returns(func_def[3] if len(func_def) > 3 else [], returns)
            if not returns:
                continue
            # parameter classes from written annotations (node: JValue)
            param_class = {}
            params = func_def[2] if len(func_def) > 2 else []
            param_annotations = func_def[4] if len(func_def) > 4 else ()
            for index, pname in enumerate(params):
                ann = (
                    param_annotations[index]
                    if index < len(param_annotations)
                    else None
                )
                if (
                    isinstance(ann, list)
                    and len(ann) >= 2
                    and ann[0] == "name"
                    and ann[1] in self._class_layouts
                ):
                    param_class[pname] = ann[1]
            ctor: Optional[str] = None
            ok = True
            for expr in returns:
                cls = ctor_class_of(expr, 0, param_class)
                if cls is None:
                    ok = False
                    break
                if ctor is None:
                    ctor = cls
                elif ctor != cls:
                    ok = False
                    break
            if ok and ctor is not None:
                self._call_ret_class[func_name] = ctor

    def _create_function_declarations(self):
        """Create raw-ABI functions for annotated ones, PyObject otherwise.

        Cross-function inference (call sites + return expressions) can
        promote an unannotated function to the raw ABI the same way
        written annotations do; a function that stays dynamic-return
        still gets raw-typed parameters when inference proves them.
        """
        self._inferred_sigs = self._infer_function_signatures()
        self._collect_ctor_returns()
        for func_name, func_def in self.function_defs.items():
            # sigs merge written annotations with inference results
            param_kinds, ret_kind = self._inferred_sigs[func_name]
            if ret_kind is not None and _all_non_obj(param_kinds):
                param_types = []
                for k in param_kinds:
                    param_types.append(LLVM_KIND_TYPES[k])
                func_ty = ir.FunctionType(LLVM_KIND_TYPES[ret_kind], param_types, False)
                func = ir.func_(self.module, func_ty, func_name)
                # module-private + inline hint: the recursive-descent
                # clusters (parsers etc.) only pay off inlined
                func.linkage = "internal"
                func.attributes.add("alwaysinline")
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
                    ir.PointerType(self.pyobj.pyobj_type), param_types, False
                )
                func = ir.func_(self.module, func_ty, func_name)
                # module-private: enables IPO on the boxed cluster too
                # (small enough that alwaysinline would bloat; LLVM's
                # regular inliner decides)
                func.linkage = "internal"
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
        old_var_class = self._var_class

        self.current_function = func
        self.current_builder = ir.builder_(entry_block)
        self.current_ret_kind = ret_kind
        old_cursor_kinds = self.cursor_kinds
        old_cursor_slots = self._cursor_slots
        param_annotations = func_def[4] if len(func_def) > 4 else ()
        param_kind_env: Dict[str, str] = {}
        for index, pname in enumerate(func_def[2]):
            ann_node = (
                param_annotations[index]
                if index < len(param_annotations) else None
            )
            param_kind_env[pname] = self._annotation_kind(ann_node) or OBJ
        self.cursor_kinds = self._infer_cursors(
            func_def[3], self._param_shared_names(), param_kind_env
        )
        self._cursor_slots = {}
        self._inferred_kinds = self._infer_assign_kinds(
            func_def[3],
            _non_obj_param_env(func_def[2], param_kinds, False),
        )
        # keep module-level variables visible (they act as globals);
        # remember which names are function-local so we can pop them on
        # exit - a local kind must never leak into other functions
        self._scope_depth = self._scope_depth + 1
        if self._scope_depth == 1:
            self._module_vars = set(self.variables.keys())
            self._module_kinds = set(self.var_kinds.keys())
        self.variables = dict(self.variables)
        self.var_kinds = dict(self.var_kinds)
        self._var_class = dict(self._var_class)

        for index, param_name in enumerate(func_def[2]):
            kind = param_kinds[index]
            # parameters always shadow: delete any inherited entry so
            # _declare_var allocates a fresh function-local slot
            self.variables.pop(param_name, None)
            self.var_kinds.pop(param_name, None)
            self._declare_var(param_name, kind)
            self.current_builder.store(func.args[index], self.variables[param_name])

        # methods: bind the self parameter's class for attribute access
        method_class = self._method_class.get(func.name)
        if method_class is not None and func_def[2]:
            self._var_class[func_def[2][0]] = method_class
        # class-annotated parameters (st: JointState) bind their class too
        for index, pname in enumerate(func_def[2]):
            ann = (
                param_annotations[index] if index < len(param_annotations) else None
            )
            if (
                isinstance(ann, list)
                and len(ann) >= 2
                and ann[0] == "name"
                and ann[1] in self._class_layouts
            ):
                self._var_class[pname] = ann[1]

        for stmt in func_def[3]:
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self._emit_local_rawstr_drops()
            if ret_kind == RAWSTR:
                # missing return: an empty owned string, never a null
                # pointer (slots must stay dereferenceable)
                empty_ptr = self._create_global_string("")
                self.current_builder.ret(
                    self.current_builder.call(
                        self.rawstr_new_copy,
                        [empty_ptr, ir.const_(ir.IntType(64), 0)],
                    )
                )
            else:
                if ret_kind == INSTANCE:
                    # missing return: a null instance pointer
                    self.current_builder.ret(
                        ir.const_(LLVM_KIND_TYPES[INSTANCE], None)
                    )
                elif ret_kind in RAWLIST_KINDS or ret_kind in RAWDICT_KINDS:
                    # missing return: an empty raw container
                    self.current_builder.ret(
                        ir.const_(LLVM_KIND_TYPES[ret_kind], None)
                    )
                else:
                    zero = {
                        I64: ir.const_(ir.IntType(64), 0),
                        F64: ir.const_(ir.DoubleType(), 0.0),
                        I1: ir.const_(ir.IntType(1), 0),
                    }[ret_kind]
                    self.current_builder.ret(zero)

        self.current_function = old_function
        self.current_builder = old_builder
        self.variables = old_variables
        self.var_kinds = old_kinds
        self.current_ret_kind = old_ret
        self._inferred_kinds = old_inferred
        self._var_class = old_var_class
        self.cursor_kinds = old_cursor_kinds
        self._cursor_slots = old_cursor_slots
        self._scope_depth = self._scope_depth - 1

    def _generate_dynamic_function_body(self, func: ir.Function, func_def: list):
        """PyObject-ABI function body (unannotated functions)."""
        entry_block = func.append_basic_block("entry")
        old_function = self.current_function
        old_builder = self.current_builder
        old_variables = self.variables.copy()
        old_kinds = dict(self.var_kinds)
        old_ret = self.current_ret_kind
        old_inferred = self._inferred_kinds
        old_var_class = self._var_class

        self.current_function = func
        self.current_builder = ir.builder_(entry_block)
        self.current_ret_kind = None
        old_cursor_kinds = self.cursor_kinds
        old_cursor_slots = self._cursor_slots
        self.cursor_kinds = self._infer_cursors(
            func_def[3],
            self._param_shared_names(),
            {},
        )
        self._cursor_slots = {}
        self._scope_depth = self._scope_depth + 1
        if self._scope_depth == 1:
            self._module_vars = set(self.variables.keys())
            self._module_kinds = set(self.var_kinds.keys())
        self.variables = dict(self.variables)
        self.var_kinds = dict(self.var_kinds)
        self._var_class = dict(self._var_class)

        # methods: bind the self parameter's class for attribute access
        method_class = self._method_class.get(func_def[1])
        if method_class is not None and func_def[2]:
            self._var_class[func_def[2][0]] = method_class
        # class-annotated parameters (st: JointState) bind their class too
        dyn_param_annotations = func_def[4] if len(func_def) > 4 else ()
        for index, pname in enumerate(func_def[2]):
            ann = (
                dyn_param_annotations[index]
                if index < len(dyn_param_annotations)
                else None
            )
            if (
                isinstance(ann, list)
                and len(ann) >= 2
                and ann[0] == "name"
                and ann[1] in self._class_layouts
            ):
                self._var_class[pname] = ann[1]

        param_kinds_dyn = self._dyn_func_kinds.get(
            func_def[1], self._dynamic_param_kinds(func_def)
        )
        self._inferred_kinds = self._infer_assign_kinds(
            func_def[3],
            _non_obj_param_env(func_def[2], param_kinds_dyn, keep_obj=True),
        )
        for index, param_name in enumerate(func_def[2]):
            if index < len(func.args):
                kind = param_kinds_dyn[index]
                if kind != OBJ:
                    # raw-ABI parameter: store the value in a typed alloca
                    param_alloca = self.current_builder.alloca(
                        LLVM_KIND_TYPES[kind], None, param_name
                    )
                    self.current_builder.store(func.args[index], param_alloca)
                    self.variables[param_name] = param_alloca
                    self.var_kinds[param_name] = kind
                    continue
                param_alloca = self.current_builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type), None, param_name
                )
                self.current_builder.store(func.args[index], param_alloca)
                self.variables[param_name] = param_alloca
                self.var_kinds[param_name] = OBJ

        for stmt in func_def[3]:
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self._emit_local_rawstr_drops()
            null_val = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
            self.current_builder.ret(null_val)

        self.current_function = old_function
        self.current_builder = old_builder
        self.variables = old_variables
        self.var_kinds = old_kinds
        self.current_ret_kind = old_ret
        self._inferred_kinds = old_inferred
        self._var_class = old_var_class
        self.cursor_kinds = old_cursor_kinds
        self._cursor_slots = old_cursor_slots
        self._scope_depth = self._scope_depth - 1

    # ================== statement / expression dispatch ==================

    def _convert_toplevel(self, node: Any) -> Tuple[str, Any]:
        return self._convert_node_scoped(node, True)

    def _convert_node(self, node: Any) -> Tuple[str, Any]:
        return self._convert_node_scoped(node, False)

    def _convert_node_scoped(self, node: Any, skip_func_defs: bool) -> Tuple[str, Any]:
        """Convert an IR node, returning a TypedValue (kind, llvm value)."""
        if not isinstance(node, list) or len(node) == 0:
            return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

        op = node[0]
        null_obj = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)

        if op == "line":
            # statement-position marker: remember the source line so a
            # runtime panic further down can name it
            self.current_builder.store(
                ir.const_(ir.IntType(64), node[1]), self.line_global
            )
            return (OBJ, null_obj)

        if op == "module":
            self._inferred_kinds = self._infer_assign_kinds(
                node[1] if len(node) > 1 else [],
                None,
            )
            for stmt in node[1] if len(node) > 1 else []:
                self._convert_statement_scoped(stmt, skip_func_defs)
            return (OBJ, null_obj)

        if op == "funcref":
            mangled = node[1]
            fn = self.functions.get(mangled)
            if fn is None:
                raise NameError(f"funcref to unknown function '{mangled}'")
            return ("func:" + mangled, fn)

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
                return (I1, ir.const_(ir.IntType(1), value))
            if kind == I64:
                return (I64, ir.const_(ir.IntType(64), value))
            if kind == F64:
                return (F64, ir.const_(ir.DoubleType(), value))
            str_len = len(value.encode('utf-8'))  # bytes, matches the utf-8 global
            str_ptr = self._create_global_string(value)
            return (
                OBJ,
                self.current_builder.call(
                    self.create_str, [str_ptr, ir.const_(ir.IntType(32), str_len)]
                ),
            )

        if op == "name":
            if node[1] in self._char_aliases:
                # live char-view alias: replay the window (register
                # arithmetic, no allocation)
                _str_name, str_tv, index_slot = self._char_aliases[node[1]]
                index = self.current_builder.load(index_slot)
                return self._emit_char_view(str_tv[1], index)
            return self._load_var(node[1])

        if op == "class_def" or op == "enum_def":
            # layouts/enums and methods were registered in the
            # collection pass; nothing to emit at statement position
            return (OBJ, null_obj)

        if op == "attribute" and len(node) >= 3:
            # enum member: Color.RED folds to its i64 constant
            if (
                isinstance(node[1], list)
                and len(node[1]) >= 2
                and node[1][0] == "name"
                and node[1][1] in self._enums
            ):
                table = self._enums[node[1][1]]
                if node[2] in table:
                    return (I64, ir.const_(ir.IntType(64), table[node[2]]))
                raise AttributeError(
                    f"'{node[1][1]}' has no member '{node[2]}'"
                )
            # a chained receiver (x.m().f) never reaches the method-call
            # emitter, which is where missing methods are caught - check
            # the receiver's methods here too
            self._check_receiver_methods(node[1])
            if self._class_of_node(node[1]) is not None:
                return self._emit_field_read(node[1], node[2])
            # dynamic attribute access stays unsupported (null)
            return (OBJ, null_obj)

        if op == "attribute_aug_assign" and len(node) >= 5:
            if self._class_of_node(node[1]) is not None:
                current = self._emit_field_read(node[1], node[2])
                rhs = self._convert_node(node[4])
                op_str = node[3]
                if isinstance(op_str, str) and op_str.endswith("="):
                    op_str = op_str[:-1]
                result = self._typed_binop(op_str, current, rhs)
                self._emit_field_write(node[1], node[2], result)
            return (OBJ, null_obj)

        if op in ("assign", "ann_assign"):
            target = node[1]
            value_node = node[2]
            if op == "ann_assign" and value_node is None:
                return (OBJ, null_obj)
            if (
                isinstance(target, (list, tuple))
                and len(target) >= 3
                and target[0] == "attribute"
            ):
                # obj.attr = value on a class instance
                if self._class_of_node(target[1]) is None:
                    raise NotImplementedError(
                        "attribute assignment is only supported on class "
                        "instances"
                    )
                field_kind = self._field_kind_of(target[1], target[2])
                self._emit_field_write(
                    target[1],
                    target[2],
                    self._convert_field_value(field_kind, value_node),
                )
                return (OBJ, null_obj)
            if isinstance(target, str):
                if (
                    isinstance(value_node, list)
                    and len(value_node) == 2
                    and value_node[0] == "funcref"
                ):
                    mangled = value_node[1]
                    if mangled not in self.functions:
                        raise NameError(
                            f"funcref to unknown function '{mangled}'"
                        )
                    self._declare_var(target, OBJ)
                    self._funcref_var[target] = mangled
                    return (OBJ, null_obj)
                ctor_class = self._constructor_call_class(value_node)
                if ctor_class is not None:
                    # st = JointState(1.0, 2.0) - optionally annotated
                    if op == "ann_assign":
                        ann = node[3] if len(node) > 3 else None
                        if (
                            isinstance(ann, list)
                            and len(ann) >= 2
                            and ann[0] == "name"
                            and ann[1] in self._class_layouts
                            and ann[1] != ctor_class
                        ):
                            raise TypeError(
                                f"cannot assign {ctor_class}() to "
                                f"'{ann[1]}' variable '{target}'"
                            )
                    inst = self._emit_construct(
                        ctor_class,
                        value_node[2] if len(value_node) > 2 else [],
                        value_node[3] if len(value_node) > 3 else [],
                    )
                    self._declare_var(target, INSTANCE)
                    self._var_class[target] = ctor_class
                    self.current_builder.store(inst[1], self.variables[target])
                    return inst
                if (
                    isinstance(value_node, list)
                    and len(value_node) >= 2
                    and value_node[0] == "name"
                    and self.var_kinds.get(value_node[1]) == INSTANCE
                ):
                    # a = b: instances alias (Python reference semantics)
                    value = self._convert_node(value_node)
                    self._declare_var(target, INSTANCE)
                    self._var_class[target] = self._var_class[value_node[1]]
                    self.current_builder.store(value[1], self.variables[target])
                    return value
                if (
                    isinstance(value_node, list)
                    and len(value_node) >= 3
                    and value_node[0] == "attribute"
                    and self._class_of_node(value_node) is not None
                ):
                    # a = b.inner: aliasing an instance field
                    value = self._convert_node(value_node)
                    self._declare_var(target, INSTANCE)
                    self._var_class[target] = self._class_of_node(value_node)
                    self.current_builder.store(value[1], self.variables[target])
                    return value
            if op == "ann_assign":
                annotation_kind = self._annotation_kind(node[3]) or OBJ
                # a class-annotated declaration binds the name to its
                # class even before the value is looked at
                ann = node[3] if len(node) > 3 else None
                if (
                    annotation_kind == INSTANCE
                    and isinstance(target, str)
                    and isinstance(ann, list)
                    and len(ann) >= 2
                    and ann[0] == "name"
                ):
                    self._var_class[target] = ann[1]
                if (
                    annotation_kind == RAWLIST_I
                    and isinstance(target, str)
                    and isinstance(ann, list)
                    and len(ann) >= 3
                    and ann[0] == "subscript"
                    and isinstance(ann[2], list)
                    and len(ann[2]) >= 2
                    and ann[2][0] == "name"
                    and ann[2][1] in self._class_layouts
                ):
                    self._list_elem_class[target] = ann[2][1]
            else:
                annotation_kind = self.var_kinds.get(target)
            if annotation_kind is None and target not in self.var_kinds:
                # unannotated rebinding: raw storage only when the
                # pre-pass proved every assignment yields one same kind
                annotation_kind = self._inferred_kinds.get(target) or OBJ
            if (
                isinstance(target, str)
                and isinstance(value_node, list)
                and len(value_node) >= 3
                and value_node[0] == "subscript"
                and isinstance(value_node[1], list)
                and len(value_node[1]) >= 2
                and value_node[1][0] == "name"
                and self.var_kinds.get(value_node[1][1]) == RAWSTR
                and not (
                    isinstance(value_node[2], list)
                    and len(value_node[2]) >= 4
                    and value_node[2][0] == "slice"
                )
            ):
                # ch = s[i]: a materialized copy. (A borrowed char-view
                # alias optimization lived here and is disabled: its
                # kill-site placement interacted badly with loop
                # back-edges and expression coercions. Revisit with a
                # proper lifetime model - a copy per char is correct.)
                str_name = value_node[1][1]
                str_tv = self._load_var(str_name)
                index_frozen = self._coerce(
                    self._convert_node(value_node[2]), I64
                )[1]
                coerced = self._coerce(
                    self._emit_char_view(str_tv[1], index_frozen), RAWSTR
                )
                self._declare_var(target, RAWSTR)
                self._store_rawstr(target, coerced[1])
                return (RAWSTR, None)
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
                data_ptr, byte_len, temp = self._rawstr_append_operand(value_node[2])
                slot_value = self._load_var(target)[1]
                self.current_builder.call(
                    self.rawstr_append, [slot_value, data_ptr, byte_len]
                )
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
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
                count_const = _extract_i64_const(count_tv[1])
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
                    self.rawlist_new, [ir.const_(ir.IntType(64), 8)]
                )
                count_i64 = self._coerce(count_tv, I64)[1]
                raw_ptr = self.current_builder.alloca(
                    ir.PointerType(ir.IntType(8)), None, 'fill_list'
                )
                self.current_builder.store(raw, raw_ptr)
                fill_idx = self.current_builder.alloca(
                    ir.IntType(64), None, 'fill_i'
                )
                self.current_builder.store(ir.const_(ir.IntType(64), 0), fill_idx)
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
                    self.current_builder.add(fill_i, ir.const_(ir.IntType(64), 1)),
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
                    val_tv = self._coerce(
                        self._convert_node(pair_node[1]), value_kind
                    )
                    val_bits = val_tv[1]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            val_tv[1], ir.IntType(64)
                        )
                    self._rawdict_key_call(
                        annotation_kind, raw_ptr,
                        pair_node[0],
                        self.rawdict_set, self.rawdict_str_set,
                        (val_bits,),
                    )
                self._declare_var(target, annotation_kind)
                self.current_builder.store(raw_ptr, self.variables[target])
                return (annotation_kind, raw_ptr)
            value = self._convert_node(value_node)
            if isinstance(target, str) and value[1] is not None:
                if value[0] == INSTANCE and annotation_kind in (None, OBJ):
                    # an unannotated name bound to an instance: declare it
                    # INSTANCE and record the class (t = self.cur())
                    ctor = self._constructor_call_class(value_node)
                    cls = (
                        ctor
                        or self._call_ret_class.get(
                            value_node[1][1]
                            if (
                                isinstance(value_node, list)
                                and len(value_node) >= 2
                                and value_node[0] == "call"
                                and isinstance(value_node[1], list)
                                and len(value_node[1]) >= 2
                                and value_node[1][0] == "name"
                            )
                            else ""
                        )
                        or self._class_of_node(value_node)
                    )
                    self._declare_var(target, INSTANCE)
                    if cls is not None:
                        self._var_class[target] = cls
                    self.current_builder.store(value[1], self.variables[target])
                    return value
                if annotation_kind == RAWSTR and value[0] == RAWSTR:
                    # a name aliases another slot's buffer, so assigning
                    # it must copy (exclusive ownership); an expression
                    # result is a fresh temporary the slot can simply own
                    aliases_slot = (
                        isinstance(value_node, list)
                        and len(value_node) >= 2
                        and value_node[0] == "name"
                    )
                    coerced = (
                        self._coerce(value, RAWSTR) if aliases_slot else value
                    )
                    self._declare_var(target, RAWSTR)
                    # the slot owns its buffer exclusively: drop the old
                    # value on overwrite (Rust drop), no leak per reassign
                    self._store_rawstr(target, coerced[1])
                    return coerced
                is_none_value = value_node is None or (
                    isinstance(value_node, list)
                    and len(value_node) >= 2
                    and value_node[:2] == ["const", None]
                )
                if is_none_value and annotation_kind in (
                    INSTANCE, RAWSTR
                ) or is_none_value and annotation_kind in RAWLIST_KINDS or (
                    is_none_value and annotation_kind in RAWDICT_KINDS
                ):
                    value = (
                        annotation_kind,
                        ir.const_(LLVM_KIND_TYPES[annotation_kind], None),
                    )
                    self._declare_var(target, annotation_kind)
                    self.current_builder.store(
                        value[1], self.variables[target]
                    )
                    return value
                coerced = self._coerce(value, annotation_kind)
                self._declare_var(target, annotation_kind)
                if annotation_kind == RAWSTR:
                    # the coerced value is a fresh owned temporary; drop
                    # the slot's previous buffer as we overwrite it
                    self._store_rawstr(target, coerced[1])
                else:
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
                if (
                    isinstance(target_node[1], (list, tuple))
                    and len(target_node[1]) >= 2
                    and target_node[1][0] == "name"
                    and target_node[1][1] in self.cursor_kinds
                    and isinstance(target_node[2], (list, tuple))
                    and target_node[2][:2] == ["const", 0]
                ):
                    slot = self._cursor_slot(target_node[1][1])
                    current = (I64, self.current_builder.load(slot))
                    result = self._typed_binop(bin_op, current, right_tv)
                    coerced = self._coerce(result, I64)
                    self.current_builder.store(coerced[1], slot)
                    return coerced
                obj_tv = self._convert_node(target_node[1])
                key_tv = self._convert_node(target_node[2])
                if obj_tv[0] == RAWLIST_S:
                    # l[i] <op>= v on str elements: copy-out, combine,
                    # set (which drops the old slot and copies in)
                    index = self._coerce(key_tv, I64)[1]
                    current = (
                        RAWSTR,
                        self.current_builder.call(
                            self.rawlist_str_get, [obj_tv[1], index]
                        ),
                    )
                    result = self._typed_binop("+", current, right_tv) if bin_op == "+" else None
                    if result is None:
                        # unsupported op on strings: fallback via boxed
                        current_boxed = self._box(current)
                        result = self._typed_binop(
                            bin_op, (OBJ, current_boxed), right_tv
                        )
                        coerced = self._coerce(result, RAWSTR)
                    else:
                        coerced = self._coerce(result, RAWSTR)
                    self.current_builder.call(
                        self.rawlist_str_set,
                        [obj_tv[1], index, coerced[1]],
                    )
                    return coerced
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
                                ir.const_(ir.IntType(32), 0),
                                ir.const_(ir.IntType(32), 2),
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
                    current_bits = self._rawdict_key_call_tv(
                        obj_tv[0], obj_tv[1], key_tv,
                        self.rawdict_get, self.rawdict_str_get,
                    (),
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
                    self._rawdict_key_call_tv(
                        obj_tv[0], obj_tv[1], key_tv,
                        self.rawdict_set, self.rawdict_str_set,
                        (stored_bits,),
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
                    # concat output is a fresh temporary: own it directly
                    # (a coerce here would copy it and leak the original)
                    self._store_rawstr(target_name, result[1])
                    return result
                data_ptr, byte_len, temp = self._rawstr_append_operand(node[3])
                slot_value = self._load_var(target_name)[1]
                self.current_builder.call(
                    self.rawstr_append, [slot_value, data_ptr, byte_len]
                )
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
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
                        ir.const_(ir.DoubleType(), 0.0), operand[1]
                    ),
                )
            _, value = self._coerce(operand, I64)
            if not self.checks:
                return (
                    I64,
                    self.current_builder.sub(ir.const_(ir.IntType(64), 0), value),
                )
            pair = self.current_builder.call(
                self.ssub_overflow,
                [
                    ir.const_(ir.IntType(64), 0),
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
            if op == "+" and left[0] != RAWSTR and right[0] != RAWSTR:
                # const str operands make this a string concatenation
                # even when both sides boxed: route it through the raw
                # concat so t = "ab" + "cd" never round-trips pyobj_add
                def is_str_const(operand_node):
                    return (
                        isinstance(operand_node, list)
                        and len(operand_node) >= 2
                        and operand_node[0] == "const"
                        and isinstance(operand_node[1], str)
                    )

                if is_str_const(node[1]) or is_str_const(node[2]):
                    left = self._coerce(left, RAWSTR)
                    right = self._coerce(right, RAWSTR)
            return self._typed_binop(op, left, right)

        if op in ("==", "!=", "<", "<=", ">", ">="):
            # s[i] <op> "<const>" must fuse BEFORE evaluating the
            # subscript, otherwise the char is materialized anyway
            fused = self._rawstr_at_eq_fusion(op, None, None, node[1], node[2])
            if fused is not None:
                return fused

        if op in ("==", "!=", "<", "<=", ">", ">="):
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])
            return self._typed_compare(op, left, right, node[1], node[2])

        if op in ("is", "is not") and len(node) >= 3:
            # identity: x is None / x is not None is the sanctioned use
            # (instances are pointers; null = None)
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])

            def as_i1(tv):
                return self._to_i1_cond(tv)

            def is_null(tv):
                if tv[0] == INSTANCE:
                    return self.current_builder.icmp_signed(
                        "==",
                        tv[1],
                        ir.const_(LLVM_KIND_TYPES[INSTANCE], None),
                    )
                boxed = self._box(tv)
                return self.current_builder.icmp_signed(
                    "==",
                    boxed,
                    ir.const_(ir.PointerType(self.pyobj.pyobj_type), None),
                )

            left_is_none = (
                node[1] is None
                or (isinstance(node[1], list) and node[1][:2] == ["const", None])
            )
            right_is_none = (
                node[2] is None
                or (isinstance(node[2], list) and node[2][:2] == ["const", None])
            )
            # x is None / x is not None: the NON-None side carries the
            # nullness test (comparing the None literal against itself
            # would be a constant true)
            if right_is_none or left_is_none:
                result = is_null(left) if right_is_none else is_null(right)
            elif (
                isinstance(node[2], list)
                and len(node[2]) >= 2
                and node[2][0] == "const"
                and isinstance(node[2][1], bool)
            ):
                result = self._is_bool_singleton(left, node[2][1])
            elif (
                isinstance(node[1], list)
                and len(node[1]) >= 2
                and node[1][0] == "const"
                and isinstance(node[1][1], bool)
            ):
                result = self._is_bool_singleton(right, node[1][1])
            elif left[0] == INSTANCE and right[0] == INSTANCE:
                result = self.current_builder.icmp_signed("==", left[1], right[1])
            elif left[0] == I64 and right[0] == I64:
                # Python `is` on ints is identity-implementational; Silu
                # treats it as value equality for machine ints (the only
                # stable meaning on an unboxed representation)
                result = self.current_builder.icmp_signed("==", left[1], right[1])
            else:
                raise NotImplementedError(
                    "'is' is supported for None checks and instance identity"
                )
            if op == "is not":
                result = self.current_builder.not_(result)
            return (I1, result)

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
            then_terminated = self.current_builder.block.is_terminated
            then_pred = self.current_builder.block

            self.current_builder.position_at_end(else_block)
            else_val = self._convert_node(node[3])
            else_terminated = self.current_builder.block.is_terminated
            else_pred = self.current_builder.block

            self.current_builder.position_at_end(merge_block)
            if then_terminated and else_terminated:
                # both arms diverge - the merge is dead code
                return (OBJ, null_obj)
            common = (
                then_val[0]
                if then_val[0] == else_val[0]
                else (F64 if F64 in (then_val[0], else_val[0]) else OBJ)
            )
            phi_type = (
                LLVM_KIND_TYPES[common]
                if common != OBJ
                else ir.PointerType(self.pyobj.pyobj_type)
            )
            slot = self._entry_alloca(phi_type, name="iexpr_val")
            # store each live arm's coerced value in a continuation block
            # chained off the arm's real predecessor, then load in merge
            if not then_terminated:
                then_store = self.current_function.append_basic_block(
                    "iexpr_then_s"
                )
                self.current_builder.position_at_end(then_pred)
                self.current_builder.branch(then_store)
                self.current_builder.position_at_end(then_store)
                self.current_builder.store(
                    self._coerce(then_val, common)[1], slot
                )
                self.current_builder.branch(merge_block)
            if not else_terminated:
                else_store = self.current_function.append_basic_block(
                    "iexpr_else_s"
                )
                self.current_builder.position_at_end(else_pred)
                self.current_builder.branch(else_store)
                self.current_builder.position_at_end(else_store)
                self.current_builder.store(
                    self._coerce(else_val, common)[1], slot
                )
                self.current_builder.branch(merge_block)

            self.current_builder.position_at_end(merge_block)
            return (common, self.current_builder.load(slot))

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
                    self._convert_statement(stmt)
                    if self.current_builder.block.is_terminated:
                        break
                if not self.current_builder.block.is_terminated:
                    self.current_builder.branch(merge_block)

                self.current_builder.position_at_end(else_block)
                for stmt in node[3]:
                    self._convert_statement(stmt)
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
                    self._convert_statement(stmt)
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

        if op == "raise":
            # the only sanctioned raise: SystemExit(code) terminates the
            # process with that status
            value_node = node[1] if len(node) > 1 else None
            if (
                isinstance(value_node, (list, tuple))
                and len(value_node) >= 3
                and value_node[0] == "call"
                and isinstance(value_node[1], (list, tuple))
                and len(value_node[1]) >= 2
                and value_node[1][0] == "name"
                and value_node[1][1] == "SystemExit"
            ):
                code = self._coerce(
                    self._convert_node(value_node[2][0])
                    if value_node[2]
                    else (I64, ir.const_(ir.IntType(64), 1)),
                    I64,
                )[1]
                self._emit_local_rawstr_drops()
                code_i32 = self.current_builder.trunc(code, ir.IntType(32))
                self.current_builder.call(self.exit_func, [code_i32])
                self.current_builder.unreachable()
                return (OBJ, null_obj)
            # raise X(msg): Rust panic! shape - print "X: msg" and
            # exit(1); the exception object never propagates
            if (
                isinstance(value_node, (list, tuple))
                and len(value_node) >= 3
                and value_node[0] == "call"
                and isinstance(value_node[1], (list, tuple))
                and len(value_node[1]) >= 2
                and value_node[1][0] == "name"
            ):
                exc_name = value_node[1][1]
                exc_args = value_node[2]
                if exc_args:
                    prefix = self._create_global_string(exc_name + ": ")
                else:
                    prefix = self._create_global_string(exc_name)
                self.current_builder.call(self.printf, [prefix])
                for index, arg_node in enumerate(exc_args):
                    if index > 0:
                        sep = self._create_global_string(" ")
                        self.current_builder.call(self.printf, [sep])
                    boxed = self._box(self._convert_node(arg_node))
                    if boxed is not None:
                        self.current_builder.call(self.pyobj_print, [boxed])
                nl = self._create_global_string("\n")
                self.current_builder.call(self.printf, [nl])
                self._emit_local_rawstr_drops()
                self.current_builder.call(
                    self.exit_func, [ir.const_(ir.IntType(32), 1)]
                )
                self.current_builder.unreachable()
                return (OBJ, null_obj)
            raise NotImplementedError(
                "only 'raise SystemExit(code)' and 'raise X(msg)' "
                "are supported"
            )

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
                        self._emit_local_rawstr_drops()
                        empty_ptr = self._create_global_string("")
                        self.current_builder.ret(
                            self.current_builder.call(
                                self.rawstr_new_copy,
                                [empty_ptr, ir.const_(ir.IntType(64), 0)],
                            )
                        )
                        return (RAWSTR, null_obj)
                    zero = {
                        I64: ir.const_(ir.IntType(64), 0),
                        F64: ir.const_(ir.DoubleType(), 0.0),
                        I1: ir.const_(ir.IntType(1), 0),
                    }[self.current_ret_kind]
                    self._emit_local_rawstr_drops()
                    self.current_builder.ret(zero)
                    return (OBJ, null_obj)
                coerced = self._coerce(value, self.current_ret_kind)
                self._emit_local_rawstr_drops()
                self.current_builder.ret(coerced[1])
                return coerced
            # dynamic function: box and return the PyObject (drops run
            # after the value is boxed - boxing copies out)
            if len(node) > 1 and node[1] is not None:
                value = self._convert_node(node[1])
                boxed = self._box(value)
                self._emit_local_rawstr_drops()
                self.current_builder.ret(boxed)
            else:
                self._emit_local_rawstr_drops()
                self.current_builder.ret(null_obj)
            return (OBJ, null_obj)

        if op == "list":
            element_nodes = node[1] if len(node) > 1 else []
            # a list literal of instances ([Token(1), ...]) becomes a raw
            # pointer array: elements ride as words, same as list[Token]
            all_instances = True
            for elem_node in element_nodes:
                if not self._instance_expr_kind(elem_node):
                    all_instances = False
            if element_nodes and all_instances:
                return self._build_raw_list(element_nodes, RAWLIST_I)
            list_obj = self.current_builder.call(self.create_list, [])
            for elem_node in element_nodes:
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
                # scalar cursor read: pos[0] on a promoted name is a
                # plain i64 load (the slot exists in this scope only)
                if (
                    isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 2
                    and node[1][0] == "name"
                    and node[1][1] in self.cursor_kinds
                    and isinstance(node[2], (list, tuple))
                    and node[2][:2] == ["const", 0]
                ):
                    return (
                        I64,
                        self.current_builder.load(
                            self._cursor_slot(node[1][1])
                        ),
                    )
                obj_tv = self._borrowed_field_str(node[1], node[2])
                if obj_tv is None:
                    obj_tv = self._convert_node(node[1])
                if obj_tv[0] in RAWDICT_KINDS:
                    # machine-word lookup; rawdict_get panics KeyError
                    # on a missing key (Python raises, Rust panics).
                    # The key node goes in unevaluated so slice keys
                    # become views without materializing
                    val_bits = self._rawdict_key_call(
                        obj_tv[0], obj_tv[1], node[2],
                        self.rawdict_get, self.rawdict_str_get,
                    (),
                    )
                    value_kind = RAWDICT_KINDS[obj_tv[0]]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            val_bits, ir.DoubleType()
                        )
                    return (value_kind, val_bits)
                key_tv = self._convert_node(node[2])
                if obj_tv[0] == RAWLIST_S:
                    # element read hands the caller its own copy (slots
                    # are shared; the reading slot owns the copy)
                    index = self._coerce(key_tv, I64)[1]
                    return (
                        RAWSTR,
                        self.current_builder.call(
                            self.rawlist_str_get, [obj_tv[1], index]
                        ),
                    )
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
                                ir.const_(ir.IntType(32), 0),
                                ir.const_(ir.IntType(32), 0),
                            ],
                        )
                    )
                    items = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.const_(ir.IntType(32), 0),
                                ir.const_(ir.IntType(32), 2),
                            ],
                        )
                    )
                    is_negative = self.current_builder.icmp_signed(
                        "<", index, ir.const_(ir.IntType(64), 0)
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
                            "IndexError: list index out of range",
                            self.current_builder,
                        )
                        self._emit_panic(self.current_builder, msg)

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
                                has_lo = ir.const_(
                                    ir.IntType(1), lower_node is not None
                                )
                                has_hi = ir.const_(
                                    ir.IntType(1), upper_node is not None
                                )
                                lo = (
                                    ir.const_(i64t, 0)
                                    if lower_node is None
                                    else self._coerce(
                                        self._convert_node(lower_node), I64
                                    )[1]
                                )
                                hi = (
                                    ir.const_(i64t, 0)
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
                                    ir.const_(ir.IntType(32), 0),
                                    ir.const_(ir.IntType(32), 3),
                                ],
                            )
                        )
                        lo = (
                            ir.const_(ir.IntType(64), 0)
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
                    return self._emit_char_view(obj_tv[1], index)
                obj = self._box(obj_tv)
                key = self._box(key_tv)
                return (
                    OBJ,
                    self.current_builder.call(self.pyobj_subscript, [obj, key]),
                )
            return (OBJ, null_obj)

        if op == "subscript_assign":
            if len(node) >= 4:
                if (
                    isinstance(node[1], (list, tuple))
                    and len(node[1]) >= 2
                    and node[1][0] == "name"
                    and node[1][1] in self.cursor_kinds
                    and isinstance(node[2], (list, tuple))
                    and node[2][:2] == ["const", 0]
                ):
                    value = self._coerce(
                        self._convert_node(node[3]), I64
                    )
                    self.current_builder.store(
                        value[1], self._cursor_slot(node[1][1])
                    )
                    return (OBJ, null_obj)
                obj_tv = self._convert_node(node[1])
                if obj_tv[0] == RAWLIST_S:
                    # copy-on-write into the slot (old element freed)
                    index = self._coerce(self._convert_node(node[2]), I64)[1]
                    value = self._coerce(self._convert_node(node[3]), RAWSTR)
                    self.current_builder.call(
                        self.rawlist_str_set,
                        [obj_tv[1], index, value[1]],
                    )
                    return (OBJ, null_obj)
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
                                ir.const_(ir.IntType(32), 0),
                                ir.const_(ir.IntType(32), 0),
                            ],
                        )
                    )
                    items = self.current_builder.load(
                        self.current_builder.gep(
                            struct_ptr,
                            [
                                ir.const_(ir.IntType(32), 0),
                                ir.const_(ir.IntType(32), 2),
                            ],
                        )
                    )
                    is_negative = self.current_builder.icmp_signed(
                        "<", index, ir.const_(ir.IntType(64), 0)
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
                            "IndexError: list assignment index out of range",
                            self.current_builder,
                        )
                        self._emit_panic(self.current_builder, msg)

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
                    value_kind = RAWDICT_KINDS[obj_tv[0]]

                    # d[k] = d.get(k, default) <op> rhs - the counting
                    # idiom. One probe via entry() (Rust's
                    # entry().or_insert) instead of get+set's two.
                    value_node = node[3]
                    if (
                        isinstance(value_node, list)
                        and len(value_node) >= 3
                        and isinstance(value_node[1], list)
                        and len(value_node[1]) >= 3
                        and value_node[1][0] == "call"
                        and isinstance(value_node[1][1], list)
                        and len(value_node[1][1]) >= 3
                        and value_node[1][1][0] == "attribute"
                        and value_node[1][1][1] == node[1]
                        and value_node[1][1][2] == "get"
                        and isinstance(value_node[1][2], (list, tuple))
                        and len(value_node[1][2]) == 2
                        and value_node[1][2][0] == node[2]
                    ):
                        binop = value_node[0]
                        default_bits_tv = self._coerce(
                            self._convert_node(value_node[1][2][1]),
                            value_kind,
                        )
                        default_bits = default_bits_tv[1]
                        if value_kind == F64:
                            default_bits = self.current_builder.bitcast(
                                default_bits, ir.IntType(64)
                            )
                        right_tv = self._convert_node(value_node[2])
                        slot = self._rawdict_key_call(
                            obj_tv[0], obj_tv[1], node[2],
                            self.rawdict_int_entry, self.rawdict_str_entry,
                            (default_bits,),
                        )
                        slot_i64 = self.current_builder.bitcast(
                            slot, ir.PointerType(ir.IntType(64))
                        )
                        current_bits = self.current_builder.load(slot_i64)
                        if value_kind == F64:
                            current_tv = (
                                F64,
                                self.current_builder.bitcast(
                                    current_bits, ir.DoubleType()
                                ),
                            )
                        else:
                            current_tv = (I64, current_bits)
                        result = self._typed_binop(binop, current_tv, right_tv)
                        coerced = self._coerce(result, value_kind)
                        store_bits = coerced[1]
                        if value_kind == F64:
                            store_bits = self.current_builder.bitcast(
                                store_bits, ir.IntType(64)
                            )
                        self.current_builder.store(store_bits, slot_i64)
                        return (OBJ, null_obj)

                    value = self._coerce(self._convert_node(node[3]), value_kind)
                    val_bits = value[1]
                    if value_kind == F64:
                        val_bits = self.current_builder.bitcast(
                            value[1], ir.IntType(64)
                        )
                    self._rawdict_key_call(
                        obj_tv[0], obj_tv[1], node[2],
                        self.rawdict_set, self.rawdict_str_set,
                        (val_bits,),
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
                    self._rawdict_key_call(
                        obj_tv[0], obj_tv[1],
                        node[2],
                        self.rawdict_del, self.rawdict_str_del,
                    (),
                    )
                    return (OBJ, null_obj)
                obj = self._box(obj_tv)
                key = self._box(self._convert_node(node[2]))
                popped = self.current_builder.call(self.dict_pop, [obj, key])
                is_null = self.current_builder.icmp_signed(
                    "==",
                    self.current_builder.ptrtoint(popped, ir.IntType(64)),
                    ir.const_(ir.IntType(64), 0),
                )
                ok_block = self.current_builder.function.append_basic_block(
                    "del_ok"
                )
                err_block = self.current_builder.function.append_basic_block(
                    "del_keyerr"
                )
                self.current_builder.cbranch(is_null, err_block, ok_block)
                self.current_builder.position_at_end(err_block)
                err_msg = self._create_global_string("KeyError: key not found")
                self._emit_panic(self.current_builder, err_msg)
                self.current_builder.position_at_end(ok_block)
            return (OBJ, null_obj)

        if op == "match":
            self._convert_match(node)
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
                    evaluated = []
                    for e in elements:
                        evaluated.append(self._convert_node(e))
                    for index, target in enumerate(targets):
                        if index >= len(evaluated) or not isinstance(target, str):
                            continue
                        kind = self.var_kinds.get(target, OBJ)
                        coerced = self._coerce(evaluated[index], kind)
                        self._declare_var(target, kind)
                        if kind == RAWSTR:
                            self._store_rawstr(target, coerced[1])
                        else:
                            self.current_builder.store(
                                coerced[1], self.variables[target]
                            )
            return (OBJ, null_obj)

        # unknown op: degrade to dynamic null
        return (OBJ, null_obj)

    def _convert_match(self, node: list):
        """match statement over a statically-typed scalar/str subject.

        Supported patterns: value literals (incl. enum members, they
        fold to constants), or-patterns, capture (case n), wildcard
        (case _), guards (case n if n > 0). Sequence/mapping/class
        patterns stay interpreter-only. First match wins; no match is
        a no-op (Python semantics)."""
        subject_tv = self._convert_node(node[1])
        subject_kind = subject_tv[0]
        if subject_kind not in (I64, I1, F64, RAWSTR):
            raise NotImplementedError(
                "compiled match needs a statically typed subject "
                "(annotate it: x: int / float / bool / str)"
            )
        i1 = ir.IntType(1)
        func = self.current_function
        end_block = func.append_basic_block("match_end")

        for case in node[2]:
            if (
                not isinstance(case, (list, tuple))
                or len(case) < 4
                or case[0] != "match_case"
            ):
                continue
            pattern, guard_node, body = case[1], case[2], case[3]
            body_block = func.append_basic_block("case_body")
            next_block = func.append_basic_block("case_next")

            cond, capture = self._match_pattern_parts(pattern, subject_kind, subject_tv)
            if capture is not None:
                # bind before the guard (guard may reference it)
                if subject_kind == RAWSTR:
                    self._declare_var(capture, RAWSTR)
                    self._store_rawstr(
                        capture,
                        self.current_builder.call(
                            self.rawstr_copy, [subject_tv[1]]
                        ),
                    )
                else:
                    self._declare_var(capture, subject_kind)
                    self.current_builder.store(
                        subject_tv[1], self.variables[capture]
                    )
            if cond is not None:
                guard_blk = (
                    func.append_basic_block("case_guard")
                    if guard_node is not None
                    else body_block
                )
                self.current_builder.cbranch(cond, guard_blk, next_block)
                self.current_builder.position_at_end(guard_blk)
            if guard_node is not None:
                guard_cond = self._to_i1_cond(self._convert_node(guard_node))
                self.current_builder.cbranch(guard_cond, body_block, next_block)
            if cond is None and guard_node is None:
                self.current_builder.branch(body_block)

            self.current_builder.position_at_end(body_block)
            for stmt in body:
                self._convert_statement(stmt)
                if self.current_builder.block.is_terminated:
                    break
            if not self.current_builder.block.is_terminated:
                self.current_builder.branch(end_block)

            self.current_builder.position_at_end(next_block)

        self.current_builder.branch(end_block)
        self.current_builder.position_at_end(end_block)

    def _convert_bool_chain(self, op: str, operand_nodes: list) -> Tuple[str, Any]:
        """N-ary short-circuit and/or over TypedValues."""
        is_and = op == "and"
        operand_kinds = []
        for n in operand_nodes:
            operand_kinds.append(self._static_kind_of(n))
        all_i1 = _all_of_kind(operand_kinds, I1)

        result_ptr = self.current_builder.alloca(
            ir.IntType(1) if all_i1 else ir.PointerType(self.pyobj.pyobj_type), None, 'sc_result',

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

    def _instance_expr_kind(self, node: Any) -> bool:
        """True when node statically evaluates to a class instance
        (constructor call, or a name already bound to an instance)."""
        if self._constructor_call_class(node) is not None:
            return True
        return self._class_of_node(node) is not None

    def _convert_for(self, node: list) -> Tuple[str, Any]:
        target_node, iter_node, body_stmts = node[1], node[2], node[3]

        # `for i, x in enumerate(seq)` desugars to a plain `for x in seq`
        # with a hidden counter: counter=0; loop { i = counter; body;
        # counter += 1 }. Static scalars stay scalars; dynamic seqs keep
        # the generic boxed iterator.
        if (
            isinstance(iter_node, (list, tuple))
            and len(iter_node) >= 3
            and iter_node[0] == "call"
            and isinstance(iter_node[1], (list, tuple))
            and len(iter_node[1]) >= 2
            and iter_node[1][0] == "name"
            and iter_node[1][1] == "enumerate"
            and len(iter_node[2]) == 1
            and isinstance(target_node, (list, tuple))
            and len(target_node) >= 2
            and target_node[0] == "tuple_unpack"
            and len(target_node[1]) == 2
            and _all_str(target_node[1])
        ):
            idx_name, val_name = target_node[1]
            counter_name = "__enum_ctr_" + str(self._enum_ctr_seq)
            self._enum_ctr_seq += 1
            seq_node = iter_node[2][0]
            self._convert_statement(
                ["assign", counter_name, ["const", 0], None]
            )
            desugared_body = [
                ["assign", idx_name, ["name", counter_name], None]
            ] + list(body_stmts) + [
                ["aug_assign", ["name", counter_name], "+=", ["const", 1]]
            ]
            return self._convert_for(
                ["for", ["name", val_name], seq_node, desugared_body,
                 node[4] if len(node) > 4 else []]
            )

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
            start = ir.const_(ir.IntType(64), 0)
            stop = self._coerce(self._convert_node(args_node[0]), I64)[1]
        elif len(args_node) >= 2:
            start = self._coerce(self._convert_node(args_node[0]), I64)[1]
            stop = self._coerce(self._convert_node(args_node[1]), I64)[1]
        else:
            start = ir.const_(ir.IntType(64), 0)
            stop = ir.const_(ir.IntType(64), 10)

        i64 = ir.IntType(64)
        loop_init = self.current_function.append_basic_block("loop_init")
        loop_cond = self.current_function.append_basic_block("loop_cond")
        loop_body = self.current_function.append_basic_block("loop_body")
        loop_end = self.current_function.append_basic_block("loop_end")
        incr_block = self.current_function.append_basic_block("loop_incr")

        counter_ptr = self.current_builder.alloca(i64, None, 'range_counter')
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
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.const_(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(loop_cond)

        self.current_builder.position_at_end(loop_end)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _loop_target_class(
        self, target_node: Any, list_tv: Tuple[str, Any]
    ) -> Optional[str]:
        """Class of a for-loop target iterating an instance-element list
        (`for t in toks` with toks: list[Token]). The list's own name
        carries the element class (recorded at its annotation)."""
        if (
            isinstance(target_node, (list, tuple))
            and len(target_node) >= 2
            and target_node[0] == "name"
            and isinstance(self._current_for_iter_name, str)
        ):
            return self._list_elem_class.get(self._current_for_iter_name)
        return None

    def _convert_rawlist_for_loop(
        self, target_node: Any, list_tv: Tuple[str, Any], body_stmts: list
    ) -> Tuple[str, Any]:
        """for x in raw_list: x loads as an unboxed element. For str
        lists the target receives a fresh copy each iteration (the
        drop-on-overwrite slot discipline frees the previous one)."""
        i64 = ir.IntType(64)
        elem_kind = RAWLIST_KINDS[list_tv[0]]
        list_ptr = list_tv[1]
        # list[Token]: elements are instance pointers riding as i64 words
        # (annotation lowered to RAWLIST_I); the target binds as INSTANCE
        if elem_kind == I64 and list_tv[0] == RAWLIST_I:
            target_class = self._loop_target_class(target_node, list_tv)
            if target_class is not None:
                elem_kind = INSTANCE

        cond_block = self.current_function.append_basic_block("riter_cond")
        body_block = self.current_function.append_basic_block("riter_body")
        incr_block = self.current_function.append_basic_block("riter_incr")
        end_block = self.current_function.append_basic_block("riter_end")

        counter_ptr = self.current_builder.alloca(i64, None, 'riter_idx')
        self.current_builder.store(ir.const_(i64, 0), counter_ptr)
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
                    [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 2)],
                )
            )
            items_i64 = self.current_builder.bitcast(
                items, ir.PointerType(ir.IntType(64))
            )
            element = self.current_builder.load(
                self.current_builder.gep(items_i64, [index])
            )
            if list_tv[0] == RAWLIST_S:
                copy = self.current_builder.call(
                    self.rawstr_copy,
                    [self.current_builder.inttoptr(element, ir.PointerType(ir.IntType(8)))],
                )
                self._declare_var(var_name, RAWSTR)
                self._store_rawstr(var_name, copy)
            elif elem_kind == INSTANCE:
                # list[Instance]: the word is the pointer - inttoptr
                self._declare_var(var_name, INSTANCE)
                self._var_class[var_name] = self._list_elem_class.get(
                    self._current_for_iter_name or "", ""
                ) or self._var_class.get(var_name)
                self.current_builder.store(
                    self.current_builder.inttoptr(
                        element, LLVM_KIND_TYPES[INSTANCE]
                    ),
                    self.variables[var_name],
                )
            else:
                if elem_kind == F64:
                    element = self.current_builder.bitcast(element, ir.DoubleType())
                self._declare_var(var_name, elem_kind)
                self.current_builder.store(element, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.const_(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _convert_rawstr_for_loop(
        self, target_node: Any, str_tv: Tuple[str, Any], body_stmts: list
    ) -> Tuple[str, Any]:
        """for ch in raw_str: ch is a fresh one-code-point rawstr per
        iteration. Iteration walks byte offsets (decode the lead byte,
        advance by the sequence length), so the whole loop is O(bytes)
        even though each char is code-point semantics."""
        i64 = ir.IntType(64)
        str_ptr = str_tv[1]

        cond_block = self.current_function.append_basic_block("siter_cond")
        body_block = self.current_function.append_basic_block("siter_body")
        end_block = self.current_function.append_basic_block("siter_end")

        offset_ptr = self.current_builder.alloca(i64, None, 'siter_off')
        seq_ptr = self.current_builder.alloca(i64, None, 'siter_seq')
        self.current_builder.store(ir.const_(i64, 0), offset_ptr)
        struct_ptr = self.current_builder.bitcast(
            str_ptr, ir.PointerType(self.rawstr_struct_type)
        )
        byte_len = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        data = self.current_builder.load(
            self.current_builder.gep(
                struct_ptr,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 2)],
            )
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(cond_block)
        offset = self.current_builder.load(offset_ptr)
        more = self.current_builder.icmp_signed("<", offset, byte_len)
        self.current_builder.cbranch(more, body_block, end_block)

        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(cond_block)

        self.current_builder.position_at_end(body_block)
        lead = self.current_builder.load(
            self.current_builder.gep(data, [offset])
        )
        seq = self._emit_utf8_seq_len(lead)
        self.current_builder.store(seq, seq_ptr)

        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            # fresh one-code-point rawstr: {seq, seq, data+off, 1}
            char_struct = self.current_builder.bitcast(
                self.current_builder.call(
                    self.malloc, [ir.const_(i64, 32)]
                ),
                ir.PointerType(self.rawstr_struct_type),
            )
            char_buf = self.current_builder.call(self.malloc, [seq])
            self.current_builder.call(
                self.memcpy,
                [
                    char_buf,
                    self.current_builder.gep(data, [offset]),
                    seq,
                    ir.const_(ir.IntType(1), 0),
                ],
            )
            for field_index, field_value in (
                (0, seq),
                (1, seq),
                (3, ir.const_(i64, 1)),
            ):
                self.current_builder.store(
                    field_value,
                    self.current_builder.gep(
                        char_struct,
                        [
                            ir.const_(ir.IntType(32), 0),
                            ir.const_(ir.IntType(32), field_index),
                        ],
                    ),
                )
            self.current_builder.store(
                char_buf,
                self.current_builder.gep(
                    char_struct,
                    [
                        ir.const_(ir.IntType(32), 0),
                        ir.const_(ir.IntType(32), 2),
                    ],
                ),
            )
            self._declare_var(var_name, RAWSTR)
            self._store_rawstr(var_name, self.current_builder.bitcast(
                char_struct, ir.PointerType(ir.IntType(8))
            ))

        for stmt in body_stmts:
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.store(
                self.current_builder.add(
                    self.current_builder.load(offset_ptr),
                    self.current_builder.load(seq_ptr),
                ),
                offset_ptr,
            )
            self.current_builder.branch(cond_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _create_char_idxerr_global(self):
        """The panic message global for char-view bounds errors (created
        once; the per-site gep lives in each emitter's error block)."""
        string_bytes = bytearray(
            b"IndexError: string index out of range\0"
        )
        string_type = ir.ArrayType(ir.IntType(8), len(string_bytes))
        gv = ir.gvar_(
            self.module,
            string_type, f'str_{len(self.module.globals)}',

        )
        gv.global_constant = True
        gv.initializer = ir.const_(string_type, string_bytes)
        return gv

    def _emit_char_view(self, str_ptr: Any, index: Any):
        """s[index] as a borrowed {i8* data, i64 seq} SSA window into
        the parent buffer - zero allocation. Code point semantics via
        the ASCII fast path / code point walk; bounds still panic."""
        zero32 = ir.const_(ir.IntType(32), 0)
        zero64 = ir.const_(ir.IntType(64), 0)
        one64 = ir.const_(ir.IntType(64), 1)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        b = self.current_builder
        s_struct = b.bitcast(str_ptr, ir.PointerType(self.rawstr_struct_type))
        s_cp = b.load(b.gep(s_struct, [zero32, ir.const_(i32, 3)]))
        s_len = b.load(b.gep(s_struct, [zero32, ir.const_(i32, 0)]))
        s_data = b.load(b.gep(s_struct, [zero32, ir.const_(i32, 2)]))
        is_neg = b.icmp_signed("<", index, zero64)
        index_eff = b.select(is_neg, b.add(index, s_cp), index)
        below = b.icmp_signed(">=", index_eff, zero64)
        above = b.icmp_signed("<", index_eff, s_cp)
        func = self.current_function
        ok_block = func.append_basic_block("cv_ok")
        err_block = func.append_basic_block("cv_err")
        b.cbranch(b.and_(below, above), ok_block, err_block)

        b.position_at_end(err_block)
        if self._char_idxerr is None:
            self._char_idxerr = self._create_char_idxerr_global()
        self._emit_panic(
            b,
            b.gep(self._char_idxerr, [zero32, zero32]),
        )

        b.position_at_end(ok_block)
        is_ascii = b.icmp_signed("==", s_len, s_cp)
        ascii_block = func.append_basic_block("cv_ascii")
        walk_block = func.append_basic_block("cv_walk")
        join_block = func.append_basic_block("cv_join")
        b.cbranch(is_ascii, ascii_block, walk_block)

        b.position_at_end(ascii_block)
        b.branch(join_block)

        b.position_at_end(walk_block)
        walked = b.call(self.rawutf8_cp_offset, [s_data, index_eff])
        b.branch(join_block)

        b.position_at_end(join_block)
        off = b.phi(i64)
        off.add_incoming(index_eff, ascii_block)
        off.add_incoming(walked, walk_block)
        lead = b.load(b.gep(s_data, [off]))
        seq = b.select(is_ascii, one64, self._emit_utf8_seq_len_with(b, lead))
        view = ir.const_(ir.LiteralStructType([i8p, i64]), ir.Undefined)
        view = b.insert_value(view, b.gep(s_data, [off]), 0)
        view = b.insert_value(view, seq, 1)
        return (RAWCHAR_VIEW, view)

    def _emit_utf8_seq_len_with(self, b, byte_value):
        """UTF-8 sequence length through an explicit builder (shared by
        the runtime builder and the char-view emitter)."""
        b8 = ir.IntType(8)
        two = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xE0)),
            ir.const_(b8, 0xC0),
        )
        three = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xF0)),
            ir.const_(b8, 0xE0),
        )
        four = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xF8)),
            ir.const_(b8, 0xF0),
        )
        len2 = b.select(four, ir.const_(ir.IntType(64), 4),
                        ir.const_(ir.IntType(64), 1))
        len3 = b.select(three, ir.const_(ir.IntType(64), 3), len2)
        return b.select(two, ir.const_(ir.IntType(64), 2), len3)

    def _emit_utf8_seq_len(self, byte_value):
        """UTF-8 sequence length from a lead byte (invalid -> 1)."""
        b8 = ir.IntType(8)
        i64 = ir.IntType(64)
        b = self.current_builder
        two = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xE0)),
            ir.const_(b8, 0xC0),
        )
        three = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xF0)),
            ir.const_(b8, 0xE0),
        )
        four = b.icmp_signed(
            "==", b.and_(byte_value, ir.const_(b8, 0xF8)),
            ir.const_(b8, 0xF0),
        )
        len2 = b.select(four, ir.const_(i64, 4), ir.const_(i64, 1))
        len3 = b.select(three, ir.const_(i64, 3), len2)
        return b.select(two, ir.const_(i64, 2), len3)

    def _build_raw_list(self, element_nodes: list, kind: str) -> Tuple[str, Any]:
        """[a, b, c] literal stored into a rawlist-typed variable. Str
        lists take copies of every element (the list owns them)."""
        i8p = ir.PointerType(ir.IntType(8))
        elem_kind = RAWLIST_KINDS[kind]
        if kind == RAWLIST_S:
            list_ptr = self.current_builder.call(
                self.rawlist_new, [ir.const_(ir.IntType(64), 8)]
            )
            for element_node in element_nodes:
                elem = self._coerce(self._convert_node(element_node), RAWSTR)
                self.current_builder.call(
                    self.rawlist_str_push, [list_ptr, elem[1]]
                )
            return (kind, list_ptr)
        elem_size = _rawlist_elem_size(kind)
        list_ptr = self.current_builder.call(
            self.rawlist_new,
            [ir.const_(ir.IntType(64), elem_size)],
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
        # dict iteration: for k, v in d.items() / for k in d.keys() /
        # for v in d.values() — a direct index walk over the entry
        # storage, no intermediate list (Rust HashMap::iter() shape;
        # iteration order is implementation-defined)
        iter_attr = None
        if (
            isinstance(iter_node, (list, tuple))
            and len(iter_node) >= 3
            and iter_node[0] == "call"
            and isinstance(iter_node[1], (list, tuple))
            and len(iter_node[1]) >= 3
            and iter_node[1][0] == "attribute"
            and iter_node[1][2] in ("items", "keys", "values")
        ):
            iter_attr = iter_node[1]
        if iter_attr is not None:
            return self._convert_dict_for_loop(
                target_node, iter_attr[1], iter_attr[2], body_stmts
            )
        iter_tv = self._convert_node(iter_node)
        if iter_tv[0] in RAWDICT_KINDS:
            # `for k in d` on a raw dict iterates the keys
            return self._convert_dict_for_loop(
                target_node, iter_node, "keys", body_stmts
            )
        if iter_tv[0] in RAWLIST_KINDS:
            # remember the iterated name so instance-element lists can
            # bind the loop target as INSTANCE
            self._current_for_iter_name = (
                iter_node[1]
                if (
                    isinstance(iter_node, (list, tuple))
                    and len(iter_node) >= 2
                    and iter_node[0] == "name"
                    and isinstance(iter_node[1], str)
                )
                else None
            )
            result = self._convert_rawlist_for_loop(
                target_node, iter_tv, body_stmts
            )
            self._current_for_iter_name = None
            return result
        if iter_tv[0] == RAWSTR:
            return self._convert_rawstr_for_loop(target_node, iter_tv, body_stmts)
        if (
            iter_tv[0] == OBJ
            and isinstance(iter_node, (list, tuple))
            and len(iter_node) >= 2
            and iter_node[0] == "const"
            and isinstance(iter_node[1], str)
        ):
            # a string literal boxes lazily; iterating one is the rawstr
            # code-point walk (the generic path below assumes a list)
            raw = self.current_builder.call(
                self.pystr_to_rawstr, [iter_tv[1]]
            )
            return self._convert_rawstr_for_loop(
                target_node, (RAWSTR, raw), body_stmts
            )
        list_obj = self._box(iter_tv)
        if list_obj is None:
            return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

        cond_block = self.current_function.append_basic_block("iter_cond")
        body_block = self.current_function.append_basic_block("iter_body")
        incr_block = self.current_function.append_basic_block("iter_incr")
        end_block = self.current_function.append_basic_block("iter_end")

        counter_ptr = self.current_builder.alloca(i64, None, 'iter_idx')
        self.current_builder.store(ir.const_(i64, 0), counter_ptr)
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
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        self.current_builder.store(
            self.current_builder.add(
                self.current_builder.load(counter_ptr), ir.const_(i64, 1)
            ),
            counter_ptr,
        )
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _bind_loop_var(self, name: str, tv: Tuple[str, Any]) -> None:
        """Store an iterated value into its loop variable, coercing into
        an existing slot or declaring a fresh one."""
        if name in self.var_kinds and self.var_kinds[name] != tv[0]:
            coerced = self._coerce(tv, self.var_kinds[name])
            self.current_builder.store(coerced[1], self.variables[name])
            return
        if name not in self.variables:
            self._declare_var(name, tv[0])
        self.current_builder.store(tv[1], self.variables[name])

    def _convert_dict_for_loop(
        self, target_node: Any, recv_node: Any, mode: str, body_stmts: list
    ) -> Tuple[str, Any]:
        recv_tv = self._convert_node(recv_node)
        if recv_tv[0] in RAWDICT_KINDS:
            return self._convert_rawdict_for_loop(
                target_node, recv_tv, mode, body_stmts
            )
        return self._convert_boxed_dict_for_loop(
            target_node, recv_tv, mode, body_stmts
        )

    def _dict_loop_blocks(self):
        func = self.current_function
        cond_block = func.append_basic_block("dict_iter_cond")
        check_block = func.append_basic_block("dict_iter_check")
        body_block = func.append_basic_block("dict_iter_body")
        incr_block = func.append_basic_block("dict_iter_incr")
        end_block = func.append_basic_block("dict_iter_end")
        return cond_block, check_block, body_block, incr_block, end_block

    def _run_dict_loop_body(self, body_stmts, incr_block, end_block):
        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(incr_block)
        for stmt in body_stmts:
            self._convert_statement(stmt)
            if self.current_builder.block.is_terminated:
                break
        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)
        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

    def _convert_rawdict_for_loop(
        self, target_node: Any, recv_tv: Tuple[str, Any], mode: str,
        body_stmts: list,
    ) -> Tuple[str, Any]:
        """Index walk over a raw dict's slot table: live slots hold
        entry_index + 1 (0 = empty, -1 = tombstone)."""
        i64 = ir.IntType(64)
        zero32 = ir.const_(ir.IntType(32), 0)
        b = self.current_builder
        kind = recv_tv[0]
        struct_ptr = b.bitcast(
            recv_tv[1], ir.PointerType(self.raw_dict_struct_type)
        )

        cap = b.add(
            b.load(_struct_gep(b, struct_ptr, 3)), ir.const_(i64, 1)
        )  # mask + 1
        table = b.load(_struct_gep(b, struct_ptr, 4))
        keys = b.load(_struct_gep(b, struct_ptr, 5))
        vals = b.load(_struct_gep(b, struct_ptr, 6))
        k_name, v_name = _dict_loop_names(target_node, mode)

        cond_block, check_block, body_block, incr_block, end_block = (
            self._dict_loop_blocks()
        )
        idx_ptr = b.alloca(i64, None, 'dict_iter_idx')
        b.store(ir.const_(i64, 0), idx_ptr)
        b.branch(cond_block)

        b.position_at_end(cond_block)
        index = b.load(idx_ptr)
        b.cbranch(b.icmp_signed("<", index, cap), check_block, end_block)

        b.position_at_end(check_block)
        slot_entry = b.load(b.gep(table, [index]))
        b.cbranch(
            b.icmp_signed(">", slot_entry, ir.const_(i64, 0)),
            body_block,
            incr_block,
        )

        b.position_at_end(body_block)
        entry_index = b.sub(slot_entry, ir.const_(i64, 1))
        if k_name is not None:
            key_bits = b.load(b.gep(keys, [entry_index]))
            if kind in RAWDICT_STR_KINDS:
                # stored key is the rawstr pointer itself (i8*); a
                # RAWSTR value IS that pointer — box a copy so the
                # loop variable owns no dict storage
                kptr = b.inttoptr(key_bits, ir.PointerType(ir.IntType(8)))
                self._bind_loop_var(
                    k_name, (OBJ, self._box((RAWSTR, kptr)))
                )
            else:
                self._bind_loop_var(k_name, (I64, key_bits))
        if v_name is not None:
            val_bits = b.load(b.gep(vals, [entry_index]))
            if RAWDICT_KINDS[kind] == F64:
                self._bind_loop_var(
                    v_name, (F64, b.bitcast(val_bits, ir.DoubleType()))
                )
            else:
                self._bind_loop_var(v_name, (I64, val_bits))
        self._run_dict_loop_body(body_stmts, incr_block, end_block)

        b.position_at_end(incr_block)
        b.store(b.add(b.load(idx_ptr), ir.const_(i64, 1)), idx_ptr)
        b.branch(cond_block)

        b.position_at_end(end_block)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _convert_boxed_dict_for_loop(
        self, target_node: Any, recv_tv: Tuple[str, Any], mode: str,
        body_stmts: list,
    ) -> Tuple[str, Any]:
        """Walk a boxed dict's entry array; deleted entries carry a
        null key and are skipped. Keys and values bind as PyObject."""
        i64 = ir.IntType(64)
        zero32 = ir.const_(ir.IntType(32), 0)
        one32 = ir.const_(ir.IntType(32), 1)
        b = self.current_builder
        pyobj_null = ir.const_(
            ir.PointerType(self.pyobj.pyobj_type), None
        )
        obj = self._box(recv_tv)
        data = b.load(b.gep(obj, [zero32, one32]))
        struct_ptr = b.bitcast(
            data, ir.PointerType(self.dict_struct_type)
        )
        used = b.load(
            b.gep(struct_ptr, [zero32, ir.const_(ir.IntType(32), 1)])
        )
        entries = b.load(
            b.gep(struct_ptr, [zero32, ir.const_(ir.IntType(32), 4)])
        )
        k_name, v_name = _dict_loop_names(target_node, mode)

        cond_block, check_block, body_block, incr_block, end_block = (
            self._dict_loop_blocks()
        )
        idx_ptr = b.alloca(i64, None, 'dict_iter_idx')
        b.store(ir.const_(i64, 0), idx_ptr)
        b.branch(cond_block)

        b.position_at_end(cond_block)
        index = b.load(idx_ptr)
        b.cbranch(b.icmp_signed("<", index, used), check_block, end_block)

        b.position_at_end(check_block)
        entry_ptr = b.gep(entries, [zero32, index])
        key_obj = b.load(b.gep(entry_ptr, [zero32, zero32]))
        b.cbranch(
            b.icmp_signed("!=", key_obj, pyobj_null), body_block, incr_block
        )

        b.position_at_end(body_block)
        if k_name is not None:
            self._bind_loop_var(k_name, (OBJ, key_obj))
        if v_name is not None:
            val_obj = b.load(b.gep(entry_ptr, [zero32, one32]))
            self._bind_loop_var(v_name, (OBJ, val_obj))
        self._run_dict_loop_body(body_stmts, incr_block, end_block)

        b.position_at_end(incr_block)
        b.store(b.add(b.load(idx_ptr), ir.const_(i64, 1)), idx_ptr)
        b.branch(cond_block)

        b.position_at_end(end_block)
        return (OBJ, pyobj_null)

    def _convert_call(self, node: list) -> Tuple[str, Any]:
        func_node = node[1]
        args_node = node[2] if len(node) > 2 else []

        # class construction: JointState(1.0, 2.0) - dataclass semantics
        if (
            isinstance(func_node, list)
            and len(func_node) >= 2
            and func_node[0] == "name"
            and func_node[1] in self._class_layouts
        ):
            return self._emit_construct(
                func_node[1], args_node, node[3] if len(node) > 3 else []
            )

        # method calls stay fully dynamic
        if (
            isinstance(func_node, list)
            and len(func_node) >= 3
            and func_node[0] == "attribute"
        ):
            method_name = func_node[2]
            raw_obj_tv = self._convert_node(func_node[1])
            raw_kind = raw_obj_tv[0]
            if raw_kind == INSTANCE:
                return self._emit_method_call(
                    func_node[1], method_name, args_node
                )
            if raw_kind in RAWLIST_KINDS:
                elem_kind = RAWLIST_KINDS[raw_kind]
                elem_size = _rawlist_elem_size(raw_kind)
                list_ptr = raw_obj_tv[1]
                if method_name == "append" and args_node:
                    arg_tv = self._convert_node(args_node[0])
                    if arg_tv[0] == INSTANCE:
                        # instance elements ride the list as raw pointers
                        self.current_builder.call(
                            self.rawlist_push,
                            [
                                list_ptr,
                                self.current_builder.ptrtoint(
                                    arg_tv[1], ir.IntType(64)
                                ),
                            ],
                        )
                        return (raw_kind, list_ptr)
                    elem = self._coerce(arg_tv, elem_kind)
                    if raw_kind == RAWLIST_S:
                        # the list stores its own copy of the string
                        self.current_builder.call(
                            self.rawlist_str_push, [list_ptr, elem[1]]
                        )
                    else:
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
                    if raw_kind == RAWLIST_S:
                        return (
                            RAWSTR,
                            self.current_builder.call(
                                self.rawlist_str_pop, [list_ptr]
                            ),
                        )
                    return (
                        elem_kind,
                        self.current_builder.call(self.rawlist_pop, [list_ptr]),
                    )
                if method_name == "clear" and not args_node:
                    if raw_kind == RAWLIST_S:
                        self.current_builder.call(
                            self.rawlist_str_clear, [list_ptr]
                        )
                    else:
                        self.current_builder.call(self.rawlist_clear, [list_ptr])
                    return (OBJ, ir.const_(
                        ir.PointerType(self.pyobj.pyobj_type), None
                    ))
                return self._unsupported_raw_method(raw_kind, method_name)
            if raw_kind in RAWDICT_KINDS:
                value_kind = RAWDICT_KINDS[raw_kind]

                if method_name == "pop" and args_node:
                    key_tv = self._convert_node(args_node[0])
                    if len(args_node) == 1:
                        # pop(k): rawdict_del panics KeyError when missing
                        bits = self._rawdict_key_call_tv(
                            raw_kind, raw_obj_tv[1], key_tv,
                            self.rawdict_del, self.rawdict_str_del,
                        (),
                        )
                    elif len(args_node) == 2:
                        bits = self._rawdict_key_call_tv(
                            raw_kind, raw_obj_tv[1], key_tv,
                            self.rawdict_pop_or, self.rawdict_str_pop_or,
                            (self._dict_value_bits(args_node[1], value_kind),),
                        )
                    else:
                        bits = None
                    if bits is not None:
                        return self._dict_bits_to_value(bits, value_kind)
                if method_name == "get" and args_node:
                    key_tv = self._convert_node(args_node[0])
                    if len(args_node) == 2:
                        bits = self._rawdict_key_call_tv(
                            raw_kind, raw_obj_tv[1], key_tv,
                            self.rawdict_get_or, self.rawdict_str_get_or,
                            (self._dict_value_bits(args_node[1], value_kind),),
                        )
                        return self._dict_bits_to_value(bits, value_kind)
                    if len(args_node) == 1:
                        # get(k): value when present, None (null)
                        # otherwise. Materialize the key once: the view
                        # helper may branch (tag check), which would
                        # break the hit/miss phi if done per call
                        if raw_kind in RAWDICT_STR_KINDS:
                            key_ptr, key_temp = self._rawstr_key_view_tv(key_tv)
                        else:
                            key_ptr = self._coerce(key_tv, I64)[1]
                            key_temp = None
                        present = self.current_builder.call(
                            _rawdict_call_fn(
                                raw_kind, self.rawdict_has,
                                self.rawdict_str_has,
                            ),
                            [raw_obj_tv[1], key_ptr],
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
                            _rawdict_call_fn(
                                raw_kind, self.rawdict_get,
                                self.rawdict_str_get,
                            ),
                            [raw_obj_tv[1], key_ptr],
                        )
                        if key_temp is not None:
                            self.current_builder.call(
                                self.rawstr_free, [key_temp]
                            )
                        boxed_hit = self._box(self._dict_bits_to_value(bits, value_kind))
                        self.current_builder.branch(merge_block)
                        self.current_builder.position_at_end(miss_block)
                        if key_temp is not None:
                            self.current_builder.call(
                                self.rawstr_free, [key_temp]
                            )
                        self.current_builder.branch(merge_block)
                        self.current_builder.position_at_end(merge_block)
                        result = self.current_builder.phi(
                            ir.PointerType(self.pyobj.pyobj_type)
                        )
                        result.add_incoming(boxed_hit, hit_block)
                        result.add_incoming(
                            ir.const_(
                                ir.PointerType(self.pyobj.pyobj_type), None
                            ),
                            miss_block,
                        )
                        return (OBJ, result)
                if method_name == "setdefault" and len(args_node) == 2:
                    bits = self._rawdict_key_call(
                        raw_kind, raw_obj_tv[1],
                        args_node[0],
                        self.rawdict_setdefault, self.rawdict_str_setdefault,
                        (self._dict_value_bits(args_node[1], value_kind),),
                    )
                    return self._dict_bits_to_value(bits, value_kind)
                if method_name == "clear" and not args_node:
                    self.current_builder.call(
                        _rawdict_call_fn(
                            raw_kind, self.rawdict_clear,
                            self.rawdict_str_clear,
                        ),
                        [raw_obj_tv[1]],
                    )
                    return (OBJ, ir.const_(
                        ir.PointerType(self.pyobj.pyobj_type), None
                    ))
                return self._unsupported_raw_method(raw_kind, method_name)
            if raw_kind in (RAWSTR, RAWCHAR_VIEW) or (
                # string literal receiver: "a,b".split(",")
                isinstance(func_node[1], list)
                and len(func_node[1]) >= 2
                and func_node[1][0] == "const"
                and isinstance(func_node[1][1], str)
            ):
                handled = self._rawstr_method_call(
                    raw_obj_tv, method_name, args_node
                )
                if handled is not None:
                    return handled
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
                "isdigit": (self.str_isdigit, 0, True),
                "isalpha": (self.str_isalpha, 0, True),
                "isspace": (self.str_isspace, 0, True),
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
                arg_vals = []
                for arg in args_node[:arg_count]:
                    arg_tv = self._convert_node(arg)
                    if arg_tv[0] == INSTANCE:
                        # boxed fallback path: instances still can't box,
                        # but counts.get/copy-free methods never see them;
                        # fail loudly rather than corrupting
                        raise NotImplementedError(
                            "class instances cannot be boxed yet "
                            "(print a field, not the instance)"
                        )
                    arg_vals.append(self._box(arg_tv))
                while len(arg_vals) < arg_count:
                    arg_vals.append(
                        ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
                    )
                if len(arg_vals) == arg_count and all(arg_vals):
                    result = self.current_builder.call(func, [obj] + arg_vals)
                    return (OBJ, result) if has_result else (OBJ, result)
            raise NotImplementedError(
                f"method '{method_name}' is not supported on dynamic values"
            )

        if (
            isinstance(func_node, list)
            and len(func_node) >= 2
            and func_node[0] == "name"
        ):
            func_name = func_node[1]

            if func_name in self._funcref_var:
                # indirect call through a funcref local: resolve the
                # target statically (the slot itself is never read)
                mangled = self._funcref_var[func_name]
                fn = self.functions.get(mangled)
                if fn is None:
                    raise NameError(
                        f"funcref to unknown function '{mangled}'"
                    )
                static = self.static_funcs.get(mangled)
                if static is not None:
                    param_kinds, ret_kind = static[0], static[1]
                else:
                    param_kinds = self._dyn_func_kinds.get(mangled)
                    ret_kind = OBJ
                raw_args = []
                for index, arg_node in enumerate(args_node):
                    kind = (
                        param_kinds[index]
                        if param_kinds and index < len(param_kinds)
                        else OBJ
                    )
                    arg_tv = self._convert_node(arg_node)
                    if kind == OBJ:
                        raw_args.append(self._box(arg_tv))
                    else:
                        raw_args.append(self._coerce(arg_tv, kind)[1])
                return (ret_kind, self.current_builder.call(fn, raw_args))

            if func_name == "print":
                kwargs = node[3] if len(node) > 3 else []
                end_str = "\n"
                for kw_name, kw_value_node in kwargs or ():
                    if kw_name == "end" and (
                        isinstance(kw_value_node, list)
                        and len(kw_value_node) >= 2
                        and kw_value_node[0] == "const"
                        and isinstance(kw_value_node[1], str)
                    ):
                        end_str = kw_value_node[1]
                if args_node:
                    for index, arg_node in enumerate(args_node):
                        if index > 0:
                            sep = self._create_global_string(" ")
                            self.current_builder.call(self.printf, [sep])
                        boxed = self._box(self._convert_node(arg_node))
                        if boxed is not None:
                            self.current_builder.call(self.pyobj_print, [boxed])
                if end_str:
                    end_fmt = self._create_global_string(end_str)
                    self.current_builder.call(self.printf, [end_fmt])
                return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

            if func_name == "input":
                return (
                    OBJ,
                    self.current_builder.call(self.pyobj_input, []),
                )

            if func_name == "read_stdin":
                # read stdin to EOF (Rust io::read_to_string)
                return (
                    OBJ,
                    self.current_builder.call(self.pyobj_read_stdin, []),
                )

            if func_name == "isinstance" and len(args_node) == 2:
                return (I1, self._emit_isinstance(args_node[0], args_node[1]))

            if func_name == "ord" and len(args_node) == 1:
                arg_tv = self._convert_node(args_node[0])
                if arg_tv[0] == RAWCHAR_VIEW:
                    # a borrowed char view decodes in place - zero
                    # allocation (the lexer hot loop: ord(src[i]))
                    data = self.current_builder.extract_value(arg_tv[1], 0)
                    seq = self.current_builder.extract_value(arg_tv[1], 1)
                    return (
                        I64,
                        self.current_builder.call(self.view_ord, [data, seq]),
                    )
                # code point of a one-character string (panics otherwise)
                raw_ptr, temp = self._rawstr_operand(arg_tv)
                result = self.current_builder.call(self.rawstr_ord, [raw_ptr])
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
                return (I64, result)

            if func_name == "chr" and len(args_node) == 1:
                # one-character string from a code point (UTF-8 encode)
                cp = self._coerce(self._convert_node(args_node[0]), I64)[1]
                return (
                    RAWSTR,
                    self.current_builder.call(self.rawstr_chr, [cp]),
                )

            if func_name == "file_exists":
                # file_exists(path) -> bool (Rust Path::exists)
                path_ptr, path_temp = self._rawstr_operand(
                    self._convert_node(args_node[0])
                )
                path_struct = self.current_builder.bitcast(
                    path_ptr, ir.PointerType(self.rawstr_struct_type)
                )
                exists_i1 = self.current_builder.call(
                    self.path_exists,
                    [
                        _rawstr_load_data(self.current_builder, path_struct),
                        _rawstr_load_len(self.current_builder, path_struct),
                    ],
                )
                if path_temp is not None:
                    self.current_builder.call(
                        self.rawstr_free, [path_temp]
                    )
                return (I1, exists_i1)

            if func_name == "read_file":
                # read_file(path) -> str (Rust fs::read_to_string)
                if not args_node:
                    return (OBJ, ir.const_(
                        ir.PointerType(self.pyobj.pyobj_type), None
                    ))
                data_ptr, byte_len, temp = self._rawstr_append_operand(
                    args_node[0]
                )
                result = self.current_builder.call(
                    self.pyobj_read_file, [data_ptr, byte_len]
                )
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
                return (OBJ, result)

            if func_name == "str":
                # scalar str() conversion; boxed path, the result coerces
                # back to rawstr at the use site when annotated
                if len(args_node) == 1:
                    boxed = self._box(self._convert_node(args_node[0]))
                    return (
                        OBJ,
                        self.current_builder.call(self.pyobj_str_conv, [boxed]),
                    )
                return (OBJ, ir.const_(
                    ir.PointerType(self.pyobj.pyobj_type), None
                ))

            if func_name == "fmt" and args_node:
                # fmt(parts...): concatenate str() of every arg (the
                # f-string desugar target - one buffer, no intermediate
                # joins at the source level)
                empty = self.current_builder.call(
                    self.create_str,
                    [
                        self._create_global_string(""),
                        ir.const_(ir.IntType(32), 0),
                    ],
                )
                acc = empty
                for arg_node in args_node:
                    boxed = self._box(self._convert_node(arg_node))
                    as_str = self.current_builder.call(
                        self.pyobj_str_conv, [boxed]
                    )
                    acc = self.current_builder.call(self.pyobj_add, [acc, as_str])
                return (OBJ, acc)

            if func_name == "float" and len(args_node) == 1:
                # float(x): numbers coerce directly; strings parse
                # through strtod (Python float())
                arg_tv = self._convert_node(args_node[0])
                if arg_tv[0] == F64:
                    return (F64, arg_tv[1])
                if arg_tv[0] in (I64, I1):
                    return (F64, self._coerce(arg_tv, F64)[1])
                if arg_tv[0] in (OBJ, RAWSTR, RAWCHAR_VIEW):
                    raw_ptr, temp = self._rawstr_operand(arg_tv)
                    cstr = self.current_builder.call(
                        self.rawstr_to_cstr, [raw_ptr]
                    )
                    end_ptr = self.current_builder.alloca(
                        ir.PointerType(ir.IntType(8)), None, 'fend'
                    )
                    parsed = self.current_builder.call(
                        self.strtod, [cstr, end_ptr]
                    )
                    end_val = self.current_builder.load(end_ptr)
                    moved = self.current_builder.icmp_signed(
                        "!=", end_val, cstr
                    )
                    if self.checks:
                        self._panic_if(
                            self.current_builder.not_(moved),
                            "ValueError: invalid literal for float()",
                        )
                    self.current_builder.call(self.free, [cstr])
                    if temp is not None:
                        self.current_builder.call(self.rawstr_free, [temp])
                    return (F64, parsed)
                return (F64, ir.const_(ir.DoubleType(), 0.0))

            if func_name == "int" and len(args_node) == 1:
                # int(x): floats truncate like Python's int(); the
                # annotation contract (x: int = f) keeps its panic via
                # the implicit-coercion path, this builtin does not
                arg_tv = self._convert_node(args_node[0])
                if arg_tv[0] == I64:
                    return (I64, arg_tv[1])
                if arg_tv[0] == I1:
                    return (I64, self._coerce(arg_tv, I64)[1])
                if arg_tv[0] == F64:
                    return (
                        I64,
                        self.current_builder.fptosi(arg_tv[1], ir.IntType(64)),
                    )
                if arg_tv[0] in (OBJ, RAWSTR, RAWCHAR_VIEW):
                    raw_ptr, temp = self._rawstr_operand(arg_tv)
                    cstr = self.current_builder.call(
                        self.rawstr_to_cstr, [raw_ptr]
                    )
                    end_ptr = self.current_builder.alloca(
                        ir.PointerType(ir.IntType(8)), None, 'iend'
                    )
                    parsed = self.current_builder.call(
                        self.strtol,
                        [
                            cstr,
                            end_ptr,
                            ir.const_(ir.IntType(32), 10),
                        ],
                    )
                    end_val = self.current_builder.load(end_ptr)
                    moved = self.current_builder.icmp_signed(
                        "!=", end_val, cstr
                    )
                    if self.checks:
                        self._panic_if(
                            self.current_builder.not_(moved),
                            "ValueError: invalid literal for int()",
                        )
                    self.current_builder.call(self.free, [cstr])
                    if temp is not None:
                        self.current_builder.call(self.rawstr_free, [temp])
                    return (I64, parsed)
                return (I64, ir.const_(ir.IntType(64), 0))

            if func_name == "int" and len(args_node) == 2:
                # int(text, base): strtol with an explicit radix
                arg_tv = self._convert_node(args_node[0])
                base_tv = self._coerce(self._convert_node(args_node[1]), I64)
                raw_ptr, temp = self._rawstr_operand(arg_tv)
                cstr = self.current_builder.call(self.rawstr_to_cstr, [raw_ptr])
                end_ptr = self.current_builder.alloca(
                    ir.PointerType(ir.IntType(8)), None, 'iend2'
                )
                base_i32 = self.current_builder.trunc(base_tv[1], ir.IntType(32))
                parsed = self.current_builder.call(
                    self.strtol, [cstr, end_ptr, base_i32]
                )
                end_val = self.current_builder.load(end_ptr)
                moved = self.current_builder.icmp_signed("!=", end_val, cstr)
                if self.checks:
                    self._panic_if(
                        self.current_builder.not_(moved),
                        "ValueError: invalid literal for int()",
                    )
                self.current_builder.call(self.free, [cstr])
                if temp is not None:
                    self.current_builder.call(self.rawstr_free, [temp])
                return (I64, parsed)

            if func_name == "len":
                if args_node:
                    arg_tv = self._borrowed_field_str(args_node[0], None)
                    if arg_tv is None:
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
                                        ir.const_(ir.IntType(32), 0),
                                        ir.const_(ir.IntType(32), 0),
                                    ],
                                )
                            ),
                        )
                    if arg_tv[0] == RAWSTR:
                        # raw string: len() counts code points (field 3)
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
                                        ir.const_(ir.IntType(32), 0),
                                        ir.const_(ir.IntType(32), 3),
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
                            self.create_int, [ir.const_(ir.IntType(64), 0)]
                        ),
                    )
                return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

            if func_name == "sum":
                if args_node:
                    boxed = self._box(self._convert_node(args_node[0]))
                    if boxed is not None:
                        return (
                            OBJ,
                            self.current_builder.call(self.list_sum, [boxed]),
                        )
                return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

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
                        self.create_int, [ir.const_(ir.IntType(64), 0)]
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
                    ir.const_(
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
                raise NotImplementedError(
                    f"call to '{func_name}' with {len(args_node)} args "
                    f"(expected {len(func.args)})"
                )

        # unknown callee: fail at compile time. A silent null leaks into
        # containers and crashes far from its origin at runtime.
        callee_desc = (
            func_node[1]
            if isinstance(func_node, (list, tuple))
            and len(func_node) >= 2
            and func_node[0] == "name"
            else str(func_node)
        )
        raise NotImplementedError(f"call to unknown function '{callee_desc}'")
