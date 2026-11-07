# 校准报告：Rust 参照实现 vs Python 参考实现（R3，T3 收官）

> 钉住版本：silu 1.16.2 / commit 87df40f。
> 结论先行：**两个平面全部逐字节一致**——前端 IR 19/19、完整 .ll 18/18。
> 第二实现可以复现参考输出的每一个字节；本文记录规模对照、发现的
> 参考实现特性（含浪费点）、以及给语言设计的建议。

## 1. 校准结果

| 平面 | 语料 | 结果 |
|---|---|---|
| 前端 IR（`silu_fe` vs `rustfe`） | 19 个 .si（含 1.84MB 的 typed_codegen_flat） | **19/19 逐字节一致** |
| 完整 .ll（`siluc1` vs `silu-conv`） | 18 个 .si | **18/18 逐字节一致** |

最大单文件：silu_fe.si 输出 1,492,988B；ir_interp.si 输出 487,006B；
typed_codegen_flat 的 IR JSON 1,839,884B。对拍命令：
`python reference/diff_harness.py ir fe rustfe` 与
`python reference/diff_harness.py ll conv rustconv`。

## 2. 规模对照

| 组件 | Python 参考 | Rust 参照 | 比值 |
|---|---|---|---|
| 前端（.si → IR JSON） | silu_fe.si 2,183 行 | src/main.rs 2,509 行 | +15% |
| 转换器（IR → .ll） | typed_codegen_flat.si 11,977 行¹ | src/bin/silu-conv.rs 7,882 行 | −34% |
| 合计 | 14,160 行 | 10,391 行 | −27% |

¹ typed_codegen_flat.si 是参考转换器压平后的形态（类结构展开、
访问器内联），对它是公平的最小对照；原始带类结构的 Python 源更大。
Rust 转换器更短的主要原因：无 llvmlite 构建器样板（直接拼 .ll 文本）、
槽位模型统一为“每指令一槽、void 静默”后大量形状用同一条发射路径。

## 3. 发现的参考实现特性

差分逐字节对齐意味着两个实现连**浪费**都一致。以下按影响分诊。

### 3.1 浪费（体积/性能，不影响语义）

1. **字符串常量不去重**：同一 panic 消息每次 panic 点都新建全局。
   ir_interp 里 `ZeroDivisionError: division by zero` 连续占
   str_411/str_412 两槽；IndexError 同样双份（str_453/454）。所有
   语料的 .ll 尾部都能看到成对重复。代价：每个二进制几 KB～十几 KB
   的重复常量；若做去重，全部语料的输出都会缩小。
2. **rawlist 写回无条件发射长度比较**：`object` 形参收 rawlist 实参时，
   即使被调函数不改列表，也发 pre-call len + 调用后
   pylist_to_rawlist_str + len + icmp ne(new, old) + select + 回写。
   语义必需（列表可能被改），但无改动分析的短路径会白白多 5 条指令。
3. **`is True/False` 三重检查**：非空 + tag==3 + payload 相等共
   5 条指令；布尔装箱格可用专用运行时一次完成。参考固定形状
   `and(non_null, and(tag==3, value==want))`（右结合），第二实现
   极易写成左结合——本参照最初即在此偏离。
4. **split-form 双 store**：owned str 参数 prologue 是
   alloca + store null + store arg，arg store 可覆盖 null store；
   参考保留两条。

### 3.2 脆弱形状（第二实现最容易写错的点——校准的核心产出）

以下无一是“错”，但都没有文档化，只能靠逐字节差分钉住：

1. **槽位记账**：void 指令也消耗匿名寄存器号（llvmlite 对所有指令
   编号，void 不打印结果但占号）。由此衍生：新 RAWSTR 局部声明在
   rhs 转换与旧值 load 之间消耗一个 null-store silent；siter 字符
   迭代的 null store 在最终 bitcast **之前**；容器参数的 store 在
   拼接区但**仍耗槽**；`lit = ""` 这类未注解声明与 `x: str = ""`
   注解声明走不同路径、silent 位置不同。
2. **所有权边界**：rawstr 可变（rawstr_append 原地改），所以
   `three = two` 名称别名必须 rawstr_copy；实例 str 字段读 copy、
   写时 rhs copy + coerce copy + free old；静态自由函数同类型实参
   不 copy 而方法实参 copy。漏一处就是 use-after-free/别名损坏，
   多一处就是提前 free。
3. **全局槽号 = len(module.globals)**：字符串编号与函数声明顺序
   交织（main 包装占基础位、每函数+1、方法预声明、match_class 捕获
   建 gvar）。任何顺序偏差放大为全文件编号漂移——ir_interp 调试
   中一次错误多耗 silent 就是 400+ 行 diff。
