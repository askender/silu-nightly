import sys
import ast
from z3 import Int, Solver, sat, And, Not, Or, BoolSort, IntVal, BoolVal, simplify, If
from z3 import ArrayRef, Store

from get_cond_tool import is_sat, simplify_range_cond
from get_cond_tool import get_boolop_func, get_cmp_func, get_binop_func


def handle_slice(value, lower, upper, step, var_dict):
    """
    处理列表切片。
    value: 原列表的 z3 表达式
    lower, upper, step: 切片参数（可能是 None）
    """
    # 在符号执行里，如果切片范围全 None，等价于原列表的浅拷贝
    if lower is None and upper is None and step is None:
        return value  # 或者 copy(value) 如果你要新的对象

    # 如果需要真正模拟切片，可以构造新的列表表达式
    # 注意：符号执行里要枚举范围才能精确建模
    raise NotImplementedError("Slice with bounds not yet implemented")


# -- 小工具：把 range(...) 的 start/stop/step 解析成 z3/int 表达 --
def parse_range_node(iter_node, var_dict):
    if (
        isinstance(iter_node, ast.Call)
        and getattr(iter_node.func, "id", None) == "range"
    ):
        args = iter_node.args
        if len(args) == 1:
            start = IntVal(0)
            stop = eval_ast_to_z3_or_int(args[0], var_dict)
            step = IntVal(1)
        elif len(args) == 2:
            start = eval_ast_to_z3_or_int(args[0], var_dict)
            stop = eval_ast_to_z3_or_int(args[1], var_dict)
            step = IntVal(1)
        elif len(args) == 3:
            start = eval_ast_to_z3_or_int(args[0], var_dict)
            stop = eval_ast_to_z3_or_int(args[1], var_dict)
            step = eval_ast_to_z3_or_int(args[2], var_dict)
        else:
            raise NotImplementedError("Unsupported number of arguments to range")
        return start, stop, step
    else:
        raise NotImplementedError("Unsupported iter node for for-loops (expect range)")


def eval_ast_to_z3_or_int(node, var_dict):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int):
            return IntVal(node.value)
        elif isinstance(node.value, bool):
            return BoolVal(node.value)
        else:
            raise NotImplementedError(f"Unsupported constant type: {type(node.value)}")
    elif isinstance(node, ast.Name):
        if node.id in var_dict:
            return var_dict[node.id]
        else:
            raise KeyError(f"Variable {node.id} not in var_dict")
    else:
        return ast_to_z3(node, var_dict)


def z3_min(a, b):
    return If(a <= b, a, b)


def z3_max(a, b):
    return If(a >= b, a, b)


def z3_min_list(lst):
    current_min = lst[0]
    for v in lst[1:]:
        current_min = z3_min(current_min, v)
    return current_min


def z3_max_list(lst):
    current_max = lst[0]
    for v in lst[1:]:
        current_max = z3_max(current_max, v)
    return current_max


def update_subscript(container_val, idx, new_val):
    if isinstance(container_val, list):
        container = list(container_val)
        if isinstance(idx, int):
            if idx >= len(container):
                container.extend([IntVal(0)] * (idx + 1 - len(container)))
            container[idx] = new_val
            return container
        else:
            return [
                If(idx == IntVal(i), new_val, elem)
                for i, elem in enumerate(container_val)
            ]
    elif isinstance(container_val, ArrayRef):
        return Store(
            container_val, idx if not isinstance(idx, int) else IntVal(idx), new_val
        )
    else:
        raise TypeError(
            f"Unsupported container type for subscript assignment: {type(container_val)}"
        )


def ast_to_z3_list(py_list, var_dict):
    result = []
    for elem in py_list:
        if isinstance(elem, int):
            result.append(IntVal(elem))
        else:
            result.append(ast_to_z3(elem, var_dict))
    return result


def to_z3_list(nodes, var_dict):
    return [ast_to_z3(n, var_dict) for n in nodes]


