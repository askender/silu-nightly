# Rust 参照实现：进展与 TODO（2026-11-01）

> 钉住版本：silu 1.18.1（cp-offset 缓存重钉；1.18.0=strbuf，1.17.0=P6/P2/P5，原神谕 1.16.2 / 87df40f，
> 校准报告记录的是原钉）。本文是唯一的状态锚点——
> compact 后从这里继续。规约细节在 `reference/README.md`。

## P6 落地（2026-11-07，1.17.0）：字符串全局内容寻址命名

## strbuf 落地完成（2026-11-08）：Python 侧 + Rust Oracle 全同步

**ll 19/19（strbuf_probe 为第 19 个语料）+ ir 20/20 双实现逐字节一致。**
Oracle 同步收官要点（除下列清单外的关键修正）：
- eval_mod 与 eval_expr **各有独立的 name 分派**——is_local_buf 要加两处；
- ucall 打包有**两处 rll/返回 Typed**（方法区 6066 + 用户区 6230）；
- **签名表在 7931 区独立重建**（非 convert_func 的 atys）——参数/返回
  归一要做两次；
- push 语句层：append 后一个 silent（null 结果槽）；buf 声明后一个
  silent；pyobj_print 前一个 silent（void 槽）；
- **构造盒形状**：strbuf("lit") 常量构造**带 create_str 盒**（gep→
  create_str→再 gep→new_copy）——早先"main 无盒"是误读（snap 段的
  .113 gep 是盒链的第二个 gep）；空构造无盒；
- b == "lit" 快照：**load buf 先**、常量链后（.124 顺序）；
- 类字段族：空构造对每个 strbuf 字段发 malloc+空构造链+store；
  字段 push/to_str/len 的 fld 取 **get(1).get(1).get(2)**（字段名）
  而非方法名——attribute-of-attribute 基座；
- **cargo 增量可能不重编**（rm 二进制或 cargo clean -p 强制）。

以下为历史过程记录：


RFC：`docs/strbuf_rfc.md`。**Python 侧全链完成**（注解 BUF kind、
构造/push/to_str/len、引用语义、快照视图；ll 18/18 byte-identical
验收 ✓、ir 20/20 ✓、`tests/test_strbuf.py` 7 项）。**性能兑现**：
字段+跨函数 3M 拼接 34.9s → 0.07s（~470×）。

**Rust Oracle 同步（下轮续作）——已提取的形状基准**（来自
strbuf_probe 的 Python 输出，逐字节对齐用）：
1. **局部声明**：`%"b" = alloca i8*` **无 null store、无声 silent**
   （对照 RAWSTR 的 null-store silent）；alloca_ty 加 "buf"→"i8*"。
2. **空构造**：`gep @"str."` + `rawstr_new_copy(gep, 0)` + store。
3. **种子构造 strbuf("ab")**：`create_str(gep,2)` 中间盒 + **再 gep** +
   `rawstr_new_copy(gep2, 2)`（_rawstr_append_operand 常量路径）；
   buf 实参 → `rawstr_copy(src)`。
4. **push**：load buf + gep 常量 + `rawstr_append(buf, data, len)`。
5. **to_str**：`rawstr_copy(load)`。
6. **len(buf)**：bitcast + gep field 3 + load（码点数）。
7. **assign/别名**：load src + **直存**（无 copy、无 free、无 silent）。
8. **buf 参数**：alloca+store 成对正序（**容器参数模式**，无 split/
   null）；**任一 buf 参数 → 函数动态 ABI**（{i32,i8*}* 返回、无
   alwaysinline）。buf 返回：i8* 直 ret + alwaysinline 保留。
9. **快照视图**（b[0]/b == s/for ch in b/print(b)）：走 box
   （rawstr_to_pystr(load)）内容快照——Typed::Str 复用即得。
10. 无注解 `b = strbuf()` 一律 dynamic 报错（双侧行为一致）。
**同步进度（2026-11-08 第二轮，进行中——silu-conv.rs 已含下列改动且
编译通过，核心链对拍推进到"具名函数调用返回 buf"一处 Typed 映射）**：
已完成：FN_SBUF/is_local_buf/alloca_ty("buf")、conv_ann_assign strbuf
分支（无 null 无 silent 直存）、参数链（白名单/"buf"/任一 buf 参数→
动态 ABI/arg_ll i8*/容器对装载）、返回归一（两处白名单+"strbuf"→
"buf"+rty_ll）、eval_mod 三 arm（常量 push：load→gep→append 无
silent；to_str：load→copy；strbuf() 空构造 + 常量构造走 create_str
盒→再 gep→new_copy——probe make 形状）。
**剩余清单（2026-11-08 第三轮后：①②已完成）**：
① ✓ 调用链全通：签名表（7931 区的 atys/rt0 两处归一 "strbuf"→"buf"）、
   ucall 实参打包（str/inst/list 分支加 "buf"）、两处 rll（6066 方法区
   + 6230 用户区）与各自返回 Typed::Str、eval_mod 委托确认（用户调用
   → eval_expr "call"+name）。
② ✓ len(buf)：len arm 头部 is_local_buf 分支（load→bitcast→gep f3→
   load，与 str 同形）。
③ conv_assign 已声明 buf 直存（alias = b：load+store 无 copy 无 free
   无 silent）——**注意 Python 形状**：`.44 load b; store alias`。
④ 快照视图——Python 形状已全部提取（spc_ref.ll）：
   - b[1]：load buf → rawstr_to_pystr → create_int(1) →
     pyobj_subscript → pyobj_print（完全装箱路径）
   - b == "abc"：**常量 create_str(gep,3) 先**、rawstr_to_pystr(load)
     后 → pyobj_eq → print
   - for ch in b：load → rawstr_to_pystr → pyobj_iter_keys →
     object 迭代族（iter_idx/list_length/list_get/create_int）
   - **构造盒形状规则（重要）**：strbuf("lit") 在**函数内**带
     create_str 盒（我的构造代码 _convert_node 副作用：gep→
     create_str→再 gep→new_copy）；在 **user_main 内无盒**（单 gep→
     new_copy——main 层走了不同路径）。Rust 复现需按上下文区分
     （IN_FN 且非 user_main → 带盒）。
   core 对拍当前停在 snap[1]（to_raw on I64(".42")）。
