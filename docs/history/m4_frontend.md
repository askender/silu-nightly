# M4 前端自举设计：Silu 源码 → Silu IR

状态：**设计定稿，待实施**。本文档圈定 M4 第一版的边界、缩进算法与
IR 发射约定。目标是 `selfhost/silu_fe.si` 对真实程序的输出与
`silu/ir_generator.py` 逐字节一致，从而无缝接入 M2/M3。

## 1. 边界：节点白名单

M4 只覆盖**经过 selfhost/*.si 实测的全部 43 种节点**（见下）；不在名单
内的语法（break/continue、嵌套 class、listcomp、`in` 用于非 str、`**`、
subscript 三参数切片的 step、`dict` 字面量、`raise`）首版拒绝并报
"M4: unsupported"。白名单里**加粗的**是必须做对才能跑通 selfhost 的：

- 模块/控制：`module`、`line`、`func_def`、`return`、`if`、`while`、`for`、`break`(拒)、`class_def`、`enum_def`、`match`、`match_case`、`match_value`、`match_as`
- 赋值：`assign`、`ann_assign`、`aug_assign`、`subscript_assign`、`attribute_aug_assign`、`tuple_assign`(拒)
- 表达式：一元 `-`、`and`、`or`、二元 `+ - * / // % **`、比较链
  `== != < <= > >= is is not in`、三元 `if_expr`
- 值：`const`(int/float/bool/None/str/bytes)、`name`、`call`(含 kwargs)、`attribute`、`subscript`、`slice`、`list`、`tuple`、`dict`(仅空/字面量)

## 2. 输入分词（lexer）

- 空白：空格/Tab 折叠；**缩进语义**（§3）由行级处理，不是 lexer 状态。
- 注释：`#` 到行尾删除。
- 数字：整数、浮点（含指数）、`0x` 十六进制（可选）。
- 标识符：字母/下划线开头，字母数字下划线继续。
- 字符串：单/双引号、转义 `\" \\ \n \t \'`、前缀 `r"/b"` 视情况拒绝。
- 运算符：多字符优先（`//` `**` `<=` `>=` `==` `!=` `+=` `-=` `*=` `/=` `->`、
  `+=` 等的 `-` 视后续规则）、单字符兜底。
- 关键字集合（语法用于消歧，不是 lexer 的额外 token）。

## 3. 缩进（行级算法，唯一"有点想法"的部分）

Python 缩进在 Silu 里是"简单版"：不区分 tab/space 混用的细节语义，
统一展开 tab 为 4 空格；同级块共享列号，新增级推栈，回退级弹栈并先
闭合更深块。

```
indent_stack = [0]
for each non-blank non-comment line:
    level = count_leading_spaces(line) // 1
    while level > indent_stack.top:
        push(level); emit_indent_marker()   # conceptual; M4 用栈帧而非标记
    while level < indent_stack.top:
        pop(); close_block()
    parse_line_as_statement_into_current_block()
```

块由**前一个语句的冒号决定**：以 `:` 结尾的语句（`def`/`class`/`if`/
`elif`/`else`/`while`/`for`/`match`/`case`）开新块。elif/else 与父块同级
时先闭合前一个 if/while/… 的当前块再重开兄弟块。match/case 视作独立
块族（case 缩进深度 > match，body 缩进深度 > case）。

M4 数据结构：一个栈，元素是"块"（类型 + 已收集的语句列表），入栈
push、弹栈完成语句并 attach 到父块。

## 4. 语法（递归下降）

Precedence（从低到高，与 Python 相同，其中右结合只用于 `**`）：
`or` → `and` → `not` → `is/is not/in` → `==!=<<=>>=` → `|`(拒) →
`+ -` → `* / // %` → `**`(右) → unary `+ -` → postfix `() [] .`

语句级：
- `def name(params) [-> ret]:` → `func_def`，注解成 (`name`, type) 元组
- `class Name[(Enum)]:` → `class_def`/`enum_def`，只允许 Enum 基类
- `return [expr]` → `return`
- `if/elif/else` → `if`（链式）；`while`、`for x in expr:`、`break`、`pass`(映射到空 tuple 或跳过)
- `match subject:` + `case pattern:` → `match`
- 赋值：目标为 Name/Subscript/Attribute 各产对应节点；`x += e` 等
- 表达式语句：函数调用 → `call`（kwargs 成 `((k, v)...)`)，否则 `expr`(被拒进语义时忽略) 或 `assign`
- `import`/`from`：跳过（忽略，与 IR 现行为一致）
- `print(...)`：special-case 到 `call`；其它表达式语句降级为 `expr`

关键的发射约定（必须与 ir_generator.py 一致）：
- 数值/字符串/None/布尔 → `["const", value]`（float 保持 Python float）
- 变量引用 → `["name", id]`
- 赋值目标为 Name → `["assign", id, value, None]`（assign 里 target 是裸字符串）；Subscript → `["subscript_assign", obj, key, value]`；Attribute → `["attribute", obj, attr]` 作为 target 进 `["assign", ...]`?——**不是**：attribute 赋值进 `["assign", ["attribute", obj, attr], value, None]`（与 ir_generator 相同）
- `aug_assign` 目标：`["aug_assign", ["name", x], op, value]`；属性/下标增赋：`["attribute_aug_assign", obj, attr, op, value]`、`["subscript_aug_assign", obj, key, op, value]`
- kwargs：`["call", f, (args...), ((k, v)...)]`（无 kwargs 时空 tuple）
- `line` 标记：每条**顶层语句**前插 `["line", n]`（与 ir_generator 的 `_visit_stmts` 相同）；块内同样逐条插
- `func_def` 六元组：`["func_def", name, params, body, param_annotations, return_annotation]`（注解节点；无注解位 `None`）
- `match` 三元组；`match_case` 四元组（pattern, guard, body）
- `slice`：`["slice", lo, hi, step]`（缺省 None）
- 空块：`pass` 语句**保留为 `("pass",)`**（ir_generator 有）

## 5. 验证

- **对拍基准**:`selfhost/*.si` 全部 + 若干基准（wordcount/knucleotide
  精简版、dict/list/str/for/if/while 核心语义集）——M4 输出 JSON 与
  `silu ir --format json` 输出的字节相等（容许空格差异，先 normalize)。
- **端到端**:M4 产出 IR → M2(ir_interp）解释 → 与 CPython 对拍；
  M4 产出 IR → M3(ir2c)→ clang → 二进制 → 与 CPython 对拍。
- **自举自洽**:M4 的**自身源码**（它是 Silu 程序）能经 M4 解析出
  IR、再经 M3 编译出二进制——`selfhost/silu_fe.si` 能编译自己。

## 6. 工作量预估

| 部分 | 行数 |
|---|---|
| lexer + 缩进块栈 | ~180 |
| 语句级递归下降 | ~150 |
| 表达式解析 | ~150 |
| **合计** | **~480 行** |

估计 1.5 小时实现 + 0.5 小时对拍调试，规模与 M2 相当。

## 7. 明确不做

- 不处理 async/await、生成器、`yield`、`global`/`nonlocal`、装饰器
- 不做错误恢复（首个语法错误即退出，带行号）
- 不做增量/缓存；输入为一次性的整段源码
