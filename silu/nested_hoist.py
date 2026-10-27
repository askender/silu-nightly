"""Nested def / lambda hoisting with Rust nested-item semantics.

Both front ends (silu/ir_generator.py and selfhost/silu_fe.si) run this
pass over the finished module IR:

- a nested ``def`` lifts to module level under a path-mangled name
  (``Class__outer__inner`` / ``outer__inner``)
- nested functions never capture enclosing locals - referencing one is an
  error (pass it as a parameter instead); the single sanctioned binding
  is ``self``: a hoisted function that touches ``self`` directly or by
  calling one that does gets ``self`` prepended (annotated with the
  class), and every call site in the group passes ``self`` along
- a ``lambda`` becomes a hoisted one-statement function; the lambda
  expression itself becomes a ``("funcref", name)`` node (a function
  reference as a value)
- direct calls to hoisted names are rewritten to the mangled names

The pass is pure tree rewriting: backends only ever see module-level
func_defs, plain direct calls, and funcref nodes.
"""

# opcodes whose first element is a string head; everything else in a
# tuple that is not an opcode position is data
_STMT_OPS_WITH_BODY = {
    "if": (2, 3),
    "while": (2,),
    "for": (3,),
    "match": (2,),  # per-case bodies handled via match_case
}

_BUILTIN_NAMES = {
    "len", "range", "str", "int", "float", "bool", "print", "fmt",
    "min", "max", "abs", "input", "enumerate", "isinstance",
    "read_stdin", "read_file", "ord", "chr", "repr", "tuple", "list",
    "dict", "set", "type", "sorted", "zip", "map", "sum", "any", "all",
    "getattr", "setattr", "hasattr", "bytes", "bytearray", "id",
}


class HoistError(Exception):
    """A nested function captures locals or a lambda needs self."""


def _is_node(x):
    return isinstance(x, (list, tuple)) and len(x) > 0 and isinstance(x[0], str)


def _mentions_name(node, name):
    """Does the tree contain ("name", name)? Descends through both IR
    nodes and statement/argument lists (tuples whose head is not a
    string). Assignment targets are bare strings, never ("name", ...)
    nodes, so a match is a load."""
    if not isinstance(node, (list, tuple)):
        return False
    if (
        len(node) == 2
        and isinstance(node[0], str)
        and node[0] == "name"
        and node[1] == name
    ):
        return True
    return any(_mentions_name(c, name) for c in node if isinstance(c, (list, tuple)))


def _calls_one_of(node, names):
    if not isinstance(node, (list, tuple)):
        return False
    if (
        len(node) >= 2
        and isinstance(node[0], str)
        and node[0] == "call"
        and isinstance(node[1], (list, tuple))
        and len(node[1]) == 2
        and node[1][0] == "name"
        and node[1][1] in names
    ):
        return True
    return any(_calls_one_of(c, names) for c in node if isinstance(c, (list, tuple)))


def _collect_locals(node, out):
    """Names assigned within a function body: assign/ann_assign/
    aug_assign targets (bare strings), for-loop targets, and nested
    def names. These are the function's own locals, never captures."""
    if not isinstance(node, (list, tuple)):
        return
    if len(node) >= 2 and isinstance(node[0], str):
        op = node[0]
        if op in ("assign", "ann_assign", "aug_assign") and isinstance(node[1], str):
            out.add(node[1])
        elif op == "tuple_assign" and len(node) >= 2:
            for target in node[1]:
                if isinstance(target, str):
                    out.add(target)
                elif (
                    isinstance(target, (list, tuple))
                    and len(target) >= 2
                    and target[0] == "name"
                    and isinstance(target[1], str)
                ):
                    out.add(target[1])
        elif op in ("for", "c_for") and len(node) >= 4:
            target = node[1]
            if isinstance(target, str):
                out.add(target)
            elif (
                isinstance(target, (list, tuple))
                and len(target) == 2
                and target[0] == "name"
                and isinstance(target[1], str)
            ):
                out.add(target[1])
            elif (
                isinstance(target, (list, tuple))
                and len(target) >= 2
                and target[0] == "tuple_unpack"
            ):
                for name in target[1]:
                    out.add(name)
        elif op == "func_def":
            out.add(node[1])
            return
    for c in node:
        if isinstance(c, (list, tuple)):
            _collect_locals(c, out)


