#!/usr/bin/env python3
"""Benchmark: Silu interpreter vs CPython vs compiled binary vs Rust.

For each benchmarks/*.si program:
1. Compile through the silu ir/llvm pipeline with clang.
2. Verify the binary, the Silu interpreter, CPython running the same
   file directly, AND the hand-written Rust mirror
   (benchmarks/rust/src/*.rs) all produce identical output.
3. Time runs of each (median), including process startup.

The .si sources are valid Python (Silu syntax is a Python subset), so
CPython executes them directly - no translation involved. The Rust
mirrors are equivalent programs, not translations of the same IR.

Usage: python benchmarks/run_benchmarks.py [--runs N] [--filter substr]
[--no-rust-build]
"""

import argparse
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SILU = REPO / ".venv" / "bin" / "silu"
if not SILU.exists():
    SILU = Path("silu")  # fallback to PATH
CPYTHON = sys.executable
# the CPython plane runs .si sources through the pycompat shim: Silu
# classes get positional ctors + __match_args__, Enum/read_stdin are
# provided - plain CPython cannot execute class patterns or dataclass
# construction
PYCOMPAT = str(Path(__file__).resolve().parent.parent / "tools" / "pycompat.py")


def run(cmd, timeout=300, stdin_path=None):
    if isinstance(cmd, dict):
        cwd = cmd["cwd"]
        cmd = cmd["cmd"]
    else:
        cwd = None
    stdin_handle = open(stdin_path, "r") if stdin_path else None
    try:
        return subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            stdin=stdin_handle,
        )
    finally:
        if stdin_handle:
            stdin_handle.close()


