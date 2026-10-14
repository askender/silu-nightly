#!/usr/bin/env python3
"""
Tests for class support (dataclass semantics = Rust struct + impl)
in the IR interpreter: instantiation, self binding, field access,
defaults, kwargs, and type-contract violations.
"""

import ast
import io
from contextlib import redirect_stdout

import pytest

from silu.ir_generator import SiluIRGenerator
from silu.ir_interpreter import IRInterpreter


def run_source(src: str) -> str:
    """Run Silu source through IR generation + IR interpreter, return stdout."""
    ir = SiluIRGenerator().visit(ast.parse(src))
    buf = io.StringIO()
    with redirect_stdout(buf):
        IRInterpreter().execute_program(ir)
    return buf.getvalue()


JOINT_STATE = """
class JointState:
    position: float
    velocity: float

    def is_moving(self) -> bool:
        return self.velocity > 0.01
"""


class TestClassBasics:
    """JointState full example: construction, methods, field printing."""

    def test_construct_and_method_call(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st.is_moving())
"""
        )
        assert out == "True\n"

    def test_method_false_branch(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1.0, 0.0)
print(st.is_moving())
"""
        )
        assert out == "False\n"

    def test_field_read(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1.5, 2.5)
print(st.position)
print(st.velocity)
"""
        )
        assert out == "1.5\n2.5\n"

    def test_field_write_and_readback(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
st.velocity = 3.5
print(st.velocity)
"""
        )
        assert out == "3.5\n"

    def test_instance_repr(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st)
"""
        )
        assert out == "JointState(position=1.0, velocity=2.0)\n"

    def test_int_coerced_to_float_field(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(1, 2)
print(st)
"""
        )
        assert out == "JointState(position=1.0, velocity=2.0)\n"


class TestDataclassRules:
    """Defaults, keyword construction, positional/keyword mixing."""

    def test_default_value(self):
        out = run_source(
            """
class Point:
    x: float
    y: float = 0.0

p = Point(1.5)
print(p)
"""
        )
        assert out == "Point(x=1.5, y=0.0)\n"

    def test_keyword_construction(self):
        out = run_source(
            """
class Point:
    x: float
    y: float

p = Point(y=2.0, x=1.0)
print(p)
"""
        )
        assert out == "Point(x=1.0, y=2.0)\n"

    def test_mixed_positional_keyword(self):
        out = run_source(
            """
class Point:
    x: float
    y: float = 0.0
    z: float = 3.0

p = Point(1.0, z=9.0)
print(p)
"""
        )
        assert out == "Point(x=1.0, y=0.0, z=9.0)\n"

    def test_missing_required_argument(self):
        with pytest.raises(TypeError, match="missing required argument"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0)
"""
            )

    def test_too_many_arguments(self):
        with pytest.raises(TypeError, match="takes at most"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0, 3.0)
"""
            )

    def test_unexpected_keyword(self):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0, speed=2.0)
"""
            )

    def test_duplicate_argument(self):
        with pytest.raises(TypeError, match="multiple values"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0, position=2.0)
"""
            )

    def test_default_before_non_default_rejected(self):
        with pytest.raises(TypeError, match="without default follows"):
            run_source(
                """
class Bad:
    a: int = 1
    b: int
"""
            )


class TestTypeContracts:
    """Field annotation violations raise TypeError."""

    def test_int_field_rejects_float(self):
        with pytest.raises(TypeError, match="annotated 'int'"):
            run_source(
                """
class Rec:
    n: int

r = Rec(1.5)
"""
            )

    def test_str_field_rejects_int(self):
        with pytest.raises(TypeError, match="annotated 'str'"):
            run_source(
                """
class Rec:
    s: str

r = Rec(42)
"""
            )

    def test_write_violation_rejected(self):
        with pytest.raises(TypeError, match="annotated 'int'"):
            run_source(
                """
class Rec:
    n: int

r = Rec(1)
r.n = 2.5
"""
            )


