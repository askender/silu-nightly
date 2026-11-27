# 会话状态与 TODO（2026-11-10 凌晨，交接锚点）

> 交接快照：当前状态、未决事项、调查现场、关键教训。
> 规约细节锚点仍是 `reference/PROGRESS.md`；本文负责"接下来做什么"。
>
> **v1.25.0 已重钉（2026-11-26）**：语义轮——容器边迭代边改、
> 推导式作用域、dss 借用语义、ll 门禁 verifier；同日续**内存安全轮**
> （§3.37：码点偏移越界读、`s = s + s` 用后释放、`str.find` 字节
> 偏移、自举转换器对 i64 槽实例属性赋值必崩、真 ASan 门禁）。前缀
> 422,537B。版本四件套（__init__/setup.py/AGENTS 钉行/本行）；**tag
> 未打**（发布动作留给用户）。
>
> **换客户端第一站 = §3.37（2026-11-26 续）**：内存安全轮，全门禁绿
> （ir 33/33、ll 32/32×2 含 verifier、语义门禁 231、ASan 门禁 124 +
> 编译器 ASan 门禁 34）。
> §3.36 的"70 探针 ASan 零报告"**作废**（当时没有插桩，见 §3.37）。
> §四 顶部：`upper/lower` 的 Unicode 边界裁决、rs 字母表缺口、ir2c
> str 所有权、一参 get 未命中语义裁决，其余仍用户门控。

## 一、已提交状态

**HEAD = `bced6d9`（v1.18.1，tag 已推 nightly）**，内容：
- cp-offset 双层缓存（rawstr 结构指针键 + pystr 数据指针键）
- 动态层 str 码点语义（len/下标/切片 CPython 对齐）
- 分号拒绝化（三前端对齐）+ 4 测试
- 孪生渲染器 _rstrip/_escape_latin1 线性化（m8 355s 回归修复）
- 前缀重钉×2、CHANGELOG/pyproject/README/PROGRESS/AGENTS 版本四件套
- 提交时门禁：ll 19/19、conv/pyll 19/19、ir 20/20、pytest 1359 通过/2 跳过

## 二、本轮内容（utf8 语料钉板 + 孪生热点扫尾，**已整体提交**）

**⚠️ 事后重大发现（2026-11-11，WASM L1 工作中暴露）**：utf8 轮的
ll 门禁绿是**陈旧 siluc1 二进制**给出的假绿——`llvmlite.si` 的
utf8_byte_len 虽在提交前改好，但 siluc1 二进制在门禁之后才被
重建（flake 实验强制 touch），重建后 bytes-分支在 typed 平面误触发
（bytes 与 str 同为 rawstr 表示，isinstance 恒真 → len() 按 1.18
语义返回码点数 26 → 字符串常量 [27 x i8] 装 36 字节内容）。
**修复**：双孪生 utf8_byte_len 去掉 tuple-isinstance 分支，改为逐元素
`isinstance(ch, str)`（单类型检查两平面语义一致；dynamic 的 bytes
迭代出 int 直接计 1 字节）。附带发现并修复：rust oracle 的
`saved: dict = self.env`（引用绑定）被降级为 rawdict_new 复制——
新增 dict ann_assign 非字面量 RHS 的引用绑定路径（silu-conv.rs）；
bail 消息现带类型与参数序号。

主题：**非 ASCII 语料钉板 + 孪生热点扫尾**。改动清单：

| 文件 | 内容 | 状态 |
|---|---|---|
| `selfhost/utf8_probe.si`（新） | 非 ASCII 语义探针，双平面字节一致，已入 CORPUS_IR | ✅ |
| `reference/diff_harness.py` | corpus += utf8_probe（ir 21/21、ll 20/20×2 实测绿） | ✅ |
| `reference/rust/src/bin/silu-conv.rs` | ① 15 处 chars().count()→.len()（字节数组定尺寸按字节）② typed str 步进切片臂（原先**静默丢步进参数=输出错误字节**，违反铁律）③ len(切片表达式) 非 name 兜底 | ✅ 门禁绿 |
| `silu/llvmlite_text.py` + `selfhost/llvmlite.si` | 新增 utf8_byte_len（含 bytes/bytearray 快分支，与 utf8_len 对齐）；_escape_str/_escape_bytes 改 append+join | ✅ |
| `tools/flatten_codegen.py` | 改写表 3 行：len(…encode)→utf8_byte_len；string_bytes ArrayType 同 | ⚠️ 见三 |
| `tools/siluc_main.c` | rt.o↔rt.ll mtime 配对校验；rt.clang 身份戳（conda LLVM21 vs Apple ld17 LTO 位码不兼容）；run_quiet 失败输出 stderr | ✅ 实测修复链接失败 |
| `tests/test_selfhost_m4.py`（另行提交 bdd39fc） | Linux gates 链接 benchmark 生成 C 补 `-lm`（schedule 层首跑暴露的潜伏缺陷，nbody 的 pow）；Linux gates dispatch 全绿验证 | ✅ |
| `.gitignore`（另行提交） | 加 `.zcode/`（代理会话目录）与 `test.txt`（scratch，内容仅 "test"） | ✅ |
| `tests/test_utf8_runtime.py`（新） | 动态码点九项对 CPython / free-reuse 陷阱 / 50K 线性走查 | ✅ 3/3 |
| `silu/cli.py` | SILU_TB=1 可选 traceback（调试钩子，可保留） | ✅ |
| `AGENTS.md` / `reference/PROGRESS.md` | 本轮记录 | ✅ |

**门禁现状（未提交态）**：ll conv rustconv **20/20** ✅；ll conv pyll **20/20** ✅；
ir fe rustfe **21/21** ✅；性能 m8 0.47s ✅；
pytest **1 failed**（见下）, 1360 passed, 3 skipped。

## 三、已解决：解释器 parity 真回归（本轮修复）

`tests/test_llvmlite_text.py::test_si_converter_interpreter_parity`
曾**真失败**（standalone 可复现，此前两次被误判为竞态）：
`silu interpret <临时目录的 flat+孪生+wrapper>`，喂 jsonparse.si 的 IR JSON，
报 `Runtime Error: ord() expected string of length 1, but int found`。

**✅ 已修复（2026-11-10）**：头号嫌疑坐实——双孪生 `utf8_byte_len`
缺 bytes/bytearray 快分支（`utf8_len` 有）；改写表把 `bytearray(b'…')`
重写成裸 bytes 后，`ArrayType(…, utf8_byte_len(string_bytes))` 以 bytes
调用 → 迭代 bytes 得 int → `ord(int)` 崩。修法：双孪生各补
`if isinstance(s,(bytes,bytearray)): return len(s)`。
验证：定向 28 全绿 → ll conv rustconv 20/20 → ir fe rustfe 21/21 →
全量 pytest 绿 → 整体提交。

**调查现场（历史记录）**：
- 直接 `interpret selfhost/silu_conv_main.si < benchmarks/jsonparse.si`（喂**源码**）**正常出 .ll** —— 孪生/flat 大体没坏；
- 该测试每次现场重新生成 flat（flatten --si）并拷贝当前 llvmlite.si；
- v1.18.1 时此测试绿；本轮改动后开始红。本轮涉解释器平面的改动只有
  改写表 3 行 + 孪生 utf8_byte_len/_escape_* 重写。

**验证次序**（已照此执行完毕）：
1. `$PY312 -m pytest tests/test_llvmlite_text.py -q`（28 全绿）
2. `$PY312 reference/diff_harness.py ll conv rustconv`（20/20）
3. `$PY312 -m pytest tests/ -q` 全量
4. 全绿后**整体提交**（含 utf8_probe/驱动器/测试/文档），消息主题
   "utf8 corpus probe + byte-domain fixes + driver cache hardening"

## 三点五、WASM L2 子集 3 已完成（2026-11-11 第二轮）

**结果**：list[int] 轻量原生运行时（内存式 (ptr,len,cap) 数组 + bump
分配器，不走 pyobj）端到端对拍 CPython 4/4（lists.si 含 append/下标/
len/for-in/while 构建/print(list) 渲染）。上一轮的段错误是**多轮补丁
叠加的文件损伤**——本轮干净重放全部变更，一次通过。

**最小复现（两行即崩，typed 编译的 backend 二进制 SIGSEGV）**：
    acc: float = 0.0
    acc = acc + 1.0
（无 print、无函数也崩；fb = ann+print 不崩 ⇒ 崩点在"普通 assign +
float RHS"路径：set_type 更新 / get_type 扫描 / to_f / decls 四者之一）

**已完成的实现（本轮回退了，设计仍有效，重做时按此恢复）**：
- RUNTIME 增 $alloc（bump+memory.grow）、$li_new/$li_append（倍增扩容
  +memory.copy）/$li_get/$li_set（越界 unreachable）/$li_len/$print_li
- collect_locals 三参化（names+types），for 目标收集
- ann_type：["name","float"]→"f"、["subscript",list,*]→"li"
- emit：list 字面量→$li_new、subscript→$li_get、attribute append→
  $li_append、assign 下标目标→$li_set、for 解糖（fresh idx + $li_len/
  $li_get）、print 按 li/f/i 分派
- 函数参数/返回类型取 IR 节点 4/5 位注解；f64 const 发射原始十进制文本
**已修的坑（重做时注意）**：Gen 的 names/tnames ctor 传同一 list 会
alias（fresh 双 append 失配）→ tnames 必须独立拷贝；assign 目标是裸
字符串而 aug 是包装形；collect 不得递归进值表达式；循环体内注解声明
曾伴段错误（未定论）；wabt 1.0.42 memory64 默认开（--enable-memory64
已不存在）；wabt.js API 是 parseWat + _wabt_set_memory64_enabled(1)。
**调试法**：注释 assign 分支的子步骤 + 退出码二分（段错误吞输出）；
动态平面可跑通后再对 typed 二进制。
**本轮新增教训**：⓮ **git checkout <commit> -- <file> 会静默清掉
未提交的同文件工作**——多轮补丁前先提交或先存档（本会话丢过一次
4b 实现，靠 /tmp 的 exp 副本救回）；⓯ **多个补丁脚本链式 replace
时用错变量（src vs text）会静默只应用最后一个**——补丁脚本本身也
要自查；⓮⓯ 合并教训：**同一文件累积 5+ 轮补丁后应整体重写**（本
轮 backend 重写后门禁立即全绿）。
①生成 WAT 后必须**程序化校验括号平衡**（手写
print_li 尾部多一个括号把 module 提前关闭，报错误导性的 undefined
function）；②多轮区域替换会吞分支（emit_stmt 的 for 分支被后续补丁
抹掉）——改完必须 grep 验证分支存在；③attribute 调用的方法名在 IR
节点 index 2（obj 在 1）；④ir_interp 是 int-only——float/list/str
示例须加进 test_run 的 INTERP_SKIP；⑤**bump 分配器堆起点必须等于
数据段终值**——$heap 硬编码 1024 与 intern 数据段重叠，alloc 踩烂
字面量（str_eq 恒假）；⑥FE 的 json_dumps 对非 ASCII 发 \uXXXX——
自写 JSON 解析器必须处理 \u 转义（ir_interp 原版有，重写时丢过）；
⑦**UTF-8 码点字节长的判断是 (b & 0xC0) != 0x80——三字节 lead 0xE6
& 0xC0 = 0xC0 ≠ 0x80**（曾把 lead 误判成续字节导致切片差 1 字节）；
⑧WAT 前向函数引用在 wat2wasm 完全合法（曾误判为前向引用错误而
浪费多轮）；⑨**带副作用的表达式（alloc/状态变更）绝不能在发射中
求值两次**——print(str) 的 slice 双次调用是本轮最后真凶，单次求值
存 local 是唯一正确模式（对一切"分配型"发射成立）。

## 三点六、WASM L2 子集 4b（str 索引/切片）——已完成并入主线

实现已全部进入 selfhost/wasm_backend.si 并被门禁守护（L2 6/6 含切片
与 upper/lower）；上一轮的独立存档文件已删除（git 847b533 保留快照）。
**验收口径备注**：wasm 平面对不支持构造采用"求值 0（documented gap）"
而非"bail 报错"——与 wasm_plan.md 旧验收条款的字面冲突已在该文件中
显式记录为接受的差异；如需铁律级 bail，须为每个 emit 分支补 escape
通道（待做清单见 docs/wasm_plan.md）。

**本轮已验证的修复（在 wip 里）**：①下标赋值守卫必须先查 kind 再
tag（裸名字 JValue 的 arr=None——`tag(裸名)` 就是此前"float assign
段错误"的真根，动态/typed 两平面同崩）；②切片循环 nxt 必须在 idx
更新**前**计算（否则双重步进，"bb"/"aa" 错位）；③slice 默认值跳过
负数调整（step<0 的 b 默认 -1 被负数调整 +clen → 循环立即空转）。

**✅ 子集 4b 完成（2026-11-12 第四轮）**：str 索引/切片端到端对拍
CPython 5/5（strings.si 含 [::-1]、负索引、多码点切片、中文）。
**最后真凶**：print(str) 的**双重 slice4 发射**（write 的 ptr 与
blen 各调一次 slice4）——两次调用各自 alloc 缓冲，write 读 #1 而
blen 扫 #2——修复：单次求值（slice 结果存 fresh local，write 读
local 两次）。此前三轮的修复全部有效（heap-after-data、defaults
skip-neg-adjust、b-clamp step-guard、nxt 先于 idx、advance 守卫、
guard 的 kind 先行）。**调试法沉淀**：export harness（slice4/clen
导出 + Node 直调 + memory dump）+ copy 循环插桩（idx/off/n/w 打印）
+ 最小化用例（单 print 的 2 行程序）。

## 三点七、WASM L2 子集 5 已完成（2026-11-12）：dict[str,int]

轻量插入序运行时（线性扫描表：$ds_new/set/get/has/len/key——str 键
$str_eq 比较，值 i64；set 未命中时整体拷贝扩容）——对拍 examples/
dicts.si（set/get/len/for-in 键迭代/in 成员/重复赋值更新）全部与
CPython 一致。**同轮修复**：①list 的元素存储 FE 节点是
subscript_assign（非 assign+下标目标）——此前 list[i]=v 静默丢弃，
现按基类型分派 li_set/ds_set；②dict 的标注 arr[1] 是嵌套数组
（["name","dict"]），ann_type 须按 tag+名字判断（arr[1].s 永远是
空串）；③for-in 的循环变量与索引临时不得共用同一 local（键是指针，
+1 后变垃圾指针提前退出）。print(dict) 渲染（{'k': v}）、str.upper/lower（ASCII 域字节变换）
与表达式级方法分派已入运行时并进正式门禁——切片版 strings.si 已
毕业（6/6，含 upper/lower 与 dict 渲染验证）。dict 哈希加速、dict
值类型扩展（float/str 值）待做。

## 三点八、代理代码审查修复轮（2026-11-13）：shim 符号群 bug

四个审查代理（backend/host-shim/build-tests/架构）发现的问题处置：
架构轮 6 个 P1 已全部修复并提交（9e7ca2d）。host/shim 轮 3 个 P1 本轮修复：
①**cStrtod 符号系统性丢失**（4 处）——`bytes[j]===45` 在 j 越过符号位后
永远为假：-inf/-Infinity/-nan 全变正、负 hex 丢号；现统一用前置 `neg`
记录。②**hex p 指数双重取负**（"0x1p-3"→8.0）——parseInt 已含符号，删掉
手动翻转。③**hexFloat 尾数低位置放**——fraction 域必须顶端对齐
（mant <<= 52-(bl-1)）；"0x10" 等整数恰好剩余位为 0，旧门禁全绿是巧合。
④**cReprDouble 小值区间错一个量级**——JS 对 [1e-6,1e-4) 给定点形式
"0.000xyz"，旧代码 decpt=idx 从不看前导零：指数阈值永不触发且重构分支
输出错位数；改用**调整指数 decpt-1-lz**（lz=mant 前导零）判阈值，mkExp
同步剥前导零。15 值直接对拍 CPython repr 全绿。
**门禁加固**：test_shim_ref.c 补 10 条符号用例（±inf/±nan/±hex/p 负指数
），门禁 148→158。廉价 P2：calloc 乘法溢出检查、free 双重释放 shim_die。
四门禁：compile 20/20、run 2/2、backend 6/6+web 冒烟、shim 158/158。

**遗留（下轮候选）**：P2 %e/%g 半偶平局（JS toExponential 半上 vs C
半偶，"2.5" 的 %.0e 触发；修法=指数路径走 fixedExact 式精确展开，中等
复杂度）；P2 strtol 溢出回绕 + \v\f 空白缺失；P3 若干（agent 报告在案）。

## 三点九、backend 审查代理两轮修复（2026-11-13 深夜）：分派层补全

**dict 值类型扩展（2026-11-14）：dict[str, float] / dict[str, str]**：
值槽统一 i64——float 走 f64.reinterpret_i64 位打包、str 走指针；类型标
记 ds/dsf/dss 由 ann_type 从 ["subscript",["name","dict"],["tuple",
[[K],[V]]]] 解析（V 是 ["name","x"] 节点，**取值要三跳 elem**：tuple→
kv 数组→val_t→名字字符串——两次写成一跳/两跳被 get_type 兜回 "ds"
静默错误，靠 print 分派与 reinterpret 缺失的 wat2wasm 类型错暴露）。
emit 分派面：subscript 读/写、print（$print_dsf 经 fmt_double repr、
$print_dss 带引号）、len、for 键迭代、aug（dsf/dss 响亮拒绝）；assign
传播守卫防空 dict 字面量 "ds" 把已声明 dsf/dss 降级。门禁示例
dicts_f.si 对拍 CPython 绿（渲染 {'mon': 21.5} 插入序 + repr float）。

**dict 哈希加速（2026-11-14）**：线性扫描 + 整表 realloc（O(n) 插入）
→ djb2 哈希索引 + 开放寻址线性探测（O(1) 查找）。结构：header
(count, data, hmask, htab) 32B——entry 数组追加式**保持插入序**（迭代
/渲染/for 键序全部不变，CPython 语义 ✓），htab 槽存 entry idx+1（0=空），
满载即 grow（cap 8→16→32，逐键重哈希）。**死循环教训**：ds_set 首版
"先 find 后 grow"——第 9 键时表满无空槽，find 的线性探测永转（N 键
二分 7/8 绿、9 卡死定位）；修复 = 先 grow 再 find（load factor < 1
恒有空槽）。扩容压力示例 dsbig.si（12 键 + 更新 + 插入序渲染）对拍
CPython 绿。**构建工具链首笔真实 SIGSEGV 观测**：build.py web 一次
silu_conv SIGSEGV（backend.ll 编译期），重跑未复现——TODO #2 竞态面
从"无复现证据"升级为"偶发已观测"，仍待更宽窗口（CI 慢机）再实施
flock 修复。

