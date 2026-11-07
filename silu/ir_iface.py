"""ir-module switch: real llvmlite or the dual-valid text layer.

SILU_LLVM_IR=text runs the same converter code against
silu.llvmlite_text - the .ll output must be byte-identical (that is
the port parity gate). Default keeps real llvmlite. The factory
spellings (const_/func_/gvar_/builder_/module_, module_str) are
normalized onto both modules so the converter source stays one text.
"""

import os

if os.environ.get("SILU_LLVM_IR") == "text":
    import silu.llvmlite_pyinit  # noqa: F401 - attaches __init__s
    from silu import llvmlite_text
    from silu import llvmlite_text as ir

    def module_str(m):
        return llvmlite_text.module_text(m)

    ir.module_str = module_str

else:
    from llvmlite import ir as _real

    class _Iface:
        pass

    ir = _Iface()
    for _n in dir(_real):
        if not _n.startswith("_"):
            setattr(ir, _n, getattr(_real, _n))
    ir.const_ = _real.Constant
    ir.func_ = _real.Function
    ir.gvar_ = _real.GlobalVariable
    ir.builder_ = _real.IRBuilder
    ir.module_ = _real.Module

    def module_str(m):
        return str(m)

    ir.module_str = module_str

    def _fn_const_bitcast(fn, ty):
        # constant-expression bitcast of a function pointer for i8*
        # funcref tables (real llvmlite exposes Function.bitcast)
        return fn.bitcast(ty)

    ir.fn_const_bitcast = _fn_const_bitcast

    def _gv_const_bitcast(gv, ty):
        # constant-expression bitcast of a global's address (the P5
        # bool singletons store an i64* payload in an i8* field)
        return gv.bitcast(ty)

    ir.gv_const_bitcast = _gv_const_bitcast
