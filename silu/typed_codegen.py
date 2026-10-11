"""Statically-typed LLVM code generation for Silu (no PyObject boxing).

This backend consumes the static type annotations written in the source
(``x: int = 0``, ``def f(a: int) -> int``) and represents those scalars
as raw machine values:

    int   -> i64 on the stack
    float -> double on the stack
    bool  -> i1 on the stack
    str / list / dict / unannotated -> PyObject* (the dynamic runtime)

No type inference is performed: only declared annotations and literal
types drive the representation. Expression kinds propagate by Python's
own numeric semantics (int+float promotes to float, ``/`` always yields
float, range variables are always int) - that is semantic propagation,
not inference. Values cross between the static and dynamic worlds at
explicit boundaries (print, containers, dynamic variables and calls)
through box/unbox steps.

Arithmetic follows the project panic policy: i64 add/sub/mul use the
llvm.s*.with.overflow intrinsics and division/modulo check for zero
divisors; both abort with a message instead of failing silently.

Select this backend with SILU_CODEGEN=typed (the default); set
SILU_CODEGEN=dynamic to restore the fully-dynamic PyObject backend.
"""

from typing import Any, Dict, List, Optional, Tuple

from llvmlite import ir

from .silu_ir_to_llvm import SiluToLLVMConverter

I64 = "i64"
F64 = "f64"
I1 = "i1"
OBJ = "obj"

ANNOTATION_KINDS = {"int": I64, "float": F64, "bool": I1}

LLVM_KIND_TYPES = {
    I64: ir.IntType(64),
    F64: ir.DoubleType(),
    I1: ir.IntType(1),
}