def handle_in_notin(left, op, right_node, var_dict):
    if not isinstance(right_node, (ast.Tuple, ast.List)):
        raise NotImplementedError(
            f"Unsupported In/NotIn comparator: {ast.dump(right_node)}"
        )
    elements = to_z3_list(right_node.elts, var_dict)
    conds = [left == e for e in elements]
    return Or(*conds) if isinstance(op, ast.In) else And(*[left != e for e in elements])


def handle_subscript(value, idx, var_dict):
    # 常量索引
    if isinstance(idx, int):
        if isinstance(value, list):
            return value[idx]
        elif isinstance(value, ArrayRef):
            return value[IntVal(idx)]
        else:
            raise TypeError(
                f"Unsupported value type for constant index: {type(value)} with value={value}"
            )

    # Z3 表达式索引
    else:
        if isinstance(value, list):
            # 构造 If 链
            expr = value[-1]
            for i in reversed(range(len(value) - 1)):
                expr = If(idx == IntVal(i), value[i], expr)
            return expr
        elif isinstance(value, ArrayRef):
            return value[idx]
        else:
            raise TypeError(
                f"Unsupported value type for variable index: {type(value)} with value={value}"
            )


def ast_to_z3(node, var_dict):
    if isinstance(node, ast.BoolOp):
        return simplify(
            get_boolop_func(node.op)(*[ast_to_z3(v, var_dict) for v in node.values])
        )

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            operand = ast_to_z3(node.operand, var_dict)
            if operand.sort() != BoolSort():
                operand = operand != 0
            return Not(operand)
        raise NotImplementedError(f"Unsupported UnaryOp op: {node.op}")

    if isinstance(node, ast.Compare):
        left = ast_to_z3(node.left, var_dict)
        op = node.ops[0]
        right_node = node.comparators[0]
        if isinstance(op, (ast.In, ast.NotIn)):
            return handle_in_notin(left, op, right_node, var_dict)
        right = ast_to_z3(right_node, var_dict)
        return get_cmp_func(op)(left, right)

    if isinstance(node, ast.BinOp):
        left = ast_to_z3(node.left, var_dict)
        right = ast_to_z3(node.right, var_dict)
        return get_binop_func(node.op)(left, right)

    if isinstance(node, ast.Subscript):
        value = ast_to_z3(node.value, var_dict)

        # Python 3.9+ 切片会直接是 ast.Slice
        if isinstance(node.slice, ast.Slice):
            lower = ast_to_z3(node.slice.lower, var_dict) if node.slice.lower else None
            upper = ast_to_z3(node.slice.upper, var_dict) if node.slice.upper else None
            step = ast_to_z3(node.slice.step, var_dict) if node.slice.step else None
            return handle_slice(value, lower, upper, step, var_dict)

        # Python <= 3.8 单元素访问
        elif isinstance(node.slice, ast.Index):  # py <=3.8
            idx = ast_to_z3(node.slice.value, var_dict)
            return handle_subscript(value, idx, var_dict)

        # Python 3.9+ 单元素常量访问
        elif isinstance(node.slice, ast.Constant):
            idx = node.slice.value
            return handle_subscript(value, idx, var_dict)

        # 变量下标访问
        elif isinstance(node.slice, ast.Name):
            idx = var_dict.get(node.slice.id)
            if idx is None:
                raise ValueError(f"Index variable {node.slice.id} not found")
            return handle_subscript(value, idx, var_dict)

        else:
            # 这里兜底支持 BinOp、Call 等表达式
            idx = ast_to_z3(node.slice, var_dict)
            return handle_subscript(value, idx, var_dict)
        # else:
        #     raise NotImplementedError(f"Unsupported subscript slice node: {ast.dump(node.slice)}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise NotImplementedError(f"Unsupported Call func: {ast.dump(node.func)}")
        func_name = node.func.id
        arg0 = node.args[0]
        # args_z3 = node.args

        if func_name == "int":
            return ast_to_z3(arg0, var_dict)
        if func_name == "len":
            if isinstance(arg0, ast.Name):
                known_len = 3  # 可改成参数或上下文提供
                return IntVal(known_len)
            raise NotImplementedError(f"Unsupported len() argument: {ast.dump(arg0)}")

        if func_name == "min":
            args_z3 = [ast_to_z3(arg, var_dict) for arg in node.args]
            if len(args_z3) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                # min([a,b,c]) 这种形式
                elts = node.args[0].elts
                elts_z3 = [ast_to_z3(e, var_dict) for e in elts]
                return z3_min_list(elts_z3)
            else:
                # min(a,b,c,...) 这种形式
                return z3_min_list(args_z3)

        if func_name == "max":
            args_z3 = [ast_to_z3(arg, var_dict) for arg in node.args]
            if len(args_z3) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                elts = node.args[0].elts
                elts_z3 = [ast_to_z3(e, var_dict) for e in elts]
                return z3_max_list(elts_z3)
            else:
                return z3_max_list(args_z3)

        raise NotImplementedError(f"Unsupported Call func: {func_name}")

    if isinstance(node, ast.Name):
        if node.id not in var_dict:
            var_dict[node.id] = Int(node.id)
        return var_dict[node.id]

    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return BoolVal(v)
        if isinstance(v, int):
            return IntVal(v)
        if v is None:
            return BoolVal(False)
        raise NotImplementedError(f"Unsupported constant: {v}")

    if isinstance(node, (ast.Tuple, ast.List)):
        return to_z3_list(node.elts, var_dict)

    raise NotImplementedError(f"Unsupported AST node: {ast.dump(node)}")


