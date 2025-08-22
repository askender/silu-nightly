#!/usr/bin/env python3
"""
Python vs Silu Execution Comparison Tool

This tool compares the execution results of Python files between the standard
Python interpreter and the Silu interpreter. It can be used to verify
compatibility and identify differences in behavior.
"""

import ast
import subprocess
import sys
import argparse
import io
import contextlib
import tempfile
from pathlib import Path
from typing import Tuple, Optional, Dict, Any
import re

# Import Silu modules
try:
    from silu.interpreter import SiluInterpreter
except ImportError:
    print("Error: Cannot import Silu modules. Make sure you're in the silu directory and it's installed.", file=sys.stderr)
    sys.exit(1)


class ExecutionResult:
    """Represents the result of executing a Python program."""

    def __init__(self, success: bool, output: str, error: str, exit_code: int = 0):
        self.success = success
        self.output = output.strip()
        self.error = error.strip()
        self.exit_code = exit_code

    def __str__(self) -> str:
        if self.success:
            return f"SUCCESS: {repr(self.output)}"
        else:
            return f"ERROR ({self.exit_code}): {repr(self.error)}"

    def __eq__(self, other) -> bool:
        if not isinstance(other, ExecutionResult):
            return False
        return (self.success == other.success and
                self.output == other.output and
                self.error == other.error)

    def normalize_output(self, normalize_line_endings: bool = False) -> 'ExecutionResult':
        """Return a new ExecutionResult with normalized output."""
        output = self.output
        error = self.error

        if normalize_line_endings:
            # Normalize line endings: convert \r to \n and \r\n to \n
            output = re.sub(r'\r\n?', '\n', output)
            error = re.sub(r'\r\n?', '\n', error)

        return ExecutionResult(self.success, output, error, self.exit_code)


def execute_with_python(source_code: str, timeout: int = 30) -> ExecutionResult:
    """
    Execute Python code using the standard Python interpreter.

    Args:
        source_code: Python source code to execute
        timeout: Timeout in seconds

    Returns:
        ExecutionResult with execution details
    """
    try:
        # Create a temporary file to avoid shell injection issues
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(source_code)
            temp_file = f.name

        try:
            # Execute the Python file
            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode
            )

        finally:
            # Clean up temporary file
            Path(temp_file).unlink(missing_ok=True)

    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            output="",
            error="Execution timed out",
            exit_code=-1
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Failed to execute: {e}",
            exit_code=-1
        )


def execute_with_silu(source_code: str, **kwargs) -> ExecutionResult:
    """
    Execute Python code using the Silu interpreter.

    Args:
        source_code: Python source code to execute
        **kwargs: Additional arguments for SiluInterpreter

    Returns:
        ExecutionResult with execution details
    """
    try:
        # Parse the source code
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter(**kwargs)

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        with contextlib.redirect_stdout(stdout_capture), \
             contextlib.redirect_stderr(stderr_capture):
            interpreter.visit(tree)

        return ExecutionResult(
            success=True,
            output=stdout_capture.getvalue(),
            error=stderr_capture.getvalue(),
            exit_code=0
        )

    except SyntaxError as e:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Syntax Error: {e}",
            exit_code=1
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            output="",
            error=f"Runtime Error: {e}",
            exit_code=1
        )


def compare_execution_results(python_result: ExecutionResult, silu_result: ExecutionResult,
                            normalize_line_endings: bool = False) -> Dict[str, Any]:
    """
    Compare execution results between Python and Silu interpreters.

    Args:
        python_result: Result from Python interpreter
        silu_result: Result from Silu interpreter

    Returns:
        Dictionary with comparison details
    """
    # Optionally normalize line endings for comparison
    if normalize_line_endings:
        python_normalized = python_result.normalize_output(True)
        silu_normalized = silu_result.normalize_output(True)
    else:
        python_normalized = python_result
        silu_normalized = silu_result

    comparison = {
        'match': python_normalized == silu_normalized,
        'python': python_result,
        'silu': silu_result,
        'normalized': normalize_line_endings,
        'differences': {}
    }

    # Detailed difference analysis
    if not comparison['match']:
        if python_normalized.success != silu_normalized.success:
            comparison['differences']['success'] = {
                'python': python_result.success,
                'silu': silu_result.success
            }

        if python_normalized.output != silu_normalized.output:
            comparison['differences']['output'] = {
                'python': python_result.output,
                'silu': silu_result.output
            }

            # If normalization was used, also show the normalized versions
            if normalize_line_endings:
                comparison['differences']['output_normalized'] = {
                    'python': python_normalized.output,
                    'silu': silu_normalized.output
                }

        if python_normalized.error != silu_normalized.error:
            comparison['differences']['error'] = {
                'python': python_result.error,
                'silu': silu_result.error
            }

            # If normalization was used, also show the normalized versions
            if normalize_line_endings:
                comparison['differences']['error_normalized'] = {
                    'python': python_normalized.error,
                    'silu': silu_normalized.error
                }

        if python_normalized.exit_code != silu_normalized.exit_code:
            comparison['differences']['exit_code'] = {
                'python': python_result.exit_code,
                'silu': silu_result.exit_code
            }

    return comparison


