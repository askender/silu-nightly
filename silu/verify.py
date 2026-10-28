"""silu verify: panic-free proofs for user programs (roadmap Phase 2).

The language's failure policy is abort-with-message on checked
operations - division/modulo by zero and (later) subscript bounds.
That makes "can this function ever abort?" a precise, decidable
property. This module drives the SymbolicExecutor over each function
with symbolic parameters, records a divide-by-zero obligation at
every '/'/'//'/'%' site together with the path condition reaching
it, and discharges each obligation with Z3. A reachable abort comes
back with a counterexample path (witness parameter values) - what
sampling fuzzers cannot give.

Scope of v1: division/modulo by zero, intra-procedural, integer
parameters. SOUND IN THE SAFETY DIRECTION ONLY: verify never says
"ok" when an abort is reachable, but it MAY warn about a divide
that a guard protects (the executor evaluates expressions on the
linear path; branch-forked rebindings are v2) - a "POSSIBLE ABORT"
is a review prompt with a witness, not a verdict. Loops are bounded
by the executor's unrolling config.
"""

import ast
from typing import Any, Dict, List, Optional, Tuple

import z3

from silu.ir_generator import SiluIRGenerator
from silu.symbolic_executor import SymbolicExecutor
from silu.symbolic.builtin_utils import (
    SymbolicValue,
    SymbolicValueType,
    create_symbolic_value,
)

_ABORT_OPS = ("/", "//", "%")


def _z3_of(value: SymbolicValue) -> Optional[z3.ExprRef]:
    """Best-effort Z3 form of a SymbolicValue."""
    if value is None:
        return None
    if value.type == SymbolicValueType.SYMBOLIC:
        nm = getattr(value, "name", None) or value.value
        return z3.Int(str(nm)) if nm is not None else None
    if value.type == SymbolicValueType.EXPRESSION:
        return _z3_of_expr(value.value, 0)
    if value.type == SymbolicValueType.CONCRETE:
        v = value.value
        if isinstance(v, bool):
            return z3.BoolVal(v)
        if isinstance(v, int):
            return z3.IntVal(v)
    return None



def _z3_of_expr(expr, depth: int):
    """Convert the executor's (op, left, right) expression tree of
    SymbolicValues into a Z3 integer expression."""
    if depth > 32:
        return None
    if isinstance(expr, SymbolicValue):
        return _z3_of(expr)
    if not isinstance(expr, (list, tuple)) or not expr:
        return None
    if len(expr) == 2:
        op, operand = expr
        sub = _z3_of_expr(operand, depth + 1)
        if sub is None:
            return None
        if op == "-":
            return -sub
        return None
    if len(expr) >= 3:
        op = expr[0]
        left = _z3_of_expr(expr[1], depth + 1)
        if left is None:
            return None
        for rhs_node in expr[2:]:
            right = _z3_of_expr(rhs_node, depth + 1)
            if right is None:
                return None
            if op == "+":
                left = left + right
            elif op == "-":
                left = left - right
            elif op == "*":
                left = left * right
            elif op in ("/", "//"):
                left = left / right
            elif op == "%":
                left = left % right
            elif op == "==":
                left = left == right
            elif op == "!=":
                left = left != right
            elif op == "<":
                left = left < right
            elif op == "<=":
                left = left <= right
            elif op == ">":
                left = left > right
            elif op == ">=":
                left = left >= right
            else:
                return None
        return left
    return None

