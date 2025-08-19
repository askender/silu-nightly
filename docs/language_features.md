# Silu Language Features

Silu is a simple programming language that supports a subset of Python syntax. This document provides a comprehensive overview of all supported language features with examples.

## Basic Data Types

### Numbers
```silu
# Integers
x = 42
y = -17
z = 0

# Floats
pi = 3.14159
temperature = -273.15
```

### Strings
```silu
# String literals
name = "Silu"
message = 'Hello, World!'
empty = ""

# String operations (basic)
greeting = "Hello"
print(greeting)
```

### Booleans
```silu
# Boolean values
is_ready = True
is_done = False

# Boolean from expressions
result = 5 > 3  # True
```

## Variables and Assignment

### Simple Assignment
```silu
x = 10
name = "Alice"
flag = True
```

### Multiple Assignment (if supported)
```silu
# Note: Check current implementation for multiple assignment support
a = b = c = 5
```

## Arithmetic Operations

### Binary Operations
```silu
# Basic arithmetic
a = 10 + 5      # Addition: 15
b = 20 - 8      # Subtraction: 12
c = 6 * 7       # Multiplication: 42
d = 15 / 3      # Division: 5.0
e = 17 // 3     # Floor division: 5
f = 17 % 3      # Modulo: 2
g = 2 ** 8      # Exponentiation: 256

# Complex expressions
result = (a + b) * c / d
```

### Unary Operations
```silu
x = 10
positive = +x   # Unary plus: 10
negative = -x   # Unary minus: -10

flag = True
opposite = not flag  # Logical not: False
```

## Comparison Operations

### Basic Comparisons
```silu
a = 10
b = 20

# Standard comparisons
equal = a == b          # False
not_equal = a != b      # True
less_than = a < b       # True
less_equal = a <= b     # True
greater_than = a > b    # False
greater_equal = a >= b  # False
```

### Chained Comparisons
```silu
x = 15
# Check if x is between 10 and 20
in_range = 10 < x < 20  # True

# Multiple chained comparisons
valid = 0 <= x <= 100 and x != 50
```

## Boolean Operations

```silu
a = True
b = False

# Logical AND
result1 = a and b       # False

# Logical OR
result2 = a or b        # True

# Complex boolean expressions
x = 10
complex_condition = (x > 5) and (x < 20) or (x == 0)
```

## Control Flow

### If Statements
```silu
x = 15

# Simple if
if x > 10:
    print("x is large")

# If-else
if x % 2 == 0:
    print("x is even")
else:
    print("x is odd")

# If-elif-else
if x < 0:
    print("negative")
elif x == 0:
    print("zero")
else:
    print("positive")
```

### While Loops
```silu
# Basic while loop
count = 0
while count < 5:
    print("Count:", count)
    count = count + 1

# While with complex condition
x = 100
while x > 1:
    x = x // 2
    print(x)
```

### For Loops
```silu
# For loop with range
for i in range(5):
    print("Iteration:", i)

# For loop with range parameters
for i in range(1, 10, 2):  # start, stop, step
    print("Odd number:", i)

# For loop with list
numbers = [1, 2, 3, 4, 5]
for num in numbers:
    print("Number:", num)
```

## Functions

### Function Definition
```silu
# Simple function
def greet():
    print("Hello!")

# Function with parameters
def greet_person(name):
    print("Hello,", name)

# Function with return value
def add(a, b):
    return a + b

# Function with multiple parameters and complex logic
def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)
```

### Function Calls
```silu
# Call simple function
greet()

# Call function with arguments
greet_person("Alice")

# Use return value
result = add(5, 3)
print("5 + 3 =", result)

# Nested function calls
big_factorial = factorial(factorial(3))
```

## Built-in Functions

