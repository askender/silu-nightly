# Leaf helpers and kind constants for the typed LLVM backend (split out
# of typed_codegen.py): stateless module-level functions over IR nodes and
# kind strings, the kind vocabulary, and the kind -> LLVM type table.
# tools/flatten_codegen.py inlines this file verbatim into the self-hosted
# converter, so everything here must stay in the dual-valid subset.

from typing import Any, Dict, List, Optional, Tuple  # noqa: F401 -
# Dict/List ride the star-export (dual-valid sources use them)

from silu.ir_iface import ir

__all__ = [
    "_dict_loop_names",
    "_target_mentions",
    "_node_rebinds",
    "_body_rebinds",
    "_comp_target_names",
    "_const_int_of",
    "_rawlist_elem_size",
    "_rawdict_call_fn",
    "_extract_i64_const",
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
    "BUF",
    "RAWSTR",
    "RAWCHAR_VIEW",
    "RAWLIST_S",
    "RAWLIST_KINDS",
    "JSON",
    "JSON_TAG_NULL",
    "JSON_TAG_INT",
    "JSON_TAG_FLOAT",
    "JSON_TAG_BOOL",
    "JSON_TAG_STR",
    "JSON_TAG_LIST",
    "JSON_TAG_DICT",
    "RAWLIST_JSON",
    "RAWDICT_SJ",
    "RAWDICT_SS",
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
    "_twin_utf8_len",
    "_RANGE_AS_VALUE",
    "_is_range_call",
    "_range_const_span",
    "_range_len",
    "_range_values",
    "_STR_REJECTED_METHODS",
    "_NONE_RESULT_METHODS",
    "_BUILTIN_ARITY",
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


def _target_mentions(target: Any, name: str) -> bool:
    """Does a binding target (a bare name, ["name", n], or a nested
    tuple_unpack of them) rebind `name`?"""
    if isinstance(target, str):
        return target == name
    if not isinstance(target, (list, tuple)):
        return False
    if len(target) >= 2 and target[0] == "name":
        return target[1] == name
    for part in target:
        if _target_mentions(part, name):
            return True
    return False


def _node_rebinds(node: Any, name: str) -> bool:
    if not isinstance(node, (list, tuple)) or not node:
        return False
    head = node[0]
    if head in ("assign", "ann_assign", "tuple_assign", "multi_assign"):
        if _target_mentions(node[1], name):
            return True
    elif head in ("aug_assign", "delete", "for", "with"):
        if _target_mentions(node[1], name):
            return True
    for child in node:
        if _node_rebinds(child, name):
            return True
    return False


def _body_rebinds(stmts: Any, name: str) -> bool:
    """True when anything in a loop body (nested statements included)
    rebinds `name`: plain, annotated, augmented or multiple assignment,
    tuple unpacking, a for/with target, or del. Conservative by design -
    a same-named local inside a nested def counts too. It decides
    whether a loop over the str bound to `name` must walk a snapshot:
    the rebind drops or grows the buffer under the walked pointer."""
    if not isinstance(stmts, (list, tuple)):
        return False
    for stmt in stmts:
        if _node_rebinds(stmt, name):
            return True
    return False


def _comp_target_names(generators: Any) -> list:
    """The names a comprehension's generators bind (a plain name or a
    tuple of names per generator), each once, in order."""
    names = []
    for gen in generators:
        if not isinstance(gen, (list, tuple)) or not gen:
            continue
        target = gen[0]
        if not isinstance(target, (list, tuple)) or not target:
            continue
        parts = target[1] if target[0] == "tuple" else (target,)
        for part in parts:
            if (
                isinstance(part, (list, tuple))
                and len(part) >= 2
                and part[0] == "name"
                and part[1] not in names
            ):
                names.append(part[1])
    return names


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


# range(...) OUTSIDE a for header. The old handler "degraded to the
# dynamic view" - it handed back the STOP VALUE as a boxed int - so
# len(range(10)) answered 0, list(range(3)) built [] and any other use
# silently meant something else. Two value forms are exact (folded from
# literal arguments, see _range_const_span); everything else is this.
_RANGE_AS_VALUE = (
    "range(...) as a value is only supported with literal arguments, as "
    "len(range(...)) or list(range(...)); use range(...) as the iterable "
    "of a for loop"
)


def _is_range_call(node: Any) -> bool:
    return (
        isinstance(node, list)
        and len(node) >= 3
        and node[0] == "call"
        and isinstance(node[1], list)
        and len(node[1]) >= 2
        and node[1][0] == "name"
        and node[1][1] == "range"
    )


def _range_const_span(call_node: Any):
    """[start, stop, step] of a range(...) call whose arguments are all
    compile-time ints, else None. Arity and step errors raise exactly as
    the for-loop form does."""
    args = call_node[2] if len(call_node) > 2 else []
    vals = []
    for a in args:
        v = _const_int_of(a)
        if v is None:
            return None
        vals.append(v)
    start = 0
    stop = 0
    step = 1
    if len(vals) == 1:
        stop = vals[0]
    elif len(vals) == 2:
        start = vals[0]
        stop = vals[1]
    elif len(vals) == 3:
        start = vals[0]
        stop = vals[1]
        step = vals[2]
    else:
        raise NotImplementedError(
            "range() takes 1 to 3 arguments, got " + str(len(vals)))
    if step == 0:
        raise ValueError("range() arg 3 must not be zero")
    return [start, stop, step]


def _range_len(start: int, stop: int, step: int) -> int:
    # number of values the span yields; ceil division per sign
    diff = stop - start
    if step > 0:
        n = (diff + step - 1) // step
    else:
        n = (diff + step + 1) // step
    if n < 0:
        n = 0
    return n


def _range_values(start: int, stop: int, step: int) -> list:
    out = []
    v = start
    if step > 0:
        while v < stop:
            out.append(v)
            v += step
    else:
        while v > stop:
            out.append(v)
            v += step
    return out


# Builtins the converter accepts with ANY number of arguments and then
# reads only the ones its emitter happens to use: len(1, 2) printed 0.
# name -> (least, most) positional arguments. Supported builtins only:
# an arity error for an unknown builtin would wrongly suggest it works.
_BUILTIN_ARITY = {
    "len": (1, 1), "chr": (1, 1), "ord": (1, 1),
    "input": (0, 0), "repr": (1, 1), "isinstance": (2, 2),
    "float": (1, 1), "str": (0, 1),
    "list": (0, 1), "tuple": (0, 1), "set": (0, 1),
    "sum": (1, 2),
}

# The boxed method map dispatches BY NAME ONLY. These are its container
# operations (list / dict / set): a STRING receiver that the typed rawstr
# arms did not handle must never reach them - `count` on a str went to
# list_count, which read the string box as a list and segfaulted.
# Boxed methods that mutate and answer None in Python. The boxed
# dispatch must hand back the None box for them, not the call's result:
# clear() is void (a stored void was invalid IR) and append() returned
# the list itself. Decided BY NAME: the table's `has_result` column is
# False for startswith/endswith too (they answer a raw i1 that gets
# boxed afterwards), so reading it as "no result" turned those into
# None and took the converter's own _is_inst (a startswith) down.
_NONE_RESULT_METHODS = (
    "clear", "add", "discard", "update", "append",
    "__setitem__", "__delitem__",
)

_STR_REJECTED_METHODS = (
    "append", "reverse", "insert", "add", "discard", "items", "keys",
    "values", "update", "setdefault", "copy", "clear", "get", "pop",
    "index", "__getitem__", "__setitem__", "__delitem__",
)


def _rawlist_elem_size(kind: str) -> int:
    return 8  # both i64 and double elements are 8 bytes


def _rawdict_call_fn(kind: str, int_fn: Any, str_fn: Any):
    return str_fn if kind in RAWDICT_STR_KINDS else int_fn


def _extract_i64_const(value: Any) -> Optional[int]:
    # NOT `isinstance(value.type, ir.IntType)`: the text layer's
    # IntType is a factory function, not a class, so that check raised
    # TypeError under SILU_LLVM_IR=text and took every `**` and every
    # `s * n` down with it. Both layers cache their type objects, so
    # the i64 type compares equal to itself (no getattr either: this
    # helper is compiled into the self-hosted converter).
    if isinstance(value, ir.Constant) and value.type == ir.IntType(64):
        return int(value.constant)
    return None


def _targets_parent(target_node, parent_names) -> bool:
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


def _all_name_parts(parts) -> bool:
    for part in parts:
        if not (
            isinstance(part, list) and len(part) >= 2 and part[0] == "name"
        ):
            return False
    return True


def _all_of_kind(kinds, want) -> bool:
    for k in kinds:
        if k != want:
            return False
    return True


def _all_non_obj(kinds) -> bool:
    for k in kinds:
        if k == OBJ:
            return False
    return True


def _all_str(names) -> bool:
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
# strbuf: the SAME rawstr header, but a REFERENCE-semantics mutable
# buffer (assignment/passing share the pointer, no copies); push()
# appends in place anywhere - the explicit contract the local
# `x = x + t` in-place window only approximates (see
# reference/P1_STRING_RESEARCH.md)
BUF = "strbuf"
# transient: a borrowed {i8* data, i64 seq} window into a parent
# rawstr (SSA struct value, no allocation). Lives inside one
# expression; any consumer needing an owned string coerces to
# RAWSTR (a copy).
RAWCHAR_VIEW = "rawchar_view"
RAWLIST_S = "rawlist_str"  # list[str]: slots own a copy of each element
JSON = "json"  # built-in sum type: one 16-byte {i32 tag, i64 payload}
# block (RFC docs/rfc_sum_types.md). Tag table (fixed, built-in):
# 0=null 1=int 2=float 3=bool 4=str 5=list 6=dict
JSON_TAG_NULL = 0
JSON_TAG_INT = 1
JSON_TAG_FLOAT = 2
JSON_TAG_BOOL = 3
JSON_TAG_STR = 4
JSON_TAG_LIST = 5
JSON_TAG_DICT = 6
RAWLIST_JSON = "rawlist_json"  # list[Json]: slots own the blocks
RAWLIST_KINDS = {
    RAWLIST_I: I64,
    RAWLIST_F: F64,
    RAWLIST_S: RAWSTR,
    RAWLIST_JSON: JSON,
}
RAWDICT_II = "rawdict_ii"  # dict[int, int]: machine-word open addressing
RAWDICT_IF = "rawdict_if"  # dict[int, float] (values as f64 bit patterns)
RAWDICT_SI = "rawdict_si"  # dict[str, int]: same table, rawstr keys
RAWDICT_SF = "rawdict_sf"  # dict[str, float]
RAWDICT_SJ = "rawdict_sj"  # dict[str, Json]: str keys, tagged values
RAWDICT_SS = "rawdict_ss"  # dict[str, str]: str keys, rawstr-pointer values
RAWDICT_KINDS = {
    RAWDICT_II: I64,
    RAWDICT_IF: F64,
    RAWDICT_SI: I64,
    RAWDICT_SF: F64,
    RAWDICT_SJ: JSON,
    RAWDICT_SS: RAWSTR,
}  # kind -> value kind
RAWDICT_STR_KINDS = (RAWDICT_SI, RAWDICT_SF, RAWDICT_SJ, RAWDICT_SS)  # kinds with rawstr keys
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
RAW_STORAGE_KINDS[JSON] = JSON  # tagged block pointer, null-initialized
RAW_STORAGE_KINDS[RAWDICT_SJ] = RAWDICT_SJ
RAW_STORAGE_KINDS[RAWDICT_SS] = RAWDICT_SS
RAW_STORAGE_KINDS[BUF] = BUF  # i8* slot like rawstr
LLVM_KIND_TYPES = {
    I64: ir.IntType(64),
    F64: ir.DoubleType(),
    I1: ir.IntType(1),
    RAWSTR: ir.PointerType(ir.IntType(8)),  # rawstr passes as i8* in ABIs
    BUF: ir.PointerType(ir.IntType(8)),  # strbuf: same header, shared ref
    RAWLIST_I: ir.PointerType(ir.IntType(8)),
    RAWLIST_F: ir.PointerType(ir.IntType(8)),
    RAWLIST_S: ir.PointerType(ir.IntType(8)),
    RAWLIST_JSON: ir.PointerType(ir.IntType(8)),
    JSON: ir.PointerType(ir.IntType(8)),  # tagged block pointer
    RAWDICT_SJ: ir.PointerType(ir.IntType(8)),
    RAWDICT_II: ir.PointerType(ir.IntType(8)),
    RAWDICT_IF: ir.PointerType(ir.IntType(8)),
    RAWDICT_SI: ir.PointerType(ir.IntType(8)),
    RAWDICT_SF: ir.PointerType(ir.IntType(8)),
    RAWDICT_SS: ir.PointerType(ir.IntType(8)),  # dict[str, str] as a param
    INSTANCE: ir.PointerType(ir.IntType(8)),
}


def _inst_kind(cls):
    """INSTANCE kind carrying its class. Box dispatch reads the cid
    from the kind, so class identity survives the value's whole
    compile-time lifetime - loads, call results and parameters - not
    just the construction site."""
    return INSTANCE + ":" + cls


def _is_inst(kind) -> bool:
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



def _twin_utf8_len(s):
    """UTF-8 byte length, computed in the dual-valid subset (no str
    .encode, no twin-module attribute): 1 byte for ASCII, the UTF-8
    leading-byte ranges give 2/3/4 otherwise - the same table the
    twin's utf8_len uses."""
    n = 0
    for ch in s:
        o = ord(ch)
        if o < 0x80:
            n += 1
        elif o < 0x800:
            n += 2
        elif o < 0x10000:
            n += 3
        else:
            n += 4
    return n
