# Control flow structures test
print("Testing control flow:")

# If-else statements
x = 10
if x > 5:
    print("x is greater than 5")
else:
    print("x is not greater than 5")

# If-elif-else chain
score = 85
if score >= 90:
    print("Grade: A")
elif score >= 80:
    print("Grade: B")
elif score >= 70:
    print("Grade: C")
elif score >= 60:
    print("Grade: D")
else:
    print("Grade: F")

# While loop
print("Counting with while loop:")
counter = 1
while counter <= 5:
    print("Count:", counter)
    counter = counter + 1

# For loop with range
print("Counting with for loop:")
for i in range(1, 6):
    print("Number:", i)

# For loop with list
print("Iterating through a list:")
fruits = ["apple", "banana", "cherry", "date"]
for fruit in fruits:
    print("Fruit:", fruit)

# Nested control structures
print("Multiplication table (3x3):")
for i in range(1, 4):
    for j in range(1, 4):
        product = i * j
        print(f"{i} x {j} = {product}")

# Boolean conditions
a = 15
b = 10
if a > b and a > 0:
    print("a is positive and greater than b")

if b < 20 or b == 10:
    print("b is less than 20 or equals 10")

# Break and continue in loops
print("Testing break and continue:")
for num in range(1, 11):
    if num == 3:
        continue  # Skip 3
    if num == 8:
        break  # Stop at 8
    print("Processing:", num)