def append_exit_path(exited_paths, vars_, path_cond, extra=None):
    """统一添加退出路径，自动简化路径条件。"""
    p = {"vars": vars_, "path_cond": simplify(path_cond), "may_continue": False}
    if extra:
        p.update(extra)
    exited_paths.append(p)


def process_for_loop_iteration(
    active_paths,
    loop_level,
    iterable_kind,
    iterable_list,
    start,
    stop,
    step,
    stmt,
    max_unroll,
):
    """统一处理 for 循环内的迭代路径更新。"""
    exited_paths = []
    for k in range(max_unroll):
        next_active = []
        for p in active_paths:
            # break 处理
            if p.get("break_loop_level", -1) == loop_level:
                append_exit_path(
                    exited_paths,
                    p["vars"],
                    p["path_cond"],
                    {"break_loop_level": -1, "ret": p.get("ret")},
                )
                continue
            # continue 处理
            if p.get("continue_loop_level", -1) == loop_level:
                newp = p.copy()
                newp["continue_loop_level"] = -1
                newp["may_continue"] = True
                next_active.append(newp)
                continue

            vd, pc = p["vars"], p["path_cond"]

            # 计算迭代变量和条件
            if iterable_kind == "range":
                base_cond = simplify_range_cond(k, start, stop, step)
                if base_cond is None or not is_sat(And(pc, base_cond)):
                    continue
                actual_iter_val = simplify(start + IntVal(k) * step)
                iter_cond = base_cond

            elif iterable_kind == "list":
                if k >= len(iterable_list):
                    append_exit_path(exited_paths, vd.copy(), pc)
                    continue
                actual_iter_val = iterable_list[k]
                if not is_sat(pc):
                    continue
                iter_cond = BoolVal(True)

            elif iterable_kind == "enumerate":
                if k >= len(iterable_list):
                    append_exit_path(exited_paths, vd.copy(), pc)
                    continue
                if not isinstance(stmt.target, ast.Tuple) or len(stmt.target.elts) != 2:
                    raise NotImplementedError(
                        "For loop with enumerate target must be tuple of length 2"
                    )
                idx_var = stmt.target.elts[0].id
                val_var = stmt.target.elts[1].id
                actual_idx_val = IntVal(k)
                actual_val_val = iterable_list[k]
                vd_exec = vd.copy()
                vd_exec[idx_var] = actual_idx_val
                vd_exec[val_var] = actual_val_val
                iter_cond = BoolVal(True)
                exec_cond = simplify(And(pc, iter_cond))
                if not is_sat(exec_cond):
                    exit_cond = simplify(And(pc, Not(iter_cond)))
                    if is_sat(exit_cond):
                        append_exit_path(exited_paths, vd.copy(), exit_cond)
                    continue
                body_results = symbolic_execute(
                    stmt.body, exec_cond, vd_exec, max_unroll, loop_level
                )
                for br in body_results:
                    if (
                        br.get("ret") is not None
                        or br.get("break_loop_level", -1) == loop_level
                    ):
                        append_exit_path(
                            exited_paths,
                            br["vars"],
                            br["path_cond"],
                            {"ret": br.get("ret"), "break_loop_level": -1},
                        )
                    else:
                        merged_vars = vd_exec.copy()
                        merged_vars.update(br.get("vars", {}))
                        next_active.append(
                            {
                                "vars": merged_vars,
                                "path_cond": br["path_cond"],
                                "may_continue": True,
                            }
                        )
                exit_cond = simplify(And(pc, Not(iter_cond)))
                if is_sat(exit_cond):
                    append_exit_path(exited_paths, vd.copy(), exit_cond)
                active_paths = next_active
                continue  # 跳过后续统一逻辑

            else:
                raise NotImplementedError("Unsupported iterable_kind in for loop")

            exec_cond = simplify(And(pc, iter_cond))
            if not is_sat(exec_cond):
                exit_cond = simplify(And(pc, Not(iter_cond)))
                if is_sat(exit_cond):
                    append_exit_path(exited_paths, vd.copy(), exit_cond)
                continue

            vd_exec = vd.copy()
            # vd_exec[stmt.target.id] = actual_iter_val
            assign_target_value(stmt.target, actual_iter_val, vd_exec)

            body_results = symbolic_execute(
                stmt.body, exec_cond, vd_exec, max_unroll, loop_level
            )

            for br in body_results:
                if (
                    br.get("ret") is not None
                    or br.get("break_loop_level", -1) == loop_level
                ):
                    append_exit_path(
                        exited_paths,
                        br["vars"],
                        br["path_cond"],
                        {"ret": br.get("ret"), "break_loop_level": -1},
                    )
                else:
                    merged_vars = vd_exec.copy()
                    merged_vars.update(br.get("vars", {}))
                    next_active.append(
                        {
                            "vars": merged_vars,
                            "path_cond": br["path_cond"],
                            "may_continue": True,
                        }
                    )

            exit_cond = simplify(And(pc, Not(iter_cond)))
            if is_sat(exit_cond):
                append_exit_path(exited_paths, vd.copy(), exit_cond)

        active_paths = next_active

    return active_paths, exited_paths


