# 会话状态与 TODO（2026-11-10 凌晨，交接锚点）

> 交接快照：当前状态、未决事项、调查现场、关键教训。
> 规约细节锚点仍是 `reference/PROGRESS.md`；本文负责"接下来做什么"。

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
- **已知性能项**：~2s/KB（46KB WAT ≈100s compiled）——逐形字符串
  累积二次方；改 list[str]+join 是后续小项，playground 手输无感。
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
  不能代表自举版（flatten+silu 化后的行为差异要过 siluc1 全链）。驱动错误透传本轮即立功
  （探针的 ValueError 不再静默）。

## 四、其余 TODO（优先级序）

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
2. pytest 全量其余偶发单失败（m4/driver/pipeline 簇）：**本轮调查未复现**
   ——串行 ×1 + xdist -n4（缓存态）×1 + 强制 touch 源造并发重建 ×1，
   74 测试全绿（2026-11-10）。代码审查确认竞态面存在：tools/selfhost_build.py
   的 ensure_* 无锁，CONV_FLAT/FE_BIN/CONV_BIN/siluc1/siluc 均在最终路径
   非原子直写（对照 silu/runtime_cache.py:97 有 os.replace 原子写），
   并发重建时读方可撕读。**修复设计已备**：flock 串行化 ensure_* +
   构建到临时路径 os.replace 落位；**无复现证据不动构建工具链**（release
   链正用），等真复现（CI 慢机器窗口更宽）再实施。另注意教训 5：本簇
   历史偶发可能是 parity 真回归的误判，已被 02b53a3/bdd39fc 顺手消灭。
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
