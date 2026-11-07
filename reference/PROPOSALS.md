# silu 语言与实现改进提案（征求外部评估，未决定实施）

> **读者**：独立评估方（人或模型）。本文自包含：不假设你了解 silu 内部；
> 每条提案附现状证据（附可执行复现命令）、方案、改动面、风险与反论。
> §9 是给评估者的问题清单。**本文不是实施决定**——评估结论出来后才
> 决定做与不做、做哪几条。

## 评估结论（2026-11-07，ZCode/GLM 会话内独立评估）

**总裁决**：P2+P6 采纳（第一批）→ P5 采纳（第二批）→ P3b 采纳（第三批）→
**P4 缓议**（自原第一批降级）→ **P1 缓议、单独立项**（语言设计决策，非实现清理）。
若全部实施，目标版本 1.17.0。**实施仍待用户最终确认，本节只是评估方裁决。**

### 实施后改判（2026-11-07 晚，P3b → 缓议）

P6/P2/P5 已全部落地（1.17.0，提交 f6ba044 / 37667af / 22ad013，全部门禁
绿）。P3b 在实现侦察阶段发现**评估前提不成立**，改判缓议：

1. "前端把已有判据写进 IR（零新逻辑）"——实际上五族判定中四族
   （riter/object/dict/str）依赖 `iter_tv = _convert_node(iter_node)`
   的**转换器类型推断**（RAWDICT/RAWLIST/OBJ kinds 来自
   candidates/var_kinds/容器注册表系统），前端没有这套信息。完整
   标注 = 前端复制类型推断，与 P4 缓议同理（判定逻辑搬家 + 新增
   遗漏面）。
2. 最小形态标注（range/enumerate 可前端判）会迁移 enumerate 的
   `__enum_ctr_N` 计数状态（`_enum_ctr_seq` 是转换器跨循环计数器，
   N 出现在 .ll 文本里）——上移即破坏"`.ll` 逐字节不变"这一本提案
   的核心验收。
3. 边际收益已让位：P6/P2/P5 删除了最大的隐式规约面（全局槽号
   模型整章、常量重复、布尔 11 指令形状）；五族循环形状已被
   PROGRESS.md 完整文档化且双实现钉住。若未来前端获得类型推断
   （例如 P4 讨论重启时），P3b 应一并重评。

评估方法：不采信本文档自述，对每条提案的可执行证据做了独立复验
（复验命令与结果见各条"复核"行），另核查了两处文档未覆盖的风险面
（P5 的 bool 释放路径、自举链的同步成本），结论均对提案有利或可控。

| 提案 | 裁决 | 一句话理由 |
|---|---|---|
| P6 命名解耦 | **采纳，第一批** | 唯一能整章删除隐式规约（槽号模型）的提案；是 P2/P5 的前置放大器 |
| P2 常量 interning | **采纳，与 P6 同批** | 复验实锤 19/9 份重复；常量为纯数据全局，零运行时影响；单独做会被编号问题卡住，与 P6 合并则天然解决 |
| P5 布尔单例 | **采纳，第二批（P6 之后）** | 复验排除 double-free 风险；11 条 → 1 条且与 CPython 语义对齐；P6 先行则 +2 全局无编号平移 |
| P3b 迭代器标注 | **采纳，第三批**（→ 实施后改判**缓议**，见上节） | 把前端**已有的**判据写进 IR，零新判定逻辑；.ll 输出不变是最强的等价性验证；3a 否决 |
| P4 声明赋值同形 | **缓议** | 判定逻辑从前端**新写**（作用域分析），是搬家不是消除；global/闭包/解包是真实遗漏面；收益六条中最模糊 |
| P1 字符串统一 | **缓议，单独立项** | 方向正确（str 语言语义本就是值语义，现状是编译期模拟），但回归面六条中最大，且 1a/1b 是语言哲学抉择，不属于本轮实现清理 |

