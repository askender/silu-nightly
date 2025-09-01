#!/usr/bin/env python3
"""
Tuple Unpacking Demo for Silu Language

This demo showcases the tuple unpacking functionality in for loops,
which allows elegant iteration over sequences of tuples.
"""


def main():
    print("=== Silu Tuple Unpacking Demo ===")
    print()

    # Demo 1: Basic tuple unpacking with list of tuples
    print("1. Basic Tuple Unpacking")
    print("------------------------")
    coordinates = [(0, 0), (1, 2), (3, 4), (5, 6)]
    print("Coordinates:", coordinates)

    distances = []
    for x, y in coordinates:
        distance = (x * x + y * y) ** 0.5
        distances.append(distance)
        print("Point (" + str(x) + ", " + str(y) + ") -> Distance: " + str(distance))

    print("All distances:", distances)
    print()

    # Demo 2: Dictionary iteration with .items()
    print("2. Dictionary Items Unpacking")
    print("-----------------------------")
    inventory = {"apples": 150, "bananas": 80, "oranges": 200, "grapes": 45}

    print("Inventory:")
    total_items = 0
    for item, quantity in inventory.items():
        total_items = total_items + quantity
        print("  " + item + ": " + str(quantity))

    print("Total items in inventory: " + str(total_items))
    print()

    # Demo 3: Three-element unpacking
    print("3. Multiple Element Unpacking")
    print("-----------------------------")
    student_records = [
        ("Alice", "Computer Science", 3.8),
        ("Bob", "Mathematics", 3.6),
        ("Charlie", "Physics", 3.9),
        ("Diana", "Chemistry", 3.7),
    ]

    print("Student Records:")
    honor_students = []
    for name, major, gpa in student_records:
        status = "Honor Student" if gpa >= 3.7 else "Regular Student"
        if gpa >= 3.7:
            honor_students.append(name)
        print("  " + name + " (" + major + ") - GPA: " + str(gpa) + " - " + status)

    print("Honor students: " + str(honor_students))
    print()

    # Demo 4: Nested data processing
    print("4. Nested Data Processing")
    print("-------------------------")
    sales_data = [
        ("January", [("Product A", 100), ("Product B", 150), ("Product C", 75)]),
        ("February", [("Product A", 120), ("Product B", 130), ("Product C", 90)]),
        ("March", [("Product A", 110), ("Product B", 160), ("Product C", 85)]),
    ]

    monthly_totals = []
    for month, products in sales_data:
        month_total = 0
        print(month + " sales:")
        for product, amount in products:
            month_total = month_total + amount
            print("  " + product + ": " + str(amount))
        monthly_totals.append((month, month_total))
        print("  Total for " + month + ": " + str(month_total))
        print()

    print("Monthly Summary:")
    for month, total in monthly_totals:
        print("  " + month + ": " + str(total))
    print()

    # Demo 5: Key-value pair processing
    print("5. Configuration Processing")
    print("---------------------------")
    config = {
        "host": "localhost",
        "port": 8080,
        "debug": True,
        "max_connections": 100,
        "timeout": 30,
    }

    print("Configuration settings:")
    for setting, value in config.items():
        setting_type = type(value).__name__
        print("  " + setting + " = " + str(value) + " (" + setting_type + ")")

    # Extract numeric settings
    numeric_settings = {}
    for key, value in config.items():
        if isinstance(value, int):
            numeric_settings[key] = value

    print("Numeric settings: " + str(numeric_settings))
    print()

    # Demo 6: Data transformation
    print("6. Data Transformation")
    print("----------------------")
    raw_data = [("A", 1), ("B", 2), ("C", 3), ("A", 4), ("B", 5), ("C", 6)]
    print("Raw data:", raw_data)

    # Group by first element
    grouped = {}
    for key, value in raw_data:
        if grouped.get(key) is None:
            grouped[key] = []
        grouped[key].append(value)

    print("Grouped data:")
    for category, values in grouped.items():
        total = 0
        for val in values:
            total = total + val
        print("  " + category + ": " + str(values) + " (sum: " + str(total) + ")")

    print()
    print("=== Demo Complete ===")


main()