**P2 边角批（2026-11-14）：bool repr + 负下标**。比较/and/or/not/bool
常量携带类型标记 "b"（expr_type 六臂 + 短路臂 + const BOOL + ann_type
bool→"b"，assign 传播加 "b"）——print 走 $print_bool（True/False repr，
scratch 90-98；**笔误把 l/s 写到 98/99 而非 96/97 → "Fa\0\0l"**，
write 5 字节含两个 NUL 抓获）；bool 参与 i64 算术与 CPython 恰好一致
（True+1=2）无需特判；str(bool) 响亮 gap。$li_get/$li_set 补负下标调整
（$str_get 原有）。门禁示例 edge.si 对拍 CPython 绿。

**门禁扩容 6→9→10→11**：新增 examples/bool_ops.si（and/or/not 短路、break/
continue、嵌套 while True、复合 while 条件）、float_ops.si（浮点比较
六臂、f64.pow 宿主导入、浮点 floordiv/floormod、str(float)）、
aug_sub.si（list/dict 下标读改写 + 渲染）。

**ir_interp 补全（2026-11-14，解除 bool_ops SKIP）**：truthy/eval_int
补 and/or/not（条件域短路真值；int 域 0/1），exec_stmt 补 break/continue
（信号 2/3，while 循环处理传播）。三平面 run 门禁 2/2→**3/3**
（bool_ops 毕业）。注意：改 ir_interp.si 后 /tmp/ir_interp_native 是
existsSync 缓存——必须删除强制重建（陈旧二进制假绿教训②又验一次）；
wasm 侧 interp.wasm 同步 build.py interp。aug_sub 永久 SKIP（ir_interp
int-only 无容器，容器平面归 backend 门禁）。

**P0×3（均实证后修复）**：①and/or/not 无分派静默 0 → 短路真值发射
（fresh temp + if 链，操作数各求值一次）；②break/continue 被静默丢弃
（while True 死循环）→ Gen 加 loop_exit/loop_top 标签栈（循环嵌套唯一
标签 $weN/$wtN 等由 tmp 计数生成，不占 local）；③未注解 str/list/dict
assign 丢类型（str 相加=指针相加）→ assign 传播 f/s/li/ds 四类。

**P1 修复**：$str_from_int 负号堆下溢（缓冲 22、q 起 p+20、NUL p+21
——19 位负数曾覆盖相邻对象尾字节）；print(dict) 冒号后补空格（CPython
{'k': v}）；浮点比较六臂 f64.lt 等（此前 i64.lt_s 编译失败）；for-dict
循环变量 set_type "s"（曾打印指针值）；return 按 rtype 走 to_f/to_s；
Json.string 补 \r\b\f；Json.number 双重负号（start 移到负号消费后）；
collect_locals 平行表失同步（assign 重复赋值 types 多 append → ann 类
型左移错挂，ann_assign 对已存在名字就地更新）；整型 /= 响亮 unreachable
（CPython 会变 float，子集不支持）；floordiv/floormod 操作数单次求值
（曾 2-4 次重复发射——print(str) slice 事故同型残留）+ 浮点臂
（f64.floor(f64.div)；% = a - floor(a/b)*b，fresh 临时须 set_type "f"）。

**响亮化（铁律）**：非空 list/dict 字面量 unreachable（元素曾静默丢弃
——注意空字面量 IR 是 ["list", []]，判空用 elem(node,1).arr）；str(float)
走 fmt_double scratch（单操作数限制已注释）；float(str)/str*int /
step=0 切片 unreachable；memory.grow -1 检查（memory64 返回 i64！）。

**连带修复**：宿主 fmt_double 补 NUL 终止（print_f64 用显式长度无碍，
但 str(float) 的 $str_blen 扫 NUL 读到历史残留 → "7.55.0"）。
main() 尾部死代码删除；头部 gap 清单全面刷新。

**语言级 bug 调查结论（2026-11-14）：误报**。代理复现 na.si 的输出
"l","","l" 经逐层分析语义正确（r2 = stmt4.arr[1].arr[1] = nm，
nm.s 本来就是 ""）；四平面探针（嵌套同函数调用 inc(inc(inc(0)))、
twice、带深度 4）在 CPython/参考解释器/原生编译/wasm 后端全部一致
（3,12,4,9）。**真缺陷是 aug_assign 不支持下标目标**（l[0] += 1 的
目标提取得空串 → 空 local 标识符编译失败）——已实现：subscript 目标
读改写（li_set/ds_set + 复合运算，容器/索引/值各求值一次进 fresh
local，+= -= *= 支持、其余 unreachable）；collect_locals 对下标目标
不再收集空名 local。门禁示例 aug_sub.si 对拍 CPython 绿（list/dict
渲染一并覆盖）。附带记录：ir_interp 平面缺 break/and 分派
（bool_ops/aug_sub 已入 INTERP_SKIP，补全待做）。

## 三点十、构建竞态 flock 修复（2026-11-14，TODO #2 落地）

**触发**：dict 哈希轮的 build.py web 首笔真实 silu_conv SIGSEGV（重跑
未复现）——从"无复现证据不动"升级为"偶发已观测"。修复设计早已备好，
本轮实施：①**可重入 flock**（.silu_build.lock，REPO 内，深度计数支持
ensure_siluc→ensure_converter 嵌套；锁内双检 mtime——排队进程解锁后
跳过已完成重建）；②**原子落位**：silu build 产物、typed_codegen_flat.si
再生、clang 驱动、save_ll 全部走 write-to-temp + os.replace（读方永不
撕读）。**并发压测**：4 fork 进程强制 touch 源后并发 ensure 全部三
工具——仅一次 flat 再生/一次 conv 重建/一次 siluc1 重建（锁生效证据：
输出无重复 building），全部 ok 无撕读。**回归**：ll 20/20、ir 21/21、
test_llvmlite_text 28/28（历史竞态受害者簇）、全量 pytest 绿。
.gitignore 加 .silu_build.lock。

## 三点十一、wasm 后端进语料（2026-11-14）：全局变量 + int 键 dict

**语料探测**（benchmarks 15 文件：fe → wasm_backend → wat2wasm → 执行
→ 对拍 CPython）：此前 7 个 RUN / 8 个失败；本轮实现两个大缺口后
**8 个 PASS**（arith/fib/float/list/mandelbrot/string/trees/dict——
全部输出逐字节一致），剩 6 个 WAT-ERR（每文件一个具体缺口，见下）+
fannkuch 1 个执行 TRAP。

**缺口 1：模块级全局变量**（nbody/spectral 等的 NO-EMIT 根因）：顶层
assign/ann_assign → wasm global（global.get/set；f → mut f64）。实现：
pass 0 收集 GNAMES/GTYPES（ann_type 定型；裸 assign 用 top_type 从首
初始化器推断）；函数 Gen 与 main Gen 都注入全局类型（**漏 main 注入
曾让方法分派 recv 变 "i" → (call $) 空名**）；局部/参数名判定用
g.names + **新 Gen 字段 g.pars**（参数名不进 names——曾把
digits_sum(n) 的参数 n 误判全局 → 读走 global → 返回值错成 1）。
**语义对齐**：函数内 aug 全局在 native 平面是响亮拒绝——wasm 的
全局 aug 臂用 **CTX[0] list 变异标记**限定 $silu_main 顶层。首版用
模块级 bool flag（MAIN_GEN = True）**静默失效**——本程序由 Silu 写
成，函数内 assign 全局 = 局部遮蔽（正是它自己发射的语义），flag 永远
False → 顶层 aug 全走局部 → 8 示例回归 undefined local。**教训：
backend 的全局状态要用 list 变异（引用语义），bool flag 会被自己的
作用域规则吃掉**。函数读全局 ✓（CPython 对拍 globals.si 绿）。
**WAT 坑**：global 声明必须带初始化器且 mut 类型与初值是两个并列子项
——`(mut i64 (i64.const 0))` 会被 wat2wasm 拒。

**缺口 2：int 键 dict**（dict.si 的 DIFF 根因）：键 i64 值直接比较
（乘法混淆 hash），结构体复用 $ds_new 布局；$dsi_find/set/get/has/
print_dsi + **$dsi_grow**（**grow 必须按键类型重哈希——首版共享
$ds_grow 用 str 版 djb2 扫 int 键指针 → 错位 → len 895 vs 500**）。
类型标记 dsif/dsis（int 键 float/str 值）已进 ann_type/分派面、
render 响亮 gap。examples/globals.si 新增（13 输出对拍 CPython）。

**剩余 7 项处置完毕（2026-11-14 深夜），语料 11/15 实质 PASS**：
①fannkuch：`[0] * n` **list×int 重复**（$li_repeat + expr_type "*" li
臂）+ **非空 list 字面量**从响亮 trap 改为 build-via-append（单次求值，
float 元素位打包）；②nbody/spectral：**list[float]**（"lf" 标记，
li_get/li_set 位打包、for 元素 "f"、print_lf、append reinterpret）+
nbody 顶层裸 assign 全局的 top_type **缺 const 臂**（["const",...] 外
层是 ARR，kind 检查全 miss → 兜 "i"）；③spectral 的 lf 下标赋值走
ds_set——**lf 被误并进 dict 值臂**（setter 默认 ds_set）——最小复现
mini1（v[1]=9.5 后读变 1.0）定位，lf 单独 li_set 臂；④aug 下标/全局臂
的 rhs **双次求值重构**（副作用安全，float 臂 fresh 标 f）；⑤
wordcount/knucleotide：**dict.get(k[,default])**（$ds_get_or/
$dsi_get_or 单次求值）+ **input() 内建**（getchar 行读，4096 上限）+
未知 callee 响亮化——两程序仍 TIMEOUT（**stdin 数据程序**，探针空
stdin 假死，接入 diff_harness 的 stdin 机制后对拍）；⑥jsonparse ×2：
pyobj 类构造响亮 unreachable（子集外 ✓）。

**语料账（最终）**：**13/15 语义正确**——wordcount@300000 修复后
逐字节一致（total 300000 ✓）；knucleotide@n=3000 对拍一致（31ms），
**n=200000 是 O(n²) str 构建**（`dna = dna + "A"` 循环——CPython 有
refcount 原地优化而 wasm 每次全拷；语义正确，待 strbuf/rope 缓解，
已知性能项非 bug）；jsonparse ×2 = pyobj 类子集外（响亮）。

**find 满表剪断的假命中 bug（wordcount 误计 4 的根因）**：ds_set 修了
grow-first 但**纯查询路径（get/get_or/has）遇满表**仍死循环——tries
剪断首版返回**最后探测槽的 ei（非 0）**→ 满表 miss 被当命中（get_or
返垃圾 entry 值 → count 虚高）。修复：剪断分支显式 `ei = 0`（两处
find）。定位链：wordcount 误计 4（与规模无关）→ get_or miss 插桩
（miss 全部正常，每键恰一次）→ per-key diff（4 键各 +1）→ w6/w12
抽查盲区（没打印出错键）→ **满表 get_or 的 tries 剪断返回值**实锤。
教训：**剪断分支的返回值必须显式归零，"探测到一半"的 ei 不是 miss
信号**；抽查 print 的键选择要覆盖出错路径。

## 三点十二、str ABI v2：knucleotide 全尺寸线性（2026-11-14，TODO #2 关闭）

**动机**：knucleotide@200000 的 `dna = dna + "A"` 循环——旧 ABI（裸
NUL 结尾字节串）每次拼接 O(n) 扫描 + O(n) 全拷 = O(n²)，200000 迭代
超时 + bump 分配器 40GB 消耗 → `$alloc` memory.grow -1 trap。

**新 ABI（CPython refcount 优化的无 refcount 等价物）**：
- **16 字节小端前缀 [blen][clen]** 置于 NUL 结尾字节之前，指针仍指向
  字节区——str_eq/djb2/write 等字节级消费者零改动，blen/clen 变 O(1)
  load。字面量在 data 段内嵌前缀（i64_le_wat 转义），intern 返回
  off+16。
- **值语义绑定（$s_copy）**：assign/ann_assign、global.set、调用实参
  （表达式级+语句级）、dict 键与 str 值存储、for-dict 键变量——每个
  str 绑定独占缓冲，这是扩展合法性的前提。
- **窄窗原地扩展（$str_extend）**：`x = x + e` / `x += e`（局部与全局
  两路，is_str_window 编译期判定）→ 堆顶（缓冲尾==bump 顶）+堆基
  （前缀≥$heap_base，字面量绝不原地改）双守卫命中即 O(len(e)) 原地
  写；否则回退 $str_concat 全拷（concat 本身从不 mutate——dict 值读出
  的指针即使堆顶也不会被 `$d[k] + "?"` 改写）。
- **ASCII 快路**：blen==clen 时 slice4/get 的码点→字节偏移直取（省
  逐码点走链）；concat 的 clen 免扫描（两操作数均纯 ASCII 则和即
  clen）；非 ASCII 走 $cp_scan 兜底。upper/lower 保持源 clen。
- **新 RT 函数**：$str_extend/$s_copy/$cp_scan/$str_from_f64（to_s 的
  float 分支从"共享 scratch 指针"改为真对象——旧形态在新 ABI 下无前缀
  可读，且两操作数共享 scratch 的文档化缺陷一并消除）。

**本轮连环抓出的 bug（全部差分暴露）**：
1. `s += e` 纯名字 str 目标此前落 i64.add fallthrough = **静默指针
   算术**（垃圾字节无报错，铁律违反）——顺带修复。
2. **slice4 按源串长度分配**：每刀 bump O(源串) 字节，n 刀 = 二次方
   堆耗（40GB → grow -1）。缩放二分（5000→46ms/10000→911ms/20000→
   15s）+ 只切片/只 dict 隔离定位。修 = 选中码点数 ×4B 最坏界。
3. `top_type` 无 name 臂：`u = s + s` 裸全局推断 "i" → print 打指针；
   修 = pass 0a 先收集注解名（ANNTYPES/ann_lookup）。
4. `in` 表达式类型标 "i" → print 渲染 1 非 True；`$ds_has` 本返 0/1，
   改标 "b"。
5. print_dsf 对 fmt_double scratch 调 $str_blen（垃圾前缀）→ 改用
   返回长度。
6. concat 首版把字节拷进前缀区、from_int 的 blen 含 NUL 地址（差 1）
   ——**ABI 换代后每个构造函数"返回指针/前缀/字节"三段关系逐个对表**
   是必须的验收动作。

**验收**：backend 门禁 13→**14**（新增 wasm/examples/strbuf_sem.si：
别名/字典键值所有权/扩展循环/中文窗口/全局 +=/实参拷贝/for 键拷贝/
`x = x + x` 回退/str(int)·str(float) 拼接）；语料 **15/15**（13 个
逐字节一致，knucleotide@200000 **45ms**、wordcount@300000 23ms；
jsonparse ×2 SKIP=pyobj 子集外 + stdin 待 #3）；compile 20/20 + web
冒烟（WAT 字节一致）。语料探针脚本 /tmp/corpus_probe.py 重写（计时 +
LOUD/SKIP 分支），**探针自身的 bytes-vs-str decode bug 曾制造全红假象**
——先验地看一眼 diff 内容再下结论。

**run 门禁 40 分钟悬死的真凶（2026-11-14）**：strbuf_sem.si 不在
INTERP_SKIP → test_run 把它喂给 ir_interp（int-only）→ **崩/挂**
（head-30 截断 SIGSEGV、全程序 spin，native/wasm 两形态都复现；逐行
二分 + 单构造最小化确认是**状态依赖的 ir_interp 自身缺口**，fe/
ir_interp 两文件本轮零改动=非回归）。处置：strbuf_sem 入 INTERP_SKIP
（容器平面归 backend 门禁，既定纪律），**ir_interp 对不支持构造的
"崩/挂"而非响亮 gap 记为已知问题**（int-only 边界无声响化；与 backend
的 unreachable 纪律不同——ir_interp 是参考实现风格，响亮化已于
  §3.17 落地（两阶段预检），深度帽 2026-11-17 补齐（见 §3.22））。
  教训：**给示例集新增文件要过一遍四门禁的每一门**——test_run
自动吃 examples/ 全目录，新示例会静默进入不兼容的解释器平面。

## 三点十三、语料门禁正式化 + stdin 管道（2026-11-14，TODO #3 关闭）

- **`wasm/test_corpus.mjs` 入仓**（/tmp 探针转正，会话间不再丢失）：
  13 个非动态 benchmark **全尺寸**逐字节对拍 CPython + 打印 wasm 执行
  计时（knucleotide@200000 40ms / wordcount@300000 20ms = str ABI
  金丝雀）；jsonparse ×2 喂 scripts/gen_json_input.py 生成的共享文档，
  CPython 正常解析、wasm 断言**非零退出**（pyobj 构造点响亮陷阱——
  真语义对拍等 TODO #4 pyobj 解锁）。backend 二进制缺失时经 PY312
  自动构建。**execFileSync 的 timeout 是毫秒**——首版写 600 让
  CPython knucleotide（~3s）ETIMEDOUT 假红，改 600000。
- **stdin 管道**：test_backend 支持 `<示例>.stdin` sidecar（存在即双端
  喂养 wasm runWasm 与 CPython execFileSync input）；新示例
  stdin_demo.si + stdin_demo.stdin 守护 input() 端到端（backend 门禁
  14→**15**）。stdin_demo/strbuf_sem 同入 run 门禁 INTERP_SKIP
  （ir_interp int-only，见 §3.12）。
- 门禁现状：compile 20/20 · run 3/3 · backend 15/15 + web 冒烟 ·
  corpus 13/13 + loud 2/2 · shim 252/252。

## 三点十四、记录类子集 + jsonparse 解锁（2026-11-14，TODO #4 前半）

**范围**：扁平记录类（class_def：注解字段、无方法/无继承）+ match 窄化
+ 记录流经动态容器。**记录单态化**路线——不需要通用 pyobj 装箱：构造
器 = [tag=类序+1][字段槽]，字段按类静态类型存（str 字段构造时 s_copy，
记录拥有其字符串）；match = tag 比较链 + 按类静态类型抽字段（str 绑定
拷贝、容器绑定引用）；通配 `case _` = else；守卫/位置模式/未知类响亮。
不透明 i64 槽承载记录指针流经裸 list/dict，match 处再静态化。

**连带修复/实现（每条差分实证）**：
- **ann_type 裸 `list`/`dict` 名字臂**：`o: dict` 字段曾推断 "i" →
  `o["k"]` 把 dict 当 list（li_get(dict, key指针)——trace 显示
  len=2（dict.count）、idx=1382（key 指针）才定位）。
- **`ls`（list[str]）标记**：len(subscript)→str_clen、append/for 绑定
  拷贝；`len(list)` 本体必须仍是 li_len（曾错改成 str_clen 读 cap）；
  print(ls) 响亮。
