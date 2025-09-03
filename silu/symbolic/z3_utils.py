#!/usr/bin/env python3
"""
Z3 Utilities for Symbolic Execution

This module provides utilities for converting AST nodes to Z3 expressions,
handling constraints, and performing satisfiability checking.
"""

import re
import ast
import sys
from typing import Any, Dict, List, Optional, Set, Union
from loguru import logger

# Z3 availability check
try:
    import z3
    from z3 import (
        Solver,
        sat,
        And,
        Or,
        Not,
        IntVal,
        BoolVal,
        RealVal,
        Int,
        Real,
        Bool,
        simplify,
        BoolRef,
        ArithRef,
        # If,
        # BoolSort,
        # ToReal,
    )

    Z3_AVAILABLE = True
except ImportError as e:
    raise ImportError(f"Z3 is not available: {e}")
    Z3_AVAILABLE = False

# print(f'Z3_AVAILABLE: {Z3_AVAILABLE}')

# Operator mappings from AST to Z3 (only available when Z3 is imported)
if Z3_AVAILABLE:
    BOOLOP_MAP = {ast.And: And, ast.Or: Or}
else:
    BOOLOP_MAP = {}

if Z3_AVAILABLE:
    BINOP_MAP = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
        ast.Mod: lambda left, right: left % right,
        ast.Pow: lambda left, right: left**right,
    }
else:
    BINOP_MAP = {}

if Z3_AVAILABLE:
    CMP_MAP = {
        ast.Eq: lambda left, right: left == right,
        ast.NotEq: lambda left, right: left != right,
        ast.Lt: lambda left, right: left < right,
        ast.LtE: lambda left, right: left <= right,
        ast.Gt: lambda left, right: left > right,
        ast.GtE: lambda left, right: left >= right,
    }
else:
    CMP_MAP = {}

if Z3_AVAILABLE:
    UNARYOP_MAP = {
        ast.UAdd: lambda x: x,
        ast.USub: lambda x: -x,
        ast.Not: lambda x: Not(x),
    }
else:
    UNARYOP_MAP = {}


logger.remove()  # 移除默认的 handler
logger.add(
    sink=sys.stderr,  # 或 sys.stdout
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{file.path}</cyan>:<cyan>{line}</cyan>:<cyan>{function}</cyan>: - "
        "<level>{message}</level>"
    ),
    colorize=True,
)


def to_z3_expr(expr, var_dict: Optional[Dict[str, Any]] = None):
    """
    Convert various expression types to Z3 expressions.

    Handles: int, float, bool, str, AST nodes, Z3 expressions
    """
    return RangeConstraintGenerator._to_z3_expr(expr, var_dict)


class RangeConstraintGenerator:
    """Generates Z3 constraints for range loop iterations"""

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

        # TODO: support AST nodes
        # if isinstance(expr, ast.AST):
        #     return ast_to_z3_expr(expr, var_dict)

        logger.warning(f"Unsupported expression type:\n {type(expr)}: {expr}")
        return None

    # TODO: check if the constraint is valid
    @staticmethod
    def generate_constraint(
        k: int, start, stop, step=None, var_dict: Optional[Dict[str, Any]] = None
    ):
        """Generate Z3 constraint for the k-th iteration of a range loop"""
        if not Z3_AVAILABLE:
            return None

        if var_dict is None:
            var_dict = {}

        # Convert to Z3 expressions
        # logger.info(f'start: {start} stop: {stop} step: {step}')
        # start_expr = stop_expr = step_expr = None
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


def create_z3_variable(name: str, var_type: str = "int"):
    """Create a Z3 variable of the specified type"""
    return Z3SafeOperations.create_z3_variable(name, var_type)


def extract_constant_value(z3_expr) -> Optional[Union[int, float, bool]]:
    """Extract constant value from Z3 expression if possible"""
    return Z3SafeOperations.extract_constant_value(z3_expr)


