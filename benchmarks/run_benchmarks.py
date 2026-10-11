#!/usr/bin/env python3
"""Benchmark: Silu interpreter vs CPython vs compiled native binary.

For each benchmarks/*.si program:
1. Compile through the silu ir/llvm pipeline with clang.
2. Verify the binary, the Silu interpreter, AND CPython running the
   same file directly all produce identical output.
3. Time 3 runs of each (median), including process startup.

The .si sources are valid Python (Silu syntax is a Python subset), so
CPython executes them directly - no translation involved.

Usage: python benchmarks/run_benchmarks.py [--runs N] [--filter substr]
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


def run(cmd, timeout=300):
    return subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, timeout=timeout
    )


def median_time(cmd, runs, timeout=300):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = run(cmd, timeout=timeout)
        elapsed = time.perf_counter() - start
        if result.returncode != 0:
            raise RuntimeError(f"{cmd} failed: {result.stderr[:200]}")
        times.append(elapsed)
    return statistics.median(times), result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--filter", default="")
    args = parser.parse_args()

    programs = sorted(
        p for p in (REPO / "benchmarks").glob("*.si") if args.filter in p.name
    )
    if not programs:
        print("no benchmark programs matched", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        # Startup baseline: minimal program through all three paths
        baseline = Path(tmp) / "hello.si"
        baseline.write_text('print("ok")\n')
        baseline_ir = Path(tmp) / "hello.ir.json"
        baseline_ll = Path(tmp) / "hello.ll"
        baseline_bin = Path(tmp) / "hello_bin"
        run([SILU, "ir", baseline, "--output", baseline_ir])
        run([SILU, "llvm", baseline_ir, "--output", baseline_ll])
        clang_result = run(["clang", baseline_ll, "-o", baseline_bin])
        if clang_result.returncode != 0:
            raise RuntimeError("baseline clang failed")
        interp_base, _ = median_time([SILU, "interpret", baseline], args.runs)
        cpython_base, _ = median_time([CPYTHON, baseline], args.runs)
        bin_base, _ = median_time([baseline_bin], args.runs)

        rows = []
        print(
            f"{'program':<10} {'silu-int':>10} {'cpython':>10} {'binary':>10} "
            f"{'vs-int':>7} {'vs-cpy':>7}  match"
        )
        print("-" * 72)
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
            if run(["clang", ll_file, "-o", binary]).returncode != 0:
                print(f"{program.stem:<10}  SKIP (clang failed)")
                continue

            interp_time, interp_out = median_time(
                [SILU, "interpret", program], args.runs
            )
            cpython_time, cpython_out = median_time([CPYTHON, program], args.runs)
            bin_time, bin_out = median_time([binary], args.runs)

            match = "ok" if interp_out == bin_out == cpython_out else "MISMATCH!"
            vs_interp = interp_time / bin_time if bin_time else float("inf")
            vs_cpython = cpython_time / bin_time if bin_time else float("inf")
            rows.append(
                (
                    program.stem,
                    interp_time,
                    cpython_time,
                    bin_time,
                    vs_interp,
                    vs_cpython,
                )
            )
            print(
                f"{program.stem:<10} {interp_time:>9.3f}s {cpython_time:>9.3f}s "
                f"{bin_time:>9.4f}s {vs_interp:>6.0f}x {vs_cpython:>6.1f}x  {match}"
            )

        print("-" * 72)
        print(
            f"startup baseline: silu-int {interp_base:.3f}s, "
            f"cpython {cpython_base:.3f}s, binary {bin_base:.4f}s"
        )
        if rows:
            geo_vs_int = statistics.geometric_mean(r[4] for r in rows)
            geo_vs_cpy = statistics.geometric_mean(r[5] for r in rows)
            print(
                f"geometric mean: {geo_vs_int:.0f}x vs silu-int, "
                f"{geo_vs_cpy:.1f}x vs cpython"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
