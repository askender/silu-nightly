#!/usr/bin/env python3
"""Compiler-plane comparison: original (Python) vs self-hosted vs rustc.

Answers two questions the three-plane table in bench_planes.py does not:
  1. compile speed: original compiler (python frontend + python codegen
     + clang) vs self-hosted compiler (python frontend + native codegen
     + clang), each with and without the runtime-.o cache, vs rustc
     invoked directly (rustc has no cross-run cache; cargo does).
  2. whether rust's number hides a cache: direct rustc timed 3x in a
     row (constant => no cache), plus cargo cold (cargo clean) vs warm
     (immediate rebuild) to show what artifact caching looks like.

Compile times: median of 3. Run times: best of 5 (interp median of 3).
Stage breakdown measured separately on each program.
"""
import os
import statistics
import subprocess
import time

REPO = "/Users/askender/aix1/silu"
PY = "/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3"
FLAT_BIN = "/tmp/fp.bin"
RUSTC = "/Users/askender/.cargo/bin/rustc"
CARGO = "/Users/askender/.cargo/bin/cargo"
BENCH = ["fib", "arith", "float", "list", "mandelbrot", "trees"]


def sh(cmd, cwd=REPO):
    return subprocess.run(cmd, capture_output=True, cwd=cwd)


SELFHOST_BUILD = f"{REPO}/tools/selfhost_build.py"


def t_median(fn, n=3, samples=False):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        xs.append(time.perf_counter() - t0)
        if r.returncode != 0:
            return (None, xs) if samples else None
    return (statistics.median(xs), xs) if samples else statistics.median(xs)


def t_best(fn, n=5):
    best = None
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        dt = time.perf_counter() - t0
        if r.returncode != 0:
            return None
        best = dt if best is None or dt < best else best
    return best


def fmt(x):
    return f"{x:8.3f}s" if x is not None else "    FAIL"


def front_end(si, ir):
    return sh([PY, "-m", "silu", "ir", si, "--format", "json",
               "--output", ir])


def codegen_py(ir, ll):
    return sh([PY, "-m", "silu", "llvm", ir, "--output", ll])


def codegen_native(ir, ll):
    with open(ir, "rb") as h:
        return subprocess.run([FLAT_BIN], stdin=h, cwd=REPO,
                              stdout=open(ll, "wb"),
                              stderr=subprocess.DEVNULL)


def clang_cold(ll, bin_):
    return sh(["clang", "-O2", ll, "-o", bin_])


def build_self_cached_oneproc(si, bin_):
    # the real self-hosted pipeline: native fe + native converter +
    # clang (python only orchestrates); binaries rebuild on source
    # change, so steady-state runs are pure execution
    return sh([PY, SELFHOST_BUILD, si, "-o", bin_])


def link_cached(ll, bin_):
    # stage isolation: just the split + cached clang link
    return sh([PY, "-c",
               "import sys; from silu import runtime_cache; "
               "runtime_cache.build_with_cache("
               "None, sys.argv[1], full_text=open(sys.argv[2]).read())",
               bin_, ll])


def build_orig(si, bin_):
    return sh([PY, "-m", "silu", "build", si, "-o", bin_])


def build_orig_cached(si, bin_):
    env = dict(os.environ, SILU_RUNTIME_CACHE="1")
    return subprocess.run([PY, "-m", "silu", "build", si, "-o", bin_],
                          capture_output=True, cwd=REPO, env=env)


# warm the runtime-.o cache once so cached timings are steady-state
sh([PY, "-c",
    "from silu import runtime_cache; runtime_cache.runtime_object()"],
   )

print(f"{'prog':<12}{'orig':>9}{'orig+oc':>9}{'selfhost':>10}"
      f"{'self+oc':>9}{'rustc':>9}")
comp_rows = []
for b in BENCH:
    si = f"benchmarks/{b}.si"
    ir = f"/tmp/bc_{b}.ir.json"
    ll_py = f"/tmp/bc_{b}.py.ll"
    ll_nat = f"/tmp/bc_{b}.nat.ll"
    bin_orig = f"/tmp/bc_{b}.orig.bin"
    bin_self = f"/tmp/bc_{b}.self.bin"

    front_end(si, ir)
    codegen_py(ir, ll_py)
    codegen_native(ir, ll_nat)

    t_orig = t_median(lambda: build_orig(si, "/tmp/bc_trash.bin"))
    t_orig_c = t_median(lambda: build_orig_cached(si, "/tmp/bc_trash.bin"))

    def build_self():
        front_end(si, ir)
        codegen_native(ir, ll_nat)
        return clang_cold(ll_nat, bin_self)

    t_self = t_median(build_self)

    def build_self_cached():
        return build_self_cached_oneproc(si, bin_self)

    t_self_c = t_median(build_self_cached)

    rs = f"benchmarks/rust/src/{b}.rs"
    rbin = f"/tmp/bc_{b}.rs.bin"

    def rust_compile():
        return sh([RUSTC, "-C", "opt-level=3", rs, "-o", rbin])

    t_rust = t_median(rust_compile)

    print(f"{b:<12}{fmt(t_orig)}{fmt(t_orig_c)}{fmt(t_self)}"
          f"{fmt(t_self_c)}{fmt(t_rust)}")
    comp_rows.append((b, t_orig, t_orig_c, t_self, t_self_c, t_rust))

