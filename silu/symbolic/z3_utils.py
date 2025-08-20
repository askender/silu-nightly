#!/usr/bin/env python3
"""
Z3 Utilities for Symbolic Execution

This module provides utilities for converting AST nodes to Z3 expressions,
handling constraints, and performing satisfiability checking.
"""

import ast
from typing import Any, Dict, List, Optional, Set, Union
from z3 import Solver, sat, And, Or, Not, IntVal, BoolVal, RealVal, IntNumRef, BoolRef, simplify

# Z3 availability check
try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False
    z3 = None


# Operator mappings from AST to Z3
BOOLOP_MAP = {
    ast.And: And,
    ast.Or: Or
}

BINOP_MAP = {
    ast.Add: lambda l, r: l + r,
    ast.Sub: lambda l, r: l - r,
    ast.Mult: lambda l, r: l * r,
    ast.Div: lambda l, r: l / r,
    ast.FloorDiv: lambda l, r: l // r,
    ast.Mod: lambda l, r: l % r,
    ast.Pow: lambda l, r: l ** r,
}

CMP_MAP = {
    ast.Eq: lambda l, r: l == r,
    ast.NotEq: lambda l, r: l != r,
    ast.Lt: lambda l, r: l < r,
    ast.LtE: lambda l, r: l <= r,
    ast.Gt: lambda l, r: l > r,
    ast.GtE: lambda l, r: l >= r,
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
        return z3.Int(name)
    elif var_type == "real":
        return z3.Real(name)
    elif var_type == "bool":
        return z3.Bool(name)
    else:
        return z3.Int(name)  # Default to int


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
        return var_dict.get(expr, z3.Int(expr))

    # Handle Z3 expressions directly
    if hasattr(expr, 'sort'):  # Z3 expression
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


def simplify_range_cond(k: int, start, stop, step=None, var_dict: Optional[Dict[str, Any]] = None):
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
    if hasattr(expr, 'sort'):
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


def check_path_satisfiability(conditions: List[str], var_dict: Optional[Dict[str, Any]] = None) -> tuple[bool, Optional[Dict[str, Any]]]:
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
            constraint = parse_condition_string(condition_str, var_dict, program_variables)
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


def parse_condition_string(condition: str, var_dict: Dict[str, Any], program_variables: set) -> Optional[Any]:
    """
    Parse a condition string into a Z3 constraint.

    Handles simple conditions like "x > 5", "y == 10", "5 < x", etc.
    """
    if not Z3_AVAILABLE:
        return None

    import re

    # Remove "not " prefix and track negation
    negated = False
    if condition.startswith("not "):
        negated = True
        condition = condition[4:]

    # Remove parentheses
    condition = condition.strip("()")

    # Pattern for simple comparisons: left op right
    pattern = r'(\w+)\s*([><=!]+)\s*(.+)'
    match = re.match(pattern, condition)

    if not match:
        return None

    left_str, op, right_str = match.groups()
    left_str = left_str.strip()
    right_str = right_str.strip()

    # Determine which is variable and which is constant
    left_is_var = False
    right_is_var = False
    left_value = None
    right_value = None

    # Try to parse left as constant first
    try:
        left_value = IntVal(int(left_str))
    except ValueError:
        try:
            left_value = RealVal(float(left_str))
        except ValueError:
            if left_str.lower() in ['true', 'false']:
                left_value = BoolVal(left_str.lower() == 'true')
            else:
                # It's a variable
                left_is_var = True
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
            if right_str.lower() in ['true', 'false']:
                right_value = BoolVal(right_str.lower() == 'true')
            else:
                # It's a variable
                right_is_var = True
                if right_str not in var_dict:
                    var_dict[right_str] = create_z3_variable(right_str)
                    program_variables.add(right_str)
                right_value = var_dict[right_str]

    if left_value is None or right_value is None:
        return None

    # Create constraint
    ops = {
        '>': lambda a, b: a > b,
        '<': lambda a, b: a < b,
        '>=': lambda a, b: a >= b,
        '<=': lambda a, b: a <= b,
        '==': lambda a, b: a == b,
        '!=': lambda a, b: a != b,
    }

    if op not in ops:
        return None

    constraint = ops[op](left_value, right_value)

    return Not(constraint) if negated else constraint
