#!/usr/bin/env python3
"""
Report Generation Utilities for Symbolic Execution

This module provides utilities for generating reports and summaries from
symbolic execution results, including path analysis and test case generation.
"""

from typing import Any, Dict, List, Optional
from enum import Enum
import json

# Import Z3 utilities
from .z3_utils import (
    Z3_AVAILABLE,
    condition_to_z3,
)


class ReportFormat(Enum):
    """Supported report formats"""

    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


def generate_execution_summary(
    paths: List[Any], total_time: float = 0.0
) -> Dict[str, Any]:
    """
    Generate a summary of symbolic execution results

    Args:
        paths: List of execution paths
        total_time: Total execution time in seconds

    Returns:
        Dictionary containing execution summary
    """
    if not paths:
        return {
            "total_paths": 0,
            "satisfiable_paths": 0,
            "unsatisfiable_paths": 0,
            "total_conditions": 0,
            "total_statements": 0,
            "unique_variables": 0,
            "variables": [],
            "execution_time": total_time,
            "avg_conditions_per_path": 0,
            "avg_statements_per_path": 0,
            "coverage_info": {},
        }

    satisfiable_count = 0
    unsatisfiable_count = 0
    total_conditions = 0
    total_statements = 0
    variables_seen = set()

    for path in paths:
        # Count satisfiable vs unsatisfiable paths
        if hasattr(path, "satisfiable"):
            if path.satisfiable:
                satisfiable_count += 1
            else:
                unsatisfiable_count += 1
        else:
            # Assume satisfiable if not specified
            satisfiable_count += 1

        # Collect statistics
        if hasattr(path, "conditions"):
            total_conditions += len(path.conditions)

        if hasattr(path, "statements"):
            total_statements += len(path.statements)

        if hasattr(path, "variables"):
            variables_seen.update(path.variables.keys())

    return {
        "total_paths": len(paths),
        "satisfiable_paths": satisfiable_count,
        "unsatisfiable_paths": unsatisfiable_count,
        "total_conditions": total_conditions,
        "total_statements": total_statements,
        "unique_variables": len(variables_seen),
        "variables": list(variables_seen),
        "execution_time": total_time,
        "avg_conditions_per_path": total_conditions / len(paths) if paths else 0,
        "avg_statements_per_path": total_statements / len(paths) if paths else 0,
    }


def format_path_conditions(conditions: List[Any]) -> List[str]:
    """
    Format path conditions for display

    Args:
        conditions: List of path conditions

    Returns:
        List of formatted condition strings
    """
    formatted = []
    for condition in conditions:
        if hasattr(condition, "__str__"):
            formatted.append(str(condition))
        else:
            formatted.append(repr(condition))
    return formatted


def format_path_variables(variables: Dict[str, Any]) -> Dict[str, str]:
    """
    Format path variables for display

    Args:
        variables: Dictionary of variable names to values

    Returns:
        Dictionary with string representations of values
    """
    formatted = {}
    for name, value in variables.items():
        if hasattr(value, "__str__"):
            formatted[name] = str(value)
        else:
            formatted[name] = repr(value)
    return formatted


def generate_path_report(path: Any, path_index: int = 0) -> Dict[str, Any]:
    """
    Generate a report for a single execution path

    Args:
        path: Execution path object
        path_index: Index of the path in the overall execution

    Returns:
        Dictionary containing path report
    """
    report = {
        "path_id": getattr(path, "path_id", f"path_{path_index + 1}"),
        "path_index": path_index,
        "satisfiable": getattr(path, "satisfiable", True),
    }

    # Add conditions
    if hasattr(path, "conditions"):
        report["conditions"] = format_path_conditions(path.conditions)
        report["condition_count"] = len(path.conditions)
    else:
        report["conditions"] = []
        report["condition_count"] = 0

    # Add statements
    if hasattr(path, "statements"):
        report["statements"] = list(path.statements) if path.statements else []
        report["statement_count"] = len(path.statements)
    else:
        report["statements"] = []
        report["statement_count"] = 0

    # Add variables
    if hasattr(path, "variables"):
        report["variables"] = format_path_variables(path.variables)
        report["variable_count"] = len(path.variables)
    else:
        report["variables"] = {}
        report["variable_count"] = 0

    # Add return value
    if hasattr(path, "return_value"):
        report["return_value"] = (
            str(path.return_value) if path.return_value is not None else None
        )

    # Add loop iterations
    if hasattr(path, "loop_iterations"):
        report["loop_iterations"] = path.loop_iterations

    # Add test case information
    if hasattr(path, "test_inputs"):
        report["test_inputs"] = path.test_inputs

    if hasattr(path, "expected_outputs"):
        report["expected_outputs"] = path.expected_outputs

    # Add Z3 error information if present
    if hasattr(path, "z3_error"):
        report["z3_error"] = path.z3_error

    return report