def test_file_compatibility(file_path: str, verbose: bool = False, timeout: int = 30,
                          normalize_line_endings: bool = False, **kwargs) -> bool:
    """
    Test a Python file for compatibility between Python and Silu interpreters.

    Args:
        file_path: Path to Python file to test
        verbose: Whether to show detailed output
        timeout: Timeout for Python execution
        normalize_line_endings: Whether to normalize \r and \n differences
        **kwargs: Additional arguments for SiluInterpreter

    Returns:
        True if execution results match, False otherwise
    """
    try:
        # Read the source file
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()

        if verbose:
            print(f"Testing file: {file_path}")
            print("=" * 50)

        # Execute with both interpreters
        if verbose:
            print("Executing with Python interpreter...")
        python_result = execute_with_python(source_code, timeout)

        if verbose:
            print("Executing with Silu interpreter...")
        silu_result = execute_with_silu(source_code, **kwargs)

        # Compare results
        comparison = compare_execution_results(python_result, silu_result, normalize_line_endings)

        if verbose:
            print("\nExecution Results:")
            print("-" * 30)
            print(f"Python: {python_result}")
            print(f"Silu:   {silu_result}")
            print()

            if comparison['match']:
                match_msg = "✅ MATCH: Both interpreters produced identical results!"
                if comparison['normalized']:
                    match_msg += " (after line ending normalization)"
                print(match_msg)
            else:
                mismatch_msg = "❌ MISMATCH: Different execution results detected!"
                if comparison['normalized']:
                    mismatch_msg += " (even after line ending normalization)"
                print(mismatch_msg)
                print("\nDifferences:")
                for key, diff in comparison['differences'].items():
                    if key.endswith('_normalized'):
                        print(f"  {key} (after normalization):")
                    else:
                        print(f"  {key}:")
                    if isinstance(diff, dict) and 'python' in diff and 'silu' in diff:
                        print(f"    Python: {repr(diff['python'])}")
                        print(f"    Silu:   {repr(diff['silu'])}")
                    else:
                        print(f"    Value: {repr(diff)}")

                # Show line ending analysis if there are output differences
                if 'output' in comparison['differences'] and not comparison['normalized']:
                    python_has_cr = '\r' in python_result.output
                    silu_has_cr = '\r' in silu_result.output
                    if python_has_cr or silu_has_cr:
                        print(f"\n  Line ending analysis:")
                        print(f"    Python output contains \\r: {python_has_cr}")
                        print(f"    Silu output contains \\r:   {silu_has_cr}")
                        print(f"    Note: Try --normalize-line-endings to ignore these differences")

        return comparison['match']

    except FileNotFoundError:
        error_msg = f"Error: File not found: {file_path}"
        if verbose:
            print(f"❌ {error_msg}")
        else:
            print(error_msg, file=sys.stderr)
        return False
    except Exception as e:
        error_msg = f"Error testing {file_path}: {e}"
        if verbose:
            print(f"❌ {error_msg}")
        else:
            print(error_msg, file=sys.stderr)
        return False


def main():
    """Main function to handle command line arguments and run comparisons."""
    parser = argparse.ArgumentParser(
        description="Compare Python vs Silu interpreter execution results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compare_execution.py example.py
  python compare_execution.py example.py --verbose
  python compare_execution.py example1.py example2.py --timeout 60
  python compare_execution.py examples/*.py --summary
  python compare_execution.py test.py --debug --verbose
        """
    )

    parser.add_argument(
        'files',
        nargs='+',
        help='Python files to test'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed output for each file'
    )

    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='Timeout for Python execution in seconds (default: 30)'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode for Silu interpreter'
    )

    parser.add_argument(
        '--normalize-line-endings',
        action='store_true',
        help='Normalize line ending differences (\\r vs \\n) when comparing outputs'
    )

    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show summary of results at the end'
    )

    args = parser.parse_args()

    # Prepare kwargs for Silu interpreter
    silu_kwargs = {}
    if args.debug:
        silu_kwargs['debug'] = True

    # Process files
    results = {}
    total_files = 0
    matching_files = 0

    for file_pattern in args.files:
        # Handle glob patterns
        if '*' in file_pattern or '?' in file_pattern:
            from glob import glob
            files = glob(file_pattern)
            if not files:
                print(f"Warning: No files found matching pattern '{file_pattern}'", file=sys.stderr)
                continue
        else:
            files = [file_pattern]

        for file_path in files:
            if not Path(file_path).exists():
                print(f"Error: File not found: {file_path}", file=sys.stderr)
                continue

            if not file_path.endswith('.py'):
                print(f"Warning: Skipping non-Python file: {file_path}", file=sys.stderr)
                continue

            total_files += 1

            is_matching = test_file_compatibility(
                file_path,
                verbose=args.verbose,
                timeout=args.timeout,
                normalize_line_endings=args.normalize_line_endings,
                **silu_kwargs
            )

            results[file_path] = is_matching
            if is_matching:
                matching_files += 1
                if not args.verbose:
                    print(f"✅ {file_path}: MATCH")
            else:
                if not args.verbose:
                    print(f"❌ {file_path}: MISMATCH")

            if args.verbose and len(files) > 1:
                print("\n" + "=" * 60 + "\n")

    # Show summary if requested or if testing multiple files
    if args.summary or total_files > 1:
        print(f"\n{'=' * 50}")
        print(f"COMPARISON SUMMARY")
        print(f"{'=' * 50}")
        print(f"Total files tested: {total_files}")
        print(f"Matching results: {matching_files}")
        print(f"Different results: {total_files - matching_files}")
        print(f"Compatibility rate: {matching_files/total_files*100:.1f}%" if total_files > 0 else "N/A")

        if total_files > 0 and matching_files < total_files:
            print(f"\nFiles with different results:")
            for file_path, is_matching in results.items():
                if not is_matching:
                    print(f"  - {file_path}")

    # Exit with appropriate code
    sys.exit(0 if matching_files == total_files else 1)


if __name__ == '__main__':
    main()