⑤ 类字段族（字段类型表存原样 "strbuf"、emit 字段默认值构造
   malloc+构造链+store（Python 形状：malloc(8)+gep @"str."+new_copy+
   gep i8,block,off+bitcast i8**+store 两次）、字段 push/to_str arm：
   load base→gep off→bitcast i8**→load buf→常量 gep→append）。
⑥ strbuf_probe 移回 ll corpus（去 diff_harness 排除）→ 19/19。
**方法教训**：heredoc 里 Rust 代码的引号会毁掉 python 补丁脚本
（两度损坏 silu-conv.rs，git checkout 回滚+原子脚本文件
/tmp/patch_*.py 方式重放才稳）；插入 eval_mod 的 arm 要落在
if e.head() 链上而非 match 臂。

> **P5（布尔单例）同日落地**：@silu_true/@silu_false 两个不朽常量盒
> （tag 3、payload 私有）；create_bool = 一条 select（零 malloc），
> `x is True/False` = 一条指针比较（替代 11 指令
> and(non_null, and(tag==3, payload==want)) 链；null 自动涵盖；
> 语义对齐 CPython 布尔身份）。运行时契约：**未来任何递归 pyobj
> 释放必须豁免 tag=3**；审计确认除 create_bool 外无 tag=3 构造点。
> 连带修复：文本层 llvmlite 的 struct 常量 initializer 双包 bug
> （首个非零 struct initializer——单例——暴露）+ 自举层
> selfhost/llvmlite.si 补 gv_const_bitcast 孪生与同一 const_ 修复
> + **split 合成器第三连环**：单例是 `{i32, i8*}` struct 类型常量，
> 类型文本含**逗号**——两份合成器（runtime_cache.py 正则 `[^,;\n]`、
> siluc_main.c 的 comma 截断）都在逗号处砍断类型，external 声明残缺
> （`external constant {i32`）。bracket 配对优先于逗号截断（双侧）。
> （**运行时辅助必须三实现同步**：ir_iface 真层 / llvmlite_text
> 文本层 / llvmlite.si 自举层——P5 一度只改两份导致
> `name 'llvmlite' is not defined`，靠逐文件二分定位）。setattr 在
> 自举类不可用（单例构建展开写两遍）。前缀 368,756B。
> 新增 tests/test_bool_singleton.py 5 项。

> P2（常量 interning）同日落地于同版本：命中 bare 内容名即复用既有
> gvar，`~N` 后缀绝迹；silu_fe 常量 1,137 份（263 唯一）→ 262 份
> 全唯一（0 冗余），该文件 .ll 缩 ~51.5KB；前缀随之再提为 368,822B。
> 显式命名的运行时 panic 全局（str_keyerr/str_idxerr/json_typeerr）
> 是 ABI 形单份，不参与 interning（已记录的残留）。
>
> **P2 连环修复（interning 的边界效应）**：用户代码第一次跨
> "运行时/用户"两部分**复用前缀常量名**，暴露了两份 split 声明
> 合成器的 constant 盲区——`silu/runtime_cache.py`（rt_globals 正则
> 漏 `constant`，补 kind round-trip）与 `tools/siluc_main.c`
> （parse_runtime_symbols 只认 `"global "`；连环修三处：constant
> 关键字+9 字符偏移、strstr 越过行尾导致 global 漏收、bracket 类型
> 无终止扫描导致 initializer 泄入 external 声明）。两处都补了
> 回归测试（tests/test_runtime_split.py、test_siluc_driver 全量）。
> 教训：**任何"运行时前缀 ↔ 用户代码"命名空间合并的提案都要审计
> split/decl 合成器**（Python 与 C 各一份，双实现）。

1. **规则**：字符串全局名 = `str.` + 内容转义（白名单
   `[a-zA-Z0-9.]` 直通，其余 UTF-8 字节 `_xx` 小写 hex；`_` 也转义
   → 编码可逆、零碰撞）；重复内容 `~N` 后缀（N≥1，P2 interning
   落地后消失）。真 llvmlite 的 DuplicatedNameError 保证双平面
   被迫采用同一后缀方案。
2. **改动面**：Python 侧 `_create_global_string_with_builder` +
   `_str_global_name`/`_unique_str_global_name`（pyobj_runtime mixin
   方法；嵌套函数**不可捕获外层变量**——flatten 后是 Rust 语义，
   bootstrap 门禁会拦）；`_create_char_idxerr_global`（typed_codegen，
   历史上内联了旧计数式，属漏网点）。Rust 侧 `add_str` 重写 +
   main 预填扫描前缀中全部 `str.` 名（等价 Python 的
   module.globals 查询）。
3. **前缀重提**：**必须用文本层平面**（`SILU_LLVM_IR=text`）提取
   ——conv/rustconv 对拍平面是自举文本层，datalayout 与真 llvmlite
   本机输出不同（新旧 pin 的 datalayout 形态也因此不同，属环境
   差异，重钉即消）。新前缀 370,740B。
4. **全局槽号模型整体退役**：STR_BASE/TAGGED_SLOTS/函数方法捕获
   计数/创建序交织章节全部作废（Rust 侧 sc 参数保留透传但无消费者，
   后续重构清理）。规约速查中"全局槽号"条目由本节取代。
5. **门禁**：ll 18/18 + IR 19/19 + pytest 1332/3skip +
   fixed-point 自举通过；siluc1/silu_conv 经 selfhost_build 重建。
6. **教训**：`while name in module.globals` 的 Python 侧查询含
   函数名（真 llvmlite globals 是函数+变量总表）——这正是旧计数
   "函数占槽"的根源；Rust 侧只预填 `str.` 前缀名即可等价。

## 总体架构

```
silu-fe  (Rust 前端)      : .si → IR JSON     ✅ 19/19 与 silu_fe 逐字节一致
silu-conv (Rust 转换器)   : .si → 完整 .ll     ✅ 18/18 语料逐字节一致（全部对齐）
diff_harness.py           : 平面对拍基架       ✅ 自校验通过
const_prefix.ll           : 365,264B 常量前缀   ✅ 跨语料恒定
```

- 位置：`reference/rust/`（cargo，零外部依赖，`src/main.rs` = silu-fe 2,509 行，
  `src/bin/silu-conv.rs` = 转换器 7,882 行）
- 运行：`cd reference/rust && cargo build`；对拍 `python reference/diff_harness.py ll conv rustconv`
- silu-conv 通过子进程调 silu-fe 取 IR（前端已独立验证）
- **非目标**：不做产品编译器、不进自举链、不做同步镜像（版本快照神谕）

