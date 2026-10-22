# 自举完成度判定与收官计划（2026-10-22，compact 入口）

> 本文回答"编译器自举是否彻底完成"，并给出接下来最值得做的
> 事。前置状态：16/16 原生门禁（-O0 与 -O2 字节一致）、全量
> pytest 绿、v0.18.0（a009116）。历史脉络见
> `progress_2026_10_16.md`、`selfhost_semantic_divergence.md`。

## 一、判定：**转换器级自举已完成；全管线自举还差两件事**

### 已完成（证据充分的）
1. **转换器级自举闭环**：`silu build selfhost/typed_codegen_flat.si`
   （clang -O2，真实 build 路径）产出的原生转换器，对全部 16 个
   基准+selfhost 程序输出与 Python 转换器**逐字节一致**的 .ll
   （tests/test_si_converter_native_parity.py，16 项）。
2. **语义对齐**：funcref 全形态（动态/混合 ABI/静态 thunk）、
   列表词法序、数值跨 tag 相等、真 set、i64 域字面量检查、运行时
   错误响亮 panic——六根源框架里能在运行时层修的都已修。
3. **工程**：全量测试 2m25s（xdist -n8）、原生门禁构建缓存、
   typed_helpers 拆分第一步（flatten --si 输出字节不变）。

### 未完成（本会话新发现 + 既有边界）

**A. 不动点自举（self-application）——"彻底"的真正判据。**
原生转换器转换**它自己的源码**（flat.ir.json），必须逐字节复现
它自己被构建时用的那份 .ll（类比 GCC stage1→stage2 比对）。
此前所有门禁都在转换**别的**程序，自应用是最后盲区。本会话
把它从"从未跑过"推到"第 5 个阻塞点"：

| # | 阻塞点 | 状态 |
|---|--------|------|
| 1 | `jr_number`（JSON 解析）i64 累加溢出：`9223372036854775808`（INT64_MIN 的正量级）直接 panic | ✅ 修：负数路径负向累加（MIN 可表示），越界响亮 ValueError |
| 2 | IR 生成器不折叠 `-<数值字面量>`：源里的 `-9223372036854775808` 序列化成 `["-",["const",+9223...]]`，正值超域 | ✅ 修：ast_processor 的 visit_UnaryOp **仅折叠** `-9223372036854775808` 这一个病态字面量（全量折叠会破坏 IR 形状契约——test_visit_unaryop 与 silu_fe 奇偶校验依赖 `["-",operand]` 形状，首版全折叠挂了 4 个测试后收窄） |
| 3 | **list × int 重复**无运行时：转换器自身的 `[pyobj_ptr] * arity`（_fn_call_dispatch）落 pyobj_mul 错误路径 | ✅ 修：新 `list_repeat` 运行时（自包含建盒，不依赖 list 运行时创建顺序）+ pyobj_mul 的 list 臂；首版 gep 在 i8* 上按元素数步进的 bug 已修（字节×8） |
| 4 | `"pyobj_fn_call%d" % arity`：% 字符串格式化不在动态平面 | ✅ 修：改 `"pyobj_fn_call" + str(arity)`（全程唯一一处 %） |
| 5 | **Block 盒（cid 8）的 `.function` 动态属性分发失败**（no field 'function'，自转换中途） | ❌ 未解——见下面的诊断现场 |

**#5 诊断现场（下一轮直接从这里继续）**：
- 症状：`AttributeError: no field 'function' (line 832)`
  （llvmlite.si:832 = `position_at_start` 里 `block.function`）。
- 已确证：接收盒 cid=8，且原生转换器自己的注册表里 **cid 8
  就是 Block**（Value1 Type2 Scope3 TypeInfo4 _Undefined5
  Constant6 Argument7 **Block8** Instr9 ... JsonR18，两平面一致）。
  Block 布局含 `function: object` 字段——cid 相同、字段存在，
  分发却落到 ga_none。矛盾未解。
