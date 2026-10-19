# 自举语义差异根源（2026-10-19，v0.15.0 存档）

## 问题：为什么 Python 运行没问题，自举版本有问题？

全自举的转换器源码（`tools/flatten_codegen.py --si` 从
`typed_codegen.py` + `silu_ir_to_llvm.py` + `llvmlite_text.py` 生成）
在两个世界执行**同一份算法**：

- **Python 平面**：源码是合法 Python，跑在 CPython 上
- **自举平面**：源码是合法 Silu（dual-valid），经 Silu typed 后端
  编译成原生机器码，值活在 Silu 自己的运行时里

两平面语义本应一致（dual-valid 的契约），但只要有一个语义点
不同，转换器就在编译期自己踩中它——转换器是唯一一个"用全部
语言特性处理全部语言特性"的程序。已修复的 17 项缺陷不是 17 个
孤立 bug，而是**六个结构性根源**的表象。

## 六个根源

### 根源一：Python 对象模型 vs tag 盒运行时

Python 里每个值天然携带类型与身份；Silu 原生里值是
`{i32 tag, i8* data}` 盒，类信息被压扁：

| Python | Silu 原生 | 引发的缺陷 |
|---|---|---|
| `bytes` 与 `str` 是不同类 | 同为 tag 2 | `isinstance(v,(bytes,bytearray))` 对字符串为真 → 字符串常量走进字节转义路径，`_hex2(字符)` → floordiv 错路径返 null → 崩 |
| 元组与列表不同 | 元组就是列表（tag 4） | （未引发缺陷，但约束了判型逻辑） |
| 集合是集合 | set 字面量曾无编译路径 → null | `stmt[0] in <null>` 崩；现按列表盒承载 |
| 实例身份 = 对象身份 | 实例槽存裸指针，**每次跨界装箱新生 {cid, inst} 边车** | `is` 比较盒指针 → 单例（`Undefined`）与实例身份判定恒 False → `const_` 走错分支、`undef` 渲染成 `{}` |
| 方法按接收者真实类型分派 | 方法表按**名字**单一签名分派 | `.pop()`/`.copy()` 只登记了 dict 版本：`list.pop()` 进 `dict_pop`、`dict.copy()` 进 `list_copy`，结构错读 → SEGV |
| `list(x)` 构造拷贝 | 曾返回同一个盒 | `call` 的 `list(args)` 与调用方列表别名，后续变异污染已建指令的操作数 |

**判据**：凡是 Python 靠"值自己知道自己是什么"的代码
（isinstance / is / 方法分派 / 拷贝语义），在 tag 盒上都要显式
重做一遍。修复模式是**补 tag 分派运行时**（`pyobj_identity_eq`、
`pyobj_pop_dispatch`、`pyobj_copy_dispatch`、构造器真拷贝），
而不是改调用点。

### 根源二：任意精度整数 vs i64（含检查溢出）

Python 整数无界，且按"传入的原样"打印；Silu 原生是 i64，带
Rust 式溢出 panic：

| 场景 | Python 平面 | 自举平面 | 修复 |
|---|---|---|---|
| `-0.0` 字面量（`-` 作用在 const 上） | 前端/解释器任意精度取负，精确 | 后端曾用 `fsub(0,x)`：`0.0-0.0=+0.0` 丢符号 | `fmul(x,-1.0)`（IEEE 精确等价）+ 常量折叠 |
| `-9223372036854775808` | bigint 折叠无误 | 拆成一元减 → 运行期 `0-x` 检查路径在 INT64_MIN 必然溢出 panic | 常量操作数编译期折叠 |
| `0x8000000000000000`、FNV 基数 `0xCBF29CE484222325`（> i64::MAX） | 原样存、原样打印（正数） | i64 回绕成负数，**打印文本不同** → .ll 字节不一致 | 源码改写为带符号等价字面量（同位型） |
| `_double_bits` 的 `total * 2^52`（符号位置位时超 i64） | bigint 无感 | 溢出 panic | 单循环逐位十六进制，消除大乘法 |

**判据**：涉及"大于 i64 的字面量"或"对极值的取负"，两平面天然
分叉。首选策略是**把源码约束到公共子集**（带符号字面量、位级
等价写法），因为让 i64 模拟 bigint 不值得；折叠类修复则让原生
语义向 Python 对齐。