### 复验记录（评估方独立执行）

- P6 源头：`typed_codegen_flat.si` L3524 确为 `f'str_{len(self.module.globals)}'`。
- P2 量化：ir_interp 输出中 `OverflowError: integer overflow in add` 恰 **19 份**、
  `ZeroDivisionError: division by zero` **9 份**；常量形态
  `@"str_411" = constant [36 x i8] c"...\00"` 为纯数据全局——interning 是
  纯 .ll 文本层去重，零运行时语义影响。
- P5 形状：`json_emit` 的 `is True` 展开实测 **11 条**（`%".19"`–`%".29"`；
  本文正文计 12、CALIBRATION 计 5，以 11 为准），单例化后 1 条。
- P5 安全性（文档未覆盖的风险，已排除）：全语料**不存在 bool 盒释放路径**
  ——pyobj 域无任何 free 调用（jsonparse.si 源码零 free），Json 域
  `tagged_free` 只分派 str/list/dict（tag 4/5/6），bool（tag 3）直达
  drop_block 且不递归。单例化不引入 double-free。**实施约束**：未来任何
  递归释放函数必须对 tag=3 豁免单例，此约定应写入运行时文档。
- P3 族分布：silu_fe 输出中 iter_*(object 迭代) 63 个函数体、riter/siter/
  loop(range) 各 1，与本文件 §10 一致；ir_interp.si 确无 `"for"` 节点处理，
  P3b 的"ir_interp 不受影响"成立。
- 自举链（文档改动面矩阵未显式覆盖的同步成本，已确认可控）：
  `selfhost/typed_codegen_flat.si` 由 `tools/flatten_codegen.py --si` 从
  Python 手写源**自动生成**；`test_selfhost_fixed_point.py` 是自反性测试
  （自举二进制转换自身 IR ≡ 自身构建 .ll），不钉住具体名字。因此输出类
  提案的完整流程 = 手改 Python 实现 + 手改 Rust 参照 + **再 flatten +
  fixed-point 重跑**。建议把这一步补进 §1 共同流程。

### 对 §9 六问的回答

1. **P1**：默认维持现状。若做，**1b（显式 strbuf）** 优于 1a——refcount
   的每次赋值开销与循环引用问题违背"无隐藏成本"；1b 把成本显式化，与
   silu 哲学一致。但都不急：copy 规则已全部文档化且第二实现证明可写对。
   建议在 P2–P6 落地、输出更稳定后，以独立语言设计提案重启（届时重钉
   成本也更低）。
2. **P2+P6**：已确认无转换器之外的部件依赖 `str_N` 顺序命名——.ll 名字
   对 clang 无语义；fixed-point 是自反性测试（见复验记录）。命名选
   **内容转义名**而非 FNV1a 哈希：可读性是 .ll 的明确项目目标，转义规则
   （非 `[a-zA-Z0-9._]` 字节 → `_XX`）比哈希协议更不易在三个实现
   （Python/Rust/Silu 自举源）间出现位级分歧。**前缀 str_0..296 保留原名**：
   它们是运行时自引用的固定资产，`str.` 与 `str_` 在命名空间上天然区分。
3. **P3**：**3b**。"IR 应自述"是正确方向，且 3b 是零新逻辑（见裁决表）。
   3a 否决：`for ch in s` 的 UTF-8 宽度判断在 desugar 成 range 后必须在
   转换器重造一遍，等于换了个地方藏复杂度，还丢零拷贝。
4. **P4**：是——global 语句、闭包提升、元组解包首次绑定构成真实遗漏
   场景，这正是缓议主因。且要注意：P4 落地后差分门禁只保护两平面一致，
   **不保护前端判定正确**（两边同错门禁仍绿）；唯一强验证是".ll 与改前
   逐字节不变"，若不成立则无法区分预期微变与判定错误。缓议至前端改动
   经验积累后（如 P3b 落地）再评估。
