import ast
from z3 import Solver, sat, And, Or
from z3 import IntVal, IntNumRef, simplify


def get_boolop_func(op):
    func = boolop_map.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unsupported BoolOp op: {op}")
    return func


def get_cmp_func(op):
    func = cmp_map.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unknown cmp op: {op}")
    return func


def get_binop_func(op):
    func = binop_map.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unknown bin op: {op}")
    return func


boolop_map = {ast.And: And, ast.Or: Or}
binop_map = {
    ast.Mod: lambda left, right: left % right,
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
}
cmp_map = {
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
}


def is_sat(cond):
    s = Solver()
    s.add(cond)
    return s.check() == sat


def simplify_range_cond_v1(k, start, stop, step=None):
    """
    构造第 k 次迭代的 range 条件: start + k*step < stop（正步长）
    对负步长则是 start + k*step > stop
    返回 None 表示条件恒假
    """
    if step is None:
        step = IntVal(1)

    # 统一成 Z3 表达式
    start_expr = IntVal(start) if isinstance(start, int) else start
    stop_expr = IntVal(stop) if isinstance(stop, int) else stop
    step_expr = IntVal(step) if isinstance(step, int) else step

    iter_val = start_expr + IntVal(k) * step_expr

    # 常量步长
    step_const = None
    if isinstance(step, IntNumRef):
        step_const = step.as_long()
    elif isinstance(step, int):
        step_const = step

    conds = []
    if step_const is None or step_const > 0:
        conds.append(iter_val < stop_expr)
        conds.append(iter_val >= start_expr)
    elif step_const < 0:
        conds.append(iter_val > stop_expr)
        conds.append(iter_val <= start_expr)
    else:
        # step == 0 不合法，直接恒假
        return None

    final_cond = simplify(And(*conds))

    # 可满足性判断
    if not is_sat(final_cond):
        return None
    return final_cond


def _to_z3_index_expr(expr, var_dict=None):
    """将 AST 节点或 int/Z3 表达式统一转成 Z3 表达式"""
    if isinstance(expr, int):
        return IntVal(expr)
    if isinstance(expr, IntNumRef):
        return expr
    if isinstance(expr, ast.Constant):
        return IntVal(expr.value)
    if isinstance(expr, ast.Name):
        if var_dict is None or expr.id not in var_dict:
            raise ValueError(f"Variable {expr.id} not found")
        return var_dict[expr.id]
    if isinstance(expr, ast.BinOp):
        left = _to_z3_index_expr(expr.left, var_dict)
        right = _to_z3_index_expr(expr.right, var_dict)
        if isinstance(expr.op, ast.Add):
            return left + right
        elif isinstance(expr.op, ast.Sub):
            return left - right
        elif isinstance(expr.op, ast.Mult):
            return left * right
        else:
            raise NotImplementedError(
                f"Unsupported BinOp in index: {ast.dump(expr.op)}"
            )
    # 直接传进来的 Z3 表达式
    return expr


def simplify_range_cond(k, start, stop, step=None, var_dict=None):
    """
    构造第 k 次迭代的 range 条件: start + k*step < stop（正步长）
    对负步长则是 start + k*step > stop
    返回 None 表示条件恒假
    支持 start/stop/step 为 AST BinOp / Name / Constant
    """
    # 先统一成 Z3 表达式
    start_expr = _to_z3_index_expr(start, var_dict)
    stop_expr = _to_z3_index_expr(stop, var_dict)
    step_expr = _to_z3_index_expr(step if step is not None else IntVal(1), var_dict)

    iter_val = start_expr + IntVal(k) * step_expr

    # 常量步长（用于判断方向）
    step_const = None
    if isinstance(step_expr, IntNumRef) and step_expr.is_int():
        try:
            step_const = step_expr.as_long()
        except Exception:
            pass
    elif isinstance(step, int):
        step_const = step

    conds = []
    if step_const is None or step_const > 0:
        conds.append(iter_val < stop_expr)
        conds.append(iter_val >= start_expr)
    elif step_const < 0:
        conds.append(iter_val > stop_expr)
        conds.append(iter_val <= start_expr)
    else:
        return None  # step == 0 不合法

    final_cond = simplify(And(*conds))

    if not is_sat(final_cond):
        return None
    return final_cond


def get_vars_from_cond(node):
    vars = set()

    class Visitor(ast.NodeVisitor):
        def visit_Name(self, n):
            vars.add(n.id)

    Visitor().visit(node)
    return vars
