"""Runtime-object cache for `silu build`.

Every program's .ll embeds the same ~350KB pyobj runtime (178
functions), created by the converter before any user statement. This
module splits the emitted .ll at that boundary and compiles the
runtime once into a cached .o (keyed by its content hash); per
program, clang only sees the ~2-30KB user part, then links.

Layout guarantee (verified by the prefix check at split time and by
the byte gates): the runtime items are created in TypedCodegen's
__init__ and precede every user item, so the runtime text is a
strict PREFIX of the full module text. The user module gets explicit
declarations for every runtime symbol it references (functions via
`declare`, globals via `= external global`), because internal linkage
cannot survive a module boundary - the runtime object's definitions
are therefore emitted with default visibility (a symbol-table change
only; the .ll split path never runs in the byte-identity gates).
"""

import hashlib
import os
import re
import subprocess
import tempfile

from silu.typed_codegen import TypedCodegen

_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "silu-runtime"
)

_HEADER_RE = re.compile(
    r'\A(?:[^\n]*\n)*?(?=define|declare|@)'  # ModuleID/triple/layout
)


def _body(text):
    """Module text without the leading header lines."""
    m = _HEADER_RE.match(text)
    return text[m.end():] if m else text


def _global_type(init_text):
    """The TYPE from a global definition line's '<type> <initializer>'
    prefix (external declarations carry the type only)."""
    t = init_text.strip()
    if t.startswith("[") or t.startswith("{"):
        depth = 0
        for i, ch in enumerate(t):
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    return t[: i + 1]
        return t
    # scalar: first token (i64, double, ptr, i8*)
    return t.split()[0]


def runtime_text():
    """The runtime-only module text (fresh converter, pre-convert)."""
    return str(TypedCodegen().module)


def split(full_text, rt_text=None):
    """(runtime_ll, user_ll) for a full converter output."""
    if rt_text is None:
        rt_text = runtime_text()
    rb, fb = _body(rt_text), _body(full_text)
    if not fb.startswith(rb):
        raise RuntimeError(
            "runtime prefix invariant violated: the converter emitted "
            "user items before the runtime finished - cannot split"
        )
    user_body = fb[len(rb):]

    # every symbol the runtime defines: functions + globals
    rt_fns = {}
    for m in re.finditer(
        r'^define\s+(.+?)\s+@"([A-Za-z0-9_.$]+)"\s*\(', rb, re.M
    ):
        rt_fns[m.group(2)] = m.group(1)
    rt_globals = {}
    for m in re.finditer(
        r'^@"([A-Za-z0-9_.$]+)"\s*=\s*(?:internal\s+)?'
        r'global\s+([^,;\n]+)', rb, re.M
    ):
        rt_globals[m.group(1)] = _global_type(m.group(2))

    # declarations the user part needs: symbols it references that the
    # runtime defines (and it does not define itself)
    user_defined = set(re.findall(
        r'^@"([A-Za-z0-9_.$]+)"\s*=', user_body, re.M
    )) | set(re.findall(
        r'^define\s+[^\n]*@"([A-Za-z0-9_.$]+)"', user_body, re.M
    ))
    referenced = set(re.findall(r'@"([A-Za-z0-9_.$]+)"', user_body))
    decls = []
    for name in sorted(referenced - user_defined):
        if name in rt_fns:
            decls.append(f"declare {rt_fns[name]} @{name}(...)")
        elif name in rt_globals:
            decls.append(f'@"{name}" = external global {rt_globals[name]}')
    # external declares (printf, intrinsics) live in the full text's
    # header region; the user module keeps its own copies
    header_declares = re.findall(
        r'^declare\s+[^\n]+$', _body(full_text), re.M
    )
    header = (
        '; ModuleID = "silu_user"\n'
        'target triple = "arm64-apple-darwin24.6.0"\n'
        'target datalayout = "e-m:o-p270:32:32-p271:32:32-p272:64:64-'
        'i64:64-i128:128-n32:64-S128-Fn32"\n\n'
    )
    user_ll = (
        header
        + "\n".join(header_declares)
        + ("\n\n" if header_declares else "")
        + "\n".join(decls)
        + ("\n\n" if decls else "")
        + user_body
    )
    # the runtime object must expose its symbols cross-module: internal
    # linkage cannot survive the boundary
    rt_ll = rt_text.replace("= internal global", "= global")
    return rt_ll, user_ll


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{r.stderr[:2000]}")
    return r


def runtime_object(rt_ll=None, cache_dir=None, opt="-O2"):
    """Path to the cached compiled runtime .o, compiling it on miss."""
    if rt_ll is None:
        rt_ll = runtime_text()
    rt_ll = rt_ll.replace("= internal global", "= global")
    key = hashlib.sha256(rt_ll.encode()).hexdigest()[:24]
    cache = cache_dir or _CACHE_DIR
    obj = os.path.join(cache, f"rt-{key}.o")
    if os.path.exists(obj):
        return obj
    os.makedirs(cache, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ll", delete=False
    ) as h:
        h.write(rt_ll)
        rt_path = h.name
    try:
        _run(["clang", opt, "-c", rt_path, "-o", obj])
    finally:
        os.unlink(rt_path)
    return obj


def build_with_cache(source_ir_json, out_path, opt="-O2", cache_dir=None,
                     full_text=None):
    """Full pipeline: convert (unless the caller already did), split,
    compile user .o, link the cached runtime .o. Returns the
    converter's full .ll text."""
    if full_text is None:
        full_text = TypedCodegen().convert(source_ir_json)
    rt_ll, user_ll = split(full_text)
    rt_obj = runtime_object(rt_ll, cache_dir=cache_dir, opt=opt)
    with tempfile.TemporaryDirectory() as td:
        user_ll_path = os.path.join(td, "user.ll")
        with open(user_ll_path, "w") as h:
            h.write(user_ll)
        user_obj = os.path.join(td, "user.o")
        _run(["clang", opt, "-c", user_ll_path, "-o", user_obj])
        _run(["clang", user_obj, rt_obj, "-o", out_path])
    return full_text