### 根源三：None 是一等值 vs 空指针

Python 里 `None` 参与一切运算并给出确定答案（`None == "x"` 是
False，属性访问抛 AttributeError）；Silu 原生里 None = null 盒，
而大量运行时**无空守卫**：

- `None == "str"`：rawstr 比较分支曾把 OBJ 侧强转 rawstr →
  `pystr_to_rawstr(null)` 崩。修：OBJ 侧仅字符串常量节点走融合，
  否则转 `pyobj_cmp`（null 路径按 Python 语义回答 ==/!=）。
- `pyobj_add`、`pyobj_contains`、`pystr_to_rawstr` 等入口直接读
  tag，null 一进即 SEGV（报错位置远离成因——"渲染期列表元素变
  null"追了一整段，实为上游 null 传播）。
- 放大器：`pyobj_*` 的一批**错误路径静默返回 null**（"Error case
  - return null for now"是既有设计），null 会旅行很远才崩。

**判据**：与 null 可能接触的每个运行时入口都需要 null 语义决策
（要么 Python 式回答，要么响亮 panic），不能默认解引用。剩余
7 个未过门禁的程序里，`jsonparse/knucleotide` 的
`pyobj_contains+284` 崩溃疑似仍是此家族。

### 根源四：函数是一等值 vs funcref 分发表

Python 里函数引用、别名、混合签名调用全部透明；Silu 原生里函数
值是 tag-7 盒索引 `silu_fn_table`，由 `pyobj_fn_callN` 按
**表索引**分发：

- **表曾恒为空**：资格检查 `_is_pyobj_ptr` 拿"指针类型"与
  "结构体类型"比较，永假 → 零臂 + 无表。这是"潜伏缺陷"的极端
  样本——所有既有门禁都测不出（见下节）。
- **表填充时机**：funcref 盒的索引在模块级语句转换期写入，臂在
  函数体生成期枚举；填充晚于前者时索引与臂错位。修：提前到
  `_create_function_declarations` 末尾，一次填满。
- **混合 ABI 不可见**：`dict_field = _dict_field` 别名指向
  `(PObj, PObj, i64)` 混合签名函数，不进"全 PObj"表 → 地址盒 →
  分发必 null。短期删别名改直接调用；**通用修复**（分发臂按目标
  参数 kind 逐参装换）列入待办。

**判据**：Python 中"把函数当值"的每种写法（别名、传参、返回）
在原生平面都需要分发机制显式支持；当前支持度 = 全 PObj 签名。

### 根源五：编译期解析 vs 运行期解析

- `llvmlite.Undefined` 这类**模块属性值读取**：Python 在模块
  对象上运行期查；Silu 前端把 `llvmlite.X` 解析为拼接模块的全局
  名（调用路径可用），但值路径若落到动态属性读（无类携带该
  "字段"）曾静默返 null——后经根源一的 identity 修复间接打通。
- 动态属性 `+=`（`j.pos += 1`）：静态实例接收者有实现，OBJ
  接收者曾被静默丢弃 → JSON 解析器无限递归栈溢出（8MB 栈耗尽
  的表现是 `pyobj_lt` 里 malloc 的栈保护页 SEGV）。
- 常量折叠边界：Python 前端对 `-常量` 的折叠是精确的；.si 路径
  曾把一元负号留给后端运行期（见根源二）。

**判据**：Python 的"解释器帮你查/帮你折"在原生平面要么编译期
做掉（折叠、名字解析），要么运行期给确定语义，不能"静默不做"。

### 根源六：静态标注的"可能值"宽于运行时实际值

typed 后端的不少快路径假设"OBJ 侧运行时一定是盒装字符串/容器"，
但 OBJ 的可能值域包含 null、实例、异类盒：

- `float(x)/int(x)` 曾把数值盒按字符串解析（`strtod` 吃 payload
  指针）→ `_convert_obj_number` 数值 tag 原地转换。
- boxed `startswith/endswith` 曾把字符缓冲当 rawstr 头传入 →
  构造借用视图。
- 实例元素列表字面量曾优化成 rawlist_i64（装箱后 tag-6 实例变
  整数 6）→ 未注解列表一律动态容器。
- 未注解 kind（`_const_kind` 对 str 返 None → null）与注解为
  `object` 的实例字段（读回丢 cid——**剩余家族**：spectral/
  calc/ir_interp 的 `no field 'element'`）。

