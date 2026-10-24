# 自举后路线图（v1.1.0 起，2026-10-23）

> compact 后单一入口。当前状态：**彻底自举已完成**（v1.0.0，
> 9bb26b6）：原生自产转换器转换自身 IR 输出与自己构建时的 .ll
> **逐字节一致**（tests/test_selfhost_fixed_point.py）；四个根源
> 家族的防御已落地（v1.1.0，ca2aba3：unknown-op panic、flatten
> 默认参守卫、funcref 表作用域化、15 项边界套件），全量 pytest
> 1112 绿。历史脉络：`progress_2026_10_16.md` 的 16/16 与不动点
> 各节、`selfhost_semantic_divergence.md`（六根源框架）。

## 一、剩余 TODO（按价值排序）

### P1：质量纵深（自举完成后的正确性余量）

1. **作用域规范 CI 审计**（根源 C 防复发，半天）
   - 脚本扫 typed_codegen.py：每个 `X = dict(self.X)` 作用域拷贝
     必须有配对 `self.X = old_X` restore；每个以名字为键的表
     （var_kinds/_var_class/_funcref_var/_list_elem_class）逐个
     核对。做成 pytest（源码静态检查，秒级）。
   - 顺带：`_STORAGE_ALIASING_STMT_OPS` 与实际处理节点集的对账
     ——unknown-op panic 落地后，这张表可以直接由 panic 覆盖
     审计生成。

2. **符号执行验证运行时不变量**（根源 D 的形式化方向，1-2 天 PoC）
   - repo 已有 symbolic 基础设施（tests/test_symbolic_executor_
     core.py、test_enhanced_symbolic.py）。目标不变量（历史 bug
     全在其中）：`list_insert/list_append 后 len <= cap`、
     `list_get 下标界检查对负数/clamp 成立`、
     `dict_find_probe 探测必终止（表有空槽）`。
   - 路线：对 pyobj 运行时函数的 .ll 做符号执行（或对 .si 源
     用现有 executor），断言不变量。拿到一个可跑的 PoC 再扩。

3. **门禁提速余项**（全量 ~2.3 分钟已可接受，可选）
   - 三个 ~20-85s 解释器门禁内部并行化（照 test_si_converter_
     interpreter_parity 的 ThreadPoolExecutor 模式）。

### P2：模块化重构（用户已点名，见下节专述）

4. **typed_codegen.py / silu_ir_to_llvm.py 渐进拆分**——
   不变量：**所有 .ll 字节不变**（含不动点）。

### P3：语言覆盖（按需）

5. **真 bytes 类型**：与 str 分离（独立 tag 或 latin1 标记贯穿
   运行时）。当前共享 tag 在全门禁下正确，无消费者驱动。
6. **真 set 的哈希实现**：当前 set 是去重列表盒，contains 是
   O(n) 扫描——对转换器自身（_module_vars 等小集合）够用，
   大集合性能场景再做。
7. **前端自举评估**（`silu ir` 仍为 Python）：silu_fe.si 已能
   编译原生且 IR 与 Python 前端逐字节一致（m4 门禁）——把它
   接入主管线是工程活，不动点已闭环，此项为锦上添花。

## 二、模块化专述（怎么拆才安全）

现状：typed_codegen.py 11,949 行 + silu_ir_to_llvm.py 6,149 行
+ typed_helpers.py 377 行；flatten 读两个源文件合并成单类 .si。

**已验证的方法**（typed_helpers.py 拆分，v0.18.0）：抽出叶子
模块 → flatten 在 derived 源里内联该文件 → **flatten --si 输出
与拆分前逐字节一致**作为验收。照妖镜就是不动点门禁本身。

推荐分四步，每步独立提交、独立验收（字节一致 + 全门禁）：

- **步骤 A（半天）**：`silu_ir_to_llvm.py` 的运行时创建方法群
  （_create_* 共 ~30 个方法、约 3,500 行）抽到
  `silu/pyobj_runtime.py`。flatten 已会内联第三文件
  （typed_helpers 机制复用）；PyImport 替换点在 si_main。
- **步骤 B（半天）**：typed_codegen.py 的动态平面方法群
  （_emit_dyn_* / _fn_call_dispatch / 方法表，~1,500 行）抽到
  `silu/typed_dynamic.py`。
