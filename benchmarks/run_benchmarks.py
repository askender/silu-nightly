#!/usr/bin/env python3
"""Benchmark: Silu interpreter vs compiled native binary.

For each benchmarks/*.si program:
1. Compile through the silu ir/llvm pipeline with clang.
2. Verify the binary output matches the interpreter output exactly.
3. Time 3 runs of each side (median), including process startup.

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
        # Startup baseline: minimal program through both paths
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
        bin_base, _ = median_time([baseline_bin], args.runs)

        rows = []
        print(
            f"{'program':<10} {'interpreter':>12} {'binary':>10} "
            f"{'speedup':>9}  output-match"
        )
        print("-" * 58)
        for program in programs:
            ir_file = Path(tmp) / (program.stem + ".ir.json")
            ll_file = Path(tmp) / (program.stem + ".ll")
            binary = Path(tmp) / (program.stem + "_bin")

            compile_result = run([SILU, "ir", program, "--output", ir_file])
            if compile_result.returncode != 0:
                print(f"{program.stem:<10}  SKIP (ir failed)")
                continue
            compile_result = run([SILU, "llvm", ir_file, "--output", ll_file])
            if compile_result.returncode != 0:
                print(f"{program.stem:<10}  SKIP (llvm failed)")
                continue
            compile_result = run(["clang", ll_file, "-o", binary])
            if compile_result.returncode != 0:
                print(f"{program.stem:<10}  SKIP (clang failed)")
                continue

            interp_time, interp_out = median_time(
                [SILU, "interpret", program], args.runs
            )
            bin_time, bin_out = median_time([binary], args.runs)

            match = "ok" if interp_out == bin_out else "MISMATCH!"
            speedup = interp_time / bin_time if bin_time else float("inf")
            rows.append((program.stem, interp_time, bin_time, speedup, match))
            print(
                f"{program.stem:<10} {interp_time:>10.3f}s {bin_time:>8.4f}s "
                f"{speedup:>8.0f}x  {match}"
            )

        print("-" * 58)
        print(
            f"startup baseline: interpreter {interp_base:.3f}s, binary {bin_base:.4f}s"
        )
        geometric = statistics.geometric_mean(r[3] for r in rows) if rows else 0
        print(f"geometric mean speedup: {geometric:.0f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
