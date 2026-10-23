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


from .pyobj_runtime import (  # noqa: F401 - shared runtime helpers
    PyobjRuntimeMixin,
    _is_numeric_tag,
    _dict_field,
    _py_mod_apply,
    _floor_div_apply,
)


from .pyobj_runtime import (  # noqa: F401 - shared runtime helpers
    PyobjRuntimeMixin,
    _is_numeric_tag,
    _dict_field,
    _py_mod_apply,
    _floor_div_apply,
)


class SiluToLLVMConverter(PyobjRuntimeMixin):
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
        self._create_list_runtime()
        # comparisons go after the list/str runtime: ==/!= route
        # tag-4 boxes into pyobj_deep_eq, which is defined there
        self._create_list_and_str_method_runtime()
        self._create_comparison_operations()
        self._create_dict_runtime()


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