5. **P5**：单例不改变任何当前可观察语义（复验见上）；`is` 在布尔上退化为
   指针比较是**更强**语义且与 CPython 一致，应当采纳。附带收益：
   `create_bool` 从 2 次 malloc 降为 0（返回单例指针）。
6. **总体**：六条中无"完全不值得做"的，但 **P4 最接近**（收益是搬家式
   的），已缓议；P1 不是不值得而是时机未到。若首要目标是自举正确性，
   P2 单独做的确不划算——这正是 P2 必须与 P6 绑定的理由，维持同批。

### 批次修正（相对 §8 的变化）

原建议第一批 P4+P5 的排序有一个依赖倒置：P5 在无 P6 时 +2 全局会平移
全部字符串编号，重钉成本反而最大；先做 P6+P2 能让后续每条提案的重钉
成本最小化。修正为：

```
第一批  P6 + P2（同 commit；命名 + 去重共享查找表）
第二批  P5（在 P6 之下 +2 全局无平移；运行时文档补 tag=3 豁免约定）
第三批  P3b（IR 加尾字段；.ll 应 byte-identical，是落地时的硬验收）
缓议    P4（待 P3b 经验；验收标准 = .ll 与改前逐字节不变）
单独立项 P1（语言设计讨论，1b 方向优先）
```

每批共同流程（在 §1 基础上补第 5 步）：双实现同 commit → 全量差分门禁
（IR 与 .ll 两平面）→ **再 flatten + fixed-point 重跑** → 重钉版本并更新
PROGRESS.md。

---

## 0. 背景

**silu** 是一种 Python 子集的静态编译语言，目标是可自举、生成可读的
LLVM IR、行为可预测。当前链路：

```
源码 .si
  → 前端 silu_fe（产出 IR JSON；参考实现 silu_fe.si，2,183 行 Silu）
  → 转换器 typed_codegen（IR → LLVM .ll；参考实现压平源 11,977 行）
  → 系统 clang 编译执行
```

字符串在参考运行时中**可变且手动管理**：rawstr 头为
`{i64 len, i64 cap, i8* data, i64 cp}`，`rawstr_append` 原地扩写；
装箱层是 pyobj `{i32 tag, i8* payload}`。内存无 GC，转换器在编译期
插入 `rawstr_free`/`free`（变量覆盖点、作用域出口、panic 路径）。

**验证基线**：存在第二实现（Rust，`reference/rust/`），与 Python 参考
在全部语料上**逐字节一致**（前端 IR 19/19，完整 .ll 18/18，见
`reference/CALIBRATION.md`）。因此本文引用的任何"参考输出现状"都是
两个独立实现共同背书的既定事实，不是单一实现的偶然行为。

复现门禁：

```bash
python reference/diff_harness.py ir fe rustfe    # 前端 IR 平面
python reference/diff_harness.py ll conv rustconv # 完整 .ll 平面
```

## 1. 共同流程约束（适用于所有提案）

1. **双实现同 commit 落地**：任何改变输出的提案必须同时修改 Python
   参考与 Rust 参照，使差分门禁保持全绿。Rust 参照是第二实现的
   逐字节 Oracle，改完仍是。
2. **版本重钉**：输出变化后更新钉住版本（当前 1.16.2 / 87df40f）与
   `reference/PROGRESS.md` 里程碑。
3. **ir_interp.si 是 IR 的消费者**：它是用 silu 写的树解释器，处理
   `assign/ann_assign/if/while/call/...` 节点。涉及 IR 节点形状的
   提案需检查它的兼容性（它按位置取字段，加尾字段不影响）。
4. **输出字节变化本身不是障碍**：Oracle 按版本重钉即可；但同一提案
   在两个实现中的产出必须一致。

---

## P1 统一字符串表示

### 现状与证据

运行时并存三种字符串形态，转换器全程追踪与转换：

