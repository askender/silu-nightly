"""Flatten the converter inheritance into one class (M6a prep).

TypedCodegen(SiluToLLVMConverter) cannot port to Silu (no class
inheritance, by design - Rust has none). This script merges the two
classes mechanically:

- base methods that the derived class does not override come in
  first, then the derived methods (7 overrides win)
- the two super() call sites are rewired to renamed base methods
  (_base_init / _base_collect_function_defs)
- the flattened module keeps both files' module-level code and the
  typed file's imports

The output is still Python: the parity gates (flattened vs originals,
real llvmlite and the text layer, .ll byte-identical on all 16
programs) prove the merge before any Silu-syntax conversion. Usage:

    python3 tools/flatten_codegen.py > silu/typed_codegen_flat.py
"""

import ast
import sys

__SI_MODE = "--si" in sys.argv
sys.argv = [a for a in sys.argv if a != "--si"]

REPO = __file__.rsplit("/tools/", 1)[0]
BASE = f"{REPO}/silu/silu_ir_to_llvm.py"
DERIVED = f"{REPO}/silu/typed_codegen.py"
HELPERS = f"{REPO}/silu/typed_helpers.py"
RUNTIME_MIXIN = f"{REPO}/silu/pyobj_runtime.py"
EXPR_MIXIN = f"{REPO}/silu/typed_expr.py"
MATCH_MIXIN = f"{REPO}/silu/typed_match.py"
CALL_MIXIN = f"{REPO}/silu/typed_call.py"

RENAMES = {
    "__init__": "_base_init",
    "_collect_function_defs": "_base_collect_function_defs",
    "_convert_node": "_base_convert_node",
    "_convert_statement": "_base_convert_statement",
}


def _reject_silent_divergence(tree, src_name):
    """Silu has no default parameter values: a Python default in the
    converter source is silently DROPPED by the .si emission and only
    explodes at runtime (the list_int_apply lesson). Fail at flatten
    time instead."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in list(node.args.posonlyargs) + list(node.args.args):
                if arg.annotation is None and arg.arg not in ("self",):
                    pass
            defaults = list(node.args.defaults) + [
                d for d in node.args.kw_defaults if d is not None
            ]
            if defaults:
                raise SystemExit(
                    f"flatten: {src_name}: function '{node.name}' has "
                    "default parameter values - Silu does not support "
                    "them and the .si emission would silently drop the "
                    "default (runtime arity errors). Pass every "
                    "argument explicitly."
                )


def method_blocks(tree, class_name):
    """[(name, start_line, end_line)] for the class' methods."""
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    out = []
    for item in cls.body:
        if isinstance(item, ast.FunctionDef):
            start = item.lineno - 1
            if item.decorator_list:
                start = min(d.lineno - 1 for d in item.decorator_list)
            out.append((item.name, start, item.end_lineno))
    return out, cls


def lines_of(path):
    return open(path).read().split("\n")


def _debase(ls):
    """Base module code may self-reference the old class name."""
    out = []
    for l in ls:
        l = l.replace("SiluToLLVMConverter._normalize_ir",
                      "TypedCodegen._normalize_ir")
        l = l.replace("converter = SiluToLLVMConverter()",
                      "converter = TypedCodegen()")
        out.append(l)
    return out


def _helpers_block():
    """typed_helpers.py's content minus its imports and __all__ (those
    are Python-module concerns; the flattened file already carries the
    imports and must not re-export)."""
    hsrc = open(HELPERS).read()
    tree = ast.parse(hsrc)
    lines = hsrc.split("\n")
    skip = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for ln in range(node.lineno - 1, node.end_lineno):
                skip.add(ln)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    for ln in range(node.lineno - 1, node.end_lineno):
                        skip.add(ln)
    out = []
    for i, l in enumerate(lines):
        if i in skip:
            continue
        out.append(l)
    # drop the comment-only header (leading comment/blank lines)
    while out and (out[0].strip().startswith("#") or not out[0].strip()):
        out.pop(0)
    return "\n".join(out)


