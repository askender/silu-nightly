# Rust 参照实现：进展与 TODO（2026-11-01）

> 钉住版本：silu 1.17.0（P6 重钉；原神谕钉 1.16.2 / 87df40f，
> 校准报告记录的是原钉）。本文是唯一的状态锚点——
> compact 后从这里继续。规约细节在 `reference/README.md`。

## P6 落地（2026-11-07，1.17.0）：字符串全局内容寻址命名

## strbuf 落地进行时（2026-11-08，Python 侧已落地，Rust Oracle 同步待续）

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
挂点：FN_SBUF 注册表、conv_ann_assign "strbuf" 分支、conv_assign
buf 拦截、eval_mod push/to_str/strbuf() arm（内联 attribute-call
模式）、len 分派、参数/返回注解归一化。harness 的 ll corpus 暂排
strbuf_probe（diff_harness.py 内注释；语料本体在 selfhost/——benchmarks/
是 CPython-parity 域，strbuf 是 silu 特有），Oracle 同步后移回并全绿。

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