| 形态 | 表示 | 可变性 |
|---|---|---|
| rawstr | `i8*` → `{len, cap, data, cp}` | **可变**（原地 append） |
| pystr | pyobj `{tag=2, payload}` → `{len, chars}` | 不可变 |
| char view | 栈上 `{ptr, seq}` 对 | 零拷贝视图 |

可变性迫使转换器实现一套隐式所有权规则（全部已由差分钉住）：

```python
three: str = two        # silu_fe.si Lexer__next_token, L220-221
```
```llvm
%".x" = load i8*, i8** %"two"
%".y" = call i8* @"rawstr_copy"(i8* %".x")   ; 别名必须拷贝
```
```python
lit = lit + ch          # silu_fe.si parse_fstring, L828
```
```llvm
call void @"rawstr_append"(i8* %lit, i8* %ch, i64 %n)  ; 原地改 lit
```

即：`x = y` 若不拷贝，之后 `y += ...` 会连带改掉 `x`；而
`x = x + t` 只在"目标 == 左操作数"时才原地 append。规则有限且已
全部文档化（Rust 参照 7,882 行中约三分之一在伺候三态转换与所有权
判断：`to_raw/to_pyobj/pystr_of/TEMP_STRS/SLICE_NO_COPY/PENDING_PAIR`）。

### 问题

1. **正确性风险**：所有权边界完全隐式。漏一处 copy = 别名损坏，
   多一处 = 提前 free。第二轮实现（本参照）在此类边界上的返工次数
   多于其他所有类别之和。
2. **复杂度**：三态转换是转换器复杂度的最大单一来源。
3. **性能偶得**：`x = x + t` 原地 append 是有意优化，但它使"字符串
   值"不再是值语义，语言语义（Python 子集）中 `str` 本应不可变。

### 提案

`str` 语义定为**不可变**（与 Python 一致）：赋值即指针传递，
`s + t` 永远新建。原地拼接的热循环改用显式 `strbuf` 类型
（`.push()`/`.append()` 方法）。内存管理二选一：

- **1a 引用计数**：rawstr 头加 refcount；赋值 = retain + store；
  覆盖/出作用域 = release；归零 free。转换器删除别名 copy 规则与
  append 特判，但保留作用域出口的 release 插入。
- **1b 显式 strbuf + arena**：`str` 不可变不回收（arena/程序期），
  `strbuf` 显式 `free`。最省运行时，但长程序内存增长。

### 改动面

| 部件 | 改动 |
|---|---|
| 运行时 | 1a：rawstr 头 +2 字段、retain/release、append 退役 |
| Python 转换器 | 删别名 copy、append 特判；`+=` 改 concat+rebind；strbuf 族新增 |
| Rust 参照 | 同步 |
| 前端 | 若引入 strbuf 类型：注解/推断 + 方法表 |
| ir_interp.si | 不受影响（不解释字符串内部） |
| 输出 | 全语料字节变化（重钉） |

### 风险与反论

- 手动管理哲学下引入 refcount 与 silu 的"无隐藏成本"取向有张力；
  1b 则把成本显式交给程序员。
- 原地 append 是 `unescape`/`json_quote` 这类热循环的性能特性；
  strbuf 方案保留它但增加语言表面积。
- **反论（支持现状）**：copy 规则虽隐式但有限且已全部文档化——
  第二实现已经证明可以写对。改语言是为修一个"已经修好"的问题。
- 迁移期风险：所有字符串相关形状重写，是六条提案中回归面最大的。

### 评估问题

1a 的 refcount 开销（每次赋值 +1/-1）在 silu 的目标场景（自举编译器、
基准程序）是否可接受？还是应选 1b，或干脆维持现状并接受文档化规则？

---

## P2 字符串常量 interning

### 现状与证据

每个常量使用点新建全局，且**同一比较物化多份**。量化（复现见 §10）：

