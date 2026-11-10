# Silu WASM 化计划：L0 在线编译 / L1 在线运行 / L2 浏览器真编译

写作时点：2026-11-10。前置评估见当次会话记录；本文是执行计划与验收标准。
所有新产物在 `wasm/` 目录，**不改任何现有编译器输出**（不触发双实现同步，
现有门禁保持全绿是每一步的前置）。

## 0. 一句话结论

siluc1 是 14 行 stdin→stdout 单体、运行时外部符号面只有 10 个 libc 函数、
IR 全程 i64 自洽——WASM 化的第一性风险不存在，剩下的是工程量。

## 1. 实证基础（2026-11-10 全部实测）

| 事实 | 证据 |
|---|---|
| siluc1 纯 stdio：`read_stdin()` → `print()` | `selfhost/siluc.si:10-13`（14 行） |
| ir_interp 纯 stdio（IR JSON 进，程序输出出） | `selfhost/ir_interp.si:4` |
| 运行时外部符号仅 malloc/calloc/free/printf/snprintf/strtod/memchr/strlen/memcmp/exit + llvm.* | fib.ll declare 段 |
| ptrtoint 仅 hash/null 判断，指针宽度无关 | fib.ll |
| IR 全 i64 尺寸/指针运算 | fib.ll（→ 用 **wasm64/memory64**，代码生成零改动） |
| brew llvm 自带 wasm32/wasm64 后端；Apple clang 没有 | `clang --print-targets` |
| Node 24.3.0（memory64 默认开）本机可用 | `node --version` |
| native siluc1 = 2.2MB；fib 全量 .ll = 385KB（含运行时） | 实测 |

**大小预期（回答"L0 应该没那么大吧"）**：siluc1.wasm 裸尺寸预计 2-4MB，
binaryen 优化后 ~1.5-2.5MB，brotli/gzip 传输 **<1MB**——比 Monaco 编辑器
本体还小。

## 2. 架构

```
浏览器（静态站，无后端）
├── siluc1.wasm        .si → .ll          （L0：在线看编译产物）
├── silu_fe.wasm       .si → IR JSON      （L1 管线前半）
├── ir_interp.wasm     IR JSON → 程序输出 （L1：在线跑程序，解释执行）
└── wasm_backend.wasm  IR JSON → WAT/wasm （L2：浏览器内真编译）
     └── + rt 模块（wasm-merge 合并运行时）→ 可下载的 .wasm
```

- 一次性原生构建（CI 或本地）：`./siluc1 < selfhost/X.si > X.ll` →
  `clang --target=wasm64-unknown-wasi --sysroot=<wasi-sysroot> -O2` → .wasm。
- 浏览器运行器：自写 stdio-only WASI shim（~200 行 JS），不引重量级依赖。
- L2 运行时复用：构建期把 rt.ll 编成独立 wasm 模块；浏览器内用
  **binaryen 的 wasm-merge**（官方有 wasm 构建）把用户模块与 rt 模块合并。

## 3. 里程碑与验收标准（每步：测试绿 → commit → 推 nightly）

### M0 探针（先证明链路，~半天）

1. 安装 wasi-sdk（brew；代理网络走 socks5）。
2. `wasm/build.py build-compiler`：`./siluc1 < selfhost/siluc.si` 取编译器
   自身 .ll → clang wasm64 → `wasm/artifacts/siluc1.wasm`。
3. `wasm/test_compile.mjs`（Node 24 + 内联 shim）：喂 benchmarks/fib.si，
   **wasm 编译器 stdout 与 native siluc1 stdout 逐字节一致**。
4. 记录实测尺寸（裸/gzip）。
- 验收：fib.si 字节一致 + siluc1.wasm 可重建。→ commit

### L0 在线编译（看 .ll）

1. `wasm/build.py` 转正：artifacts 重建脚本（编译器、后续全部 wasm 工件）。
2. `wasm/shim/wasi_shim.mjs`：stdio-only WASI（fd_read/fd_write/fd_close/
   proc_exit/args/environ/clock），单测。
3. `wasm/web/index.html`：编辑框 + Compile → 显示 .ll、耗时、尺寸。
4. `wasm/test_corpus.mjs`：**全语料对拍**——diff_harness 的 ir/ll 语料清单，
   每个 .si 的 wasm 编译输出 ≡ native 输出（字节一致）。
- 验收：语料 21+ 文件全一致 + 本地静态页手动 e2e。→ commit
- （部署到 silu.askender.xyz 属后续运维，代码同步走 silu-lang checkout，
  遵守"源码不进公开仓"拓扑。）

### L1 在线运行（解释执行）

1. 构建 `silu_fe.wasm`（先验证 `selfhost/silu_fe.si` main 是
   read_stdin→print(json)；它以 json_dumps 收尾，形态吻合）与
   `ir_interp.wasm`。
2. 浏览器管线：.si → silu_fe.wasm → IR JSON → ir_interp.wasm → 输出。
3. `wasm/test_interp.mjs`：语料程序 wasm 执行输出 ≡ native 执行输出
   ≡ CPython（参照 test_selfhost_m4::test_m5 的 CPython 对拍清单）；
   读 stdin 的程序（jsonparse）单列处理（WASI 多 fd 接线）。
4. web 页加"Run"标签页。
- 验收：语料执行输出三面对拍一致。→ commit

### L2 IR→WASM 后端（浏览器内真编译）

`selfhost/wasm_backend.si`：消费 IR JSON，产出 WAT；本地 wat2wasm
（wabt，brew 装；官方也有 wasm 版）→ .wasm。跑通后评估是否切直接二进制
发射（LEB128）摆脱 wabt。

子集推进（**每个子集一个 commit**，全部三面对拍）：
1. int/bool、算术/比较、if/while、print → fib.si 绿
2. float、位运算 → nbody 类
3. list/dict → 容器运行时（合并 rt 模块，wasm-merge 路线）
4. str 全语义（码点索引/切片）→ utf8_probe 绿
5. 视覆盖面决定：record/pyobj、strbuf、closure 族

- 验收：当前子集在语料中所有可编译文件上输出三面一致；不支持构造
  **bail 报错**（宁报 ERROR 不出错误字节——铁律同样适用 wasm 平面）。

## 4. 测试策略总则

- **字节级对拍优先**：L0/L1 的 wasm 产物与 native 产物同输入比字节，
  复用 diff_harness 语料清单，不新造期望值（教训：手写期望必被坑）。
- 浮点输出若因 musl/Apple libc 格式化差异不一致：先定位、把差异平台
  记录成显式已知差异清单，不静默放宽。
- 每个里程碑前跑一遍现有三门禁（ll/ir/pytest 全量）确认未伤主链。

## 5. 风险与规避

| 风险 | 规避 |
|---|---|
| wasi-libc(musl) 浮点格式化与 Apple libc 差异 | 语料对拍暴露 → 已知差异清单 |
| 12k 行自举输入 ~1GB wasm 内存 | playground 限输入大小；桌面浏览器 4GB 上限内 |
| memory64 浏览器兼容 | 2025 起三大浏览器默认启用；Node 24 本地全绿兜底 |
| wabt/binaryen 分发体积 | 仅 L2 需要；wabt wasm 版 ~2MB 级，后评估 |
| wasm-merge 合并后索引/重定位错误 | 以执行对拍兜底，不靠目测 |

## 6. 不做什么

- 不把 Python 侧（`silu` 主实现、prove/Z3）带进浏览器（z3.js 桥接另立项）。
- 不在公开仓（silu-lang）提交源码或二进制；部署物走其独立流程。
- 不动现有 .ll 渲染路径的一行代码。