print(f"{'TOTAL':<12}" + "".join(
    fmt(sum(r[i] for r in comp_rows if r[i] is not None))
    for i in range(1, 6)))
print()

# rustc cache probe: three consecutive compiles of the same file must
# cost the same if rustc keeps no cross-run cache
print("rustc cross-run cache probe (3 consecutive compiles of fib.rs):")
_, xs = t_median(rust_compile, n=3, samples=True)
print("  " + " ".join(f"{x:.3f}s" for x in xs) +
      "   (constant => no hidden cache)")
print()

# cargo artifact-cache probe: cold (after cargo clean) vs warm rebuild
def cargo_cold():
    sh([CARGO, "clean"], cwd=f"{REPO}/benchmarks/rust")
    return sh([CARGO, "build", "--release", "--bin", "fib"],
              cwd=f"{REPO}/benchmarks/rust")

def cargo_warm():
    return sh([CARGO, "build", "--release", "--bin", "fib"],
              cwd=f"{REPO}/benchmarks/rust")

t_cold = t_median(cargo_cold, n=2)
t_warm = t_median(cargo_warm, n=3)
print(f"cargo artifact cache (fib): cold(after clean) {fmt(t_cold)}"
      f"  warm {fmt(t_warm)}")
print()

# stage breakdown on one program (mandelbrot: representative size)
b = "mandelbrot"
si = f"benchmarks/{b}.si"
ir = f"/tmp/bc_{b}.ir.json"
ll_nat = f"/tmp/bc_{b}.nat.ll"
front_end(si, ir)
codegen_native(ir, ll_nat)
print("stage breakdown (mandelbrot, median of 3):")


def fe_front():
    with open(si) as h:
        return subprocess.run([f"{REPO}/silu_fe"], stdin=h,
                              stdout=open(ir, "wb"),
                              stderr=subprocess.DEVNULL, cwd=REPO)


tfe = t_median(fe_front)
t0 = t_median(lambda: front_end(si, ir))
print(f"  native frontend (silu_fe)          {fmt(tfe)}")
t1 = t_median(lambda: codegen_py(ir, ll_py))
t2 = t_median(lambda: codegen_native(ir, ll_nat))
t3 = t_median(lambda: clang_cold(ll_nat, "/tmp/bc_trash.bin"))
t4 = t_median(lambda: link_cached(ll_nat, "/tmp/bc_trash.bin"))
print(f"  python frontend (silu ir)          {fmt(t0)}")
print(f"  codegen python (silu llvm)         {fmt(t1)}")
print(f"  codegen native (fp.bin)            {fmt(t2)}")
print(f"  clang -O2 cold (full .ll)          {fmt(t3)}")
print(f"  clang cached (runtime .o + link)   {fmt(t4)}")
t5 = t_median(lambda: sh([PY, "-c", "pass"]))
t6 = t_median(lambda: sh(["clang", "--version"]))
t7 = t_median(lambda: sh([RUSTC, "--version"]))
print(f"  process spawn: python -c pass      {fmt(t5)}")
print(f"  process spawn: clang --version     {fmt(t6)}")
print(f"  process spawn: rustc --version     {fmt(t7)}")
print()

# run speeds: interpreter vs silu binary (self-hosted build) vs rust
print(f"{'prog':<12}{'interp':>10}{'silu run':>10}{'rust run':>10}")
run_rows = []
for b in BENCH:
    si = f"benchmarks/{b}.si"
    bin_self = f"/tmp/bc_{b}.self.bin"
    rbin = f"/tmp/bc_{b}.rs.bin"
    t_int = t_median(lambda: sh([PY, "-m", "silu", "interpret", si]))
    t_silu = t_best(lambda: sh([bin_self]))
    t_rust = t_best(lambda: sh([rbin]))
    print(f"{b:<12}{fmt(t_int)}{fmt(t_silu)}{fmt(t_rust)}")
    run_rows.append((b, t_int, t_silu, t_rust))
ti = sum(r[1] for r in run_rows if r[1] is not None)
ts = sum(r[2] for r in run_rows if r[2] is not None)
tr = sum(r[3] for r in run_rows if r[3] is not None)
print(f"{'TOTAL':<12}{fmt(ti)}{fmt(ts)}{fmt(tr)}")
print(f"interp/silu {ti/ts:6.0f}x  interp/rust {ti/tr:6.0f}x  "
      f"silu/rust {ts/tr:6.2f}x")
