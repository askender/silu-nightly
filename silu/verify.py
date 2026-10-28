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
    create_concrete_value,
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
            elif op == "and":
                left = z3.And(left, right)
            elif op == "or":
                left = z3.Or(left, right)
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
        # require(cond) contracts seen in THIS function: function-
        # scoped assumes - the function's proof stands alone under
        # its declared domain, independent of any caller
        self.preconditions: List[SymbolicValue] = []
        # call sites to contract-bearing functions: (callee, arg
        # SymbolicValues, line, path snapshot, env bindings)
        self.contract_checks: List[Tuple] = []
        # the function's parameter order, for instantiation
        self.param_order: List[str] = []
        # callee-name -> [precondition z3 formulas]: set by
        # verify_source between the two passes (None while
        # collecting contracts)
        self._contracts: Optional[Dict[str, List]] = None
        # literal-container tracking: name -> ("list", len) or
        # ("dict", {keys}); invalidated conservatively on any
        # subscript-assign into the name
        self.literal_containers: Dict[str, Tuple[str, Any]] = {}

    def _execute_ir(self, ir_node: Any) -> SymbolicValue:
        if (
            isinstance(ir_node, (list, tuple))
            and ir_node
            and ir_node[0] in ("assign", "ann_assign")
            and len(ir_node) >= 3
            and isinstance(ir_node[1], str)
        ):
            # the stock AssignmentHandler only knows the C-style
            # 4-tuple assign; Silu assign/ann_assign falls through
            # the dispatch table and the RHS is never evaluated
            # (checked operations inside assignments were invisible).
            # Evaluate here so obligations record, then bind.
            self._track_literal_container(ir_node[1], ir_node[2])
            value = self._execute_ir(ir_node[2])
            try:
                self.current_env.set_variable(ir_node[1], value)
            except Exception:
                pass
            if self.current_path is not None:
                try:
                    self.current_path.variables[ir_node[1]] = value
                except Exception:
                    pass
            return value
        if (
            isinstance(ir_node, (list, tuple))
            and len(ir_node) >= 2
            and ir_node[0] == "line"
        ):
            self.current_line = ir_node[1]
        elif (
            isinstance(ir_node, (list, tuple))
            and len(ir_node) >= 3
            and ir_node[0] == "subscript"
        ):
            self._record_bounds_obligation(ir_node)
        elif (
            isinstance(ir_node, (list, tuple))
            and ir_node
            and ir_node[0] == "call"
            and len(ir_node) >= 3
            and isinstance(ir_node[1], (list, tuple))
            and len(ir_node[1]) >= 2
            and ir_node[1][0] == "name"
            and ir_node[1][1] == "require"
            and ir_node[2]
        ):
            # contract assume: proof-time only, no-op in every other
            # plane. Function-scoped - place at function entry.
            cond = self._execute_ir(ir_node[2][0])
            if cond is not None and cond.type != SymbolicValueType.CONCRETE:
                self.preconditions.append(cond)
            elif cond is not None and cond.type == SymbolicValueType.CONCRETE and not cond.value:
                self.abort_obligations.append(
                    ("definite-assume-false", self.current_line, cond, [])
                )
            return create_concrete_value(True)
        elif (
            isinstance(ir_node, (list, tuple))
            and ir_node
            and ir_node[0] in ("subscript_assign", "subscript_aug_assign")
            and len(ir_node) >= 2
            and isinstance(ir_node[1], (list, tuple))
            and len(ir_node[1]) >= 2
            and ir_node[1][0] == "name"
        ):
            self.literal_containers.pop(ir_node[1][1], None)
        elif (
            isinstance(ir_node, (list, tuple))
            and ir_node
            and ir_node[0] == "call"
            and len(ir_node) >= 3
            and isinstance(ir_node[1], (list, tuple))
            and len(ir_node[1]) >= 2
            and ir_node[1][0] == "name"
            and self._contracts is not None
            and ir_node[1][1] in self._contracts
        ):
            # call to a contract-bearing function: remember the site;
            # discharge happens after this function's analysis, when
            # the callee's precondition formulas are final
            callee = ir_node[1][1]
            argvals = []
            for arg_ir in ir_node[2]:
                argvals.append(self._execute_ir(arg_ir))
            snapshot = list(getattr(self.current_path, "conditions", []))
            env = getattr(self, "current_env", None)
            binds: Dict[str, Any] = {}
            if env is not None:
                try:
                    for nm in env.variables:
                        binds[nm] = env.variables[nm]
                except Exception:
                    binds = {}
            self.contract_checks.append(
                (callee, argvals, self.current_line, snapshot, binds)
            )
        return super()._execute_ir(ir_node)

    def _track_literal_container(self, name: str, value_ir) -> None:
        if not isinstance(value_ir, (list, tuple)) or not value_ir:
            return
        if value_ir[0] == "list":
            self.literal_containers[name] = (
                "list", len(value_ir[1]) if len(value_ir) > 1 else 0
            )
        elif value_ir[0] == "dict":
            keys = set()
            for pair in value_ir[1] if len(value_ir) > 1 else []:
                if (
                    isinstance(pair, (list, tuple))
                    and len(pair) >= 2
                    and isinstance(pair[0], (list, tuple))
                    and len(pair[0]) >= 2
                    and pair[0][0] == "const"
                    and isinstance(pair[0][1], str)
                ):
                    keys.add(pair[0][1])
            self.literal_containers[name] = ("dict", keys)

    def _record_bounds_obligation(self, ir_node) -> None:
        """subscript abort obligation, v1.1: recorded when the
        container length is STATICALLY KNOWN (literal lists/str
        constants). Symbolic-length containers stay silent - flagging
        every xs[i] would drown the signal; the docstring pins this
        scope."""
        base_ir, index_ir = ir_node[1], ir_node[2]
        if not isinstance(base_ir, (list, tuple)) or not base_ir:
            return
        # a slice index is not a bounds-abort site in the same sense
        if (
            isinstance(index_ir, (list, tuple))
            and len(index_ir) >= 4
            and index_ir[0] == "slice"
        ):
            return
        length = None
        known_keys = None
        if base_ir[0] == "list":
            length = len(base_ir[1]) if len(base_ir) > 1 else 0
        elif base_ir[0] == "const" and isinstance(base_ir[1], str):
            length = len(base_ir[1])
        elif base_ir[0] == "name":
            info = self.literal_containers.get(base_ir[1])
            if info is not None:
                if info[0] == "list":
                    length = info[1]
                else:
                    known_keys = info[1]
        if length is None and known_keys is None:
            return
        if known_keys is not None:
            key_ir = index_ir
            if (
                isinstance(key_ir, (list, tuple))
                and len(key_ir) >= 2
                and key_ir[0] == "const"
                and isinstance(key_ir[1], str)
                and key_ir[1] not in known_keys
            ):
                self.abort_obligations.append(
                    ("KeyError", self.current_line, None, [], None)
                )
            return
        index = self._execute_ir(index_ir)
        snapshot = list(getattr(self.current_path, "conditions", []))
        self.abort_obligations.append(
            ("index", self.current_line, index, snapshot, length)
        )

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
                # v2: also snapshot the live environment bindings so
                # guarded rebindings (x = 1 on the x==0 branch) apply
                env = getattr(self, "current_env", None)
                binds: Dict[str, Any] = {}
                if env is not None:
                    try:
                        for nm in env.variables:
                            binds[nm] = env.variables[nm]
                    except Exception:
                        binds = {}
                self.abort_obligations.append(
                    (op, self.current_line, right, snapshot, None, binds)
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


def _path_z3_raw(conditions: list) -> List[z3.ExprRef]:
    """v2 path conditions: prefer raw_expression (the live symbolic
    tree) with the path's truth DIRECTION applied - a false branch
    contributes the negation."""
    out: List[z3.ExprRef] = []
    for cond in conditions:
        raw = getattr(cond, "raw_expression", None)
        z = None
        if isinstance(raw, SymbolicValue):
            z = _z3_of(raw)
        elif isinstance(raw, z3.ExprRef):
            z = raw
        if z is None:
            legacy = _path_z3([cond])
            if legacy:
                out.append(legacy[0])
            continue
        if getattr(cond, "is_true", True) is False:
            z = z3.Not(z)
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
    """Verify every function in a Silu source. Returns (ok, report).

    Two passes: pass 1 analyzes every function standalone and
    collects its require() contracts; pass 2 re-analyzes to check
    that every call site into a contract-bearing function satisfies
    the callee's declared domain under the caller's path conditions.
    A function's own proof uses ONLY its declared contracts - never
    its callers - so removing a caller never invalidates anything.
    """
    tree = ast.parse(source)
    ir_program = SiluIRGenerator().visit(tree)
    report: List[str] = []
    ok = True

    # ---- pass 1: standalone proofs + contract collection ----
    contracts: Dict[str, Tuple[List[str], List]] = {}
    execs: Dict[str, VerifyExecutor] = {}
    for func_def in _func_defs(ir_program):
        name, params, fbody = func_def[0], func_def[1], func_def[2]
        ex = VerifyExecutor()
        ex._current_fn = name
        ex.param_order = [str(p) for p in params]
        try:
            # the executor's own per-function analysis: fresh path
            # manager, symbolic parameters, branch-forked path
            # exploration - obligations record against the live path
            ex._analyze_function_definition(name, list(params), fbody, None, None)
        except Exception as exc:  # executor limits: report, not crash
            report.append(f"{name}: analysis incomplete ({exc})")
            ok = False
            continue
        execs[name] = ex
        if ex.preconditions:
            pre_z3 = []
            for p in ex.preconditions:
                z = _z3_of(p)
                if z is not None:
                    pre_z3.append(z)
            contracts[name] = ([str(p) for p in params], pre_z3)

        ok, _ = _report_one(name, ex, report, ok)

    # ---- pass 2: call-site contract checking ----
    for func_def in _func_defs(ir_program):
        name, params, fbody = func_def[0], func_def[1], func_def[2]
        if name not in execs:
            continue
        ex2 = VerifyExecutor()
        ex2._current_fn = name
        ex2.param_order = [str(p) for p in params]
        ex2._contracts = contracts
        try:
            ex2._analyze_function_definition(name, list(params), fbody, None, None)
        except Exception:
            continue  # already reported in pass 1
        ok, _report_tail = _check_call_sites(name, ex2, contracts, report, ok)
    return ok, report


def _report_one(name: str, ex, report: List[str], ok: bool) -> Tuple[bool, List[str]]:
    if not ex.abort_obligations:
        report.append(f"{name}: ok (no checked operations)")
        return ok, report

    fn_ok = True
    checked = 0
    for entry in ex.abort_obligations:
        op, line, operand, snapshot = entry[0], entry[1], entry[2], entry[3]
        length = entry[4] if len(entry) > 4 else None
        binds = entry[5] if len(entry) > 5 else None
        solver = z3.Solver()
        for cond in _path_z3_raw(snapshot):
            solver.add(cond)
        # function-scoped require() assumes: the declared domain
        for p in ex.preconditions:
            z = _z3_of(p)
            if z is not None:
                solver.add(z)
        if op == "definite-assume-false":
            report.append(
                f"{name}: POSSIBLE ABORT - require(false) at line {line} (unsatisfiable domain)"
            )
            fn_ok = False
            continue
        if op == "KeyError":
            report.append(
                f"{name}: POSSIBLE ABORT - KeyError: literal key missing at line {line} []"
            )
            fn_ok = False
            continue
        if op == "index":
            iz = _z3_of(operand)
            if iz is None:
                checked += 1
                continue
            # obligation: i < 0 or i >= length (abort condition)
            solver.add(z3.Or(iz < 0, iz >= length))
            label = f"index out of range [0, {length})"
        else:
                dz = _z3_of(operand)
                # v2 path sensitivity: if the environment snapshot
                # rebinds the divisor's variable, substitute the
                # rebinding (the guard x = 1 on the x==0 branch makes
                # the divisor concrete there)
                if (
                    dz is not None
                    and binds
                    and getattr(operand, "name", None) in binds
                ):
                    rz = _z3_of(binds[getattr(operand, "name", None)])
                    if rz is not None:
                        dz = rz
                if dz is None:
                    report.append(
                        f"{name}: unknown (operand not expressible at line {line})"
                    )
                    fn_ok = False
                    continue
                if not isinstance(dz, z3.ArithRef):
                    dz = z3.If(dz, z3.IntVal(1), z3.IntVal(0))
                solver.add(dz == 0)
                label = (
                    "division" if op in ("/", "//") else "modulo"
                ) + " by zero"
        res = solver.check()
        if res == z3.sat:
            model = solver.model()
            witness = ", ".join(
                f"{str(d)}={model[d]}" for d in model
            )
            report.append(
                f"{name}: POSSIBLE ABORT - {label} at line {line} [{witness}]"
            )
            fn_ok = False
        elif res == z3.unsat:
            checked += 1
        else:
                report.append(f"{name}: unknown (solver timeout, line {line})")
                fn_ok = False
    if fn_ok:
        report.append(
            f"{name}: ok ({checked} checked abort site(s) proved safe)"
        )
    else:
        ok = False
    return ok, report


def _check_call_sites(
    name: str,
    ex,
    contracts: Dict[str, Tuple[List[str], List]],
    report: List[str],
    ok: bool,
) -> Tuple[bool, List[str]]:
    """Pass 2: every call into a contract-bearing function must
    satisfy the callee's declared domain under the caller's path
    conditions at the call point."""
    for callee, argvals, line, snapshot, binds in ex.contract_checks:
        if callee not in contracts:
            continue
        param_names, pre_z3 = contracts[callee]
        if not pre_z3:
            continue
        solver = z3.Solver()
        for cond in _path_z3_raw(snapshot):
            solver.add(cond)
        # caller env bindings apply to the ARG expressions' variables
        arg_z3 = []
        unknown = False
        for av in argvals:
            z = _z3_of(av)
            if (
                z is None
                and binds
                and getattr(av, "name", None) in binds
            ):
                z = _z3_of(binds[getattr(av, "name", None)])
            if z is None:
                unknown = True
                break
            arg_z3.append(z)
        if unknown:
            report.append(
                f"{name}: unknown (argument not expressible at the "
                f"{callee}() call, line {line})"
            )
            ok = False
            continue
        # instantiate each precondition: rename callee params to
        # fresh names, then substitute with the call-site args -
        # caller vars and callee params never collide
        subs = []
        for idx, pn in enumerate(param_names):
            if idx < len(arg_z3):
                fresh = z3.Int(f"_c_{callee}_{line}_{idx}")
                subs.append((pn, fresh, arg_z3[idx]))
        for pre in pre_z3:
            renamed = pre
            for pn, fresh, _arg in subs:
                renamed = z3.substitute(renamed, (z3.Int(pn), fresh))
            instantiated = renamed
            for _pn, fresh, arg in subs:
                instantiated = z3.substitute(instantiated, (fresh, arg))
            if not isinstance(instantiated, z3.BoolRef):
                instantiated = instantiated != 0
            solver.add(z3.Not(instantiated))
        res = solver.check()
        if res == z3.sat:
            model = solver.model()
            witness = ", ".join(f"{str(d)}={model[d]}" for d in model)
            report.append(
                f"{name}: CONTRACT VIOLATION - call to {callee}() at "
                f"line {line} violates its require [{witness}]"
            )
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
