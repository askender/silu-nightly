# Rust 参照实现：进展与 TODO（2026-11-01）

> 钉住版本：silu 1.16.2 / commit 87df40f。本文是唯一的状态锚点——
> compact 后从这里继续。规约细节在 `reference/README.md`。

## 总体架构

```
silu-fe  (Rust 前端)      : .si → IR JSON     ✅ 19/19 与 silu_fe 逐字节一致
silu-conv (Rust 转换器)   : .si → 完整 .ll     ✅ 13/18 语料逐字节一致
diff_harness.py           : 平面对拍基架       ✅ 自校验通过
const_prefix.ll           : 365,264B 常量前缀   ✅ 跨语料恒定
```

- 位置：`reference/rust/`（cargo，零外部依赖，`src/main.rs` = silu-fe，
  `src/bin/silu-conv.rs` = 转换器，~2,300 行）
- 运行：`cd reference/rust && cargo build`；对拍 `python reference/diff_harness.py ll conv rustconv`
- silu-conv 通过子进程调 silu-fe 取 IR（前端已独立验证）
- **非目标**：不做产品编译器、不进自举链、不做同步镜像（版本快照神谕）

## 当前状态：转换器 15/18

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
| jsonparse_json.si | 伴生变体 | 未实现 |
| ir_interp / silu_fe | import 系 + 全特性 | 未实现 |

里程碑提交：`c25628d` calc.si（事故重放+回归修复）、`355cb81` jsonparse 前置、
`cedef08` **jsonparse.si 逐字节对齐（15/18）**。
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
   **class_def：inst 域类耗 1 槽、pyobj 动态类不耗**（jsonparse 的 JInt 等
   被 match_class 消费→DYN_CLASSES→不耗）；**match_class 每个捕获耗 1 槽**
   （建 gvar）。这条修正了迭代 1“捕获不耗槽”的误判
9. len(names[i]) → rawlist_str_get（非 copy_into）；str 捕获先 rawstr_copy

**下一目标**：jsonparse_json.si（当前 ERROR: list elem type）。
jsonparse.si 输出 442,328 字节 = 参考，逐字节一致。

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

### T2c 动态实例层（calc → jsonparse×2）——下一个大台阶
- calc.si 参考：方法 → `Class__method(i8* self)` 独立函数；构造
  `Token(...)`；实例字段读写；`__silu_user_main` 包装（main 调它）；
  pyobj_input/truthy/rawstr_eq_cstr/isdigit/to_cstr 等运行时族
- 读参考尾：`./siluc1 < selfhost/calc.si` 截 const_prefix 之后（51KB/1323行）
- enum_def（Tok）/ class_def / match 语句形状待解剖

### T2d import 系（ir_interp → silu_fe 终关）
- ir_interp: from_import；silu_fe: import + 2,183 行全特性

### T3 校准报告（R3）
- 分组件行数对照表（前端 2509 Rust vs 2183 Silu +15%；转换器对照待量）
- 省/费热点归因；发现 bug 分诊；语言设计建议

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
