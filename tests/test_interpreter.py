"""
Unit tests for the Silu interpreter components using pytest.
"""

import ast
import subprocess
import sys
import pytest
from silu.interpreter import Environment, SiluInterpreter, main, Function


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

        # Test various language features
        test_programs = [
            # (code, variable_to_check, expected_value)
            ("x = 5 + 3", "x", 8),
            ("y = (10 - 4) * 2", "y", 12),
            ("z = True and False", "z", False),
            ("w = 5 > 3", "w", True),
        ]
        
        for code, var_name, expected in test_programs:
            tree = ast.parse(code)
            interpreter.visit(tree)
            assert interpreter.env.get(var_name) == expected

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

        # Test that built-in functions are available
        builtins = ["print", "type", "isinstance", "int", "float", "str", "bool"]
        type_objects = ["int_type", "float_type", "str_type", "bool_type"]
        
        for builtin in builtins:
            assert builtin in interpreter.env.vars
            assert callable(interpreter.env.vars[builtin])
            
        for type_obj in type_objects:
            assert type_obj in interpreter.env.vars

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

        # Test type function
        assert interpreter.env.vars["type"](42) is int
        assert interpreter.env.vars["type"](3.14) is float
        assert interpreter.env.vars["type"]("hello") is str
        assert interpreter.env.vars["type"](True) is bool

        # Test conversion functions with various inputs
        conversion_tests = [
            # (function_name, input_value, expected_output)
            ("int", None, 0),
            ("int", 42, 42),
            ("int", 3.14, 3),
            ("int", "123", 123),
            ("int", True, 1),
            ("int", False, 0),
            ("float", None, 0.0),
            ("float", 3.14, 3.14),
            ("float", 42, 42.0),
            ("float", "3.14", 3.14),
            ("float", True, 1.0),
            ("float", False, 0.0),
            ("str", None, ""),
            ("str", 42, "42"),
            ("str", 3.14, "3.14"),
            ("str", "hello", "hello"),
            ("str", True, "True"),
            ("str", False, "False"),
            ("bool", None, False),
            ("bool", 0, False),
            ("bool", 1, True),
            ("bool", "", False),
            ("bool", "hello", True),
            ("bool", True, True),
            ("bool", False, False),
        ]
        
        for func_name, input_val, expected in conversion_tests:
            if input_val is None:
                assert interpreter.env.vars[func_name]() == expected
            else:
                assert interpreter.env.vars[func_name](input_val) == expected

        # Test isinstance function
        isinstance_tests = [
            # (value, type, expected_result)
            (42, int, True),
            (3.14, float, True),
            ("hello", str, True),
            (True, bool, True),
            (42, float, False),
            (3.14, int, False),
            ("hello", bool, False),
            (True, str, False),
        ]
        
        for value, type_cls, expected in isinstance_tests:
            assert interpreter.env.vars["isinstance"](value, type_cls) == expected

        # Test isinstance with type objects from env
        isinstance_type_tests = [
            (42, "int_type"),
            (3.14, "float_type"),
            ("hello", "str_type"),
            (True, "bool_type"),
        ]
        
        for value, type_name in isinstance_type_tests:
            assert interpreter.env.vars["isinstance"](value, interpreter.env.vars[type_name])

        # Test isinstance error cases
        with pytest.raises(NotImplementedError):
            interpreter.env.vars["isinstance"](42, list)  # Passing list should raise NotImplementedError

        # Test isinstance with custom object that has __name__ attribute
        class CustomType:
            def __init__(self, name):
                self.__name__ = name

        custom_int_type = CustomType("int")
        custom_float_type = CustomType("float")
        custom_str_type = CustomType("str")
        custom_bool_type = CustomType("bool")
        custom_unknown_type = CustomType("unknown")

        assert interpreter.env.vars["isinstance"](42, custom_int_type)
        assert interpreter.env.vars["isinstance"](3.14, custom_float_type)
        assert interpreter.env.vars["isinstance"]("hello", custom_str_type)
        assert interpreter.env.vars["isinstance"](True, custom_bool_type)

        # Test isinstance with unknown type
        with pytest.raises(NotImplementedError):
            interpreter.env.vars["isinstance"](42, custom_unknown_type)

    def test_builtins_error_cases(self):
        """Test error cases for built-in functions."""
        interpreter = SiluInterpreter()

        # Test TypeError in visit_Call method
        # Create a call node for an integer (not callable)
        func_node = ast.Constant(value=42)
        call_node = ast.Call(func=func_node, args=[], keywords=[])

        # This should raise a TypeError
        with pytest.raises(TypeError, match="'int' object is not callable"):
            interpreter.visit_Call(call_node)

        # Test error cases for conversion functions
        error_cases = [
            # (function_name, invalid_input)
            ("int", []),
            ("float", []),
            ("float", [1, 2, 3]),
        ]
        
        for func_name, invalid_input in error_cases:
            with pytest.raises(NotImplementedError):
                interpreter.env.vars[func_name](invalid_input)

        # Test isinstance with unsupported types
        class UnsupportedType:
            pass

        unsupported_type = UnsupportedType()

        # This should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            interpreter.env.vars["isinstance"](42, unsupported_type)

        # Test isinstance with custom unknown type
        class CustomType:
            def __init__(self, name):
                self.__name__ = name

        custom_unknown_type = CustomType("unknown")

        # This should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            interpreter.env.vars["isinstance"](42, custom_unknown_type)

        # Test conversion with boolean values (should work, not raise errors)
        assert interpreter.env._int(True) == 1
        assert interpreter.env._int(False) == 0
        assert interpreter.env._float(True) == 1.0
        assert interpreter.env._float(False) == 0.0

    def test_visit_functiondef_and_call(self):
        """Test function definition and call."""
        interpreter = SiluInterpreter()

        # Test simple function definition
        # Create AST nodes for:
        # def greet(name):
        #     print("Hello, " + name)
        func_name = "greet"
        arg_name = "name"
        func_args = ast.arguments(
            args=[ast.arg(arg=arg_name, annotation=None)],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        print_call = ast.Call(
            func=ast.Name(id="print", ctx=ast.Load()),
            args=[
                ast.BinOp(
                    left=ast.Constant(value="Hello, "),
                    op=ast.Add(),
                    right=ast.Name(id=arg_name, ctx=ast.Load()),
                )
            ],
            keywords=[],
        )
        func_body = [ast.Expr(value=print_call)]
        func_def_node = ast.FunctionDef(
            name=func_name,
            args=func_args,
            body=func_body,
            decorator_list=[],
            returns=None,
        )

        # Visit the function definition
        interpreter.visit_FunctionDef(func_def_node)

        # Check that the function is in the environment
        assert func_name in interpreter.env.vars
        func_obj = interpreter.env.vars[func_name]
        assert isinstance(func_obj, Function)

        # Test calling the function
        # Create AST nodes for: greet("World")
        call_node = ast.Call(
            func=ast.Name(id=func_name, ctx=ast.Load()),
            args=[ast.Constant(value="World")],
            keywords=[],
        )

        # This should not raise an error
        try:
            interpreter.visit_Call(call_node)
        except Exception as e:
            pytest.fail(f"visit_Call raised an exception unexpectedly: {e}")

        # Test function with return statement
        # Create AST nodes for:
        # def add(a, b):
        #     return a + b
        func_name = "add"
        arg_a = "a"
        arg_b = "b"
        func_args = ast.arguments(
            args=[
                ast.arg(arg=arg_a, annotation=None),
                ast.arg(arg=arg_b, annotation=None),
            ],
            vararg=None,
            kwonlyargs=[],
            kw_defaults=[],
            kwarg=None,
            defaults=[],
        )
        return_stmt = ast.Return(
            value=ast.BinOp(
                left=ast.Name(id=arg_a, ctx=ast.Load()),
                op=ast.Add(),
                right=ast.Name(id=arg_b, ctx=ast.Load()),
            )
        )
        func_body = [return_stmt]
        func_def_node = ast.FunctionDef(
            name=func_name,
            args=func_args,
            body=func_body,
            decorator_list=[],
            returns=None,
        )

        # Visit the function definition
        interpreter.visit_FunctionDef(func_def_node)

        # Check that the function is in the environment
        assert func_name in interpreter.env.vars
        func_obj = interpreter.env.vars[func_name]
        assert isinstance(func_obj, Function)

        # Test calling the function
        # Create AST nodes for: add(3, 5)
        call_node = ast.Call(
            func=ast.Name(id=func_name, ctx=ast.Load()),
            args=[ast.Constant(value=3), ast.Constant(value=5)],
            keywords=[],
        )

        result = interpreter.visit_Call(call_node)
        assert result == 8

    def test_visit_return(self):
        """Test return statement."""
        interpreter = SiluInterpreter()

        # Test return with value
        return_value = ast.Constant(value=42)
        return_node = ast.Return(value=return_value)
        result = interpreter.visit_Return(return_node)
        assert result == 42

        # Test return without value
        return_node = ast.Return(value=None)
        result = interpreter.visit_Return(return_node)
        assert result is None


def test_main_function(capsys):
    """Test the main function."""
    main()
    captured = capsys.readouterr()
    assert captured.out == "Hello from Silu!\n"


def test_module_execution():
    """Test that the module can be executed directly."""
    result = subprocess.run(
        [sys.executable, "-m", "silu.interpreter"],
        cwd=".",
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout == "Hello from Silu!\n"


class TestElifForSupport:
    """Tests for elif and for loop support."""

    def test_elif_support(self):
        """Test elif statement support."""
        interpreter = SiluInterpreter()

        # Test elif with multiple conditions
        code = """
x = 2
if x == 1:
    print("x is 1")
elif x == 2:
    print("x is 2")
elif x == 3:
    print("x is 3")
else:
    print("x is something else")
"""

        tree = ast.parse(code)
        # This should not raise any exceptions
        interpreter.visit(tree)

    def test_for_loop_support(self):
        """Test for loop support."""
        interpreter = SiluInterpreter()

        # Test basic for loop with list function
        code = """
total = 0
items = list([1, 2, 3, 4, 5])
for i in items:
    total = total + i
"""

        tree = ast.parse(code)
        # This should not raise any exceptions
        interpreter.visit(tree)

        # Check that the loop executed correctly
        assert interpreter.env.get("total") == 15

    def test_for_loop_with_range(self):
        """Test for loop with range function."""
        interpreter = SiluInterpreter()

        # Add range function to environment for testing
        interpreter.env.set("range", range)

        # Test for loop with range
        code = """
total = 0
for i in range(3):
    total = total + i
print(total)
"""

        tree = ast.parse(code)
        # This should not raise any exceptions
        interpreter.visit(tree)

        # Check that the loop executed correctly (0 + 1 + 2 = 3)
        assert interpreter.env.get("total") == 3

    def test_nested_control_flow(self):
        """Test nested control flow with if, elif, and for loops."""
        interpreter = SiluInterpreter()

        # Test nested control flow
        code = """
result = list([])
for i in range(5):
    if i == 0:
        result.append("zero")
    elif i == 1:
        result.append("one")
    elif i == 2:
        result.append("two")
    else:
        result.append("other")
"""

        tree = ast.parse(code)
        # This should not raise any exceptions
        interpreter.visit(tree)

        # Check that the nested control flow executed correctly
        assert interpreter.env.get("result") == ["zero", "one", "two", "other", "other"]

    def test_append_method_error(self):
        """Test error handling for append method."""
        interpreter = SiluInterpreter()

        # Test append with wrong number of arguments
        code = """
items = list([])
"""

        tree = ast.parse(code)
        interpreter.visit(tree)

        # Manually test the append method with wrong number of arguments
        items = interpreter.env.get("items")
        with pytest.raises(
            TypeError, match="append\\(\\) takes exactly one argument \\(0 given\\)"
        ):
            items.append()

    def test_for_else_clause(self):
        """Test for loop with else clause."""
        interpreter = SiluInterpreter()

        # Test for loop with else clause that executes
        code = """
executed = list([])
for i in range(0):  # Empty range
    executed.append("loop")
else:
    executed.append("else")
"""

        tree = ast.parse(code)
        interpreter.visit(tree)

        # Check that the else clause executed
        assert interpreter.env.get("executed") == ["else"]
