"""
Unit tests for the Silu CLI module.
"""

import sys
import ast
import pytest
import subprocess
import os
from silu.cli import main
from unittest.mock import patch, mock_open


def test_main_with_no_arguments(capsys):
    """Test main function with no arguments."""
    with patch.object(sys, "argv", ["silu"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Usage: silu <file.si>" in captured.out


def test_main_with_too_many_arguments(capsys):
    """Test main function with too many arguments."""
    with patch.object(sys, "argv", ["silu", "file1.si", "file2.si"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Usage: silu <file.si>" in captured.out


@patch("builtins.open", new_callable=mock_open, read_data="x = 42\nprint(x)")
@patch("silu.cli.ast.parse")
def test_main_with_valid_file(mock_parse, mock_file):
    """Test main function with a valid file."""
    # Create a mock AST
    mock_tree = ast.Module()
    mock_parse.return_value = mock_tree

    with patch.object(sys, "argv", ["silu", "test.si"]):
        with patch("silu.cli.SiluInterpreter") as mock_interpreter_class:
            mock_interpreter = mock_interpreter_class.return_value
            main()

    # Verify that the file was opened
    mock_file.assert_called_once_with("test.si", "r")

    # Verify that ast.parse was called
    mock_parse.assert_called_once()

    # Verify that the interpreter was created and used
    mock_interpreter_class.assert_called_once()
    mock_interpreter.visit.assert_called_once_with(mock_tree)


@patch("builtins.open", side_effect=FileNotFoundError())
def test_main_with_nonexistent_file(mock_file, capsys):
    """Test main function with a nonexistent file."""
    with patch.object(sys, "argv", ["silu", "nonexistent.si"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    mock_file.assert_called_once_with("nonexistent.si", "r")

    captured = capsys.readouterr()
    assert "Error: File 'nonexistent.si' not found." in captured.out


@patch("builtins.open", new_callable=mock_open, read_data="x = 42")
@patch("silu.cli.ast.parse", side_effect=SyntaxError("Invalid syntax"))
def test_main_with_syntax_error(mock_parse, mock_file, capsys):
    """Test main function with a file that has syntax errors."""
    with patch.object(sys, "argv", ["silu", "test.si"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "Error executing 'test.si': Invalid syntax" in captured.out


def test_cli_as_module(capsys):
    """Test that cli.py can be run as a module."""
    # Import the module to ensure it can be imported without errors
    import silu.cli

    assert silu.cli is not None


def test_cli_integration():
    """Integration test for the CLI."""
    # Test with no arguments
    result = subprocess.run(
        [sys.executable, "-m", "silu.cli"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )

    assert result.returncode == 1
    assert "Usage: silu <file.si>" in result.stdout
