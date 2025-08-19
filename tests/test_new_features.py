"""
Unit tests for new Silu language features.

Tests for break/continue statements, assert statements,
annotated assignments, and lambda functions.
"""

import ast
import pytest
from silu.interpreter import SiluInterpreter


class TestBreakContinue:
    """Test break and continue statements."""

    def test_break_in_while_loop(self):
        """Test break statement in while loop."""
        code = """
i = 0
result = []
while i < 10:
    i = i + 1
    if i == 3:
        break
    result.append(i)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2]
        assert interpreter.env.get("i") == 3

    def test_continue_in_while_loop(self):
        """Test continue statement in while loop."""
        code = """
i = 0
result = []
while i < 5:
    i = i + 1
    if i == 3:
        continue
    result.append(i)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2, 4, 5]

    def test_break_in_for_loop(self):
        """Test break statement in for loop."""
        code = """
result = []
for i in [1, 2, 3, 4, 5]:
    if i == 4:
        break
    result.append(i)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2, 3]

    def test_continue_in_for_loop(self):
        """Test continue statement in for loop."""
        code = """
result = []
for i in [1, 2, 3, 4, 5]:
    if i == 3:
        continue
    result.append(i)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2, 4, 5]

    def test_for_loop_with_else_no_break(self):
        """Test for loop with else clause when no break occurs."""
        code = """
result = []
for i in [1, 2, 3]:
    result.append(i)
else:
    result.append("completed")
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2, 3, "completed"]

    def test_for_loop_with_else_break(self):
        """Test for loop with else clause when break occurs."""
        code = """
result = []
for i in [1, 2, 3, 4, 5]:
    result.append(i)
    if i == 3:
        break
else:
    result.append("completed")
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [1, 2, 3]

    def test_nested_loops_with_break(self):
        """Test nested loops with break."""
        code = """
result = []
for i in [1, 2]:
    for j in [1, 2, 3]:
        if j == 2:
            break
        result.append((i, j))
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        # break only affects inner loop
        assert interpreter.env.get("result") == [(1, 1), (2, 1)]


class TestAssert:
    """Test assert statements."""

    def test_assert_true(self):
        """Test assert with True condition."""
        code = "assert True"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        # Should not raise any exception
        interpreter.visit(tree)

    def test_assert_expression_true(self):
        """Test assert with true expression."""
        code = "assert 5 > 3"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        # Should not raise any exception
        interpreter.visit(tree)

    def test_assert_false_without_message(self):
        """Test assert with False condition and no message."""
        code = "assert False"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        with pytest.raises(AssertionError):
            interpreter.visit(tree)

    def test_assert_false_with_message(self):
        """Test assert with False condition and message."""
        code = 'assert False, "This should fail"'
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        with pytest.raises(AssertionError, match="This should fail"):
            interpreter.visit(tree)

    def test_assert_expression_false(self):
        """Test assert with false expression."""
        code = "assert 3 > 5"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        with pytest.raises(AssertionError):
            interpreter.visit(tree)

    def test_assert_with_variable(self):
        """Test assert with variable."""
        code = """
x = 10
assert x == 10, "x should be 10"
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        # Should not raise any exception
        interpreter.visit(tree)

    def test_assert_complex_expression(self):
        """Test assert with complex expression."""
        code = """
numbers = [1, 2, 3]
assert len(numbers) == 3 and numbers[0] == 1
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        # Should not raise any exception
        interpreter.visit(tree)


class TestAnnotatedAssignment:
    """Test annotated assignments."""

    def test_simple_annotated_assignment(self):
        """Test simple annotated assignment."""
        code = "x: int = 5"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("x") == 5

    def test_annotated_assignment_different_types(self):
        """Test annotated assignments with different types."""
        code = """
