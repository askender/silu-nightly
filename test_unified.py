"""
Test file for the simple interpreter
"""

import ast
import sys
import os

# Add the silu package to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "silu"))

from silu.interpreter import SiluInterpreter
from silu.ir_generator import SiluIRGenerator


def test_basic_arithmetic():
    """Test basic arithmetic operations."""
    source_code = """
x = 10
y = 5
result = x + y * 2
print("Result:", result)
"""

    print("=== Testing Basic Arithmetic ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()

    # Test IR generation
    print("\n--- IR Generation Mode ---")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        import pprint

        pprint.pprint(ir_result)
    except Exception as e:
        print(f"IR generation error: {e}")


def test_function_definition():
    """Test function definition and calls."""
    source_code = """
def add(a, b):
    return a + b

def multiply(x, y):
    result = x * y
    return result

sum_result = add(3, 4)
mult_result = multiply(5, 6)
print("Sum:", sum_result)
print("Product:", mult_result)
"""

    print("\n\n=== Testing Function Definition ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()


def test_control_flow():
    """Test control flow structures."""
    source_code = """
def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)

print("Factorial of 5:", factorial(5))

for i in range(3):
    print("Loop iteration:", i)

x = 3
while x > 0:
    print("Countdown:", x)
    x = x - 1
"""

    print("\n\n=== Testing Control Flow ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()


def test_comparisons():
    """Test comparison operations."""
    source_code = """
a = 5
b = 10
c = 15

print("a < b:", a < b)
print("b >= a:", b >= a)
print("c != a:", c != a)

# Chained comparisons
print("a < b < c:", a < b < c)
print("1 <= a <= 10:", 1 <= a <= 10)

# Boolean operations
result1 = a < b and b < c
result2 = c < a or a < b
print("Boolean results:", result1, result2)
"""

    print("\n\n=== Testing Comparisons ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()


def test_data_structures():
    """Test lists and other data structures."""
    source_code = """
# Lists
numbers = [1, 2, 3, 4, 5]
mixed = [1, "hello", 3.14, True]

print("Numbers:", numbers)
print("Mixed:", mixed)

# List indexing
first = numbers[0]
last = numbers[-1]
print("First:", first, "Last:", last)

# Dictionary
person = {"name": "Alice", "age": 30}
print("Person:", person)

# Tuple
coordinates = (10, 20)
print("Coordinates:", coordinates)
"""

    print("\n\n=== Testing Data Structures ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()


def test_comprehensive_example():
    """Test a comprehensive example combining multiple features."""
    source_code = """
def fibonacci(n):
    if n <= 1:
        return n
    else:
        return fibonacci(n-1) + fibonacci(n-2)

def is_even(x):
    return x % 2 == 0

print("=== Fibonacci Sequence ===")
for i in range(8):
    fib = fibonacci(i)
    even_odd = "even" if is_even(fib) else "odd"
    print("F(" + str(i) + ") = " + str(fib) + " (" + even_odd + ")")

print("=== List Processing ===")
numbers = [1, 2, 3, 4, 5]
squares = []
for num in numbers:
    square = num * num
    squares.append(square)

print("Numbers:", numbers)
print("Squares:", squares)

total = 0
for square in squares:
    total = total + square

print("Sum of squares:", total)
"""

    print("\n\n=== Testing Comprehensive Example ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")
        import traceback

        traceback.print_exc()


def test_unified_modes():
    """Test both interpretation and IR generation on the same code."""
    source_code = """
def greet(name):
    message = "Hello, " + name + "!"
    return message

result = greet("World")
print(result)

# Test conditionals
x = 42
if x > 40:
    print("x is greater than 40")
else:
    print("x is not greater than 40")
"""

    print("\n\n=== Testing Unified Modes ===")
    print("Source code:")
    print(source_code)

    # Test interpretation
    print("\n--- Interpretation Mode ---")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
    except Exception as e:
        print(f"Interpretation error: {e}")

    # Test IR generation
    print("\n--- IR Generation Mode ---")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        import pprint

        pprint.pprint(ir_result)
    except Exception as e:
        print(f"IR generation error: {e}")


def main():
    """Run all tests."""
    print("Testing Unified Silu Architecture")
    print("=" * 60)

    test_basic_arithmetic()
    test_function_definition()
    test_control_flow()
    test_comparisons()
    test_data_structures()
    test_comprehensive_example()
    test_unified_modes()

    print("\n" + "=" * 60)
    print("Testing complete!")


if __name__ == "__main__":
    main()
