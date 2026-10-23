"""Scope-discipline audit (static, seconds): the name-keyed compiler
state tables must be function-scoped. This is the CI enforcement of
the root-cause-C lesson - a module-level entry surviving a function
scope copy hijacked class resolution for same-named locals (the
'corruption' family of the self-hosting campaign).

Checks, by parsing typed_codegen.py's AST (not regex, so renames
can't silently hide a violation):

1. Every function-body generator that copies a scope table
   (`self.X = dict(self.X)` or `.copy()`) must, within the same
   method, (a) save the original first, (b) restore it before return,
   and (c) drop inherited entries for names the body rebinds (the
   _collect_rebound_names call) for the class-hint tables.
2. The known name-keyed tables (var_kinds, _var_class, _funcref_var,
   _list_elem_class) must not be mutated at module-conversion scope
   without a matching save (i.e. every write outside the generators
   runs while no function body is being converted - approximated by
   requiring generators to be the only copy sites).
3. nested_hoist's funcref rewrite must keep its locals shadow guard
   (_collect_assigned_names consulted before rewriting).
"""

import ast
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCOPE_TABLES = ("var_kinds", "_var_class", "_funcref_var",
                "_list_elem_class", "variables")
# tables carrying CLASS hints need the rebound-name drop
CLASS_HINT_TABLES = ("_var_class", "_list_elem_class")
# plain-kind tables whose inherited instance kinds mislead reads
KIND_TABLES = ("var_kinds",)


def _method_sources(path, class_name):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    yield item.name, item
            return
    raise AssertionError(f"class {class_name} not found in {path}")


def _copies_table(method, table):
    """`self.<table> = dict(self.<table>)` or `.copy()` sites."""
    hits = []
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr in ("dict", "copy")
            and isinstance(node.value.func.value, ast.Attribute)
            and node.value.func.value.attr == table
        ):
            hits.append(node.lineno)
    return hits


def _saves_table(method, table):
    """`old_x = self.table` or `old_x = self.table.copy()`."""
    hits = []
    for node in ast.walk(method):
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith("old_")
        ):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr == "copy"
        ):
            value = value.func.value
        if isinstance(value, ast.Attribute) and value.attr == table:
            hits.append(node.lineno)
    return hits


def _restores_table(method, table):
    hits = []
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            and node.value.id.startswith("old_")
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and node.targets[0].attr == table
        ):
            hits.append(node.lineno)
    return hits


def _fresh_assigns_table(method, table):
    """`self.<table> = {}` / `set()` - a fresh table entering scope."""
    hits = []
    for node in ast.walk(method):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Attribute)
            and node.targets[0].attr == table
            and isinstance(node.value, (ast.Dict, ast.Call))
            and (
                isinstance(node.value, ast.Dict)
                or (isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "set")
            )
        ):
            hits.append(node.lineno)
    return hits


def test_function_generators_scope_every_copied_table():
    src = os.path.join(REPO, "silu/typed_codegen.py")
    generators = [
        (name, m) for name, m in _method_sources(src, "TypedCodegen")
        if name in ("_generate_typed_function_body",
                    "_generate_dynamic_function_body")
    ]
    assert len(generators) == 2, "generators renamed?"
    for name, method in generators:
        for table in SCOPE_TABLES:
            copies = _copies_table(method, table)
            fresh = _fresh_assigns_table(method, table)
            if not copies and not fresh:
                continue
            where = copies or fresh
            saves = _saves_table(method, table)
            restores = _restores_table(method, table)
            assert saves, (
                f"{name}: scopes {table} (line {where}) without "
                "saving the outer value first"
            )
            assert restores, (
                f"{name}: scopes {table} (line {where}) without a "
                "matching restore before returning - the function's "
                "locals would leak into module-level conversion"
            )


def test_generators_drop_rebound_inherited_entries():
    """Both generators must clear inherited entries for names the
    body rebinds (params included) on the class-hint/kind tables."""
    src = os.path.join(REPO, "silu/typed_codegen.py")
    for name, method in _method_sources(src, "TypedCodegen"):
        if name not in ("_generate_typed_function_body",
                        "_generate_dynamic_function_body"):
            continue
        calls = [
            n for n in ast.walk(method)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_collect_rebound_names"
        ]
        assert calls, (
            f"{name}: no _collect_rebound_names call - inherited "
            "class hints for rebound names would leak in"
        )
        # the drop loop must reference the collected set
        src_text = ast.get_source_segment(
            open(src).read(), method
        ) or ""
        assert ".pop(" in src_text, (
            f"{name}: rebound set collected but never used to pop"
        )


def test_nested_hoist_keeps_shadow_guard():
    """The funcref rewrite must skip locally-bound names."""
    path = os.path.join(REPO, "silu/nested_hoist.py")
    text = open(path).read()
    assert "_collect_assigned_names(body, group.locals)" in text, (
        "nested_hoist: the locals-shadow guard was removed - hoisted "
        "function names colliding with locals hijack every use"
    )
    assert 'if node[1] in getattr(group, "locals", ())' in text, (
        "nested_hoist: the rewrite no longer consults group.locals"
    )


def test_no_unguarded_name_keyed_table_writes_at_module_scope():
    """Writes to the name-keyed tables outside the generators are
    module-level conversion (legitimate) - but each generator entry
    must have re-scoped them. Approximation: assert the generators
    are the ONLY `.copy()`/`dict(self.` sites for these tables."""
    src = os.path.join(REPO, "silu/typed_codegen.py")
    tree = ast.parse(open(src).read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name in ("_generate_typed_function_body",
                         "_generate_dynamic_function_body"):
            continue
        for table in SCOPE_TABLES:
            bad = _copies_table(node, table)
            assert not bad, (
                f"{node.name} (line {node.lineno}) copies self."
                f"{table} - scope copies belong to the function-body "
                "generators only; a copy elsewhere silently forks the "
                "table"
            )
