"""
Unit tests for the Silu interpreter components using pytest.
"""

import ast
import subprocess
import sys
import pytest
from silu.interpreter import Environment, SiluInterpreter, main


class TestEnvironment:
    """Tests for the Environment class."""

    def test_init(self):
        # Test default initialization
        env = Environment()
        assert env.vars == {}
        assert env.parent is None

        # Test with parent environment
        parent_env = Environment()
        child_env = Environment(parent=parent_env)
        assert child_env.parent is parent_env

    def test_set_and_get(self):
        env = Environment()
        env.set("x", 10)
        assert env.get("x") == 10

    def test_get_undefined_variable(self):
        env = Environment()
        with pytest.raises(NameError, match="Name 'undefined_var' is not defined"):
            env.get("undefined_var")

    def test_get_variable_from_parent(self):
        parent_env = Environment()
        parent_env.set("y", 20)
        child_env = Environment(parent=parent_env)
        
        # Should be able to get variable from parent
        assert child_env.get("y") == 20
        
        # Setting in child should not affect parent
        child_env.set("y", 30)
        assert child_env.get("y") == 30
        assert parent_env.get("y") == 20


class TestSiluInterpreter:
    """Tests for the SiluInterpreter class."""

    def test_init(self):
        # Test default initialization
        interpreter = SiluInterpreter()
        assert isinstance(interpreter.env, Environment)

        # Test with custom environment
        custom_env = Environment()
        interpreter_with_env = SiluInterpreter(env=custom_env)
        assert interpreter_with_env.env is custom_env

    def test_visit_module(self):
        interpreter = SiluInterpreter()
        
        # Test visiting an empty module
        empty_module = ast.Module(body=[], type_ignores=[])
        interpreter.visit(empty_module)  # Should not raise any exceptions

        # Test visiting a module with a pass statement
        code = "pass"
        tree = ast.parse(code)
        interpreter.visit(tree)  # Should not raise any exceptions


def test_main_function(capsys):
    """Test the main function."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello from Silu!\\n"


# This test is designed to cover the `if __name__ == "__main__"` block
def test_module_execution():
    """Test that the module can be executed directly."""
    # Execute the interpreter.py module as a script
    result = subprocess.run(
        [sys.executable, "-m", "silu.interpreter"],
        cwd="/Users/askender/aix1/silu",  # Make sure we're in the project root
        capture_output=True,
        text=True,
        timeout=5  # Timeout after 5 seconds
    )
    
    # Check that it ran successfully and produced the expected output
    assert result.returncode == 0
    assert result.stdout == "Hello from Silu!\\n"