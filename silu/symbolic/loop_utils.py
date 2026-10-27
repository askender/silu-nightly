#!/usr/bin/env python3
"""
Loop Analysis Utilities for Symbolic Execution

This module provides utilities for analyzing and symbolically executing loops,
particularly range-based loops with support for complex step values and conditions.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

from .z3_utils import (
    Z3_AVAILABLE,
    to_z3_expr,
    simplify_range_cond,
    create_z3_variable,
    extract_constant_value,
)

if Z3_AVAILABLE:
    pass
    # from .z3_utils import ast_to_z3_expr


class LoopType(Enum):
    """Types of loops"""

    RANGE = "range"
    WHILE = "while"
    FOR_ITER = "for_iter"
    UNKNOWN = "unknown"


class LoopBound:
    """Represents loop bounds (start, stop, step)"""

    def __init__(self, start=None, stop=None, step=None):
        self.start = start
        self.stop = stop
        self.step = step if step is not None else 1

    def __str__(self):
        return f"LoopBound(start={self.start}, stop={self.stop}, step={self.step})"

    def __repr__(self):
        return self.__str__()


class LoopIteration:
    """Represents a single loop iteration with constraints"""

    def __init__(
        self,
        iteration: int,
        constraint=None,
        variable_values: Optional[Dict[str, Any]] = None,
    ):
        self.iteration = iteration
        self.constraint = constraint
        self.variable_values = variable_values if variable_values is not None else {}
        self.is_valid = constraint is not None

    def __str__(self):
        return f"Iteration {self.iteration}: {self.constraint}"


class LoopAnalyzer:
    """Analyzer for loop constructs in symbolic execution"""

    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
        self.variable_dict: Dict[str, Any] = {}

    def analyze_range_loop(
        self, start, stop, step=None, var_name: str = "i"
    ) -> List[LoopIteration]:
        """
        Analyze a range-based loop and generate symbolic constraints for iterations.

        Args:
            start: Loop start value
            stop: Loop stop value
            step: Loop step value (default 1)
            var_name: Name of loop variable

        Returns:
            List of LoopIteration objects representing possible iterations
        """
        iterations = []

        if not Z3_AVAILABLE:
            # Fallback: create simple iterations without constraints
            for k in range(min(self.max_iterations, 5)):
                iterations.append(
                    LoopIteration(k, f"{var_name} = {start} + {k} * {step or 1}")
                )
            return iterations

        # Create Z3 variable for loop variable
        if var_name not in self.variable_dict:
            self.variable_dict[var_name] = create_z3_variable(var_name)

        for k in range(self.max_iterations):
            constraint = simplify_range_cond(k, start, stop, step, self.variable_dict)

            if constraint is None:
                # No more valid iterations
                break

            # Calculate iteration variable value
            var_values = {var_name: f"{start} + {k} * {step or 1}"}

            iteration = LoopIteration(k, constraint, var_values)
            iterations.append(iteration)

        return iterations

    def detect_loop_type(self, ir_node: Tuple) -> LoopType:
        """
        Detect the type of loop from IR node.

        Args:
            ir_node: IR tuple representing a loop

        Returns:
            LoopType enum value
        """
        if not isinstance(ir_node, tuple) or len(ir_node) < 2:
            return LoopType.UNKNOWN

        op = ir_node[0]

        if op == "while":
            return LoopType.WHILE
        elif op == "for":
            # Check if it's a range-based for loop
            if len(ir_node) >= 3:
                iter_expr = ir_node[2] if len(ir_node) > 2 else None
                if self._is_range_expression(iter_expr):
                    return LoopType.RANGE
                else:
                    return LoopType.FOR_ITER

        return LoopType.UNKNOWN

    def extract_range_bounds(self, range_expr) -> Optional[LoopBound]:
        """
        Extract bounds from a range expression.
        """
        if not self._is_range_expression(range_expr):
            return None

        args = range_expr[2]

        if len(args) == 1:
            # range(stop)
            return LoopBound(start=('const', 0), stop=args[0], step=('const', 1))
        elif len(args) == 2:
            # range(start, stop)
            return LoopBound(start=args[0], stop=args[1], step=('const', 1))
        elif len(args) == 3:
            # range(start, stop, step)
            return LoopBound(start=args[0], stop=args[1], step=args[2])

        return None

    def _is_range_expression(self, expr) -> bool:
        """Check if expression represents a range() call"""
        if not isinstance(expr, (tuple, list)) or len(expr) < 3 or expr[0] != "call":
            return False

        # New format: ('call', ('name', 'range'), ...)
        if isinstance(expr[1], (tuple, list)) and len(expr[1]) == 2 and expr[1][0] == 'name' and expr[1][1] == 'range':
            return True

        # Old format: ('call', 'range', ...)
        if isinstance(expr[1], str) and expr[1] == 'range':
            return True

        return False

    def estimate_loop_bound(self, start, stop, step=None) -> int:
        """
        Estimate the number of iterations for a loop.

        Args:
            start: Loop start value
            stop: Loop stop value
            step: Loop step value

        Returns:
            Estimated number of iterations
        """
        if step is None:
            step = 1

        # Try to extract constant values
        start_val = self._extract_numeric_value(start)
        stop_val = self._extract_numeric_value(stop)
        step_val = self._extract_numeric_value(step)

        # Only proceed with calculation if all values are numeric
        if start_val is not None and stop_val is not None and step_val is not None:
            if step_val == 0:
                return 0  # Infinite loop or error
            elif step_val > 0:
                return max(0, int((stop_val - start_val + step_val - 1) // step_val))
            else:  # step_val < 0
                return max(0, int((start_val - stop_val - step_val - 1) // (-step_val)))

        # Default estimate for symbolic values
        return self.max_iterations

    def _extract_numeric_value(self, expr) -> Optional[Union[int, float]]:
        """Extract numeric value from expression if possible, return None for non-numeric"""
        if isinstance(expr, (int, float)):
            return expr

        if Z3_AVAILABLE:
            z3_expr = to_z3_expr(expr, self.variable_dict)
            if z3_expr is not None:
                const_val = extract_constant_value(z3_expr)
                if isinstance(const_val, (int, float)):
                    return const_val

        # For string expressions, try to parse as number
        if isinstance(expr, str):
            try:
                # Try integer first
                return int(expr)
            except ValueError:
                try:
                    # Try float
                    return float(expr)
                except ValueError:
                    # Not a numeric string
                    pass

        return None

    # def _extract_value(self, expr) -> Union[int, float, str, None]:
    #     """Extract value from expression if possible (kept for backward compatibility)"""
    #     if isinstance(expr, (int, float)):
    #         return expr

    #     if Z3_AVAILABLE:
    #         z3_expr = to_z3_expr(expr, self.variable_dict)
    #         if z3_expr is not None:
    #             const_val = extract_constant_value(z3_expr)
    #             if const_val is not None:
    #                 return const_val

    #     if isinstance(expr, str):
    #         return expr

    #     return None
