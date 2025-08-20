#!/usr/bin/env python3
"""
Condition Processing Utilities for Symbolic Execution

This module provides utilities for handling path conditions, simplifying expressions,
and managing condition-related operations in symbolic execution.
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


class PathCondition:
    """Represents a path condition in symbolic execution"""

    def __init__(self, expression: str, is_true: bool = True):
        self.expression = expression
        self.is_true = is_true

    def __str__(self) -> str:
        if self.is_true:
            return self.expression
        return f"not ({self.expression})"

    def negate(self) -> 'PathCondition':
        """Return the negation of this condition"""
        # Handle double negation
        if not self.is_true and self.expression.startswith("not (") and self.expression.endswith(")"):
            # Extract the inner expression from "not (inner)"
            inner = self.expression[5:-1]  # Remove "not (" and ")"
            return PathCondition(inner, True)

        # Handle already negated expressions
        if self.expression.startswith("not "):
            inner = self.expression[4:]  # Remove "not "
            return PathCondition(inner, True)

        # Simple negation
        return PathCondition(self.expression, not self.is_true)

    def __repr__(self) -> str:
        return f"PathCondition({self.expression!r}, {self.is_true})"


def extract_variable_from_condition(condition_str: str) -> Optional[str]:
    """
    Extract variable name from a simple condition like 'x > 5'

    Args:
        condition_str: String representation of the condition

    Returns:
        Variable name if found, None otherwise
    """
    condition_str = condition_str.strip()

    # Pattern for simple variable comparisons: variable op value
    pattern = r'^(\w+)\s*([><=!]+)\s*(.+)$'
    match = re.match(pattern, condition_str)

    if match:
        var_name = match.group(1)
        # Check if this is a simple variable (not a function call or complex expression)
        if var_name.isidentifier():
            return var_name

    return None


def is_simple_variable_condition(condition_str: str) -> bool:
    """Check if condition is a simple variable comparison"""
    return extract_variable_from_condition(condition_str) is not None


def group_conditions_by_variable(conditions: List[PathCondition]) -> Dict[str, List[PathCondition]]:
    """
    Group conditions by the variable they reference

    Args:
        conditions: List of path conditions

    Returns:
        Dictionary mapping variable names to their conditions
    """
    groups = {}

    for condition in conditions:
        var_name = extract_variable_from_condition(condition.expression)
        if var_name:
            if var_name not in groups:
                groups[var_name] = []
            groups[var_name].append(condition)

    return groups


def merge_conditions_for_variable(variable: str, conditions: List[PathCondition]) -> List[PathCondition]:
    """
    Merge conditions for a single variable

    Args:
        variable: Variable name
        conditions: List of conditions for this variable

    Returns:
        List of merged/simplified conditions
    """
    if len(conditions) <= 1:
        return conditions

    # Separate positive and negative conditions
    positive_conditions = [c for c in conditions if c.is_true]
    negative_conditions = [c for c in conditions if not c.is_true]

    # Try to merge negative conditions (not operators)
    merged_negative = merge_negative_conditions(variable, negative_conditions)

    # For now, just return original conditions if no simplification
    # More sophisticated merging could be implemented here
    return positive_conditions + merged_negative


def merge_negative_conditions(variable: str, negative_conditions: List[PathCondition]) -> List[PathCondition]:
    """
    Merge negative conditions for a variable

    Args:
        variable: Variable name
        negative_conditions: List of negative conditions

    Returns:
        List of merged negative conditions
    """
    if len(negative_conditions) <= 1:
        return negative_conditions

    # Look for patterns like "not (x > 10)" and "not (x > 0)" -> "x <= 0"
    gt_conditions = []
    lt_conditions = []
    eq_conditions = []
    other_conditions = []

    for condition in negative_conditions:
        expr = condition.expression.strip()

        # Parse "x > value" patterns
        gt_match = re.match(rf'^{re.escape(variable)}\s*>\s*(.+)$', expr)
        if gt_match:
            try:
                value = float(gt_match.group(1))
                gt_conditions.append((value, condition))
                continue
            except ValueError:
                pass

        # Parse "x < value" patterns
        lt_match = re.match(rf'^{re.escape(variable)}\s*<\s*(.+)$', expr)
        if lt_match:
            try:
                value = float(lt_match.group(1))
                lt_conditions.append((value, condition))
                continue
            except ValueError:
                pass

        # Parse "x == value" patterns
        eq_match = re.match(rf'^{re.escape(variable)}\s*==\s*(.+)$', expr)
        if eq_match:
            eq_conditions.append(condition)
            continue

        other_conditions.append(condition)

    # If we have non-numeric conditions, don't merge anything to avoid confusion
    if other_conditions:
        return negative_conditions

    # Merge "not (x > value)" conditions -> "x <= min_value"
    merged = []
    if gt_conditions:
        min_value = min(value for value, _ in gt_conditions)
        merged.append(PathCondition(f"{variable} <= {min_value}", True))

    # Merge "not (x < value)" conditions -> "x >= max_value"
    if lt_conditions:
        max_value = max(value for value, _ in lt_conditions)
        merged.append(PathCondition(f"{variable} >= {max_value}", True))

    # Keep other conditions as-is
    merged.extend(eq_conditions)

    return merged


def simplify_condition_expression(expression: str) -> str:
    """
    Simplify a condition expression by removing redundant parts

    Args:
        expression: String representation of condition

    Returns:
        Simplified expression string
    """
    # Remove extra whitespace
    expr = re.sub(r'\s+', ' ', expression.strip())

    # Remove redundant parentheses around simple expressions
    if expr.startswith('(') and expr.endswith(')'):
        # Check if parentheses are actually redundant
        paren_count = 0
        can_remove = True
        for i, char in enumerate(expr[1:-1]):  # Skip outer parentheses
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
                if paren_count < 0:  # Closing paren that matches outer paren
                    can_remove = False
                    break

        if can_remove and paren_count == 0:
            expr = expr[1:-1]

    # Normalize comparison operators (use negative lookahead to avoid conflicts)
    expr = re.sub(r'\s*<=\s*', ' <= ', expr)
    expr = re.sub(r'\s*>=\s*', ' >= ', expr)
    expr = re.sub(r'\s*==\s*', ' == ', expr)
    expr = re.sub(r'\s*!=\s*', ' != ', expr)
    expr = re.sub(r'\s*(?<!<|>)>\s*(?![=>])', ' > ', expr)
    expr = re.sub(r'\s*(?<!<|>)<\s*(?![=>])', ' < ', expr)

    return expr


def make_condition_readable(condition_str: str) -> str:
    """
    Make a condition more readable by improving formatting and simplifying

    Args:
        condition_str: String representation of condition

    Returns:
        More readable condition string
    """
    # Handle tuple expressions from symbolic execution
    if condition_str.startswith("(") and "," in condition_str and condition_str.endswith(")"):
        try:
            # Try to parse as tuple and make it readable
            import ast
            parsed = ast.literal_eval(condition_str)
            if isinstance(parsed, tuple) and len(parsed) >= 2:
                op = parsed[0]
                if op in ['>', '<', '>=', '<=', '==', '!=']:
                    left = parsed[1] if len(parsed) > 1 else "?"
                    right = parsed[2] if len(parsed) > 2 else "?"
                    return f"{left} {op} {right}"
                elif op == 'And':
                    conditions = [make_condition_readable(str(cond)) for cond in parsed[1:]]
                    return " and ".join(conditions)
                elif op == 'Or':
                    conditions = [make_condition_readable(str(cond)) for cond in parsed[1:]]
                    return " or ".join(conditions)
        except (ValueError, SyntaxError):
            pass

    # Handle Z3-style expressions
    if any(z3_op in condition_str for z3_op in ['And(', 'Or(', 'Not(']):
        # Convert Z3-style to readable format
        condition_str = condition_str.replace('And(', '(').replace('Or(', '(')
        condition_str = condition_str.replace('Not(', 'not (')

        # Replace Z3 operators with readable ones
        condition_str = re.sub(r'\s*,\s*', ' and ', condition_str)

    return simplify_condition_expression(condition_str)


def split_condition_args(args_str: str) -> List[str]:
    """
    Split condition arguments, handling nested parentheses

    Args:
        args_str: String containing comma-separated arguments

    Returns:
        List of argument strings
    """
    args = []
    current_arg = ""
    paren_count = 0

    for char in args_str:
        if char == ',' and paren_count == 0:
            args.append(current_arg.strip())
            current_arg = ""
        else:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            current_arg += char

    # Add the last argument
    if current_arg.strip():
        args.append(current_arg.strip())

    return args


def normalize_condition(condition: PathCondition) -> PathCondition:
    """
    Normalize a condition to a standard form

    Args:
        condition: Path condition to normalize

    Returns:
        Normalized path condition
    """
    expr = condition.expression.strip()
    is_true = condition.is_true

    # Handle double negation
    if expr.startswith("not ") and not is_true:
        # "not (not expr)" becomes "expr"
        inner_expr = expr[4:].strip()
        if inner_expr.startswith("(") and inner_expr.endswith(")"):
            inner_expr = inner_expr[1:-1].strip()
        return PathCondition(inner_expr, True)

    # Simplify the expression
    simplified_expr = make_condition_readable(expr)

    return PathCondition(simplified_expr, is_true)


def conditions_are_contradictory(cond1: PathCondition, cond2: PathCondition) -> bool:
    """
    Check if two conditions are contradictory

    Args:
        cond1: First condition
        cond2: Second condition

    Returns:
        True if conditions contradict each other
    """
    # Normalize both conditions
    norm1 = normalize_condition(cond1)
    norm2 = normalize_condition(cond2)

    # Check if they're exact opposites
    if norm1.expression == norm2.expression:
        return norm1.is_true != norm2.is_true

    # Check for some simple contradictions
    # e.g., "x > 5" and "x < 3"
    var1 = extract_variable_from_condition(norm1.expression)
    var2 = extract_variable_from_condition(norm2.expression)

    if var1 and var2 and var1 == var2:
        # Same variable, check for contradictory ranges
        return check_range_contradiction(norm1, norm2, var1)

    return False


def check_range_contradiction(cond1: PathCondition, cond2: PathCondition, variable: str) -> bool:
    """
    Check if two conditions on the same variable create a contradiction

    Args:
        cond1: First condition
        cond2: Second condition
        variable: Variable name

    Returns:
        True if conditions are contradictory
    """
    def parse_range_condition(cond: PathCondition) -> Optional[Tuple[str, float, bool]]:
        """Parse condition like 'x > 5' into (op, value, is_true)"""
        expr = cond.expression.strip()
        for op in ['>=', '<=', '==', '!=', '>', '<']:
            if op in expr:
                parts = expr.split(op)
                if len(parts) == 2:
                    var_part = parts[0].strip()
                    val_part = parts[1].strip()
                    if var_part == variable:
                        try:
                            value = float(val_part)
                            return (op, value, cond.is_true)
                        except ValueError:
                            pass
        return None

    parsed1 = parse_range_condition(cond1)
    parsed2 = parse_range_condition(cond2)

    if not parsed1 or not parsed2:
        return False

    op1, val1, true1 = parsed1
    op2, val2, true2 = parsed2

    # Check some obvious contradictions
    if true1 and true2:
        # Both conditions must be true
        if op1 == '>' and op2 == '<' and val1 >= val2:
            return True  # x > 5 and x < 5 (or x < 3)
        if op1 == '>=' and op2 == '<' and val1 >= val2:
            return True  # x >= 5 and x < 5
        if op1 == '>' and op2 == '<=' and val1 >= val2:
            return True  # x > 5 and x <= 5
        if op1 == '==' and op2 == '!=' and val1 == val2:
            return True  # x == 5 and x != 5

    return False


def simplify_conditions_list(conditions: List[PathCondition]) -> List[PathCondition]:
    """
    Simplify a list of conditions by removing redundancies and contradictions

    Args:
        conditions: List of path conditions

    Returns:
        Simplified list of conditions
    """
    if not conditions:
        return conditions

    # Remove exact duplicates
    seen = set()
    unique_conditions = []
    for cond in conditions:
        cond_key = (cond.expression, cond.is_true)
        if cond_key not in seen:
            seen.add(cond_key)
            unique_conditions.append(cond)

    # Group conditions by variable for potential simplification
    grouped_conditions = group_conditions_by_variable(unique_conditions)

    # Simplify conditions for each variable group
    simplified_conditions = []
    for var_name, conditions_for_var in grouped_conditions.items():
        if var_name and len(conditions_for_var) > 1:
            # Use the enhanced variable-level merging strategy
            merged_conditions = merge_conditions_for_variable(var_name, conditions_for_var)
            simplified_conditions.extend(merged_conditions)
        else:
            simplified_conditions.extend(conditions_for_var)

    # Add any conditions that couldn't be grouped by variable
    for condition in unique_conditions:
        if not is_simple_variable_condition(condition.expression):
            simplified_conditions.append(condition)

    # Check for contradictions
    final_simplified = []
    for cond in simplified_conditions:
        is_contradictory = False
        for existing in final_simplified:
            if conditions_are_contradictory(cond, existing):
                is_contradictory = True
                break

        if not is_contradictory:
            final_simplified.append(normalize_condition(cond))

    return final_simplified