class Z3SafeOperations:
    """Safe wrapper for Z3 operations that handles unavailability"""

    @staticmethod
    def create_z3_variable(name: str, var_type: str = "int"):
        """Create a Z3 variable of the specified type"""
        if not Z3_AVAILABLE:
            return name  # Return name if Z3 not available
        var_type = var_type.lower()
        if var_type == "int":
            return Int(name)
        elif var_type == "real":
            return Real(name)
        elif var_type == "bool":
            return Bool(name)
        else:
            return Int(name)  # Default to int

    # TODO: check
    @staticmethod
    def extract_constant_value(z3_expr) -> Optional[Union[int, float, bool]]:
        """Extract constant value from Z3 expression if possible"""
        if not Z3_AVAILABLE or z3_expr is None:
            return None

        try:
            if (
                hasattr(z3, "is_int_value")
                and z3 is not None
                and z3.is_int_value(z3_expr)
            ):
                return z3_expr.as_long()
            elif (
                hasattr(z3, "is_rational_value")
                and z3 is not None
                and z3.is_rational_value(z3_expr)
            ):
                return float(z3_expr.as_decimal(10))
            elif hasattr(z3, "is_bool") and z3 is not None and z3.is_bool(z3_expr):
                return z3.is_true(z3_expr)
        except Exception:
            pass

        return None

    # @staticmethod
    # def is_sat(constraint) -> bool:
    #     """Check if a Z3 constraint is satisfiable"""
    #     if not Z3_AVAILABLE or constraint is None:
    #         return True  # Default to satisfiable if Z3 not available

    #     try:
    #         solver = Solver()
    #         solver.add(constraint)
    #         return solver.check() == sat
    #     except Exception:
    #         return True

    # @staticmethod
    # def create_solver_with_constraints(constraints: List[Any]) -> Optional[Any]:
    #     """Create a Z3 solver with the given constraints"""
    #     if not Z3_AVAILABLE or not constraints:
    #         return None

    #     try:
    #         solver = Solver()
    #         for constraint in constraints:
    #             if constraint is not None:
    #                 solver.add(constraint)
    #         return solver
    #     except Exception:
    #         return None


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


def is_bool(expr):
    """Check if a Z3 expression is boolean type"""
    if expr is None:
        return False
    try:
        return expr.sort() == BoolSort()
    except:
        return isinstance(expr, bool)

def to_bool(expr):
    """Convert an expression to Z3 boolean if possible"""
    if expr is None:
        return None
    if is_bool(expr):
        return expr
    if isinstance(expr, int):
        return BoolVal(expr != 0)
    try:
        # Try to convert Z3 Int to Bool
        return expr != 0
    except:
        # Fall back to Python bool conversion
        try:
            return BoolVal(bool(expr))
        except:
            return None

