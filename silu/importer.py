"""Cross-file imports for Silu (Rust `mod` shape).

`import foo` reads foo.si next to the importing file, recursively
expands its own imports, and inlines its top-level statements at the
import position. References `foo.X` rewrite to the plain name `X`.
`from foo import a, b` inlines the same way and leaves a/b directly
usable; `import foo as f` aliases.

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


def _expand(tree: ast.Module, base_dir: str, seen: set, stack: tuple,
            aliases: dict) -> None:
    """Splice imported .si files into tree.body in place; record
    alias -> exported-names in aliases."""
    new_body = []
    for node in tree.body:
        specs = []  # (module_name, alias, from_names or None)
        if isinstance(node, ast.Import):
            for a in node.names:
                specs.append((a.name, a.asname or a.name, None))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for a in node.names:
                specs.append((node.module, a.name, a.name))
        if not specs:
            new_body.append(node)
            continue
        remaining = []
        for module_name, alias, from_names in specs:
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
                new_body.extend(sub_tree.body)
                sub_exports = _exports_of(sub_tree)
                aliases.setdefault(module_name, set()).update(sub_exports)
                if alias != module_name:
                    aliases.setdefault(alias, set()).update(sub_exports)
        if remaining:
            if isinstance(node, ast.Import):
                node.names = [
                    ast.alias(name=m, asname=(a if a != m else None))
                    for m, a in remaining
                ]
            else:
                node.names = [
                    ast.alias(name=a, asname=None) for _m, a in remaining
                ]
            new_body.append(node)
    tree.body = new_body


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


def expand_imports_tree(source: str, base_dir: str) -> ast.Module:
    """Expand .si imports in source; returns the merged AST. Line
    numbers keep each file's original positions (no re-parse)."""
    tree = ast.parse(source)
    aliases: dict = {}
    _expand(tree, os.path.abspath(base_dir), set(), (), aliases)
    if aliases:
        tree = _AliasRewriter(aliases).visit(tree)
        ast.fix_missing_locations(tree)
    return tree


def parse_with_imports(source: str) -> ast.Module:
    return expand_imports_tree(source, SOURCE_DIR)
