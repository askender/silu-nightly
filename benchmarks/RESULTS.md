# Silu 性能评测结果（2026-10-14）

由 `python benchmarks/run_benchmarks.py --report` 生成。
Apple Silicon，CPython / Rust release / clang -O2，多轮中位数（含进程启动）。

几何平均：**410x vs silu-int，10.7x vs CPython，0.9x vs Rust**

| 程序 | silu 解释器 | CPython | silu 二进制 | Rust | vs 解释器 | vs CPython | vs Rust | 输出 |
|---|---|---|---|---|---|---|---|---|
| arith | 5.236s | 0.073s | 0.0036s | 0.0033s | 1438x | 20.0x | 0.9x | ok |
| dict | 0.345s | 0.029s | 0.0029s | 0.0044s | 120x | 10.3x | 1.5x | ok |
| fannkuch | 0.150s | 0.027s | 0.0052s | 0.0044s | 29x | 5.2x | 0.8x | ok |
| fib | 1.743s | 0.031s | 0.0038s | 0.0035s | 464x | 8.3x | 0.9x | ok |
| float | 3.372s | 0.049s | 0.0034s | 0.0042s | 984x | 14.2x | 1.2x | ok |
| jsonparse | 1.660s | 0.038s | 0.0783s | 0.0065s | 21x | 0.5x | 0.1x | ok |
| knucleotide | 14.225s | 0.780s | 0.0144s | 0.0228s | 986x | 54.1x | 1.6x | ok |
| list | 0.526s | 0.031s | 0.0030s | 0.0045s | 178x | 10.6x | 1.5x | ok |
| mandelbrot | 1.191s | 0.035s | 0.0032s | 0.0040s | 367x | 10.8x | 1.2x | ok |
| nbody | 54.763s | 0.210s | 0.0081s | 0.0082s | 6756x | 25.9x | 1.0x | ok |
| spectral | 64.307s | 0.292s | 0.0047s | 0.0047s | 13670x | 62.1x | 1.0x | ok |
| string | 0.615s | 0.048s | 0.0045s | 0.0031s | 136x | 10.7x | 0.7x | ok |
| trees | 0.918s | 0.029s | 0.0027s | 0.0031s | 345x | 10.9x | 1.2x | ok |
| wordcount | 6.285s | 0.085s | 0.0222s | 0.0151s | 283x | 3.8x | 0.7x | ok |

方法学与归因实验见 [README.md](README.md)。