| 语料输出 | 常量总数 | 唯一 | 冗余 | 常量字节 |
|---|---|---|---|---|
| ir_interp.si | 218 | 97 | 121 | 3,986 → 1,923（**51% 冗余**） |
| silu_fe.si | 1,137 | 263 | 874 | 11,445 → 3,318（**71% 冗余**） |

极端例子：`"OverflowError: integer overflow in add"` 在 ir_interp
输出中出现 **19 次**；`"IndexError: list index out of range"` 8 次。

```bash
./siluc1 < selfhost/ir_interp.si | grep 'ZeroDivisionError'   # 9 份
./siluc1 < benchmarks/jsonparse.si | grep 'c" \\00"'          # 同内容多份
```

### 问题

体积浪费（自举编译器自身 71% 常量字节冗余）；且全局名按创建顺序
编号，去重与 P6 联动才干净。

### 提案

模块级内容寻址去重：`_create_global_string` 查 `dict[内容] → gvar`，
命中复用。panic 消息、字面量、fused-compare cstr 全部走同一入口。

### 改动面

| 部件 | 改动 |
|---|---|
| Python 转换器 | `_create_global_string*` 加 interning 表（约 10 行） |
| Rust 参照 | `add_str` 同样 |
| 运行时 / 前端 | 无 |
| 输出 | 全语料字符串编号变化（重钉） |

### 风险与反论

- 与 P6 联动：现有命名 `str_{len(module.globals)}` 按创建顺序编号，
  去重后编号不再 append-only。单独做需要处理"复用时名字仍唯一"，
  与 P6 一起做（内容寻址）则天然解决。
- 绝对节省小（几 KB），主要收益是与 P6 合并后的命名稳定性。
- 反论：如果只在乎正确性不在乎体积，现状无任何错误。

---

## P3 迭代器归一

### 现状与证据

前端 IR 中五种迭代都是同一节点 `["for", target, iter, body, orelse]`，
**由转换器按迭代表达式的静态类型猜族**。五族的块名、创建顺序、
目标声明、槽位各不相同：

| 族 | 块名 | 状态 |
|---|---|---|
| `range(n)` | `loop_init/cond/body/end/incr` | `range_counter` |
| `enumerate(rawlist)` | `riter_*` | `riter_idx` + `__enum_ctr_N`（pyobj 计数器） |
| object 迭代 | `iter_*` | `iter_idx` + `pyobj_iter_keys`/`list_length`/`list_get` |
| dict 键迭代 | `dict_iter_*` | probe 循环 |
| `for ch in str` | `siter_*` | `siter_off/siter_seq` 字节偏移 + UTF-8 宽度 + 每字符 malloc |

第二实现为此写了 4 个独立函数；每族的目标声明规则、null store 位置
（riterr 有 / siter 在 bitcast 前）各不相同——全部靠差分钉住。

### 问题

"按类型猜族"意味着类型推断与循环发射耦合在转换器；第二实现必须
同时复刻类型推断和五种发射形状，且推断错族只会静默产出错误形状
（差分能抓到，但定位成本高）。

### 提案（两个方向）

- **3a 前端 desugar**：`for i, x in enumerate(xs)` →
  `for i in range(len(xs)): x = xs[i]`；转换器只剩 range 一族。
  代价：dict 迭代需先键列表化；`for ch in s` 丢零拷贝机会。
- **3b IR 显式标注（推荐）**：for 节点追加 `iter_kind` 字段
  （`range|riter|object|dict|str`），前端类型推断时写入；转换器按
  标注分发，删类型嗅探。加尾字段，ir_interp 按位置取值不受影响。

### 改动面

| 部件 | 3a | 3b |
|---|---|---|
| 前端 | desugar 逻辑（现 `_convert_for` 上移） | 写 iter_kind（现 `_convert_for` 的判据直接用） |
| 转换器 | 删 4 族发射 | 删类型嗅探，保留 5 族发射 |
| Rust 参照 | 同步 | 同步 |
| ir_interp.si | 不含 for，不受影响 | 同左 |
| 输出 | 全变（重钉） | 不变（纯标注，若转换器行为不变） |

