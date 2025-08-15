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
        # Test default and parent initialization
        env = Environment()
        assert env.vars == {}
        assert env.parent is None

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
        # Test default and custom environment initialization
        interpreter = SiluInterpreter()
        assert isinstance(interpreter.env, Environment)

        custom_env = Environment()
        interpreter_with_env = SiluInterpreter(env=custom_env)
        assert interpreter_with_env.env is custom_env

    def test_visit_module(self):
        interpreter = SiluInterpreter()

        # Test visiting an empty module and a module with a pass statement
        empty_module = ast.Module(body=[], type_ignores=[])
        interpreter.visit(empty_module)

        code = "pass"
        tree = ast.parse(code)
        interpreter.visit(tree)

    def test_visit_constant(self):
        interpreter = SiluInterpreter()
        
        # Test with integer
        node = ast.Constant(value=42)
        assert interpreter.visit_Constant(node) == 42
        
        # Test with string
        node = ast.Constant(value="hello")
        assert interpreter.visit_Constant(node) == "hello"
        
        # Test with float
        node = ast.Constant(value=3.14)
        assert interpreter.visit_Constant(node) == 3.14
        
        # Test with boolean
        node = ast.Constant(value=True)
        assert interpreter.visit_Constant(node) == True

    def test_visit_name(self):
        interpreter = SiluInterpreter()
        interpreter.env.set("x", 10)
        
        # Test loading a variable
        load_node = ast.Name(id="x", ctx=ast.Load())
        assert interpreter.visit_Name(load_node) == 10
        
        # Test undefined variable
        undefined_node = ast.Name(id="y", ctx=ast.Load())
        with pytest.raises(NameError, match="Name 'y' is not defined"):
            interpreter.visit_Name(undefined_node)
            
        # Test store context (should not raise error)
        store_node = ast.Name(id="z", ctx=ast.Store())
        interpreter.visit_Name(store_node)  # Should not raise error
        
        # Test unsupported context
        unsupported_node = ast.Name(id="w", ctx=ast.Del())
        with pytest.raises(NotImplementedError, match="Unsupported context for name"):
            interpreter.visit_Name(unsupported_node)

    def test_visit_assign(self):
        interpreter = SiluInterpreter()
        
        # Test simple assignment
        target = ast.Name(id="x", ctx=ast.Store())
        value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[target], value=value)
        interpreter.visit_Assign(assign_node)
        assert interpreter.env.get("x") == 42
        
        # Test assignment with expression
        # First set y = 10
        interpreter.env.set("y", 10)
        # Then x = y + 5
        target = ast.Name(id="z", ctx=ast.Store())
        left = ast.Name(id="y", ctx=ast.Load())
        right = ast.Constant(value=5)
        value = ast.BinOp(left=left, op=ast.Add(), right=right)
        assign_node = ast.Assign(targets=[target], value=value)
        interpreter.visit_Assign(assign_node)
        assert interpreter.env.get("z") == 15
        
        # Test multiple targets (should raise NotImplementedError)
        target1 = ast.Name(id="a", ctx=ast.Store())
        target2 = ast.Name(id="b", ctx=ast.Store())
        value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[target1, target2], value=value)
        with pytest.raises(NotImplementedError, match="Only single target assignments are supported"):
            interpreter.visit_Assign(assign_node)
            
        # Test complex target (should raise NotImplementedError)
        target = ast.Subscript(
            value=ast.Name(id="lst", ctx=ast.Load()),
            slice=ast.Constant(value=0),
            ctx=ast.Store()
        )
        value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[target], value=value)
        with pytest.raises(NotImplementedError, match="Only simple variable assignments are supported"):
            interpreter.visit_Assign(assign_node)

    def test_visit_binop(self):
        interpreter = SiluInterpreter()
        
        # Test addition
        left = ast.Constant(value=5)
        right = ast.Constant(value=3)
        node = ast.BinOp(left=left, op=ast.Add(), right=right)
        assert interpreter.visit_BinOp(node) == 8
        
        # Test subtraction
        node = ast.BinOp(left=left, op=ast.Sub(), right=right)
        assert interpreter.visit_BinOp(node) == 2
        
        # Test multiplication
        node = ast.BinOp(left=left, op=ast.Mult(), right=right)
        assert interpreter.visit_BinOp(node) == 15
        
        # Test division
        node = ast.BinOp(left=left, op=ast.Div(), right=right)
        assert interpreter.visit_BinOp(node) == 5/3
        
        # Test floor division
        node = ast.BinOp(left=left, op=ast.FloorDiv(), right=right)
        assert interpreter.visit_BinOp(node) == 1
        
        # Test modulo
        node = ast.BinOp(left=left, op=ast.Mod(), right=right)
        assert interpreter.visit_BinOp(node) == 2
        
        # Test power
        node = ast.BinOp(left=left, op=ast.Pow(), right=right)
        assert interpreter.visit_BinOp(node) == 125
        
        # Test division by zero
        right = ast.Constant(value=0)
        node = ast.BinOp(left=left, op=ast.Div(), right=right)
        with pytest.raises(ZeroDivisionError, match="Division by zero"):
            interpreter.visit_BinOp(node)
            
        # Test modulo by zero
        node = ast.BinOp(left=left, op=ast.Mod(), right=right)
        with pytest.raises(ZeroDivisionError, match="Modulo by zero"):
            interpreter.visit_BinOp(node)
            
        # Test floor division by zero
        node = ast.BinOp(left=left, op=ast.FloorDiv(), right=right)
        with pytest.raises(ZeroDivisionError, match="Division by zero"):
            interpreter.visit_BinOp(node)
            
        # Test unsupported operator
        node = ast.BinOp(left=left, op=ast.LShift(), right=right)
        with pytest.raises(NotImplementedError, match="Unsupported binary operator"):
            interpreter.visit_BinOp(node)

    def test_visit_unaryop(self):
        interpreter = SiluInterpreter()
        
        # Test unary plus
        operand = ast.Constant(value=5)
        node = ast.UnaryOp(op=ast.UAdd(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == 5
        
        # Test unary minus
        node = ast.UnaryOp(op=ast.USub(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == -5
        
        # Test logical not
        operand = ast.Constant(value=True)
        node = ast.UnaryOp(op=ast.Not(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == False
        
        operand = ast.Constant(value=False)
        node = ast.UnaryOp(op=ast.Not(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == True
        
        # Test unsupported operator
        operand = ast.Constant(value=5)
        node = ast.UnaryOp(op=ast.Invert(), operand=operand)
        with pytest.raises(NotImplementedError, match="Unsupported unary operator"):
            interpreter.visit_UnaryOp(node)

    def test_visit_boolop(self):
        interpreter = SiluInterpreter()
        
        # Test and operation
        values = [ast.Constant(value=True), ast.Constant(value=False), ast.Constant(value=True)]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert interpreter.visit_BoolOp(node) == False  # Short-circuit evaluation
        
        values = [ast.Constant(value=True), ast.Constant(value=True)]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert interpreter.visit_BoolOp(node) == True
        
        # Test or operation
        values = [ast.Constant(value=False), ast.Constant(value=True), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.Or(), values=values)
        assert interpreter.visit_BoolOp(node) == True  # Short-circuit evaluation
        
        values = [ast.Constant(value=False), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.Or(), values=values)
        assert interpreter.visit_BoolOp(node) == False
        
        # Test with variables
        interpreter.env.set("a", True)
        interpreter.env.set("b", False)
        values = [ast.Name(id="a", ctx=ast.Load()), ast.Name(id="b", ctx=ast.Load())]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert interpreter.visit_BoolOp(node) == False
        
        # Test unsupported operator
        values = [ast.Constant(value=True), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.MatMult(), values=values)
        with pytest.raises(NotImplementedError, match="Unsupported boolean operator"):
            interpreter.visit_BoolOp(node)

    def test_visit_compare(self):
        interpreter = SiluInterpreter()
        
        # Test equality
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=5)]
        ops = [ast.Eq()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test inequality
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]
        ops = [ast.NotEq()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test less than
        left = ast.Constant(value=3)
        comparators = [ast.Constant(value=5)]
        ops = [ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test less than or equal
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=5)]
        ops = [ast.LtE()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test greater than
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]
        ops = [ast.Gt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test greater than or equal
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=5)]
        ops = [ast.GtE()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test chained comparisons
        left = ast.Constant(value=3)
        comparators = [ast.Constant(value=5), ast.Constant(value=7)]
        ops = [ast.Lt(), ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == True
        
        # Test short-circuit evaluation in chained comparisons
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3), ast.Constant(value=7)]
        ops = [ast.Lt(), ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node) == False  # First comparison fails
        
        # Test unsupported operator
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]
        ops = [ast.In()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        with pytest.raises(NotImplementedError, match="Unsupported comparison operator"):
            interpreter.visit_Compare(node)
            
        # Test mismatch between comparators and operators
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3), ast.Constant(value=7)]
        ops = [ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        with pytest.raises(ValueError, match="Mismatch between comparators and operators"):
            interpreter.visit_Compare(node)

    def test_visit_expr(self):
        interpreter = SiluInterpreter()
        
        # Test visiting an expression
        value = ast.Constant(value=42)
        node = ast.Expr(value=value)
        assert interpreter.visit_Expr(node) == 42

    def test_e2e_programs(self):
        # Test end-to-end programs
        interpreter = SiluInterpreter()
        
        # Test simple arithmetic
        tree = ast.parse("x = 5 + 3")
        interpreter.visit(tree)
        assert interpreter.env.get("x") == 8
        
        # Test complex expression
        tree = ast.parse("y = (10 - 4) * 2")
        interpreter.visit(tree)
        assert interpreter.env.get("y") == 12
        
        # Test boolean operations
        tree = ast.parse("z = True and False")
        interpreter.visit(tree)
        assert interpreter.env.get("z") == False
        
        # Test comparison
        tree = ast.parse("w = 5 > 3")
        interpreter.visit(tree)
        assert interpreter.env.get("w") == True
        
        # Test variable usage
        tree = ast.parse("""
a = 10
b = 5
c = a + b
""")
        interpreter.visit(tree)
        assert interpreter.env.get("c") == 15


def test_main_function(capsys):
    """Test the main function."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello from Silu!\n"


# Test that the module can be executed directly
def test_module_execution():
    """Test that the module can be executed directly."""
    result = subprocess.run(
        [sys.executable, "-m", "silu.interpreter"],
        cwd="/Users/askender/aix1/silu",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout == "Hello from Silu!\n"