name: str = "Alice"
age: int = 25
height: float = 5.6
is_student: bool = True
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("name") == "Alice"
        assert interpreter.env.get("age") == 25
        assert interpreter.env.get("height") == 5.6
        assert interpreter.env.get("is_student") is True

    def test_annotated_assignment_without_value(self):
        """Test annotated assignment without initial value."""
        code = "future_value: int"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        # Should not raise exception, but variable shouldn't be set
        interpreter.visit(tree)
        with pytest.raises(NameError):
            interpreter.env.get("future_value")

    def test_annotated_assignment_complex_annotation(self):
        """Test annotated assignment with complex annotation."""
        code = """
items: list = [1, 2, 3]
mapping: dict = {"key": "value"}
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("items") == [1, 2, 3]
        assert interpreter.env.get("mapping") == {"key": "value"}


class TestLambda:
    """Test lambda functions."""

    def test_simple_lambda(self):
        """Test simple lambda function."""
        code = """
add = lambda a, b: a + b
result = add(3, 5)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 8

    def test_lambda_single_parameter(self):
        """Test lambda with single parameter."""
        code = """
square = lambda x: x * x
result = square(4)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 16

    def test_lambda_no_parameters(self):
        """Test lambda with no parameters."""
        code = """
get_answer = lambda: 42
result = get_answer()
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 42

    def test_lambda_immediate_call(self):
        """Test lambda called immediately."""
        code = "result = (lambda x: x * 2)(7)"
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 14

    def test_lambda_in_list(self):
        """Test lambda functions in a list."""
        code = """
operations = [
    lambda x: x + 1,
    lambda x: x * 2,
    lambda x: x - 3
]
value = 5
for op in operations:
    value = op(value)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        # 5 -> 6 -> 12 -> 9
        assert interpreter.env.get("value") == 9

    def test_lambda_with_closure(self):
        """Test lambda with closure over outer variables."""
        code = """
def make_multiplier(factor):
    return lambda x: x * factor

double = make_multiplier(2)
triple = make_multiplier(3)
result1 = double(5)
result2 = triple(4)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result1") == 10
        assert interpreter.env.get("result2") == 12

    def test_lambda_wrong_argument_count(self):
        """Test lambda with wrong number of arguments."""
        code = """
add = lambda a, b: a + b
result = add(1)  # Missing second argument
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        with pytest.raises(
            TypeError, match="Lambda takes 2 arguments but 1 were given"
        ):
            interpreter.visit(tree)

    def test_lambda_complex_body(self):
        """Test lambda with complex body expression."""
        code = """
condition_check = lambda x: x > 0 and x < 100
result1 = condition_check(50)
result2 = condition_check(-5)
result3 = condition_check(150)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result1") is True
        assert interpreter.env.get("result2") is False
        assert interpreter.env.get("result3") is False


class TestCombinedFeatures:
    """Test combinations of new features."""

    def test_lambda_with_assert(self):
        """Test lambda function with assert."""
        code = """
safe_divide = lambda a, b: a / b
result = safe_divide(10, 2)
assert result == 5.0
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 5.0

    def test_annotated_lambda_assignment(self):
        """Test annotated assignment with lambda."""
        code = """
calculator = lambda x, y: x + y
result = calculator(3, 4)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == 7

    def test_loop_with_lambda_and_break(self):
        """Test loop with lambda and break statement."""
        code = """
is_even = lambda n: n % 2 == 0
result = []
for num in [1, 2, 3, 4, 5, 6, 7, 8]:
    if num > 6:
        break
    if is_even(num):
        result.append(num)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        assert interpreter.env.get("result") == [2, 4, 6]

    def test_function_with_all_features(self):
        """Test function using all new features."""
        code = """
def process_numbers(numbers):
    is_valid = lambda n: isinstance(n, int) and n > 0
    result: list = []

    for num in numbers:
        if not is_valid(num):
            continue
        if num > 100:
            break
        result.append(num * 2)

    assert isinstance(result, list)
    return result

test_data = [1, 2, -3, 4, 5, 101, 6]
filtered = process_numbers(test_data)
"""
        interpreter = SiluInterpreter()
        tree = ast.parse(code)
        interpreter.visit(tree)
        # Process: 1->2, 2->4, skip -3, 4->8, 5->10, break at 101
        assert interpreter.env.get("filtered") == [2, 4, 8, 10]