def _format_summary_section(summary: Dict[str, Any]) -> List[str]:
    """Format summary section for reports"""
    lines = []
    lines.append("EXECUTION SUMMARY")
    lines.append("-" * 20)
    lines.append(f"Total paths: {summary['total_paths']}")
    lines.append(f"Satisfiable paths: {summary['satisfiable_paths']}")
    lines.append(f"Unsatisfiable paths: {summary['unsatisfiable_paths']}")
    lines.append(f"Total conditions: {summary['total_conditions']}")
    lines.append(f"Total statements: {summary['total_statements']}")
    lines.append(f"Unique variables: {summary['unique_variables']}")
    if summary["execution_time"] > 0:
        lines.append(f"Execution time: {summary['execution_time']:.3f}s")
    return lines


def _format_variables_section(summary: Dict[str, Any]) -> List[str]:
    """Format variables section for reports"""
    lines = []
    if summary.get("variables"):
        lines.append("VARIABLES")
        lines.append("-" * 10)
        for var in sorted(summary["variables"]):
            lines.append(f"  {var}")
    return lines


def _format_path_details_text(paths: List[Any]) -> List[str]:
    """Format path details for text report"""
    lines = []
    lines.append("PATH DETAILS")
    lines.append("-" * 15)

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)
        lines.extend(_format_single_path_text(path_report, i))

    return lines


def _format_single_path_text(path_report: Dict[str, Any], index: int) -> List[str]:
    """Format a single path for text report"""
    lines = []
    lines.append(f"Path {index + 1}: {path_report['path_id']}")

    if not path_report["satisfiable"]:
        lines.append("  Status: UNSATISFIABLE")

    if path_report["conditions"]:
        lines.append("  Conditions:")
        for condition in path_report["conditions"]:
            lines.append(f"    - {condition}")

    if path_report["variables"]:
        lines.append("  Variables:")
        for name, value in path_report["variables"].items():
            lines.append(f"    {name} = {value}")

    if path_report["statements"]:
        lines.append("  Statements:")
        for stmt in path_report["statements"]:
            lines.append(f"    {stmt}")

    if path_report.get("return_value") is not None:
        lines.append(f"  Return: {path_report['return_value']}")

    if path_report.get("test_inputs"):
        lines.append("  Test inputs:")
        for name, value in path_report["test_inputs"].items():
            lines.append(f"    {name} = {value}")

    lines.append("")
    return lines


def generate_text_report(paths: List[Any], summary: Dict[str, Any]) -> str:
    """
    Generate a text-based report

    Args:
        paths: List of execution paths
        summary: Execution summary dictionary

    Returns:
        Formatted text report
    """
    lines = []

    # Header
    lines.append("Symbolic Execution Report")
    lines.append("=" * 50)
    lines.append("")

    # Summary
    lines.extend(_format_summary_section(summary))
    lines.append("")

    # Variables
    var_lines = _format_variables_section(summary)
    if var_lines:
        lines.extend(var_lines)
        lines.append("")

    # Path details
    lines.extend(_format_path_details_text(paths))

    return "\n".join(lines)


def generate_json_report(paths: List[Any], summary: Dict[str, Any]) -> str:
    """
    Generate a JSON-based report

    Args:
        paths: List of execution paths
        summary: Execution summary dictionary

    Returns:
        JSON-formatted report string
    """
    report = {"summary": summary, "paths": []}

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)
        report["paths"].append(path_report)

    return json.dumps(report, indent=2, default=str)


