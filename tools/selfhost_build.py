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
import fcntl
import os
import subprocess
import sys
from contextlib import contextmanager

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# pytest xdist / parallel builds once produced a real silu_conv SIGSEGV:
# concurrent ensure_* rebuilt the same binary while another process was
# reading it (non-atomic write). Every ensure_* therefore holds a
# process-level reentrant flock, and every artifact lands via
# write-to-temp + os.replace so readers never see a torn file.
LOCK_PATH = os.path.join(REPO, ".silu_build.lock")
_LOCK_DEPTH = 0
_LOCK_FD = None


@contextmanager
def build_lock():
    global _LOCK_DEPTH, _LOCK_FD
    if _LOCK_DEPTH == 0:
        _LOCK_FD = open(LOCK_PATH, "w")
        fcntl.flock(_LOCK_FD, fcntl.LOCK_EX)
    _LOCK_DEPTH += 1
    try:
        yield
    finally:
        _LOCK_DEPTH -= 1
        if _LOCK_DEPTH == 0:
            fcntl.flock(_LOCK_FD, fcntl.LOCK_UN)
            _LOCK_FD.close()
            _LOCK_FD = None


def _replace(tmp, out):
    os.replace(tmp, out)


def _atomic_write(path, data):
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as h:
        h.write(data)
    _replace(tmp, path)

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
        "typed_expr.py", "typed_match.py", "typed_call.py",
    )
] + [
    os.path.join(REPO, "tools", "flatten_codegen.py"),
    os.path.join(REPO, "tools", "flatten_si_tail.si"),
]

SILUC_SRC = os.path.join(SELFHOST, "siluc.si")
SILUC_DEPS = [SILUC_SRC] + FE_DEPS + CONV_DEPS


def _newer(a, b):
    return not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)


def _build(src, out, what):
    print(f"building {what} (source newer)...", file=sys.stderr)
    tmp = out + f".tmp{os.getpid()}"
    subprocess.run(
        [sys.executable, "-m", "silu", "build", src, "-o", tmp],
        check=True, capture_output=True, cwd=REPO,
    )
    _replace(tmp, out)


def ensure_frontend():
    with build_lock():
        if any(_newer(d, FE_BIN) for d in FE_DEPS):
            _build(FE_MAIN, FE_BIN, "silu_fe")
    return FE_BIN


def ensure_converter():
    with build_lock():
        if any(_newer(d, CONV_FLAT) for d in CONV_DEPS[3:]):
            print("regenerating typed_codegen_flat.si (converter sources newer)...",
                  file=sys.stderr)
            gen = subprocess.run(
                [sys.executable, "tools/flatten_codegen.py", "--si"],
                capture_output=True, text=True, cwd=REPO,
            )
            if gen.returncode != 0:
                raise RuntimeError(f"flatten failed:\n{gen.stderr[:2000]}")
            _atomic_write(CONV_FLAT, gen.stdout)
        if any(_newer(d, CONV_BIN) for d in CONV_DEPS[:3]):
            _build(CONV_MAIN, CONV_BIN, "silu_conv")
    return CONV_BIN


SILUC1_BIN = os.path.join(REPO, "siluc1")
DRIVER_SRC = os.path.join(REPO, "tools", "siluc_main.c")


def ensure_siluc():
    """siluc1 = the native compiler core (stdin .si -> stdout .ll);
    siluc = the C driver (file-in binary-out, no Python anywhere)."""
    with build_lock():
        ensure_converter()  # flat regeneration feeds the monolith too
        if any(_newer(d, SILUC1_BIN) for d in SILUC_DEPS):
            _build(SILUC_SRC, SILUC1_BIN, "siluc1 (one-shot, ~25s)")
        driver_deps = [DRIVER_SRC] + [SILUC1_BIN]
        if any(_newer(d, SILUC_BIN) for d in driver_deps):
            tmp = SILUC_BIN + f".tmp{os.getpid()}"
            subprocess.run(
                ["clang", "-O2", DRIVER_SRC, "-o", tmp],
                check=True, capture_output=True, cwd=REPO,
            )
            _replace(tmp, SILUC_BIN)
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


def build(source, out_path, save_ll=None, static_only=False):
    """source .si -> native binary via the siluc driver (C, no
    Python anywhere between the user and the compilers)."""
    ensure_siluc()
    src = os.path.abspath(source)
    if save_ll is None and static_only is False:
        # the driver handles the whole pipeline including the .o cache
        subprocess.run(
            [SILUC_BIN, src, "-o", out_path],
            check=True, capture_output=True, cwd=REPO,
        )
        return
    # --save-ll / --static fall back to the split pipeline (siluc1
    # emits .ll; the python side splits/links or runs the gate)
    full_ll = subprocess.run(
        [SILUC1_BIN], stdin=open(src, "r"), stdout=subprocess.PIPE,
        cwd=os.path.dirname(src), check=True,
    ).stdout.decode("utf-8")
    if static_only:
        sys.path.insert(0, REPO)
        from silu.static_gate import static_gate_error, static_violations

        violations = static_violations(full_ll)
        if violations:
            raise RuntimeError(static_gate_error(violations))
    _link(full_ll, out_path, save_ll)


def _link(full_ll, out_path, save_ll=None):
    if save_ll:
        _atomic_write(save_ll, full_ll)
    sys.path.insert(0, REPO)
    from silu import runtime_cache

    runtime_cache.build_with_cache(None, out_path, full_text=full_ll)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", help="Silu source file")
    ap.add_argument("-o", "--output", required=True, help="output binary")
    ap.add_argument("--save-ll", help="also dump the converter's full .ll here")
    ap.add_argument(
        "--static", action="store_true",
        help="refuse programs whose code touches the dynamic (pyobj) runtime",
    )
    args = ap.parse_args()
    build(args.file, args.output, save_ll=args.save_ll,
          static_only=args.static)
    print(f"Built (self-hosted): {args.output}")


if __name__ == "__main__":
    main()
