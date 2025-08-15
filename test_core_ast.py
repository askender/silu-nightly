"""
Unit tests for the Silu interpreter's core AST node visitors.
"""

import ast
import pytest
from silu.interpreter import SiluInterpreter, Environment


class TestCoreASTNodes:
    """Tests for core AST node visitors."""

    def test_visit_expr(self):
        interpreter = SiluInterpreter()
        
        # Create an expression node with a constant
        constant_node = ast.Constant(value=42)
        expr_node = ast.Expr(value=constant_node)
        
        # Visit the expression node
        result = interpreter.visit(expr_node)
        
        # The result should be the value of the constant
        assert result == 42

    def test_visit_assign_and_name(self):
        interpreter = SiluInterpreter()
        
        # Create an assignment node: x = 10
        target = ast.Name(id='x', ctx=ast.Store())
        value = ast.Constant(value=10)
        assign_node = ast.Assign(targets=[target], value=value)
        
        # Visit the assignment node
        interpreter.visit(assign_node)
        
        # Create a name node to load the variable: x
        load_target = ast.Name(id='x', ctx=ast.Load())
        
        # Visit the name node
        result = interpreter.visit(load_target)
        
        # The result should be the value we assigned
        assert result == 10

    def test_visit_assign_multiple_targets_not_implemented(self):
        interpreter = SiluInterpreter()
        
        # Create an assignment node with multiple targets: x = y = 10
        target1 = ast.Name(id='x', ctx=ast.Store())
        target2 = ast.Name(id='y', ctx=ast.Store())
        value = ast.Constant(value=10)
        assign_node = ast.Assign(targets=[target1, target2], value=value)
        
        # Visiting this should raise NotImplementedError
        with pytest.raises(NotImplementedError, match="Only single target assignments are supported"):
            interpreter.visit(assign_node)

    def test_visit_assign_complex_target_not_implemented(self):
        interpreter = SiluInterpreter()
        
        # Create an assignment node with a complex target: a[0] = 10
        # This is represented as a Subscript node
        target = ast.Subscript(
            value=ast.Name(id='a', ctx=ast.Load()),
            slice=ast.Constant(value=0),
            ctx=ast.Store()
        )
        value = ast.Constant(value=10)
        assign_node = ast.Assign(targets=[target], value=value)
        
        # Visiting this should raise NotImplementedError
        with pytest.raises(NotImplementedError, match="Only simple variable assignments are supported"):
            interpreter.visit(assign_node)
            
    def test_visit_name_unsupported_context(self):
        interpreter = SiluInterpreter()
        
        # Create a name node with an unsupported context (Del)
        name_node = ast.Name(id='x', ctx=ast.Del())
        
        # Visiting this should raise NotImplementedError
        with pytest.raises(NotImplementedError, match="Unsupported context for name"):
            interpreter.visit(name_node)
            
    def test_visit_name_undefined_variable(self):
        interpreter = SiluInterpreter()
        
        # Create a name node to load an undefined variable: y
        load_target = ast.Name(id='y', ctx=ast.Load())
        
        # Visiting this should raise NameError
        with pytest.raises(NameError, match="Name 'y' is not defined"):
            interpreter.visit(load_target)

    def test_visit_constant(self):
        interpreter = SiluInterpreter()
        
        # Test various constant types
        test_cases = [
            (42, int),
            (3.14, float),
            ("hello", str),
            (True, bool),
            (False, bool),
            (None, type(None))
        ]
        
        for value, expected_type in test_cases:
            constant_node = ast.Constant(value=value)
            result = interpreter.visit(constant_node)
            assert result == value
            assert isinstance(result, expected_type)
            
    def test_visit_name_store_context(self):
        # Test that visiting a Name node with Store context doesn't raise an exception
        # and doesn't do anything (as it's handled by visit_Assign)
        interpreter = SiluInterpreter()
        name_node = ast.Name(id='x', ctx=ast.Store())
        
        try:
            interpreter.visit(name_node)
        except Exception as e:
            pytest.fail(f"visit_Name with Store context raised an exception unexpectedly: {e}")