### 风险与反论

- 3a 语义等价性需逐族证明（enumerate 的计数器语义、str 的 UTF-8
  语义在 range 下要显式处理字节 vs 码点）。
- 3b 的反论：IR 变大一点；且"猜"与"标"只是把决策换了地方，发射
  形状本身没减少。
- 反论（支持现状）：现状对语言用户零影响，纯属实现内部分工。

---

## P4 声明赋值同形

### 现状与证据

首次绑定与重绑定在 IR 中是不同节点、转换器里是两条路径：

```python
lit = ""        # → ["assign", "lit", ["const",""], None]（4 元素，注解 None）
lit: str = ""   # → ann_assign 节点（注解分支）
```

两条路径的槽位形状恰好一致（都有 null-store silent），但实现是
两份；第二实现第一轮只覆盖了一条，差分立刻报错。ir_interp.si 的
`exec_stmt` 把两者同等对待（按位置取 1/2 字段）。

**量化**：`"是否首次绑定"` 目前由转换器查自身符号表决定——Rust 参照
为此维护 `is_declared/FN_S/FN_I/FN_PY/...` 五套注册表交叉查询。

### 提案

前端做作用域分析，**首次绑定一律发 `ann_assign`**（注解字段可为
null）；`assign` 仅用于重绑定。IR 自述声明性，转换器的自动声明
推断分支整段删除。

**注意**：前端判"首次绑定"需与转换器当前的遮蔽规则一致（函数局部
遮蔽模块全局）——silu_fe 的 hoist 机制已有 assigned-names 收集设施
可复用，但需覆盖"函数内读全局、赋值即局部"的 Python 语义。

### 改动面

| 部件 | 改动 |
|---|---|
| 前端 | parse/hoist 处发 ann_assign（首次绑定） |
| Python 转换器 | 删自动声明推断分支 |
| Rust 参照 | 删 auto-decl 分支（约 200 行） |
| ir_interp.si | 兼容（两节点同构处理，无需改） |
| 输出 | 不变（若形状逐字节保持）或微变（重钉） |

### 风险与反论

- 前端作用域分析与转换器符号表现在是**两处必须一致的规则**——
  本提案把"声明判定"从转换器挪到前端，规则总数不变，但 IR 更自述。
- 反论：现状已被差分钉住且文档化；此提案省的是第二实现的工作量，
  对参考本身几乎无收益。
- 细节坑：`global` 语句、闭包提升（hoist）下的绑定判定、元组解包
  首次绑定——都要进前端判定范围。

---

## P5 布尔装箱单例

### 现状与证据

`node is True`（pyobj 值）展开为 12 条指令，且结合形状固定为右折叠：

```llvm
%".19" = icmp ne {i32,i8*}* %node, null    ; 非空
%".20" = gep {i32,i8*}* %node, 0           ; tag
%".21" = load i32
%".22" = icmp eq i32 %".21", 3             ; tag==BOOL
%".23" = gep {i32,i8*}* %node, 1           ; payload
%".24" = load i8*
%".25" = bitcast i8* → i64*
%".26" = load i64
%".27" = icmp eq i64 %".26", 1             ; 值==1
%".28" = and i1 %".22", %".27"             ; and(tag_eq, val_eq)
%".29" = and i1 %".19", %".28"             ; and(non_null, ·)
```

`create_bool` 每次 malloc 新盒；`is True/False` 靠 tag+payload 判等。
第二实现曾把折叠顺序写成左结合，差分立即报错——形状无语义影响
却极易写错。

### 提案

`True`/`False` 做成**模块级单例**：const_prefix 预置 `@silu_true`/
`@silu_false` 两个全局盒，`create_bool` 直接返回（payload 私有不可变，
共享安全）。于是：