- **read_line 可增长**（倍增缓冲）：旧固定 4K scratch 会**静默截断**
  jsonparse 的 84KB 单行文档。
- **n 元 and/or（P0 级既有 bug）**：FE 发射**扁平操作数列表**，旧二元
  发射把第三操作数**静默丢弃**——`pos < len and s[pos] >= "0" and
  s[pos] <= "9"` 曾恒少一项；bool_ops 门禁全绿也没抓到（全是二元链）。
  新 emit_bool_chain 递归嵌套 if；**操作数从 arr[1] 起（arr[0] 是
  tag 字符串——把 tag 当节点喂 emit_expr 会同裸名一样段错误）**。
  and_or_nary.si 门禁（含短路副作用计数与全假 or——旧 or 初值 1 的
  形状）。
- **to_s 动态串**：无返回注解的调用携带的是动态字符串——str_from_int
  会把指针打成十进制数字（jsonparse 的 name 曾变成 "440119"）。仅
  构造器 str 字段对非 const 的静态 "i" 参数按指针处理；`str()` 内建
  保持 int 强转（print(42) 形状不变）。
- **脏形参拷贝消除**：$s_copy 实参保护只在 callee（传递闭包）确实
  窄窗扩展 str 形参时需要——walk_dirty 单趟扫 assign/aug 窗口 +
  call 边，FDIRTY 不动点。jsonparse 84KB 文档曾每次调用全拷
  （~9000 × 84KB ≈ 750MB bump → grow -1 trap、18s）；现 9ms。
  walk_dirty 守卫：attribute 调用（无平名 callee）与空数组（call
  节点尾随 []，tag 会越界）。
- **pass 重排**：pass 0（全局类型推断）挪到 pass 1（函数注册）后——
  顶层 `w = grab(...)` 曾推断 "i" → print 打指针、len 走 li_len
  （"1407 25185"——25185 = "ab" 的字节小端读数）。
- **`case` 不能做变量名**：自举 FE 的解析器把它当关键字（"expected
  end of line"），Python FE 宽容——**两前端的又一处分歧**；walk_dirty
  还需防裸 STR/空 ARR 进 tag()。

**jsonparse 解锁（语料 14/15）**：全尺寸文档（gen_json_input，3000
对象）**9ms 逐字节一致**（参照平面 = silu interpret——CPython 无自动
记录构造器语义，test_match_class.py 既定做法）。jsonparse_json 仍响亮
（需 Json tagged-union + json_* builtins + 隐式装箱，TODO #4 后半）。

**门禁**：backend 15→**17**（record_sem.si：别名/字段所有权/通配/
先匹配优先/经函数构造；and_or_nary.si）；run 门禁 INTERP_SKIP 扩
record_sem/and_or_nary（ir_interp 对 str/类程序崩/挂，见 §3.12）。

**教训**：①**给示例/语料新增文件要过每一门**——run 门禁自动吃
examples/ 全目录，strbuf_sem 曾让 ir_interp 崩/挂 40 分钟；②探针
喂 stdin 用 `new Uint8Array(str)` 产生 [0,0,0]——必须 Buffer.from；
③execFileSync 的 timeout 是毫秒；④调试打印走 stdout 缓冲，SIGSEGV
会吞掉全部输出——wasm 宿主跑同源码可把栈溢出变可见 trap；⑤**先写
CPython 期望再写测试**——本次又栽在参数序上（g(2,9) 的 i=9,n=2）。

## 三点十五、Json 装箱层——语料 15/15 封顶（2026-11-14，TODO #4 完成）

jsonparse_json 需要 RFC S3 的 tagged-union：每个 Json 值是 16B
{tag i64, payload i64} 块（payload = 裸值/指针）。wasm 后端实现：

- **$jbox(tag, payload)** 分配块；RT json_tag/int/bool/str/list/dict =
  载荷读取（tag 表 0=null 1=int 2=float 3=bool 4=str 5=list 6=dict，
  与 interpreter.py 的固定表逐位对齐）；**json_free = 文档化 no-op**
  （bump 分配程序期回收，interpreter 的 json_free 本就返回 0）。
- **类型标记 "J"**：ann_type 裸 `Json` 名 → "J"（块指针、引用语义、
  绑定不拷贝）；fn.rtype = "J" → expr_type(call) = "J"。
- **返回装箱**：rtype "J" 的 return 按静态类型分发——"J" 直通（嵌套
  Json 调用不二次装箱）、li→5、ds→6、s→4、i→1、f→2（reinterpret）。
- **json_* 分派**：emit_expr/emit_stmt 的 call 分派在 class/fn 查找
  之前；json_free 语句级 drop；expr_type 补 json_list→li、json_str→s
  等（`names.append(json_str(w))` 的 append 拷贝靠它）。
- `list[Json]`/`dict[str,Json]` 无需新容器：槽位本就是 i64，装块
  指针即可；`return items`/`return o` 的隐式装箱由 return 分发覆盖。

**jsonparse_json 全尺寸 8ms 逐字节一致（参照 = silu interpret）**
——第一发全中（记录类/动态串/脏拷贝消除等前置修复直接铺平）。
**语料 15/15 全部逐字节一致——L2 语料完整达成**：13 个对拍 CPython +
jsonparse ×2 对拍 silu interpret（参照解释器平面），全部全尺寸。

## 三点十六、wat2wasm.si 语料 32/32——TODO #5 关闭（2026-11-14 深夜）

纯 Silu 的 WAT→wasm64 汇编器对拍 wabt（差分 oracle）全量逐字节一致：
wasm/examples + benchmarks 全部 32 文件，经 fe→backend→WAT→
wat2wasm.wasm 产出二进制 ↔ wabt CLI 组装同一 WAT，逐字节相等。
**门禁入仓 `wasm/test_wat2wasm.mjs`**（自动枚举两目录；prereq：仓库根
./silu_fe、/tmp/wasm_backend_native、wat2wasm CLI、
wasm/artifacts/wat2wasm.wasm）。

- **playground 摘除 wabt.js（−0.66MB）**：index.html 的 "Compile →
  .wasm" 改走 modules.wat2wasm——后端吐 WAT 文本直接喂 wat2wasm.wasm，
  hex 文本流宿主解码（2 hex 字符/字节；Silu 字符串无 NUL）。build.py
  TOOLS 清掉 9 个 /tmp 调试条目（fresh checkout 的 build.py web 本会
  立即崩）。wabt.js/WABT_LICENSE 移出 git。
- **本轮九类 bug 全部差分实证后修复**（详见 docs/wasm_todo.md §五.8）：
  then 体吞没 / 包裹 RP 截断（pd 计数）/ 裸原子 unreachable / 双 $
  名字键 / op 表缺 return+drop 且 store8 错 0x3F / result 块类型 /
  空 else 省略 / sleb 终止符 / global 臂三处下标。
- **输出形态**：hex 文本流一行（宿主 Buffer.from(hex,'hex')）；模块
  magic + wasm64 version `01 00 00 00`。
- **性能项已关闭（§3.18 3800× 修复覆盖）**：本条曾记 ~2s/KB——§3.18
  的逐行化 + T_TXT 直存落地后实测 wat2wasm.wasm 对 46KB WAT（mandelbrot
  全量）**18ms**（host.mjs 端到端），二次方累积已消除。
- **结构（~1200 行）**：tokenize（kind/pos/len 三列表）→ structure
  （imports/globals/memory/export/data/funcs 五收集，top-level 形整体
  跳过）→ emit_form（后序折叠 WAT；block/loop/if 前序头 + 条件；
  OPN/OPC/OPE 算符表，OPE≥0 = 默认 memarg）→ emit_section/emit_all
  （types 按首用序 = imports 先于 funcs；memory 节带多内存计数字节
  `01`；export kind func=0 memory=2）。

## 三点十七、ir_interp 响亮化 + host 退出码语义修复（2026-11-14 深夜）

int-only 树解释器 selfhost/ir_interp.si 对子集外程序过去静默求 0
甚至挂死——**挂死根因**：float const 在 IR JSON 里是裸浮点
（`["const", 0.0]`），Json 解析器 number() 消费整数位后停在 '.'，
value() 再派发 number() 又不消费——无限循环（strbuf_sem 40 分钟悬死）。
修复三层：

- **解析器加固**：非 int 数字（. e E）/未知字符/转义串/越界 → err 标记，
  各容器循环短路。
- **两阶段预检**（check_block mode 0/1）：pass A 收集 func_def 名，
  pass B 全树校验 int-only 白名单（aug_assign 仅 name 目标、call 仅
  print+用户函数、const 仅 int）——首个违规入 ERRS，main 打
  `ir_interp bail: <原因>` 返回 **exit 3**（对齐 Rust oracle bail 惯例），
  先于任何程序输出。
- **err 标记展开**：exec_stmts 每步检查点、while 体检查点、eval/fallthrough
  全部落 err——运行期永不静默 0。

**连带发现并修复 host.mjs 语义缺口**：`ex[entry]()` 一直丢弃入口返回
值 → wasm 平面 exitCode 恒 0（native 驱动是把 main 返回值当进程退出码
的）。现 main 返回值 → exitCode（BigInt→Number）。die()/trap 路径不变。

**test_run 门禁改版**：INTERP_SKIP（14 项静默跳过）→ INTERP_LOUD 断言
——两平面各自响亮（exit≠0）、bail 消息**逐字节互拍**、退出码互拍；
3/17 三方一致 + 14 loud。五门禁全绿：compile 20/20（含 split 管线重建
的 siluc1.wasm 与 native 逐字节互拍）、shim 252/252、backend 17/17、
corpus 15/15、run 3+14。

**已知边界**：`silu interpret` 平面（AST 解释器）不把 main 返回值映射
为退出码（cli.py run_interpreter 丢弃返回值）——ir_interp 经该平面跑
时 bail 消息仍打印但 rc=0。改 cli.py 是独立小项（pytest 期望值爆炸
半径未查）。另：test_run 的 native interp 构建从 existsSync 缓存改为
mtime-newer 重建（教训②的门禁侧防线）。

## 三点十八、wat2wasm 性能：73.7s → 19ms（2026-11-14 深夜）

消融二分定位（微基准 + 变体矩阵，全部 wasm 模块计时）：

1. **shim memcpy 逐字节循环**：llvm.memcpy intrinsic 在 wasm64 后端
   默认展开成内联字节循环（~60MB/s）。修复 = 链接加 `-mbulk-memory`
   （后端才有权把 intrinsic 降为 memory.copy 指令）+
   wasm/shim/bulk_mem.ll（llvm.wasm.memory.copy/fill 直写的符号版，
   clang 直编 IR 文本，无需 llc）。**教训：给 .ll 内建换实现，flag
   加在链接步骤；单独链一个实现没人引用**。
2. **泄漏临时值 × 页粒度 grow**：单表达式 `SRC[0][n]` 的 `SRC[0]`
   中间拷贝（list[str] 值语义读必拷）无人释放 → 逐字符 tokenize 泄漏
   O(n²) 字节（46KB 输入 = 2.1GB）→ 29K 次 64KB 页 memory.grow（VM 侧
   每次 ~1ms）= 27s。shim malloc 改 256MB 块提交（**2× 翻倍 overshoot
   会撞 V8 memory64 提交上限 → OOB trap**，实测）。
3. **wat2wasm.si 逐行化**：`split("\n")` 一次 + token 文本直存 T_TXT
   （ttext 不再切片 SRC；data 解码走 T_TXT）→ 泄漏 O(n×行长) ≈ 50MB。
   fib 19ms（3800×），语料 32/32 逐字节不变。

**遗留正道项**：codegen 层单表达式临时值不释放是所有 .ll 编译程序的
共有泄漏（fe/interp/siluc1 同样受累，只是输入小不触发）——修要动
Python + selfhost 孪生 + Rust oracle 三平面（.ll 字节变化 → 重钉），
列为独立里程碑；shim 块提交使其从"二次方挂死"降为"线性泄漏"。

六门禁全绿：wat2wasm 32/32（19ms/fib）、shim 252/252、run 3+14、
backend 17/17、corpus 15/15、compile 20/20、playground smoke ✓。

## 三点十九、closure 族裁定 + nested_fn 语料（2026-11-14 深夜）

**设计裁定**：真闭包（嵌套函数捕获外层局部）= 设计外——FE hoist pass
响亮拒绝（"nested function 'X' captures 'n'; pass it as a parameter"，
Rust nested-item 语义），三平面一致，非 gap。**支持面 = 无捕获嵌套
函数**（hoist 成模块级 `outer__inner`），端到端已通。

- 新门禁示例 `wasm/examples/nested_fn.si`：嵌套调模块函数 + 读模块
  全局、双层嵌套（def in def in def）、模块级前向引用、嵌套内递归、
  三面输出互拍。三门禁自动吃（run/backend/wat2wasm）。
- **连带真 bug（新示例首轮即抓到）**：ir_interp 的 call_user 换新 env
  后读不到模块级全局——hoisted `outer__inner` 读 BASE 静默求 0，
  outer(4) 出 10 而非 410（CPython/native/wasm 后端三面全对）。
  修复 = **env→genv 回退**：genv 与模块 env 初始为同一 dict，
  call_user 只换 env；get_int 先 env 后 genv。run 门禁 4 三方一致
  + 14 loud，backend 18/18，wat2wasm 33/33。

## 三点二十、interpret 平面退出码映射（2026-11-14 深夜）

`silu interpret`（AST 解释器）过去丢弃 main() 返回值——visit_Module
调 candidate() 不接返回值，进程退出码恒 0；而 native 驱动和 wasm 平面
（§3.17 修的 host.mjs）都是 exit(main())。修复：visit_Module 把
main() 返回值存到 `self.main_return`（BaseASTProcessor 类属性，所有
子类共享），cli.run_interpreter 访问后 `sys.exit(rv)`（仅非 0 时）。
三条路径实测：main 返回 3 → rc=3；返回 0 → rc=0；**ir_interp 经
interpret 平面跑 → bail 消息 + rc=3**（§3.17 的已知边界就此关闭）。
raise SystemExit(n) 的既有语义不受影响（BaseException 直接穿透）。

## 三点二十一、irvm 字节码平面：孪生落地 + 双侧性能修复（2026-11-14 深夜）

用户要求的两个新执行平面（保留 ir_interp 不动）：**1) Rust IR→字节码
编译器 + 紧凑 VM**（tools/irvm，已提交 f0e1de8）；**2) Silu 孪生**
（selfhost/ir_vm.si，本轮完成）。字节码规范采纳 monty 风格（u8 操作码
+ W(u16 LE)/K(u8) 后缀、常量池、帧槽、标签回填；逐字节一致对 monty
原理上不可达——源语言不同，达成的是规范一致 + 跨平面字节一致）。

- **门禁（均 9 探针，探针落仓 tools/irvm/probes/）**：执行差分
  `tools/irvm/test.sh`（irvm vs ir_interp，9/9）；跨平面字节一致
  `tools/irvm/bytecode_diff.sh`（Rust IRVM_DUMP vs 孪生 @dump，
  9/9 逐字节）。
- **孪生发散根因（fibseq2 "2 2 2 2"）**：VDEPTH 惰性值栈是当时
  rawlist_pop bug 的绕行产物，且 FRAME_VBASE 声明后从未 append/pop
  （死变量）——RETURN 无帧基址可截断，fib(n-1) 清零类 bug 在孪生
  复活；CALL arg_start 又混用 len(VSTACK)（物理）与 VDEPTH（逻辑）
  两套深度。**修复 = 整体回物理栈模型**（push=append / pop=take+drop /
  truncate 循环），与 Rust 侧逐臂同构；模块帧补 FRAME_VBASE.append(0)；
  CALL/RETURN/隐式返回三处补基址记账；VM 循环尾补 is_err() 检查
  （镜像 Rust return Err）；PRINT/CALL 补栈下溢 bail。
- **Rust VM 性能两连修（fib28 0.775s → 0.05s，15.5×）**：
  ①`std::env::var("IRVM_TRACE")` 每指令一查（调试残留，environ 线性
  扫描 ×63 万次分派）——提出循环为一次性 trace flag；
  ②CALL 每帧 `vec![0i64; nslots]` 堆分配——改共享 flat slotarea
  （帧记 sbase，与孪生 SLOTAREA 同构）。
- **速度榜（fib28 总耗时）**：Rust VM 50ms / **Silu 孪生 native
  60ms（内联热臂 → 按频次重排 → pc/end/sbase 寄存器化，三轮
  115→84→60ms）** / monty 116ms /
  ir_interp 1,760ms / AST 解释器 ~15s（CPython 60ms 仍略快于孪生
  ——CPython 的 fib 是 C 级字节码解释器）。孪生与 Rust 的剩余差距
  ~1.2×：elif 链 vs Rust match 跳转表——Python 子集无 switch/goto
  的表达能力边界，孪生的角色是跨平面互证而非绝对速度。
- **连带修复（编译平面真 bug，双平面同 commit）**：conv 的
  rawlist_pop 把长度 store zero64 清零整个列表（Python
  typed_codegen.py + Rust const_prefix.ll 镜像）→ ll 门禁曾 19/20，
  修复后 20/20；ir 21/21；pytest 1361/3 全绿复跑。
- **文档与评测**：docs/interp_vs_comp.md（执行平面全景 + fib28 速度
  榜 + 编译 vs 解释评测结论 + monty 差距关闭分析）；
  tools/irvm/eval.py（编译+运行 vs 解释的评测集，含逐 workload 裁决列）。
- **教训**：①孪生必须与参照**同构**（同为物理栈），不要为绕已修复
  的 bug 保留惰性变体——变体的深度模型必然发散；②"声明未用"的帧
  基址列表 = 截断语义没有落点，grep 一下声明处的 append/pop 配对
  就能抓住；③VM 循环内禁止 env 查询等系统调用形状的开销，哪怕
  "只是读个开关"；④每帧堆分配在递归 workload 上是数量级杀手。

## 三点二十二、P8 match switch/br_table + siluc daemon（2026-11-17）

**P8（用户决策通过，提案入档 reference/PROPOSALS.md §12，commit 39225ef）**：
全 int 字面量 match（value 模式为 `["const", int]` + 可选**末位**无名
通配 `case _`，无 guard/捕获/or，无重复值，≥1 值臂）降为 LLVM
`switch`（三 conv 逐字节一致）与 wasm `br_table`（backend +
wat2wasm.si 新 br_table 分支）；其余模式维持原链式降路。**FE 零改动**
（三前端早已解析 int 模式、`case` 已是关键字）。门禁：ir 22/22、
ll 21/21（语料 benchmarks/match_int.si 自动进 ir/ll/compile(21/21)/
wat2wasm/corpus 五道）、wat2wasm 34/34、corpus 16/16、backend 18/18、
test_compiled_match 20/20（新增 4 个降路测试）。

