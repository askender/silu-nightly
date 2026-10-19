# Leaf helpers and kind constants for the typed LLVM backend (split out
# of typed_codegen.py): stateless module-level functions over IR nodes and
# kind strings, the kind vocabulary, and the kind -> LLVM type table.
# tools/flatten_codegen.py inlines this file verbatim into the self-hosted
# converter, so everything here must stay in the dual-valid subset.

from typing import Any, Dict, List, Optional, Tuple

from silu.ir_iface import ir

__all__ = [
    "_dict_loop_names",
    "_const_int_of",
    "_rawlist_elem_size",
    "_rawdict_call_fn",
    "_extract_i64_const",
    "_kind_of_llvm_type",
    "_targets_parent",
    "_all_name_parts",
    "_all_of_kind",
    "_all_non_obj",
    "_all_str",
    "_non_obj_param_env",
    "_clamp_str_bound",
    "_is_ws_byte",
    "_pred_digit",
    "_pred_alpha",
    "_load_byte",
    "_chr_store",
    "_struct_gep",
    "_rawstr_load_len",
    "_rawstr_load_data",
    "_rawstr_load_cp",
    "I64",
    "F64",
    "I1",
    "OBJ",
    "_type_text",
    "_type_ret",
    "ANNOTATION_KINDS",
    "RAWLIST_I",
    "RAWLIST_F",
    "RAWSTR",
    "RAWCHAR_VIEW",
    "RAWLIST_S",
    "RAWLIST_KINDS",
    "RAWDICT_II",
    "RAWDICT_IF",
    "RAWDICT_SI",
    "RAWDICT_SF",
    "RAWDICT_KINDS",
    "RAWDICT_STR_KINDS",
    "INSTANCE",
    "RAW_STORAGE_KINDS",
    "LLVM_KIND_TYPES",
    "_inst_kind",
    "_is_inst",
    "_kind_cls",
    "_kind_llvm_key",
]



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

def _type_text(t):
    txt = getattr(t, "text", None)
    if txt is not None:
        return txt
    return str(t)


def _type_ret(ftype):
    return getattr(ftype, "return_type", None)


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


def _inst_kind(cls):
    """INSTANCE kind carrying its class. Box dispatch reads the cid
    from the kind, so class identity survives the value's whole
    compile-time lifetime - loads, call results and parameters - not
    just the construction site."""
    return INSTANCE + ":" + cls


def _is_inst(kind):
    if not isinstance(kind, str):
        return False
    return kind == INSTANCE or kind.startswith(INSTANCE + ":")


def _kind_cls(kind):
    """The class of an instance kind, None for plain/other kinds."""
    if isinstance(kind, str) and kind.startswith(INSTANCE + ":"):
        return kind[len(INSTANCE) + 1:]
    return None


def _kind_llvm_key(kind):
    """LLVM_KIND_TYPES key for a possibly classed instance kind."""
    return INSTANCE if _is_inst(kind) else kind

