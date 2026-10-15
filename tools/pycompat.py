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
    g = {
        "__name__": "__silu__",
        "Enum": Enum,
        "read_stdin": read_stdin,
        "read_file": read_file,
    }
    # LOAD_BUILD_CLASS reads __build_class__ from builtins (a class
    # statement ignores the surrounding globals for this name)
    import builtins
    builtins.__build_class__ = _silu_build_class
    try:
        exec(compile(source, path, "exec"), g)
    finally:
        builtins.__build_class__ = _orig_build_class
    # the Silu compiler entry calls main() automatically
    entry = g.get("main")
    if callable(entry):
        entry()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    run(sys.argv[1])