- **字节契约的实验事实**：llvmlite switch 单行渲染 `[i64 1, label
  %"match_case" i64 5, ...]`（case 对空格分隔、块去重 `.1/.2` 与具名
  值共享命名空间）、**消耗一个匿名槽（与 br 相同）**、具名块零槽——
  Rust 镜像据此写单行 switch + 一次 `b.silent()`。
- **llvmlite.si 孪生无需加 switch**（add_case/渲染早已预置）——但
  **`.si 孪生不支持关键字调用**：`switch(v, default=blk)` 编译期
  "no method 'switch'"，必须位置传参（AGENTS 教训的新实例：.si 面
  的 API 差异在编译期才爆）。
- **wasm br_table 两个语义点**：①OOB 索引取 default（wasm 规范），
  **无需 guard**（负数 wrap 后自然超界）；②**通配 body 必须在 match
  块之外**（br 到 match-exit 标签 = 退出该块落到其后；case 臂用外层
  块跳过通配区）——首轮实现把通配放块内，未匹配值静默保留旧值
  （1317→813，差分实证后修）。③汇编器侧：br_table 的**索引表达式
  字节必须在 0x0E 之前入栈**（同 br_if 的操作数在前）。
- **siluc_main.c 环境关键**：daemon 的 `SIGCHLD SIG_IGN` 会被 fork
  链继承——run_quiet 的 waitpid 拿到 ECHILD+垃圾状态，clang 成败
  判断全乱；**请求子进程必须恢复 SIG_DFL**。

**siluc daemon（commit 本轮）**：`siluc --serve` 常驻编译服务 +
`SILUC_DAEMON=1 siluc file.si -o out` 透明转发（`--object`/`--no-lto`
不转发、无 daemon 自动拉起、空闲 300s 自退）；**直连路径零改动**。
内容键缓存（`<cache>/builds.log`：FNV-1a(源码) + out mtime 校验）：
**重复编译 ~0ms（vs 160ms）**；每请求 fork 隔离（4 路并发实测全过），
缓存追加 O_APPEND 原子、rt.o 刷新沿用内容校验——**多任务无串扰**。
实测：direct 160ms / daemon 首编 160-190ms（管线未变）/ cached ~0ms /
4 路并发 188ms 全绿。诊断流：子进程 stderr 捕获到临时文件，成功时
先行流式发送、verdict 永远最后一行（**教训：stderr 与协议共用一个
fd 会在客户端早断后静默破坏编译**——SIGPIPE 忽略下 clang 写死连接
的表现是"无声消失"，差分定位 3 轮）；EOF 界定协议，客户端按行解析、
非 OK/ERR 行转投 stderr。

**复查轮（2026-11-17，独立审查代理 96 探针实证）**：7 项确认全修——
S7【静默错误输出】孪生 VM bool 常量编成 0（b6a39c0 起：`if True:` 走
else、`while True` 体被跳过，全 rc=0；根因 const 臂只读 `.n`，bool 存
`.b`）→ kind==BOOL 臂修 + bool_lit.si 探针入门禁（10/10）；
S1【静默错误输出】daemon builds.log 缓存投毒（mtime 测试被"更新的覆盖"
命中，同 out 不同源供给旧二进制）→ **last-record-wins**；
S2 相对 `-o` 按 daemon cwd 落盘 + 相对键污染 → out 绝对化；
S3【挂死】自启 daemon 继承客户端 stdio（等待管道 EOF 挂 300s）→
fork 后全三 fd 接 /dev/null；S4 客户端 16KB 缓冲截掉 verdict（成功报
失败）→ 动态缓冲读到 EOF；S5 空格路径按空格分词会编错源 → 检出空格
直连；S6 失败路径诊断全丢（die 在 run_compile 内部，post-compile 流回
不执行）→ **die 钩子流回捕获的 stderr**（ld/clang 详情现在到达客户端）。
已实证排除：寄存器化语义等价（5 组探针）、wasm br_table 九探针（嵌套
循环/连续 match/臂内 break/负值/1024 边界）、switch 镜像决策一致、
深度帽无误伤（1500 深递归正确求值，CPython 反而 RecursionError）、
缓存键正确性四场景、kill -9 后陈旧 socket 接管。遗留观察：三小项已于同日第二巡修复——①**siluc1 语法错误静默**实为
  错误走 stdout 被驱动 .ll 管道捕获后丢弃（Rust FE 用 eprintln 本就
  正确）→ 驱动失败时把捕获首行带进 die 消息，直连/daemon 双链响亮；
  ②缓存键缺编译器身份 → serve 启动时叠 siluc1+rt.o (mtime,size) 为
  silucd.stamp，错配即清 builds.log；③builds.log 过 512KB 尾部截断
  64KB。

**P9 里程碑 spec（2026-11-17 普查完成，实施待字节对齐轮）**——"codegen
  层临时值不释放"（§3.18 遗留正道项）的精确边界：**泄漏实账**（30 万次
  循环 RSS）：`(s+s)+s` 模块层 6.1MB vs 无串基线 1.0MB（~17B/次滞留）；
  命名局部重赋值 1.2MB 无泄漏（赋值 move + 旧值释放已正确）；跨函数
  返回的 concat 结果泄漏（追踪按函数边界清空，不跨函数）。**泄漏主体**
  = 被 `+` 消费的表达式临时（concat 结果/切片/str-get）——TODO #1 的
  str 生命周期只覆盖下标/切片的视图消费路径。**修复设计**（两平面）：
  Python 复用 _owned_str_fresh（concat 臂消费 owned 操作数即 free +
  结果入册，链式传递/下标取 concat 走视图父缓冲——**已实现并实测
  6.1→1.3MB**）；Rust 镜像 CONCAT_TEMPS（已实现）。**byte-parity 未达
  ——实施中止点**：Python 的 _rawstr_operand 对 const/pystr 强制临时
  返回 temp 并释放，Rust 的 to_raw 临时走 TEMP_STRS 且 cleanup 被
  IN_FN + dynamic_operands 双门控——同一源形状两平面 free 集合不同；
  已实证的**潜在既有分歧**（探针形状暴露，非本次引入）：模块层 coerced
  临时 Python 释放/Rust 不释放；双 PStr concat 的 slice 操作数同分歧。
  去掉两门 → wordcount/silu_fe 反向过激（to_raw 临时 Rust 释放/
  Python 不释放）。**剩余工作 + 本轮新增实证（形状矩阵，五探针双平面 diff）**：
  s1 raw 局部单 concat=0 分歧（两平面同泄漏）；s4 链式=0 分歧（同泄漏，
  纯 raw 链的修复**字节可落地**）；s2 const+str(i)=全局声明顺序分歧
  （free 集相同——潜在既有分歧，与 free 无关）；s3 slice+const=Python
  多 1 free（slice 临时 Python 入册释放/Rust 不入册）；s5 字面量初始化
  list 的 push(concat)=**Rust bail "elem type"**（既有能力缺口，宁报
  ERROR ✓）。**wordcount 实证**：Python concat 臂触发 2 次
  （SILU_TRACE_CONCAT 探针）但 a_temp/b_temp 全 None——coercion
  （pystr_to_rawstr）在 _convert_node/_coerce 层发生而非
  _rawstr_operand，Python 该形状本就不 free（泄漏且字节与 Rust 一致）。
  **根因层**：Python 的 kind 词汇表 const str = RAWSTR 但值域 pystr，
  coercion/temp 归属跨 _convert_node/_coerce/_rawstr_operand 三层；
  Rust 的 Typed 词汇（Str/PStr/Pyo）与 Python kind 不一一对应——
  raw_arm 判据（任一 Typed::Str）误判链式内层。**下一轮路径 + 本轮 kind 流追的证据（SILU_TRACE_CONCAT）**：
  wordcount 的 `"w" + str(i)`——COERCE->RAWSTR from obj ×2 发生在
  操作数求值层（str(i) 的 call 返回 coercion + const 的值构造），
  binop 收到 rawstr|rawstr 且 a_temp/b_temp 全 None（coercion 临时
  在 _coerce/_unbox 层产生、无人释放 = 泄漏的字节兼容形态）；concat
  臂在 flatten/normalize 上下文中的分流（direct conv 与 siluc1 路径
  行为一致但 owned-pass 未生效的原因未定位）。**已试并验证的设计**：
  universal obj->rawstr-coercion 注册（_coerce 处）+ concat 臂
  owned-pass + Rust to_raw 注册 + raw_arm(not-both-Pyo)——Rust 侧独立
  可编译可运行，但与 Python 侧合流后仍 18/21（Rust 多 free：Python
  的注册后 free 未出现在 .ll 的原因未定位——嫌疑在 flatten 上下文或
  _owned_str_fresh 的 key 生命周期）。**下一轮路径**：先仪器化
  _owned_str_fresh 的 add/del/free 三点（trace 每个 key 的生死），
  定位注册后 free 不出现的层；探针（temp_free.si / concat_chain.si /
  形状矩阵 s1-s5）已备。
  **第二轮实施（同日，回退）——崩溃链完整取证**：universal-coercion
  注册 + owned-pass + to_raw 注册 + 4 slice/get 入册 + raw_arm
  (not-both-Pyo) + 双边界清空（walk_module / _convert_toplevel）全部
  落地后，**自举版 conv 在 __py_init（运行时前缀发射期）SIGABRT**
  （lldb: ___BUG_IN_CLIENT_OF_LIBMALLOC_POINTER_BEING_FREED_WAS_NOT_
  ALLOCATED ← rawstr_free ← LiteralStructType ← TypedCodegen___py_init
  ← main；direct Python conv 同补丁完全正常、free 正确触发）。根因：
  注册/释放跨了**运行时前缀发射期**与用户转换期的边界——发射期的
  concat 臂（运行时体含 concat）注册的 operand 名字含字面量结构体
  路径（LiteralStructType，非 malloc 分配），owned-pass 对其发 free。
  **修复要求（下轮）**：相位门——注册/释放仅在用户转换期生效
  （IN_USER_PHASE flag：convert() 入口置位、__init__ 的运行时创建
  不置位；两平面同 flag），或运行时发射期结束时的强制双 set 清空
  （须先定位 Python 侧的等价边界）。**教训**：跨 init/convert 相位
  的全局状态（所有权追踪字典）必须有相位门；纯 Python direct 验证
  不能代表自举版（flatten+silu 化后的行为差异要过 siluc1 全链）。
  **相位门实施（第三轮，回退）——最终发现**：IN_USER_PHASE 相位门
  （Python list 标记——bool 注解属性被 .si 转换吃掉，AGENTS CTX 教训
  再证）+ Rust IN_USER_PHASE 后：小输入过、**大输入（自举源）仍
  SIGABRT 且连 silu_fe 自己重建后都崩**——根因升级：**运行时函数体
  是惰性创建的**（_unbox_inst_cache is None 模式），用户相位期间
  惰性发射的运行时体仍会注册/释放。**下一轮的正确设计**：所有权集
  按 CURRENT FUNCTION 隔离（每函数一个 set，concat 臂读当前函数的
  set——运行时体与用户体天然隔离，无需相位门），或等价地给 _unbox/
  _rawstr_operand/concat 臂全部加 current_builder 归属校验。
  **状态**：P9 泄漏修复合入必须与该重设计同轮；树已回绿
  （ll 21/21、ir 22/22、irvm 10/10、pytest 子集 28/28、corpus 16/16
  复跑全过）。
  **第五轮（同日，wordcount ✓ 绿后回退）——consume 站点清单完整化**：
  universal obj→rawstr 注册（_unbox 门控版）+ owned-pass + to_raw
  Pyo-only 注册 + raw_arm(not-both-Pyo) + pass1 的 CONCAT_TEMPS
  retain（双重 free 修复——P9_DEBUG 实证：pass1 free .351 后集合仍
  含 .351，pass2 再放）→ **wordcount ✓ 绿**（Python/Rust free 完全
  对齐）。剩余唯一分歧类：**arg-conversion 路径的 consume 站点**
  （push/join 的参数 _coerce 注册后无人释放——Python 经
  _rawstr_finish/temp-return 模型性泄漏，Rust 经注册被释放）。
  **完整 consume 站点清单**（produce×consume 表的 consume 列）：
  concat 操作数 ✓已对齐、char1 视图 ✓、push 参数 ✗、join 分隔符 ✗、
  call 参数 ✗、compare/contains 操作数 ✗、return/global-store
  （transfer，删注册即可）——每个站点 = 一行 owned-pass（free+del），
  Python/Rust 各 ~2 行。**下一轮**：逐站点补齐（每补一个过一次
  ll 门禁）→ concat_chain.si 探针入仓 → 全门禁 → RSS 复测 → 重钉。
  **新增教训**：patch 脚本必须逐条 assert 当前文件实际状态（本轮
  三次 stale-anchor 空写）；_rawstr_operand 的 del 语义 = "temp-return
  接管"，与 owned-pass 互斥——两套释放模型不能并存于同一注册。
  **第六轮（同日，最终泊车）——渐进 patch 循环的教训**：六轮
  patch/revert 循环后文件状态漂移（Rust 全套已入、Python 全裸的
  混合态反复出现；逐个失败脚本重放互相覆盖）——**结论：此类多文件
  双平面改动必须一次性原子落地**（单一脚本/单一 commit，全门禁后
  提交），禁止增量 patch-循环。最终设计已五轮验证、全部锚点已实证
  可重放；剩余工作（.si 表达性已解：plain int 属性/模块级旗；两遍
  free 结构；Pyo-only 注册；push/join/call/compare 逐 consume 站点）
  = 一次原子实施，预计一轮内收口。
  **第六轮落地（2026-11-18，commit 60ced6d 已推 nightly）——join
  consume 站点 + 探针入仓，泊车态 ll 21/22**：①join 臂修复落地。此前
  patch 曾把 `joined = call(rawlist_str_join,…)` 赋值行整个替换掉
  （NameError 崩溃的直接根因，也解释了 Python 侧 join free"缺失"——
  join 调用本身没发射）；恢复赋值 + 接收者 obj→rawstr coercion 临时
  在 join 后释放（_rawstr_finish 机制性 free temp；obj 域接收者的
  分歧闭合）。②to_raw Pyo-only 注册 + pass-1 CONCAT_TEMPS retain
  （P9_DEBUG 实证 pass1 free 后集合仍含条目 → pass2 双 free，retain
  修复）。③concat_chain.si（链式 concat 所有权探针，CPython 验证）
  入仓：ir 23/23、ll 语料 22。④**当前门禁态**：ll 21/22（唯 silu_fe）、
  ir 23/23、irvm 10/10×2、corpus 16/16、ruff 净、pytest 子集全绿；
  RSS 复测 1.15MB（修复前 6.1MB）。
  **silu_fe 残差定性（hunk 级分析，difflib 全量）**：frees
  py 240 / rs 246（Rust 多 6），260 个 hunk，delta 形态 = +1/-1 位置对
  （同一 free 的顺序漂移）+ -2/-2/-1/-1/-3 簇（Rust 额外 free）——
  **系统性形状类**而非逐 hunk 可修：char-pair pause free（Rust pause
  路径释放 char1+left，Python 经 temp-return/pause 路径泄漏）、
  push-orig 捕获、join 分隔符、free 落块归属。**kind 词汇表映射（下轮
  实施地基）**：Python OBJ→_unbox→pystr_to_rawstr = 注册+释放；
  PStr/pystr 值 = RAWSTR-with-pystr-value 借用类 = 不注册；raw_arm =
  not-both-Pyo（pyobj 形状走 pyobj 路径）。**下轮规格**：先逐函数
  free 归因（P9_DEBUG/trace 定位 6 个额外 free 的函数与形状）→ Python
  侧 pause 路径补注册+释放（正当性：char1 在 concat 后即死）或 Rust
  侧 !pause_any 门控 → 全门禁 → RSS 复测 → 重钉。
  **教训（本轮新增）**：槽号 pattern 是 `%"\.(\d+)"`（bisect 脚本曾写
  `="\.(\d+)"` 匹配全空）；发射关键文件内仪器化只许 stderr（clippy
  --fix 曾位移 .ll 发射 21→20，checkout 回退）；stale-anchor 空写的
  对策 = 写前 assert 文件实际状态。
  **第七轮（2026-11-18）——ll 22/22 收口 ✓ 残差全归因 + 三点对齐**：
  ①**归因方法论**：free 的槽号多重集比对被 free 自身占槽导致的漂移污染
  （free 一多，后续全部槽号错位）——**形状序列比对**（每个 freed 操作数
  回溯其定义形态：COERCE/CONCAT/COPY/CHAR1/LOAD:var，平移不变）才是可
  靠工具；difflib operand 级对齐定性残差。**结论推翻前几轮的形状猜想**：
  6 个额外 free 全部 = **push 参数 coercion 临时**（.30/.191/.226/.336/
  .363/.824，喂 rawlist_str_push 的 pystr_to_rawstr 结果），json_quote
  的差异 = **集合交换**（py free coercion 泄漏 char1，rs free char1 泄漏
  coercion，计数相等净零）——char-pair/join/free-落块 猜想全部排除。
  ②**根因链**：py 的 const 融合预 coerce（typed_codegen 9521-9535）在
  _typed_binop 之外把双操作数 coerce 成 (RAWSTR,…) → concat 臂的
  _rawstr_operand 双双走借用分支 → 左（OBJ→_unbox 注册 ✓ owned-pass
  释放）与右（view→char1 未注册 = 泄漏）；rs 对称地 free char1
  （TEMP_STRS）泄漏 PStr coercion（const=PStr 不注册 + 旧 !pause_any
  门把非暂停侧的 lpy 释放也压掉）。push 侧：rs 释放 Pyo 域 coercion
  （CONCAT_TEMPS 注册→orig_owned），py 的 cleanup 只查 arg_tv[0]==RAWSTR
  漏掉 OBJ 实参的 coercion。
  ③**修复（三点，全绿验证）**：py push 臂 kind 门释放（arg_tv[0]!=RAWSTR
  且 SSA 名变——**RAWSTR 实参的 _coerce 结果是 list 持有的 rawstr_copy，
  释放它 = use-after-free，第一版曾自伤，kind 门保护**）；py 预 coerce
  处 view→char1 相位门注册（concat 臂 owned-pass 释放，顺序
  [coercion, char1] 与 rs pass-1 逐侧门一致）；rs `!pause_any` 改逐侧
  （!pause_lhs/!pause_rhs——暂停侧是 SSA view 结构体非堆临时，非暂停侧
  的 coercion 照常释放）+ **两个 push 站点**（3230 方法臂 + 3308 通用臂
  ——只改一个曾致 ir_interp 反向分歧）扩展 coerced/view_temp 释放。
  ④**仪器化退役**：SILU_TRACE_CONCAT（import os as _os）让新编 siluc1
  运行时读未定义全局 `_os`（FE 对函数级 import 是 no-op）——**fresh
  toolchain 自仪器化引入后首次可构建**；此前仓库根二进制是仪器化之前的
  旧物（前轮门禁跑的是旧 py 平面！）。两处 trace 块摘除（纯 stderr 诊断
  零 .ll 影响）。**教训：调试仪器化必须随调试结束立即退役**；py 双平面
  改动后必须重建自举孪生并重发布仓库根二进制（内容键指纹会自动换目录，
  但仓库根拷贝是手工步骤）。
  ⑤**门禁（全绿）**：ll **22/22**（silu_fe 首次逐字节）、ir 23/23、
  pytest **1374 通过/3 跳过**、corpus 16/16、irvm 10/10×2、backend
  18/18、wat2wasm 35/35、run 4/18+14 loud、ruff 净、**RSS 1.15MB**
  （30 万次链式 concat，修复前 6.1MB）。P9 ll 平面收口；剩余：版本重钉。
  **重钉 + 收尾（同日）**：版本 1.21.0（setup.py + __init__，tag
  v1.21.0 已推，release run 全绿后 promote——4 平台二进制 + sha256 上
  silu-lang releases）。**clippy 收敛（bf99c64）**：silu-conv.rs +
  main.rs 全部 80 条手工清零（**不用 --fix**：它可能删除"结果未用"的
  b.nx() 槽号调用 = 发射位移）——46 条 TLS const 块、contains/fn-path
  闭包、MAIN_OUT static mut→TLS RefCell（unsafe 块消失）、死代码
  （field_ll_ty/local_slot/Ty/Slot/ns4/Val::push/HG 三字段）、不可达
  臂×2、&mut [String] 签名×2；每批跑 silu_fe 字节 cmp + ll/ir 门禁
  全绿。STATUS §四 TODO 全部 ✅ 或等触发（pytest 并发重建竞态修复
  设计已备但无复现证据不动；pyobj_utf8_cp_offset 死函数等下次动前缀）。
  **第四轮（同日，推进到 19/21 后回退）——两张决定性地图**：
  ①**两遍 free 结构**（Python 臂的真实形态）：pass 1 = coerced temps
  （a_temp/b_temp：to_raw 强制临时 + char1 视图）按操作数序；pass 2 =
  owned 表达式临时（concat 结果/slice/str-get，produce 站点入册）按
  操作数序——Rust 单遍合并会颠倒顺序（ir_interp 的 .357/.352 颠倒
  实证）；改两遍后 ir_interp ✓ 绿。②**consume 站点清单仍缺一类**：
  silu_fe 的 join 分隔符（`rawlist_str_join(out, "")` 的接收者
  to_raw 临时）——Python 经 _rawstr_finish 机制性泄漏（不 free），
  Rust 经 CONCAT_TEMPS 注册被释放（多 1 free）——join 是
  produce×consume 表的新 consume 站点，Python 侧需补 free 或 Rust
  侧对齐不释放。**.si 可表达性清单（第四轮实证）**：bool 注解类属性
  ✗、属性下标赋值 ✗、plain int 属性 ✓、模块级 list 旗 ✓、
  方法调用的注册/释放辅助 ✓。**下一轮收口清单**：join consume 站点
  对齐（唯一剩余分歧，1 个形状）→ concat_chain.si 探针入仓 →
  全门禁 → RSS 复测 → 重钉。全部 probe/锚点已验证可重放。驱动错误透传本轮即立功
  （探针的 ValueError 不再静默）。

## 三点二十三、默认构建走运行时缓存 + P9 形状入仓 + 陈旧注记清理（2026-11-18）

- **默认构建 470ms → 210ms（2.2×）**：`silu build` 的运行时缓存快路径
  （runtime_cache.build_with_cache：~350KB 运行时一次编译成缓存 .o，
  每程序 clang 只看用户部分）原是 **SILU_RUNTIME_CACHE=1 opt-in**，
  基础设施完备但默认不用——§3.21 记录的 "默认 530ms vs daemon 170ms"
  差距的根源。翻转默认（**SILU_RUNTIME_CACHE=0 显式退出**；dynamic
  codegen 保持不缓存）。**安全性**：该路径被 selfhost_build 每日锤炼
  （siluc1/silu_fe 工具链构建全走它）+ 全门禁背书；本轮新增 18 基准
  **A/B 执行对拍**（cache 路径 vs 全量 clang 路径，逐文件输出 cmp）
  全一致；缓存目录 `~/.cache/silu-runtime/`（根）与 daemon 的
  `driver/` 子目录分离，内容键指纹含全部转换器源（本轮 P9 修改自动
  失效旧缓存）。实测 fib 210-220ms 稳定（冷启动 0.60s：一次性 rt.o
  编译）。剩余 210-160ms 差 = Python
  llvmlite 转换 vs 原生 siluc1 转换——不动（默认构建保持 Python 平面
  转换器的 bootstrap 身份）。
  **翻转揭出的 opt-in 路径潜在 bug（split 修复）**：Apple Clang 16+
  拒绝同名重复 declare（"invalid redefinition of function"，最小 ll
  复现实证）——split() 的 header_declares 扫**全文本**（含 user_body
  自己的 C-import declare）→ 每个带 `from c import` 的程序在缓存路径
  必炸（user.ll 中 sqrt declare ×2）；selfhost 程序无 C import 所以
  opt-in 时代从未触发，**唯 c_abi 测试能抓**（翻转即价值）。修复：
  header_declares 只取运行时前缀 rb 的 declare，且排除 user_body 已
  声明/定义的符号（用户的 declare 是调用点签名的权威）。c_abi
  6 过 1 跳 + A/B 18/18 + 冷暖缓存时序验证。
- **char_pair.si 入仓（P9 回归钉）**：第七轮对齐的 const+view concat
  形状的最小探针（CPython 对拍 "x4" ✓、双平面字节一致 ✓）；
  ll 门禁 23/23、ir 24/24（枚举自动收录），
  test_frontend_parity_corpus 计数 21→22。
- **陈旧注记清理（实测驱动）**：①§3.16 的 "~2s/KB" 性能项——
  §3.18 的 3800× 修复（逐行化+T_TXT 直存）早已覆盖，实测
  wat2wasm.wasm 对 46KB WAT（mandelbrot 全量）**18ms**，条目改写为
  已关闭；②TODO #2 的 pytest 竞态——flock（build_lock）+ os.replace
  原子落位早已在 tools/selfhost_build.py 落地，条目改 ✅。

## 三点二十四、Oracle membership 族补齐 + 全局容器名 eval 修复（2026-11-18）

- **g3 族 Oracle 面字节对齐（语料压力 T3 触发）**：g-探针复跑发现
  语言面（py 平面 + native）早已支持非空列表字面量族，唯 Oracle 落后。
  补齐三处：①**`x in list` membership**（eval_i1 的 in/not-in 臂：
  int/float 走 rawlist_contains_bits 位比对（bool zext/f64 bitcast），
  str 走 rawlist_str_contains；实参 coercion 临时**两平面一致泄漏**
  ——py 的 _typed_contains RAWLIST_S 臂本就不释放）；②模块级
  list[str] 字面量（ann_assign 循环补 str 臂：to_raw +
  rawlist_str_push，同样对齐泄漏）；③**list:str 调用实参**（py 按
  **实参位置类型**分派装箱 build + pylist_to_rawlist_str，rs 原按
  callee 返回类型分派——probe(["alpha","beta"]) 形态对齐）。
- **连带修复：全局容器名 eval 错误类型读**：eval_expr 与 eval_mod
  的 name 臂都把 LST_SLOTS/DCT_SLOTS 全局落到 **i64 兜底 load**（裸
  读一个 i8* 槽当 i64）——补 LST_SLOTS||DCT_SLOTS 臂（`load i8*` +
  Typed::Inst），与 py 的发射一致。**教训：rs 有两个平行的 name-eval
  （eval_expr + eval_mod 各一份完整分发）——改 name 语义必须两处同
  改，漏一处 = 半数路径仍旧类型**。
- **新语料**：benchmarks/list_ops.si（模块级 int 字面量 + append +
  in/not-in（const/not-in/loop-var）+ 函数 list[str] 参数 + 函数内
  append + list:str 调用实参 + 字面量 + 下标；CPython 对拍
  1/2/1/2/4/4/7 一致）。ll **24/24**、ir **25/25**、corpus 计数 23、
  native 输出 = CPython。PROGRESS g-清单 2026-11-18 重普查入档。
- **仍未钉（响亮 bail = 纪律内）**：g1 ctor 列表实参（str-only
  to_raw 撞 I64）、g9 dict[int,*] store（同类）、pop/clear 语句臂
  （只有 append）、g6/g7 dict 方法族、join 的 str 参数接收者。
- 三次自伤修正入档：membership 臂的调用格式缺类型前缀（`i64 2`/
  `i8* %x`——py 的调用点逐参前缀）、`create_list()` 的括号进引号、
  草稿残渣（b.pop_line 不存在）——每次都被探针字节 diff 当场抓获。

## 三点二十五、pop/clear + 丢弃式 rawstr 释放 + 装箱 join + 全局 str 尾序（2026-11-19）

- **pop/clear 臂（g5 关闭）**：eval_expr 的方法分派补 pop/clear（int →
  `rawlist_pop` → I64；str → `rawlist_str_pop` → Str——**缓冲 move 给
  消费者，无拷贝**；clear → `void rawlist_clear` → 返回容器）。置名
  分派前（join 臂后），以 FN_L||LST_SLOTS 门控。
- **丢弃式 rawstr 语句值释放（通用机制补齐）**：py 的
  `_convert_statement_scoped` 对裸表达式的 RAWSTR 结果做语句尾 free
  （赋值族别名槽存储、由各自臂分派、永不经此路）——rs 的 bare-call
  臂原样 `let _ =` 丢弃。补齐后 `words.pop()` 丢弃式的弹出串释放对齐。
  语料无此形状（门禁曾绿）——探针当场抓获。
- **装箱 join（两段式分派镜像）**：`(s+t).join(lit)` 形状 py 走
  `str_join_boxed`：raw-join 探针先求值实参一次（其产物留在 .ll 里
  是**死代码但字节在场**），generic 回退**再求值一次** + 接收者装箱
  （rawstr_to_pystr）+ 结果 pystr_to_rawstr——rs 必须镜像两次求值。
  join 实参为全局 list 的 bail 此前已被 name-eval 修复免费带好。
- **全局 str 尾序修复**：模块级非 const str 全局的声明（tail_push）
  原在 eval 之前——py 按值类别在 **eval 后**声明（str.x/str.y 等初值
  intern 的串先于全局名进 tail；join_concat 探针证据）。ord1
  （input()）与 ord2（raw concat）此前即一致（tail 内无竞争条目/
  走 raw 臂）——竞争条目场景唯 join 形状暴露。
- **新语料**：benchmarks/pop_clear.si（int/str 双 pop（valued +
  discarded）+ clear + append；CPython 对拍 3/2/0/b/1/2 一致）。
  ll 24/24、ir 25/25、corpus 计数 24。join 探针（global list 接收者）
  字节一致——name-eval 修复的免费红利。
- **ir2c 第三平面联动（m5 当场抓获，与 membership 轮同模式）**：C 后端
  无 pop/clear → 实参降级为 `0;` 空操作 → `w: str = words.pop()` 把 0
  赋给 Str* → print 解引用 NULL → **SIGSEGV 空输出**。补 method 臂
  （pop int/str、clear）+ C 助手（list_pop/list_pop_str/list_clear：
  弹出槽清零镜像 .ll rawlist_pop 规则、空 pop panic "IndexError: pop
  from empty list"）。C 输出 = CPython ✓、m4/m5 59 全过。
  **测试方法教训**：手动验证 ir2c 必须用 `python -m silu ir --format
  json`（m5 的 IR 来源）——用 silu_fe 的 JSON 会静默得空 main（两前端
  JSON 序列化不同，ir2c 解析后者失败降级）——该静默降级本身是 ir2c
  的响亮化欠账（待办）。
- **仍未钉（响亮 bail）**：g1 ctor 列表实参、g9 dict[int,*] store、
  g6/g7 dict 方法族。

## 三点二十六、dict 方法族 + str-key store 验证（g6/g7 关闭，2026-11-19）

- **dict 方法族（Oracle 补齐）**：pop（1 参 = rawdict_del/str_del
  KeyError panic 形；2 参 = pop_or + default）/clear/setdefault ×
  str/int key 域，全部经 emit_pyobj_key_view（新抽取的共享机器：pyobj
  tag==2 检查 + panic "TypeError: expected str key" + 解包 + 借用
  str_view——py 对每个 pystr 域 dict key 都跑此验证）。**RAWSTR key
  直接传缓冲**（无 view 无验证——py 同）；const key 走 checked 视图。
- **str-key store 验证补齐**：`d["a"] = 1` 的 key 在 py 有 tag 检查
  （_rawdict_key_call 机器），rs 原 pystr_to_rawstr 直通——dict.si
  语料全是 int key 所以从未触及（**语料覆盖面教训再证**）。PStr/Pyo
  key 现走共享视图；RAWSTR 直通不变。
- **emit_const_key_view 重构**：get 专用的 emit_const_key_get_mode
  拆出共享视图构建（返回已包裹指针，调用点 verbatim）——get/store/
  方法族三处共用同一形状。
- **新语料**：benchmarks/dict_ops.si（2 参 pop + setdefault + int-key
  dict 全族 + clear；CPython 对拍 7/3/10/20/0 一致）。ll **25/25**、
  ir **26/26**、corpus 计数 25。**g9 条目作废**（dict[int,*] store
  字节早已一致——重普查时 g9b 即绿，g-list 未更新）。
- **ir2c 第三平面联动（第三轮同模式）**：C 后端无 dict 方法族 →
  实参降级 `0;` → 输出错值。补方法臂（pop 1/2 参、setdefault、clear ×
  dict/dicti）+ C 助手（dict_del/pop_or/setdefault/clear + dicti_* 四
  件套）。**哈希一致性手伤**：dicti 助手的探针原写 `k % cap`，而
  dicti_set/get 用 `ihash(k) % cap`（真哈希非恒等）——探针错位 = 合法
  key KeyError；探针必须与插入方同一哈希。C 输出 = CPython ✓、
  m4/m5 全绿。
- **仍未钉（响亮 bail）**：g2/g1（模块级实例 ann_assign）、局部 dict
  的 key/val 类型注册（方法臂限定全局 dict）、get(k) 单参装箱 phi。
- 伤痕记录：emit_pyobj_key_view 抽取时 cs/py 引用与包裹层级三次
  手伤（双引号/裸指针/漏改解包基址）——全部被探针字节 diff 当场
  抓获；py 的调用点逐参类型前缀（i64/i8*）继续是对齐的主坑。

## 三点二十七、局部 dict 族 + 1 参装箱 get（g7 闭合，2026-11-20）

- **局部 dict 全族字节对齐**：三处修复——①**len 臂的 dict 分支槽域**
  （硬编码 @"n" → dct_slot：FN_D → %、否则 @；全局 dict 字节不变）；
  ②**2 参 get 臂的槽域**（同上）；③**int/float 局部的 alloca 收集序**
  （FN_ALLOCAS push 从 RHS 求值前移到后——py 在值存在后才声明局部，
  竞争条目（dict key 视图）场景的 alloca 序才一致；list_ops/pop_clear
  等既有语料无竞争条目、字节不变）。
- **1 参装箱 get（has/phi 机器首次入 rs）**：key 视图先物化（两臂共享）
  → rawdict_str_has → get_hit（rawdict_str_get + create_int）/
  get_miss（null）→ **phi  {i32, i8*}***（llvmlite 双空格风格）→
  unbox_int（模块级与局部 int ann_assign 的 Pyo unbox 边界补齐——
  py 的 _coerce(OBJ→int) 对应物）。dss（str 值）1 参 get 未钉（响亮
  bail：create_int 硬编码 int 值域）。
- **新语料**：benchmarks/dict_local.si（局部 dict 全族：store/setdefault/
  pop/clear/len/2 参 get/1 参装箱 get；interpret = native = ir2c =
  1/1/2 一致）。ll 27/27、ir 28/28、corpus 计数 27。
- **g-list 终态**：g1-g12 全部关闭或作废；唯余 dss 1 参 get（响亮
  bail）。dict 家族四平面完整。

## 三点二十八、str 方法族 + index 语义修复（WIP：ll parity 最后一公里，2026-11-20）

- **str 方法族四平面落地**：strip/split(sep/ws)/replace/lower/upper/
  find/index/startswith/endswith/isdigit/isalpha/isspace + print-bool。
  py：replace 臂 + **rawstr_replace 运行时**（新 .ll builder：两遍
  单缓冲、匹配循环镜像 split_sep、中间串全释放；**签名 = append 风格
  (s, old_data, old_len, new_data, new_len)**——首版按 rawstr 指针
  签名、py 臂传 append_operand 的 data 指针 → len 读成数据字节 →
  replace 恒返回原串，native ≠ CPython 当场抓获）+ **index 语义修复**
  （原走 list_index 通用分派：str 接收者的 items=null → len=0 → 循环
  跳过 → **静默 -1**（CPython=6）；改 str_find + unbox（py 的
  _load_number_as_i64 内联 gep 形状）+ ValueError panic（panic_bad/
  panic_ok 共享标签））。rs：strip/split/replace/lower/upper/find/
  index/六谓词/print-bool 臂 + emit_rawstr_append_data（const=全局
  gep+const len；var=结构体字段 load）+ **const_prefix.ll 重生成**
  （include_str 快照——新运行时函数必须重生成，教训入档）+ fn 渲染
  空行（**py 的 inter-function 空行在每个函数之前**：prefix→f 与
  f→main 统一；main 用 FUNC_DEFS 判空条件式——f 尾部渲染空行已存在，
  叠加会双空行）。ir2c：replace/strip/split/lower/upper/find/index
  臂 + C 助手（两遍单缓冲 str_replace、ASCII 空白集 str_strip、
  str_find/index、str_lower/upper）。
- **四平面执行 = CPython ✓**（str_methods.si 全 14 语句：interpret =
  native = ir2c = CPython）；strm 双平面字节一致 ✓。
- **WIP：ll parity 15/29**——14 文件细粒度差异入档：dict 方法臂的
  形状细差（dict_local +63/dict_ops +163/pop_clear +135/record_global
  +31 字节，rs 偏大）+ nbody/spectral +2 + jsonparse ×2 +5。
  下一轮首项：14 文件的 hunk 级分析 → 臂形状对齐 → ll 29/29。
- 三次自伤修正：①strip 臂补丁残留双发射；②ir2c str_replace 助手被
  strip/split 补丁的锚点整个替换（锚点 = str_replace 行本身——插入
  新助手勿锚在被插对象上）；③fn 渲染空行的 insert 索引偏一行 +
  叠加双发——全部被探针/门禁当场抓获。

## 三点二十九、ll parity 29/29 收口（2026-11-21）

- **str 方法族轮的 parity 债清偿**：①str-method 前奏的急切接收者求值
  对 dict 方法也发（双重 load）——dict 族移至 str 族之前；②局部 dict
  的槽域：多臂硬编码 @d → dct_slot（FN_D → %d）——len/get/方法臂
  全部对齐；③边界空行规则**定版**：py 的 .ll = 每个 inter-function
  边界恰好一个空行（CONST→TAGGED、TAGGED→首用户 fn、fn→main——
  fn→fn 之间**无**空行）；rs 的 emit 点：CONST 尾、TAGGED 尾、
  fn→main 各一，与 py 逐字节对齐。**文件级验证**：jsonparse_json
  py = rs = 471526 字节逐字节一致（直跑 cmp ✓）。
- **门禁数字的平面陈旧伪影**：harness 的 ll 计数在 28/29 与 29/29 间
  波动——直跑 cmp 恒一致，harness 的平面二进制存在陈旧窗口（本会话
  教训"改被 ll 门禁钉住的文件必须跑 ll 门禁"的镜像：**ll 门禁的
  平面二进制也必须与被测源同步重发布**）。以文件级 cmp 为准。
- **门禁**：ll 29/29（文件级 ✓）、ir 30/30、pytest 1395/3。
- **v1.23.0 已发布**（release run 全绿 + promote：4 平台 + sha256 上
  silu-lang releases；AGENTS 钉住同步 1.23.0 ✓）。
- **str 方法族全量**：strip/split(sep/ws)/replace/lower/upper/find/
  index/startswith/endswith/isdigit/isalpha/isspace/print-bool +
  rawstr_replace 运行时（append 风格签名）+ index 语义修复
  （list_index 分派对 str 接收者静默 -1 → str_find + ValueError
  panic）+ ir2c 全族 C 助手。str_methods.si 四平面 = CPython。

## 三点三十、dss（str 值 dict）轮收口：快照重生成 + list 臂归位 + 全门禁绿（2026-11-21）

- **dss 探针暴露两平面表示分歧**：py 的 dict[str,str] = 动态 dict
  （pyobj_subscript_set/dict_get_or）；rs 的 = str 值 rawdict
  （rawdict_str_set/rawdict_str_get_or）——语义一致、表示不同、语料
  从未钉过。store PStr 臂 + 1 参 get 双平面已落地（77d5e54/855bc7e）。
- **WIP 谜题破案（ok_block 自循环）**：siluc1 陈旧非指纹问题——
  pystr_to_rawstr builder 的 tag-check cbranch 目标就是 ok_block 自身
  （null 分支插入后 br 回命中块 → ret 命中断言）。修复：真 continuation
  块 str_ok；重建 + 重发布后 null 分支入 siluc1 .ll，native SIGSEGV 消。
- **ll 门禁 0/29 → 29/29 两连根因**：
  1. **const_prefix.ll 手写快照违背重生成约定**（0/29 全体 DIFF，
     总差 1 字节）：上轮手补的 null 分支用命名寄存器 %.n0/独立 ptr_ok
     块/str._25s 空串全局，py 侧是 llvmlite 匿名槽直跳 ok——快照
     必须从 py runtime_text() 原样重生成（尾 `}\n`，oracle 自补空行）。
     重生成 385,611B → 28/29。
  2. **list pop/clear 臂被 str-family 重定位吞没**（e96ce39 编辑事故，
     28/29 仅剩 pop_clear ERROR）：整臂落进 is_str_family 块内且守卫
     被掏空成 no-op `if {}` + 逃逸体——`xs.pop()` 时 is_str_family=false
     跳过整块 → 落 dict 区 → is_dict_slot=false → 实例分派 →
     bail("method base type")。修复：臂移出块外（str-family 块闭合
     之后、dict 区之前），守卫恢复。**v1.23.0 的"29/29"跑在陈旧
     二进制上——陈旧窗口教训再次命中（提交前门禁必须用刚重建的
     平面二进制）**。
- **dss 四平面执行终验**：interpret = CPython（None/alpha ✓）；
  native = ""/alpha（raw 边界合并，rc=0 ✓）；**ir2c = 静默错 C**——
  dss 形状走 dsi int 值字典臂（Str* 传 int64_t 参数，clang 拒收），
  ir2c.si 未获 dss 臂（本轮未触及）→ **下一轮首项：ir2c dss 臂**
  （str 值 dict 表示 + store/get/print），补齐后 dss 语料钉板。
- **miss 路径平面边界（既记录边界族，非本轮回归）**：1 参 get miss：
  dict[str,int] native = 响亮 TypeError panic（既有）；dict[str,str]
  native = "" 合流（本轮设计——str 域零值）；interpret = CPython None
  （两者同——解释器 = CPython 语义线）。miss 形状不入语料钉板
  （钉 2 参 get 默认值 + hit 路径）。
- **门禁全绿**：ll 29/29、ir 30/30、pytest 1395/3。

## 三点三十一、dss 收敛轮：ir2c 臂 + rs 铁律修复 + RAWDICT_SS 表示统一 + 语料钉板（2026-11-21）

- **ir2c dss 臂落地（27b074c）**：anno_type 本就产出 dict:S:str
  标签，缺的是全部下游消费臂——非空字面量构造（all_str_v 跟踪 +
  值指针裸放 int64 槽）、store（intptr 强转）、读（dict_get_str
  新 C 助手——miss 响亮 KeyError 对齐 CPython d[k]）、get 1 参
  （get_or 空串默认 = None 经 raw 边界合流）、get 2 参/pop/
  setdefault（intptr 双向强转）、aug（响亮读 + str_add 回写）。
  宽探针 13 语句 + 4 边缘探针执行 = CPython。
- **rs 三处被接受但错误的字节（dde4097，铁律违反——执行探针
  当场抓获，字节门禁从未见过这些形状）**：①eval_mod 全局 1 参
  get 用 dsi 的 int 装箱 phi（create_int 装裸指针 → pystr_to_rawstr
  的 tag 检查 panic "expected str"）→ str 值 dict 改走 eval_expr
  孪生的 get_or 形状（两分发器同形）；②下标读返回 i64 bits →
  print 发射裸指针十进制（5383412944）→ str 值 dict inttoptr →
  Str（const 键与一般键两路都修）；③pop 把 del/pop_or 的 bits
  直接当 Typed::Str（clang 拒收 store i64→i8*，丢弃清理把 bits
  当指针 free）→ inttoptr 先行。修后最小集 store/get/read/len/
  pop/clear 执行 = CPython，miss 读/1 参 pop miss 响亮 KeyError。
- **py 表示收敛 RAWDICT_SS**：dict[str,str] 从动态 dict
  （pyobj_subscript_set/dict_get_or）切到 str 值 rawdict——kind 表
  （RAWSTR 值槽）+ 注解映射 + _dict_value_bits/_dict_bits_to_value
  （ptrtoint/inttoptr）+ store ptrtoint 臂 + get 1 参 get_or 形状
  （空串全局 @"str." 引用运行时前缀，无 has/phi）+ 读臂 inttoptr。
  11 探针**一次研磨后全数逐字节一致**（dsi 机制参数化程度的回报）。
- **dss 语料钉板（benchmarks/dict_str.si，第 8 枚能力钉板）**：
  store×3/get/下标读/print-read/len/pop×2/clear——py conv = rs conv
  **406,041B 逐字节**；interpret = native = ir2c = CPython 逐行。
  已知 rs 响亮 bail 形状（ERROR 不是错误字节，未入钉板）：
  membership（任何 dict 类型）、非空 dict 字面量、str 值 dict 的
  aug/2 参 get/2 参 pop（tail PStr 臂缺）/setdefault。
- **动态 dict pop 语义缺口（记录，未修）**：pyobj_pop_dispatch
  无默认值参数——dss 动态路径 1 参 pop miss 静默 None（应 KeyError）、
  2 参 miss 丢默认值（应返回默认）；表示收敛后 dss 不再走该路径，
  pyobj 类型 dict 的该形状无语料钉住——出现时门禁响亮拦截。
- **教训**：①siluc1 读 stdin 不读文件参数——文件参数调用静默空转
  （rc=0 零字节输出），差分前必须核尺寸；②rs 是字节目标但**其
  产物也要执行验证**——conv rc=0 ≠ 语义正确（本轮三处错误字节全
  是 clang+运行才暴露）；③工具链 py 编辑后必须 ensure_siluc 重建
  （fingerprint 驱动，driver 不自动重建参考平面二进制）。
- **门禁**：ll **30/30**、ir **31/31**、corpus 29 断言更新、
  pytest **1398/3**。

## 三点三十二、oracle 形状补齐轮规划（2026-11-22，本轮 §3.33 已全部落地）

**已落地（8f6a4d8）**：值上下文 membership——臂此前只在 eval_i1
（bool 上下文，list_ops 钉证）；print 实参/赋值走 eval_mod→eval_expr
bail（语料零 `in` 使用者，从未暴露）。eval_expr 新增 in/not-in 臂
（返回 Typed::Bool，str-in-str/pyobj/list 逐字节镜像 eval_i1 已钉证
形状；dict 臂用 checked-view 键= get/store 键形状，非 to_raw）；
eval_i1 dict 兜底臂同修（未钉形状的潜伏字节分歧）。**研磨教训**：
首版 dict 臂在容器名求值（dv 已载入）后又 b.nx() 重复载入——多一条
指令使全部槽位后移（py .35 vs rs .36 load 的差一签名）——复用 dv 的
Inst 值闭合，m1/m2（dsi+dss membership）字节一致，双平面执行 True/
False = CPython，ll 30/30 不动。

**本轮 TODO 1-5 已全部落地——见上方 §3.33（e74c38a/a914a3f/
c3546ff/915e2a6/6ce0680）；探针 28 枚在 /tmp/gprobes/（u 系 30 枚含
skip）。剩余仅第 6 项（版本重钉决策，用户裁决中）。**

**探针清单（/tmp/gprobes/，compact 后重建用）**：s1-s8（dss 最小
集形状）、t1-t9（miss 读/字面量/aug/pop 作值/2 参 pop/dsi miss/
dsi 字面量）、m1-m2（membership dsi+dss）、dss/dss_wide/pin_min
（宽探针）。钉板 = benchmarks/dict_str.si（store×3/get/读/
print-read/len/pop×2/clear，406,041B 双平面逐字节）。

**本会话教训（补入下方六节）**：①siluc1 读 stdin——文件参数静默
空转（rc=0 零字节），差分前核尺寸；②conv rc=0 ≠ 语义正确——rs
产物必须 clang+执行验证（本轮三处错误字节全由执行暴露）；③转换器
py 源编辑后必须 `python3 -c "import sys; sys.path.insert(0,'tools');
import selfhost_build as sb; sb.ensure_siluc()"` 重建（driver 不自动
重建参考平面二进制）；④eval_expr 臂的容器复用 dv——重复载入差一
槽的研磨签名（py .N vs rs .N+1 load）。

