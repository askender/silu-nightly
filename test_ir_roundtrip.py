#!/usr/bin/env python3
"""
IR Round-trip Consistency Testing Tool

This tool tests the consistency of Silu's IR conversion by:
1. Reading a Python file
2. Converting it to IR
3. Converting the IR back to Python code
4. Comparing the original and generated code (ignoring comments and blank lines)
"""

import ast
import json
import sys
import argparse
from pathlib import Path

# Import Silu modules
try:
    from silu.ir_generator import SiluIRGenerator
    from silu.ir_to_source import convert_ir_string_to_source
except ImportError:
    print(
        "Error: Cannot import Silu modules. Make sure you're in the silu directory and it's installed.",
        file=sys.stderr,
    )
    sys.exit(1)


def normalize_code(code: str) -> str:
    """
    Normalize Python code by removing comments, blank lines, and extra whitespace.

    Args:
        code: Python source code string

    Returns:
        Normalized code string
    """
    lines = []
    for line in code.split("\n"):
        # Remove comments (but preserve strings that might contain #)
        # This is a simple approach - for more robust comment removal,
        # we'd need to parse the code properly
        line_stripped = line.strip()

        # Skip empty lines
        if not line_stripped:
            continue

        # Simple comment removal (doesn't handle # in strings perfectly, but good enough for testing)
        if "#" in line_stripped and not ('"' in line_stripped or "'" in line_stripped):
            # Find the # that's not in a string
            comment_pos = line_stripped.find("#")
            # Simple heuristic: if # appears before any quotes, it's likely a comment
            quote_pos_single = line_stripped.find("'")
            quote_pos_double = line_stripped.find('"')

            if quote_pos_single == -1:
                quote_pos_single = float("inf")
            if quote_pos_double == -1:
                quote_pos_double = float("inf")

            min_quote_pos = min(quote_pos_single, quote_pos_double)

            if comment_pos < min_quote_pos:
                line_stripped = line_stripped[:comment_pos].strip()
                if not line_stripped:
                    continue

        lines.append(line_stripped)

    return "\n".join(lines)


def advanced_normalize_code(code: str) -> str:
    """
    More robust code normalization using AST parsing.
    This preserves the semantic structure while removing comments and formatting differences.

    Args:
        code: Python source code string

    Returns:
        Normalized code string
    """
    try:
        # Parse the code into an AST
        tree = ast.parse(code)

        # Convert back to source code (this removes comments and normalizes formatting)
        normalized = ast.unparse(tree)

        # Remove extra blank lines
        lines = []
        for line in normalized.split("\n"):
            line_stripped = line.strip()
            if line_stripped:  # Only keep non-empty lines
                lines.append(line_stripped)

        return "\n".join(lines)

    except Exception as e:
        print(
            f"Warning: Could not use AST normalization ({e}), falling back to simple normalization",
            file=sys.stderr,
        )
        return normalize_code(code)


def python_to_ir(source_code: str, output_format: str = "json") -> str:
    """
    Convert Python source code to Silu IR.

    Args:
        source_code: Python source code string
        output_format: Output format ("json" or "pretty")

    Returns:
        IR representation as string
    """
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        if output_format == "json":
            return json.dumps(ir_result, indent=2)
        else:
            return str(ir_result)

    except Exception as e:
        raise RuntimeError(f"Error converting Python to IR: {e}")


def ir_to_python(ir_string: str) -> str:
    """
    Convert Silu IR to Python source code.

    Args:
        ir_string: IR representation as string

    Returns:
        Python source code string
    """
    try:
        return convert_ir_string_to_source(ir_string)
    except Exception as e:
        raise RuntimeError(f"Error converting IR to Python: {e}")


