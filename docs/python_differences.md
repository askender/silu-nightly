# Silu 与 CPython 的差异清单

本文档列 Silu 与 CPython 的**全部已知差异**，供从 Python 迁移的读者
快速对照。每一条都有差分探针背书（CPython 现场对拍；语义门禁
`tests/test_semantics_vs_cpython.py` 或 2026-11-27 的四平面电池）。
语义细节与内存模型见 `docs/semantics.md`；本文只讲"哪里不一样"。

**两个接受面要先分清**：

| 平面 | 定位 | 语法/内建接受面 |
|---|---|---|
| `silu interpret`（参考解释器） | 参考语义 Oracle | 宽：支持 try/except、lambda、import、生成器、闭包等（它就是为准 CPython 语义服务的） |
| 编译平面（`siluc` / 自举 `siluc1` → clang） | 产品编译器 | 严：本文标注"响亮拒绝"的构造在编译期直接报错，**绝不静默给错** |

两边都拒绝的构造（如 `for/else`、分号、默认参数）在任何平面都过不去；
只被编译平面拒绝的构造在解释器里能跑——`silu verify` 会把这类分歧
当成对拍差异报出来。

## 1. 数值

| 方面 | CPython | Silu 编译平面 | Silu 解释器 |
|---|---|---|---|
| 整数 | 任意精度 bigint | 有符号 i64 | 与 CPython 一致（bigint） |
| 超范围运算 | 正确结果 | panic（默认）/回绕（`SILU_CHECKS=0`） | 正确的 bigint 结果 |
| `2 ** -1` | `0.5` | panic `int pow with negative exponent` | `0.5` |
| `round` / `divmod` | 有 | 无（响亮拒绝） | 有 |
| `abs` / `min` / `max` / `any` / `all` | 有 | 无（响亮拒绝） | 有 |
| `sum` | 有 | 有 | 有 |
| `map` / `filter` / `enumerate` / `zip` / `reversed` | 有 | 无（响亮拒绝） | map/enumerate/zip 有，filter/reversed 无 |
| 布尔算术 | `True + True == 2` | 一致 | 一致 |
| 浮点格式 | 最短往返表示 | 一致（C 库半偶舍入，已对拍） | 一致 |
| 链式比较 / 三元 | 有 | 一致 | 一致 |

解释器与编译平面在整数溢出上的分歧是**有意保留**的：解释器是参考
语义（Python 精确），编译平面按硬件整数 panic/回绕。`silu verify`
对这类程序会报告差异。

## 2. 字符串

码点语义（`len` / `s[i]` / 切片 / 迭代 / `find` 系返回值）与 CPython
**完全一致**，多字节文本已逐字节对拍。差异在方法面与少数边界：

- **`upper()` / `lower()` 只映射 ASCII 字母**（`"é".upper()` 仍是
  `"é"`，CPython 得 `"É"`）。当前语言边界，Unicode 简单大小写映射表
  待裁决（STATUS §四）；`"ß".upper()` 的多字符展开 CPython 也与简单
  映射不同。
- **`strip()` / `lstrip()` / `rstrip()` 只剥 ASCII 空白**；编译平面
  还不支持 `strip(chars)` 带参与独立的 `lstrip`/`rstrip`（响亮拒绝；
  解释器全部支持）。
- **`find` / `rfind` / `index` / `startswith` / `endswith` 的
  `start`/`end` 参数在编译平面被忽略**（`"abcabc".find("c", 3)` 编译
  得 2，CPython 得 5）——已知 bug，修复中；解释器行为正确。
- **`replace("", x)` 编译平面返回空串**（CPython 在每个边界插入）——
  已知 bug，修复中。
- f-string：基本插值 `f"hi {name} {1 + 2}"` 三平面一致；**格式 spec
  （`{x:.2f}`）、调试（`{x=}`）与 `!r` 转换**：三平面一致响亮拒绝
  （2026-11-28 起，措辞同源）。`repr(x)` 作为**值**（返回带引号字符
  串）尚未实现。
- `%` 格式化与 `str.format`：解释器支持 `%`（与 CPython 一致），
  编译平面响亮拒绝；`.format` 两边都不支持。
- 编译平面不支持的 str 方法（响亮拒绝，解释器全部支持）：
  `title` `capitalize` `swapcase` `center` `ljust` `rjust` `zfill`
  `partition` `rpartition` `splitlines` `expandtabs` `casefold`
  `removeprefix` `removesuffix` `encode` `rsplit`、`split` 的
  `maxsplit` 参数、`index`/`find` 的 start 参数、`isalnum`
  `isdecimal` `isidentifier` `istitle`。