## 当前状态：转换器 18/18 全部对齐 ✅

| 文件 | 能力面 | 状态 |
|---|---|---|
| fib/arith/float/string | 函数/if/while/panic对/typed算术/rawstr | ✅ |
| list/dict/trees | rawlist/rawdict 容器 + for-in riter + 函数族 | ✅ |
| fannkuch | 边界检查下标读写/负索引/`[0]*n` fill/裸赋值自动声明/break/if嵌套 | ✅ |
| nbody | list[float]/函数内模块全局/float局部逆序alloca/`**`→sqrt/一元负号折叠 | ✅ |
| spectral | list[float] 函数参数/none 返回类型/alloca 双轨(局部逆序+容器成对) | ✅ |
| mandelbrot | print(str 变量)/体内 str 声明 | ✅ |
| wordcount | str 层：PStr/pystr 拼接/str()/list[str]/dict[str,int] get 惯用法 | ✅ |
| knucleotide | str 切片(str_view)/elif 链/const 键 get_or + 标签检查 | ✅ |
| calc | **动态实例层全套**（class/enum/方法/match/sc短路/存储类型/epilogue/user-main） | ✅ |
| jsonparse.si | **pyobj 装箱动态层**（{i32,i8*}* 值树 + 90+ pyobj_* 运行时族 + match_class） | ✅ |
| jsonparse_json.si | **tagged-union Json 域**（{tag,bits} 块 + json_* 内建 + RAWLIST_JSON/RAWDICT_SJ） | ✅ |
| ir_interp.si | **混合实例/pyobj 平面**（变元短路、嵌套字段、dict 属性、bool/rawstr ownership） | ✅ |
| silu_fe.si | **全特性前端**（import 展开/动态 object 全域/嵌套函数提升/迭代器三态） | ✅ 1,492,988B |

**R2 完成（2026-11-07）：18/18 全语料逐字节一致。** 前端 19/19 + 转换器 18/18，
diff_harness 两个平面全部 PASS。Rust 参照实现使命达成：钉住 1.16.2/87df40f
的第二实现已可对任意语料复现参考输出，隐含规约提取完毕（见下）。

里程碑提交：`c25628d` calc.si、`cedef08` jsonparse.si（15/18）、
`f9fa865` jsonparse_json.si（16/18）、`e9cffcc` ir_interp.si（17/18）、
本轮 **silu_fe.si 逐字节对齐（18/18，1,492,988B）——全语料收官**。
本轮事故：git checkout 回退未提交工作树——已全部重放并验证；教训：**每达成一个
byte-identical 立即提交**。

**jsonparse.si 已完成（cedef08，15/18）——迭代 6 全函数跨过**

迭代 6 修复（201 行改动）：
1. **emit_sc 变长重写**：IR 的 and 是扁平变长节点（["and",op1,op2,op3]），
   原实现只读两个操作数。重写为：sc_end 块在首操作数求值前创建，每个后续
   操作数在 sc_next.k 块求值，最后一操作数直接 create_bool 收尾
2. 未拥有 str 参数直接 alloca+store（无 null；null 仅 split form）
3. alloca_ty 补 pyobj→{i32,i8*}*；FN_PY 注册表 + py_slot()（pyobj 局部
   解析 %"name" 而非 @"name"）；list_append/pyobj_subscript_set/name 装载
   走 py_slot；两个调用点补 none|pyobj→{i32,i8*}* 返回
4. Typed::Inst 裸赋值自动声明 = load 旧值+free+store（key=parse_string
   证据；call 结果多耗一 silent 槽：call .121, silent .122, load .123）
5. **emit_dyn_ctor 字段次序**：实参求值→转换(copy/to_f64/to_raw)→gep→
   bitcast→store（JStr copy 在 gep 前）
6. pyobj 被调者的 list 字面量实参走装箱域：create_list+create_int+
   list_append+pylist_to_rawlist（main 的 parse_value(doc,[0])）
7. **match 收尾规则**：conv_block 尾部在 case body 耗尽且当前块未终止时
   发 br 最内层 match_end。MATCH_END 栈（push 在 case 循环**前**）+
   LOOP_DEPTH/CASE_DEPTH 区分 case body（发 match_end）vs while/if/for
   body（由语句自身回环/merge）。内层 match 结束由外层收尾补 br 父 match_end
8. **全局槽号模型**（关键）：ref 的 `_create_global_string` 用
   `str_{len(module.globals)}`——槽号=模块全局表长度（含变量和函数）。
   `STR_BASE=297` 已含 main 包装；class/enum 仅占编译期表、不耗模块槽；
   每个顶层函数和方法各耗 1 槽（main  renamed 后也仅 1）；match_class
   每个捕获建 gvar、耗 1 槽。ir_interp 的 12 个方法证实方法必须预声明计数；
   早期“实例类额外占 1/main 双计”的局部近似已由本规约取代
9. len(names[i]) → rawlist_str_get（非 copy_into）；str 捕获先 rawstr_copy

**下一目标**：silu_fe.si（import 系，最后一关）。
jsonparse.si 输出 442,328 字节 = 参考，逐字节一致。

**jsonparse_json.si 已完成（f9fa865，16/18）——tagged-union Json 平面**

新平面（745 行改动 + tagged_prefix.ll 281 行静态模板）：
1. **tagged 运行时模板**：13 个 tagged_*/json_unwrap_* 函数 + json_typeerr
   常量 = **15 个模块全局**（不是 14，含 14 define + 1 常量）。检测 Json
   注解 → TAGGED flag + STR_BASE 偏移 +15，模板注入 const_prefix 之后、
   首个用户函数之前（后补一个空行）
2. **Json 类型**：注解 `-> Json`/`: Json`/`list[Json]`/`dict[str,Json]` 归一化
   为内部 "json"（i8* tagged 块指针，行为类 inst 但保留 alwaysinline）。
   arg_ll/rty_ll 补 json→i8*
3. **json_* 内建族**（eval_mod + eval_expr 双分派，后者让 expr_i64 可达）：
   json_tag→tagged_tag+sext；json_int→json_unwrap_int；json_str→
   json_unwrap_str+rawstr_copy；json_list/dict→json_unwrap_*→Inst；
   json_free→tagged_free(i8*,4,5,6)
