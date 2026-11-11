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

## 三点六、WASM L2 子集 4b（str 索引/切片）——WIP 待续（2026-11-12）

**状态**：实现 ~95% 完成存于 `reference/wasm_str4b_wip.si`（相比已提交
的 d0ad45a 后端，新增 $cp_len_at/$str_get/$str_slice4 运行时、下标按
基类型分派、slice 节点 has-flags 发射；文件头两行多 2 个诊断用 export
——续作时删除）。已提交的 d0ad45a 后端保持 5/5 绿（str 基础面）。

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
+1 后变垃圾指针提前退出）。dict 哈希加速、dict 值类型扩展（float/
str 值）、print(dict) 渲染待做。切片版 strings.si 已毕业进正式门禁
（6/6）。

## 四、其余 TODO（优先级序）

1. ✅ **v1.18.1 已公开发布（2026-11-10）**：
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