class TestMethods:
    """self binding, field mutation inside methods, method inter-calls."""

    def test_method_mutates_field(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(0.0, 1.0)
st.velocity = st.velocity * 3.0
print(st.velocity)
"""
        )
        assert out == "3.0\n"

    def test_method_calls_method(self):
        out = run_source(
            JOINT_STATE
            + """
st = JointState(0.0, 5.0)
print(st.is_moving())
"""
        )
        assert out == "True\n"

    def test_method_with_args_and_return(self):
        out = run_source(
            """
class Acc:
    total: int

    def add(self, x: int) -> int:
        self.total = self.total + x
        return self.total

a = Acc(10)
print(a.add(5))
print(a.add(7))
print(a.total)
"""
        )
        assert out == "15\n22\n22\n"

    def test_attribute_aug_assign(self):
        out = run_source(
            """
class Acc:
    total: int

a = Acc(10)
a.total += 5
print(a.total)
"""
        )
        assert out == "15\n"

    def test_instances_are_independent(self):
        out = run_source(
            """
class Acc:
    total: int

a = Acc(1)
b = Acc(2)
a.total = 99
print(b.total)
"""
        )
        assert out == "2\n"

    def test_unknown_field_write_rejected(self):
        with pytest.raises(AttributeError, match="has no field"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0)
st.speed = 3.0
"""
            )

    def test_unknown_attribute_read_rejected(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            run_source(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0)
print(st.speed)
"""
            )


class TestClassDefinitionErrors:
    """Non-goals are rejected at definition time."""

    def test_inheritance_rejected(self):
        with pytest.raises(NotImplementedError, match="inheritance"):
            run_source(
                """
class Base:
    x: int

class Child(Base):
    y: int
"""
            )

    def test_unannotated_field_rejected(self):
        with pytest.raises(TypeError, match="must be annotated"):
            run_source(
                """
class Bad:
    x = 1
"""
            )

    def test_user_init_rejected(self):
        with pytest.raises(TypeError, match="__init__ is not supported"):
            run_source(
                """
class Bad:
    x: int

    def __init__(self, x: int):
        self.x = x
"""
            )

    def test_method_without_self_rejected(self):
        with pytest.raises(TypeError, match="must take 'self'"):
            run_source(
                """
class Bad:
    x: int

    def m() -> int:
        return 1
"""
            )


class TestClassInFunctions:
    """Classes used inside functions and across calls."""
    def test_construct_inside_function(self):
        out = run_source(
            JOINT_STATE
            + """
def make_stopped() -> bool:
    st = JointState(0.0, 0.0)
    return st.is_moving()

print(make_stopped())
"""
        )
        assert out == "False\n"

    def test_class_with_str_field(self):
        out = run_source(
            """
class Tagged:
    name: str
    value: int

    def label(self) -> str:
        return self.name

t = Tagged("hello", 7)
print(t.label())
print(t)
"""
        )
        assert out == "hello\nTagged(name='hello', value=7)\n"


def run_ast_interpreter(src: str) -> str:
    """Run Silu source through the tree-walking interpreter (interpret
    mode), return stdout."""
    from silu.interpreter import SiluInterpreter

    buf = io.StringIO()
    with redirect_stdout(buf):
        SiluInterpreter().visit(ast.parse(src))
    return buf.getvalue()


class TestClassASTInterpreter:
    """Same semantics through the tree-walking interpreter (interpret
    mode) - the path `silu verify` uses as its reference."""

    def test_joint_state_full(self):
        out = run_ast_interpreter(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st.is_moving())
print(st)
"""
        )
        assert out == "True\nJointState(position=1.0, velocity=2.0)\n"

    def test_methods_defaults_kwargs(self):
        out = run_ast_interpreter(
            """
class Acc:
    total: int
    name: str = "acc"

    def add(self, x: int) -> int:
        self.total += x
        return self.total

a = Acc(10, name="counter")
print(a.add(5))
print(a.name)
b = Acc(1)
print(b)
"""
        )
        assert out == "15\ncounter\nAcc(total=1, name='acc')\n"

    def test_type_violation(self):
        with pytest.raises(TypeError, match="annotated 'int'"):
            run_ast_interpreter(
                """
class Rec:
    n: int

r = Rec(1.5)
"""
            )

    def test_inheritance_rejected(self):
        with pytest.raises(TypeError, match="inheritance"):
            run_ast_interpreter(
                """
class Base:
    x: int

class Child(Base):
    y: int
"""
            )