4. **短路链的表示分叉**：i1 链走 sc_finish/sc_next 块族 +
   create_bool；pyobj 链直接保存原对象到 sc_result，object 返回
   函数连 unbox 都不做直接 ret。条件上下文里的动态 ==/!=（str 常量
   除外）也不 create_bool。三种形态按“操作数类型 + 所在函数返回
   类型”组合选择。
5. **迭代器五族**：range（loop_init/cond/body/end/incr）、
   rawlist riter（含 enumerate 的 __enum_ctr_N pyobj 计数器）、
   object pyobj_iter_keys、dict 键迭代、str siter（字节偏移 +
   UTF-8 宽度 + 单字符 malloc）。每族的块名、创建顺序、目标声明
   的 null store 位置各不相同。
6. **比较发射的分派树**：常量右操作数走 rawstr_eq_cstr/rawstr_at_*
   融合；两个运行时字符串走 rawstr_eq；char 视图走 view_ord/
   rawstr_char1；pyobj 走 pyobj_eq/lt/le/gt/ge；数字走 icmp/fcmp。
   融合路径（如 `s[k] op "c"` 不物化 char1）与非融合路径的槽号
   交错（rhs 常量链插在 insertvalue 对之间）是早期语料的难点。

### 3.3 参考实现的潜在 bug 风险

未发现改变程序语义的 bug（参考本身有 CI 门禁，符合预期）。两个
值得上游注意的脆弱点：

1. **可变 rawstr 的别名隐患靠 copy 规则兜底**：`three = two` 的
   copy 是正确的（后续 rawstr_append 原地改 two 不影响 three），
   但规则完全隐式——任何一条路径漏 copy 或多 copy 都是内存错误。
   差分中我们实际踩过：`digits` 循环内 `out = out + chr(...)` 若
   走 concat+free 而非原地 append，只是性能差；若 append 时漏掉
   “目标==左操作数”判断，别名对象会被原地改写。
2. **`icmp ne(new, old)` 操作数顺序**与 `and` 右结合：纯形状问题，
   但写反后差分立刻报错——这类“无语义影响的形状”恰恰是第二实现
   的主要失败面，也是本参照的价值所在。

## 4. 语言设计建议（给 silu 本体）

1. **统一字符串表示**。rawstr/pystr/pyobj 三态是转换器复杂度的
   最大来源（本参照 7,882 行里约三分之一在处理三态转换与所有权）。
   若语言层面固定一种表示（如不可变字符串 + 显式 StringBuf），
   转换器可以砍掉整个 copy/free 边界推导层。
2. **字符串常量去重**。参考不去重，每个 panic 点重复一份；建议
   在模块级做 interning，输出更小且编号更稳定。
3. **迭代器归一**。range/enumerate/rawlist/str/dict 五族循环形状
   各异，建议语言规定统一的 desugar 目标（例如全部归一到
   iter/next 协议或全部归一到索引循环），转换器与文档都受益。
4. **声明与赋值同形**。`x = ""` 与 `x: str = ""` 产生不同槽位
   形状（null store 有无、路径不同）纯属实现痕迹；若声明即赋值
   统一处理，可删掉一类特判。
5. **布尔装箱比较内建**。`is True` 展开成 5 条指令且形状脆弱，
   建议 `pyobj_is_bool(obj, want)` 一类运行时。
6. **全局命名与顺序解耦**。`str_{len(module.globals)}` 使输出对
   声明顺序极度敏感；按“定义序 + 类别前缀”命名可以让增量编译和
   第三方实现都更稳。

## 5. 方法论备忘

- **差分先行**：每个语料先 `siluc1 < X.si > ref.ll`，实现到 cmp
  为止；所有规约都有 diff hunk 背书，不靠读源码猜。
- **最小探针**：跨文件规则冲突时（如 null-store 是否存在）写
  /tmp 探针 .si，两平面各跑一次，10 行内定案。
- **归一化 diff**：匿名寄存器号漂移会淹没真实差异；`%".N"`
  归一化后的结构 diff（本报告期间从 27,114 行收敛到 0）是定位
  语义差异的主力。
- **槽号追踪器**：按 `__silu_line` 行号 + 函数边界配对两侧匿名
  寄存器号，第一次错位点直接指出少/多耗槽的语句。
- 全部 18 语料 × 2 平面随时可复跑（毫秒级），回归零成本。

## 6. 产出索引

- 实现：`reference/rust/src/main.rs`（前端 2,509 行）、
  `reference/rust/src/bin/silu-conv.rs`（转换器 7,882 行）
- 规约清单：`reference/PROGRESS.md`（隐式规约 38 项 + silu_fe 补遗）
- 形状蓝图：`reference/DYNAMIC_SHAPES.md`
- 运行时前缀：`reference/rust/const_prefix.ll`（365,264B）、
  `reference/rust/tagged_prefix.ll`（Json 域）
- 里程碑链：c25628d calc → cedef08 jsonparse → f9fa865
  jsonparse_json → e9cffcc ir_interp → f25fa26 silu_fe（收官）