## 三点三十三、oracle 形状补齐轮全收口：2 参族/aug/字面量/无效 IR/动态 pop（2026-11-22）

**五项 TODO 全部落地（e74c38a → 6ce0680），全门禁绿**：ll 30/30、
ir 31/31、pytest 1398+4/3、wasm corpus 16/16、backend 18/18、run
4+14、wat2wasm 43/43。探针 28 枚（t6/u1-u30）双平面逐字节 + clang
执行对拍全一致。

1. **rs dss 2 参族 tail PStr 臂（e74c38a）**：get/pop/setdefault 的
   str 默认值臂 + 求值顺序对齐（py 顺序：pop/get 键先转换、
   setdefault **默认值元组先构建**（u2 实证——py 源码 tail_args 在
   键转换前求值）、checked 视图一律在默认值之后物化）；RAWSTR 默认
   值 copy（别名铁律）、PStr/Pyo 走 pystr_to_rawstr（新缓冲）；str
   返回的用户调用 ride copy（Inst 域必须节点级查 FN_SIGS 才接受）。
   **连带修复**：①eval_mod get-2 的 entry+bitcast+load 形状是"被接受
   的错误字节"且 entry 会插入默认键（get_or 只读）——u12/u14 抓获；
   ②slice 键误用 aug-idiom 的 str_view 形状（py 用通用 rawstr_slice
   直读，u15）；③**str 局部变量 alloca 记录须在 RHS 求值后注册**
   （u10 prologue 序——视图产出型初始化先分配视图再分配槽位）。
