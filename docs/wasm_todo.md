# WASM 化：进度快照与 TODO（2026-11-14）

> 状态锚点：本文回答"现在做到哪了、接下来做什么"。
> 设计与验收口径见 `docs/wasm_plan.md`；会话级细节见 `reference/STATUS.md` §3.5-3.12。

## 一、现状快照

- HEAD：`dd90cad` 后续（记录类轮，main，nightly 已推）。门禁全绿：
  **wasm compile 20/20 · wasm run 3/3（三方对拍）· L2 backend 17/17（对拍
  CPython，新增 record_sem/and_or_nary）+ web 产物冒烟 · 语料门禁
  test_corpus **14/15 全尺寸逐字节**（jsonparse 解锁！）+ jsonparse_json
  响亮 · shim 252/252（对拍真 C 库 bit-exact）· 主链 ll 20/20 · ir 21/21 ·
  pytest 1361 通过/3 跳过**。
- **语料 15/15 全部逐字节一致（L2 语料完整达成）**：13 个对拍
  CPython + jsonparse ×2 对拍 silu interpret（CPython 无自动记录构造
  /Json 语义）——jsonparse 9ms、jsonparse_json 8ms（Json 装箱层
  16B {tag,payload} 块 + json_* builtins + 返回隐式装箱）、
  knucleotide@200000 40ms、wordcount@300000 20ms。
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
门禁脚本：`node wasm/test_{compile,run,backend,shim,corpus}.mjs`——
corpus 门禁全尺寸对拍（fe→backend→wat2wasm→执行→CPython，打印计时，
backend 二进制缺失时经 PY312 自动构建；jsonparse ×2 断言响亮陷阱）；
test_backend 支持 `<示例>.stdin` sidecar 双端喂养（input() 管道）。

## 三、里程碑进度

| 里程碑 | 状态 | 内容 |
|---|---|---|
| M0 探针 | ✅ efcdf62 | 链路证明（wasm 编译器 .ll 与 native 字节一致）|
| L0 在线编译 | ✅ de58c53 | playground Compile→.ll；语料 20/20 |
| L1 在线运行 | ✅ 704310f | fe+interp 执行；三方对拍 3/3 |
| L2 真编译 | ✅ 2026-11-14 | IR→WAT 后端；14 例门禁 + 语料 13/15；浏览器 Compile→.wasm→执行闭环 |
| L2+ str ABI v2 | ✅ 2026-11-14 | 长度前缀 + 窄窗原地扩展 + 值语义绑定；knucleotide 全尺寸线性 |
| L2+ 记录类 | ✅ 2026-11-14 | class 构造器 + match 窄化 + 动态容器透传；jsonparse 解锁（9ms）|

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

**记录类轮新发现（2026-11-14，全部修复）**：
- **n 元 and/or 静默丢操作数（P0 级既有 bug）**：FE 发射扁平操作数
  列表，旧二元发射把第三项静默丢掉（`a and b and c` 恒按 `a and b`
  编译）——bool_ops 门禁全绿也没抓到（全二元链）。and_or_nary.si
  门禁（短路副作用计数 + 全假 or——旧 or 初值恒 1）。**操作数从
  arr[1] 起：把 arr[0] 的 tag 字符串喂 emit_expr 会同裸名一样段错误**。
- `o: dict` 裸类型字段曾推断 "i"：`o["k"]` 把 dict 当 list（trace:
  len=2=dict.count、idx=key 指针）。ann_type 补裸 list/dict 臂。
- `str(动态)` 形状：无返回注解的调用携带动态字符串——构造器 str 字段
  若走 str_from_int 会把**指针地址打成十进制数字**（"440119"）。
  仅构造器对非 const 静态 "i" 参数按指针处理；`str()` 内建保持强转。
- 脏形参拷贝消除：$s_copy 实参保护只需覆盖（传递闭包上）确实窄窗
  扩展 str 形参的 callee——jsonparse 84KB 文档曾每次调用全拷
  （750MB bump → trap、18s），现 9ms。
- pass 顺序：全局类型推断必须在函数注册之后（顶层 `w = f()` 曾推断
  "i" → print 打指针、len 走 li_len）。
- read_line 旧 4K 上限**静默截断** 84KB 单行文档 → 可增长缓冲。
- `case` 不能做变量名：自举 FE 视为关键字（Python FE 宽容）——两
  前端又一处分歧。
- 调试教训：探针 stdin 必须 Buffer.from（`new Uint8Array(str)` 产生
  全零字节）；execFileSync timeout 单位毫秒；SIGSEGV 吞 stdout 缓冲
  （调试打印要在 wasm 宿主里跑才可见）。

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

