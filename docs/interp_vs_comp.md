# 解释器与编译器：silu 的执行平面全景

写作时点：2026-11-14（v1.19.0 之后，irvm 字节码平面落地）。
基准环境：Apple Silicon (arm64 macOS)，fib(28) 递归（~63 万次调用）。
所有数字含进程启动；"纯执行"已扣除。

## 一、执行平面清单

| 平面 | 形态 | 实现 | 角色 |
|---|---|---|---|
| AST 解释器 | 树遍历（Python） | silu/interpreter.py | 语义参照（最强兼容） |
| IR 解释器 native | 树遍历（Silu→native） | selfhost/ir_interp.si | 语义参照（int 子集） |
| IR 解释器 wasm | 树遍历（Silu→wasm） | selfhost/ir_interp.si | 同上（浏览器） |
| **字节码 VM** | **扁平字节码（Rust）** | **tools/irvm（本次新增）** | **快速交互执行** |
| **字节码 VM 孪生** | **扁平字节码（Silu）** | **selfhost/ir_vm.si（本次新增）** | **同上（双平面互证）** |
| native 编译器 | .si → .ll → 二进制 | siluc driver + clang | 性能部署 |
| wasm 编译器 | .si → WAT → .wasm | wasm_backend + wat2wasm | 浏览器真编译 |
| Rust 参照 conv | .si → .ll（对照实现） | reference/rust | 差分 oracle |

## 二、fib(28) 速度实测（数值：317811，全平面一致）

| 实现语言/形态 | 总耗时 | 纯执行 | 相对 native |
|---|---:|---:|---:|
| **C (gcc -O2)** | 3 ms | ~2 ms | 1× |
| Rust (rustc -O) | 4 ms | ~3 ms | 1.3× |
| **silu native 二进制** | **4 ms** | ~3 ms | **1.3×** |
| **silu 字节码 VM (Rust, fe|irvm)** | **50 ms** | ~45 ms | **12.5×** |
| Cython (cdef long) | 28 ms | ~25 ms | 9× |
| CPython 3.12 | 67 ms | ~60 ms | 22× |
| monty (Rust Python 沙箱) | 116 ms | ~88 ms | 39× |
| **silu 字节码 VM 孪生 (Silu→native)** | **110 ms** | ~105 ms | **30×** |
| silu IR 解释器 native -O2 | 1,760 ms | ~1,700 ms | 578× |
| silu IR 解释器 wasm (node) | 1,168 ms* | — | — |
| silu AST 解释器 | 15,256 ms | — | 5,085× |

\* wasm 含 Node 启动 ~40ms。

**编译时间**（.si → 产物）：Rust conv 7ms；siluc1 native 56ms；fe+backend
wasm 65ms；siluc1 wasm 151ms；Python 平面 conv 185ms；driver 全链
（含 clang -O0 链接）488ms；clang -O2 .ll→二进制 387ms（-O0 仅 79ms）。

## 三、为什么差这么多（每个数量级一个原因）

1. **AST 解释器 ~65×慢于 CPython**：树遍历（每节点虚分派+dict 环境），
   且宿主是 CPython（解释器自身也被解释）。这是自举启动器/最强兼容
   参照的代价，不是产品路径。
2. **IR 解释器 ~35×慢于字节码 VM**：JSON→树→遍历，宿主是编译后的
   机器码（native -O2）——单步分派快，但树遍历重复下降 + dict 查找
   是结构性开销；字节码 VM 把它们换成了线性指令流 + 数组下标。
3. **字节码 VM 首版比 monty 慢 7×，两处修复后反超（fib28 0.775s →
   0.05s，15.5×）**：
   - **每条指令查一次 `std::env::var("IRVM_TRACE")`**（调试残留）——
     环境变量查找是 µs 级全表扫描，63 万次分派被它拖垮。提出循环后
     单独这一项占了大头。教训：**VM 循环内禁止任何系统调用形状的
     查询，哪怕"只是读个开关"**。
   - **每帧 `vec![0i64; nslots]` 堆分配**——63 万次调用 = 63 万次
     malloc/free。改成共享 flat 槽区（append 零槽 + 帧记 sbase，与
     Silu 孪生的 SLOTAREA 同构）后消掉。