2. **rs dss/dii aug（a914a3f）**：conv_aug_assign 下标臂加 dict 门
   （此前 dii aug 静默走 list 数据 gep——错误字节，u20 抓获）。形状：
   rhs 先转换 → 键只转换一次（get/set 两次 checked 视图）→ get
   （rawdict_str_get miss 即 KeyError panic）→  checked binop → set。
3. **rs 非空 dict 字面量（c3546ff）**：全局 + 函数局部，dsi/dss/dii
   三族（t2/t9/u23-u27）。entry 顺序 = **值转换 → 键 → 视图 → set**
   （const int 值零指令所以 t9 看似键先）；str 值 ride 指针。局部
   字面量此前**静默变空 dict**（init 被忽略）；alloca 记录在 entry
   后注册（u23）。**连带闭合**：`d["x"] + d["y"]` 读拼接（is_str_expr
   认 dss 下标读；char-pair 暂停机制空 pair 纯透传）——STATUS 清单外
   的新发现缺口。
4. **扩钉板 + 无效 IR 修复（915e2a6）**：dict_str.si += membership/
   2 参族/aug/字面量/读拼接（miss-None 边界不入钉）；dict_ops.si +=
   dsi+dii 字面量 + membership。**钉板当场抓获三平面共有既有 bug**：
   aug concat 把 i64 位直传 i8* 形参、str 值 set 直传 i8*（rawdict_
   str_set 收 i64 位）——clang ABI 宽容让它运行时碰巧对、text 层
   渲染无校验，**真 llvmlite 的 verifier 拒绝**（test_text_layer_
   matches_llvmlite 响亮失败=门禁在干活）。修 py 参考（aug 臂
   inttoptr 后 concat、set 前 ptrtoint；字面量臂 ptrtoint——对齐
   下标 store 约定）+ flat 孪生再生成 + rs 镜像。
5. **动态 dict pop 语义（6ce0680，纯 py 平面——rs 对动态 dict 整体
   bail）**：1 参 pop miss 静默 None → **KeyError panic**；2 参 miss
   丢默认值 → 返回默认。ABI：dict_pop(d,key,def)（null def = 1 参域，
   miss panic）+ dict_pop_def（miss 恒返回默认——含 None；CPython
   2 参 pop 从不 raise；**转换器自身 .pop(k,None) 惯用法依赖它**——
   首版只做 panic 版让 siluc1 编译期自爆 KeyError，行为级实证）+
   双 dispatch 3 参透传 + 方法表 pop arg_count 1→2 按参选函数 + del
   直调去掉死检查。const_prefix.ll 重生成（391,059B）+ rs 快照同步。
   tests/test_dynamic_dict_pop.py 四测（子进程级：编译 == 解释器）。
   **前缀重生成约定**：快照必须终止于 `}\n`（闭括号新行）——多带一个
   空行会与渲染器的 inter-function 空行翻倍（ll 0/30 → 修 snap 后
   30/30）。

**新发现待办**：①str `-=`/`*=`（泛型 pyobj binop 域）rs bail——py
发射 panic 字节，缓议（u21）；②dsf（dict[str,float]）rs 整族未注册
（bail "dict elem types"，u8）；③object 注解局部 rs 不支持（bail
"ann_assign type"，u9）；④str 局部 buf 惯用法 alloca 记录时序同 u10
问题（未验证，动前先探）。

**本会话教训（并入 §六）**：⑤**"conv rc=0 ≠ 语义正确"的第三形态**：
clang 接受 + 执行正确 ≠ IR 合法——真 llvmlite verifier 是第三个执行
比对平面，aug/字面量的 i8*/i64 位混传全靠它抓获；⑥**前缀快照边界**：
公共前缀提取必须 snap 到闭括号新行；⑦**手写期望再次被真参照纠正**
（dp 测试 len 期望）——教训 1 的第四次命中。

## 三点三十四、v1.24.0 发布 + 4 项后续 TODO 收口（2026-11-22 深夜续）

**v1.24.0 已重钉并打 tag 推 nightly**（d83c3bb）：oracle 形状补齐轮
+ 钉板扩容 + 动态 pop 语义 + **pyobj_utf8_cp_offset 死函数退役**
（§四.6 的"下次动前缀时顺手"——前缀 390,013B，rs 快照锁步）。版本
四件套（__init__/setup.py/AGENTS 钉行/本文件）。

**§3.33 尾的四项新发现全部闭合（d12739b→343bc93），39 探针双平面
字节+执行一致，全门禁绿**（ll 30/30、ir 31/31、pytest 1402/3、wasm
corpus 16/16、backend 18/18、run 4+14、wat2wasm 43/43）：

1. **rs str `-=`（d12739b）**：py 仅对 pyobj 域 rhs（const str）发射
   字节——inttoptr get 位 → rawstr_to_pystr 装箱 → pyobj_sub（str-str
   运行时 TypeError = CPython 语义）→ pystr_to_rawstr → ptrtoint →
   set。raw 域 rhs（var）与 str `*=` py 平面自身 bail（u31/u32：
   "cannot coerce rawstr to i64"）——rs 同步 bail，双平面响亮一致。
2. **rs dsf/df 整族（bec359e）**：注册门放行 float 值；float 值 ride
   槽位 i64 位、边缘 bitcast（读 get/pop/字面量/2 参族默认值与返回、
   aug = bitcast→fadd/fsub/fmul→bitcast 无溢出检查、store str 键/int
   键两路、get-1 装箱 phi 的 hit 臂 bitcast 先于 create_float 分配）。
   **连带修复既有分歧**：float ann_assign 全局常量折叠进声明（v7）——
   py 恒 0x0 声明 + main 内 store（SOLAR_MASS 约定）。
3. **rs object 注解全局 + 重赋值（d611b26）**：object 全局直持 pyobj
   （{i32,i8*}* null 尾声明；const str → create_str 无
   pystr_to_rawstr）；PY_SLOTS 重赋值 to_pyobj 后 store；局部 object
   已有 FN_PY 机制（w4 本就一致）；object 值作 dict 键 ride checked
   view（w3）。