**判据**：每个"假设值形态"的快路径都要么先验 tag，要么保证
可能值域闭合；instance-kind 的 cid 盖章目前只在已知类标注的
字段/边界生效，`object` 标注字段是已知的盖章缺口。

## 为什么所有既有门禁都测不出（盲区分析）

修复前的四层门禁（tests/test_llvmlite_text.py 27 项）：

1. 文本层 vs 真 llvmlite：**两个都是 Python 执行**——共享 CPython
   对象模型，tag 类差异不存在
2. flatten(Python) vs 原类：同上
3. flatten --si 过 check：语法层，不执行语义
4. **解释器跑 .si 转换器**：AST 解释器把 .si 当 Python 对象求值
   ——`isinstance`/`is`/`list()`/None 全是 CPython 语义！

即：**每一层门禁都活在 Python 对象模型里**；tag 盒、i64、null、
funcref 表这些原生世界的不变量，只有"原生执行"本身才能检验。
这就是"Python 没问题、自举有问题"的完整答案：不是 Python 版
typed_codegen.py 有 bug 被掩盖（少数确是，见下），而是**转换器
源码隐式依赖了 CPython 的十二条语义契约，而原生平面此前没有
一层门禁去核对这些契约**。

对用户早前问题的修正结论：三类成因里，"Python 对象模型掩盖的
设计缺陷"（根源一、四、六）确实占大头；"Silu-Python 语义差"
（根源二、三、五）次之；纯粹的"新代码 bug"（终结符后发指令、
二次装箱等，上一段已修）最少。三类边界在根源框架下现在可以
机械判定：**凡是"Python 下不可达、原生下可达"的路径就是语义
差；凡是"两平面都该工作但原生写错"的是新 bug；凡是"Python 靠
自身对象模型天然正确"的是被掩盖的设计缺陷。**

## 统一原则：在静态类型 Python 层面求同

目标状态：dual-valid 源码在 CPython 与 Silu 原生下**语义一致**
（同一输入、同一输出、同一报错）。落到工程决策：

1. **优先让原生语义向 Python 对齐**（运行时补全 tag 分派 / null
   语义 / 拷贝语义）——这是语言能力建设，修一处、全局受益。
   本段 17 项中 12 项走此路。
2. **源码约束到公共子集**仅当 Python 行为依赖 bigint 或真实类型
   信息、原生无法忠实再现时（FNV/INT64_MIN 字面量、dict_field
   别名、const_b 的 Latin-1 链）。这些点同时是**语言覆盖缺口
   清单**：混合 ABI funcref、超大整数字面量、真 bytes 类型。
3. **静默 null 一律改为响亮 panic**（"报来源优于报现状"）——
   `_emit_dyn_attr_read` 的 no-match panic 已证明价值
   （spectral/calc/ir_interp 现在是干净报错而非远端 SEGV）。
4. **新增门禁必须跨对象模型**：`test_si_converter_native_parity`
   （原生执行 vs Python 执行的 .ll 字节对拍）是第一层真正跨
   模型的门禁，当前 9/16；全部通过后固化进 pytest，堵上盲区。

## 剩余已知差异（compact 后从这里继续）

| 程序 | 症状 | 归因（推测→待证） |
|---|---|---|
| spectral / calc / ir_interp | `AttributeError: no field 'element'`（flat:988，gep 的 `.type.element` 链） | 根源六：`object` 注解字段读回丢实例 cid（盖章缺口） |
| jsonparse / knucleotide | `pyobj_contains+284` 崩 | 根源三或六：列表扫描内元素比较吃 null/异类 |
| wordcount | 输出 247 行差异（`str_view` alloca 摆放、块序） | 待查：块创建顺序或 alloca 锚点分叉 |
| nbody | rc=0 但 stdout 为空 | 待查：输出路径/print 缓冲差异 |
| 全部（O2） | O0 字节一致、O2 崩 | 优化暴露的 UB（生成 IR 里某处约定）或 clang 误编译；ASan(O1) 无堆损坏报告 |

以及两个工程待办：混合 ABI funcref 分发（根源四的通用修复）、
`pyobj_*` 错误路径从静默 null 全面改为 panic（根源三的系统性
收尾）。
