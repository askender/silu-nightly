# WASM 化：进度快照与 TODO（2026-11-14）

> 状态锚点：本文回答"现在做到哪了、接下来做什么"。
> 设计与验收口径见 `docs/wasm_plan.md`；会话级细节见 `reference/STATUS.md` §3.5-3.12。

## 一、现状快照

- HEAD：`92a7eb1` 后续（str ABI v2 轮，main，nightly 已推）。门禁全绿：
  **wasm compile 20/20 · wasm run 3/3（三方对拍）· L2 backend 14/14（对拍
  CPython，新增 strbuf_sem）+ web 产物冒烟 · shim 252/252（对拍真 C 库
  bit-exact）· 主链 ll 20/20 · ir 21/21 · pytest 1361 通过/3 跳过**。
- **语料 15/15 处置完毕**：13 个 benchmark 逐字节对拍 CPython——
  **knucleotide@200000 从"O(n²) 超时 + 内存耗尽"降到 45ms 线性**（str
  ABI v2，见 TODO #2 已关闭）；wordcount@300000 23ms；jsonparse ×2 =
  pyobj 类子集外（构造点响亮 unreachable；文档本身走 stdin，待 #3）。
- 本地 playground 完全可用：`python3 -m http.server -d wasm/web` 后浏览器
  打开即可 Compile→.ll / Run / Compile→.wasm 三条管线全闭环。
  **公网部署（silu.askender.xyz）尚未做**——见 TODO #1。

## 二、四个 wasm 二进制（web/ 内 4.15 MB，未压缩）

| 模块 | 尺寸 | 角色（管线位置） |
|---|---|---|
| `siluc1.wasm` | 2.78 MB | **完整自举编译器 monolith**（.si → .ll，字节一致）|
| `fe.wasm` | 0.41 MB | 前端（.si → IR JSON）|
| `interp.wasm` | 0.05 MB | IR 树解释器（IR JSON → 程序输出；int-only）|
| `backend.wasm` | 0.36 MB | wasm 后端（IR JSON → WAT；wabt.js 汇编执行）|
| `wabt.js`（依赖） | 0.66 MB | 浏览器内 wat2wasm（Apache-2.0）|
| `host_core.mjs` | 0.02 MB | silu_host shim（stdio/fmt_double/strtod/pow/getchar）|

构建：`python3 wasm/build.py web`（artifacts/ 不提交，web/ 提交）。
门禁脚本：`node wasm/test_{compile,run,backend,shim}.mjs`；语料探针
`/tmp/corpus_probe.py`（fe→backend→wat2wasm→node→对拍 CPython，含计时）。

## 三、里程碑进度

| 里程碑 | 状态 | 内容 |
|---|---|---|
| M0 探针 | ✅ efcdf62 | 链路证明（wasm 编译器 .ll 与 native 字节一致）|
| L0 在线编译 | ✅ de58c53 | playground Compile→.ll；语料 20/20 |
| L1 在线运行 | ✅ 704310f | fe+interp 执行；三方对拍 3/3 |
| L2 真编译 | ✅ 2026-11-14 | IR→WAT 后端；14 例门禁 + 语料 13/15；浏览器 Compile→.wasm→执行闭环 |
| L2+ str ABI v2 | ✅ 2026-11-14 | 长度前缀 + 窄窗原地扩展 + 值语义绑定；knucleotide 全尺寸线性 |

L2 子集能力清单（全部对拍 CPython）：int/float/bool（True/False repr）、
list[int]/list[float]（位打包）、str（码点 len/索引/切片/upper/lower/拼接）、
dict[str|int, int|float|str]（哈希索引、插入序、get/default）、非空字面量、
`[x]*n`、模块级全局变量、下标 aug（`l[i]+=`）、str 拼接 aug（`s += e`，
窄窗原地扩展）、and/or/not 短路、break/continue、for（list/dict）、
函数/递归、print 全类型渲染、input()、`//`/`%`（含浮点地板语义）、
`**`（int 平方 + 宿主 pow）、`in`（bool repr）。静默 gap 全部响亮化
（unreachable，绝不出错误字节）。

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

**str ABI v2 轮新发现（2026-11-14，全部修复）**：
- **`s += e` 静默指针算术**（P0）：纯名字 str 目标的 aug 落进 i64.add
  fallthrough → 指针+数字=垃圾字节，无任何报错。现走窄窗扩展，其余
  str aug 响亮化。
- **slice4 按"源串长度"分配**（P0 级性能）：每个小切片 bump O(源串)
  字节——knucleotide n 刀 × n 字节 = 二次方堆消耗，n=200000 时 40GB
  把 `$alloc` 的 memory.grow 打成 -1（trap）。改为按选中码点数 ×4B
  最坏界。**教训：切片分配的量级必须跟着切片结果走，不跟源串走**。
- `top_type` 对 name 操作数无臂：`u = s + s` 裸全局推断成 "i" → print
  打出指针。修 = pass 0 先收集注解名（ANNTYPES），top_type 加 name 臂。
- `in` 表达式类型标 "i"：print 渲染 1 而非 True。`$ds_has` 本就返回
  0/1，改标 "b" 即可。
- `print_dsf` 对 fmt_double 的 scratch 指针调 `$str_blen`（新 ABI 下读
  垃圾前缀）→ 改用 fmt_double 的返回长度。
- concat 拷贝目标是前缀区而非字节区（一次低级失误，strings.si 差分
  立即暴露）；`$str_from_int` blen 把 NUL 地址算进去（差 1，同样差分
  暴露）。**教训：ABI 换代后每个构造函数的"返回指针-前缀-字节"三段
  关系要逐个对表**。
- **run 门禁 40 分钟悬死**：新示例 strbuf_sem.si 被 test_run 自动喂给
  ir_interp（int-only）→ 崩/挂（非响亮 gap，ir_interp 自身缺口，非
  回归）。入 INTERP_SKIP 处置；**ir_interp 对不支持构造的响亮化列为
  后续小项**。教训：新示例要过每一门（test_run 自动吃 examples/ 全
  目录）。

## 五、TODO（优先级序）

1. **公网部署**（运维，非代码）：wasm/web/ 发布到 silu.askender.xyz。
   走 silu-lang 公开仓 checkout，遵守"源码不进公开仓"拓扑；产物带
   BUILD_INFO 戳。本地体验不受影响。
2. ✅ ~~knucleotide O(n²) str 构建~~（2026-11-14 关闭）：**str ABI v2**
   落地——16 字节小端前缀 [blen][clen]（指针指向字节区，字节级消费者
   不变）+ O(1) len + 每绑定必拷贝的值语义（$s_copy：assign/global/
   实参/dict 键值/for 变量）+ 窄窗 `x = x + e`/`x += e` 原地扩展
   （$str_extend：堆顶+堆基双守卫，字面量绝不原地改；`x = x + x` 回退
   concat 防重叠拷贝）。knucleotide@200000 45ms（原超时），语义仍
   13/15 逐字节一致。CPython 式 refcount 优化的无 refcount 等价物。
3. **stdin 数据管道**：diff_harness 的 stdin 喂养机制接入 wasm 门禁
   （jsonparse 全尺寸进正式对拍；探针脚本 /tmp/corpus_probe.py 目前
   手动维护，正式化时一并入 gates）。
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
