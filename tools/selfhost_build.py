#!/usr/bin/env python3
"""Self-hosted build pipeline: the siluc MONOLITH (front end +
converter in one native process, import-inlined) + clang, linked
through the runtime-.o cache. No Python runs inside the compiler -
Python only orchestrates (spawn, split, link), the way cargo
orchestrates rustc.

Usage: python tools/selfhost_build.py file.si -o out [--save-ll PATH]

Process chain per build: python (orchestration) + siluc + clang x2.
The split binaries (silu_fe / silu_conv wrappers) stay available for
the fixed-point tests; every binary rebuilds on demand when any of
its sources is newer (mtime). The flat converter source regenerates
from the converter .py sources via tools/flatten_codegen.py.
"""

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SELFHOST = os.path.join(REPO, "selfhost")
FE_BIN = os.path.join(REPO, "silu_fe")
CONV_BIN = os.path.join(REPO, "silu_conv")
SILUC_BIN = os.path.join(REPO, "siluc")

FE_MAIN = os.path.join(SELFHOST, "silu_fe_main.si")
FE_DEPS = [FE_MAIN, os.path.join(SELFHOST, "silu_fe.si")]

CONV_MAIN = os.path.join(SELFHOST, "silu_conv_main.si")
CONV_FLAT = os.path.join(SELFHOST, "typed_codegen_flat.si")
CONV_DEPS = [CONV_MAIN, CONV_FLAT, os.path.join(SELFHOST, "llvmlite.si")] + [
    os.path.join(REPO, "silu", n)
    for n in (
        "typed_codegen.py", "typed_helpers.py",
        "pyobj_runtime.py", "silu_ir_to_llvm.py",
    )
]

SILUC_SRC = os.path.join(SELFHOST, "siluc.si")
SILUC_DEPS = [SILUC_SRC] + FE_DEPS + CONV_DEPS


def _newer(a, b):
    return not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)


def _build(src, out, what):
    print(f"building {what} (source newer)...", file=sys.stderr)
    subprocess.run(
        [sys.executable, "-m", "silu", "build", src, "-o", out],
        check=True, capture_output=True, cwd=REPO,
    )


def ensure_frontend():
    if any(_newer(d, FE_BIN) for d in FE_DEPS):
        _build(FE_MAIN, FE_BIN, "silu_fe")
    return FE_BIN


def ensure_converter():
    if any(_newer(d, CONV_FLAT) for d in CONV_DEPS[3:]):
        print("regenerating typed_codegen_flat.si (converter sources newer)...",
              file=sys.stderr)
        gen = subprocess.run(
            [sys.executable, "tools/flatten_codegen.py", "--si"],
            capture_output=True, text=True, cwd=REPO,
        )
        if gen.returncode != 0:
            raise RuntimeError(f"flatten failed:\n{gen.stderr[:2000]}")
        with open(CONV_FLAT, "w", encoding="utf-8") as h:
            h.write(gen.stdout)
    if any(_newer(d, CONV_BIN) for d in CONV_DEPS[:3]):
        _build(CONV_MAIN, CONV_BIN, "silu_conv")
    return CONV_BIN


def ensure_siluc():
    ensure_converter()  # flat regeneration feeds the monolith too
    if any(_newer(d, SILUC_BIN) for d in SILUC_DEPS):
        _build(SILUC_SRC, SILUC_BIN, "siluc (one-shot, ~25s)")
    return SILUC_BIN


def compile_with(fe, conv, source, out_path, save_ll=None):
    """The split three-stage form (front end | converter | cached clang
    link); the fixed-point tests drive this explicitly."""
    src = os.path.abspath(source)

    ir = subprocess.run(
        [fe], stdin=open(src, "r"), stdout=subprocess.PIPE,
        cwd=os.path.dirname(src), check=True,
    ).stdout
    full_ll = subprocess.run(
        [conv], input=ir, stdout=subprocess.PIPE, check=True
    ).stdout.decode("utf-8")
    _link(full_ll, out_path, save_ll)


def build(source, out_path, save_ll=None):
    """source .si -> native binary via siluc + clang."""
    siluc = ensure_siluc()
    src = os.path.abspath(source)
    full_ll = subprocess.run(
        [siluc], stdin=open(src, "r"), stdout=subprocess.PIPE,
        cwd=os.path.dirname(src), check=True,
    ).stdout.decode("utf-8")
    _link(full_ll, out_path, save_ll)


def _link(full_ll, out_path, save_ll=None):
    if save_ll:
        with open(save_ll, "w", encoding="utf-8") as h:
            h.write(full_ll)
    sys.path.insert(0, REPO)
    from silu import runtime_cache

    runtime_cache.build_with_cache(None, out_path, full_text=full_ll)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", help="Silu source file")
    ap.add_argument("-o", "--output", required=True, help="output binary")
    ap.add_argument("--save-ll", help="also dump the converter's full .ll here")
    args = ap.parse_args()
    build(args.file, args.output, save_ll=args.save_ll)
    print(f"Built (self-hosted): {args.output}")


if __name__ == "__main__":
    main()
