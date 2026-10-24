"""
Unit tests for the Silu CLI module.
"""

import sys
import ast
import pytest
from silu.cli import main
from unittest.mock import patch, mock_open


def test_main_with_no_arguments(capsys):
    """Test main function with no arguments shows help."""
    with patch.object(sys, "argv", ["silu"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Silu Language Processor" in captured.out
    assert "interpret" in captured.out
    assert "ir" in captured.out


def test_main_with_invalid_mode(capsys):
    """Test main function with invalid mode shows help."""
    with patch.object(sys, "argv", ["silu", "invalid_mode"]):
        with patch("silu.cli.Path.exists", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "File 'invalid_mode' not found" in captured.err


@patch("builtins.open", new_callable=mock_open, read_data="x = 42\nprint(x)")
@patch("silu.cli.ast.parse")
def test_legacy_usage_with_valid_file(mock_parse, mock_file):
    """Test legacy usage (silu file.si) with a valid file."""
    # Create a mock AST
    mock_tree = ast.parse("x = 42\nprint(x)")
    mock_parse.return_value = mock_tree

    with patch.object(sys, "argv", ["silu", "test.si"]):
        # the import is lazy inside run_interpreter, so patch at the
        # defining module (from-import resolves it at call time)
        with patch("silu.interpreter.SiluInterpreter") as mock_interpreter:
            # This should not raise an exception for legacy usage
            main()

            # Verify the file was opened and interpreter was created
            mock_file.assert_called_once_with("test.si", "r", encoding="utf-8")
            # Legacy usage should call parse at least once
            assert mock_parse.call_count >= 1
            mock_interpreter.assert_called_once()


@patch("silu.cli.read_source_file")
def test_interpret_mode_with_valid_file(mock_read_file, capsys):
    """Test interpret mode with a valid file."""
    mock_read_file.return_value = "x = 42\nprint(x)"

    with patch.object(sys, "argv", ["silu", "interpret", "test.si"]):
        with patch("silu.cli.Path.exists", return_value=True):
            with patch("silu.cli.run_interpreter") as mock_run:
                main()
                mock_run.assert_called_once_with("x = 42\nprint(x)")


@patch("silu.cli.read_source_file")
def test_ir_mode_with_valid_file(mock_read_file, capsys):
    """Test IR mode with a valid file."""
    mock_read_file.return_value = "x = 42\nprint(x)"

    with patch.object(sys, "argv", ["silu", "ir", "test.si"]):
        with patch("silu.cli.Path.exists", return_value=True):
            with patch("silu.cli.generate_ir") as mock_generate:
                main()
                mock_generate.assert_called_once_with(
                    "x = 42\nprint(x)", "pretty", record_types=True
                )


def test_interpret_mode_with_source_string(capsys):
    """Test interpret mode with source string."""
    with patch.object(sys, "argv", ["silu", "interpret", "--source", "x = 5"]):
        with patch("silu.cli.run_interpreter") as mock_run:
            main()
            mock_run.assert_called_once_with("x = 5")


def test_ir_mode_with_source_string_and_format(capsys):
    """Test IR mode with source string and JSON format."""
    with patch.object(
        sys, "argv", ["silu", "ir", "--source", "x = 5", "--format", "json"]
    ):
        with patch("silu.cli.generate_ir") as mock_generate:
            main()
            mock_generate.assert_called_once_with("x = 5", "json", record_types=True)


def test_verify_mode_passes_for_matching_program(tmp_path):
    """silu verify compiles and diffs against the interpreter."""
    import shutil

    if shutil.which("clang") is None:
        pytest.skip("clang not available")

    program = tmp_path / "ok.si"
    program.write_text('x: int = 6\ny: int = 7\nprint(x * y)\n')

    with patch.object(sys, "argv", ["silu", "verify", str(program)]):
        main()  # must not raise SystemExit


def test_runtime_panic_reports_source_line(tmp_path):
    """A runtime panic names the failing statement's source line."""
    import shutil
    import subprocess

    if shutil.which("clang") is None:
        pytest.skip("clang not available")

    program = tmp_path / "boom.si"
    program.write_text(
        'l: list[int] = [1, 2]\n'
        "d: dict[int, int] = {1: 10}\n"
        "x: int = l[5]\n"
    )
    binary = tmp_path / "boom_bin"

    with patch.object(
        sys, "argv", ["silu", "build", str(program), "-o", str(binary)]
    ):
        main()

    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == "IndexError: list index out of range (line 3)\n"


def test_build_mode_compiles_and_runs(tmp_path):
    """silu build produces a working native executable in one command."""
    import shutil
    import subprocess

    if shutil.which("clang") is None:
        pytest.skip("clang not available")

    program = tmp_path / "hello.si"
    program.write_text('x: int = 6\ny: int = 7\nprint(x * y)\n')
    binary = tmp_path / "hello_bin"

    with patch.object(
        sys, "argv", ["silu", "build", str(program), "-o", str(binary)]
    ):
        main()

    assert binary.exists()
    result = subprocess.run(
        [str(binary)], capture_output=True, text=True, check=True
    )
    assert result.stdout == "42\n"


def test_main_with_nonexistent_file(capsys):
    """Test main function with a nonexistent file."""
    with patch.object(sys, "argv", ["silu", "interpret", "nonexistent.si"]):
        with patch("silu.cli.Path.exists", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_main_with_syntax_error(capsys):
    """Test main function with a file containing syntax errors."""
    with patch.object(sys, "argv", ["silu", "interpret", "--source", "x = = 42"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Syntax Error" in captured.err


def test_main_with_missing_file_and_source(capsys):
    """Test main function when neither file nor source is provided."""
    with patch.object(sys, "argv", ["silu", "interpret"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Either a source file or --source must be provided" in captured.err


def test_main_with_both_file_and_source(capsys):
    """Test main function when both file and source are provided."""
    with patch.object(
        sys, "argv", ["silu", "interpret", "test.si", "--source", "x = 5"]
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Cannot specify both file and --source" in captured.err


def test_ir_mode_with_output_file():
    """Test IR mode with output file."""
    with patch.object(
        sys, "argv", ["silu", "ir", "--source", "x = 5", "--output", "test.ir"]
    ):
        with patch("silu.cli.ast.parse") as mock_parse:
            with patch("silu.cli.SiluIRGenerator") as mock_ir_gen:
                with patch("silu.cli.save_ir_to_file") as mock_save:
                    mock_tree = ast.parse("x = 5")
                    mock_parse.return_value = mock_tree
                    mock_ir_gen.return_value.visit.return_value = ("module", [])

                    main()

                    mock_save.assert_called_once()


def test_cli_as_module():
    """Test that the CLI can be called as a module."""
    # This test just ensures the module structure is correct
    import silu.cli

    assert hasattr(silu.cli, "main")
    assert callable(silu.cli.main)


def test_cli_integration():
    """Integration test to verify the CLI works end-to-end."""
    # Test that we can import and the main function exists
    from silu.cli import main

    assert callable(main)

    # Test help output
    with patch.object(sys, "argv", ["silu", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        # Help should exit with code 0
        assert exc_info.value.code == 0


def test_debug_mode():
    """Test debug mode functionality."""
    with patch.object(
        sys, "argv", ["silu", "interpret", "--source", "x = 5", "--debug"]
    ):
        with patch("silu.cli.run_interpreter") as mock_run:
            main()
            mock_run.assert_called_once_with("x = 5")


def test_no_types_flag():
    """Test --no-types flag for IR generation."""
    with patch.object(sys, "argv", ["silu", "ir", "--source", "x = 5", "--no-types"]):
        with patch("silu.cli.generate_ir") as mock_generate:
            main()
            mock_generate.assert_called_once_with("x = 5", "pretty", record_types=False)


def test_cli_module_stays_lean():
    """Importing silu.cli must not pull z3/loguru/llvmlite: those ride
    behind their subcommands now (the fat-import fix, ~0.1s per CLI
    call). Locks the property against accidental top-level re-imports."""
    import subprocess

    from tests import REPO

    code = (
        "import sys; import silu.cli; "
        "assert 'z3' not in sys.modules, 'z3 eagerly imported'; "
        "assert 'loguru' not in sys.modules, 'loguru eagerly imported'; "
        "assert 'llvmlite' not in sys.modules, 'llvmlite eagerly imported'"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, r.stderr
    assert silu_cli_import_cost_bounded()


def silu_cli_import_cost_bounded() -> bool:
    """And the silu.cli import itself stays under 60ms of wall time
    (was ~96ms with the fat imports, ~12ms after the fix)."""
    import statistics
    import subprocess

    from tests import REPO

    code = (
        "import time; t = time.perf_counter(); "
        "import silu.cli; print(time.perf_counter() - t)"
    )
    times = []
    for _ in range(3):
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, cwd=REPO,
        )
        times.append(float(r.stdout.strip()))
    return statistics.median(times) < 0.06
