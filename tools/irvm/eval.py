#!/usr/bin/env python3
"""评测集：哪些代码 编译+运行 快于 解释执行，哪些依然更慢。

对每个 workload 测量（取 3 次最优，含进程启动）：
  编译+运行(native) : silu build -> 运行二进制     （编译时间 + 运行时间）
  编译+运行(rust VM): silu_fe | silu-irvm          （前端 + 字节码 VM）
  编译+运行(silu VM): silu_fe | ir_vm 孪生 native   （前端 + 字节码 VM 孪生）
  解释(ir_interp)   : silu_fe | ir_interp -O2      （前端 + 树遍历解释器）
  解释(CPython)     : python3 直接跑源码
  解释(AST)         : silu interpret（树遍历，最强兼容参照）

最后一列给裁决：编译+运行 vs 解释(ir_interp) 谁快。

用法：python3 tools/irvm/eval.py [bench.si ...]
      无参数时跑内置四件套（fib28 / 循环密集 / 短打印 / fib(12)）
环境：IR_INTERP=路径 覆盖 ir_interp -O2 二进制（缺省 /tmp/ir_interp_O2，
      缺失时自动构建）；IRVM_TWIN=路径 覆盖孪生二进制（缺省自动构建）。
"""
import subprocess, time, sys, os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = "/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3"
if not os.path.exists(PY):
    PY = sys.executable

FIB28 = """\
def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
print(fib(28))
"""
LOOPS = """\
total: int = 0
i: int = 0
while i < 1000000:
    total += i % 7 * 3 - (i % 5)
    i += 1
print(total)
"""
SHORT = """\
print(1)
print(2 + 3)
print(40 + 2)
"""
FIB12 = """\
def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)
print(fib(12))
"""


def best(cmd, stdin=None, shell=False, runs=3):
    t0_best = None
    for _ in range(runs):
        t0 = time.monotonic()
        subprocess.run(cmd, input=stdin, capture_output=True, shell=shell, cwd=REPO)
        dt = time.monotonic() - t0
        if t0_best is None or dt < t0_best:
            t0_best = dt
    return round(t0_best * 1000)


def ensure_ir_interp():
    path = os.environ.get("IR_INTERP", "/tmp/ir_interp_O2")
    if os.path.exists(path):
        return path
    print(f"# 构建 ir_interp native -> {path}（一次性）", file=sys.stderr)
    subprocess.run([PY, "-m", "silu", "build", "selfhost/ir_interp.si", "-O2",
                    "-o", path], cwd=REPO, check=True)
    return path


def ensure_twin():
    path = os.environ.get("IRVM_TWIN", "/tmp/ir_vm_native")
    if os.path.exists(path):
        return path
    print(f"# 构建字节码 VM 孪生 -> {path}（一次性）", file=sys.stderr)
    subprocess.run([PY, "-m", "silu", "build", "selfhost/ir_vm.si",
                    "-o", path], cwd=REPO, check=True)
    return path


def run_workload(name, src):
    ir = f"/tmp/eval_{name}.json"
    binp = f"/tmp/eval_{name}_bin"
    with open(ir, "wb") as f:
        subprocess.run([os.path.join(REPO, "silu_fe")], input=src.encode(),
                       stdout=f, check=True, cwd=REPO)

    # 编译(native，含 clang 链接) —— 编译时间与运行时间分开记
    with open("/tmp/eval_src.si", "w") as f:
        f.write(src)
    t0 = time.monotonic()
    subprocess.run([PY, "-m", "silu", "build", "/tmp/eval_src.si", "-o", binp],
                   cwd=REPO, check=True, capture_output=True)
    build_ms = round((time.monotonic() - t0) * 1000)
    run_ms = best([binp])

    interp = ensure_ir_interp()
    twin = ensure_twin()
    rust_vm = os.path.join(REPO, "tools/irvm/target/release/silu-irvm")

    rust_vm_ms = best(f"./silu_fe < /tmp/eval_src.si | {rust_vm} > /dev/null",
                      shell=True)
    twin_ms = best(f"./silu_fe < /tmp/eval_src.si | {twin} > /dev/null",
                   shell=True)
    interp_ms = best(f"./silu_fe < /tmp/eval_src.si | {interp} > /dev/null",
                     shell=True)

    rows = []
    rows.append(("编译+运行 native", build_ms + run_ms,
                 f"(build {build_ms} + run {run_ms})"))
    rows.append(("编译+运行 rust VM", rust_vm_ms, ""))
    rows.append(("编译+运行 silu VM(孪生)", twin_ms, ""))
    rows.append(("解释 ir_interp", interp_ms, ""))
    cpy = best([sys.executable, "/tmp/eval_src.si"])
    rows.append(("解释 CPython", cpy, ""))
    rows.append(("解释 AST(silu interpret)", best([PY, "-m", "silu", "interpret",
                 "/tmp/eval_src.si"]), ""))

    comp_vm = min(rust_vm_ms, twin_ms)
    verdict = "编译快" if rows[0][1] < interp_ms else "解释快"
    verdict_vm = "VM快" if comp_vm < interp_ms else "解释快"

    print(f"\n=== {name} ===")
    print(f"{'平面':<28}{'ms':>7}  备注")
    for nm, ms, note in rows:
        print(f"{nm:<28}{ms:>7}  {note}")
    print(f"裁决: native 编译+运行 {verdict} | 字节码 VM 编译+运行 {verdict_vm}"
          f" (vs ir_interp {interp_ms}ms)")
    return 0


def main() -> int:
    benches = [("fib28", FIB28), ("loops1m", LOOPS), ("short3prints", SHORT),
               ("fib12", FIB12)]
    for arg in sys.argv[1:]:
        with open(arg) as f:
            benches.append((os.path.basename(arg).replace(".si", ""), f.read()))
    for name, src in benches:
        run_workload(name, src)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
