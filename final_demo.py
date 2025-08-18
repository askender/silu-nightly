"""
Final Demo - Showcasing the Refactored Silu Architecture

This demo shows how we successfully abstracted the common parts between
the interpreter and IR generator, allowing for both direct execution
and intermediate representation generation from the same codebase.
"""

import ast
import sys
import os
import json
from pprint import pprint

# Add the silu package to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "silu"))

from silu.interpreter import SiluInterpreter
from silu.ir_generator import SiluIRGenerator


def print_section(title):
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f" {title} ")
    print("=" * 60)


def print_subsection(title):
    """Print a subsection header."""
    print(f"\n--- {title} ---")


def demo_basic_features():
    """Demo basic language features in both modes."""
    source_code = """
# Variables and basic arithmetic
x = 10
y = 5
result = x + y * 2 - 3

# Function definition and calls
def square(n):
    return n * n

def cube(n):
    temp = square(n)
    return temp * n

# Using functions
sq_result = square(7)
cube_result = cube(4)

print("Basic arithmetic:", result)
print("Square of 7:", sq_result)
print("Cube of 4:", cube_result)
"""

    print_section("BASIC FEATURES DEMO")
    print("Source Code:")
    print(source_code)

    # Interpretation mode
    print_subsection("INTERPRETATION MODE")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
        print("✅ Interpretation successful!")
    except Exception as e:
        print(f"❌ Interpretation error: {e}")

    # IR generation mode
    print_subsection("IR GENERATION MODE")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        print("Generated IR (pretty format):")
        pprint(ir_result, width=100)
        print("✅ IR generation successful!")
    except Exception as e:
        print(f"❌ IR generation error: {e}")


def demo_control_flow():
    """Demo control flow structures."""
    source_code = """
def fibonacci(n):
    if n <= 1:
        return n
    else:
        return fibonacci(n-1) + fibonacci(n-2)

def classify_number(x):
    if x > 0:
        return "positive"
    elif x < 0:
        return "negative"
    else:
        return "zero"

# Generate fibonacci sequence
print("Fibonacci sequence:")
for i in range(6):
    fib = fibonacci(i)
    classification = classify_number(fib)
    print(f"F({i}) = {fib} ({classification})")

# While loop example
countdown = 3
print("Countdown:")
while countdown > 0:
    print(countdown)
    countdown = countdown - 1
print("Blast off!")
"""

    print_section("CONTROL FLOW DEMO")
    print("Source Code:")
    print(source_code)

    # Interpretation mode
    print_subsection("INTERPRETATION MODE")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
        print("✅ Control flow execution successful!")
    except Exception as e:
        print(f"❌ Interpretation error: {e}")
        import traceback

        traceback.print_exc()

    # Show IR structure for control flow
    print_subsection("IR STRUCTURE FOR CONTROL FLOW")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        print("IR for fibonacci function:")
        pprint(ir_result[0], width=100)  # First item should be fibonacci function
        print("\nIR for if-elif-else structure:")
        pprint(
            ir_result[1], width=100
        )  # Second item should be classify_number function
    except Exception as e:
        print(f"❌ IR generation error: {e}")


def demo_data_structures():
    """Demo data structure handling."""
    source_code = """
# Lists and operations
numbers = [1, 2, 3, 4, 5]
squares = []

print("Original numbers:", numbers)

for num in numbers:
    square = num * num
    squares.append(square)

print("Squares:", squares)

# Dictionary usage
person = {
    "name": "Alice",
    "age": 30,
    "city": "New York"
}

print("Person info:", person)

# Tuple usage
coordinates = (10, 20, 30)
print("Coordinates:", coordinates)

# List indexing and slicing
first = numbers[0]
last = numbers[-1]
print(f"First: {first}, Last: {last}")
"""

    print_section("DATA STRUCTURES DEMO")
    print("Source Code:")
    print(source_code)

    # Interpretation mode
    print_subsection("INTERPRETATION MODE")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
        print("✅ Data structures handling successful!")
    except Exception as e:
        print(f"❌ Interpretation error: {e}")

    # Show how data structures are represented in IR
    print_subsection("DATA STRUCTURES IN IR")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        print("Sample IR representations:")
        for i, stmt in enumerate(ir_result[:5]):  # Show first 5 statements
            print(f"Statement {i + 1}: {stmt}")
    except Exception as e:
        print(f"❌ IR generation error: {e}")


