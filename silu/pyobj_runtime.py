"""The pyobj runtime-emission methods of SiluToLLVMConverter.

Split out of silu_ir_to_llvm.py (module step A of the modularization
plan): every method that BUILDS the pyobj runtime functions of the
output module lives here as a mixin. tools/flatten_codegen.py splices
these method blocks into the flattened single class in this file's
definition order, so the flattened output stays byte-identical - the
acceptance gate is the fixed-point test.

Every method here runs at converter-build time (before any user
statement converts) and only touches self attributes introduced by
SiluToLLVMConverter.__init__.
"""


from silu.ir_iface import ir
from silu.silu_ir_to_llvm import (
    _is_numeric_tag,
    _dict_field,
    _py_mod_apply,
    _floor_div_apply,
)


class PyobjRuntimeMixin:
    def _create_pyobj_constructors(self):
        """Create PyObject constructor functions."""

        # PyObject* create_int(i64 value)
        create_int_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.IntType(64)], False
        )
        self.create_int = ir.func_(self.module, create_int_ty, 'create_int')

        block = self.create_int.append_basic_block("entry")
        builder = ir.builder_(block)

        # Allocate PyObject
        obj_ptr = builder.call(
            self.malloc, [ir.const_(ir.IntType(64), 16)]
        )  # sizeof(PyObject)
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 0 (int)
        tag_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        builder.store(ir.const_(ir.IntType(32), 0), tag_ptr)

        # Allocate and store integer value
        data_ptr = builder.call(
            self.malloc, [ir.const_(ir.IntType(64), 8)]
        )  # sizeof(i64)
        data_i64 = builder.bitcast(data_ptr, ir.PointerType(ir.IntType(64)))
        builder.store(self.create_int.args[0], data_i64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

        # PyObject* create_str(i8* str, i32 len)
        create_str_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [ir.PointerType(ir.IntType(8)), ir.IntType(32)], False,
        )
        self.create_str = ir.func_(self.module, create_str_ty, 'create_str')

        block = self.create_str.append_basic_block("entry")
        builder = ir.builder_(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 2 (string)
        tag_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        builder.store(ir.const_(ir.IntType(32), 2), tag_ptr)

        # Allocate string struct
        str_ptr = builder.call(
            self.malloc, [ir.const_(ir.IntType(64), 16)]
        )  # sizeof(string_type)
        str_struct = builder.bitcast(str_ptr, ir.PointerType(self.pyobj.string_type))

        # Store length
        len_ptr = builder.gep(
            str_struct, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        builder.store(self.create_str.args[1], len_ptr)

        # Store chars pointer
        chars_ptr = builder.gep(
            str_struct, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        builder.store(self.create_str.args[0], chars_ptr)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        builder.store(str_ptr, data_ptr_field)

        builder.ret(obj)

        # P5: the two immortal bool singleton boxes. Every boolean in
        # the program IS one of these (create_bool hands them out), so
        # `x is True` compiles to a single pointer compare. The tag-3
        # payload is private and never written after init, so sharing
        # is safe. NOTE for any future recursive pyobj release: tag-3
        # boxes are singletons and MUST be exempt from free.
        # (Written out twice instead of a loop: Silu classes reject
        # setattr-created fields, so the flattened twin cannot do
        # `setattr(self, name, ...)`.)
        i8p_ty = ir.PointerType(ir.IntType(8))
        i64_ty = ir.IntType(64)
        pyobj_ty = self.pyobj.pyobj_type

        true_payload = ir.gvar_(self.module, i64_ty, "silu_true_payload")
        true_payload.global_constant = True
        true_payload.initializer = ir.const_(i64_ty, 1)
        self.silu_true = ir.gvar_(self.module, pyobj_ty, "silu_true")
        self.silu_true.global_constant = True
        self.silu_true.initializer = ir.const_(pyobj_ty, [
            ir.const_(ir.IntType(32), 3),
            ir.gv_const_bitcast(true_payload, i8p_ty),
        ])

        false_payload = ir.gvar_(self.module, i64_ty, "silu_false_payload")
        false_payload.global_constant = True
        false_payload.initializer = ir.const_(i64_ty, 0)
        self.silu_false = ir.gvar_(self.module, pyobj_ty, "silu_false")
        self.silu_false.global_constant = True
        self.silu_false.initializer = ir.const_(pyobj_ty, [
            ir.const_(ir.IntType(32), 3),
            ir.gv_const_bitcast(false_payload, i8p_ty),
        ])

        # PyObject* create_bool(i1 value) - returns the singleton
        create_bool_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.IntType(1)], False
        )
        self.create_bool = ir.func_(self.module, create_bool_ty, 'create_bool')

        block = self.create_bool.append_basic_block("entry")
        builder = ir.builder_(block)

        builder.ret(builder.select(
            self.create_bool.args[0], self.silu_true, self.silu_false
        ))

        # PyObject* create_float(double value)
        create_float_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.DoubleType()], False
        )
        self.create_float = ir.func_(
            self.module, create_float_ty, 'create_float'
        )

        block = self.create_float.append_basic_block("entry")
        builder = ir.builder_(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 1 (float)
        tag_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        builder.store(ir.const_(ir.IntType(32), 1), tag_ptr)

        # Allocate and store the double value
        data_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 8)])
        data_f64 = builder.bitcast(data_ptr, ir.PointerType(ir.DoubleType()))
        builder.store(self.create_float.args[0], data_f64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

        # PyObject* create_list() - tag 4, data -> list struct
        # (created here so pyobj_add's list concatenation can reference it)
        self.create_list = ir.func_(
            self.module,
            ir.FunctionType(ir.PointerType(self.pyobj.pyobj_type), [], False), 'create_list',

        )
        builder = ir.builder_(self.create_list.append_basic_block("entry"))
        obj_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))
        builder.store(
            ir.const_(ir.IntType(32), 4),
            builder.gep(
                obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
            ),
        )
        list_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 24)])
        list_struct_ptr = builder.bitcast(
            list_ptr, ir.PointerType(self.list_struct_type)
        )
        zero32 = ir.const_(ir.IntType(32), 0)
        builder.store(
            ir.const_(ir.IntType(64), 0),
            builder.gep(list_struct_ptr, [zero32, zero32]),
        )
        builder.store(
            ir.const_(ir.IntType(64), 0),
            builder.gep(list_struct_ptr, [zero32, ir.const_(ir.IntType(32), 1)]),
        )
        builder.store(
            ir.const_(ir.PointerType(ir.PointerType(self.pyobj.pyobj_type)), None),
            builder.gep(list_struct_ptr, [zero32, ir.const_(ir.IntType(32), 2)]),
        )
        builder.store(
            list_ptr, builder.gep(obj, [zero32, ir.const_(ir.IntType(32), 1)])
        )
        builder.ret(obj)

    def _create_pyobj_operations(self):
        """Create PyObject operation functions."""

        # PyObject* pyobj_add(PyObject* left, PyObject* right)
        add_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ], False,
        )
        self.pyobj_add = ir.func_(self.module, add_ty, 'pyobj_add')

        block = self.pyobj_add.append_basic_block("entry")
        builder = ir.builder_(block)

        left, right = self.pyobj_add.args

        # Get type tags
        left_tag_ptr = builder.gep(
            left, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        right_tag_ptr = builder.gep(
            right, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        left_tag = builder.load(left_tag_ptr)
        right_tag = builder.load(right_tag_ptr)

        # Ints, bools and floats take the numeric path (bool coerces to int)
        both_numeric_cond = builder.and_(
            _is_numeric_tag(builder, left_tag),
            _is_numeric_tag(builder, right_tag),
        )

        float_check_block = self.pyobj_add.append_basic_block("float_check")
        str_check_block = self.pyobj_add.append_basic_block("str_check")
        str_concat_block = self.pyobj_add.append_basic_block("str_concat")
        error_block = self.pyobj_add.append_basic_block("error")
        builder.cbranch(both_numeric_cond, float_check_block, str_check_block)

        # Any float operand promotes the result to float (Python semantics)
        builder.position_at_end(float_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 1)),
        )
        int_block = self.pyobj_add.append_basic_block("int_add")
        float_add_block = self.pyobj_add.append_basic_block("float_add")
        builder.cbranch(either_float, float_add_block, int_block)

        # Float addition
        builder.position_at_end(float_add_block)
        left_double = self._load_number_as_f64(builder, left)
        right_double = self._load_number_as_f64(builder, right)
        float_result = builder.call(
            self.create_float, [builder.fadd(left_double, right_double)]
        )
        builder.ret(float_result)

        # Integer addition
        builder.position_at_end(int_block)

        # Get integer values
        left_data_ptr = builder.gep(
            left, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        right_data_ptr = builder.gep(
            right, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        left_data = builder.load(left_data_ptr)
        right_data = builder.load(right_data_ptr)
        left_i64_ptr = builder.bitcast(left_data, ir.PointerType(ir.IntType(64)))
        right_i64_ptr = builder.bitcast(right_data, ir.PointerType(ir.IntType(64)))
        left_val = builder.load(left_i64_ptr)
        right_val = builder.load(right_i64_ptr)

        # Add values with overflow detection
        overflow_result = builder.call(self.sadd_overflow, [left_val, right_val])

        # Extract sum and overflow flag
        sum_val = builder.extract_value(overflow_result, 0)
        overflow_flag = builder.extract_value(overflow_result, 1)

        # Check for overflow
        overflow_block = self.pyobj_add.append_basic_block("overflow")
        success_block = self.pyobj_add.append_basic_block("success")
        builder.cbranch(overflow_flag, overflow_block, success_block)

        # Overflow case - print error and exit
        builder.position_at_end(overflow_block)
        error_msg = self._create_global_string_with_builder(
            "Error: Integer overflow in addition", builder
        )
        self._emit_panic(builder, error_msg)

        # Success case - return result
        builder.position_at_end(success_block)
        result_obj = builder.call(self.create_int, [sum_val])
        builder.ret(result_obj)

        # String check: both operands strings -> concatenation
        builder.position_at_end(str_check_block)
        both_str_cond = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 2)),
            builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 2)),
        )
        list_check_block = self.pyobj_add.append_basic_block("list_check")
        builder.cbranch(both_str_cond, str_concat_block, list_check_block)

        # List check: both operands lists -> concatenation
        builder.position_at_end(list_check_block)
        both_list_cond = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 4)),
            builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 4)),
        )
        list_concat_block = self.pyobj_add.append_basic_block("list_concat")
        builder.cbranch(both_list_cond, list_concat_block, error_block)

        # List concatenation: new list with copies of both item arrays
        builder.position_at_end(list_concat_block)
        left_struct = self._load_list_struct(builder, left)
        right_struct = self._load_list_struct(builder, right)
        i64t = ir.IntType(64)
        zero64c = ir.const_(i64t, 0)
        zero32l = ir.const_(ir.IntType(32), 0)
        one32l = ir.const_(ir.IntType(32), 1)
        two32l = ir.const_(ir.IntType(32), 2)
        left_len_l = builder.load(builder.gep(left_struct, [zero32l, zero32l]))
        right_len_l = builder.load(builder.gep(right_struct, [zero32l, zero32l]))
        left_items_l = builder.load(builder.gep(left_struct, [zero32l, two32l]))
        right_items_l = builder.load(builder.gep(right_struct, [zero32l, two32l]))
        total_l = builder.add(left_len_l, right_len_l)
        new_list_l = builder.call(self.create_list, [])
        new_struct_l = self._load_list_struct(builder, new_list_l)
        concat_buf = builder.call(
            self.malloc, [builder.mul(total_l, ir.const_(i64t, 8))]
        )
        left_has_items = builder.icmp_signed(">", left_len_l, zero64c)
        copy_left_block = self.pyobj_add.append_basic_block("concat_copy_left")
        after_left_block = self.pyobj_add.append_basic_block("concat_after_left")
        builder.cbranch(left_has_items, copy_left_block, after_left_block)

        builder.position_at_end(copy_left_block)
        builder.call(
            self.memcpy,
            [
                concat_buf,
                builder.bitcast(left_items_l, ir.PointerType(ir.IntType(8))),
                builder.mul(left_len_l, ir.const_(i64t, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.branch(after_left_block)

        builder.position_at_end(after_left_block)
        right_has_items = builder.icmp_signed(">", right_len_l, zero64c)
        copy_right_block = self.pyobj_add.append_basic_block("concat_copy_right")
        after_right_block = self.pyobj_add.append_basic_block("concat_after_right")
        builder.cbranch(right_has_items, copy_right_block, after_right_block)

        builder.position_at_end(copy_right_block)
        right_dest = builder.gep(
            concat_buf, [builder.mul(left_len_l, ir.const_(i64t, 8))]
        )
        builder.call(
            self.memcpy,
            [
                right_dest,
                builder.bitcast(right_items_l, ir.PointerType(ir.IntType(8))),
                builder.mul(right_len_l, ir.const_(i64t, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.branch(after_right_block)

        builder.position_at_end(after_right_block)
        builder.store(total_l, builder.gep(new_struct_l, [zero32l, zero32l]))
        builder.store(total_l, builder.gep(new_struct_l, [zero32l, one32l]))
        builder.store(
            builder.bitcast(
                concat_buf, ir.PointerType(ir.PointerType(self.pyobj.pyobj_type))
            ),
            builder.gep(new_struct_l, [zero32l, two32l]),
        )
        builder.ret(new_list_l)

        # String concatenation: malloc new buffer, copy both, null-terminate
        builder.position_at_end(str_concat_block)
        zero32 = ir.const_(ir.IntType(32), 0)
        one32 = ir.const_(ir.IntType(32), 1)

        left_len, left_chars = self._pyobj_string_parts(builder, left, zero32, one32)
        right_len, right_chars = self._pyobj_string_parts(builder, right, zero32, one32)
        left_len64 = builder.zext(left_len, ir.IntType(64))
        right_len64 = builder.zext(right_len, ir.IntType(64))
        total_len = builder.add(left_len64, right_len64)

        buf = builder.call(
            self.malloc,
            [builder.add(total_len, ir.const_(ir.IntType(64), 1))],
        )
        false_flag = ir.const_(ir.IntType(1), 0)
        builder.call(self.memcpy, [buf, left_chars, left_len64, false_flag])
        buf_offset = builder.gep(buf, [left_len64])
        builder.call(self.memcpy, [buf_offset, right_chars, right_len64, false_flag])
        null_pos = builder.gep(buf, [total_len])
        builder.store(ir.const_(ir.IntType(8), 0), null_pos)

        concat_obj = builder.call(
            self.create_str, [buf, builder.trunc(total_len, ir.IntType(32))]
        )
        builder.ret(concat_obj)

        # type mismatch on +: Python raises TypeError; a silent null
        # here used to surface far away as a null dereference
        builder.position_at_end(error_block)
        add_err = self._create_global_string_with_builder(
            "TypeError: unsupported operand types for +", builder
        )
        self._emit_panic(builder, add_err)

        # Arithmetic over int/bool/float operands with Python promotion rules
        self._create_str_repeat_runtime()
        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            lambda b, left, right: b.sub(left, right),
            lambda b, left, right: b.fsub(left, right),
            None,
            False,
            True,
            None,
        )
        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            lambda b, left, right: b.mul(left, right),
            lambda b, left, right: b.fmul(left, right),
            lambda b, s, n: b.call(self.str_repeat, [s, n]),
            False,
            True,
            lambda b, l_val, n: b.call(self.list_repeat, [l_val, n]),
        )
        # Python true division always returns a float
        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            None,
            lambda b, left, right: b.fdiv(left, right),
            None,
            True,
            False,
            None,
        )
        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            _floor_div_apply,
            self._float_floordiv_apply,
            None,
            True,
            False,
            None,
        )
        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            _py_mod_apply,
            self._float_mod_apply,
            None,
            True,
            False,
            None,
        )
        # bitwise ops on int/bool PyObjects (float operands fall to the
        # error path - bitwise on floats is a type error)
        self.pyobj_bitor = self._create_numeric_binary_function(
            "bitor", lambda b, l_val, r: b.or_(l_val, r, ""), False,
            None, False, False,
            None,
        )
        self.pyobj_bitand = self._create_numeric_binary_function(
            "bitand", lambda b, l_val, r: b.and_(l_val, r, ""), False,
            None, False, False,
            None,
        )
        self.pyobj_bitxor = self._create_numeric_binary_function(
            "bitxor", lambda b, l_val, r: b.xor(l_val, r, ""), False,
            None, False, False,
            None,
        )
        self.pyobj_shl = self._create_numeric_binary_function(
            "shl", lambda b, l_val, r: b.shl(l_val, r, ""), False,
            None, False, False,
            None,
        )
        self.pyobj_shr = self._create_numeric_binary_function(
            "shr", lambda b, l_val, r: b.ashr(l_val, r, ""), False,
            None, False, False,
            None,
        )

        # Create print function for PyObjects
        self._create_pyobj_print()


    def _load_number_as_i64(self, builder, obj):
        """Load the payload of an int/bool PyObject as an i64."""
        data = builder.load(
            builder.gep(
                obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
            )
        )
        return builder.load(builder.bitcast(data, ir.PointerType(ir.IntType(64))))

    def _load_number_as_f64(self, builder, obj):
        """Load the payload of an int/bool/float PyObject as a double."""
        data = builder.load(
            builder.gep(
                obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
            )
        )
        as_float = builder.load(builder.bitcast(data, ir.PointerType(ir.DoubleType())))
        int_bits = builder.load(builder.bitcast(data, ir.PointerType(ir.IntType(64))))
        as_int = builder.sitofp(int_bits, ir.DoubleType())
        tag = builder.load(
            builder.gep(
                obj,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        is_float = builder.icmp_signed("==", tag, ir.const_(ir.IntType(32), 1))
        return builder.select(is_float, as_float, as_int)

    def _float_floordiv_apply(self, builder, left_val, right_val):
        """Python float floor division: floor(left / right)."""
        quotient = builder.fdiv(left_val, right_val)
        return builder.call(self.floor_f64, [quotient])

    def _float_mod_apply(self, builder, left_val, right_val):
        """Python float modulo: result has the sign of the divisor."""
        remainder = builder.frem(left_val, right_val)
        zero = ir.const_(ir.DoubleType(), 0.0)
        r_ne_zero = builder.fcmp_ordered("!=", remainder, zero)
        r_negative = builder.fcmp_ordered("<", remainder, zero)
        right_negative = builder.fcmp_ordered("<", right_val, zero)
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        return builder.select(adjust, builder.fadd(remainder, right_val), remainder)



    def _panic_string(self, string_content: str):
        """A lazily-created panic message global.

        Since P2 the global is content-named and interned like every
        other string constant: identical messages share one
        definition (the old explicit labels - str_keyerr/
        str_idxerr/str_typeerr/json_typeerr - are gone; e.g. the
        subscript IndexError and the char-view IndexError are one
        global now). Body shaped to hit flatten's .si rewrites - keep
        the string_bytes/string_content spellings."""
        string_bytes = bytearray((string_content + "\x00").encode("utf-8"))
        base = self._str_global_name(string_content)
        if base in self.module.globals:
            return self.module.globals[base]
        gv = ir.gvar_(
            self.module,
            ir.ArrayType(ir.IntType(8), len(string_bytes)), base,

        )
        gv.global_constant = True
        gv.initializer = ir.const_(
            ir.ArrayType(ir.IntType(8), len(string_bytes)), string_bytes
        )
        return gv

    def _pyobj_string_parts(self, builder, obj, zero32, one32):
        data_ptr = builder.gep(obj, [zero32, one32])
        data = builder.load(data_ptr)
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        return str_len, chars


    def _for_i64_loop(self, i64, builder, func, prefix, start, stop):
        """Emit a counting loop header; caller fills body, then closes."""
        idx_ptr = builder.alloca(i64, None, f'{prefix}_i')
        builder.store(start, idx_ptr)
        cond = func.append_basic_block(f"{prefix}_cond")
        body = func.append_basic_block(f"{prefix}_body")
        done = func.append_basic_block(f"{prefix}_done")
        builder.branch(cond)
        builder.position_at_end(cond)
        current = builder.load(idx_ptr)
        more = builder.icmp_signed("<", current, stop)
        builder.cbranch(more, body, done)
        builder.position_at_end(body)
        return idx_ptr, cond, body, done


    def _close_i64_loop(self, builder, idx_ptr, cond, one64):
        builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
        builder.branch(cond)


    def _list_parts(self, builder, func, obj, prefix):
        """Return (struct_ptr, length, items) with items loop-ready."""
        zero32 = ir.const_(ir.IntType(32), 0)
        struct_ptr = self._load_list_struct(builder, obj)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(ir.IntType(32), 2)]))
        return struct_ptr, length, items


    def _emit_case_fold(self, builder, func, to_upper, i32, i64, one32, one64, zero32, zero64):
        (obj_arg,) = func.args
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        length = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        buf = builder.call(
            self.malloc, [builder.add(builder.sext(length, i64), one64)]
        )
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder, func, "fold", zero64, builder.sext(length, i64)
        )
        ch = builder.load(builder.gep(chars, [builder.load(idx_ptr)]))
        ch32 = builder.sext(ch, i32)
        if to_upper:
            in_range = builder.and_(
                builder.icmp_signed(">=", ch32, ir.const_(i32, 97)),
                builder.icmp_signed("<=", ch32, ir.const_(i32, 122)),
            )
            folded = builder.select(
                in_range, builder.sub(ch, ir.const_(ir.IntType(8), 32)), ch
            )
        else:
            in_range = builder.and_(
                builder.icmp_signed(">=", ch32, ir.const_(i32, 65)),
                builder.icmp_signed("<=", ch32, ir.const_(i32, 90)),
            )
            folded = builder.select(
                in_range, builder.add(ch, ir.const_(ir.IntType(8), 32)), ch
            )
        builder.store(folded, builder.gep(buf, [builder.load(idx_ptr)]))
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.store(
            ir.const_(ir.IntType(8), 0),
            builder.gep(buf, [builder.sext(length, i64)]),
        )
        builder.ret(builder.call(self.create_str, [buf, length]))


    def _emit_str_pred(self, name, lo_hi_pairs, extra_bytes, i64, one32, one64, zero32, zero64, pyobj_ptr):
        """str.isdigit/isalpha/isspace for boxed strings (ASCII
        approximation of Python's Unicode classes; empty -> False)."""
        func = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), name
        )
        builder = ir.builder_(func.append_basic_block("entry"))
        data = builder.load(builder.gep(func.args[0], [zero32, one32]))
        str_struct = builder.bitcast(
            data, ir.PointerType(self.pyobj.string_type)
        )
        length = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        empty = builder.icmp_signed("==", length, zero64)
        ret_bool = func.append_basic_block("pred_ret")
        loop = func.append_basic_block("pred_loop")
        builder.cbranch(empty, ret_bool, loop)

        builder.position_at_end(loop)
        idx_ptr = builder.alloca(i64, None, 'pred_i')
        builder.store(zero64, idx_ptr)
        cond = func.append_basic_block("pred_cond")
        body = func.append_basic_block("pred_body")
        false_block = func.append_basic_block("pred_false")
        step = func.append_basic_block("pred_step")
        builder.branch(cond)

        builder.position_at_end(cond)
        builder.cbranch(
            builder.icmp_signed("<", builder.load(idx_ptr), length),
            body,
            ret_bool,
        )

        builder.position_at_end(body)
        byte = builder.load(builder.gep(chars, [builder.load(idx_ptr)]))
        matched = ir.const_(ir.IntType(1), 0)
        for lo, hi in lo_hi_pairs:
            in_range = builder.or_(
                builder.and_(
                    builder.icmp_signed(">=", byte, ir.const_(ir.IntType(8), lo)),
                    builder.icmp_signed("<=", byte, ir.const_(ir.IntType(8), hi)),
                ),
                ir.const_(ir.IntType(1), 0),
            )
            matched = builder.or_(matched, in_range)
        for extra in extra_bytes:
            is_eq = builder.icmp_signed(
                "==", byte, ir.const_(ir.IntType(8), extra)
            )
            matched = builder.or_(matched, is_eq)
        builder.cbranch(matched, step, false_block)

        builder.position_at_end(false_block)
        builder.ret(builder.call(self.create_bool, [ir.const_(ir.IntType(1), 0)]))

        builder.position_at_end(step)
        builder.store(
            builder.add(builder.load(idx_ptr), one64), idx_ptr
        )
        builder.branch(cond)

        builder.position_at_end(ret_bool)
        builder.ret(builder.call(self.create_bool, [ir.const_(ir.IntType(1), 1)]))
        return func


    def _emit_sub_search(self, builder, func, from_right, i32, i64, one32, one64, zero32, zero64):
        s_arg, sub_arg = func.args
        s_len_raw, s_chars = self._pyobj_string_parts(builder, s_arg, zero32, one32)
        s_len = builder.sext(s_len_raw, i64)
        sub_len_raw, sub_chars = self._pyobj_string_parts(builder, sub_arg, zero32, one32)
        sub_len = builder.sext(sub_len_raw, i64)
        too_long = builder.icmp_signed(">", sub_len, s_len)
        miss_block = func.append_basic_block("search_miss")
        scan_block = func.append_basic_block("search_scan")
        builder.cbranch(too_long, miss_block, scan_block)

        builder.position_at_end(miss_block)
        builder.ret(builder.call(self.create_int, [ir.const_(i64, -1)]))

        builder.position_at_end(scan_block)
        last_pos = builder.add(builder.sub(s_len, sub_len), ir.const_(i64, 1))
        start = builder.sub(last_pos, one64) if from_right else zero64
        idx_ptr = builder.alloca(i64, None, 'search_i')
        builder.store(start, idx_ptr)
        cond = func.append_basic_block("search_cond")
        body = func.append_basic_block("search_body")
        after = func.append_basic_block("search_after")
        builder.branch(cond)

        builder.position_at_end(cond)
        if from_right:
            keep_going = builder.icmp_signed(">=", builder.load(idx_ptr), zero64)
        else:
            keep_going = builder.icmp_signed("<", builder.load(idx_ptr), last_pos)
        builder.cbranch(keep_going, body, after)

        builder.position_at_end(body)
        at = builder.load(idx_ptr)
        needle = builder.gep(s_chars, [at])
        same = builder.icmp_signed(
            "==",
            builder.call(self.memcmp, [needle, sub_chars, sub_len]),
            ir.const_(i32, 0),
        )
        hit_block = func.append_basic_block("search_hit")
        step_block = func.append_basic_block("search_step")
        builder.cbranch(same, hit_block, step_block)

        builder.position_at_end(hit_block)
        builder.ret(builder.call(self.create_int, [at]))

        builder.position_at_end(step_block)
        if from_right:
            builder.store(builder.sub(at, one64), idx_ptr)
        else:
            builder.store(builder.add(at, one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(after)
        builder.ret(builder.call(self.create_int, [ir.const_(i64, -1)]))

    def _emit_str_count(self, builder, func, i32, i64, one32, one64, zero32, zero64):
        """str_count(s, sub): CPython str.count on a boxed string - the
        non-overlapping occurrences scanning forward from a moving start
        (the match advances by the whole length, a miss by one). An
        empty sub matches at every position: codepoint length + 1."""
        s_arg, sub_arg = func.args
        s_len_raw, s_chars = self._pyobj_string_parts(builder, s_arg, zero32, one32)
        s_len = builder.sext(s_len_raw, i64)
        sub_len_raw, sub_chars = self._pyobj_string_parts(builder, sub_arg, zero32, one32)
        sub_len = builder.sext(sub_len_raw, i64)
        sc_empty = func.append_basic_block("sc_empty")
        sc_init = func.append_basic_block("sc_init")
        builder.cbranch(
            builder.icmp_signed("==", sub_len, zero64), sc_empty, sc_init
        )

        builder.position_at_end(sc_empty)
        cp_obj = builder.call(self.pyobj_len, [s_arg])
        cp_len = self._load_number_as_i64(builder, cp_obj)
        builder.ret(builder.call(self.create_int, [builder.add(cp_len, one64)]))

        builder.position_at_end(sc_init)
        count_ptr = builder.alloca(i64, None, 'sc_count')
        pos_ptr = builder.alloca(i64, None, 'sc_pos')
        builder.store(zero64, count_ptr)
        builder.store(zero64, pos_ptr)
        sc_cond = func.append_basic_block("sc_cond")
        sc_body = func.append_basic_block("sc_body")
        sc_step = func.append_basic_block("sc_step")
        sc_hit = func.append_basic_block("sc_hit")
        sc_end = func.append_basic_block("sc_end")
        builder.branch(sc_cond)

        builder.position_at_end(sc_cond)
        pos_now = builder.load(pos_ptr)
        # positions 0 .. s_len - sub_len (inclusive); a sub longer than
        # s makes the bound non-positive and the loop never runs
        last = builder.add(builder.sub(s_len, sub_len), one64)
        builder.cbranch(
            builder.icmp_signed("<", pos_now, last), sc_body, sc_end
        )

        builder.position_at_end(sc_body)
        needle = builder.gep(s_chars, [pos_now])
        same = builder.icmp_signed(
            "==",
            builder.call(self.memcmp, [needle, sub_chars, sub_len]),
            ir.const_(i32, 0),
        )
        builder.cbranch(same, sc_hit, sc_step)

        builder.position_at_end(sc_step)
        builder.store(builder.add(builder.load(pos_ptr), one64), pos_ptr)
        builder.branch(sc_cond)

        builder.position_at_end(sc_hit)
        builder.store(builder.add(builder.load(count_ptr), one64), count_ptr)
        builder.store(builder.add(builder.load(pos_ptr), sub_len), pos_ptr)
        builder.branch(sc_cond)

        builder.position_at_end(sc_end)
        builder.ret(builder.call(self.create_int, [builder.load(count_ptr)]))

    def _load_dict_parts(self, builder, obj, zero32, one32):
        """Return (struct_ptr, count, used, mask, itable, entries)."""
        data = builder.load(builder.gep(obj, [zero32, one32]))
        struct_ptr = builder.bitcast(data, ir.PointerType(self.dict_struct_type))
        count = builder.load(_dict_field(builder, struct_ptr, 0))
        used = builder.load(_dict_field(builder, struct_ptr, 1))
        mask = builder.load(_dict_field(builder, struct_ptr, 2))
        itable = builder.load(_dict_field(builder, struct_ptr, 3))
        entries = builder.load(_dict_field(builder, struct_ptr, 4))
        return struct_ptr, count, used, mask, itable, entries


    def _slice_clamp_bound(self, b, bound, has, default, floor, ceil, s_len, zero64):
        adjusted = b.select(
            b.icmp_signed("<", bound, zero64), b.add(bound, s_len), bound
        )
        picked = b.select(has, adjusted, default)
        floored = b.select(b.icmp_signed("<", picked, floor), floor, picked)
        return b.select(b.icmp_signed(">", floored, ceil), ceil, floored)


    def _float_emit_fmt(self, builder, value, fmt):
        buf = builder.call(self.malloc, [ir.const_(ir.IntType(64), 40)])
        fmt_ptr = self._create_global_string_with_builder(fmt, builder)
        builder.call(
            self.snprintf, [buf, ir.const_(ir.IntType(64), 40), fmt_ptr, value]
        )
        return buf


    def _float_parsed_back(self, builder, value, i8p, buf):
        endp = builder.call(self.malloc, [ir.const_(ir.IntType(64), 8)])
        endp_i8pp = builder.bitcast(endp, ir.PointerType(i8p))
        back = builder.call(self.strtod, [buf, endp_i8pp])
        return builder.fcmp_ordered("==", back, value)


    def _float_is_marker(self, builder, i8p, buf, ch):
        hit = builder.call(
            self.memchr,
            [
                buf,
                ir.const_(ir.IntType(32), ord(ch)),
                builder.call(self.strlen, [buf]),
            ],
        )
        return builder.icmp_signed("!=", hit, ir.const_(i8p, None))


    def _tag_is_intish(self, builder, tag):
        zero = ir.const_(ir.IntType(32), 0)
        return builder.or_(
            builder.icmp_signed("==", tag, zero),
            builder.icmp_signed("==", tag, ir.const_(ir.IntType(32), 3)),
        )


    def _tag_is_str(self, builder, tag):
        return builder.icmp_signed("==", tag, ir.const_(ir.IntType(32), 2))


    def _create_instance_runtime(self):
        """Boxed class instances ride tag 6 with data pointing at a
        {i64 class_id, i8* instance} side cell. Dynamic attribute and
        method dispatch switch on the class id; the converter emits
        those switches from its layout table."""
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i8p = ir.PointerType(ir.IntType(8))
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        cell_ty = ir.LiteralStructType([i64, i8p])
        self.inst_cell_ty = cell_ty

        # PObj* pyobj_make_instance(i64 cid, i8* inst)
        self.pyobj_make_instance = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [i64, i8p], False),
            "pyobj_make_instance",
        )
        b = ir.builder_(self.pyobj_make_instance.append_basic_block("entry"))
        cid_arg, inst_arg = self.pyobj_make_instance.args
        cell = b.call(self.malloc, [ir.const_(i64, 16)])
        cellp = b.bitcast(cell, ir.PointerType(cell_ty))
        b.store(cid_arg, b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 0)]))
        b.store(
            b.bitcast(inst_arg, i8p),
            b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        box_raw = b.call(self.malloc, [ir.const_(i64, 16)])
        box = b.bitcast(box_raw, ir.PointerType(self.pyobj.pyobj_type))
        b.store(
            ir.const_(i32, 6),
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 0)]),
        )
        b.store(
            b.bitcast(cell, i8p),
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        b.ret(box)

        # i8* pyobj_instance_ptr(PObj* o)
        self.pyobj_instance_ptr = ir.func_(
            self.module, ir.FunctionType(i8p, [pyobj_ptr], False),
            "pyobj_instance_ptr",
        )
        b = ir.builder_(self.pyobj_instance_ptr.append_basic_block("entry"))
        (o_arg,) = self.pyobj_instance_ptr.args
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        cellp = b.bitcast(data, ir.PointerType(cell_ty))
        inst = b.load(b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        b.ret(inst)

        # i64 pyobj_instance_cid(PObj* o)
        # Tag-guarded: a non-instance box's payload must never be
        # dereferenced as a side cell; such boxes answer cid -1.
        no_cid_gv = ir.gvar_(
            self.module, i64, "silu_no_cid",
        )
        no_cid_gv.initializer = ir.const_(i64, -1)
        self.pyobj_instance_cid = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False),
            "pyobj_instance_cid",
        )
        b = ir.builder_(self.pyobj_instance_cid.append_basic_block("entry"))
        (o_arg,) = self.pyobj_instance_cid.args
        tag = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 0)]))
        is6 = b.icmp_signed("==", tag, ir.const_(i32, 6))
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        cell_field = b.gep(
            b.bitcast(data, ir.PointerType(cell_ty)),
            [ir.const_(i32, 0), ir.const_(i32, 0)],
        )
        cid = b.load(b.select(is6, cell_field, no_cid_gv))
        b.ret(cid)

    def _create_fnref_runtime(self):
        """Indirect calls: tag-7 funcref boxes carry a table index; a
        global table of function pointers is filled by silu_fn_init
        (emitted by the converter once all functions exist), and
        pyobj_fn_call dispatches on the index with compile-time-known
        arity."""
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)

        self.pyobj_fnref = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [i64, pyobj_ptr], False),
            "pyobj_fnref",
        )
        b = ir.builder_(self.pyobj_fnref.append_basic_block("entry"))
        idx_arg, self_arg = self.pyobj_fnref.args
        box_raw = b.call(self.malloc, [ir.const_(i64, 16)])
        box = b.bitcast(box_raw, ir.PointerType(self.pyobj.pyobj_type))
        b.store(
            ir.const_(i32, 7),
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 0)]),
        )
        cell_ty = ir.LiteralStructType([i64, pyobj_ptr])
        self.fnref_cell_ty = cell_ty
        cell = b.call(self.malloc, [ir.const_(i64, 16)])
        cellp = b.bitcast(cell, ir.PointerType(cell_ty))
        b.store(
            idx_arg,
            b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 0)]),
        )
        b.store(
            self_arg,
            b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        b.store(
            cell,
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        b.ret(box)

        # PObj* pyobj_fn_self(PObj* o) - the bound self (null when the
        # funcref is a plain function)
        self.pyobj_fn_self = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False),
            "pyobj_fn_self",
        )
        b = ir.builder_(self.pyobj_fn_self.append_basic_block("entry"))
        (o_arg,) = self.pyobj_fn_self.args
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        cellp = b.bitcast(data, ir.PointerType(cell_ty))
        b.ret(b.load(b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)])))

        self.pyobj_fn_index = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False),
            "pyobj_fn_index",
        )
        b = ir.builder_(self.pyobj_fn_index.append_basic_block("entry"))
        (o_arg,) = self.pyobj_fn_index.args
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        b.ret(b.load(b.bitcast(data, ir.PointerType(i64))))

    def _create_generic_iter_runtime(self):
        """Generic `for x in obj`: pyobj_iter_keys(obj) materializes a
        list of elements - list items, live dict keys, or chars - and
        the existing list walk iterates it."""
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        zero32 = ir.const_(i32, 0)
        null_obj = ir.const_(pyobj_ptr, None)

        self.pyobj_iter_keys = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr], False),
            "pyobj_iter_keys",
        )
        fn = self.pyobj_iter_keys
        entry = fn.append_basic_block("entry")
        list_blk = fn.append_basic_block("as_list")
        dict_blk = fn.append_basic_block("as_dict")
        other_blk = fn.append_basic_block("as_other")
        str_blk = fn.append_basic_block("as_str")
        empty_blk = fn.append_basic_block("as_empty")
        b = ir.builder_(entry)
        (obj_arg,) = fn.args
        tag = b.load(b.gep(obj_arg, [zero32, zero32]))
        b.cbranch(
            b.or_(
                b.icmp_signed("==", tag, ir.const_(i32, 4)),
                b.icmp_signed("==", tag, ir.const_(i32, 8)),
            ),
            list_blk,
            dict_blk,
        )
        b.position_at_end(list_blk)
        b.ret(obj_arg)

        b.position_at_end(dict_blk)
        b.cbranch(
            b.icmp_signed("==", tag, ir.const_(i32, 5)),
            fn.append_basic_block("dict_walk"),
            other_blk,
        )
        b.position_at_end(fn.blocks[-1])
        di_struct, di_count, di_used, di_mask, di_itable, di_entries = (
            self._load_dict_parts(b, obj_arg, zero32, ir.const_(i32, 1))
        )
        out_list = b.call(self.create_list, [])
        pos_ptr = b.alloca(i64, None, "ik_pos")
        b.store(ir.const_(i64, 0), pos_ptr)
        cond_blk = fn.append_basic_block("ik_cond")
        body_blk = fn.append_basic_block("ik_body")
        live_blk = fn.append_basic_block("ik_live")
        step_blk = fn.append_basic_block("ik_step")
        done_blk = fn.append_basic_block("ik_done")
        b.branch(cond_blk)
        b.position_at_end(cond_blk)
        pos = b.load(pos_ptr)
        b.cbranch(b.icmp_signed("<", pos, di_used), body_blk, done_blk)
        b.position_at_end(body_blk)
        entry_ptr = b.gep(di_entries, [zero32, pos])
        key_obj = b.load(b.gep(entry_ptr, [zero32, zero32]))
        b.cbranch(
            b.icmp_signed("!=", key_obj, null_obj), live_blk, step_blk
        )
        b.position_at_end(live_blk)
        b.call(self.list_append, [out_list, key_obj])
        b.branch(step_blk)
        b.position_at_end(step_blk)
        b.store(b.add(pos, ir.const_(i64, 1)), pos_ptr)
        b.branch(cond_blk)
        b.position_at_end(done_blk)
        b.ret(out_list)

        b.position_at_end(other_blk)
        b.cbranch(
            b.icmp_signed("==", tag, ir.const_(i32, 2)),
            str_blk,
            empty_blk,
        )
        b.position_at_end(empty_blk)
        b.ret(b.call(self.create_list, []))

        b.position_at_end(str_blk)
        str_len, str_chars = self._pyobj_string_parts(
            b, obj_arg, zero32, ir.const_(i32, 1)
        )
        str_len64 = b.sext(str_len, i64)
        str_out = b.call(self.create_list, [])
        str_pos = b.alloca(i64, None, "ik_str_pos")
        b.store(ir.const_(i64, 0), str_pos)
        str_cond = fn.append_basic_block("ik_str_cond")
        str_body = fn.append_basic_block("ik_str_body")
        str_done = fn.append_basic_block("ik_str_done")
        b.branch(str_cond)
        b.position_at_end(str_cond)
        pos_now = b.load(str_pos)
        b.cbranch(b.icmp_signed("<", pos_now, str_len64), str_body, str_done)
        b.position_at_end(str_body)
        lead = b.load(b.gep(str_chars, [pos_now]))
        two = b.icmp_signed(
            "==", b.and_(lead, ir.const_(ir.IntType(8), 0xE0)),
            ir.const_(ir.IntType(8), 0xC0),
        )
        three = b.icmp_signed(
            "==", b.and_(lead, ir.const_(ir.IntType(8), 0xF0)),
            ir.const_(ir.IntType(8), 0xE0),
        )
        four = b.icmp_signed(
            "==", b.and_(lead, ir.const_(ir.IntType(8), 0xF8)),
            ir.const_(ir.IntType(8), 0xF0),
        )
        seq = b.select(four, ir.const_(i64, 4), ir.const_(i64, 1))
        seq = b.select(three, ir.const_(i64, 3), seq)
        seq = b.select(two, ir.const_(i64, 2), seq)
        char_obj = b.call(
            self.create_str,
            [b.gep(str_chars, [pos_now]), b.trunc(seq, i32)],
        )
        b.call(self.list_append, [str_out, char_obj])
        b.store(b.add(pos_now, seq), str_pos)
        b.branch(str_cond)
        b.position_at_end(str_done)
        b.ret(str_out)

        # That key list is only a SNAPSHOT: a loop over a dict watches
        # the dict itself, the way CPython's iterator does. A set rides
        # the same walk unchanged (pyobj_iter_keys returns it as its own
        # list) and is held to CPython's rule too: it may not change
        # size under its own loop.
        #   i64 pyobj_dict_count(d) / pyobj_dict_used(d) /
        #      pyobj_dict_entries_bits(d)   its shape as it stands now
        #   i64 pyobj_dict_watch(d, count0, used0, entries0)
        #      0 = unchanged, 1 = the live count moved, 2 = same size
        #      but rebuilt or appended to underneath the cursor
        # Anything that is neither reads as (-1, -1, 0), never changes.
        one32 = ir.const_(i32, 1)
        self.pyobj_dict_count = self._emit_dict_shape_getter(
            "pyobj_dict_count", 0, ir.const_(i64, -1)
        )
        self.pyobj_dict_used = self._emit_dict_shape_getter(
            "pyobj_dict_used", 1, ir.const_(i64, -1)
        )
        self.pyobj_dict_entries_bits = self._emit_dict_shape_getter(
            "pyobj_dict_entries_bits", 4, ir.const_(i64, 0)
        )

        self.pyobj_dict_watch = ir.func_(
            self.module,
            ir.FunctionType(i64, [pyobj_ptr, i64, i64, i64], False),
            'pyobj_dict_watch',
        )
        entry = self.pyobj_dict_watch.append_basic_block("entry")
        as_dict = self.pyobj_dict_watch.append_basic_block("as_dict")
        as_set = self.pyobj_dict_watch.append_basic_block("as_set")
        not_dict = self.pyobj_dict_watch.append_basic_block("not_dict")
        size_moved = self.pyobj_dict_watch.append_basic_block("size_moved")
        shape_moved = self.pyobj_dict_watch.append_basic_block("shape_moved")
        same_shape = self.pyobj_dict_watch.append_basic_block("same_shape")
        churned = self.pyobj_dict_watch.append_basic_block("churned")
        b = ir.builder_(entry)
        w_obj, w_count, w_used, w_entries = self.pyobj_dict_watch.args
        w_tag = b.load(b.gep(w_obj, [zero32, zero32]))
        b.cbranch(b.icmp_signed("==", w_tag, ir.const_(i32, 5)), as_dict, not_dict)
        b.position_at_end(not_dict)
        b.cbranch(b.icmp_signed("==", w_tag, ir.const_(i32, 8)), as_set, same_shape)
        b.position_at_end(as_set)
        b.cbranch(
            b.icmp_signed(
                "!=", b.call(self.list_length, [w_obj]), w_count
            ),
            size_moved,
            same_shape,
        )
        b.position_at_end(as_dict)
        w_parts = self._load_dict_parts(b, w_obj, zero32, one32)
        # field 0 is the live count, field 1 the slots in use
        b.cbranch(
            b.icmp_signed("!=", w_parts[1], w_count), size_moved, shape_moved
        )
        b.position_at_end(shape_moved)
        b.cbranch(
            b.or_(
                b.icmp_signed("!=", w_parts[2], w_used),
                b.icmp_signed(
                    "!=", b.ptrtoint(w_parts[5], i64), w_entries
                ),
            ),
            churned,
            same_shape,
        )
        b.position_at_end(size_moved)
        b.ret(ir.const_(i64, 1))
        b.position_at_end(churned)
        b.ret(ir.const_(i64, 2))
        b.position_at_end(same_shape)
        b.ret(ir.const_(i64, 0))

    def _emit_dict_shape_getter(self, name: str, field_index: int, miss):
        """i64 name(PyObject* d): one field of a boxed dict's shape
        (0 live count, 1 slots in use, 4 entries array as its address
        bits). A set answers with its length for field 0 and `miss`
        otherwise; `miss` for anything that is neither."""
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        fn = ir.func_(self.module, ir.FunctionType(i64, [pyobj_ptr], False), name)
        entry = fn.append_basic_block("entry")
        as_dict = fn.append_basic_block("as_dict")
        as_set = fn.append_basic_block("as_set")
        not_dict = fn.append_basic_block("not_dict")
        as_other = fn.append_basic_block("as_other")
        b = ir.builder_(entry)
        (obj_arg,) = fn.args
        tag = b.load(b.gep(obj_arg, [zero32, zero32]))
        b.cbranch(b.icmp_signed("==", tag, ir.const_(i32, 5)), as_dict, not_dict)
        b.position_at_end(not_dict)
        b.cbranch(b.icmp_signed("==", tag, ir.const_(i32, 8)), as_set, as_other)
        b.position_at_end(as_other)
        b.ret(miss)
        b.position_at_end(as_set)
        if field_index == 0:
            b.ret(b.call(self.list_length, [obj_arg]))
        else:
            b.ret(miss)
        b.position_at_end(as_dict)
        parts = self._load_dict_parts(b, obj_arg, zero32, one32)
        if field_index == 4:
            b.ret(b.ptrtoint(parts[5], i64))
        elif field_index == 1:
            b.ret(parts[2])
        else:
            b.ret(parts[1])
        return fn

    def _create_pyobj_print(self):
        """Create PyObject print function."""
        self._create_instance_runtime()
        self._create_fnref_runtime()
        self._create_float_repr_runtime()

        print_ty = ir.FunctionType(
            ir.VoidType(), [ir.PointerType(self.pyobj.pyobj_type)], False
        )
        self.pyobj_print = ir.func_(self.module, print_ty, 'pyobj_print')

        # void pyobj_repr_print(PyObject* obj) - repr-style: strings quoted
        self.pyobj_repr_print = ir.func_(
            self.module, print_ty, 'pyobj_repr_print'
        )
        repr_entry = self.pyobj_repr_print.append_basic_block("entry")
        repr_tagged = self.pyobj_repr_print.append_basic_block("repr_tagged")
        repr_str_case = self.pyobj_repr_print.append_basic_block("repr_str")
        repr_other = self.pyobj_repr_print.append_basic_block("repr_other")
        repr_null = self.pyobj_repr_print.append_basic_block("repr_null")
        repr_builder = ir.builder_(repr_entry)
        repr_obj = self.pyobj_repr_print.args[0]
        # a None element inside a container arrives as a null pointer:
        # reading its tag segfaulted (print([None]), print({"k": None})).
        # The scalar printer already has this check; repr did not.
        repr_is_null = repr_builder.icmp_signed(
            "==",
            repr_obj,
            ir.const_(ir.PointerType(self.pyobj.pyobj_type), None),
        )
        repr_builder.cbranch(repr_is_null, repr_null, repr_tagged)

        repr_builder.position_at_end(repr_tagged)
        repr_tag = repr_builder.load(
            repr_builder.gep(
                repr_obj,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        is_str_tag = repr_builder.icmp_signed(
            "==", repr_tag, ir.const_(ir.IntType(32), 2)
        )
        repr_builder.cbranch(is_str_tag, repr_str_case, repr_other)

        repr_builder.position_at_end(repr_str_case)
        zero32r = ir.const_(ir.IntType(32), 0)
        one32r = ir.const_(ir.IntType(32), 1)
        r_data = repr_builder.load(repr_builder.gep(repr_obj, [zero32r, one32r]))
        r_struct = repr_builder.bitcast(r_data, ir.PointerType(self.pyobj.string_type))
        r_chars = repr_builder.load(repr_builder.gep(r_struct, [zero32r, one32r]))
        # string buffers are not NUL-terminated; print by length
        r_len = repr_builder.load(repr_builder.gep(r_struct, [zero32r, zero32r]))
        quoted_fmt = self._create_global_string_with_builder("'%.*s'", repr_builder)
        repr_builder.call(self.printf, [quoted_fmt, r_len, r_chars])
        repr_builder.ret_void()

        repr_builder.position_at_end(repr_other)
        repr_builder.call(self.pyobj_print, [repr_obj])
        repr_builder.ret_void()

        repr_builder.position_at_end(repr_null)
        repr_none = self._create_global_string_with_builder("None", repr_builder)
        repr_builder.call(self.printf, [repr_none])
        repr_builder.ret_void()

        entry_block = self.pyobj_print.append_basic_block("entry")
        null_block = self.pyobj_print.append_basic_block("print_null")
        dispatch_block = self.pyobj_print.append_basic_block("dispatch")
        int_block = self.pyobj_print.append_basic_block("print_int")
        float_block = self.pyobj_print.append_basic_block("print_float")
        str_block = self.pyobj_print.append_basic_block("print_str")
        bool_block = self.pyobj_print.append_basic_block("print_bool")
        list_block = self.pyobj_print.append_basic_block("print_list")
        dict_block = self.pyobj_print.append_basic_block("print_dict")
        default_block = self.pyobj_print.append_basic_block("default")

        builder = ir.builder_(entry_block)

        obj = self.pyobj_print.args[0]

        # Null pointer prints as None (e.g. bare return values)
        null_ptr = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
        is_null = builder.icmp_signed("==", obj, null_ptr)
        builder.cbranch(is_null, null_block, dispatch_block)

        builder.position_at_end(null_block)
        none_str = self._create_global_string_with_builder("None", builder)
        builder.call(self.printf, [none_str])
        builder.ret_void()

        # Get type tag
        builder.position_at_end(dispatch_block)
        tag_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        tag = builder.load(tag_ptr)

        # Switch on type tag
        switch = builder.switch(tag, default_block)
        switch.add_case(ir.const_(ir.IntType(32), 0), int_block)  # int
        switch.add_case(ir.const_(ir.IntType(32), 1), float_block)  # float
        switch.add_case(ir.const_(ir.IntType(32), 2), str_block)  # str
        switch.add_case(ir.const_(ir.IntType(32), 3), bool_block)  # bool
        switch.add_case(ir.const_(ir.IntType(32), 4), list_block)  # list
        switch.add_case(ir.const_(ir.IntType(32), 8), list_block)  # set
        switch.add_case(ir.const_(ir.IntType(32), 5), dict_block)  # dict

        # Print list as [a, b, c] with recursive element printing
        builder.position_at_end(list_block)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.const_(i32, 0)
        struct_ptr = self._load_list_struct(builder, obj)
        list_len = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        open_bracket = self._create_global_string_with_builder("[", builder)
        builder.call(self.printf, [open_bracket])
        loop_check = self.pyobj_print.append_basic_block("list_loop_check")
        loop_body = self.pyobj_print.append_basic_block("list_loop_body")
        loop_incr = self.pyobj_print.append_basic_block("list_loop_incr")
        list_done = self.pyobj_print.append_basic_block("list_done")
        counter_ptr = builder.alloca(i64, None, 'list_print_idx')
        builder.store(ir.const_(i64, 0), counter_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        counter = builder.load(counter_ptr)
        more = builder.icmp_signed("<", counter, list_len)
        builder.cbranch(more, loop_body, list_done)

        builder.position_at_end(loop_body)
        not_first = builder.icmp_signed(">", counter, ir.const_(i64, 0))
        sep_block = self.pyobj_print.append_basic_block("list_sep")
        elem_block = self.pyobj_print.append_basic_block("list_elem")
        builder.cbranch(not_first, sep_block, elem_block)

        builder.position_at_end(sep_block)
        comma = self._create_global_string_with_builder(", ", builder)
        builder.call(self.printf, [comma])
        builder.branch(elem_block)

        builder.position_at_end(elem_block)
        item_slot = builder.gep(items, [counter])
        item = builder.load(item_slot)
        builder.call(self.pyobj_repr_print, [item])
        builder.branch(loop_incr)

        builder.position_at_end(loop_incr)
        builder.store(builder.add(counter, ir.const_(i64, 1)), counter_ptr)
        builder.branch(loop_check)

        builder.position_at_end(list_done)
        close_bracket = self._create_global_string_with_builder("]", builder)
        builder.call(self.printf, [close_bracket])
        builder.ret_void()

        # Print dict as {'k': v, ...} with repr-style keys and values
        builder.position_at_end(dict_block)
        d_null_const = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
        d_data = builder.load(
            builder.gep(
                obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
            )
        )
        d_struct = builder.bitcast(d_data, ir.PointerType(self.dict_struct_type))
        d_used = builder.load(
            builder.gep(
                d_struct,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)],
            )
        )
        d_entries = builder.load(
            builder.gep(
                d_struct,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 4)],
            )
        )
        open_brace = self._create_global_string_with_builder("{", builder)
        builder.call(self.printf, [open_brace])
        d_check = self.pyobj_print.append_basic_block("dict_check")
        d_body = self.pyobj_print.append_basic_block("dict_body")
        d_sep = self.pyobj_print.append_basic_block("dict_sep")
        d_key = self.pyobj_print.append_basic_block("dict_key")
        d_incr = self.pyobj_print.append_basic_block("dict_incr")
        d_done = self.pyobj_print.append_basic_block("dict_done")
        d_idx = builder.alloca(ir.IntType(64), None, 'dict_print_idx')
        d_printed = builder.alloca(ir.IntType(64), None, 'dict_printed')
        builder.store(ir.const_(ir.IntType(64), 0), d_idx)
        builder.store(ir.const_(ir.IntType(64), 0), d_printed)
        builder.branch(d_check)

        builder.position_at_end(d_check)
        d_i = builder.load(d_idx)
        d_more = builder.icmp_signed("<", d_i, d_used)
        builder.cbranch(d_more, d_body, d_done)

        builder.position_at_end(d_body)
        d_entry = builder.gep(d_entries, [ir.const_(ir.IntType(32), 0), d_i])
        d_key_obj = builder.load(
            builder.gep(
                d_entry,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        # deleted entries (null key) are skipped
        d_is_live = builder.icmp_signed("!=", d_key_obj, d_null_const)
        d_skip = self.pyobj_print.append_basic_block("dict_skip")
        d_live = self.pyobj_print.append_basic_block("dict_live")
        builder.cbranch(d_is_live, d_live, d_skip)

        builder.position_at_end(d_skip)
        builder.store(builder.add(d_i, ir.const_(ir.IntType(64), 1)), d_idx)
        builder.branch(d_check)

        builder.position_at_end(d_live)
        d_not_first = builder.icmp_signed(
            ">", builder.load(d_printed), ir.const_(ir.IntType(64), 0)
        )
        builder.cbranch(d_not_first, d_sep, d_key)

        builder.position_at_end(d_sep)
        comma = self._create_global_string_with_builder(", ", builder)
        builder.call(self.printf, [comma])
        builder.branch(d_key)

        builder.position_at_end(d_key)
        d_val_obj = builder.load(
            builder.gep(
                d_entry,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)],
            )
        )
        builder.call(self.pyobj_repr_print, [d_key_obj])
        colon = self._create_global_string_with_builder(": ", builder)
        builder.call(self.printf, [colon])
        builder.call(self.pyobj_repr_print, [d_val_obj])
        builder.branch(d_incr)

        builder.position_at_end(d_incr)
        builder.store(
            builder.add(builder.load(d_printed), ir.const_(ir.IntType(64), 1)),
            d_printed,
        )
        builder.store(builder.add(d_i, ir.const_(ir.IntType(64), 1)), d_idx)
        builder.branch(d_check)

        builder.position_at_end(d_done)
        close_brace = self._create_global_string_with_builder("}", builder)
        builder.call(self.printf, [close_brace])
        builder.ret_void()

        # Print float via the Python-style repr runtime
        builder.position_at_end(float_block)
        f64_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        f64_data = builder.load(f64_ptr)
        f64_val = builder.load(
            builder.bitcast(f64_data, ir.PointerType(ir.DoubleType()))
        )
        chars = builder.call(self.float_repr, [f64_val])
        float_fmt = self._create_global_string_with_builder("%s", builder)
        builder.call(self.printf, [float_fmt, chars])
        builder.ret_void()

        # Print bool as True/False
        builder.position_at_end(bool_block)
        data_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        data = builder.load(data_ptr)
        bool_i64_ptr = builder.bitcast(data, ir.PointerType(ir.IntType(64)))
        bool_val = builder.load(bool_i64_ptr)
        is_true = builder.icmp_signed("!=", bool_val, ir.const_(ir.IntType(64), 0))
        true_str = self._create_global_string_with_builder("True", builder)
        false_str = self._create_global_string_with_builder("False", builder)
        bool_fmt = builder.select(is_true, true_str, false_str)
        builder.call(self.printf, [bool_fmt])
        builder.ret_void()

        # Print integer
        builder.position_at_end(int_block)
        data_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        data = builder.load(data_ptr)
        i64_ptr = builder.bitcast(data, ir.PointerType(ir.IntType(64)))
        val = builder.load(i64_ptr)

        # Create format string for integer (use %ld for signed)
        int_fmt = self._create_global_string_with_builder("%ld", builder)
        builder.call(self.printf, [int_fmt, val])
        builder.ret_void()

        # Print string
        builder.position_at_end(str_block)
        data_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        data = builder.load(data_ptr)
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        chars_ptr_ptr = builder.gep(
            str_struct, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        chars_ptr = builder.load(chars_ptr_ptr)
        # print with an explicit precision: string buffers are not
        # NUL-terminated (concat allocates exactly len bytes), so a
        # bare %s reads past the end into heap garbage
        str_len_ptr = builder.gep(
            str_struct, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        str_len = builder.load(str_len_ptr)

        str_fmt = self._create_global_string_with_builder("%.*s", builder)
        builder.call(self.printf, [str_fmt, str_len, chars_ptr])
        builder.ret_void()

        # Default case
        builder.position_at_end(default_block)
        unknown_fmt = self._create_global_string_with_builder(
            "<unknown object>", builder
        )
        builder.call(self.printf, [unknown_fmt])
        builder.ret_void()


    def _seq_len_inline(self, b, byte_value):
        """UTF-8 sequence length from a lead byte (invalid -> 1).
        Self-contained twin of the typed layer's _emit_seq_len: this
        mixin's creators run on the base converter, where the typed
        helper is not defined (and no @staticmethod: the self-hosted
        class model passes self explicitly either way)."""
        i64 = ir.IntType(64)
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
        l2 = b.select(two, ir.const_(i64, 2), ir.const_(i64, 1))
        l3 = b.select(three, ir.const_(i64, 3), l2)
        return b.select(four, ir.const_(i64, 4), l3)

    def _create_list_runtime(self):
        """Runtime for list PyObjects (tag 4).

        data points to {i64 length, i64 capacity, PyObject** items}.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i8p = ir.PointerType(ir.IntType(8))
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)

        # create_list() is built in _create_pyobj_constructors so that
        # pyobj_add (list concatenation) can reference it.

        # PyObject* list_append(PyObject* list, PyObject* item)
        append_fn_ty = ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False)
        self.list_append = ir.func_(self.module, append_fn_ty, 'list_append')
        entry = self.list_append.append_basic_block("entry")
        grow_block = self.list_append.append_basic_block("grow")
        do_append_block = self.list_append.append_basic_block("do_append")
        builder = ir.builder_(entry)
        list_arg, item_arg = self.list_append.args
        struct_ptr = self._load_list_struct(builder, list_arg)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        capacity = builder.load(builder.gep(struct_ptr, [zero32, one32]))
        needs_grow = builder.icmp_signed("==", length, capacity)
        builder.cbranch(needs_grow, grow_block, do_append_block)

        builder.position_at_end(grow_block)
        zero64 = ir.const_(i64, 0)
        four64 = ir.const_(i64, 4)
        cap_is_zero = builder.icmp_signed("==", capacity, zero64)
        new_capacity = builder.select(
            cap_is_zero, four64, builder.mul(capacity, ir.const_(i64, 2))
        )
        new_items = builder.call(
            self.malloc, [builder.mul(new_capacity, ir.const_(i64, 8))]
        )
        has_old = builder.icmp_signed(">", capacity, zero64)
        copy_block = self.list_append.append_basic_block("grow_copy")
        after_copy_block = self.list_append.append_basic_block("grow_after_copy")
        builder.cbranch(has_old, copy_block, after_copy_block)

        builder.position_at_end(copy_block)
        old_items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        builder.call(
            self.memcpy,
            [
                new_items,
                builder.bitcast(old_items, ir.PointerType(ir.IntType(8))),
                builder.mul(capacity, ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.branch(after_copy_block)

        builder.position_at_end(after_copy_block)
        builder.store(new_capacity, builder.gep(struct_ptr, [zero32, one32]))
        items_typed = builder.bitcast(new_items, ir.PointerType(pyobj_ptr))
        builder.store(
            items_typed, builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)])
        )
        builder.branch(do_append_block)

        builder.position_at_end(do_append_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        length_now = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        slot = builder.gep(items, [length_now])
        builder.store(item_arg, slot)
        builder.store(
            builder.add(length_now, ir.const_(i64, 1)),
            builder.gep(struct_ptr, [zero32, zero32]),
        )
        builder.ret(list_arg)

        # i64 list_length(PyObject* list) - raw length helper
        self.list_length = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False), 'list_length'
        )
        builder = ir.builder_(self.list_length.append_basic_block("entry"))
        struct_ptr = self._load_list_struct(builder, self.list_length.args[0])
        builder.ret(builder.load(builder.gep(struct_ptr, [zero32, zero32])))

        # i64 pyobj_iter_len(PyObject* obj) - length for `for` iteration:
        # strings read the str struct, everything else the list struct
        self.pyobj_iter_len = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False), 'pyobj_iter_len'
        )
        entry = self.pyobj_iter_len.append_basic_block("entry")
        str_block = self.pyobj_iter_len.append_basic_block("str_len_case")
        list_block = self.pyobj_iter_len.append_basic_block("list_len_case")
        builder = ir.builder_(entry)
        (iter_obj,) = self.pyobj_iter_len.args
        iter_tag = builder.load(builder.gep(iter_obj, [zero32, zero32]))
        is_str = builder.icmp_signed("==", iter_tag, ir.const_(i32, 2))
        builder.cbranch(is_str, str_block, list_block)

        builder.position_at_end(str_block)
        str_struct = builder.bitcast(
            builder.load(builder.gep(iter_obj, [zero32, one32])),
            ir.PointerType(self.pyobj.string_type),
        )
        builder.ret(
            builder.sext(
                builder.load(builder.gep(str_struct, [zero32, zero32])), i64
            )
        )

        builder.position_at_end(list_block)
        iter_list_ptr = self._load_list_struct(builder, iter_obj)
        builder.ret(builder.load(builder.gep(iter_list_ptr, [zero32, zero32])))

        # PyObject* list_get(PyObject* list, PyObject* index)
        self.list_get = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'list_get',

        )
        entry = self.list_get.append_basic_block("entry")
        bounds_block = self.list_get.append_basic_block("bounds")
        negative_block = self.list_get.append_basic_block("negative")
        ok_block = self.list_get.append_basic_block("ok")
        error_block = self.list_get.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg = self.list_get.args
        struct_ptr = self._load_list_struct(builder, list_arg)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        raw_index = self._load_number_as_i64(builder, index_arg)
        is_negative = builder.icmp_signed("<", raw_index, zero64)
        builder.cbranch(is_negative, negative_block, bounds_block)

        builder.position_at_end(negative_block)
        adjusted = builder.add(raw_index, length)
        builder.branch(bounds_block)

        builder.position_at_end(bounds_block)
        adjusted_index = builder.phi(i64)
        adjusted_index.add_incoming(raw_index, entry)
        adjusted_index.add_incoming(adjusted, negative_block)
        in_range = builder.and_(
            builder.icmp_signed(">=", adjusted_index, zero64),
            builder.icmp_signed("<", adjusted_index, length),
        )
        builder.cbranch(in_range, ok_block, error_block)

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "IndexError: list index out of range", builder
        )
        self._emit_panic(builder, error_msg)

        builder.position_at_end(ok_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        slot = builder.gep(items, [adjusted_index])
        builder.ret(builder.load(slot))

        # void list_set(PyObject* list, PyObject* index, PyObject* value)
        self.list_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'list_set',

        )
        entry = self.list_set.append_basic_block("entry")
        neg_block = self.list_set.append_basic_block("negative")
        bounds_block = self.list_set.append_basic_block("bounds")
        ok_block = self.list_set.append_basic_block("ok")
        error_block = self.list_set.append_basic_block("index_error")
        builder = ir.builder_(entry)
        list_arg, index_arg, value_arg = self.list_set.args
        struct_ptr = self._load_list_struct(builder, list_arg)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        raw_index = self._load_number_as_i64(builder, index_arg)
        builder.cbranch(
            builder.icmp_signed("<", raw_index, zero64), neg_block, bounds_block
        )

        builder.position_at_end(neg_block)
        adjusted = builder.add(raw_index, length)
        builder.branch(bounds_block)

        builder.position_at_end(bounds_block)
        adjusted_index = builder.phi(i64)
        adjusted_index.add_incoming(raw_index, entry)
        adjusted_index.add_incoming(adjusted, neg_block)
        in_range = builder.and_(
            builder.icmp_signed(">=", adjusted_index, zero64),
            builder.icmp_signed("<", adjusted_index, length),
        )
        builder.cbranch(in_range, ok_block, error_block)

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "IndexError: list assignment index out of range", builder
        )
        self._emit_panic(builder, error_msg)

        builder.position_at_end(ok_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        builder.store(value_arg, builder.gep(items, [adjusted_index]))
        builder.ret_void()

        # PyObject* pyobj_len(PyObject* obj) - len() for lists and strings
        self.pyobj_len = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'pyobj_len'
        )
        entry = self.pyobj_len.append_basic_block("entry")
        list_block = self.pyobj_len.append_basic_block("len_list")
        str_check_block = self.pyobj_len.append_basic_block("str_check")
        str_block = self.pyobj_len.append_basic_block("len_str")
        dict_check_block = self.pyobj_len.append_basic_block("dict_check")
        dict_block = self.pyobj_len.append_basic_block("len_dict")
        error_block = self.pyobj_len.append_basic_block("error")
        builder = ir.builder_(entry)
        obj_arg = self.pyobj_len.args[0]
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        # tag 8 (set) shares the list struct: len/set ops read it alike
        is_list = builder.or_(
            builder.icmp_signed("==", tag, ir.const_(i32, 4)),
            builder.icmp_signed("==", tag, ir.const_(i32, 8)),
        )
        builder.cbranch(is_list, list_block, str_check_block)

        builder.position_at_end(list_block)
        struct_ptr = self._load_list_struct(builder, obj_arg)
        list_len = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [list_len]))

        builder.position_at_end(str_check_block)
        is_str = builder.icmp_signed("==", tag, ir.const_(i32, 2))
        builder.cbranch(is_str, str_block, dict_check_block)

        builder.position_at_end(str_block)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [builder.sext(str_len, i64)]))

        builder.position_at_end(dict_check_block)
        is_dict = builder.icmp_signed("==", tag, ir.const_(i32, 5))
        builder.cbranch(is_dict, dict_block, error_block)

        builder.position_at_end(dict_block)
        dict_data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        dict_struct_ptr = builder.bitcast(
            dict_data, ir.PointerType(self.dict_struct_type)
        )
        dict_count = builder.load(builder.gep(dict_struct_ptr, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [dict_count]))

        builder.position_at_end(error_block)
        builder.ret(ir.const_(pyobj_ptr, None))

        # i64 pyobj_len_raw(PyObject* obj) - the same tag dispatch with
        # a RAW result: len() feeds loop bounds (`while i < len(xs)`)
        # and subscripts almost exclusively, and the boxed form made
        # every iteration allocate one int box AND forced the compare
        # through pyobj_lt (one bool box more). Unsupported tags give
        # 0 (valid programs never reach them).
        # private code point walkers (self-contained on purpose: this
        # creator runs during base __init__, before the rawstr family
        # defines rawutf8_cp_count / rawutf8_cp_offset)
        self.pyobj_utf8_cp_count = ir.func_(
            self.module, ir.FunctionType(ir.IntType(64), [i8p, i64], False),
            'pyobj_utf8_cp_count',
        )
        pc = self.pyobj_utf8_cp_count
        builder = ir.builder_(pc.append_basic_block("pucc_entry"))
        pc_cond = pc.append_basic_block("pucc_cond")
        pc_body = pc.append_basic_block("pucc_body")
        pc_done = pc.append_basic_block("pucc_done")
        pc_data, pc_len = pc.args
        pc_i = builder.alloca(i64, None, 'pucc_i')
        pc_n = builder.alloca(i64, None, 'pucc_n')
        builder.store(ir.const_(i64, 0), pc_i)
        builder.store(ir.const_(i64, 0), pc_n)
        builder.branch(pc_cond)
        builder.position_at_end(pc_cond)
        pcv_i = builder.load(pc_i)
        builder.cbranch(
            builder.icmp_signed("<", pcv_i, pc_len), pc_body, pc_done
        )
        builder.position_at_end(pc_body)
        pc_byte = builder.load(builder.gep(pc_data, [pcv_i]))
        pc_lead = builder.icmp_signed(
            "!=",
            builder.and_(pc_byte, ir.const_(ir.IntType(8), 0xC0)),
            ir.const_(ir.IntType(8), 0x80),
        )
        builder.store(
            builder.select(
                pc_lead, builder.add(builder.load(pc_n), one64),
                builder.load(pc_n),
            ),
            pc_n,
        )
        builder.store(builder.add(pcv_i, one64), pc_i)
        builder.branch(pc_cond)
        builder.position_at_end(pc_done)
        builder.ret(builder.load(pc_n))

        # ---- pystr code point side cache --------------------------
        # pyobj_str boxes are {i32 bytes, i8* data} with no cp field;
        # code-point semantics (len / s[i] / s[a:b:c]) would otherwise
        # walk the bytes on EVERY call - O(n) per op, O(n^2) per loop.
        # This table caches {data_ptr, bytes} -> {cp, offs array}.
        # Keyed by the DATA pointer: box buffers are never freed in
        # the dynamic layer (and string literals share immutable
        # constant globals), so a key can never dangle or get reused
        # by different content - NO purge hook is needed (if box
        # freeing is ever introduced, a purge must be added).
        PYOFF_SLOTS = 1024
        pyoff_entry_t = ir.LiteralStructType([i8p, i64, i64, i8p])
        self.pyoff_tab_gv = ir.gvar_(
            self.module, ir.ArrayType(pyoff_entry_t, PYOFF_SLOTS),
            'pyoff_tab'
        )
        self.pyoff_tab_gv.initializer = ir.const_(
            ir.ArrayType(pyoff_entry_t, PYOFF_SLOTS), None
        )

        # {i8* offs, i64 cp} pystr_cp_entry(i8* data, i64 bytes)
        info_t = ir.LiteralStructType([i8p, i64])
        self.pystr_cp_entry = ir.func_(
            self.module,
            ir.FunctionType(info_t, [i8p, i64], False),
            'pystr_cp_entry',
        )
        pf2 = self.pystr_cp_entry
        qe = pf2.append_basic_block("pce_entry")
        qh = pf2.append_basic_block("pce_hash")
        qc = pf2.append_basic_block("pce_cond")
        qb = pf2.append_basic_block("pce_body")
        qn = pf2.append_basic_block("pce_chknull")
        qv = pf2.append_basic_block("pce_valid")
        ql = pf2.append_basic_block("pce_load")
        qa = pf2.append_basic_block("pce_adv")
        qg = pf2.append_basic_block("pce_build")
        qw_c = pf2.append_basic_block("pce_wcond")
        qw_b = pf2.append_basic_block("pce_wbody")
        qw_d = pf2.append_basic_block("pce_wdone")
        qi = pf2.append_basic_block("pce_insert")
        builder = ir.builder_(qe)
        q_data, q_bytes = pf2.args
        builder.branch(qh)

        builder.position_at_end(qh)
        qp = builder.ptrtoint(q_data, i64)
        qh64 = builder.and_(
            builder.xor(
                builder.lshr(qp, ir.const_(i64, 4)),
                builder.lshr(qp, ir.const_(i64, 18)),
            ),
            ir.const_(i64, PYOFF_SLOTS - 1),
        )
        q_base = builder.alloca(i64, None, 'pce_base')
        q_try = builder.alloca(i64, None, 'pce_try')
        builder.store(qh64, q_base)
        builder.store(zero64, q_try)
        builder.branch(qc)

        builder.position_at_end(qc)
        q_t = builder.load(q_try)
        builder.cbranch(
            builder.icmp_signed("<", q_t, ir.const_(i64, 8)), qb, qg
        )

        builder.position_at_end(qb)
        q_slot = builder.and_(
            builder.add(builder.load(q_base), q_t),
            ir.const_(i64, PYOFF_SLOTS - 1),
        )
        q_ent = builder.gep(
            self.pyoff_tab_gv,
            [zero32, builder.trunc(q_slot, i32)],
        )
        q_key = builder.load(builder.gep(q_ent, [zero32, zero32]))
        q_self = builder.icmp_signed("==", q_key, q_data)
        builder.cbranch(q_self, qv, qn)

        builder.position_at_end(qn)
        q_null = builder.icmp_signed("==", q_key, ir.const_(i8p, None))
        builder.cbranch(q_null, qg, qa)

        builder.position_at_end(qv)
        q_elen = builder.load(builder.gep(q_ent, [zero32, one32]))
        builder.cbranch(
            builder.icmp_signed("==", q_elen, q_bytes), ql, qg
        )

        builder.position_at_end(ql)
        q_offs = builder.load(builder.gep(q_ent, [zero32, ir.const_(i32, 3)]))
        q_cp = builder.load(builder.gep(q_ent, [zero32, ir.const_(i32, 2)]))
        q_v0 = builder.insert_value(
            ir.const_(info_t, ir.Undefined), q_offs, 0)
        q_v1 = builder.insert_value(q_v0, q_cp, 1)
        builder.ret(q_v1)

        builder.position_at_end(qa)
        builder.store(builder.add(q_t, one64), q_try)
        builder.branch(qc)

        builder.position_at_end(qg)
        q_cp2 = builder.call(self.pyobj_utf8_cp_count, [q_data, q_bytes])
        q_offs2 = builder.call(
            self.malloc,
            [builder.mul(builder.add(q_cp2, one64), ir.const_(i64, 8))],
        )
        q_offs64 = builder.bitcast(q_offs2, ir.PointerType(i64))
        q_wi = builder.alloca(i64, None, 'pce_wi')
        q_wo = builder.alloca(i64, None, 'pce_wo')
        builder.store(zero64, q_wi)
        builder.store(zero64, q_wo)
        builder.branch(qw_c)

        builder.position_at_end(qw_c)
        q_w = builder.load(q_wi)
        builder.cbranch(
            builder.icmp_signed("<=", q_w, q_cp2), qw_b, qw_d
        )

        builder.position_at_end(qw_b)
        q_o = builder.load(q_wo)
        builder.store(q_o, builder.gep(q_offs64, [q_w]))
        q_lead = builder.load(builder.gep(q_data, [q_o]))
        builder.store(
            builder.add(q_o, self._seq_len_inline(builder, q_lead)), q_wo
        )
        builder.store(builder.add(q_w, one64), q_wi)
        builder.branch(qw_c)

        builder.position_at_end(qw_d)
        builder.branch(qi)

        builder.position_at_end(qi)
        q_ins = builder.gep(
            self.pyoff_tab_gv,
            [zero32, builder.trunc(builder.load(q_base), i32)],
        )
        builder.store(q_data, builder.gep(q_ins, [zero32, zero32]))
        builder.store(q_bytes, builder.gep(q_ins, [zero32, one32]))
        builder.store(q_cp2, builder.gep(q_ins, [zero32, ir.const_(i32, 2)]))
        builder.store(q_offs2, builder.gep(q_ins, [zero32, ir.const_(i32, 3)]))
        q_iv0 = builder.insert_value(
            ir.const_(info_t, ir.Undefined), q_offs2, 0)
        q_iv1 = builder.insert_value(q_iv0, q_cp2, 1)
        builder.ret(q_iv1)

        self.pyobj_len_raw = ir.func_(
            self.module, ir.FunctionType(ir.IntType(64), [pyobj_ptr], False),
            'pyobj_len_raw',
        )
        entry = self.pyobj_len_raw.append_basic_block("rlr_entry")
        list_block = self.pyobj_len_raw.append_basic_block("rlr_list")
        str_check = self.pyobj_len_raw.append_basic_block("rlr_str_chk")
        str_block = self.pyobj_len_raw.append_basic_block("rlr_str")
        dict_check = self.pyobj_len_raw.append_basic_block("rlr_dict_chk")
        dict_block = self.pyobj_len_raw.append_basic_block("rlr_dict")
        zero_block = self.pyobj_len_raw.append_basic_block("rlr_zero")
        builder = ir.builder_(entry)
        obj_arg = self.pyobj_len_raw.args[0]
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.or_(
            builder.icmp_signed("==", tag, ir.const_(i32, 4)),
            builder.icmp_signed("==", tag, ir.const_(i32, 8)),
        )
        builder.cbranch(is_list, list_block, str_check)
        builder.position_at_end(list_block)
        struct_ptr = self._load_list_struct(builder, obj_arg)
        builder.ret(builder.load(builder.gep(struct_ptr, [zero32, zero32])))
        builder.position_at_end(str_check)
        builder.cbranch(
            builder.icmp_signed("==", tag, ir.const_(i32, 2)),
            str_block, dict_check,
        )
        builder.position_at_end(str_block)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(
            data, ir.PointerType(self.pyobj.string_type)
        )
        # code point semantics (Python len): the box stores BYTES, so
        # count the code points (rawutf8_cp_count walks once)
        s_bytes = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
        s_data = builder.load(builder.gep(str_struct, [zero32, one32]))
        info = builder.call(self.pystr_cp_entry, [s_data, s_bytes])
        builder.ret(builder.extract_value(info, 1))
        builder.position_at_end(dict_check)
        builder.cbranch(
            builder.icmp_signed("==", tag, ir.const_(i32, 5)),
            dict_block, zero_block,
        )
        builder.position_at_end(dict_block)
        dict_data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        dict_struct_ptr = builder.bitcast(
            dict_data, ir.PointerType(self.dict_struct_type)
        )
        builder.ret(builder.load(builder.gep(dict_struct_ptr, [zero32, zero32])))
        builder.position_at_end(zero_block)
        builder.ret(ir.const_(i64, 0))

    def _create_list_and_str_method_runtime(self):
        """Runtime for list methods and string methods/equality."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        items_ptr_t = ir.PointerType(pyobj_ptr)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)

        # i1 pyobj_truthy(PyObject* obj) - Python truthiness by type
        self.pyobj_truthy = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr], False), 'pyobj_truthy',

        )
        entry = self.pyobj_truthy.append_basic_block("entry")
        dispatch_block = self.pyobj_truthy.append_basic_block("dispatch")
        int_case = self.pyobj_truthy.append_basic_block("truthy_int")
        float_case = self.pyobj_truthy.append_basic_block("truthy_float")
        str_case = self.pyobj_truthy.append_basic_block("truthy_str")
        list_case = self.pyobj_truthy.append_basic_block("truthy_list")
        dict_case = self.pyobj_truthy.append_basic_block("truthy_dict")
        true_case = self.pyobj_truthy.append_basic_block("truthy_true")
        false_case = self.pyobj_truthy.append_basic_block("truthy_false")
        builder = ir.builder_(entry)
        (obj_arg,) = self.pyobj_truthy.args
        null_obj = ir.const_(pyobj_ptr, None)
        is_null = builder.icmp_signed("==", obj_arg, null_obj)
        builder.cbranch(is_null, false_case, dispatch_block)

        builder.position_at_end(dispatch_block)
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        switch = builder.switch(tag, true_case)
        switch.add_case(ir.const_(i32, 0), int_case)
        switch.add_case(ir.const_(i32, 1), float_case)
        switch.add_case(ir.const_(i32, 2), str_case)
        switch.add_case(ir.const_(i32, 3), int_case)
        switch.add_case(ir.const_(i32, 4), list_case)
        switch.add_case(ir.const_(i32, 8), list_case)
        switch.add_case(ir.const_(i32, 5), dict_case)

        builder.position_at_end(int_case)
        int_val = self._load_number_as_i64(builder, obj_arg)
        builder.ret(builder.icmp_signed("!=", int_val, ir.const_(i64, 0)))

        builder.position_at_end(float_case)
        f64_val = self._load_number_as_f64(builder, obj_arg)
        builder.ret(
            builder.fcmp_ordered("!=", f64_val, ir.const_(ir.DoubleType(), 0.0))
        )

        builder.position_at_end(str_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", str_len, ir.const_(i32, 0)))

        builder.position_at_end(list_case)
        list_struct_ptr = self._load_list_struct(builder, obj_arg)
        list_len = builder.load(builder.gep(list_struct_ptr, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", list_len, ir.const_(i64, 0)))

        builder.position_at_end(dict_case)
        dict_data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        dict_struct_ptr = builder.bitcast(
            dict_data, ir.PointerType(self.dict_struct_type)
        )
        dict_count = builder.load(builder.gep(dict_struct_ptr, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", dict_count, ir.const_(i64, 0)))

        builder.position_at_end(true_case)
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(false_case)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # i1 pyobj_dict_eq(PyObject* a, PyObject* b) - DECLARED here as
        # a forward reference from pyobj_deep_eq; its body is emitted in
        # _emit_dict_ops, where dict_find_probe exists.
        self.pyobj_dict_eq = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr, pyobj_ptr], False), 'pyobj_dict_eq',

        )

        # i1 pyobj_deep_eq(PyObject* a, PyObject* b) - structural equality
        # numeric: value compare (int/bool/float mix); str: memcmp;
        # list: recursive pairwise compare; dict: pyobj_dict_eq (the
        # tag-5 pair used to fall through to `false`, so no two dicts
        # were ever equal - not even d == d)
        self.pyobj_deep_eq = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr, pyobj_ptr], False), 'pyobj_deep_eq',

        )
        entry = self.pyobj_deep_eq.append_basic_block("entry")
        dispatch_block = self.pyobj_deep_eq.append_basic_block("dispatch")
        num_check_block = self.pyobj_deep_eq.append_basic_block("num_check")
        num_float_block = self.pyobj_deep_eq.append_basic_block("num_float")
        num_int_block = self.pyobj_deep_eq.append_basic_block("num_int")
        str_check_block = self.pyobj_deep_eq.append_basic_block("str_check")
        str_body_block = self.pyobj_deep_eq.append_basic_block("str_body")
        list_check_block = self.pyobj_deep_eq.append_basic_block("list_check")
        list_body_block = self.pyobj_deep_eq.append_basic_block("list_body")
        list_len_bad_block = self.pyobj_deep_eq.append_basic_block("list_len_bad")
        false_block = self.pyobj_deep_eq.append_basic_block("eq_false")
        tag_block = self.pyobj_deep_eq.append_basic_block("tag_check")
        builder = ir.builder_(entry)
        arg_a, arg_b = self.pyobj_deep_eq.args
        null_a = builder.icmp_signed("==", arg_a, ir.const_(pyobj_ptr, None))
        null_b = builder.icmp_signed("==", arg_b, ir.const_(pyobj_ptr, None))
        both_null = builder.and_(null_a, null_b)
        either_null = builder.or_(null_a, null_b)
        # None == None is True; None == anything else is False
        null_check_block = self.pyobj_deep_eq.append_basic_block("null_check")
        builder.cbranch(either_null, null_check_block, tag_block)

        builder.position_at_end(null_check_block)
        builder.ret(both_null)

        builder.position_at_end(tag_block)
        tag_a = builder.load(builder.gep(arg_a, [zero32, zero32]))
        tag_b = builder.load(builder.gep(arg_b, [zero32, zero32]))
        same_kind = builder.icmp_signed("==", tag_a, tag_b)
        # numeric tags interoperate (1 == 1.0 == True in Python), so a
        # numeric pair reaches the numeric path even across tags
        both_numeric_eq = builder.and_(
            _is_numeric_tag(builder, tag_a), _is_numeric_tag(builder, tag_b)
        )
        builder.cbranch(
            builder.or_(same_kind, both_numeric_eq), dispatch_block,
            false_block,
        )

        builder.position_at_end(dispatch_block)
        is_num_tag = _is_numeric_tag(builder, tag_a)
        is_str_tag = builder.icmp_signed("==", tag_a, ir.const_(i32, 2))
        is_list_tag = builder.icmp_signed("==", tag_a, ir.const_(i32, 4))
        builder.cbranch(is_num_tag, num_check_block, str_check_block)

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", tag_a, ir.const_(i32, 1)),
            builder.icmp_signed("==", tag_b, ir.const_(i32, 1)),
        )
        builder.cbranch(either_float, num_float_block, num_int_block)

        builder.position_at_end(num_float_block)
        left_f64 = self._load_number_as_f64(builder, arg_a)
        right_f64 = self._load_number_as_f64(builder, arg_b)
        builder.ret(builder.fcmp_ordered("==", left_f64, right_f64))

        builder.position_at_end(num_int_block)
        left_i64 = self._load_number_as_i64(builder, arg_a)
        right_i64 = self._load_number_as_i64(builder, arg_b)
        builder.ret(builder.icmp_signed("==", left_i64, right_i64))

        builder.position_at_end(str_check_block)
        builder.cbranch(is_str_tag, str_body_block, list_check_block)

        builder.position_at_end(str_body_block)
        data_a = builder.load(builder.gep(arg_a, [zero32, one32]))
        struct_a = builder.bitcast(data_a, ir.PointerType(self.pyobj.string_type))
        data_b = builder.load(builder.gep(arg_b, [zero32, one32]))
        struct_b = builder.bitcast(data_b, ir.PointerType(self.pyobj.string_type))
        len_a = builder.load(builder.gep(struct_a, [zero32, zero32]))
        len_b = builder.load(builder.gep(struct_b, [zero32, zero32]))
        chars_a = builder.load(builder.gep(struct_a, [zero32, one32]))
        chars_b = builder.load(builder.gep(struct_b, [zero32, one32]))
        lens_match = builder.icmp_signed("==", len_a, len_b)
        str_cmp_block = self.pyobj_deep_eq.append_basic_block("str_cmp")
        builder.cbranch(lens_match, str_cmp_block, false_block)

        builder.position_at_end(str_cmp_block)
        same_chars = builder.icmp_signed(
            "==",
            builder.call(self.memcmp, [chars_a, chars_b, builder.sext(len_a, i64)]),
            ir.const_(i32, 0),
        )
        builder.ret(same_chars)

        builder.position_at_end(list_check_block)
        # tag-6 instance boxes: identity on the carried instance
        is_inst_tag = builder.icmp_signed("==", tag_a, ir.const_(i32, 6))
        inst_body_block = self.pyobj_deep_eq.append_basic_block("inst_body")
        inst_gate_block = self.pyobj_deep_eq.append_basic_block("inst_gate")
        builder.cbranch(is_list_tag, list_body_block, inst_gate_block)

        builder.position_at_end(inst_gate_block)
        is_dict_tag = builder.icmp_signed("==", tag_a, ir.const_(i32, 5))
        dict_gate_block = self.pyobj_deep_eq.append_basic_block("dict_gate")
        dict_eq_block = self.pyobj_deep_eq.append_basic_block("dict_eq")
        builder.cbranch(is_inst_tag, inst_body_block, dict_gate_block)

        builder.position_at_end(dict_gate_block)
        builder.cbranch(is_dict_tag, dict_eq_block, false_block)

        builder.position_at_end(dict_eq_block)
        builder.ret(builder.call(self.pyobj_dict_eq, [arg_a, arg_b]))

        builder.position_at_end(inst_body_block)
        builder.ret(
            builder.icmp_signed(
                "==",
                builder.call(self.pyobj_instance_ptr, [arg_a]),
                builder.call(self.pyobj_instance_ptr, [arg_b]),
            )
        )

        builder.position_at_end(list_body_block)
        struct_a = self._load_list_struct(builder, arg_a)
        struct_b = self._load_list_struct(builder, arg_b)
        len_a = builder.load(builder.gep(struct_a, [zero32, zero32]))
        len_b = builder.load(builder.gep(struct_b, [zero32, zero32]))
        items_a = builder.load(builder.gep(struct_a, [zero32, ir.const_(i32, 2)]))
        items_b = builder.load(builder.gep(struct_b, [zero32, ir.const_(i32, 2)]))
        lens_match = builder.icmp_signed("==", len_a, len_b)
        builder.cbranch(lens_match, list_len_bad_block, false_block)

        builder.position_at_end(list_len_bad_block)
        diff_ptr = builder.alloca(ir.IntType(1), None, 'deep_diff')
        builder.store(ir.const_(ir.IntType(1), 0), diff_ptr)
        idx_ptr = builder.alloca(i64, None, 'deep_i')
        builder.store(zero64, idx_ptr)
        cond = self.pyobj_deep_eq.append_basic_block("deep_cond")
        inner = self.pyobj_deep_eq.append_basic_block("deep_body")
        after = self.pyobj_deep_eq.append_basic_block("deep_after")
        builder.branch(cond)

        builder.position_at_end(cond)
        current = builder.load(idx_ptr)
        more = builder.icmp_signed("<", current, len_a)
        builder.cbranch(more, inner, after)

        builder.position_at_end(inner)
        item_a = builder.load(builder.gep(items_a, [current]))
        item_b = builder.load(builder.gep(items_b, [current]))
        items_equal = builder.call(self.pyobj_deep_eq, [item_a, item_b])
        differ = builder.not_(items_equal)
        set_diff = self.pyobj_deep_eq.append_basic_block("deep_set_diff")
        keep_going = self.pyobj_deep_eq.append_basic_block("deep_next")
        builder.cbranch(differ, set_diff, keep_going)

        builder.position_at_end(set_diff)
        builder.store(ir.const_(ir.IntType(1), 1), diff_ptr)
        builder.branch(keep_going)

        builder.position_at_end(keep_going)
        builder.store(builder.add(current, one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(after)
        no_diff = builder.not_(builder.load(diff_ptr))
        builder.ret(no_diff)

        builder.position_at_end(false_block)
        builder.ret(ir.const_(ir.IntType(1), 0))

        # i64 pyobj_list_cmp(PObj* a, PObj* b) - Python lexicographic
        # order for the tag-4 branch of ordering comparisons: the first
        # unequal element pair decides (nested lists recurse), a prefix
        # compares smaller. Unorderable element pairs panic TypeError.
        self.pyobj_list_cmp = ir.func_(
            self.module,
            ir.FunctionType(i64, [pyobj_ptr, pyobj_ptr], False),
            'pyobj_list_cmp',
        )
        lc_entry = self.pyobj_list_cmp.append_basic_block("entry")
        b = ir.builder_(lc_entry)
        lc_a, lc_b = self.pyobj_list_cmp.args
        lc_sa = self._load_list_struct(b, lc_a)
        lc_sb = self._load_list_struct(b, lc_b)
        lc_len_a = b.load(b.gep(lc_sa, [zero32, zero32]))
        lc_len_b = b.load(b.gep(lc_sb, [zero32, zero32]))
        lc_items_a = b.load(b.gep(lc_sa, [zero32, ir.const_(i32, 2)]))
        lc_items_b = b.load(b.gep(lc_sb, [zero32, ir.const_(i32, 2)]))
        lc_idx = b.alloca(i64, None, 'lc_i')
        b.store(zero64, lc_idx)
        lc_cond = self.pyobj_list_cmp.append_basic_block("lc_cond")
        lc_body = self.pyobj_list_cmp.append_basic_block("lc_body")
        lc_step = self.pyobj_list_cmp.append_basic_block("lc_step")
        lc_after = self.pyobj_list_cmp.append_basic_block("lc_after")
        b.branch(lc_cond)

        b.position_at_end(lc_cond)
        lc_i = b.load(lc_idx)
        lc_min = b.select(
            b.icmp_signed("<", lc_len_a, lc_len_b), lc_len_a, lc_len_b
        )
        b.cbranch(b.icmp_signed("<", lc_i, lc_min), lc_body, lc_after)

        b.position_at_end(lc_body)
        lc_ea = b.load(b.gep(lc_items_a, [lc_i]))
        lc_eb = b.load(b.gep(lc_items_b, [lc_i]))
        lc_eq = b.call(self.pyobj_deep_eq, [lc_ea, lc_eb])
        lc_neq = self.pyobj_list_cmp.append_basic_block("lc_neq")
        b.cbranch(lc_eq, lc_step, lc_neq)

        # order the unequal pair: nested lists recurse; numerics compare
        # as f64 (int/float mix like Python); strings by memcmp order;
        # anything else is a Python TypeError
        b.position_at_end(lc_neq)
        lc_ta = b.load(b.gep(lc_ea, [zero32, zero32]))
        lc_tb = b.load(b.gep(lc_eb, [zero32, zero32]))
        lc_both_list = b.and_(
            b.icmp_signed("==", lc_ta, ir.const_(i32, 4)),
            b.icmp_signed("==", lc_tb, ir.const_(i32, 4)),
        )
        lc_both_num = b.and_(
            _is_numeric_tag(b, lc_ta), _is_numeric_tag(b, lc_tb)
        )
        lc_both_str = b.and_(
            b.icmp_signed("==", lc_ta, ir.const_(i32, 2)),
            b.icmp_signed("==", lc_tb, ir.const_(i32, 2)),
        )
        lc_as_list = self.pyobj_list_cmp.append_basic_block("lc_as_list")
        lc_not_list = self.pyobj_list_cmp.append_basic_block("lc_not_list")
        b.cbranch(lc_both_list, lc_as_list, lc_not_list)
        b.position_at_end(lc_as_list)
        b.ret(b.call(self.pyobj_list_cmp, [lc_ea, lc_eb]))

        b.position_at_end(lc_not_list)
        lc_as_num = self.pyobj_list_cmp.append_basic_block("lc_as_num")
        lc_not_num = self.pyobj_list_cmp.append_basic_block("lc_not_num")
        b.cbranch(lc_both_num, lc_as_num, lc_not_num)
        b.position_at_end(lc_as_num)
        lc_fa = self._load_number_as_f64(b, lc_ea)
        lc_fb = self._load_number_as_f64(b, lc_eb)
        b.ret(
            b.select(
                b.fcmp_ordered("<", lc_fa, lc_fb),
                ir.const_(i64, -1),
                one64,
            )
        )

        b.position_at_end(lc_not_num)
        lc_as_str = self.pyobj_list_cmp.append_basic_block("lc_as_str")
        lc_bad = self.pyobj_list_cmp.append_basic_block("lc_bad")
        b.cbranch(lc_both_str, lc_as_str, lc_bad)
        b.position_at_end(lc_as_str)
        la, ca = self._pyobj_string_parts(b, lc_ea, zero32, one32)
        lb, cb = self._pyobj_string_parts(b, lc_eb, zero32, one32)
        lc_prefix = b.select(b.icmp_signed("<", la, lb), la, lb)
        lc_order = b.sext(
            b.call(self.memcmp, [ca, cb, b.sext(lc_prefix, i64)]), i64
        )
        lc_str_eq = b.icmp_signed("==", lc_order, zero64)
        lc_final = b.select(
            lc_str_eq,
            b.sub(b.sext(la, i64), b.sext(lb, i64)),
            lc_order,
        )
        b.ret(
            b.select(
                b.icmp_signed("<", lc_final, zero64),
                ir.const_(i64, -1),
                one64,
            )
        )

        b.position_at_end(lc_bad)
        lc_msg = self._create_global_string_with_builder(
            "TypeError: '<' not supported between these operands", b
        )
        self._emit_panic(b, lc_msg)

        b.position_at_end(lc_step)
        b.store(b.add(lc_i, one64), lc_idx)
        b.branch(lc_cond)

        # prefix rule: shorter-is-prefix compares smaller
        b.position_at_end(lc_after)
        b.ret(
            b.select(
                b.icmp_signed("<", lc_len_a, lc_len_b),
                ir.const_(i64, -1),
                b.select(
                    b.icmp_signed(">", lc_len_a, lc_len_b),
                    one64,
                    zero64,
                ),
            )
        )

        self.list_reverse = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'list_reverse'
        )
        builder = ir.builder_(self.list_reverse.append_basic_block("entry"))
        (list_arg,) = self.list_reverse.args
        struct_ptr, length, items = self._list_parts(
            builder, self.list_reverse, list_arg, "rev"
        )
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder,
            self.list_reverse,
            "rev",
            zero64,
            builder.sdiv(length, ir.const_(i64, 2)),
        )
        back = builder.sub(builder.sub(length, one64), builder.load(idx_ptr))
        front_slot = builder.gep(items, [builder.load(idx_ptr)])
        back_slot = builder.gep(items, [back])
        front_val = builder.load(front_slot)
        builder.store(builder.load(back_slot), front_slot)
        builder.store(front_val, back_slot)
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.ret(list_arg)

        # PyObject* list_insert(PyObject* list, PyObject* index, PyObject* item)
        self.list_insert = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'list_insert',

        )
        builder = ir.builder_(self.list_insert.append_basic_block("entry"))
        list_arg, index_arg, item_arg = self.list_insert.args
        struct_ptr, length, items = self._list_parts(
            builder, self.list_insert, list_arg, "ins"
        )
        raw_index = self._load_number_as_i64(builder, index_arg)
        # Python: negative index counts from the end, then clamps to [0, len]
        adjusted = builder.select(
            builder.icmp_signed("<", raw_index, zero64),
            builder.add(raw_index, length),
            raw_index,
        )
        clamped = builder.select(
            builder.icmp_signed("<", adjusted, zero64), zero64, adjusted
        )
        clamped = builder.select(
            builder.icmp_signed(">", clamped, length), length, clamped
        )
        new_length = builder.add(length, one64)
        new_items = builder.call(
            self.malloc, [builder.mul(new_length, ir.const_(i64, 8))]
        )
        new_items = builder.bitcast(new_items, items_ptr_t)
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder, self.list_insert, "ins1", zero64, clamped
        )
        builder.store(
            builder.load(builder.gep(items, [builder.load(idx_ptr)])),
            builder.gep(new_items, [builder.load(idx_ptr)]),
        )
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.store(item_arg, builder.gep(new_items, [clamped]))
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder, self.list_insert, "ins2", clamped, length
        )
        shifted = builder.add(builder.load(idx_ptr), one64)
        builder.store(
            builder.load(builder.gep(items, [builder.load(idx_ptr)])),
            builder.gep(new_items, [shifted]),
        )
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.store(new_length, builder.gep(struct_ptr, [zero32, zero32]))
        # the fresh buffer holds exactly new_length items: capacity must
        # follow, or the next append thinks no grow is needed and writes
        # one slot past the buffer
        builder.store(new_length, builder.gep(struct_ptr, [zero32, one32]))
        builder.store(new_items, builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
        builder.ret(list_arg)

        # PyObject* list_count(PyObject* list, PyObject* item)
        self.list_count = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'list_count',

        )
        builder = ir.builder_(self.list_count.append_basic_block("entry"))
        list_arg, item_arg = self.list_count.args
        struct_ptr, length, items = self._list_parts(
            builder, self.list_count, list_arg, "cnt"
        )
        count_ptr = builder.alloca(i64, None, 'count_acc')
        builder.store(zero64, count_ptr)
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder, self.list_count, "cnt", zero64, length
        )
        candidate = builder.load(builder.gep(items, [builder.load(idx_ptr)]))
        is_match = builder.call(self.pyobj_deep_eq, [candidate, item_arg])
        acc_block = self.list_count.append_basic_block("cnt_acc")
        next_block = self.list_count.append_basic_block("cnt_next")
        builder.cbranch(is_match, acc_block, next_block)
        builder.position_at_end(acc_block)
        builder.store(builder.add(builder.load(count_ptr), one64), count_ptr)
        builder.branch(next_block)
        builder.position_at_end(next_block)
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.ret(builder.call(self.create_int, [builder.load(count_ptr)]))

        # PyObject* list_copy(PyObject* list)
        self.list_copy = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'list_copy'
        )
        builder = ir.builder_(self.list_copy.append_basic_block("entry"))
        (list_arg,) = self.list_copy.args
        struct_ptr, length, items = self._list_parts(
            builder, self.list_copy, list_arg, "cpy"
        )
        new_list = builder.call(self.create_list, [])
        new_struct = self._load_list_struct(builder, new_list)
        empty = builder.icmp_signed("==", length, zero64)
        copy_block = self.list_copy.append_basic_block("cpy_do")
        after_block = self.list_copy.append_basic_block("cpy_after")
        builder.cbranch(empty, after_block, copy_block)

        builder.position_at_end(copy_block)
        fresh_items = builder.call(
            self.malloc, [builder.mul(length, ir.const_(i64, 8))]
        )
        builder.call(
            self.memcpy,
            [
                fresh_items,
                builder.bitcast(items, i8p),
                builder.mul(length, ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        builder.store(length, builder.gep(new_struct, [zero32, zero32]))
        builder.store(length, builder.gep(new_struct, [zero32, one32]))
        builder.store(
            builder.bitcast(fresh_items, items_ptr_t),
            builder.gep(new_struct, [zero32, ir.const_(i32, 2)]),
        )
        builder.branch(after_block)

        builder.position_at_end(after_block)
        builder.ret(new_list)

        # void list_clear(PyObject* list)
        self.list_clear = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [pyobj_ptr], False), 'list_clear'
        )
        builder = ir.builder_(self.list_clear.append_basic_block("entry"))
        struct_ptr = self._load_list_struct(builder, self.list_clear.args[0])
        builder.store(zero64, builder.gep(struct_ptr, [zero32, zero32]))
        builder.ret_void()

        # PyObject* list_sum(PyObject* list)
        self.list_sum = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'list_sum'
        )
        builder = ir.builder_(self.list_sum.append_basic_block("entry"))
        (list_arg,) = self.list_sum.args
        struct_ptr, length, items = self._list_parts(
            builder, self.list_sum, list_arg, "sum"
        )
        acc_ptr = builder.alloca(pyobj_ptr, None, 'sum_acc')
        builder.store(builder.call(self.create_int, [zero64]), acc_ptr)
        idx_ptr, cond, body, done = self._for_i64_loop(i64, 
            builder, self.list_sum, "sum", zero64, length
        )
        item = builder.load(builder.gep(items, [builder.load(idx_ptr)]))
        acc_next = builder.call(self.pyobj_add, [builder.load(acc_ptr), item])
        builder.store(acc_next, acc_ptr)
        self._close_i64_loop(builder, idx_ptr, cond, one64)
        builder.position_at_end(done)
        builder.ret(builder.load(acc_ptr))

        # --- string methods ---

        self.str_upper = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'str_upper'
        )
        self._emit_case_fold(
            ir.builder_(self.str_upper.append_basic_block("entry")),
            self.str_upper,
            True,
            i32, i64, one32, one64, zero32, zero64,
        )
        self.str_lower = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'str_lower'
        )
        self._emit_case_fold(
            ir.builder_(self.str_lower.append_basic_block("entry")),
            self.str_lower,
            False,
            i32, i64, one32, one64, zero32, zero64,
        )

        self.str_isdigit = self._emit_str_pred(
            "str_isdigit", [(ord("0"), ord("9"))], (),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )
        self.str_isalpha = self._emit_str_pred(
            "str_isalpha", [(ord("A"), ord("Z")), (ord("a"), ord("z"))], (),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )
        self.str_isspace = self._emit_str_pred(
            "str_isspace", [], (0x20, 0x09, 0x0A, 0x0B, 0x0C, 0x0D),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )

        self.str_find = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'str_find',

        )
        self._emit_sub_search(
            ir.builder_(self.str_find.append_basic_block("entry")),
            self.str_find,
            False,
            i32, i64, one32, one64, zero32, zero64,
        )
        self.str_rfind = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'str_rfind',

        )
        self._emit_sub_search(
            ir.builder_(self.str_rfind.append_basic_block("entry")),
            self.str_rfind,
            True,
            i32, i64, one32, one64, zero32, zero64,
        )

        # PObj* str_count(PObj* s, PObj* sub) - CPython str.count on a
        # boxed string (see _emit_str_count)
        self.str_count = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'str_count',
        )
        self._emit_str_count(
            ir.builder_(self.str_count.append_basic_block("entry")),
            self.str_count,
            i32, i64, one32, one64, zero32, zero64,
        )

        # PObj* pyobj_count_dispatch(PObj* obj, PObj* item) - .count()
        # with one ABI. The method map bound `count` to list_count
        # outright: on a str receiver list_count read the string box as
        # a list and segfaulted.
        self.pyobj_count_dispatch = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'pyobj_count_dispatch',
        )
        cd_entry = self.pyobj_count_dispatch.append_basic_block("cd_entry")
        cd_str = self.pyobj_count_dispatch.append_basic_block("cd_str")
        cd_list = self.pyobj_count_dispatch.append_basic_block("cd_list")
        cd_ok = self.pyobj_count_dispatch.append_basic_block("cd_list_count")
        cd_bad = self.pyobj_count_dispatch.append_basic_block("cd_bad")
        b = ir.builder_(cd_entry)
        cd_obj, cd_item = self.pyobj_count_dispatch.args
        cd_tag = b.load(b.gep(cd_obj, [zero32, zero32]))
        b.cbranch(
            b.icmp_signed("==", cd_tag, ir.const_(i32, 2)), cd_str, cd_list
        )
        b.position_at_end(cd_str)
        b.ret(b.call(self.str_count, [cd_obj, cd_item]))
        b.position_at_end(cd_list)
        b.cbranch(
            b.icmp_signed("==", cd_tag, ir.const_(i32, 4)), cd_ok, cd_bad
        )
        b.position_at_end(cd_ok)
        b.ret(b.call(self.list_count, [cd_obj, cd_item]))
        b.position_at_end(cd_bad)
        cd_msg = self._create_global_string_with_builder(
            "TypeError: count() is not supported on this object", b
        )
        self._emit_panic(b, cd_msg)
        # PObj* list_index(PObj* list, PObj* item) - first match or -1
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        self.list_index = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            "list_index",

        )
        li_b = ir.builder_(self.list_index.append_basic_block("entry"))
        li_list, li_item = self.list_index.args
        li_struct, li_len, li_items = self._list_parts(
            li_b, self.list_index, li_list, "idx"
        )
        li_found = li_b.alloca(ir.IntType(64), None, "idx_found")
        li_b.store(ir.const_(ir.IntType(64), -1), li_found)
        li_idx, li_cond, li_body, li_done = self._for_i64_loop(
            ir.IntType(64), li_b, self.list_index, "lidx",
            ir.const_(ir.IntType(64), 0), li_len,
        )
        li_cand = li_b.load(li_b.gep(li_items, [li_b.load(li_idx)]))
        li_match = li_b.call(self.pyobj_deep_eq, [li_cand, li_item])
        li_hit = self.list_index.append_basic_block("lidx_hit")
        li_next = self.list_index.append_basic_block("lidx_next")
        li_b.cbranch(li_match, li_hit, li_next)
        li_b.position_at_end(li_hit)
        li_b.store(li_b.load(li_idx), li_found)
        li_b.branch(li_done)
        li_b.position_at_end(li_next)
        self._close_i64_loop(
            li_b, li_idx, li_cond, ir.const_(ir.IntType(64), 1)
        )
        li_b.position_at_end(li_done)
        li_b.ret(li_b.call(self.create_int, [li_b.load(li_found)]))
        self._create_generic_iter_runtime()

    def _create_dict_projection_rt(self, name: str, mode: int):
        """PObj* name(PObj* d): walk live entries into a fresh list.
        mode 0 = [k, v] pair boxes (items), 1 = keys, 2 = values."""
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i64 = ir.IntType(64)
        zero32 = ir.const_(ir.IntType(32), 0)
        one32 = ir.const_(ir.IntType(32), 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)
        fn = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), name,
        )
        b = ir.builder_(fn.append_basic_block("entry"))
        (d_arg,) = fn.args
        _s, _c, used, _m, _t, entries = self._load_dict_parts(
            b, d_arg, zero32, one32
        )
        out = b.call(self.create_list, [])
        idx_ptr, cond, body, done = self._for_i64_loop(
            i64, b, fn, name, zero64, used
        )
        entry_ptr = b.gep(entries, [zero32, b.load(idx_ptr)])
        key = b.load(b.gep(entry_ptr, [zero32, zero32]))
        val = b.load(b.gep(entry_ptr, [zero32, one32]))
        is_live = b.icmp_signed("!=", key, ir.const_(pyobj_ptr, None))
        live_blk = fn.append_basic_block(name + "_live")
        step_blk = fn.append_basic_block(name + "_step")
        b.cbranch(is_live, live_blk, step_blk)
        b.position_at_end(live_blk)
        if mode == 0:
            pair = b.call(self.create_list, [])
            b.call(self.list_append, [pair, key])
            b.call(self.list_append, [pair, val])
            b.call(self.list_append, [out, pair])
        else:
            b.call(self.list_append, [out, key if mode == 1 else val])
        b.branch(step_blk)
        b.position_at_end(step_blk)
        self._close_i64_loop(b, idx_ptr, cond, one64)
        b.position_at_end(done)
        b.ret(out)
        return fn

    def _create_dict_runtime(self):
        """Runtime for dict PyObjects (tag 5): a CPython-style compact dict.

        Insertion-ordered entries array (deleted entries keep their slot
        with a null key) plus a power-of-two open-addressed index table
        whose slots hold entry_index + 1, 0 = empty, -1 = deleted.
        """
        self._emit_dict_core()
        self._emit_dict_ops()
        self._emit_contains_and_set()
        self._emit_io()
        self._emit_dict_views()
        self._emit_dict_update()
        self._emit_slice()
        self._emit_subscript_set_clear()

    def _emit_dict_core(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)
        pyobj_null = ir.const_(pyobj_ptr, None)


        # i64 pyobj_hash(PyObject* obj)
        self.pyobj_hash = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False), 'pyobj_hash'
        )
        entry = self.pyobj_hash.append_basic_block("entry")
        dispatch = self.pyobj_hash.append_basic_block("dispatch")
        int_case = self.pyobj_hash.append_basic_block("hash_int")
        float_case = self.pyobj_hash.append_basic_block("hash_float")
        str_case = self.pyobj_hash.append_basic_block("hash_str")
        zero_case = self.pyobj_hash.append_basic_block("hash_zero")
        builder = ir.builder_(entry)
        (obj_arg,) = self.pyobj_hash.args
        is_null = builder.icmp_signed("==", obj_arg, pyobj_null)
        builder.cbranch(is_null, zero_case, dispatch)

        builder.position_at_end(dispatch)
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        inst_case = self.pyobj_hash.append_basic_block("hash_inst")
        switch = builder.switch(tag, int_case)
        switch.add_case(ir.const_(i32, 1), float_case)
        switch.add_case(ir.const_(i32, 2), str_case)
        switch.add_case(ir.const_(i32, 5), zero_case)
        switch.add_case(ir.const_(i32, 6), inst_case)

        builder.position_at_end(inst_case)
        builder.ret(
            builder.ptrtoint(
                builder.call(self.pyobj_instance_ptr, [obj_arg]), i64
            )
        )

        builder.position_at_end(int_case)
        builder.ret(self._load_number_as_i64(builder, obj_arg))

        builder.position_at_end(float_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        bits = builder.load(builder.bitcast(data, ir.PointerType(i64)))
        # -0.0 must hash like 0.0 (they compare equal); the signed form
        # keeps the literal inside i64 (the .si plane wraps out-of-range
        # hex to the same bits but renders them differently)
        neg_zero = builder.icmp_signed(
            "==", bits, ir.const_(i64, -9223372036854775808)
        )
        builder.ret(builder.select(neg_zero, zero64, bits))

        builder.position_at_end(str_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        # FNV-1a over the bytes
        hash_ptr = builder.alloca(i64, None, 'fnv_h')
        idx_ptr = builder.alloca(i64, None, 'fnv_i')
        # FNV-1a offset basis in signed form (0xCBF29CE484222325
        # exceeds i64::MAX; the .si plane would wrap and render it
        # differently than Python's arbitrary-precision literal)
        builder.store(ir.const_(i64, -3750763034362895579), hash_ptr)
        builder.store(zero64, idx_ptr)
        cond = self.pyobj_hash.append_basic_block("fnv_cond")
        body = self.pyobj_hash.append_basic_block("fnv_body")
        done = self.pyobj_hash.append_basic_block("fnv_done")
        builder.branch(cond)

        builder.position_at_end(cond)
        i_val = builder.load(idx_ptr)
        more = builder.icmp_signed("<", i_val, builder.sext(str_len, i64))
        builder.cbranch(more, body, done)

        builder.position_at_end(body)
        ch = builder.load(builder.gep(chars, [i_val]))
        h_val = builder.load(hash_ptr)
        h_val = builder.xor(h_val, builder.zext(ch, i64))
        h_val = builder.mul(h_val, ir.const_(i64, 0x100000001B3))
        builder.store(h_val, hash_ptr)
        builder.store(builder.add(i_val, one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(done)
        builder.ret(builder.load(hash_ptr))

        builder.position_at_end(zero_case)
        builder.ret(zero64)

        # i64 dict_find_probe(PyObject* d, PyObject* key, i64* out_slot)
        # Returns the entry index of the match, or -1 when the key is
        # absent; out_slot receives the match slot (hit) or the slot to
        # insert into (miss, reusing the first tombstone seen).
        self.dict_find_probe = ir.func_(
            self.module,
            ir.FunctionType(i64, [pyobj_ptr, pyobj_ptr, ir.PointerType(i64)], False), 'dict_find_probe',

        )
        entry = self.dict_find_probe.append_basic_block("entry")
        probe_cond = self.dict_find_probe.append_basic_block("probe_cond")
        probe_body = self.dict_find_probe.append_basic_block("probe_body")
        probe_hit = self.dict_find_probe.append_basic_block("probe_hit")
        probe_empty = self.dict_find_probe.append_basic_block("probe_empty")
        probe_tomb = self.dict_find_probe.append_basic_block("probe_tomb")
        probe_step = self.dict_find_probe.append_basic_block("probe_step")
        builder = ir.builder_(entry)
        dict_arg, key_arg, out_slot_arg = self.dict_find_probe.args
        _, _, _, mask, itable, entries = self._load_dict_parts(builder, dict_arg, zero32, one32)
        hash_val = builder.call(self.pyobj_hash, [key_arg])
        slot_ptr = builder.alloca(i64, None, 'probe_slot')
        tomb_ptr = builder.alloca(i64, None, 'probe_tomb')
        builder.store(builder.and_(hash_val, mask), slot_ptr)
        builder.store(ir.const_(i64, -1), tomb_ptr)
        builder.branch(probe_cond)

        builder.position_at_end(probe_cond)
        slot_val = builder.load(slot_ptr)
        table_val = builder.load(builder.gep(itable, [slot_val]))
        is_empty = builder.icmp_signed("==", table_val, zero64)
        is_tomb = builder.icmp_signed("==", table_val, ir.const_(i64, -1))
        builder.cbranch(is_empty, probe_empty, probe_body)

        builder.position_at_end(probe_empty)
        first_tomb = builder.load(tomb_ptr)
        has_tomb = builder.icmp_signed(">=", first_tomb, zero64)
        use_slot = builder.select(has_tomb, first_tomb, slot_val)
        builder.store(use_slot, out_slot_arg)
        builder.ret(ir.const_(i64, -1))

        builder.position_at_end(probe_body)
        builder.cbranch(is_tomb, probe_tomb, probe_hit)

        builder.position_at_end(probe_tomb)
        first_tomb = builder.load(tomb_ptr)
        no_tomb = builder.icmp_signed("<", first_tomb, zero64)
        builder.store(builder.select(no_tomb, slot_val, first_tomb), tomb_ptr)
        builder.branch(probe_step)

        builder.position_at_end(probe_hit)
        entry_ptr = builder.gep(entries, [zero32, builder.sub(table_val, one64)])
        entry_key = builder.load(builder.gep(entry_ptr, [zero32, zero32]))
        same = builder.call(self.pyobj_deep_eq, [entry_key, key_arg])
        match_block = self.dict_find_probe.append_basic_block("probe_match")
        builder.cbranch(same, match_block, probe_step)

        builder.position_at_end(match_block)
        builder.store(slot_val, out_slot_arg)
        builder.ret(builder.sub(table_val, one64))

        builder.position_at_end(probe_step)
        next_slot = builder.and_(builder.add(builder.load(slot_ptr), one64), mask)
        builder.store(next_slot, slot_ptr)
        builder.branch(probe_cond)

        # void dict_rehash(PyObject* d) - double the table, compact entries
        self.dict_rehash = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr], False), 'dict_rehash',

        )
        entry = self.dict_rehash.append_basic_block("entry")
        scan_cond = self.dict_rehash.append_basic_block("reh_scan_cond")
        scan_body = self.dict_rehash.append_basic_block("reh_scan_body")
        scan_dead = self.dict_rehash.append_basic_block("reh_scan_dead")
        scan_live = self.dict_rehash.append_basic_block("reh_scan_live")
        place_cond = self.dict_rehash.append_basic_block("reh_place_cond")
        scan_done = self.dict_rehash.append_basic_block("reh_scan_done")
        builder = ir.builder_(entry)
        (dict_arg,) = self.dict_rehash.args
        struct_ptr, count, used, mask, itable, entries = self._load_dict_parts(
            builder, dict_arg, zero32, one32
        )
        old_cap = builder.add(mask, one64)
        new_cap = builder.select(
            builder.icmp_signed("==", old_cap, zero64),
            ir.const_(i64, 4),
            builder.mul(old_cap, ir.const_(i64, 2)),
        )
        new_mask = builder.sub(new_cap, one64)
        new_table = builder.call(self.calloc, [new_cap, ir.const_(i64, 8)])
        new_table = builder.bitcast(new_table, ir.PointerType(i64))
        new_entries = builder.call(
            self.malloc, [builder.mul(new_cap, ir.const_(i64, 16))]
        )
        new_entries = builder.bitcast(new_entries, self.dict_entries_ptr_type)
        j_ptr = builder.alloca(i64, None, 'reh_j')
        i_ptr = builder.alloca(i64, None, 'reh_i')
        builder.store(zero64, j_ptr)
        builder.store(zero64, i_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_cond)
        i_val = builder.load(i_ptr)
        more = builder.icmp_signed("<", i_val, used)
        builder.cbranch(more, scan_body, scan_done)

        builder.position_at_end(scan_body)
        old_entry = builder.gep(entries, [zero32, i_val])
        old_key = builder.load(builder.gep(old_entry, [zero32, zero32]))
        is_live = builder.icmp_signed("!=", old_key, pyobj_null)
        builder.cbranch(is_live, scan_live, scan_dead)

        builder.position_at_end(scan_dead)
        builder.store(builder.add(builder.load(i_ptr), one64), i_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_live)
        old_value = builder.load(builder.gep(old_entry, [zero32, one32]))
        key_hash = builder.call(self.pyobj_hash, [old_key])
        place_ptr = builder.alloca(i64, None, 'reh_s')
        builder.store(builder.and_(key_hash, new_mask), place_ptr)
        builder.branch(place_cond)

        builder.position_at_end(place_cond)
        s_val = builder.load(place_ptr)
        taken = builder.icmp_signed(
            "!=", builder.load(builder.gep(new_table, [s_val])), zero64
        )
        place_advance = self.dict_rehash.append_basic_block("reh_place_adv")
        place_do = self.dict_rehash.append_basic_block("reh_place_do")
        builder.cbranch(taken, place_advance, place_do)

        builder.position_at_end(place_advance)
        builder.store(builder.and_(builder.add(s_val, one64), new_mask), place_ptr)
        builder.branch(place_cond)

        # free slot found: place the entry
        builder.position_at_end(place_do)
        j_val = builder.load(j_ptr)
        dest = builder.gep(new_entries, [zero32, j_val])
        builder.store(old_key, builder.gep(dest, [zero32, zero32]))
        builder.store(old_value, builder.gep(dest, [zero32, one32]))
        builder.store(builder.add(j_val, one64), builder.gep(new_table, [s_val]))
        builder.store(builder.add(j_val, one64), j_ptr)
        builder.store(builder.add(builder.load(i_ptr), one64), i_ptr)
        builder.branch(scan_cond)

        builder.position_at_end(scan_done)
        builder.store(new_mask, _dict_field(builder, struct_ptr, 2))
        builder.store(new_table, _dict_field(builder, struct_ptr, 3))
        builder.store(new_entries, _dict_field(builder, struct_ptr, 4))
        builder.store(builder.load(j_ptr), _dict_field(builder, struct_ptr, 1))
        builder.ret_void()

    def _emit_dict_ops(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)
        pyobj_null = ir.const_(pyobj_ptr, None)


        # PyObject* create_dict()
        self.create_dict = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [], False), 'create_dict'
        )
        builder = ir.builder_(self.create_dict.append_basic_block("entry"))
        obj_ptr = builder.call(self.malloc, [ir.const_(i64, 16)])
        obj = builder.bitcast(obj_ptr, pyobj_ptr)
        builder.store(ir.const_(i32, 5), builder.gep(obj, [zero32, zero32]))
        dict_ptr = builder.call(self.malloc, [ir.const_(i64, 40)])
        dict_struct_ptr = builder.bitcast(
            dict_ptr, ir.PointerType(self.dict_struct_type)
        )
        # allocate the initial 4-slot index table and entries array so
        # probing never dereferences null
        initial_table = builder.call(
            self.calloc, [ir.const_(i64, 4), ir.const_(i64, 8)]
        )
        initial_table = builder.bitcast(initial_table, ir.PointerType(i64))
        initial_entries = builder.call(self.malloc, [ir.const_(i64, 64)])
        initial_entries = builder.bitcast(initial_entries, self.dict_entries_ptr_type)
        for field_index, field_value in enumerate(
            [zero64, zero64, ir.const_(i64, 3), initial_table, initial_entries]
        ):
            builder.store(
                field_value,
                builder.gep(
                    dict_struct_ptr,
                    [zero32, ir.const_(i32, field_index)],
                ),
            )
        builder.store(dict_ptr, builder.gep(obj, [zero32, one32]))
        builder.ret(obj)

        # Body of pyobj_dict_eq (declared in _create_list_and_str_method_runtime):
        # same live count, and every live entry of a has its key in b
        # with a deep-equal value. Entries of a are scanned in table
        # order and looked up in b through the hash probe, so the cost
        # stays linear in the size (no cross product of the two tables).
        de_entry = self.pyobj_dict_eq.append_basic_block("entry")
        de_len_block = self.pyobj_dict_eq.append_basic_block("de_len_ok")
        de_cond_block = self.pyobj_dict_eq.append_basic_block("de_cond")
        de_body_block = self.pyobj_dict_eq.append_basic_block("de_body")
        de_live_block = self.pyobj_dict_eq.append_basic_block("de_live")
        de_hit_block = self.pyobj_dict_eq.append_basic_block("de_hit")
        de_step_block = self.pyobj_dict_eq.append_basic_block("de_step")
        de_true_block = self.pyobj_dict_eq.append_basic_block("de_true")
        de_false_block = self.pyobj_dict_eq.append_basic_block("de_false")
        b = ir.builder_(de_entry)
        de_a, de_b = self.pyobj_dict_eq.args
        parts_a = self._load_dict_parts(b, de_a, zero32, one32)
        parts_b = self._load_dict_parts(b, de_b, zero32, one32)
        # field 0 is the live count, field 1 the slots in use
        b.cbranch(
            b.icmp_signed("==", parts_a[1], parts_b[1]),
            de_len_block, de_false_block,
        )

        b.position_at_end(de_len_block)
        de_i = b.alloca(i64, None, 'de_i')
        de_slot = b.alloca(i64, None, 'de_slot')
        b.store(zero64, de_i)
        b.branch(de_cond_block)

        b.position_at_end(de_cond_block)
        de_cur = b.load(de_i)
        b.cbranch(
            b.icmp_signed("<", de_cur, parts_a[2]), de_body_block, de_true_block
        )

        b.position_at_end(de_body_block)
        de_cur = b.load(de_i)
        de_entry_a = b.gep(parts_a[5], [zero32, de_cur])
        de_key = b.load(b.gep(de_entry_a, [zero32, zero32]))
        # a tombstone or empty slot carries a null key
        b.cbranch(
            b.icmp_signed("!=", de_key, pyobj_null), de_live_block, de_step_block
        )

        b.position_at_end(de_live_block)
        de_found = b.call(self.dict_find_probe, [de_b, de_key, de_slot])
        b.cbranch(
            b.icmp_signed(">=", de_found, zero64), de_hit_block, de_false_block
        )

        b.position_at_end(de_hit_block)
        de_value_a = b.load(b.gep(de_entry_a, [zero32, one32]))
        de_entry_b = b.gep(parts_b[5], [zero32, de_found])
        de_value_b = b.load(b.gep(de_entry_b, [zero32, one32]))
        b.cbranch(
            b.call(self.pyobj_deep_eq, [de_value_a, de_value_b]),
            de_step_block, de_false_block,
        )

        b.position_at_end(de_step_block)
        b.store(b.add(b.load(de_i), one64), de_i)
        b.branch(de_cond_block)

        b.position_at_end(de_true_block)
        b.ret(ir.const_(ir.IntType(1), 1))

        b.position_at_end(de_false_block)
        b.ret(ir.const_(ir.IntType(1), 0))

        # PyObject* dict_get_or(PyObject* d, PyObject* key, PyObject* default)
        self.dict_get_or = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'dict_get_or',

        )
        entry = self.dict_get_or.append_basic_block("entry")
        found_block = self.dict_get_or.append_basic_block("found")
        missing_block = self.dict_get_or.append_basic_block("missing")
        builder = ir.builder_(entry)
        dict_arg, key_arg, default_arg = self.dict_get_or.args
        _, _, _, _, _, entries = self._load_dict_parts(builder, dict_arg, zero32, one32)
        out_slot = builder.alloca(i64, None, 'get_slot')
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, missing_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(missing_block)
        builder.ret(default_arg)

        # void dict_set(PyObject* d, PyObject* key, PyObject* value)
        self.dict_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'dict_set',

        )
        entry = self.dict_set.append_basic_block("entry")
        capacity_check = self.dict_set.append_basic_block("capacity_check")
        rehash_block = self.dict_set.append_basic_block("do_rehash")
        probe_block = self.dict_set.append_basic_block("probe")
        replace_block = self.dict_set.append_basic_block("replace")
        insert_block = self.dict_set.append_basic_block("insert")
        builder = ir.builder_(entry)
        dict_arg, key_arg, value_arg = self.dict_set.args
        struct_ptr, count, used, mask, itable, entries = self._load_dict_parts(
            builder, dict_arg, zero32, one32
        )
        out_slot = builder.alloca(i64, None, 'set_slot')
        # grow the table BEFORE probing at 2/3 load, not at full: a
        # table that becomes exactly full after this insert would send
        # the NEXT read-side probe (dict_get on a missing key never
        # grows) circling forever without finding an empty slot
        table_cap = builder.add(mask, one64)
        load_exceeded = builder.icmp_signed(
            ">",
            builder.mul(builder.add(used, one64), ir.const_(i64, 3)),
            builder.mul(table_cap, ir.const_(i64, 2)),
        )
        builder.cbranch(load_exceeded, rehash_block, capacity_check)

        builder.position_at_end(rehash_block)
        builder.call(self.dict_rehash, [dict_arg])
        builder.branch(capacity_check)

        builder.position_at_end(capacity_check)
        builder.branch(probe_block)

        builder.position_at_end(probe_block)
        _, count, used, mask, itable, entries = self._load_dict_parts(builder, dict_arg, zero32, one32)
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, replace_block, insert_block)

        builder.position_at_end(replace_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.store(value_arg, builder.gep(entry_ptr, [zero32, one32]))
        builder.ret_void()

        builder.position_at_end(insert_block)
        _, count, used, mask, itable, entries = self._load_dict_parts(builder, dict_arg, zero32, one32)
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        slot = builder.load(out_slot)
        builder.store(builder.add(used, one64), builder.gep(itable, [slot]))
        entry_ptr = builder.gep(entries, [zero32, used])
        builder.store(key_arg, builder.gep(entry_ptr, [zero32, zero32]))
        builder.store(value_arg, builder.gep(entry_ptr, [zero32, one32]))
        builder.store(builder.add(used, one64), _dict_field(builder, struct_ptr, 1))
        builder.store(builder.add(count, one64), _dict_field(builder, struct_ptr, 0))
        builder.ret_void()

        # PyObject* dict_pop(PyObject* d, PyObject* key, PyObject* def)
        # A null def is the 1-arg pop: a miss panics KeyError. A
        # non-null def returns it on a miss (CPython's 2-arg pop).
        self.dict_pop = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr],
                            False), 'dict_pop',

        )
        entry = self.dict_pop.append_basic_block("entry")
        found_block = self.dict_pop.append_basic_block("found")
        missing_block = self.dict_pop.append_basic_block("missing")
        keyerr_block = self.dict_pop.append_basic_block("pop_keyerr")
        defret_block = self.dict_pop.append_basic_block("pop_defret")
        builder = ir.builder_(entry)
        dict_arg, key_arg, def_arg = self.dict_pop.args
        struct_ptr, count, used, mask, itable, entries = self._load_dict_parts(
            builder, dict_arg, zero32, one32
        )
        out_slot = builder.alloca(i64, None, 'pop_slot')
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, missing_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        removed_value = builder.load(builder.gep(entry_ptr, [zero32, one32]))
        # mark the entry dead and its table slot as a tombstone
        builder.store(pyobj_null, builder.gep(entry_ptr, [zero32, zero32]))
        builder.store(
            ir.const_(i64, -1),
            builder.gep(itable, [builder.load(out_slot)]),
        )
        builder.store(builder.sub(count, one64), _dict_field(builder, struct_ptr, 0))
        builder.ret(removed_value)

        builder.position_at_end(missing_block)
        has_def = builder.icmp_unsigned(
            "!=", def_arg, ir.const_(pyobj_ptr, None)
        )
        builder.cbranch(has_def, defret_block, keyerr_block)

        builder.position_at_end(keyerr_block)
        err_msg = self._create_global_string_with_builder(
            "KeyError: key not found", builder
        )
        self._emit_panic(builder, err_msg)

        builder.position_at_end(defret_block)
        builder.ret(def_arg)

        # PyObject* dict_pop_def(PyObject* d, PyObject* key, PyObject* def)
        # The 2-arg pop domain: a miss ALWAYS returns the default (any
        # value, including null = None). CPython's 2-arg pop never raises.
        self.dict_pop_def = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr],
                            False), 'dict_pop_def',

        )
        entry = self.dict_pop_def.append_basic_block("entry")
        found_block = self.dict_pop_def.append_basic_block("found")
        missing_block = self.dict_pop_def.append_basic_block("missing")
        builder = ir.builder_(entry)
        dict_arg, key_arg, def_arg = self.dict_pop_def.args
        struct_ptr, count, used, mask, itable, entries = self._load_dict_parts(
            builder, dict_arg, zero32, one32
        )
        out_slot = builder.alloca(i64, None, 'popd_slot')
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, missing_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        removed_value = builder.load(builder.gep(entry_ptr, [zero32, one32]))
        # mark the entry dead and its table slot as a tombstone
        builder.store(pyobj_null, builder.gep(entry_ptr, [zero32, zero32]))
        builder.store(
            ir.const_(i64, -1),
            builder.gep(itable, [builder.load(out_slot)]),
        )
        builder.store(builder.sub(count, one64), _dict_field(builder, struct_ptr, 0))
        builder.ret(removed_value)

        builder.position_at_end(missing_block)
        builder.ret(def_arg)

    def _emit_contains_and_set(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)


        # i1 pyobj_contains(PyObject* container, PyObject* item)
        # Membership test for `in` / `not in`: dict keys via probe,
        # str substring via str_find, list elements via pyobj_eq scan.
        self.pyobj_contains = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr, pyobj_ptr], False), 'pyobj_contains',

        )
        entry = self.pyobj_contains.append_basic_block("entry")
        str_check_block = self.pyobj_contains.append_basic_block("str_check")
        list_check_block = self.pyobj_contains.append_basic_block("list_check")
        dict_case = self.pyobj_contains.append_basic_block("dict_case")
        str_case = self.pyobj_contains.append_basic_block("str_case")
        list_case = self.pyobj_contains.append_basic_block("list_case")
        list_cond = self.pyobj_contains.append_basic_block("contains_cond")
        list_body = self.pyobj_contains.append_basic_block("contains_body")
        list_hit = self.pyobj_contains.append_basic_block("contains_hit")
        list_step = self.pyobj_contains.append_basic_block("contains_step")
        list_miss = self.pyobj_contains.append_basic_block("contains_miss")
        type_error = self.pyobj_contains.append_basic_block("type_error")
        builder = ir.builder_(entry)
        container_arg, item_arg = self.pyobj_contains.args
        container_tag = builder.load(
            builder.gep(container_arg, [zero32, zero32])
        )
        is_dict = builder.icmp_signed("==", container_tag, ir.const_(i32, 5))
        builder.cbranch(is_dict, dict_case, str_check_block)

        builder.position_at_end(str_check_block)
        is_str = builder.icmp_signed("==", container_tag, ir.const_(i32, 2))
        builder.cbranch(is_str, str_case, list_check_block)

        builder.position_at_end(list_check_block)
        is_list = builder.or_(
            builder.icmp_signed("==", container_tag, ir.const_(i32, 4)),
            builder.icmp_signed("==", container_tag, ir.const_(i32, 8)),
        )
        builder.cbranch(is_list, list_case, type_error)

        builder.position_at_end(dict_case)
        out_slot = builder.alloca(i64, None, 'contains_slot')
        found = builder.call(
            self.dict_find_probe, [container_arg, item_arg, out_slot]
        )
        builder.ret(builder.icmp_signed(">=", found, zero64))

        builder.position_at_end(str_case)
        found_pyobj = builder.call(self.str_find, [container_arg, item_arg])
        found_idx = self._load_number_as_i64(builder, found_pyobj)
        builder.ret(builder.icmp_signed(">=", found_idx, zero64))

        builder.position_at_end(list_case)
        list_ptr = builder.bitcast(
            builder.load(builder.gep(container_arg, [zero32, one32])),
            ir.PointerType(self.list_struct_type),
        )
        list_len = builder.load(builder.gep(list_ptr, [zero32, zero32]))
        items = builder.load(builder.gep(list_ptr, [zero32, ir.const_(i32, 2)]))
        idx_ptr = builder.alloca(i64, None, 'contains_i')
        builder.store(zero64, idx_ptr)
        builder.branch(list_cond)

        builder.position_at_end(list_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(more, list_body, list_miss)

        builder.position_at_end(list_body)
        elem = builder.load(builder.gep(items, [idx]))
        eq_pyobj = builder.call(self.pyobj_cmp["=="], [elem, item_arg])
        eq_val = self._load_number_as_i64(builder, eq_pyobj)
        is_eq = builder.icmp_signed("!=", eq_val, zero64)
        builder.cbranch(is_eq, list_hit, list_step)

        builder.position_at_end(list_hit)
        builder.ret(ir.const_(ir.IntType(1), 1))

        builder.position_at_end(list_step)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(list_cond)

        builder.position_at_end(list_miss)
        builder.ret(ir.const_(ir.IntType(1), 0))

        builder.position_at_end(type_error)
        err_msg = self._create_global_string_with_builder(
            "TypeError: argument of type is not iterable", builder
        )
        self._emit_panic(builder, err_msg)

        # PObj* create_set() - a tag-8 box wrapping the same {len, cap,
        # items} struct as a list: len/contains/iterate/print read it
        # through the list paths, while ==/</<=... carry set semantics
        self.create_set = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [], False), 'create_set'
        )
        cs_b = ir.builder_(self.create_set.append_basic_block("entry"))
        cs_box_raw = cs_b.call(self.malloc, [ir.const_(i64, 16)])
        cs_box = cs_b.bitcast(cs_box_raw, pyobj_ptr)
        cs_b.store(ir.const_(i32, 8), cs_b.gep(cs_box, [zero32, zero32]))
        cs_st_raw = cs_b.call(self.malloc, [ir.const_(i64, 24)])
        cs_st = cs_b.bitcast(
            cs_st_raw, ir.PointerType(self.list_struct_type)
        )
        cs_b.store(ir.const_(i64, 0), cs_b.gep(cs_st, [zero32, zero32]))
        cs_b.store(ir.const_(i64, 0), cs_b.gep(cs_st, [zero32, one32]))
        cs_b.store(
            ir.const_(
                ir.PointerType(ir.PointerType(self.pyobj.pyobj_type)), None
            ),
            cs_b.gep(cs_st, [zero32, ir.const_(i32, 2)]),
        )
        cs_b.store(cs_st_raw, cs_b.gep(cs_box, [zero32, one32]))
        cs_b.ret(cs_box)

        # PObj* pyobj_set_discard(PObj* set, PObj* item) - remove by
        # value if present, no error when absent (Python set.discard).
        # Scan + in-place shift on the underlying list struct.
        self.pyobj_set_discard = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'pyobj_set_discard',
        )
        sd_entry = self.pyobj_set_discard.append_basic_block("sd_entry")
        sd_loop = self.pyobj_set_discard.append_basic_block("sd_loop")
        sd_shift = self.pyobj_set_discard.append_basic_block("sd_shift")
        sd_done = self.pyobj_set_discard.append_basic_block("sd_done")
        b = ir.builder_(sd_entry)
        sd_set, sd_item = self.pyobj_set_discard.args
        sd_struct = self._load_list_struct(b, sd_set)
        sd_len = b.load(b.gep(sd_struct, [zero32, zero32]))
        b.branch(sd_loop)
        b.position_at_end(sd_loop)
        sd_i_phi = b.phi(i64)
        sd_i_phi.add_incoming(ir.const_(i64, 0), sd_entry)
        sd_in_range = b.icmp_signed("<", sd_i_phi, sd_len)
        sd_body = self.pyobj_set_discard.append_basic_block("sd_body")
        b.cbranch(sd_in_range, sd_body, sd_done)
        b.position_at_end(sd_body)
        sd_items = b.load(b.gep(sd_struct, [zero32, ir.const_(i32, 2)]))
        # mirror list_get: gep steps pointer-sized slots (result stays
        # PObj**), the load is the element pointer
        sd_elem = b.load(b.gep(sd_items, [sd_i_phi]))
        sd_eq = b.call(self.pyobj_deep_eq, [sd_elem, sd_item])
        sd_next = self.pyobj_set_discard.append_basic_block("sd_next")
        b.cbranch(sd_eq, sd_shift, sd_next)
        b.position_at_end(sd_next)
        sd_i_inc = b.add(sd_i_phi, ir.const_(i64, 1))
        sd_i_phi.add_incoming(sd_i_inc, sd_next)
        b.branch(sd_loop)
        b.position_at_end(sd_shift)
        # memmove items[i+1 .. len) down one slot, then len -= 1;
        # reload the items pointer here - the sd_body value does not
        # dominate this block
        sd_items2 = b.load(b.gep(sd_struct, [zero32, ir.const_(i32, 2)]))
        sd_src = b.gep(sd_items2, [b.add(sd_i_phi, ir.const_(i64, 1))])
        sd_dst = b.gep(sd_items2, [sd_i_phi])
        sd_count = b.sub(sd_len, b.add(sd_i_phi, ir.const_(i64, 1)))
        b.call(
            self.memmove,
            [
                b.bitcast(sd_dst, ir.PointerType(ir.IntType(8))),
                b.bitcast(sd_src, ir.PointerType(ir.IntType(8))),
                b.mul(sd_count, ir.const_(i64, 8)),
                ir.const_(ir.IntType(1), 0),
            ],
        )
        b.store(b.sub(sd_len, ir.const_(i64, 1)), b.gep(sd_struct, [zero32, zero32]))
        b.branch(sd_done)
        b.position_at_end(sd_done)
        b.ret(sd_set)

        # PObj* pyobj_set_add(PObj* set, PObj* item) - idempotent add,
        # returning the set (same ABI shape as list_append: void here
        # once broke the converter binary in ways not worth chasing)
        self.pyobj_set_add = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'pyobj_set_add',
        )
        sa_entry = self.pyobj_set_add.append_basic_block("entry")
        sa_add = self.pyobj_set_add.append_basic_block("sa_add")
        sa_done = self.pyobj_set_add.append_basic_block("sa_done")
        b = ir.builder_(sa_entry)
        sa_set, sa_item = self.pyobj_set_add.args
        sa_present = b.call(self.pyobj_contains, [sa_set, sa_item])
        b.cbranch(sa_present, sa_done, sa_add)
        b.position_at_end(sa_add)
        b.call(self.list_append, [sa_set, sa_item])
        b.branch(sa_done)
        b.position_at_end(sa_done)
        b.ret(sa_set)

    def _emit_io(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)



        # PyObject* pyobj_str_conv(PyObject* obj) - str(x) for scalars:
        # int via %lld, float via float_repr (shortest round-trip),
        # bool True/False, str identity, null/None the string "None".
        self.pyobj_str_conv = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'pyobj_str_conv',

        )
        entry = self.pyobj_str_conv.append_basic_block("entry")
        float_case = self.pyobj_str_conv.append_basic_block("str_float")
        bool_case = self.pyobj_str_conv.append_basic_block("str_bool")
        str_case = self.pyobj_str_conv.append_basic_block("str_str")
        fail_case = self.pyobj_str_conv.append_basic_block("str_fail")
        builder = ir.builder_(entry)
        (strconv_arg,) = self.pyobj_str_conv.args
        null_ptr = ir.const_(pyobj_ptr, None)
        is_null = builder.icmp_signed("==", strconv_arg, null_ptr)
        null_block = self.pyobj_str_conv.append_basic_block("str_null")
        dispatch_block = self.pyobj_str_conv.append_basic_block("dispatch")
        builder.cbranch(is_null, null_block, dispatch_block)

        builder.position_at_end(null_block)
        none_ptr = self._create_global_string_with_builder("None", builder)
        builder.ret(
            builder.call(self.create_str, [none_ptr, ir.const_(i32, 4)])
        )

        builder.position_at_end(dispatch_block)
        str_tag = builder.load(builder.gep(strconv_arg, [zero32, zero32]))
        switch = builder.switch(str_tag, fail_case)
        entry_block = self.pyobj_str_conv.append_basic_block("str_int")
        switch.add_case(ir.const_(i32, 0), entry_block)
        switch.add_case(ir.const_(i32, 1), float_case)
        switch.add_case(ir.const_(i32, 2), str_case)
        switch.add_case(ir.const_(i32, 3), bool_case)
        switch.add_case(ir.const_(i32, 6), null_block)

        builder.position_at_end(entry_block)
        int_val = self._load_number_as_i64(builder, strconv_arg)
        int_buf = builder.call(self.malloc, [ir.const_(i64, 24)])
        int_fmt = self._create_global_string_with_builder("%lld", builder)
        builder.call(self.snprintf, [int_buf, ir.const_(i64, 24), int_fmt, int_val])
        int_len = builder.trunc(
            builder.call(self.strlen, [int_buf]), i32
        )
        builder.ret(builder.call(self.create_str, [int_buf, int_len]))

        builder.position_at_end(float_case)
        f64_val = self._load_number_as_f64(builder, strconv_arg)
        fbuf = builder.call(self.float_repr, [f64_val])
        flen = builder.trunc(builder.call(self.strlen, [fbuf]), i32)
        builder.ret(builder.call(self.create_str, [fbuf, flen]))

        builder.position_at_end(str_case)
        builder.ret(strconv_arg)

        builder.position_at_end(bool_case)
        bool_val = self._load_number_as_i64(builder, strconv_arg)
        is_true = builder.icmp_signed("!=", bool_val, zero64)
        true_ptr = self._create_global_string_with_builder("True", builder)
        false_ptr = self._create_global_string_with_builder("False", builder)
        bool_ptr = builder.select(is_true, true_ptr, false_ptr)
        bool_len = builder.select(
            is_true, ir.const_(i32, 4), ir.const_(i32, 5)
        )
        builder.ret(builder.call(self.create_str, [bool_ptr, bool_len]))

        builder.position_at_end(fail_case)
        fail_msg = self._create_global_string_with_builder(
            "TypeError: str() of this type is not supported", builder
        )
        self._emit_panic(builder, fail_msg)

        # PyObject* pyobj_input() - read one line from stdin (EOF -> "")
        # Python input() semantics: trailing newline stripped
        i8p = ir.PointerType(ir.IntType(8))
        self.getchar = ir.func_(
            self.module, ir.FunctionType(i32, [], False), 'getchar'
        )
        if self.realloc is None:
            self.realloc = ir.func_(
                self.module, ir.FunctionType(i8p, [i8p, i64], False), 'realloc'
            )
        self.pyobj_input = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [], False), 'pyobj_input'
        )
        entry = self.pyobj_input.append_basic_block("entry")
        read_cond = self.pyobj_input.append_basic_block("read_cond")
        read_body = self.pyobj_input.append_basic_block("read_body")
        eof_block = self.pyobj_input.append_basic_block("read_eof")
        builder = ir.builder_(entry)
        # dynamic byte buffer, geometric growth
        cap_ptr = builder.alloca(i64, None, 'in_cap')
        len_ptr = builder.alloca(i64, None, 'in_len')
        buf_ptr = builder.alloca(i8p, None, 'in_buf')
        builder.store(ir.const_(i64, 64), cap_ptr)
        builder.store(zero64, len_ptr)
        builder.store(builder.call(self.malloc, [ir.const_(i64, 64)]), buf_ptr)
        builder.branch(read_cond)

        builder.position_at_end(read_cond)
        ch = builder.call(self.getchar, [])
        is_eof = builder.icmp_signed("==", ch, ir.const_(i32, -1))
        is_nl = builder.icmp_signed("==", ch, ir.const_(i32, 10))
        done_read = builder.or_(is_eof, is_nl)
        builder.cbranch(done_read, eof_block, read_body)

        builder.position_at_end(read_body)
        curlen = builder.load(len_ptr)
        curcap = builder.load(cap_ptr)
        needs_grow = builder.icmp_signed("==", curlen, curcap)
        grow_block = self.pyobj_input.append_basic_block("read_grow")
        store_block = self.pyobj_input.append_basic_block("read_store")
        builder.cbranch(needs_grow, grow_block, store_block)

        builder.position_at_end(grow_block)
        newcap = builder.mul(curcap, ir.const_(i64, 2))
        grown = builder.call(
            self.realloc, [builder.load(buf_ptr), newcap]
        )
        builder.store(newcap, cap_ptr)
        builder.store(grown, buf_ptr)
        builder.branch(store_block)

        builder.position_at_end(store_block)
        buf_now = builder.load(buf_ptr)
        len_now = builder.load(len_ptr)
        byte_val = builder.trunc(ch, ir.IntType(8))
        builder.store(
            byte_val, builder.gep(buf_now, [len_now])
        )
        builder.store(builder.add(len_now, one64), len_ptr)
        builder.branch(read_cond)

        builder.position_at_end(eof_block)
        buf_final = builder.load(buf_ptr)
        len_final = builder.load(len_ptr)
        builder.ret(
            builder.call(self.create_str, [buf_final, builder.trunc(len_final, i32)])
        )

        # PyObject* pyobj_read_stdin() - read stdin to EOF (keeps
        # newlines, unlike input(); Rust io::read_to_string)
        self.pyobj_read_stdin = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [], False), 'pyobj_read_stdin'
        )
        entry = self.pyobj_read_stdin.append_basic_block("entry")
        rs_cond = self.pyobj_read_stdin.append_basic_block("rs_cond")
        rs_body = self.pyobj_read_stdin.append_basic_block("rs_body")
        rs_grow = self.pyobj_read_stdin.append_basic_block("rs_grow")
        rs_store = self.pyobj_read_stdin.append_basic_block("rs_store")
        rs_done = self.pyobj_read_stdin.append_basic_block("rs_done")
        builder = ir.builder_(entry)
        cap_ptr = builder.alloca(i64, None, 'rs_cap')
        len_ptr = builder.alloca(i64, None, 'rs_len')
        buf_ptr = builder.alloca(i8p, None, 'rs_buf')
        builder.store(ir.const_(i64, 4096), cap_ptr)
        builder.store(zero64, len_ptr)
        builder.store(builder.call(self.malloc, [ir.const_(i64, 4096)]), buf_ptr)
        builder.branch(rs_cond)

        builder.position_at_end(rs_cond)
        ch = builder.call(self.getchar, [])
        builder.cbranch(
            builder.icmp_signed("==", ch, ir.const_(i32, -1)), rs_done, rs_body
        )

        builder.position_at_end(rs_body)
        curlen = builder.load(len_ptr)
        curcap = builder.load(cap_ptr)
        builder.cbranch(
            builder.icmp_signed("==", curlen, curcap), rs_grow, rs_store
        )

        builder.position_at_end(rs_grow)
        newcap = builder.mul(curcap, ir.const_(i64, 2))
        grown = builder.call(self.realloc, [builder.load(buf_ptr), newcap])
        builder.store(newcap, cap_ptr)
        builder.store(grown, buf_ptr)
        builder.branch(rs_store)

        builder.position_at_end(rs_store)
        builder.store(
            builder.trunc(ch, ir.IntType(8)),
            builder.gep(builder.load(buf_ptr), [builder.load(len_ptr)]),
        )
        builder.store(builder.add(builder.load(len_ptr), one64), len_ptr)
        builder.branch(rs_cond)

        builder.position_at_end(rs_done)
        builder.ret(
            builder.call(
                self.create_str,
                [builder.load(buf_ptr), builder.trunc(builder.load(len_ptr), i32)],
            )
        )

        # PyObject* pyobj_read_file(i8* name, i64 name_len) - read the
        # whole file (Rust fs::read_to_string); missing file panics
        self.fopen = ir.func_(
            self.module,
            ir.FunctionType(i8p, [i8p, i8p], False), 'fopen',

        )
        self.fread = ir.func_(
            self.module,
            ir.FunctionType(i64, [i8p, i64, i64, i8p], False), 'fread',

        )
        self.fseek = ir.func_(
            self.module,
            ir.FunctionType(i32, [i8p, i64, i32], False), 'fseek',

        )
        self.ftell = ir.func_(
            self.module, ir.FunctionType(i64, [i8p], False), 'ftell'
        )
        self.fclose = ir.func_(
            self.module, ir.FunctionType(i32, [i8p], False), 'fclose'
        )
        self.pyobj_read_file = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [i8p, i64], False), 'pyobj_read_file',

        )
        entry = self.pyobj_read_file.append_basic_block("entry")
        open_fail = self.pyobj_read_file.append_basic_block("rf_fail")
        open_ok = self.pyobj_read_file.append_basic_block("rf_ok")
        builder = ir.builder_(entry)
        name_arg, name_len = self.pyobj_read_file.args
        # NUL-terminate the path for libc (rawstr data is unterminated)
        cname = builder.call(self.malloc, [builder.add(name_len, one64)])
        builder.call(self.memcpy, [cname, name_arg, name_len, ir.const_(ir.IntType(1), 0)])
        builder.store(
            ir.const_(ir.IntType(8), 0), builder.gep(cname, [name_len])
        )
        mode_r = self._create_global_string_with_builder("r", builder)
        handle = builder.call(self.fopen, [cname, mode_r])
        builder.cbranch(
            builder.icmp_signed(
                "==", handle, ir.const_(i8p, None)
            ),
            open_fail,
            open_ok,
        )

        builder.position_at_end(open_fail)
        fail_msg = self._create_global_string_with_builder(
            "OSError: cannot open file", builder
        )
        builder.call(self.silu_panic, [fail_msg])
        builder.unreachable()

        builder.position_at_end(open_ok)
        # fseek END / ftell / rewind, then one fread into a sized buffer
        builder.call(
            self.fseek, [handle, zero64, ir.const_(i32, 2)]
        )
        size = builder.call(self.ftell, [handle])
        builder.call(
            self.fseek, [handle, zero64, ir.const_(i32, 0)]
        )
        fbuf = builder.call(self.malloc, [builder.add(size, one64)])
        builder.call(self.fread, [fbuf, one64, size, handle])
        builder.call(self.fclose, [handle])
        builder.ret(
            builder.call(self.create_str, [fbuf, builder.trunc(size, i32)])
        )

        # i1 silu_path_exists(i8* data, i64 len) - Rust Path::exists:
        # fopen/fclose probe; the rawstr data is not NUL-terminated,
        # so the path is copied first
        self.path_exists = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [i8p, i64], False), 'silu_path_exists',

        )
        pe_entry = self.path_exists.append_basic_block("pe_entry")
        pe_yes = self.path_exists.append_basic_block("pe_yes")
        pe_no = self.path_exists.append_basic_block("pe_no")
        peb = ir.builder_(pe_entry)
        pe_data, pe_len = self.path_exists.args
        pe_name = peb.call(self.malloc, [peb.add(pe_len, one64)])
        peb.call(self.memcpy, [pe_name, pe_data, pe_len, ir.const_(ir.IntType(1), 0)])
        peb.store(
            ir.const_(ir.IntType(8), 0), peb.gep(pe_name, [pe_len])
        )
        pe_mode = self._create_global_string_with_builder("r", peb)
        pe_handle = peb.call(self.fopen, [pe_name, pe_mode])
        peb.cbranch(
            peb.icmp_signed(
                "==", pe_handle, ir.const_(i8p, None)
            ),
            pe_no,
            pe_yes,
        )
        peb.position_at_end(pe_yes)
        peb.call(self.fclose, [pe_handle])
        peb.ret(ir.const_(ir.IntType(1), 1))
        peb.position_at_end(pe_no)
        peb.ret(ir.const_(ir.IntType(1), 0))

    def _emit_dict_views(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)


        # void dict_clear_entries(PyObject* d)
        self.dict_clear_entries = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr], False), 'dict_clear_entries',

        )
        entry = self.dict_clear_entries.append_basic_block("entry")
        wipe_cond = self.dict_clear_entries.append_basic_block("wipe_cond")
        wipe_body = self.dict_clear_entries.append_basic_block("wipe_body")
        wipe_done = self.dict_clear_entries.append_basic_block("wipe_done")
        builder = ir.builder_(entry)
        (dict_arg,) = self.dict_clear_entries.args
        struct_ptr, _, _, mask, itable, _ = self._load_dict_parts(builder, dict_arg, zero32, one32)
        builder.store(zero64, _dict_field(builder, struct_ptr, 0))
        builder.store(zero64, _dict_field(builder, struct_ptr, 1))
        wipe_idx = builder.alloca(i64, None, 'wipe_i')
        builder.store(zero64, wipe_idx)
        builder.branch(wipe_cond)

        builder.position_at_end(wipe_cond)
        w_i = builder.load(wipe_idx)
        w_more = builder.icmp_signed("<=", w_i, mask)
        builder.cbranch(w_more, wipe_body, wipe_done)

        builder.position_at_end(wipe_body)
        builder.store(zero64, builder.gep(itable, [w_i]))
        builder.store(builder.add(w_i, one64), wipe_idx)
        builder.branch(wipe_cond)

        builder.position_at_end(wipe_done)
        builder.ret_void()

        # PyObject* dict_setdefault(PyObject* d, PyObject* key, PyObject* default)
        self.dict_setdefault = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'dict_setdefault',

        )
        entry = self.dict_setdefault.append_basic_block("entry")
        found_block = self.dict_setdefault.append_basic_block("found")
        insert_block = self.dict_setdefault.append_basic_block("insert")
        builder = ir.builder_(entry)
        dict_arg, key_arg, default_arg = self.dict_setdefault.args
        _, _, _, _, _, entries = self._load_dict_parts(builder, dict_arg, zero32, one32)
        out_slot = builder.alloca(i64, None, 'sd_slot')
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, insert_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(insert_block)
        builder.call(self.dict_set, [dict_arg, key_arg, default_arg])
        builder.ret(default_arg)

        # dict projections: items -> [k,v] pair boxes, keys -> key
        # boxes, values -> value boxes (Python semantics; routing keys()
        # to the pairs view breaks every `k in d.keys()` scan, which
        # compares the key against a pair box and gets a null back)
        self.dict_items_rt = self._create_dict_projection_rt(
            'dict_items_rt', 0
        )
        self.dict_keys_rt = self._create_dict_projection_rt(
            'dict_keys_rt', 1
        )
        self.dict_values_rt = self._create_dict_projection_rt(
            'dict_values_rt', 2
        )

    def _emit_dict_update(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)
        pyobj_null = ir.const_(pyobj_ptr, None)


        # void dict_update(PyObject* dst, PyObject* src)
        # src may be a dict (copy live entries) or a list of [k, v] pairs
        self.dict_update = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr], False), 'dict_update',

        )
        entry = self.dict_update.append_basic_block("entry")
        src_tag_check = self.dict_update.append_basic_block("upd_src_check")
        src_is_list = self.dict_update.append_basic_block("upd_src_list")
        loop_check = self.dict_update.append_basic_block("upd_check")
        loop_body = self.dict_update.append_basic_block("upd_body")
        loop_step = self.dict_update.append_basic_block("upd_step")
        loop_done = self.dict_update.append_basic_block("upd_done")
        pair_loop_check = self.dict_update.append_basic_block("upd_pair_check")
        pair_loop_body = self.dict_update.append_basic_block("upd_pair_body")
        pair_loop_done = self.dict_update.append_basic_block("upd_pair_done")
        builder = ir.builder_(entry)
        dst_arg, src_arg = self.dict_update.args
        src_tag = builder.load(builder.gep(src_arg, [zero32, zero32]))
        is_list_src = builder.icmp_signed("==", src_tag, ir.const_(i32, 4))
        builder.cbranch(is_list_src, src_is_list, src_tag_check)

        # list source: each item is a [key, value] pair
        builder.position_at_end(src_is_list)
        list_struct_ptr = self._load_list_struct(builder, src_arg)
        pair_count = builder.load(builder.gep(list_struct_ptr, [zero32, zero32]))
        pair_items = builder.load(
            builder.gep(list_struct_ptr, [zero32, ir.const_(i32, 2)])
        )
        pair_idx = builder.alloca(i64, None, 'upd_pair_i')
        builder.store(zero64, pair_idx)
        builder.branch(pair_loop_check)

        builder.position_at_end(pair_loop_check)
        pair_i = builder.load(pair_idx)
        pair_more = builder.icmp_signed("<", pair_i, pair_count)
        builder.cbranch(pair_more, pair_loop_body, pair_loop_done)

        builder.position_at_end(pair_loop_body)
        pair_obj = builder.load(builder.gep(pair_items, [pair_i]))
        pair_struct = self._load_list_struct(builder, pair_obj)
        pair_elems = builder.load(
            builder.gep(pair_struct, [zero32, ir.const_(i32, 2)])
        )
        pair_key = builder.load(builder.gep(pair_elems, [zero64]))
        pair_value = builder.load(builder.gep(pair_elems, [one64]))
        builder.call(self.dict_set, [dst_arg, pair_key, pair_value])
        builder.store(builder.add(pair_i, one64), pair_idx)
        builder.branch(pair_loop_check)

        builder.position_at_end(pair_loop_done)
        builder.ret_void()

        # PObj* pyobj_update_dispatch(PObj* dst, PObj* src) - .update()
        # with one ABI: a set receiver (tag 4) absorbs src's elements
        # idempotently (set.update); anything else forwards to
        # dict_update. Routing a set to dict_update used to write dict
        # fields into the list struct, corrupting it silently.
        self.pyobj_update_dispatch = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'pyobj_update_dispatch',
        )
        ud_entry = self.pyobj_update_dispatch.append_basic_block("entry")
        ud_set = self.pyobj_update_dispatch.append_basic_block("ud_set")
        ud_dict = self.pyobj_update_dispatch.append_basic_block("ud_dict")
        b = ir.builder_(ud_entry)
        ud_dst, ud_src = self.pyobj_update_dispatch.args
        ud_tag = b.load(b.gep(ud_dst, [zero32, zero32]))
        b.cbranch(
            b.or_(
                b.icmp_signed("==", ud_tag, ir.const_(i32, 4)),
                b.icmp_signed("==", ud_tag, ir.const_(i32, 8)),
            ),
            ud_set, ud_dict,
        )
        b.position_at_end(ud_dict)
        b.call(self.dict_update, [ud_dst, ud_src])
        b.ret(ud_dst)
        b.position_at_end(ud_set)
        ud_keys = b.call(self.pyobj_iter_keys, [ud_src])
        ud_total = b.call(self.list_length, [ud_keys])
        ud_i = b.alloca(ir.IntType(64), None, "ud_i")
        b.store(ir.const_(i64, 0), ud_i)
        ud_cond = self.pyobj_update_dispatch.append_basic_block("ud_cond")
        ud_body = self.pyobj_update_dispatch.append_basic_block("ud_body")
        ud_done = self.pyobj_update_dispatch.append_basic_block("ud_done")
        b.branch(ud_cond)
        b.position_at_end(ud_cond)
        ud_cur = b.load(ud_i)
        b.cbranch(
            b.icmp_signed("<", ud_cur, ud_total), ud_body, ud_done
        )
        b.position_at_end(ud_body)
        ud_elem = b.call(
            self.list_get,
            [ud_keys, b.call(self.create_int, [b.load(ud_i)])],
        )
        b.call(self.pyobj_set_add, [ud_dst, ud_elem])
        b.store(b.add(b.load(ud_i), ir.const_(i64, 1)), ud_i)
        b.branch(ud_cond)
        b.position_at_end(ud_done)
        b.ret(ud_dst)

        # dict source: copy all live entries
        builder.position_at_end(src_tag_check)
        _, _, src_used, _, _, src_entries = self._load_dict_parts(builder, src_arg, zero32, one32)
        upd_idx = builder.alloca(i64, None, 'upd_i')
        builder.store(zero64, upd_idx)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        upd_i = builder.load(upd_idx)
        upd_more = builder.icmp_signed("<", upd_i, src_used)
        builder.cbranch(upd_more, loop_body, loop_done)

        builder.position_at_end(loop_body)
        upd_entry = builder.gep(src_entries, [zero32, upd_i])
        upd_key = builder.load(builder.gep(upd_entry, [zero32, zero32]))
        is_live = builder.icmp_signed("!=", upd_key, pyobj_null)
        upd_value = builder.load(builder.gep(upd_entry, [zero32, one32]))
        live_block = self.dict_update.append_basic_block("upd_live")
        builder.cbranch(is_live, live_block, loop_step)

        builder.position_at_end(live_block)
        builder.call(self.dict_set, [dst_arg, upd_key, upd_value])
        builder.branch(loop_step)

        builder.position_at_end(loop_step)
        builder.store(builder.add(upd_i, one64), upd_idx)
        builder.branch(loop_check)

        builder.position_at_end(loop_done)
        builder.ret_void()

    def _emit_slice(self):
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)


        # PyObject* pyobj_str_char_at(PyObject* s, PyObject* index)
        # s[i] on a boxed str: 1-byte string, negative indices adjust,
        # out-of-range panics IndexError (byte semantics, ASCII-exact)
        self.pyobj_str_char_at = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'pyobj_str_char_at',

        )
        entry = self.pyobj_str_char_at.append_basic_block("entry")
        ok_block = self.pyobj_str_char_at.append_basic_block("ok")
        err_block = self.pyobj_str_char_at.append_basic_block("index_error")
        builder = ir.builder_(entry)
        s_arg, index_arg = self.pyobj_str_char_at.args
        raw_index = self._load_number_as_i64(builder, index_arg)
        str_struct = builder.bitcast(
            builder.load(builder.gep(s_arg, [zero32, one32])),
            ir.PointerType(self.pyobj.string_type),
        )
        # code point semantics: the box stores BYTES, so the bounds
        # check and the element access both count code points
        s_bytes = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        info = builder.call(self.pystr_cp_entry, [chars, s_bytes])
        s_len = builder.extract_value(info, 1)
        cp_offs = builder.extract_value(info, 0)
        is_neg = builder.icmp_signed("<", raw_index, zero64)
        index_eff = builder.select(is_neg, builder.add(raw_index, s_len), raw_index)
        in_range = builder.and_(
            builder.icmp_signed(">=", index_eff, zero64),
            builder.icmp_signed("<", index_eff, s_len),
        )
        builder.cbranch(in_range, ok_block, err_block)

        builder.position_at_end(err_block)
        idx_msg = self._create_global_string_with_builder(
            "IndexError: string index out of range", builder
        )
        self._emit_panic(builder, idx_msg)

        builder.position_at_end(ok_block)
        char_off = builder.load(builder.gep(
            builder.bitcast(cp_offs, ir.PointerType(i64)), [index_eff]
        ))
        lead = builder.load(builder.gep(chars, [char_off]))
        seq = self._seq_len_inline(builder, lead)
        char_buf = builder.call(self.malloc, [seq])
        builder.call(
            self.memcpy,
            [char_buf, builder.gep(chars, [char_off]), seq,
             ir.const_(ir.IntType(1), 0)],
        )
        builder.ret(
            builder.call(self.create_str, [char_buf, builder.trunc(seq, i32)])
        )

        # PyObject* pyobj_str_slice(PyObject* s, i64 lo, i64 hi, i64 step,
        #                           i1 has_lo, i1 has_hi)
        # Python slice clamping in both directions; step == 0 panics.
        self.pyobj_str_slice = ir.func_(
            self.module,
            ir.FunctionType(
                pyobj_ptr, [pyobj_ptr, i64, i64, i64, ir.IntType(1), ir.IntType(1)], False
            ), 'pyobj_str_slice',

        )
        entry = self.pyobj_str_slice.append_basic_block("entry")
        step_ok = self.pyobj_str_slice.append_basic_block("step_ok")
        zero_step = self.pyobj_str_slice.append_basic_block("zero_step")
        copy_cond = self.pyobj_str_slice.append_basic_block("copy_cond")
        copy_body = self.pyobj_str_slice.append_basic_block("copy_body")
        copy_done = self.pyobj_str_slice.append_basic_block("copy_done")
        builder = ir.builder_(entry)
        s_arg, lo_arg, hi_arg, step_arg, has_lo, has_hi = self.pyobj_str_slice.args
        str_tag = builder.load(builder.gep(s_arg, [zero32, zero32]))
        not_str = builder.icmp_signed("!=", str_tag, ir.const_(i32, 2))
        tag_error = self.pyobj_str_slice.append_basic_block("tag_error")
        str_case = self.pyobj_str_slice.append_basic_block("str_case")
        builder.cbranch(not_str, tag_error, str_case)

        builder.position_at_end(tag_error)
        tag_msg = self._create_global_string_with_builder(
            "TypeError: only str slicing is supported", builder
        )
        self._emit_panic(builder, tag_msg)

        builder.position_at_end(str_case)
        str_struct = builder.bitcast(
            builder.load(builder.gep(s_arg, [zero32, one32])),
            ir.PointerType(self.pyobj.string_type),
        )
        # code point semantics: clamps and stepping are in code
        # points; each selected element copies its whole UTF-8
        # sequence (1..4 bytes) at a walked byte offset
        s_bytes = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        info = builder.call(self.pystr_cp_entry, [chars, s_bytes])
        s_len = builder.extract_value(info, 1)
        cp_offs64 = builder.bitcast(
            builder.extract_value(info, 0), ir.PointerType(i64)
        )
        step_zero = builder.icmp_signed("==", step_arg, zero64)
        builder.cbranch(step_zero, zero_step, step_ok)

        builder.position_at_end(zero_step)
        step_msg = self._create_global_string_with_builder(
            "ValueError: slice step cannot be zero", builder
        )
        self._emit_panic(builder, step_msg)

        builder.position_at_end(step_ok)
        neg_step = builder.icmp_signed("<", step_arg, zero64)
        len_m1 = builder.sub(s_len, one64)

        lo_eff = self._slice_clamp_bound(
            builder, lo_arg, has_lo,
            builder.select(neg_step, len_m1, zero64),
            zero64,
            builder.select(neg_step, len_m1, s_len),
            s_len, zero64,
        )
        hi_eff = self._slice_clamp_bound(
            builder, hi_arg, has_hi,
            builder.select(neg_step, ir.const_(i64, -1), s_len),
            builder.select(neg_step, ir.const_(i64, -1), zero64),
            builder.select(neg_step, len_m1, s_len),
            s_len, zero64,
        )
        # element count: forward span/step, backward span/(-step)
        fwd_span = builder.sub(hi_eff, lo_eff)
        fwd_count = builder.sdiv(builder.sub(fwd_span, one64), step_arg)
        fwd = builder.select(
            builder.icmp_signed(">", fwd_span, zero64),
            builder.add(fwd_count, one64),
            zero64,
        )
        neg_step_size = builder.sub(zero64, step_arg)
        bwd_span = builder.sub(lo_eff, hi_eff)
        bwd_count = builder.sdiv(builder.sub(bwd_span, one64), neg_step_size)
        bwd = builder.select(
            builder.icmp_signed(">", bwd_span, zero64),
            builder.add(bwd_count, one64),
            zero64,
        )
        count = builder.select(neg_step, bwd, fwd)
        # the byte buffer can never exceed the source's own byte count
        alloc_len = builder.select(
            builder.icmp_signed(">", count, zero64), s_bytes, one64
        )
        out_buf = builder.call(self.malloc, [alloc_len])
        idx_ptr = builder.alloca(i64, None, 'slice_i')
        out_len_ptr = builder.alloca(i64, None, 'slice_out')
        builder.store(zero64, idx_ptr)
        builder.store(zero64, out_len_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, count)
        builder.cbranch(more, copy_body, copy_done)

        builder.position_at_end(copy_body)
        src_cp = builder.add(lo_eff, builder.mul(idx, step_arg))
        src_off = builder.load(builder.gep(cp_offs64, [src_cp]))
        lead = builder.load(builder.gep(chars, [src_off]))
        seq = self._seq_len_inline(builder, lead)
        out_now = builder.load(out_len_ptr)
        builder.call(
            self.memcpy,
            [builder.gep(out_buf, [out_now]),
             builder.gep(chars, [src_off]), seq,
             ir.const_(ir.IntType(1), 0)],
        )
        builder.store(builder.add(out_now, seq), out_len_ptr)
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_done)
        builder.ret(
            builder.call(
                self.create_str,
                [out_buf, builder.trunc(builder.load(out_len_ptr), i32)],
            )
        )

        # PObj* pyobj_list_slice(PObj* lst, i64 lo, hi, step, has_lo, has_hi)
        # the str slice twin over list boxes (elements copied by
        # reference, matching Python's shallow list slicing)
        self.pyobj_list_slice = ir.func_(
            self.module,
            ir.FunctionType(
                pyobj_ptr, [pyobj_ptr, i64, i64, i64, ir.IntType(1), ir.IntType(1)], False
            ), 'pyobj_list_slice',

        )
        entry = self.pyobj_list_slice.append_basic_block("entry")
        lst_case = self.pyobj_list_slice.append_basic_block("lst_case")
        zero_step = self.pyobj_list_slice.append_basic_block("ls_zero_step")
        step_ok = self.pyobj_list_slice.append_basic_block("ls_step_ok")
        copy_cond = self.pyobj_list_slice.append_basic_block("ls_cond")
        copy_body = self.pyobj_list_slice.append_basic_block("ls_body")
        copy_done = self.pyobj_list_slice.append_basic_block("ls_done")
        builder = ir.builder_(entry)
        lst_arg, lo_arg, hi_arg, step_arg, has_lo, has_hi = (
            self.pyobj_list_slice.args
        )
        lst_tag = builder.load(builder.gep(lst_arg, [zero32, zero32]))
        not_list = builder.icmp_signed("!=", lst_tag, ir.const_(i32, 4))
        tag_error = self.pyobj_list_slice.append_basic_block("ls_tag_error")
        builder.cbranch(not_list, tag_error, lst_case)

        builder.position_at_end(tag_error)
        tag_msg = self._create_global_string_with_builder(
            "TypeError: only list slicing is supported", builder
        )
        self._emit_panic(builder, tag_msg)

        builder.position_at_end(lst_case)
        lst_struct = self._load_list_struct(builder, lst_arg)
        n = builder.load(builder.gep(lst_struct, [zero32, zero32]))
        items = builder.load(
            builder.gep(lst_struct, [zero32, ir.const_(i32, 2)])
        )
        step_zero = builder.icmp_signed("==", step_arg, zero64)
        builder.cbranch(step_zero, zero_step, step_ok)

        builder.position_at_end(zero_step)
        step_msg = self._create_global_string_with_builder(
            "ValueError: slice step cannot be zero", builder
        )
        self._emit_panic(builder, step_msg)

        builder.position_at_end(step_ok)
        neg_step = builder.icmp_signed("<", step_arg, zero64)
        n_m1 = builder.sub(n, one64)
        lo_eff = self._slice_clamp_bound(
            builder, lo_arg, has_lo,
            builder.select(neg_step, n_m1, zero64),
            zero64,
            builder.select(neg_step, n_m1, n),
            n, zero64,
        )
        hi_eff = self._slice_clamp_bound(
            builder, hi_arg, has_hi,
            builder.select(neg_step, ir.const_(i64, -1), n),
            builder.select(neg_step, ir.const_(i64, -1), zero64),
            builder.select(neg_step, n_m1, n),
            n, zero64,
        )
        fwd_span = builder.sub(hi_eff, lo_eff)
        fwd_count = builder.sdiv(builder.sub(fwd_span, one64), step_arg)
        fwd = builder.select(
            builder.icmp_signed(">", fwd_span, zero64),
            builder.add(fwd_count, one64),
            zero64,
        )
        neg_step_size = builder.sub(zero64, step_arg)
        bwd_span = builder.sub(lo_eff, hi_eff)
        bwd_count = builder.sdiv(builder.sub(bwd_span, one64), neg_step_size)
        bwd = builder.select(
            builder.icmp_signed(">", bwd_span, zero64),
            builder.add(bwd_count, one64),
            zero64,
        )
        count = builder.select(neg_step, bwd, fwd)
        out = builder.call(self.create_list, [])
        idx_ptr = builder.alloca(i64, None, 'ls_i')
        builder.store(zero64, idx_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, count)
        builder.cbranch(more, copy_body, copy_done)

        builder.position_at_end(copy_body)
        fwd_src = builder.add(lo_eff, builder.mul(idx, step_arg))
        bwd_src = builder.sub(lo_eff, builder.mul(idx, neg_step_size))
        src_index = builder.select(neg_step, bwd_src, fwd_src)
        elem = builder.load(builder.gep(items, [src_index]))
        builder.call(self.list_append, [out, elem])
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_done)
        builder.ret(out)

        # PObj* pyobj_slice_any(PObj* obj, ...) - tag dispatch to the
        # str/list slice twins (the dynamic subscript slice entry)
        self.pyobj_slice_any = ir.func_(
            self.module,
            ir.FunctionType(
                pyobj_ptr, [pyobj_ptr, i64, i64, i64, ir.IntType(1), ir.IntType(1)], False
            ), 'pyobj_slice_any',

        )
        entry = self.pyobj_slice_any.append_basic_block("entry")
        is_str_blk = self.pyobj_slice_any.append_basic_block("sa_str")
        lst_chk_blk = self.pyobj_slice_any.append_basic_block("sa_lst_chk")
        do_list_blk = self.pyobj_slice_any.append_basic_block("sa_do_list")
        sa_error = self.pyobj_slice_any.append_basic_block("sa_error")
        builder = ir.builder_(entry)
        obj_arg = self.pyobj_slice_any.args[0]
        slice_args = list(self.pyobj_slice_any.args)
        obj_tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_str = builder.icmp_signed("==", obj_tag, ir.const_(i32, 2))
        builder.cbranch(is_str, is_str_blk, lst_chk_blk)
        builder.position_at_end(is_str_blk)
        builder.ret(
            builder.call(self.pyobj_str_slice, slice_args)
        )
        builder.position_at_end(lst_chk_blk)
        is_list = builder.icmp_signed("==", obj_tag, ir.const_(i32, 4))
        builder.cbranch(is_list, do_list_blk, sa_error)
        builder.position_at_end(do_list_blk)
        builder.ret(
            builder.call(self.pyobj_list_slice, slice_args)
        )
        builder.position_at_end(sa_error)
        err_msg = self._create_global_string_with_builder(
            "TypeError: object is not sliceable", builder
        )
        self._emit_panic(builder, err_msg)

        # {i32,i8*}* pyobj_subscript(PyObject* obj, PyObject* key)
        # tag dispatch: 4 -> list_get, 5 -> dict_get_or(key, null)
        self.pyobj_subscript = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'pyobj_subscript',

        )
        entry = self.pyobj_subscript.append_basic_block("entry")
        list_block = self.pyobj_subscript.append_basic_block("sub_list")
        str_check = self.pyobj_subscript.append_basic_block("sub_str_check")
        str_do = self.pyobj_subscript.append_basic_block("sub_str_do")
        dict_check = self.pyobj_subscript.append_basic_block("sub_dict_check")
        dict_do = self.pyobj_subscript.append_basic_block("sub_dict_do")
        error_block = self.pyobj_subscript.append_basic_block("sub_error")
        builder = ir.builder_(entry)
        obj_arg, key_arg = self.pyobj_subscript.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.const_(i32, 4))
        builder.cbranch(is_list, list_block, str_check)

        builder.position_at_end(str_check)
        is_str = builder.icmp_signed("==", tag, ir.const_(i32, 2))
        builder.cbranch(is_str, str_do, dict_check)

        builder.position_at_end(str_do)
        builder.ret(builder.call(self.pyobj_str_char_at, [obj_arg, key_arg]))

        builder.position_at_end(list_block)
        builder.ret(builder.call(self.list_get, [obj_arg, key_arg]))

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.const_(i32, 5))
        builder.cbranch(is_dict, dict_do, error_block)

        builder.position_at_end(dict_do)
        # d[k] on a missing key is a KeyError (Python raises, Rust panics);
        # .get() with its default goes through dict_get_or instead
        out_slot = builder.alloca(ir.IntType(64), None, 'sub_slot')
        found = builder.call(self.dict_find_probe, [obj_arg, key_arg, out_slot])
        is_hit = builder.icmp_signed(">=", found, ir.const_(ir.IntType(64), 0))
        hit_block = self.pyobj_subscript.append_basic_block("sub_dict_hit")
        key_error = self.pyobj_subscript.append_basic_block("sub_key_error")
        builder.cbranch(is_hit, hit_block, key_error)

        builder.position_at_end(hit_block)
        _, _, _, _, _, entries = self._load_dict_parts(builder, obj_arg, zero32, one32)
        entry_ptr = builder.gep(
            entries,
            [zero32, found],
        )
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(key_error)
        key_msg = self._create_global_string_with_builder(
            "KeyError: key not found", builder
        )
        self._emit_panic(builder, key_msg)

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "TypeError: object is not subscriptable", builder
        )
        self._emit_panic(builder, error_msg)

    def _emit_subscript_set_clear(self):
        i32 = ir.IntType(32)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)


        # void pyobj_subscript_set(PyObject* obj, PyObject* key, PyObject* value)
        self.pyobj_subscript_set = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr], False), 'pyobj_subscript_set',

        )
        entry = self.pyobj_subscript_set.append_basic_block("entry")
        list_block = self.pyobj_subscript_set.append_basic_block("sub_list")
        dict_check = self.pyobj_subscript_set.append_basic_block("sub_dict_check")
        dict_do = self.pyobj_subscript_set.append_basic_block("sub_dict_do")
        error_block = self.pyobj_subscript_set.append_basic_block("sub_error")
        builder = ir.builder_(entry)
        obj_arg, key_arg, value_arg = self.pyobj_subscript_set.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.const_(i32, 4))
        builder.cbranch(is_list, list_block, dict_check)

        builder.position_at_end(list_block)
        builder.call(self.list_set, [obj_arg, key_arg, value_arg])
        builder.ret_void()

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.const_(i32, 5))
        builder.cbranch(is_dict, dict_do, error_block)

        builder.position_at_end(dict_do)
        builder.call(self.dict_set, [obj_arg, key_arg, value_arg])
        builder.ret_void()

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "TypeError: object does not support item assignment", builder
        )
        self._emit_panic(builder, error_msg)

        # void pyobj_clear(PyObject* obj) - clear() for lists and dicts
        self.pyobj_clear = ir.func_(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr], False), 'pyobj_clear',

        )
        entry = self.pyobj_clear.append_basic_block("entry")
        list_case = self.pyobj_clear.append_basic_block("clear_list")
        dict_check = self.pyobj_clear.append_basic_block("clear_dict_check")
        dict_case = self.pyobj_clear.append_basic_block("clear_dict")
        error_block = self.pyobj_clear.append_basic_block("clear_error")
        builder = ir.builder_(entry)
        obj_arg = self.pyobj_clear.args[0]
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.const_(i32, 4))
        builder.cbranch(is_list, list_case, dict_check)

        builder.position_at_end(list_case)
        builder.call(self.list_clear, [obj_arg])
        builder.ret_void()

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.const_(i32, 5))
        builder.cbranch(is_dict, dict_case, error_block)

        builder.position_at_end(dict_case)
        builder.call(self.dict_clear_entries, [obj_arg])
        builder.ret_void()

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "AttributeError: object has no clear()", builder
        )
        self._emit_panic(builder, error_msg)

    def _create_str_repeat_runtime(self):
        """PyObject* str_repeat(PyObject* s, PyObject* count) - "ab" * 3.

        Built before pyobj_mul so the str*int dispatch can reference it.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)

        self.str_repeat = ir.func_(
            self.module,
            ir.FunctionType(
                ir.PointerType(self.pyobj.pyobj_type),
                [
                    ir.PointerType(self.pyobj.pyobj_type),
                    ir.PointerType(self.pyobj.pyobj_type),
                ], False,
            ), 'str_repeat',

        )
        builder = ir.builder_(self.str_repeat.append_basic_block("entry"))
        s_arg, count_arg = self.str_repeat.args
        data = builder.load(builder.gep(s_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        s_len32 = builder.load(builder.gep(str_struct, [zero32, zero32]))
        s_chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        s_len = builder.sext(s_len32, i64)
        repeat = self._load_number_as_i64(builder, count_arg)
        repeat = builder.select(
            builder.icmp_signed("<", repeat, zero64), zero64, repeat
        )
        total = builder.mul(s_len, repeat)
        buf = builder.call(self.malloc, [builder.add(total, one64)])
        idx_ptr = builder.alloca(i64, None, 'rep_i')
        builder.store(zero64, idx_ptr)
        cond = self.str_repeat.append_basic_block("rep_cond")
        body = self.str_repeat.append_basic_block("rep_body")
        done = self.str_repeat.append_basic_block("rep_done")
        builder.branch(cond)

        builder.position_at_end(cond)
        more = builder.icmp_signed("<", builder.load(idx_ptr), repeat)
        builder.cbranch(more, body, done)

        builder.position_at_end(body)
        offset = builder.mul(builder.load(idx_ptr), s_len)
        dest = builder.gep(buf, [offset])
        builder.call(
            self.memcpy,
            [dest, s_chars, s_len, ir.const_(ir.IntType(1), 0)],
        )
        builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(done)
        builder.store(ir.const_(ir.IntType(8), 0), builder.gep(buf, [total]))
        builder.ret(builder.call(self.create_str, [buf, builder.trunc(total, i32)]))

        # PyObject* list_repeat(PyObject* list, PyObject* count) -
        # [x, y] * n. Self-contained box building: this runs before the
        # list runtime exists, so the struct/box are assembled inline.
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        self.list_repeat = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False),
            'list_repeat',
        )
        b = ir.builder_(self.list_repeat.append_basic_block("entry"))
        l_arg, c_arg = self.list_repeat.args
        l_struct = b.bitcast(
            b.load(b.gep(l_arg, [zero32, one32])),
            ir.PointerType(self.list_struct_type),
        )
        l_len = b.load(b.gep(l_struct, [zero32, zero32]))
        l_items = b.load(b.gep(l_struct, [zero32, ir.const_(ir.IntType(32), 2)]))
        count = self._load_number_as_i64(b, c_arg)
        count = b.select(
            b.icmp_signed("<", count, zero64), zero64, count
        )
        total = b.mul(l_len, count)
        items_buf = b.call(self.malloc, [b.mul(total, ir.const_(i64, 8))])
        # copy the source items `count` times
        ri_ptr = b.alloca(i64, None, 'lrep_i')
        b.store(zero64, ri_ptr)
        rcond = self.list_repeat.append_basic_block("lrep_cond")
        rbody = self.list_repeat.append_basic_block("lrep_body")
        rdone = self.list_repeat.append_basic_block("lrep_done")
        b.branch(rcond)
        b.position_at_end(rcond)
        b.cbranch(
            b.icmp_signed("<", b.load(ri_ptr), count), rbody, rdone
        )
        b.position_at_end(rbody)
        r_off = b.mul(b.load(ri_ptr), l_len)
        r_dest = b.gep(b.bitcast(items_buf, ir.PointerType(pyobj_ptr)), [r_off])
        b.call(
            self.memcpy,
            [b.bitcast(r_dest, ir.PointerType(ir.IntType(8))),
             b.bitcast(l_items, ir.PointerType(ir.IntType(8))),
             b.mul(l_len, ir.const_(i64, 8)), ir.const_(ir.IntType(1), 0)],
        )
        b.store(b.add(b.load(ri_ptr), one64), ri_ptr)
        b.branch(rcond)
        b.position_at_end(rdone)
        box_raw = b.call(self.malloc, [ir.const_(i64, 16)])
        box = b.bitcast(box_raw, ir.PointerType(self.pyobj.pyobj_type))
        b.store(ir.const_(ir.IntType(32), 4), b.gep(box, [zero32, zero32]))
        st_raw = b.call(self.malloc, [ir.const_(i64, 24)])
        st = b.bitcast(st_raw, ir.PointerType(self.list_struct_type))
        b.store(total, b.gep(st, [zero32, zero32]))
        b.store(total, b.gep(st, [zero32, one32]))
        b.store(b.bitcast(items_buf, ir.PointerType(pyobj_ptr)),
                b.gep(st, [zero32, ir.const_(ir.IntType(32), 2)]))
        b.store(st_raw, b.gep(box, [zero32, one32]))
        b.ret(box)

    def _load_list_struct(self, builder, obj):
        """Load the list struct pointer from a list PyObject (tag 4)."""
        data = builder.load(
            builder.gep(
                obj,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)],
            )
        )
        return builder.bitcast(data, ir.PointerType(self.list_struct_type))

    def _create_float_repr_runtime(self):
        """Create i8* float_repr(double): Python-style shortest repr.

        Emits "%.15g"; if strtod of the buffer differs from the input,
        retries with "%.16g" then "%.17g". Appends ".0" when no '.', 'e',
        'n'(nan) or 'i'(inf) appears, so 4.0 keeps its trailing zero.
        Returns a pointer to a heap buffer (string struct, chars field).
        """
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        repr_ty = ir.FunctionType(i8p, [f64], False)
        func = ir.func_(self.module, repr_ty, 'float_repr')

        entry = func.append_basic_block("entry")
        retry = func.append_basic_block("retry")
        more_digits = func.append_basic_block("more_digits")
        finish = func.append_basic_block("finish")

        builder = ir.builder_(entry)
        value = func.args[0]

        # First try: 15 significant digits
        buf1 = self._float_emit_fmt(builder, value, "%.15g")
        ok1 = self._float_parsed_back(builder, value, i8p, buf1)
        builder.cbranch(ok1, finish, retry)

        # Retry with 16 digits
        builder.position_at_end(retry)
        buf2 = self._float_emit_fmt(builder, value, "%.16g")
        ok2 = self._float_parsed_back(builder, value, i8p, buf2)
        builder.cbranch(ok2, finish, more_digits)

        # Retry with 17 digits
        builder.position_at_end(more_digits)
        buf3 = self._float_emit_fmt(builder, value, "%.17g")
        builder.branch(finish)

        # finish: pick the winning buffer, then append ".0" when there
        # is no '.', 'e', 'n' (nan) or 'i' (inf) in the output
        builder.position_at_end(finish)
        buf = builder.phi(i8p)
        buf.add_incoming(buf1, entry)
        buf.add_incoming(buf2, retry)
        buf.add_incoming(buf3, more_digits)

        needs_dot = builder.and_(
            builder.not_(self._float_is_marker(builder, i8p, buf, ".")),
            builder.and_(
                builder.not_(self._float_is_marker(builder, i8p, buf, "e")),
                builder.and_(
                    builder.not_(self._float_is_marker(builder, i8p, buf, "n")),
                    builder.not_(self._float_is_marker(builder, i8p, buf, "i")),
                ),
            ),
        )

        append_block = func.append_basic_block("append_dot")
        done_block = func.append_basic_block("done")
        builder.cbranch(needs_dot, append_block, done_block)

        builder.position_at_end(append_block)
        len1 = builder.call(self.strlen, [buf])
        gep_dot = builder.gep(buf, [len1])
        builder.store(ir.const_(ir.IntType(8), ord(".")), gep_dot)
        gep_zero = builder.gep(buf, [builder.add(len1, ir.const_(ir.IntType(64), 1))])
        builder.store(ir.const_(ir.IntType(8), ord("0")), gep_zero)
        gep_nul = builder.gep(buf, [builder.add(len1, ir.const_(ir.IntType(64), 2))])
        builder.store(ir.const_(ir.IntType(8), 0), gep_nul)
        builder.branch(done_block)

        builder.position_at_end(done_block)
        builder.ret(buf)

        self.float_repr = func

    def _create_numeric_binary_function(
        self,
        func_name,
        int_apply,
        float_apply,
        str_int_apply,
        zero_check,
        overflow_check,
        list_int_apply,
    ) -> ir.Function:
        """Create a pyobj arithmetic function over int/bool/float operands.

        int_apply(builder, left_i64, right_i64) returns the i64 result,
        delivered as an int PyObject. float_apply(builder, left_f64,
        right_f64) returns the double result, delivered as a float
        PyObject. With int_apply None the operation always promotes to
        float (Python true division always returns float).
        str_int_apply(builder, str_obj, int_obj) handles str*int mixes
        (string repetition) when provided. list_int_apply likewise
        handles list*int mixes (sequence repetition) when provided.
        zero_check aborts on zero right operand (Python/Rust division).
        overflow_check aborts on i64 overflow (Rust debug panic semantics).
        """
        func_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ], False,
        )
        func = ir.func_(self.module, func_ty, f'pyobj_{func_name}')

        entry_block = func.append_basic_block("entry")
        num_check_block = func.append_basic_block("num_check")
        float_op_block = func.append_basic_block("float_op")
        # Only create the int block when int operations exist, otherwise
        # it would be an empty (invalid) basic block.
        int_op_block = (
            func.append_basic_block("int_op") if int_apply is not None else None
        )
        str_op_block = (
            func.append_basic_block("str_op") if str_int_apply is not None else None
        )
        error_block = func.append_basic_block("error")
        builder = ir.builder_(entry_block)

        left, right = func.args
        left_tag = builder.load(
            builder.gep(
                left,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        right_tag = builder.load(
            builder.gep(
                right,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        both_numeric = builder.and_(
            _is_numeric_tag(builder, left_tag),
            _is_numeric_tag(builder, right_tag),
        )

        if str_int_apply is not None:
            # str*int / int*str goes to the repetition path first
            str_mix = builder.or_(
                builder.and_(self._tag_is_str(builder, left_tag), self._tag_is_intish(builder, right_tag)),
                builder.and_(self._tag_is_str(builder, right_tag), self._tag_is_intish(builder, left_tag)),
            )
            str_gate_block = func.append_basic_block("str_gate")
            builder.cbranch(str_mix, str_op_block, str_gate_block)

            builder.position_at_end(str_op_block)
            left_is_str = self._tag_is_str(builder, left_tag)
            str_obj = builder.select(left_is_str, left, right)
            int_obj = builder.select(left_is_str, right, left)
            str_result = str_int_apply(builder, str_obj, int_obj)
            builder.ret(str_result)

            builder.position_at_end(str_gate_block)
            if list_int_apply is not None:
                # list*int / int*list repetition, same shape as the
                # str gate
                list_mix = builder.or_(
                    builder.and_(
                        builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 4)),
                        self._tag_is_intish(builder, right_tag),
                    ),
                    builder.and_(
                        builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 4)),
                        self._tag_is_intish(builder, left_tag),
                    ),
                )
                list_op_block = func.append_basic_block("list_op")
                after_list_block = func.append_basic_block("list_gate")
                builder.cbranch(list_mix, list_op_block, after_list_block)
                builder.position_at_end(list_op_block)
                left_is_list = builder.icmp_signed(
                    "==", left_tag, ir.const_(ir.IntType(32), 4)
                )
                list_obj = builder.select(left_is_list, left, right)
                int_obj = builder.select(left_is_list, right, left)
                builder.ret(list_int_apply(builder, list_obj, int_obj))
                builder.position_at_end(after_list_block)
            builder.cbranch(both_numeric, num_check_block, error_block)
        else:
            builder.cbranch(both_numeric, num_check_block, error_block)

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 1)),
        )

        if int_apply is None:
            builder.branch(float_op_block)
        elif float_apply is False:
            # int-only operation (bitwise): float operands are a type
            # error, routed straight to the error block
            builder.cbranch(either_float, error_block, int_op_block)
        else:
            builder.cbranch(either_float, float_op_block, int_op_block)

        builder.position_at_end(float_op_block)
        if float_apply is False:
            # int-only op: the float_op block stays unreachable (the
            # num_check routes floats to the error block); terminate it
            # to keep the block well-formed
            builder.unreachable()
        else:
            left_f64 = self._load_number_as_f64(builder, left)
            right_f64 = self._load_number_as_f64(builder, right)
            if zero_check:
                float_is_zero = builder.fcmp_ordered(
                    "==", right_f64, ir.const_(ir.DoubleType(), 0.0)
                )
                fbad_block = func.append_basic_block("float_zero")
                fok_block = func.append_basic_block("float_ok")
                builder.cbranch(float_is_zero, fbad_block, fok_block)

                builder.position_at_end(fbad_block)
                fmsg = self._create_global_string_with_builder(
                    "ZeroDivisionError: division by zero", builder
                )
                self._emit_panic(builder, fmsg)
                builder.position_at_end(fok_block)

            float_result = float_apply(builder, left_f64, right_f64)
            builder.ret(builder.call(self.create_float, [float_result]))
        if int_apply is not None:
            builder.position_at_end(int_op_block)
            left_i64 = self._load_number_as_i64(builder, left)
            right_i64 = self._load_number_as_i64(builder, right)

            if zero_check:
                int_is_zero = builder.icmp_signed(
                    "==", right_i64, ir.const_(ir.IntType(64), 0)
                )
                zbad_block = func.append_basic_block("int_zero")
                zok_block = func.append_basic_block("int_ok")
                builder.cbranch(int_is_zero, zbad_block, zok_block)

                builder.position_at_end(zbad_block)
                zmsg = self._create_global_string_with_builder(
                    "ZeroDivisionError: division by zero", builder
                )
                self._emit_panic(builder, zmsg)
                builder.position_at_end(zok_block)

            if overflow_check:
                overflow_pair = builder.call(
                    self.overflow_intrinsics[func_name], [left_i64, right_i64]
                )
                int_result = builder.extract_value(overflow_pair, 0)
                overflowed = builder.extract_value(overflow_pair, 1)
                obad_block = func.append_basic_block("int_overflow")
                ook_block = func.append_basic_block("int_no_overflow")
                builder.cbranch(overflowed, obad_block, ook_block)

                builder.position_at_end(obad_block)
                omsg = self._create_global_string_with_builder(
                    f"OverflowError: integer overflow in {func_name}", builder
                )
                self._emit_panic(builder, omsg)
                builder.position_at_end(ook_block)
            else:
                int_result = int_apply(builder, left_i64, right_i64)
            builder.ret(builder.call(self.create_int, [int_result]))

        builder.position_at_end(error_block)
        # type mismatch on an arithmetic op: Python raises TypeError;
        # a silent null here used to surface far away as a null
        # dereference
        nerr = self._create_global_string_with_builder(
            "TypeError: unsupported operand types for " + func_name,
            builder,
        )
        self._emit_panic(builder, nerr)
        return func

    def _create_bool_result_function(self, func_name: str, pred: str) -> ir.Function:
        """Create a comparison function over int/bool/float/str operands.

        pred is one of "==", "!=", "<", "<=", ">", ">=". String
        operands compare via memcmp byte order (UTF-8 byte order equals
        Python code point order) with length breaking ties.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        str_tag = ir.const_(i32, 2)

        func_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ], False,
        )
        func = ir.func_(self.module, func_ty, f'pyobj_{func_name}')

        entry_block = func.append_basic_block("entry")
        num_check_block = func.append_basic_block("num_check")
        float_op_block = func.append_basic_block("float_op")
        int_op_block = func.append_basic_block("int_op")
        error_block = func.append_basic_block("error")
        builder = ir.builder_(entry_block)

        left, right = func.args
        # a null operand (an unboxed None) is not dereferenceable: null
        # == null, null != anything, and no ordering holds against it
        null_ptr = ir.const_(
            ir.PointerType(self.pyobj.pyobj_type), None
        )
        left_null = builder.icmp_signed("==", left, null_ptr)
        right_null = builder.icmp_signed("==", right, null_ptr)
        either_null = builder.or_(left_null, right_null)
        null_block = func.append_basic_block("null_check")
        tags_block = func.append_basic_block("tags")
        builder.cbranch(either_null, null_block, tags_block)

        builder.position_at_end(null_block)
        both_null = builder.and_(left_null, right_null)
        # eq holds on double null; ne holds unless both null; ordering
        # never holds with a null
        if pred == "==":
            null_result = both_null
        elif pred == "!=":
            null_result = builder.not_(both_null)
        else:
            null_result = ir.const_(ir.IntType(1), 0)
        builder.ret(
            builder.call(self.create_bool, [null_result])
        )

        builder.position_at_end(tags_block)
        left_tag = builder.load(
            builder.gep(
                left,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        right_tag = builder.load(
            builder.gep(
                right,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )
        both_numeric = builder.and_(
            _is_numeric_tag(builder, left_tag),
            _is_numeric_tag(builder, right_tag),
        )
        str_check_block = func.append_basic_block("str_check")
        builder.cbranch(both_numeric, num_check_block, str_check_block)

        # str <op> str for every predicate: memcmp byte order (UTF-8
        # byte order equals Python code point order) with the length
        # difference breaking ties, matching rawstr_cmp
        builder.position_at_end(str_check_block)
        # tag-6 instance boxes compare by the INSTANCE they carry (the
        # cell holds {cid, inst}; two boxes of one instance are equal)
        both_inst = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(i32, 6)),
            builder.icmp_signed("==", right_tag, ir.const_(i32, 6)),
        )
        inst_check_block = func.append_basic_block("inst_check")
        str_gate_block = func.append_basic_block("str_gate")
        builder.cbranch(both_inst, inst_check_block, str_gate_block)

        builder.position_at_end(inst_check_block)
        inst_eq = builder.icmp_signed(
            "==",
            builder.call(self.pyobj_instance_ptr, [left]),
            builder.call(self.pyobj_instance_ptr, [right]),
        )
        # == and != answer both identity outcomes (distinct instances
        # are simply unequal); only ordering is undefined on instances
        if pred in ("==", "!="):
            if pred == "!=":
                inst_eq = builder.not_(inst_eq)
            builder.ret(builder.call(self.create_bool, [inst_eq]))
        else:
            inst_op_block = func.append_basic_block("inst_op")
            builder.cbranch(inst_eq, inst_op_block, error_block)
            builder.position_at_end(inst_op_block)
            builder.branch(error_block)

        builder.position_at_end(str_gate_block)
        both_str = builder.and_(
            builder.icmp_signed("==", left_tag, str_tag),
            builder.icmp_signed("==", right_tag, str_tag),
        )
        str_op_block = func.append_basic_block("str_op")
        # tag-4 boxes (list/tuple): structural equality for ==/!= and
        # lexicographic order for </<=/>/>=, matching Python
        list_gate_block = func.append_basic_block("list_gate")
        builder.cbranch(both_str, str_op_block, list_gate_block)

        builder.position_at_end(list_gate_block)
        both_list = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(i32, 4)),
            builder.icmp_signed("==", right_tag, ir.const_(i32, 4)),
        )
        # sets are their own tag: 8x8 pairs take set semantics
        both_set = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(i32, 8)),
            builder.icmp_signed("==", right_tag, ir.const_(i32, 8)),
        )
        list_op_block = func.append_basic_block("list_op")
        set_op_block = func.append_basic_block("set_op")
        after_seq_block = func.append_basic_block("seq_gate")
        dict_gate_block = func.append_basic_block("dict_gate")
        dict_op_block = func.append_basic_block("dict_op")
        builder.cbranch(both_list, list_op_block, after_seq_block)

        builder.position_at_end(list_op_block)
        if pred in ("==", "!="):
            list_eq = builder.call(self.pyobj_deep_eq, [left, right])
            if pred == "!=":
                list_eq = builder.not_(list_eq)
            builder.ret(builder.call(self.create_bool, [list_eq]))
        else:
            # Python lists order lexicographically
            list_order = builder.call(self.pyobj_list_cmp, [left, right])
            list_result = builder.icmp_signed(
                pred, list_order, ir.const_(i64, 0)
            )
            builder.ret(builder.call(self.create_bool, [list_result]))

        builder.position_at_end(after_seq_block)
        # tag-5 pairs: structural equality for ==/!= (order-free, by
        # lookup). They used to fall through to the mixed-type answer:
        # no two dicts were ever equal - not even d == d.
        both_dict = builder.and_(
            builder.icmp_signed("==", left_tag, ir.const_(i32, 5)),
            builder.icmp_signed("==", right_tag, ir.const_(i32, 5)),
        )
        builder.cbranch(both_set, set_op_block, dict_gate_block)

        builder.position_at_end(dict_gate_block)
        builder.cbranch(both_dict, dict_op_block, error_block)

        builder.position_at_end(dict_op_block)
        if pred in ("==", "!="):
            dict_eq = builder.call(self.pyobj_dict_eq, [left, right])
            if pred == "!=":
                dict_eq = builder.not_(dict_eq)
            builder.ret(builder.call(self.create_bool, [dict_eq]))
        else:
            # Python raises on ordering dicts: the shared TypeError
            builder.branch(error_block)

        builder.position_at_end(set_op_block)
        # set semantics: ==/!= by content (order-free, via mutual
        # subset), </<= (proper) subset, >/>= (proper) superset
        a_in_b = builder.call(self.pyobj_set_subset, [left, right])
        b_in_a = builder.call(self.pyobj_set_subset, [right, left])
        if pred == "==":
            set_result = builder.and_(a_in_b, b_in_a)
        elif pred == "!=":
            set_result = builder.not_(builder.and_(a_in_b, b_in_a))
        elif pred == "<=":
            set_result = a_in_b
        elif pred == "<":
            set_result = builder.and_(
                a_in_b, builder.not_(b_in_a)
            )
        elif pred == ">=":
            set_result = b_in_a
        else:  # ">"
            set_result = builder.and_(
                b_in_a, builder.not_(a_in_b)
            )
        builder.ret(builder.call(self.create_bool, [set_result]))

        builder.position_at_end(str_op_block)

        left_len, left_chars = self._pyobj_string_parts(builder, left, zero32, one32)
        right_len, right_chars = self._pyobj_string_parts(builder, right, zero32, one32)
        prefix_len = builder.select(
            builder.icmp_signed("<", left_len, right_len), left_len, right_len
        )
        memcmp_i64 = builder.sext(
            builder.call(
                self.memcmp,
                [left_chars, right_chars, builder.sext(prefix_len, i64)],
            ),
            i64,
        )
        order = builder.select(
            builder.icmp_signed("==", memcmp_i64, ir.const_(i64, 0)),
            builder.sub(builder.sext(left_len, i64), builder.sext(right_len, i64)),
            memcmp_i64,
        )
        str_result = builder.icmp_signed(
            pred, order, ir.const_(i64, 0)
        )
        builder.ret(builder.call(self.create_bool, [str_result]))

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.const_(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.const_(ir.IntType(32), 1)),
        )
        builder.cbranch(either_float, float_op_block, int_op_block)

        builder.position_at_end(float_op_block)
        left_f64 = self._load_number_as_f64(builder, left)
        right_f64 = self._load_number_as_f64(builder, right)
        # Python NaN semantics: != is true whenever == is false
        if pred == "!=":
            float_result = builder.fcmp_unordered(pred, left_f64, right_f64)
        else:
            float_result = builder.fcmp_ordered(pred, left_f64, right_f64)
        builder.ret(builder.call(self.create_bool, [float_result]))

        builder.position_at_end(int_op_block)
        left_i64 = self._load_number_as_i64(builder, left)
        right_i64 = self._load_number_as_i64(builder, right)
        int_result = builder.icmp_signed(pred, left_i64, right_i64)
        builder.ret(builder.call(self.create_bool, [int_result]))

        builder.position_at_end(error_block)
        if pred == "==":
            # mismatched non-null types are simply unequal in Python;
            # returning null here crashes the caller's unbox (the
            # contains scan hit exactly this on a [k, v] pair element)
            builder.ret(
                builder.call(
                    self.create_bool, [ir.const_(ir.IntType(1), 0)]
                )
            )
        elif pred == "!=":
            builder.ret(
                builder.call(
                    self.create_bool, [ir.const_(ir.IntType(1), 1)]
                )
            )
        else:
            # ordering on mismatched/unsupported types: Python raises
            # TypeError; a silent null here used to read as "false"
            oerr = self._create_global_string_with_builder(
                "TypeError: '" + pred + "' not supported between these "
                "operands", builder,
            )
            self._emit_panic(builder, oerr)
        return func

    def _create_comparison_operations(self):
        """Create PyObject comparison operations."""

        predicates = {
            "eq": "==",
            "ne": "!=",
            "lt": "<",
            "le": "<=",
            "gt": ">",
            "ge": ">=",
        }
        # a plain dict (Silu classes reject setattr-created fields);
        # readers go through self.pyobj_cmp
        # i1 pyobj_set_subset(PObj* a, PObj* b) - every element of a is
        # in b (sets are tag-8 boxes over the list struct). Created here
        # so pyobj_eq (first in the loop above) already exists.
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.const_(i32, 0)
        self.pyobj_set_subset = ir.func_(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr, pyobj_ptr], False),
            'pyobj_set_subset',
        )
        b = ir.builder_(self.pyobj_set_subset.append_basic_block("ss_entry"))
        ss_cond = self.pyobj_set_subset.append_basic_block("ss_cond")
        ss_body = self.pyobj_set_subset.append_basic_block("ss_body")
        ss_ic = self.pyobj_set_subset.append_basic_block("ss_ic")
        ss_ib = self.pyobj_set_subset.append_basic_block("ss_ib")
        ss_istep = self.pyobj_set_subset.append_basic_block("ss_istep")
        ss_ostep = self.pyobj_set_subset.append_basic_block("ss_ostep")
        ss_miss = self.pyobj_set_subset.append_basic_block("ss_miss")
        ss_done = self.pyobj_set_subset.append_basic_block("ss_done")
        ss_a, ss_b = self.pyobj_set_subset.args
        a_struct = self._load_list_struct(b, ss_a)
        a_len = b.load(b.gep(a_struct, [zero32, zero32]))
        a_items = b.load(b.gep(a_struct, [zero32, ir.const_(i32, 2)]))
        b_struct = self._load_list_struct(b, ss_b)
        b_len = b.load(b.gep(b_struct, [zero32, zero32]))
        b_items = b.load(b.gep(b_struct, [zero32, ir.const_(i32, 2)]))
        i_ptr = b.alloca(i64, None, "ss_i")
        j_ptr = b.alloca(i64, None, "ss_j")
        b.store(ir.const_(i64, 0), i_ptr)
        b.branch(ss_cond)
        b.position_at_end(ss_cond)
        i_cur = b.load(i_ptr)
        b.cbranch(b.icmp_signed("<", i_cur, a_len), ss_body, ss_done)
        b.position_at_end(ss_body)
        a_elem = b.load(b.gep(a_items, [i_cur]))
        b.store(ir.const_(i64, 0), j_ptr)
        b.branch(ss_ic)
        b.position_at_end(ss_ic)
        j_cur = b.load(j_ptr)
        b.cbranch(b.icmp_signed("<", j_cur, b_len), ss_ib, ss_miss)
        b.position_at_end(ss_ib)
        b_elem = b.load(b.gep(b_items, [j_cur]))
        eq_i1 = b.call(self.pyobj_deep_eq, [a_elem, b_elem])
        b.cbranch(eq_i1, ss_ostep, ss_istep)
        b.position_at_end(ss_istep)
        b.store(b.add(j_cur, ir.const_(i64, 1)), j_ptr)
        b.branch(ss_ic)
        b.position_at_end(ss_ostep)
        b.store(b.add(i_cur, ir.const_(i64, 1)), i_ptr)
        b.branch(ss_cond)
        b.position_at_end(ss_miss)
        b.ret(ir.const_(ir.IntType(1), 0))
        b.position_at_end(ss_done)
        b.ret(ir.const_(ir.IntType(1), 1))

        # i1 pyobj_str_eq_cstr(PObj* obj, i8* cstr, i64 clen) - a box
        # compared against a string constant with ZERO allocation:
        # non-string/null boxes are simply unequal (exactly pyobj_eq's
        # mixed-type answer), strings compare by length + memcmp. The
        # IR-tree dispatch shape (`node[0] == "assign"`) runs millions
        # of times in the self-hosted converter; the boxed pyobj_eq
        # path allocated one never-freed bool per comparison.
        i8p = ir.PointerType(ir.IntType(8))
        self.pyobj_str_eq_cstr = ir.func_(
            self.module,
            ir.FunctionType(
                ir.IntType(1), [pyobj_ptr, i8p, ir.IntType(64)], False
            ),
            'pyobj_str_eq_cstr',
        )
        sec_entry = self.pyobj_str_eq_cstr.append_basic_block("sec_entry")
        sec_nn = self.pyobj_str_eq_cstr.append_basic_block("sec_nn")
        sec_len_ok = self.pyobj_str_eq_cstr.append_basic_block("sec_len_ok")
        sec_mem = self.pyobj_str_eq_cstr.append_basic_block("sec_mem")
        sec_out = self.pyobj_str_eq_cstr.append_basic_block("sec_out")
        cb = ir.builder_(sec_entry)
        sec_obj, sec_cdata, sec_clen = self.pyobj_str_eq_cstr.args
        # null boxes (IR optional slots) are simply unequal - pyobj_eq
        # answers None == "x" as False; the tag load must never touch a
        # null pointer, so the checks are separate blocks (LLVM's and_
        # evaluates both operands - no short-circuit)
        cb.cbranch(
            cb.icmp_signed("!=", sec_obj, ir.const_(pyobj_ptr, None)),
            sec_nn, sec_out,
        )
        cb.position_at_end(sec_nn)
        sec_is_str = cb.icmp_signed(
            "==", cb.load(cb.gep(sec_obj, [zero32, zero32])),
            ir.const_(i32, 2),
        )
        cb.cbranch(sec_is_str, sec_len_ok, sec_out)
        cb.position_at_end(sec_len_ok)
        sec_len32, sec_chars = self._pyobj_string_parts(
            cb, sec_obj, zero32, ir.const_(i32, 1)
        )
        cb.cbranch(
            cb.icmp_signed(
                "==", cb.sext(sec_len32, ir.IntType(64)), sec_clen
            ),
            sec_mem, sec_out,
        )
        cb.position_at_end(sec_mem)
        sec_m = cb.call(self.memcmp, [sec_chars, sec_cdata, sec_clen])
        sec_eq = cb.icmp_signed("==", sec_m, ir.const_(i32, 0))
        cb.branch(sec_out)
        cb.position_at_end(sec_out)
        sec_r = cb.phi(ir.IntType(1))
        sec_r.add_incoming(ir.const_(ir.IntType(1), 0), sec_entry)
        sec_r.add_incoming(ir.const_(ir.IntType(1), 0), sec_nn)
        sec_r.add_incoming(ir.const_(ir.IntType(1), 0), sec_len_ok)
        sec_r.add_incoming(sec_eq, sec_mem)
        cb.ret(sec_r)

        self.pyobj_cmp = {}
        for name, pred in predicates.items():
            self.pyobj_cmp[pred] = self._create_bool_result_function(name, pred)


    def _create_less_than_comparison(self, left: ir.Value, right: ir.Value) -> ir.Value:
        """Less-than over int/float operands, used by loop conditions."""
        return self.current_builder.call(self.pyobj_cmp["<"], [left, right])

    def _create_unary_minus(self, operand: ir.Value) -> ir.Value:
        """Unary minus over int/bool/float PyObjects."""
        builder = self.current_builder
        tag = builder.load(
            builder.gep(
                operand,
                [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)],
            )
        )

        is_float = builder.icmp_signed("==", tag, ir.const_(ir.IntType(32), 1))
        is_numeric = _is_numeric_tag(builder, tag)

        float_block = self.current_function.append_basic_block("unary_minus_float")
        int_check_block = self.current_function.append_basic_block(
            "unary_minus_int_chk"
        )
        int_block = self.current_function.append_basic_block("unary_minus_int")
        error_block = self.current_function.append_basic_block("unary_minus_error")
        merge_block = self.current_function.append_basic_block("unary_minus_merge")
        builder.cbranch(is_float, float_block, int_check_block)

        # Float negation - fmul by -1.0 keeps -0.0's sign bit
        # (0.0 - 0.0 evaluates to +0.0)
        builder.position_at_end(float_block)
        f64_val = self._load_number_as_f64(builder, operand)
        float_result = builder.call(
            self.create_float,
            [builder.fmul(f64_val, ir.const_(ir.DoubleType(), -1.0))],
        )
        builder.branch(merge_block)

        # Int/bool negation
        builder.position_at_end(int_check_block)
        builder.cbranch(is_numeric, int_block, error_block)

        builder.position_at_end(int_block)
        i64_val = self._load_number_as_i64(builder, operand)
        int_result = builder.call(
            self.create_int,
            [builder.sub(ir.const_(ir.IntType(64), 0), i64_val)],
        )
        builder.branch(merge_block)

        # Error case
        builder.position_at_end(error_block)
        null_result = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
        builder.branch(merge_block)

        # Merge block with PHI node
        builder.position_at_end(merge_block)
        phi = builder.phi(ir.PointerType(self.pyobj.pyobj_type))
        phi.add_incoming(float_result, float_block)
        phi.add_incoming(int_result, int_block)
        phi.add_incoming(null_result, error_block)

        return phi

    def _create_overflow_intrinsics(self):
        """Create LLVM overflow detection intrinsics."""

        # llvm.sadd.with.overflow.i64 - signed add with overflow detection
        overflow_ty = ir.LiteralStructType([ir.IntType(64), ir.IntType(1)])  # {i64, i1}
        sadd_overflow_ty = ir.FunctionType(
            overflow_ty, [ir.IntType(64), ir.IntType(64)], False
        )
        self.sadd_overflow = ir.func_(
            self.module, sadd_overflow_ty, 'llvm.sadd.with.overflow.i64'
        )

        # signed sub and mul with overflow detection (Rust panic semantics)
        self.ssub_overflow = ir.func_(
            self.module, sadd_overflow_ty, 'llvm.ssub.with.overflow.i64'
        )
        self.smul_overflow = ir.func_(
            self.module, sadd_overflow_ty, 'llvm.smul.with.overflow.i64'
        )
        self.overflow_intrinsics = {
            "sub": self.ssub_overflow,
            "mul": self.smul_overflow,
        }

    def _str_global_name(self, string_content: str) -> str:
        """Content-addressed name for a string constant global (P6).

        ASCII letters, digits and '.' pass through; every other UTF-8
        byte becomes '_' + two lowercase hex digits. '_' itself is
        escaped, so distinct contents always map to distinct names
        (the encoding is injective - no collision suffixes are needed
        for *different* contents). Duplicate contents get a '~N'
        suffix decided by the caller; '~' can never occur in an
        escaped name, so suffixed names never collide with plain ones.
        """
        safe = ("abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.")
        hexd = "0123456789abcdef"

        def esc(b: int, safe: str, hexd: str) -> str:
            if chr(b) in safe:
                return chr(b)
            return "_" + hexd[b // 16] + hexd[b % 16]

        parts: list[str] = ["str."]
        for ch in string_content:
            cp = ord(ch)
            if cp < 0x80:
                parts.append(esc(cp, safe, hexd))
            elif cp < 0x800:
                parts.append(esc(0xC0 | (cp // 64), safe, hexd))
                parts.append(esc(0x80 | (cp & 0x3F), safe, hexd))
            elif cp < 0x10000:
                parts.append(esc(0xE0 | (cp // 4096), safe, hexd))
                parts.append(esc(0x80 | ((cp // 64) & 0x3F), safe, hexd))
                parts.append(esc(0x80 | (cp & 0x3F), safe, hexd))
            else:
                parts.append(esc(0xF0 | (cp // 262144), safe, hexd))
                parts.append(esc(0x80 | ((cp // 4096) & 0x3F), safe, hexd))
                parts.append(esc(0x80 | ((cp // 64) & 0x3F), safe, hexd))
                parts.append(esc(0x80 | (cp & 0x3F), safe, hexd))
        return "".join(parts)

    def _unique_str_global_name(self, string_content: str) -> str:
        """Resolve the content-addressed name against occupied names.

        Duplicates of one content get '~N' (N >= 1); the real llvmlite
        rejects duplicate global names, so both planes are forced into
        the same suffix scheme. P2 interning can later flip this lookup
        into a reuse.
        """
        base = self._str_global_name(string_content)
        name = base
        n = 0
        while name in self.module.globals:
            n += 1
            name = base + "~" + str(n)
        return name

    def _create_global_string(self, string_content: str) -> ir.Value:
        """Create a global string constant."""
        return self._create_global_string_with_builder(
            string_content, self.current_builder
        )

    def _emit_panic(self, builder: ir.IRBuilder, msg_ptr: ir.Value) -> None:
        """Abort with a runtime error: prints the message plus the
        current source line (from the __silu_line global), then exits.
        Replaces the printf(msg); exit(1); unreachable() triple."""
        builder.call(self.silu_panic, [msg_ptr])
        builder.unreachable()

    def _create_global_string_with_builder(
        self, string_content: str, builder: ir.IRBuilder
    ) -> ir.Value:
        """Create a global string constant with a specific builder."""
        string_bytes = bytearray((string_content + "\0").encode("utf-8"))
        string_type = ir.ArrayType(ir.IntType(8), len(string_bytes))

        # Content-addressed global name (P6): the old
        # f'str_{len(self.module.globals)}' numbering made every string
        # name depend on the declaration order of ALL module globals.
        # P2 interning: the bare content name can only ever be THIS
        # content's global (the str. namespace is exclusive), so a hit
        # means an identical constant already exists - reuse it. The
        # '~N' duplicate suffixes from the P6 stage disappear entirely.
        base = self._str_global_name(string_content)
        zero = ir.const_(ir.IntType(32), 0)
        if base in self.module.globals:
            return builder.gep(self.module.globals[base], [zero, zero])

        # Create global variable
        global_str = ir.gvar_(self.module, string_type, base)
        global_str.global_constant = True
        global_str.initializer = ir.const_(string_type, string_bytes)

        # Get pointer to first character
        return builder.gep(global_str, [zero, zero])