def _format_markdown_summary(summary: Dict[str, Any]) -> List[str]:
    """Format summary section for markdown report"""
    lines = []
    lines.append("## Execution Summary")
    lines.append("")
    lines.append(f"- **Total paths**: {summary['total_paths']}")
    lines.append(f"- **Satisfiable paths**: {summary['satisfiable_paths']}")
    lines.append(f"- **Unsatisfiable paths**: {summary['unsatisfiable_paths']}")
    lines.append(f"- **Total conditions**: {summary['total_conditions']}")
    lines.append(f"- **Total statements**: {summary['total_statements']}")
    lines.append(f"- **Unique variables**: {summary['unique_variables']}")
    if summary["execution_time"] > 0:
        lines.append(f"- **Execution time**: {summary['execution_time']:.3f}s")
    return lines


def _format_markdown_variables(summary: Dict[str, Any]) -> List[str]:
    """Format variables section for markdown report"""
    lines = []
    if summary.get("variables"):
        lines.append("## Variables")
        lines.append("")
        for var in sorted(summary["variables"]):
            lines.append(f"- `{var}`")
    return lines


def _format_markdown_path_details(paths: List[Any]) -> List[str]:
    """Format path details for markdown report"""
    lines = []
    lines.append("## Path Details")
    lines.append("")

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)
        lines.extend(_format_single_path_markdown(path_report, i))

    return lines


def _format_single_path_markdown(path_report: Dict[str, Any], index: int) -> List[str]:
    """Format a single path for markdown report"""
    lines = []
    lines.append(f"### Path {index + 1}: {path_report['path_id']}")
    lines.append("")

    if not path_report["satisfiable"]:
        lines.append("**Status**: UNSATISFIABLE")
        lines.append("")

    if path_report["conditions"]:
        lines.append("**Conditions**:")
        for condition in path_report["conditions"]:
            lines.append(f"- `{condition}`")
        lines.append("")

    if path_report["variables"]:
        lines.append("**Variables**:")
        for name, value in path_report["variables"].items():
            lines.append(f"- `{name} = {value}`")
        lines.append("")

    if path_report["statements"]:
        lines.append("**Statements**:")
        for stmt in path_report["statements"]:
            lines.append(f"- `{stmt}`")
        lines.append("")

    if path_report.get("return_value") is not None:
        lines.append(f"**Return**: `{path_report['return_value']}`")
        lines.append("")

    if path_report.get("test_inputs"):
        lines.append("**Test inputs**:")
        for name, value in path_report["test_inputs"].items():
            lines.append(f"- `{name} = {value}`")
        lines.append("")

    return lines


def generate_markdown_report(paths: List[Any], summary: Dict[str, Any]) -> str:
    """
    Generate a Markdown-based report

    Args:
        paths: List of execution paths
        summary: Execution summary dictionary

    Returns:
        Markdown-formatted report string
    """
    lines = []

    # Header
    lines.append("# Symbolic Execution Report")
    lines.append("")

    # Summary
    lines.extend(_format_markdown_summary(summary))
    lines.append("")

    # Variables
    var_lines = _format_markdown_variables(summary)
    if var_lines:
        lines.extend(var_lines)
        lines.append("")

    # Path details
    lines.extend(_format_markdown_path_details(paths))

    return "\n".join(lines)


def generate_report(
    paths: List[Any],
    format_type: ReportFormat = ReportFormat.TEXT,
    execution_time: float = 0.0,
) -> str:
    """
    Generate a report in the specified format

    Args:
        paths: List of execution paths
        format_type: Desired report format
        execution_time: Total execution time

    Returns:
        Formatted report string
    """
    summary = generate_execution_summary(paths, execution_time)

    if format_type == ReportFormat.JSON:
        return generate_json_report(paths, summary)
    elif format_type == ReportFormat.MARKDOWN:
        return generate_markdown_report(paths, summary)
    else:  # Default to text
        return generate_text_report(paths, summary)