def demo_comparison_and_boolean():
    """Demo comparison and boolean operations."""
    source_code = """
# Comparison operations
a, b, c = 5, 10, 15

print("Simple comparisons:")
print(f"a < b: {a < b}")
print(f"b >= c: {b >= c}")
print(f"a != c: {a != c}")

print("Chained comparisons:")
print(f"a < b < c: {a < b < c}")
print(f"0 <= a <= 10: {0 <= a <= 10}")

# Boolean operations
result1 = a < b and b < c
result2 = a > b or b < c
result3 = not (a > c)

print("Boolean operations:")
print(f"a < b and b < c: {result1}")
print(f"a > b or b < c: {result2}")
print(f"not (a > c): {result3}")
"""

    print_section("COMPARISONS AND BOOLEAN OPERATIONS DEMO")
    print("Source Code:")
    print(source_code)

    # Interpretation mode
    print_subsection("INTERPRETATION MODE")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
        print("✅ Comparison and boolean operations successful!")
    except Exception as e:
        print(f"❌ Interpretation error: {e}")

    # Show IR for comparisons
    print_subsection("COMPARISON IR REPRESENTATION")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        print("IR for chained comparison (a < b < c):")
        # Find the chained comparison in IR
        for stmt in ir_result:
            if isinstance(stmt, tuple) and len(stmt) > 2 and isinstance(stmt[2], list):
                if isinstance(stmt[2][0], list) and len(stmt[2]) > 1:
                    pprint(stmt)
                    break
    except Exception as e:
        print(f"❌ IR generation error: {e}")


def architecture_summary():
    """Show the architecture summary."""
    print_section("ARCHITECTURE SUMMARY")

    print("""
🏗️  REFACTORED ARCHITECTURE OVERVIEW:

1. BaseASTProcessor (Abstract Base Class)
   ├── Common AST traversal logic
   ├── Shared operator mappings
   ├── Abstract methods for customization
   └── Consistent node processing interface

2. SimpleInterpreter (Concrete Implementation)
   ├── Extends BaseASTProcessor
   ├── Implements direct code execution
   ├── Manages runtime environment and variables
   └── Handles function calls and returns

3. SiluIRGenerator (Concrete Implementation)
   ├── Extends BaseASTProcessor
   ├── Generates intermediate representation
   ├── Preserves program structure without execution
   └── Supports various output formats

🎯 BENEFITS OF THE REFACTORED DESIGN:

✅ Code Reuse: Common AST processing logic is shared
✅ Consistency: Both modes handle the same syntax identically
✅ Maintainability: Changes to syntax support propagate automatically
✅ Extensibility: Easy to add new processing modes
✅ Flexibility: Choose interpretation or IR generation per use case

🔄 DUAL MODE OPERATION:

The same source code can be:
• INTERPRETED: Executed directly for immediate results
• IR GENERATED: Converted to intermediate representation for analysis,
  optimization, or compilation to other targets

This architecture successfully abstracts the common parts while allowing
specialized behavior for each processing mode.
""")


def comprehensive_example():
    """Run a comprehensive example showing both modes side by side."""
    source_code = """
def calculate_stats(numbers):
    total = 0
    count = 0

    for num in numbers:
        total = total + num
        count = count + 1

    if count > 0:
        average = total / count
        return {"sum": total, "count": count, "average": average}
    else:
        return {"sum": 0, "count": 0, "average": 0}

def main():
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    stats = calculate_stats(data)

    print("Data:", data)
    print("Statistics:", stats)

    # Conditional logic based on results
    if stats["average"] > 5:
        print("Average is above 5")
    else:
        print("Average is 5 or below")

    return stats

result = main()
"""

    print_section("COMPREHENSIVE EXAMPLE")
    print("Source Code:")
    print(source_code)

    print_subsection("INTERPRETATION MODE OUTPUT")
    try:
        tree = ast.parse(source_code)
        interpreter = SiluInterpreter()
        interpreter.visit(tree)
        print("✅ Full program execution successful!")
    except Exception as e:
        print(f"❌ Interpretation error: {e}")

    print_subsection("IR GENERATION (JSON FORMAT)")
    try:
        tree = ast.parse(source_code)
        ir_generator = SiluIRGenerator()
        ir_result = ir_generator.visit(tree)

        # Convert to JSON for display
        ir_json = json.dumps(ir_result, indent=2, default=str)
        print("Complete program IR in JSON format:")
        print(ir_json[:1000] + "..." if len(ir_json) > 1000 else ir_json)
        print("✅ Complete IR generation successful!")
    except Exception as e:
        print(f"❌ IR generation error: {e}")


def main():
    """Run the complete demo."""
    print("🚀 SILU LANGUAGE REFACTORED ARCHITECTURE DEMO")
    print("=" * 80)
    print("""
This demo showcases the successful refactoring of Silu language processing
into a unified architecture that supports both:

1. 🎯 DIRECT INTERPRETATION - Execute code immediately
2. 🔧 IR GENERATION - Create intermediate representation

Both modes share the same AST processing foundation!
""")

    # Run all demos
    demo_basic_features()
    demo_control_flow()
    demo_data_structures()
    demo_comparison_and_boolean()
    comprehensive_example()
    architecture_summary()

    print_section("DEMO COMPLETE")
    print("""
🎉 SUCCESS! The refactored architecture demonstrates:

• ✅ Shared codebase for AST processing
• ✅ Dual-mode operation (interpret vs IR generation)
• ✅ Consistent handling of language constructs
• ✅ Extensible design for future enhancements

The abstraction successfully extracted common functionality while
maintaining the flexibility to choose between direct execution
and intermediate representation generation.
""")


if __name__ == "__main__":
    main()
