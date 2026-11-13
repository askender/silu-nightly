# WASM 化：进度快照与 TODO（2026-11-14）

> 状态锚点：本文回答"现在做到哪了、接下来做什么"。
> 设计与验收口径见 `docs/wasm_plan.md`；会话级细节见 `reference/STATUS.md` §3.5-3.11。

## 一、现状快照

- HEAD：`9033602`（main，nightly 已推）。门禁全绿：
  **wasm compile 20/20 · wasm run 3/3（三方对拍）· L2 backend 13/13（对拍
  CPython）+ web 产物冒烟 · shim 252/252（对拍真 C 库 bit-exact）·
  主链 ll 20/20 · ir 21/21 · pytest 1361 通过/3 跳过**。
- **L2 计划验收条款已达成**：子集在语料中所有可编译文件上输出一致——
  **13/15 benchmark 逐字节对拍 CPython**（arith/dict/fannkuch/fib/float/
  list/mandelbrot/nbody/spectral/string/trees/wordcount@300000/
  knucleotide@小 n）。jsonparse ×2 = pyobj 类子集外（响亮 unreachable，
  不出错误字节）。
- 本地 playground 完全可用：`python3 -m http.server -d wasm/web` 后浏览器
  打开即可 Compile→.ll / Run / Compile→.wasm 三条管线全闭环。
  **公网部署（silu.askender.xyz）尚未做**——见 TODO #1。

## 二、四个 wasm 二进制（web/ 内 4.08 MB，未压缩）

| 模块 | 尺寸 | 角色（管线位置） |
|---|---|---|
| `siluc1.wasm` | 2.65 MB | **完整自举编译器 monolith**（.si → .ll，字节一致）|
| `fe.wasm` | 0.39 MB | 前端（.si → IR JSON）|
| `interp.wasm` | 0.05 MB | IR 树解释器（IR JSON → 程序输出；int-only）|
| `backend.wasm` | 0.31 MB | wasm 后端（IR JSON → WAT；wabt.js 汇编执行）|
| `wabt.js`（依赖） | 0.66 MB | 浏览器内 wat2wasm（Apache-2.0）|
| `host_core.mjs` | 0.02 MB | silu_host shim（stdio/fmt_double/strtod/pow/getchar）|

构建：`python3 wasm/build.py web`（artifacts/ 不提交，web/ 提交）。
门禁脚本：`node wasm/test_{compile,run,backend,shim}.mjs`。

## 三、里程碑进度

| 里程碑 | 状态 | 内容 |
|---|---|---|
| M0 探针 | ✅ efcdf62 | 链路证明（wasm 编译器 .ll 与 native 字节一致）|
| L0 在线编译 | ✅ de58c53 | playground Compile→.ll；语料 20/20 |
| L1 在线运行 | ✅ 704310f | fe+interp 执行；三方对拍 3/3 |
| L2 真编译 | ✅ 2026-11-14 | IR→WAT 后端；13 例门禁 + 语料 13/15；浏览器 Compile→.wasm→执行闭环 |

L2 子集能力清单（全部对拍 CPython）：int/float/bool（True/False repr）、
list[int]/list[float]（位打包）、str（码点 len/索引/切片/upper/lower/拼接）、
dict[str|int, int|float|str]（哈希索引、插入序、get/default）、非空字面量、
`[x]*n`、模块级全局变量、下标 aug（`l[i]+=`）、and/or/not 短路、break/
continue、for（list/dict）、函数/递归、print 全类型渲染、input()、
`//`/`%`（含浮点地板语义）、`**`（int 平方 + 宿主 pow）。静默 gap 全部
响亮化（unreachable，绝不出错误字节）。

## 四、实现过程中发现的问题（含主链交叉验证结论）

**主链（Python/Rust/自举编译器）**：
- 本轮 wasm 语料 13/15 字节一致 = 对主链前端 + IR 的一次**全量交叉验证**
  （wasm 后端消费同一 IR JSON，任何主链语义漂移都会在对拍中暴露）。
- L1 时期（2026-11-11）曾暴露一次**真主链回归**：utf8_byte_len 的 bytes
  分支在 typed 平面误触发 → 字符串常量按码点定尺寸；根因是 ll 门禁的
  假绿（陈旧 siluc1 二进制）。已修复并沉淀"改 selfhost 源必须确认重建"
  教训。
- 本会话一次 **silu_conv SIGSEGV** 观测（构建竞态，非语义问题）→ 已用
  可重入 flock + 原子落位修复（4 进程压测干净），TODO #2 关闭。
- 一份代理报告声称"语言级嵌套调用错求值"——四平面探针（CPython/参考
  解释器/native/wasm 后端）证明**误报**；真缺陷是 wasm 后端 aug 下标
  目标缺口，已实现。

**wasm 后端自身**（审查代理发现 + 语料攻坚修复，全部差分实证）：
- P0×3：and/or/not 无分派静默 0、break/continue 被丢弃（while True 死
  循环）、未注解 str/list/dict 变量丢类型（指针相加）。
- 经典 bug：`$str_from_int` 负号堆下溢破坏相邻对象；哈希表满表查询的
  find 剪断返回陈旧 ei 被当命中（wordcount 误计 4 根因）——**剪断分支
  必须显式归零**；grow 与 find 的次序（满表无空槽）；lf 被误并进 dict
  值臂；backend 自己的全局标记被自己的作用域规则吃掉（改 CTX list）。
- shim 层：cStrtod 符号群 4 处、hexFloat fraction 顶端对齐、cReprDouble
  调整指数、%e/%g 半偶舍入（expExact）、fmt_double 缺 NUL 终止。

## 五、TODO（优先级序）

1. **公网部署**（运维，非代码）：wasm/web/ 发布到 silu.askender.xyz。
   走 silu-lang 公开仓 checkout，遵守"源码不进公开仓"拓扑；产物带
   BUILD_INFO 戳。本地体验不受影响。
2. **knucleotide O(n²) str 构建**：`dna = dna + "A"` 20 万次，CPython 有
   refcount 原地优化而 wasm 每次全拷。缓解 = strbuf 类 ABI（P1 研究已
   有基础，`reference/P1_STRING_RESEARCH.md`）或 rope；语义已正确，纯
   性能项。
3. **stdin 数据管道**：diff_harness 的 stdin 喂养机制接入 wasm 门禁
   （jsonparse 全尺寸、knucleotide@200000 进正式对拍；目前是探针脚本
   手动验证）。
4. **pyobj/record 类**（L2 子集 5 剩余）：class 定义/构造/字段访问/
   方法调用。jsonparse 语料依赖此解锁；评估 record 单态化 vs 动态
   pyobj 路线。
5. **直接二进制发射**：backend 直出 wasm 二进制（LEB128）摆脱 wabt.js
   0.66 MB 依赖；评估 `docs/wasm_plan.md` §L2 尾注。
6. **closure 族 / strbuf 语料**（视覆盖面决定，wasm_plan §3.5）。
7. **工程化**：wasm 四门禁进 CI（Node 已钉 24.3；artifacts 缓存策略）；
   playground 示例列表扩充（新门禁示例自动同步进下拉）。

## 六、边界（不做什么，wasm_plan §6 重申）

- 不做 wasm 侧的独立调试器/REPL。
- 不做非 stdio 的 WASI 面（文件系统/网络）。
- 不追求与 native 二进制逐指令对齐（只对齐可观测输出）。
- 主线源码不进公开仓；公开产物走 silu-lang。
