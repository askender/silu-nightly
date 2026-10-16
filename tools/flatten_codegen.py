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

RENAMES = {
    "__init__": "_base_init",
    "_collect_function_defs": "_base_collect_function_defs",
}


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


def main():
    base_src = open(BASE).read()
    derived_src = open(DERIVED).read()
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
    header = header.replace("(SiluToLLVMConverter)", "")

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
        merged.append("")
        merged.extend(block)
    # derived class-level constants (non-function statements) stay
    for item in derived_cls.body:
        if isinstance(item, ast.Assign):
            block = derived_lines[item.lineno - 1:item.end_lineno]
            merged.append("")
            merged.extend(block)

    # derived body: rewire the two super() calls
    for name, s, e in derived_methods:
        block = derived_lines[s:e]
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

    # imports & module-level code
    keep_pre = []
    for l in derived_pre:
        if "from .silu_ir_to_llvm import" in l:
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

    import ast as A

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
            self.generic_visit(node)
            node.body = self._strip_doc(node.body)
            node.returns = None
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
            args = [A.Constant(value=None) for _ in fields]
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

    out = "import llvmlite\n\n" + out
    sys.stdout.write(out)


if __name__ == "__main__":
    if __SI_MODE:
        si_main()
    else:
        main()
