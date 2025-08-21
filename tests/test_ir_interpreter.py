"""
Tests for the IR interpreter module.
"""

import pytest
from silu.ir_interpreter import IRInterpreter, execute_ir_from_string


class TestIRInterpreter:
    """Test cases for the IR interpreter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.interpreter = IRInterpreter()

    def test_basic_assignment_and_variables(self):
        """Test basic variable assignment and retrieval."""
        ir = ("module", (("assign", "x", 42, None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 42

    def test_arithmetic_operations(self):
        """Test basic arithmetic operations."""
        # x = 10 + 5
        ir = ("module", (("assign", "x", ("+", 10, 5), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 15

        # y = 20 - 8
        ir = ("module", (("assign", "y", ("-", 20, 8), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") == 12

        # z = 6 * 7
        ir = ("module", (("assign", "z", ("*", 6, 7), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("z") == 42

    def test_comparison_operations(self):
        """Test comparison operations."""
        # x = 5 > 3
        ir = ("module", (("assign", "x", (">", 5, 3), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") is True

        # y = 10 <= 5
        ir = ("module", (("assign", "y", ("<=", 10, 5), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") is False

    def test_unary_operations(self):
        """Test unary operations."""
        # x = -42
        ir = ("module", (("assign", "x", ("-", 42), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == -42

        # y = not True
        ir = ("module", (("assign", "y", ("not", True), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") is False

    def test_function_call_builtin(self):
        """Test calling built-in functions."""
        # Test print function (captured via redirect would be complex, so we just test it doesn't error)
        ir = ("module", (("call", "print", ("Hello, World!",), ()),))
        result = self.interpreter.execute_program(ir)
        # print returns None
        assert result is None

        # Test type function
        ir = ("module", (("assign", "x", ("call", "type", (42,), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") is int

    def test_function_definition_and_call(self):
        """Test user-defined functions."""
        # def add(a, b): return a + b
        # result = add(3, 5)
        ir = (
            "module",
            (
                ("func_def", "add", ("a", "b"), (("return", ("+", "a", "b")),)),
                ("assign", "result", ("call", "add", (3, 5), ()), None),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") == 8

    def test_if_statement(self):
        """Test if statements."""
        # if True: x = 10
        # else: x = 20
        ir = (
            "module",
            (
                (
                    "if",
                    True,
                    (("assign", "x", 10, None),),
                    (("assign", "x", 20, None),),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 10

        # Test false condition
        ir = (
            "module",
            (
                (
                    "if",
                    False,
                    (("assign", "y", 10, None),),
                    (("assign", "y", 20, None),),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") == 20

    def test_while_loop(self):
        """Test while loops."""
        # i = 0
        # while i < 3:
        #     i = i + 1
        ir = (
            "module",
            (
                ("assign", "i", 0, None),
                (
                    "while",
                    ("<", "i", 3),
                    (("assign", "i", ("+", "i", 1), None),),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("i") == 3

    def test_for_loop(self):
        """Test for loops."""
        # total = 0
        # for i in [1, 2, 3]:
        #     total = total + i
        ir = (
            "module",
            (
                ("assign", "total", 0, None),
                (
                    "for",
                    "i",
                    ("list", (1, 2, 3)),
                    (("assign", "total", ("+", "total", "i"), None),),
                    (),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("total") == 6

    def test_for_loop_with_range(self):
        """Test for loops with range."""
        # total = 0
        # for i in range(5):
        #     total = total + i
        ir = (
            "module",
            (
                ("assign", "total", 0, None),
                (
                    "for",
                    "i",
                    ("call", "range", (5,), ()),
                    (("assign", "total", ("+", "total", "i"), None),),
                    (),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("total") == 10  # 0+1+2+3+4

    def test_list_operations(self):
        """Test list creation and indexing."""
        # lst = [1, 2, 3]
        # x = lst[1]
        ir = (
            "module",
            (
                ("assign", "lst", ("list", (1, 2, 3)), None),
                ("assign", "x", ("subscript", "lst", 1), None),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("lst") == [1, 2, 3]
        assert self.interpreter._get_variable("x") == 2

    def test_dictionary_operations(self):
        """Test dictionary creation and access."""
        # d = {"key": "value", "num": 42}
        # x = d["key"]
        ir = (
            "module",
            (
                ("assign", "d", ("dict", (("key", "value"), ("num", 42))), None),
                ("assign", "x", ("subscript", "d", "key"), None),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("d") == {"key": "value", "num": 42}
        assert self.interpreter._get_variable("x") == "value"

    def test_lambda_function(self):
        """Test lambda functions."""
        # double = lambda x: x * 2
        # result = double(5)
        ir = (
            "module",
            (
                ("assign", "double", ("lambda", ("x",), ("*", "x", 2)), None),
                ("assign", "result", ("call", "double", (5,), ()), None),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") == 10

    def test_break_continue(self):
        """Test break and continue statements."""
        # count = 0
        # for i in range(10):
        #     if i == 5:
        #         break
        #     count = count + 1
        ir = (
            "module",
            (
                ("assign", "count", 0, None),
                (
                    "for",
                    "i",
                    ("call", "range", (10,), ()),
                    (
                        (
                            "if",
                            ("==", "i", 5),
                            (("break",),),
                            (),
                        ),
                        ("assign", "count", ("+", "count", 1), None),
                    ),
                    (),
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("count") == 5

    def test_augmented_assignment(self):
        """Test augmented assignment operations."""
        # x = 10
        # x += 5
        ir = (
            "module",
            (
                ("assign", "x", 10, None),
                ("aug_assign", "x", "+=", 5),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 15

    def test_chained_comparison(self):
        """Test chained comparisons."""
        # result = 3 < 5 < 7
        ir = (
            "module",
            (
                (
                    "assign",
                    "result",
                    ("chained_compare", (("<", 3, 5), ("<", 5, 7))),
                    None,
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") is True

        # Test failing chained comparison
        ir = (
            "module",
            (
                (
                    "assign",
                    "result2",
                    ("chained_compare", (("<", 3, 5), ("<", 7, 5))),
                    None,
                ),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result2") is False

    def test_nested_function_calls(self):
        """Test nested function calls and scoping."""
        # def outer(x):
        #     def inner(y):
        #         return x + y
        #     return inner(10)
        # result = outer(5)
        ir = (
            "module",
            (
                (
                    "func_def",
                    "outer",
                    ("x",),
                    (
                        (
                            "func_def",
                            "inner",
                            ("y",),
                            (("return", ("+", "x", "y")),),
                        ),
                        ("return", ("call", "inner", (10,), ())),
                    ),
                ),
                ("assign", "result", ("call", "outer", (5,), ()), None),
            ),
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") == 15

    def test_builtin_functions(self):
        """Test various built-in functions."""
        # Test len
        ir = ("module", (("assign", "x", ("call", "len", ([1, 2, 3],), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 3

        # Test abs
        ir = ("module", (("assign", "y", ("call", "abs", (-42,), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") == 42

        # Test min/max
        ir = ("module", (("assign", "z", ("call", "min", (5, 3, 8), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("z") == 3

    def test_error_handling(self):
        """Test error conditions."""
        # Test undefined variable in function call
        with pytest.raises(NameError):
            ir = ("module", (("call", "print", ("some_undefined_variable",), ()),))
            self.interpreter.execute_program(ir)

        # Test division by zero
        with pytest.raises(ZeroDivisionError):
            ir = ("module", (("assign", "x", ("/", 10, 0), None),))
            self.interpreter.execute_program(ir)

        # Test undefined function
        with pytest.raises(NameError):
            ir = ("module", (("call", "undefined_func", (), ()),))
            self.interpreter.execute_program(ir)

    def test_type_conversion_functions(self):
        """Test type conversion built-in functions."""
        # Test int conversion
        ir = ("module", (("assign", "x", ("call", "int", ("42",), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("x") == 42

        # Test float conversion
        ir = ("module", (("assign", "y", ("call", "float", ("3.14",), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("y") == 3.14

        # Test str conversion
        ir = ("module", (("assign", "z", ("call", "str", (123,), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("z") == "123"

        # Test bool conversion
        ir = ("module", (("assign", "w", ("call", "bool", (0,), ()), None),))
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("w") is False


class TestIRExecutionFromString:
    """Test IR execution from string format."""

    def test_simple_execution(self):
        """Test executing IR from string."""
        ir_string = '("module", (("assign", "x", 42, null),))'
        execute_ir_from_string(ir_string)
        # The function doesn't return the variable values, but we can test that it doesn't error

    def test_json_format_execution(self):
        """Test executing IR from JSON string."""
        ir_json = '["module", [["assign", "x", 42, null]]]'
        execute_ir_from_string(ir_json)
        # The function doesn't return the variable values, but we can test that it doesn't error


class TestComplexPrograms:
    """Test more complex programs to ensure IR interpreter works correctly."""

    def test_factorial_function(self):
        """Test recursive factorial function."""
        # def factorial(n):
        #     if n <= 1:
        #         return 1
        #     else:
        #         return n * factorial(n - 1)
        # result = factorial(5)
        ir = (
            "module",
            (
                (
                    "func_def",
                    "factorial",
                    ("n",),
                    (
                        (
                            "if",
                            ("<=", "n", 1),
                            (("return", 1),),
                            (
                                (
                                    "return",
                                    (
                                        "*",
                                        "n",
                                        (
                                            "call",
                                            "factorial",
                                            (("-", "n", 1),),
                                            (),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                ("assign", "result", ("call", "factorial", (5,), ()), None),
            ),
        )
        interpreter = IRInterpreter()
        interpreter.execute_program(ir)
        assert interpreter._get_variable("result") == 120

    def test_fibonacci_sequence(self):
        """Test generating Fibonacci sequence."""
        # def fib(n):
        #     if n <= 1:
        #         return n
        #     return fib(n-1) + fib(n-2)
        # result = fib(7)
        ir = (
            "module",
            (
                (
                    "func_def",
                    "fib",
                    ("n",),
                    (
                        (
                            "if",
                            ("<=", "n", 1),
                            (("return", "n"),),
                            (
                                (
                                    "return",
                                    (
                                        "+",
                                        ("call", "fib", (("-", "n", 1),), ()),
                                        ("call", "fib", (("-", "n", 2),), ()),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                ("assign", "result", ("call", "fib", (7,), ()), None),
            ),
        )
        interpreter = IRInterpreter()
        interpreter.execute_program(ir)
        assert interpreter._get_variable("result") == 13

    def test_list_comprehension_simulation(self):
        """Test simulating list comprehension behavior."""
        # squares = []
        # for i in range(5):
        #     squares.append(i * i)
        ir = (
            "module",
            (
                ("assign", "squares", ("list", ()), None),
                (
                    "for",
                    "i",
                    ("call", "range", (5,), ()),
                    (
                        # Simulate list.append by creating new list with existing + new element
                        (
                            "assign",
                            "squares",
                            ("+", "squares", ("list", (("*", "i", "i"),))),
                            None,
                        ),
                    ),
                    (),
                ),
            ),
        )
        interpreter = IRInterpreter()
        interpreter.execute_program(ir)
        assert interpreter._get_variable("squares") == [0, 1, 4, 9, 16]


class TestClosureFunctionality:
    """Test closure support in IR interpreter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.interpreter = IRInterpreter()

    def test_basic_closure(self):
        """Test basic closure functionality."""
        ir = (
            "module",
            (
                (
                    "func_def",
                    "make_adder",
                    ("n",),
                    (
                        (
                            "func_def",
                            "adder",
                            ("x",),
                            (
                                (
                                    "return",
                                    ("+", ("name", "x"), ("name", "n"))
                                ),
                            )
                        ),
                        ("return", ("name", "adder"))
                    )
                ),
                (
                    "assign",
                    "add5",
                    ("call", ("name", "make_adder"), (("const", 5),), ()),
                    None
                ),
                (
                    "assign",
                    "result",
                    ("call", ("name", "add5"), (("const", 3),), ()),
                    None
                )
            )
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") == 8

    def test_multiple_closures(self):
        """Test multiple independent closures."""
        ir = (
            "module",
            (
                (
                    "func_def",
                    "make_multiplier",
                    ("factor",),
                    (
                        (
                            "func_def",
                            "multiply",
                            ("x",),
                            (
                                (
                                    "return",
                                    ("*", ("name", "x"), ("name", "factor"))
                                ),
                            )
                        ),
                        ("return", ("name", "multiply"))
                    )
                ),
                (
                    "assign",
                    "double",
                    ("call", ("name", "make_multiplier"), (("const", 2),), ()),
                    None
                ),
                (
                    "assign",
                    "triple",
                    ("call", ("name", "make_multiplier"), (("const", 3),), ()),
                    None
                ),
                (
                    "assign",
                    "result1",
                    ("call", ("name", "double"), (("const", 4),), ()),
                    None
                ),
                (
                    "assign",
                    "result2",
                    ("call", ("name", "triple"), (("const", 4),), ()),
                    None
                )
            )
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result1") == 8
        assert self.interpreter._get_variable("result2") == 12

    def test_closure_with_multiple_variables(self):
        """Test closure capturing multiple variables."""
        ir = (
            "module",
            (
                (
                    "func_def",
                    "make_polynomial",
                    ("a", "b", "c"),
                    (
                        (
                            "func_def",
                            "poly",
                            ("x",),
                            (
                                (
                                    "return",
                                    (
                                        "+",
                                        (
                                            "+",
                                            (
                                                "*",
                                                ("name", "a"),
                                                ("**", ("name", "x"), ("const", 2))
                                            ),
                                            ("*", ("name", "b"), ("name", "x"))
                                        ),
                                        ("name", "c")
                                    )
                                ),
                            )
                        ),
                        ("return", ("name", "poly"))
                    )
                ),
                (
                    "assign",
                    "f1",
                    ("call", ("name", "make_polynomial"), (("const", 1), ("const", 0), ("const", 0)), ()),
                    None
                ),
                (
                    "assign",
                    "f2",
                    ("call", ("name", "make_polynomial"), (("const", 2), ("const", 3), ("const", 1)), ()),
                    None
                ),
                (
                    "assign",
                    "result1",
                    ("call", ("name", "f1"), (("const", 5),), ()),
                    None
                ),
                (
                    "assign",
                    "result2",
                    ("call", ("name", "f2"), (("const", 5),), ()),
                    None
                )
            )
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result1") == 25  # 1*5^2 + 0*5 + 0
        assert self.interpreter._get_variable("result2") == 66  # 2*5^2 + 3*5 + 1

    def test_nested_closure(self):
        """Test nested closures."""
        ir = (
            "module",
            (
                (
                    "func_def",
                    "make_outer",
                    ("x",),
                    (
                        (
                            "func_def",
                            "make_inner",
                            ("y",),
                            (
                                (
                                    "func_def",
                                    "innermost",
                                    ("z",),
                                    (
                                        (
                                            "return",
                                            ("+", ("+", ("name", "x"), ("name", "y")), ("name", "z"))
                                        ),
                                    )
                                ),
                                ("return", ("name", "innermost"))
                            )
                        ),
                        ("return", ("name", "make_inner"))
                    )
                ),
                (
                    "assign",
                    "outer_func",
                    ("call", ("name", "make_outer"), (("const", 10),), ()),
                    None
                ),
                (
                    "assign",
                    "inner_func",
                    ("call", ("name", "outer_func"), (("const", 20),), ()),
                    None
                ),
                (
                    "assign",
                    "result",
                    ("call", ("name", "inner_func"), (("const", 30),), ()),
                    None
                )
            )
        )
        self.interpreter.execute_program(ir)
        assert self.interpreter._get_variable("result") == 60  # 10 + 20 + 30
