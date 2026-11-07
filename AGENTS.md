# AGENTS.md

给 AI 代理与本仓库协作者的工作指南。**本文件是代理上下文的唯一权威
入口**（CLAUDE.md 仅指向本文件）；写作时点：2026-11-07。

## 项目是什么

**Silu**：Python 语法子集的**自举编译型语言**。类型注解驱动非装箱
机器表示（int/float/bool、list[int]、dict[str,int]、Rust-String 风格
的 owned str），保守推断让可证明安全的未注解代码获得同等处理；
`silu prove` 用 Z3 做除零/越界/缺键证明。参考解释器与符号执行器
并存。生成 LLVM IR 后由系统 clang 出本机码。

编译链（自举）：

```
.si → silu_fe（前端，Silu 自实现）→ IR JSON → typed_codegen（转换器）→ .ll → clang
```

## 仓库地图

| 路径 | 内容 |
|---|---|
| `silu/` | Python 主实现：cli/解释器/IR 生成/ir→LLVM（llvmlite）/符号执行/hoist/runtime cache |
| `selfhost/` | 用 Silu 写的编译器自身：`silu_fe.si`（前端 2,183 行）、`typed_codegen_flat.si`（转换器压平源 11,977 行）、`ir_interp.si`（IR 树解释器）等 |
| `benchmarks/` | 15 个基准 + parity 语料（含 jsonparse 双版本） |
| `reference/` | **第二实现（差分 Oracle）与其文档**——见下节，代理最常需要的都在这 |
| `docs/` | 语言/CLI/基准报告等用户文档 |
| `siluc1`, `silu_fe` | 仓库根的参考平面可执行文件（Python 平面） |
| `CLAUDE.md` | 已过时，仅指向本文件 |

## reference/：第二实现（差分 Oracle）——当前工作重心

**是什么**：`reference/rust/` 下的独立 Rust 实现（前端 `src/main.rs`
2,509 行 + 转换器 `src/bin/silu-conv.rs` ~7,950 行），钉住
**silu 1.17.0（P6 重钉；原神谕 1.16.2 / 87df40f）** 的行为。用途：
差分 Oracle、表达力校准、隐式规约提取。**不是产品编译器，不进自举链，
不做同步镜像**。

**状态（2026-11-07）：已完成**——前端 IR **19/19**、完整 .ll **18/18**
全语料逐字节一致。规模对照、参考特性分诊、语言设计建议见校准报告。

**关键文档（都在 reference/）**：

| 文档 | 内容 |
|---|---|
| `PROGRESS.md` | **状态锚点**：槽位/所有权/槽号等 38+ 项隐式规约（全部 diff 实证），逐文件迭代记录 |
| `CALIBRATION.md` | R3 校准报告：规模对照（转换器 −34%）、参考实现浪费点与脆弱形状分诊 |
| `PROPOSALS.md` | 六条语言/实现改进提案（P1 字符串统一、P2 interning、P3 迭代器归一、P4 声明赋值同形、P5 布尔单例、P6 内容寻址命名）——**已评估（2026-11-07，结论见文档头部）：采纳 P6+P2→P5→P3b，缓议 P4/P1；实施待用户确认，未经用户决策不得动手** |
| `DYNAMIC_SHAPES.md` | 动态层（pyobj/Json）形状蓝图 |
| `README.md` | Oracle 契约（钉住版本、语料、非目标） |

**常用命令**：

```bash
export PATH="$HOME/.cargo/bin:$PATH"        # cargo 常不在默认 PATH
cd reference/rust && cargo build            # 产出 target/debug/{silu-fe,silu-conv}
cd <仓库根>                                  # 以下命令都必须在仓库根执行
python3 reference/diff_harness.py ir fe rustfe    # 前端 IR 平面，应 19/19
python3 reference/diff_harness.py ll conv rustconv # 完整 .ll 平面，应 18/18
./siluc1 < benchmarks/fib.si > /tmp/ref.ll                  # Python 平面参考输出
reference/rust/target/debug/silu-conv benchmarks/fib.si > /tmp/rust.ll
cmp /tmp/ref.ll /tmp/rust.ll                # 前缀恒定，可整文件比
./target/debug/silu-fe selfhost/silu_fe.si  # 单独跑 Rust 前端（相对路径）
```

注意：`silu-conv` 通过子进程调同目录 `silu-fe`；`.si` 路径按当前工作
目录解析，**一律从仓库根运行**。

## 硬约束（违反即事故）

1. **Git 拓扑**：源码提交/标签只推 `nightly`（远端名）的 `main`；
   `askender/silu-lang` 是公开展示仓，**不与主线 merge/rebase**；
   旧远端 `askender/silu` 已暂停——**不推送、不删除**。
2. **里程碑纪律**：每达成一个 byte-identical 里程碑**立即提交推送**
   （历史上发生过 checkout 回退未提交工作树的事故，全部靠重放恢复）。
3. **宁报 ERROR 不出错误字节**：Rust 参照遇到未支持构造一律
   `bail()` → exit 3；harness 报 ERROR 属预期（如曾长期保留
   silu_fe 的 import 未实现），绝不输出可能错误的近似字节。
4. **输出变化的提案必须双实现同 commit**：改 Python 参考必须同步
   改 Rust 参照并保持门禁全绿，随后重钉版本。`reference/PROPOSALS.md`
   的六条提案在用户决策前**不得动手**。
5. **差分先行**：改转换器/前端前先 `siluc1 < X.si > ref.ll` 留参考；
   所有行为论断要有 diff hunk 背书，不靠读源码猜。

## 隐式规约速查（详表见 reference/PROGRESS.md）

调第二实现最容易踩的同类坑（全部差分实证）：

- **槽位记账**：每条指令（含 void）消耗一个匿名槽，void 只是不打印；
  新 RAWSTR 局部声明多耗一个 null-store silent；函数序言 2N+1；
  容器参数 store 在拼接区但仍耗槽。
- **rawstr 所有权**：别名赋值必须 copy（rawstr 可变，append 原地改）；
  字段读 copy、写时 copy+free old；静态自由函数同类型实参不 copy，
  方法实参 copy。
- **全局槽号**：~~字符串名 = `str_{len(module.globals)}`~~ **已退役
  （1.17.0/P6）**：字符串全局按内容寻址命名 `str.<转义>`，重复内容
  `~N` 后缀；STR_BASE/TAGGED_SLOTS/函数方法捕获计数全部作废（详见
  PROGRESS.md"P6 落地"节）。
- **短路链**：i1 链与 pyobj 链形态不同（后者直接存原对象）；
  object 返回函数的 and/or 不 create_bool 直接 ret。
- **迭代器五族**（range/riter/object/dict/str）块名、创建顺序、
  null store 位置各不相同。

## 已知坑

- `cargo` 不在默认 PATH（见上 export）。
- 仓库根有不少历史遗留实验文件（`.attic/`、`aok*/`、`c_for*` 等），
  与当前链路无关，不要试图"清理"它们。
- CLAUDE.md 描述的是早期纯解释器时代，已过时；以本文件为准。
- Python 平面跑 `.ll` 全量对拍较慢（typed_codegen_flat 需分钟级），
  IR 平面与 Rust 平面都是毫秒级。
