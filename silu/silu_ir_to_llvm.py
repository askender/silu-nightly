"""
Silu IR to LLVM IR Converter

This module converts Silu IR (JSON format) to LLVM IR, enabling compilation
of Silu programs to native machine code.

The converter handles the dynamic typing of Silu by creating a runtime system
with tagged unions for Python-like objects.
"""

import sys
from typing import Any, Dict, Optional
from silu.ir_iface import ir
import llvmlite.binding as llvm
from .ir_utils import parse_ir_from_json_string, IRParseError


class PyObject:
    """Runtime representation of Python objects in LLVM IR."""

    module: object
    pyobj_type: object
    string_type: object


def pyobj_new(module):
    p = PyObject(
        module,
        ir.LiteralStructType(
            [
                ir.IntType(32),
                ir.PointerType(ir.IntType(8)),
            ]
        ),
        ir.LiteralStructType(
            [
                ir.IntType(32),
                ir.PointerType(ir.IntType(8)),
            ]
        ),
    )
    return p


def _dict_field(builder, struct_ptr, index):
    return builder.gep(
        struct_ptr,
        [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), index)],
    )

def _normalize_ir(node: Any) -> Any:
    """Recursively convert tuple IR nodes to lists.

    parse_ir_from_json_string returns tuple structures, while node
    dispatch in this converter expects lists.
    """
    if isinstance(node, (list, tuple)):
        out = []
        for item in node:
            out.append(_normalize_ir(item))
        return out
    return node


def _py_mod_apply(builder, left_val, right_val):
    """Python modulo: result has the sign of the divisor."""
    i64 = ir.IntType(64)
    zero = ir.const_(i64, 0)
    r = builder.srem(left_val, right_val)
    r_ne_zero = builder.icmp_signed("!=", r, zero)
    r_negative = builder.icmp_signed("<", r, zero)
    right_negative = builder.icmp_signed("<", right_val, zero)
    signs_differ = builder.xor(r_negative, right_negative)
    adjust = builder.and_(r_ne_zero, signs_differ)
    adj_val = builder.select(adjust, right_val, zero)
    return builder.add(r, adj_val)


def _floor_div_apply(builder, left_val, right_val):
    """Python floor division: rounds toward negative infinity."""
    i64 = ir.IntType(64)
    zero = ir.const_(i64, 0)
    q = builder.sdiv(left_val, right_val)
    r = builder.srem(left_val, right_val)
    r_ne_zero = builder.icmp_signed("!=", r, zero)
    r_negative = builder.icmp_signed("<", r, zero)
    right_negative = builder.icmp_signed("<", right_val, zero)
    signs_differ = builder.xor(r_negative, right_negative)
    adjust = builder.and_(r_ne_zero, signs_differ)
    adj_val = builder.select(adjust, ir.const_(i64, -1), zero)
    return builder.add(q, adj_val)


def _is_numeric_tag(builder, tag):
    """True if the tag is int (0), float (1), or bool (3)."""
    i32 = ir.IntType(32)
    return builder.or_(
        builder.icmp_signed("==", tag, ir.const_(i32, 0)),
        builder.or_(
            builder.icmp_signed("==", tag, ir.const_(i32, 1)),
            builder.icmp_signed("==", tag, ir.const_(i32, 3)),
        ),
    )


