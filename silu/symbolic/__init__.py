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

from .builtin_utils import (
    SymbolicValueType,
    SymbolicValue,
    create_concrete_value,
    create_expression_value,
    create_builtin_functions_dict,
    symbolic_print,
    simplify_args_display,
    is_builtin_function,
    get_builtin_function
)

from .condition_utils import (
    PathCondition,
    extract_variable_from_condition,
    is_simple_variable_condition,
    group_conditions_by_variable,
    merge_conditions_for_variable,
    make_condition_readable,
    simplify_conditions_list,
    normalize_condition,
    conditions_are_contradictory
)

from .report_utils import (
    ReportFormat,
    generate_report,
    generate_fast_report,
    extract_test_cases,
    generate_test_case_report,
    generate_execution_summary
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
    'analyze_nested_loops',

    # Builtin utilities
    'SymbolicValueType',
    'SymbolicValue',
    'create_concrete_value',
    'create_expression_value',
    'create_builtin_functions_dict',
    'symbolic_print',
    'simplify_args_display',
    'is_builtin_function',
    'get_builtin_function',

    # Condition utilities
    'PathCondition',
    'extract_variable_from_condition',
    'is_simple_variable_condition',
    'group_conditions_by_variable',
    'merge_conditions_for_variable',
    'make_condition_readable',
    'simplify_conditions_list',
    'normalize_condition',
    'conditions_are_contradictory',

    # Report utilities
    'ReportFormat',
    'generate_report',
    'generate_fast_report',
    'extract_test_cases',
    'generate_test_case_report',
    'generate_execution_summary'
]
