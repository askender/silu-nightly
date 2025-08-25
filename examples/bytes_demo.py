#!/usr/bin/env python3
"""
Bytes Functionality Demo for Silu Language

This demo showcases the bytes data type functionality in Silu,
including creation, operations, comparisons, and usage patterns.
"""

def main():
    print("=== Silu Bytes Functionality Demo ===")
    print()

    # Demo 1: Basic bytes creation
    print("1. Basic Bytes Creation")
    print("-----------------------")

    # Simple bytes literals
    greeting = b"Hello, World!"
    empty = b""
    print("Greeting bytes:", greeting)
    print("Empty bytes:", empty)
    print("Greeting length:", len(greeting))
    print("Empty length:", len(empty))
    print()

    # Demo 2: Bytes with escape sequences
    print("2. Bytes with Escape Sequences")
    print("------------------------------")

    newline_data = b"Line 1\nLine 2\nLine 3"
    tab_data = b"Col1\tCol2\tCol3"
    mixed_escapes = b"Quote: \"Hello\"\nTab: \tEnd"

    print("Newline data:", newline_data)
    print("Tab data:", tab_data)
    print("Mixed escapes:", mixed_escapes)
    print()

    # Demo 3: Binary data with hex/octal escapes
    print("3. Binary Data with Hex Escapes")
    print("-------------------------------")

    null_byte = b"\x00"
    high_bytes = b"\x80\x90\xA0\xB0\xC0\xD0\xE0\xF0\xFF"
    mixed_binary = b"Header\x00\x01\x02Data\xFF\xFE\xFD"

    print("Null byte:", null_byte)
    print("High bytes:", high_bytes)
    print("Mixed binary:", mixed_binary)
    print("High bytes length:", len(high_bytes))
    print()

    # Demo 4: Bytes operations
    print("4. Bytes Operations")
    print("-------------------")

    # Concatenation
    part1 = b"Hello"
    part2 = b", "
    part3 = b"Silu!"
    combined = part1 + part2 + part3
    print("Concatenation:", part1, "+", part2, "+", part3, "=", combined)

    # Repetition
    pattern = b"ABC"
    repeated = pattern * 4
    print("Repetition:", pattern, "* 4 =", repeated)

    # Chain operations
    complex_result = b"Pre-" + b"fix" * 2 + b"-Post"
    print("Complex operation:", complex_result)
    print()

    # Demo 5: Bytes comparisons
    print("5. Bytes Comparisons")
    print("--------------------")

    data1 = b"test"
    data2 = b"test"
    data3 = b"other"

    print("data1:", data1)
    print("data2:", data2)
    print("data3:", data3)
    print("data1 == data2:", data1 == data2)
    print("data1 != data3:", data1 != data3)
    print("data1 < data3:", data1 < data3)
    print("data3 > data1:", data3 > data1)
    print()

    # Demo 6: Mixed type comparisons
    print("6. Mixed Type Comparisons")
    print("-------------------------")

    bytes_val = b"123"
    string_val = "123"
    int_val = 123

    print("bytes_val:", bytes_val)
    print("string_val:", string_val)
    print("int_val:", int_val)
    print("bytes_val == string_val:", bytes_val == string_val)
    print("bytes_val == int_val:", bytes_val == int_val)
    print("string_val == int_val:", string_val == int_val)
    print()

    # Demo 7: Bytes in data structures
    print("7. Bytes in Data Structures")
    print("---------------------------")

    # List of bytes
    byte_list = [b"first", b"second", b"third"]
    print("List of bytes:", byte_list)

    # Tuple with bytes
    byte_tuple = (b"header", b"\x00\x01", b"footer")
    print("Tuple with bytes:", byte_tuple)

    # Dictionary with bytes
    byte_dict = {
        b"key1": "value1",
        "key2": b"value2",
        b"key3": b"value3"
    }
    print("Dictionary with bytes:", byte_dict)
    print()

    # Demo 8: Bytes processing patterns
    print("8. Bytes Processing Patterns")
    print("----------------------------")

    # Simulating packet processing
    packets = [
        b"\x01\x02\x03DATA1",
        b"\x04\x05\x06DATA2",
        b"\x07\x08\x09DATA3"
    ]

    print("Processing packets:")
    i = 0
    for packet in packets:
        first_byte = packet[0]  # First byte
        print("  Packet " + str(i + 1) + ":")
        print("    First byte:", first_byte)
        print("    Full packet:", packet)
        print("    Length:", len(packet))
        i = i + 1
    print()

    # Demo 9: Bytes validation and filtering
    print("9. Bytes Validation and Filtering")
    print("---------------------------------")

    data_samples = [
        b"valid_data",
        b"",
        b"\x00\x00\x00",
        b"text_content",
        b"\xFF\xFE\xFD"
    ]

    non_empty_data = []
    text_like_data = []

    for sample in data_samples:
        if len(sample) > 0:
            non_empty_data.append(sample)

        # Check if contains only printable ASCII-like bytes (simplified)
        is_text_like = True
        j = 0
        while j < len(sample):
            byte_val = sample[j]
            if byte_val < 32 or byte_val > 126:
                is_text_like = False
                break
            j = j + 1

        if is_text_like and len(sample) > 0:
            text_like_data.append(sample)

    print("All samples:", data_samples)
    print("Non-empty data:", non_empty_data)
    print("Text-like data:", text_like_data)
    print()

    # Demo 10: Bytes construction patterns
    print("10. Bytes Construction Patterns")
    print("-------------------------------")

    # Building bytes dynamically (simulated)
    prefix = b"HEADER:"
    middle = b"Important Data"
    suffix = b":END"
    constructed = prefix + middle + suffix
    print("Constructed bytes:", constructed)

    # Repeating patterns
    separator = b"-" * 10
    framed_data = separator + b"CONTENT" + separator
    print("Framed data:", framed_data)

    # Multiple concatenations
    protocol_header = b"PROTO" + b"VER1" + b"TYPE" + b"DATA"
    print("Protocol header:", protocol_header)
    print()

    print("=== Demo Complete ===")
    print("Bytes functionality includes:")
    print("- Literal creation with b\"\" syntax")
    print("- Escape sequences (\\n, \\t, \\x00, etc.)")
    print("- Concatenation with + operator")
    print("- Repetition with * operator")
    print("- All comparison operators (==, !=, <, >, etc.)")
    print("- Integration with lists, tuples, and dictionaries")
    print("- Length calculation with len()")
    print("- Type safety (bytes != strings != integers)")

main()
