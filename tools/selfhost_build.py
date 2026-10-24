#!/usr/bin/env python3
"""Self-hosted build pipeline: native front end (silu_fe) + native
converter (typed_codegen_flat) + clang, linked through the runtime-.o
cache. No Python runs inside the compiler itself - Python only
orchestrates (spawn, split, link), the way cargo orchestrates rustc.

Usage: python tools/selfhost_build.py file.si -o out [--save-ll PATH]

Both native binaries live at the repo root and rebuild on demand when
their sources are newer (mtime). The flat converter source regenerates
from the converter .py sources via tools/flatten_codegen.py whenever
any of them changed.

First run pays the converter build (~30s); afterwards each build is
fe (ms) + converter + cached clang, no Python in the compile stages.
"""

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FE_SRC = os.path.join(REPO, "selfhost", "silu_fe.si")
FE_BIN = os.path.join(REPO, "silu_fe")
CONV_SRC = os.path.join(REPO, "selfhost", "typed_codegen_flat.si")
CONV_BIN = os.path.join(REPO, "silu_conv")
CONV_DEPS = [
    os.path.join(REPO, "silu", n)
    for n in (
        "typed_codegen.py", "typed_helpers.py",
        "pyobj_runtime.py", "silu_ir_to_llvm.py",
    )
]


def _newer(a, b):
    return not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)


def ensure_frontend(bin_path=None):
    bin_path = bin_path or FE_BIN
    if _newer(FE_SRC, bin_path):
        print("building silu_fe (source newer)...", file=sys.stderr)
        subprocess.run(
            [sys.executable, "-m", "silu", "build", FE_SRC, "-o", bin_path],
            check=True, capture_output=True, cwd=REPO,
        )
    return bin_path


def ensure_converter(bin_path=None):
    bin_path = bin_path or CONV_BIN
    if any(_newer(d, CONV_SRC) for d in CONV_DEPS):
        print("regenerating typed_codegen_flat.si (converter sources newer)...",
              file=sys.stderr)
        gen = subprocess.run(
            [sys.executable, "tools/flatten_codegen.py", "--si"],
            capture_output=True, text=True, cwd=REPO,
        )
        if gen.returncode != 0:
            raise RuntimeError(f"flatten failed:\n{gen.stderr[:2000]}")
        with open(CONV_SRC, "w", encoding="utf-8") as h:
            h.write(gen.stdout)
    if _newer(CONV_SRC, bin_path):
        print("building silu_conv (source newer; ~30s)...", file=sys.stderr)
        subprocess.run(
            [sys.executable, "-m", "silu", "build", CONV_SRC, "-o", bin_path],
            check=True, capture_output=True, cwd=REPO,
        )
    return bin_path


def compile_with(fe, conv, source, out_path, save_ll=None):
    """The three native stages: fe -> converter -> cached clang link.
    Everything between the subprocesses is orchestration only."""
    src = os.path.abspath(source)

    ir = subprocess.run(
        [fe], stdin=open(src, "r"), stdout=subprocess.PIPE,
        cwd=os.path.dirname(src), check=True,
    ).stdout
    full_ll = subprocess.run(
        [conv], input=ir, stdout=subprocess.PIPE, check=True
    ).stdout.decode("utf-8")
    if save_ll:
        with open(save_ll, "w", encoding="utf-8") as h:
            h.write(full_ll)

    sys.path.insert(0, REPO)
    from silu import runtime_cache

    runtime_cache.build_with_cache(None, out_path, full_text=full_ll)


def build(source, out_path, save_ll=None):
    """source .si -> native binary via fe + converter + clang."""
    compile_with(ensure_frontend(), ensure_converter(),
                 source, out_path, save_ll=save_ll)


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