def process_if_stmt(stmt, statements_rest, path_cond, var_dict, max_unroll):
    cond_z3 = ast_to_z3(stmt.test, var_dict)
    true_cond = simplify(And(path_cond, cond_z3))
    false_cond = simplify(And(path_cond, Not(cond_z3)))

    results = []
    if is_sat(true_cond):
        results.extend(
            symbolic_execute(
                stmt.body + statements_rest, true_cond, var_dict.copy(), max_unroll
            )
        )
    if is_sat(false_cond):
        results.extend(
            symbolic_execute(
                stmt.orelse + statements_rest, false_cond, var_dict.copy(), max_unroll
            )
        )

    return results


def assign_target_value(target_node, iter_val, vd_exec):
    """支持 ast.Name 或 ast.Tuple 形式的循环变量赋值"""
    if isinstance(target_node, ast.Name):
        vd_exec[target_node.id] = iter_val
    elif isinstance(target_node, ast.Tuple):
        if not isinstance(iter_val, (tuple, list)) or len(iter_val) != len(
            target_node.elts
        ):
            raise ValueError("Tuple unpacking mismatch in for loop target")
        for sub_target, sub_val in zip(target_node.elts, iter_val):
            assign_target_value(sub_target, sub_val, vd_exec)
    else:
        raise NotImplementedError(
            f"Unsupported for loop target: {ast.dump(target_node)}"
        )


