#!/usr/bin/env python3
"""
Report Generation Utilities for Symbolic Execution

This module provides utilities for generating reports and summaries from
symbolic execution results, including path analysis and test case generation.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
import json


class ReportFormat(Enum):
    """Supported report formats"""
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


def generate_execution_summary(paths: List[Any], total_time: float = 0.0) -> Dict[str, Any]:
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
            'total_paths': 0,
            'satisfiable_paths': 0,
            'unsatisfiable_paths': 0,
            'execution_time': total_time,
            'coverage_info': {}
        }

    satisfiable_count = 0
    unsatisfiable_count = 0
    total_conditions = 0
    total_statements = 0
    variables_seen = set()

    for path in paths:
        # Count satisfiable vs unsatisfiable paths
        if hasattr(path, 'satisfiable'):
            if path.satisfiable:
                satisfiable_count += 1
            else:
                unsatisfiable_count += 1
        else:
            # Assume satisfiable if not specified
            satisfiable_count += 1

        # Collect statistics
        if hasattr(path, 'conditions'):
            total_conditions += len(path.conditions)

        if hasattr(path, 'statements'):
            total_statements += len(path.statements)

        if hasattr(path, 'variables'):
            variables_seen.update(path.variables.keys())

    return {
        'total_paths': len(paths),
        'satisfiable_paths': satisfiable_count,
        'unsatisfiable_paths': unsatisfiable_count,
        'total_conditions': total_conditions,
        'total_statements': total_statements,
        'unique_variables': len(variables_seen),
        'variables': list(variables_seen),
        'execution_time': total_time,
        'avg_conditions_per_path': total_conditions / len(paths) if paths else 0,
        'avg_statements_per_path': total_statements / len(paths) if paths else 0
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
        if hasattr(condition, '__str__'):
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
        if hasattr(value, '__str__'):
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
        'path_id': getattr(path, 'path_id', f'path_{path_index + 1}'),
        'path_index': path_index,
        'satisfiable': getattr(path, 'satisfiable', True)
    }

    # Add conditions
    if hasattr(path, 'conditions'):
        report['conditions'] = format_path_conditions(path.conditions)
        report['condition_count'] = len(path.conditions)
    else:
        report['conditions'] = []
        report['condition_count'] = 0

    # Add statements
    if hasattr(path, 'statements'):
        report['statements'] = list(path.statements) if path.statements else []
        report['statement_count'] = len(path.statements)
    else:
        report['statements'] = []
        report['statement_count'] = 0

    # Add variables
    if hasattr(path, 'variables'):
        report['variables'] = format_path_variables(path.variables)
        report['variable_count'] = len(path.variables)
    else:
        report['variables'] = {}
        report['variable_count'] = 0

    # Add return value
    if hasattr(path, 'return_value'):
        report['return_value'] = str(path.return_value) if path.return_value is not None else None

    # Add loop iterations
    if hasattr(path, 'loop_iterations'):
        report['loop_iterations'] = path.loop_iterations

    # Add test case information
    if hasattr(path, 'test_inputs'):
        report['test_inputs'] = path.test_inputs

    if hasattr(path, 'expected_outputs'):
        report['expected_outputs'] = path.expected_outputs

    # Add Z3 error information if present
    if hasattr(path, 'z3_error'):
        report['z3_error'] = path.z3_error

    return report


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
    lines.append("EXECUTION SUMMARY")
    lines.append("-" * 20)
    lines.append(f"Total paths: {summary['total_paths']}")
    lines.append(f"Satisfiable paths: {summary['satisfiable_paths']}")
    lines.append(f"Unsatisfiable paths: {summary['unsatisfiable_paths']}")
    lines.append(f"Total conditions: {summary['total_conditions']}")
    lines.append(f"Total statements: {summary['total_statements']}")
    lines.append(f"Unique variables: {summary['unique_variables']}")
    if summary['execution_time'] > 0:
        lines.append(f"Execution time: {summary['execution_time']:.3f}s")
    lines.append("")

    # Variables
    if summary.get('variables'):
        lines.append("VARIABLES")
        lines.append("-" * 10)
        for var in sorted(summary['variables']):
            lines.append(f"  {var}")
        lines.append("")

    # Path details
    lines.append("PATH DETAILS")
    lines.append("-" * 15)

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)

        lines.append(f"Path {i + 1}: {path_report['path_id']}")
        if not path_report['satisfiable']:
            lines.append("  Status: UNSATISFIABLE")

        if path_report['conditions']:
            lines.append("  Conditions:")
            for condition in path_report['conditions']:
                lines.append(f"    - {condition}")

        if path_report['variables']:
            lines.append("  Variables:")
            for name, value in path_report['variables'].items():
                lines.append(f"    {name} = {value}")

        if path_report['statements']:
            lines.append("  Statements:")
            for stmt in path_report['statements']:
                lines.append(f"    {stmt}")

        if path_report.get('return_value') is not None:
            lines.append(f"  Return: {path_report['return_value']}")

        if path_report.get('test_inputs'):
            lines.append("  Test inputs:")
            for name, value in path_report['test_inputs'].items():
                lines.append(f"    {name} = {value}")

        lines.append("")

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
    report = {
        'summary': summary,
        'paths': []
    }

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)
        report['paths'].append(path_report)

    return json.dumps(report, indent=2, default=str)


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
    lines.append("## Execution Summary")
    lines.append("")
    lines.append(f"- **Total paths**: {summary['total_paths']}")
    lines.append(f"- **Satisfiable paths**: {summary['satisfiable_paths']}")
    lines.append(f"- **Unsatisfiable paths**: {summary['unsatisfiable_paths']}")
    lines.append(f"- **Total conditions**: {summary['total_conditions']}")
    lines.append(f"- **Total statements**: {summary['total_statements']}")
    lines.append(f"- **Unique variables**: {summary['unique_variables']}")
    if summary['execution_time'] > 0:
        lines.append(f"- **Execution time**: {summary['execution_time']:.3f}s")
    lines.append("")

    # Variables
    if summary.get('variables'):
        lines.append("## Variables")
        lines.append("")
        for var in sorted(summary['variables']):
            lines.append(f"- `{var}`")
        lines.append("")

    # Path details
    lines.append("## Path Details")
    lines.append("")

    for i, path in enumerate(paths):
        path_report = generate_path_report(path, i)

        lines.append(f"### Path {i + 1}: {path_report['path_id']}")
        lines.append("")

        if not path_report['satisfiable']:
            lines.append("**Status**: UNSATISFIABLE")
            lines.append("")

        if path_report['conditions']:
            lines.append("**Conditions**:")
            for condition in path_report['conditions']:
                lines.append(f"- `{condition}`")
            lines.append("")

        if path_report['variables']:
            lines.append("**Variables**:")
            for name, value in path_report['variables'].items():
                lines.append(f"- `{name} = {value}`")
            lines.append("")

        if path_report['statements']:
            lines.append("**Statements**:")
            for stmt in path_report['statements']:
                lines.append(f"- `{stmt}`")
            lines.append("")

        if path_report.get('return_value') is not None:
            lines.append(f"**Return**: `{path_report['return_value']}`")
            lines.append("")

        if path_report.get('test_inputs'):
            lines.append("**Test inputs**:")
            for name, value in path_report['test_inputs'].items():
                lines.append(f"- `{name} = {value}`")
            lines.append("")

    return "\n".join(lines)


def generate_report(paths: List[Any], format_type: ReportFormat = ReportFormat.TEXT,
                   execution_time: float = 0.0) -> str:
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
    lines.append(f"Satisfiable: {summary['satisfiable_paths']}, "
                f"Unsatisfiable: {summary['unsatisfiable_paths']}")

    if summary['unique_variables'] > 0:
        lines.append(f"Variables: {', '.join(sorted(summary.get('variables', [])))}")

    # Show details for first few paths
    if paths:
        lines.append("\nPath details:")
        for i, path in enumerate(paths[:max_paths]):
            path_report = generate_path_report(path, i)
            status = "SAT" if path_report['satisfiable'] else "UNSAT"
            cond_count = path_report['condition_count']
            lines.append(f"  {path_report['path_id']}: {status}, {cond_count} conditions")

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
        if hasattr(path, 'test_inputs') and path.test_inputs:
            test_case = {
                'path_id': getattr(path, 'path_id', 'unknown'),
                'inputs': path.test_inputs.copy(),
                'satisfiable': getattr(path, 'satisfiable', True)
            }

            if hasattr(path, 'expected_outputs') and path.expected_outputs:
                test_case['expected_outputs'] = path.expected_outputs.copy()

            if hasattr(path, 'return_value') and path.return_value is not None:
                test_case['expected_return'] = str(path.return_value)

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

        if not test_case['satisfiable']:
            lines.append("  Status: UNSATISFIABLE (invalid test case)")
            continue

        lines.append("  Inputs:")
        for name, value in test_case['inputs'].items():
            lines.append(f"    {name} = {value}")

        if test_case.get('expected_outputs'):
            lines.append("  Expected outputs:")
            for name, value in test_case['expected_outputs'].items():
                lines.append(f"    {name} = {value}")

        if test_case.get('expected_return'):
            lines.append(f"  Expected return: {test_case['expected_return']}")

        lines.append("")

    return "\n".join(lines)
