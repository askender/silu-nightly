"""
Unit tests for the Silu interpreter components using pytest.
"""

import ast
import pytest
from silu.interpreter import Environment, SiluInterpreter


class TestEnvironment:
    """Tests for the Environment class."""

    def test_init(self):
        env = Environment()
        assert isinstance(env, Environment)
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
        interpreter = SiluInterpreter()
        assert isinstance(interpreter, SiluInterpreter)
        assert isinstance(interpreter.env, Environment)

        # Test with custom environment
        custom_env = Environment()
        interpreter_with_env = SiluInterpreter(env=custom_env)
        assert interpreter_with_env.env is custom_env

    def test_visit_empty_module(self):
        interpreter = SiluInterpreter()
        empty_module = ast.Module(body=[], type_ignores=[])
        
        # This should not raise any exceptions
        try:
            interpreter.visit(empty_module)
        except Exception as e:
            pytest.fail(f"visit(empty_module) raised an exception unexpectedly: {e}")