def symbolic_execute(statements, path_cond, var_dict, max_unroll=6, loop_level=0):
    if not statements:
        return [{"ret": None, "vars": var_dict, "path_cond": simplify(path_cond)}]

    stmt = statements[0]
    print("Current var_dict keys:", list(var_dict.keys()))
    print(f"stmt: {str(stmt)}   {sys.argv[1]}:{stmt.lineno}")

    if isinstance(stmt, ast.For):
        # 解析迭代器（省略部分原有逻辑，保持一致）
        if (
            isinstance(stmt.iter, ast.Call)
            and getattr(stmt.iter.func, "id", None) == "range"
        ):
            start, stop, step = parse_range_node(stmt.iter, var_dict)
            iterable_kind = "range"
            iterable_list = None
        elif isinstance(stmt.iter, ast.Name):
            iterable_name = stmt.iter.id
            iterable_val = var_dict.get(iterable_name)
            if iterable_val is None:
                raise ValueError(f"Iterable variable '{iterable_name}' not found")
            if isinstance(iterable_val, list):
                iterable_kind = "list"
                iterable_list = iterable_val
            else:
                raise NotImplementedError(
                    "Only list type iterables supported for ast.Name"
                )
        elif (
            isinstance(stmt.iter, ast.Call)
            and getattr(stmt.iter.func, "id", None) == "enumerate"
        ):
            enum_arg_node = stmt.iter.args[0]
            if isinstance(enum_arg_node, ast.Name):
                enum_list_name = enum_arg_node.id
                enum_list_val = var_dict.get(enum_list_name)
                if enum_list_val is None:
                    raise ValueError(f"Iterable variable '{enum_list_name}' not found")
                if not isinstance(enum_list_val, list):
                    raise ValueError(
                        f"Variable '{enum_list_name}' for enumerate must be list"
                    )
                iterable_kind = "enumerate"
                iterable_list = enum_list_val
            else:
                raise NotImplementedError(
                    "Only simple variable enumerate argument supported"
                )
        else:
            raise NotImplementedError("Unsupported iter node for for-loops")

        active_paths = [
            {"vars": var_dict.copy(), "path_cond": path_cond, "may_continue": False}
        ]

        active_paths, exited_paths = process_for_loop_iteration(
            active_paths,
            loop_level,
            iterable_kind,
            iterable_list,
            start if iterable_kind == "range" else None,
            stop if iterable_kind == "range" else None,
            step if iterable_kind == "range" else None,
            stmt,
            max_unroll,
        )

        # 截断后过滤仍可能继续的路径，转为退出路径
        for p in active_paths:
            if not is_sat(p["path_cond"]):
                continue
            still_can_continue = False
            if iterable_kind == "range":
                cond_after_max = simplify_range_cond(
                    max_unroll, start, stop, step, var_dict
                )
                if cond_after_max is not None and is_sat(
                    simplify(And(p["path_cond"], cond_after_max))
                ):
                    still_can_continue = True
            elif iterable_kind in ("list", "enumerate"):
                if max_unroll < len(iterable_list):
                    still_can_continue = True
            if p.get("may_continue", False) and still_can_continue:
                continue
            append_exit_path(exited_paths, p["vars"], p["path_cond"])

        final_results = []
        for p in exited_paths:
            if not is_sat(p["path_cond"]):
                continue
            if p.get("ret") is not None:
                final_results.append(p)
            else:
                final_results.extend(
                    symbolic_execute(
                        statements[1:],
                        p["path_cond"],
                        p["vars"],
                        max_unroll,
                        loop_level,
                    )
                )
        return final_results

    if isinstance(stmt, ast.While):
        active_paths = [
            {"vars": var_dict.copy(), "path_cond": path_cond, "may_continue": False}
        ]
        exited_paths = []

        for _ in range(max_unroll):
            next_active = []
            for p in active_paths:
                if p.get("break_loop_level", -1) == loop_level:
                    cond_expr = ast_to_z3(stmt.test, p["vars"])
                    false_cond = simplify(And(p["path_cond"], Not(cond_expr)))
                    if is_sat(false_cond):
                        append_exit_path(
                            exited_paths,
                            p["vars"],
                            false_cond,
                            {"break_loop_level": -1, "ret": p.get("ret")},
                        )
                    continue
                if p.get("continue_loop_level", -1) == loop_level:
                    newp = p.copy()
                    newp["continue_loop_level"] = -1
                    newp["may_continue"] = True
                    next_active.append(newp)
                    continue

                vd, pc = p["vars"], p["path_cond"]
                cond_expr = ast_to_z3(stmt.test, vd)
                true_cond = simplify(And(pc, cond_expr))
                false_cond = simplify(And(pc, Not(cond_expr)))

                if is_sat(false_cond):
                    append_exit_path(
                        exited_paths,
                        vd.copy(),
                        false_cond,
                        {"break_loop_level": -1, "may_continue": False},
                    )

                if is_sat(true_cond):
                    body_results = symbolic_execute(
                        stmt.body, true_cond, vd.copy(), max_unroll, loop_level + 1
                    )
                    for br in body_results:
                        if br.get("break_loop_level", -1) == loop_level:
                            if is_sat(false_cond):
                                append_exit_path(
                                    exited_paths,
                                    br["vars"],
                                    false_cond,
                                    {
                                        "break_loop_level": -1,
                                        "ret": br.get("ret"),
                                        "may_continue": False,
                                    },
                                )
                        else:
                            merged_vars = vd.copy()
                            merged_vars.update(br.get("vars", {}))
                            if br.get("ret") is not None:
                                append_exit_path(
                                    exited_paths,
                                    merged_vars,
                                    br["path_cond"],
                                    {"ret": br.get("ret"), "may_continue": False},
                                )
                            else:
                                next_active.append(
                                    {
                                        "vars": merged_vars,
                                        "path_cond": br["path_cond"],
                                        "may_continue": True,
                                    }
                                )

            active_paths = next_active

        for p in active_paths:
            if not is_sat(p["path_cond"]):
                continue
            cond_expr_after = ast_to_z3(stmt.test, p["vars"])
            if p.get("may_continue", False) and is_sat(
                simplify(And(p["path_cond"], cond_expr_after))
            ):
                continue
            append_exit_path(
                exited_paths, p["vars"], p["path_cond"], {"may_continue": False}
            )

        final_results = []
        for p in exited_paths:
            if p.get("ret") is not None:
                final_results.append(p)
            else:
                final_results.extend(
                    symbolic_execute(
                        statements[1:],
                        p["path_cond"],
                        p["vars"],
                        max_unroll,
                        loop_level,
                    )
                )
        return final_results

    if isinstance(stmt, ast.If):
        return process_if_stmt(stmt, statements[1:], path_cond, var_dict, max_unroll)

    if isinstance(stmt, ast.Break):
        return [
            {
                "ret": None,
                "vars": var_dict,
                "path_cond": simplify(path_cond),
                "break_loop_level": loop_level,
            }
        ]
    if isinstance(stmt, ast.Continue):
        return [
            {
                "ret": None,
                "vars": var_dict,
                "path_cond": simplify(path_cond),
                "continue_loop_level": loop_level,
            }
        ]

    if isinstance(stmt, ast.Return):
        ret_val = None if stmt.value is None else ast_to_z3(stmt.value, var_dict)
        return [{"ret": ret_val, "vars": var_dict, "path_cond": simplify(path_cond)}]

    if isinstance(stmt, ast.Assign):
        target = stmt.targets[0]

        # 普通变量赋值
        if isinstance(target, ast.Name):
            if isinstance(stmt.value, ast.List):
                z3_list = ast_to_z3_list(
                    [elt.value for elt in stmt.value.elts], var_dict
                )
                new_var_dict = var_dict.copy()
                new_var_dict[target.id] = z3_list
            else:
                z3_val = ast_to_z3(stmt.value, var_dict)
                new_var_dict = var_dict.copy()
                new_var_dict[target.id] = z3_val
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        # 多变量赋值: a, b = ...
        if isinstance(target, ast.Tuple):
            values = ast_to_z3(stmt.value, var_dict)
            if not isinstance(values, (list, tuple)):
                raise ValueError("Tuple assignment value must be iterable")
            new_var_dict = var_dict.copy()
            for elt, val in zip(target.elts, values):
                if isinstance(elt, ast.Name):
                    new_var_dict[elt.id] = val
                else:
                    raise NotImplementedError(
                        f"Unsupported tuple element type: {type(elt)}"
                    )
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        # 下标赋值: arr[i] = ...
        if isinstance(target, ast.Subscript):
            if isinstance(target.value, ast.Name):
                container_name = target.value.id
            else:
                raise NotImplementedError("Subscript target must be a variable name")

            container_val = var_dict.get(container_name)
            if container_val is None:
                raise ValueError(
                    f"Variable '{container_name}' not found for subscript assignment"
                )

            # 处理索引
            if isinstance(target.slice, ast.Constant):
                idx = target.slice.value
            else:
                idx = ast_to_z3(target.slice, var_dict)

            right_val = ast_to_z3(stmt.value, var_dict)

            # 调用统一更新函数
            new_container = update_subscript(container_val, idx, right_val)

            new_var_dict = var_dict.copy()
            new_var_dict[container_name] = new_container
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        raise NotImplementedError(f"Unsupported assignment target: {type(target)}")

    if isinstance(stmt, ast.AugAssign):
        target = stmt.target
        right_val = ast_to_z3(stmt.value, var_dict)

        # 普通变量自增/自减
        if isinstance(target, ast.Name):
            old_val = var_dict.get(target.id, IntVal(0))
            if isinstance(stmt.op, ast.Add):
                new_val = old_val + right_val
            elif isinstance(stmt.op, ast.Sub):
                new_val = old_val - right_val
            elif isinstance(stmt.op, ast.Mult):
                new_val = old_val * right_val
            else:
                raise NotImplementedError(f"Unsupported AugAssign op: {stmt.op}")
            new_var_dict = var_dict.copy()
            new_var_dict[target.id] = new_val
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        # 下标自增: arr[i] += ...
        if isinstance(target, ast.Subscript):
            if isinstance(target.value, ast.Name):
                container_name = target.value.id
            else:
                raise NotImplementedError(
                    "Subscript AugAssign target must be a variable name"
                )

            container_val = var_dict.get(container_name)
            if container_val is None:
                raise ValueError(
                    f"Variable '{container_name}' not found for subscript AugAssign"
                )

            if isinstance(target.slice, ast.Constant):
                idx = target.slice.value
            else:
                idx = ast_to_z3(target.slice, var_dict)

            # 先取旧值
            if isinstance(container_val, list):
                if isinstance(idx, int):
                    old_val = container_val[idx]
                else:
                    # 符号索引，构造 If 链取旧值
                    old_val = container_val[-1]
                    for i in reversed(range(len(container_val) - 1)):
                        old_val = If(idx == IntVal(i), container_val[i], old_val)
            elif isinstance(container_val, ArrayRef):
                old_val = (
                    container_val
                    if idx is None
                    else container_val[idx if not isinstance(idx, int) else IntVal(idx)]
                )
            else:
                raise TypeError(
                    f"Unsupported container type for AugAssign: {type(container_val)}"
                )

            # 计算新值
            if isinstance(stmt.op, ast.Add):
                new_val = old_val + right_val
            elif isinstance(stmt.op, ast.Sub):
                new_val = old_val - right_val
            elif isinstance(stmt.op, ast.Mult):
                new_val = old_val * right_val
            else:
                raise NotImplementedError(f"Unsupported AugAssign op: {stmt.op}")

            # 调用统一更新函数
            new_container = update_subscript(container_val, idx, new_val)

            new_var_dict = var_dict.copy()
            new_var_dict[container_name] = new_container
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        raise NotImplementedError(f"Unsupported AugAssign target: {type(target)}")

    if isinstance(stmt, ast.AnnAssign):
        if isinstance(stmt.target, ast.Name):
            target_name = stmt.target.id
            annotation_str = ast.unparse(stmt.annotation) if stmt.annotation else None

            if annotation_str == "int":
                init_val = ast_to_z3(stmt.value, var_dict) if stmt.value else IntVal(0)
            elif annotation_str.startswith("list[") and isinstance(
                stmt.value, ast.List
            ):
                # 对 list[int] 初始化，调用 ast_to_z3_list
                py_list = [elt.value for elt in stmt.value.elts]  # 只支持常数元素
                init_val = ast_to_z3_list(py_list, var_dict)
            else:
                # 其他情况，你可以选择直接调用 ast_to_z3
                init_val = ast_to_z3(stmt.value, var_dict) if stmt.value else None

            new_var_dict = var_dict.copy()
            new_var_dict[target_name] = init_val
            return symbolic_execute(statements[1:], path_cond, new_var_dict, max_unroll)

        return symbolic_execute(statements[1:], path_cond, var_dict, max_unroll)

    if isinstance(stmt, ast.Assert):
        assert_cond = ast_to_z3(stmt.test, var_dict)
        new_path_cond = simplify(And(path_cond, assert_cond))
        if is_sat(new_path_cond):
            return symbolic_execute(statements[1:], new_path_cond, var_dict, max_unroll)
        else:
            return []

    # 其他未知语句，跳过执行剩余
    return symbolic_execute(statements[1:], path_cond, var_dict, max_unroll)