4. **Silu 孪生（Silu 写的 VM 再编译）比 Rust 手写 VM 慢 ~2×**：每条
   字节码仍是 Silu 函数调用链（vstack_push/eq01...），边界检查与
   调用开销是自举的代价。但**"被编译语言写的解释器"跑赢了 monty**
   （手写 Rust Python 沙箱）——说明 VM 的模型（扁平字节码+flat 槽区）
   比宿主语言的手写优化更关键。
5. **native 二进制与 C/Rust 同级**：LLVM 后端的代码质量对纯算术
   递归已达机器码水平（1.3× 于 gcc -O2）。

## 四、为什么字节码与 monty 不是逐字节一致（以及什么是一致）

monty 编译 Python 源码到它自己的字节码（CPython 风格操作码
+ monty 扩展）；silu-irvm 编译 **silu IR** 到 **silu 自己的字节码**。
源语言不同 → 逐字节一致在原理上不可达。真正可达且已实现的
"一致"有两层：

1. **设计规范一致**（本次采纳）：u8 操作码判别 + W/K 操作数后缀、
   常量池、具名槽位帧、跳转控制流、标签回填——monty 的
   bytecode/op.rs + code.rs + vm 结构。
2. **跨平面字节一致**（本次达成并门禁化）：同一份 silu IR →
   Rust 平面与 Silu 平面产生**逐字节相同**的字节流
   （`tools/irvm/bytecode_diff.sh`，9 探针全绿；执行差分
   `tools/irvm/test.sh` 同 9 探针对拍 ir_interp）。

## 五、评测集：编译+运行 vs 解释，谁快

评测集 `tools/irvm/eval.py`（2026-11-14 实测，四次运行取最优，
均含进程启动与前端/编译时间）：

| workload | native 编译+运行 | 字节码 VM 编译+运行 | ir_interp 解释 | CPython | 裁决 |
|---|---:|---:|---:|---:|---|
| fib(28) | 506ms（build 502 + run 4） | 59ms（rust）/ 122ms（孪生） | 1,767ms | 59ms | **编译快**（VM 路径 30×；native 路径 3.5×） |
| 循环密集 1M 次迭代 | 497ms（build 494 + run 3） | 81ms / 160ms | 2,364ms | 149ms | **编译快**（VM 路径 29×） |
| 短脚本（3 行 print） | 516ms | 6ms | 6ms | 26ms | **解释快**（native 被 build 拖垮；VM 与解释打平） |
| fib(12)（毫秒级算完） | 529ms | 6ms | 7ms | 26ms | native：解释快；VM：打平 |

**规律**：
- **native 编译的固定开销 ~500ms**（siluc driver 全链含 clang 链接）
  只有程序实际计算 >10ms 量级才能摊销；毫秒级脚本永远"解释快"。
- **字节码 VM 路径的"编译"只是 silu_fe 前端（~7ms）**——它没有
  clang 环节，6ms 就能编译+跑完短脚本，与树遍历解释器打平；
  计算一重（fib28/loops），VM 路径立即以 ~30× 甩开解释器。
- 解释器的不可替代场景：单次极短脚本、REPL、无工具链环境、
  自举启动器、**可执行的语义规约**（差分门禁的 ground truth——
  编译器 bug 修复的判据"解释器输出对"不可替代）。

## 六、monty 的启示（差距是如何关闭的）

monty（Rust Python 沙箱）fib(28) 纯执行 ~88ms。silu 字节码 VM 首版
~700ms（8 倍慢），两处修复后 Rust 平面 ~45ms、Silu 孪生 ~105ms——
**双双反超 monty**。差距的真正来源不是"手写 Rust vs 生成代码"，
而是两个工程 bug：

1. **每指令一次 env 查询**（调试残留）：`std::env::var` 是 environ
   线性扫描，63 万次分派被它拖垮——单项占了大半。提出循环即消。
2. **每帧一次堆分配**：`vec![0i64; nslots]` 在 63 万次 CALL 上 =
   63 万次 malloc/free。换 flat 槽区（帧记 sbase）即消。

（若还要继续压）：操作数解码内联进分派臂、hot loop 局部变量缓存
到临时、Silu 孪生的辅助函数（vstack_push/eq01）内联化——预计还能
拿 1.5-2×，但相对收益已小。

**结论**：VM 快慢的第一序因素是**每条指令的常数开销**（有无隐藏
的系统调用/分配），第二序才是宿主语言。模型选对（扁平字节码 +
帧槽）后，"被编译语言写的解释器"也能跑赢产品级手写沙箱。
