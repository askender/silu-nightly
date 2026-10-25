# Silu 性能评测结果（2026-10-25）

由 `python benchmarks/run_benchmarks.py --report` 生成。
Apple Silicon，CPython / Rust release / clang -O2，多轮中位数（含进程启动）。

几何平均：**400x vs silu-int，12.3x vs CPython，0.9x vs Rust**

| 程序 | silu 解释器 | CPython | silu 二进制 | Rust | vs 解释器 | vs CPython | vs Rust | 输出 |
|---|---|---|---|---|---|---|---|---|
| arith | 5.896s | 0.086s | 0.0030s | 0.0036s | 1939x | 28.4x | 1.2x | ok |
| dict | 0.273s | 0.035s | 0.0030s | 0.0045s | 92x | 11.6x | 1.5x | ok |
| fannkuch | 0.054s | 0.033s | 0.0028s | 0.0028s | 19x | 11.7x | 1.0x | ok |
| fib | 1.818s | 0.036s | 0.0034s | 0.0035s | 541x | 10.7x | 1.0x | ok |
| float | 3.805s | 0.053s | 0.0032s | 0.0034s | 1196x | 16.6x | 1.1x | ok |
| jsonparse | 1.768s | 0.049s | 0.0144s | 0.0048s | 123x | 3.4x | 0.3x | ok |
| knucleotide | 15.913s | 0.820s | 0.0188s | 0.0216s | 845x | 43.6x | 1.1x | ok |
| list | 0.484s | 0.036s | 0.0039s | 0.0055s | 125x | 9.3x | 1.4x | ok |
| mandelbrot | 1.278s | 0.040s | 0.0077s | 0.0048s | 166x | 5.2x | 0.6x | ok |
| nbody | 61.273s | 0.213s | 0.0088s | 0.0078s | 6989x | 24.4x | 0.9x | ok |
| spectral | 74.291s | 0.294s | 0.0075s | 0.0060s | 9937x | 39.3x | 0.8x | ok |
| string | 0.586s | 0.054s | 0.0053s | 0.0038s | 111x | 10.3x | 0.7x | ok |
| trees | 0.921s | 0.035s | 0.0032s | 0.0044s | 286x | 10.8x | 1.4x | ok |
| wordcount | 6.757s | 0.089s | 0.0268s | 0.0218s | 252x | 3.3x | 0.8x | ok |

方法学与归因实验见 [README.md](README.md)。
