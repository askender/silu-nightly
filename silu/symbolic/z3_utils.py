#!/usr/bin/env python3
"""
Z3 Utilities for Symbolic Execution

This module provides utilities for converting AST nodes to Z3 expressions,
handling constraints, and performing satisfiability checking.
"""

import ast
import re
from typing import Any, Dict, List, Optional, Set, Union, Callable

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
    # Create dummy classes/functions when Z3 is not available
    class _DummyZ3:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    if z3 is None:
        z3 = _DummyZ3()

    # Dummy functions for when Z3 is not available
    Solver = lambda: None
    sat = None
    And = Or = Not = If = lambda *args: None
    IntVal = BoolVal = RealVal = lambda x: None
    BoolSort = Int = Real = Bool = ToReal = simplify = lambda *args: None


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


class Z3OperatorMapper:
    """Helper class to safely map AST operators to Z3 functions"""

    @staticmethod
    def get_boolop_func(op: ast.boolop) -> Callable:
        """Get Z3 function for boolean operation"""
        func = BOOLOP_MAP.get(type(op))
        if func is None:
            raise NotImplementedError(f"Unsupported BoolOp: {type(op).__name__}")
        return func

    @staticmethod
    def get_binop_func(op: ast.operator) -> Callable:
        """Get Z3 function for binary operation"""
        func = BINOP_MAP.get(type(op))
        if func is None:
            raise NotImplementedError(f"Unsupported BinOp: {type(op).__name__}")
        return func

    @staticmethod
    def get_cmp_func(op: ast.cmpop) -> Callable:
        """Get Z3 function for comparison operation"""
        func = CMP_MAP.get(type(op))
        if func is None:
            raise NotImplementedError(f"Unsupported Compare: {type(op).__name__}")
        return func

    @staticmethod
    def get_unaryop_func(op: ast.unaryop) -> Callable:
        """Get Z3 function for unary operation"""
        func = UNARYOP_MAP.get(type(op))
        if func is None:
            raise NotImplementedError(f"Unsupported UnaryOp: {type(op).__name__}")
        return func


# Legacy function wrappers for backward compatibility
def get_boolop_func(op: ast.boolop) -> Callable:
    """Get Z3 function for boolean operation"""
    return Z3OperatorMapper.get_boolop_func(op)


def get_binop_func(op: ast.operator) -> Callable:
    """Get Z3 function for binary operation"""
    return Z3OperatorMapper.get_binop_func(op)


def get_cmp_func(op: ast.cmpop) -> Callable:
    """Get Z3 function for comparison operation"""
    return Z3OperatorMapper.get_cmp_func(op)


def get_unaryop_func(op: ast.unaryop) -> Callable:
    """Get Z3 function for unary operation"""
    return Z3OperatorMapper.get_unaryop_func(op)


class Z3SafeOperations:
    """Safe wrapper for Z3 operations that handles unavailability"""

    @staticmethod
    def is_sat(constraint) -> bool:
        """Check if a Z3 constraint is satisfiable"""
        if not Z3_AVAILABLE or constraint is None:
            return True  # Default to satisfiable if Z3 not available

        try:
            solver = Solver()
            solver.add(constraint)
            return solver.check() == sat
        except Exception:
            return True

    @staticmethod
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

    @staticmethod
    def extract_constant_value(z3_expr) -> Optional[Union[int, float, bool]]:
        """Extract constant value from Z3 expression if possible"""
        if not Z3_AVAILABLE or z3_expr is None:
            return None

        try:
            if (hasattr(z3, 'is_int_value') and z3 is not None and
                z3.is_int_value(z3_expr)):
                return z3_expr.as_long()
            elif (hasattr(z3, 'is_rational_value') and z3 is not None and
                  z3.is_rational_value(z3_expr)):
                return float(z3_expr.as_decimal(10))
            elif (hasattr(z3, 'is_bool') and z3 is not None and
                  z3.is_bool(z3_expr)):
                return z3.is_true(z3_expr)
        except Exception:
            pass

        return None

    @staticmethod
    def create_solver_with_constraints(constraints: List[Any]) -> Optional[Any]:
        """Create a Z3 solver with the given constraints"""
        if not Z3_AVAILABLE or not constraints:
            return None

        try:
            solver = Solver()
            for constraint in constraints:
                if constraint is not None:
                    solver.add(constraint)
            return solver
        except Exception:
            return None


