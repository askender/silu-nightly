#!/usr/bin/env python3
"""
Command line interface for the Silu interpreter and IR generator.
"""

import argparse
import ast  # noqa: F401 - tests patch silu.cli.ast
import json
import os
import sys
import logging
from pathlib import Path
from typing import Any

from silu.ir_generator import SiluIRGenerator
from silu import __version__

# Heavy subcommand dependencies (symbolic chain pulls z3+loguru, ~66ms;
# ir_interpreter/ir_to_source/interpreter add ~15ms) import lazily
# inside their command functions: every CLI invocation runs exactly one
# subcommand, so the others never pay. silu_ir_to_llvm stays module
# level - argparse needs LLVM_AVAILABLE to register build/llvm/verify.

import importlib.util

# Availability probe only: importing the converter pulls the llvmlite
# dylib (~0.1s cold dlopen), which the ir/interpret paths never need.
# The command functions import SiluToLLVMConverter lazily after this
# flag gates them.
LLVM_AVAILABLE = importlib.util.find_spec("llvmlite") is not None

# Setup logging
logger = logging.getLogger(__name__)


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
        from silu.importer import parse_with_imports
        from silu.interpreter import SiluInterpreter

        tree = parse_with_imports(source_code)
        interpreter = SiluInterpreter(**kwargs)
        interpreter.visit(tree)
        # main's return value maps to the process exit code, matching
        # the compiled planes (native driver: exit(main())).  int guard:
        # the AST plane is dynamically typed, and mocked interpreters in
        # tests auto-attribute MagicMock here
        rv = getattr(interpreter, "main_return", 0)
        if isinstance(rv, int) and rv != 0:
            sys.exit(rv)
    except SyntaxError as e:
        print(f"Syntax Error: {e}", file=sys.stderr)
        sys.exit(1)
    except AttributeError as e:
        # Special handling for _fields attribute error which occurs with classes
        # if "'ClassType' object has no attribute '_fields'" in str(e) or "'dict' object has no attribute '_fields'" in str(e):
        #     print("Note: Class feature partially implemented, some operations may not work", file=sys.stderr)
        #     sys.exit(1)
        print(f"Runtime Error: {e}", file=sys.stderr)

        if kwargs.get("debug", False):
            import traceback

            logger.error(traceback.format_exc())

        sys.exit(1)
    except Exception as e:
        print(f"Runtime Error: {e}", file=sys.stderr)
        sys.exit(1)


def check_interpreter_tree(tree, **kwargs) -> tuple[bool, str]:
    """Check whether a prepared module tree interprets cleanly."""
    try:
        from silu.interpreter import SiluInterpreter

        interpreter = SiluInterpreter(**kwargs)
        interpreter.visit(tree)
        return True, ""
    except Exception as e:
        return False, str(e)


def run_check(filename: str) -> None:
    """Check if a file can be interpreted by Silu and print result."""
    try:
        # Read file directly without using read_source_file to avoid sys.exit
        with open(filename, "r", encoding="utf-8") as file:
            source_code = file.read()

        if not source_code.strip():
            print(f"{filename} bad: empty file")
            return

        from silu.importer import expand_imports_tree

        tree = expand_imports_tree(
            source_code, os.path.dirname(os.path.abspath(filename))
        )
        success, error_reason = check_interpreter_tree(tree)
        if success:
            print(f"{filename} ok")
        else:
            print(f"{filename} bad: {error_reason}")
    except FileNotFoundError:
        print(f"{filename} bad: file not found")
    except PermissionError:
        print(f"{filename} bad: permission denied")
    except UnicodeDecodeError:
        print(f"{filename} bad: file encoding error")
    except Exception as e:
        print(f"{filename} bad: {str(e)}")


def generate_ir(source_code: str, output_format: str = "pretty", **kwargs) -> None:
    """Generate IR from source code and print it."""
    try:
        from silu.importer import parse_with_imports

        tree = parse_with_imports(source_code)
        ir_generator = SiluIRGenerator(**kwargs)
        ir_result = ir_generator.visit(tree)

        formatted_output = format_ir_output(ir_result, output_format)
        print(formatted_output)
    except SyntaxError as e:
        print(f"Syntax error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error generating IR: {e}", file=sys.stderr)
        sys.exit(1)


