"""The call-expression compiler of TypedCodegen.

Split out of silu/typed_codegen.py (module step C, part 2): the
single dispatch for every call shape - static/dynamic/funcref/
extern-C/builtin/method. tools/flatten_codegen.py splices this
block back at its historical position (the end of the class), so
the flattened output stays byte-identical.
"""

from typing import Any, Tuple

from silu.ir_iface import ir
from silu.typed_helpers import (
    F64, I1, I64, INSTANCE, JSON, JSON_TAG_STR, JSON_TAG_LIST, JSON_TAG_DICT, LLVM_KIND_TYPES, OBJ, RAWCHAR_VIEW, RAWDICT_KINDS, RAWDICT_STR_KINDS, RAWLIST_KINDS, RAWLIST_S, RAWSTR, _inst_kind, _is_inst, _rawdict_call_fn, _rawstr_load_data, _rawstr_load_len, _twin_utf8_len, _type_ret, _type_text,
)


class TypedCallMixin:

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
            _r = self._call_method(func_node, args_node)
            if _r is not None:
                return _r

        if (
            isinstance(func_node, list)
            and len(func_node) >= 2
            and func_node[0] == "name"
        ):
            _r = self._call_named(func_node, args_node, node)
            if _r is not None:
                return _r

        if (
            isinstance(func_node, (list, tuple))
            and len(func_node) >= 2
            and func_node[0] == "name"
            and func_node[1] in self.variables
            and self.var_kinds.get(func_node[1]) == OBJ
            and len(args_node) >= 1
        ):
            return self._call_obj_var(func_node, args_node)

        if (
            isinstance(func_node, (list, tuple))
            and len(func_node) >= 2
            and func_node[0] == "name"
            and func_node[1] in ("list", "dict", "set", "tuple")
        ):
            return self._call_container(func_node, args_node)
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

    def _call_method(self, func_node, args_node):
        method_name = func_node[2]
        raw_obj_tv = self._convert_node(func_node[1])
        raw_kind = raw_obj_tv[0]
        if _is_inst(raw_kind) or (
            raw_kind == I64
            and self._class_of_node(func_node[1]) is not None
        ):
            # an instance-list element rides as an i64 word but
            # still has a resolvable class - the method-call
            # emitter coerces self to the callee's ABI
            return self._emit_method_call(
                func_node[1], method_name, args_node
            )
        if raw_kind in RAWLIST_KINDS:
            elem_kind = RAWLIST_KINDS[raw_kind]
            list_ptr = raw_obj_tv[1]
            if method_name == "append" and args_node:
                arg_tv = self._convert_node(args_node[0])
                if _is_inst(arg_tv[0]):
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
                    if elem_kind == JSON:
                        # tagged blocks ride the slots as pointer bits
                        elem_bits = self.current_builder.ptrtoint(
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
            "index": (self.list_index, 1, True),
            "add": (self.pyobj_set_add, 1, False),
            "discard": (self.pyobj_set_discard, 1, False),
            "items": (self.dict_items_rt, 0, True),
            "join": (self.str_join_boxed, 1, True),
            "keys": (self.dict_keys_rt, 0, True),
            "values": (self.dict_values_rt, 0, True),
            "update": (self.pyobj_update_dispatch, 1, False),
            "setdefault": (self.dict_setdefault, 2, True),
            "copy": (self.pyobj_copy_dispatch, 0, True),
            "clear": (self.pyobj_clear, 0, False),
            "upper": (self.str_upper, 0, True),
            "lower": (self.str_lower, 0, True),
            "isdigit": (self.str_isdigit, 0, True),
            "isalpha": (self.str_isalpha, 0, True),
            "isspace": (self.str_isspace, 0, True),
            "find": (self.str_find, 1, True),
            "startswith": (self.boxed_affix["str_starts_with"], 1, False),
            "endswith": (self.boxed_affix["str_ends_with"], 1, False),
            "rfind": (self.str_rfind, 1, True),
            "get": (self.dict_get_or, 2, True),
            "pop": (self.pyobj_pop_dispatch, 1, True),
            "__getitem__": (self.dict_get_or, 2, True),
            "__setitem__": (self.dict_set, 2, False),
            "__delitem__": (self.dict_pop, 1, False),
        }
        entry = method_map.get(method_name)
        user_method = self._dyn_member_classes(method_name, True)
        if obj is not None and entry and not user_method:
            func, arg_count, has_result = entry
            arg_vals = []
            for arg in args_node[:arg_count]:
                arg_tv = self._convert_node(arg)
                arg_vals.append(self._box(arg_tv))
            while len(arg_vals) < arg_count:
                arg_vals.append(
                    ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
                )
            if len(arg_vals) == arg_count and all(arg_vals):
                result = self.current_builder.call(func, [obj] + arg_vals)
                # box scalar results: several map entries (startswith,
                # isdigit...) return i1/i64 raw, and the consumer
                # treats the tv as a dynamic value
                ret_ty = _type_ret(func.ftype)
                if ret_ty is None:
                    ret_ty = func.ftype.ret
                if ret_ty is not None and ret_ty != self.pyobj.pyobj_type:
                    if str(ret_ty) == "i1" or _type_text(ret_ty) == "i1":
                        result = self.current_builder.call(
                            self.create_bool, [result]
                        )
                    elif str(ret_ty) == "i64" or _type_text(ret_ty) == "i64":
                        result = self.current_builder.call(
                            self.create_int, [result]
                        )
                    elif str(ret_ty) == "double" or _type_text(ret_ty) == "double":
                        result = self.current_builder.call(
                            self.create_float, [result]
                        )
                return (OBJ, result) if has_result else (OBJ, result)
        # boxed instance receiver with user-class methods: class-id
        # dispatch into the compiled methods; a same-named builtin
        # shim is the fallback arm for non-instance receivers
        if user_method:
            return self._emit_dyn_method_call(
                raw_obj_tv, method_name, args_node,
                (entry, obj) if entry else None,
            )
        raise NotImplementedError(
            f"method '{method_name}' is not supported on dynamic values"
        )

    def _call_named(self, func_node, args_node, node):
        func_name = func_node[1]

        if func_name in self._c_externs:
            return self._emit_c_extern_call(
                self._c_externs[func_name], args_node
            )
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
                elif kind == RAWSTR and arg_tv[0] == RAWSTR:
                    # borrow, not copy (see the method-call site)
                    raw_args.append(arg_tv[1])
                else:
                    raw_args.append(self._coerce(arg_tv, kind)[1])
            call = self.current_builder.call(fn, raw_args)
            if ret_kind == INSTANCE:
                cls = self._call_ret_class.get(mangled)
                return (_inst_kind(cls) if cls else INSTANCE, call)
            return (ret_kind, call)

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
                    # print specialisation: a statically-typed scalar
                    # or string renders straight through printf /
                    # float_repr - no box, no pyobj_print (the only
                    # pyobj reference fully static programs had)
                    if (
                        isinstance(arg_node, (list, tuple))
                        and len(arg_node) >= 2
                        and arg_node[0] == "const"
                        and isinstance(arg_node[1], str)
                    ):
                        # a string LITERAL prints straight out of its
                        # global - no create_str box at all
                        data = self._create_global_string(arg_node[1])
                        fmt = self._create_global_string("%.*s")
                        self.current_builder.call(
                            self.printf,
                            [fmt,
                             ir.const_(
                                 ir.IntType(64),
                                 _twin_utf8_len(arg_node[1]),
                             ),
                             data],
                        )
                        continue
                    arg_tv = self._convert_node(arg_node)
                    b = self.current_builder
                    printed = False
                    if arg_tv[0] == I64:
                        fmt = self._create_global_string("%lld")
                        b.call(self.printf, [fmt, arg_tv[1]])
                        printed = True
                    elif arg_tv[0] == F64:
                        # floats render through float_repr (shortest
                        # round-trip + ".0" fixup) - the same runtime
                        # call the boxed path uses, byte-identical
                        rep = b.call(self.float_repr, [arg_tv[1]])
                        fmt = self._create_global_string("%s")
                        b.call(self.printf, [fmt, rep])
                        printed = True
                    elif arg_tv[0] == I1:
                        if (
                            isinstance(arg_node, (list, tuple))
                            and len(arg_node) >= 2
                            and arg_node[0] == "const"
                            and isinstance(arg_node[1], bool)
                        ):
                            fmt = self._create_global_string(
                                "True" if arg_node[1] else "False"
                            )
                            b.call(self.printf, [fmt])
                        else:
                            t_str = self._create_global_string("True")
                            f_str = self._create_global_string("False")
                            chosen = b.select(arg_tv[1], t_str, f_str)
                            fmt = self._create_global_string("%s")
                            b.call(self.printf, [fmt, chosen])
                        printed = True
                    elif arg_tv[0] == RAWSTR:
                        # {len, cap, data, cp}: print by (byte len,
                        # data) exactly like the boxed %.*s path
                        sc = b.bitcast(
                            arg_tv[1],
                            ir.PointerType(self.rawstr_struct_type), "",
                        )
                        i0 = ir.const_(ir.IntType(32), 0)
                        i2 = ir.const_(ir.IntType(32), 2)
                        len_slot = b.gep(sc, [i0, i0], "")
                        slen = b.load(len_slot, "")
                        dat_slot = b.gep(sc, [i0, i2], "")
                        sdata = b.load(dat_slot, "")
                        fmt = self._create_global_string("%.*s")
                        sl64 = b.sext(slen, ir.IntType(64), "")
                        b.call(self.printf, [fmt, sl64, sdata])
                        printed = True
                    if not printed:
                        boxed = self._box(arg_tv)
                        if boxed is not None:
                            b.call(self.pyobj_print, [boxed])
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
            if arg_tv[0] == OBJ:
                return self._convert_obj_number(arg_tv, True)
            if arg_tv[0] in (RAWSTR, RAWCHAR_VIEW):
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
            if arg_tv[0] == OBJ:
                return self._convert_obj_number(arg_tv, False)
            if arg_tv[0] in (RAWSTR, RAWCHAR_VIEW):
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

        if func_name == "json_tag" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            tag = self.current_builder.call(self.tagged_tag, [jv])
            return (I64, self.current_builder.sext(tag, ir.IntType(64)))
        if func_name == "json_free" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            self.current_builder.call(
                self.tagged_free,
                [
                    jv,
                    ir.const_(ir.IntType(32), JSON_TAG_STR),
                    ir.const_(ir.IntType(32), JSON_TAG_LIST),
                    ir.const_(ir.IntType(32), JSON_TAG_DICT),
                ],
            )
            return (I64, ir.const_(ir.IntType(64), 0))
        if func_name == "json_int" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            return (I64, self.current_builder.call(self.json_unwrap_int, [jv]))
        if func_name == "json_float" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            return (F64, self.current_builder.call(self.json_unwrap_float, [jv]))
        if func_name == "json_bool" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            return (I1, self.current_builder.call(self.json_unwrap_bool, [jv]))
        if func_name == "json_str" and len(args_node) == 1:
            jv = self._coerce(self._convert_node(args_node[0]), JSON)[1]
            borrowed = self.current_builder.call(self.json_unwrap_str, [jv])
            return (RAWSTR, self.current_builder.call(self.rawstr_copy, [borrowed]))
        if func_name == "bool" and len(args_node) == 1:
            return self._convert_node(
                ["call", ["name", "_builtin_bool"], [args_node[0]], []]
            )
        if func_name == "repr" and len(args_node) == 1:
            return self._convert_node(args_node[0])
        # set(...) falls through to the general constructor branch
        # (tag-8 box, construction dedup, real copy)
        if func_name == "all" and len(args_node) == 1:
            # iterate boxed elements, AND their truthiness
            return self._convert_node(
                ["call", ["name", "_builtin_all"],
                 [args_node[0]], []]
            )
        if func_name == "sorted" and len(args_node) == 1:
            return self._convert_node(
                ["call", ["name", "_builtin_sorted"],
                 [args_node[0]], []]
            )
        if func_name == "zip" and len(args_node) == 2:
            return self._convert_node(
                ["call", ["name", "_builtin_zip"],
                 [args_node[0], args_node[1]], []]
            )
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
                arg_tv = self._convert_node(arg_node)
                if kind == RAWSTR and arg_tv[0] == RAWSTR:
                    # borrow, not copy (the callee only reads)
                    raw_args.append(arg_tv[1])
                else:
                    raw_args.append(self._coerce(arg_tv, kind)[1])
            if len(raw_args) == len(param_kinds):
                call = self.current_builder.call(func, raw_args)
                if ret_kind == INSTANCE:
                    # instance returns carry their class into the box
                    cls = self._call_ret_class.get(func_name)
                    return (_inst_kind(cls) if cls else INSTANCE, call)
                return (ret_kind, call)
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
            writebacks = []
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
                elif expected == RAWSTR and arg_tv[0] == RAWSTR:
                    # borrow, not copy: the callee treats str params
                    # as read-only (a += rebinds via concat)
                    boxed_args.append(arg_tv[1])
                else:
                    # proven raw scalar/str parameter: coerce in place
                    # (str coercion copies at the boundary)
                    boxed_args.append(
                        self._coerce(arg_tv, expected)[1]
                    )
                if expected == OBJ and arg_tv[0] in RAWLIST_KINDS:
                    before_len = self.current_builder.call(
                        self.rawlist_len, [arg_tv[1]]
                    )
                    writebacks.append(
                        (arg_node, boxed_args[-1], before_len)
                    )
            if len(boxed_args) == len(func.args):
                result = self.current_builder.call(func, boxed_args)
                for wb_node, wb_boxed, wb_len in writebacks:
                    self._rawlist_writeback(
                        wb_node, wb_boxed, self.current_builder, wb_len
                    )
                return (OBJ, result)
            raise NotImplementedError(
                f"call to '{func_name}' with {len(args_node)} args "
                f"(expected {len(func.args)})"
            )

    def _call_obj_var(self, func_node, args_node):
        # indirect call through a funcref local: dispatch via the
        # function table (arity from the call site)
        callee_name = func_node[1]
        fn_box = self.current_builder.load(self.variables[callee_name])
        arg_boxes = []
        for an in args_node:
            arg_boxes.append(self._box(self._convert_node(an)))
        result = self.current_builder.call(
            self._fn_call_dispatch(len(arg_boxes)),
            [fn_box] + arg_boxes,
        )
        return (OBJ, result)

    def _call_container(self, func_node, args_node):
        # constructor call over an iterable: a COPY into a fresh box
        # (Python's constructors copy; returning the same box would
        # alias the source and later mutations would corrupt
        # instructions already built from it)
        b = self.current_builder
        if args_node:
            src = self._box(self._convert_node(args_node[0]))
            is_set_ctor = func_node[1] == "set"
            out = (
                b.call(self.create_set, [])
                if is_set_ctor
                else b.call(self.create_list, [])
            )
            keys = b.call(self.pyobj_iter_keys, [src])
            idx_ptr = b.alloca(ir.IntType(64), None, "ctor_i")
            b.store(ir.const_(ir.IntType(64), 0), idx_ptr)
            cond = self.current_function.append_basic_block("ctor_cond")
            body = self.current_function.append_basic_block("ctor_body")
            done = self.current_function.append_basic_block("ctor_done")
            total = b.call(self.list_length, [keys])
            b.branch(cond)
            b.position_at_end(cond)
            cur = b.load(idx_ptr)
            b.cbranch(
                b.icmp_signed("<", cur, total), body, done
            )
            b.position_at_end(body)
            key = b.call(
                self.list_get, [keys, b.call(self.create_int, [cur])]
            )
            if func_node[1] == "dict":
                val = b.call(self.pyobj_subscript, [src, key])
                b.call(self.dict_set, [out, key, val])
            elif is_set_ctor:
                b.call(self.pyobj_set_add, [out, key])
            else:
                b.call(self.list_append, [out, key])
            b.store(b.add(cur, ir.const_(ir.IntType(64), 1)), idx_ptr)
            b.branch(cond)
            b.position_at_end(done)
            return (OBJ, out)
        # no-arg constructors: empty containers (all PyObj; sets
        # keep their tag-8 box)
        if func_node[1] == "dict":
            return self._convert_node(["dict", []])
        if func_node[1] == "set":
            return (OBJ, self.current_builder.call(self.create_set, []))
        return self._convert_node(["list", []])
