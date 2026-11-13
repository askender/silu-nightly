# AGENTS.md

给 AI 代理与本仓库协作者的工作指南。**本文件是代理上下文的唯一权威
入口**（CLAUDE.md 仅指向本文件）；写作时点：2026-11-07（最近更新 2026-11-09 晚）。

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
**silu 1.18.1（cp-offset 缓存重钉；1.18.0=strbuf，1.17.0=P6/P2/P5，原神谕 1.16.2）** 的行为。用途：
差分 Oracle、表达力校准、隐式规约提取。**不是产品编译器，不进自举链，
不做同步镜像**。

**状态（2026-11-07）：已完成**——前端 IR **21/21**、完整 .ll **20/20**（含 utf8_probe）
全语料逐字节一致。规模对照、参考特性分诊、语言设计建议见校准报告。

**关键文档（都在 reference/）**：

| 文档 | 内容 |
|---|---|
| `PROGRESS.md` | **状态锚点**：槽位/所有权/槽号等 38+ 项隐式规约（全部 diff 实证），逐文件迭代记录 |
| `CALIBRATION.md` | R3 校准报告：规模对照（转换器 −34%）、参考实现浪费点与脆弱形状分诊 |
| `PROPOSALS.md` | 六条提案——**P6+P2+P5 已落地（1.17.0）；P1→1b-lite 已实施（1.18.0 strbuf，RFC docs/strbuf_rfc.md，Oracle 全同步 ll 19/19）；P3b/P4 维持缓议**（见文档头部"实施后进展"） |
| `DYNAMIC_SHAPES.md` | 动态层（pyobj/Json）形状蓝图 |
| `P1_STRING_RESEARCH.md` | P1 前置研究：窄窗实证（字段/跨函数 1000×）、470× strbuf 基准、自举源码普查（无窄窗外热循环） |
| `README.md` | Oracle 契约（钉住版本、语料、非目标） |
| `STATUS.md` | **会话交接锚点**：当前状态、TODO、环境关键、教训（compact/换客户端后先读这个） |

**常用命令**：

```bash
export PATH="$HOME/.cargo/bin:$PATH"        # cargo 常不在默认 PATH
cd reference/rust && cargo build            # 产出 target/debug/{silu-fe,silu-conv}
cd <仓库根>                                  # 以下命令都必须在仓库根执行
$PY312 reference/diff_harness.py ir fe rustfe    # 前端 IR 平面，应 21/21
$PY312 reference/diff_harness.py ll conv rustconv # 完整 .ll 平面，应 20/20
./siluc1 < benchmarks/fib.si > /tmp/ref.ll                  # Python 平面参考输出
reference/rust/target/debug/silu-conv benchmarks/fib.si > /tmp/rust.ll
cmp /tmp/ref.ll /tmp/rust.ll                # 前缀恒定，可整文件比
./target/debug/silu-fe selfhost/silu_fe.si  # 单独跑 Rust 前端（相对路径）
```

注意：`silu-conv` 通过子进程调同目录 `silu-fe`；`.si` 路径按当前工作
目录解析，**一律从仓库根运行**。命令里的 `python3` 一律指
`/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3`（裸
homebrew python3 无 llvmlite，CLI 会静默隐藏 build/llvm/verify 子命令）。

## 当前状态锚点（2026-11-14 深夜）

- **v1.18.1 已公开发布**；发布链根因（GitHub 退役 macos-14 池）已修复
  入档。**tag push 用 tag 所在 commit 的 workflow 文件**，改 CI 后 tag 必须前移。
- 门禁全绿：ll 20/20、ir 21/21、pytest **1361 通过/3 跳过**。
- **L2 语料验收达成（HEAD 66fdfa7 后续，2026-11-14）**：wasm 后端跑通
  **全部非动态层语料**——13/15 benchmark 逐字节对拍 CPython（arith/
  dict/fannkuch/fib/float/list/mandelbrot/nbody/spectral/string/trees/
  wordcount@300000/knucleotide@小 n），jsonparse ×2 = pyobj 类子集外
  （响亮 unreachable）。**新增子集能力**：模块级全局变量（global.get/
  set，CTX list 标记——bool flag 会被自己的作用域规则吃掉）、int 键
  dict（dsi 族）、list[float]（lf 位打包）、非空字面量/list×int、
  dict.get/input()/bool repr/负下标。**经典 bug**：find 满表剪断返回
  陈旧 ei 被当命中（wordcount 误计 4 根因）——剪断必须显式归零。