class PathSatisfiabilityChecker:
    """Checker for path satisfiability using Z3"""

    def __init__(self):
        self.parser = ExpressionParser()

    def check_satisfiability(
        self, conditions: List[str], var_dict: Optional[Dict[str, Any]] = None
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

        # try:
        if 1:
            solver = Solver()
            program_variables = set(var_dict.keys())
            # logger.debug(f"program_variables: {program_variables}")

            for condition_str in conditions:
                # try:
                if 1:
                    # constraint = self._parse_condition_string(
                    #     condition_str, var_dict, program_variables
                    # )
                    logger.warning(f"condition_str: {condition_str}")
                    logger.warning(f"var_dict: {var_dict}")
                    constraint = to_z3_expr_new(condition_str, var_dict)

                    # Ensure constraint is boolean before adding to solver
                    if constraint is not None:
                        logger.debug(f"Adding constraint: {constraint} {type(constraint)}")
                        # TODO
                        # bool_constraint = to_bool(constraint)
                        # if bool_constraint is not None:
                            # solver.add(bool_constraint)

                        # Convert integer expressions to boolean comparisons when needed
                        if z3 is not None and hasattr(z3, "is_expr") and z3.is_expr(constraint):
                            # Check if this is a pure integer expression used in boolean context
                            if z3.is_int(constraint) or z3.is_real(constraint):
                                # Convert to boolean comparison (non-zero = True)
                                constraint = constraint != 0
                        else:
                            logger.debug(f"Constraint is not a Z3 expression: {constraint}")
                            raise ValueError(f"Constraint is not a Z3 expression: {constraint}")

                        solver.add(constraint)
                    else:
                        logger.debug(f"Constraint is not a Z3 expression: {constraint}")
                        raise ValueError(f"Constraint is not a Z3 expression: {constraint}")

                # except Exception as e:
                #     logger.error(f"Error adding constraint for '{condition_str}': {e}")
                #     raise ValueError(f"Error adding constraint for '{condition_str}': {e}")
                    # Skip problematic constraints to allow execution to continue

            result = solver.check()
            if result == sat:
                model = solver.model()
                model_values = self._extract_model_values(
                    model, var_dict, program_variables
                )
                return True, model_values
            else:
                return False, None
        # except Exception as e:
        #     logger.error(f"Error checking satisfiability: {e}")
        #     return True, None

    def _parse_condition_string(
        self, condition: str, var_dict: dict, program_variables: set
    ) -> Optional[Any]:
        condition = condition.strip()
        # logger.debug(f"condition: {condition} var_dict: {var_dict} program_variables: {program_variables} raw")

        if condition.startswith("not "):
            inner = condition[4:].strip()
            # 对于其他情况，递归解析内部表达式
            try:
                inner_expr = self._parse_condition_string(inner, var_dict, program_variables)
                return Not(inner_expr)
            except Exception as e:
                logger.error(f"Error parsing negated condition '{inner}': {e}")
                # 如果解析失败，尝试基本处理
                if inner not in var_dict:
                    var_dict[inner] = Bool(inner)
                return Not(var_dict[inner])

        # 移除外层括号
        while condition.startswith("(") and condition.endswith(")"):
            condition = condition[1:-1].strip()

        # 处理 or
        depth = 0
        for i, c in enumerate(condition):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif depth == 0 and condition[i : i + 4] == " or ":
                left = condition[:i].strip()
                right = condition[i + 4 :].strip()
                return Or(
                    self._parse_condition_string(left, var_dict, program_variables),
                    self._parse_condition_string(right, var_dict, program_variables),
                )

        # 处理 and
        depth = 0
        for i, c in enumerate(condition):
            # logger.debug(f"i: {i}; c: {c} == {condition[i:i+3]}")
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif depth == 0 and condition[i : i + 3] == "and":
                left = condition[:i].strip()
                right = condition[i + 3 :].strip()
                # logger.debug(f"left: {left}; right: {right}")
                left_result = self._parse_condition_string(left, var_dict, program_variables)
                right_result = self._parse_condition_string(right, var_dict, program_variables)
                return And(
                    left_result,
                    right_result,
                )


        # logger.debug(f"program_variables: {program_variables} raw2")
        # 单个比较
        # logger.debug(f"condition: {condition}  repr:{repr(condition)}")
        pattern = r"(\w+)\s*([%><=!]+)\s*(.+)"
        match = re.match(pattern, condition)
        if match:
            left_str, op, right_str = match.groups()
            left_value = var_dict.get(left_str, None)
            right_value = var_dict.get(right_str, None)
            # logger.debug(f"left_str: {left_str}; right_str: {right_str} op: {op}")
            # logger.debug(f"!! var_dict: {var_dict} left_value: {left_value} right_value: {right_value}")
            # if left_value is None:
            #     left_value = Real(left_str) if left_str in program_variables else None
            #     logger.debug(f"left_value: {left_value} ~~~~")
            # if right_value is None:
            #     right_value = Real(right_str) if right_str in program_variables else None
            #     logger.debug(f"right_value: {right_value} ~~~~")

            left_value = self._parse_value(left_str, var_dict, program_variables)
            right_value = self._parse_value(right_str, var_dict, program_variables)

            if left_value is None or right_value is None:
                return None

            # logger.debug(f"left_str: {left_str}; right_str: {right_str} op: {op}")
            return self.parser._create_comparison(left_value, op, right_value)

        elif condition.lower() in "true false".split():
            # Handle "true" and "false" literals
            one_value = self._parse_value(condition, var_dict, program_variables)
            return one_value
        elif condition.count(' ')==0:
            one_value = self._parse_bool(condition, var_dict, program_variables)
            return one_value
        else:
            # For any other condition, treat it as a basic comparison or variable
            raise ValueError(f"Invalid condition: {condition} {type(condition)}")

            # try:
            #     # Try to handle it as a comparison condition
            #     for op in self.parser.comparison_ops:
            #         if op in condition:
            #             parts = condition.split(op, 1)
            #             if len(parts) == 2:
            #                 left_str, right_str = parts[0].strip(), parts[1].strip()
            #                 left_value = self._parse_value(left_str, var_dict, program_variables)
            #                 right_value = self._parse_value(right_str, var_dict, program_variables)
            #                 if left_value is not None and right_value is not None:
            #                     # Create boolean comparison
            #                     result = self.parser._create_comparison(left_value, op, right_value)
            #                     # logger.debug(f"Created comparison: {left_str} {op} {right_str} = {result}")
            #                     return result

            #     # If not a comparison, try to use it directly as a value
            #     return self._parse_value(condition, var_dict, program_variables)
            # except Exception as e:
            #     logger.error(f"Error parsing complex condition '{condition}': {e}")
            #     # Return None to skip this condition rather than failing
            #     return None


    def _extract_model_values(self, model, var_dict, program_variables):
        """Extract model values for program variables"""
        model_values = {}
        for var_name in program_variables:
            if var_name in var_dict and model[var_dict[var_name]] is not None:
                z3_value = model[var_dict[var_name]]
                # Convert Z3 value to Python value
                try:
                    if (
                        hasattr(z3, "is_int_value")
                        and z3 is not None
                        and z3.is_int_value(z3_value)  # IntNumRef
                    ):
                        model_values[var_name] = z3_value.as_long()
                    elif isinstance(z3_value, z3.RatNumRef):
                        num = z3_value.numerator_as_long()
                        den = z3_value.denominator_as_long()
                        if den == 0:  # 表示无穷大
                            return float("inf") if num > 0 else float("-inf")
                        elif den == 1:  # 表示整数
                            model_values[var_name] = num
                        else:
                            # 转换为浮点 same as? float(z3_value.as_fraction())
                            model_values[var_name] = num / den
                    elif (
                        hasattr(z3, "is_bool")
                        and z3 is not None
                        and z3.is_bool(z3_value)
                    ):
                        # raise ValueError("Error parsing Z3 value is_bool")
                        # str(z3.is_true(z3_value)).lower()
                        model_values[var_name] = z3.is_true(z3_value)
                    else:
                        logger.error(
                            f"Error var_name {var_name} z3_value: {z3_value} {type(z3_value)}"
                        )
                        raise ValueError("Error parsing Z3 value others")
                        model_values[var_name] = str(z3_value)
                except Exception as e:
                    logger.error(f"Error parsing Z3 value: {e}")
                    raise ValueError(f"Error parsing Z3 value: {e}")
                    model_values[var_name] = str(z3_value)
        return model_values

    def _parse_value(
        self, value_str: str, var_dict: Dict[str, Any], program_variables: set
    ):
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
            logger.trace(f"Variable '{value_str}' not found in {var_dict}")
            var_dict[value_str] = create_z3_variable(value_str)
            program_variables.add(value_str)

        return var_dict[value_str]

    def _parse_bool(
        self, value_str: str, var_dict: Dict[str, Any], program_variables: set
    ):
        assert value_str.count(" ")==0
        if value_str not in var_dict:
            logger.trace(f"Variable '{value_str}' not found in {var_dict}")
            var_dict[value_str] = create_z3_variable(value_str, "bool")
            program_variables.add(value_str)
            return var_dict[value_str]

        # raise ValueError(f"!!!Variable '{value_str}' already exists in {var_dict} {var_dict[value_str]}, {type(var_dict[value_str])}")
        assert value_str in program_variables
        return Not(Not((var_dict[value_str] != 0)))

        # 检查是否是布尔字面量
        if value_str.lower() == "true":
            return BoolVal(True)
        elif value_str.lower() == "false":
            return BoolVal(False)
        # 检查是否是程序变量
        elif value_str in program_variables:
            if value_str not in var_dict:
                var_dict[value_str] = Bool(value_str)
            # raise ValueError(f"Invalid boolean value: {value_str} {var_dict[value_str]} {type(var_dict[value_str])}")
            return var_dict[value_str]
        # 其他情况
        else:
            raise ValueError(f"Invalid boolean value: {value_str}")

class ExpressionParser:
    """Helper class to parse expressions into Z3 constraints"""

    def __init__(self):
        self.comparison_ops = [">=", "<=", "==", "!=", ">", "<"]

    def _create_comparison(self, left, op: str, right):
        """Create Z3 comparison constraint"""
        if op == "<":
            return left < right
        elif op == "<=":
            return left <= right
        elif op == ">":
            return left > right
        elif op == ">=":
            return left >= right
        if op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op == "%":
            return left % right
        return None

    # def _parse_basic_comparison(
    #     self, expr: str, var_map: Dict[str, Any]
    # ) -> Optional[Any]:
    #     """Parse basic comparison operations like 'x > 5'"""
    #     if not Z3_AVAILABLE:
    #         return None

    #     # Find comparison operator
    #     for op in self.comparison_ops:
    #         if op in expr and not expr.startswith(op):
    #             parts = expr.split(op, 1)
    #             if len(parts) == 2:
    #                 left = parts[0].strip()
    #                 right = parts[1].strip()

    #                 # 确保变量在 var_map 中
    #                 if (
    #                     left not in var_map
    #                     and not left.isdigit()
    #                     and left not in {"True", "False", "None"}
    #                 ):
    #                     var_map[left] = Int(left)

    #                 if (
    #                     right not in var_map
    #                     and not right.isdigit()
    #                     and right not in {"True", "False", "None"}
    #                 ):
    #                     var_map[right] = Int(right)

    #                 left_z3 = self._expr_to_z3_simple(left, var_map)
    #                 right_z3 = self._expr_to_z3_simple(right, var_map)

    #                 if left_z3 is not None and right_z3 is not None:
    #                     return self._create_comparison(left_z3, op, right_z3)

    #     return None

    # def _expr_to_z3_simple(self, expr: str, var_map: Dict[str, Any]) -> Any:
    #     """Convert simple expression to Z3"""
    #     if not Z3_AVAILABLE:
    #         return None

    #     expr = expr.strip()

    #     # Try integer
    #     try:
    #         return IntVal(int(expr))
    #     except ValueError:
    #         pass

    #     # Try float
    #     try:
    #         return RealVal(float(expr))
    #     except ValueError:
    #         pass

    #     # Try boolean
    #     if expr.lower() in ["true", "false"]:
    #         return BoolVal(expr.lower() == "true")

    #     # Treat as variable
    #     if expr not in var_map:
    #         var_map[expr] = Int(expr)
    #     return var_map[expr]

    # def parse_operand_format(self, expr: str, var_map: Dict[str, Any]) -> Optional[Any]:
    #     """Parse expressions in format '> ('name', 'x') 0'"""
    #     if not Z3_AVAILABLE:
    #         return None

    #     # Pattern for "OPERATOR ('name', 'var') VALUE" or "OPERATOR VALUE VALUE"
    #     pattern = r"^([><=!]+)\s+(.+)$"
    #     match = re.match(pattern, expr)

    #     if match:
    #         op = match.group(1)
    #         operands_part = match.group(2)

    #         operands = self._parse_operands(operands_part)
    #         if len(operands) == 2:
    #             left_z3 = self._operand_to_z3(operands[0], var_map)
    #             right_z3 = self._operand_to_z3(operands[1], var_map)

    #             if left_z3 is not None and right_z3 is not None:
    #                 return self._create_comparison(left_z3, op, right_z3)

    #     return None

    # def _parse_operands(self, operands_str: str) -> List[Any]:
    #     """Parse operands from string"""
    #     operands = []

    #     # Handle tuple operand followed by simple operand
    #     match = re.match(r"\(([^)]+)\)\s+(.+)$", operands_str.strip())
    #     if match:
    #         tuple_content = match.group(1)
    #         second_operand = match.group(2)

    #         try:
    #             # Parse the tuple content
    #             tuple_parts = [
    #                 part.strip().strip("'\"") for part in tuple_content.split(",")
    #             ]
    #             if len(tuple_parts) == 2:
    #                 operands.append(tuple(tuple_parts))

    #                 # Parse second operand
    #                 try:
    #                     operands.append(int(second_operand))
    #                 except ValueError:
    #                     try:
    #                         operands.append(float(second_operand))
    #                     except ValueError:
    #                         operands.append(second_operand)

    #                 return operands
    #         except Exception:
    #             pass

    #     # Fallback parsing
    #     parts = operands_str.split()
    #     for part in parts:
    #         try:
    #             operands.append(int(part))
    #         except ValueError:
    #             try:
    #                 operands.append(float(part))
    #             except ValueError:
    #                 if part.startswith("(") and part.endswith(")"):
    #                     try:
    #                         operands.append(ast.literal_eval(part))
    #                     except Exception:
    #                         operands.append(part)
    #                 else:
    #                     operands.append(part)

    #     return operands

    # def _operand_to_z3(self, operand: Any, var_map: Dict[str, Any]) -> Any:
    #     """Convert operand to Z3 expression"""
    #     if not Z3_AVAILABLE:
    #         return None

    #     # Handle tuple format like ('name', 'x')
    #     if isinstance(operand, tuple) and len(operand) == 2:
    #         if operand[0] == "name":
    #             var_name = operand[1]
    #             if var_name not in var_map:
    #                 var_map[var_name] = Int(var_name)
    #             return var_map[var_name]

    #     # Handle constants
    #     if isinstance(operand, int):
    #         return IntVal(operand)
    #     elif isinstance(operand, float):
    #         return RealVal(operand)
    #     elif isinstance(operand, str):
    #         return self._expr_to_z3_simple(operand, var_map)

    #     return None


def to_z3_expr_new(expr_str, env):
    node = ast.parse(expr_str, mode="eval").body

    def convert(n, bool_context=False):
        if isinstance(n, ast.BinOp):
            left = convert(n.left)
            right = convert(n.right)
            if isinstance(n.op, ast.Add): return left + right
            if isinstance(n.op, ast.Sub): return left - right
            if isinstance(n.op, ast.Mult): return left * right
            if isinstance(n.op, ast.Div): return left / right
        elif isinstance(n, ast.Compare):
            left = convert(n.left)
            right = convert(n.comparators[0])
            op = n.ops[0]

            # 如果都是 Python 常量，直接返回 BoolVal
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if isinstance(op, ast.Lt): return BoolVal(left < right)
                if isinstance(op, ast.LtE): return BoolVal(left <= right)
                if isinstance(op, ast.Gt): return BoolVal(left > right)
                if isinstance(op, ast.GtE): return BoolVal(left >= right)
                if isinstance(op, ast.Eq): return BoolVal(left == right)
                if isinstance(op, ast.NotEq): return BoolVal(left != right)

            # BoolRef 与 0/1 比较特殊处理
            if isinstance(left, BoolRef) and isinstance(right, int):
                if isinstance(op, ast.Lt):
                    return left == False if right == 1 else NotImplemented
                if isinstance(op, ast.LtE):
                    if right == 0: return left == False
                    if right == 1: return True
                if isinstance(op, ast.Gt):
                    return left == True if right == 0 else False
                if isinstance(op, ast.GtE):
                    if right == 0: return True
                    if right == 1: return left == True
                if isinstance(op, ast.Eq): return left == bool(right)
                if isinstance(op, ast.NotEq): return left != bool(right)

            # 普通比较
            if isinstance(op, ast.Lt): return left < right
            if isinstance(op, ast.LtE): return left <= right
            if isinstance(op, ast.Gt): return left > right
            if isinstance(op, ast.GtE): return left >= right
            if isinstance(op, ast.Eq): return left == right
            if isinstance(op, ast.NotEq): return left != right

        elif isinstance(n, ast.BoolOp):
            values = [convert(v, bool_context=True) for v in n.values]
            if isinstance(n.op, ast.And): return And(*values)
            if isinstance(n.op, ast.Or): return Or(*values)
        elif isinstance(n, ast.UnaryOp):
            if isinstance(n.op, ast.Not):
                inner = convert(n.operand, bool_context=True)
                if isinstance(inner, ArithRef):
                    return inner == 0
                return Not(inner)
            if isinstance(n.op, ast.USub): return -convert(n.operand)
            if isinstance(n.op, ast.UAdd): return convert(n.operand)
        elif isinstance(n, ast.Name):
            v = env[n.id]
            if bool_context and isinstance(v, ArithRef):
                return v != 0
            return v
        elif isinstance(n, ast.Constant):
            return n.value
        else:
            raise NotImplementedError(f"Unsupported node: {ast.dump(n)}")

    r = convert(node)
    logger.debug(f"Converted node: {node} to {r} {type(r)}")
    return r