4. **Json 返回装箱**（返回位置类型强制）：callee 返回 json → 直接 ret；
   str→rawstr_copy+tagged_new_ptr(4)；int→tagged_new_scalar(1)；
   list[Json] 局部→tagged_new_ptr(5)；dict[str,Json] 局部→tagged_new_ptr(6)。
   按 callee_rty（call）或容器注册（name）判源类型。**epilogue free 在装箱
   之后**（tagged_new_ptr 先于 ch free，parse_value 证据）——通用 free 循环
   对 rty=="json" 跳过，Json 分支内 macro free_str_locals! 在 ret 前发
5. **容器**：list[Json] 元素存指针位值（append=ptrtoint+rawlist_push；
   下标读=rawlist 边界检查+inttoptr）；dict[str,Json] 写=ptrtoint+
   rawdict_str_set；读=emit_const_key_direct（const 键 key_str_ok/err 检查+
   str_view 解包+rawdict_str_get，泛化自 emit_const_key_get 加 def:Option）
6. **split form 规则修正**：有显式返回注解（typed 路径）的函数 str 参数
   一律 split（_declare_var 对 RAWSTR 参数总是 null-init+逆序）；无注解按
   str_owned 扫描。这条区分了 jsonparse.si parse_value（pyobj 无注解→非
   split）与 jsonparse_json parse_value（-> Json→split）
7. **Json 下标读裸赋值自动声明**：it=items[i]/n1=o["id"]/w=o["name"] →
   目标自动声明 Json 全局（i8*），**rhs（含 panic 字符串）先于目标绑定**
   （_convert_node→_declare_var 次序）
8. 函数内 dict[str,Json] 局部：FN_D 注册表 + dct_slot()（%"o" 非 @"o"），
   name 求值（eval_mod/eval_expr）补 FN_D→Inst

**ir_interp.si 已完成（17/18，487,006B）——混合实例与 pyobj 平面**

1. **pyobj 序比较/短路**：ch=self.src[self.pos] 在裸赋值中经
   rawstr_to_pystr 成为 Pyo；>=/<= 发射 pyobj_ge/le。短路操作数以 ScVal
   显式携带 I1/Pyo：非末尾 Pyo 先做 null+pyobj_truthy 分支，sc_finish 直接
   保存原 Pyo（不 create_bool），末尾同样保存原值，sc_end 后统一 truthy。
   既有 i1 链保持 create_bool 形态。
2. **直接索引比较与 concat 的暂停形态**：条件中的 self.src[i] 不走 Pyo，
   而走既有融合 str_view/rawstr_eq_cstr；rawstr concat 左侧字符视图在
   insertvalue 后暂停，先求 rhs，再 extractvalue+rawstr_char1+concat。
3. **实例域扩展**：bool 构造字段/参数/返回均为 i1；is not None、in dict、
   read_stdin、ord、嵌套 call/subscript 基址字段读、dict 属性读写、空 dict
   构造均已覆盖。列表中的实例元素始终读为 i64 位值，属性访问时才 inttoptr。
4. **rawstr ownership**：普通字段读复制；静态方法 rawstr 实参复制，静态
   自由函数同类型实参不复制；rawstr 返回先 copy 再按声明序释放局部；
   属性 str 写为 rhs copy→base 求值→field coerce copy→free old→store。
   concat 在函数内释放转换/char1 临时，顶层 wordcount 形状不多发 free。
5. **typed prologue**：显式返回注解触发参数逆序 alloca、正序 store；
   rawstr 参数 alloca+null，参数 store 延迟；标量参数同步注册 FN_I/FN_B，
   不再误读为模块全局。隐式 str 返回释放局部后生成空 rawstr_new_copy。
6. **Json 内建与用户类同名**：只有内建 Json 注解且不存在用户自定义
   `class Json` 时才注入 tagged runtime；ir_interp 的 Json 类不再误触发。
7. **回归验证**：wordcount/calc 曾分别暴露顶层临时释放和实例列表表示
   回归，修复后聚焦 cmp 通过；最终全量 17/18，仅 silu_fe 的 import 仍 ERROR。
   `cargo test --quiet` 通过（当前 0 个单元测试）。

**silu_fe.si 已完成（18/18，1,492,988B）——全语料收官**

2,183 行前端全特性，迭代要点：
1. **import/from_import/c_extern**：无代码、无槽号的编译期声明。
2. **动态 object 全域**：`x: object`、裸 `list/dict/tuple/set`、未注解参数
   一律 pyobj 域；任一 pyobj 参数使函数走动态 ABI（{i32,i8*}* 返回、无
   alwaysinline、正序参数 alloca+store，不触发 typed split-form）。
3. **迭代器三态**：range → loop_init/cond/body/end/incr 整数计数器；
   enumerate(rawlist) → riter 家族 + __enum_ctr_N pyobj 计数器；
   enumerate/dict(object) → pyobj_iter_keys + list_length/list_get + iter_*；
   str 直接迭代 → siter_off/siter_seq 字节偏移 + UTF-8 宽度 + malloc 单字符
   rawstr（null store 在最终 bitcast 之前）。
4. **动态声明链**：str()/chr()/int(str,base)/float(str)/file_exists/read_file/
   isinstance(内联 isa_tags/isa_merge phi)/join/contains/嵌套 call 属性、
   if_expr（iexpr_val 槽 + then_s/else_s 写块）、list_comp（lc_cond/body/
   emit/skip/done）、dict 字面量 create_dict + dict_set。
5. **动态短路**：ScVal 携带 I1/Pyo；动态函数内 and/or 直接保存原 Pyo 到
   sc_result（无 create_bool），返回 object 的函数 ret sc_result 原值。
6. **rawlist 写回**：object 形参收 rawlist 实参时保存调用前长度，调用后
   pylist_to_rawlist_str + 长度 icmp ne(new,old) + select + 回写槽。
7. **槽位规约补遗**：新 RAWSTR 局部（含循环目标）声明时消耗一个 null-store
   silent；siter 的 silent 在 char-struct bitcast 之前；`is True/False` 固定
   形状 and(non_null, and(tag==3, value==want))；rawlist 写回长度比较操作数
   顺序 icmp ne(new, old)。
8. **验证**：前端 19/19 + 转换器 18/18 全部 PASS；`cargo test --quiet` 通过。

**下一目标**：T3 校准报告（见 TODO）。