- **str ABI v2（HEAD 92a7eb1 后续，2026-11-14，TODO #2 关闭）**：
  16 字节前缀 [blen][clen]（指针指向字节区，O(1) len）+ 值语义绑定
  （$s_copy：assign/global/实参/dict 键值/for 变量）+ 窄窗 `x = x + e`/
  `x += e` 原地扩展（$str_extend：堆顶+堆基双守卫）+ ASCII 快路。
  **knucleotide@200000 从 O(n²) 超时+内存耗尽降到 40ms**。连带修复：
  **`s += e` 曾是静默指针算术**（铁律违反）、slice4 按源串长度分配
  （二次方堆耗的真根因）、top_type name 臂、`in` 类型标记、print_dsf
  scratch。**语料门禁入仓** `wasm/test_corpus.mjs`（全尺寸对拍+计时），
  test_backend 加 `.stdin` sidecar 管道。ir_interp 对 str 重程序会
  崩/挂（非回归，int-only 边界无声响化）——响亮化列为后续小项。
- **记录类子集 + jsonparse 解锁（HEAD dd90cad 后续，2026-11-14，
  TODO #4 前半）**：扁平记录类（构造器 [tag][字段槽]、str 字段记录
  持有）+ match 窄化（tag 链 + 按类静态类型抽字段）+ 不透明 i64 槽
  透传动态容器（记录单态化，无 pyobj 装箱）。**jsonparse 全尺寸 9ms
  逐字节一致**（参照平面 = silu interpret——CPython 无自动记录构造
  语义）。连带修复：**n 元 and/or 静默丢第三操作数（P0 级既有 bug，
  FE 扁平操作数列表；and_or_nary.si 门禁）**、ann_type 裸 list/dict
  臂（`o: dict` 曾当 list 下标）、ls（list[str]）、read_line 4K 上限
  静默截断 → 可增长、to_s 动态串（str_from_int 曾把指针打成十进制
  数字）、脏形参拷贝消除（FDIRTY 传递闭包；84KB 文档 750MB 拷贝 →
  线性）、pass 顺序（全局推断须在函数注册后）、**`case` 不能做变量名
  （自举 FE 关键字，Python FE 宽容——两前端分歧）**。backend 门禁
  15→**17**（record_sem.si + and_or_nary.si）。详见 STATUS.md
  §3.12-3.14。
- **Json 装箱层——语料 15/15 封顶（HEAD c8411cd 后续，2026-11-14，
  TODO #4 完成）**：$jbox 16B {tag,payload} 块（tag 表 0=null 1=int
  2=float 3=bool 4=str 5=list 6=dict，与 interpreter.py 逐位对齐）+
  json_tag/int/bool/str/list/dict/float/free builtins（json_free =
  bump 分配的文档化 no-op）+ 类型标记 "J"（块指针引用语义）+ 返回
  隐式装箱（按静态类型分发；嵌套 Json 调用直通不二次装箱）。
  **jsonparse_json 8ms 逐字节一致（一发全中）——语料 15/15 全部
  逐字节，L2 语料完整达成**（13 对拍 CPython + jsonparse ×2 对拍
  silu interpret）。详见 STATUS.md §3.15。
- **WASM 化（`wasm/`，计划见 `docs/wasm_plan.md`）**：M0-L2 全部完成 +
  **审查修复轮（2026-11-13/14，HEAD d9b0551 后续）**：
  - shim 层（host.mjs）：cStrtod 符号群修复（-inf/-nan/负 hex/p 指数
    四处）、hexFloat fraction 顶端对齐、cReprDouble 调整指数、%e/%g
    精确展开半偶舍入（expExact）、calloc/free 加固、fmt_double 补 NUL。
    shim 门禁 148→**252**（对拍真 C 库 bit-exact）。
  - wasm_backend：and/or/not 短路、break/continue、未注解 str/list/dict
    类型传播、浮点比较/floordiv/floormod 臂、$str_from_int 堆下溢、
    print_ds 冒号空格、collect_locals 失同步、下标 aug_assign（l[i]+=）、
    **dict 值类型**（dsf=float 位打包/dss=str 指针 + per-type repr）；
    静默 gap 全面响亮化（unreachable）。门禁 **10/10** 对拍 CPython。
  - ir_interp：and/or/not + break/continue 补全。run 门禁 2/2→**3/3**。
  - **语言 bug 误报澄清**：嵌套同函数调用四平面（CPython/参考解释器/
    原生/wasm 后端）探针全部正确——代理报告的"错求值"实为 aug 下标
    目标缺口，已实现。
  - 门禁示例扩到 **13** 个（bool_ops/float_ops/aug_sub/dicts_f/
    globals/edge 新增）。
