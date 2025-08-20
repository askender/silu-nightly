#!/usr/bin/env python3
"""
Z3 Utilities for Symbolic Execution

This module provides utilities for converting AST nodes to Z3 expressions,
handling constraints, and performing satisfiability checking.
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Union

# Z3 availability check
try:
    import z3
    from z3 import (
        Solver,
        sat,
        And,
        Or,
        Not,
        If,
        IntVal,
        BoolVal,
        RealVal,
        BoolSort,
        Int,
        Real,
        Bool,
        ToReal,
        simplify,
    )

    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False
    z3 = None


# Operator mappings from AST to Z3
BOOLOP_MAP = {ast.And: And, ast.Or: Or}

BINOP_MAP = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.FloorDiv: lambda left, right: left // right,
    ast.Mod: lambda left, right: left % right,
    ast.Pow: lambda left, right: left**right,
}

CMP_MAP = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
}

UNARYOP_MAP = {
    ast.UAdd: lambda x: x,
    ast.USub: lambda x: -x,
    ast.Not: lambda x: Not(x),
}


def get_boolop_func(op: ast.boolop) -> callable:
    """Get Z3 function for boolean operation"""
    func = BOOLOP_MAP.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unsupported BoolOp: {type(op).__name__}")
    return func


def get_binop_func(op: ast.operator) -> callable:
    """Get Z3 function for binary operation"""
    func = BINOP_MAP.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unsupported BinOp: {type(op).__name__}")
    return func


def get_cmp_func(op: ast.cmpop) -> callable:
    """Get Z3 function for comparison operation"""
    func = CMP_MAP.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unsupported Compare: {type(op).__name__}")
    return func


def get_unaryop_func(op: ast.unaryop) -> callable:
    """Get Z3 function for unary operation"""
    func = UNARYOP_MAP.get(type(op))
    if func is None:
        raise NotImplementedError(f"Unsupported UnaryOp: {type(op).__name__}")
    return func


def is_sat(constraint) -> bool:
    """Check if a Z3 constraint is satisfiable"""
    if not Z3_AVAILABLE:
        return True  # Default to satisfiable if Z3 not available

    solver = Solver()
    solver.add(constraint)
    return solver.check() == sat


def create_z3_variable(name: str, var_type: str = "int"):
    """Create a Z3 variable of the specified type"""
    if not Z3_AVAILABLE:
        return name  # Return name if Z3 not available

    if var_type == "int":
        return Int(name)
    elif var_type == "real":
        return Real(name)
    elif var_type == "bool":
        return Bool(name)
    else:
        return Int(name)  # Default to int


def condition_to_z3(condition: Any, var_map: Dict[str, Any], solver) -> Any:
    """Convert a path condition to Z3 constraint (from symbolic_executor.py)"""
    if not Z3_AVAILABLE:
        return None

    expr = condition.expression.strip()

    # Handle expressions in format "> ('name', 'x') 0" or similar (from symbolic execution)
    import re

    # Pattern for "OPERATOR ('name', 'var') VALUE" or "OPERATOR VALUE VALUE"
    pattern = r"^([><=!]+)\s+(.+)$"
    match = re.match(pattern, expr)

    if match:
        op = match.group(1)
        operands_part = match.group(2)

        # Try to parse operands - handle both tuple format and simple format
        operands = parse_operands(operands_part)
        if len(operands) == 2:
            left_z3 = operand_to_z3(operands[0], var_map)
            right_z3 = operand_to_z3(operands[1], var_map)

            if left_z3 is not None and right_z3 is not None:
                # Create Z3 constraint
                if op == "==":
                    constraint = left_z3 == right_z3
                elif op == "!=":
                    constraint = left_z3 != right_z3
                elif op == "<":
                    constraint = left_z3 < right_z3
                elif op == "<=":
                    constraint = left_z3 <= right_z3
                elif op == ">":
                    constraint = left_z3 > right_z3
                elif op == ">=":
                    constraint = left_z3 >= right_z3
                else:
                    return None

                return constraint if condition.is_true else Not(constraint)

    # Try to parse the expression as a tuple (symbolic expression)
    try:
        if expr.startswith("(") and expr.endswith(")"):
            # Try to evaluate as Python literal to get the tuple structure
            parsed_expr = ast.literal_eval(expr)
            z3_constraint = tuple_expr_to_z3(parsed_expr, var_map, solver)
            if z3_constraint is not None:
                return z3_constraint if condition.is_true else Not(z3_constraint)
    except (ValueError, SyntaxError):
        pass

    # Handle Z3-like expressions (And, Or, etc.)
    if any(z3_op in expr for z3_op in ["And(", "Or(", "Not("]):
        try:
            z3_constraint = parse_z3_expression(expr, var_map, solver)
            if z3_constraint is not None:
                return z3_constraint if condition.is_true else Not(z3_constraint)
        except Exception:
            pass

    # Handle basic comparison operations with simple format like "x > 5"
    for op in [">=", "<=", "==", "!=", ">", "<"]:
        if op in expr and not expr.startswith(op):  # Avoid double parsing
            left, right = expr.split(op, 1)
            left = left.strip()
            right = right.strip()

            left_z3 = expr_to_z3(left, var_map, solver)
            right_z3 = expr_to_z3(right, var_map, solver)

            if left_z3 is not None and right_z3 is not None:
                if op == "==":
                    constraint = left_z3 == right_z3
                elif op == "!=":
                    constraint = left_z3 != right_z3
                elif op == "<":
                    constraint = left_z3 < right_z3
                elif op == "<=":
                    constraint = left_z3 <= right_z3
                elif op == ">":
                    constraint = left_z3 > right_z3
                elif op == ">=":
                    constraint = left_z3 >= right_z3

                return constraint if condition.is_true else Not(constraint)

    # Handle boolean expressions
    if expr in var_map:
        z3_var = var_map[expr]
        return z3_var if condition.is_true else Not(z3_var)

    return None


def expr_to_z3(expr, var_map: Dict[str, Any], solver) -> Any:
    """Convert an expression to Z3 variable or constant"""
    if not Z3_AVAILABLE:
        return None

    # Handle tuple expressions (from symbolic execution)
    if isinstance(expr, tuple):
        return tuple_expr_to_z3(expr, var_map, solver)

    # Handle string expressions
    if not isinstance(expr, str):
        expr = str(expr)

    expr = expr.strip()

    # Try to parse as integer
    try:
        return IntVal(int(expr))
    except ValueError:
        pass

    # Try to parse as float
    try:
        return RealVal(float(expr))
    except ValueError:
        pass

    # Try to parse as boolean
    if expr.lower() in ["true", "false"]:
        return BoolVal(expr.lower() == "true")

    # Treat as variable name
    if expr not in var_map:
        # Create appropriate Z3 variable based on context
        # For now, assume integer variables (could be enhanced with type inference)
        var_map[expr] = Int(expr)

    return var_map[expr]


def tuple_expr_to_z3(expr, var_map: Dict[str, Any], solver) -> Any:
    """Convert tuple expression to Z3 constraint"""
    if not Z3_AVAILABLE:
        return None

    if not isinstance(expr, tuple) or len(expr) < 2:
        return None

    op = expr[0]

    if op == "and":
        # Handle logical AND
        if len(expr) >= 3:
            left = tuple_expr_to_z3(expr[1], var_map, solver)
            right = tuple_expr_to_z3(expr[2], var_map, solver)
            if left is not None and right is not None:
                return And(left, right)

    elif op == "or":
        # Handle logical OR
        if len(expr) >= 3:
            left = tuple_expr_to_z3(expr[1], var_map, solver)
            right = tuple_expr_to_z3(expr[2], var_map, solver)
            if left is not None and right is not None:
                return Or(left, right)

    elif op in [">", "<", ">=", "<=", "==", "!="]:
        # Handle comparison operations
        if len(expr) >= 3:
            left = expr_to_z3(expr[1], var_map, solver)
            right = expr_to_z3(expr[2], var_map, solver)
            if left is not None and right is not None:
                if op == ">":
                    return left > right
                elif op == "<":
                    return left < right
                elif op == ">=":
                    return left >= right
                elif op == "<=":
                    return left <= right
                elif op == "==":
                    return left == right
                elif op == "!=":
                    return left != right

    return None


def parse_z3_expression(expr: str, var_map: Dict[str, Any], solver) -> Any:
    """Parse Z3-like expressions such as 'And(0 < x, 10 > y)'"""
    if not Z3_AVAILABLE:
        return None

    # Handle And expressions
    and_match = re.match(r"And\((.*)\)", expr)
    if and_match:
        args_str = and_match.group(1)
        args = split_condition_args(args_str)
        constraints = []
        for arg in args:
            constraint = parse_simple_condition(arg.strip(), var_map)
            if constraint is not None:
                constraints.append(constraint)
        if constraints:
            return And(*constraints) if len(constraints) > 1 else constraints[0]

    # Handle Or expressions
    or_match = re.match(r"Or\((.*)\)", expr)
    if or_match:
        args_str = or_match.group(1)
        args = split_condition_args(args_str)
        constraints = []
        for arg in args:
            constraint = parse_simple_condition(arg.strip(), var_map)
            if constraint is not None:
                constraints.append(constraint)
        if constraints:
            return Or(*constraints) if len(constraints) > 1 else constraints[0]

    # Handle Not expressions
    not_match = re.match(r"Not\((.*)\)", expr)
    if not_match:
        inner_expr = not_match.group(1)
        constraint = parse_z3_expression(inner_expr, var_map, solver)
        if constraint is not None:
            return Not(constraint)

    # Try as simple condition
    return parse_simple_condition(expr, var_map)


def split_condition_args(args_str: str) -> List[str]:
    """Split condition arguments, handling nested parentheses"""
    args = []
    current_arg = ""
    paren_count = 0

    for char in args_str:
        if char == "," and paren_count == 0:
            args.append(current_arg.strip())
            current_arg = ""
        else:
            if char == "(":
                paren_count += 1
            elif char == ")":
                paren_count -= 1
            current_arg += char

    if current_arg.strip():
        args.append(current_arg.strip())

    return args


def parse_simple_condition(expr: str, var_map: Dict[str, Any]) -> Any:
    """Parse a simple condition like '0 < x' or 'x > 10'"""
    if not Z3_AVAILABLE:
        return None

    # Handle comparison operations
    patterns = [
        (r"(\w+)\s*([><=!]+)\s*(.+)", lambda m: (m.group(1), m.group(2), m.group(3))),
        (r"(.+)\s*([><=!]+)\s*(\w+)", lambda m: (m.group(1), m.group(2), m.group(3))),
    ]

    for pattern, extractor in patterns:
        match = re.match(pattern, expr.strip())
        if match:
            left_str, op, right_str = extractor(match)
            left_str = left_str.strip()
            right_str = right_str.strip()

            # Convert to Z3 expressions
            left_z3 = simple_expr_to_z3(left_str, var_map)
            right_z3 = simple_expr_to_z3(right_str, var_map)

            if left_z3 is None or right_z3 is None:
                continue

            # Create constraint
            ops = {
                ">": lambda a, b: a > b,
                "<": lambda a, b: a < b,
                ">=": lambda a, b: a >= b,
                "<=": lambda a, b: a <= b,
                "==": lambda a, b: a == b,
                "!=": lambda a, b: a != b,
            }

            if op in ops:
                return ops[op](left_z3, right_z3)

    return None


def simple_expr_to_z3(expr: str, var_map: Dict[str, Any]) -> Any:
    """Convert simple expressions to Z3, handling variables and constants"""
    if not Z3_AVAILABLE:
        return None

    expr = expr.strip()

    # Try integer
    try:
        return IntVal(int(expr))
    except ValueError:
        pass

    # Try float
    try:
        return RealVal(float(expr))
    except ValueError:
        pass

    # Try boolean
    if expr.lower() in ["true", "false"]:
        return BoolVal(expr.lower() == "true")

    # Handle special Z3 functions
    if expr.startswith("ToReal(") and expr.endswith(")"):
        inner = expr[7:-1]
        inner_z3 = simple_expr_to_z3(inner, var_map)
        if inner_z3 is not None:
            return ToReal(inner_z3)

    # Treat as variable
    if expr not in var_map:
        var_map[expr] = Int(expr)
    return var_map[expr]


def enhanced_ast_to_z3(
    node,
    var_dict,
    handle_subscript_func=None,
    handle_in_notin_func=None,
    z3_min_list_func=None,
    z3_max_list_func=None,
):
    """Enhanced AST to Z3 conversion with support for more node types"""
    if not Z3_AVAILABLE:
        return None

    if isinstance(node, ast.BoolOp):
        return simplify(
            get_boolop_func(node.op)(
                *[
                    enhanced_ast_to_z3(
                        v,
                        var_dict,
                        handle_subscript_func,
                        handle_in_notin_func,
                        z3_min_list_func,
                        z3_max_list_func,
                    )
                    for v in node.values
                ]
            )
        )

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            operand = enhanced_ast_to_z3(
                node.operand,
                var_dict,
                handle_subscript_func,
                handle_in_notin_func,
                z3_min_list_func,
                z3_max_list_func,
            )
            if operand and Z3_AVAILABLE:
                try:
                    if hasattr(operand, "sort") and operand.sort() != BoolSort():
                        operand = operand != 0
                except Exception:
                    pass
            return Not(operand) if operand else None
        return None

    if isinstance(node, ast.Compare):
        left = enhanced_ast_to_z3(
            node.left,
            var_dict,
            handle_subscript_func,
            handle_in_notin_func,
            z3_min_list_func,
            z3_max_list_func,
        )
        if not left:
            return None

        op = node.ops[0]
        right_node = node.comparators[0]

        if isinstance(op, (ast.In, ast.NotIn)) and handle_in_notin_func:
            return handle_in_notin_func(left, op, right_node, var_dict)

        right = enhanced_ast_to_z3(
            right_node,
            var_dict,
            handle_subscript_func,
            handle_in_notin_func,
            z3_min_list_func,
            z3_max_list_func,
        )
        if not right:
            return None

        return get_cmp_func(op)(left, right)

    if isinstance(node, ast.BinOp):
        left = enhanced_ast_to_z3(
            node.left,
            var_dict,
            handle_subscript_func,
            handle_in_notin_func,
            z3_min_list_func,
            z3_max_list_func,
        )
        right = enhanced_ast_to_z3(
            node.right,
            var_dict,
            handle_subscript_func,
            handle_in_notin_func,
            z3_min_list_func,
            z3_max_list_func,
        )
        if not left or not right:
            return None
        return get_binop_func(node.op)(left, right)

    if isinstance(node, ast.Subscript) and handle_subscript_func:
        value = enhanced_ast_to_z3(
            node.value,
            var_dict,
            handle_subscript_func,
            handle_in_notin_func,
            z3_min_list_func,
            z3_max_list_func,
        )
        if not value:
            return None

        # Handle different slice types
        if isinstance(node.slice, ast.Slice):
            # Slice operations - simplified handling
            return value  # For now, return the original value
        elif isinstance(node.slice, ast.Constant):
            idx = node.slice.value
            return handle_subscript_func(value, idx, var_dict)
        elif isinstance(node.slice, ast.Name):
            idx = var_dict.get(node.slice.id)
            if idx is None:
                idx = Int(node.slice.id)
                var_dict[node.slice.id] = idx
            return handle_subscript_func(value, idx, var_dict)
        else:
            idx = enhanced_ast_to_z3(
                node.slice,
                var_dict,
                handle_subscript_func,
                handle_in_notin_func,
                z3_min_list_func,
                z3_max_list_func,
            )
            return handle_subscript_func(value, idx, var_dict) if idx else None

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            return None

        func_name = node.func.id

        if func_name == "int":
            if node.args:
                return enhanced_ast_to_z3(
                    node.args[0],
                    var_dict,
                    handle_subscript_func,
                    handle_in_notin_func,
                    z3_min_list_func,
                    z3_max_list_func,
                )
            return IntVal(0)

        if func_name == "len":
            # Simplified length handling - assume known length
            return IntVal(3)  # Default length for symbolic lists

        if func_name in ["min", "max"]:
            args_z3 = [
                enhanced_ast_to_z3(
                    arg,
                    var_dict,
                    handle_subscript_func,
                    handle_in_notin_func,
                    z3_min_list_func,
                    z3_max_list_func,
                )
                for arg in node.args
            ]
            args_z3 = [arg for arg in args_z3 if arg is not None]
            if not args_z3:
                return None

            if len(args_z3) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                # min([a,b,c]) or max([a,b,c])
                elts = node.args[0].elts
                elts_z3 = [
                    enhanced_ast_to_z3(
                        e,
                        var_dict,
                        handle_subscript_func,
                        handle_in_notin_func,
                        z3_min_list_func,
                        z3_max_list_func,
                    )
                    for e in elts
                ]
                elts_z3 = [e for e in elts_z3 if e is not None]
                if func_name == "min" and z3_min_list_func:
                    return z3_min_list_func(elts_z3)
                elif func_name == "max" and z3_max_list_func:
                    return z3_max_list_func(elts_z3)
            else:
                # min(a,b,c) or max(a,b,c)
                if func_name == "min" and z3_min_list_func:
                    return z3_min_list_func(args_z3)
                elif func_name == "max" and z3_max_list_func:
                    return z3_max_list_func(args_z3)

        return None

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
        return None

    if isinstance(node, (ast.Tuple, ast.List)):
        return [
            enhanced_ast_to_z3(
                elt,
                var_dict,
                handle_subscript_func,
                handle_in_notin_func,
                z3_min_list_func,
                z3_max_list_func,
            )
            for elt in node.elts
        ]

    return None


def z3_min_list(lst):
    """Compute minimum of a list using Z3 If expressions"""
    if not Z3_AVAILABLE:
        return None
    if not lst:
        return IntVal(0)
    current_min = lst[0]
    for v in lst[1:]:
        current_min = If(current_min <= v, current_min, v)
    return current_min


def z3_max_list(lst):
    """Compute maximum of a list using Z3 If expressions"""
    if not Z3_AVAILABLE:
        return None
    if not lst:
        return IntVal(0)
    current_max = lst[0]
    for v in lst[1:]:
        current_max = If(current_max >= v, current_max, v)
    return current_max


def ast_to_z3_expr(expr: ast.AST, var_dict: Optional[Dict[str, Any]] = None) -> Any:
    """
    Convert an AST expression to a Z3 expression.

    Args:
        expr: AST node to convert
        var_dict: Dictionary mapping variable names to Z3 variables

    Returns:
        Z3 expression or None if conversion fails
    """
    if not Z3_AVAILABLE:
        return None

    if var_dict is None:
        var_dict = {}

    try:
        return _ast_to_z3_recursive(expr, var_dict)
    except Exception:
        return None


def _ast_to_z3_recursive(expr: ast.AST, var_dict: Dict[str, Any]) -> Any:
    """Recursive helper for AST to Z3 conversion"""

    # Handle direct values
    if isinstance(expr, int):
        return IntVal(expr)
    if isinstance(expr, float):
        return RealVal(expr)
    if isinstance(expr, bool):
        return BoolVal(expr)
    if isinstance(expr, str):
        return var_dict.get(expr, Int(expr))

    # Handle Z3 expressions directly
    if hasattr(expr, "sort"):  # Z3 expression
        return expr

    if not isinstance(expr, ast.AST):
        return None

    # Constant values
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, int):
            return IntVal(expr.value)
        elif isinstance(expr.value, float):
            return RealVal(expr.value)
        elif isinstance(expr.value, bool):
            return BoolVal(expr.value)
        else:
            return None

    # Variable names
    if isinstance(expr, ast.Name):
        if expr.id not in var_dict:
            var_dict[expr.id] = create_z3_variable(expr.id)
        return var_dict[expr.id]

    # Binary operations
    if isinstance(expr, ast.BinOp):
        left = _ast_to_z3_recursive(expr.left, var_dict)
        right = _ast_to_z3_recursive(expr.right, var_dict)
        if left is None or right is None:
            return None

        func = get_binop_func(expr.op)
        return func(left, right)

    # Unary operations
    if isinstance(expr, ast.UnaryOp):
        operand = _ast_to_z3_recursive(expr.operand, var_dict)
        if operand is None:
            return None

        func = get_unaryop_func(expr.op)
        return func(operand)

    # Comparisons
    if isinstance(expr, ast.Compare):
        if len(expr.ops) == 1 and len(expr.comparators) == 1:
            left = _ast_to_z3_recursive(expr.left, var_dict)
            right = _ast_to_z3_recursive(expr.comparators[0], var_dict)
            if left is None or right is None:
                return None

            func = get_cmp_func(expr.ops[0])
            return func(left, right)
        else:
            # Handle chained comparisons
            constraints = []
            current = expr.left

            for op, comparator in zip(expr.ops, expr.comparators):
                left = _ast_to_z3_recursive(current, var_dict)
                right = _ast_to_z3_recursive(comparator, var_dict)
                if left is None or right is None:
                    return None

                func = get_cmp_func(op)
                constraints.append(func(left, right))
                current = comparator

            return And(*constraints) if len(constraints) > 1 else constraints[0]

    # Boolean operations
    if isinstance(expr, ast.BoolOp):
        values = []
        for value in expr.values:
            z3_value = _ast_to_z3_recursive(value, var_dict)
            if z3_value is None:
                return None
            values.append(z3_value)

        func = get_boolop_func(expr.op)
        return func(*values)

    return None


def simplify_range_cond(
    k: int, start, stop, step=None, var_dict: Optional[Dict[str, Any]] = None
):
    """
    Generate Z3 constraint for the k-th iteration of a range loop.

    Args:
        k: Iteration number (0-based)
        start: Start value (int, AST node, or Z3 expression)
        stop: Stop value (int, AST node, or Z3 expression)
        step: Step value (int, AST node, or Z3 expression), defaults to 1
        var_dict: Dictionary mapping variable names to Z3 variables

    Returns:
        Z3 constraint for the k-th iteration, or None if unsatisfiable
    """
    if not Z3_AVAILABLE:
        return None

    if var_dict is None:
        var_dict = {}

    # Convert to Z3 expressions
    start_expr = to_z3_expr(start, var_dict)
    stop_expr = to_z3_expr(stop, var_dict)
    step_expr = to_z3_expr(step if step is not None else 1, var_dict)

    if None in [start_expr, stop_expr, step_expr]:
        return None

    # Calculate iteration value: start + k * step
    iter_val = start_expr + IntVal(k) * step_expr

    # Determine step direction for constraint generation
    step_const = extract_constant_value(step_expr)

    constraints = []
    if step_const is None or step_const > 0:
        # Positive step: iter_val < stop and iter_val >= start
        constraints.append(iter_val < stop_expr)
        constraints.append(iter_val >= start_expr)
    elif step_const < 0:
        # Negative step: iter_val > stop and iter_val <= start
        constraints.append(iter_val > stop_expr)
        constraints.append(iter_val <= start_expr)
    else:
        # Zero step is invalid
        return None

    final_constraint = simplify(And(*constraints))

    # Check satisfiability
    if not is_sat(final_constraint):
        return None

    return final_constraint


def to_z3_expr(expr, var_dict: Optional[Dict[str, Any]] = None):
    """
    Convert various expression types to Z3 expressions.

    Handles: int, float, bool, str, AST nodes, Z3 expressions
    """
    if not Z3_AVAILABLE:
        return None

    if var_dict is None:
        var_dict = {}

    # Direct Z3 expressions
    if hasattr(expr, "sort"):
        return expr

    # Python primitives
    if isinstance(expr, int):
        return IntVal(expr)
    if isinstance(expr, float):
        return RealVal(expr)
    if isinstance(expr, bool):
        return BoolVal(expr)
    if isinstance(expr, str):
        if expr not in var_dict:
            var_dict[expr] = create_z3_variable(expr)
        return var_dict[expr]

    # AST nodes
    if isinstance(expr, ast.AST):
        return ast_to_z3_expr(expr, var_dict)

    return None


def extract_constant_value(z3_expr) -> Optional[Union[int, float, bool]]:
    """Extract constant value from Z3 expression if possible"""
    if not Z3_AVAILABLE:
        return None

    try:
        if z3.is_int_value(z3_expr):
            return z3_expr.as_long()
        elif z3.is_rational_value(z3_expr):
            return float(z3_expr.as_decimal(10))
        elif z3.is_bool(z3_expr):
            return z3.is_true(z3_expr)
    except Exception:
        pass

    return None


def get_vars_from_ast(node: ast.AST) -> Set[str]:
    """Extract all variable names from an AST node"""
    variables = set()

    class VariableCollector(ast.NodeVisitor):
        def visit_Name(self, node):
            variables.add(node.id)
            self.generic_visit(node)

    collector = VariableCollector()
    collector.visit(node)
    return variables


def create_solver_with_constraints(constraints: List[Any]) -> Optional[Solver]:
    """Create a Z3 solver with the given constraints"""
    if not Z3_AVAILABLE or not constraints:
        return None

    solver = Solver()
    for constraint in constraints:
        if constraint is not None:
            solver.add(constraint)

    return solver


def check_path_satisfiability(
    conditions: List[str], var_dict: Optional[Dict[str, Any]] = None
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a list of path conditions is satisfiable.

    Returns:
        Tuple of (is_satisfiable, model_values)
    """
    if not Z3_AVAILABLE:
        return True, None

    if var_dict is None:
        var_dict = {}

    solver = Solver()
    # Track which variables are actual program variables (not constants)
    # Initialize with existing variables from var_dict (these are already program variables)
    program_variables = set(var_dict.keys())

    for condition_str in conditions:
        try:
            # Simple parsing for basic conditions
            constraint = parse_condition_string(
                condition_str, var_dict, program_variables
            )
            if constraint is not None:
                solver.add(constraint)
        except Exception:
            continue  # Skip unparseable conditions

    result = solver.check()
    if result == sat:
        model = solver.model()
        # Only extract values for actual program variables, not constants
        model_values = {}
        for var_name in program_variables:
            if var_name in var_dict and model[var_dict[var_name]] is not None:
                z3_value = model[var_dict[var_name]]
                # Convert Z3 value to Python value
                if z3.is_int_value(z3_value):
                    model_values[var_name] = str(z3_value.as_long())
                elif z3.is_real_value(z3_value):
                    model_values[var_name] = str(float(z3_value.as_fraction()))
                elif z3.is_bool(z3_value):
                    model_values[var_name] = str(z3.is_true(z3_value)).lower()
                else:
                    model_values[var_name] = str(z3_value)
        return True, model_values
    else:
        return False, None