1. ✅ ~~公网部署~~（2026-11-14 深夜关闭）：**https://silu.askender.xyz/playground/
   已上线并浏览器实测全通**。部署 = wasm/web/ 产物（index + host_core.mjs
   + 5 个 .wasm + BUILD_INFO 戳，3.9MB，无源码）推 silu-lang 公开仓
   docs/playground/（Pages = main /docs 已有配置）；EN/ZH 落地页导航加
   playground/在线试用链接。真浏览器验证：5 模块加载（3.92MB over
   HTTPS）+ nested_fn.si → Compile → .wasm（6,302B/272ms，自托管
   wat2wasm）→ 金色按钮变形 → 执行（real wasm compilation，1ms,
   exit 0，输出 410/55/25 44 7 9）。**浏览器缓存注意**：Pages 重建后
   同 tab 重载可能命中修正前缓存——cache-busting 参数（?v=Date.now()）
   强制新取。运维节奏：nightly 侧 `wasm/build.py web` + 复制 8 个文件
   到 silu-lang docs/playground/ + push（Pages 自动构建 ~1min）。
2. ✅ ~~knucleotide O(n²) str 构建~~（2026-11-14 关闭）：**str ABI v2**
   落地——16 字节小端前缀 [blen][clen]（指针指向字节区，字节级消费者
   不变）+ O(1) len + 每绑定必拷贝的值语义（$s_copy：assign/global/
   实参/dict 键值/for 变量）+ 窄窗 `x = x + e`/`x += e` 原地扩展
   （$str_extend：堆顶+堆基双守卫，字面量绝不原地改；`x = x + x` 回退
   concat 防重叠拷贝）。knucleotide@200000 45ms（原超时），语义仍
   13/15 逐字节一致。CPython 式 refcount 优化的无 refcount 等价物。
3. ✅ ~~stdin 数据管道 + 语料探针正式化~~（2026-11-14 关闭）：语料门禁
   入仓为 `wasm/test_corpus.mjs`（全尺寸 13 项逐字节 + jsonparse ×2 响亮
   断言 + 计时）；test_backend 加 `<示例>.stdin` sidecar 管道（stdin_demo
   示例守护 input() 端到端）。**遗留真对拍**：jsonparse 全尺寸语义对拍
   等 pyobj（TODO #4）解锁——现在只能断言"响亮失败"。
4. **pyobj/record 类**（前半完成）：✅ **记录单态化落地**——class_def
   表 + 构造器（[tag][字段槽]，str 字段记录持有）+ match 窄化（tag 链 +
   按类静态类型抽字段）+ 不透明 i64 槽透传动态容器 + `ls`/裸
   list/dict 类型臂 + to_s 动态串 + 脏形参拷贝消除（FDIRTY 闭包）+
   read_line 去上限。jsonparse 9ms 逐字节。✅ **Json 装箱层完成**：
   $jbox 16B {tag,payload} 块（tag 表与 interpreter.py 逐位对齐）+
   json_tag/int/bool/str/list/dict/float/free builtins + "J" 类型标记 +
   返回隐式装箱（按静态类型分发 tag；嵌套 Json 调用直通）+ json_free
   文档化 no-op。jsonparse_json 8ms 逐字节。
   **剩余（按需）**：方法调用/继承/守卫与位置模式 = 响亮 gap；
   json_null/json_free 深释放 = 子集外。
5. ✅ ~~直接二进制发射~~（2026-11-14 关闭，见第 8 条）：backend 直出
   wasm 二进制（LEB128）摆脱 wabt.js 0.66 MB 依赖。
6. ✅ ~~closure 族语料~~（2026-11-14 关闭）：**设计裁定 + 语料钉板**。
   真闭包（捕获外层局部）= **设计外**：FE hoist pass 对捕获响亮拒绝
   （"nested function 'X' captures 'n'; pass it as a parameter"，Rust
   nested-item 语义）——不是 gap 是裁定。无捕获嵌套函数端到端已支持：
   新门禁示例 `wasm/examples/nested_fn.si`（嵌套调模块函数+模块全局、
   双层嵌套、模块级前向引用、嵌套内递归、三面输出互拍）。
   **连带真 bug**：ir_interp 的 call_user 换新 env 后读不到模块级全局
   （hoisted `outer__inner` 里的 BASE 静默变 0 → outer(4) 出 10 而非
   410；CPython/native/wasm 三面全对，ir_interp 独错）——修 = env→genv
   回退（genv 与模块 env 初始同 dict，call_user 只换 env）。run 门禁
   4 三方一致 + 14 loud；backend 18/18、wat2wasm 33/33（新示例自动入
   三门禁）。
