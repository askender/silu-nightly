"""Run a selfhost .si program under CPython - no AST rewriting.

    python3 tools/pycompat.py selfhost/silu_fe.si < input.si

The selfhost sources are a Python-syntax subset; the remaining gaps
are bridged at runtime:

- ``Enum``            : imported from the stdlib (a Silu builtin)
- ``read_stdin``/
  ``read_file``       : Silu I/O builtins
- positional ctors    : Silu classes are dataclasses; ``__build_class__``
                        is hooked so every plain class gets an
                        ``__init__`` assigning its annotated fields in
                        declaration order

Enum members must carry explicit values in the source (``A = 0``):
bare members are Silu-only sugar and mean an undefined name to Python.
"""

import os
import sys
from enum import Enum


def read_stdin():
    return sys.stdin.read()


def read_file(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


_orig_build_class = __build_class__


def _silu_build_class(func, name, *bases, **kw):
    cls = _orig_build_class(func, name, *bases, **kw)
    if bases and bases[0] is Enum:
        return cls
    # positional match patterns (case C(x)) need __match_args__ =
    # annotated fields in declaration order (dataclass semantics)
    cls.__match_args__ = tuple(getattr(cls, "__annotations__", {}))
    fields = list(getattr(cls, "__annotations__", {}))
    if fields and "__init__" not in cls.__dict__:
        def __init__(self, *args):
            if len(args) != len(fields):
                raise TypeError(
                    f"{name}() takes {len(fields)} arguments "
                    f"but {len(args)} given"
                )
            for fname, val in zip(fields, args):
                setattr(self, fname, val)
        cls.__init__ = __init__
    return cls


def run(path):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    # Silu imports are compile-time file inlining (Rust mod shape), not
    # Python module imports - expand them first so main-free workhorses
    # plus their wrappers run exactly like the native front end sees them
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    from silu.importer import expand_imports_tree

    tree = expand_imports_tree(
        source, os.path.dirname(os.path.abspath(path))
    )
    def _json_tag(v):
        if v is None:
            return 0
        if isinstance(v, bool):
            return 3
        if isinstance(v, int):
            return 1
        if isinstance(v, float):
            return 2
        if isinstance(v, str):
            return 4
        if isinstance(v, list):
            return 5
        if isinstance(v, dict):
            return 6
        raise TypeError("not a Json value")
    def _unwrap(want, label):
        def f(v):
            if type(v) is not want:
                raise TypeError(f"json_{label}: wrong member")
            return v
        return f
    g = {
        "__name__": "__silu__",
        "Enum": Enum,
        "read_stdin": read_stdin,
        "read_file": read_file,
        "file_exists": os.path.exists,
        "Json": object,  # annotation placeholder; values stay native
        "json_tag": _json_tag,
        "json_int": _unwrap(int, "int"),
        "json_float": _unwrap(float, "float"),
        "json_bool": _unwrap(bool, "bool"),
        "json_str": _unwrap(str, "str"),
        "json_free": lambda v: 0,
    }
    # LOAD_BUILD_CLASS reads __build_class__ from builtins (a class
    # statement ignores the surrounding globals for this name)
    import builtins
    builtins.__build_class__ = _silu_build_class
    try:
        exec(compile(tree, path, "exec"), g)
    finally:
        builtins.__build_class__ = _orig_build_class
    # the Silu compiler entry calls main() automatically
    entry = g.get("main")
    if callable(entry):
        entry()





def export(f):
    """@export decorator for the CPython plane: a no-op here, the
    compiled plane lifts the function to external C-ABI linkage."""
    return f


import ctypes as _ctypes  # noqa: E402

_C_LIBM = _ctypes.CDLL(None)
_C_LIBM.sqrt.restype = _ctypes.c_double
_C_LIBM.sqrt.argtypes = [_ctypes.c_double]
_C_LIBM.floor.restype = _ctypes.c_double
_C_LIBM.floor.argtypes = [_ctypes.c_double]
_C_LIBM.pow.restype = _ctypes.c_double
_C_LIBM.pow.argtypes = [_ctypes.c_double, _ctypes.c_double]
_C_LIBM.strlen.restype = _ctypes.c_longlong
_C_LIBM.strlen.argtypes = [_ctypes.c_char_p]


def _strlen_shim(s):
    if isinstance(s, str):
        return _C_LIBM.strlen(s.encode("utf-8"))
    return _C_LIBM.strlen(s)


class _CModule:
    """`from c import ...` under CPython: ctypes bindings for the
    common libc/libm surface the compiled plane declares."""
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "strlen":
            return _strlen_shim
        fn = getattr(_C_LIBM, name, None)
        if fn is not None:
            return fn
        raise ImportError(f"extern '{name}' has no ctypes binding")


sys.modules.setdefault("c", _CModule())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    run(sys.argv[1])
