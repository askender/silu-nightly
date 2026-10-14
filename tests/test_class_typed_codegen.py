#!/usr/bin/env python3
"""
Tests for class support (dataclass semantics) in the typed LLVM backend:
flat 8-byte-slot layout, construction, field reads/writes, method calls
with self binding, and differential checking against the IR interpreter
(the reference semantics).
"""

import ast
import io
import json
from contextlib import redirect_stdout

import pytest

from silu.ir_generator import SiluIRGenerator
from silu.ir_interpreter import IRInterpreter
from silu.typed_codegen import TypedCodegen


def _convert(source: str) -> str:
    tree = ast.parse(source)
    ir_result = SiluIRGenerator().visit(tree)
    return TypedCodegen().convert(json.dumps(ir_result))


def _run_main(llvm_ir: str) -> str:
    """Execute the module through MCJIT and capture stdout."""
    import ctypes
    import os
    import tempfile

    from llvmlite import binding as llvm

    module = llvm.parse_assembly(llvm_ir)
    module.verify()
    target = llvm.Target.from_default_triple()
    engine = llvm.create_mcjit_compiler(module, target.create_target_machine())
    engine.finalize_object()
    main_ptr = engine.get_function_address("main")
    output = tempfile.TemporaryFile()
    saved = os.dup(1)
    os.dup2(output.fileno(), 1)
    try:
        ctypes.CFUNCTYPE(ctypes.c_int)(main_ptr)()
        ctypes.CDLL(None).fflush(None)
    finally:
        os.dup2(saved, 1)
        os.close(saved)
    output.seek(0)
    return output.read().decode()


def _run_ir_interpreter(source: str) -> str:
    """Reference output from the IR interpreter (reference semantics)."""
    ir = SiluIRGenerator().visit(ast.parse(source))
    buf = io.StringIO()
    with redirect_stdout(buf):
        IRInterpreter().execute_program(ir)
    return buf.getvalue()


def _assert_matches_interpreter(source: str) -> None:
    compiled = _run_main(_convert(source))
    interpreted = _run_ir_interpreter(source)
    assert compiled == interpreted


JOINT_STATE = """
class JointState:
    position: float
    velocity: float

    def is_moving(self) -> bool:
        return self.velocity > 0.01
"""


class TestClassConstruction:
    def test_positional_construction(self):
        _assert_matches_interpreter(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st.position)
print(st.velocity)
"""
        )

    def test_default_and_keyword_construction(self):
        _assert_matches_interpreter(
            """
class Point:
    x: float
    y: float = 0.0
    z: float = 3.0

p = Point(1.0, z=9.0)
print(p.x)
print(p.y)
print(p.z)
"""
        )

    def test_int_coerced_to_float_field(self):
        _assert_matches_interpreter(
            JOINT_STATE
            + """
st = JointState(1, 2)
print(st.position)
print(st.velocity)
"""
        )

    def test_missing_argument_is_compile_error(self):
        with pytest.raises(TypeError, match="missing required argument"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0)
"""
            )

    def test_unexpected_keyword_is_compile_error(self):
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0, speed=2.0)
"""
            )

    def test_too_many_arguments_is_compile_error(self):
        with pytest.raises(TypeError, match="takes at most"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0, 3.0)
"""
            )