class TypedCodegen(SiluToLLVMConverter):
    """LLVM backend with unboxed scalars driven by source annotations."""

    def __init__(self):
        super().__init__()
        # kind of every named variable in the current scope
        self.var_kinds: Dict[str, str] = {}
        # name -> (param_kinds, return_kind, llvm.Function) for
        # fully-annotated numeric functions (raw machine ABI)
        self.static_funcs: Dict[str, Tuple[List[str], Optional[str], ir.Function]] = {}
        self.current_ret_kind: Optional[str] = None
        self._create_unbox_runtime()

    # ================== runtime additions ==================

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
        raise ValueError(f"unknown kind {kind}")

    def _coerce(self, tv: Tuple[str, Any], target: str) -> Tuple[str, Any]:
        """Convert a TypedValue to the target kind."""
        kind, value = tv
        if kind == target:
            return tv
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
        return self._emit_truthiness(value)

    # ================== variables ==================

    def _declare_var(self, name: str, kind: str):
        if name in self.variables:
            return
        if kind == OBJ:
            self.variables[name] = self.current_builder.alloca(
                ir.PointerType(self.pyobj.pyobj_type), name=name
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
            pair = self.current_builder.call(self.sadd_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "add", l_val, r_val))
        if op == "-":
            pair = self.current_builder.call(self.ssub_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "sub", l_val, r_val))
        if op == "*":
            pair = self.current_builder.call(self.smul_overflow, [l_val, r_val])
            return (I64, self._overflow_checked(pair, "mul", l_val, r_val))
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

    def _overflow_checked(self, pair: Any, op: str, left: Any, right: Any) -> Any:
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

    # ================== declarations ==================

    def _annotation_kind(self, node: Any) -> Optional[str]:
        """('name', 'int') -> 'i64'; returns None for unknown annotations."""
        if (
            isinstance(node, list)
            and len(node) >= 2
            and node[0] == "name"
            and isinstance(node[1], str)
        ):
            return ANNOTATION_KINDS.get(node[1])
        return None

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
        """Create raw-ABI functions for annotated ones, PyObject otherwise."""
        for func_name, func_def in self.function_defs.items():
            param_kinds, ret_kind = self._static_signature(func_def)
            if param_kinds is not None:
                param_types = [LLVM_KIND_TYPES[k] for k in param_kinds]
                func_ty = ir.FunctionType(LLVM_KIND_TYPES[ret_kind], param_types)
                func = ir.Function(self.module, func_ty, name=func_name)
                self.static_funcs[func_name] = (param_kinds, ret_kind, func)
            else:
                param_count = len(func_def[2]) if len(func_def) > 2 else 0
                param_types = [ir.PointerType(self.pyobj.pyobj_type)] * param_count
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

        self.current_function = func
        self.current_builder = ir.IRBuilder(entry_block)
        self.current_ret_kind = ret_kind
        self.variables = {}
        self.var_kinds = {}

        for index, param_name in enumerate(func_def[2]):
            kind = param_kinds[index]
            self._declare_var(param_name, kind)
            self.current_builder.store(func.args[index], self.variables[param_name])

        for stmt in func_def[3]:
            self._convert_node(stmt)
            if self.current_builder.block.is_terminated:
                break

        if not self.current_builder.block.is_terminated:
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

    def _generate_dynamic_function_body(self, func: ir.Function, func_def: list):
        """PyObject-ABI function body (unannotated functions)."""
        entry_block = func.append_basic_block("entry")
        old_function = self.current_function
        old_builder = self.current_builder
        old_variables = self.variables.copy()
        old_kinds = dict(self.var_kinds)
        old_ret = self.current_ret_kind

        self.current_function = func
        self.current_builder = ir.IRBuilder(entry_block)
        self.current_ret_kind = None
        self.variables = {}
        self.var_kinds = {}

        for index, param_name in enumerate(func_def[2]):
            if index < len(func.args):
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

    # ================== statement / expression dispatch ==================

    def _convert_node(self, node: Any, skip_func_defs: bool = False) -> Tuple[str, Any]:
        """Convert an IR node, returning a TypedValue (kind, llvm value)."""
        if not isinstance(node, list) or len(node) == 0:
            return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        op = node[0]
        null_obj = ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None)

        if op == "module":
            for stmt in node[1] if len(node) > 1 else []:
                self._convert_node(stmt, skip_func_defs)
            return (OBJ, null_obj)

        if op == "const":
            value = node[1]
            kind = self._const_kind(value)
            if kind == I1:
                return (I1, ir.Constant(ir.IntType(1), value))
            if kind == I64:
                return (I64, ir.Constant(ir.IntType(64), value))
            if kind == F64:
                return (F64, ir.Constant(ir.DoubleType(), value))
            str_len = len(value)
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
                annotation_kind = OBJ
            value = self._convert_node(value_node)
            if isinstance(target, str) and value[1] is not None:
                coerced = self._coerce(value, annotation_kind)
                self._declare_var(target, annotation_kind)
                self.current_builder.store(coerced[1], self.variables[target])
                return coerced
            return (OBJ, null_obj)

        if op == "aug_assign":
            target_name = node[1][1]
            bin_op = node[2][:-1]  # "+=" -> "+"
            if target_name not in self.var_kinds and target_name not in self.variables:
                return (OBJ, null_obj)
            current = self._load_var(target_name)
            right = self._convert_node(node[3])
            result = self._typed_binop(bin_op, current, right)
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
            pair = self.current_builder.call(
                self.ssub_overflow,
                [
                    ir.Constant(ir.IntType(64), 0),
                    value,
                ],
            )
            return (
                I64,
                self._overflow_checked(
                    pair, "sub", ir.Constant(ir.IntType(64), 0), value
                ),
            )

        if op in ("+", "-", "*", "/", "//", "%") and len(node) >= 3:
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])
            return self._typed_binop(op, left, right)

        if op in ("==", "!=", "<", "<=", ">", ">="):
            left = self._convert_node(node[1])
            right = self._convert_node(node[2])
            return self._typed_compare(op, left, right)

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
                obj = self._box(obj_tv)
                key = self._box(key_tv)
                return (
                    OBJ,
                    self.current_builder.call(self.pyobj_subscript, [obj, key]),
                )
            return (OBJ, null_obj)

        if op == "subscript_assign":
            if len(node) >= 4:
                obj = self._box(self._convert_node(node[1]))
                key = self._box(self._convert_node(node[2]))
                value = self._box(self._convert_node(node[3]))
                self.current_builder.call(self.pyobj_subscript_set, [obj, key, value])
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

    def _convert_list_for_loop(
        self, target_node: Any, iter_node: Any, body_stmts: list
    ) -> Tuple[str, Any]:
        i64 = ir.IntType(64)
        list_obj = self._box(self._convert_node(iter_node))
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
            obj = self._box(self._convert_node(func_node[1]))
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
                    boxed = self._box(self._convert_node(args_node[0]))
                    if boxed is not None:
                        return (
                            OBJ,
                            self.current_builder.call(self.pyobj_len, [boxed]),
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
                boxed_args = []
                for arg_node in args_node:
                    boxed_args.append(self._box(self._convert_node(arg_node)))
                if len(boxed_args) == len(func.args):
                    result = self.current_builder.call(func, boxed_args)
                    return (OBJ, result)
                return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))

        return (OBJ, ir.Constant(ir.PointerType(self.pyobj.pyobj_type), None))
