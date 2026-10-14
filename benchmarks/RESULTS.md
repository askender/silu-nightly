# Silu 性能评测结果（2026-10-14）

由 `python benchmarks/run_benchmarks.py --report` 生成。
Apple Silicon，CPython / Rust release / clang -O2，多轮中位数（含进程启动）。

几何平均：**331x vs silu-int，8.5x vs CPython，0.7x vs Rust**

| 程序 | silu 解释器 | CPython | silu 二进制 | Rust | vs 解释器 | vs CPython | vs Rust | 输出 |
|---|---|---|---|---|---|---|---|---|
| arith | 5.178s | 0.074s | 0.0060s | 0.0047s | 868x | 12.5x | 0.8x | ok |
| dict | 0.365s | 0.029s | 0.0057s | 0.0035s | 64x | 5.0x | 0.6x | ok |
| fannkuch | 0.147s | 0.027s | 0.0088s | 0.0051s | 17x | 3.1x | 0.6x | ok |
| fib | 1.752s | 0.032s | 0.0029s | 0.0029s | 599x | 11.1x | 1.0x | ok |
| float | 3.409s | 0.047s | 0.0033s | 0.0036s | 1020x | 14.1x | 1.1x | ok |
| jsonparse | 1.674s | 0.037s | 0.0762s | 0.0082s | 22x | 0.5x | 0.1x | ok |
| knucleotide | 14.083s | 0.790s | 0.0159s | 0.0183s | 884x | 49.6x | 1.1x | ok |
| list | 0.522s | 0.031s | 0.0032s | 0.0039s | 164x | 9.8x | 1.2x | ok |
| mandelbrot | 1.173s | 0.035s | 0.0032s | 0.0039s | 368x | 11.0x | 1.2x | ok |
| nbody | 54.580s | 0.207s | 0.0067s | 0.0075s | 8172x | 30.9x | 1.1x | ok |
| spectral | 64.378s | 0.289s | 0.0085s | 0.0093s | 7553x | 33.9x | 1.1x | ok |
| string | 0.660s | 0.048s | 0.0058s | 0.0033s | 114x | 8.4x | 0.6x | ok |
| trees | 0.904s | 0.029s | 0.0053s | 0.0035s | 171x | 5.5x | 0.7x | ok |
| wordcount | 6.759s | 0.083s | 0.0290s | 0.0158s | 233x | 2.9x | 0.5x | ok |

方法学与归因实验见 [README.md](README.md)。
