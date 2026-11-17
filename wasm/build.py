#!/usr/bin/env python3
"""Build wasm64 artifacts of the self-hosted Silu compiler.

Usage:
    python3 wasm/build.py siluc1          # compiler .si -> .ll artifact

Pipeline (see docs/wasm_plan.md):
  1. compiler's own .ll via the Python planes (compile_with save_ll)
  2. shim_libc.c -> wasm64 object (wasi-sdk clang, freestanding)
  3. link .ll + shim.o -> wasm64-unknown-unknown, main/memory exported,
     remaining undefined symbols become silu_host imports (JS side)

Everything lands in wasm/artifacts/ (not committed; rebuilt by mtime).
"""

import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WASM = os.path.join(REPO, "wasm")
ART = os.path.join(WASM, "artifacts")
WASI_SDK = os.path.expanduser(os.environ.get("WASI_SDK", "~/wasi-sdk"))
CLANG = os.path.join(WASI_SDK, "bin", "clang")

PY = os.environ.get(
    "PY312",
    "/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3",
)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"build failed: {' '.join(cmd)}\n{r.stdout[-2000:]}\n{r.stderr[-4000:]}")
    return r


TOOLS = {
    "siluc1": "selfhost/siluc.si",
    "fe": "selfhost/silu_fe_main.si",
    "interp": "selfhost/ir_interp.si",
    "backend": "selfhost/wasm_backend.si",
    "wat2wasm": "selfhost/wat2wasm.si",
}


