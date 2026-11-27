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
**silu 1.25.0（语义轮重钉：容器边迭代边改、推导式作用域、dss 借用语义 + ll 门禁 verifier；同版追加内存安全轮——码点偏移越界读、`s = s + s` 用后释放、`str.find` 字节偏移、自举转换器对 i64 槽实例属性赋值必崩、真 ASan 门禁；1.24.0=oracle 形状补齐/dss 2 参族，1.23.0=str 方法族，1.22.0=g-清单闭合，1.21.0=P9 concat 所有权，1.18.1=cp-offset 缓存，1.18.0=strbuf，1.17.0=P6/P2/P5，原神谕 1.16.2）** 的行为。用途：
差分 Oracle、表达力校准、隐式规约提取。**不是产品编译器，不进自举链，
不做同步镜像**。

**状态（2026-11-21）：已完成**——前端 IR **31/31**、完整 .ll **30/30**（含 silu_fe/str_methods/dict_ops/record_global/dict_str 全语料）
逐字节一致；语料 29 文件（八枚能力钉板：char_pair/list_ops/pop_clear/dict_ops/record_global/dict_local/str_methods/dict_str——dict[str,str] 四平面表示统一 RAWDICT_SS）。规模对照、参考特性分诊、语言设计建议见校准报告。

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
cd <仓库根>                                  # 以下命令都必须在仓库根执行
tools/gates.sh                               # 全门禁一条命令：ruff + IR/ll 四个平面 + 全量 pytest
                                             #   + GitHub 上 HEAD 的 CI 结论；退出 0 才能称"全门禁绿"