def main():
    base_src = open(BASE).read()
    # the mixin import is dropped: flatten inlines the mixin's methods,
    # and the multi-line parenthesized import would otherwise break the
    # line-based import collector
    import re as _re_imp
    base_src = _re_imp.sub(
        r"from \.pyobj_runtime import \([^)]*\)\n\n*", "", base_src
    )
    derived_src = open(DERIVED).read()
    mixin_src = open(RUNTIME_MIXIN).read()
    mixin_tree = ast.parse(mixin_src)
    mixin_lines = mixin_src.split("\n")
    mixin_methods, _unused_cls = method_blocks(
        mixin_tree, "PyobjRuntimeMixin"
    )
    expr_src = open(EXPR_MIXIN).read()
    expr_tree = ast.parse(expr_src)
    expr_lines = expr_src.split("\n")
    expr_methods, _e_cls = method_blocks(
        expr_tree, "TypedExprMixin"
    )
    match_src = open(MATCH_MIXIN).read()
    match_tree = ast.parse(match_src)
    match_lines = match_src.split("\n")
    match_methods, _m_cls = method_blocks(
        match_tree, "TypedMatchMixin"
    )
    call_src = open(CALL_MIXIN).read()
    call_tree = ast.parse(call_src)
    call_lines = call_src.split("\n")
    call_methods, _c_cls = method_blocks(
        call_tree, "TypedCallMixin"
    )
    # typed_codegen.py's leaf helpers live in silu/typed_helpers.py;
    # inline them so the flattened module stays self-contained
    marker = "from silu.typed_helpers import *"
    if marker in derived_src:
        derived_src = derived_src.replace(marker, _helpers_block())
    base_tree = ast.parse(base_src)
    derived_tree = ast.parse(derived_src)

    base_methods, base_cls = method_blocks(base_tree, "SiluToLLVMConverter")
    derived_methods, derived_cls = method_blocks(derived_tree, "TypedCodegen")

    base_lines = base_src.split("\n")
    derived_lines = derived_src.split("\n")

    derived_names = {m[0] for m in derived_methods}

    # base module-level statements before the class, and after it
    base_cls_start = base_cls.lineno - 1
    base_cls_end = base_cls.end_lineno
    base_pre = base_lines[:base_cls_start]
    base_post = base_lines[base_cls_end:]

    derived_cls_start = derived_cls.lineno - 1
    derived_cls_end = derived_cls.end_lineno
    derived_pre = derived_lines[:derived_cls_start]
    derived_post = derived_lines[derived_cls_end:]

    # merged class: header from derived, then non-overridden base
    # methods (renamed where super() needs them), then derived body
    header = derived_lines[derived_cls_start]  # class TypedCodegen(...):
    header = header.replace(
        "(SiluToLLVMConverter, TypedExprMixin, TypedMatchMixin, TypedCallMixin)", ""
    )
    header = header.replace("TypedExprMixin, TypedMatchMixin, TypedCallMixin", "")
    header = header.replace(
        "(SiluToLLVMConverter, TypedExprMixin, TypedMatchMixin)", ""
    )
    header = header.replace("(SiluToLLVMConverter, TypedExprMixin)", "")
    header = header.replace("(SiluToLLVMConverter)", "")
    header = header.replace(", TypedExprMixin", "")

    def emit_mixin():
        # the runtime-emission mixin methods occupy exactly the slot
        # they held in the pre-split single file: right after the
        # base's _init_runtime_functions, before convert() and the
        # rest - keeping the flattened output byte-identical
        for name, s_, e_ in mixin_methods:
            if name in derived_names:
                continue  # derived overrides win, same rule as base
            block = mixin_lines[s_:e_]
            di = 0
            while not block[di].lstrip().startswith("def "):
                di += 1
            sig = block[di].strip()
            paren = sig.index("(")
            block[di] = "    def " + name + sig[paren:]
            block = _debase(block)
            merged.append("")
            merged.extend(block)

    merged = [header]
    for name, s, e in base_methods:
        out_name = RENAMES.get(name, name)
        if name in derived_names and name not in RENAMES:
            continue  # derived overrides
        block = base_lines[s:e]
        di = 0
        while not block[di].lstrip().startswith("def "):
            di += 1
        sig = block[di].strip()
        paren = sig.index("(")
        block[di] = "    def " + out_name + sig[paren:]
        block = _debase(block)
        # base-internal calls to overridden names whose ARITY differs
        # route to the renamed base versions; same-arity overrides
        # (like _collect_function_defs) must stay virtual so base
        # methods dispatch into the derived behavior
        for old_m, new_m in RENAMES.items():
            if old_m in ("__init__", "_collect_function_defs"):
                continue
            block = [
                l.replace("self." + old_m + "(", "self." + new_m + "(")
                for l in block
            ]
        merged.append("")
        merged.extend(block)
        if out_name == "_init_runtime_functions":
            emit_mixin()
    # derived class-level constants (non-function statements) stay
    for item in derived_cls.body:
        if isinstance(item, ast.Assign):
            block = derived_lines[item.lineno - 1:item.end_lineno]
            merged.append("")
            merged.extend(block)

    # derived body: rewire the two super() calls. The expr-mixin
    # methods re-enter at their historical position: immediately
    # before _unsupported_raw_method, keeping the flat output
    # byte-identical
    def emit_expr_mixin():
        for name, s_, e_ in expr_methods:
            block = expr_lines[s_:e_]
            merged.append("")
            merged.extend(block)

    def emit_match_helpers():
        for name, s_, e_ in match_methods:
            if name == "_convert_match":
                continue
            block = match_lines[s_:e_]
            merged.append("")
            merged.extend(block)

    def emit_match_statement():
        for name, s_, e_ in match_methods:
            if name == "_convert_match":
                block = match_lines[s_:e_]
                merged.append("")
                merged.extend(block)

    # derived body: rewire the two super() calls
    _last_derived_name = derived_methods[-1][0]
    for name, s, e in derived_methods:
        block = derived_lines[s:e]
        if name == "_unsupported_raw_method":
            emit_expr_mixin()
        if name == "_count_scalar_uses":
            emit_match_helpers()
        if name == "_convert_bool_chain":
            emit_match_statement()
        rewired = []
        for l in block:
            l = l.replace("super().__init__()", "self._base_init()")
            l = l.replace(
                "super()._collect_function_defs(node)",
                "self._base_collect_function_defs(node)",
            )
            rewired.append(l)
        merged.append("")
        merged.extend(rewired)
        if name == _last_derived_name:
            for cname, cs_, ce_ in call_methods:
                block = call_lines[cs_:ce_]
                merged.append("")
                merged.extend(block)

    # imports & module-level code
    keep_pre = []
    for l in derived_pre:
        if "from .silu_ir_to_llvm import" in l:
            continue
        # the expr-mixin import resolved its methods at import time;
        # the flat file carries the method bodies inline
        if "from silu.typed_expr import" in l:
            continue
        if "from silu.typed_match import" in l:
            continue
        if "from silu.typed_call import" in l:
            continue
        keep_pre.append(l)

    # base: docstring (via AST) and import lines are handled
    # separately from the rest of its module-level code
    base_doc_end = 0
    first = base_tree.body[0]
    if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        base_doc_end = first.end_lineno
    base_imports = []
    base_code = []
    for idx, l in enumerate(base_pre):
        if idx < base_doc_end:
            continue
        stripped = l.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            if stripped not in {x.strip() for x in keep_pre}:
                base_imports.append(l)
            continue
        if stripped.startswith("#"):
            continue
        if stripped:
            base_code.append(l)

    out = []
    out.append('"""Flattened converter (generated by tools/flatten_codegen.py).')
    out.append("Do not edit: the sources are silu/silu_ir_to_llvm.py and")
    out.append('silu/typed_codegen.py."""')
    out.append("")
    out.extend(keep_pre)
    out.append("")
    out.extend(base_imports)
    out.append("")
    out.extend(base_code)
    out.append("")
    out.extend(merged)
    out.append("")
    out.extend(base_post)
    out.extend(derived_post)
    text = "\n".join(out)
    ast.parse(text)  # sanity: the flattened module must be valid Python
    sys.stdout.write(text)