def _free_names(node, out):
    if not isinstance(node, (list, tuple)):
        return
    if (
        len(node) == 2
        and isinstance(node[0], str)
        and node[0] == "name"
        and isinstance(node[1], str)
    ):
        out.add(node[1])
        return
    for c in node:
        if isinstance(c, (list, tuple)):
            _free_names(c, out)


def _collect_assigned_names(stmts, sink):
    """Names the function body itself binds (assignments, for targets,
    ann/aug assigns). A nested def's name can be shadowed by such a
    local - uses after the rebinding read the local slot, not the
    hoisted function."""
    for st in stmts if isinstance(stmts, (list, tuple)) else []:
        if not isinstance(st, (list, tuple)) or not st:
            continue
        op = st[0]
        if op in ("assign", "ann_assign", "aug_assign"):
            if isinstance(st[1], str):
                sink.add(st[1])
            elif (
                isinstance(st[1], (list, tuple))
                and len(st[1]) >= 2
                and st[1][0] == "name"
            ):
                sink.add(st[1][1])
        elif op == "for" and len(st) >= 2:
            t = st[1]
            if isinstance(t, str):
                sink.add(t)
            elif (
                isinstance(t, (list, tuple))
                and len(t) >= 2
                and t[0] == "name"
            ):
                sink.add(t[1])
            _collect_locals(st[3] if len(st) > 3 else [], sink)
        elif op == "if" and len(st) >= 4:
            _collect_locals(st[2], sink)
            _collect_locals(st[3], sink)
        elif op == "while" and len(st) >= 3:
            _collect_locals(st[2], sink)


class _Group:
    """One outer function's hoisting context."""

    def __init__(self, prefix, cls_name, is_method, global_names):
        self.prefix = prefix
        self.cls_name = cls_name
        self.is_method = is_method
        self.globals = global_names
        self.renames = {}      # source name -> mangled
        self.hoisted = []      # module-level func_def nodes
        self.counter = 0

    def fresh(self, base):
        self.counter += 1
        return "%s__%s%d" % (self.prefix, base, self.counter)


def hoist_module(module):
    """Run the pass over ("module", stmts). Returns a new module node."""
    global_names = set(_BUILTIN_NAMES)
    for stmt in module[1]:
        if _is_node(stmt) and stmt[0] in ("func_def", "class_def"):
            global_names.add(stmt[1])
        elif _is_node(stmt) and stmt[0] in ("assign", "ann_assign") and isinstance(stmt[1], str):
            global_names.add(stmt[1])

    out = []
    for stmt in module[1]:
        if _is_node(stmt) and stmt[0] == "func_def":
            extra = []
            out.append(_hoist_def(stmt, None, False, global_names, extra))
            out.extend(extra)  # right after the parent: registration order
        elif _is_node(stmt) and stmt[0] == "class_def":
            cls = stmt[1]
            body = []
            extra = []
            for m in stmt[3]:
                if _is_node(m) and m[0] == "func_def":
                    is_method = len(m[2]) > 0 and m[2][0] == "self"
                    body.append(_hoist_def(m, cls, is_method, global_names, extra))
                else:
                    body.append(m)
            out.append((stmt[0], stmt[1], stmt[2], tuple(body)))
            out.extend(extra)
        else:
            out.append(stmt)
    return (module[0], tuple(out))


def _hoist_def(func_def, cls_name, is_method, global_names, extra):
    """Hoist one (possibly method) def; append results to extra."""
    prefix = ("%s__%s" % (cls_name, func_def[1])) if cls_name else func_def[1]
    group = _Group(prefix, cls_name, is_method, global_names)

    _name, _params, body, _annos, _ret = (
        func_def[1], func_def[2], func_def[3], func_def[4],
        func_def[5] if len(func_def) > 5 else None,
    )
    group.locals = set()
    _collect_assigned_names(body, group.locals)
    new_body = _rec(body, group)

    # transitive self-need fixpoint over the whole group
    needs = {}
    for h in group.hoisted:
        needs[h[1]] = _mentions_name(h[3], "self")
    changed = True
    while changed:
        changed = False
        for h in group.hoisted:
            if needs[h[1]]:
                continue
            callees = [m for m, v in needs.items() if v]
            if _calls_one_of(h[3], callees):
                needs[h[1]] = True
                changed = True
    needing = {m for m, v in needs.items() if v}

    final = []
    for h in group.hoisted:
        mangled = h[1]
        body2 = _insert_self_calls(h[3], needing) if mangled in needing else h[3]
        if mangled in needing:
            cls_anno = (("name", cls_name) if cls_name else None)
            h = (
                h[0], mangled,
                ("self",) + tuple(h[2]),
                body2,
                (cls_anno,) + tuple(h[4]),
                h[5] if len(h) > 5 else None,
            )
        else:
            h = h[0:3] + (body2,) + h[4:]
        # capture check: free names must be globals, params, the
        # function's own locals, self, or sibling hoisted names within
        # the same group (calls already renamed to mangled names)
        own_locals = set()
        _collect_locals(h[3], own_locals)
        bound = set(h[2]) | own_locals | {"self"} | {g[1] for g in group.hoisted}
        free = set()
        _free_names(h[3], free)
        bad = free - bound - global_names
        if bad:
            raise HoistError(
                "nested function '%s' captures enclosing variable(s) "
                "%s; pass them as parameters (Rust nested-item "
                "semantics: no captures)" % (mangled, sorted(bad))
            )
        final.append(h)

    if is_method and needing:
        new_body = _insert_self_calls(new_body, needing)
    extra.extend(final)
    return func_def[0:3] + (new_body,) + func_def[4:]


