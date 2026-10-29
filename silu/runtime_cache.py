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
import platform
import subprocess
import tempfile

_CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache")),
    "silu-runtime",
)

_HEADER_RE = re.compile(
    r'\A(?:[^\n]*\n)*?(?=define|declare|@)'  # ModuleID/triple/layout
)

# any edit to a converter source changes the emitted runtime text, so
# the text cache keys on the sources' combined content hash. A stale
# cache cannot silently corrupt a build: split()'s prefix check
# compares against the CURRENT converter's output and fails loudly.
_TEXT_SOURCES = (
    "typed_codegen.py", "typed_helpers.py",
    "pyobj_runtime.py", "silu_ir_to_llvm.py",
    "typed_expr.py", "typed_match.py", "typed_call.py",
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


def _fingerprint():
    h = hashlib.sha256()
    here = os.path.dirname(os.path.abspath(__file__))
    for name in _TEXT_SOURCES:
        with open(os.path.join(here, name), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:24]


def runtime_text(cached=True):
    """The runtime-only module text (fresh converter, pre-convert).

    Disk-cached under a fingerprint of the converter sources: the
    TypedCodegen import (a 12k-line module that also drags llvmlite)
    and the runtime module build only run on a cold cache."""
    cache = os.path.join(_CACHE_DIR, f"rt-text-{_fingerprint()}.ll")
    if cached and os.path.exists(cache):
        with open(cache, "r", encoding="utf-8") as fh:
            return fh.read()
    from silu.typed_codegen import TypedCodegen

    text = str(TypedCodegen().module)
    os.makedirs(_CACHE_DIR, exist_ok=True)
    tmp = cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, cache)
    return text


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
    # Keep the converter's actual target: a hard-coded ARM64 Darwin
    # triple would poison Linux and Intel-Mac user modules.
    header = full_text[:_HEADER_RE.match(full_text).end()]
    if "target triple" not in header:
        header = '; ModuleID = "silu_user"\n\n'
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
        from silu.typed_codegen import TypedCodegen

        full_text = TypedCodegen().convert(source_ir_json)
    rt_ll, user_ll = split(full_text)
    rt_obj = runtime_object(rt_ll, cache_dir=cache_dir, opt=opt)
    with tempfile.TemporaryDirectory() as td:
        user_ll_path = os.path.join(td, "user.ll")
        with open(user_ll_path, "w") as h:
            h.write(user_ll)
        user_obj = os.path.join(td, "user.o")
        _run(["clang", opt, "-c", user_ll_path, "-o", user_obj])
        # dead_strip keeps only referenced runtime functions in the
        # final binary (a static program links 1 of the 178; verified
        # behavior-identical, ~3x smaller)
        link_flags = (["-Wl,-dead_strip"] if platform.system() == "Darwin"
                      else ["-Wl,--gc-sections"])
        _run(["clang", user_obj, rt_obj, "-o", out_path, "-lm"] + link_flags)
    return full_text