- 已排除：推断签名分歧（两侧 _inferred_sigs 逐项一致）、类布局
  分歧（逐字段一致）、堆越界（16 程序门禁 + 此前 ASan 经验，
  但注意 ASan 绿不能排除合法地址错值）。
- 嫌疑方向（按优先级）：
  1. ga 分发臂的**编译期常量**与运行时盒 cid 的对照在某一处
     断裂——例如 `_emit_dyn_attr_read` 发射时 `self._class_ids`
     还没填到 Block（注册顺序 vs 发射顺序的时序窗口），嵌入的
     icmp 常量是旧值/错位值；对照 Python 平面为何不崩（Python
     平面同一代码路径走 CPython dict，天然正确——根源一）。
  2. `_dyn_member_classes("function")` 在原生实例里返回的臂序与
     Python 侧不同（sorted() 的输入依赖 _class_layouts 填充时点）。
  3. 该 ga 读的接收者实际不是 Block：cid 读出的 8 来自边车残值
     （盒复用/别名路径），需要打 tag（确认 tag==6）+ 边车两槽
     （cid+inst 指针）双打。
- 快速复挂诊断三件套（都在本会话用过，源码级 TEMP-DIAG，用完
  即删）：
  1. `_register_class` 里打印 `CID n name`（类注册序）；
  2. `_emit_dyn_attr_read` 的 ga_none 前打印 cid；
  3. silu_ir_to_llvm 的 exit_func 包 backtrace 包装器
     （`backtrace`+`backtrace_symbols_fd`，非零退出才打；注意
     缓冲用 malloc+bitcast，twin 的 alloca 不吃裸 int size）。
- **修完后固化**：`tests/test_selfhost_fixed_point.py`——
  flatten → ir → llvm → clang -O2 → 用产出的 bin 转换同一份
  ir.json → cmp 自身的 .ll。这是终极门禁（"转换器能再造自己"），
  每个阻塞点修完都值得重跑一次直到绿。

**B. 前端自举（全管线）**：`silu ir`（Python 的 IR 生成器）仍在
管线里；`tools/flatten_codegen.py` 是 Python（引导期工具，可
接受）。完整"源码→二进制无 Python"需要原生前端
（selfhost/silu_fe.si 已有 M4 覆盖，但主管线未接）。**建议**：
不动点通过后再评估；那之前它只是锦上添花。

## 二、接下来最值得做的（按序）

1. **不动点收口（#5 起步）**——价值最高：它是"彻底自举"的
   最后一块，且每个阻塞点都是真实语义缺陷（本会话 4 个修复里
   3 个是通用 Python 语义缺口：list*int、%-format 无、大字面量
   序列化）。方法论不变：探针先行 → 六根源归因 → 原生对齐优先
   → 门禁 → 提交。注意自转换是终极模糊测试——#5 之后可能还有
   #6、#7，逐个消灭直到 cmp 通过。
2. **固化 test_selfhost_fixed_point.py**（随 1 一起）。
3. **门禁提速余项**（可选）：ir2c build 测试合并 clang 调用。
4. **typed_codegen mixin 拆分**（需 flatten 支持 N 类合并；
   第一步 typed_helpers 已示范"拆分前后 flatten 输出字节一致"
   的验收法）。
5. **真 bytes 类型**（按需；做时覆盖 repr/索引/迭代/与 str 不等/
   len=字节数——当前两平面在 bytes 上全面分歧，探针已存
   /tmp/t_bytes2.si）。

## 三、本会话提交物（若 compact 后核对）

- 三项真修复（jr_number 溢出 / IR -字面量折叠 / list_repeat +
  %-format 改写）+ 门禁 16/16 重跑绿 —— 待提交（见工作树）。
- 陷阱新增：**Silu 无默认参数**——给 flatten 后代码加参数必须
  显式传全（list_int_apply 的教训：Python 默认值在 .si 里静默
  丢失，运行时才炸）；自包含运行时函数不要依赖后创建的属性。