def build_tool(name):
    """One selfhost tool -> wasm64 (compiler .ll via the Python planes)."""

    os.makedirs(ART, exist_ok=True)
    src = TOOLS[name] if os.path.isabs(TOOLS[name]) else os.path.join(REPO, TOOLS[name])
    ll = os.path.join(ART, f"{name}.ll")

    if not os.path.exists(ll) or os.path.getmtime(ll) < max(
        os.path.getmtime(p)
        for p in [src]
        + [os.path.join(REPO, "selfhost", f) for f in os.listdir(os.path.join(REPO, "selfhost")) if f.endswith(".si")]
        + [os.path.join(REPO, "silu", f) for f in os.listdir(os.path.join(REPO, "silu")) if f.endswith(".py")]
    ):
        # siluc.si / silu_fe_main.si call helpers defined in other files
        # (conv_convert / fe_compile) - the monolith rejects them, so
        # they emit through the split fe|conv fixed-point pipeline;
        # interp/backend/wat2wasm are single-file monolith sources (the
        # split pipeline's typed conversion diverges on some shapes,
        # e.g. rawstr -> i64 only on the IR path)
        if name in ("siluc1", "fe"):
            print(f"emitting {name} .ll (self-host fixed point)...", file=sys.stderr)
            sys.path.insert(0, REPO)
            from tools.selfhost_build import compile_with, ensure_converter, ensure_frontend

            compile_with(
                ensure_frontend(),
                ensure_converter(),
                src,
                os.path.join(ART, "_native_probe"),
                save_ll=ll,
            )
        else:
            print(f"emitting {name} .ll (self-host monolith)...", file=sys.stderr)
            sys.path.insert(0, REPO)
            from tools.selfhost_build import ensure_siluc, SILUC1_BIN

            # rebuild siluc1 when its sources are newer: without this a
            # stale binary compiles monolith tools from an outdated
            # compiler (the interpreter/backend/wat2wasm artifacts would
            # silently miss the latest conv fixes). ensure_siluc returns
            # the DRIVER path - the one-shot compiler is SILUC1_BIN.
            ensure_siluc()
            siluc1_bin = SILUC1_BIN
            # the monolith reads the SOURCE directly - no fe|conv IR-JSON
            # handoff
            with open(src, "rb") as fh:
                ir = subprocess.run([siluc1_bin], stdin=fh, capture_output=True, check=True).stdout
            with open(ll, "wb") as fh:
                fh.write(ir)

    # wasm-ld turns --export=main into an (i32,i32) command-ABI wrapper;
    # rename the entry so the plain () -> i32 function is exportable
    link_ll = os.path.join(ART, f"{name}_link.ll")
    text = open(ll, encoding="utf-8").read()
    open(link_ll, "w", encoding="utf-8").write(
        text.replace('@"main"', f'@"{name}_main"')
    )

    shim_c = os.path.join(WASM, "shim", "shim_libc.c")
    shim_o = os.path.join(ART, "shim_libc.o")
    # the two multiply helpers carry optnone: at -O2 instcombine re-widens
    # them into i128 multiplies that lower to __multi3 (self-recursion)
    run([CLANG, "--target=wasm64-unknown-unknown", "-O2", "-ffreestanding",
         "-nostdlib", "-fno-builtin", "-c", shim_c, "-o", shim_o])
    # bulk_mem.ll: memcpy/memmove/memset as wasm memory.copy/fill block
    # ops (the C byte loops capped every runtime str copy at ~60MB/s;
    # see wasm/shim/bulk_mem.ll) - compiled from IR text, linked first
    bulk_ll = os.path.join(WASM, "shim", "bulk_mem.ll")
    bulk_o = os.path.join(ART, "bulk_mem.o")
    run([CLANG, "--target=wasm64-unknown-unknown", "-O2", "-c", bulk_ll, "-o", bulk_o])
    dec_c = os.path.join(WASM, "shim", "dec_bits.c")
    dec_o = os.path.join(ART, "dec_bits.o")
    run([CLANG, "--target=wasm64-unknown-unknown", "-O2", "-ffreestanding",
         "-nostdlib", "-fno-builtin", "-c", dec_c, "-o", dec_o])

    out = os.path.join(ART, f"{name}.wasm")
    # -mbulk-memory is load-bearing: without it the backend lowers the
    # runtime's llvm.memcpy intrinsics into inline byte loops (~600x
    # slower than memory.copy; a 1.9GB tokenize copy took 30s). bulk_mem.o
    # provides the symbol forms for any call-lowered leftovers.
    run([
        CLANG, "--target=wasm64-unknown-unknown", "-O2", "-nostdlib",
        "-mbulk-memory",
        "-Wl,--no-entry", f"-Wl,--export={name}_main", "-Wl,--export-memory",
        "-Wl,--import-undefined", "-Wl,-z,stack-size=16777216",
        # max-memory lets the VM reserve the whole address space upfront:
        # without a declared max each 64KB-page grow detaches and
        # reallocates the JS backing store (~1ms), and leaked temporaries
        # (rawlist_str_get's fresh copy in a one-expression subscript)
        # push the heap through tens of thousands of grows
        "-Wl,--max-memory=4294967296",
        bulk_o, shim_o, dec_o, link_ll, "-o", out,
    ])
    size = os.path.getsize(out)
    print(f"{name}.wasm: {size} bytes ({size / 1e6:.2f} MB)")


def build_siluc1():
    build_tool("siluc1")


def build_web():
    """Assemble the self-contained playground dir: wasm/web/."""
    import shutil

    for tool in TOOLS:
        build_tool(tool)
    web = os.path.join(WASM, "web")
    os.makedirs(web, exist_ok=True)
    shutil.copy(os.path.join(WASM, "shim", "host.mjs"),
                os.path.join(web, "host_core.mjs"))
    for tool in TOOLS:
        shutil.copy(os.path.join(ART, f"{tool}.wasm"), web)
    # the example dropdown tracks the gate corpus automatically (new
    # gate examples join all three wasm gates and appear in the
    # playground with zero manual steps)
    sys.path.insert(0, REPO)
    from tools.sync_playground_examples import sync

    sync(os.path.join(web, "index.html"))
    stamp = os.path.join(web, "BUILD_INFO.txt")
    with open(stamp, "w") as h:
        for t in TOOLS:
            h.write(f"{t}.wasm {os.path.getsize(os.path.join(ART, t + '.wasm'))} bytes\n")
        h.write("host_core.mjs copied from wasm/shim/host.mjs\n")
    print(f"playground ready: serve {web}/ (index + host_core.mjs + "
          + ", ".join(f"{t}.wasm" for t in TOOLS) + ")")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "siluc1"
    if what in TOOLS:
        build_tool(what)
    elif what == "web":
        build_web()
    else:
        sys.exit(f"unknown target: {what}")