**蓝图文档**（完整形状）（reference/DYNAMIC_SHAPES.md 提交 9a7f325）：
pyobj={i32,i8*}*（= none 型作值载体）、动态 ctor=malloc+pyobj字段+
pyobj_make_instance(CID=class定义序)、match_class=pyobj_instance_cid==CID+
instance_ptr+gep 捕获、动态容器 create_list/dict+list_append+
pyobj_subscript(_set)+pyobj_len_raw、str 序比较融合 rawstr_at_cmp_cstr
（>=/<= 不物化 char1，!= 仍走 char1+eq_cstr）。实现入口：加 Typed::Pyo
变体贯穿（参照 Typed::Inst 的先例，涉及全部 match 臂）；判别规则 =
untyped（无注解）值一律 pyobj。

原始规模备注（/tmp/jp_ref.ll 尾 77KB）：pyobj 动态层 = 值全走 {i32,i8*}*
装箱；匹配 class 用 pyobj_instance_cid(==类序号)+pyobj_instance_ptr+字段
{i32,i8*}* 装载；len(装箱list) = pyobj_len_raw；下标 = create_int+
pyobj_subscript；[0] 字面量实参 = create_list+create_int+list_append+
pylist_to_rawlist；**enum 提取序**里 JInt/JStr/JArr/JObj 的 cid=1/2/3/4
（JArr=3 已证）。这是第三种表示（静态 rawlist/rawdict 之外），建议下一轮
从 jsonparse 的 parse_number/digit_value（纯静态 str 层）先行，再啃 match_class。

之前提交（前轮 8 个）：`8428fc8` knucleotide、`7f31ccd` wordcount、
`f9cc50b` mandelbrot、`2abfbb9` spectral、`aa69e5b` nbody、`9c06ce8` fannkuch、
`12a6758` trees、`e6e2f5f` list+dict。更早：`05fd782` string 等。

## 核心实现模型（已在代码中验证）

1. **conv_block 递归分发器**：while/for/if/break 嵌套任意深度；break =
   直跳内层循环 end 标签（循环端标签栈）；if 空else仍建 if_else+br；
   then支break后不再补 br if_merge（terminated 标志）。
2. **槽位规则**：每条指令恰好消耗一个匿名槽；void 静默。函数序言 =
   N参数 + 1函数名 + N参数存储（2N+1；容器参数存储在拼接区但**仍耗槽**）。
   main 序言 = 1（函数名）。
3. **函数统一**：convert_func 复用 conv_block；FN_I/FN_F/FN_L 局部注册表
   （遮蔽模块全局）；alloca 提升 = 局部逆序 + **容器参数 alloca+store 成对
   正序**（标量参数走逆序块）；无返回注解 → `{i32,i8*}*` none 型 +
   隐式 `ret null` + **无 alwaysinline**。
4. **类型化求值**：`Typed::{I64,F64,Str(裸),PStr(pystr域)}`；
   拼接 = 双侧求值后依序 to_rawstr 再 rawstr_concat；str(int) =
   create_int + pyobj_str_conv；**常量一元负号编译期折叠**（0xbff… hex），
   名字用 fmul -1.0（非 fneg）。
5. **字符串计数**：模块绑定各耗一槽；**int/float 声明的槽在 rhs 求值之后**
   （spectral result 证据）；裸赋值未声明名 → rhs 后自动声明（fannkuch）；
   但 list[str] 读的 w 赋值例外（目标先声明——copy_into 需要它）。
6. **尾部全局 = 严格创建序**（字符串与变量交错）；最后一条无换行。
7. **下标三态**：list int/float 读写走 get_ok/set_ok 边界检查对
   （**ok 先建、err 后建**——与 panic 对的 bad→ok 相反！）；float 元素
   i64 装载后 bitcast（写侧 bitcast 在 gep **之前**）；aug-subscript =
   **无检查** RMW（gep field 2 直达）；dict str 键走 rawdict_str_* 族。
8. **切片**：`dna[s:e]` = subscript(dna, slice) AST；rawstr_slice_parts +
   str_view 临时结构体（4 字段存储 len,len,chars,len）+ bitcast；
   view 的 alloca 提升到函数/主 entry（逆序）；const 键 .get 走
   pystr 标签检查对（key_str_ok/err，`TypeError: expected str key`）+
   rawstr_to... get_or。
9. **常量前缀**：365,264B，include_str! 嵌入；用户串计数基数 297。

## 已发现的隐式规约（38 项，全部差分实证）

strtod十六进制 / enum提取序 / 空名槽位 / 常量前缀边界 / 幻影槽公式 /
槽位机制 / 字符串计数顺序 / panic后缀数标签定义行 / 尾部无换行 /
模块绑定耗槽 / panic-ok续体 / 模块全局领先尾部 / mod-floordiv形状 /
floordiv修正加在商上 / alloca在entry后 / llvmlite hex空格填充 /
str绑定先造常量再耗槽 / 有值调用一槽 / 创建序全局块 /
**尾部严格创建序（串与变量交错）** / llvmlite 重复名 .N 后缀（块+alloca
共享函数级命名空间） / while/if/for 标签独立计数 / for 目标耗槽+全局 /
panic对 bad→ok vs 边界对 ok→err / 下标赋值序（list: obj,key,value+检查；
dict: obj,value,key） / 负索引 select(Python语义) / fill 循环形状
（new寄存器直存全局/自增不检查/float先bitcast后load） / 裸赋值自动声明
（rhs先）/ in-body ann_assign 耗槽 / print 交错求值打印+空格分隔 /
print str const = %.*s(len,gep) / print str 名 = 字段0+2 / 函数序言2N+1 /
容器参数 alloca 成对正序 / none 型无 alwaysinline / int/int `/` 用
**icmp** 零检查（浮点用 fcmp） / int/float 声明槽在 rhs 后 / 常量一元负号
折叠 / aug-subscript 无检查 / 切片 str_view 逆序提升。

## TODO（优先级序）

### T2c 动态实例层（calc → jsonparse×2）✅ 完成
- calc（c25628d）→ jsonparse（cedef08）→ jsonparse_json（f9fa865）

### T2d import 系（ir_interp → silu_fe 终关）✅ 完成
- ir_interp.si ✅ 487,006B；silu_fe.si ✅ 1,492,988B——18/18 全语料逐字节一致