- 支持的核心面（三平面与 CPython 一致）：`split(sep)`（字面分隔、
  保留空字段）、`split()` 空白合并、`join`、`count`、`replace`（非空
  针）、1 参 `find`/`rfind`/`index`、1 参 `startswith`/`endswith`、
  `isdigit`/`isalpha`/`isspace`/`isupper`/`islower`、比较与 `in`、
  `ord`/`chr`、`*` 重复、`+` 拼接、切片（含步长与负下标）。
- `str(实例)` 得 `"None"`（不是类名）；实例打印 `print(p)` 编译平面
  直接拒绝——打印字段即可。

## 3. 容器

- **list / dict / 实例是引用语义**（`b = a` 共享），与 CPython 一致；
  rawstr 槽是 Rust-String 式所有权（`t = s` 拷贝，观测上与 CPython 的
  不可变 str 一致）。
- **dict 键序是插入序**，与 CPython 一致（`.items()` / `.keys()` /
  `.values()` / `print(d)` 同序）。
- **循环中改容器**（2026-11-26 起，行为与 CPython 3.12 实测对齐）：
  - 循环体对正在迭代的 dict 插入/删除/`pop`/`clear`，下一步循环头
    panic `RuntimeError`。**设计决定（2026-11-27 用户确认保留）**：
    CPython 3.12 实测对"先删后插、大小不变"同样 raise
    （`dictionary keys changed during iteration`），Silu 同样 panic
    （消息为 `dictionary modified during iteration`）——行为一致，仅
    消息不同。只改值（`d[k] = v * 10`）永远合法，后续迭代读到新值。
  - list 循环按活动长度走（循环体 `append` 的元素会被访问到，
    `pop` 缩短循环），与 CPython 的 list 迭代器一致。
  - str 循环迭代进入循环时的内容（快照），与 CPython 一致。
- **`del xs[i]`** 尾部左移、负下标、越界 panic——一致。
- **tuple**（2026-11-28 起与 CPython 完全对齐）：构造、索引、`len`、
  `in`、`==`、`!=`、字典序比较、拼接（`(1,) + (2,)`）、重复、切片、
  迭代、嵌套（元组进 list/dict 的 repr）、`isinstance(t, tuple)` /
  `isinstance(t, list)` 全部一致——`print((1, 2))` 输出 `(1, 2)`，
  `(1, 2) == [1, 2]` 为 `False`。此前 tuple 与 list 共用 tag-4 盒，
  repr 打 `[...]`、跨类型相等误答 True。残余：`str(t)`/`repr(t)`
  作为**值**（非打印）尚未实现（响亮/空盒边界），rs 神谕对 tuple
  的下标/切片响亮 bail。
- **set**：`len` / `in` / `add` / `discard` / 并交差可用（配
  `sorted(list(s))` 比较）；**`print(s)` 的元素序与 CPython 不同**
  （且编译平面输出 `[...]`）——元素序取决于各自哈希表内部布局，无法
  复刻 CPython 的顺序，这是永久边界，不是 bug。
- **`d.get(k)` 一参在 `dict[str, str]` 未命中**：编译平面返回空串、
  解释器返回 `None`（typed str 不能为 None）——待裁决（STATUS §四）；
  二参形式与 CPython 一致。
- 编译平面不支持的容器方法（响亮拒绝；解释器支持）：
  list 的 `extend` / `remove` / `sort`（动态与 typed 都不支持；
  `insert` 动态可用、typed 不支持）、dict 的 `popitem`、
  `update(kw 形式)`。支持的：list 的 `append` / `insert`(动态) /
  `pop` / `clear` / `index` / `count` / `reverse` / `copy`，dict 的
  `get` / `setdefault` / `pop` / `keys` / `values` / `items` /
  `update(字典)` / `copy` / `del`。
- dict/set 推导式与 list 推导式：单生成器形式三平面一致（含 if 过滤、
  元组目标、目标作用域）；**多生成器**（`for x in a for y in b`）支持
  面不一致——避免使用。

## 4. 类（record 类型）

- dataclass 语义：`P(a, b)` 按声明顺序位置构造；`self.x` 读写；
  方法可互调——与使用 `@dataclass` 的 CPython 一致（探针：构造、
  字段写、方法链、容器字段每实例独立、str 字段）。
