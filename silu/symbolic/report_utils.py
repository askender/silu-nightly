#!/usr/bin/env python3
"""
Report Generation Utilities for Symbolic Execution

This module provides utilities for generating reports and summaries from
symbolic execution results, including path analysis and test case generation.
"""

from typing import Any, Dict, List, Optional

from .z3_utils import (
    Z3_AVAILABLE,
    # condition_to_z3,
)


def path_to_dict(path: Any) -> Dict[str, Any]:
    """Convert a path object to dictionary format"""
    if hasattr(path, "to_dict"):
        return path.to_dict()

    path_dict = {
        "path_id": getattr(path, "path_id", "unknown"),
        "conditions": [str(c) for c in getattr(path, "conditions", [])],
        "statements": list(getattr(path, "statements", [])),
        "return_value": str(getattr(path, "return_value", None))
        if getattr(path, "return_value", None) is not None
        else None,
        "variables": {
            str(k): str(v) for k, v in getattr(path, "variables", {}).items()
        },
        "satisfiable": getattr(path, "satisfiable", True),
        "loop_iterations": getattr(path, "loop_iterations", {}),
        "test_inputs": getattr(path, "test_inputs", {}),
        "expected_outputs": getattr(path, "expected_outputs", {}),
        "z3_error": getattr(path, "z3_error", None),
    }
    return path_dict


def _build_path_metrics(paths: List[Any]) -> Dict[str, Any]:
    """Build path metrics information from paths"""
    return {
        "average_path_length": sum(len(getattr(p, "statements", [])) for p in paths)
        / len(paths)
        if paths
        else 0,
        "average_conditions_per_path": sum(
            len(getattr(p, "conditions", [])) for p in paths
        )
        / len(paths)
        if paths
        else 0,
        "paths_with_loops": sum(1 for p in paths if getattr(p, "loop_iterations", {})),
        "paths_with_returns": sum(
            1 for p in paths if getattr(p, "return_value", None) is not None
        ),
    }


def _build_constraint_analysis(paths: List[Any]) -> Dict[str, Any]:
    """Build constraint analysis information from paths"""
    satisfiable_paths = [p for p in paths if getattr(p, "satisfiable", True)]

    return {
        "total_constraints": sum(len(getattr(p, "conditions", [])) for p in paths),
        "z3_constraints": sum(
            1
            for p in paths
            for c in getattr(p, "conditions", [])
            if getattr(c, "z3_constraint", None) is not None
        ),
        "symbolic_variables": 0,  # Will be set by caller if available
        "satisfiable_constraint_ratio": len(satisfiable_paths) / len(paths)
        if paths
        else 0,
    }


def _build_loop_analysis(paths: List[Any]) -> Dict[str, Dict[str, int]]:
    """Build loop analysis information from paths"""
    loop_info = {}
    for path in paths:
        loop_iterations = getattr(path, "loop_iterations", {})
        for loop_id, iteration in loop_iterations.items():
            if loop_id not in loop_info:
                loop_info[loop_id] = {"max_iteration": 0, "paths": 0}
            loop_info[loop_id]["max_iteration"] = max(
                loop_info[loop_id]["max_iteration"], iteration
            )
            loop_info[loop_id]["paths"] += 1
    return loop_info


def generate_comprehensive_report(
    paths: List[Any],
    performance_mode: bool = False,
    global_env_functions: Optional[Dict] = None,
    function_analyses: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Generate a comprehensive report of symbolic execution results with enhanced analysis

    Args:
        paths: List of execution paths
        performance_mode: Whether to generate a simplified report for performance
        global_env_functions: Global environment functions dict
        function_analyses: Function analysis results

    Returns:
        Comprehensive report dictionary
    """

    if performance_mode:
        return generate_fast_comprehensive_report(
            paths, global_env_functions, function_analyses
        )

    satisfiable_paths = [p for p in paths if getattr(p, "satisfiable", True)]

    # Enhanced loop analysis
    loop_info = _build_loop_analysis(paths)

    # Enhanced constraint analysis
    constraint_analysis = _build_constraint_analysis(paths)

    # Path complexity metrics
    path_metrics = _build_path_metrics(paths)

    summary = {
        "functions_analyzed": len(global_env_functions) if global_env_functions else 0,
        "max_path_length": max(
            (len(getattr(p, "statements", [])) for p in paths), default=0
        ),
        "max_conditions": max(
            (len(getattr(p, "conditions", [])) for p in paths), default=0
        ),
        "z3_available": Z3_AVAILABLE,
        "loop_analysis": loop_info,
        "constraint_analysis": constraint_analysis,
        "path_metrics": path_metrics,
        "enhanced_features": {
            "z3_constraint_generation": Z3_AVAILABLE,
            "range_loop_precision": True,
            "enhanced_ast_conversion": True,
            "path_satisfiability_checking": Z3_AVAILABLE,
        },
    }
    print(f"len of summary: {len(summary)}")
    report = {
        "total_paths": len(paths),
        "satisfiable_paths": len(satisfiable_paths),
        "paths": [path_to_dict(path) for path in paths],
    }

    # Add function analysis details if available
    if function_analyses:
        report["function_analyses"] = {}
        for func_name, func_paths in function_analyses.items():
            report["function_analyses"][func_name] = {
                "total_paths": len(func_paths),
                "satisfiable_paths": len(
                    [p for p in func_paths if getattr(p, "satisfiable", True)]
                ),
                "paths": [path_to_dict(path) for path in func_paths],
            }

    return report


def generate_fast_comprehensive_report(
    paths: List[Any],
    global_env_functions: Optional[Dict] = None,
    function_analyses: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Generate simplified report for performance mode"""
    satisfiable_paths = [p for p in paths if getattr(p, "satisfiable", True)]

    report = {
        "total_paths": len(paths),
        "satisfiable_paths": len(satisfiable_paths),
        "paths": [path_to_dict(path) for path in paths],
        "summary": {
            "functions_analyzed": len(global_env_functions)
            if global_env_functions
            else 0,
            "max_path_length": max(
                (len(getattr(p, "statements", [])) for p in paths), default=0
            ),
            "max_conditions": max(
                (len(getattr(p, "conditions", [])) for p in paths), default=0
            ),
            "performance_mode": True,
        },
    }

    # Add function analysis if available
    if function_analyses:
        report["function_analyses"] = {}
        for func_name, func_paths in function_analyses.items():
            report["function_analyses"][func_name] = {
                "total_paths": len(func_paths),
                "satisfiable_paths": len(
                    [p for p in func_paths if getattr(p, "satisfiable", True)]
                ),
                "paths": [path_to_dict(path) for path in func_paths],
            }

    return report


def renumber_paths_sequentially(paths: List[Any]) -> List[Any]:
    """Renumber paths sequentially starting from 1"""
    for i, path in enumerate(paths, 1):
        if hasattr(path, "path_id"):
            path.path_id = f"path_{i}"
    return paths