```llvm
%".x" = icmp eq {i32,i8*}* %node, @"silu_true"    ; 12 条 → 1 条
```

附带收益：布尔不再逐个 malloc；`is` 在布尔上的语义与 CPython 的
小整数/布尔单例行为对齐。

### 改动面

| 部件 | 改动 |
|---|---|
| const_prefix.ll | +2 全局；create_bool 改为查单例 |
| Python 转换器 | is-bool 分支 12 行 → 1 行 |
| Rust 参照 | 同步 |
| 输出 | 字符串编号整体 +2（与 P6 联动则无感）；重钉 |

### 风险与反论

- 需确认无代码依赖 create_bool 返回不同分配（如对盒做指针身份比较
  的语义——当前 `is` 的展开只做 tag+payload 判等，改单例后甚至可以
  更强：指针即身份，与 Python 一致）。
- +2 全局使所有语料的字符串编号平移；无 P6 时是全量重钉的机械工作。
- 反论：展开在 silu_fe 源中仅 2 处（json_emit 的 `is True/False`），
  绝对开销很小；本提案的主要价值是消除易错形状，而非性能。

---

## P6 命名与声明顺序解耦

### 现状与证据

字符串全局名 = `str_{len(module.globals)}`（typed_codegen_flat.si
L3524：`f'str_{len(self.module.globals)}'`），即**模块全局表的实时
长度**。由此产生整套"全局槽号模型"（PROGRESS.md"核心实现模型"§5）：

- 运行时前缀占 str_0..296（STR_BASE=297）；
- 每个源级函数 +1（main 改名后仍占位）、方法预声明、
  match_class 捕获建 gvar、Json 运行时 +15（TAGGED_SLOTS）；
- 字符串与变量声明顺序交织决定编号。

第二实现调试中，多消耗一个 silent 槽即产生 400+ 行编号漂移；
"全局槽号模型"是 PROGRESS 里篇幅最大的一章。

### 问题

1. 输出对声明顺序极度敏感：任何语句顺序调整、任何新函数都会平移
   全部后续字符串编号——对增量编译、输出 diff、第三方实现都不友好。
2. 编号唯一性依赖"每次创建必递增"，与 interning（P2）互斥。
3. 规约表面积大：第二实现的主要失败面之一。

### 提案

内容寻址命名：字符串全局名改为 `@"str." + 内容转义`（如
`@"str.hello_20world"`）或 `@"str.<FNV1a64 hex>"`（哈希函数需在
两个实现中逐位一致，约 10 行；转义内容名则无需哈希协议但长字面量
名字冗长）。碰撞用确定性后缀（首次出现序）。

### 改动面

| 部件 | 改动 |
|---|---|
| Python 转换器 | `_create_global_string*` 命名函数 |
| Rust 参照 | `add_str` 命名函数 |
| 运行时前缀 | str_0..296 保留原名（或一并重命名，二选一需评估） |
| 输出 | 全语料变化（重钉） |

**连带删除**：STR_BASE/TAGGED_SLOTS 算术、函数/方法/捕获计数规则、
"字符串与变量创建序交织"章节——PROGRESS 的"全局槽号模型"整章作废，
 replaced by 一句"字符串全局按内容命名，变量按源码名"。

### 风险与反论

- `.ll` 可读性：`str_297` vs `str.hello` —— 内容名可读性反而更好；
  哈希名较差。
- 前缀内 297 个运行时字符串是否重命名需决策：不重命名则存在两套
  命名风格并存（str_N 与 str.内容）；重命名则前缀 diff 巨大但一次性。
- 反论（支持现状）：`len(module.globals)` 实现只有一行，简单到
  不可能写错；复杂的是它的**后果**（槽号模型），而后果已经文档化。

---

## 8. 依赖与建议顺序

