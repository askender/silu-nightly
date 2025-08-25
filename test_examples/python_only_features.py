# Python features not supported by Silu
print("Testing Python-only features that should fail in Silu:")

# Classes (not supported in Silu)
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    def greet(self):
        return f"Hello, I'm {self.name}"

# Create an instance
person = Person("Alice", 25)
print(person.greet())

# Dictionaries (not supported in Silu)
student = {
    "name": "Bob",
    "age": 20,
    "grades": [85, 92, 78]
}
print("Student:", student["name"])

# List comprehensions (not supported in Silu)
squares = [x**2 for x in range(5)]
print("Squares:", squares)

# Lambda functions (not supported in Silu)
double = lambda x: x * 2
print("Double of 5:", double(5))

# Try-except error handling (not supported in Silu)
try:
    result = 10 / 0
except ZeroDivisionError:
    print("Cannot divide by zero")

# Import statements (not supported in Silu)
import math
print("Pi:", math.pi)

# With statements (not supported in Silu)
with open("test.txt", "w") as f:
    f.write("Hello World")

# Generator expressions (not supported in Silu)
gen = (x for x in range(3))
print("Generator:", list(gen))