def parse_condition_string(
    condition: str, var_dict: Dict[str, Any], program_variables: set
) -> Optional[Any]:
    """
    Parse a condition string into a Z3 constraint.

    Handles simple conditions like "x > 5", "y == 10", "5 < x", etc.
    """
    if not Z3_AVAILABLE:
        return None

    # Remove "not " prefix and track negation
    negated = False
    if condition.startswith("not "):
        negated = True
        condition = condition[4:]

    # Remove parentheses
    condition = condition.strip("()")

    # Pattern for simple comparisons: left op right
    pattern = r"(\w+)\s*([><=!]+)\s*(.+)"
    match = re.match(pattern, condition)

    if not match:
        return None

    left_str, op, right_str = match.groups()
    left_str = left_str.strip()
    right_str = right_str.strip()

    # Determine which is variable and which is constant
    left_value = None
    right_value = None

    # Try to parse left as constant first
    try:
        left_value = IntVal(int(left_str))
    except ValueError:
        try:
            left_value = RealVal(float(left_str))
        except ValueError:
            if left_str.lower() in ["true", "false"]:
                left_value = BoolVal(left_str.lower() == "true")
            else:
                # It's a variable

                if left_str not in var_dict:
                    var_dict[left_str] = create_z3_variable(left_str)
                    program_variables.add(left_str)
                left_value = var_dict[left_str]

    # Try to parse right as constant first
    try:
        right_value = IntVal(int(right_str))
    except ValueError:
        try:
            right_value = RealVal(float(right_str))
        except ValueError:
            if right_str.lower() in ["true", "false"]:
                right_value = BoolVal(right_str.lower() == "true")
            else:
                # It's a variable

                if right_str not in var_dict:
                    var_dict[right_str] = create_z3_variable(right_str)
                    program_variables.add(right_str)
                right_value = var_dict[right_str]

    if left_value is None or right_value is None:
        return None

    # Create constraint
    ops = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }

    if op not in ops:
        return None

    constraint = ops[op](left_value, right_value)

    return Not(constraint) if negated else constraint