### T3 校准报告（R3）✅ 完成
- 报告：`reference/CALIBRATION.md`（规模对照、参考特性分诊、设计建议、方法论）

### 方法提醒
- 每个新文件：读参考尾 → 实现子集 → 差分迭代（本轮多数文件 1-2 轮可达）
- 差分命令：
  ```bash
  cd reference/rust && cargo build
  ./target/debug/silu-conv ../../benchmarks/X.si > /tmp/r_X.ll
  # 与 ./siluc1 < benchmarks/X.si 输出 cmp（前缀恒定可直接整文件比）
  ```
- 未支持构造一律 `bail()` → exit 3（宁报 ERROR 不出错误字节）
- **python 补丁脚本两大坑**（本轮反复返工）：heredoc `\\"` 与 Rust 字面量
  双层转义（改用"提取区域→变换→回写"或 Edit 工具）；断言失败的批次
  **全部未写入**（每个补丁独立写盘）。稳妥套路：`BS=chr(92); Q=BS+'"';
  seg=Q+'{}'+Q` 构造含引号的 Rust 代码，先 `assert seg == '\\"{}\\"'`
- 每文件过完立即跑全量 `diff_harness.py ll conv rustconv`（防回归）

## R0 以来产出

- 差分基架 + 契约（4a3f446）/ Rust 前端 19/19（b43a7cf）
- .ll 解剖 + 常量前缀（fd2bef1）/ 序言+槽位规约（751d6be、101561c）
- arith/fib/float/string（dea0a70、2065595、a491739、ea377e4、05fd782）
- T1 容器族：list+dict（e6e2f5f）、trees（12a6758）
- T2 复杂程序：fannkuch（9c06ce8）、nbody（aa69e5b）、spectral（2abfbb9）、
  mandelbrot（f9cc50b）、wordcount（7f31ccd）、knucleotide（8428fc8）
- T2c 动态层：calc（c25628d）、jsonparse（cedef08）、jsonparse_json（f9fa865）
- T2d 终关：ir_interp（e9cffcc）、**silu_fe（18/18 全语料收官）**


## siluc1 非 ASCII 源 O(n²) 排查与修复（2026-11-09，v1.18.0 后）

**症状**：siluc1 直喂原始 Python 转换器源（11,877 行，含一个 U+00A7）
>6 分钟无输出；语料全部秒级。最小复现：字符串/注释里**任何一个多字节
UTF-8 字符** + 长文件 = 词法 O(n²)（合法程序 87s/3000 行；错误路径更糟）。

**根因**（三层，全部同族）：rawstr 下标在字符串含任意多字节字符后，
每次访问走 rawutf8_cp_offset 从字节 0 步进到第 i 个码点（O(i)/次；
ASCII 快路径是 len==cp 时直接用下标）。逐字符下标的三个热点：
1. silu_fe.si 词法器 peek（src[pos]）
2. flatten_si_tail.si 的 JsonR（IR JSON 逐 token 切片/读字符）
3. unescape/parse_fstring 的 `out = out + ch` 逐字符拼接（O(len²)，
   与多字节无关，巨型 docstring 单独触发 ~30s）

语料 100% ASCII + 解释器语义正确 + 双平面 .ll 字节一致（同错同对）
→ 三重掩护，门禁全盲。

**修复**（行为保持纯性能重构，cps 物化一次 + append/join 线性构建）：
- silu_fe.si：cps 以 `list[int]` 参数贯穿 Lexer 方法（peek/text/
  next_token/advance 签名加 cps）；token 文本 = append+`"".join`；
  unescape/parse_fstring 同型。类字段不动（避免容器字段新形状）。
- flatten_si_tail.si：JsonR 同型改造（jr_* 方法带 cps 参数）。
- Oracle 新 arm ×5（见 silu-conv.rs）：eval_expr 局部 b.to_str()；
  方法调用的 list:E 参数打包（原先掉进 float 兜底）；buf 局部重赋值
  `lit = strbuf()`（silent 槽记账：前置语句槽 ×1+后置丢弃槽 ×1）；
  空列表重赋值 `lit = []`（rawlist_new(8)+store+后置丢弃 silent）；
  print 的 str 拷贝收窄（调用结果直接打印不 copy，p1 探针）。
- tools/pycompat.py：补 strbuf 内建（dual-valid 执行器 shim）。
- tests/test_utf8_lexer_perf.py：性能回归 ×2 + 多字节内容寻址断言。

**验证**：>6min→0.25s（原始 typed_codegen.py）；m8 90KB docstring
32s→0.45s；m11 87s→0.27s（ASCII 同速）；ll 19/19、ir 20/20、
pytest 全绿（含 M5 ir2c 工具链——list+join 方案同时被 ir2c 原生支持，
strbuf 方案曾使其段错误）。

**遗留（未修，已知）**：
1. 运行时 cp-offset 无缓存——任何 Silu 程序对非 ASCII str 的逐字符
   下标循环仍是 O(n²)（语言级性能悬崖，非自举链独有；修复 = 改钉字节
   的运行时形状，需双实现同 commit + 重钉前缀）。
2. 动态层 str 语义按字节不按码点：pyobj_len_raw 读 rawstr field-0
   低 32 位（字节长），pyobj_str_char_at 按字节索引/定界——与解释器
   及 typed 层（码点语义）分歧；ASCII 语料掩护同上。修复同样动前缀。
3. Oracle 已知缺口（bail，语料未钉）：容器类型类字段（list[int] 字段
   + ctor 实参）、模块级 `l: L = L(0)` 注解实例赋值、非空列表字面量
   `cps: list[int] = [65,66]`、链式 `L().f()` 调用。
4. 错误路径分歧：Python 平面前端接受 `;` 分隔多语句（经 CPython ast），
   自举前端拒绝——错误路径不在门禁钉住范围。


## 1.18.1 重钉：cp-offset 侧缓存 + 动态层码点语义（2026-11-09）

**变更**（输出性变更，Python 转换器 + Oracle 前缀同批重钉，ll 19/19）：