def test_roundtrip_consistency(
    file_path: str, verbose: bool = False, use_ast_normalize: bool = True
) -> bool:
    """
    Test round-trip consistency for a Python file.

    Args:
        file_path: Path to Python file to test
        verbose: Whether to show detailed output
        use_ast_normalize: Whether to use AST-based normalization

    Returns:
        True if round-trip is consistent, False otherwise
    """
    try:
        # Read original file
        with open(file_path, "r", encoding="utf-8") as f:
            original_code = f.read()

        if verbose:
            print(f"Testing file: {file_path}")
            print("=" * 50)

        # Step 1: Python -> IR
        if verbose:
            print("Step 1: Converting Python to IR...")
        ir_string = python_to_ir(original_code, "json")

        if verbose:
            print("IR generated successfully")
            print("IR preview (first 200 chars):")
            print(ir_string[:200] + "..." if len(ir_string) > 200 else ir_string)
            print()

        # Step 2: IR -> Python
        if verbose:
            print("Step 2: Converting IR back to Python...")
        generated_code = ir_to_python(ir_string)

        if verbose:
            print("Python code generated successfully")
            print()

        # Step 3: Normalize and compare
        if verbose:
            print("Step 3: Normalizing and comparing codes...")

        normalize_func = (
            advanced_normalize_code if use_ast_normalize else normalize_code
        )

        normalized_original = normalize_func(original_code)
        normalized_generated = normalize_func(generated_code)

        if verbose:
            print("Original code (normalized):")
            print("-" * 30)
            print(normalized_original)
            print()
            print("Generated code (normalized):")
            print("-" * 30)
            print(normalized_generated)
            print()

        # Compare
        is_consistent = normalized_original == normalized_generated

        if verbose:
            if is_consistent:
                print("✅ CONSISTENT: Round-trip conversion successful!")
            else:
                print("❌ INCONSISTENT: Round-trip conversion failed!")
                print("\nDifferences found:")
                print("=" * 40)

                # Show line-by-line differences
                orig_lines = normalized_original.split("\n")
                gen_lines = normalized_generated.split("\n")

                max_lines = max(len(orig_lines), len(gen_lines))
                for i in range(max_lines):
                    orig_line = orig_lines[i] if i < len(orig_lines) else "<missing>"
                    gen_line = gen_lines[i] if i < len(gen_lines) else "<missing>"

                    if orig_line != gen_line:
                        print(f"Line {i + 1}:")
                        print(f"  Original: {repr(orig_line)}")
                        print(f"  Generated: {repr(gen_line)}")

        return is_consistent

    except Exception as e:
        if verbose:
            print(f"❌ ERROR: {e}")
        else:
            print(f"Error testing {file_path}: {e}", file=sys.stderr)
        return False


def main():
    """Main function to handle command line arguments and run tests."""
    parser = argparse.ArgumentParser(
        description="Test Silu IR round-trip consistency",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_ir_roundtrip.py example.py
  python test_ir_roundtrip.py example.py --verbose
  python test_ir_roundtrip.py example1.py example2.py --no-ast-normalize
  python test_ir_roundtrip.py examples/*.py
        """,
    )

    parser.add_argument("files", nargs="+", help="Python files to test")

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed output"
    )

    parser.add_argument(
        "--no-ast-normalize",
        action="store_true",
        help="Use simple normalization instead of AST-based normalization",
    )

    parser.add_argument(
        "--summary", action="store_true", help="Show summary of results at the end"
    )

    args = parser.parse_args()

    # Process files
    results = {}
    total_files = 0
    passed_files = 0

    for file_pattern in args.files:
        # Handle glob patterns
        if "*" in file_pattern or "?" in file_pattern:
            from glob import glob

            files = glob(file_pattern)
            if not files:
                print(
                    f"Warning: No files found matching pattern '{file_pattern}'",
                    file=sys.stderr,
                )
                continue
        else:
            files = [file_pattern]

        for file_path in files:
            if not Path(file_path).exists():
                print(f"Error: File not found: {file_path}", file=sys.stderr)
                continue

            if not file_path.endswith(".py"):
                print(
                    f"Warning: Skipping non-Python file: {file_path}", file=sys.stderr
                )
                continue

            total_files += 1

            is_consistent = test_roundtrip_consistency(
                file_path,
                verbose=args.verbose,
                use_ast_normalize=not args.no_ast_normalize,
            )

            results[file_path] = is_consistent
            if is_consistent:
                passed_files += 1
                if not args.verbose:
                    print(f"✅ {file_path}: CONSISTENT")
            else:
                if not args.verbose:
                    print(f"❌ {file_path}: INCONSISTENT")

            if args.verbose and len(files) > 1:
                print("\n" + "=" * 60 + "\n")

    # Show summary if requested or if testing multiple files
    if args.summary or total_files > 1:
        print(f"\n{'=' * 50}")
        print("SUMMARY")
        print(f"{'=' * 50}")
        print(f"Total files tested: {total_files}")
        print(f"Consistent: {passed_files}")
        print(f"Inconsistent: {total_files - passed_files}")
        print(
            f"Success rate: {passed_files / total_files * 100:.1f}%"
            if total_files > 0
            else "N/A"
        )

        if total_files > 0 and passed_files < total_files:
            print("\nFiles with issues:")
            for file_path, is_consistent in results.items():
                if not is_consistent:
                    print(f"  - {file_path}")

    # Exit with appropriate code
    sys.exit(0 if passed_files == total_files else 1)


if __name__ == "__main__":
    main()
