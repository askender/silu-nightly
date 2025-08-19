#!/usr/bin/env python3
"""
Command line interface for the Silu interpreter and IR generator.
"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

from silu.interpreter import SiluInterpreter
from silu.ir_generator import SiluIRGenerator


def read_source_file(file_path: str) -> str:
    """Read source code from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error reading file '{file_path}': {e}", file=sys.stderr)
        sys.exit(1)


def format_ir_output(ir_result: Any, output_format: str) -> str:
    """Format IR result according to the specified output format."""
    if output_format == "json":
        return json.dumps(ir_result, indent=2, default=str)
    elif output_format == "pretty":
        import pprint
        return pprint.pformat(ir_result, width=80, depth=None)
    elif output_format == "compact":
        return str(ir_result)
    else:
        raise ValueError(f"Unsupported output format: {output_format}")


def run_interpreter(source_code: str, **kwargs) -> None:
    """Run the interpreter on the source code."""
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter(**kwargs)
        interpreter.visit(tree)
    except SyntaxError as e:
        print(f"Syntax Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Runtime Error: {e}", file=sys.stderr)
        sys.exit(1)


def generate_ir(source_code: str, output_format: str = "pretty", **kwargs) -> None:
    """Generate IR from the source code."""
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator(**kwargs)
        ir_result = ir_generator.visit(tree)

        formatted_output = format_ir_output(ir_result, output_format)
        print(formatted_output)
    except SyntaxError as e:
        print(f"Syntax Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"IR Generation Error: {e}", file=sys.stderr)
        sys.exit(1)


def save_ir_to_file(ir_result: Any, output_file: str, output_format: str) -> None:
    """Save IR result to a file."""
    try:
        formatted_output = format_ir_output(ir_result, output_format)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(formatted_output)
        print(f"IR saved to: {output_file}")
    except IOError as e:
        print(f"Error writing to file '{output_file}': {e}", file=sys.stderr)
        sys.exit(1)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Silu Language Processor - Interpreter and IR Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interpret a Silu program (traditional usage)
  %(prog)s program.si

  # Interpret a Silu program (explicit)
  %(prog)s interpret program.si

  # Generate IR in pretty format
  %(prog)s ir program.si

  # Generate IR in JSON format
  %(prog)s ir program.si --format json

  # Save IR to file
  %(prog)s ir program.si --output program.ir.json --format json

  # Process source code directly
  %(prog)s interpret --source "x = 5; print(x)"
        """,
    )

    # Add subcommands
    subparsers = parser.add_subparsers(dest="mode", help="Processing mode")

    # Interpreter subcommand
    interpret_parser = subparsers.add_parser(
        "interpret", help="Interpret and execute Silu code"
    )
    interpret_parser.add_argument(
        "file", nargs="?", help="Silu source file to interpret"
    )
    interpret_parser.add_argument(
        "--source", help="Source code string to interpret (alternative to file)"
    )
    interpret_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose output"
    )

    # IR generation subcommand
    ir_parser = subparsers.add_parser("ir", help="Generate intermediate representation")
    ir_parser.add_argument("file", nargs="?", help="Silu source file to process")
    ir_parser.add_argument(
        "--source", help="Source code string to process (alternative to file)"
    )
    ir_parser.add_argument(
        "--format",
        choices=["pretty", "json", "compact"],
        default="pretty",
        help="Output format for IR (default: pretty)",
    )
    ir_parser.add_argument(
        "--output", "-o", help="Output file to save IR (default: stdout)"
    )
    ir_parser.add_argument(
        "--no-types",
        action="store_true",
        help="Disable type information recording in IR",
    )

    return parser


def validate_arguments(args) -> None:
    """Validate command line arguments."""
    if not args.file and not args.source:
        print(
            "Error: Either a source file or --source must be provided.", file=sys.stderr
        )
        sys.exit(1)

    if args.file and args.source:
        print("Error: Cannot specify both file and --source.", file=sys.stderr)
        sys.exit(1)

    if args.file and not Path(args.file).exists():
        print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
        sys.exit(1)


def handle_legacy_usage(args) -> bool:
    """Handle legacy usage: silu file.si (interpret directly)."""
    # Check if it's legacy usage: exactly 2 args, second arg is not a subcommand
    if len(sys.argv) == 2 and not sys.argv[1].startswith('-') and sys.argv[1] not in ['interpret', 'ir']:
        filename = sys.argv[1]
        try:
            source_code = read_source_file(filename)
            run_interpreter(source_code)
        except KeyboardInterrupt:
            print("\nInterrupted by user.", file=sys.stderr)
            sys.exit(1)
        return True
    return False


def main() -> None:
    """Main entry point for the Silu CLI."""
    # Handle legacy usage first (backward compatibility)
    if handle_legacy_usage(sys.argv):
        return

    parser = create_parser()

    # If no arguments provided, show help
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    # If no mode specified, show help
    if not args.mode:
        parser.print_help()
        sys.exit(1)

    # Validate arguments
    validate_arguments(args)

    # Get source code
    if args.file:
        source_code = read_source_file(args.file)
        source_name = args.file
    else:
        source_code = args.source
        source_name = "<string>"

    if not source_code.strip():
        print("Error: Source code is empty.", file=sys.stderr)
        sys.exit(1)

    # Process based on mode
    try:
        if args.mode == "interpret":
            if hasattr(args, "debug") and args.debug:
                print(f"Interpreting {source_name} (debug mode)...", file=sys.stderr)

            run_interpreter(source_code)

        elif args.mode == "ir":
            # Prepare kwargs for IR generator
            ir_kwargs = {"record_types": not getattr(args, "no_types", False)}

            if hasattr(args, "output") and args.output:
                # Generate IR and save to file
                tree = ast.parse(source_code)
                ir_generator = SiluIRGenerator(**ir_kwargs)
                ir_result = ir_generator.visit(tree)
                save_ir_to_file(ir_result, args.output, args.format)
            else:
                # Generate IR and print to stdout
                generate_ir(source_code, args.format, **ir_kwargs)

    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if hasattr(args, "debug") and getattr(args, "debug", False):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
