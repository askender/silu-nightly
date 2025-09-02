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


class PathSatisfiabilityChecker:
    """Checks satisfiability of path conditions"""

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
                if 1:
                    # try:
                    constraint = self._parse_condition_string(
                        condition_str, var_dict, program_variables
                    )
                    # logger.debug(f"Adding constraint: {constraint}")
                    # 保存原始条件字符串，用于生成测试输入
                    if "_condition_strings" not in var_dict:
                        var_dict["_condition_strings"] = []
                    var_dict["_condition_strings"].append(condition_str)

                    if constraint is not None:
                        # 确保约束是布尔值类型
                        try:
                            if z3.is_bool(constraint):
                                solver.add(constraint)
                            else:
                                # 非布尔值转换为布尔表达式（与0比较）
                                solver.add(constraint != 0)
                        except Exception as e:
                            logger.warning(f"Skipping invalid constraint '{constraint}': {e}")
                    else:
                        logger.debug(f"Skipping None constraint for condition: {condition_str}")
                # except Exception as e:
                #     logger.error(f"Error parsing condition '{condition_str}': {e}")
                #     continue  # Skip unparseable conditions

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

    def _parse_condition_string_bad(
        self, condition: str, var_dict: Dict[str, Any], program_variables: set
    ) -> Optional[Any]:
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

        if "and" not in condition and "or" not in condition and "not" not in condition:
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
        else:
            raise ValueError("Invalid condition format")

    def _parse_condition_string(
        self, condition: str, var_dict: dict, program_variables: set
    ) -> Optional[Any]:
        condition = condition.strip()
        # logger.debug(f"condition: {condition} var_dict: {var_dict} program_variables: {program_variables} raw")

        if condition.startswith("not "):
            inner = condition[4:].strip()
            return Not(self._parse_condition_string(inner, var_dict, program_variables))

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
                logger.debug(f"left: {left}; right: {right}")
                return And(
                    self._parse_condition_string(left, var_dict, program_variables),
                    self._parse_condition_string(right, var_dict, program_variables),
                )

        # logger.debug(f"program_variables: {program_variables} raw2")
        # 单个比较
        # logger.debug(f"condition: {condition}  repr:{repr(condition)}")
        # 修改正则表达式以支持结构体成员访问 (example: struct_CarModeResult.status)
        pattern = r"([\w\.]+)\s*([%><=!]+)\s*(.+)"
        match = re.match(pattern, condition)
        if match:
            left_str, op, right_str = match.groups()

            # Log for debugging
            logger.debug(f"Parsing condition: '{left_str} {op} {right_str}'")

            # Ensure struct members are properly handled
            left_str = left_str.strip()
            right_str = right_str.strip()

            # Handle struct members by adding them to program_variables
            if "." in left_str and left_str not in program_variables:
                program_variables.add(left_str)
                # Also add the struct_name_field version for Z3
                program_variables.add(left_str.replace(".", "_"))

            if "." in right_str and right_str not in program_variables:
                program_variables.add(right_str)
                # Also add the struct_name_field version for Z3
                program_variables.add(right_str.replace(".", "_"))

            left_value = self._parse_value(left_str, var_dict, program_variables)
            right_value = self._parse_value(right_str, var_dict, program_variables)

            # Add another fallback for numbers in right_str
            if right_value is None:
                try:
                    if "." in right_str:  # Try as float
                        right_value = RealVal(float(right_str))
                    else:  # Try as int
                        right_value = IntVal(int(right_str))
                except ValueError:
                    pass

            if left_value is None or right_value is None:
                logger.warning(f"Could not parse values for condition: {left_str} {op} {right_str}")
                return None

            # 确保对应的Z3变量字典中只保留原始点号格式的键
            if "." in left_str and left_str.replace(".", "_") in var_dict:
                var_dict.pop(left_str.replace(".", "_"), None)
            if "." in right_str and right_str.replace(".", "_") in var_dict:
                var_dict.pop(right_str.replace(".", "_"), None)

            # logger.debug(f"left_str: {left_str}; right_str: {right_str} op: {op}")
            return self.parser._create_comparison(left_value, op, right_value)
        else:
            logger.warning(f"Invalid condition: {condition}")
            # 不再断言条件必须是true/false，而是尝试作为变量处理
            try:
                # 处理复合条件表达式，如 "VehSpd / 100 - 200 < 0"
                # 尝试使用简单解析来处理常见的比较操作
                for op in ["<=", ">=", "==", "!=", "<", ">"]:
                    if op in condition:
                        parts = condition.split(op, 1)
                        if len(parts) == 2:
                            left_expr = parts[0].strip()
                            right_expr = parts[1].strip()
                            # 递归解析左右表达式
                            left_value = self._parse_condition_string(left_expr, var_dict, program_variables)
                            if left_value is None:
                                left_value = self._parse_value(left_expr, var_dict, program_variables)

                            # 尝试将右侧解析为数值
                            try:
                                if "." in right_expr:
                                    right_value = RealVal(float(right_expr))
                                else:
                                    right_value = IntVal(int(right_expr))
                            except ValueError:
                                right_value = self._parse_value(right_expr, var_dict, program_variables)

                            if left_value is not None and right_value is not None:
                                return self.parser._create_comparison(left_value, op, right_value)

                # Handle struct member access directly in condition
                if "." in condition and condition not in program_variables:
                    # Create struct member variable
                    struct_var = condition.replace(".", "_")
                    program_variables.add(condition)
                    if condition not in var_dict:
                        # 创建Z3变量（使用下划线格式作为Z3变量名，但用点号格式作为键）
                        var_dict[condition] = z3.Int(struct_var)
                    return var_dict[condition] != 0  # Non-zero check as default condition

                one_value = self._parse_value(condition, var_dict, program_variables)
                # Ensure we return a boolean expression
                if one_value is not None:
                    if z3.is_bool(one_value):
                        return one_value
                    else:
                        # Convert to boolean by comparing with 0
                        return one_value != 0
                else:
                    return BoolVal(True)  # Default fallback
            except Exception as e:
                logger.error(f"Failed to parse condition '{condition}': {e}")
                # 返回一个默认的True值，避免完全中断执行
                return BoolVal(True)

    def _extract_model_values(self, model, var_dict, program_variables):
        """Extract model values for program variables"""
        model_values = {}

        # 从条件字符串中提取变量和操作
        condition_strings = var_dict.get("_condition_strings", [])
        condition_vars = {}
        for condition in condition_strings:
            # 简单解析条件，提取变量名和操作
            for op in ["==", "!=", ">=", "<=", ">", "<"]:
                if op in condition:
                    parts = condition.split(op, 1)
                    if len(parts) == 2:
                        var_name = parts[0].strip()
                        value_str = parts[1].strip()
                        if "not (" in var_name:
                            var_name = var_name.replace("not (", "").strip()
                        condition_vars[var_name] = (op, value_str)
                        break

        # 首先收集所有出现在条件中的变量及其Z3变量
        relevant_vars = {}
        for var_name, z3_var in var_dict.items():
            # 只处理点号格式或原始变量名，跳过临时使用的下划线格式
            if "_" in var_name and "." in var_name.replace("_", "."):
                continue

            # 收集所有有值的变量
            if z3_var in model:
                relevant_vars[var_name] = z3_var

        # 从模型中提取值
        for var_name, z3_var in relevant_vars.items():
            if model[z3_var] is not None:
                z3_value = model[z3_var]
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
                            model_values[var_name] = float("inf") if num > 0 else float("-inf")
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
                        model_values[var_name] = z3.is_true(z3_value)
                    else:
                        logger.debug(f"Using string representation for {var_name}: {z3_value} ({type(z3_value)})")
                        model_values[var_name] = str(z3_value)
                except Exception as e:
                    logger.warning(f"Error parsing Z3 value for {var_name}: {e}, using string representation")
                    model_values[var_name] = str(z3_value)

        # 特殊处理结构体成员：如果是布尔类型的条件变量，确保有测试输入
        for var_name in program_variables:
            if var_name in condition_vars and var_name not in model_values:
                op, value = condition_vars[var_name]

                # 尝试转换值
                try:
                    if value.lower() == "true":
                        parsed_value = True
                    elif value.lower() == "false":
                        parsed_value = False
                    elif "." in value:
                        parsed_value = float(value)
                    else:
                        parsed_value = int(value)

                    # 根据操作符设置相应的值
                    if op == "==":
                        model_values[var_name] = parsed_value
                    elif op == "!=":
                        # 使用不同的值
                        if isinstance(parsed_value, bool):
                            model_values[var_name] = not parsed_value
                        else:
                            model_values[var_name] = parsed_value + 1
                except:
                    # 无法解析，使用默认值
                    if "status" in var_name.lower() or "flag" in var_name.lower() or "bool" in var_name.lower():
                        model_values[var_name] = False
                    else:
                        model_values[var_name] = 0

            # 处理没有出现在条件中但有点号的变量（结构体成员）
            elif "." in var_name and var_name not in model_values:
                if "status" in var_name.lower() or "flag" in var_name.lower() or "bool" in var_name.lower():
                    model_values[var_name] = False  # 默认布尔值
                else:
                    model_values[var_name] = 0  # 默认整数值

        return model_values

    def _parse_value(
        self, value_str: str, var_dict: Dict[str, Any], program_variables: set
    ):
        """Parse a value string to Z3 expression"""
        # Strip whitespace
        value_str = value_str.strip()

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

        # 处理结构体成员访问 (例如: struct_CarModeResult.status)
        if "." in value_str:
            # 将结构体成员访问替换为合法的变量名（仅用于Z3内部处理）
            struct_var = value_str.replace(".", "_")

            # 仅添加原始点号格式到程序变量列表
            program_variables.add(value_str)

            if value_str not in var_dict:
                logger.debug(f"Creating struct member variable: {value_str}")
                try:
                    # 尝试推断类型：如果名称中包含 status/flag/enable/disable 等，使用 Bool 类型
                    if any(hint in value_str.lower() for hint in ["status", "flag", "enable", "disable", "active", "bool"]):
                        # 创建Bool类型变量，但只使用临时下划线格式供Z3内部使用
                        z3_var = z3.Bool(struct_var)
                    else:
                        # 默认使用整数类型
                        z3_var = z3.Int(struct_var)

                    # 只在var_dict中保存原始点号格式作为键
                    var_dict[value_str] = z3_var
                except Exception as e:
                    logger.warning(f"Failed to create Z3 variable for {value_str}: {e}")
                    # Create a fallback Int variable
                    try:
                        z3_var = z3.Int(f"fallback_{struct_var}")
                        var_dict[value_str] = z3_var
                    except Exception as e2:
                        logger.error(f"Failed to create fallback Z3 variable: {e2}")
                        # Last resort - use a constant
                        var_dict[value_str] = z3.IntVal(0)

            return var_dict[value_str]

        # 普通变量
        if value_str not in var_dict:
            logger.trace(f"Variable '{value_str}' not found in {var_dict}")
            var_dict[value_str] = create_z3_variable(value_str)
            program_variables.add(value_str)
        return var_dict[value_str]


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