- **步骤 C（1 天）**：表达式转换群（_typed_binop/_typed_compare/
  _typed_contains/_rawstr_*，~3,000 行）抽到
  `silu/typed_expr.py`。
- **步骤 D（可选，风险最高）**：单类真正的 mixin 化需要 flatten
  支持 N 类合并——先不做；A-C 的"方法分文件、单类不变"已能把
  单文件压到 ~4,000 行以下，阅读/导航收益已兑现大半。

每步的验收命令固定为：
`tools/flatten_codegen.py --si > /tmp/a.si` 与上一步输出 diff
为零 → 全量 pytest → 不动点门禁。

## 三、陷阱清单（累积，新增随时补）

- dual-valid 子集：无推导式（转换器源；程序源现已支持
  list_comp）、无默认参数（flatten 硬错误）、无 f-string 转换
  说明符（`{x!r}` 会炸 IR 生成）、无 try/finally、无闭包捕获
  （nested_hoist 拒绝）。
- flatten 的构建器元数补全按接收者白名单（NON_BUILDER_RECV）
  ——新代码用 `.add(` 等同名方法必须核白名单。
- `str(x.type)` 必须 `_type_text`（twin 的 str() 是 repr）。
- /tmp 探针前 `cp selfhost/llvmlite.si /tmp/llvmlite.si`；
  管道下 printf 全缓冲，诊断走 panic/exit（会 flush）或 ASan
  构建（干净退出会 flush）。
- 以名字为键的编译期状态必须随函数作用域 save/restore。

## 2026-10-23 晚推进记录（①②③全部落地）

- ① 作用域 CI 审计（e316330）：tests/test_scope_audit.py 四项
  AST 静态检查；双变异验证（删 restore / 删 rebound-drop 均被抓）。
- ② 模块化步骤 A（d962815，v1.2.0）：silu_ir_to_llvm.py 6,149 →
  1,519 行，4,674 行运行时发射方法群入 silu/pyobj_runtime.py
  （PyobjRuntimeMixin）。flatten 读第三源并在历史槽位拼接——
  **字节门禁自己抓了两个放置 bug 后才绿**（mixin 排全部基类之后
  → 类字段序漂移；多行 import 穿透行式收集器）。
- ③ 符号执行不变量（本提交）：tests/test_symbolic_invariants.py
  8 项——append/insert 的 len≤cap 全量证明（Z3 unsat）、容量
  单调、负下标 clamp、界内读 total / 界外读必 panic、insert
  三分支路径覆盖（SymbolicExecutor.function_analyses）。变异
  验证：历史 bug 形态（needs_grow = len < cap 迟一步增长）被
  Z3 当场反例击中（len0=cap0=0）。

## 编译提速：运行时 .o 缓存（2026-10-23 深夜）

可以更快——已实现。`SILU_RUNTIME_CACHE=1 silu build`（opt-in）：

- 原理：每个程序的 .ll 都内嵌同一个 ~350KB pyobj 运行时
  （178 个函数，__init__ 期创建、先于一切用户项——**前缀不变量**
  已验证并作为拆分守卫）。缓存路径把它编译成 ~/.cache/silu-
  runtime/<sha>.o（冷缓存一次性 0.66s），此后每次编译 clang 只见
  3-30KB 用户部分 + 一次链接。
- 用户 .ll 自动补齐外部声明（函数 declare / 全局 external，从
  运行时定义行推导类型；libc/intrinsics 的 header declares 随
  用户带走；internal 链接不能跨界 → 运行时对象提升默认可见性，
  仅符号表变化）。
- 实测（6 基准，warm）：**0.72s → 0.32s/程序（2.2×）**，总量
  4.20s → 1.90s；输出与直编**逐字节一致**（6/6），运行速度
  持平（2-4ms）。冷缓存首次 0.66s。
- 剩余成本剖析：Python 进程启动+FE ~0.15s（含解释器启动）、
  convert 0.05s、split 0.07s（内含运行时文本重生成）、
  clang 用户+链接 ~0.10s。下一步空间：split 复用磁盘缓存的
  运行时文本（省 0.05s）、FE 与 convert 常驻进程（省 0.1s+）。
- 默认关闭（字节门禁走直编路径不受影响）；门禁抽查 27+17 全绿。

### 后续提速空间（2026-10-24 四管线实测后排序，见 progress 文档）