def run_ir_interpreter(ir_source: str, **kwargs) -> None:
    """Run the IR interpreter on IR code."""
    try:
        from silu.ir_interpreter import (
            execute_ir_from_file,
            execute_ir_from_string,
        )

        result = None
        if ir_source.strip().startswith(("[", "(")):
            # Direct IR string
            result = execute_ir_from_string(ir_source)
        else:
            # Treat as filename
            result = execute_ir_from_file(ir_source)

        if result is not None:
            print(result)
    except Exception as e:
        print(f"Error executing IR: {e}", file=sys.stderr)
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


def run_llvm_ir_generator(
    source: str, output_file: str = None, is_file: bool = True, **kwargs
) -> None:
    """Generate LLVM IR from Silu IR."""
    if not LLVM_AVAILABLE:
        print(
            "Error: LLVM IR generation not available. Please install llvmlite.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        if is_file:
            # Read IR from file
            with open(source, "r", encoding="utf-8") as f:
                ir_json = f.read()
        else:
            # Use IR string directly
            ir_json = source

        # Convert to LLVM IR. SILU_CODEGEN=typed (default) uses the
        # statically-typed backend for annotated scalars; "dynamic"
        # restores the original all-PyObject backend.
        codegen_mode = os.environ.get("SILU_CODEGEN", "typed")
        if codegen_mode == "dynamic":
            from silu.silu_ir_to_llvm import SiluToLLVMConverter

            converter = SiluToLLVMConverter()
        else:
            from silu.typed_codegen import TypedCodegen

            converter = TypedCodegen()
        llvm_ir = converter.convert(ir_json)

        if output_file:
            converter.save_to_file(llvm_ir, output_file)
            print(f"LLVM IR saved to: {output_file}")
        else:
            print(llvm_ir)

    except Exception as e:
        print(f"Error generating LLVM IR: {e}", file=sys.stderr)
        sys.exit(1)


def _compile_to_binary(source_file: str, out_path: str,
                       static_only: bool = False) -> None:
    """Silu source -> IR -> LLVM IR -> clang executable.

    Honors SILU_CODEGEN (typed default / dynamic) and SILU_CHECKS the
    same way the step-by-step pipeline does. With static_only, the
    dynamic (pyobj) runtime must go unreferenced - a silent fallback
    to PyObject storage becomes a loud error. Raises on any failure."""
    import json
    import shutil
    import subprocess
    import tempfile

    if not LLVM_AVAILABLE:
        raise RuntimeError("llvmlite is not installed")
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError("clang not found on PATH")

    with open(source_file, "r", encoding="utf-8") as handle:
        source_code = handle.read()
    from silu.importer import expand_imports_tree

    tree = expand_imports_tree(
        source_code, os.path.dirname(os.path.abspath(source_file))
    )
    ir_result = SiluIRGenerator().visit(tree)
    ir_json = json.dumps(ir_result)

    codegen_mode = os.environ.get("SILU_CODEGEN", "typed")
    if codegen_mode == "dynamic":
        from silu.silu_ir_to_llvm import SiluToLLVMConverter

        converter = SiluToLLVMConverter()
    else:
        from silu.typed_codegen import TypedCodegen

        converter = TypedCodegen()
    llvm_ir = converter.convert(ir_json)

    if static_only:
        from silu.static_gate import static_gate_error, static_violations

        violations = static_violations(llvm_ir)
        if violations:
            raise RuntimeError(static_gate_error(violations))

    if os.environ.get("SILU_RUNTIME_CACHE", "") == "1" and \
            codegen_mode != "dynamic":
        # opt-in fast path: the ~350KB pyobj runtime compiles once
        # into a cached .o; per program clang only sees the user part
        from silu import runtime_cache

        runtime_cache.build_with_cache(
            None, out_path, full_text=llvm_ir
        )
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        ll_path = os.path.join(tmpdir, "program.ll")
        with open(ll_path, "w", encoding="utf-8") as handle:
            handle.write(llvm_ir)
        link_flags = (["-Wl,-dead_strip"] if sys.platform == "darwin"
                      else ["-Wl,--gc-sections"])
        result = subprocess.run(
            # Strip unreferenced runtime functions without assuming the
            # macOS-only dead_strip linker flag on Linux.
            [clang, "-O2", ll_path, "-o", out_path, "-lm"] + link_flags,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"clang failed:\n{result.stderr}")


def run_build(source_file: str, output_file: str = None,
              static_only: bool = False, **kwargs) -> None:
    """One-command native build: Silu source -> executable."""
    try:
        out_path = output_file or os.path.splitext(os.path.basename(source_file))[0]
        _compile_to_binary(source_file, out_path, static_only=static_only)
        print(f"Built executable: {out_path}")
    except Exception as e:
        print(f"Error building {source_file}: {e}", file=sys.stderr)
        sys.exit(1)


def run_verify(source_file: str, **kwargs) -> None:
    """Differential verification: run the program under the reference
    interpreter and as a compiled native binary, then diff the output.

    The interpreter defines the language semantics, so any divergence
    is a compiler bug. Exits 0 on match, 1 on mismatch."""
    import subprocess
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            binary = os.path.join(tmpdir, "verify_bin")
            _compile_to_binary(source_file, binary)
            compiled = subprocess.run(
                [binary], capture_output=True, text=True, timeout=300
            )
        interpreted = subprocess.run(
            [sys.executable, "-m", "silu", "interpret", source_file],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as e:
        print(f"Error verifying {source_file}: {e}", file=sys.stderr)
        sys.exit(1)

    if (
        compiled.stdout == interpreted.stdout
        and compiled.returncode == interpreted.returncode
    ):
        print(f"PASS: {source_file} - compiled output matches the interpreter")
        if interpreted.stdout:
            print(interpreted.stdout, end="")
        return

    print(f"FAIL: {source_file} - compiled binary diverges", file=sys.stderr)
    print(
        f"  interpreter (exit {interpreted.returncode}):",
        file=sys.stderr,
    )
    print(f"    {interpreted.stdout!r}", file=sys.stderr)
    if interpreted.stderr:
        print(f"    stderr: {interpreted.stderr!r}", file=sys.stderr)
    print(f"  compiled (exit {compiled.returncode}):", file=sys.stderr)
    print(f"    {compiled.stdout!r}", file=sys.stderr)
    if compiled.stderr:
        print(f"    stderr: {compiled.stderr!r}", file=sys.stderr)
    sys.exit(1)


def run_ir_to_source_converter(
    ir_source: str, output_file: str = None, **kwargs
) -> None:
    """Convert IR to source code."""
    try:
        from silu.ir_to_source import (
            convert_ir_file_to_source,
            convert_ir_string_to_source,
        )

        if ir_source.strip().startswith(("[", "(")):
            # Direct IR string
            source_code = convert_ir_string_to_source(ir_source)
        else:
            # Treat as filename
            source_code = convert_ir_file_to_source(ir_source, output_file)

        if not output_file:
            print(source_code)
        else:
            print(f"Source code saved to: {output_file}")

    except Exception as e:
        print(f"Error converting IR to source: {e}", file=sys.stderr)
        sys.exit(1)


def run_symbolic_executor(
    source: str, is_file: bool = True, **kwargs
) -> dict[str, Any]:
    """Run symbolic execution on source code or IR."""
    debug = kwargs.get("debug", False)
    report = {}
    try:
        from silu.symbolic_executor import SymbolicExecutor
        from silu.symbolic_executor_wrapper import (
            execute_symbolic_from_file_with_executor,
        )

        performance_mode = kwargs.get("performance_mode", False)
        if debug:
            logger.info(
                f"Running symbolic execution on {'file' if is_file else 'source'}: {source}"
            )

        simplify = kwargs.get("simplify", False)
        solve = kwargs.get("solve", False)

        executor = SymbolicExecutor(
            performance_mode=performance_mode,
            debug=debug,
        )

        if is_file:
            # Execute from file
            if source.endswith(".si"):
                # Silu source file - need to convert to IR first
                # TODO
                source_code = read_source_file(source)
                from silu.importer import parse_with_imports

                tree = parse_with_imports(source_code)
                ir_generator = SiluIRGenerator()
                ir_result = ir_generator.visit(tree)
                paths = executor.execute_program(ir_result)
            else:
                # IR file - need to get both paths and function analyses
                ir_executor_result = execute_symbolic_from_file_with_executor(
                    source,
                    performance_mode=performance_mode,
                    debug=debug,
                )
                paths = ir_executor_result.get("paths", [])

                # Handle error in symbolic execution
                if "error" in ir_executor_result:
                    logger.warning(
                        f"Symbolic execution had errors: {ir_executor_result['error']}"
                    )

                # Transfer function analyses from IR executor to main executor
                if "function_analyses" in ir_executor_result:
                    executor.function_analyses = ir_executor_result["function_analyses"]

        else:
            raise ValueError("Invalid input source")
            # Execute from IR string
            # if source.strip().startswith(("[", "(")):
            #     # IR string
            #     ir_executor_result = execute_symbolic_from_string_with_executor(
            #         source,
            #         performance_mode=performance_mode,
            #         debug=debug,
            #     )
            #     paths = ir_executor_result["paths"]
            #     # Transfer function analyses from IR executor to main executor
            #     if "function_analyses" in ir_executor_result:
            #         executor.function_analyses = ir_executor_result["function_analyses"]
            # else:
            #     # Silu source string - convert to IR first
            #     tree = ast.parse(source)
            #     ir_generator = SiluIRGenerator()
            #     ir_result = ir_generator.visit(tree)
            #     paths = executor.execute_program(ir_result)

        # Apply condition simplification if requested
        if simplify:
            if paths:
                paths = executor.simplify_path_conditions(paths)

            # Also simplify function analysis results
            if hasattr(executor, "function_analyses"):
                for func_name, func_paths in executor.function_analyses.items():
                    executor.function_analyses[func_name] = (
                        executor.simplify_path_conditions(func_paths)
                    )

        # Generate and display unified report with optional test cases
        if paths:
            # Enhance paths with test cases if solve option is enabled
            if solve:
                # Also enhance function analyses paths
                if (
                    hasattr(executor, "function_analyses")
                    and executor.function_analyses
                ):
                    for func_name, func_paths in executor.function_analyses.items():
                        if isinstance(func_paths, list) and func_paths:
                            # Process paths before report generation
                            # for path in func_paths:
                            #     if hasattr(path, "clean_test_inputs"):
                            #         path.clean_test_inputs()
                            executor.function_analyses[func_name] = func_paths

            # Generate and print report for all files
            try:
                report = executor.generate_report(paths)
                output = kwargs.get("output", False)
                if debug or not output:
                    print(json.dumps(report, indent=2, default=str))
            except Exception as e:
                logger.error(f"Error generating report: {e}")
                print(f"Error generating report: {e}", file=sys.stderr)
                print(
                    json.dumps({"error": str(e), "paths_count": len(paths)}, indent=2)
                )
        else:
            print("No execution paths found.")
        return report
    except KeyError as ke:
        print(f"Dictionary key error in symbolic execution: {ke}", file=sys.stderr)
        if debug:
            import traceback

            logger.error(traceback.format_exc())
        print(json.dumps({"error": f"KeyError: {ke}"}, indent=2))
    except Exception as e:
        print(f"Error in symbolic execution: {e}", file=sys.stderr)
        if debug:
            import traceback

            logger.error(traceback.format_exc())
        print(json.dumps({"error": str(e)}, indent=2))
    return report


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        prog="silu",
        description="Silu Language Processor - Interpreter, IR Generator, and IR Executor",
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

  # Execute IR directly
  %(prog)s exec program.ir.json

  # Convert IR back to source code
  %(prog)s to-source program.ir.json

  # Convert IR to source and save to file
  %(prog)s to-source program.ir.json --output program_reconstructed.si

  # Symbolic execution of a Silu program
  %(prog)s symbolic program.si

  # Symbolic execution of IR
  %(prog)s symbolic program.ir.json

  # Process source code directly
  %(prog)s interpret --source "x = 5; print(x)"

  # Check if Python code can be interpreted by Silu
  %(prog)s check program.py
  # Output: program.py ok (or program.py bad: reason)
""",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + __version__
    )

    subparsers = parser.add_subparsers(
        dest="mode", help="Processing mode", required=True
    )

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

    # Check subcommand
    check_parser = subparsers.add_parser(
        "check", help="Check if Python code can be interpreted by Silu"
    )
    check_parser.add_argument("file", help="Python source file to check")

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

    # IR execution subcommand
    exec_parser = subparsers.add_parser("exec", help="Execute IR directly")
    exec_parser.add_argument("file", help="IR file to execute")
    exec_parser.add_argument(
        "--source", help="IR string to execute (alternative to file)"
    )
    exec_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose output"
    )

    # IR to source conversion subcommand
    to_source_parser = subparsers.add_parser(
        "to-source", help="Convert IR to source code"
    )
    to_source_parser.add_argument("file", nargs="?", help="IR file to convert")
    to_source_parser.add_argument(
        "--source", help="IR string to convert (alternative to file)"
    )
    to_source_parser.add_argument(
        "--output", "-o", help="Output file to save source code (default: stdout)"
    )

    # LLVM IR generation subcommand
    if LLVM_AVAILABLE:
        llvm_parser = subparsers.add_parser(
            "llvm", help="Generate LLVM IR from Silu IR"
        )
        llvm_parser.add_argument("file", nargs="?", help="Silu IR file to convert")
        llvm_parser.add_argument(
            "--source", help="IR string to convert (alternative to file)"
        )
        llvm_parser.add_argument(
            "--output", "-o", help="Output file to save LLVM IR (default: stdout)"
        )

    # One-command native build subcommand
    if LLVM_AVAILABLE:
        build_parser = subparsers.add_parser(
            "build", help="Compile a Silu source file to a native executable"
        )
        build_parser.add_argument("file", help="Silu source file to compile")
        build_parser.add_argument(
            "--output", "-o", help="Output executable path (default: source basename)"
        )
        build_parser.add_argument(
            "--static", action="store_true",
            help="Refuse programs whose code touches the dynamic (pyobj) "
            "runtime - silent fallback to PyObject storage becomes an error",
        )

    # Differential verification subcommand
    if LLVM_AVAILABLE:
        verify_parser = subparsers.add_parser(
            "verify",
            help="Verify compiled output matches the reference interpreter",
        )
        verify_parser.add_argument("file", help="Silu source file to verify")

    # Panic-free proof subcommand (roadmap Phase 2)
    prove_parser = subparsers.add_parser(
        "prove",
        help="Z3 panic-free proof: can any function abort (div/mod by zero)?",
    )
    prove_parser.add_argument("file", help="Silu source file")

    # One-time self-hosted toolchain build (siluc1 + siluc driver)
    subparsers.add_parser(
        "bootstrap",
        help="Build the zero-Python toolchain (siluc) from this "
        "package's own sources, once (~25s)",
    )

    # Symbolic execution subcommand
    symbolic_parser = subparsers.add_parser(
        "symbolic", help="Perform symbolic execution"
    )
    symbolic_parser.add_argument(
        "file", nargs="?", help="Silu source file or IR file to analyze"
    )
    symbolic_parser.add_argument(
        "--source", help="Source code or IR string to analyze (alternative to file)"
    )
    symbolic_parser.add_argument(
        "--output", "-o", help="Output file to save symbolic execution report"
    )
    symbolic_parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="json",
        help="Output format for the report (default: json)",
    )
    symbolic_parser.add_argument(
        "--simplify",
        action="store_true",
        help="Simplify and merge path conditions where possible",
    )
    symbolic_parser.add_argument(
        "--solve",
        action="store_true",
        help="Use Z3 solver to generate concrete test cases for each execution path",
    )
    symbolic_parser.add_argument(
        "--include-function-paths",
        action="store_true",
        help="Include function internal paths in main path collection (for compatibility with original behavior)",
    )
    symbolic_parser.add_argument(
        "--performance-mode",
        action="store_true",
        help="Enable performance optimizations for faster execution with simplified analysis",
    )
    symbolic_parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode with verbose output"
    )

    return parser


def validate_arguments(args) -> None:
    """Validate command line arguments."""
    if args.mode in ("prove", "bootstrap"):
        if args.mode == "prove" and (
            not args.file or not Path(args.file).exists()
        ):
            print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
            sys.exit(1)
        return
    if args.mode == "check":
        # For check mode, only file is required (no --source support)
        if not args.file:
            print(
                "Error: A Python source file must be provided for check mode.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif args.mode in ("build", "verify"):
        # For build/verify modes, only the source file is required
        if not args.file:
            print(
                f"Error: A Silu source file must be provided for {args.mode} mode.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not Path(args.file).exists():
            print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
            sys.exit(1)
        # Don't check file existence here for check mode - let run_check handle it
    elif args.mode in ["exec", "symbolic", "to-source", "llvm", "prove"]:
        # For exec/symbolic/to-source/llvm modes, either file or --source is required
        if not args.file and not args.source:
            if args.mode == "exec":
                mode_name = "IR file"
            elif args.mode == "to-source":
                mode_name = "IR file"
            elif args.mode == "llvm":
                mode_name = "IR file"
            else:
                mode_name = "source file or IR file"
            print(
                f"Error: Either a {mode_name} or --source must be provided.",
                file=sys.stderr,
            )
            sys.exit(1)
        if args.file and args.source:
            print("Error: Cannot specify both file and --source.", file=sys.stderr)
            sys.exit(1)
        if args.file and not Path(args.file).exists():
            print(f"Error: File '{args.file}' does not exist.", file=sys.stderr)
            sys.exit(1)
    else:
        # For interpret/ir modes, either file or --source is required
        if not args.file and not args.source:
            print(
                "Error: Either a source file or --source must be provided.",
                file=sys.stderr,
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
    if (
        len(sys.argv) == 2
        and not sys.argv[1].startswith("-")
        and sys.argv[1]
        not in [
            "interpret", "ir", "exec", "symbolic", "to-source",
            "prove", "bootstrap", "check", "verify", "build", "llvm",
        ]
    ):
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

    # Handle check mode separately (doesn't need source code validation)
    if args.mode == "check":
        try:
            run_check(args.file)
        except KeyboardInterrupt:
            print("\nInterrupted by user.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.mode == "bootstrap":
        import shutil as _shutil

        if _shutil.which("clang") is None:
            print(
                "Error: clang is required (Xcode Command Line "
                "Tools on macOS, 'apt install clang' on Linux).",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            from tools.bootstrap import ensure_toolchain
            siluc, fe = ensure_toolchain()
        except Exception as e:
            print(f"Error bootstrapping the toolchain: {e}", file=sys.stderr)
            sys.exit(1)
        print("bootstrapped the self-hosted toolchain:")
        print(f"  {siluc}   # file-in binary-out, zero Python (~0.13s)")
        print(f"  {fe}       # stdin .si -> IR JSON")
        print(f'Try: "{siluc}" program.si -o program\n'
              "Generated files are cached per user; re-run after upgrades.")
        return

    # Get source code for other modes
    if args.file:
        source_code = read_source_file(args.file)
        source_name = args.file
        # cross-file imports (Rust mod shape): inline sibling .si
        # files; the parse hook below picks the directory up
        from silu import importer

        importer.SOURCE_DIR = os.path.dirname(os.path.abspath(args.file))
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
                from silu.importer import parse_with_imports

                tree = parse_with_imports(source_code)
                ir_generator = SiluIRGenerator(**ir_kwargs)
                ir_result = ir_generator.visit(tree)
                save_ir_to_file(ir_result, args.output, args.format)
            else:
                # Generate IR and print to stdout
                generate_ir(source_code, args.format, **ir_kwargs)

        elif args.mode == "exec":
            # Execute IR directly
            ir_kwargs = {"debug": getattr(args, "debug", False)}

            if args.source:
                # Execute IR from command line source
                run_ir_interpreter(args.source, **ir_kwargs)
            else:
                # Execute IR from file
                run_ir_interpreter(args.file, **ir_kwargs)

        elif args.mode == "to-source":
            # IR to source conversion
            to_source_kwargs = {"output_file": getattr(args, "output", None)}

            if args.source:
                # Convert IR from command line source
                run_ir_to_source_converter(args.source, **to_source_kwargs)
            else:
                # Convert IR from file
                run_ir_to_source_converter(args.file, **to_source_kwargs)

        elif args.mode == "llvm":
            # LLVM IR generation
            llvm_kwargs = {"output_file": getattr(args, "output", None)}

            if args.source:
                # Generate LLVM IR from command line IR source
                run_llvm_ir_generator(args.source, is_file=False, **llvm_kwargs)
            else:
                # Generate LLVM IR from IR file
                run_llvm_ir_generator(args.file, is_file=True, **llvm_kwargs)

        elif args.mode == "build":
            # One-command native build
            run_build(
                args.file,
                output_file=getattr(args, "output", None),
                static_only=getattr(args, "static", False),
            )

        elif args.mode == "prove":
            from silu.verify import verify_file

            sys.exit(verify_file(args.file))
        elif args.mode == "verify":
            # Differential verification: interpreter vs compiled binary
            run_verify(args.file)

        elif args.mode == "symbolic":
            # Symbolic execution
            symbolic_kwargs = {
                "simplify": getattr(args, "simplify", False),
                "solve": getattr(args, "solve", False),
                "performance_mode": getattr(args, "performance_mode", False),
                "debug": getattr(args, "debug", False),
                "output": getattr(args, "output", False),
            }

            # Execute symbolic execution with better error handling
            report = {}
            if args.source:
                # Symbolic execution from command line source
                report = run_symbolic_executor(
                    args.source, is_file=False, **symbolic_kwargs
                )
            else:
                # Symbolic execution from file
                report = run_symbolic_executor(
                    args.file, is_file=True, **symbolic_kwargs
                )

            if hasattr(args, "output") and args.output:
                # Save symbolic execution report to file
                with open(args.output, "w") as f:
                    report_str = json.dumps(report, indent=2, default=str)
                    f.write(report_str)

    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        # SILU_TB=1 prints the full traceback (runtime errors otherwise
        # surface without any location)
        if os.environ.get("SILU_TB"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
