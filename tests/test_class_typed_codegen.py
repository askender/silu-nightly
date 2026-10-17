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


class TestContainerFields:
    """list/dict fields: reference semantics, like everywhere in Silu."""

    def test_list_int_field(self):
        _assert_matches_interpreter(
            """
class Bag:
    items: list[int]
    name: str

    def add(self, x: int) -> int:
        self.items.append(x)
        return len(self.items)

b = Bag([1, 2], "bag")
print(b.add(3))
print(b.items[0], b.items[2])
b.items[1] = 99
print(b.items)
"""
        )

    def test_list_field_aliasing(self):
        """Reading a container field hands out the shared reference -
        mutating it mutates the field (Python container semantics)."""
        _assert_matches_interpreter(
            """
class Bag:
    items: list[int]

b = Bag([1])
lst: list[int] = b.items
lst.append(2)
print(len(b.items))
print(b.items)
"""
        )

    def test_dict_str_int_field_with_method(self):
        _assert_matches_interpreter(
            """
class WordCount:
    word: str
    counts: dict[str, int]

    def bump(self) -> int:
        self.counts[self.word] = self.counts.get(self.word, 0) + 1
        return self.counts[self.word]

w = WordCount("hi", {})
print(w.bump())
print(w.bump())
print(w.counts)
"""
        )

    def test_list_str_field(self):
        """list[str] fields keep their element copy discipline."""
        _assert_matches_interpreter(
            """
class Names:
    tags: list[str]

n = Names(["a", "b"])
n.tags.append("c")
print(n.tags)
s = n.tags[1]
n.tags[1] = "z"
print(s, n.tags[1])
"""
        )

    def test_list_float_field(self):
        _assert_matches_interpreter(
            """
class Acc:
    xs: list[float]

a = Acc([0.5])
a.xs.append(1.5)
print(a.xs)
print(a.xs[0] + a.xs[1])
"""
        )

    def test_container_default_fresh_per_instance(self):
        """A container default is fresh per instance - no shared-mutable-
        default gotcha (differs from plain Python on purpose)."""
        _assert_matches_interpreter(
            """
class Fresh:
    xs: list[int] = []

f1 = Fresh()
f2 = Fresh()
f1.xs.append(1)
print(len(f1.xs), len(f2.xs))
"""
        )

    def test_field_reassigned_with_literal(self):
        _assert_matches_interpreter(
            """
class Bag:
    items: list[int]

b = Bag([1, 2])
b.items = [7, 8, 9]
print(b.items)
"""
        )


class TestNestedInstanceFields:
    """Instance fields: pointer slots with reference semantics, forward
    and self references allowed (docs/selfhosting.md item 3)."""

    def test_nested_construct_and_read(self):
        _assert_matches_interpreter(
            """
class Inner:
    x: int
    label: str

class Outer:
    inner: Inner
    name: str

o = Outer(Inner(21, "core"), "outer")
print(o.inner.x)
print(o.inner.label)
print(o.name)
"""
        )

    def test_method_through_field_chain(self):
        _assert_matches_interpreter(
            """
class Inner:
    x: int

    def double(self) -> int:
        return self.x * 2

class Outer:
    inner: Inner

    def total(self) -> int:
        return self.inner.double() + 1

o = Outer(Inner(21))
print(o.total())
"""
        )

    def test_write_through_chain(self):
        _assert_matches_interpreter(
            """
class Inner:
    x: int

class Outer:
    inner: Inner

o = Outer(Inner(1))
o.inner.x = 100
o.inner.x += 5
print(o.inner.x)
"""
        )

    def test_instance_field_aliasing(self):
        """i2 = o.inner shares the instance (reference semantics)."""
        _assert_matches_interpreter(
            """
class Inner:
    x: int

class Outer:
    inner: Inner

o = Outer(Inner(1))
i2 = o.inner
i2.x = 7
print(o.inner.x)
"""
        )

    def test_forward_reference(self):
        """A field may name a class defined later in the module."""
        _assert_matches_interpreter(
            """
class Outer:
    inner: Inner

class Inner:
    x: int

o = Outer(Inner(5))
print(o.inner.x)
"""
        )

    def test_self_reference_registers(self):
        """A class may name itself as a field type (layout is pointer-
        sized, so recursion needs no cycle-breaking)."""
        llvm_ir = _convert(
            """
class Node:
    value: int
    child: Node

print("ok")
"""
        )
        assert _run_main(llvm_ir) == "ok\n"

    def test_instance_field_default_rejected(self):
        with pytest.raises(NotImplementedError, match="cannot have a default"):
            _convert(
                """
class Inner:
    x: int

class Outer:
    inner: Inner = None
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

    def test_printing_instance_boxes_address(self):
        """An instance printed in a dynamic position boxes as its
        address (opaque identity); compiling succeeds."""
        llvm_ir = _convert(
            JOINT_STATE
            + """
st = JointState(1.0, 2.0)
print(st)
"""
        )
        assert "create_int" in llvm_ir

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
