# Variables and string operations test
print("Testing variables and strings:")

# String variables
name = "Alice"
greeting = "Hello"
print(greeting, name)

# String concatenation
full_greeting = greeting + ", " + name + "!"
print(full_greeting)

# String repetition
separator = "-" * 20
print(separator)

# String methods and operations
message = "Python Programming"
print("Original:", message)
print("Length:", len(message))
print("Uppercase:", message.upper())
print("Lowercase:", message.lower())

# String indexing and slicing
print("First character:", message[0])
print("Last character:", message[-1])
print("First 6 characters:", message[:6])
print("Last 11 characters:", message[7:])

# Variables with different types
age = 25
height = 5.8
is_student = True

print("Name:", name)
print("Age:", age)
print("Height:", height)
print("Is student:", is_student)

# Type checking
print("Type of name:", type(name))
print("Type of age:", type(age))
print("Type of height:", type(height))
print("Type of is_student:", type(is_student))

# String formatting
info = "My name is " + name + " and I am " + str(age) + " years old."
print(info)
