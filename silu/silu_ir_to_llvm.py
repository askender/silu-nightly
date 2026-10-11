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

        # List struct layout: {i64 length, i64 capacity, PyObject** items}
        self.list_struct_type = ir.LiteralStructType(
            [
                ir.IntType(64),
                ir.IntType(64),
                ir.PointerType(ir.PointerType(self.pyobj.pyobj_type)),
            ]
        )

        # Dict struct layout (CPython-style compact dict):
        # { i64 count        - live entries
        #   i64 used         - entries array length (live + deleted)
        #   i64 mask         - index table size - 1 (table is a power of 2)
        #   i64* index_table - open-addressed slots: entry_index + 1,
        #                      0 = empty, -1 = deleted
        #   {PyObject* key, PyObject* value}* entries - insertion ordered,
        #                      key == null marks a deleted entry }
        self.dict_entry_type = ir.LiteralStructType(
            [
                ir.PointerType(self.pyobj.pyobj_type),
                ir.PointerType(self.pyobj.pyobj_type),
            ]
        )
        self.dict_entries_ptr_type = ir.PointerType(
            ir.ArrayType(self.dict_entry_type, 0)
        )
        self.dict_struct_type = ir.LiteralStructType(
            [
                ir.IntType(64),
                ir.IntType(64),
                ir.IntType(64),
                ir.PointerType(ir.IntType(64)),
                self.dict_entries_ptr_type,
            ]
        )

        # Global context
        self.variables: Dict[
            str, ir.Value
        ] = {}  # Maps variable names to alloca instructions
        self.functions: Dict[str, ir.Function] = {}
        self.current_function: Optional[ir.Function] = None
        self.current_builder: Optional[ir.IRBuilder] = None

        # Function definitions (IR nodes for later processing)
        self.function_defs: Dict[str, Any] = {}

        # Targets for break/continue inside the innermost active loop
        self.loop_break_blocks = []
        self.loop_continue_blocks = []

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

        # calloc for zero-initialized hash index tables
        calloc_ty = ir.FunctionType(
            ir.PointerType(ir.IntType(8)), [ir.IntType(64), ir.IntType(64)]
        )
        self.calloc = ir.Function(self.module, calloc_ty, name="calloc")

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

        # exit for runtime error aborts
        exit_ty = ir.FunctionType(ir.VoidType(), [ir.IntType(32)])
        self.exit_func = ir.Function(self.module, exit_ty, name="exit")

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

        memcmp_ty = ir.FunctionType(
            ir.IntType(32),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
            ],
        )
        self.memcmp = ir.Function(self.module, memcmp_ty, name="memcmp")

        # llvm.floor.f64 intrinsic for float floor division
        floor_ty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()])
        self.floor_f64 = ir.Function(self.module, floor_ty, name="llvm.floor.f64")

        # PyObject creation functions
        self._create_overflow_intrinsics()
        self._create_pyobj_constructors()
        self._create_pyobj_operations()
        self._create_comparison_operations()
        self._create_list_runtime()
        self._create_list_and_str_method_runtime()
        self._create_dict_runtime()

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

        # PyObject* create_list() - tag 4, data -> list struct
        # (created here so pyobj_add's list concatenation can reference it)
        self.create_list = ir.Function(
            self.module,
            ir.FunctionType(ir.PointerType(self.pyobj.pyobj_type), []),
            name="create_list",
        )
        builder = ir.IRBuilder(self.create_list.append_basic_block("entry"))
        obj_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))
        builder.store(
            ir.Constant(ir.IntType(32), 4),
            builder.gep(
                obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
            ),
        )
        list_ptr = builder.call(self.malloc, [ir.Constant(ir.IntType(64), 24)])
        list_struct_ptr = builder.bitcast(
            list_ptr, ir.PointerType(self.list_struct_type)
        )
        zero32 = ir.Constant(ir.IntType(32), 0)
        builder.store(
            ir.Constant(ir.IntType(64), 0),
            builder.gep(list_struct_ptr, [zero32, zero32]),
        )
        builder.store(
            ir.Constant(ir.IntType(64), 0),
            builder.gep(list_struct_ptr, [zero32, ir.Constant(ir.IntType(32), 1)]),
        )
        builder.store(
            ir.Constant(ir.PointerType(ir.PointerType(self.pyobj.pyobj_type)), None),
            builder.gep(list_struct_ptr, [zero32, ir.Constant(ir.IntType(32), 2)]),
        )
        builder.store(
            list_ptr, builder.gep(obj, [zero32, ir.Constant(ir.IntType(32), 1)])
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
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
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
        list_check_block = self.pyobj_add.append_basic_block("list_check")
        builder.cbranch(both_str_cond, str_concat_block, list_check_block)

        # List check: both operands lists -> concatenation
        builder.position_at_end(list_check_block)
        both_list_cond = builder.and_(
            builder.icmp_signed("==", left_tag, ir.Constant(ir.IntType(32), 4)),
            builder.icmp_signed("==", right_tag, ir.Constant(ir.IntType(32), 4)),
        )
        list_concat_block = self.pyobj_add.append_basic_block("list_concat")
        builder.cbranch(both_list_cond, list_concat_block, error_block)

        # List concatenation: new list with copies of both item arrays
        builder.position_at_end(list_concat_block)
        left_struct = self._load_list_struct(builder, left)
        right_struct = self._load_list_struct(builder, right)
        i64t = ir.IntType(64)
        zero64c = ir.Constant(i64t, 0)
        zero32l = ir.Constant(ir.IntType(32), 0)
        one32l = ir.Constant(ir.IntType(32), 1)
        two32l = ir.Constant(ir.IntType(32), 2)
        left_len_l = builder.load(builder.gep(left_struct, [zero32l, zero32l]))
        right_len_l = builder.load(builder.gep(right_struct, [zero32l, zero32l]))
        left_items_l = builder.load(builder.gep(left_struct, [zero32l, two32l]))
        right_items_l = builder.load(builder.gep(right_struct, [zero32l, two32l]))
        total_l = builder.add(left_len_l, right_len_l)
        new_list_l = builder.call(self.create_list, [])
        new_struct_l = self._load_list_struct(builder, new_list_l)
        concat_buf = builder.call(
            self.malloc, [builder.mul(total_l, ir.Constant(i64t, 8))]
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
                builder.mul(left_len_l, ir.Constant(i64t, 8)),
                ir.Constant(ir.IntType(1), 0),
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
            concat_buf, [builder.mul(left_len_l, ir.Constant(i64t, 8))]
        )
        builder.call(
            self.memcpy,
            [
                right_dest,
                builder.bitcast(right_items_l, ir.PointerType(ir.IntType(8))),
                builder.mul(right_len_l, ir.Constant(i64t, 8)),
                ir.Constant(ir.IntType(1), 0),
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
        self._create_str_repeat_runtime()
        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            int_apply=lambda b, left, right: b.sub(left, right),
            float_apply=lambda b, left, right: b.fsub(left, right),
            overflow_check=True,
        )
        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            int_apply=lambda b, left, right: b.mul(left, right),
            float_apply=lambda b, left, right: b.fmul(left, right),
            str_int_apply=lambda b, s, n: b.call(self.str_repeat, [s, n]),
            overflow_check=True,
        )
        # Python true division always returns a float
        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            float_apply=lambda b, left, right: b.fdiv(left, right),
            zero_check=True,
        )
        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            int_apply=self._floor_div_apply,
            float_apply=self._float_floordiv_apply,
            zero_check=True,
        )
        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            int_apply=self._py_mod_apply,
            float_apply=self._float_mod_apply,
            zero_check=True,
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

        # void pyobj_repr_print(PyObject* obj) - repr-style: strings quoted
        self.pyobj_repr_print = ir.Function(
            self.module, print_ty, name="pyobj_repr_print"
        )
        repr_entry = self.pyobj_repr_print.append_basic_block("entry")
        repr_str_case = self.pyobj_repr_print.append_basic_block("repr_str")
        repr_other = self.pyobj_repr_print.append_basic_block("repr_other")
        repr_builder = ir.IRBuilder(repr_entry)
        repr_obj = self.pyobj_repr_print.args[0]
        repr_tag = repr_builder.load(
            repr_builder.gep(
                repr_obj,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        is_str_tag = repr_builder.icmp_signed(
            "==", repr_tag, ir.Constant(ir.IntType(32), 2)
        )
        repr_builder.cbranch(is_str_tag, repr_str_case, repr_other)

        repr_builder.position_at_end(repr_str_case)
        zero32r = ir.Constant(ir.IntType(32), 0)
        one32r = ir.Constant(ir.IntType(32), 1)
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
        switch.add_case(ir.Constant(ir.IntType(32), 4), list_block)  # list
        switch.add_case(ir.Constant(ir.IntType(32), 5), dict_block)  # dict

        # Print list as [a, b, c] with recursive element printing
        builder.position_at_end(list_block)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.Constant(i32, 0)
        struct_ptr = self._load_list_struct(builder, obj)
        list_len = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        open_bracket = self._create_global_string_with_builder("[", builder)
        builder.call(self.printf, [open_bracket])
        loop_check = self.pyobj_print.append_basic_block("list_loop_check")
        loop_body = self.pyobj_print.append_basic_block("list_loop_body")
        loop_incr = self.pyobj_print.append_basic_block("list_loop_incr")
        list_done = self.pyobj_print.append_basic_block("list_done")
        counter_ptr = builder.alloca(i64, name="list_print_idx")
        builder.store(ir.Constant(i64, 0), counter_ptr)
        builder.branch(loop_check)

        builder.position_at_end(loop_check)
        counter = builder.load(counter_ptr)
        more = builder.icmp_signed("<", counter, list_len)
        builder.cbranch(more, loop_body, list_done)

        builder.position_at_end(loop_body)
        not_first = builder.icmp_signed(">", counter, ir.Constant(i64, 0))
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
        builder.store(builder.add(counter, ir.Constant(i64, 1)), counter_ptr)
        builder.branch(loop_check)

        builder.position_at_end(list_done)
        close_bracket = self._create_global_string_with_builder("]", builder)
        builder.call(self.printf, [close_bracket])
        builder.ret_void()

        # Print dict as {'k': v, ...} with repr-style keys and values
        builder.position_at_end(dict_block)
        d_null_const = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
        d_data = builder.load(
            builder.gep(
                obj, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]
            )
        )
        d_struct = builder.bitcast(d_data, ir.PointerType(self.dict_struct_type))
        d_used = builder.load(
            builder.gep(
                d_struct,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
            )
        )
        d_entries = builder.load(
            builder.gep(
                d_struct,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)],
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
        d_idx = builder.alloca(ir.IntType(64), name="dict_print_idx")
        d_printed = builder.alloca(ir.IntType(64), name="dict_printed")
        builder.store(ir.Constant(ir.IntType(64), 0), d_idx)
        builder.store(ir.Constant(ir.IntType(64), 0), d_printed)
        builder.branch(d_check)

        builder.position_at_end(d_check)
        d_i = builder.load(d_idx)
        d_more = builder.icmp_signed("<", d_i, d_used)
        builder.cbranch(d_more, d_body, d_done)

        builder.position_at_end(d_body)
        d_entry = builder.gep(d_entries, [ir.Constant(ir.IntType(32), 0), d_i])
        d_key_obj = builder.load(
            builder.gep(
                d_entry,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)],
            )
        )
        # deleted entries (null key) are skipped
        d_is_live = builder.icmp_signed("!=", d_key_obj, d_null_const)
        d_skip = self.pyobj_print.append_basic_block("dict_skip")
        d_live = self.pyobj_print.append_basic_block("dict_live")
        builder.cbranch(d_is_live, d_live, d_skip)

        builder.position_at_end(d_skip)
        builder.store(builder.add(d_i, ir.Constant(ir.IntType(64), 1)), d_idx)
        builder.branch(d_check)

        builder.position_at_end(d_live)
        d_not_first = builder.icmp_signed(
            ">", builder.load(d_printed), ir.Constant(ir.IntType(64), 0)
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
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
            )
        )
        builder.call(self.pyobj_repr_print, [d_key_obj])
        colon = self._create_global_string_with_builder(": ", builder)
        builder.call(self.printf, [colon])
        builder.call(self.pyobj_repr_print, [d_val_obj])
        builder.branch(d_incr)

        builder.position_at_end(d_incr)
        builder.store(
            builder.add(builder.load(d_printed), ir.Constant(ir.IntType(64), 1)),
            d_printed,
        )
        builder.store(builder.add(d_i, ir.Constant(ir.IntType(64), 1)), d_idx)
        builder.branch(d_check)

        builder.position_at_end(d_done)
        close_brace = self._create_global_string_with_builder("}", builder)
        builder.call(self.printf, [close_brace])
        builder.ret_void()

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
        # print with an explicit precision: string buffers are not
        # NUL-terminated (concat allocates exactly len bytes), so a
        # bare %s reads past the end into heap garbage
        str_len_ptr = builder.gep(
            str_struct, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]
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

    def _create_list_runtime(self):
        """Runtime for list PyObjects (tag 4).

        data points to {i64 length, i64 capacity, PyObject** items}.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)

        # create_list() is built in _create_pyobj_constructors so that
        # pyobj_add (list concatenation) can reference it.

        # PyObject* list_append(PyObject* list, PyObject* item)
        append_fn_ty = ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr])
        self.list_append = ir.Function(self.module, append_fn_ty, name="list_append")
        entry = self.list_append.append_basic_block("entry")
        grow_block = self.list_append.append_basic_block("grow")
        do_append_block = self.list_append.append_basic_block("do_append")
        builder = ir.IRBuilder(entry)
        list_arg, item_arg = self.list_append.args
        struct_ptr = self._load_list_struct(builder, list_arg)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        capacity = builder.load(builder.gep(struct_ptr, [zero32, one32]))
        needs_grow = builder.icmp_signed("==", length, capacity)
        builder.cbranch(needs_grow, grow_block, do_append_block)

        builder.position_at_end(grow_block)
        zero64 = ir.Constant(i64, 0)
        four64 = ir.Constant(i64, 4)
        cap_is_zero = builder.icmp_signed("==", capacity, zero64)
        new_capacity = builder.select(
            cap_is_zero, four64, builder.mul(capacity, ir.Constant(i64, 2))
        )
        new_items = builder.call(
            self.malloc, [builder.mul(new_capacity, ir.Constant(i64, 8))]
        )
        has_old = builder.icmp_signed(">", capacity, zero64)
        copy_block = self.list_append.append_basic_block("grow_copy")
        after_copy_block = self.list_append.append_basic_block("grow_after_copy")
        builder.cbranch(has_old, copy_block, after_copy_block)

        builder.position_at_end(copy_block)
        old_items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        builder.call(
            self.memcpy,
            [
                new_items,
                builder.bitcast(old_items, ir.PointerType(ir.IntType(8))),
                builder.mul(capacity, ir.Constant(i64, 8)),
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.branch(after_copy_block)

        builder.position_at_end(after_copy_block)
        builder.store(new_capacity, builder.gep(struct_ptr, [zero32, one32]))
        items_typed = builder.bitcast(new_items, ir.PointerType(pyobj_ptr))
        builder.store(
            items_typed, builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)])
        )
        builder.branch(do_append_block)

        builder.position_at_end(do_append_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        length_now = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        slot = builder.gep(items, [length_now])
        builder.store(item_arg, slot)
        builder.store(
            builder.add(length_now, ir.Constant(i64, 1)),
            builder.gep(struct_ptr, [zero32, zero32]),
        )
        builder.ret(list_arg)

        # i64 list_length(PyObject* list) - raw length helper
        self.list_length = ir.Function(
            self.module, ir.FunctionType(i64, [pyobj_ptr]), name="list_length"
        )
        builder = ir.IRBuilder(self.list_length.append_basic_block("entry"))
        struct_ptr = self._load_list_struct(builder, self.list_length.args[0])
        builder.ret(builder.load(builder.gep(struct_ptr, [zero32, zero32])))

        # PyObject* list_get(PyObject* list, PyObject* index)
        self.list_get = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="list_get",
        )
        entry = self.list_get.append_basic_block("entry")
        bounds_block = self.list_get.append_basic_block("bounds")
        negative_block = self.list_get.append_basic_block("negative")
        ok_block = self.list_get.append_basic_block("ok")
        error_block = self.list_get.append_basic_block("index_error")
        builder = ir.IRBuilder(entry)
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
            "IndexError: list index out of range\n", builder
        )
        builder.call(self.printf, [error_msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        slot = builder.gep(items, [adjusted_index])
        builder.ret(builder.load(slot))

        # void list_set(PyObject* list, PyObject* index, PyObject* value)
        self.list_set = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="list_set",
        )
        entry = self.list_set.append_basic_block("entry")
        neg_block = self.list_set.append_basic_block("negative")
        bounds_block = self.list_set.append_basic_block("bounds")
        ok_block = self.list_set.append_basic_block("ok")
        error_block = self.list_set.append_basic_block("index_error")
        builder = ir.IRBuilder(entry)
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
            "IndexError: list assignment index out of range\n", builder
        )
        builder.call(self.printf, [error_msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        builder.position_at_end(ok_block)
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        builder.store(value_arg, builder.gep(items, [adjusted_index]))
        builder.ret_void()

        # PyObject* pyobj_len(PyObject* obj) - len() for lists and strings
        self.pyobj_len = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="pyobj_len"
        )
        entry = self.pyobj_len.append_basic_block("entry")
        list_block = self.pyobj_len.append_basic_block("len_list")
        str_check_block = self.pyobj_len.append_basic_block("str_check")
        str_block = self.pyobj_len.append_basic_block("len_str")
        dict_check_block = self.pyobj_len.append_basic_block("dict_check")
        dict_block = self.pyobj_len.append_basic_block("len_dict")
        error_block = self.pyobj_len.append_basic_block("error")
        builder = ir.IRBuilder(entry)
        obj_arg = self.pyobj_len.args[0]
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.Constant(i32, 4))
        builder.cbranch(is_list, list_block, str_check_block)

        builder.position_at_end(list_block)
        struct_ptr = self._load_list_struct(builder, obj_arg)
        list_len = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [list_len]))

        builder.position_at_end(str_check_block)
        is_str = builder.icmp_signed("==", tag, ir.Constant(i32, 2))
        builder.cbranch(is_str, str_block, dict_check_block)

        builder.position_at_end(str_block)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [builder.sext(str_len, i64)]))

        builder.position_at_end(dict_check_block)
        is_dict = builder.icmp_signed("==", tag, ir.Constant(i32, 5))
        builder.cbranch(is_dict, dict_block, error_block)

        builder.position_at_end(dict_block)
        dict_data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        dict_struct_ptr = builder.bitcast(
            dict_data, ir.PointerType(self.dict_struct_type)
        )
        dict_count = builder.load(builder.gep(dict_struct_ptr, [zero32, zero32]))
        builder.ret(builder.call(self.create_int, [dict_count]))

        builder.position_at_end(error_block)
        builder.ret(ir.Constant(pyobj_ptr, None))

    def _create_list_and_str_method_runtime(self):
        """Runtime for list methods and string methods/equality."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8p = ir.PointerType(ir.IntType(8))
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        items_ptr_t = ir.PointerType(pyobj_ptr)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)
        zero64 = ir.Constant(i64, 0)
        one64 = ir.Constant(i64, 1)

        def for_i64_loop(builder, func, prefix, start, stop):
            """Emit a counting loop header; caller fills body, then closes."""
            idx_ptr = builder.alloca(i64, name=f"{prefix}_i")
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

        def close_loop(builder, idx_ptr, cond):
            builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
            builder.branch(cond)

        def load_list_parts(builder, func, obj, prefix):
            """Return (struct_ptr, length, items) with items loop-ready."""
            struct_ptr = self._load_list_struct(builder, obj)
            length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
            items = builder.load(builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
            return struct_ptr, length, items

        # i1 pyobj_truthy(PyObject* obj) - Python truthiness by type
        self.pyobj_truthy = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr]),
            name="pyobj_truthy",
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
        builder = ir.IRBuilder(entry)
        (obj_arg,) = self.pyobj_truthy.args
        null_obj = ir.Constant(pyobj_ptr, None)
        is_null = builder.icmp_signed("==", obj_arg, null_obj)
        builder.cbranch(is_null, false_case, dispatch_block)

        builder.position_at_end(dispatch_block)
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        switch = builder.switch(tag, true_case)
        switch.add_case(ir.Constant(i32, 0), int_case)
        switch.add_case(ir.Constant(i32, 1), float_case)
        switch.add_case(ir.Constant(i32, 2), str_case)
        switch.add_case(ir.Constant(i32, 3), int_case)
        switch.add_case(ir.Constant(i32, 4), list_case)
        switch.add_case(ir.Constant(i32, 5), dict_case)

        builder.position_at_end(int_case)
        int_val = self._load_number_as_i64(builder, obj_arg)
        builder.ret(builder.icmp_signed("!=", int_val, ir.Constant(i64, 0)))

        builder.position_at_end(float_case)
        f64_val = self._load_number_as_f64(builder, obj_arg)
        builder.ret(
            builder.fcmp_ordered("!=", f64_val, ir.Constant(ir.DoubleType(), 0.0))
        )

        builder.position_at_end(str_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", str_len, ir.Constant(i32, 0)))

        builder.position_at_end(list_case)
        list_struct_ptr = self._load_list_struct(builder, obj_arg)
        list_len = builder.load(builder.gep(list_struct_ptr, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", list_len, ir.Constant(i64, 0)))

        builder.position_at_end(dict_case)
        dict_data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        dict_struct_ptr = builder.bitcast(
            dict_data, ir.PointerType(self.dict_struct_type)
        )
        dict_count = builder.load(builder.gep(dict_struct_ptr, [zero32, zero32]))
        builder.ret(builder.icmp_signed("!=", dict_count, ir.Constant(i64, 0)))

        builder.position_at_end(true_case)
        builder.ret(ir.Constant(ir.IntType(1), 1))

        builder.position_at_end(false_case)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        # i1 pyobj_deep_eq(PyObject* a, PyObject* b) - structural equality
        # numeric: value compare (int/bool/float mix); str: memcmp;
        # list: recursive pairwise compare
        self.pyobj_deep_eq = ir.Function(
            self.module,
            ir.FunctionType(ir.IntType(1), [pyobj_ptr, pyobj_ptr]),
            name="pyobj_deep_eq",
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
        builder = ir.IRBuilder(entry)
        arg_a, arg_b = self.pyobj_deep_eq.args
        null_a = builder.icmp_signed("==", arg_a, ir.Constant(pyobj_ptr, None))
        null_b = builder.icmp_signed("==", arg_b, ir.Constant(pyobj_ptr, None))
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
        builder.cbranch(same_kind, dispatch_block, false_block)

        builder.position_at_end(dispatch_block)
        is_num_tag = self._is_numeric_tag(builder, tag_a)
        is_str_tag = builder.icmp_signed("==", tag_a, ir.Constant(i32, 2))
        is_list_tag = builder.icmp_signed("==", tag_a, ir.Constant(i32, 4))
        builder.cbranch(is_num_tag, num_check_block, str_check_block)

        builder.position_at_end(num_check_block)
        either_float = builder.or_(
            builder.icmp_signed("==", tag_a, ir.Constant(i32, 1)),
            builder.icmp_signed("==", tag_b, ir.Constant(i32, 1)),
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
            ir.Constant(i32, 0),
        )
        builder.ret(same_chars)

        builder.position_at_end(list_check_block)
        builder.cbranch(is_list_tag, list_body_block, false_block)

        builder.position_at_end(list_body_block)
        struct_a = self._load_list_struct(builder, arg_a)
        struct_b = self._load_list_struct(builder, arg_b)
        len_a = builder.load(builder.gep(struct_a, [zero32, zero32]))
        len_b = builder.load(builder.gep(struct_b, [zero32, zero32]))
        items_a = builder.load(builder.gep(struct_a, [zero32, ir.Constant(i32, 2)]))
        items_b = builder.load(builder.gep(struct_b, [zero32, ir.Constant(i32, 2)]))
        lens_match = builder.icmp_signed("==", len_a, len_b)
        builder.cbranch(lens_match, list_len_bad_block, false_block)

        builder.position_at_end(list_len_bad_block)
        diff_ptr = builder.alloca(ir.IntType(1), name="deep_diff")
        builder.store(ir.Constant(ir.IntType(1), 0), diff_ptr)
        idx_ptr = builder.alloca(i64, name="deep_i")
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
        builder.store(ir.Constant(ir.IntType(1), 1), diff_ptr)
        builder.branch(keep_going)

        builder.position_at_end(keep_going)
        builder.store(builder.add(current, one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(after)
        no_diff = builder.not_(builder.load(diff_ptr))
        builder.ret(no_diff)

        builder.position_at_end(false_block)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        # PyObject* list_reverse(PyObject* list)
        self.list_reverse = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="list_reverse"
        )
        builder = ir.IRBuilder(self.list_reverse.append_basic_block("entry"))
        (list_arg,) = self.list_reverse.args
        struct_ptr, length, items = load_list_parts(
            builder, self.list_reverse, list_arg, "rev"
        )
        idx_ptr, cond, body, done = for_i64_loop(
            builder,
            self.list_reverse,
            "rev",
            zero64,
            builder.sdiv(length, ir.Constant(i64, 2)),
        )
        back = builder.sub(builder.sub(length, one64), builder.load(idx_ptr))
        front_slot = builder.gep(items, [builder.load(idx_ptr)])
        back_slot = builder.gep(items, [back])
        front_val = builder.load(front_slot)
        builder.store(builder.load(back_slot), front_slot)
        builder.store(front_val, back_slot)
        close_loop(builder, idx_ptr, cond)
        builder.position_at_end(done)
        builder.ret(list_arg)

        # PyObject* list_insert(PyObject* list, PyObject* index, PyObject* item)
        self.list_insert = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="list_insert",
        )
        builder = ir.IRBuilder(self.list_insert.append_basic_block("entry"))
        list_arg, index_arg, item_arg = self.list_insert.args
        struct_ptr, length, items = load_list_parts(
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
            self.malloc, [builder.mul(new_length, ir.Constant(i64, 8))]
        )
        new_items = builder.bitcast(new_items, items_ptr_t)
        idx_ptr, cond, body, done = for_i64_loop(
            builder, self.list_insert, "ins1", zero64, clamped
        )
        builder.store(
            builder.load(builder.gep(items, [builder.load(idx_ptr)])),
            builder.gep(new_items, [builder.load(idx_ptr)]),
        )
        close_loop(builder, idx_ptr, cond)
        builder.position_at_end(done)
        builder.store(item_arg, builder.gep(new_items, [clamped]))
        idx_ptr, cond, body, done = for_i64_loop(
            builder, self.list_insert, "ins2", clamped, length
        )
        shifted = builder.add(builder.load(idx_ptr), one64)
        builder.store(
            builder.load(builder.gep(items, [builder.load(idx_ptr)])),
            builder.gep(new_items, [shifted]),
        )
        close_loop(builder, idx_ptr, cond)
        builder.position_at_end(done)
        builder.store(new_length, builder.gep(struct_ptr, [zero32, zero32]))
        builder.store(new_items, builder.gep(struct_ptr, [zero32, ir.Constant(i32, 2)]))
        builder.ret(list_arg)

        # PyObject* list_count(PyObject* list, PyObject* item)
        self.list_count = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="list_count",
        )
        builder = ir.IRBuilder(self.list_count.append_basic_block("entry"))
        list_arg, item_arg = self.list_count.args
        struct_ptr, length, items = load_list_parts(
            builder, self.list_count, list_arg, "cnt"
        )
        count_ptr = builder.alloca(i64, name="count_acc")
        builder.store(zero64, count_ptr)
        idx_ptr, cond, body, done = for_i64_loop(
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
        close_loop(builder, idx_ptr, cond)
        builder.position_at_end(done)
        builder.ret(builder.call(self.create_int, [builder.load(count_ptr)]))

        # PyObject* list_copy(PyObject* list)
        self.list_copy = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="list_copy"
        )
        builder = ir.IRBuilder(self.list_copy.append_basic_block("entry"))
        (list_arg,) = self.list_copy.args
        struct_ptr, length, items = load_list_parts(
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
            self.malloc, [builder.mul(length, ir.Constant(i64, 8))]
        )
        builder.call(
            self.memcpy,
            [
                fresh_items,
                builder.bitcast(items, i8p),
                builder.mul(length, ir.Constant(i64, 8)),
                ir.Constant(ir.IntType(1), 0),
            ],
        )
        builder.store(length, builder.gep(new_struct, [zero32, zero32]))
        builder.store(length, builder.gep(new_struct, [zero32, one32]))
        builder.store(
            builder.bitcast(fresh_items, items_ptr_t),
            builder.gep(new_struct, [zero32, ir.Constant(i32, 2)]),
        )
        builder.branch(after_block)

        builder.position_at_end(after_block)
        builder.ret(new_list)

        # void list_clear(PyObject* list)
        self.list_clear = ir.Function(
            self.module, ir.FunctionType(ir.VoidType(), [pyobj_ptr]), name="list_clear"
        )
        builder = ir.IRBuilder(self.list_clear.append_basic_block("entry"))
        struct_ptr = self._load_list_struct(builder, self.list_clear.args[0])
        builder.store(zero64, builder.gep(struct_ptr, [zero32, zero32]))
        builder.ret_void()

        # PyObject* list_sum(PyObject* list)
        self.list_sum = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="list_sum"
        )
        builder = ir.IRBuilder(self.list_sum.append_basic_block("entry"))
        (list_arg,) = self.list_sum.args
        struct_ptr, length, items = load_list_parts(
            builder, self.list_sum, list_arg, "sum"
        )
        acc_ptr = builder.alloca(pyobj_ptr, name="sum_acc")
        builder.store(builder.call(self.create_int, [zero64]), acc_ptr)
        idx_ptr, cond, body, done = for_i64_loop(
            builder, self.list_sum, "sum", zero64, length
        )
        item = builder.load(builder.gep(items, [builder.load(idx_ptr)]))
        acc_next = builder.call(self.pyobj_add, [builder.load(acc_ptr), item])
        builder.store(acc_next, acc_ptr)
        close_loop(builder, idx_ptr, cond)
        builder.position_at_end(done)
        builder.ret(builder.load(acc_ptr))

        # --- string methods ---

        def emit_case_fold(builder, func, to_upper):
            (obj_arg,) = func.args
            data = builder.load(builder.gep(obj_arg, [zero32, one32]))
            str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
            length = builder.load(builder.gep(str_struct, [zero32, zero32]))
            chars = builder.load(builder.gep(str_struct, [zero32, one32]))
            buf = builder.call(
                self.malloc, [builder.add(builder.sext(length, i64), one64)]
            )
            idx_ptr, cond, body, done = for_i64_loop(
                builder, func, "fold", zero64, builder.sext(length, i64)
            )
            ch = builder.load(builder.gep(chars, [builder.load(idx_ptr)]))
            ch32 = builder.sext(ch, i32)
            if to_upper:
                in_range = builder.and_(
                    builder.icmp_signed(">=", ch32, ir.Constant(i32, 97)),
                    builder.icmp_signed("<=", ch32, ir.Constant(i32, 122)),
                )
                folded = builder.select(
                    in_range, builder.sub(ch, ir.Constant(ir.IntType(8), 32)), ch
                )
            else:
                in_range = builder.and_(
                    builder.icmp_signed(">=", ch32, ir.Constant(i32, 65)),
                    builder.icmp_signed("<=", ch32, ir.Constant(i32, 90)),
                )
                folded = builder.select(
                    in_range, builder.add(ch, ir.Constant(ir.IntType(8), 32)), ch
                )
            builder.store(folded, builder.gep(buf, [builder.load(idx_ptr)]))
            close_loop(builder, idx_ptr, cond)
            builder.position_at_end(done)
            builder.store(
                ir.Constant(ir.IntType(8), 0),
                builder.gep(buf, [builder.sext(length, i64)]),
            )
            builder.ret(builder.call(self.create_str, [buf, length]))

        self.str_upper = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="str_upper"
        )
        emit_case_fold(
            ir.IRBuilder(self.str_upper.append_basic_block("entry")),
            self.str_upper,
            to_upper=True,
        )
        self.str_lower = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, [pyobj_ptr]), name="str_lower"
        )
        emit_case_fold(
            ir.IRBuilder(self.str_lower.append_basic_block("entry")),
            self.str_lower,
            to_upper=False,
        )

        def emit_sub_search(builder, func, from_right):
            def string_parts(obj):
                data = builder.load(builder.gep(obj, [zero32, one32]))
                str_struct = builder.bitcast(
                    data, ir.PointerType(self.pyobj.string_type)
                )
                length = builder.load(builder.gep(str_struct, [zero32, zero32]))
                chars = builder.load(builder.gep(str_struct, [zero32, one32]))
                return builder.sext(length, i64), chars

            s_arg, sub_arg = func.args
            s_len, s_chars = string_parts(s_arg)
            sub_len, sub_chars = string_parts(sub_arg)
            too_long = builder.icmp_signed(">", sub_len, s_len)
            miss_block = func.append_basic_block("search_miss")
            scan_block = func.append_basic_block("search_scan")
            builder.cbranch(too_long, miss_block, scan_block)

            builder.position_at_end(miss_block)
            builder.ret(builder.call(self.create_int, [ir.Constant(i64, -1)]))

            builder.position_at_end(scan_block)
            last_pos = builder.add(builder.sub(s_len, sub_len), ir.Constant(i64, 1))
            start = builder.sub(last_pos, one64) if from_right else zero64
            idx_ptr = builder.alloca(i64, name="search_i")
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
                ir.Constant(i32, 0),
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
            builder.ret(builder.call(self.create_int, [ir.Constant(i64, -1)]))

        self.str_find = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="str_find",
        )
        emit_sub_search(
            ir.IRBuilder(self.str_find.append_basic_block("entry")),
            self.str_find,
            False,
        )
        self.str_rfind = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="str_rfind",
        )
        emit_sub_search(
            ir.IRBuilder(self.str_rfind.append_basic_block("entry")),
            self.str_rfind,
            True,
        )

    def _create_dict_runtime(self):
        """Runtime for dict PyObjects (tag 5): a CPython-style compact dict.

        Insertion-ordered entries array (deleted entries keep their slot
        with a null key) plus a power-of-two open-addressed index table
        whose slots hold entry_index + 1, 0 = empty, -1 = deleted.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)
        zero64 = ir.Constant(i64, 0)
        one64 = ir.Constant(i64, 1)
        pyobj_null = ir.Constant(pyobj_ptr, None)

        def dict_field(builder, struct_ptr, index):
            return builder.gep(
                struct_ptr,
                [zero32, ir.Constant(i32, index)],
            )

        def load_dict_parts(builder, obj):
            """Return (struct_ptr, count, used, mask, itable, entries)."""
            data = builder.load(builder.gep(obj, [zero32, one32]))
            struct_ptr = builder.bitcast(data, ir.PointerType(self.dict_struct_type))
            count = builder.load(dict_field(builder, struct_ptr, 0))
            used = builder.load(dict_field(builder, struct_ptr, 1))
            mask = builder.load(dict_field(builder, struct_ptr, 2))
            itable = builder.load(dict_field(builder, struct_ptr, 3))
            entries = builder.load(dict_field(builder, struct_ptr, 4))
            return struct_ptr, count, used, mask, itable, entries

        # i64 pyobj_hash(PyObject* obj)
        self.pyobj_hash = ir.Function(
            self.module, ir.FunctionType(i64, [pyobj_ptr]), name="pyobj_hash"
        )
        entry = self.pyobj_hash.append_basic_block("entry")
        dispatch = self.pyobj_hash.append_basic_block("dispatch")
        int_case = self.pyobj_hash.append_basic_block("hash_int")
        float_case = self.pyobj_hash.append_basic_block("hash_float")
        str_case = self.pyobj_hash.append_basic_block("hash_str")
        zero_case = self.pyobj_hash.append_basic_block("hash_zero")
        builder = ir.IRBuilder(entry)
        (obj_arg,) = self.pyobj_hash.args
        is_null = builder.icmp_signed("==", obj_arg, pyobj_null)
        builder.cbranch(is_null, zero_case, dispatch)

        builder.position_at_end(dispatch)
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        switch = builder.switch(tag, int_case)
        switch.add_case(ir.Constant(i32, 1), float_case)
        switch.add_case(ir.Constant(i32, 2), str_case)
        switch.add_case(ir.Constant(i32, 5), zero_case)

        builder.position_at_end(int_case)
        builder.ret(self._load_number_as_i64(builder, obj_arg))

        builder.position_at_end(float_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        bits = builder.load(builder.bitcast(data, ir.PointerType(i64)))
        # -0.0 must hash like 0.0 (they compare equal)
        neg_zero = builder.icmp_signed("==", bits, ir.Constant(i64, 0x8000000000000000))
        builder.ret(builder.select(neg_zero, zero64, bits))

        builder.position_at_end(str_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        # FNV-1a over the bytes
        hash_ptr = builder.alloca(i64, name="fnv_h")
        idx_ptr = builder.alloca(i64, name="fnv_i")
        builder.store(ir.Constant(i64, 0xCBF29CE484222325), hash_ptr)
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
        h_val = builder.mul(h_val, ir.Constant(i64, 0x100000001B3))
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
        self.dict_find_probe = ir.Function(
            self.module,
            ir.FunctionType(i64, [pyobj_ptr, pyobj_ptr, ir.PointerType(i64)]),
            name="dict_find_probe",
        )
        entry = self.dict_find_probe.append_basic_block("entry")
        probe_cond = self.dict_find_probe.append_basic_block("probe_cond")
        probe_body = self.dict_find_probe.append_basic_block("probe_body")
        probe_hit = self.dict_find_probe.append_basic_block("probe_hit")
        probe_empty = self.dict_find_probe.append_basic_block("probe_empty")
        probe_tomb = self.dict_find_probe.append_basic_block("probe_tomb")
        probe_step = self.dict_find_probe.append_basic_block("probe_step")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg, out_slot_arg = self.dict_find_probe.args
        _, _, _, mask, itable, entries = load_dict_parts(builder, dict_arg)
        hash_val = builder.call(self.pyobj_hash, [key_arg])
        slot_ptr = builder.alloca(i64, name="probe_slot")
        tomb_ptr = builder.alloca(i64, name="probe_tomb")
        builder.store(builder.and_(hash_val, mask), slot_ptr)
        builder.store(ir.Constant(i64, -1), tomb_ptr)
        builder.branch(probe_cond)

        builder.position_at_end(probe_cond)
        slot_val = builder.load(slot_ptr)
        table_val = builder.load(builder.gep(itable, [slot_val]))
        is_empty = builder.icmp_signed("==", table_val, zero64)
        is_tomb = builder.icmp_signed("==", table_val, ir.Constant(i64, -1))
        builder.cbranch(is_empty, probe_empty, probe_body)

        builder.position_at_end(probe_empty)
        first_tomb = builder.load(tomb_ptr)
        has_tomb = builder.icmp_signed(">=", first_tomb, zero64)
        use_slot = builder.select(has_tomb, first_tomb, slot_val)
        builder.store(use_slot, out_slot_arg)
        builder.ret(ir.Constant(i64, -1))

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
        self.dict_rehash = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr]),
            name="dict_rehash",
        )
        entry = self.dict_rehash.append_basic_block("entry")
        scan_cond = self.dict_rehash.append_basic_block("reh_scan_cond")
        scan_body = self.dict_rehash.append_basic_block("reh_scan_body")
        scan_dead = self.dict_rehash.append_basic_block("reh_scan_dead")
        scan_live = self.dict_rehash.append_basic_block("reh_scan_live")
        place_cond = self.dict_rehash.append_basic_block("reh_place_cond")
        scan_done = self.dict_rehash.append_basic_block("reh_scan_done")
        builder = ir.IRBuilder(entry)
        (dict_arg,) = self.dict_rehash.args
        struct_ptr, count, used, mask, itable, entries = load_dict_parts(
            builder, dict_arg
        )
        old_cap = builder.add(mask, one64)
        new_cap = builder.select(
            builder.icmp_signed("==", old_cap, zero64),
            ir.Constant(i64, 4),
            builder.mul(old_cap, ir.Constant(i64, 2)),
        )
        new_mask = builder.sub(new_cap, one64)
        new_table = builder.call(self.calloc, [new_cap, ir.Constant(i64, 8)])
        new_table = builder.bitcast(new_table, ir.PointerType(i64))
        new_entries = builder.call(
            self.malloc, [builder.mul(new_cap, ir.Constant(i64, 16))]
        )
        new_entries = builder.bitcast(new_entries, self.dict_entries_ptr_type)
        j_ptr = builder.alloca(i64, name="reh_j")
        i_ptr = builder.alloca(i64, name="reh_i")
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
        place_ptr = builder.alloca(i64, name="reh_s")
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
        builder.store(new_mask, dict_field(builder, struct_ptr, 2))
        builder.store(new_table, dict_field(builder, struct_ptr, 3))
        builder.store(new_entries, dict_field(builder, struct_ptr, 4))
        builder.store(builder.load(j_ptr), dict_field(builder, struct_ptr, 1))
        builder.ret_void()

        # PyObject* create_dict()
        self.create_dict = ir.Function(
            self.module, ir.FunctionType(pyobj_ptr, []), name="create_dict"
        )
        builder = ir.IRBuilder(self.create_dict.append_basic_block("entry"))
        obj_ptr = builder.call(self.malloc, [ir.Constant(i64, 16)])
        obj = builder.bitcast(obj_ptr, pyobj_ptr)
        builder.store(ir.Constant(i32, 5), builder.gep(obj, [zero32, zero32]))
        dict_ptr = builder.call(self.malloc, [ir.Constant(i64, 40)])
        dict_struct_ptr = builder.bitcast(
            dict_ptr, ir.PointerType(self.dict_struct_type)
        )
        # allocate the initial 4-slot index table and entries array so
        # probing never dereferences null
        initial_table = builder.call(
            self.calloc, [ir.Constant(i64, 4), ir.Constant(i64, 8)]
        )
        initial_table = builder.bitcast(initial_table, ir.PointerType(i64))
        initial_entries = builder.call(self.malloc, [ir.Constant(i64, 64)])
        initial_entries = builder.bitcast(initial_entries, self.dict_entries_ptr_type)
        for field_index, field_value in enumerate(
            [zero64, zero64, ir.Constant(i64, 3), initial_table, initial_entries]
        ):
            builder.store(
                field_value,
                builder.gep(
                    dict_struct_ptr,
                    [zero32, ir.Constant(i32, field_index)],
                ),
            )
        builder.store(dict_ptr, builder.gep(obj, [zero32, one32]))
        builder.ret(obj)

        # PyObject* dict_get_or(PyObject* d, PyObject* key, PyObject* default)
        self.dict_get_or = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="dict_get_or",
        )
        entry = self.dict_get_or.append_basic_block("entry")
        found_block = self.dict_get_or.append_basic_block("found")
        missing_block = self.dict_get_or.append_basic_block("missing")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg, default_arg = self.dict_get_or.args
        _, _, _, _, _, entries = load_dict_parts(builder, dict_arg)
        out_slot = builder.alloca(i64, name="get_slot")
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, missing_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(missing_block)
        builder.ret(default_arg)

        # void dict_set(PyObject* d, PyObject* key, PyObject* value)
        self.dict_set = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="dict_set",
        )
        entry = self.dict_set.append_basic_block("entry")
        capacity_check = self.dict_set.append_basic_block("capacity_check")
        rehash_block = self.dict_set.append_basic_block("do_rehash")
        probe_block = self.dict_set.append_basic_block("probe")
        replace_block = self.dict_set.append_basic_block("replace")
        insert_block = self.dict_set.append_basic_block("insert")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg, value_arg = self.dict_set.args
        struct_ptr, count, used, mask, itable, entries = load_dict_parts(
            builder, dict_arg
        )
        out_slot = builder.alloca(i64, name="set_slot")
        # grow the table BEFORE probing: a full table would send the
        # probe loop circling forever without finding an empty slot
        at_capacity = builder.icmp_signed("==", used, builder.add(mask, one64))
        builder.cbranch(at_capacity, rehash_block, capacity_check)

        builder.position_at_end(rehash_block)
        builder.call(self.dict_rehash, [dict_arg])
        builder.branch(capacity_check)

        builder.position_at_end(capacity_check)
        builder.branch(probe_block)

        builder.position_at_end(probe_block)
        _, count, used, mask, itable, entries = load_dict_parts(builder, dict_arg)
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, replace_block, insert_block)

        builder.position_at_end(replace_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.store(value_arg, builder.gep(entry_ptr, [zero32, one32]))
        builder.ret_void()

        builder.position_at_end(insert_block)
        _, count, used, mask, itable, entries = load_dict_parts(builder, dict_arg)
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        slot = builder.load(out_slot)
        builder.store(builder.add(used, one64), builder.gep(itable, [slot]))
        entry_ptr = builder.gep(entries, [zero32, used])
        builder.store(key_arg, builder.gep(entry_ptr, [zero32, zero32]))
        builder.store(value_arg, builder.gep(entry_ptr, [zero32, one32]))
        builder.store(builder.add(used, one64), dict_field(builder, struct_ptr, 1))
        builder.store(builder.add(count, one64), dict_field(builder, struct_ptr, 0))
        builder.ret_void()

        # PyObject* dict_pop(PyObject* d, PyObject* key)
        self.dict_pop = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="dict_pop",
        )
        entry = self.dict_pop.append_basic_block("entry")
        found_block = self.dict_pop.append_basic_block("found")
        missing_block = self.dict_pop.append_basic_block("missing")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg = self.dict_pop.args
        struct_ptr, count, used, mask, itable, entries = load_dict_parts(
            builder, dict_arg
        )
        out_slot = builder.alloca(i64, name="pop_slot")
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, missing_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        removed_value = builder.load(builder.gep(entry_ptr, [zero32, one32]))
        # mark the entry dead and its table slot as a tombstone
        builder.store(pyobj_null, builder.gep(entry_ptr, [zero32, zero32]))
        builder.store(
            ir.Constant(i64, -1),
            builder.gep(itable, [builder.load(out_slot)]),
        )
        builder.store(builder.sub(count, one64), dict_field(builder, struct_ptr, 0))
        builder.ret(removed_value)

        builder.position_at_end(missing_block)
        builder.ret(pyobj_null)

        # void dict_clear_entries(PyObject* d)
        self.dict_clear_entries = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr]),
            name="dict_clear_entries",
        )
        entry = self.dict_clear_entries.append_basic_block("entry")
        wipe_cond = self.dict_clear_entries.append_basic_block("wipe_cond")
        wipe_body = self.dict_clear_entries.append_basic_block("wipe_body")
        wipe_done = self.dict_clear_entries.append_basic_block("wipe_done")
        builder = ir.IRBuilder(entry)
        (dict_arg,) = self.dict_clear_entries.args
        struct_ptr, _, _, mask, itable, _ = load_dict_parts(builder, dict_arg)
        builder.store(zero64, dict_field(builder, struct_ptr, 0))
        builder.store(zero64, dict_field(builder, struct_ptr, 1))
        wipe_idx = builder.alloca(i64, name="wipe_i")
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
        self.dict_setdefault = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="dict_setdefault",
        )
        entry = self.dict_setdefault.append_basic_block("entry")
        found_block = self.dict_setdefault.append_basic_block("found")
        insert_block = self.dict_setdefault.append_basic_block("insert")
        builder = ir.IRBuilder(entry)
        dict_arg, key_arg, default_arg = self.dict_setdefault.args
        _, _, _, _, _, entries = load_dict_parts(builder, dict_arg)
        out_slot = builder.alloca(i64, name="sd_slot")
        found = builder.call(self.dict_find_probe, [dict_arg, key_arg, out_slot])
        hit = builder.icmp_signed(">=", found, zero64)
        builder.cbranch(hit, found_block, insert_block)

        builder.position_at_end(found_block)
        entry_ptr = builder.gep(entries, [zero32, found])
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(insert_block)
        builder.call(self.dict_set, [dict_arg, key_arg, default_arg])
        builder.ret(default_arg)

        # void dict_update(PyObject* dst, PyObject* src)
        # src may be a dict (copy live entries) or a list of [k, v] pairs
        self.dict_update = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr]),
            name="dict_update",
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
        builder = ir.IRBuilder(entry)
        dst_arg, src_arg = self.dict_update.args
        src_tag = builder.load(builder.gep(src_arg, [zero32, zero32]))
        is_list_src = builder.icmp_signed("==", src_tag, ir.Constant(i32, 4))
        builder.cbranch(is_list_src, src_is_list, src_tag_check)

        # list source: each item is a [key, value] pair
        builder.position_at_end(src_is_list)
        list_struct_ptr = self._load_list_struct(builder, src_arg)
        pair_count = builder.load(builder.gep(list_struct_ptr, [zero32, zero32]))
        pair_items = builder.load(
            builder.gep(list_struct_ptr, [zero32, ir.Constant(i32, 2)])
        )
        pair_idx = builder.alloca(i64, name="upd_pair_i")
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
            builder.gep(pair_struct, [zero32, ir.Constant(i32, 2)])
        )
        pair_key = builder.load(builder.gep(pair_elems, [zero64]))
        pair_value = builder.load(builder.gep(pair_elems, [one64]))
        builder.call(self.dict_set, [dst_arg, pair_key, pair_value])
        builder.store(builder.add(pair_i, one64), pair_idx)
        builder.branch(pair_loop_check)

        builder.position_at_end(pair_loop_done)
        builder.ret_void()

        # dict source: copy all live entries
        builder.position_at_end(src_tag_check)
        _, _, src_used, _, _, src_entries = load_dict_parts(builder, src_arg)
        upd_idx = builder.alloca(i64, name="upd_i")
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

        # {i32,i8*}* pyobj_subscript(PyObject* obj, PyObject* key)
        # tag dispatch: 4 -> list_get, 5 -> dict_get_or(key, null)
        self.pyobj_subscript = ir.Function(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr]),
            name="pyobj_subscript",
        )
        entry = self.pyobj_subscript.append_basic_block("entry")
        list_block = self.pyobj_subscript.append_basic_block("sub_list")
        dict_check = self.pyobj_subscript.append_basic_block("sub_dict_check")
        dict_do = self.pyobj_subscript.append_basic_block("sub_dict_do")
        error_block = self.pyobj_subscript.append_basic_block("sub_error")
        builder = ir.IRBuilder(entry)
        obj_arg, key_arg = self.pyobj_subscript.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.Constant(i32, 4))
        builder.cbranch(is_list, list_block, dict_check)

        builder.position_at_end(list_block)
        builder.ret(builder.call(self.list_get, [obj_arg, key_arg]))

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.Constant(i32, 5))
        builder.cbranch(is_dict, dict_do, error_block)

        builder.position_at_end(dict_do)
        # d[k] on a missing key is a KeyError (Python raises, Rust panics);
        # .get() with its default goes through dict_get_or instead
        out_slot = builder.alloca(ir.IntType(64), name="sub_slot")
        found = builder.call(self.dict_find_probe, [obj_arg, key_arg, out_slot])
        is_hit = builder.icmp_signed(">=", found, ir.Constant(ir.IntType(64), 0))
        hit_block = self.pyobj_subscript.append_basic_block("sub_dict_hit")
        key_error = self.pyobj_subscript.append_basic_block("sub_key_error")
        builder.cbranch(is_hit, hit_block, key_error)

        builder.position_at_end(hit_block)
        _, _, _, _, _, entries = load_dict_parts(builder, obj_arg)
        entry_ptr = builder.gep(
            entries,
            [zero32, found],
        )
        builder.ret(builder.load(builder.gep(entry_ptr, [zero32, one32])))

        builder.position_at_end(key_error)
        key_msg = self._create_global_string_with_builder(
            "KeyError: key not found\n", builder
        )
        builder.call(self.printf, [key_msg])
        builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
        builder.unreachable()

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "TypeError: object is not subscriptable\n", builder
        )
        builder.call(self.printf, [error_msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        # void pyobj_subscript_set(PyObject* obj, PyObject* key, PyObject* value)
        self.pyobj_subscript_set = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr, pyobj_ptr, pyobj_ptr]),
            name="pyobj_subscript_set",
        )
        entry = self.pyobj_subscript_set.append_basic_block("entry")
        list_block = self.pyobj_subscript_set.append_basic_block("sub_list")
        dict_check = self.pyobj_subscript_set.append_basic_block("sub_dict_check")
        dict_do = self.pyobj_subscript_set.append_basic_block("sub_dict_do")
        error_block = self.pyobj_subscript_set.append_basic_block("sub_error")
        builder = ir.IRBuilder(entry)
        obj_arg, key_arg, value_arg = self.pyobj_subscript_set.args
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.Constant(i32, 4))
        builder.cbranch(is_list, list_block, dict_check)

        builder.position_at_end(list_block)
        builder.call(self.list_set, [obj_arg, key_arg, value_arg])
        builder.ret_void()

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.Constant(i32, 5))
        builder.cbranch(is_dict, dict_do, error_block)

        builder.position_at_end(dict_do)
        builder.call(self.dict_set, [obj_arg, key_arg, value_arg])
        builder.ret_void()

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "TypeError: object does not support item assignment\n", builder
        )
        builder.call(self.printf, [error_msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

        # void pyobj_clear(PyObject* obj) - clear() for lists and dicts
        self.pyobj_clear = ir.Function(
            self.module,
            ir.FunctionType(ir.VoidType(), [pyobj_ptr]),
            name="pyobj_clear",
        )
        entry = self.pyobj_clear.append_basic_block("entry")
        list_case = self.pyobj_clear.append_basic_block("clear_list")
        dict_check = self.pyobj_clear.append_basic_block("clear_dict_check")
        dict_case = self.pyobj_clear.append_basic_block("clear_dict")
        error_block = self.pyobj_clear.append_basic_block("clear_error")
        builder = ir.IRBuilder(entry)
        obj_arg = self.pyobj_clear.args[0]
        tag = builder.load(builder.gep(obj_arg, [zero32, zero32]))
        is_list = builder.icmp_signed("==", tag, ir.Constant(i32, 4))
        builder.cbranch(is_list, list_case, dict_check)

        builder.position_at_end(list_case)
        builder.call(self.list_clear, [obj_arg])
        builder.ret_void()

        builder.position_at_end(dict_check)
        is_dict = builder.icmp_signed("==", tag, ir.Constant(i32, 5))
        builder.cbranch(is_dict, dict_case, error_block)

        builder.position_at_end(dict_case)
        builder.call(self.dict_clear_entries, [obj_arg])
        builder.ret_void()

        builder.position_at_end(error_block)
        error_msg = self._create_global_string_with_builder(
            "AttributeError: object has no clear()\n", builder
        )
        builder.call(self.printf, [error_msg])
        builder.call(self.exit_func, [ir.Constant(i32, 1)])
        builder.unreachable()

    def _create_str_repeat_runtime(self):
        """PyObject* str_repeat(PyObject* s, PyObject* count) - "ab" * 3.

        Built before pyobj_mul so the str*int dispatch can reference it.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)
        zero64 = ir.Constant(i64, 0)
        one64 = ir.Constant(i64, 1)

        self.str_repeat = ir.Function(
            self.module,
            ir.FunctionType(
                ir.PointerType(self.pyobj.pyobj_type),
                [
                    ir.PointerType(self.pyobj.pyobj_type),
                    ir.PointerType(self.pyobj.pyobj_type),
                ],
            ),
            name="str_repeat",
        )
        builder = ir.IRBuilder(self.str_repeat.append_basic_block("entry"))
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
        idx_ptr = builder.alloca(i64, name="rep_i")
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
            [dest, s_chars, s_len, ir.Constant(ir.IntType(1), 0)],
        )
        builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
        builder.branch(cond)

        builder.position_at_end(done)
        builder.store(ir.Constant(ir.IntType(8), 0), builder.gep(buf, [total]))
        builder.ret(builder.call(self.create_str, [buf, builder.trunc(total, i32)]))

    def _load_list_struct(self, builder, obj):
        """Load the list struct pointer from a list PyObject (tag 4)."""
        data = builder.load(
            builder.gep(
                obj,
                [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
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
        self,
        func_name: str,
        int_apply=None,
        float_apply=None,
        str_int_apply=None,
        zero_check=False,
        overflow_check=False,
    ) -> ir.Function:
        """Create a pyobj arithmetic function over int/bool/float operands.

        int_apply(builder, left_i64, right_i64) returns the i64 result,
        delivered as an int PyObject. float_apply(builder, left_f64,
        right_f64) returns the double result, delivered as a float
        PyObject. With int_apply None the operation always promotes to
        float (Python true division always returns float).
        str_int_apply(builder, str_obj, int_obj) handles str*int mixes
        (string repetition) when provided.
        zero_check aborts on zero right operand (Python/Rust division).
        overflow_check aborts on i64 overflow (Rust debug panic semantics).
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
        str_op_block = (
            func.append_basic_block("str_op") if str_int_apply is not None else None
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

        def is_intish(tag):
            zero = ir.Constant(ir.IntType(32), 0)
            return builder.or_(
                builder.icmp_signed("==", tag, zero),
                builder.icmp_signed("==", tag, ir.Constant(ir.IntType(32), 3)),
            )

        def is_str(tag):
            return builder.icmp_signed("==", tag, ir.Constant(ir.IntType(32), 2))

        if str_int_apply is not None:
            # str*int / int*str goes to the repetition path first
            str_mix = builder.or_(
                builder.and_(is_str(left_tag), is_intish(right_tag)),
                builder.and_(is_str(right_tag), is_intish(left_tag)),
            )
            str_gate_block = func.append_basic_block("str_gate")
            builder.cbranch(str_mix, str_op_block, str_gate_block)

            builder.position_at_end(str_op_block)
            left_is_str = is_str(left_tag)
            str_obj = builder.select(left_is_str, left, right)
            int_obj = builder.select(left_is_str, right, left)
            str_result = str_int_apply(builder, str_obj, int_obj)
            builder.ret(str_result)

            builder.position_at_end(str_gate_block)
            builder.cbranch(both_numeric, num_check_block, error_block)
        else:
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
        if zero_check:
            float_is_zero = builder.fcmp_ordered(
                "==", right_f64, ir.Constant(ir.DoubleType(), 0.0)
            )
            fbad_block = func.append_basic_block("float_zero")
            fok_block = func.append_basic_block("float_ok")
            builder.cbranch(float_is_zero, fbad_block, fok_block)

            builder.position_at_end(fbad_block)
            fmsg = self._create_global_string_with_builder(
                "ZeroDivisionError: division by zero\n", builder
            )
            builder.call(self.printf, [fmsg])
            builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
            builder.unreachable()
            builder.position_at_end(fok_block)

        float_result = float_apply(builder, left_f64, right_f64)
        builder.ret(builder.call(self.create_float, [float_result]))

        if int_apply is not None:
            builder.position_at_end(int_op_block)
            left_i64 = self._load_number_as_i64(builder, left)
            right_i64 = self._load_number_as_i64(builder, right)

            if zero_check:
                int_is_zero = builder.icmp_signed(
                    "==", right_i64, ir.Constant(ir.IntType(64), 0)
                )
                zbad_block = func.append_basic_block("int_zero")
                zok_block = func.append_basic_block("int_ok")
                builder.cbranch(int_is_zero, zbad_block, zok_block)

                builder.position_at_end(zbad_block)
                zmsg = self._create_global_string_with_builder(
                    "ZeroDivisionError: division by zero\n", builder
                )
                builder.call(self.printf, [zmsg])
                builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
                builder.unreachable()
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
                    f"OverflowError: integer overflow in {func_name}\n", builder
                )
                builder.call(self.printf, [omsg])
                builder.call(self.exit_func, [ir.Constant(ir.IntType(32), 1)])
                builder.unreachable()
                builder.position_at_end(ook_block)
            else:
                int_result = int_apply(builder, left_i64, right_i64)
            builder.ret(builder.call(self.create_int, [int_result]))

        builder.position_at_end(error_block)
        builder.ret(ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))
        return func

    def _create_bool_result_function(self, func_name: str, pred: str) -> ir.Function:
        """Create a comparison function over int/bool/float/str operands.

        pred is one of "==", "!=", "<", "<=", ">", ">=". String
        operands compare via memcmp byte order (UTF-8 byte order equals
        Python code point order) with length breaking ties.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero32 = ir.Constant(i32, 0)
        one32 = ir.Constant(i32, 1)
        str_tag = ir.Constant(i32, 2)

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
        str_check_block = func.append_basic_block("str_check")
        builder.cbranch(both_numeric, num_check_block, str_check_block)

        # str <op> str for every predicate: memcmp byte order (UTF-8
        # byte order equals Python code point order) with the length
        # difference breaking ties, matching rawstr_cmp
        builder.position_at_end(str_check_block)
        both_str = builder.and_(
            builder.icmp_signed("==", left_tag, str_tag),
            builder.icmp_signed("==", right_tag, str_tag),
        )
        str_op_block = func.append_basic_block("str_op")
        builder.cbranch(both_str, str_op_block, error_block)

        builder.position_at_end(str_op_block)

        def string_parts(obj):
            data = builder.load(builder.gep(obj, [zero32, one32]))
            str_struct = builder.bitcast(
                data, ir.PointerType(self.pyobj.string_type)
            )
            length = builder.load(builder.gep(str_struct, [zero32, zero32]))
            chars = builder.load(builder.gep(str_struct, [zero32, one32]))
            return length, chars

        left_len, left_chars = string_parts(left)
        right_len, right_chars = string_parts(right)
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
            builder.icmp_signed("==", memcmp_i64, ir.Constant(i64, 0)),
            builder.sub(builder.sext(left_len, i64), builder.sext(right_len, i64)),
            memcmp_i64,
        )
        str_result = builder.icmp_signed(
            pred, order, ir.Constant(i64, 0)
        )
        builder.ret(builder.call(self.create_bool, [str_result]))

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

        # signed sub and mul with overflow detection (Rust panic semantics)
        self.ssub_overflow = ir.Function(
            self.module, sadd_overflow_ty, name="llvm.ssub.with.overflow.i64"
        )
        self.smul_overflow = ir.Function(
            self.module, sadd_overflow_ty, name="llvm.smul.with.overflow.i64"
        )
        self.overflow_intrinsics = {
            "sub": self.ssub_overflow,
            "mul": self.smul_overflow,
        }

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

    def _emit_truthiness(self, obj: ir.Value) -> ir.Value:
        """Emit a null-aware truthiness test; returns an i1 phi.

        Null pointers (unsupported/void values) are treated as false,
        everything else goes through the pyobj_truthy runtime.
        """
        builder = self.current_builder
        null_ptr = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
        is_null = builder.icmp_signed("==", obj, null_ptr)

        check_block = builder.block
        call_block = self.current_function.append_basic_block("truthy_call")
        merge_block = self.current_function.append_basic_block("truthy_merge")
        builder.cbranch(is_null, merge_block, call_block)

        builder.position_at_end(call_block)
        truthy = builder.call(self.pyobj_truthy, [obj])
        builder.branch(merge_block)

        builder.position_at_end(merge_block)
        phi = builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), check_block)
        phi.add_incoming(truthy, call_block)
        return phi

    def _extract_bool_condition(self, test_val: ir.Value) -> ir.Value:
        """Extract an i1 condition from a PyObject (Python truthiness)."""
        return self._emit_truthiness(test_val)

    def _convert_list_for_loop(self, target_node, iter_node, body_stmts):
        """For loop over a list: for item in some_list."""
        i64 = ir.IntType(64)
        builder = self.current_builder

        list_obj = self._convert_node(iter_node)
        if not list_obj:
            return None

        cond_block = self.current_function.append_basic_block("iter_cond")
        body_block = self.current_function.append_basic_block("iter_body")
        incr_block = self.current_function.append_basic_block("iter_incr")
        end_block = self.current_function.append_basic_block("iter_end")

        # Raw i64 index counter
        counter_ptr = builder.alloca(i64, name="iter_idx")
        builder.store(ir.Constant(i64, 0), counter_ptr)
        list_len = builder.call(self.list_length, [list_obj])
        builder.branch(cond_block)

        builder.position_at_end(cond_block)
        index = builder.load(counter_ptr)
        more = builder.icmp_signed("<", index, list_len)
        builder.cbranch(more, body_block, end_block)

        self.loop_break_blocks.append(end_block)
        self.loop_continue_blocks.append(incr_block)

        builder.position_at_end(body_block)
        if (
            isinstance(target_node, list)
            and len(target_node) >= 2
            and target_node[0] == "name"
        ):
            var_name = target_node[1]
            if var_name not in self.variables:
                self.variables[var_name] = builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type), name=var_name
                )
            item = builder.call(
                self.list_get, [list_obj, builder.call(self.create_int, [index])]
            )
            builder.store(item, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)

        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        next_index = self.current_builder.add(
            self.current_builder.load(counter_ptr), ir.Constant(i64, 1)
        )
        self.current_builder.store(next_index, counter_ptr)
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return None

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
                str_len = len(value.encode('utf-8'))  # byte length, not char count
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

        elif op == "ann_assign":
            # x: int = 5 - statically typed assignment. The annotation is
            # recorded in the IR (node[3]) but per project direction no
            # type inference is performed; runtime semantics match assign.
            return self._convert_node(["assign", node[1], node[2]])

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

        elif op == "not":
            operand = self._convert_node(node[1])
            if operand:
                truthy = self._emit_truthiness(operand)
                negated = self.current_builder.not_(truthy)
                return self.current_builder.call(self.create_bool, [negated])
            return None

        elif op in ("and", "or"):
            # N-ary short-circuit returning the deciding operand object:
            #   a and b and c -> first falsy operand, else the last
            #   a or b or c   -> first truthy operand, else the last
            builder = self.current_builder
            operands = node[1:]
            is_and = op == "and"
            null_const = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
            result_ptr = builder.alloca(
                ir.PointerType(self.pyobj.pyobj_type), name="sc_result"
            )
            end_block = self.current_function.append_basic_block("sc_end")

            for index, operand_node in enumerate(operands):
                val = self._convert_node(operand_node) or null_const
                if index == len(operands) - 1:
                    builder.store(val, result_ptr)
                    builder.branch(end_block)
                    break
                truthy = self._emit_truthiness(val)
                finish_block = self.current_function.append_basic_block("sc_finish")
                next_block = self.current_function.append_basic_block("sc_next")
                if is_and:
                    builder.cbranch(truthy, next_block, finish_block)
                else:
                    builder.cbranch(truthy, finish_block, next_block)

                builder.position_at_end(finish_block)
                builder.store(val, result_ptr)
                builder.branch(end_block)
                builder.position_at_end(next_block)

            builder.position_at_end(end_block)
            return builder.load(result_ptr)

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

            # Method calls: obj.method(args)
            if (
                isinstance(func_node, list)
                and len(func_node) >= 3
                and func_node[0] == "attribute"
            ):
                obj_val = self._convert_node(func_node[1])
                method_name = func_node[2]
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
                    # dict methods
                    "get": (self.dict_get_or, 2, True),
                    "setdefault": (self.dict_setdefault, 2, True),
                    "pop": (self.dict_pop, 1, True),
                    "__getitem__": (self.dict_get_or, 2, True),
                    "__setitem__": (self.dict_set, 2, False),
                    "__delitem__": (self.dict_pop, 1, False),
                }
                entry = method_map.get(method_name)
                if obj_val and entry:
                    func, arg_count, has_result = entry
                    arg_vals = [
                        self._convert_node(arg_node)
                        for arg_node in args_node[:arg_count]
                    ]
                    # Optional-argument methods (get/setdefault) pad with
                    # null, which the runtimes treat as None.
                    while len(arg_vals) < arg_count:
                        arg_vals.append(
                            ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)
                        )
                    if len(arg_vals) == arg_count and all(arg_vals):
                        result = self.current_builder.call(func, [obj_val] + arg_vals)
                        return result if has_result else None
                return None

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

                elif func_name == "len":
                    if args_node:
                        arg_val = self._convert_node(args_node[0])
                        if arg_val:
                            return self.current_builder.call(self.pyobj_len, [arg_val])
                    return None

                elif func_name == "sum":
                    if args_node:
                        arg_val = self._convert_node(args_node[0])
                        if arg_val:
                            return self.current_builder.call(self.list_sum, [arg_val])
                    return None

                elif func_name == "dict":
                    # dict(), dict({...}), dict(a=1, b=2)
                    dict_obj = self.current_builder.call(self.create_dict, [])
                    for arg_node in args_node:
                        arg_val = self._convert_node(arg_node)
                        if arg_val:
                            self.current_builder.call(
                                self.dict_update, [dict_obj, arg_val]
                            )
                    for kw_name, kw_value_node in node[3] if len(node) > 3 else []:
                        key_val = self._convert_node(["const", kw_name])
                        value_val = self._convert_node(kw_value_node)
                        if key_val and value_val:
                            self.current_builder.call(
                                self.dict_set, [dict_obj, key_val, value_val]
                            )
                    return dict_obj

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

                    # Loop body (break -> end, continue -> condition)
                    self.loop_break_blocks.append(end_block)
                    self.loop_continue_blocks.append(cond_block)
                    self.current_builder.position_at_end(body_block)
                    for stmt in body_stmts:
                        self._convert_node(stmt)
                        if self.current_builder.block.is_terminated:
                            break
                    self.loop_break_blocks.pop()
                    self.loop_continue_blocks.pop()
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(cond_block)

                    # Continue after loop
                    self.current_builder.position_at_end(end_block)

                return None

        elif op == "break":
            if self.loop_break_blocks:
                self.current_builder.branch(self.loop_break_blocks[-1])
            return None

        elif op == "continue":
            if self.loop_continue_blocks:
                self.current_builder.branch(self.loop_continue_blocks[-1])
            return None

        elif op == "aug_assign":
            # i <op>= value  =>  i = i <op> value
            if len(node) >= 3:
                target_node, bin_op, value_node = node[1], node[2], node[3]
                func = {
                    "+=": self.pyobj_add,
                    "-=": self.pyobj_sub,
                    "*=": self.pyobj_mul,
                    "/=": self.pyobj_truediv,
                    "//=": self.pyobj_floordiv,
                    "%=": self.pyobj_mod,
                }.get(bin_op)
                if func is None:
                    return None
                right = self._convert_node(value_node)
                if not right:
                    return None
                if (
                    isinstance(target_node, list)
                    and len(target_node) >= 3
                    and target_node[0] == "subscript"
                ):
                    # obj[i] <op>= value: read-modify-write through the
                    # dynamic subscript runtime
                    obj = self._convert_node(target_node[1])
                    key = self._convert_node(target_node[2])
                    if not obj or not key:
                        return None
                    current = self.current_builder.call(
                        self.pyobj_subscript, [obj, key]
                    )
                    result = self.current_builder.call(func, [current, right])
                    self.current_builder.call(
                        self.pyobj_subscript_set, [obj, key, result]
                    )
                    return None
                target_name = target_node[1]
                if target_name not in self.variables:
                    return None
                left = self.current_builder.load(self.variables[target_name])
                result = self.current_builder.call(func, [left, right])
                self.current_builder.store(result, self.variables[target_name])
            return None

        elif op == "for":
            if len(node) >= 4:
                target_node = node[1]
                iter_node = node[2]
                body_stmts = node[3]

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
                    return self._convert_list_for_loop(
                        target_node, iter_node, body_stmts
                    )

                # range() handling: extract start/stop from the call
                args_node = iter_node[2] if len(iter_node) > 2 else []
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
                else:
                    start_val = self.current_builder.call(
                        self.create_int, [ir.Constant(ir.IntType(64), 0)]
                    )
                    end_val = self.current_builder.call(
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

                # Loop body (break -> loop_end, continue -> increment step)
                incr_block = self.current_function.append_basic_block("loop_incr")
                self.loop_break_blocks.append(loop_end)
                self.loop_continue_blocks.append(incr_block)
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
                    self.current_builder.branch(incr_block)

                self.loop_break_blocks.pop()
                self.loop_continue_blocks.pop()

                # Counter increment step (continue target)
                self.current_builder.position_at_end(incr_block)
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

        elif op == "list":
            # List literal: create runtime list and append each element
            list_obj = self.current_builder.call(self.create_list, [])
            for elem_node in node[1] if len(node) > 1 else []:
                elem_val = self._convert_node(elem_node)
                if elem_val:
                    self.current_builder.call(self.list_append, [list_obj, elem_val])
            return list_obj

        elif op == "subscript":
            if len(node) >= 3:
                obj_val = self._convert_node(node[1])
                index_val = self._convert_node(node[2])
                if obj_val and index_val:
                    # Runtime tag dispatch: list index vs dict key
                    return self.current_builder.call(
                        self.pyobj_subscript, [obj_val, index_val]
                    )
            return None

        elif op == "subscript_assign":
            if len(node) >= 4:
                obj_val = self._convert_node(node[1])
                index_val = self._convert_node(node[2])
                value_val = self._convert_node(node[3])
                if obj_val and index_val and value_val:
                    self.current_builder.call(
                        self.pyobj_subscript_set, [obj_val, index_val, value_val]
                    )
            return None

        elif op == "dict":
            # Dict literal: {"k": v, ...} pairs
            dict_obj = self.current_builder.call(self.create_dict, [])
            for pair_node in node[1] if len(node) > 1 else []:
                key_val = self._convert_node(pair_node[0])
                value_val = self._convert_node(pair_node[1])
                if key_val and value_val:
                    self.current_builder.call(
                        self.dict_set, [dict_obj, key_val, value_val]
                    )
            return dict_obj

        elif op == "tuple":
            # Tuples share the list runtime (Rust maps tuples to fixed-size
            # sequence values; iteration/len/index semantics are identical).
            # Known deviation: backed by a mutable list, so tuple item
            # assignment is not rejected as it would be in Rust/Python.
            tuple_obj = self.current_builder.call(self.create_list, [])
            for elem_node in node[1] if len(node) > 1 else []:
                elem_val = self._convert_node(elem_node)
                if elem_val:
                    self.current_builder.call(self.list_append, [tuple_obj, elem_val])
            return tuple_obj

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