1. **rawstr_cp_off_at 侧表缓存**（typed_codegen._emit_rawstr_core）：
   1024 槽开寻址提示表 `@cpoff_tab`（{struct_ptr, len, cp, offs*}），
   键=rawstr 结构指针，校验=(len,cp)；append 改 len/cp 自动失效；
   **rawstr_free real_free 路径 cpoff_purge**（malloc 复用同址同 len 同
   cp 不同布局的陷阱由清除钩子封死——trap 探针实证）；逐出=覆写（提示
   性缓存，miss 重建）。ASCII 走 len==cp 快路径不进表。调用点改接：
   at_eq_cstr/at_cmp_cstr/slice/slice_parts/_emit_char_view（6 处，
   rawutf8_cp_offset 本体保留为步行器）。
   实测：50K 码点循环 minutes → 0.31s（含 strbuf 构建）。
2. **动态层 str 码点语义**（pyobj_runtime）：pyobj_len_raw str 分支
   改 pyobj_utf8_cp_count（原读 pystr{i32 字节长}）；pyobj_str_char_at
   改码点定界 + pyobj_utf8_cp_offset 步行 + 变宽 UTF-8 序列拷贝；
   pyobj_str_slice 改码点 clamp/步进 + 变宽拷贝。CPython 对齐实证：
   len(chr(167))=1、ord(s[0])=167（原 2/128）、步进切片全对。
   早期创建器自包含步行器 pyobj_utf8_cp_count/offset（基类 __init__
   早于 rawstr 家族；@staticmethod 在 Silu 类模型无效会挤占参数位——
   用普通方法）。_seq_len_inline 为 _emit_seq_len 的自包含孪生。
3. **前缀重钉**：const_prefix 368,892→378,133B（含尾随空行——oracle
   直接拼接用户部，空行属前缀）；tagged 8,882B（14 define + 1 常量，
   **不含**首尾空行——oracle main 在 tagged 后补 '\n'）。提取流程：
   fib/dict/jsonparse 三对公共前缀取 min，剥回 `}\n`；tagged 从
   jsonparse_json 按 tagged 名字集（含点号！str.TypeError…）结构化
   前进到首个用户 define。
4. **分号分歧封口**（错误路径，无输出变化）：Python 平面
   importer.expand_imports_tree 入口 tokenize 扫描拒绝 `;` 语句分隔
   （字符串/注释免疫）；自举/Rust 前端本就拒绝。tests/test_semicolon_rejected.py。

### Oracle 未钉形状清单（2026-11-18 重普查更新；原始 2026-11-09 实证 g1-g12）

探针法：`siluc1 < gN.si`（Python 平面，恒 rc=0）vs `silu-conv gN.si`，
比 rc 与（rc=0 时）规范化后字节。**本轮已钉**：表达式内 `b.to_str()`
（g12 ✓）；`print(str 返回的方法调用)`（g11 ✓，Inst 重定型直打臂）。
**仍未钉**（语料零出现，bail 或字节分歧即预期行为）：

| # | 形状 | 证据 | 根因 |
|---|---|---|---|
| 1 | 容器类型类字段 `cps: list[int]` + ctor 列表实参 | g1 rc=0 但 41 行分歧 | 字段注册丢元素类型（"list"）→ ctor 实参走动态装箱 |
| 2 | 模块级注解实例赋值 `l: L = L(0)` | g2 bail "ann_assign type" | 模块级 ann_assign 分发落入 int 全局臂 |
| 3 | 非空列表字面量声明 `xs: list[int] = [1,2]` | g3 bail "local list literal elem" | ann_assign list 臂只认空 `[]`；连锁封死 g5 pop/g8 in/g10 clear（测试声明用字面量） |
| 4 | 链式构造调用 `L(7).f()` | g4 bail "method base in" | 方法分派要求 base 是 name |
| 5 | `del d[k]` | g6 bail "delete" | delete 语句无 arm |
| 6 | `d.setdefault(k,v)` | g7 bail "method base type" | dict 方法族未注册 |
| 7 | dict[int,*] 存储路径 | g9 rc=0 但 25 行分歧 | 待逐形状细分（get/set 字面量已钉，store 组合有分歧） |
| 8 | l.pop/l.clear/x in list/d.pop/d.clear/to_pylist/to_pydict | 运行时 47 函数仅 16 被引用普查 | 由 3/6 连锁；补齐需配套语料文件 |

### 2026-11-18 重普查（g-探针复跑，双平面 rc + 字节）

**语言面（Python 平面 + native 产品链）已大幅前进**：g3 族（非空列表
字面量 int/str、append、len、下标）在 Python 平面早已支持；本轮把
Oracle 面补齐——**`x in list` membership（rawlist_contains_bits /
rawlist_str_contains，in/not-in、const/var/loop-var 实参）、模块级
list[str] 字面量、list:str 调用实参（装箱 + pylist_to_rawlist_str）**
全部字节对齐；**连带修复全局容器名 eval 的错误类型读**（eval_expr 与
eval_mod 的 name 臂原把 LST_SLOTS/DCT_SLOTS 全局落到 i64 兜底 load，
现按 i8* 槽读 + Typed::Inst，与 py 的 `load i8*, i8** @"name"` 一致）。
新语料钉板 benchmarks/list_ops.si（ll 24/24、ir 25/25、CPython 对拍
1/2/1/2/4/4/7 一致）。**g5 pop/clear 已关闭（2026-11-19，STATUS §3.25）**：pop（int/str）、
clear、丢弃式 rawstr 语句值释放（py 的 _convert_statement_scoped 对应
物）、装箱 join（str_join_boxed 两段式求值镜像）、全局 str 尾序
（declare 在 eval 后）全部字节对齐。**g5 关闭后 ir2c 第三平面同轮补齐（2026-11-19）**：C 后端 pop/clear 臂
+ list_pop/list_pop_str/list_clear 助手（弹出槽清零 + 空 pop panic），
pop_clear 经 C 平面对拍 CPython 一致。**g6/g7 关闭（2026-11-19，STATUS §3.26）**：dict pop（del/pop_or）/
clear/setdefault × str/int key 域 + str-key store 的 tag 验证
（emit_pyobj_key_view 共享机器：tag==2 检查 + panic + 借用 str_view）
全部字节对齐。**g9 作废**（dict[int,*] store 重普查时即字节一致）。
**ir2c 第三平面同轮补齐（2026-11-19）**：C 后端 dict 方法族（pop/
setdefault/clear × dict/dicti）+ 助手；dicti 探针必须与 dicti_set 的
ihash 同哈希（真哈希非恒等——探针错位 = 合法 key KeyError）。dict_ops
经 C 平面对拍 CPython 一致。**g7 关闭（2026-11-20，STATUS §3.27）**：局部 dict 全族（方法臂槽域
经 dct_slot、alloca 收集序对齐、1 参装箱 get 的 has/phi 机器首次入
rs + 模块/局部 int ann_assign 的 Pyo unbox 边界）字节对齐。
**g-list 终态：g1-g12 全部关闭或作废**；唯余 dss 1 参 get（响亮
bail：create_int 硬编码 int 值域）。dict 家族四平面完整。