- ~~**cli.py 胖 import 懒加载**~~ **已完成**：silu.cli 导入
  96ms→12ms（z3+loguru+ir_interpreter/ir_to_source 全部下沉到
  子命令函数；LLVM_AVAILABLE 改 find_spec 探测，llvmlite dylib
  不再进 ir/interpret 路径）；`silu ir` 0.138s→0.047s。性质由
  test_cli 的 sys.modules 断言 + 60ms 导入预算锁住。
- ~~前端自举收尾~~ **已完成（v1.6.0）**：aug-assign 形状 +
  as-别名 + flat 转换器源全构造解析（三引号/裸元组/集合/字节
  串/完整转义表/链式比较/链式赋值/元组下标/软 match/case/点
  路径与相对 import/LLONG_MIN 折叠/del 形状/提升镜像对齐）；
  语料 18/18 parity；管线级不动点落地（tools/selfhost_build +
  test_pipeline_fixed_point）。
- 常驻编译 daemon：再省进程启动 + import + 重复解析（估算
  0.19 → ~0.13s/程序，与 rustc 0.128s 打平）。
- **typed 后端待查怪癖**（v1.6.0 发现，均已绕开）：
  ①`list[str]` 类型化局部传入 object 参数按值装箱——append
  改副本、调用方不可见（应共享或编译期报错）；
  ②`t2 = toks[i+1]; t2.kind` 动态 getattr 崩溃而内联
  `toks[i+1].kind` 正常（同函数同型）。
- **ir2c 动态字符串缺口**（v1.6.1 发现）：ir2c 的动态槽是
  无类型 int64，pyobj 字符串无法乘坐（`nm + ".si"` 被推成整数
  加法）——ir2c 版前端能解析自包含源但走不了 import 展开路径。
  read_file 内建已补（fopen/fread 全量读）。要支持需给 ir2c
  引入字符串感知的动态表示（或 pyobj 桥），按需排期。
- rustc 直调无缓存（实证：三连编译恒定 + 磁盘零残留）；cargo
  的缓存是工件级（冷 0.274s/热 0.050s），与我们的 .o 缓存同类。

## RFC：编译器静态化（flatten 保留注解路线，v1.5.0 后评估）

**现状量化**（本节实测）：flatten 把全部注解剥掉（`a.annotation =
None`），自举转换器 391 函数、1,090 参数中静态可推参数仅 13 个
（1%）、静态 ABI 函数 1 个——**整个编译器跑在 pyobj 动态平面上**
（42 个 pyobj 运时函数的消费主力）。jsonparse 同理：6 函数中仅
1 个（digit_value(str)）可全注解——它的数据天然是异构 JSON 树。

**结论先行**：两者都不存在"简单加注解就能静态化"的空间。
- jsonparse：对象字段是运行时 JSON 决定的（tag/name/value 三
  种类型混住一个字段），注解无法表达；除非改写成 tagged-union
  显式分派（等于重写）。
- 转换器：IR 树节点是 ["op", ...] 异构表，属性按 tag 动态分发
  （_emit_dyn_attr_read）；550 参数全是对象流。静态化 = 把
  IR 数据模型改成 sum-type + 每节点类型一个类——是"给编译器
  换心脏"级重构（估 3-4 周），不是注解补丁。

**值得做的静态化分档**（按性价比）：
1. **热路径局部静态化**（可做，半天-数天/项）：不改数据模型，
   只把最热的标量局部循环变量/计数器加注解（推断已支持：
   未重绑 + 调用点一致 → 自动 raw ABI）。用 --dump-inferred
   找出"差一个注解就静态"的函数。
2. **print 特化已做**（v1.5.0）：静态程序 pyobj 引用清零。
3. **真 tagged-union 静态化**（RFC 主体，暂缓）：前置条件是
   语言层 sum-type/模式匹配完备 + 性能动机成立（当前转换器
   0.05s/程序，无压力）。若未来做，建议路径：
   a. 语言层先支持 `class Parser(Op): ...` 继承 + match 完备
   b. IR 节点改 final class 家族（每 op 一类）
   c. flatten 保注解（去 annotation=None 剥离，改成子集校验）
   d. _emit_dyn_attr_read 全部退化为直接字段读
   验收不变量不变：flatten --si 字节一致 + 不动点。
