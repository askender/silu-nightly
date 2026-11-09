"""Cross-file imports for Silu (Rust `mod` shape).

`import foo` reads foo.si next to the importing file, recursively
expands its own imports, and inlines its top-level statements at the
import position. References `foo.X` rewrite to the plain name `X`.
`from foo import a, b` inlines the same way and leaves a/b directly
usable; `import foo as f` aliases.

Imports nested inside function/class bodies (Python's deferred-import
syntax) hoist to compile time the same way: the module inlines at
module level, before the top-level statement enclosing the import,
and the in-body import statement becomes `pass` - a no-op for every
backend. Observable behaviour matches CPython running the same source
against twin .py modules (the call works either way).

Every file is inlined once (diamond imports are safe); a cycle or a
missing .si file is a compile error. Names that do not resolve to a
.si file (os, sys, ...) keep their import node untouched so the
backends keep ignoring them.

The expansion is a pure front-end desugar: the IR handed to every
backend is indistinguishable from a single-file program.
"""

import ast
import os


class ImportError_(Exception):
    pass


def _exports_of(tree: ast.Module) -> set:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _resolve_import_node(node, base_dir: str, seen: set, stack: tuple,
                         aliases: dict):
    """Resolve one Import/ImportFrom node against .si modules.

    Returns (spliced, replacement): spliced holds the top-level nodes
    to inline for resolved modules; replacement is the node to keep at
    the original position (None when every spec resolved, i.e. the
    import is fully consumed - nested callers substitute pass)."""
    if isinstance(node, ast.Import):
        specs = [(a.name, a.asname or a.name, None) for a in node.names]
    elif isinstance(node, ast.ImportFrom) and node.level == 0:
        specs = [(node.module, a.name, a.name) for a in node.names]
    else:
        return [], node
    remaining = []
    spliced = []
    for module_name, alias, _from_names in specs:
        if not module_name or "." in module_name:
            remaining.append((module_name, alias))
            continue
        path = os.path.join(base_dir, module_name + ".si")
        if not os.path.exists(path):
            # a builtin/foreign module: leave the import
            remaining.append((module_name, alias))
            continue
        path = os.path.abspath(path)
        if path in stack:
            chain = " -> ".join(
                os.path.basename(p) for p in (*stack, path)
            )
            raise ImportError_(f"import cycle: {chain}")
        if path not in seen:
            seen.add(path)
            with open(path, "r", encoding="utf-8") as handle:
                sub_source = handle.read()
            sub_tree = ast.parse(sub_source, filename=path)
            _expand(
                sub_tree, os.path.dirname(path), seen,
                (*stack, path), aliases,
            )
            spliced.extend(sub_tree.body)
            sub_exports = _exports_of(sub_tree)
            aliases.setdefault(module_name, set()).update(sub_exports)
        # record the alias even when the module was already inlined:
        # a second import under a new name still needs foo.X rewriting
        if alias != module_name:
            aliases.setdefault(alias, set()).update(aliases[module_name])
    if not remaining:
        return spliced, None
    if isinstance(node, ast.Import):
        node.names = [
            ast.alias(name=m, asname=(a if a != m else None))
            for m, a in remaining
        ]
    else:
        node.names = [
            ast.alias(name=a, asname=None) for _m, a in remaining
        ]
    return spliced, node


class _PassSubstitutor(ast.NodeTransformer):
    """Turn fully-consumed nested import statements into pass."""

    def __init__(self, consumed: set):
        self.consumed = consumed

    def visit_Import(self, node):
        if id(node) in self.consumed:
            return ast.copy_location(ast.Pass(), node)
        return node

    def visit_ImportFrom(self, node):
        if id(node) in self.consumed:
            return ast.copy_location(ast.Pass(), node)
        return node


def _hoist_nested_imports(tree: ast.Module, base_dir: str, seen: set,
                          stack: tuple, aliases: dict) -> None:
    """Hoist .si imports found inside function/class bodies: splice the
    module at module level before the enclosing top-level statement;
    substitute the in-body import with pass. Foreign imports keep their
    nodes (backends no-op them)."""
    inserts = {}
    consumed_by_stmt = {}
    for i, stmt in enumerate(tree.body):
        consumed = set()
        for sub in ast.walk(stmt):
            if not isinstance(sub, (ast.Import, ast.ImportFrom)):
                continue
            spliced, replacement = _resolve_import_node(
                sub, base_dir, seen, stack, aliases
            )
            if spliced:
                inserts.setdefault(i, []).extend(spliced)
            if replacement is None:
                consumed.add(id(sub))
            # partial resolution mutated sub.names in place
        if consumed:
            consumed_by_stmt[i] = consumed
    if not inserts and not consumed_by_stmt:
        return
    for i, consumed in consumed_by_stmt.items():
        _PassSubstitutor(consumed).visit(tree.body[i])
    if inserts:
        new_body = []
        for i, stmt in enumerate(tree.body):
            new_body.extend(inserts.get(i, []))
            new_body.append(stmt)
        tree.body = new_body


def _expand(tree: ast.Module, base_dir: str, seen: set, stack: tuple,
            aliases: dict) -> None:
    """Splice imported .si files into tree.body in place; record
    alias -> exported-names in aliases."""
    new_body = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            spliced, replacement = _resolve_import_node(
                node, base_dir, seen, stack, aliases
            )
            new_body.extend(spliced)
            if replacement is not None:
                new_body.append(replacement)
        else:
            new_body.append(node)
    tree.body = new_body
    _hoist_nested_imports(tree, base_dir, seen, stack, aliases)


class _AliasRewriter(ast.NodeTransformer):
    """foo.X -> X for imported aliases (attribute access only)."""

    def __init__(self, aliases: dict):
        self.aliases = aliases

    def visit_Attribute(self, node: ast.Attribute):
        self.generic_visit(node)
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.aliases
            and node.attr in self.aliases[node.value.id]
        ):
            return ast.copy_location(
                ast.Name(id=node.attr, ctx=node.ctx), node
            )
        return node


# directory of the file being compiled (set by the CLI); --source
# stdin programs have no import surface
SOURCE_DIR = "."


def _reject_semicolons(source: str) -> None:
    """Silu has no `;` statement separators. CPython's ast would
    accept them (the Python plane rides ast.parse), while the
    self-hosted and Rust front ends reject - pin the strict subset
    at the shared parse choke point. Error path only: no accepted
    program's IR changes; separators inside strings/comments are
    untouched (tokenize-based scan)."""
    import io
    import tokenize

    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.OP and tok.string == ";":
                raise SyntaxError(
                    f"; statement separators are not part of Silu "
                    f"(line {tok.start[0]})"
                )
    except tokenize.TokenError:
        pass  # let ast.parse produce the real diagnostic


def expand_imports_tree(source: str, base_dir: str) -> ast.Module:
    """Expand .si imports in source; returns the merged AST. Line
    numbers keep each file's original positions (no re-parse)."""
    _reject_semicolons(source)
    tree = ast.parse(source)
    aliases: dict = {}
    _expand(tree, os.path.abspath(base_dir), set(), (), aliases)
    if aliases:
        tree = _AliasRewriter(aliases).visit(tree)
    # unconditionally: partially-resolved import nodes get REBUILT
    # ast.alias children with no locations, and compile() requires
    # lineno on them even when no alias rewriting happened
    ast.fix_missing_locations(tree)
    return tree


def parse_with_imports(source: str) -> ast.Module:
    return expand_imports_tree(source, SOURCE_DIR)