- **教训（11-13/14）**：①"门禁绿"的覆盖面极窄——示例集外的真实程序
  曾有整类静默缺分派（and/break/浮点比较），审查代理先实证再报告才可信；
  ②/tmp 下的 native 二进制（ir_interp_native 等）是 existsSync 缓存，
  改 selfhost 源后必须删除强制重建（教训②的第三种形态）；③代理审查
  报告的"语言级 bug"必须四平面探针复核后才动手——本次为误报。
- 其余 TODO 见 **`reference/STATUS.md`——换客户端后的第一站**。

## 环境关键（换客户端/新会话必读，2026-11-09 实证）

1. **$PY312 = `/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3`**
   ——pytest、diff_harness、selfhost_build、`-m silu build` 全用它。
2. `cargo` 不在默认 PATH：`export PATH="$HOME/.cargo/bin:$PATH"`。
3. siluc 驱动的运行时缓存 `~/.cache/silu-runtime/driver/`（带内容校验 +
   clang 身份戳；conda LLVM 与 Apple clang 的 LTO 位码互不兼容，缓存失配
   自动重建；怀疑异常可整目录删）。
4. pytest 全量失败**先定向重跑再下结论**：定向重跑全绿的多为二进制
   重建竞态；但**定向重跑仍红的才是真回归**（当前工作树就有 1 个：
   见最上方"当前状态锚点"）。
5. SSH 推送降级路径（代理 7897 未开时）：
   `GIT_SSH_COMMAND="ssh -i $HOME/.ssh/lb_ali_18 -o IdentitiesOnly=yes" git push ssh://git@ssh.github.com:443/askender/silu-nightly.git main`
6. **换客户端后的第一站**：`reference/STATUS.md`（当前状态、TODO、
   环境关键、本会话教训——包括"手写期望值必须用真 CPython 生成"、
   "Oracle 新 arm 位置敏感"、"改运行时复杂度要同步审视 .ll 渲染器孪生"）。

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
  （1.17.0/P6+P2）**：字符串全局按内容寻址命名 `str.<转义>` 且
  interning（同内容仅一份定义）；STR_BASE/TAGGED_SLOTS/函数方法捕获
  计数全部作废（详见 PROGRESS.md"P6 落地"节）。
- **短路链**：i1 链与 pyobj 链形态不同（后者直接存原对象）；
  object 返回函数的 and/or 不 create_bool 直接 ret。
- **迭代器五族**（range/riter/object/dict/str）块名、创建顺序、
  null store 位置各不相同。

## 已知坑

- `cargo` 不在默认 PATH（见上 export）。
- 仓库根有不少历史遗留实验文件（`.attic/`、`aok*/`、`c_for*` 等），
  与当前链路无关，不要试图"清理"它们。
- CLAUDE.md 描述的是早期纯解释器时代，已过时；以本文件为准。
- 手写测试期望值先用真 CPython 跑一遍再写（本会话三次被自己的手写
  参照误导）；Oracle 新增 arm 的插入位置敏感（放错会短路既有臂），
  插完必须跑全量 ll 门禁；改运行时函数复杂度要同步审视 .ll 渲染器
  孪生（llvmlite_text.py + llvmlite.si）——它们是运行时的编译期消费者。
- 语料已非全 ASCII（selfhost/utf8_probe.si 钉码点语义）；`_rstrip`/
  `_escape_*` 等孪生热点循环已全部线性化，新增渲染循环时勿再引入
  逐字符 `+=`/循环内切片。
- Python 平面跑 `.ll` 全量对拍较慢（typed_codegen_flat 需分钟级），
  IR 平面与 Rust 平面都是毫秒级。