### Type Conversion
```silu
# Convert to integer
x = int("42")       # 42
y = int(3.14)       # 3
z = int(True)       # 1

# Convert to float
a = float("3.14")   # 3.14
b = float(42)       # 42.0
c = float(True)     # 1.0

# Convert to string
s1 = str(42)        # "42"
s2 = str(3.14)      # "3.14"
s3 = str(True)      # "True"

# Convert to boolean
b1 = bool(1)        # True
b2 = bool(0)        # False
b3 = bool("")       # False
b4 = bool("hello")  # True
```

### Type Checking
```silu
x = 42
name = "Alice"

# Get type
print(type(x))      # <class 'int'>
print(type(name))   # <class 'str'>

# Check if instance of type
is_int = isinstance(x, int)         # True
is_str = isinstance(name, str)      # True
is_float = isinstance(x, float)     # False
```

### Input/Output
```silu
# Print output
print("Hello, World!")
print("Value:", 42)
print("Multiple", "values", "here")

# Print variables
x = 10
y = 20
print("x =", x, "y =", y)
```

## Data Structures

### Lists
```silu
# List creation
numbers = [1, 2, 3, 4, 5]
mixed = [1, "hello", True, 3.14]
empty = []

# List access (if supported)
first = numbers[0]      # 1
last = numbers[-1]      # 5

# List operations (check implementation)
length = len(numbers)   # 5 (if len() is implemented)
```

### Tuples (if supported)
```silu
# Tuple creation
point = (10, 20)
coordinates = (x, y, z)

# Tuple access
x_coord = point[0]
y_coord = point[1]
```

### Dictionaries (if supported)
```silu
# Dictionary creation
person = {"name": "Alice", "age": 30}
empty_dict = {}

# Dictionary access
name = person["name"]
age = person["age"]
```

## Advanced Features

### Lambda Expressions (if supported)
```silu
# Simple lambda
square = lambda x: x * x
result = square(5)  # 25

# Lambda with multiple parameters
add = lambda a, b: a + b
sum_result = add(3, 4)  # 7
```

### List Comprehensions (if supported)
```silu
# Basic list comprehension
squares = [x * x for x in range(5)]  # [0, 1, 4, 9, 16]

# With condition
evens = [x for x in range(10) if x % 2 == 0]  # [0, 2, 4, 6, 8]
```

## Error Handling

### Common Runtime Errors
```silu
# Division by zero
try:
    result = 10 / 0  # ZeroDivisionError
except:
    print("Cannot divide by zero")

# Undefined variable
try:
    print(undefined_var)  # NameError
except:
    print("Variable not defined")

# Type errors
try:
    result = "hello" + 5  # TypeError
except:
    print("Cannot add string and number")
```

## Comments

```silu
# Single line comment
x = 10  # End of line comment

# Multi-line comments using multiple # symbols
# This is a longer comment
# that spans multiple lines
# to explain complex logic
```

## Example Programs

### Complete Program Example
```silu
# Fibonacci sequence calculator
def fibonacci(n):
    if n <= 0:
        return 0
    elif n == 1:
        return 1
    else:
        return fibonacci(n - 1) + fibonacci(n - 2)

# Calculate and print first 10 Fibonacci numbers
print("Fibonacci sequence:")
for i in range(10):
    fib_num = fibonacci(i)
    print("F(" + str(i) + ") =", fib_num)
```

### Calculator Example
```silu
# Simple calculator
def calculate(operation, a, b):
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b != 0:
            return a / b
        else:
            print("Error: Division by zero")
            return None
    else:
        print("Unknown operation")
        return None

# Test the calculator
result1 = calculate("add", 10, 5)      # 15
result2 = calculate("multiply", 3, 7)  # 21
result3 = calculate("divide", 10, 2)   # 5.0

print("Results:", result1, result2, result3)
```

## Language Limitations

Current implementation may not support:
- Exception handling (try/except)
- Classes and objects
- Modules and imports
- Advanced data structure methods
- File I/O operations
- Decorators
- Generators
- Context managers

Check the current interpreter implementation for the most up-to-date feature support.