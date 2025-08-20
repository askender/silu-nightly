#!/usr/bin/env python3
"""
Symbolic Execution Package for Silu Language

This package provides enhanced symbolic execution capabilities with Z3 integration
and advanced loop analysis for the Silu programming language.
"""

from .z3_utils import (
    Z3_AVAILABLE,
    ast_to_z3_expr,
    check_path_satisfiability,
    create_solver_with_constraints,
    parse_condition_string,
    get_vars_from_ast,
    to_z3_expr,
    simplify_range_cond,
    is_sat,
    create_z3_variable,
    extract_constant_value
)

from .loop_utils import (
    LoopAnalyzer,
    LoopType,
    LoopBound,
    LoopIteration,
    analyze_nested_loops
)

__all__ = [
    # Z3 utilities
    'Z3_AVAILABLE',
    'ast_to_z3_expr',
    'check_path_satisfiability',
    'create_solver_with_constraints',
    'parse_condition_string',
    'get_vars_from_ast',
    'to_z3_expr',
    'simplify_range_cond',
    'is_sat',
    'create_z3_variable',
    'extract_constant_value',

    # Loop analysis
    'LoopAnalyzer',
    'LoopType',
    'LoopBound',
    'LoopIteration',
    'analyze_nested_loops'
]
