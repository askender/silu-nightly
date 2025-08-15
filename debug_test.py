"""Debug test to check coverage."""

import pytest
from silu.interpreter import Environment


def test_isinstance_coverage():
    """Test to cover line 117 in interpreter.py"""
    env = Environment()

    # Test isinstance with custom object that has __name__ attribute but is not a basic type
    class CustomType:
        def __init__(self, name):
            self.__name__ = name

    custom_unknown_type = CustomType("unknown")

    # This should raise NotImplementedError (covers line 117)
    with pytest.raises(NotImplementedError):
        env.vars["isinstance"](42, custom_unknown_type)
        print("Exception raised")  # This line should not be reached


def test_float_coverage():
    """Test to cover line 132 in interpreter.py"""
    env = Environment()

    # Test float() error case with a complex object (covers line 132)
    with pytest.raises(NotImplementedError):
        env.vars["float"]([1, 2, 3])  # Passing a list should raise NotImplementedError
        print("Exception raised")  # This line should not be reached


if __name__ == "__main__":
    test_isinstance_coverage()
    test_float_coverage()