# ---------------------------------------------------------------- --
# --si mode: emit the flattened converter as Silu source

def si_main():
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main()
    text = buf.getvalue()

    # dual-valid contract enforcement (see _reject_silent_divergence)
    _reject_silent_divergence(ast.parse(text), "flattened converter")

    import ast as A

    # builder calls get their omitted trailing arguments filled (the
    # .si has no default parameters); receiver-text guard keeps set /
    # attribute .add sites out. Line/col are valid for `text`.
    NAME_LAST = {
        "add", "sub", "mul", "sdiv", "udiv", "srem", "urem", "fadd",
        "fsub", "fmul", "fdiv", "frem", "shl", "lshr", "ashr", "and_",
        "or_", "xor", "not_", "icmp_signed", "icmp_unsigned",
        "fcmp_ordered", "fcmp_unordered", "zext", "sext", "trunc",
        "bitcast", "ptrtoint", "inttoptr", "sitofp", "fptosi",
        "fpext", "fptrunc", "load", "gep", "call", "phi", "select",
        "extract_value", "insert_value",
    }
    # full positional arity of llvmlite.si's builder methods (the
    # trailing parameter is always the result name)
    ARITY = {m: 3 for m in NAME_LAST}
    ARITY["load"] = 2
    ARITY["gep"] = 3
    ARITY["not_"] = 2
    ARITY["phi"] = 2
    ARITY["select"] = 4
    ARITY["call"] = 3
    ARITY["icmp_signed"] = 4
    ARITY["icmp_unsigned"] = 4
    ARITY["fcmp_ordered"] = 4
    ARITY["fcmp_unordered"] = 4
    ARITY["insert_value"] = 4
    ARITY["func_"] = 3
    ARITY["gvar_"] = 3
    ARITY["builder_"] = 1
    ARITY["const_"] = 2
    ARITY["module_"] = 1
    NON_BUILDER_RECV = {"sink", "_rebound", "seen", "useset", "parts", "out",
                        "probes", "calls", "fill", "parent_names",
                        "repeated", "field_names", "tags"}
    # attribute receivers that are real container objects, not the
    # llvmlite builder (self._scope_local_vars.add(name) would
    # otherwise get builder-arity-rewritten to three arguments)
    NON_BUILDER_ATTR = {"_scope_local_vars", "_owned_strs",
                        "_borrowed_strs"}
    _t = A.parse(text)
    _lines = text.split("\n")
    _edits = []
    for _n in A.walk(_t):
        if not (isinstance(_n, A.Call) and isinstance(_n.func, A.Attribute)):
            continue
        _m = _n.func.attr
        if _m not in ARITY or _n.keywords:
            continue
        _recv = _n.func.value
        if isinstance(_recv, A.Name) and _recv.id in NON_BUILDER_RECV:
            continue
        if isinstance(_recv, A.Attribute) and _recv.attr in NON_BUILDER_ATTR:
            continue
        if (isinstance(_recv, A.Attribute)
                and _recv.attr in ("attributes", "metadata")):
            continue
        _missing = ARITY[_m] - len(_n.args)
        if _missing <= 0:
            continue
        if _m == "alloca" and _missing == 2:
            _ins = "None, ''"
        else:
            _ins = ", ".join(['""'] * _missing)
        _edits.append((_n.end_lineno, _n.end_col_offset, _ins))
    for _ln, _col, _ins in sorted(_edits, reverse=True):
        _l = _lines[_ln - 1]
        if _l.strip() == ")" or _l.strip() == "),":
            # closing paren alone on its line: add the filler as a
            # proper new argument line (comma-separating the previous)
            _ind = _l[: len(_l) - len(_l.lstrip())]
            _tail = _l.strip()[1:]
            _prev = _lines[_ln - 2].rstrip()
            if not _prev.endswith(",") and not _prev.endswith("("):
                _lines[_ln - 2] = _prev + ","
            _lines[_ln - 1] = _ind + _ins + "\n" + _ind + ")" + _tail
        else:
            _lines[_ln - 1] = _l[:_col - 1] + ", " + _ins + _l[_col - 1:]
    text = "\n".join(_lines)

    tree = A.parse(text)

    class ToSilu(A.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == "silu.ir_iface":
                return None
            return node

        def _strip_doc(self, body):
            if (body and isinstance(body[0], A.Expr)
                    and isinstance(body[0].value, A.Constant)
                    and isinstance(body[0].value.value, str)):
                return body[1:]
            return body

        def visit_ClassDef(self, node):
            self.generic_visit(node)
            node.body = self._strip_doc(node.body)
            return node

        def _strip_default_args(self, node):
            node.args.defaults = []
            node.args.kw_defaults = []
            return node

        def visit_FunctionDef(self, node):
            # kw_defaults holds None for unset keyword defaults, which
            # generic_visit would choke on
            node.args.kw_defaults = []
            prefix = node.name
            self.generic_visit(node)
            node.body = self._strip_doc(node.body)
            node.returns = None
            # rewrite self-capturing lambdas into nested defs
            new_body = []
            lam_defs = []

            class LamRewriter(A.NodeTransformer):
                def __init__(s):
                    s.n = 0

                def visit_Lambda(s, lam):
                    src_txt = A.unparse(lam)
                    if "self." not in src_txt and "self " not in src_txt \
                            and "self)" not in src_txt and "self," not in src_txt:
                        return lam
                    s.n += 1
                    name = f"__lam_{prefix}_{s.n}"
                    params = [a.arg for a in lam.args.args]
                    lam_defs.append(A.FunctionDef(
                        name=name,
                        args=A.arguments(
                            posonlyargs=[],
                            args=[A.arg(arg=p) for p in params],
                            vararg=None, kwonlyargs=[],
                            kw_defaults=[], kwarg=None, defaults=[],
                        ),
                        body=[A.Return(value=lam.body)],
                        decorator_list=[], returns=None, type_params=[],
                    ))
                    return A.copy_location(
                        A.Name(id=name, ctx=A.Load()), lam)

            rw = LamRewriter()
            for st in node.body:
                new_body.append(rw.visit(st))
            if lam_defs:
                node.body = lam_defs + new_body
            for a in node.args.args + node.args.kwonlyargs:
                a.annotation = None
            if node.args.vararg:
                node.args.vararg.annotation = None
            return node

        def visit_Lambda(self, node):
            self.generic_visit(node)
            for a in node.args.args:
                a.annotation = None
            return node

        def visit_AnnAssign(self, node):
            self.generic_visit(node)
            if node.value is None:
                # bare declaration (class field): Silu wants the shape
                # `x: T`; any annotation slot works, use object
                node.annotation = A.Name(id="object", ctx=A.Load())
                return node
            new = A.Assign(
                targets=[node.target], value=node.value
            )
            return A.copy_location(new, node)

        def visit_arg(self, node):
            node.annotation = None
            return node

        def visit_Try(self, node):
            # keep the guarded body, drop handlers
            out = []
            for st in node.body:
                out.append(st)
            return out

        def visit_With(self, node):
            self.generic_visit(node)
            out = []
            for st in node.body:
                out.append(st)
            return out

        def visit_Attribute(self, node):
            self.generic_visit(node)
            if (isinstance(node.value, A.Name) and node.value.id == "ir"):
                attr = node.attr
                if attr == "module_str":
                    attr = "module_text"
                return A.copy_location(
                    A.Attribute(
                        value=A.Name(id="llvmlite", ctx=A.Load()),
                        attr=attr, ctx=node.ctx,
                    ),
                    node,
                )
            return node

    tree = ToSilu().visit(tree)

    # class-level constants keep the annotated shape (Silu classes
    # support `x: T = value` but not bare assignment)
    for n in A.walk(tree):
        if isinstance(n, A.ClassDef):
            n.body = [
                (A.AnnAssign(
                    target=st.targets[0],
                    annotation=A.Name(id="object", ctx=A.Load()),
                    value=st.value, simple=1,
                ) if isinstance(st, A.Assign) else st)
                for st in n.body
            ]

    # the merged converter class: Silu classes declare fields and get
    # an auto-ctor; the Python __init__ becomes a _py_init method plus
    # a module-level factory constructing with None placeholders
    for n in A.walk(tree):
        if isinstance(n, A.ClassDef) and n.name == "TypedCodegen":
            # class-body constants act as field defaults; the factory
            # re-embeds them instead of a None placeholder
            defaults = {}
            for st in n.body:
                if isinstance(st, A.AnnAssign) and st.value is not None:
                    defaults[st.target.id] = A.unparse(st.value)
            fields = []
            for m in n.body:
                if isinstance(m, A.FunctionDef):
                    for x in A.walk(m):
                        if (isinstance(x, A.Attribute)
                                and isinstance(x.value, A.Name)
                                and x.value.id == "self"
                                and isinstance(x.ctx, A.Store)
                                and x.attr not in fields):
                            fields.append(x.attr)
            decls = [
                A.AnnAssign(
                    target=A.Name(id=f, ctx=A.Store()),
                    annotation=A.Name(id="object", ctx=A.Load()),
                    value=None, simple=1,
                )
                for f in fields
            ]
            for m in n.body:
                if isinstance(m, A.FunctionDef) and m.name == "__init__":
                    m.name = "_py_init"
            args = [
                A.parse(defaults.get(f, "None"), mode="eval").body
                for f in fields
            ]
            factory = A.FunctionDef(
                name="typed_codegen_new",
                args=A.arguments(
                    posonlyargs=[], args=[], vararg=None,
                    kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
                ),
                body=[
                    A.Assign(
                        targets=[A.Name(id="c", ctx=A.Store())],
                        value=A.Call(
                            func=A.Name(id="TypedCodegen", ctx=A.Load()),
                            args=args, keywords=[],
                        ),
                    ),
                    A.Expr(
                        value=A.Call(
                            func=A.Attribute(
                                value=A.Name(id="c", ctx=A.Load()),
                                attr="_py_init", ctx=A.Load(),
                            ),
                            args=[], keywords=[],
                        )
                    ),
                    A.Return(value=A.Name(id="c", ctx=A.Load())),
                ],
                decorator_list=[], returns=None, type_params=[],
            )
            n.body = decls + n.body
            # module-level factory after the class
            tree.body.append(factory)

    # host-only method: save_to_file uses with/open (Silu has neither;
    # the .si writes via print)
    for n in A.walk(tree):
        if isinstance(n, A.ClassDef) and n.name == "TypedCodegen":
            n.body = [m for m in n.body
                      if not (isinstance(m, A.FunctionDef)
                              and m.name == "save_to_file")]

    # drop Python-only module tails: the base file's CLI main() and
    # the __main__ guard (the .si gets its own stdin entry later)
    tree.body = [
        st for st in tree.body
        if not (
            isinstance(st, A.FunctionDef)
            and st.name == "main"
            and isinstance(st.args.args, list)
            and len(st.args.args) == 0
        )
        and not (
            isinstance(st, A.If)
            and isinstance(st.test, A.Compare)
            and isinstance(st.test.left, A.Name)
            and st.test.left.id == "__name__"
        )
        and not (
            isinstance(st, A.Assign)
            and isinstance(st.targets[0], A.Attribute)
            and st.targets[0].attr == "__init__"
        )
        and not (
            isinstance(st, A.FunctionDef)
            and st.name == "_pyobj_init"
        )
    ]

    # constructor call sites go through the factory
    A.fix_missing_locations(tree)
    out = A.unparse(tree)
    out = out.replace("TypedCodegen()", "typed_codegen_new()")

    import re as _re2

    # twin + converter both call sorted/zip/any/all/set at module level;
    # rewrite whole-word call sites to the plain-Silu shims and prepend
    # the shim definitions
    for _b in ("sorted", "zip", "any", "all", "repr", "bool"):
        out = _re2.sub(r"(?<![\w.])" + _b + r"\(", "_builtin_" + _b + "(", out)
    shims = """def _builtin_all(xs) -> bool:
    for x in xs:
        if not x:
            return False
    return True


def _builtin_sorted(xs):
    out = []
    for x in xs:
        out.append(x)
    i = 0
    while i < len(out):
        j = i + 1
        while j < len(out):
            if out[j] < out[i]:
                t = out[i]
                out[i] = out[j]
                out[j] = t
            j += 1
        i += 1
    return out


def _builtin_zip(a, b):
    out = []
    n = len(a)
    if len(b) < n:
        n = len(b)
    i = 0
    while i < n:
        out.append((a[i], b[i]))
        i += 1
    return out


def _builtin_repr(x):
    if isinstance(x, str):
        return "'" + x + "'"
    return str(x)


def _builtin_bool(x) -> bool:
    if x:
        return True
    return False


"""
    out = "import llvmlite\n\n" + shims + out

    # env switches become compile-time constants in the .si
    out = out.replace("os.environ.get('SILU_CHECKS', '1') != '0'", "True")
    out = out.replace("os.environ.get('SILU_SCALARS', '1') != '0'", "True")

    # the LLVM C-API bootstrap becomes baked host constants (the .si
    # pipeline has no binding; compilation is clang's job)
    import llvmlite.binding as _llvm

    _llvm.initialize_native_target()
    _llvm.initialize_native_asmprinter()
    _tm = _llvm.Target.from_default_triple().create_target_machine()
    old_init = (
        "        llvm.initialize()\n"
        "        llvm.initialize_native_target()\n"
        "        llvm.initialize_native_asmprinter()\n"
        "        target = llvm.Target.from_default_triple()\n"
        "        self.target_machine = target.create_target_machine()\n"
        "        self.module = llvmlite.module_('silu_module')\n"
        "        self.module.triple = self.target_machine.triple\n"
        "        self.module.data_layout = str(self.target_machine.target_data)"
    )
    new_init = (
        "        self.module = llvmlite.module_('silu_module')\n"
        "        self.module.triple = %r\n"
        "        self.module.data_layout = %r"
    ) % (_tm.triple, str(_tm.target_data))
    assert old_init in out, "binding init block not found"
    out = out.replace(old_init, new_init, 1)

    # string constants: Silu has bytes literals but no bytearray /
    # str.encode; the text layer accepts plain str for i8 arrays
    out = out.replace(
        "string_bytes = bytearray((string_content + '\\x00').encode('utf-8'))",
        "string_bytes = string_content + '\\x00'")
    out = out.replace(
        "llvmlite.ArrayType(llvmlite.IntType(8), len(string_bytes))",
        "llvmlite.ArrayType(llvmlite.IntType(8), llvmlite.utf8_len(string_bytes))")
    out = out.replace(
        "llvmlite.const_(llvmlite.ArrayType(llvmlite.IntType(8), len(data)), bytearray(data))",
        "llvmlite.const_latin1_(llvmlite.ArrayType(llvmlite.IntType(8), len(data)), data)")
    out = out.replace(
        "llvmlite.ArrayType(llvmlite.IntType(8), len(data))",
        "llvmlite.ArrayType(llvmlite.IntType(8), llvmlite.latin1_len(data))")
    out = out.replace(
        "bytearray(b'IndexError: string index out of range\\x00')",
        "b'IndexError: string index out of range\\x00'")
    out = out.replace("len(text.encode('utf-8'))", "llvmlite.utf8_len(text)")
    out = out.replace("len(value.encode('utf-8'))", "llvmlite.utf8_len(value)")

    # twin type checks: the twin's IntType is a factory function, not a
    # class - isinstance against it becomes a structural .kind check
    out = out.replace(
        "isinstance(value.type, llvmlite.IntType)",
        "(value.type.kind == 'int')",
    )

    # host-only instance tracking (id-keyed dicts) leaves the .si
    import re as _re

    out = _re.sub(r"self\._inst_class\[id\(([^)]*)\)\] = ([^\n]+)",
                  r"self._inst_class[\1] = \2", out)
    out = out.replace("cls = self._inst_class.get(id(value))",
                      "cls = self._inst_class.get(value)")
    # the type shims: Silu has no getattr-with-default; the twin's
    # TypeInfo always carries text/ret, real code paths guard None
    out = out.replace(
        "    txt = getattr(t, 'text', None)\n"
        "    if txt is not None:\n"
        "        return txt\n"
        "    return str(t)",
        "    return t.text")
    out = out.replace(
        '    txt = getattr(t, "text", None)\n'
        '    if txt is not None:\n'
        '        return txt\n'
        '    return str(t)',
        "    return t.text")
    out = out.replace(
        "    return getattr(ftype, 'return_type', None)",
        "    return ftype.ret")
    out = out.replace(
        '    return getattr(ftype, "return_type", None)',
        "    return ftype.ret")

    # host-side getattr-with-default -> explicit attribute reads (the
    # attributes always exist by body-generation time)
    out = out.replace("getattr(mfn.ftype, 'return_type', None)",
                      "mfn.ftype.return_type")
    out = out.replace('getattr(mfn.ftype, "return_type", None)',
                      "mfn.ftype.return_type")
    out = out.replace("getattr(self, '_fn_table', None)",
                      "self._fn_table")
    out = out.replace('getattr(self, "_fn_table", None)',
                      "self._fn_table")
    out = out.replace("getattr(self, '_fn_table', [])",
                      "self._fn_table")

    # stdin entry + the JSON leaf parser (template file, plain Silu)
    out += open(REPO + "/tools/flatten_si_tail.si").read()
    sys.stdout.write(out)


if __name__ == "__main__":
    if __SI_MODE:
        si_main()
    else:
        main()