# Legacy function wrappers
def is_sat(constraint) -> bool:
    """Check if a Z3 constraint is satisfiable"""
    return Z3SafeOperations.is_sat(constraint)


def create_z3_variable(name: str, var_type: str = "int"):
    """Create a Z3 variable of the specified type"""
    return Z3SafeOperations.create_z3_variable(name, var_type)


def extract_constant_value(z3_expr) -> Optional[Union[int, float, bool]]:
    """Extract constant value from Z3 expression if possible"""
    return Z3SafeOperations.extract_constant_value(z3_expr)


def create_solver_with_constraints(constraints: List[Any]) -> Optional[Any]:
    """Create a Z3 solver with the given constraints"""
    return Z3SafeOperations.create_solver_with_constraints(constraints)


class ExpressionParser:
    """Helper class to parse expressions into Z3 constraints"""

    def __init__(self):
        self.comparison_ops = [">=", "<=", "==", "!=", ">", "<"]

    def _parse_basic_comparison(self, expr: str, var_map: Dict[str, Any]) -> Optional[Any]:
        """Parse basic comparison operations like 'x > 5'"""
        if not Z3_AVAILABLE:
            return None

        # Find comparison operator
        for op in self.comparison_ops:
            if op in expr and not expr.startswith(op):
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()

                    left_z3 = self._expr_to_z3_simple(left, var_map)
                    right_z3 = self._expr_to_z3_simple(right, var_map)

                    if left_z3 is not None and right_z3 is not None:
                        return self._create_comparison(left_z3, op, right_z3)

        return None

    def _expr_to_z3_simple(self, expr: str, var_map: Dict[str, Any]) -> Any:
        """Convert simple expression to Z3"""
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

        # Treat as variable
        if expr not in var_map:
            var_map[expr] = Int(expr)
        return var_map[expr]

    def _create_comparison(self, left, op: str, right):
        """Create Z3 comparison constraint"""
        if not Z3_AVAILABLE:
            return None

        if op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op == "<":
            return left < right
        elif op == "<=":
            return left <= right
        elif op == ">":
            return left > right
        elif op == ">=":
            return left >= right

        return None

    def parse_operand_format(self, expr: str, var_map: Dict[str, Any]) -> Optional[Any]:
        """Parse expressions in format '> ('name', 'x') 0'"""
        if not Z3_AVAILABLE:
            return None

        # Pattern for "OPERATOR ('name', 'var') VALUE" or "OPERATOR VALUE VALUE"
        pattern = r"^([><=!]+)\s+(.+)$"
        match = re.match(pattern, expr)

        if match:
            op = match.group(1)
            operands_part = match.group(2)

            operands = self._parse_operands(operands_part)
            if len(operands) == 2:
                left_z3 = self._operand_to_z3(operands[0], var_map)
                right_z3 = self._operand_to_z3(operands[1], var_map)

                if left_z3 is not None and right_z3 is not None:
                    return self._create_comparison(left_z3, op, right_z3)

        return None

    def _parse_operands(self, operands_str: str) -> List[Any]:
        """Parse operands from string"""
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
                    operands.append(tuple(tuple_parts))

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

        # Fallback parsing
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

    def _operand_to_z3(self, operand: Any, var_map: Dict[str, Any]) -> Any:
        """Convert operand to Z3 expression"""
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
            return self._expr_to_z3_simple(operand, var_map)

        return None