- **继承、类变量、用户 `__init__` 响亮拒绝**（编译错误，解释器
  TypeError）。
- 容器字段默认值**每实例独立**（CPython 的共享可变默认值陷阱不
  存在）；参数默认值整体不支持（见下）。
- 实例允许自由别名、不 drop（内存随进程）；嵌套实例字段暂不支持；
  实例不可装箱。

## 5. 函数与作用域

- **一个名字一种类型**：同一作用域一个名字只能有一种表示（`x = 5`
  后 `x = "a"` 编译错误）。
- **无默认参数**（每个参数必填）、无 `*args`、无 `**kwargs`、无
  `f(*[1,2,3])` 星号调用、无 lambda——全部响亮拒绝（三个平面一致）。
  关键字实参 `f(b=3, a=1)` 不支持。
- **`global` / `nonlocal` 语句**：全部平面响亮拒绝（解释器曾静默忽略，
  2026-11-28 起在共享解析关卡拒绝，与编译平面对齐）。
- 闭包（内层函数捕获外层局部量）拒绝；无捕获嵌套函数支持。
- 推导式目标只属于推导式（Python 3 作用域）；函数里后赋值的名字是
  整函数局部量（UnboundLocalError 规则，编译期报错）。
- `sorted`：编译平面无 `sorted` 内建（响亮拒绝）；解释器的 `sorted`
  就是 Python 的 sorted（`key=`/`reverse=` 完全支持）。
- **海象 `:=`**：全部平面响亮拒绝（解释器曾误解析为 None 再报运行
  时错，2026-11-28 起语法期拒绝）。
- `__name__` / `if __name__ == "__main__"`：解释器可用；编译平面
  `__name__` 未定义（响亮 NameError）。

## 6. 语句与控制流

| 构造 | CPython | Silu 解释器 | Silu 编译平面 |
|---|---|---|---|
| `for/else`、`while/else` | 有 | 响亮拒绝 | 响亮拒绝 |
| 分号 `;` 复合行 | 有 | 响亮拒绝 | 响亮拒绝 |
| 反斜杠续行 | 有 | 支持 | 响亮拒绝 |
| `try/except` / `finally` | 有 | 支持 | 响亮拒绝 |
| `raise` | 有 | 支持 | **支持**（运行时响亮 panic，退出码非 0，无捕获） |
| `assert` | 有 | 支持 | 响亮拒绝 |
| `import` | 有 | 支持 | 接受（`import math` 探针通过；模块功能可用性未承诺） |
| `with` | 有 | 支持 | 响亮拒绝 |
| `yield` / 生成器 | 有 | 支持 | 响亮拒绝 |
| `lambda` | 有 | 支持 | 响亮拒绝（IR 节点未实现） |
| 海象 `:=` | 有 | 响亮拒绝 | 响亮拒绝 |
| `match` | 完整模式匹配 | int 字面量与 str 字面量 case + 通配 | 同左（全 int 字面量降 switch） |
| 三元 / 短路 / `is` / `isinstance` | 有 | 一致 | 一致 |
| `print(sep=, end=)` | 有 | 一致 | 一致 |
| `input()` | 有 | 一致 | 一致 |
| 文档字符串 / pass / 三引号 | 有 | 一致 | 一致 |

## 7. 输出时机（编译平面）

`print(a, b, c)` 编译产物**逐个求值、逐个输出**；CPython 先求值全部
参数再统一格式化。后面的参数修改了前面的可变参数时输出不同：

```python
d = {"b": 2}
print(d, d.pop("b"))      # CPython: {} 2   Silu 编译: {'b': 2} 2
```

求值顺序本身一致（从左到右）；`silu interpret` 与 CPython 一致。
需要一致输出时，把变更与打印分开写。

## 8. 差异背后的纪律

1. **宁报 ERROR 不出错误字节**：编译平面遇到不支持的构造一律响亮
   拒绝（编译期 NotImplementedError / 语法错误，或运行时响亮
   panic / wasm `unreachable`），绝不静默给近似结果。本文标"响亮
   拒绝"的条目都是这个纪律的产物。
2. **每一版与 CPython 对拍**：语义门禁的期望值由真 CPython 现场产生；
   探针电池（数值 / 字符串 / 容器 / 类 / 控制流 / 内建矩阵）持续
   扩充，新分歧先对拍再定性（bug 修复，边界文档化）。
3. 已知 bug 与待裁决项跟踪在 `reference/STATUS.md` §四。