**str 方法族轮收口（2026-11-21，ll 29/29）**：边界空行规则定版（py 的
.ll = 每个 inter-function 边界恰好一个空行：CONST→TAGGED、TAGGED→首
用户 fn、fn→main；fn→fn 无空行）+ 局部 dict 槽域全对齐（len/get/方法
臂的 dct_slot）+ index 语义修复（list_index 分派对 str 接收者静默 -1）。
**str 方法族轮（2026-11-20，WIP）**：strip/split/replace/lower/upper/
find/index/谓词/print-bool 四平面落地（**index 语义修复**：原 list_index
分派对 str 接收者静默 -1，改 str_find + ValueError panic）；replace =
新 .ll 运行时 rawstr_replace（append 风格签名）+ const_prefix.ll 重生成。
四平面执行 = CPython ✓；ll parity 15/29——14 文件细粒度差异（dict 方法
臂形状 + 2 字节项）入档 STATUS §3.28，下一轮首项。join 的 str 参数接收者已被全局
容器名 eval 修复带好（字节一致）。g2（模块级注解实例赋值）与 g4（链式构造）未复验。
**隐式规约新增**：membership 实参的 str-coercion 临时**两平面一致
泄漏**（py 的 _typed_contains RAWLIST_S 臂不释放——P9 consume 站点
在 list-contains 处两侧同开同漏，字节对齐；如未来补齐须双平面同
commit）。

### 1.18.1 追记：m8 中间态回归（355s→0.52s）与孪生双循环

语义修正首版引入回归：m8（90KB 未闭合 docstring）从 0.41s 恶化到 355s。
采样/lldb 断点定位：热点 `pyobj_str_slice ← _rstrip/_escape_latin1 ←
module_text`（.ll 文本渲染器，llvmlite.si 孪生）。消融实证：纯 ASCII
巨型 docstring 也 55.8s（尺寸触发，与多字节无关），§ 再放 ~6×。

**根因（两层叠加）**：
1. 孪生 `_rstrip` 循环内 `s = s[:len(s)-1]`——每剥一个空白字符一次
   切片，而语义修正后的切片每次付全串 cp 计数（当时无缓存）；
2. 孪生 `_escape_latin1` 逐字节 `out += piece`（落在动态层的 O(n)/次
   拼接）。

**修复**：
- 双孪生（llvmlite_text.py + llvmlite.si 同改）：`_rstrip` 改索引回扫
  +单次切片；`_escape_latin1` 改 append+`"".join`。纯渲染层性能改动，
  输出字节不变。
- pystr 层新增 **pyoff_tab**（{data_ptr, bytes}→{cp, offs}，1024 槽）：
  pyobj_len_raw/char_at/str_slice 三入口改走 `pystr_cp_entry`（首访
  建表 O(n) 一次，后续 O(1)）。键=数据指针且 box 数据永不释放（动态
  层按设计泄漏、字面量共享不可变常量）故无需 purge——若将来引入 box
  释放必须补 purge。返回 {offs, cp} 按值（insertvalue 形状，照
  rawstr_slice_parts 先例；返回 alloca 指针=悬垂）。曾试 ASCII 预扫描
  快路径——那会让每次调用 O(n)，已删。

**终态**：m8 0.52s / m11 0.29s / 原始 .py 0.24s / trap 探针（free 复用
同 len 同 cp 不同布局）正确 / perf2（150K 码点访问）0.31s。ll 19/19、
conv/pyll 19/19、ir 20/20（const_prefix 382,443B 二次重钉）。
教训入档：**改运行时函数复杂度时，必须同时审视所有编译期消费者**
（本仓库里 .ll 渲染器就是运行时的"用户程序"）。

### utf8_probe 入语料 + 热点扫尾（2026-11-09 晚）

**① 非 ASCII 语料钉板**：selfhost/utf8_probe.si 入 CORPUS_IR（ir 21/21、
ll 20/20×2 平面）。探针首跑即抓获三个真 bug（全部当场修复）：
1. 非 ASCII 字面量全局的 `[N x i8]` 尺寸按码点数（flatten 表 len→utf8_len）
   与 Rust 的 15 处 chars().count()——全改字节长度（utf8_byte_len / .len()）；
2. **Oracle typed str 步进切片丢步进参数**（s[1:5:2] 发成 rawstr_slice(1,5)
   ——输出错误字节，违反"宁报 ERROR"；补镜像 Python 的装箱路径
   to_pystr→pyobj_str_slice(step)→to_rawstr，Null 步进=步 1）；
3. len(切片表达式) 无 arm（len(LIT[0:14])）——非 name 参数先试通用 str
   求值（位置在 name 守卫内，避免短路 dict/list 的 pyobj 臂——首版放臂首
   打破 8 个旧文件，已修正）。

**驱动器（siluc_main.c）两处健壮性**：rt.o↔rt.ll 配对校验（--no-lto 刷新
rt.ll 不再留下旧 rt.o 被复用）；rt.clang 身份戳（conda 环境 LLVM21 构建
的 LTO 位码 Apple ld17 读不了——失配自动重建）；run_quiet 失败时输出
子进程 stderr（"link failed"从此带原因）。

**② 孪生热点扫尾**：_escape_str/_escape_bytes 两处逐字节拼接改 append+join
（双孪生同步；_escape_latin1 已在此前修）。全源自举源扫描确认：逐字符
拼接 0 残留、循环内切片仅剩有界的 16 位定长格式化。

**执行级守护**：tests/test_utf8_runtime.py ×3（动态码点九项对 CPython、
free-reuse 陷阱、50K 码点线性走查）；探针本身无动态段——见下。

**g-清单更新**：新增 #10 未注解局部从 chr()/concat 初始化的推断分歧
（Python 保持 pyobj vs Oracle 推 str；`object` 注解局部 Oracle 空 bail）
——动态语义由执行级测试守护而非语料；#2/#3 类部分收窄（len-of-slice、
步进切片、字节定尺寸已钉）。