def parse_annotation(node):
    return ast.unparse(node) if node else None


def parse_default(node):
    return ast.unparse(node) if node else None


def get_sig(node):
    func_name = node.name

    # 补齐默认值长度
    defaults = [None] * (len(node.args.args) - len(node.args.defaults)) + list(
        node.args.defaults
    )

    args = []
    for arg, default in zip(node.args.args, defaults):
        args.append((arg.arg, parse_annotation(arg.annotation), parse_default(default)))

    if node.args.vararg:
        args.append(
            (
                "*" + node.args.vararg.arg,
                parse_annotation(node.args.vararg.annotation),
                None,
            )
        )

    if node.args.kwarg:
        args.append(
            (
                "**" + node.args.kwarg.arg,
                parse_annotation(node.args.kwarg.annotation),
                None,
            )
        )

    return {"name": func_name, "args": args, "returns": parse_annotation(node.returns)}


def eval_z3_val(model, val):
    """从 model 中获取 val 的具体整数值，支持列表和单值"""
    if isinstance(val, list):
        return [model.eval(v, model_completion=True).as_long() for v in val]
    else:
        concrete = model.eval(val, model_completion=True)
        if hasattr(concrete, "as_long"):
            return concrete.as_long()
        return concrete


def demo2():
    f = sys.argv[1]
    code = open(f).read()
    tree = ast.parse(code)

    # 找函数定义
    func_defs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert len(func_defs) == 1, "Expect exactly one function definition"
    func_def = func_defs[0]

    print(f"func_def: {func_def.name}")
    func_sig = get_sig(func_def)
    print(f"func_sig: {func_sig}")
    print(f"func_def.body: {func_def.body}")

    vars = {}
    for arg_name, annotation, _default in func_sig["args"]:
        if annotation == "int":
            vars[arg_name] = Int(arg_name)
        elif annotation and annotation.startswith("list[int]"):
            length = 3  # 这里假定长度，实际可外部传入
            vars[arg_name] = [Int(f"{arg_name}_{i}") for i in range(length)]
        else:
            vars[arg_name] = Int(arg_name)

    print(f"vars: {vars}")
    paths = symbolic_execute(func_def.body, BoolVal(True), vars, max_unroll=9)
    print("paths:\n" + "\n".join(map(str, paths)))
    print(f"len of paths: {len(paths)}")

    solver = Solver()
    for res in paths:
        solver.push()
        solver.add(res["path_cond"])
        if solver.check() == sat:
            model = solver.model()
            inputs = {name: eval_z3_val(model, val) for name, val in vars.items()}

            ret_val_z3 = res["ret"]
            if isinstance(ret_val_z3, list):
                # 对返回列表的每个元素求具体值
                concrete_ret = [eval_z3_val(model, elem) for elem in ret_val_z3]
            else:
                concrete_ret = eval_z3_val(model, ret_val_z3)

            if len(inputs) == 1:
                inputs = list(inputs.values())[0]
            print(f"{{'input': {inputs}, 'answer': {concrete_ret}}},")
        solver.pop()


if __name__ == "__main__":
    demo2()