def generate_fast_report(paths: List[Any], max_paths: int = 5) -> str:
    """
    Generate a quick summary report with limited path details

    Args:
        paths: List of execution paths
        max_paths: Maximum number of paths to include in detail

    Returns:
        Quick summary report string
    """
    summary = generate_execution_summary(paths)

    lines = []
    lines.append(f"Quick Summary: {summary['total_paths']} paths")
    lines.append(
        f"Satisfiable: {summary['satisfiable_paths']}, "
        f"Unsatisfiable: {summary['unsatisfiable_paths']}"
    )

    if summary["unique_variables"] > 0:
        lines.append(f"Variables: {', '.join(sorted(summary.get('variables', [])))}")

    # Show details for first few paths
    if paths:
        lines.append("\nPath details:")
        for i, path in enumerate(paths[:max_paths]):
            path_report = generate_path_report(path, i)
            status = "SAT" if path_report["satisfiable"] else "UNSAT"
            cond_count = path_report["condition_count"]
            lines.append(
                f"  {path_report['path_id']}: {status}, {cond_count} conditions"
            )

        if len(paths) > max_paths:
            lines.append(f"  ... and {len(paths) - max_paths} more paths")

    return "\n".join(lines)


def extract_test_cases(paths: List[Any]) -> List[Dict[str, Any]]:
    """
    Extract test cases from execution paths

    Args:
        paths: List of execution paths

    Returns:
        List of test case dictionaries
    """
    test_cases = []

    for path in paths:
        if hasattr(path, "test_inputs") and path.test_inputs:
            test_case = {
                "path_id": getattr(path, "path_id", "unknown"),
                "inputs": path.test_inputs.copy(),
                "satisfiable": getattr(path, "satisfiable", True),
            }

            if hasattr(path, "expected_outputs") and path.expected_outputs:
                test_case["expected_outputs"] = path.expected_outputs.copy()

            if hasattr(path, "return_value") and path.return_value is not None:
                test_case["expected_return"] = str(path.return_value)

            test_cases.append(test_case)

    return test_cases


def generate_test_case_report(paths: List[Any]) -> str:
    """
    Generate a report focused on test cases

    Args:
        paths: List of execution paths

    Returns:
        Test case report string
    """
    test_cases = extract_test_cases(paths)

    if not test_cases:
        return "No test cases generated."

    lines = []
    lines.append("Test Cases Generated")
    lines.append("=" * 20)
    lines.append("")

    for i, test_case in enumerate(test_cases, 1):
        lines.append(f"Test Case {i} (Path: {test_case['path_id']})")

        if not test_case["satisfiable"]:
            lines.append("  Status: UNSATISFIABLE (invalid test case)")
            continue

        lines.append("  Inputs:")
        for name, value in test_case["inputs"].items():
            lines.append(f"    {name} = {value}")

        if test_case.get("expected_outputs"):
            lines.append("  Expected outputs:")
            for name, value in test_case["expected_outputs"].items():
                lines.append(f"    {name} = {value}")

        if test_case.get("expected_return"):
            lines.append(f"  Expected return: {test_case['expected_return']}")

        lines.append("")

    return "\n".join(lines)


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
        },
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


def path_to_dict(path: Any) -> Dict[str, Any]:
    """Convert a path object to dictionary format"""
    if hasattr(path, "to_dict"):
        return path.to_dict()

    # Fallback manual conversion
    path_dict = {
        "path_id": getattr(path, "path_id", "unknown"),
        "conditions": [str(c) for c in getattr(path, "conditions", [])],
        "statements": list(getattr(path, "statements", [])),
        "return_value": str(getattr(path, "return_value", None))
        if getattr(path, "return_value", None) is not None
        else None,
        "variables": {str(k): str(v) for k, v in getattr(path, "variables", {}).items()},
        "satisfiable": getattr(path, "satisfiable", True),
        "loop_iterations": getattr(path, "loop_iterations", {}),
        "test_inputs": getattr(path, "test_inputs", {}),
        "expected_outputs": getattr(path, "expected_outputs", {}),
        "z3_error": getattr(path, "z3_error", None),
    }
    return path_dict


def _convert_z3_value_to_python(z3_value) -> Any:
    """Convert Z3 value to Python value with proper error handling"""
    if not Z3_AVAILABLE:
        return str(z3_value)

    try:
        import z3

        if z3.is_int_value(z3_value):
            return z3_value.as_long()
        elif z3.is_rational_value(z3_value):
            # Use as_decimal for rational values
            return float(z3_value.as_decimal(10))
        elif z3.is_true(z3_value):
            return True
        elif z3.is_false(z3_value):
            return False
        else:
            return str(z3_value)
    except (AttributeError, ValueError):
        return str(z3_value)