def parse_operands(operands_str: str) -> List[Any]:
    """Parse operands from string like "('name', 'x') 0" """
    operands = []

    # Handle tuple operand followed by simple operand
    match = re.match(r"\(([^)]+)\)\s+(.+)$", operands_str.strip())
    if match:
        tuple_content = match.group(1)
        second_operand = match.group(2)

        try:
            # Parse the tuple content
            tuple_parts = [
                part.strip().strip("'\"") for part in tuple_content.split(",")
            ]
            if len(tuple_parts) == 2:
                operands.append(tuple(tuple_parts))  # ('name', 'x')

                # Parse second operand
                try:
                    operands.append(int(second_operand))
                except ValueError:
                    try:
                        operands.append(float(second_operand))
                    except ValueError:
                        operands.append(second_operand)

                return operands
        except Exception:
            pass

    # Fallback: try to split by spaces and parse each part
    parts = operands_str.split()
    for part in parts:
        try:
            operands.append(int(part))
        except ValueError:
            try:
                operands.append(float(part))
            except ValueError:
                if part.startswith("(") and part.endswith(")"):
                    try:
                        operands.append(ast.literal_eval(part))
                    except Exception:
                        operands.append(part)
                else:
                    operands.append(part)

    return operands


def operand_to_z3(operand: Any, var_map: Dict[str, Any]) -> Any:
    """Convert an operand (which could be ('name', 'x') or a constant) to Z3"""
    if not Z3_AVAILABLE:
        return None

    # Handle tuple format like ('name', 'x')
    if isinstance(operand, tuple) and len(operand) == 2:
        if operand[0] == "name":
            var_name = operand[1]
            if var_name not in var_map:
                var_map[var_name] = Int(var_name)
            return var_map[var_name]

    # Handle constants
    if isinstance(operand, int):
        return IntVal(operand)
    elif isinstance(operand, float):
        return RealVal(operand)
    elif isinstance(operand, str):
        # Try to parse as number first
        try:
            return IntVal(int(operand))
        except ValueError:
            try:
                return RealVal(float(operand))
            except ValueError:
                # Treat as variable name
                if operand not in var_map:
                    var_map[operand] = Int(operand)
                return var_map[operand]

    return None