7. **工程化（2026-11-14 深夜落地）**：✅ **wasm 六门禁进 CI**——
   .github/workflows/ci.yml 新增 `wasm` job（同 selfhost gates 的
   按需触发：schedule 周一 03:00 UTC + workflow_dispatch）：wasi-sdk
   34.0 钉版下载（wasm64 需 LLVM 19+）+ wabt 1.0.42（差分 oracle）+
   Node 24 + 原生辅助链构建（ensure_frontend/ensure_siluc +
   wasm_backend_native）→ `wasm/build.py web` 一次建全部 artifacts →
   shim/run/backend/corpus/wat2wasm/compile 六门禁逐条断言。
   ✅ **playground 示例全自动同步**——tools/sync_playground_examples.py
   读 wasm/examples/ 全部门禁示例，内联重写 index.html 的
   EXAMPLES/EXAMPLE_TEXT 块（部署目录自包含、无 repo-root fetch 依赖；
   模板字面量危险字符 `/${/\ 反拒不产出坏 JS），接入 `wasm/build.py
   web`——**新门禁示例入 examples/ 即自动出现在 playground 下拉**。
   现挂 18 live 示例 + containers.si（compile-only）；下拉既有的
   strings.si/floats.si compile-only 条目指向不存在的文件（404）已顺手清除。
   **真浏览器验证（2026-11-14 深夜）**：IAB 实测四条 UI 路径全通——下拉
   19 条（含 nested_fn.si）、Compile → .ll（395KB/477ms）、Run ▶（IR
   解释器）、**Compile → .wasm（6,302B/256ms，自托管 wat2wasm）→ WASM
   ▶（1ms, exit 0）**。**连带修既有 UI 断线**：`runWasmProgram`（执行
   编译产物）从未接线——compileWasm 的提示说 "press WASM ▶" 但按钮不
   存在，Run ▶ 永远走 IR 解释器；现 Run 按钮按最后编译产物分派
   （.wasm → WASM ▶ 金色标签；.ll/源码编辑 → Run ▶ 复位并作废产物）。
8. ✅ ~~直接二进制发射~~（2026-11-14 关闭）：**selfhost/wat2wasm.si**
   （纯 Silu WAT→wasm64 汇编器）+ wasm/shim/dec_bits.c（精确十进制→
   binary64，13019 向量对拍 CPython 零误差）。**语料 32/32 逐字节一致
   对拍 wabt**（wasm/examples + benchmarks 全量，wasm/test_wat2wasm.mjs
   入仓门禁：fe→backend→wat→wat2wasm.wasm↔wabt CLI）。playground 已换
   掉 wabt.js（-0.66MB）：index.html 的 .wasm 按钮改走 modules.wat2wasm
   （hex 文本流→宿主解码 2 字符/字节；Silu 字符串无法承载 NUL）；
   build.py 清掉 /tmp 调试 TOOLS。**本轮修的九类 bug**：① if 臂
   `(then…)` 把 then 体整个吞掉（emit_form 对 then 头返回 ""）；
   ② then/else 包裹 RP 与 if 自身 RP 混淆 → if 之后语句全丢（pd 深度
   计数修复）；③ 裸原子指令（`(then unreachable)` 256 处）不落任何臂
   → emit_form 加 TK_ATOM 臂；④ 函数/全局名注册 `"$"+fnm` 双 $ 键 →
   call/global 全部 miss 落 "00"（uleb_hex(-1) 静默 0）；⑤ op 表缺
   return/drop、i64.store8 写成 0x3F（memory.size！）；⑥ `(if (result
   i64)…)` 块类型硬编码 0x40 → 解析 result 形取 valtype 字节；
   ⑦ **空 `(else)` 必须省略**（wabt 规范化掉 05..0b 对）；
   ⑧ **sleb_hex 终止条件读未重符号化的字节** → 改 `v % 128` 直接取
   payload 的规范写法（floor-mod = payload、floor-div = 算术移位）；
   ⑨ **global 臂三处下标**：init 形 `(const VALUE)` 的 opcode=j-4、
   value=j-3（const 形自己的 RP 也要让位），非 mut 全局类型在 i+3 而
   mut 形在 i+5，i32 init 用 0x41。
   **教训**：①token 相对下标（j-N、i+N）必须拿 DBG 探针实证，不靠
   心算——本次 j-3/j-2/j-4 连猜三次；②match_close 返回 RP+1（哨兵
   语义），所有 j-N 下标都要让位；③补丁迭代 >3 轮的文件必须整体重写；
   ④silu_conv split-IR-JSON 与直读源两条路径类型推断有分歧（rawstr→
   i64 只在 IR 路径）——build.py wat2wasm 走 monolith siluc1 绕开；
   ⑤调自托管程序挂死：AST 解释器平面 print 实时可见。
   **性能已知项 → 已解决（2026-11-14 第二轮，见第 10 条）**。
10. ✅ ~~wat2wasm 性能~~（2026-11-14 深夜关闭）：**73.7s → 19ms（fib，
    3800×），32/32 逐字节不变**。消融定位链（微基准 + 变体二分，教训：
    理论猜三次不如实测一次）：①emit 累积改 list[str]+join（正确但非主因）；
    ②**shim memcpy/memmove/memset 逐字节循环** → wasm/shim/bulk_mem.ll
    用 llvm.wasm.memory.copy/fill 内建（clang 直编 IR 文本）+ 链接加
    `-mbulk-memory`（无它后端把 runtime 的 llvm.memcpy intrinsic 展开成
    内联字节循环——bulk_mem.o 没人引用，flag 才是关键）；③**泄漏临时值
    × 页粒度 memory.grow**：单表达式 `SRC[0][n]` 的 `SRC[0]` 中间拷贝
    （值语义，rawlist_str_get 必拷）无人释放 → 每字符泄漏整串 → 46KB 输入
    泄漏 2.1GB → 29K 次 64KB 页 grow（每次 VM 侧 ~1ms）= 27s。shim malloc
    改 256MB 块提交（2× 翻倍会 overshoot 撞 V8 memory64 提交上限 OOB）；
    ④**wat2wasm.si 逐行化**：`split("\n")` 一次 + 逐 token 存 T_TXT
    （token 文本直存，ttext 不再切片 SRC）→ 泄漏从 O(n²) 降到 O(n×行长)
    ≈ 50MB。**遗留正道项**：codegen 层单表达式临时值不释放（`SRC[0][n]`
    的中间拷贝）是所有 .ll 编译程序的共有泄漏——修要动 Python +
    selfhost 孪生 + Rust oracle 三平面（.ll 字节变化 → 重钉），列为
    独立里程碑；shim 块提交使其从"二次方挂死"降为"线性泄漏"。
10. ✅ ~~wat2wasm 性能~~（2026-11-14 第二轮收尾）：73.7s → 19ms 之外，
    **单表达式下标的内层拷贝泄漏已在 codegen 层修掉**（owned 父缓冲
    追踪 + 视图消费后 free，详见 STATUS.md TODO #1）——wat2wasm.si 的
    逐行化仍是热路径主修，codegen 追踪覆盖其余工具（fe/interp/siluc1）。
9. ✅ ~~ir_interp 响亮化~~（2026-11-14 关闭）：selfhost/ir_interp.si
   （int-only 树解释器）过去对子集外程序**静默求 0 甚至挂死**——float
   const（`["const", 0.0]` 裸 JSON 浮点）让 Json 解析器在 '.' 上无限
   循环（strbuf_sem 40 分钟悬死根因），其余未知 IR tag 一律 `return 0`。
   现在：①解析器加固（非 int 数字/未知字符/转义串/越界 → err）；②
   **两阶段预检**——pass A 收集 func_def 名，pass B 全树校验白名单
   （stmt：line/assign/ann_assign/aug_assign(仅 name 目标)/print/call/
   func_def/return/break/continue/if/while；expr：const(仅 int)/name/
   call(仅 print+用户函数)/算术/比较/and/or/not）——首个违规记入 ERRS；
   ③err 标记展开（exec_stmts 每步检查点）。命中即打
   `ir_interp bail: <原因>` + **exit 3**（对齐 Rust oracle bail 惯例）
   且**先于任何程序输出**。连带修 **host.mjs 语义缺口**：入口返回值
   一直被丢弃（`ex[entry]()`）→ wasm 平面 exitCode 恒 0；现 main 返回
   值 = 进程退出码（BigInt→Number），与 native 驱动一致。
   **test_run 门禁改版**：INTERP_SKIP 14 项 → INTERP_LOUD 断言（两平面
   各自响亮 + **bail 消息逐字节互拍** + 退出码互拍）；3 三方一致 + 14
   loud。五门禁全绿（compile 20/20、shim 252/252、backend 17/17、corpus
   15/15、run 3+14）。**已知边界**：`silu interpret` 平面（AST 解释器）
   不把 main 返回值映射为退出码（run_interpreter 丢弃返回值）——ir_interp
   经 interpret 平面跑时消息仍打印但 rc=0；改 cli.py 语义是独立小项
   （需查 pytest 期望值爆炸半径）。test_run 的 native interp 构建加了
   mtime-newer 重建（existsSync 缓存教训的门禁侧防线）。

## 六、边界（不做什么，wasm_plan §6 重申）

- 不做 wasm 侧的独立调试器/REPL。
- 不做非 stdio 的 WASI 面（文件系统/网络）。
- 不追求与 native 二进制逐指令对齐（只对齐可观测输出）。
- 主线源码不进公开仓；公开产物走 silu-lang。
