# ruff: noqa: E741, F401 - build tool, not product code
#!/usr/bin/env python3
"""Three-toolchain timing harness (interp vs silu pipeline vs rustc).

Usage: python tools/bench_planes.py

Planes, per benchmark program:
  interp : python -m silu interpret  (total incl. parse - no separate
           compile step exists)
  silu   : compile = silu ir + silu llvm + clang -O2 (the `silu build`
           pipeline); run = the produced binary
  rust   : compile = rustc -C opt-level=3; run = the produced binary

Also isolates the CONVERTER stage of the silu pipeline both ways:
  conv-py  : python -m silu llvm        (Python TypedCodegen)
  conv-self: the natively-built flat converter (self-hosted)

Compile times: median of 3. Run times: best of 5.
"""
import subprocess
import sys
import time
import statistics
import os

REPO = "/Users/askender/aix1/silu"
PY = "/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3"
FLAT_BIN = "/tmp/fp.bin"          # current self-hosted converter (-O2)
BENCH = ["fib", "arith", "float", "list", "mandelbrot", "trees"]


def t_median(fn, n=3):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        xs.append(time.perf_counter() - t0)
        if r.returncode != 0:
            return None, r
    return statistics.median(xs), None


def t_best(fn, n=5):
    best = None
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        dt = time.perf_counter() - t0
        if r.returncode != 0:
            return None, r
        best = dt if best is None or dt < best else best
    return best, None


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, cwd=REPO, **kw)


rows = []
print(f"{'prog':<12}{'interp run':>11}{'silu comp':>11}{'silu run':>10}"
      f"{'rust comp':>11}{'rust run':>10}{'conv-py':>10}{'conv-self':>11}")
for b in BENCH:
    si = f"benchmarks/{b}.si"
    ir = f"/tmp/bm_{b}.ir.json"
    ll = f"/tmp/bm_{b}.ll"
    bin_ = f"/tmp/bm_{b}.bin"

    interp_t, e1 = t_median(
        lambda: sh([PY, "-m", "silu", "interpret", si]), 3)

    def silu_compile():
        sh([PY, "-m", "silu", "ir", si, "--format", "json",
            "--output", ir])
        sh([PY, "-m", "silu", "llvm", ir, "--output", ll])
        return sh(["clang", "-O2", ll, "-o", bin_])

    silu_c, e2 = t_median(silu_compile, 3)

    def conv_py():
        return sh([PY, "-m", "silu", "llvm", ir, "--output", ll])

    conv_py_t, _ = t_median(conv_py, 3)

    def conv_self():
        with open(ir, "rb") as h:
            return subprocess.run([FLAT_BIN], stdin=h,
                                  stdout=open(ll, "wb"),
                                  stderr=subprocess.DEVNULL)

    conv_self_t, _ = t_median(conv_self, 3)

    rs = f"benchmarks/rust/src/{b}.rs"
    rbin = f"/tmp/bm_{b}.rs.bin"

    def rust_compile():
        return sh(["/Users/askender/.cargo/bin/rustc",
                   "-C", "opt-level=3", rs, "-o", rbin])

    rust_c, e3 = t_median(rust_compile, 3)

    silu_r, e4 = t_best(lambda: sh([bin_]), 5)
    rust_r, e5 = t_best(lambda: sh([rbin]), 5)

    def fmt(x):
        return f"{x:9.3f}s" if x is not None else "     FAIL"

    print(f"{b:<12}{fmt(interp_t)}{fmt(silu_c)}{fmt(silu_r)}"
          f"{fmt(rust_c)}{fmt(rust_r)}{fmt(conv_py_t)}{fmt(conv_self_t)}")
    rows.append((b, interp_t, silu_c, silu_r, rust_c, rust_r,
                 conv_py_t, conv_self_t))

# aggregate: totals over the set
tot = ["TOTAL"] + [
    sum(r[i] for r in rows if r[i] is not None)
    for i in range(1, 8)
]
def fmt2(x): return f"{x:9.3f}s"
print(f"{tot[0]:<12}{fmt2(tot[1])}{fmt2(tot[2])}{fmt2(tot[3])}"
      f"{fmt2(tot[4])}{fmt2(tot[5])}{fmt2(tot[6])}{fmt2(tot[7])}")
print()
print("derived ratios (run-only):")
print(f"  interp / silu-bin : {tot[1]/tot[3]:7.1f}x slower than compiled silu")
print(f"  interp / rust-bin : {tot[1]/tot[5]:7.1f}x slower than rust")
print(f"  silu-bin / rust   : {tot[3]/tot[5]:7.1f}x")
print("derived ratios (compile):")
print(f"  silu pipeline / rustc : {tot[2]/tot[4]:7.1f}x")
print(f"  self converter / py converter : {tot[7]/tot[6]:7.2f}x"
      f"  (speedup {tot[6]/tot[7]:.1f}x)")