class TestClassFields:
    def test_field_write_readback(self):
        _assert_matches_interpreter(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
st.velocity = 3.5
print(st.velocity)
"""
        )

    def test_field_aug_assign(self):
        _assert_matches_interpreter(
            """
class Acc:
    total: int

a = Acc(10)
a.total += 5
a.total *= 2
print(a.total)
"""
        )

    def test_int_and_bool_fields(self):
        _assert_matches_interpreter(
            """
class Flags:
    count: int
    active: bool

f = Flags(7, True)
print(f.count)
print(f.active)
f.count = f.count + 1
print(f.count)
"""
        )

    def test_str_field_copy_isolation(self):
        """A name bound from a str field owns a copy; overwriting the
        field must not disturb it (and vice versa)."""
        _assert_matches_interpreter(
            """
class Tagged:
    name: str

t = Tagged("hello")
s = t.name
t.name = "changed"
print(s)
print(t.name)
"""
        )

    def test_str_field_multibyte(self):
        _assert_matches_interpreter(
            """
class Tagged:
    name: str

t = Tagged("你好")
print(t.name)
t.name = "世界"
print(t.name)
"""
        )

    def test_unknown_field_write_is_compile_error(self):
        with pytest.raises(AttributeError, match="has no field"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0)
st.speed = 3.0
"""
            )

    def test_unknown_field_read_is_compile_error(self):
        with pytest.raises(AttributeError, match="has no attribute"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0)
print(st.speed)
"""
            )


class TestClassMethods:
    def test_method_call(self):
        _assert_matches_interpreter(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st.is_moving())
st2 = JointState(1.0, 0.0)
print(st2.is_moving())
"""
        )

    def test_method_mutates_and_returns(self):
        _assert_matches_interpreter(
            """
class JointState:
    position: float
    velocity: float

    def scale(self, factor: float) -> float:
        self.velocity = self.velocity * factor
        return self.velocity

st = JointState(1.0, 2.0)
print(st.scale(3.0))
print(st.velocity)
"""
        )

    def test_method_calls_method(self):
        _assert_matches_interpreter(
            """
class Acc:
    total: int

    def add(self, x: int) -> int:
        self.total = self.total + x
        return self.total

    def add_twice(self, x: int) -> int:
        return self.add(x) + self.add(x)

a = Acc(10)
print(a.add_twice(5))
print(a.total)
"""
        )

    def test_method_in_loop(self):
        _assert_matches_interpreter(
            """
class Acc:
    total: int

    def add(self, x: int) -> int:
        self.total += x
        return self.total

a = Acc(0)
i: int = 0
while i < 5:
    a.add(i)
    i += 1
print(a.total)
"""
        )

    def test_instance_aliasing(self):
        """a = b aliases the instance (Python reference semantics)."""
        _assert_matches_interpreter(
            """
class Acc:
    total: int

a = Acc(1)
b = a
b.total = 99
print(a.total)
"""
        )

    def test_instance_in_function_scope(self):
        _assert_matches_interpreter(
            JOINT_STATE
            + """
def stopped() -> bool:
    st = JointState(0.0, 0.0)
    return st.is_moving()

print(stopped())
"""
        )

    def test_instance_as_function_parameter(self):
        """A class-annotated parameter (st: JointState) supports field
        reads and method calls inside the function."""
        _assert_matches_interpreter(
            JOINT_STATE
            + """
def speed_of(st: JointState) -> float:
    return st.velocity

def moving_flag(st: JointState) -> bool:
    return st.is_moving()

st = JointState(1.0, 2.5)
print(speed_of(st))
print(moving_flag(st))
"""
        )


class TestClassCompileTimeErrors:
    def test_container_field_rejected(self):
        with pytest.raises(NotImplementedError, match="container/instance field"):
            _convert(
                """
class Bag:
    items: list[int]
"""
            )

    def test_inheritance_rejected(self):
        with pytest.raises(NotImplementedError, match="inheritance"):
            _convert(
                """
class Base:
    x: int

class Child(Base):
    y: int
"""
            )

    def test_printing_instance_rejected(self):
        with pytest.raises(NotImplementedError, match="cannot be boxed"):
            _convert(
                JOINT_STATE
                + """
st = JointState(1.0, 2.0)
print(st)
"""
            )

    def test_layout_is_flat_slots(self):
        """The constructor mallocs 8 bytes per field - no header."""
        llvm_ir = _convert(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st.position)
"""
        )
        main = llvm_ir.split('define i32 @"main"')[1]
        assert "call i8* @\"malloc\"(i64 16)" in main