class ConditionProcessor:
    """Processes path conditions and converts them to Z3 constraints"""

    def __init__(self):
        self.parser = ExpressionParser()

    def condition_to_z3_simple(self, condition_str: str, var_map: Dict[str, Any],
                              is_true: bool = True) -> Any:
        """Simple condition processing for basic cases"""
        if not Z3_AVAILABLE:
            return None

        # Try operand format parsing
        constraint = self.parser.parse_operand_format(condition_str, var_map)
        if constraint is not None:
            return constraint if is_true else Not(constraint)

        # Try basic comparison parsing
        constraint = self.parser._parse_basic_comparison(condition_str, var_map)
        if constraint is not None:
            return constraint if is_true else Not(constraint)

        # Handle boolean variables
        if condition_str in var_map:
            z3_var = var_map[condition_str]
            return z3_var if is_true else Not(z3_var)

        return None

    def tuple_expr_to_z3_simple(self, expr: tuple, var_map: Dict[str, Any]) -> Any:
        """Simple tuple expression processing"""
        if not Z3_AVAILABLE or not isinstance(expr, tuple) or len(expr) < 2:
            return None

        op = expr[0]

        if op == "and" and len(expr) >= 3:
            left = self._convert_expr_recursive(expr[1], var_map)
            right = self._convert_expr_recursive(expr[2], var_map)
            if left is not None and right is not None:
                return And(left, right)

        elif op == "or" and len(expr) >= 3:
            left = self._convert_expr_recursive(expr[1], var_map)
            right = self._convert_expr_recursive(expr[2], var_map)
            if left is not None and right is not None:
                return Or(left, right)

        elif op in [">", "<", ">=", "<=", "==", "!="] and len(expr) >= 3:
            left = self._convert_expr_value(expr[1], var_map)
            right = self._convert_expr_value(expr[2], var_map)
            if left is not None and right is not None:
                return self.parser._create_comparison(left, op, right)

        return None

    def _convert_expr_recursive(self, expr, var_map: Dict[str, Any]) -> Any:
        """Recursively convert expressions"""
        if isinstance(expr, tuple):
            return self.tuple_expr_to_z3_simple(expr, var_map)
        else:
            return self._convert_expr_value(expr, var_map)

    def _convert_expr_value(self, expr, var_map: Dict[str, Any]) -> Any:
        """Convert expression value to Z3"""
        if not Z3_AVAILABLE:
            return None

        if isinstance(expr, tuple):
            return self.tuple_expr_to_z3_simple(expr, var_map)

        if not isinstance(expr, str):
            expr = str(expr)

        return self.parser._expr_to_z3_simple(expr.strip(), var_map)


def condition_to_z3(condition: Any, var_map: Dict[str, Any], solver) -> Any:
    """Convert a path condition to Z3 constraint"""
    if not Z3_AVAILABLE:
        return None

    processor = ConditionProcessor()
    expr = condition.expression.strip()

    # Try operand format first
    constraint = processor.parser.parse_operand_format(expr, var_map)
    if constraint is not None:
        return constraint if condition.is_true else Not(constraint)

    # Try tuple expression parsing
    try:
        if expr.startswith("(") and expr.endswith(")"):
            parsed_expr = ast.literal_eval(expr)
            z3_constraint = processor.tuple_expr_to_z3_simple(parsed_expr, var_map)
            if z3_constraint is not None:
                return z3_constraint if condition.is_true else Not(z3_constraint)
    except (ValueError, SyntaxError):
        pass

    # Handle Z3-like expressions
    if any(z3_op in expr for z3_op in ["And(", "Or(", "Not("]):
        try:
            z3_constraint = parse_z3_expression(expr, var_map, solver)
            if z3_constraint is not None:
                return z3_constraint if condition.is_true else Not(z3_constraint)
        except Exception:
            pass

    # Try basic comparison
    constraint = processor.parser._parse_basic_comparison(expr, var_map)
    if constraint is not None:
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

    processor = ConditionProcessor()

    # Handle tuple expressions
    if isinstance(expr, tuple):
        return processor.tuple_expr_to_z3_simple(expr, var_map)

    # Handle string expressions
    if not isinstance(expr, str):
        expr = str(expr)

    return processor.parser._expr_to_z3_simple(expr.strip(), var_map)


def tuple_expr_to_z3(expr, var_map: Dict[str, Any], solver) -> Any:
    """Convert tuple expression to Z3 constraint"""
    if not Z3_AVAILABLE:
        return None

    processor = ConditionProcessor()
    return processor.tuple_expr_to_z3_simple(expr, var_map)


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

    parser = ExpressionParser()
    return parser._parse_basic_comparison(expr, var_map)