```
P6（内容寻址命名）──┐
                    ├──→ P2（interning）   # 两者共享查找表，建议同批
P5（布尔单例）──────┘   # +2 全局在 P6 下无编号平移问题
P4（声明赋值同形）       # 独立，工作量最小
P3（迭代器标注 3b）      # 独立，IR 加尾字段
P1（字符串统一）         # 独立但最大；建议最后单独评估 1a vs 1b
```

建议批次：**第一批 P4+P5**（小、独立、直接删易错形状）→
**第二批 P6+P2**（结构性最大收益）→ **第三批 P3b** →
**P1 单独立项**（需先回答 §P1 评估问题）。

每批 = Python 参考 + Rust 参照 + 运行时（如涉及）同 commit，
全量差分门禁绿后重钉版本。

## 9. 给评估者的问题清单

1. **P1 方向裁决**：手动内存管理的前提下，1a（refcount 不可变 str）
   / 1b（不可变 str + 显式 strbuf）/ 维持现状，哪个与 silu 的目标
   （自举、可预测、小实现）最一致？refcount 的每次赋值开销是否
   违背项目"无隐藏成本"原则？
2. **P2+P6**：是否存在转换器之外的部件依赖 `str_N` 顺序命名？
   （已知：.ll 由 clang 编译，名字无语义；自举 fixed-point 测试
   比较的是输出一致性而非具体名字——请确认。）若做，内容转义名与
   FNV1a 哈希名哪个更可取？
3. **P3**：3a（desugar）与 3b（标注）哪个更符合"IR 应自述"的长期
   方向？3a 对 `for ch in s` 的 UTF-8 语义在 desugar 后如何保真？
4. **P4**：前端承担"首次绑定"判定后，`global` 语句、闭包提升、
   元组解包首次绑定是否构成遗漏场景？转换器删自动声明分支后，
   差分门禁还能保护什么？
5. **P5**：布尔单例是否会改变任何可观察语义（`is` 的指针比较在
   单例下与 tag+payload 判等等价——是否应当让 `is` 在布尔上直接
   退化为指针比较，与 CPython 对齐）？
6. **总体**：这六条里是否存在"不值得做"的？判据建议：第二实现的
   边际难度下降量 vs 参考实现的改动风险。若 silu 的首要目标是
   自举正确性而非输出质量，P2 的优先级是否应下调？

## 10. 证据复现命令

```bash
cd <repo 根目录>
python reference/diff_harness.py ll conv rustconv   # 18/18
python reference/diff_harness.py ir fe rustfe       # 19/19

# P1：别名拷贝（silu_fe.si L220-221 three = two）
./siluc1 < selfhost/silu_fe.si | grep -B1 -A1 'rawstr_copy' | head -12
# P1：原地 append（parse_fstring L828 lit = lit + ch）
./siluc1 < selfhost/silu_fe.si | grep 'rawstr_append' | head -6
# P2：常量重复（ir_interp 218 个常量 97 个唯一；add 19 份）
./siluc1 < selfhost/ir_interp.si | grep 'ZeroDivisionError'
# P3：五族循环块名（silu_fe 内 object 迭代 63 处、range/riter/siter 各 1 处）
./siluc1 < selfhost/silu_fe.si | grep -oE '^(loop|riter|iter|siter|dict_iter)_[a-z]+(\.[0-9]+)?:' | sed 's/[.:]$//;s/\.[0-9]*$//' | sort | uniq -c
# P5：is True 展开（json_emit）
./siluc1 < selfhost/silu_fe.si | sed -n '/json_emit/,/^}/p' | head -50
# P6：命名规则源头
sed -n '3524p' selfhost/typed_codegen_flat.si
```

## 11. 决策记录要求

评估完成后，无论结论如何，请在本文档头部追加一节
"## 评估结论（日期/评估方）"，逐条记录：采纳/否决/缓议、理由、
以及（若采纳）目标版本。实施类提案一律走"双实现同 commit + 门禁
全绿 + 重钉"流程。
