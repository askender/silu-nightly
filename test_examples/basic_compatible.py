# Basic compatible operations test
print("Testing basic compatible features:")

# Simple variables
x = 10
y = 20
print("x =", x)
print("y =", y)

# Basic arithmetic
sum_result = x + y
diff_result = y - x
mult_result = x * y
print("x + y =", sum_result)
print("y - x =", diff_result)
print("x * y =", mult_result)

# Simple conditions
if x < y:
    print("x is less than y")

if x > 5:
    print("x is greater than 5")

# Simple loop
print("Counting:")
for i in range(1, 6):
    print(i)

# List operations
numbers = [1, 2, 3, 4, 5]
print("Numbers:", numbers)

total = 0
for num in numbers:
    total = total + num
print("Sum of numbers:", total)

# String operations (basic)
name = "World"
greeting = "Hello " + name
print(greeting)

# Boolean operations
is_positive = x > 0
is_even = x % 2 == 0
print("x is positive:", is_positive)
print("x is even:", is_even)
