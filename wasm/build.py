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


def compiler_ll(out_ll):
    """The compiler compiling itself, via the Python planes."""
    if os.path.exists(out_ll):
        newest_dep = 0
        for root in ("selfhost", "silu"):
            for d, _, fs in os.walk(os.path.join(REPO, root)):
                for f in fs:
                    if f.endswith((".si", ".py")):
                        newest_dep = max(
                            newest_dep, os.path.getmtime(os.path.join(d, f))
                        )
        if os.path.getmtime(out_ll) >= newest_dep:
            return
    print("emitting compiler .ll (self-host fixed point)...", file=sys.stderr)
    sys.path.insert(0, REPO)
    from tools.selfhost_build import compile_with, ensure_converter, ensure_frontend

    compile_with(
        ensure_frontend(),
        ensure_converter(),
        os.path.join(REPO, "selfhost", "siluc.si"),
        os.path.join(ART, "_native_probe"),
        save_ll=out_ll,
    )


def build_siluc1():
    os.makedirs(ART, exist_ok=True)
    ll = os.path.join(ART, "siluc1.ll")
    compiler_ll(ll)

    # wasm-ld treats --export=main as the command ABI (argc/argv wrapper);
    # rename the entry so we can export the plain () -> i32 function.
    link_ll = os.path.join(ART, "siluc1_link.ll")
    text = open(ll, encoding="utf-8").read()
    open(link_ll, "w", encoding="utf-8").write(
        text.replace('@"main"', '@"silu_main"')
    )

    shim_c = os.path.join(WASM, "shim", "shim_libc.c")
    shim_o = os.path.join(ART, "shim_libc.o")
    # the two multiply helpers carry optnone: at -O2 instcombine re-widens
    # them into i128 multiplies that lower to __multi3 (self-recursion)
    run([CLANG, "--target=wasm64-unknown-unknown", "-O2", "-ffreestanding",
         "-nostdlib", "-fno-builtin", "-c", shim_c, "-o", shim_o])

    out = os.path.join(ART, "siluc1.wasm")
    run([
        CLANG, "--target=wasm64-unknown-unknown", "-O2", "-nostdlib",
        "-Wl,--no-entry", "-Wl,--export=silu_main", "-Wl,--export-memory",
        "-Wl,--import-undefined", "-Wl,-z,stack-size=16777216",
        shim_o, link_ll, "-o", out,
    ])
    size = os.path.getsize(out)
    print(f"siluc1.wasm: {size} bytes ({size / 1e6:.2f} MB)")


def build_web():
    """Assemble the self-contained playground dir: wasm/web/."""
    import shutil

    build_siluc1()
    web = os.path.join(WASM, "web")
    os.makedirs(web, exist_ok=True)
    shutil.copy(os.path.join(WASM, "shim", "host.mjs"),
                os.path.join(web, "host_core.mjs"))
    shutil.copy(os.path.join(ART, "siluc1.wasm"), web)
    print(f"playground ready: serve {web}/ (index + host_core.mjs + siluc1.wasm)")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "siluc1"
    if what == "siluc1":
        build_siluc1()
    elif what == "web":
        build_web()
    else:
        sys.exit(f"unknown target: {what}")
