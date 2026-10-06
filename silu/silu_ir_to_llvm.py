"""
Silu IR to LLVM IR Converter

This module converts Silu IR (JSON format) to LLVM IR, enabling compilation
of Silu programs to native machine code.

The converter handles the dynamic typing of Silu by creating a runtime system
with tagged unions for Python-like objects.
"""

import sys
from typing import Any, Dict, Optional
from llvmlite import ir
import llvmlite.binding as llvm
from .ir_utils import parse_ir_from_json_string, IRParseError


class PyObject:
    """Runtime representation of Python objects in LLVM IR."""

    def __init__(self, module: ir.Module):
        self.module = module

        # Define PyObject struct: { i32 type_tag, i8* data }
        self.pyobj_type = ir.LiteralStructType(
            [
                ir.IntType(
                    32
                ),  # type tag (0=int, 1=float, 2=str, 3=bool, 4=list, 5=dict, 6=none)
                ir.PointerType(ir.IntType(8)),  # data pointer
            ]
        )

        # Define string struct: { i32 length, i8* chars }
        self.string_type = ir.LiteralStructType(
            [
                ir.IntType(32),  # length
                ir.PointerType(ir.IntType(8)),  # chars
            ]
        )


class SiluToLLVMConverter:
    """Converts Silu IR to LLVM IR."""

    def __init__(self):
        # Initialize LLVM
        llvm.initialize()
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        # Get target information
        target = llvm.Target.from_default_triple()
        self.target_machine = target.create_target_machine()

        # Create LLVM module
        self.module = ir.Module(name="silu_module")
        self.module.triple = self.target_machine.triple
        self.module.data_layout = str(self.target_machine.target_data)

        # Runtime object system
        self.pyobj = PyObject(self.module)

        # Global context
        self.variables: Dict[
            str, ir.Value
        ] = {}  # Maps variable names to alloca instructions
        self.functions: Dict[str, ir.Function] = {}
        self.current_function: Optional[ir.Function] = None
        self.current_builder: Optional[ir.IRBuilder] = None

        # Function definitions (IR nodes for later processing)
        self.function_defs: Dict[str, Any] = {}

        # Initialize runtime functions
        self._init_runtime_functions()

    def _init_runtime_functions(self):
        """Initialize runtime support functions."""

        # printf declaration
        printf_ty = ir.FunctionType(
            ir.IntType(32), [ir.PointerType(ir.IntType(8))], var_arg=True
        )
        self.printf = ir.Function(self.module, printf_ty, name="printf")

        # malloc and free
        malloc_ty = ir.FunctionType(ir.PointerType(ir.IntType(8)), [ir.IntType(64)])
        self.malloc = ir.Function(self.module, malloc_ty, name="malloc")

        free_ty = ir.FunctionType(ir.VoidType(), [ir.PointerType(ir.IntType(8))])
        self.free = ir.Function(self.module, free_ty, name="free")

        # llvm.memcpy for string concatenation
        memcpy_ty = ir.FunctionType(
            ir.VoidType(),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
                ir.IntType(1),
            ],
        )
        self.memcpy = ir.Function(
            self.module, memcpy_ty, name="llvm.memcpy.p0i8.p0i8.i64"
        )

        # libc helpers for Python-style float printing
        # (fmt is a fixed parameter of snprintf, not a vararg)
        snprintf_ty = ir.FunctionType(
            ir.IntType(32),
            [
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
                ir.PointerType(ir.IntType(8)),
            ],
            var_arg=True,
        )
        self.snprintf = ir.Function(self.module, snprintf_ty, name="snprintf")

        strtod_ty = ir.FunctionType(
            ir.DoubleType(),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.PointerType(ir.IntType(8))),
            ],
        )
        self.strtod = ir.Function(self.module, strtod_ty, name="strtod")

        memchr_ty = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.IntType(32), ir.IntType(64)],
        )
        self.memchr = ir.Function(self.module, memchr_ty, name="memchr")

        strlen_ty = ir.FunctionType(ir.IntType(64), [ir.PointerType(ir.IntType(8))])
        self.strlen = ir.Function(self.module, strlen_ty, name="strlen")

        # llvm.floor.f64 intrinsic for float floor division
        floor_ty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()])
        self.floor_f64 = ir.Function(self.module, floor_ty, name="llvm.floor.f64")

        # PyObject creation functions
        self._create_overflow_intrinsics()
        self._create_pyobj_constructors()
        self._create_pyobj_operations()
        self._create_comparison_operations()

    def _create_pyobj_constructors(self):
        """Create PyObject constructor functions."""

        # PyObject* create_int(i64 value)
        create_int_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.IntType(64)]
        )
        self.create_int = ir.Function(self.module, create_int_ty, name="create_int")

        block = self.create_int.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        # Allocate PyObject
        obj_ptr = builder.call(
            self.malloc, [ir.Constant(ir.IntType(64), 16)]
        )  # sizeof(PyObject)
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 0 (int)
        tag_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        builder.store(ir.Constant(ir.IntType(32), 0), tag_ptr)

        # Allocate and store integer value
        data_ptr = builder.call(
            self.malloc, [ir.Constant(ir.IntType(64), 8)]
        )  # sizeof(i64)
        data_i64 = builder.bitcast(data_ptr, ir.PointerType(ir.IntType(64)))
        builder.store(self.create_int.args[0], data_i64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

        # PyObject* create_str(i8* str, i32 len)
        create_str_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [ir.PointerType(ir.IntType(8)), ir.IntType(32)],
        )
        self.create_str = ir.Function(self.module, create_str_ty, name="create_str")

        block = self.create_str.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 2 (string)
        tag_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        builder.store(ir.Constant(ir.IntType(32), 2), tag_ptr)

        # Allocate string struct
        str_ptr = builder.call(
            self.malloc, [ir.Constant(ir.IntType(64), 16)]
        )  # sizeof(string_type)
        str_struct = builder.bitcast(str_ptr, ir.PointerType(self.pyobj.string_type))

        # Store length
        len_ptr = builder.gep(
            str_struct, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        builder.store(self.create_str.args[1], len_ptr)

        # Store chars pointer
        chars_ptr = builder.gep(
            str_struct, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        builder.store(self.create_str.args[0], chars_ptr)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        builder.store(str_ptr, data_ptr_field)

        builder.ret(obj)

        # PyObject* create_bool(i1 value)
        create_bool_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.IntType(1)]
        )
        self.create_bool = ir.Function(self.module, create_bool_ty, name="create_bool")

        block = self.create_bool.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 3 (bool)
        tag_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        builder.store(ir.Constant(ir.IntType(32), 3), tag_ptr)

        # Allocate and store the value as i64 0/1
        data_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 8)])
        data_i64 = builder.bitcast(data_ptr, ir.PointerType(ir.IntType(64)))
        bool_i64 = builder.zext(self.create_bool.args[0], ir.IntType(64))
        builder.store(bool_i64, data_i64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

        # PyObject* create_float(double value)
        create_float_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.DoubleType()]
        )
        self.create_float = ir.Function(
            self.module, create_float_ty, name="create_float"
        )

        block = self.create_float.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 1 (float)
        tag_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        builder.store(ir.Constant(ir.IntType(32), 1), tag_ptr)

        # Allocate and store the double value
        data_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 8)])
        data_f64 = builder.bitcast(data_ptr, ir.PointerType(ir.DoubleType()))
        builder.store(self.create_float.args[0], data_f64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

    def _create_pyobj_operations(self):
        """Create PyObject operation functions."""

        # PyObject* pyobj_add(PyObject* left, PyObject* right)
        add_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ],
        )
        self.pyobj_add = ir.Function(self.module, add_ty, name="pyobj_add")

        block = self.pyobj_add.append_basic_block("entry")
        builder = ir.IRBuilder(block)

        left, right = self.pyobj_add.args

        # Get type tags
        left_tag_ptr = builder.gep(
            left, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        right_tag_ptr = builder.gep(
            right, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        left_tag = builder.load(left_tag_ptr)
        right_tag = builder.load(right_tag_ptr)

        # Ints, bools and floats take the numeric path (bool coerces to int)
        both_numeric_cond = builder.and_(
            self._is_numeric_tag(builder, left_tag),
            self._is_numeric_tag(builder, right_tag),
        )

        float_check_block = self.pyobj_add.append_basic_block("float_check")
        str_check_block = self.pyobj_add.append_basic_block("str_check")
        str_concat_block = self.pyobj_add.append_basic_block("str_concat")
        error_block = self.pyobj_add.append_basic_block("error")
        builder.cbranch(both_numeric_cond, float_check_block, str_check_block)

        # Any float operand promotes the result to float (Python semantics)
        builder.position_at_end(float_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.Constant(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.Constant(ir.IntType(32), 1)),
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
            left, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        right_data_ptr = builder.gep(
            right, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
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
            "Error: Integer overflow in addition\n", builder
        )
        builder.call(self.printf, [error_msg])

        # Exit with error code 1
        exit_ty = ir.FunctionType(ir.VoidType(), [ir.IntType(32)])
        exit_func = ir.Function(self.module, exit_ty, name="exit")
        builder.call(exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        # Success case - return result
        builder.position_at_end(success_block)
        result_obj = builder.call(self.create_int, [sum_val])
        builder.ret(result_obj)

        # String check: both operands strings -> concatenation
        builder.position_at_end(str_check_block)
        both_str_cond = builder.and_(
            builder.icmp_signed("==", left_tag, ir.Constant(ir.IntType(32), 2)),
            builder.icmp_signed("==", right_tag, ir.Constant(ir.IntType(32), 2)),
        )
        builder.cbranch(both_str_cond, str_concat_block, error_block)

        # String concatenation: malloc new buffer, copy both, null-terminate
        builder.position_at_end(str_concat_block)
        zero32 = ir.Constant(ir.IntType(32), 0)
        one32 = ir.Constant(ir.IntType(32), 1)

        def load_string_parts(obj):
            data_ptr = builder.gep(obj, [zero32, one32])
            data = builder.load(data_ptr)
            str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
            str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
            chars = builder.load(builder.gep(str_struct, [zero32, one32]))
            return str_len, chars

        left_len, left_chars = load_string_parts(left)
        right_len, right_chars = load_string_parts(right)
        left_len64 = builder.zext(left_len, ir.IntType(64))
        right_len64 = builder.zext(right_len, ir.IntType(64))
        total_len = builder.add(left_len64, right_len64)

        buf = builder.call(
            self.malloc,
            [builder.add(total_len, ir.Constant(ir.IntType(64), 1))],
        )
        false_flag = ir.Constant(ir.IntType(1), 0)
        builder.call(self.memcpy, [buf, left_chars, left_len64, false_flag])
        buf_offset = builder.gep(buf, [left_len64])
        builder.call(self.memcpy, [buf_offset, right_chars, right_len64, false_flag])
        null_pos = builder.gep(buf, [total_len])
        builder.store(ir.Constant(ir.IntType(8), 0), null_pos)

        concat_obj = builder.call(
            self.create_str, [buf, builder.trunc(total_len, ir.IntType(32))]
        )
        builder.ret(concat_obj)

        # Error case - return null for now
        builder.position_at_end(error_block)
        builder.ret(ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        # Arithmetic over int/bool/float operands with Python promotion rules
        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            int_apply=lambda b, left, right: b.sub(left, right),
            float_apply=lambda b, left, right: b.fsub(left, right),
        )
        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            int_apply=lambda b, left, right: b.mul(left, right),
            float_apply=lambda b, left, right: b.fmul(left, right),
        )
        # Python true division always returns a float
        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            float_apply=lambda b, left, right: b.fdiv(left, right),
        )
        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            int_apply=self._floor_div_apply,
            float_apply=self._float_floordiv_apply,
        )
        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            int_apply=self._py_mod_apply,
            float_apply=self._float_mod_apply,
        )

        # Create print function for PyObjects
        self._create_pyobj_print()

    @staticmethod
    def _is_numeric_tag(builder, tag):
        """True if the tag is int (0), float (1), or bool (3)."""
        i32 = ir.IntType(32)
        return builder.or_(
            builder.icmp_signed("==", tag, ir.Constant(i32, 0)),
            builder.or_(
                builder.icmp_signed("==", tag, ir.Constant(i32, 1)),
                builder.icmp_signed("==", tag, ir.Constant(i32, 3)),
            ),
        )

    def _load_number_as_i64(self, builder, obj):
        """Load the payload of an int/bool PyObject as an i64."""
        data = builder.load(
            builder.gep(
                obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
            )
        )
        return builder.load(builder.bitcast(data, ir.PointerType(ir.IntType(64))))

    def _load_number_as_f64(self, builder, obj):
        """Load the payload of an int/bool/float PyObject as a double."""
        data = builder.load(
            builder.gep(
                obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
            )
        )
        as_float = builder.load(builder.bitcast(data, ir.PointerType(ir.DoubleType())))
        int_bits = builder.load(builder.bitcast(data, ir.PointerType(ir.IntType(64))))
        as_int = builder.sitofp(int_bits, ir.DoubleType())
        tag = builder.load(
            builder.gep(
                obj,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        is_float = builder.icmp_signed("==", tag, ir.Constant(ir.IntType(32), 1))
        return builder.select(is_float, as_float, as_int)

    def _float_floordiv_apply(self, builder, left_val, right_val):
        """Python float floor division: floor(left / right)."""
        quotient = builder.fdiv(left_val, right_val)
        return builder.call(self.floor_f64, [quotient])

    def _float_mod_apply(self, builder, left_val, right_val):
        """Python float modulo: result has the sign of the divisor."""
        remainder = builder.frem(left_val, right_val)
        zero = ir.Constant(ir.DoubleType(), 0.0)
        r_ne_zero = builder.fcmp_ordered("!=", remainder, zero)
        r_negative = builder.fcmp_ordered("<", remainder, zero)
        right_negative = builder.fcmp_ordered("<", right_val, zero)
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        return builder.select(adjust, builder.fadd(remainder, right_val), remainder)

    @staticmethod
    def _floor_div_apply(builder, left_val, right_val):
        """Python floor division: rounds toward negative infinity."""
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)
        q = builder.sdiv(left_val, right_val)
        r = builder.srem(left_val, right_val)
        r_ne_zero = builder.icmp_signed("!=", r, zero)
        r_negative = builder.icmp_signed("<", r, zero)
        right_negative = builder.icmp_signed("<", right_val, zero)
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adj_val = builder.select(adjust, ir.Constant(i64, -1), zero)
        return builder.add(q, adj_val)

    @staticmethod
    def _py_mod_apply(builder, left_val, right_val):
        """Python modulo: result has the sign of the divisor."""
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)
        r = builder.srem(left_val, right_val)
        r_ne_zero = builder.icmp_signed("!=", r, zero)
        r_negative = builder.icmp_signed("<", r, zero)
        right_negative = builder.icmp_signed("<", right_val, zero)
        signs_differ = builder.xor(r_negative, right_negative)
        adjust = builder.and_(r_ne_zero, signs_differ)
        adj_val = builder.select(adjust, right_val, zero)
        return builder.add(r, adj_val)

    def _create_pyobj_print(self):
        """Create PyObject print function."""
        self._create_float_repr_runtime()

        print_ty = ir.FunctionType(
            ir.VoidType(), [ir.PointerType(self.pyobj.pyobj_type)]
        )
        self.pyobj_print = ir.Function(self.module, print_ty, name="pyobj_print")

        entry_block = self.pyobj_print.append_basic_block("entry")
        null_block = self.pyobj_print.append_basic_block("print_null")
        dispatch_block = self.pyobj_print.append_basic_block("dispatch")
        int_block = self.pyobj_print.append_basic_block("print_int")
        float_block = self.pyobj_print.append_basic_block("print_float")
        str_block = self.pyobj_print.append_basic_block("print_str")
        bool_block = self.pyobj_print.append_basic_block("print_bool")
        default_block = self.pyobj_print.append_basic_block("default")

        builder = ir.IRBuilder(entry_block)

        obj = self.pyobj_print.args[0]

        # Null pointer prints as None (e.g. bare return values)
        null_ptr = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
        is_null = builder.icmp_signed("==", obj, null_ptr)
        builder.cbranch(is_null, null_block, dispatch_block)

        builder.position_at_end(null_block)
        none_str = self._create_global_string_with_builder("None", builder)
        builder.call(self.printf, [none_str])
        builder.ret_void()

        # Get type tag
        builder.position_at_end(dispatch_block)
        tag_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
        )
        tag = builder.load(tag_ptr)

        # Switch on type tag
        switch = builder.switch(tag, default_block)
        switch.add_case(ir.Constant(ir.IntType(32), 0), int_block)  # int
        switch.add_case(ir.Constant(ir.IntType(32), 1), float_block)  # float
        switch.add_case(ir.Constant(ir.IntType(32), 2), str_block)  # str
        switch.add_case(ir.Constant(ir.IntType(32), 3), bool_block)  # bool

        # Print float via the Python-style repr runtime
        builder.position_at_end(float_block)
        f64_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
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
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        data = builder.load(data_ptr)
        bool_i64_ptr = builder.bitcast(data, ir.PointerType(ir.IntType(64)))
        bool_val = builder.load(bool_i64_ptr)
        is_true = builder.icmp_signed("!=", bool_val, ir.Constant(ir.IntType(64), 0))
        true_str = self._create_global_string_with_builder("True", builder)
        false_str = self._create_global_string_with_builder("False", builder)
        bool_fmt = builder.select(is_true, true_str, false_str)
        builder.call(self.printf, [bool_fmt])
        builder.ret_void()

        # Print integer
        builder.position_at_end(int_block)
        data_ptr = builder.gep(
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
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
            obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        data = builder.load(data_ptr)
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        chars_ptr_ptr = builder.gep(
            str_struct, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
        )
        chars_ptr = builder.load(chars_ptr_ptr)

        str_fmt = self._create_global_string_with_builder("%s", builder)
        builder.call(self.printf, [str_fmt, chars_ptr])
        builder.ret_void()

        # Default case
        builder.position_at_end(default_block)
        unknown_fmt = self._create_global_string_with_builder(
            "<unknown object>", builder
        )
        builder.call(self.printf, [unknown_fmt])
        builder.ret_void()

    def _create_float_repr_runtime(self):
        """Create i8* float_repr(double): Python-style shortest repr.

        Emits "%.15g"; if strtod of the buffer differs from the input,
        retries with "%.16g" then "%.17g". Appends ".0" when no '.', 'e',
        'n'(nan) or 'i'(inf) appears, so 4.0 keeps its trailing zero.
        Returns a pointer to a heap buffer (string struct, chars field).
        """
        f64 = ir.DoubleType()
        i8p = ir.PointerType(ir.IntType(8))
        repr_ty = ir.FunctionType(i8p, [f64])
        func = ir.Function(self.module, repr_ty, name="float_repr")

        entry = func.append_basic_block("entry")
        retry = func.append_basic_block("retry")
        more_digits = func.append_basic_block("more_digits")
        finish = func.append_basic_block("finish")

        builder = ir.IRBuilder(entry)
        value = func.args[0]

        def emit(fmt):
            buf = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 40)])
            fmt_ptr = self._create_global_string_with_builder(fmt, builder)
            builder.call(
                self.snprintf, [buf, ir.Constant(ir.IntType(64), 40), fmt_ptr, value]
            )
            return buf

        def parsed_back(buf):
            endp = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 8)])
            endp_i8pp = builder.bitcast(endp, ir.PointerType(i8p))
            back = builder.call(self.strtod, [buf, endp_i8pp])
            return builder.fcmp_ordered("==", back, value)

        # First try: 15 significant digits
        buf1 = emit("%.15g")
        ok1 = parsed_back(buf1)
        builder.cbranch(ok1, finish, retry)

        # Retry with 16 digits
        builder.position_at_end(retry)
        buf2 = emit("%.16g")
        ok2 = parsed_back(buf2)
        builder.cbranch(ok2, finish, more_digits)

        # Retry with 17 digits
        builder.position_at_end(more_digits)
        buf3 = emit("%.17g")
        builder.branch(finish)

        # finish: pick the winning buffer, then append ".0" when there
        # is no '.', 'e', 'n' (nan) or 'i' (inf) in the output
        builder.position_at_end(finish)
        buf = builder.phi(i8p)
        buf.add_incoming(buf1, entry)
        buf.add_incoming(buf2, retry)
        buf.add_incoming(buf3, more_digits)

        def is_float_marker(buf, ch):
            hit = builder.call(
                self.memchr,
                [
                    buf,
                    ir.Constant(ir.IntType(32), ord(ch)),
                    builder.call(self.strlen, [buf]),
                ],
            )
            return builder.icmp_signed("!=", hit, ir.Constant(i8p, None))

        needs_dot = builder.and_(
            builder.not_(is_float_marker(buf, ".")),
            builder.and_(
                builder.not_(is_float_marker(buf, "e")),
                builder.and_(
                    builder.not_(is_float_marker(buf, "n")),
                    builder.not_(is_float_marker(buf, "i")),
                ),
            ),
        )

        append_block = func.append_basic_block("append_dot")
        done_block = func.append_basic_block("done")
        builder.cbranch(needs_dot, append_block, done_block)

        builder.position_at_end(append_block)
        len1 = builder.call(self.strlen, [buf])
        gep_dot = builder.gep(buf, [len1])
        builder.store(ir.Constant(ir.IntType(8), ord(".")), gep_dot)
        gep_zero = builder.gep(buf, [builder.add(len1, ir.Constant(ir.IntType(64), 1))])
        builder.store(ir.Constant(ir.IntType(8), ord("0")), gep_zero)
        gep_nul = builder.gep(buf, [builder.add(len1, ir.Constant(ir.IntType(64), 2))])
        builder.store(ir.Constant(ir.IntType(8), 0), gep_nul)
        builder.branch(done_block)

        builder.position_at_end(done_block)
        builder.ret(buf)

        self.float_repr = func

    def _create_numeric_binary_function(
        self, func_name: str, int_apply=None, float_apply=None
    ) -> ir.Function:
        """Create a pyobj arithmetic function over int/bool/float operands.

        int_apply(builder, left_i64, right_i64) returns the i64 result,
        delivered as an int PyObject. float_apply(builder, left_f64,
        right_f64) returns the double result, delivered as a float
        PyObject. With int_apply None the operation always promotes to
        float (Python true division always returns float).
        """
        func_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ],
        )
        func = ir.Function(self.module, func_ty, name=f"pyobj_{func_name}")

        entry_block = func.append_basic_block("entry")
        num_check_block = func.append_basic_block("num_check")
        float_op_block = func.append_basic_block("float_op")
        # Only create the int block when int operations exist, otherwise
        # it would be an empty (invalid) basic block.
        int_op_block = (
            func.append_basic_block("int_op") if int_apply is not None else None
        )
        error_block = func.append_basic_block("error")
        builder = ir.IRBuilder(entry_block)

        left, right = func.args
        left_tag = builder.load(
            builder.gep(
                left,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        right_tag = builder.load(
            builder.gep(
                right,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        both_numeric = builder.and_(
            self._is_numeric_tag(builder, left_tag),
            self._is_numeric_tag(builder, right_tag),
        )
        builder.cbranch(both_numeric, num_check_block, error_block)

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.Constant(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.Constant(ir.IntType(32), 1)),
        )
        if int_apply is None:
            builder.branch(float_op_block)
        else:
            builder.cbranch(either_float, float_op_block, int_op_block)

        builder.position_at_end(float_op_block)
        left_f64 = self._load_number_as_f64(builder, left)
        right_f64 = self._load_number_as_f64(builder, right)
        float_result = float_apply(builder, left_f64, right_f64)
        builder.ret(builder.call(self.create_float, [float_result]))

        if int_apply is not None:
            builder.position_at_end(int_op_block)
            left_i64 = self._load_number_as_i64(builder, left)
            right_i64 = self._load_number_as_i64(builder, right)
            int_result = int_apply(builder, left_i64, right_i64)
            builder.ret(builder.call(self.create_int, [int_result]))

        builder.position_at_end(error_block)
        builder.ret(ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))
        return func

    def _create_bool_result_function(self, func_name: str, pred: str) -> ir.Function:
        """Create a comparison function over int/bool/float operands.

        pred is one of "==", "!=", "<", "<=", ">", ">=".
        """
        func_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type),
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ],
        )
        func = ir.Function(self.module, func_ty, name=f"pyobj_{func_name}")

        entry_block = func.append_basic_block("entry")
        num_check_block = func.append_basic_block("num_check")
        float_op_block = func.append_basic_block("float_op")
        int_op_block = func.append_basic_block("int_op")
        error_block = func.append_basic_block("error")
        builder = ir.IRBuilder(entry_block)

        left, right = func.args
        left_tag = builder.load(
            builder.gep(
                left,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        right_tag = builder.load(
            builder.gep(
                right,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        both_numeric = builder.and_(
            self._is_numeric_tag(builder, left_tag),
            self._is_numeric_tag(builder, right_tag),
        )
        builder.cbranch(both_numeric, num_check_block, error_block)

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", left_tag, ir.Constant(ir.IntType(32), 1)),
            builder.icmp_signed("==", right_tag, ir.Constant(ir.IntType(32), 1)),
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
        builder.ret(ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))
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
        for name, pred in predicates.items():
            setattr(
                self, f"pyobj_{name}", self._create_bool_result_function(name, pred)
            )

    def _create_less_than_comparison(self, left: ir.Value, right: ir.Value) -> ir.Value:
        """Less-than over int/float operands, used by loop conditions."""
        return self.current_builder.call(self.pyobj_lt, [left, right])

    def _create_unary_minus(self, operand: ir.Value) -> ir.Value:
        """Unary minus over int/bool/float PyObjects."""
        builder = self.current_builder
        tag = builder.load(
            builder.gep(
                operand,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )

        is_float = builder.icmp_signed("==", tag, ir.Constant(ir.IntType(32), 1))
        is_numeric = self._is_numeric_tag(builder, tag)

        float_block = self.current_function.append_basic_block("unary_minus_float")
        int_check_block = self.current_function.append_basic_block(
            "unary_minus_int_chk"
        )
        int_block = self.current_function.append_basic_block("unary_minus_int")
        error_block = self.current_function.append_basic_block("unary_minus_error")
        merge_block = self.current_function.append_basic_block("unary_minus_merge")
        builder.cbranch(is_float, float_block, int_check_block)

        # Float negation
        builder.position_at_end(float_block)
        f64_val = self._load_number_as_f64(builder, operand)
        float_result = builder.call(
            self.create_float,
            [builder.fsub(ir.Constant(ir.DoubleType(), 0.0), f64_val)],
        )
        builder.branch(merge_block)

        # Int/bool negation
        builder.position_at_end(int_check_block)
        builder.cbranch(is_numeric, int_block, error_block)

        builder.position_at_end(int_block)
        i64_val = self._load_number_as_i64(builder, operand)
        int_result = builder.call(
            self.create_int,
            [builder.sub(ir.Constant(ir.IntType(64), 0), i64_val)],
        )
        builder.branch(merge_block)

        # Error case
        builder.position_at_end(error_block)
        null_result = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
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
            overflow_ty, [ir.IntType(64), ir.IntType(64)]
        )
        self.sadd_overflow = ir.Function(
            self.module, sadd_overflow_ty, name="llvm.sadd.with.overflow.i64"
        )

    def _create_global_string(self, string_content: str) -> ir.Value:
        """Create a global string constant."""
        return self._create_global_string_with_builder(
            string_content, self.current_builder
        )

    def _create_global_string_with_builder(
        self, string_content: str, builder: ir.IRBuilder
    ) -> ir.Value:
        """Create a global string constant with a specific builder."""
        string_bytes = bytearray((string_content + "\0").encode("utf-8"))
        string_type = ir.ArrayType(ir.IntType(8), len(string_bytes))

        # Create global variable
        global_str = ir.GlobalVariable(
            self.module, string_type, name=f"str_{len(self.module.globals)}"
        )
        global_str.global_constant = True
        global_str.initializer = ir.Constant(string_type, string_bytes)

        # Get pointer to first character
        zero = ir.Constant(ir.IntType(32), 0)
        return builder.gep(global_str, [zero, zero])

    @staticmethod
    def _normalize_ir(node: Any) -> Any:
        """Recursively convert tuple IR nodes to lists.

        parse_ir_from_json_string returns tuple structures, while node
        dispatch in this converter expects lists.
        """
        if isinstance(node, (list, tuple)):
            return [SiluToLLVMConverter._normalize_ir(item) for item in node]
        return node

    def convert(self, ir_json: str) -> str:
        """Convert Silu IR JSON to LLVM IR."""

        # Parse JSON
        try:
            ir_data = parse_ir_from_json_string(ir_json)
        except IRParseError as e:
            raise ValueError(f"Failed to parse IR: {e}")

        ir_data = self._normalize_ir(ir_data)

        # First pass: collect function definitions
        self._collect_function_defs(ir_data)

        # Second pass: create function declarations
        self._create_function_declarations()

        # Create main function
        main_ty = ir.FunctionType(ir.IntType(32), [])
        main_func = ir.Function(self.module, main_ty, name="main")
        self.current_function = main_func

        entry_block = main_func.append_basic_block("entry")
        self.current_builder = ir.IRBuilder(entry_block)

        # Convert IR (skip function definitions in main)
        self._convert_node(ir_data, skip_func_defs=True)

        # Return 0 from main
        self.current_builder.ret(ir.Constant(ir.IntType(32), 0))

        # Generate function bodies
        self._generate_function_bodies()

        return str(self.module)

    def _collect_function_defs(self, node):
        """Collect function definitions from IR tree."""
        if isinstance(node, list) and len(node) > 0:
            if node[0] == "module" and len(node) > 1:
                for stmt in node[1]:
                    self._collect_function_defs(stmt)
            elif node[0] == "func_def" and len(node) >= 4:
                func_name = node[1]
                self.function_defs[func_name] = node
            else:
                # Recursively process other nodes
                for item in node[1:]:
                    if isinstance(item, list):
                        self._collect_function_defs(item)

    def _create_function_declarations(self):
        """Create LLVM function declarations for user-defined functions."""
        for func_name, func_def in self.function_defs.items():
            # All functions return PyObject* and take PyObject* parameters
            param_count = len(func_def[2]) if len(func_def) > 2 else 0
            param_types = [ir.PointerType(self.pyobj.pyobj_type)] * param_count
            func_ty = ir.FunctionType(
                ir.PointerType(self.pyobj.pyobj_type), param_types
            )
            func = ir.Function(self.module, func_ty, name=func_name)
            self.functions[func_name] = func

    def _generate_function_bodies(self):
        """Generate function bodies for user-defined functions."""
        for func_name, func_def in self.function_defs.items():
            func = self.functions[func_name]
            self._generate_function_body(func, func_def)

    def _extract_bool_condition(self, test_val: ir.Value) -> ir.Value:
        """Extract an i1 condition from a PyObject (non-zero int is true).

        Null pointers (unsupported/void values) are treated as false.
        """
        builder = self.current_builder
        null_ptr = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
        is_null = builder.icmp_signed("==", test_val, null_ptr)

        check_block = builder.block
        load_block = self.current_function.append_basic_block("bool_load")
        merge_block = self.current_function.append_basic_block("bool_merge")
        builder.cbranch(is_null, merge_block, load_block)

        builder.position_at_end(load_block)
        data_ptr = builder.gep(
            test_val,
            [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
        )
        data = builder.load(data_ptr)
        i64_ptr = builder.bitcast(data, ir.PointerType(ir.IntType(64)))
        bool_val = builder.load(i64_ptr)
        nonzero = builder.icmp_signed("!=", bool_val, ir.Constant(ir.IntType(64), 0))
        builder.branch(merge_block)

        builder.position_at_end(merge_block)
        phi = builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), check_block)
        phi.add_incoming(nonzero, load_block)
        return phi

    def _convert_node(
        self, node: Any, skip_func_defs: bool = False
    ) -> Optional[ir.Value]:
        """Convert a single IR node."""

        if not isinstance(node, list) or len(node) == 0:
            return None

        op = node[0]

        if op == "module":
            # Convert all statements in module
            statements = node[1] if len(node) > 1 else []
            for stmt in statements:
                self._convert_node(stmt, skip_func_defs)
            return None

        elif op == "const":
            value = node[1]
            if isinstance(value, bool):
                return self.current_builder.call(
                    self.create_bool, [ir.Constant(ir.IntType(1), value)]
                )
            elif isinstance(value, int):
                return self.current_builder.call(
                    self.create_int, [ir.Constant(ir.IntType(64), value)]
                )
            elif isinstance(value, float):
                return self.current_builder.call(
                    self.create_float, [ir.Constant(ir.DoubleType(), value)]
                )
            elif isinstance(value, str):
                # Create string constant
                str_len = len(value)  # Not including null terminator
                str_ptr = self._create_global_string(value)
                return self.current_builder.call(
                    self.create_str, [str_ptr, ir.Constant(ir.IntType(32), str_len)]
                )
            else:
                # For now, just treat other constants as integers
                return self.current_builder.call(
                    self.create_int, [ir.Constant(ir.IntType(64), 0)]
                )

        elif op == "name":
            var_name = node[1]
            if var_name in self.variables:
                # Load the value from the alloca
                return self.current_builder.load(self.variables[var_name])
            else:
                # Return a null PyObject for undefined variables
                return ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)

        elif op == "assign":
            target = node[1]
            value_node = node[2]
            value = self._convert_node(value_node)
            if value and isinstance(target, str):
                # Create alloca if variable doesn't exist
                if target not in self.variables:
                    self.variables[target] = self.current_builder.alloca(
                        ir.PointerType(self.pyobj.pyobj_type), name=target
                    )
                # Store the value
                self.current_builder.store(value, self.variables[target])
            return value

        elif op == "+":
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_add, [left, right])
            return None

        elif op == "-":
            if len(node) == 2:
                # Unary minus: -operand
                operand = self._convert_node(node[1])
                if operand:
                    return self._create_unary_minus(operand)
            elif len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_sub, [left, right])
            return None

        elif op == "*":
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_mul, [left, right])
            return None

        elif op == "/":
            # Python true division: always promotes to float
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_truediv, [left, right])
            return None

        elif op == "//":
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_floordiv, [left, right])
            return None

        elif op == "%":
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(self.pyobj_mod, [left, right])
            return None

        elif op == "if_expr":
            if len(node) >= 4:
                cond_val = self._convert_node(node[1])
                if cond_val:
                    then_block = self.current_function.append_basic_block("iexpr_then")
                    else_block = self.current_function.append_basic_block("iexpr_else")
                    merge_block = self.current_function.append_basic_block(
                        "iexpr_merge"
                    )
                    condition = self._extract_bool_condition(cond_val)
                    self.current_builder.cbranch(condition, then_block, else_block)

                    self.current_builder.position_at_end(then_block)
                    then_val = self._convert_node(node[2])
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    self.current_builder.position_at_end(else_block)
                    else_val = self._convert_node(node[3])
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    self.current_builder.position_at_end(merge_block)
                    phi = self.current_builder.phi(
                        ir.PointerType(self.pyobj.pyobj_type)
                    )
                    phi.add_incoming(then_val, then_block)
                    phi.add_incoming(else_val, else_block)
                    return phi
            return None

        elif op in ("==", "!=", "<", "<=", ">", ">="):
            func = {
                "==": self.pyobj_eq,
                "!=": self.pyobj_ne,
                "<": self.pyobj_lt,
                "<=": self.pyobj_le,
                ">": self.pyobj_gt,
                ">=": self.pyobj_ge,
            }[op]
            if len(node) >= 3:
                left = self._convert_node(node[1])
                right = self._convert_node(node[2])
                if left and right:
                    return self.current_builder.call(func, [left, right])
            return None

        elif op == "call":
            func_node = node[1]
            args_node = node[2] if len(node) > 2 else []

            if (
                isinstance(func_node, list)
                and len(func_node) >= 2
                and func_node[0] == "name"
            ):
                func_name = func_node[1]

                if func_name == "print":
                    # Handle print function
                    if args_node:
                        for idx, arg_node in enumerate(args_node):
                            if idx > 0:
                                sep = self._create_global_string(" ")
                                self.current_builder.call(self.printf, [sep])
                            arg_val = self._convert_node(arg_node)
                            if arg_val:
                                self.current_builder.call(self.pyobj_print, [arg_val])
                    # Add newline
                    newline_fmt = self._create_global_string("\n")
                    self.current_builder.call(self.printf, [newline_fmt])
                    return None

                elif func_name == "range":
                    # Handle range function with start and stop parameters
                    if len(args_node) == 1:
                        # range(stop) -> return stop
                        return self._convert_node(args_node[0])
                    elif len(args_node) >= 2:
                        # range(start, stop) -> return stop for loop iteration count
                        # For proper loop implementation, we need the stop value
                        stop_val = self._convert_node(args_node[1])
                        return (
                            stop_val
                            if stop_val
                            else self.current_builder.call(
                                self.create_int, [ir.Constant(ir.IntType(64), 0)]
                            )
                        )
                    return self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 0)]
                    )

                elif func_name in self.functions:
                    # Handle user-defined function calls
                    func = self.functions[func_name]
                    llvm_args = []
                    for arg_node in args_node:
                        arg_val = self._convert_node(arg_node)
                        if arg_val:
                            llvm_args.append(arg_val)

                    if len(llvm_args) == len(func.args):
                        return self.current_builder.call(func, llvm_args)
                    else:
                        # Argument count mismatch - return null for now
                        return ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)

            return None

        elif op == "if":
            if len(node) >= 4:
                test_node = node[1]
                body_stmts = node[2]
                else_stmts = node[3]

                # Evaluate condition
                test_val = self._convert_node(test_node)
                if test_val:
                    # Create basic blocks for if/else/merge
                    then_block = self.current_function.append_basic_block("if_then")
                    else_block = self.current_function.append_basic_block("if_else")
                    merge_block = self.current_function.append_basic_block("if_merge")

                    # Extract boolean value from PyObject and branch accordingly
                    condition = self._extract_bool_condition(test_val)
                    self.current_builder.cbranch(condition, then_block, else_block)

                    # Generate then block
                    self.current_builder.position_at_end(then_block)
                    for stmt in body_stmts:
                        self._convert_node(stmt)
                        if self.current_builder.block.is_terminated:
                            break
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    # Generate else block
                    self.current_builder.position_at_end(else_block)
                    for stmt in else_stmts:
                        self._convert_node(stmt)
                        if self.current_builder.block.is_terminated:
                            break
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    # Continue with merge block
                    self.current_builder.position_at_end(merge_block)

                return None

        elif op == "while":
            if len(node) >= 3:
                test_node = node[1]
                body_stmts = node[2]

                cond_block = self.current_function.append_basic_block("while_cond")
                body_block = self.current_function.append_basic_block("while_body")
                end_block = self.current_function.append_basic_block("while_end")

                self.current_builder.branch(cond_block)

                # Re-evaluate the condition on every iteration
                self.current_builder.position_at_end(cond_block)
                test_val = self._convert_node(test_node)
                if test_val:
                    condition = self._extract_bool_condition(test_val)
                    self.current_builder.cbranch(condition, body_block, end_block)

                    # Loop body
                    self.current_builder.position_at_end(body_block)
                    for stmt in body_stmts:
                        self._convert_node(stmt)
                        if self.current_builder.block.is_terminated:
                            break
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(cond_block)

                    # Continue after loop
                    self.current_builder.position_at_end(end_block)

                return None

        elif op == "for":
            if len(node) >= 4:
                target_node = node[1]
                iter_node = node[2]
                body_stmts = node[3]

                # Enhanced for loop implementation with proper range handling
                # Handle range() call to get start and stop values
                start_val = None
                end_val = None

                if (
                    isinstance(iter_node, list)
                    and len(iter_node) >= 3
                    and iter_node[0] == "call"
                ):
                    func_node = iter_node[1]
                    args_node = iter_node[2] if len(iter_node) > 2 else []

                    if (
                        isinstance(func_node, list)
                        and len(func_node) >= 2
                        and func_node[0] == "name"
                        and func_node[1] == "range"
                    ):
                        if len(args_node) == 1:
                            # range(stop) -> start=0, stop=args[0]
                            start_val = self.current_builder.call(
                                self.create_int, [ir.Constant(ir.IntType(64), 0)]
                            )
                            end_val = self._convert_node(args_node[0])
                        elif len(args_node) >= 2:
                            # range(start, stop) -> start=args[0], stop=args[1]
                            start_val = self._convert_node(args_node[0])
                            end_val = self._convert_node(args_node[1])

                # Default values if not range()
                if not start_val:
                    start_val = self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 0)]
                    )
                if not end_val:
                    end_val = self._convert_node(
                        iter_node
                    ) or self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 10)]
                    )

                # Create loop blocks
                loop_init = self.current_function.append_basic_block("loop_init")
                loop_cond = self.current_function.append_basic_block("loop_cond")
                loop_body = self.current_function.append_basic_block("loop_body")
                loop_end = self.current_function.append_basic_block("loop_end")

                # Jump to init
                self.current_builder.branch(loop_init)

                # Initialize loop variable to start value
                self.current_builder.position_at_end(loop_init)
                counter_ptr = self.current_builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type)
                )
                self.current_builder.store(start_val, counter_ptr)
                self.current_builder.branch(loop_cond)

                # Loop condition: counter < end_val (for proper range semantics)
                self.current_builder.position_at_end(loop_cond)
                current_val = self.current_builder.load(counter_ptr)

                # Use < instead of <= for proper range semantics
                cond_result = self._create_less_than_comparison(current_val, end_val)

                # Extract boolean condition
                data_ptr = self.current_builder.gep(
                    cond_result,
                    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
                )
                data = self.current_builder.load(data_ptr)
                i64_ptr = self.current_builder.bitcast(
                    data, ir.PointerType(ir.IntType(64))
                )
                bool_val = self.current_builder.load(i64_ptr)
                condition = self.current_builder.icmp_signed(
                    "!=", bool_val, ir.Constant(ir.IntType(64), 0)
                )
                self.current_builder.cbranch(condition, loop_body, loop_end)

                # Loop body
                self.current_builder.position_at_end(loop_body)

                # Set loop variable if it's a name (current iteration value)
                if (
                    isinstance(target_node, list)
                    and len(target_node) >= 2
                    and target_node[0] == "name"
                ):
                    var_name = target_node[1]
                    # Create alloca if variable doesn't exist
                    if var_name not in self.variables:
                        self.variables[var_name] = self.current_builder.alloca(
                            ir.PointerType(self.pyobj.pyobj_type), name=var_name
                        )
                    # Store current iteration value
                    current_iter_val = self.current_builder.load(counter_ptr)
                    self.current_builder.store(
                        current_iter_val, self.variables[var_name]
                    )

                # Execute body statements
                for stmt in body_stmts:
                    self._convert_node(stmt)
                    if self.current_builder.block.is_terminated:
                        break

                # Increment counter if not terminated
                if not self.current_builder.block.is_terminated:
                    current_counter = self.current_builder.load(counter_ptr)
                    one = self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 1)]
                    )
                    next_val = self.current_builder.call(
                        self.pyobj_add, [current_counter, one]
                    )
                    self.current_builder.store(next_val, counter_ptr)
                    self.current_builder.branch(loop_cond)

                # Continue after loop
                self.current_builder.position_at_end(loop_end)
                return None

        elif op == "func_def":
            # Function definitions are handled separately
            if skip_func_defs:
                return None
            # This shouldn't be reached in normal flow
            return None

        elif op == "tuple_assign":
            # Handle tuple unpacking assignment: a, b = expr
            if len(node) >= 3:
                targets = node[1]  # List of target variable names
                value_node = node[2]  # Expression to unpack

                # Handle tuple assignment with proper simultaneous semantics
                if (
                    isinstance(value_node, list)
                    and len(value_node) >= 2
                    and value_node[0] == "tuple"
                ):
                    elements = value_node[1] if len(value_node) > 1 else []

                    # First, evaluate all right-hand side values before any assignment
                    # This ensures simultaneous assignment semantics for cases like a, b = b, a + b
                    evaluated_values = []
                    for element in elements:
                        element_val = self._convert_node(element)
                        evaluated_values.append(element_val)

                    # Then assign all values to targets
                    for i, target in enumerate(targets):
                        if (
                            i < len(evaluated_values)
                            and evaluated_values[i]
                            and isinstance(target, str)
                        ):
                            # Create alloca if variable doesn't exist
                            if target not in self.variables:
                                self.variables[target] = self.current_builder.alloca(
                                    ir.PointerType(self.pyobj.pyobj_type), name=target
                                )
                            # Store the value
                            self.current_builder.store(
                                evaluated_values[i], self.variables[target]
                            )

                return None

        elif op == "tuple":
            # Handle tuple creation
            if len(node) >= 2:
                elements = node[1]
                # For now, just return the first element
                # A full implementation would create a tuple object
                if elements:
                    return self._convert_node(elements[0])
            return None

        elif op == "return":
            # Handle return statements
            if len(node) > 1:
                return_val = self._convert_node(node[1])
                if (
                    return_val
                    and self.current_function
                    and not self.current_builder.block.is_terminated
                ):
                    self.current_builder.ret(return_val)
                    return return_val
            # Return None/null if no value
            null_val = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
            if self.current_function and not self.current_builder.block.is_terminated:
                self.current_builder.ret(null_val)
            return null_val

        else:
            # Ignore unknown operations for now
            return None

    def _generate_function_body(self, func: ir.Function, func_def: Any):
        """Generate the body of a user-defined function."""
        if len(func_def) < 4:
            return

        # func_name = func_def[1]
        param_names = func_def[2]
        body_stmts = func_def[3]

        # Create function entry block
        entry_block = func.append_basic_block("entry")

        # Save current state
        old_function = self.current_function
        old_builder = self.current_builder
        old_variables = self.variables.copy()

        # Set up function context
        self.current_function = func
        self.current_builder = ir.IRBuilder(entry_block)

        # Set up parameters as variables
        for i, param_name in enumerate(param_names):
            if i < len(func.args):
                # Create alloca for parameter and store the argument value
                param_alloca = self.current_builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type), name=param_name
                )
                self.current_builder.store(func.args[i], param_alloca)
                self.variables[param_name] = param_alloca

        # Generate function body
        return_generated = False
        for stmt in body_stmts:
            # result =
            self._convert_node(stmt)
            if isinstance(stmt, list) and len(stmt) > 0 and stmt[0] == "return":
                return_generated = True
                break

        # Add default return if no explicit return
        if not return_generated and not self.current_builder.block.is_terminated:
            null_val = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
            self.current_builder.ret(null_val)

        # Restore previous state
        self.current_function = old_function
        self.current_builder = old_builder
        self.variables = old_variables

    def save_to_file(self, llvm_ir: str, filename: str):
        """Save LLVM IR to file."""
        with open(filename, "w") as f:
            f.write(llvm_ir)


def main():
    """Command line interface for Silu IR to LLVM converter."""

    if len(sys.argv) != 3:
        print("Usage: python silu_ir_to_llvm.py <input.ir.json> <output.ll>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    try:
        # Read Silu IR
        with open(input_file, "r", encoding="utf-8") as f:
            ir_json = f.read()

        # Convert to LLVM IR
        converter = SiluToLLVMConverter()
        llvm_ir = converter.convert(ir_json)

        # Save result
        converter.save_to_file(llvm_ir, output_file)

        print(f"Successfully converted {input_file} to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
