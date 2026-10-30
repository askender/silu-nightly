"""Python-only bootstrap for the shared llvmlite text layer.

The shared core (silu/llvmlite_text.py == selfhost/llvmlite.si) is
dual-valid source: its classes declare fields and every construction
passes them positionally - which is exactly Silu's auto-generated
constructor. Python needs an __init__ with the same shape; this
module attaches one per class, generated from the field
declarations. Silu never loads this module: its import line in the
shared core resolves to no .si file and stays inert.
"""

import silu.llvmlite_text as T


def _attach(cls):
    names = list(cls.__annotations__)
    code = "def _init(self, %s):\n    pass\n" % ", ".join(names)
    for n in names:
        code += "    self.%s = %s\n" % (n, n)
    ns = {}
    exec(code, ns)
    cls.__init__ = ns["_init"]


for _cls in (T.Value, T.Type, T.Scope, T.TypeInfo, T._Undefined,
             T.Constant, T.Argument, T.Block, T.Instr,
             T.GlobalVariable, T.Function, T.Module, T.IRBuilder,
             T.AttrSet, T.FormattedConstant):
    _attach(_cls)


def _wrap_builder_methods():
    """The shared core declares no default arguments (Silu has none);
    Python call sites may omit the trailing name (and alloca's size).
    This wrapper restores llvmlite's call ergonomics on the Python
    side only - the Silu twin gets full arguments from the flattened
    converter."""
    import inspect

    fill = {"name": "", "size": None}
    for mname, meth in inspect.getmembers(T.IRBuilder, inspect.isfunction):
        params = list(inspect.signature(meth).parameters)
        tail = []
        for p in reversed(params[1:]):
            if p in fill:
                tail.append(p)
            else:
                break
        if not tail:
            continue
        tail = list(reversed(tail))
        arity = len(params) - 1
        tail_vals = tuple(fill[p] for p in tail)
        code = "def _w(self, *a):\n"
        code += "    missing = %d - len(a)\n" % arity
        code += "    if missing > 0:\n"
        code += "        a = tuple(a) + _tail[len(_tail) - missing:]\n"
        code += "    return _fn(self, *a)\n"
        ns = {"_fn": meth, "_tail": tail_vals}
        exec(code, ns)
        setattr(T.IRBuilder, mname, ns["_w"])


_wrap_builder_methods()

# __str__ shims so host code can str() a type like real llvmlite
def _ti_str(self):
    return self.text


T.TypeInfo.__str__ = _ti_str
T.TypeInfo.__repr__ = _ti_str