def simple_expr_to_z3(expr: str, var_map: Dict[str, Any]) -> Any:
    """Convert simple expressions to Z3, handling variables and constants"""
    if not Z3_AVAILABLE:
        return None

    parser = ExpressionParser()
    return parser._expr_to_z3_simple(expr, var_map)


class EnhancedASTConverter:
    """Enhanced AST to Z3 converter with better structure"""

    def __init__(self):
        self.mapper = Z3OperatorMapper()

    def convert(self, node, var_dict, handle_subscript_func=None,
                handle_in_notin_func=None, z3_min_list_func=None,
                z3_max_list_func=None):
        """Main conversion method"""
        if not Z3_AVAILABLE:
            return None

        return self._convert_node(
            node, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )

    def _convert_node(self, node, var_dict, handle_subscript_func,
                      handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Convert individual AST node"""
        if isinstance(node, ast.BoolOp):
            return self._handle_boolop(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.UnaryOp):
            return self._handle_unaryop(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.Compare):
            return self._handle_compare(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.BinOp):
            return self._handle_binop(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.Subscript):
            return self._handle_subscript(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.Call):
            return self._handle_call(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        if isinstance(node, ast.Name):
            return self._handle_name(node, var_dict)

        if isinstance(node, ast.Constant):
            return self._handle_constant(node)

        if isinstance(node, (ast.Tuple, ast.List)):
            return self._handle_sequence(
                node, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )

        return None

    def _handle_boolop(self, node, var_dict, handle_subscript_func,
                       handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle boolean operations"""
        values = []
        for v in node.values:
            converted = self._convert_node(
                v, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )
            if converted is not None:
                values.append(converted)

        if values:
            return simplify(self.mapper.get_boolop_func(node.op)(*values))
        return None

    def _handle_unaryop(self, node, var_dict, handle_subscript_func,
                        handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle unary operations"""
        if isinstance(node.op, ast.Not):
            operand = self._convert_node(
                node.operand, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )
            if operand is not None and Z3_AVAILABLE:
                try:
                    if hasattr(operand, "sort") and operand.sort() != BoolSort():
                        operand = operand != 0
                except Exception:
                    pass
                return Not(operand)
            return None
        return None

    def _handle_compare(self, node, var_dict, handle_subscript_func,
                        handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle comparison operations"""
        left = self._convert_node(
            node.left, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )
        if left is None:
            return None

        op = node.ops[0]
        right_node = node.comparators[0]

        if isinstance(op, (ast.In, ast.NotIn)) and handle_in_notin_func:
            return handle_in_notin_func(left, op, right_node, var_dict)

        right = self._convert_node(
            right_node, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )
        if right is None:
            return None

        return self.mapper.get_cmp_func(op)(left, right)

    def _handle_binop(self, node, var_dict, handle_subscript_func,
                      handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle binary operations"""
        left = self._convert_node(
            node.left, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )
        right = self._convert_node(
            node.right, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )
        if left is None or right is None:
            return None
        return self.mapper.get_binop_func(node.op)(left, right)

    def _handle_subscript(self, node, var_dict, handle_subscript_func,
                          handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle subscript operations"""
        if not handle_subscript_func:
            return None

        value = self._convert_node(
            node.value, var_dict, handle_subscript_func,
            handle_in_notin_func, z3_min_list_func, z3_max_list_func
        )
        if value is None:
            return None

        # Handle different slice types
        if isinstance(node.slice, ast.Slice):
            return value  # Simplified handling
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
            idx = self._convert_node(
                node.slice, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )
            return handle_subscript_func(value, idx, var_dict) if idx else None

    def _handle_call(self, node, var_dict, handle_subscript_func,
                     handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle function calls"""
        if not isinstance(node.func, ast.Name):
            return None

        func_name = node.func.id

        if func_name == "int":
            if node.args:
                return self._convert_node(
                    node.args[0], var_dict, handle_subscript_func,
                    handle_in_notin_func, z3_min_list_func, z3_max_list_func
                )
            return IntVal(0)

        if func_name == "len":
            # Simplified length handling - assume known length
            return IntVal(3)  # Default length for symbolic lists

        if func_name in ["min", "max"]:
            args_z3 = []
            for arg in node.args:
                converted = self._convert_node(
                    arg, var_dict, handle_subscript_func,
                    handle_in_notin_func, z3_min_list_func, z3_max_list_func
                )
                if converted is not None:
                    args_z3.append(converted)

            if not args_z3:
                return None

            if len(args_z3) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                # min([a,b,c]) or max([a,b,c])
                elts = node.args[0].elts
                elts_z3 = []
                for e in elts:
                    converted = self._convert_node(
                        e, var_dict, handle_subscript_func,
                        handle_in_notin_func, z3_min_list_func, z3_max_list_func
                    )
                    if converted is not None:
                        elts_z3.append(converted)

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

    def _handle_name(self, node, var_dict):
        """Handle variable names"""
        if node.id not in var_dict:
            var_dict[node.id] = Int(node.id)
        return var_dict[node.id]

    def _handle_constant(self, node):
        """Handle constant values"""
        v = node.value
        if isinstance(v, bool):
            return BoolVal(v)
        if isinstance(v, int):
            return IntVal(v)
        if v is None:
            return BoolVal(False)
        return None

    def _handle_sequence(self, node, var_dict, handle_subscript_func,
                        handle_in_notin_func, z3_min_list_func, z3_max_list_func):
        """Handle tuple and list nodes"""
        result = []
        for elt in node.elts:
            converted = self._convert_node(
                elt, var_dict, handle_subscript_func,
                handle_in_notin_func, z3_min_list_func, z3_max_list_func
            )
            result.append(converted)
        return result


# Legacy function wrapper
def enhanced_ast_to_z3(
    node,
    var_dict,
    handle_subscript_func=None,
    handle_in_notin_func=None,
    z3_min_list_func=None,
    z3_max_list_func=None,
):
    """Enhanced AST to Z3 conversion with support for more node types"""
    converter = EnhancedASTConverter()
    return converter.convert(
        node, var_dict, handle_subscript_func,
        handle_in_notin_func, z3_min_list_func, z3_max_list_func
    )


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


class SimpleASTToZ3Converter:
    """Simplified AST to Z3 converter for basic expressions"""

    def __init__(self):
        self.mapper = Z3OperatorMapper()

    def convert(self, expr: ast.AST, var_dict: Optional[Dict[str, Any]] = None) -> Any:
        """Convert an AST expression to a Z3 expression"""
        if not Z3_AVAILABLE:
            return None

        if var_dict is None:
            var_dict = {}

        try:
            return self._convert_recursive(expr, var_dict)
        except Exception:
            return None

    def _convert_recursive(self, expr: ast.AST, var_dict: Dict[str, Any]) -> Any:
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
            return self._handle_constant(expr)

        # Variable names
        if isinstance(expr, ast.Name):
            return self._handle_name(expr, var_dict)

        # Binary operations
        if isinstance(expr, ast.BinOp):
            return self._handle_binop(expr, var_dict)

        # Unary operations
        if isinstance(expr, ast.UnaryOp):
            return self._handle_unaryop(expr, var_dict)

        # Comparisons
        if isinstance(expr, ast.Compare):
            return self._handle_compare(expr, var_dict)

        # Boolean operations
        if isinstance(expr, ast.BoolOp):
            return self._handle_boolop(expr, var_dict)

        return None

    def _handle_constant(self, expr):
        """Handle constant values"""
        if isinstance(expr.value, int):
            return IntVal(expr.value)
        elif isinstance(expr.value, float):
            return RealVal(expr.value)
        elif isinstance(expr.value, bool):
            return BoolVal(expr.value)
        return None

    def _handle_name(self, expr, var_dict):
        """Handle variable names"""
        if expr.id not in var_dict:
            var_dict[expr.id] = create_z3_variable(expr.id)
        return var_dict[expr.id]

    def _handle_binop(self, expr, var_dict):
        """Handle binary operations"""
        left = self._convert_recursive(expr.left, var_dict)
        right = self._convert_recursive(expr.right, var_dict)
        if left is None or right is None:
            return None

        func = self.mapper.get_binop_func(expr.op)
        return func(left, right)

    def _handle_unaryop(self, expr, var_dict):
        """Handle unary operations"""
        operand = self._convert_recursive(expr.operand, var_dict)
        if operand is None:
            return None

        func = self.mapper.get_unaryop_func(expr.op)
        return func(operand)

    def _handle_compare(self, expr, var_dict):
        """Handle comparison operations"""
        if len(expr.ops) == 1 and len(expr.comparators) == 1:
            left = self._convert_recursive(expr.left, var_dict)
            right = self._convert_recursive(expr.comparators[0], var_dict)
            if left is None or right is None:
                return None

            func = self.mapper.get_cmp_func(expr.ops[0])
            return func(left, right)
        else:
            # Handle chained comparisons
            constraints = []
            current = expr.left

            for op, comparator in zip(expr.ops, expr.comparators):
                left = self._convert_recursive(current, var_dict)
                right = self._convert_recursive(comparator, var_dict)
                if left is None or right is None:
                    return None

                func = self.mapper.get_cmp_func(op)
                constraints.append(func(left, right))
                current = comparator

            return And(*constraints) if len(constraints) > 1 else constraints[0]

    def _handle_boolop(self, expr, var_dict):
        """Handle boolean operations"""
        values = []
        for value in expr.values:
            z3_value = self._convert_recursive(value, var_dict)
            if z3_value is None:
                return None
            values.append(z3_value)

        func = self.mapper.get_boolop_func(expr.op)
        return func(*values)


def ast_to_z3_expr(expr: ast.AST, var_dict: Optional[Dict[str, Any]] = None) -> Any:
    """
    Convert an AST expression to a Z3 expression.

    Args:
        expr: AST node to convert
        var_dict: Dictionary mapping variable names to Z3 variables

    Returns:
        Z3 expression or None if conversion fails
    """
    converter = SimpleASTToZ3Converter()
    return converter.convert(expr, var_dict)


def _ast_to_z3_recursive(expr: ast.AST, var_dict: Dict[str, Any]) -> Any:
    """Recursive helper for AST to Z3 conversion"""
    converter = SimpleASTToZ3Converter()
    return converter._convert_recursive(expr, var_dict)


class RangeConstraintGenerator:
    """Generates Z3 constraints for range loop iterations"""

    @staticmethod
    def generate_constraint(k: int, start, stop, step=None,
                           var_dict: Optional[Dict[str, Any]] = None):
        """Generate Z3 constraint for the k-th iteration of a range loop"""
        if not Z3_AVAILABLE:
            return None

        if var_dict is None:
            var_dict = {}

        # Convert to Z3 expressions
        start_expr = RangeConstraintGenerator._to_z3_expr(start, var_dict)
        stop_expr = RangeConstraintGenerator._to_z3_expr(stop, var_dict)
        step_expr = RangeConstraintGenerator._to_z3_expr(
            step if step is not None else 1, var_dict
        )

        if None in [start_expr, stop_expr, step_expr]:
            return None

        # Calculate iteration value: start + k * step
        try:
            if start_expr is None or step_expr is None:
                return None
            iter_val = start_expr + IntVal(k) * step_expr
        except Exception:
            return None

        # Determine step direction for constraint generation
        step_const = Z3SafeOperations.extract_constant_value(step_expr)

        constraints = []
        try:
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
            if not Z3SafeOperations.is_sat(final_constraint):
                return None

            return final_constraint
        except Exception:
            return None

    @staticmethod
    def _to_z3_expr(expr, var_dict: Optional[Dict[str, Any]] = None):
        """Convert various expression types to Z3 expressions"""
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


# Legacy function wrappers
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
    return RangeConstraintGenerator.generate_constraint(k, start, stop, step, var_dict)


def to_z3_expr(expr, var_dict: Optional[Dict[str, Any]] = None):
    """
    Convert various expression types to Z3 expressions.

    Handles: int, float, bool, str, AST nodes, Z3 expressions
    """
    return RangeConstraintGenerator._to_z3_expr(expr, var_dict)


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


class PathSatisfiabilityChecker:
    """Checks satisfiability of path conditions"""

    def __init__(self):
        self.parser = ExpressionParser()

    def check_satisfiability(self, conditions: List[str],
                           var_dict: Optional[Dict[str, Any]] = None
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

        try:
            solver = Solver()
            program_variables = set(var_dict.keys())

            for condition_str in conditions:
                try:
                    constraint = self._parse_condition_string(
                        condition_str, var_dict, program_variables
                    )
                    if constraint is not None:
                        solver.add(constraint)
                except Exception:
                    continue  # Skip unparseable conditions

            result = solver.check()
            if result == sat:
                model = solver.model()
                model_values = self._extract_model_values(model, var_dict, program_variables)
                return True, model_values
            else:
                return False, None
        except Exception:
            return True, None

    def _extract_model_values(self, model, var_dict, program_variables):
        """Extract model values for program variables"""
        model_values = {}
        for var_name in program_variables:
            if var_name in var_dict and model[var_dict[var_name]] is not None:
                z3_value = model[var_dict[var_name]]
                # Convert Z3 value to Python value
                try:
                    if (hasattr(z3, 'is_int_value') and z3 is not None and
                        z3.is_int_value(z3_value)):
                        model_values[var_name] = str(z3_value.as_long())
                    elif (hasattr(z3, 'is_real_value') and z3 is not None and
                          z3.is_real_value(z3_value)):
                        model_values[var_name] = str(float(z3_value.as_fraction()))
                    elif (hasattr(z3, 'is_bool') and z3 is not None and
                          z3.is_bool(z3_value)):
                        model_values[var_name] = str(z3.is_true(z3_value)).lower()
                    else:
                        model_values[var_name] = str(z3_value)
                except Exception:
                    model_values[var_name] = str(z3_value)
        return model_values

    def _parse_condition_string(self, condition: str, var_dict: Dict[str, Any],
                               program_variables: set) -> Optional[Any]:
        """Parse a condition string into a Z3 constraint"""
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

        # Convert to Z3 expressions
        left_value = self._parse_value(left_str, var_dict, program_variables)
        right_value = self._parse_value(right_str, var_dict, program_variables)

        if left_value is None or right_value is None:
            return None

        # Create constraint
        constraint = self.parser._create_comparison(left_value, op, right_value)
        return Not(constraint) if negated else constraint

    def _parse_value(self, value_str: str, var_dict: Dict[str, Any],
                    program_variables: set):
        """Parse a value string to Z3 expression"""
        # Try to parse as constant first
        try:
            return IntVal(int(value_str))
        except ValueError:
            pass

        try:
            return RealVal(float(value_str))
        except ValueError:
            pass

        if value_str.lower() in ["true", "false"]:
            return BoolVal(value_str.lower() == "true")

        # It's a variable
        if value_str not in var_dict:
            var_dict[value_str] = create_z3_variable(value_str)
            program_variables.add(value_str)
        return var_dict[value_str]


# Legacy function wrappers
def check_path_satisfiability(
    conditions: List[str], var_dict: Optional[Dict[str, Any]] = None
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check if a list of path conditions is satisfiable.

    Returns:
        Tuple of (is_satisfiable, model_values)
    """
    checker = PathSatisfiabilityChecker()
    return checker.check_satisfiability(conditions, var_dict)


def parse_condition_string(
    condition: str, var_dict: Dict[str, Any], program_variables: set
) -> Optional[Any]:
    """
    Parse a condition string into a Z3 constraint.

    Handles simple conditions like "x > 5", "y == 10", "5 < x", etc.
    """
    checker = PathSatisfiabilityChecker()
    return checker._parse_condition_string(condition, var_dict, program_variables)


def parse_operands(operands_str: str) -> List[Any]:
    """Parse operands from string like "('name', 'x') 0" """
    parser = ExpressionParser()
    return parser._parse_operands(operands_str)


def operand_to_z3(operand: Any, var_map: Dict[str, Any]) -> Any:
    """Convert an operand (which could be ('name', 'x') or a constant) to Z3"""
    parser = ExpressionParser()
    return parser._operand_to_z3(operand, var_map)