4. **strbuf ctor 语义修复（343bc93）**：py 双重转换构造参数（BUF
   kind 检查死值 + append-operand 重转换）——副作用参数死转换不死：
   `strbuf(d.pop("a"))` **执行两次 pop，hit 变 KeyError**（x2，双平面
   字节一致且同错；解释器无 strbuf——CPython 推理语义为准）。修 py
   参考（非 const 单次转换 + 从已转换值解包 len/data；const 钉住形状
   保留——死转换无副作用）+ flat 孪生 + rs 镜像；buf 局部 alloca
   记录移到 RHS 后（u10 惯例，x2 prologue）。x2: KeyError → alpha。

**教训**：①**字节一致 ≠ 语义正确（第四形态）**——x2 双平面字节一致
且同错，探针的执行对拍（对 CPython 推理语义）是最后一道闸；副作用
参数的死转换是 compile-visible 行为。②转换器自身的 `.pop(k, None)`
惯用法依赖 dict_pop_def——运行时语义改动先扫转换器自用面。

## 三点三十五、§四 TODO 全收口：g-#10 推断分歧闭合（2026-11-24）

**STATUS §四 全部可行动项关闭（c5ebb98）**。g-清单 #10 的三重分歧
实证与修复：

- **y/z 电池 8 探针**：`x = chr(65)`（py 装箱 vs rs str 槽）、
  `y = s + "d"`（同，y2）、`zs = "lit"`（py 全局 vs rs main 局部——
  既有）、join（z2）、to_str（z3）、object 注解（y3，§3.33 已闭合）、
  函数域 chr（y4）、混合电池（z1）。
- **修复三点**：①py `_resolve_kind` 加 str 返回 builtin 表（chr/str/
  unescape/json_quote/read_file/read_stdin/read_line/input）与
  to_str/join 方法——**孪生可表达的 or-链**（frozenset 形式让自举
  构建炸 'call to unknown function'，教训⑩）；②rs str auto-decl 补
  模块上下文分支（IN_FN=false → 真全局 + free-old，int/float 先例——
  无条件局部 alloca 破坏跨函数引用）；③rs 无模块级名文件的 EOF 悬空
  空行（y4：main 尾空行在空尾上悬挂）。
- **两个测试前提过时**（input() 静态 str 化后不再动态）：动态值源换
  1 参 dict get 装箱 phi，拒绝契约保留。
- **验证**：8 探针字节+执行一致 == 解释器；51 探针清扫净；ll 30/30、
  ir 31/31、corpus 16/16、backend 18/18、run 4+14、wat2wasm 43/43、
  pytest **1403/2**（第 3 个原跳过被推断修复解锁可运行）。
- **既知残差**：read_line 为 rs 独有（py 响亮 'unknown function'——
  既有平面能力不对称，非本轮回归）。

**§四 终态**：1✅（str 生命周期）2✅（部署/发布）3✅（本轮）4✅
（g-list 终态，PROGRESS.md 在档）5=**用户门控**（P7 T1/T3 未触发——
升格产品/维护瓶颈/语料压力三者满足其一才立项，反触发条款明确）6✅
（cp_offset 已随 v1.24.0 退役）。**无遗留可行动项**；PROPOSALS.md
六提案与 P7 立项均须用户裁决（硬约束 4）。

## 三点三十六、语义轮：编译产物对齐 CPython（2026-11-26）

**起因**：304 探针扫描（/tmp 电池，五平面对拍）发现约 20 种
"每个字节门禁都绿、`silu build` 也接受、答案却错或段错误"的程序。
本轮按严重度逐个修到根因；每条修复先 `siluc1 < X.si` 留参照、
CPython 生成期望、多平面执行对拍后才动手。

**修复清单**（全部已提交，详见 CHANGELOG "Unreleased"）：

| 类别 | 根因 | 修法 |
|---|---|---|
| typed dict 边迭代边改 | 循环一次性抓 table/keys/vals；按哈希槽走 | 按 entry 数组走（插入序）；reindex 保序；每步核对 count/filled/keys 指针，结构变化 `RuntimeError`；覆盖写不再 reindex（负载检查移到插入路径） |
| 动态 dict/set | 快照列表，体内改动无感知 | `pyobj_dict_count/used/entries_bits` + `pyobj_dict_watch` 运行时（set 走 tag 8 长度） |
| list 循环 | 长度快照（items 指针也提升） | 活动长度 + 每步重读 items |
| str 循环 | 体内重绑定后被迭代的缓冲已释放 | `_body_rebinds` 判定 → `rawstr_copy` 快照；`loop_str_cleanups` 在 return 路径释放 |
| 推导式 | 元组目标被跳过；目标名泄漏 | 三个前端解析元组目标；`_push/_pop_comprehension_scope`；typed 槽仅在元素种类已知时解箱 |
| dss 借用 | 读结果被当新鲜临时 | `_mark_borrowed_str`：赋值拷贝、语句释放跳过 |
| del xs[i] | 装箱后对拷贝做 dict_pop | `rawlist_delete_at`/`rawlist_str_delete_at` + `pyobj_delete_dispatch` |
| 其余 | pow/range/count/kwargs/arity/defaults/for-else/None 打印/dict ==/s += 双求值/移位与 int(float) 检查/strbuf 非常量构造/IEEE-754 字面量 | 见 CHANGELOG |

**门禁升级**：

- `tests/test_semantics_vs_cpython.py`（217 项）：期望由 CPython 现场
  产生，**Python 平面与自举平面各跑一遍**（转换器有两份实现，只测
  一份看不出孪生有没有跟上）；另有 MUST_REJECT / MUST_PANIC 两表。
- `diff_harness.py` ll 模式对逐字节一致的模块跑真 llvmlite
  `parse_assembly + verify`——**同轮当场抓获** del 运行时的 phi 不
  支配（`del_negative` 里引用了 `del_bounds` 才定义的值）：clang
  照样汇编、四平面字节一致，只有 pytest 红（164 个）。
- `tools/gates.sh` 失败时完整 pytest 输出留 `gates-last-failure.log`
  并按文件汇总（屏幕只有最后 25 行，164 红只看得到 24 条）。
- `tools/regen_rust_prefix.py`（`--check` 入门禁）。

**语料**：33 文件。新钉板 `selfhost/comp_unpack.si`（推导式元组
目标 + 遮蔽还原，三前端 + rs 逐字节）；`dict_str.si` 扩所有权形状；
`record_global.si` 扩模块级属性赋值。comp_unpack 最初放
benchmarks/ 被 ir2c 拦下（m5 要求每个 benchmark 过 C 后端）→ 移到
selfhost/（float_edge 先例）。

**rs 神谕镜像**：typed list 循环（`riter`/enumerate）长度移入 cond、
generic `conv_dyn_for` 与推导式的 dict 监视 + 活动长度、动态 for 的
元组目标、推导式元组目标与作用域、`borrows_dict_entry`（dss 借用）、
模块级实例属性赋值、`reg_py`（模块级 pyobj 名是全局不是 alloca）。
前缀 421,380B。

**C 后端 ir2c 顺手修复**（dict_str 扩容后被 m5 暴露）：模块级 str
`+=` 发出 `Str* + Str*`（clang 编译失败）→ `str_add`；`t = s + "d"`
的 `str_add` 原地改写左操作数并让 t 别名 s → 只在被重新赋值的槽上
原地（`str_inplace_ok`），其余 `str_concat`；dss 的下标/get/
setdefault 读交出 `str_copy`。

**验证**：全门禁绿——ir 33/33×2、ll 32/32×2（含 verifier）、pytest
**1636/2**、m5 C 后端 benchmark 全量对拍。~~70 探针 ASan 零报告~~
——**作废**：当时对 `.ll` 直接 `clang -fsanitize=address`，没有任何
插桩（§3.37）。

**既知残差（未修，入 §四）**：rs 字母表缺口（typed dict 参数/循环、
typed 槽推导式遮蔽、模块级 str `+=`、整只 dss print——均 bail）；
ir2c 的 `d[k] = v` 存储仍别名；wasm 后端的 dict 循环是
`idx < $ds_len(d)` + `$ds_key(d, idx)` 的活动下标走法——体内插入/
删除不报错（与原生平面的 RuntimeError、与 CPython 都不一致，
wasm/test_backend.mjs 未覆盖该形状）；一参 `d.get(k)` 对
dict[str,str] 未命中返回 `""`（有意设计，已记入
docs/semantics.md，解释器仍回 None——平面分歧，待裁决）；set/tuple
的 repr 与 CPython 不同（`{'a'}` 打成 `['a']`）；多生成器推导式
（`[x for a in b for x in a]`）两个替代前端仍拒绝、Python 平台报
`name 'e' is not defined`；`bool()/all()/sorted()/zip()` 重写成不
存在的 `_builtin_*`。**教训 11-13 见 §六。**

## 三点三十七、内存安全轮：真 ASan 与编译器自身的崩溃（2026-11-26 续）

**起因**：语义轮收口后 `gates-last-failure.log` 里留着一条
`regen_rust_prefix: siluc1 failed on jsonparse_json.si: b''`，当时
归为"与重建竞态、重跑即绿"。复核时去查
`~/Library/Logs/DiagnosticReports/`——**5 份 `siluc1` 段错误报告**
（01:49、02:06×3 在 `_typed`，02:35 在 `pystr_cp_entry`）。不是竞态：
编译器二进制自己在崩，崩不崩取决于堆布局。

**先修验证工具**：对 `.ll` 直接 `clang -fsanitize=address` **一个函数
都不插桩**。对照实验：同一段越界读，C 源码输入报
heap-buffer-overflow，`.ll` 输入静默通过（-O0/-O1/-O2 皆然，二进制
里零个 `__asan_report` 符号）。机制：clang 只插桩带 `sanitize_address`
属性的函数，C 输入由前端自动加，IR 输入没有。手工给 `define` 加上
属性后立刻报错。`tools/asan_run.py` 把这件事做成工具（加属性 +
`malloc(2)` 读第三字节的对照）。

**修复清单**（每条都是真 ASan 先复现、修后干净、CPython 对拍）：

| 根因 | 现象 | 修法 |
|---|---|---|
| `pystr_cp_entry` 构表循环为写哨兵多转一轮，`load data[bytes]` | 装箱 str 的 `len`/下标/切片在精确大小缓冲（`s[i]`、切片结果）末尾后读 1 字节；02:35 那次编译器崩溃 | 与计数同一谓词的一次有界逐字节扫描（`o < bytes`），哨兵 `offs[cp] = len` |
| `rawstr_cp_off_at` 同一模式（按首字节长度跳跃 + 多一轮） | typed str 码点缓存：`utf8_probe.si` 200 字节缓冲末尾后读 1 字节 | 同上；顺带消除畸形字节下与表头 cp 的失配 |
| `rawstr_append` 的 realloc 可能在拷贝之下释放源 | `s = s + s`（窄窗原地追加把 s 自己的缓冲当源）：use-after-free，12 次加倍后 `s[-1]` 为空 | 源在目标缓冲内时不 realloc，分配-拷贝，旧缓冲在追加拷贝之后才释放（第一版在拷贝前就 free，门禁探针当场抓回） |
| `_emit_sub_search` 命中后直接返回字节偏移 | `find/rfind/index` 在非 ASCII 串上返回字节偏移：`"aé中bñc".find("中")` 得 3，`t[t.find("中")]` 取到 `b` | 返回 `pyobj_utf8_cp_count(s, at)`；ir2c 的 C 版同修 |
| `_field_slot` 用 `str(inst_ptr.type) == "i64"` 判 i64 槽 | **自举转换器**对 `it: Rec = items[i]; it.ret = v` 必崩（10-25 起）；`selfhost/ir2c.si` 因此从未被 siluc1 编过 | 缓存类型比较 `inst_ptr.type == ir.IntType(64)` |
| 文本渲染器对空操作数直接解引用 | 上面那条崩在 `_instr_body`，无任何信息 | `_instr_body` 响亮 `ValueError`（两份锁定孪生同步） |
| 动态方法表把 void 调用结果当值返回；typed/dynamic `append` 返回列表自身 | `r = d.clear()` 生成 `store void`（clang 报内部错误）；`xs.append(x)` 的值是列表 | 按方法名绑定 None（`_NONE_RESULT_METHODS`）。**不能读表里的 `has_result`**：那一列从未被读取（return 的两个分支原本相同），对 startswith/endswith 也是 False——读了之后 `startswith` 返回 None，转换器自己的 `_is_inst` 失效，6 个语料文件在自举平面 `KeyError` |

**为什么实例属性赋值那条一个多月没人发现**：`_field_slot` 的写法
本意是双平面通用（注释写明 isinstance 不可用），但孪生里
`str(类型记录)` 恒为 `"None"`；语料里没有这个形状，而唯一含它的
`selfhost/ir2c.si` 不在 ll 语料里（第 36 项是 `ir_interp.si`）——
ir2c 一直只由 Python 平面构建。现在：语义门禁
`instance_word_local_field_store`（双平面 + 解释器）；修后 siluc1 编
ir2c.si 与 Python 平面逐字节一致（2.68MB）。rs 神谕对它是响亮 bail
（`attribute assign base`），故不进跨平面语料。

**门禁**：`tests/test_asan_runtime.py`（124 项，本地 53s，fast 层）=
语义用例源码 × 两平面 + 11 个内存形状 + 9 个语料文件（conv 平面）。
**对修复前的编译器与源码实测**：三个代表性程序在两平面上全部被标
（2× heap-buffer-overflow、1× heap-use-after-free）。
`tests/test_asan_compiler.py`（34 项，约 3 分钟，慢层——ci.yml 的
gates 作业；fast 作业 ignore）：**编译器二进制自身**跑真 ASan 编全部
语料 + `selfhost/ir2c.si` + 自己的转换器（`silu_conv_main.si`，12K 行
→ 19.7MB IR，31s），无报告、rc=0、与普通二进制逐字节一致。这也是
唯一一道让自举转换器去编 ir2c.si 的门禁（教训 17 的盲区由它闭合）。

**语料**：`benchmarks/str_methods.si` 追加非 ASCII 的 find/index
（四实现：两转换器平面、rs、ir2c + m5 对拍 CPython）。`print(s[i])`
与 `rfind` 未入板：rs 对前者的打印分派本就与 Python 平面不同
（装箱 `pyobj_print` vs `printf`），对后者 bail。

**电池**（真 ASan，/tmp/silu_audit/asan/battery.py，一次性脚本）：
语义 63×2、语料 32×2、探针 867×2（CLEAN 678/680，189/187 个被
正确拒绝）——**零报告**。全量 pytest **1810/2**（隔离 worktree
wtI，含两道 ASan 门禁）。注意直接 `siluc1 <
selfhost/typed_codegen_flat.si` 会报 `NameError: name 'llvmlite' is
not defined`（stdin 源没有目录，前端解析不了 import），不是回归；
要编转换器请从 selfhost/ 目录喂包装源 `silu_conv_main.si`。

**既知残差（未修，入 §四）**：`upper()/lower()` 只映射 ASCII（已记入
docs/semantics.md §2，Unicode 大小写表需裁决）；`print(a, b)` 逐个
求值并立即输出——后面的参数改了前面的可变参数时与 CPython 不同
（解释器同 CPython；已记入 semantics.md §3.6，属设计取舍）；rs 字母表
缺口扩至函数内实例属性赋值、`str.rfind`、`print(s[i])`；ir2c 的
`d[k] = v` 存储别名；`strip(chars)` 的拒绝消息对 typed str 误称
"dynamic values"；typed dict 的 `update`、动态 list 的
`extend/insert/remove/reverse/sort` 不支持（响亮）。

## 三点三十八、打磨轮：四平面探针电池 + 差异文档 + wasm 响亮化（2026-11-27）

用户指令：按优先级依次修 bug（从根源规避）、写真实 Python 程序对拍
发现新 bug/差异、upper()/lower() 暂缓入 TODO、循环先删后插 panic
设计保留但需单独文档、不引入新特性、通宵运行（定时器驱动）。

**v1.25.0 已打 tag 发布**（release workflow success；dispatch 的
gates 作业在 CI 上 **success**——编译器 ASan 门禁首次在 GitHub 上跑
通）。tag 的 wasm 作业红：`wat2wasm` 对 `benchmarks/record_global.si`
报"empty identifier"——该语料 11-25 才进 benchmarks/，node 层 wasm
门禁自 11-22 后没跑过，回归带着发布溜出去。三个根因全在
selfhost/wasm_backend.si：①模块级全局/局部声明扫描对 assign 目标
一律 elem_str——属性 store 的目标是列表节点，得 ""，声明出无名
`(global $ ...)`（非法 WAT，wabt 拒绝）；②assign 发射器同样落进
名字路径；③`emit_expr` 兜底 `return "(i64.const 0)"`——任何未识别
表达式静默求 0（模块级 `print(c.x)` 打 0 = 错误字节）。修法：声明
扫描只认字符串名目标；属性 store 发射 `(unreachable)`；
`emit_expr` 加显式 attribute 响亮臂 + 兜底改 `(unreachable)`。
**教训：①IR 里 assign 的纯名字目标是字符串、属性目标是列表节点，
对字符串 JValue 调 tag() = 段错误（arr[0] 下标 None）——判目标形状
用 `.kind == JKind.STR`；②node 层 wasm 门禁（shim/run/backend/
corpus/wat2wasm/compile）不在本地 gates.sh 里，只有 CI 的 wasm 作业
跑——本地全绿 + CI wasm 红的组合已出现两次，值得把 node 门禁纳入
本地收口清单；③wasm/artifacts 的 siluc1.wasm 是 11-17 旧物
（内嵌内存安全轮之前的运行时前缀），test_compile 0/30 假红——重建
后 30/30。** 七门禁绿：wat2wasm 43/43、backend 18/18、run 4+14
loud、corpus 16/16、compile 30/30、shim 252、pytest 不涉。

**四平面探针电池**（/tmp/silu_night/battery.py，120+ 探针 × 4 平面：
CPython / interpret / siluc / siluc1→clang）。收获：
- **解释器接受面 ≫ 编译平面**：try/except、lambda、import、yield、
  闭包、with、% 格式化、assert、文档字符串解释器全支持（参考语义）；
  编译平面响亮拒绝。`raise` 编译平面是**响亮 panic**（支持，无捕获）。
- **真 bug（编译平面静默错误字节，按优先级修复中）**：
  ①`-2 ** 2` 编译得 4（CPython -4）——一元负号与 `**` 的优先级，
  解释器对、两个 typed FE 错；②`find/rfind/index/startswith/
  endswith` 的 start/end 参数被静默忽略（`"abcabc".find("c", 3)`
  编译得 2）；③`replace("", x)` 编译得空串；④**tuple repr 打
  `[...]`**（`print((1, 2))` 得 `[1, 2]`，含嵌套容器内）；⑤
  `repr("a")` 不加引号；⑥f-string 的 `{x:.2f}`/`{x=}`/`{x!r}` 编译
  平面静默忽略 spec（解释器响亮拒绝）。
