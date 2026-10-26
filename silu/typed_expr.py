"""The arithmetic/comparison emission methods of TypedCodegen.

Split out of silu/typed_codegen.py (module step B of the
modularization plan): the typed binary-operator and comparison
compilers, their overflow/floordiv/mod inline helpers, and the
fused rawstr subscript-comparison path. tools/flatten_codegen.py
splices these method blocks back into the flattened single class in
this file's definition order, so the flattened output stays
byte-identical - the acceptance gate is the fixed-point test.

Every method here reads only the converter state introduced by
TypedCodegen.__init__ and the shared constants from typed_helpers.
"""

from typing import Any, Tuple

from silu.ir_iface import ir
from silu.typed_helpers import (
    F64, I1, I64, OBJ, RAWSTR, RAWCHAR_VIEW,
    LLVM_KIND_TYPES, _extract_i64_const,
)


class TypedExprMixin:

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
                "|": self.pyobj_bitor,
                "&": self.pyobj_bitand,
                "^": self.pyobj_bitxor,
                "<<": self.pyobj_shl,
                ">>": self.pyobj_shr,
            }[op]
            result = self.current_builder.call(runtime, [l_obj, r_obj])
            return (OBJ, result)

        if left[0] == F64 or right[0] == F64:
            __ptup = self._promote_pair(left, right, F64)
            l_kind, l_val = __ptup[0]
            r_kind, r_val = __ptup[1]
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
        __ptup = self._promote_pair(left, right, I64)
        l_kind, l_val = __ptup[0]
        r_kind, r_val = __ptup[1]
        i64 = ir.IntType(64)
        if op == "|":
            return (I64, self.current_builder.or_(l_val, r_val, ""))
        if op == "&":
            return (I64, self.current_builder.and_(l_val, r_val, ""))
        if op == "^":
            return (I64, self.current_builder.xor(l_val, r_val, ""))
        if op == "<<":
            return (I64, self.current_builder.shl(l_val, r_val, ""))
        if op == ">>":
            return (I64, self.current_builder.ashr(l_val, r_val, ""))
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
                    if exp % 2 == 1:
                        pair = builder.call(self.smul_overflow, [result, base])
                        result = self._overflow_checked(pair, "mul")
                    exp = exp // 2
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
        def _is_str_const(n):
            return isinstance(n, (list, tuple)) and len(n) >= 2 and \
                n[0] == "const" and isinstance(n[1], str)

        if (
            (left[0] == RAWSTR or right[0] == RAWSTR)
            and (left[0] != OBJ or _is_str_const(left_node))
            and (right[0] != OBJ or _is_str_const(right_node))
        ):
            # raw string comparisons: memcmp semantics, which on UTF-8
            # bytes equals Python's code point ordering; coerced
            # temporaries are dropped after the call. A string constant
            # compares straight out of its global - no allocation.
            # s[i] <op> "<const>" never materializes the character.
            # Any other dynamic (OBJ) side - a variable, a None - goes
            # to pyobj_cmp instead: coercing a null or non-string box
            # into rawstr would crash, and pyobj_eq already answers
            # None == "x" as False.
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
            runtime = self.pyobj_cmp[op]
            return (OBJ, self.current_builder.call(runtime, [l_obj, r_obj]))

        target = F64 if left[0] == F64 or right[0] == F64 else I64
        __ptup = self._promote_pair(left, right, target)
        l_kind, l_val = __ptup[0]
        r_kind, r_val = __ptup[1]
        if target == F64:
            if op == "!=":
                return (I1, self.current_builder.fcmp_unordered("!=", l_val, r_val))
            return (I1, self.current_builder.fcmp_ordered(op, l_val, r_val))
        return (I1, self.current_builder.icmp_signed(op, l_val, r_val))