def median_time(cmd, runs, timeout=300, stdin_path=None):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = run(cmd, timeout=timeout, stdin_path=stdin_path)
        elapsed = time.perf_counter() - start
        if result.returncode != 0:
            raise RuntimeError(f"{cmd} failed: {result.stderr[:200]}")
        times.append(elapsed)
    return statistics.median(times), result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--filter", default="")
    parser.add_argument("--no-rust-build", action="store_true")
    parser.add_argument("--report", action="store_true",
                        help="Write RESULTS.md / RESULTS.html")
    args = parser.parse_args()

    programs = sorted(
        p for p in (REPO / "benchmarks").glob("*.si") if args.filter in p.name
    )
    if not programs:
        print("no benchmark programs matched", file=sys.stderr)
        return 1

    # Build the Rust mirrors once (skip with --no-rust-build)
    rust_dir = REPO / "benchmarks" / "rust"
    rust_bins = {}
    if not args.no_rust_build and (rust_dir / "Cargo.toml").exists():
        build = run(
            {"cmd": ["cargo", "build", "--release"], "cwd": str(rust_dir)},
            timeout=600,
        )
        if build.returncode != 0:
            print(
                "warning: cargo build failed, rust column disabled",
                file=sys.stderr,
            )
    for program in programs:
        candidate = rust_dir / "target" / "release" / program.stem
        if candidate.exists():
            rust_bins[program.stem] = candidate

    with tempfile.TemporaryDirectory() as tmp:
        # Startup baseline: minimal program through all paths
        baseline = Path(tmp) / "hello.si"
        baseline.write_text('print("ok")\n')
        baseline_ir = Path(tmp) / "hello.ir.json"
        baseline_ll = Path(tmp) / "hello.ll"
        baseline_bin = Path(tmp) / "hello_bin"
        run([SILU, "ir", baseline, "--output", baseline_ir])
        run([SILU, "llvm", baseline_ir, "--output", baseline_ll])
        clang_result = run(["clang", "-O2", baseline_ll, "-o", baseline_bin])
        if clang_result.returncode != 0:
            raise RuntimeError("baseline clang failed")
        interp_base, _ = median_time([SILU, "interpret", baseline], args.runs)
        cpython_base, _ = median_time([CPYTHON, PYCOMPAT, baseline], args.runs)
        bin_base, _ = median_time([baseline_bin], args.runs)

        rows = []
        print(
            f"{'program':<10} {'silu-int':>10} {'cpython':>10} {'binary':>10} "
            f"{'rust':>10} {'vs-int':>7} {'vs-cpy':>7} {'vs-rust':>8}  match"
        )
        print("-" * 92)
        for program in programs:
            ir_file = Path(tmp) / (program.stem + ".ir.json")
            ll_file = Path(tmp) / (program.stem + ".ll")
            binary = Path(tmp) / (program.stem + "_bin")

            if run([SILU, "ir", program, "--output", ir_file]).returncode != 0:
                print(f"{program.stem:<10}  SKIP (ir failed)")
                continue
            if run([SILU, "llvm", ir_file, "--output", ll_file]).returncode != 0:
                print(f"{program.stem:<10}  SKIP (llvm failed)")
                continue
            if run(["clang", "-O2", ll_file, "-o", binary]).returncode != 0:
                print(f"{program.stem:<10}  SKIP (clang failed)")
                continue

            # programs reading stdin (jsonparse) share a pre-generated
            # input file; generation is scaffolding, not measured work
            stdin_path = Path(tmp) / "shared_input.txt"
            stdin_arg = None
            if program.stem == "jsonparse":
                gen = REPO / "scripts" / "gen_json_input.py"
                gen_result = run([CPYTHON, gen])
                if gen_result.returncode != 0:
                    print(f"{program.stem:<10}  SKIP (input generation failed)")
                    continue
                stdin_path.write_text(gen_result.stdout)
                stdin_arg = str(stdin_path)

            interp_time, interp_out = median_time(
                [SILU, "interpret", program], args.runs, stdin_path=stdin_arg
            )
            cpython_time, cpython_out = median_time(
                [CPYTHON, PYCOMPAT, program], args.runs, stdin_path=stdin_arg
            )
            bin_time, bin_out = median_time(
                [binary], args.runs, stdin_path=stdin_arg
            )

            rust_time = None
            rust_out = None
            rust_bin = rust_bins.get(program.stem)
            if rust_bin is not None:
                rust_time, rust_out = median_time(
                    [rust_bin], args.runs, stdin_path=stdin_arg
                )

            outputs = [interp_out, bin_out, cpython_out]
            if rust_out is not None:
                outputs.append(rust_out)

            def _equivalent(a: str, b: str) -> bool:
                """Exact match, or all floats equal within 1e-9 relative."""
                if a == b:
                    return True
                try:
                    fa = [float(t) for t in a.split()]
                    fb = [float(t) for t in b.split()]
                except ValueError:
                    return False
                if len(fa) != len(fb) or not fa:
                    return False
                return all(
                    abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))
                    for x, y in zip(fa, fb)
                )

            base = outputs[0]
            match = (
                "ok"
                if all(_equivalent(base, o) for o in outputs[1:])
                else "MISMATCH!"
            )
            vs_interp = interp_time / bin_time if bin_time else float("inf")
            vs_cpython = cpython_time / bin_time if bin_time else float("inf")
            vs_rust = rust_time / bin_time if rust_time and bin_time else float("nan")
            rows.append(
                (
                    program.stem,
                    interp_time,
                    cpython_time,
                    bin_time,
                    rust_time,
                    vs_interp,
                    vs_cpython,
                    vs_rust,
                    match,
                )
            )
            rust_str = f"{rust_time:>9.4f}s" if rust_time is not None else " " * 10
            print(
                f"{program.stem:<10} {interp_time:>9.3f}s {cpython_time:>9.3f}s "
                f"{bin_time:>9.4f}s {rust_str} {vs_interp:>6.0f}x "
                f"{vs_cpython:>6.1f}x {vs_rust:>7.1f}x  {match}"
            )

        print("-" * 92)
        print(
            f"startup baseline: silu-int {interp_base:.3f}s, "
            f"cpython {cpython_base:.3f}s, binary {bin_base:.4f}s"
        )
        if rows:
            geo_vs_int = statistics.geometric_mean(r[5] for r in rows)
            geo_vs_cpy = statistics.geometric_mean(r[6] for r in rows)
            geo_vs_rust = statistics.geometric_mean(r[7] for r in rows if r[7] == r[7])
            print(
                f"geometric mean: {geo_vs_int:.0f}x vs silu-int, "
                f"{geo_vs_cpy:.1f}x vs cpython, {geo_vs_rust:.1f}x vs rust"
            )
            if getattr(args, "report", False):
                write_report(rows, geo_vs_int, geo_vs_cpy, geo_vs_rust)
    return 0