- **响亮一致性欠账（解释器静默错，编译平面响亮）**：`global`/
  `nonlocal` 被解释器接受但忽略、`sorted(key=, reverse=)` 被解释器
  静默忽略、walrus `:=` 解释器误解析成 None 再报运行时错——全部待
  改语法期响亮拒绝。
- **文档修正**：docs/semantics.md §3 旧断言"先删后插大小不变时
  CPython 继续迭代"**是错的**——CPython 3.12 实测同样 raise
  （`dictionary keys changed during iteration`，电池实证）；Silu 的
  panic 行为与之一致，仅消息不同。设计按用户裁决保留。
- 新文档 **docs/python_differences.md**：全部已知差异一页清单
  （数值/字符串/容器/类/函数/语句/输出时机 + 内建与方法支持矩阵），
  每条带探针背书。

**既知残差（入 §四）**：ir2c `d[k] = v` 存储别名（P0）；rs 字母表
缺口（typed dict 参数/循环、模块级 str `+=`、整只 dss print、函数内
实例属性赋值、`rfind`、`print(s[i])` 字节分歧）；`strip(chars)` 对
typed str 的拒绝消息误称 "dynamic values"；编译平面缺 `lstrip/
rstrip/insert(typed)/popitem/sum/min/max/abs/bool/sorted/zip/
enumerate/map/reversed/divmod/round`（响亮，属能力边界非 bug）。

## 四、其余 TODO（优先级序）

- [ ] **电池轮 P1 静默错误字节清单（2026-11-27，修复中，按优先级）**：
  ①`-2 ** 2` 编译得 4（一元负号 vs `**` 优先级，两个 typed FE）；
  ②`find/rfind/index/startswith/endswith` 的 start/end 参数编译平面
  被静默忽略；③`replace("", x)` 编译得空串；④tuple repr 打 `[...]`
  而非 `(...)`（含嵌套容器内）；⑤`repr("a")` 不加引号；⑥f-string
  `{x:.2f}`/`{x=}`/`{x!r}` 编译静默忽略 spec（响亮化）。**响亮一致性
  （解释器侧）**：`global`/`nonlocal`/`sorted(key=,reverse=)` 静默
  忽略、walrus 误解析——改语法期响亮拒绝。证据与明细见 §3.38 与
  /tmp/silu_night/battery.py（电池脚本，results.json 同目录）。

- [ ] **`upper()` / `lower()` 的 Unicode 边界——用户裁决：暂缓**
  （2026-11-27）：维持文档化边界（只映射 ASCII 字母，非 ASCII 原样；
  已记入 docs/semantics.md §2 与 docs/python_differences.md §2）。
  后续三条路备选：维持现状；引入 Unicode 简单大小小写映射表（约
  1,400 对，运行时体积 + 每 str 方法族四平面/rs 前缀重钉）；或在
  遇到有大小写映射的非 ASCII 码点时响亮 panic。`"ß".upper()` 的
  多字符展开 CPython 也与简单映射不同。
- [ ] **rs 神谕字母表**（§3.36/§3.37 残差）：typed dict 作函数参数
  （`param type in f` bail）、typed dict 循环（按 entry 走 + 监视）、
  typed 槽的推导式遮蔽、模块级 str `+=`、整只 dss dict 的 print；
  §3.37 新增：**函数内实例属性赋值**（`attribute assign base` bail）、
  `str.rfind`（`method base type` bail）、`print(s[i])`（rs 直接
  `printf`，Python 平面装箱 `pyobj_print`——不是 bail，是未被语料钉住
  的字节分歧）。每项先拿 `silu-conv` 单跑最小探针看 bail 位置；补齐后
  把对应形状入钉板（否则这些能力只受语义门禁保护、rs 不参与）。
- [ ] **ir2c 的 str 所有权**：`d[k] = v` 存的是 v 的指针（应拷贝）；
  `str_concat` 对 `f() + "x"` 类左操作数每次新拷贝（调用结果是
  独占的，可原地）。正确性优先于性能，前者是真别名 bug。
- [ ] **一参 `d.get(k)` 在 dict[str,str] 上的未命中语义**：编译返回
  `""`、解释器返回 None、CPython 返回 None——需裁决（改编译要动
  dict_str 钉板 + rs 的 PStr 臂；改解释器则偏离 CPython）。
- [ ] 解释器 `global` 被接受但被忽略；`sorted(key=, reverse=)` 被
  忽略；set/tuple repr 与 CPython 不同；多生成器推导式在三个前端
  的支持面不一致；wasm 后端 dict 循环的体内结构变化不报错。

1. ✅ **str 临时值生命周期（2026-11-14 深夜落地，追平两平面）**：
   单表达式 `SRC[0][n]` / `SRC[0][a:b]` 的内层 rawlist_str_get 拷贝
   过去无人释放（泄漏；wasm 平面曾致二次方）。现在：
   - **追踪**：rawlist_str_get / rawstr_slice 结果按 SSA 值的 NAME
     字符串注册为 owned（`_owned_str_fresh`）；视图创建时父缓冲为
     owned 则登记 `_owned_view_parent[view.name] = parent`；视图消费
     （char1 coercion）后 free 父缓冲；slice 消费 owned 父缓冲后 free
     并注册 slice 结果。**键 = name 字符串**（llvmlite NameScope
     per-function 去重）——str 键两平面（真 llvmlite / llvmlite.si）都
     是已证形状；**I64 coercion 不 free**（只读视图 SSA 字段，同一
     视图可能再 RAWSTR coerce）。
   - **函数边界清空**：llvmlite 名字每函数重启——字典模块级持久会
     跨函数键名冲突（wat2wasm float 文件的 shim double-free 实证），
     函数入口 clear。
   - **变异经辅助方法**（字典作 LOCAL 参数）：selfhost 孪生不可表达
     属性字典下标赋值（`self.d[k] = v`）与 set.add（mangle 成
     `.add(x, '', '')`）；flatten 拒绝默认参数值（正确行为）。
   - **配套修复**：view+view concat 落算术 promote（typed_expr 的 +
     分派缺 RAWCHAR_VIEW 臂 → seq 长度当 int 相加）；Rust conv 双拷贝
     + bool 属性条件臂（见上条）。
   - **Rust conv 未移植追踪**：钉住语料无组合下标形状 → ll 20/20 不
     变；未来语料出现该形状时 ll 门禁会响亮拦截，届时按 name 键方案
     移植（Rust 侧文本发射器的值同样有名字）。
   - 语义验证：m0/m1/m2/m3/own_probe 五探针（组合下标/切片/concat/
     len/ord/循环内下标）native 输出逐字节对拍 CPython；九门禁全绿
     （ll 20/20、ir 21/21、pytest、backend 18/18、corpus 15/15、
     run 4+14、wat2wasm 33/33、shim 252/252、compile 20/20）。
   - **driver 运行时缓存陈旧会伪装成编译器损坏**（M4 乱码/未知函数
     '0'），删 `~/.cache/silu-runtime/driver` 重建是第一步排查；
     **构造器路径依赖急拷贝**（`_emit_construct` 直接 store，无拷贝
     则字段别名源缓冲 → 编译器自腐蚀）——两条均本轮实证。
2. ✅ **公网部署上线（2026-11-14 深夜，docs/wasm_todo.md TODO #1 关闭）**：
   https://silu.askender.xyz/playground/ —— wasm/web/ 产物推 silu-lang
   公开仓 docs/playground/（Pages main/docs），EN/ZH 落地页加导航。
   真浏览器全流程验证（编译 .ll/.wasm + 执行）。**GitHub Actions
   Billing 需用户处理**（jobs 0 步骤拒启："recent account payments
   have failed"），wasm job 的下载 URL/tar 结构已本地预验证
   （wabt 资产名 404 已修：-linux-x64 非 -ubuntu-x64）。
   ✅ **v1.18.1 已公开发布（2026-11-10）**：
   https://github.com/askender/silu-lang/releases/tag/v1.18.1
   （gates + 4 平台全绿，promote 校验通过）。**根因备忘**：GitHub 退役
   `macos-14-arm64-us-default` 池，release.yml 是唯一用 macos-14 的
   workflow——7 次秒杀全部由此；已迁 macos-15（b9b1e4d）。**注意**：
   tag push 用 tag 所在 commit 的 workflow 文件，改 CI 后必须把 tag
   前移（v1.18.1 现指 e3f5713，编译器源码与 bced6d9 一致）。驱动速度
   门禁 0.25→0.50（macos-15 镜像慢 ~15%，e3f5713）。
   **当前工作重心已切换：WASM 化 L0/L1/L2，计划见 `docs/wasm_plan.md`。**
2. ✅ **pytest 全量其余偶发单失败（m4/driver/pipeline 簇）——修复已落地**：
   代码审查确认的竞态面（ensure_* 并发重建读方撕读）已在
   tools/selfhost_build.py 修复——**每个 ensure_* 持进程级可重入
   flock（build_lock）+ 产物一律写临时路径 os.replace 原子落位**（
   头注明载 SIGSEGV 竞态史）；2026-11-18 复核确认，本条旧文本的
   "无锁/非原子直写" 已过时。历史偶发另注意教训 5：本簇部分为
   parity 真回归的误判，已被 02b53a3/bdd39fc 顺手消灭。
3. g-清单 #10：未注解局部从 chr()/concat 初始化的推断分歧（Python 保持
   pyobj vs Oracle 推 str；`object` 注解 Oracle 空 bail）→ utf8_probe 因此
   无动态段；动态语义由 tests/test_utf8_runtime.py 执行级守护。深水区，
   等需要时再做。
4. g-清单其余（PROGRESS.md"Oracle 未钉形状清单"）：等语料压力（T3）。
5. P7（Rust 独立编译器）：T1/T2/T3 未触发（reference/P7_RUST_STANDALONE.md）。
6. 小项：pyobj_utf8_cp_offset 死函数（**纯 Python 运行时独有**，孪生
   llvmlite.si 与 Rust 参照均无此函数；删除后 .ll 变化需重钉一轮门禁
   ——下次动前缀时顺手）。docs/ UTF-8 码点语义声明**已核实存在**
   （主仓 docs/semantics.md §2 + 公开仓 semantics_zh.md），此项完成。

## 五、环境关键（换客户端必读，AGENTS.md 已同步）

- **$PY312 = `/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3`**
  ——裸 `/opt/homebrew/bin/python3` 无 llvmlite，silu CLI 会**静默隐藏**
  build/llvm/verify 子命令，门禁以 "invalid choice" 全红（实证踩过）。
- `export PATH="$HOME/.cargo/bin:$PATH"`（cargo 不在默认 PATH）。
- 一切从仓库根执行；siluc rt 缓存 `~/.cache/silu-runtime/driver/`（自带
  内容校验+clang 身份戳，异常可整删）。
- SSH 降级：`GIT_SSH_COMMAND="ssh -i $HOME/.ssh/lb_ali_18 -o IdentitiesOnly=yes"
git push ssh://git@ssh.github.com:443/askender/silu-nightly.git main`
- git 推送三档路径（11-10 实证）：①直连 `ssh.github.com:443` 通常可用；
  ②直连失败且代理已开：HTTPS/gh 用 `export https_proxy=http://127.0.0.1:7897
  http_proxy=http://127.0.0.1:7897 all_proxy=socks5://127.0.0.1:7897`，
  SSH 用 `GIT_SSH_COMMAND="ssh -o ProxyCommand='nc -X 5 -x 127.0.0.1:7897 %h %p'"`
  （两条均实测通）；③代理也未开时用上面 lb_ali_18 直连降级。

## 六、本会话教训（新增四条）

1. **手写测试期望必须真跑 CPython 生成**——三次被自己的手写参照误导。
2. **Oracle 新 arm 位置敏感**：len 兜底首版放臂首短路 dict/list 的 pyobj
   臂，打破 8 个旧文件；插臂后必跑全量 ll 门禁。
3. **改运行时函数复杂度要同步审视编译期消费者**（.ll 渲染器孪生）——
   m8 一度 0.41s→355s。
4. **语料探针性价比极高**：utf8_probe 首跑抓获 3 个真 bug（含一个违反
   "宁报 ERROR"铁律的静默错误字节：步进切片丢步进）。
5. （补充）**"偶发竞态"结论要复现验证**：本失败两次被误判为竞态，
   standalone 复现后才确认真回归——全量跑失败先定向重跑一次再下结论。
6. （2026-11-21/22 dss 三轮）**siluc1 读 stdin 不读文件参数**——文件
   参数调用静默空转（rc=0 零字节输出）；差分前必须核输出尺寸。
   **conv rc=0 ≠ 语义正确**——rs 产物必须 clang+执行验证（三处被
   接受的错误字节全由执行暴露：int 装箱 phi 喂 pystr_to_rawstr、
   裸指针十进制打印、bits 当指针 free）。**转换器 py 源编辑后必须
   ensure_siluc 重建**（driver 不自动重建参考平面二进制；fingerprint
   只管运行时缓存）。**eval_expr 臂复用 dv**——重复载入差一槽的
   研磨签名（py .N vs rs .N+1 的同形 load）。**陈旧窗口教训第三次
   命中**（v1.23.0 的 29/29 跑在 e96ce39 吞臂前的旧二进制上）——
   提交前门禁必须用刚重建的平面二进制。
7. （2026-11-22 形状补齐轮）**"conv rc=0 ≠ 语义正确"的第三形态**：
   clang 接受且执行正确 ≠ IR 合法——aug concat 的 i64 位直传 i8*
   形参、str 值 set 传裸指针，clang 的 ABI 宽容让它们运行时碰巧
   正确、text 层渲染无校验，真 llvmlite 的 verifier 当场拒绝
   （test_text_layer_matches_llvmlite 响亮失败）——**llvmlite
   verifier 是第三执行比对平面**，钉板扩容是它的触发器。
8. （同轮）**前缀快照边界**：const_prefix.ll 重生成的公共前缀必须
   snap 到闭括号新行（`}\n`）——多带的空行与渲染器自身的
   inter-function 空行翻倍，ll 门禁 0/30 当场暴露。
9. （同轮）**手写期望第四次被真参照纠正**：dp 测试的 len 期望
   （pop "gone" 后 len=1 非 0）、解释器 panic 走 stderr 且消息是
   键 repr 非 "KeyError" 字样——先跑参照再写断言。
10. （2026-11-24 推断轮）**孪生子集无 frozenset**——推断表用 or-链
   表达集合成员（自举构建 'call to unknown function' 当场暴露）；
   追踪转换器行为要在**真实 JSON 流**上打点（IRGenerator 的 tuple
   形状是 FE 内部表示，convert 吃 list JSON——打错层全程无命中）。
11. （2026-11-26 语义轮）**字节一致 ≠ IR 合法**（教训 7 的第四形态，
   这次整段会话没人发现）：phi 引用了后继块才定义的值，clang 照样
   汇编、运行时碰巧正确、四平面一致——**ll 门禁现在自带 verifier**；
   改运行时发射器后若 pytest 大面积变红，先跑
   `tests/test_typed_codegen.py`（它调真 verifier）。
12. （同轮）**转换器有两份实现，修复必须两份都验**：模块级辅助函数
   放 typed_call.py 会被 flatten 丢掉（'call to unknown function'）
   → 一律放 typed_helpers.py 并加进 `__all__`；`getattr`/`setattr`/
   frozenset/默认参数/捕获嵌套函数都是孪生雷区。每修一处就
   `ensure_siluc` 重建后用同一探针跑自举平面。
13. （同轮）**新钉板有三道隐形门槛**：m5 要求 benchmarks/ 下每个
   文件过 ir2c；语料里每个形状 rs 都要能镜像；语义测试的源码字符串
   写错缩进就是死循环（`i += 1` 顶格，三平面一起"超时"，差点当成
   编译器死循环 bug）。先用多平面探针脚本过一遍再入表。
14. （2026-11-26 内存安全轮）**验证工具本身要先被验证**：对 `.ll`
   直接 `clang -fsanitize=address` 零插桩、零提示——"ASan 零报告"
   写进 STATUS 之前没有任何一步证明过探针真的被检查。任何"干净"
   结论都要配一个**已知会脏的对照**（`asan_run.control()`）。
15. （同轮）**"重跑即绿的瞬态失败"先查崩溃报告**：
   `~/Library/Logs/DiagnosticReports/siluc1-*.ips` 直接给出信号、
   地址与出错函数。一条 `b''` 的空输出失败被当成门禁竞态埋掉，
   背后是编译器二进制 5 次段错误。
16. （同轮）**孪生里没有 Python 的反射**：`str()`/`type()`/
   `isinstance(x, 某工厂函数)` 在自举平面上的含义与 CPython 不同。
   类型判断一律走两平面都成立的比较（`x.type == ir.IntType(64)`，
   类型对象两边都有缓存）。`_field_slot` 的 `str(inst_ptr.type)`
   在 Python 平面正确、在孪生里恒假，对一类程序必崩了一个月。
17. （同轮）**门禁的盲区 = 只由 Python 平面构建的文件**：
   `selfhost/ir2c.si`、`ir_interp.si` 等从不经过 `siluc1`；"自举
   编译器编不了自己的 C 后端"没有任何门禁看得见。新形状入了
   语义门禁（双平面）；是否把 ir2c.si 纳入 ll 语料待定（rs 会 bail）。
18. （同轮）**`silu/llvmlite_text.py` 与 `selfhost/llvmlite.si` 是锁定
   孪生**：只改一侧等于没改，且 `.py` 不在 siluc1 依赖表里连重建都
   不触发。我加的空操作数守卫两轮"无效"就是这个原因。
19. （同轮）**闲置的标志位不要顺手赋予含义**：方法表的 `has_result`
   两分支原本相同、从未被读取；我读它来决定"返回 None"，结果
   `startswith` 也变成 None，而转换器自己的 `_is_inst` 靠
   `startswith` 判实例——6 个语料文件在自举平面 `KeyError`，Python
   平面却正常。改一个分派条件前先列出它的全部取值与使用者。
20. （同轮）**新门禁自身的 bug 会伪装成编译器回归**：ASan 编译器对
   转换器包装源报 `unknown function 'conv_convert'`，实测是测试没把
   `cwd=selfhost` 传给被测进程（stdin 源解析不了 import）。先用同样
   的输入在 shell 里手工复现、对齐 cwd/环境，再怀疑被测对象。
21. （同轮）**语义用例也是程序**（教训 13 的又一形态，两次）：
   `clear()` 之后又去 `pop("a")`（CPython 自己 KeyError）；
   `print(d.setdefault(..), d, d.pop(..), d)` 踩到 print 逐个输出的
   设计边界。用例先在四平面脚本里过一遍再入表——这条已经写过。
