"""Bootstrap the self-hosted compiler without writing to the install tree.

A wheel's Python and Silu files are immutable inputs. Generated converter
sources and native binaries live in a content-keyed per-user workspace;
`siluc` and `siluc1` remain adjacent because the C driver locates its
compiler relative to its own executable.
"""

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile

import tools.selfhost_build as repo_builder
from silu import __version__

REPO = repo_builder.REPO
_TOOLS = (
    "silu_ir_to_llvm.py", "typed_codegen.py", "typed_helpers.py",
    "pyobj_runtime.py", "typed_expr.py", "typed_match.py", "typed_call.py",
)
_WRAPPERS = ("silu_fe_main.si", "silu_conv_main.si", "siluc.si")
_SELFHOST_SOURCES = ("silu_fe.si", "llvmlite.si")


def _fingerprint():
    h = hashlib.sha256()
    h.update((platform.system() + "/" + platform.machine()).encode())
    h.update(platform.python_version().encode())
    h.update(__version__.encode())
    for name in _TOOLS:
        path = os.path.join(REPO, "silu", name)
        h.update(name.encode())
        with open(path, "rb") as f:
            h.update(f.read())
    for rel in ("tools/flatten_codegen.py", "tools/flatten_si_tail.si",
                "tools/siluc_main.c"):
        h.update(rel.encode())
        with open(os.path.join(REPO, rel), "rb") as f:
            h.update(f.read())
    for name in _WRAPPERS + _SELFHOST_SOURCES:
        h.update(name.encode())
        with open(os.path.join(REPO, "selfhost", name), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:24]


def cache_root():
    root = os.environ.get("XDG_CACHE_HOME")
    if not root:
        root = os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(root, "silu-selfhost", "toolchain-" + _fingerprint())


def _generate_flat(destination):
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "flatten_codegen.py"), "--si"],
        capture_output=True, text=True, cwd=REPO, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"flatten failed:\n{result.stderr[:2000]}")
    with open(destination, "w", encoding="utf-8") as f:
        f.write(result.stdout)


def ensure_toolchain(cache=None):
    """Return ``(siluc, silu_fe)`` in a complete content-keyed cache.

    A temporary sibling workspace prevents a failed compile from leaving
    a seemingly valid cache entry. Concurrent bootstraps may both compile;
    only a complete toolchain is eligible for publication.
    """
    cache = cache or cache_root()
    siluc = os.path.join(cache, "siluc")
    frontend = os.path.join(cache, "silu_fe")
    if os.path.isfile(siluc) and os.path.isfile(os.path.join(cache, "siluc1")) \
            and os.path.isfile(frontend):
        return siluc, frontend

    parent = os.path.dirname(cache)
    os.makedirs(parent, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".build-", dir=parent)
    try:
        # Imports resolve beside the wrapper being compiled, so stage the
        # read-only packaged .si inputs in the writable cache workspace.
        for name in _WRAPPERS + _SELFHOST_SOURCES:
            shutil.copyfile(os.path.join(REPO, "selfhost", name),
                            os.path.join(work, name))
        _generate_flat(os.path.join(work, "typed_codegen_flat.si"))
        for wrapper, output, description in (
            ("silu_fe_main.si", "silu_fe", "native front end"),
            ("siluc.si", "siluc1", "self-hosted compiler (first build ~25s)"),
        ):
            print(f"building {description}...", file=sys.stderr)
            result = subprocess.run(
                [sys.executable, "-m", "silu", "build",
                 os.path.join(work, wrapper), "-o", os.path.join(work, output)],
                capture_output=True, text=True, cwd=REPO, check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stderr[-4000:])
        subprocess.run(
            ["clang", "-O2", os.path.join(REPO, "tools", "siluc_main.c"),
             "-o", os.path.join(work, "siluc")],
            capture_output=True, text=True, cwd=REPO, check=True,
        )
        if not os.path.exists(cache):
            os.replace(work, cache)
        # A concurrent complete build is equally valid; discard ours.
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return siluc, frontend