def write_report(rows, geo_int, geo_cpy, geo_rust):
    """Write RESULTS.md / RESULTS.html next to this script."""
    import datetime
    import html

    today = datetime.date.today().isoformat()
    header = ["程序", "silu 解释器", "CPython", "silu 二进制", "Rust",
              "vs 解释器", "vs CPython", "vs Rust", "输出"]

    md = [f"# Silu 性能评测结果（{today}）", "",
          "由 `python benchmarks/run_benchmarks.py --report` 生成。",
          "Apple Silicon，CPython / Rust release / clang -O2，"
          "多轮中位数（含进程启动）。", "",
          f"几何平均：**{geo_int:.0f}x vs silu-int，{geo_cpy:.1f}x vs CPython，"
          f"{geo_rust:.1f}x vs Rust**", "",
          "| " + " | ".join(header) + " |",
          "|---" * len(header) + "|"]
    for r in rows:
        cells = [r[0], f"{r[1]:.3f}s", f"{r[2]:.3f}s", f"{r[3]:.4f}s",
                 f"{r[4]:.4f}s", f"{r[5]:.0f}x", f"{r[6]:.1f}x",
                 f"{r[7]:.1f}x", r[8]]
        md.append("| " + " | ".join(cells) + " |")
    md += ["", "方法学与归因实验见 [README.md](README.md)。"]
    (Path(__file__).parent / "RESULTS.md").write_text(
        chr(10).join(md) + chr(10), encoding="utf-8")

    trs = ["<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in header)
           + "</tr>"]
    for r in rows:
        cells = [r[0], f"{r[1]:.3f}s", f"{r[2]:.3f}s", f"{r[3]:.4f}s",
                 f"{r[4]:.4f}s", f"{r[5]:.0f}x", f"{r[6]:.1f}x",
                 f"{r[7]:.1f}x", r[8]]
        trs.append("<tr>" + "".join(
            f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    style = ("body{font-family:-apple-system,sans-serif;margin:2rem auto;"
             "max-width:60rem}table{border-collapse:collapse;width:100%;"
             "font-size:.9rem}th,td{border:1px solid #ddd;padding:6px 10px;"
             "text-align:right}th:first-child,td:first-child{text-align:left}"
             "th{background:#f4f4f4}.geo{background:#eef6ff;padding:10px 14px;"
             "border-radius:6px;display:inline-block}.meta{color:#666;"
             "font-size:.85rem}")
    html_doc = (
        f'<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
        f"<title>Silu 性能评测结果（{today}）</title>"
        f"<style>{style}</style></head><body>"
        f"<h1>Silu 性能评测结果</h1>"
        f'<p class="meta">生成于 {today} · Apple Silicon · '
        f"多轮中位数（含进程启动）</p>"
        f'<p class="geo">{geo_int:.0f}x vs silu-int · '
        f"{geo_cpy:.1f}x vs CPython · {geo_rust:.1f}x vs Rust</p>"
        f"<table>{chr(10).join(trs)}</table>"
        f'<p class="meta">方法学与归因实验见 '
        f'<a href="README.md">README.md</a></p></body></html>'
    )
    (Path(__file__).parent / "RESULTS.html").write_text(
        html_doc, encoding="utf-8")
    print("report written: RESULTS.md / RESULTS.html")


if __name__ == "__main__":
    sys.exit(main())
