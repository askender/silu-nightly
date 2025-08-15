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

    def test_environment_basic_operations(self):
        # Test default and parent initialization
        env = Environment()
        # Check that env.vars contains at least the print function
        assert "print" in env.vars
        assert env.parent is None

        parent_env = Environment()
        parent_env.set("y", 20)
        child_env = Environment(parent=parent_env)
        assert child_env.parent is parent_env

        # Test set, get, and parent variable access
        env.set("x", 10)
        assert env.get("x") == 10
        assert child_env.get("y") == 20

        # Test undefined variable
        with pytest.raises(NameError, match="Name 'undefined_var' is not defined"):
            env.get("undefined_var")

        # Test variable shadowing
        child_env.set("y", 30)
        assert child_env.get("y") == 30
        assert parent_env.get("y") == 20


class TestSiluInterpreter:
    """Tests for the SiluInterpreter class."""

    def test_init_and_module_visiting(self):
        # Test default and custom environment initialization
        interpreter = SiluInterpreter()
        assert isinstance(interpreter.env, Environment)

        custom_env = Environment()
        interpreter_with_env = SiluInterpreter(env=custom_env)
        assert interpreter_with_env.env is custom_env

        # Test visiting modules
        empty_module = ast.Module(body=[], type_ignores=[])
        interpreter.visit(empty_module)

        code = "pass"
        tree = ast.parse(code)
        interpreter.visit(tree)

    def test_visit_constant_and_name(self):
        interpreter = SiluInterpreter()

        # Test constants
        test_cases = [
            (42, int),
            ("hello", str),
            (3.14, float),
            (True, bool),
            (False, bool),
        ]

        for value, expected_type in test_cases:
            node = ast.Constant(value=value)
            result = interpreter.visit_Constant(node)
            assert result == value
            assert isinstance(result, expected_type)

        # Test name operations
        interpreter.env.set("x", 10)
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
        interpreter.env.set("y", 10)
        target = ast.Name(id="z", ctx=ast.Store())
        left = ast.Name(id="y", ctx=ast.Load())
        right = ast.Constant(value=5)
        value = ast.BinOp(left=left, op=ast.Add(), right=right)
        assign_node = ast.Assign(targets=[target], value=value)
        interpreter.visit_Assign(assign_node)
        assert interpreter.env.get("z") == 15

        # Test error cases
        target1 = ast.Name(id="a", ctx=ast.Store())
        target2 = ast.Name(id="b", ctx=ast.Store())
        value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[target1, target2], value=value)
        with pytest.raises(
            NotImplementedError, match="Only single target assignments are supported"
        ):
            interpreter.visit_Assign(assign_node)

        target = ast.Subscript(
            value=ast.Name(id="lst", ctx=ast.Load()),
            slice=ast.Constant(value=0),
            ctx=ast.Store(),
        )
        value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[target], value=value)
        with pytest.raises(
            NotImplementedError, match="Only simple variable assignments are supported"
        ):
            interpreter.visit_Assign(assign_node)

    def test_visit_binop(self):
        interpreter = SiluInterpreter()

        # Test all binary operations
        left = ast.Constant(value=5)
        right = ast.Constant(value=3)

        # Test normal operations
        test_cases = [
            (ast.Add(), 8),
            (ast.Sub(), 2),
            (ast.Mult(), 15),
            (ast.Div(), 5 / 3),
            (ast.FloorDiv(), 1),
            (ast.Mod(), 2),
            (ast.Pow(), 125),
        ]

        for op, expected in test_cases:
            node = ast.BinOp(left=left, op=op, right=right)
            assert interpreter.visit_BinOp(node) == expected

        # Test division by zero errors
        right = ast.Constant(value=0)
        error_cases = [
            (ast.Div(), "Division by zero"),
            (ast.Mod(), "Modulo by zero"),
            (ast.FloorDiv(), "Division by zero"),
        ]

        for op, error_msg in error_cases:
            node = ast.BinOp(left=left, op=op, right=right)
            with pytest.raises(ZeroDivisionError, match=error_msg):
                interpreter.visit_BinOp(node)

        # Test unsupported operator
        node = ast.BinOp(left=left, op=ast.LShift(), right=right)
        with pytest.raises(NotImplementedError, match="Unsupported binary operator"):
            interpreter.visit_BinOp(node)

    def test_visit_unaryop_and_boolop(self):
        interpreter = SiluInterpreter()

        # Test unary operations
        operand = ast.Constant(value=5)
        node = ast.UnaryOp(op=ast.UAdd(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == 5

        node = ast.UnaryOp(op=ast.USub(), operand=operand)
        assert interpreter.visit_UnaryOp(node) == -5

        operand = ast.Constant(value=True)
        node = ast.UnaryOp(op=ast.Not(), operand=operand)
        assert not interpreter.visit_UnaryOp(node)

        operand = ast.Constant(value=False)
        node = ast.UnaryOp(op=ast.Not(), operand=operand)
        assert interpreter.visit_UnaryOp(node)

        # Test unsupported unary operator
        operand = ast.Constant(value=5)
        node = ast.UnaryOp(op=ast.Invert(), operand=operand)
        with pytest.raises(NotImplementedError, match="Unsupported unary operator"):
            interpreter.visit_UnaryOp(node)

        # Test boolean operations
        values = [ast.Constant(value=True), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert not interpreter.visit_BoolOp(node)

        values = [ast.Constant(value=True), ast.Constant(value=True)]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert interpreter.visit_BoolOp(node)

        values = [ast.Constant(value=False), ast.Constant(value=True)]
        node = ast.BoolOp(op=ast.Or(), values=values)
        assert interpreter.visit_BoolOp(node)

        values = [ast.Constant(value=False), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.Or(), values=values)
        assert not interpreter.visit_BoolOp(node)

        # Test with variables
        interpreter.env.set("a", True)
        interpreter.env.set("b", False)
        values = [ast.Name(id="a", ctx=ast.Load()), ast.Name(id="b", ctx=ast.Load())]
        node = ast.BoolOp(op=ast.And(), values=values)
        assert not interpreter.visit_BoolOp(node)

        # Test unsupported boolean operator
        values = [ast.Constant(value=True), ast.Constant(value=False)]
        node = ast.BoolOp(op=ast.MatMult(), values=values)
        with pytest.raises(NotImplementedError, match="Unsupported boolean operator"):
            interpreter.visit_BoolOp(node)

    def test_visit_compare(self):
        interpreter = SiluInterpreter()

        # Test all comparison operations
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]

        test_cases = [
            (ast.Eq(), False),
            (ast.NotEq(), True),
            (ast.Lt(), False),
            (ast.LtE(), False),
            (ast.Gt(), True),
            (ast.GtE(), True),
        ]

        for op, expected in test_cases:
            node = ast.Compare(left=left, ops=[op], comparators=comparators)
            assert interpreter.visit_Compare(node) == expected

        # Test chained comparisons
        left = ast.Constant(value=3)
        comparators = [ast.Constant(value=5), ast.Constant(value=7)]
        ops = [ast.Lt(), ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert interpreter.visit_Compare(node)

        # Test short-circuit evaluation
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3), ast.Constant(value=7)]
        ops = [ast.Lt(), ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        assert not interpreter.visit_Compare(node)

        # Test unsupported operator
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]
        ops = [ast.In()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        with pytest.raises(
            NotImplementedError, match="Unsupported comparison operator"
        ):
            interpreter.visit_Compare(node)

        # Test mismatch between comparators and operators
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3), ast.Constant(value=7)]
        ops = [ast.Lt()]
        node = ast.Compare(left=left, ops=ops, comparators=comparators)
        with pytest.raises(
            ValueError, match="Mismatch between comparators and operators"
        ):
            interpreter.visit_Compare(node)

    def test_visit_expr(self):
        interpreter = SiluInterpreter()

        # Test visiting an expression
        value = ast.Constant(value=42)
        node = ast.Expr(value=value)
        assert interpreter.visit_Expr(node) == 42

    def test_visit_if(self):
        interpreter = SiluInterpreter()

        # Test simple if statement (true condition)
        interpreter.env.set("x", 10)
        test = ast.Compare(
            left=ast.Name(id="x", ctx=ast.Load()),
            ops=[ast.Gt()],
            comparators=[ast.Constant(value=5)],
        )
        body = [
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="print", ctx=ast.Load()),
                    args=[ast.Constant(value="x is greater than 5")],
                    keywords=[],
                )
            )
        ]
        orelse = [
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="print", ctx=ast.Load()),
                    args=[ast.Constant(value="x is not greater than 5")],
                    keywords=[],
                )
            )
        ]
        node = ast.If(test=test, body=body, orelse=orelse)

        # We can't easily test the output, but we can test that it doesn't raise an error
        try:
            interpreter.visit_If(node)
        except Exception as e:
            pytest.fail(f"visit_If raised an exception unexpectedly: {e}")

        # Test simple if statement (false condition)
        interpreter.env.set("y", 3)
        test = ast.Compare(
            left=ast.Name(id="y", ctx=ast.Load()),
            ops=[ast.Gt()],
            comparators=[ast.Constant(value=5)],
        )
        node = ast.If(test=test, body=body, orelse=orelse)

        try:
            interpreter.visit_If(node)
        except Exception as e:
            pytest.fail(f"visit_If raised an exception unexpectedly: {e}")

    def test_visit_while(self):
        interpreter = SiluInterpreter()

        # Test simple while loop
        interpreter.env.set("i", 0)
        test = ast.Compare(
            left=ast.Name(id="i", ctx=ast.Load()),
            ops=[ast.Lt()],
            comparators=[ast.Constant(value=3)],
        )
        body = [
            ast.Expr(
                value=ast.Call(
                    func=ast.Name(id="print", ctx=ast.Load()),
                    args=[ast.Name(id="i", ctx=ast.Load())],
                    keywords=[],
                )
            ),
            ast.Assign(
                targets=[ast.Name(id="i", ctx=ast.Store())],
                value=ast.BinOp(
                    left=ast.Name(id="i", ctx=ast.Load()),
                    op=ast.Add(),
                    right=ast.Constant(value=1),
                ),
            ),
        ]
        node = ast.While(test=test, body=body, orelse=[])

        # We can't easily test the output, but we can test that it doesn't raise an error
        try:
            interpreter.visit_While(node)
        except Exception as e:
            pytest.fail(f"visit_While raised an exception unexpectedly: {e}")

        # Test while loop with false condition (should not execute body)
        interpreter.env.set("j", 5)
        test = ast.Compare(
            left=ast.Name(id="j", ctx=ast.Load()),
            ops=[ast.Lt()],
            comparators=[ast.Constant(value=3)],
        )
        node = ast.While(test=test, body=body, orelse=[])

        try:
            interpreter.visit_While(node)
            # j should still be 5
            assert interpreter.env.get("j") == 5
        except Exception as e:
            pytest.fail(f"visit_While raised an exception unexpectedly: {e}")

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
        assert not interpreter.env.get("z")

        # Test comparison
        tree = ast.parse("w = 5 > 3")
        interpreter.visit(tree)
        assert interpreter.env.get("w")

        # Test variable usage
        tree = ast.parse("""
a = 10
b = 5
c = a + b
""")
        interpreter.visit(tree)
        assert interpreter.env.get("c") == 15

    def test_visit_call_and_builtins(self):
        """Test function calls and built-in functions."""
        interpreter = SiluInterpreter()

        # Test that 'print' is available as a built-in
        assert "print" in interpreter.env.vars
        assert callable(interpreter.env.vars["print"])

        # Test calling print with different arguments
        # We can't easily test the output, but we can test that it doesn't raise an error
        try:
            interpreter.env.vars["print"]("Hello, World!")
            interpreter.env.vars["print"](1, 2, 3)
            interpreter.env.vars["print"](True, False)
        except Exception as e:
            pytest.fail(f"Calling print raised an exception unexpectedly: {e}")

        # Test visit_Call method
        # Create a call node for print("test")
        func_node = ast.Name(id="print", ctx=ast.Load())
        arg_node = ast.Constant(value="test")
        call_node = ast.Call(func=func_node, args=[arg_node], keywords=[])

        # This should not raise an error
        try:
            interpreter.visit_Call(call_node)
        except Exception as e:
            pytest.fail(f"visit_Call raised an exception unexpectedly: {e}")

        # Test calling a non-callable
        func_node = ast.Constant(value=42)
        call_node = ast.Call(func=func_node, args=[], keywords=[])
        with pytest.raises(TypeError, match="'int' object is not callable"):
            interpreter.visit_Call(call_node)


def test_main_function(capsys):
    """Test the main function."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello from Silu!\n"


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