def _create_enhanced_path(
    path: Any, satisfiable: bool, test_inputs: Optional[Dict], expected_outputs: Dict
) -> Any:
    """Create an enhanced path object with test case information"""
    # Create enhanced path data
    enhanced_path = type(path)(getattr(path, "path_id", "unknown"))

    # Copy basic attributes
    if hasattr(path, "conditions"):
        enhanced_path.conditions = path.conditions.copy()
    if hasattr(path, "statements"):
        enhanced_path.statements = path.statements.copy()
    if hasattr(path, "return_value"):
        enhanced_path.return_value = path.return_value
    if hasattr(path, "variables"):
        enhanced_path.variables = path.variables.copy()
    if hasattr(path, "loop_iterations"):
        enhanced_path.loop_iterations = path.loop_iterations.copy()

    # Set new attributes
    enhanced_path.satisfiable = satisfiable
    enhanced_path.test_inputs = (
        test_inputs if test_inputs is not None else ({} if satisfiable else None)
    )
    enhanced_path.expected_outputs = expected_outputs if satisfiable else None

    return enhanced_path


def _solve_path_constraints(path: Any) -> tuple[bool, Optional[Dict[str, Any]]]:
    """Solve path constraints using Z3 and return satisfiability and test inputs"""
    if not Z3_AVAILABLE:
        return True, {}  # Assume satisfiable if Z3 not available

    conditions = getattr(path, "conditions", [])
    if not conditions:
        return True, {}

    try:
        import z3

        solver = z3.Solver()
        var_map = {}

        # Convert conditions to Z3 constraints
        for condition in conditions:
            try:
                z3_constraint = condition_to_z3(condition, var_map, solver)
                if z3_constraint is not None:
                    solver.add(z3_constraint)
            except Exception:
                # Skip problematic conditions but continue processing
                continue

        # Check satisfiability
        if solver.check() == z3.sat:
            model = solver.model()
            test_inputs = {}

            # Extract concrete values from the model
            for var_name, z3_var in var_map.items():
                if model[z3_var] is not None:
                    value = model[z3_var]
                    test_inputs[var_name] = _convert_z3_value_to_python(value)

            return True, test_inputs
        else:
            return False, None

    except Exception:
        # If Z3 processing fails, assume satisfiable
        return True, {}


def enhance_paths_with_z3_test_cases(paths: List[Any]) -> List[Any]:
    """Enhance execution paths with Z3-generated test case information"""
    if not Z3_AVAILABLE:
        # Just return paths with a note that Z3 is not available
        for path in paths:
            if not hasattr(path, "z3_error") or getattr(path, "z3_error", None) is None:
                path.z3_error = (
                    "Z3 solver not available. Install with: pip install z3-solver"
                )
        return paths

    enhanced_paths = []

    for path in paths:
        expected_outputs = extract_outputs_from_path(path)
        satisfiable, test_inputs = _solve_path_constraints(path)
        enhanced_path = _create_enhanced_path(
            path, satisfiable, test_inputs, expected_outputs
        )
        enhanced_paths.append(enhanced_path)

    return enhanced_paths


def extract_outputs_from_path(path: Any) -> Dict[str, Any]:
    """Extract expected outputs from a path"""
    outputs = {}

    return_value = getattr(path, "return_value", None)
    if return_value:
        outputs["return_value"] = str(return_value)

    statements = getattr(path, "statements", [])
    print_outputs = [stmt for stmt in statements if "print(" in stmt]
    if print_outputs:
        outputs["print_statements"] = print_outputs

    variables = getattr(path, "variables", {})
    if variables:
        outputs["final_variables"] = {str(k): str(v) for k, v in variables.items()}

    loop_iterations = getattr(path, "loop_iterations", {})
    if loop_iterations:
        outputs["loop_iterations"] = loop_iterations

    return outputs


def renumber_paths_sequentially(paths: List[Any]) -> List[Any]:
    """Renumber paths sequentially starting from 1"""
    for i, path in enumerate(paths, 1):
        if hasattr(path, "path_id"):
            path.path_id = f"path_{i}"
    return paths