def _rec(node, group):
    """Rewrite one statement list / expression tree in place.

    A tuple with a string head is an IR node; any other list/tuple is a
    statement/argument sequence (rebuilt, Nones from extracted defs
    dropped)."""
    if isinstance(node, (list, tuple)):
        if len(node) > 0 and isinstance(node[0], str):
            pass  # IR node - fall through to the opcode dispatch below
        else:
            items = []
            for x in node:
                r = _rec(x, group)
                if r is not None:
                    items.append(r)
            return tuple(items) if isinstance(node, tuple) else items
    if not _is_node(node):
        return node
    op = node[0]

    if op == "func_def":
        # nested def: hoist (its own body is rewritten in the same group)
        mangled = "%s__%s" % (group.prefix, node[1])
        group.renames[node[1]] = mangled
        body = _rec(node[3], group)
        group.hoisted.append(
            ("func_def", mangled, node[2], body, node[4],
             node[5] if len(node) > 5 else None)
        )
        return None  # removed from the enclosing statement list

    if op == "lambda":
        mangled = group.fresh("L")
        if _mentions_name(node[2], "self"):
            raise HoistError(
                "lambda capturing 'self' is not supported; use a nested def"
            )
        body = _rec(node[2], group)
        group.hoisted.append(
            ("func_def", mangled, node[1], (("return", body),),
             tuple(None for _ in node[1]), None)
        )
        return ("funcref", mangled)

    if (
        op == "call"
        and isinstance(node[1], (list, tuple))
        and len(node[1]) == 2
        and node[1][0] == "name"
        and node[1][1] in group.renames
    ):
        mangled = group.renames[node[1][1]]
        args = tuple(_rec(a, group) for a in node[2])
        return ("call", ("name", mangled), args, node[3])

    if (
        op == "name"
        and isinstance(node[1], str)
        and node[1] in group.renames
    ):
        # a hoisted function referenced as a VALUE (passed as an
        # argument): point at the mangled name; the typed backend
        # resolves funcref values statically. A name the body ALSO
        # assigns is a local that shadows the function - uses read
        # the local slot, never the funcref
        if node[1] in getattr(group, "locals", ()):
            return node
        return ("funcref", group.renames[node[1]])

    return tuple(_rec(x, group) for x in node)


def _insert_self_calls(body, needing):
    """Second pass: prepend the self argument at direct call sites of
    self-needing hoisted functions (call sites already use mangled names).
    Descends through both IR nodes and statement lists."""
    if isinstance(body, (list, tuple)):
        if (
            len(body) >= 2
            and isinstance(body[0], str)
            and body[0] == "call"
            and isinstance(body[1], (list, tuple))
            and len(body[1]) == 2
            and body[1][0] == "name"
            and body[1][1] in needing
        ):
            return (
                body[0], body[1],
                (("name", "self"),)
                + tuple(_insert_self_calls(a, needing) for a in body[2]),
                body[3],
            )
        rebuilt = tuple(_insert_self_calls(x, needing) for x in body)
        return list(rebuilt) if isinstance(body, list) else rebuilt
    return body
    if (
        body[0] == "call"
        and isinstance(body[1], (list, tuple))
        and len(body[1]) == 2
        and body[1][0] == "name"
        and body[1][1] in needing
    ):
        return (
            body[0], body[1],
            (("name", "self"),) + tuple(
                _insert_self_calls(a, needing) for a in body[2]
            ),
            body[3],
        )
    return tuple(_insert_self_calls(x, needing) for x in body)
