"""Debug script to check coverage."""

from silu.interpreter import Environment


def test_isinstance_line_117():
    """Test to cover line 117 in interpreter.py"""
    env = Environment()

    # Test isinstance with custom object that has __name__ attribute but is not a basic type
    class CustomType:
        def __init__(self, name):
            self.__name__ = name

    custom_unknown_type = CustomType("unknown")

    try:
        # This should raise NotImplementedError (covers line 117)
        env.vars["isinstance"](42, custom_unknown_type)
        print("ERROR: Should have raised NotImplementedError")
    except NotImplementedError as e:
        print(f"SUCCESS: Raised NotImplementedError as expected: {e}")
    except Exception as e:
        print(f"ERROR: Raised unexpected exception: {e}")


def test_float_line_132():
    """Test to cover line 132 in interpreter.py"""
    env = Environment()

    try:
        # Test float() error case with a complex object (covers line 132)
        env.vars["float"]([1, 2, 3])  # Passing a list should raise NotImplementedError
        print("ERROR: Should have raised NotImplementedError")
    except NotImplementedError as e:
        print(f"SUCCESS: Raised NotImplementedError as expected: {e}")
    except Exception as e:
        print(f"ERROR: Raised unexpected exception: {e}")


if __name__ == "__main__":
    print("Testing isinstance coverage (line 117):")
    test_isinstance_line_117()

    print("\nTesting float coverage (line 132):")
    test_float_line_132()
