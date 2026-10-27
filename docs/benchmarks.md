# Speed Benchmarks: Silu vs CPython vs Rust（2026-10-25, v1.9.0）

> 数据由 `python benchmarks/run_benchmarks.py --report` 生成
> （每程序 3 轮取中位数，含进程启动；Apple Silicon；CPython 3.13
> / Rust 1.89 release / clang -O2）。方法学与各程序归因见
> [benchmarks/README.md](../benchmarks/README.md)。复现：
> `python benchmarks/run_benchmarks.py --report`。

## 一、运行速度：14 程序 × 4 平方

| 程序 | 工作负载 | Silu 解释器 | CPython | **Silu 原生** | Rust | 原生 vs Rust |
|---|---|---|---|---|---|---|
| arith | 300k 循环 mod/floordiv | 5.821s | 0.090s | 0.0043s | 0.0045s | **1.0×** |
| dict | 20k 写+查 `dict[int,int]` | 0.283s | 0.036s | 0.0034s | 0.0036s | **1.0×** |
| fannkuch | n=10 排列 | 0.057s | 0.034s | 0.0032s | 0.0032s | **1.0×** |
| fib | fib(24) 递归 | 1.842s | 0.036s | 0.0055s | 0.0045s | 0.8× |
| float | 200k 浮点运算 | 3.794s | 0.055s | 0.0061s | 0.0057s | 0.9× |
| jsonparse | 87KB JSON 解析 | 1.781s | 0.050s | 0.0107s | 0.0047s | 0.4× |
| knucleotide | DNA k-mer 计数 | 15.852s | 0.832s | 0.0114s | 0.0163s | **1.4×** |
| list | 30k append+遍历 | 0.491s | 0.036s | 0.0031s | 0.0036s | **1.2×** |
| mandelbrot | 80×24 ASCII | 1.283s | 0.045s | 0.0038s | 0.0032s | 0.9× |
| nbody | 50k 步 5 体 | 63.042s | 0.215s | 0.0060s | 0.0064s | **1.1×** |
| spectral | n=300 范数 | 77.151s | 0.299s | 0.0045s | 0.0049s | **1.1×** |
| string | 48k 字符串拼接 | 0.580s | 0.053s | 0.0028s | 0.0031s | **1.1×** |
| trees | 深度 4-14 二叉树 | 0.939s | 0.033s | 0.0030s | 0.0031s | **1.0×** |
| wordcount | 单词计数 | 7.143s | 0.091s | 0.0268s | 0.0155s | 0.6× |

**几何平均：0.9× vs Rust（整体领先）｜14.1× vs CPython｜457× vs
解释器**；进程启动基线 4.3ms。8 个程序打平或反超（knucleotide
领先 1.4× 为最大）；两块已归因的短板见文末。

## 二、编译速度：siluc vs rustc vs clang

| 编译器 | fib（s/程序） | 说明 |
|---|---|---|
| **siluc（C 驱动 + siluc1）** | **0.136s** | 一行命令、零 Python；运行时 .o 缓存 |
| rustc -C opt-level=3 | 0.128s | 直调无缓存（三连编译恒定 + 磁盘零残留，实证） |
| Python 管线（selfhost_build） | 0.178s | 编排是 Python，编译器本体仍是 siluc1 |
| Python 编译器（silu build） | 0.497s | 全 Python 实现，开发/调试用 |
| clang -O2（C 孪生） | 0.06s | 参照 |

siluc 与 rustc 差距 1.06×，剩余部分全在 clang 用户段+链接本体
（管线 ~0.12s 是 clang 地板价）。cargo 的缓存是工件级（冷
0.274s / 热 0.050s），与我们的 .o 缓存同类但粒度更粗。

## 三、速度演进轨迹（做对了什么）

| 日期 | 里程碑 | jsonparse | 全套几何 vs Rust |
|---|---|---|---|
| 10-14 | 基线（v1.0 前） | 78ms（0.06×） | 0.9×（Rust 略胜） |
| 10-24 | print 特化：静态标量/字符串免 pyobj 盒 | — | — |
| 10-25 | dead_strip 链接（体积 3×↓） | — | — |
| 10-25 | match 类模式窄化：`case JInt(n)` 载荷静态绑定 | 78→75ms | — |
| 10-25 | **str 传参借用**：修复每层递归深拷整个文档 | **78.7→8.3ms（9.5×）** | — |
| 10-25 | 刷新报告（含全部修复） | 10.7ms（0.4×） | **0.9×（反超）** |

两个已归因的剩余短板（按需再战）：

- **jsonparse 0.4×**：变体树的 pyobj 容器构造——根治需 sum-type
  数据模型（RFC `docs/rfc_sum_types.md`，3-4 周级）。arena 分配器已实测否定
  （malloc 仅占 ~2%，瓶颈在 pyobj 派发常数）。
- **wordcount 0.6×（10-27 复测）**：v1.11.3 的下标类型推断消除了
  `w = vocab[i]` 的 pyobj 装箱（`.ll` 调用序列验证），但暴露了更深
  一层：`rawlist_str_get` 是**拷贝语义**（slots own copies），每次
  读取 malloc 新块 + free 旧槽，两次堆操作反而贵过单次装箱。
  A/B 实测（旧 `.ll` 21.2ms vs 新 24.3ms，各 15 次取最小值）。
  根治 = 借用读（不可变元素下标返回借用指针）或缓冲复用
  （`rawstr_copy_into`，Rust `clone_from` 思路）——即 RFC 的 S4
  所有权议题；int/dict 场景的推断收益已落地（消除装箱纯赢）。

## 四、方法学要点

- **四平面先验证后计时**：每个程序先确认解释器/CPython/编译
  产物/Rust 孪生四方输出一致，否则该行标记 MISMATCH 不计。
- CPython 平面经 pycompat 垫片（Silu 类的位置构造器与裸
  CPython 语义不同）；Rust 孪生逐程序手工镜像并比对输出。
- 编译计时中位数 3 次；启动基线单独扣除参照（4.3ms silu /
  2.3ms rust 空程序）。
- 逐项归因采用 ablation + macOS `sample` 采样（示例：jsonparse
  的 70ms 热区被采样锁定为传参深拷贝，修复后 8.3ms）。