class SiluToLLVMConverter:
    """Converts Silu IR to LLVM IR."""

    def __init__(self):
        # created lazily by whichever runtime builder runs first
        self.realloc = None
        # Initialize LLVM (llvmlite >= 0.44 initializes automatically and
        # its explicit initialize() raises; older versions require it)
        try:
            llvm.initialize()
        except RuntimeError:
            pass
        llvm.initialize_native_target()
        llvm.initialize_native_asmprinter()

        # Get target information
        target = llvm.Target.from_default_triple()
        self.target_machine = target.create_target_machine()

        # Create LLVM module
        self.module = ir.module_('silu_module', )
        self.module.triple = self.target_machine.triple
        self.module.data_layout = str(self.target_machine.target_data)

        # Runtime object system
        self.pyobj = pyobj_new(self.module)

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
            ir.IntType(32), [ir.PointerType(ir.IntType(8))], True
        )
        self.printf = ir.func_(self.module, printf_ty, 'printf')

        # malloc and free
        malloc_ty = ir.FunctionType(ir.PointerType(ir.IntType(8)), [ir.IntType(64)], False)
        self.malloc = ir.func_(self.module, malloc_ty, 'malloc')

        # calloc for zero-initialized hash index tables
        calloc_ty = ir.FunctionType(
            ir.PointerType(ir.IntType(8)), [ir.IntType(64), ir.IntType(64)], False
        )
        self.calloc = ir.func_(self.module, calloc_ty, 'calloc')

        free_ty = ir.FunctionType(ir.VoidType(), [ir.PointerType(ir.IntType(8))], False)
        self.free = ir.func_(self.module, free_ty, 'free')

        # llvm.memcpy for string concatenation
        memcpy_ty = ir.FunctionType(
            ir.VoidType(),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
                ir.IntType(1),
            ], False,
        )
        self.memcpy = ir.func_(
            self.module, memcpy_ty, 'llvm.memcpy.p0i8.p0i8.i64'
        )
        memset_ty = ir.FunctionType(
            ir.VoidType(),
            [
                ir.PointerType(ir.IntType(8)),
                ir.IntType(8),
                ir.IntType(64),
                ir.IntType(1),
            ], False,
        )
        self.memset = ir.func_(
            self.module, memset_ty, 'llvm.memset.p0i8.i64'
        )

        # exit for runtime error aborts
        exit_ty = ir.FunctionType(ir.VoidType(), [ir.IntType(32)], False)
        self.exit_func = ir.func_(self.module, exit_ty, 'exit')

        # current source line, updated by ("line", n) IR markers so
        # runtime errors can report where they happened
        self.line_global = ir.gvar_(
            self.module, ir.IntType(64), '__silu_line'
        )
        self.line_global.linkage = "internal"
        self.line_global.initializer = ir.const_(ir.IntType(64), 0)

        # void silu_panic(i8* msg) - print "msg (line N)" and exit(1).
        # Every runtime error path goes through here, including the
        # shared runtime functions (the line global is read at panic
        # time, so even line-less helpers report the failing statement).
        i8p = ir.PointerType(ir.IntType(8))
        self.silu_panic = ir.func_(
            self.module, ir.FunctionType(ir.VoidType(), [i8p], False), 'silu_panic',

        )
        entry = self.silu_panic.append_basic_block("entry")
        line_block = self.silu_panic.append_basic_block("with_line")
        plain_block = self.silu_panic.append_basic_block("no_line")
        builder = ir.builder_(entry)
        panic_msg = self.silu_panic.args[0]
        fmt_s = self._create_global_string_with_builder("%s", builder)
        builder.call(self.printf, [fmt_s, panic_msg])
        cur_line = builder.load(self.line_global)
        has_line = builder.icmp_signed(
            ">", cur_line, ir.const_(ir.IntType(64), 0)
        )
        builder.cbranch(has_line, line_block, plain_block)

        builder.position_at_end(line_block)
        fmt_line = self._create_global_string_with_builder(" (line %d)\n", builder)
        builder.call(self.printf, [fmt_line, cur_line])
        builder.call(self.exit_func, [ir.const_(ir.IntType(32), 1)])
        builder.unreachable()

        builder.position_at_end(plain_block)
        fmt_nl = self._create_global_string_with_builder("\n", builder)
        builder.call(self.printf, [fmt_nl])
        builder.call(self.exit_func, [ir.const_(ir.IntType(32), 1)])
        builder.unreachable()

        # libc helpers for Python-style float printing
        # (fmt is a fixed parameter of snprintf, not a vararg)
        snprintf_ty = ir.FunctionType(
            ir.IntType(32),
            [
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
                ir.PointerType(ir.IntType(8)),
            ], True,

        )
        self.snprintf = ir.func_(self.module, snprintf_ty, 'snprintf')

        strtod_ty = ir.FunctionType(
            ir.DoubleType(),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.PointerType(ir.IntType(8))),
            ], False,
        )
        self.strtod = ir.func_(self.module, strtod_ty, 'strtod')

        memchr_ty = ir.FunctionType(
            ir.PointerType(ir.IntType(8)),
            [ir.PointerType(ir.IntType(8)), ir.IntType(32), ir.IntType(64)], False,
        )
        self.memchr = ir.func_(self.module, memchr_ty, 'memchr')

        strlen_ty = ir.FunctionType(ir.IntType(64), [ir.PointerType(ir.IntType(8))], False)
        self.strlen = ir.func_(self.module, strlen_ty, 'strlen')

        memcmp_ty = ir.FunctionType(
            ir.IntType(32),
            [
                ir.PointerType(ir.IntType(8)),
                ir.PointerType(ir.IntType(8)),
                ir.IntType(64),
            ], False,
        )
        self.memcmp = ir.func_(self.module, memcmp_ty, 'memcmp')

        # llvm.floor.f64 intrinsic for float floor division
        floor_ty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType()], False)
        self.floor_f64 = ir.func_(self.module, floor_ty, 'llvm.floor.f64')

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

        # PyObject* create_bool(i1 value)
        create_bool_ty = ir.FunctionType(
            ir.PointerType(self.pyobj.pyobj_type), [ir.IntType(1)], False
        )
        self.create_bool = ir.func_(self.module, create_bool_ty, 'create_bool')

        block = self.create_bool.append_basic_block("entry")
        builder = ir.builder_(block)

        # Allocate PyObject
        obj_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 16)])
        obj = builder.bitcast(obj_ptr, ir.PointerType(self.pyobj.pyobj_type))

        # Set type tag to 3 (bool)
        tag_ptr = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 0)]
        )
        builder.store(ir.const_(ir.IntType(32), 3), tag_ptr)

        # Allocate and store the value as i64 0/1
        data_ptr = builder.call(self.malloc, [ir.const_(ir.IntType(64), 8)])
        data_i64 = builder.bitcast(data_ptr, ir.PointerType(ir.IntType(64)))
        bool_i64 = builder.zext(self.create_bool.args[0], ir.IntType(64))
        builder.store(bool_i64, data_i64)

        # Store data pointer
        data_ptr_field = builder.gep(
            obj, [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)]
        )
        builder.store(data_ptr, data_ptr_field)

        builder.ret(obj)

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

        # Error case - return null for now
        builder.position_at_end(error_block)
        builder.ret(ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

        # Arithmetic over int/bool/float operands with Python promotion rules
        self._create_str_repeat_runtime()
        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            lambda b, left, right: b.sub(left, right),
            lambda b, left, right: b.fsub(left, right),
            None,
            False,
            True,
        )
        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            lambda b, left, right: b.mul(left, right),
            lambda b, left, right: b.fmul(left, right),
            lambda b, s, n: b.call(self.str_repeat, [s, n]),
            False,
            True,
        )
        # Python true division always returns a float
        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            None,
            lambda b, left, right: b.fdiv(left, right),
            None,
            True,
            False,
        )
        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            _floor_div_apply,
            self._float_floordiv_apply,
            None,
            True,
            False,
        )
        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            _py_mod_apply,
            self._float_mod_apply,
            None,
            True,
            False,
        )
        # bitwise ops on int/bool PyObjects (float operands fall to the
        # error path - bitwise on floats is a type error)
        self.pyobj_bitor = self._create_numeric_binary_function(
            "bitor", lambda b, l, r: b.or_(l, r, ""), False,
            None, False, False,
        )
        self.pyobj_bitand = self._create_numeric_binary_function(
            "bitand", lambda b, l, r: b.and_(l, r, ""), False,
            None, False, False,
        )
        self.pyobj_bitxor = self._create_numeric_binary_function(
            "bitxor", lambda b, l, r: b.xor(l, r, ""), False,
            None, False, False,
        )
        self.pyobj_shl = self._create_numeric_binary_function(
            "shl", lambda b, l, r: b.shl(l, r, ""), False,
            None, False, False,
        )
        self.pyobj_shr = self._create_numeric_binary_function(
            "shr", lambda b, l, r: b.ashr(l, r, ""), False,
            None, False, False,
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



    def _panic_string(self, data, label):
        gv = ir.gvar_(
            self.module,
            ir.ArrayType(ir.IntType(8), len(data)), label,

        )
        gv.global_constant = True
        gv.initializer = ir.const_(
            ir.ArrayType(ir.IntType(8), len(data)), bytearray(data)
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
        i8p = ir.PointerType(ir.IntType(8))
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
        b = ir.builder_(entry)
        (obj_arg,) = fn.args
        tag = b.load(b.gep(obj_arg, [zero32, zero32]))
        b.cbranch(
            b.icmp_signed("==", tag, ir.const_(i32, 4)),
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
        b.ret(b.call(self.create_list, []))

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
        repr_str_case = self.pyobj_repr_print.append_basic_block("repr_str")
        repr_other = self.pyobj_repr_print.append_basic_block("repr_other")
        repr_builder = ir.builder_(repr_entry)
        repr_obj = self.pyobj_repr_print.args[0]
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

    def _create_list_runtime(self):
        """Runtime for list PyObjects (tag 4).

        data points to {i64 length, i64 capacity, PyObject** items}.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)

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
        is_list = builder.icmp_signed("==", tag, ir.const_(i32, 4))
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

    def _create_boxed_str_affix(self):
        """i1 str_starts_with / str_ends_with(PObj* s, PObj* p) - the
        boxed twins of the rawstr affix probes (emitted by the typed
        subclass; here we only declare wrappers when they exist)."""
        # emitted lazily by the typed subclass; nothing to do in base
        return None

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

        # i1 pyobj_deep_eq(PyObject* a, PyObject* b) - structural equality
        # numeric: value compare (int/bool/float mix); str: memcmp;
        # list: recursive pairwise compare
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
        builder.cbranch(same_kind, dispatch_block, false_block)

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
        builder.cbranch(is_inst_tag, inst_body_block, false_block)

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

        # PyObject* list_reverse(PyObject* list)
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

    def _create_dict_runtime(self):
        """Runtime for dict PyObjects (tag 5): a CPython-style compact dict.

        Insertion-ordered entries array (deleted entries keep their slot
        with a null key) plus a power-of-two open-addressed index table
        whose slots hold entry_index + 1, 0 = empty, -1 = deleted.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        zero32 = ir.const_(i32, 0)
        one32 = ir.const_(i32, 1)
        zero64 = ir.const_(i64, 0)
        one64 = ir.const_(i64, 1)
        pyobj_null = ir.const_(pyobj_ptr, None)

        dict_field = _dict_field

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
        # -0.0 must hash like 0.0 (they compare equal)
        neg_zero = builder.icmp_signed("==", bits, ir.const_(i64, 0x8000000000000000))
        builder.ret(builder.select(neg_zero, zero64, bits))

        builder.position_at_end(str_case)
        data = builder.load(builder.gep(obj_arg, [zero32, one32]))
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        # FNV-1a over the bytes
        hash_ptr = builder.alloca(i64, None, 'fnv_h')
        idx_ptr = builder.alloca(i64, None, 'fnv_i')
        builder.store(ir.const_(i64, 0xCBF29CE484222325), hash_ptr)
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
        builder.store(new_mask, dict_field(builder, struct_ptr, 2))
        builder.store(new_table, dict_field(builder, struct_ptr, 3))
        builder.store(new_entries, dict_field(builder, struct_ptr, 4))
        builder.store(builder.load(j_ptr), dict_field(builder, struct_ptr, 1))
        builder.ret_void()

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
        builder.store(builder.add(used, one64), dict_field(builder, struct_ptr, 1))
        builder.store(builder.add(count, one64), dict_field(builder, struct_ptr, 0))
        builder.ret_void()

        # PyObject* dict_pop(PyObject* d, PyObject* key)
        self.dict_pop = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr, pyobj_ptr], False), 'dict_pop',

        )
        entry = self.dict_pop.append_basic_block("entry")
        found_block = self.dict_pop.append_basic_block("found")
        missing_block = self.dict_pop.append_basic_block("missing")
        builder = ir.builder_(entry)
        dict_arg, key_arg = self.dict_pop.args
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
        builder.store(builder.sub(count, one64), dict_field(builder, struct_ptr, 0))
        builder.ret(removed_value)

        builder.position_at_end(missing_block)
        builder.ret(pyobj_null)

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
        is_list = builder.icmp_signed("==", container_tag, ir.const_(i32, 4))
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
        builder.store(zero64, dict_field(builder, struct_ptr, 0))
        builder.store(zero64, dict_field(builder, struct_ptr, 1))
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

        # PObj* dict_items_rt(PObj* d) - list of [key, value] pair boxes
        self.dict_items_rt = ir.func_(
            self.module,
            ir.FunctionType(pyobj_ptr, [pyobj_ptr], False), 'dict_items_rt',

        )
        b = ir.builder_(self.dict_items_rt.append_basic_block("entry"))
        (di_arg,) = self.dict_items_rt.args
        di_struct, di_count, di_used, di_mask, di_itable, di_entries = (
            self._load_dict_parts(
                b, di_arg,
                ir.const_(ir.IntType(32), 0),
                ir.const_(ir.IntType(32), 1),
            )
        )
        di_out = b.call(self.create_list, [])
        di_ptr, di_cond, di_body, di_done = self._for_i64_loop(i64, 
            b, self.dict_items_rt, "ditems", zero64, di_used
        )
        di_entry_ptr = b.gep(di_entries, [zero32, b.load(di_ptr)])
        di_key = b.load(b.gep(di_entry_ptr, [zero32, zero32]))
        di_val = b.load(b.gep(di_entry_ptr, [zero32, one32]))
        di_is_live = b.icmp_signed("!=", di_key, ir.const_(pyobj_ptr, None))
        di_live_blk = self.dict_items_rt.append_basic_block("ditems_live")
        di_step_blk = self.dict_items_rt.append_basic_block("ditems_step")
        b.cbranch(di_is_live, di_live_blk, di_step_blk)
        b.position_at_end(di_live_blk)
        di_pair = b.call(self.create_list, [])
        b.call(self.list_append, [di_pair, di_key])
        b.call(self.list_append, [di_pair, di_val])
        b.call(self.list_append, [di_out, di_pair])
        b.branch(di_step_blk)
        b.position_at_end(di_step_blk)
        self._close_i64_loop(b, di_ptr, di_cond, one64)
        b.position_at_end(di_done)
        b.ret(di_out)

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
        s_len = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
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
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        char_buf = builder.call(self.malloc, [one64])
        builder.store(
            builder.load(builder.gep(chars, [index_eff])), char_buf
        )
        builder.ret(builder.call(self.create_str, [char_buf, one32]))

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
        s_len = builder.sext(
            builder.load(builder.gep(str_struct, [zero32, zero32])), i64
        )
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
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
        alloc_len = builder.select(
            builder.icmp_signed(">", count, zero64), count, one64
        )
        out_buf = builder.call(self.malloc, [alloc_len])
        idx_ptr = builder.alloca(i64, None, 'slice_i')
        builder.store(zero64, idx_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_cond)
        idx = builder.load(idx_ptr)
        more = builder.icmp_signed("<", idx, count)
        builder.cbranch(more, copy_body, copy_done)

        builder.position_at_end(copy_body)
        src_index = builder.add(lo_eff, builder.mul(idx, step_arg))
        builder.store(
            builder.load(builder.gep(chars, [src_index])),
            builder.gep(out_buf, [idx]),
        )
        builder.store(builder.add(idx, one64), idx_ptr)
        builder.branch(copy_cond)

        builder.position_at_end(copy_done)
        builder.ret(
            builder.call(
                self.create_str, [out_buf, builder.trunc(count, i32)]
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
        builder.ret(ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))
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
        inst_op_block = func.append_basic_block("inst_op")
        builder.cbranch(inst_eq, inst_op_block, error_block)

        builder.position_at_end(inst_op_block)
        if pred == "==":
            builder.ret(builder.call(self.create_bool, [ir.const_(ir.IntType(1), 1)]))
        elif pred == "!=":
            builder.ret(builder.call(self.create_bool, [ir.const_(ir.IntType(1), 1)]))
        else:
            builder.branch(error_block)

        builder.position_at_end(str_gate_block)
        both_str = builder.and_(
            builder.icmp_signed("==", left_tag, str_tag),
            builder.icmp_signed("==", right_tag, str_tag),
        )
        str_op_block = func.append_basic_block("str_op")
        builder.cbranch(both_str, str_op_block, error_block)

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
        builder.ret(ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))
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

        # Float negation
        builder.position_at_end(float_block)
        f64_val = self._load_number_as_f64(builder, operand)
        float_result = builder.call(
            self.create_float,
            [builder.fsub(ir.const_(ir.DoubleType(), 0.0), f64_val)],
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

        # Create global variable
        global_str = ir.gvar_(
            self.module, string_type, f'str_{len(self.module.globals)}'
        )
        global_str.global_constant = True
        global_str.initializer = ir.const_(string_type, string_bytes)

        # Get pointer to first character
        zero = ir.const_(ir.IntType(32), 0)
        return builder.gep(global_str, [zero, zero])


    def convert(self, ir_json: str) -> str:
        """Convert Silu IR JSON to LLVM IR."""

        # Parse JSON
        try:
            ir_data = parse_ir_from_json_string(ir_json)
        except IRParseError as e:
            raise ValueError(f"Failed to parse IR: {e}")

        ir_data = _normalize_ir(ir_data)

        # First pass: collect function definitions. A user-defined
        # `main` is renamed to __silu_user_main up front and invoked
        # from the generated entry point (C forbids calling main, and
        # the module defines a `main` symbol of its own).
        self._collect_function_defs(ir_data)
        if "main" in self.function_defs:
            user_main = list(self.function_defs.pop("main"))
            user_main[1] = "__silu_user_main"
            self.function_defs["__silu_user_main"] = user_main
            self._renamed_user_main = True
            self._rename_main_callsites(ir_data)
        else:
            self._renamed_user_main = False

        # Second pass: create function declarations
        self._create_function_declarations()

        main_ty = ir.FunctionType(ir.IntType(32), [], False)
        main_func = ir.func_(self.module, main_ty, 'main')
        self.current_function = main_func

        entry_block = main_func.append_basic_block("entry")
        self.current_builder = ir.builder_(entry_block)

        # Convert IR (skip function definitions in main)
        self._convert_toplevel(ir_data)

        # A user main() becomes the program body
        if self._renamed_user_main:
            user_fn = self.functions.get("__silu_user_main") or (
                self.static_funcs.get("__silu_user_main", (None, None, None))[2]
            )
            if user_fn is not None:
                result = self.current_builder.call(user_fn, [])
                if result.type == ir.IntType(32):
                    self.current_builder.ret(result)
                elif result.type == ir.IntType(64):
                    self.current_builder.ret(
                        self.current_builder.trunc(result, ir.IntType(32))
                    )
                else:
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.ret(ir.const_(ir.IntType(32), 0))
            else:
                if not self.current_builder.block.is_terminated:
                    self.current_builder.ret(ir.const_(ir.IntType(32), 0))
        else:
            if not self.current_builder.block.is_terminated:
                self.current_builder.ret(ir.const_(ir.IntType(32), 0))

        # Generate function bodies
        self._generate_function_bodies()
        # funcref table (only the typed subclass fills _fn_table)
        if getattr(self, "_fn_table", None):
            self._emit_fn_table_init()

        return ir.module_str(self.module)

    def _rename_main_callsites(self, node):
        """Rewrite `main(...)` call targets to the renamed user main."""
        if isinstance(node, list):
            if (
                len(node) >= 3
                and node[0] == "call"
                and isinstance(node[1], list)
                and len(node[1]) >= 2
                and node[1][0] == "name"
                and node[1][1] == "main"
            ):
                node[1][1] = "__silu_user_main"
            for child in node:
                self._rename_main_callsites(child)
        elif isinstance(node, tuple):
            for child in node:
                self._rename_main_callsites(child)

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
                ir.PointerType(self.pyobj.pyobj_type), param_types, False
            )
            func = ir.func_(self.module, func_ty, func_name)
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
        null_ptr = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
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
        phi.add_incoming(ir.const_(ir.IntType(1), 0), check_block)
        phi.add_incoming(truthy, call_block)
        return phi

    def _extract_bool_condition(self, test_val: ir.Value) -> ir.Value:
        """Extract an i1 condition from a PyObject (Python truthiness)."""
        return self._emit_truthiness(test_val)

    def _convert_list_for_loop(self, target_node, iter_node, body_stmts):
        """For loop over a list: for item in some_list."""
        i64 = ir.IntType(64)
        builder = self.current_builder

        list_obj = self._convert_node(iter_node, False)
        if not list_obj:
            return None

        cond_block = self.current_function.append_basic_block("iter_cond")
        body_block = self.current_function.append_basic_block("iter_body")
        incr_block = self.current_function.append_basic_block("iter_incr")
        end_block = self.current_function.append_basic_block("iter_end")

        # Raw i64 index counter
        counter_ptr = builder.alloca(i64, None, 'iter_idx')
        builder.store(ir.const_(i64, 0), counter_ptr)
        list_len = builder.call(self.pyobj_iter_len, [list_obj])
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
                    ir.PointerType(self.pyobj.pyobj_type), None, var_name
                )
            item = builder.call(
                self.pyobj_subscript,
                [list_obj, builder.call(self.create_int, [index])],
            )
            builder.store(item, self.variables[var_name])

        for stmt in body_stmts:
            self._convert_node(stmt, False)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(incr_block)

        self.loop_break_blocks.pop()
        self.loop_continue_blocks.pop()

        self.current_builder.position_at_end(incr_block)
        next_index = self.current_builder.add(
            self.current_builder.load(counter_ptr), ir.const_(i64, 1)
        )
        self.current_builder.store(next_index, counter_ptr)
        self.current_builder.branch(cond_block)

        self.current_builder.position_at_end(end_block)
        return None

    def _convert_toplevel(self, node: Any):
        """Entry for the module root; subclasses override to route
        around their own _convert_node signature."""
        return self._convert_node(node, True)

    def _convert_node(
        self, node, skip_func_defs
    ) -> Optional[ir.Value]:
        """Convert a single IR node."""

        if not isinstance(node, list) or len(node) == 0:
            return None

        op = node[0]

        if op == "line":
            # statement-position marker: remember the source line so a
            # runtime panic further down can name it
            self.current_builder.store(
                ir.const_(ir.IntType(64), node[1]), self.line_global
            )
            return None

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
                    self.create_bool, [ir.const_(ir.IntType(1), value)]
                )
            elif isinstance(value, int):
                return self.current_builder.call(
                    self.create_int, [ir.const_(ir.IntType(64), value)]
                )
            elif isinstance(value, float):
                return self.current_builder.call(
                    self.create_float, [ir.const_(ir.DoubleType(), value)]
                )
            elif isinstance(value, str):
                # Create string constant
                str_len = len(value.encode('utf-8'))  # byte length, not char count
                str_ptr = self._create_global_string(value)
                return self.current_builder.call(
                    self.create_str, [str_ptr, ir.const_(ir.IntType(32), str_len)]
                )
            else:
                # For now, just treat other constants as integers
                return self.current_builder.call(
                    self.create_int, [ir.const_(ir.IntType(64), 0)]
                )

        elif op == "name":
            var_name = node[1]
            if var_name in self.variables:
                # Load the value from the alloca
                return self.current_builder.load(self.variables[var_name])
            else:
                # Return a null PyObject for undefined variables
                return ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)

        elif op == "assign":
            target = node[1]
            value_node = node[2]
            value = self._convert_node(value_node, False)
            if value and isinstance(target, str):
                # Create alloca if variable doesn't exist
                if target not in self.variables:
                    self.variables[target] = self.current_builder.alloca(
                        ir.PointerType(self.pyobj.pyobj_type), None, target
                    )
                # Store the value
                self.current_builder.store(value, self.variables[target])
            return value

        elif op == "ann_assign":
            # x: int = 5 - statically typed assignment. The annotation is
            # recorded in the IR (node[3]) but per project direction no
            # type inference is performed; runtime semantics match assign.
            return self._convert_node(["assign", node[1], node[2]], False)

        elif op == "+":
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_add, [left, right])
            return None

        elif op == "-":
            if len(node) == 2:
                # Unary minus: -operand
                operand = self._convert_node(node[1], False)
                if operand:
                    return self._create_unary_minus(operand)
            elif len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_sub, [left, right])
            return None

        elif op == "*":
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_mul, [left, right])
            return None

        elif op == "/":
            # Python true division: always promotes to float
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_truediv, [left, right])
            return None

        elif op == "//":
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_floordiv, [left, right])
            return None

        elif op == "%":
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(self.pyobj_mod, [left, right])
            return None

        elif op == "not":
            operand = self._convert_node(node[1], False)
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
            null_const = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
            result_ptr = builder.alloca(
                ir.PointerType(self.pyobj.pyobj_type), None, 'sc_result'
            )
            end_block = self.current_function.append_basic_block("sc_end")

            for index, operand_node in enumerate(operands):
                val = self._convert_node(operand_node, False) or null_const
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
                cond_val = self._convert_node(node[1], False)
                if cond_val:
                    then_block = self.current_function.append_basic_block("iexpr_then")
                    else_block = self.current_function.append_basic_block("iexpr_else")
                    merge_block = self.current_function.append_basic_block(
                        "iexpr_merge"
                    )
                    condition = self._extract_bool_condition(cond_val)
                    self.current_builder.cbranch(condition, then_block, else_block)

                    self.current_builder.position_at_end(then_block)
                    then_val = self._convert_node(node[2], False)
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    self.current_builder.position_at_end(else_block)
                    else_val = self._convert_node(node[3], False)
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
            func = self.pyobj_cmp[op]
            if len(node) >= 3:
                left = self._convert_node(node[1], False)
                right = self._convert_node(node[2], False)
                if left and right:
                    return self.current_builder.call(func, [left, right])
            return None

        elif op in ("in", "not in"):
            # (in, item, container); result is always a bool PyObject
            if len(node) >= 3:
                item = self._convert_node(node[1], False)
                container = self._convert_node(node[2], False)
                if item and container:
                    result = self.current_builder.call(
                        self.pyobj_contains, [container, item]
                    )
                    if op == "not in":
                        result = self.current_builder.not_(result)
                    return self.current_builder.call(self.create_bool, [result])
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
                obj_val = self._convert_node(func_node[1], False)
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
                    arg_vals = []
                    for arg_node in args_node[:arg_count]:
                        arg_vals.append(self._convert_node(arg_node, False))
                    # Optional-argument methods (get/setdefault) pad with
                    # null, which the runtimes treat as None.
                    while len(arg_vals) < arg_count:
                        arg_vals.append(
                            ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
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
                            arg_val = self._convert_node(arg_node, False)
                            if arg_val:
                                self.current_builder.call(self.pyobj_print, [arg_val])
                    # Add newline
                    newline_fmt = self._create_global_string("\n")
                    self.current_builder.call(self.printf, [newline_fmt])
                    return None

                elif func_name == "input":
                    return self.current_builder.call(self.pyobj_input, [])

                elif func_name == "str":
                    # scalar str() conversion: int/float/bool/str/None
                    if len(args_node) == 1:
                        arg_val = self._convert_node(args_node[0], False)
                        if arg_val:
                            return self.current_builder.call(
                                self.pyobj_str_conv, [arg_val]
                            )
                    return None

                elif func_name == "len":
                    if args_node:
                        arg_val = self._convert_node(args_node[0], False)
                        if arg_val:
                            return self.current_builder.call(self.pyobj_len, [arg_val])
                    return None

                elif func_name == "sum":
                    if args_node:
                        arg_val = self._convert_node(args_node[0], False)
                        if arg_val:
                            return self.current_builder.call(self.list_sum, [arg_val])
                    return None

                elif func_name == "dict":
                    # dict(), dict({...}), dict(a=1, b=2)
                    dict_obj = self.current_builder.call(self.create_dict, [])
                    for arg_node in args_node:
                        arg_val = self._convert_node(arg_node, False)
                        if arg_val:
                            self.current_builder.call(
                                self.dict_update, [dict_obj, arg_val]
                            )
                    for kw_name, kw_value_node in node[3] if len(node) > 3 else []:
                        key_val = self._convert_node(["const", kw_name], False)
                        value_val = self._convert_node(kw_value_node, False)
                        if key_val and value_val:
                            self.current_builder.call(
                                self.dict_set, [dict_obj, key_val, value_val]
                            )
                    return dict_obj

                elif func_name == "range":
                    # Handle range function with start and stop parameters
                    if len(args_node) == 1:
                        # range(stop) -> return stop
                        return self._convert_node(args_node[0], False)
                    elif len(args_node) >= 2:
                        # range(start, stop) -> return stop for loop iteration count
                        # For proper loop implementation, we need the stop value
                        stop_val = self._convert_node(args_node[1], False)
                        return (
                            stop_val
                            if stop_val
                            else self.current_builder.call(
                                self.create_int, [ir.const_(ir.IntType(64), 0)]
                            )
                        )
                    return self.current_builder.call(
                        self.create_int, [ir.const_(ir.IntType(64), 0)]
                    )

                elif func_name in self.functions:
                    # Handle user-defined function calls
                    func = self.functions[func_name]
                    llvm_args = []
                    for arg_node in args_node:
                        arg_val = self._convert_node(arg_node, False)
                        if arg_val:
                            llvm_args.append(arg_val)

                    if len(llvm_args) == len(func.args):
                        return self.current_builder.call(func, llvm_args)
                    else:
                        # Argument count mismatch - return null for now
                        return ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)

            return None

        elif op == "if":
            if len(node) >= 4:
                test_node = node[1]
                body_stmts = node[2]
                else_stmts = node[3]

                # Evaluate condition
                test_val = self._convert_node(test_node, False)
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
                        self._convert_node(stmt, False)
                        if self.current_builder.block.is_terminated:
                            break
                    if not self.current_builder.block.is_terminated:
                        self.current_builder.branch(merge_block)

                    # Generate else block
                    self.current_builder.position_at_end(else_block)
                    for stmt in else_stmts:
                        self._convert_node(stmt, False)
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
                test_val = self._convert_node(test_node, False)
                if test_val:
                    condition = self._extract_bool_condition(test_val)
                    self.current_builder.cbranch(condition, body_block, end_block)

                    # Loop body (break -> end, continue -> condition)
                    self.loop_break_blocks.append(end_block)
                    self.loop_continue_blocks.append(cond_block)
                    self.current_builder.position_at_end(body_block)
                    for stmt in body_stmts:
                        self._convert_node(stmt, False)
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
                right = self._convert_node(value_node, False)
                if not right:
                    return None
                if (
                    isinstance(target_node, list)
                    and len(target_node) >= 3
                    and target_node[0] == "subscript"
                ):
                    # obj[i] <op>= value: read-modify-write through the
                    # dynamic subscript runtime
                    obj = self._convert_node(target_node[1], False)
                    key = self._convert_node(target_node[2], False)
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
                        self.create_int, [ir.const_(ir.IntType(64), 0)]
                    )
                    end_val = self._convert_node(args_node[0], False)
                elif len(args_node) >= 2:
                    # range(start, stop) -> start=args[0], stop=args[1]
                    start_val = self._convert_node(args_node[0], False)
                    end_val = self._convert_node(args_node[1], False)
                else:
                    start_val = self.current_builder.call(
                        self.create_int, [ir.const_(ir.IntType(64), 0)]
                    )
                    end_val = self.current_builder.call(
                        self.create_int, [ir.const_(ir.IntType(64), 10)]
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
                    ir.PointerType(self.pyobj.pyobj_type), None, "counter"
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
                    [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), 1)],
                )
                data = self.current_builder.load(data_ptr)
                i64_ptr = self.current_builder.bitcast(
                    data, ir.PointerType(ir.IntType(64))
                )
                bool_val = self.current_builder.load(i64_ptr)
                condition = self.current_builder.icmp_signed(
                    "!=", bool_val, ir.const_(ir.IntType(64), 0)
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
                            ir.PointerType(self.pyobj.pyobj_type), None, var_name
                        )
                    # Store current iteration value
                    current_iter_val = self.current_builder.load(counter_ptr)
                    self.current_builder.store(
                        current_iter_val, self.variables[var_name]
                    )

                # Execute body statements
                for stmt in body_stmts:
                    self._convert_node(stmt, False)
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
                    self.create_int, [ir.const_(ir.IntType(64), 1)]
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
                        element_val = self._convert_node(element, False)
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
                                    ir.PointerType(self.pyobj.pyobj_type), None, target
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
                elem_val = self._convert_node(elem_node, False)
                if elem_val:
                    self.current_builder.call(self.list_append, [list_obj, elem_val])
            return list_obj

        elif op == "subscript":
            if len(node) >= 3:
                obj_val = self._convert_node(node[1], False)
                index_node = node[2]
                if (
                    isinstance(index_node, list)
                    and len(index_node) >= 4
                    and index_node[0] == "slice"
                    and obj_val
                ):
                    # s[lo:hi:step]: missing bounds are resolved inside
                    # the runtime helper (it owns the length)
                    lower_node, upper_node, step_node = (
                        index_node[1],
                        index_node[2],
                        index_node[3],
                    )
                    i64t = ir.IntType(64)
                    has_lo = ir.const_(ir.IntType(1), lower_node is not None)
                    has_hi = ir.const_(ir.IntType(1), upper_node is not None)
                    lo = (
                        self._load_number_as_i64(
                            self.current_builder,
                            self._convert_node(lower_node, False),
                        )
                        if lower_node is not None
                        else ir.const_(i64t, 0)
                    )
                    hi = (
                        self._load_number_as_i64(
                            self.current_builder,
                            self._convert_node(upper_node, False),
                        )
                        if upper_node is not None
                        else ir.const_(i64t, 0)
                    )
                    step = (
                        self._load_number_as_i64(
                            self.current_builder,
                            self._convert_node(step_node, False),
                        )
                        if step_node is not None
                        else ir.const_(i64t, 1)
                    )
                    return self.current_builder.call(
                        self.pyobj_str_slice,
                        [obj_val, lo, hi, step, has_lo, has_hi],
                    )
                index_val = self._convert_node(index_node, False)
                if obj_val and index_val:
                    # Runtime tag dispatch: list index vs dict key vs str index
                    return self.current_builder.call(
                        self.pyobj_subscript, [obj_val, index_val]
                    )
            return None

        elif op == "subscript_assign":
            if len(node) >= 4:
                obj_val = self._convert_node(node[1], False)
                index_val = self._convert_node(node[2], False)
                value_val = self._convert_node(node[3], False)
                if obj_val and index_val and value_val:
                    self.current_builder.call(
                        self.pyobj_subscript_set, [obj_val, index_val, value_val]
                    )
            return None

        elif op == "delete":
            # del obj[key]: dict_pop tombstones the entry; Python's del
            # raises KeyError when the key is missing
            if len(node) >= 3:
                obj_val = self._convert_node(node[1], False)
                key_val = self._convert_node(node[2], False)
                if obj_val and key_val:
                    popped = self.current_builder.call(
                        self.dict_pop, [obj_val, key_val]
                    )
                    is_null = self.current_builder.icmp_unsigned(
                        "==",
                        popped,
                        ir.const_(
                            ir.PointerType(self.pyobj.pyobj_type), None
                        ),
                    )
                    func = self.current_builder.function
                    ok_block = func.append_basic_block("del_ok")
                    err_block = func.append_basic_block("del_keyerr")
                    self.current_builder.cbranch(is_null, err_block, ok_block)
                    self.current_builder.position_at_end(err_block)
                    err_msg = self._create_global_string_with_builder(
                        "KeyError: key not found", self.current_builder
                    )
                    self._emit_panic(self.current_builder, err_msg)
                    self.current_builder.position_at_end(ok_block)
            return None

        elif op == "dict":
            # Dict literal: {"k": v, ...} pairs
            dict_obj = self.current_builder.call(self.create_dict, [])
            for pair_node in node[1] if len(node) > 1 else []:
                key_val = self._convert_node(pair_node[0], False)
                value_val = self._convert_node(pair_node[1], False)
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
                elem_val = self._convert_node(elem_node, False)
                if elem_val:
                    self.current_builder.call(self.list_append, [tuple_obj, elem_val])
            return tuple_obj

        elif op == "return":
            # Handle return statements
            if len(node) > 1:
                return_val = self._convert_node(node[1], False)
                if (
                    return_val
                    and self.current_function
                    and not self.current_builder.block.is_terminated
                ):
                    self.current_builder.ret(return_val)
                    return return_val
            # Return None/null if no value
            null_val = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
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
        self.current_builder = ir.builder_(entry_block)

        # Set up parameters as variables
        for i, param_name in enumerate(param_names):
            if i < len(func.args):
                # Create alloca for parameter and store the argument value
                param_alloca = self.current_builder.alloca(
                    ir.PointerType(self.pyobj.pyobj_type), None, param_name
                )
                self.current_builder.store(func.args[i], param_alloca)
                self.variables[param_name] = param_alloca

        # Generate function body
        return_generated = False
        for stmt in body_stmts:
            # result =
            self._convert_node(stmt, False)
            if isinstance(stmt, list) and len(stmt) > 0 and stmt[0] == "return":
                return_generated = True
                break

        # Add default return if no explicit return
        if not return_generated and not self.current_builder.block.is_terminated:
            null_val = ir.const_(ir.PointerType(self.pyobj.pyobj_type), None)
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


def _pyobj_init(self, module, pyobj_type, string_type):
    # Python bootstrap for the dual-valid PyObject (Silu's auto-ctor
    # already has this shape); the flatten script strips this hook
    self.module = module
    self.pyobj_type = pyobj_type
    self.string_type = string_type


PyObject.__init__ = _pyobj_init