tools/gates.sh --no-pytest                   # 只跑平面门禁（秒~分钟级）
python3 tools/regen_rust_prefix.py            # 改运行时发射器后重生成 rs 前缀快照（--check 只校验）
export PATH="$HOME/.cargo/bin:$PATH"        # cargo 常不在默认 PATH
$PY312 reference/diff_harness.py ir fe rustfe    # 前端 IR 平面，33/33
$PY312 reference/diff_harness.py ir fe pyir      # 自举前端 vs Python 前端，33/33
$PY312 reference/diff_harness.py ll conv rustconv # 完整 .ll 平面，32/32
$PY312 reference/diff_harness.py ll conv pyll     # 自举转换器 vs Python 转换器，32/32
$PY312 -m pytest tests/test_asan_runtime.py -q   # 内存安全门禁（真 ASan，约 1 分钟）
$PY312 -m pytest tests/test_asan_compiler.py -q  # 编译器自身跑真 ASan（慢层，约 3 分钟）
./siluc1 < benchmarks/fib.si > /tmp/ref.ll                  # Python 平面参考输出
reference/rust/target/debug/silu-conv benchmarks/fib.si > /tmp/rust.ll
cmp /tmp/ref.ll /tmp/rust.ll                # 前缀恒定，可整文件比
SILUC_DAEMON=1 ./siluc prog.si -o prog     # 经 daemon 编译（重复编译 ~0ms）
./siluc --serve                            # 常驻编译服务（空闲 300s 自退）
```

注意：`silu-conv` 通过子进程调同目录 `silu-fe`；`.si` 路径按当前工作
目录解析，**一律从仓库根运行**。命令里的 `python3` 一律指
`/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3`（裸
homebrew python3 无 llvmlite，CLI 会静默隐藏 build/llvm/verify 子命令）。
**harness 开跑前按源码 mtime 自动重建 `siluc1`/`silu_fe` 并 `cargo build`**
——门禁不会再跑在陈旧二进制上。**lint 属于门禁**：`tests/test_lint.py`
跑的就是 CI 的那条 ruff 命令，pytest 全绿即蕴含 ruff 干净。

## 当前状态锚点（2026-11-27）

- **打磨轮（2026-11-27，STATUS §3.38，进行中）**：v1.25.0 已打 tag
  发布（release + CI gates 作业 success）；tag 的 wasm 作业暴露
  `wat2wasm` 空标识符回归（wasm_backend.si 声明扫描对属性 store 目标
  elem_str 得 "" → 无名全局；`emit_expr` 兜底静默求 0 → 全部改响亮
  unreachable，七 wasm 门禁绿）。**四平面探针电池**
  （/tmp/silu_night/battery.py，120+ 探针）扫出编译平面静默错误字节
  一批（`-2**2` 优先级、find/startswith start 参数忽略、replace 空针、
  tuple repr 打 `[...]`、repr 不加引号、f-string spec 忽略）与解释器
  响亮一致性欠账（global/nonlocal/sorted key 静默忽略、walrus 误解析）
  ——修复中，见 STATUS §四 首条。**新文档 docs/python_differences.md**
  （全部已知差异 + 支持矩阵，每条探针背书）；semantics.md §3 的
  "先删后插 CPython 继续迭代"旧断言已修正（CPython 3.12 实测同样
  raise，Silu 行为一致仅消息不同，设计保留）。**教训**：node 层 wasm
  门禁不在本地 gates.sh，本地全绿 + CI wasm 红的组合已出现两次；
  IR 里 assign 纯名字目标是字符串、属性目标是列表节点，对字符串
  JValue 调 tag() 段错误——判形状用 `.kind == JKind.STR`。
- **内存安全轮（2026-11-26 续，STATUS §3.37）**：追查
  `gates-last-failure.log` 里一条被我当成"门禁竞态"的瞬态失败，
  发现 macOS 崩溃报告目录里有 **5 份 `siluc1` 段错误**。真 ASan
  （`tools/asan_run.py`）逐个定位，全部修到根因——
  ①`pystr_cp_entry`/`rawstr_cp_off_at` 的码点偏移表为写哨兵多转一轮，
  读 `data[len]` 越界 1 字节（缓冲恰在分配区末尾时段错误）→ 改成
  与计数同一谓词的一次有界逐字节扫描；②`rawstr_append` 的 realloc
  可能在拷贝之下释放源缓冲（`s = s + s`：use-after-free + 错误
  尾部）→ 源在自身缓冲内时走"分配-拷贝-追加完再释放"；③`str.find/
  rfind/index` 返回**字节偏移**而非码点下标（非 ASCII 串上
  `s[s.find(x)]` 取错字符；四处实现同修：两转换器平面、rs 经前缀、
  ir2c）；④**自举转换器对"typed 实例列表元素 + 属性赋值"必崩**
  （10-25 起）：`_field_slot` 的 `str(inst_ptr.type) == "i64"` 在孪生
  里恒假（孪生的类型记录没有 `__str__`），裸 i64 字被当指针用；
  `selfhost/ir2c.si` 正是这形状，从未被 siluc1 编过而无门禁覆盖
  → 改缓存类型比较；文本渲染器遇空操作数响亮报错；⑤变更方法的
  返回值：`r = d.clear()` 的 void store（非法 IR）、`xs.append(x)`
  返回列表自身 → 绑定 None（按方法名判定 `_NONE_RESULT_METHODS`；
  方法表的 `has_result` 列从未被读取，对 startswith/endswith 也是
  False，读它会把转换器自己的 `_is_inst` 拖垮）。
  **此前所有"ASan 零报告"都是空泛的**：clang 只插桩带
  `sanitize_address` 属性的函数，`.ll` 输入没有这个属性——`clang
  -fsanitize=address x.ll` 链接了运行时却什么都不检查。新门禁
  `tests/test_asan_runtime.py`（124 项：语义用例 × 双平面 + 内存形状
  + 语料，约 1 分钟，fast 层）与 `tests/test_asan_compiler.py`（34 项：
  **编译器二进制自身**跑真 ASan 编全部语料 + ir2c.si + 自己的转换器，
  无报告、rc=0、与普通二进制逐字节一致；慢层，约 3 分钟，CI 的
  gates 作业）——都先给每个 `define` 加属性，再用一个已知越界读证明
  工具链有效；对修复前的代码实测会红。前缀 422,537B。
  **已文档化的边界**：`upper()/lower()` 只映射 ASCII（非 ASCII 字母
  原样），Unicode 大小写表待裁决；`print(a, b)` 逐个求值并立即输出
  （后面的参数改了前面的可变参数时与 CPython 不同，解释器同 CPython）。
- **语义轮（2026-11-26，STATUS §3.36）**：304 探针扫出的"门禁全绿
  但答案错/崩"的一批根因修复，全部先 CPython 对拍再动手——
  ①**容器边迭代边改**：typed dict 循环改按 entry 数组走（插入序，
  reindex 保序、覆盖写不再 reindex），每步核对 count/filled/keys
  指针，结构变化即 `RuntimeError`（旧实现一次性抓 table/keys/vals，
  体内一次扩容就踩释放内存）；动态 dict/set 加 `pyobj_dict_*`
  监视运行时；list 循环改活动长度（工作表惯用法）；str 循环体内
  重绑定走快照拷贝（return 路径经 `loop_str_cleanups` 释放）。
  ②**推导式**：元组目标绑定（三个前端都解析，此前两个拒绝、
  Python 平台静默给 `[2, 2]`）+ 目标作用域（遮蔽的名字还原，
  typed 槽仅在可迭代对象声明元素种类时解箱）。
  ③**dss 借用语义**：`_mark_borrowed_str`——`d[k]`/get/setdefault
  的结果归 dict 所有，赋值拷贝、语句释放跳过（旧实现语句形式直接
  free 掉 dict 自己的缓冲）；`dict[str,str]` 可作参数种类。
  ④其余：`del xs[i]`、dict `==` 内容比较、`s += f()` 单次求值、
  strbuf 非常量构造、IEEE-754 边界字面量、pow/range/count/kwargs。
  ⑤**ll 门禁带 verifier**（diff_harness 对逐字节一致的模块跑真
  llvmlite verify）：del 运行时的 phi 不支配整段会话没人发现——
  clang 照样汇编、四平面字节一致，只有 pytest 红（164 个）。
  ⑥自举前端 `hoist_module` 漏了 nested_hoist 的 isinstance 守卫，
  模块级 `h.n = 5` 直接崩（已钉 record_global.si）。
  语料 33 文件（selfhost/comp_unpack.si）；门禁 ir 33/33、ll 32/32
  （含 verifier）、语义门禁 tests/test_semantics_vs_cpython.py
  （Python 平面 + 自举平面各跑一遍，现 231 项）。**rs 神谕的字母表
  缺口**（一律 bail，不是错误字节）：typed dict 作函数参数、typed
  dict 循环、typed 槽的推导式遮蔽、模块级 str `+=`、整只 dss dict
  的 print、函数内实例属性赋值、`str.rfind`、`print(s[i])`。
- **oracle 形状补齐轮全收口（2026-11-22 深夜，e74c38a→6ce0680）**：
  §3.32 五项全部落地——①rs dss 2 参族（get/pop/setdefault tail PStr
  臂 + py 求值顺序对齐：pop/get 键先、setdefault 默认值元组先）②rs
  dss/dii aug（dict 门修复 dii 静默走 list 形状的错误字节）③rs 非空
  dict 字面量（dsi/dss/dii × 全局/局部；局部字面量曾静默变空 dict）
  ④钉板扩容（dict_str.si membership/2 参族/aug/字面量/读拼接 +
  dict_ops.si dsi/dii 字面量）并**当场抓获三平面共有无效 IR bug**
  （aug concat i64 位传 i8* 形参、str 值 set 传裸指针——clang 宽容/
  text 层不校验，真 llvmlite verifier 拒绝；py 参考+flat 孪生+rs 三处
  同步修复）⑤动态 dict pop 语义（1 参 miss KeyError panic、2 参 miss
  返回默认含 None；dict_pop+dict_pop_def 双域 ABI + 双 dispatch +
  方法表按参选函数；const_prefix.ll 重生成 391,059B + rs 快照同步；
  前缀快照必须止于 `}\n`）。全门禁绿：ll 30/30、ir 31/31、pytest
  1398+4/3、wasm corpus 16/16、backend 18/18、wat2wasm 43/43、探针
  28 枚双平面字节+执行一致。
- **v1.24.0 已发布 + §3.33 四项后续收口（2026-11-22 深夜，d83c3bb→
  343bc93）**：cp_offset 死函数退役（前缀 390,013B）、rs str `-=`、
  rs dsf/df 整族（+float 全局声明 SOLAR_MASS 约定修复）、rs object
  全局/重赋值、**strbuf ctor 单次转换语义修复**（双 pop 副作用 bug：
  `strbuf(d.pop("a"))` hit 曾变 KeyError——x2 探针，双平面字节一致
  且同错的第四形态）。39 探针 + 全门禁绿（pytest 1402/3）。
- **§四 TODO 全收口（2026-11-24，c5ebb98）**：g-#10 推断分歧闭合
  （str 返回 builtin/方法 → RAWSTR 推断 or-链 + rs 模块上下文 str
  auto-decl + EOF 悬空空行修复；input() 静态 str 化后两个测试动态值
  源换 1 参 get phi，拒绝契约保留）；51 探针 + 全门禁绿（pytest
  1403/2）。**STATUS §四 无遗留可行动项**——剩余全部用户门控（P7
  立项 T1/T3 未触发；PROPOSALS 六提案须裁决，硬约束 4）。换客户端
  第一站 = STATUS.md §3.35。
- **dss 收敛轮全绿（2026-11-21/22，53a0942/27b074c/dde4097/9baa855/
  bdb35e7）**：dict[str,str] 四平面表示统一 RAWDICT_SS（py 从动态
  dict 切换），语料 29 文件（第 8 枚能力钉板 dict_str.si，406,041B
  双平面逐字节）；rs 三处被接受但错误的字节（int 装箱 phi/裸指针
  十进制/bits 当指针 free）执行探针抓获并修复（dde4097，铁律）；
  ir2c dss 臂（27b074c）；门禁 ll 30/30、ir 31/31、pytest 1398/3。
- **P9 收口：ll 22/22 全绿（2026-11-18，34c2a61，STATUS.md P9 第七轮）**：
  codegen 层 concat/临时值所有权追踪跨 ll 全语料逐字节一致（silu_fe
  首次）。残差全归因（形状序列法——槽号多重集比对被 free 占槽漂移污染，
  不可用）：6 个额外 free 全是 push 参数 coercion 临时；json_quote 是
  集合交换（py free coercion 泄漏 char1 / rs 反向）。修复三点：py push
  臂 kind 门释放（**RAWSTR 实参的 _coerce 结果是 list 持有的 copy，
  释放 = use-after-free**）、py const 融合预 coerce 处 char1 相位门注册、
  rs 逐侧 pause 门 + 两个 push 站点扩展。**仪器化退役教训**：
  SILU_TRACE_CONCAT 的 `import os as _os` 使新编 siluc1 读未定义全局——
  仓库根二进制曾是仪器化前旧物（门禁跑的是旧 py 平面）；调试仪器化
  随调试结束立即摘除。门禁全绿：ll 22/22、ir 23/23、pytest 1374/3、
  corpus 16/16、irvm 10/10×2、backend 18/18、wat2wasm 35/35、
  ruff 净、RSS 1.15MB（30 万链式 concat，修复前 6.1MB）。**版本重钉
  1.21.0**（v1.20.0 发布于 P9 输出变更之前）。
- **str 方法族四平面 + ll parity 29/29（2026-11-20/21，STATUS §3.28-3.29）**：
  strip/split(sep/ws)/replace/lower/upper/find/index/startswith/endswith/
  谓词/print-bool 全族四平面字节对齐（rawstr_replace 新 .ll 运行时：
  append 风格签名——首版 rawstr 指针签名把 len 读成数据字节，replace
  恒返回原串，native ≠ CPython 当场抓获）；**index 语义修复**（原
  list_index 通用分派对 str 接收者静默 -1 → str_find + ValueError
  panic）；str-method 前奏的急切接收者求值对 dict 方法也发（双重
  load）——dict 族移至 str 族之前；**局部 dict 槽域**（len/get/方法臂
  dct_slot 对齐）；**边界空行规则定版**（.ll = 每个 inter-function
  边界恰一空行，fn-fn 无空行——CONST→TAGGED、TAGGED→首用户 fn、
  fn→main 三处各一）。**教训**：①harness 的 ll 计数有平面二进制陈旧
  窗口——直跑 cmp 为准；②rs 的运行时前缀 = include_str 快照——新
  运行时函数必须重生成 const_prefix.ll；③str-method 前奏的急切求值
  对非 str 方法也是隐藏分支——族块按方法集合门控。str_methods.si
  四平面 = CPython（14 语句）。ll 29/29、ir 30/30、pytest 1395/3。
- **g-清单闭合：语料压力五轮（2026-11-19/20，STATUS §3.24-3.27）**：
  membership、pop/clear、dict 方法族（pop/setdefault/clear × str/int
  key）、局部 dict 全族、模块级实例全局（GLOBAL_TY 注册表 + 方法调用
  + ctor 字段上下文）、str-key store 验证（emit_pyobj_key_view 共享
  机器）、装箱 join、丢弃式 rawstr 释放、alloca 收集序——全部四平面
  字节对齐。**语料 22→27**（char_pair/list_ops/pop_clear/dict_ops/
  record_global/dict_local 六枚钉板）。**m5 执行比对三次当场抓获 C
  后端静默降级/SIGSEGV**（membership/pop_clear/dict_ops 三轮）；
  ir2c 语句级响亮化落地（expr 级 0 降级为设计线：自举链 C 前端一直
  带死值 0 工作，m5 执行比对守护值消费位点）。**教训**：rs 有两份
  平行 name-eval 分发（eval_expr/eval_mod）——改 name 语义必须两处
  同改；哈希探针必须与插入方同哈希；方法臂插入位置敏感（dict 臂
  无类型门曾截走 list 的 clear → SIGSEGV）。g-list 终态：g1-g12
  全部关闭或作废，唯余 dss 1 参 get（响亮 bail）。ll 27/27、ir 28/28、
  pytest 1392/3。
- **默认构建走运行时缓存（2026-11-18，STATUS.md §3.23）**：`silu build`
  470→210ms——运行时缓存快路径由 SILU_RUNTIME_CACHE=1 opt-in 翻转为
  默认（**=0 显式退出**，dynamic codegen 不缓存）；路径由 selfhost_build
  每日锤炼 + 18 基准 A/B 执行对拍背书。char_pair.si 入仓钉 P9 形状
  （ll 23/23、ir 24/24、corpus 计数 22）。
- **P8 match switch/br_table + siluc daemon（2026-11-17，STATUS.md
  §3.22）**：全 int 字面量 match 降为 LLVM switch（三 conv 字节一致）
  与 wasm br_table（backend+wat2wasm.si 新分支）；其余模式维持链式。
  门禁：ir 22/22、ll 21/21（新语料 benchmarks/match_int.si）、
  wat2wasm 34/34、corpus 16/16、backend 18/18、compile 21/21。
  **wasm br_table 三坑**：OOB 取 default 无需 guard；通配 body 必须
  在 match 块之外（br 到 match-exit = 退出整块）；索引字节先于 0x0E
  入栈。**siluc daemon**：`siluc --serve` + `SILUC_DAEMON=1 siluc
  file.si -o out` 透明转发（--object/--no-lto 不转发；直连路径零
  改动）；内容键缓存**重复编译 ~0ms**（vs 160ms），fork 隔离多任务
  无串扰；EOF 界定协议（verdict 永远最后一行）——**stderr 与协议
  共用 fd 会在客户端早断后静默破坏编译**。daemon 子进程必须恢复
  `SIGCHLD SIG_DFL`（父的 SIG_IGN 让 run_quiet 的 waitpid 拿到
  ECHILD 垃圾状态）。
- **irvm 字节码平面落地（2026-11-14 深夜，STATUS.md §3.21）**：
  Rust 平面 tools/irvm（f0e1de8）+ Silu 孪生 selfhost/ir_vm.si（单文件
  自包含，stdin 首行 "@dump" 选 dump 模式）。门禁两道（探针在
  tools/irvm/probes/）：执行差分 test.sh（vs ir_interp，9/9）、跨平面
  字节一致 bytecode_diff.sh（Rust dump vs 孪生 dump，9/9 逐字节）。
  **速度（fib28 总耗时）**：Rust VM 50ms / 孪生 native 60ms（内联热臂
  → 频次重排 → pc/end/sbase 寄存器化，115→84→60ms）/ monty 116ms /
  ir_interp 1.76s / AST
  解释器 ~15s（CPython 60ms 仍略快——C 级解释器）。Rust VM 曾
  0.775s——每指令 env 查询（调试残留）+ 每帧堆分配两连修后 15.5×；
  **VM 循环内禁止 env 查询/每帧分配**。孪生回物理栈模型（VDEPTH
  惰性栈是绕已修 bug 的变体，必然发散；FRAME_VBASE 声明未用 =
  RETURN 截断无落点）。连带修 conv rawlist_pop 清零 bug（双平面）。
  **编译链对比**：rustc -O 同 workload 固定 100ms（运行 <1ms）；
  siluc 缓存驱动 170ms（runtime 预编译 .o，只编用户部分）；默认
  `silu build` 530ms（clang -O2 全量 375KB IR 是大头）。
  思考文档 docs/interp_vs_comp.md、评测集 tools/irvm/eval.py。
- **v1.18.1 已公开发布**；发布链根因（GitHub 退役 macos-14 池）已修复
  入档。**tag push 用 tag 所在 commit 的 workflow 文件**，改 CI 后 tag 必须前移。
- 门禁全绿：ll **20/20（2026-11-14 深夜修复，见下）**、ir 21/21、
  pytest **1361 通过/3 跳过**。
- **ll 门禁失真修复（2026-11-14 深夜，STATUS.md TODO #1）**：str 字段
  赋值两平面双拷贝且字节序相反（Python copy 在 base load 前、Rust 后
  且多一份）——edae9f1（ir_interp 响亮化）以来 ll 实际 19/20 + 1
  ERROR，本会话首次跑 ll 门禁才暴露。修复：Python `_convert_field_value`
  门控 defer（赋值路径拷贝延到 base load 后，**构造器路径保持急拷贝
  ——构造器直接 store，丢拷贝 = 字段别名源缓冲 = 编译器自腐蚀**）；
  Rust `conv_assign` 单拷贝 + bool 属性条件臂（`if v.b:`）。**教训：
  改被 ll 门禁钉住的文件（ir_interp.si）必须跑 ll 门禁；flatten 工具
  拒绝默认参数值（正确行为）；孪生变异经辅助方法（属性字典下标赋值
  不可表达）；driver 缓存陈旧伪装成编译器损坏（先删
  ~/.cache/silu-runtime/driver）**。str 临时值追踪**已落地（2026-11-14
  深夜，STATUS.md TODO #1）**：rawlist_str_get/slice 结果按 SSA name
  字符串注册 owned，视图消费后 free 父缓冲；键 = name 字符串（对象
  键在孪生编译版发散）；**函数边界必须 clear**（llvmlite 名字每函数
  重启，残留条目跨函数别名 → double free 实证）；变异经辅助方法
  （字典作本地参数）。配套修 view+view concat 分派缺臂。Rust conv
  未移植追踪（语料无该形状，ll 20/20；出现时门禁响亮拦截）**。
- **interpret 平面退出码映射（2026-11-14 深夜，STATUS.md §3.20）**：
  `silu interpret` 过去丢弃 main() 返回值（退出码恒 0）——visit_Module
  把返回值存 `self.main_return`，cli.run_interpreter 对非零 int
  `sys.exit(rv)`（int 守卫防 mocked 解释器的 MagicMock）。**§3.17 的
  已知边界关闭**：ir_interp 经 interpret 平面跑现在 bail + rc=3。
  raise SystemExit(n) 语义不变；全量 pytest 复跑全绿。
- **wat2wasm 32/32——TODO #5 关闭（2026-11-14 深夜，详见 STATUS.md
  §3.16）**：纯 Silu WAT→wasm64 汇编器对拍 wabt 全语料逐字节一致
  （examples+benchmarks 32 文件，门禁 `wasm/test_wat2wasm.mjs`）；
  playground 摘除 wabt.js（−0.66MB，.wasm 按钮走 wat2wasm.wasm hex
  流）。九类 bug（then 吞体/包裹 RP 截断/裸原子/双 $ 键/op 表缺
  return+store8 错码/result 块类型/空 else/sleb 终止/global 三下标）
  全部差分实证。**教训：token 相对下标（j-N）必须 DBG 探针实证不心算；
  match_close 返回 RP+1 哨兵**。已知性能项 ~2s/KB（逐形字符串累积
  二次方，后续 list+join）。
- **ir_interp 响亮化 + host 退出码（2026-11-14 深夜，详见 STATUS.md
  §3.17）**：int-only 树解释器对子集外程序从"静默求 0/挂死"改为
  两阶段预检 → `ir_interp bail: <原因>` + exit 3（挂死根因 = IR JSON
  裸浮点 const 让解析器在 '.' 上死循环）。连带修 host.mjs 入口返回值
  丢弃缺口——wasm 平面 exitCode 从恒 0 改为 main 返回值（与 native
  一致）。test_run 门禁 INTERP_SKIP → INTERP_LOUD（两平面 bail 消息
  逐字节互拍）；3 三方一致 + 14 loud，五门禁全绿。已知边界：AST
  interpret 平面不映射 main 返回值为退出码（独立小项）。
- **wat2wasm 性能 73.7s→19ms（3800×，2026-11-14 深夜，详见 STATUS.md
  §3.18）**：三连根因——①wasm64 后端默认把 llvm.memcpy intrinsic 展开
  成字节循环（修复：链接 `-mbulk-memory` + shim/bulk_mem.ll）；
  ②单表达式临时值（`SRC[0][n]` 的中间整串拷贝）无人释放 → 泄漏 O(n²)
  字节 → 29K 次 64KB 页 memory.grow（每次 ~1ms）= 二次方（修复：shim
  malloc 256MB 块提交；**2× 翻倍会撞 V8 memory64 提交上限 OOB**）；
  ③wat2wasm.si 逐行化 + T_TXT 直存 token 文本。**遗留正道项：codegen
  层临时值不释放是所有 .ll 工具共有泄漏，修要三平面同步+重钉（独立
  里程碑）**。六门禁全绿。
- **closure 族裁定（2026-11-14 深夜，STATUS.md §3.19）**：真闭包 =
  设计外（FE hoist 响亮拒绝，Rust nested-item 语义）；无捕获嵌套函数
  端到端已支持，新门禁示例 nested_fn.si。**连带修 ir_interp 全局回退
  bug**（call_user 换 env 后读不到模块全局，hoisted 嵌套函数静默求 0
  ——env→genv 回退修复）。run 4+14、backend 18/18、wat2wasm 33/33。
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
- **raw dict 布局**：`{count, filled, cap, mask, table, keys, vals}`
  七个 i64；entry 数组按插入序追加，`filled` 是已用 entry 数；
  reindex 按 entry 序压紧（保序）；int 键的删除不留标记（0 是合法
  键）——entry 存活要问表（`rawdict_int_entry_of`），str 键的删除把
  entry 清零。负载检查只在插入路径（覆盖写永不 reindex）。
- **循环头先核对后判界**：dict 循环每步核对 count/filled/keys
  指针（`_panic_if`×2），list 每步重读长度，str 的 `siter_*` 块序
  cond/body/end；generic 循环带 `pyobj_dict_count/used/entries_bits`
  三个捕获 + `pyobj_dict_watch`。
- **borrowed rawstr**：`_mark_borrowed_str` 登记的结果不被语句释放、
  赋值时拷贝；每个语句开头清表。所有其余 RAWSTR 表达式结果都视为
  "新鲜临时"——新增返回容器内部指针的读路径必须登记。
- **码点偏移表 = 一次有界逐字节扫描**：谓词与计数函数相同
  (`(b & 0xC0) != 0x80`)，循环条件是字节下标 `< len`，哨兵自然落在
  `offs[cp]`。不要按首字节声明的长度跳跃（畸形字节下与计数失配），
  更不要为写哨兵多转一轮（读 `data[len]` 越界）。
- **`rawstr_append` 对任意参数正确**：源字节可以落在目标自己的缓冲
  里（`s = s + s`），此时不 realloc 而是分配-拷贝，旧缓冲在追加拷贝
  完成之后才释放。调用方不需要再为自追加绕道 concat。
- **SSA 值的类型判断用缓存类型比较**：`x.type == ir.IntType(64)`。
  **不要** `str(x.type)`（孪生的类型记录没有 `__str__`，恒为
  `"None"`），**不要** `x.type.kind`（真实 llvmlite 的 PointerType
  没有这个属性），**不要** `isinstance(x.type, ir.IntType)`（文本层的
  IntType 是工厂函数）。`_field_slot` 曾因第一种写法在自举平面上
  把裸 i64 当指针用了一个月。

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
- **`benchmarks/*.si` 全部要过 ir2c（C 后端）**：`test_m5_benchmarks_
  match_cpython` 把每个 benchmark 经纯 Silu 的 ir2c 编译执行对拍
  CPython（record_global/jsonparse 两个在 skip 表里）。新钉板若用到
  C 后端没有的形状，放 `selfhost/`（float_edge、comp_unpack 的先例）
  并登记 CORPUS_IR + test_frontend_parity_corpus + test_llvmlite_text
  PROGRAMS 三处。
- **新钉板还受 rs 神谕字母表约束**：语料里出现的每个形状 rs 都要
  能逐字节镜像（否则 ll 门禁红）。先拿 `silu-conv` 单跑新文件看
  bail 在哪，再决定放 benchmarks/、selfhost/ 还是只进语义门禁。
- **语义测试的源码字符串也是程序**：写错缩进就是死循环（`i += 1`
  顶格写在 while 外，三个平面一起"超时"）。用例先在 pb 式四平面
  脚本里过一遍再入表。
- gates.sh 失败时把完整 pytest 输出留在 `gates-last-failure.log`
  （*.log 已忽略）；屏幕上只有最后 25 行，大面失败时要看这个文件。
  **日志里的一条瞬态失败不要靠重跑放过去**：先看
  `~/Library/Logs/DiagnosticReports/` 有没有 `siluc1-*.ips`——那是对
  "竞态"的证伪，5 份崩溃报告就是这么被当成重跑即绿埋掉的。
- **`clang -fsanitize=address x.ll` 不检查任何东西**：clang 只插桩带
  `sanitize_address` 属性的函数，IR 输入没有。要用
  `tools/asan_run.py`（加属性 + 已知越界读对照）。报告时 macOS 的
  atos 符号化会挂几分钟——先 `symbolize=0` 跑，再事后 `atos -o`。
- **`silu/llvmlite_text.py` 与 `selfhost/llvmlite.si` 是手工保持逐
  字节相同的锁定孪生**（`tests/test_llvmlite_text.py` 锁）。只改
  Python 一侧对 `siluc1` 毫无作用——它编的是 `.si`，而且 `.py` 不在
  siluc1 的依赖表里，连重建都不会触发。改完 `cp` 过去再 regen。
- **`str(记录实例)` 在 Silu 里是 `"None"`**（装箱后非标量走
  `pyobj_str_conv` 的空盒），不是类名或地址。