class VerifyExecutor(SymbolicExecutor):
    """SymbolicExecutor that records abort obligations."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # (op, line, divisor SymbolicValue, path-condition snapshot)
        self.abort_obligations: List[Tuple[str, Optional[int], SymbolicValue, list]] = []
        self.current_line: Optional[int] = None

    def _execute_ir(self, ir_node: Any) -> SymbolicValue:
        if (
            isinstance(ir_node, (list, tuple))
            and len(ir_node) >= 2
            and ir_node[0] == "line"
        ):
            self.current_line = ir_node[1]
        return super()._execute_ir(ir_node)

    def _execute_binary_op(self, ir_node: Tuple) -> SymbolicValue:  # type: ignore[override]
        op = ir_node[0]
        if op in _ABORT_OPS and len(ir_node) >= 3:
            # the divisor: last operand (n-ary chains end with it)
            right_ir = ir_node[-1]
            right = self._execute_ir(right_ir)
            if right.type == SymbolicValueType.CONCRETE:
                if right.value == 0:
                    self.abort_obligations.append(
                        ("definite", self.current_line, right, [])
                    )
                # a concrete NON-zero divisor can never abort: no
                # obligation at all
            else:
                snapshot = list(getattr(self.current_path, "conditions", []))
                self.abort_obligations.append(
                    (op, self.current_line, right, snapshot)
                )
        return super()._execute_binary_op(ir_node)


def _path_z3(conditions: list) -> List[z3.ExprRef]:
    out = []
    for cond in conditions:
        expr = getattr(cond, "z3_condition", None) or getattr(cond, "condition", None)
        if isinstance(expr, z3.ExprRef):
            out.append(expr)
        elif isinstance(expr, SymbolicValue):
            z = _z3_of(expr)
            if z is not None:
                out.append(z)
    return out


def _func_defs(ir_program) -> List[Tuple[str, list, list, dict]]:
    body = ir_program[1] if isinstance(ir_program, (list, tuple)) and len(ir_program) > 1 else []
    annos_of = {}
    out = []
    for stmt in body:
        if isinstance(stmt, (list, tuple)) and stmt and stmt[0] == "func_def":
            name, params, fbody = stmt[1], stmt[2], stmt[3]
            annos = stmt[4] if len(stmt) > 4 else []
            annos_of[name] = annos
            out.append((name, params, fbody, annos))
    return out


def _param_kinds(func_def: Tuple) -> Dict[str, str]:
    """func_def slot 5 (annos) is the parameter annotation map when
    present; fall back to scanning the AST is overkill - use it if
    shaped like [[name, kind], ...]."""
    annos = func_def[3] if len(func_def) > 3 else []
    kinds: Dict[str, str] = {}
    if isinstance(annos, (list, tuple)):
        for pair in annos:
            if (
                isinstance(pair, (list, tuple))
                and len(pair) == 2
                and isinstance(pair[0], str)
                and isinstance(pair[1], str)
            ):
                kinds[pair[0]] = pair[1]
    return kinds


def verify_source(source: str) -> Tuple[bool, List[str]]:
    """Verify every function in a Silu source. Returns (ok, report)."""
    tree = ast.parse(source)
    ir_program = SiluIRGenerator().visit(tree)
    report: List[str] = []
    ok = True

    for func_def in _func_defs(ir_program):
        name, params, fbody = func_def[0], func_def[1], func_def[2]
        kinds = _param_kinds(func_def)
        ex = VerifyExecutor()
        ex._current_fn = name
        try:
            # the executor's own per-function analysis: fresh path
            # manager, symbolic parameters, branch-forked path
            # exploration - obligations record against the live path
            ex._analyze_function_definition(name, list(params), fbody, None, None)
        except Exception as exc:  # executor limits: report, not crash
            report.append(f"{name}: analysis incomplete ({exc})")
            ok = False
            continue

        if not ex.abort_obligations:
            report.append(f"{name}: ok (no checked operations)")
            continue

        fn_ok = True
        for op, line, divisor, snapshot in ex.abort_obligations:
            solver = z3.Solver()
            for cond in _path_z3(snapshot):
                solver.add(cond)
            dz = _z3_of(divisor)
            if dz is None:
                report.append(
                    f"{name}: unknown (divisor not expressible at line {line})"
                )
                fn_ok = False
                continue
            solver.add(dz == 0)
            res = solver.check()
            if res == z3.sat:
                model = solver.model()
                witness = ", ".join(
                    f"{str(d)}={model[d]}" for d in model
                )
                report.append(
                    f"{name}: POSSIBLE ABORT - {'division' if op in ('/', '//') else 'modulo'} by zero at line {line} [{witness}]"
                )
                fn_ok = False
            elif res == z3.unsat:
                continue
            else:
                report.append(f"{name}: unknown (solver timeout, line {line})")
                fn_ok = False
        if fn_ok:
            report.append(
                f"{name}: ok ({len(ex.abort_obligations)} checked divide(s) proved safe)"
            )
        else:
            ok = False
    return ok, report


def verify_file(path: str) -> int:
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    ok, report = verify_source(source)
    for line in report:
        print(line)
    print("verify:", "ok - no abort reachable" if ok else "ABORT REACHABLE")
    return 0 if ok else 1
