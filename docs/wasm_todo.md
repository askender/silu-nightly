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
5. **直接二进制发射**：backend 直出 wasm 二进制（LEB128）摆脱 wabt.js
   0.66 MB 依赖；评估 `docs/wasm_plan.md` §L2 尾注。
6. **closure 族 / strbuf 语料**（视覆盖面决定，wasm_plan §3.5）。
7. **工程化**：wasm 四门禁进 CI（Node 已钉 24.3；artifacts 缓存策略）；
   playground 示例列表扩充（新门禁示例自动同步进下拉）。
8. **直接二进制发射（WIP，0092534）**：selfhost/wat2wasm.si（纯 Silu
   WAT→wasm64 汇编器，~1100 行）+ wasm/shim/dec_bits.c（精确十进制→
   binary64，13019 向量对拍 CPython 零误差）。手写 tiny WAT 已与 wabt
   字节一致；**语料 WAT 仍有类型节差异**（structure 的函数 sig 收集 +
   遍历推进在补丁中受损，文件需单次干净重写）。输出为 hex 文本流（宿主
   解码；Silu 字符串无法承载 NUL 字节）。**教训**：①补丁迭代 >3 轮的
   文件必须整体重写（本次重写后仍残留旧 splice 损伤，第二次重写才净）；
   ②silu_conv 对同一源存在 split-IR-JSON 与直接读源两条路径，类型推断
   有分歧（rawstr→i64 只在 IR 路径出现）——build.py wat2wasm 已改走
   monolith siluc1 路径绕开；③调试自托管 Silu 程序的挂死：AST 解释器
   平面 print 实时可见（wasm 宿主平面 stdout 缓冲到退出才可见），
   faulthandler+SIGINT 可抓 Python 栈。

## 六、边界（不做什么，wasm_plan §6 重申）

- 不做 wasm 侧的独立调试器/REPL。
- 不做非 stdio 的 WASI 面（文件系统/网络）。
- 不追求与 native 二进制逐指令对齐（只对齐可观测输出）。
- 主线源码不进公开仓；公开产物走 silu-lang。
