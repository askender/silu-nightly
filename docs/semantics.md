# Silu 语义契约（Semantics Contract）

本文档写明 Silu 与 Python 语义**一致**的地方、**有意分歧**的地方，
以及原生编译（typed 后端）下的性能与内存契约。它的定位是"系统程序员
一页纸"：写高性能 Silu 代码前读这一篇就够。

## 1. 数值语义

| 方面 | 行为 |
|---|---|
| 整数表示 | 有符号 64 位（i64），**不是** Python 的任意精度 bigint |
| 整数溢出 | 默认（`SILU_CHECKS=1`）panic 并报行号，等同 Rust debug 构建；`SILU_CHECKS=0` 时二进制补码回绕（wrap），等同 Rust release 构建 |
| 浮点 | IEEE 754 双精度（f64）；`int / int` 恒为 float（Python 语义），`//` 与 `%` 遵循 Python 的向下取整语义（与被除数符号无关） |
| 除零 | 任何配置下都 panic（Rust 亦如此） |
| NaN | `!=` 对 NaN 恒为真（Python 语义），其余比较为假 |
| int/float 混合运算 | int 提升为 float（Python 语义） |
| int → float 精度 | `float(int)` 与比较遵循 IEEE 最近舍入；`int(float)` 截断，不可表示时 panic（checks 开启） |

**与 Python 的最大分歧就是 bigint**：超过 i64 范围的整数运算在默认配置下
会 panic（而不是静默正确），在 `SILU_CHECKS=0` 下会回绕（而不是报错）。
需要任意精度的程序目前不适合 Silu。

## 2. 字符串语义

- **码点语义（与 Python 完全一致）**：`len(s)`、`s[i]`、`s[a:b]`、
  `for ch in s` 都按 Unicode 码点计，已在多字节文本（CJK）上与
  CPython 逐字节对拍验证。代价是 `s[i]` 为 O(n) 走查（与 Rust 的
  `chars().nth(i)` 相同）；`for` 迭代整体仍为 O(字节数)。
- **等值/比较/成员判断**：按 UTF-8 字节序，与码点序等价（memcmp 语义）。
- **`find` / `rfind` / `index` 返回码点下标**：与 `len(s)`、`s[i]`
  同一坐标系，多字节文本上可直接用作下标（`s[s.find("中")]`、
  `s[i:]`）。未命中时 `find`/`rfind` 为 -1，`index` 抛 ValueError。
- **`upper()` / `lower()` 只映射 ASCII 字母**：非 ASCII 字母原样保留
  （`"é".upper()` 仍是 `"é"`，CPython 得 `"É"`，`"ß".upper()` 的
  多字符展开也没有）。这是当前的语言边界，**不是** CPython 语义；
  需要 Unicode 大小写的程序应注意。
- **可变性的幻觉**：Python 的 str 不可变，Silu 的 rawstr 槽用
  Rust String 式所有权模拟：`s = s + x` 摊销 O(1) 原地追加，但
  `t = s` 是**拷贝**——之后改 `t` 不影响 `s`，与 Python 一致。
- **内存**：槽被覆写时释放旧缓冲（drop-on-assign）；表达式临时量
  （拼接/比较/包含的操作数、被丢弃的表达式语句结果）在使用后立即释放；
  函数退出时释放其全部 rawstr 局部槽与参数槽。重赋值循环与高频调用
  均为常量内存。
- **lexer 内建**（自举前置，docs/selfhosting.md）：`ord`/`chr` 按码点
  编解码 UTF-8；`split()`（空白运行合并，空串抑制）与 `split(sep)`
  （字面分隔，保留空字段，空分隔符 panic）；`strip()` 去两端 ASCII
  空白；`startswith`/`endswith`；`isdigit`/`isalpha`/`isspace` 对
  ASCII 精确，非 ASCII 码点归入 alpha（其余 False）；空串的
  is* 全为 False。`read_file(path)` 整读文件（不存在则 panic
  OSError）；`read_stdin()` 读 stdin 到 EOF（保留换行）。

## 3. 容器语义

- **list / dict 是 Python 引用语义**：`b = a` 共享同一对象，
  函数参数传入的也是引用。这与 rawstr 的拷贝语义**有意不同**，
  因为 Python 程序员对容器的预期就是共享。
- 因此 int/float 元素的 rawlist 与 rawdict **不做作用域 drop**：参数、
  名字赋值、返回值都可能共享指针，没有逃逸分析就释放会是
  use-after-free。其缓冲区随进程生命周期存在（无 GC）。需要严格
  内存上限的长驻程序应注意。
- **`list[str]` 是例外**：槽持有元素的**拷贝**（写入时 copy-in），
  读取交出**新拷贝**（读出即拥有，改 `l[0]` 不影响已读出的值）——
  因此它可以安全地做逐元素 drop（clear/覆写/作用域退出），与
  rawdict 的 str 键同一套所有权约定。
- **dict 的键序是插入序，与 CPython 一致**（typed dict 的五个族与
  动态 dict 都是）：`for k in d`、`.items()`/`.keys()`/`.values()`、
  `print(d)`、装箱同一个顺序；删除后的重排（reindex）按 entry 序
  压紧，`d[k] = v` 覆盖已有键绝不触发重排。（早期版本按哈希表序
  迭代 typed dict，输出与 CPython 不同。）
- **在自身的循环里改结构是运行时错误**：循环体对正在迭代的 dict
  做插入、删除、`pop`、`clear`，或对正在迭代的 set 做 `add`，下一步
  循环头 panic `RuntimeError: dictionary changed size during iteration`
  （先检查后判界，所以最后一次迭代里的改动照样报错，与 CPython
  相同）。`break` 之后的改动不算。只改值（`d[k] = v * 10`）永远合法，
  后续迭代读到新值。**比 CPython 严格的一点**：先删后插使大小不变
  时，CPython 继续迭代，Silu 同样 panic（`dictionary modified during
  iteration`）——CPython 文档本就允许这种程序"漏迭代"。
- **list 循环按活动长度走**（CPython 的 list 迭代器语义）：循环体里
  `append` 的元素会被访问到（工作表惯用法 `for x in xs:
  xs.append(...)`），`pop` 会缩短循环；typed 与动态 list 一致。
- **str 循环迭代进入循环时的内容**：循环体里对被迭代的名字重绑定
  或原地追加，都不影响正在进行的循环。
- **`del xs[i]`**（typed / 动态 list）：尾部左移、长度减一，负下标
  从末尾数，越界 panic `IndexError`。
- **dict 相等按内容**：`==` / `!=` 比较键值对（嵌套递归比较），
  与顺序无关；list 的 `==` 同理。
- **`dict[str, str]` 的值归 dict 所有，读是借用**：`x = d[k]` 得到
  拷贝（`x += "!"` 不影响 dict）；`d.get(k)` / `d.setdefault(k, v)`
  同样交出拷贝；`d.pop(k)` 把所有权交给调用方。已知差异：一参
  `d.get(k)` 未命中返回**空串**而非 None（typed str 不能为 None），
  二参形式与 CPython 一致；一参 `pop` 未命中 panic KeyError。
- **一个名字一种类型**：同一作用域里一个名字只能有一种表示。
  `for k in int_dict` 之后再 `for k in str_dict` 是编译错误（改个
  名字）；同理 `x = 5` 之后 `x = "a"`。
- 边界检查：默认 panic 并报行号；`SILU_CHECKS=0` 时下标越界是
  未定义行为（UB）——只在已验证的程序上关。

## 3.5 类（record 类型，dataclass 语义）

- **每个 class 都是记录类型**：类体只允许注解字段（按声明顺序）
  与方法（首参 `self`）；继承、类变量、用户 `__init__` 一律拒绝。
  对应 Rust 的 `struct` + `impl`。
- **构造**：`P(a, b)` 按声明顺序位置构造；`P(x=a)` 关键字构造；
  带默认值的字段之后不能再出现无默认值字段（dataclass 规则）。
  每个实参按字段注解 coerce，违约：解释器 TypeError / 编译 panic
  （int 字段收 float 属于违约，不做静默截断）。
- **方法与 self**：`st.m(a)` 脱糖为 `P__m(st, a)`；`self.x` 读写
  走字段偏移；方法可互调。self 是只读绑定。
- **表示**（编译路径）：实例是一块 `8 × 字段数` 字节的堆缓冲，
  无对象头、无 vtable；字段按编译期布局表做偏移 load/store。
  str 字段写入时 copy-in、读出时 copy-on-read（与 rawstr 槽同一
  纪律）。
- **容器字段（list/dict）是引用语义**：字段槽存指针，读出交出
  共享引用（`lst = b.items` 后 `lst.append(...)` 直接影响字段），
  与 Silu 容器的全局规则（§3）一致。容器默认值**每实例独立**——
  Python 的共享可变默认值陷阱在 Silu 不存在。
- **实例不 drop**（正式决定）：实例允许自由别名（`b = a` 共享），
  没有借用检查器，对共享实例做 drop 就是 use-after-free；实例内存
  随进程生命周期。Rust 的 drop 依赖所有权系统，没有对应物就不做。
- **实例引用语义**：`b = a` 共享同一实例（与 list/dict 一致）。
- **编译路径第一版的边界**：嵌套实例字段（字段是另一个 class）暂
  不支持（明确报错）；实例不可装箱——`print(p)` 是编译错误，
  打印字段（`print(p.x)`）即可。
- **从 typed 容器取出的实例再赋值字段**（`it: Rec = items[i]` 之后
  `it.ret = v`）：实例在列表里以 i64 字承载，赋值前转回指针。自举
  编译器曾对这整个形状段错误（2026-10-25 起），现已修复并有门禁。

## 3.6 输出时机：`print` 逐个求值并立即输出

`print(a, b, c)` 在编译后的程序里**逐个**求值参数、输出一个再求值
下一个（流式，无中间缓冲）。CPython 先求值全部参数、最后统一格式
化，所以后面的参数若修改了前面的可变参数，两边输出不同：

```python
d = {"b": 2}
print(d, d.pop("b"))      # CPython: {} 2   Silu（编译）: {'b': 2} 2
```

求值顺序本身与 CPython 相同（从左到右）；不同的只是容器参数被
格式化的时刻。`silu interpret` 与 CPython 一致。需要与 CPython 一致
的输出时，把变更与打印分开写。

## 4. 标量光标提升（SILU_SCALARS=1，默认开）

`list[int]` 若在一个函数作用域内**只以 `x[0]` 形式出现**（读或写），
编译器把它提升为局部 i64 槽（入口播种一次）——递归下降解析器的
`pos[0] += 1` 光标从每次 4 次装箱下标变为纯寄存器算术。保守规则：
名字在**多个函数的参数表**中出现（跨函数共享游标）、有任何其他使用
（传参、`len(x)`、非 0 下标、`x = ...` 改绑）或是 `list[float]` 时
一律不提升；不提升即走普通装箱路径，**永远不会产生错误代码**。
`SILU_SCALARS=0` 可整体关闭。

**热循环惯用法**：若分析器不覆盖你的场景（如光标跨函数共享），
可手动把 `pos[0]` 提出为 `p: int` 局部量、在调用边界前后同步——
实测对 jsonparse 这类"每字符都要物化字符对象"的负载**无收益**
（差距主体在字符物化而非光标装箱），仅当循环体内有大量独立于字符
访问的游标算术时才值得。

## 5. 类型推断契约

- 注解（`x: int`、`def f(a: int) -> int`）是**用户契约**：编译器
  无条件相信，违背注解的改绑会被强制转换或 panic。
- 未注解的名字经**保守推断**升级为原始类型：只有证明该作用域内
  所有赋值都产生同一类型时才升级；任何冲突（如 `x = 7` 后 `x = x / 2`）
  都回落 PyObject 动态存储，Python 改绑语义完整保留。
- 跨函数推断同样保守：参数从未在函数体内改绑、且所有调用点传同一
  原始类型才非装箱传递；返回表达式全部解析为同一类型才非装箱返回。
  递归、关键字参数、元数不符、调用点类型冲突一律回落动态 ABI。
- **推导式的目标名只属于推导式**（Python 3 作用域）：`x = a;
  y = [x for x in xs]` 之后 `x` 仍是 `a`。目标可以遮蔽一个已有的
  动态名字，或一个类型与元素种类相同的 typed 槽（`list[str]` 的元素
  进 str 槽、`list[int]` 进 int 槽）；元素种类对不上（动态可迭代对象
  进 typed 槽、str 元素进 int 槽）是编译错误。元组目标
  `[n for n, s in rows]` 的每个名字都绑定。
- **函数里后赋值的名字是整函数的局部量**（Python 规则）：
  `def f(): y = x; x = 2` 里读 `x` 是编译错误
  （`is read before it is assigned ... Python raises UnboundLocalError`），
  不是回落去读模块全局。

## 6. 检查开关

| 配置 | 溢出 | 边界 | 除零 | 适用 |
|---|---|---|---|---|
| `SILU_CHECKS=1`（默认） | panic | panic | panic | 开发、调试、正确性优先 |
| `SILU_CHECKS=0` | 回绕 | UB | panic | 已验证程序的最后几个百分点 |

`SILU_CODEGEN=dynamic` 可回到全 PyObject 的旧后端用于对照调试。

## 7. 验证工具

- `silu verify program.si`：解释器（参考语义）与编译产物对拍，
  任何分歧都是编译器 bug。
- 运行时错误带源码行号：`IndexError: list index out of range (line 3)`。
- `silu symbolic program.si`：Z3 符号执行，枚举路径并生成测试输入。
- **语义门禁** `tests/test_semantics_vs_cpython.py`：期望值由真
  CPython 现场产生，每个用例在 Python 平面（`silu build`）和自举
  平面（`siluc1` → clang）各跑一遍；另有"必须编译失败"（不支持的
  构造）与"必须响亮 panic"（文档化差异）两张表。
- **内存安全门禁** `tests/test_asan_runtime.py`：上述用例源码、一组
  内存形状（精确大小缓冲上的装箱 str、`s = s + s`、码点偏移缓存、
  `input()`、strbuf、`list[str]`）和若干语料文件，在真
  AddressSanitizer 下运行，两个转换器平面各一遍；任何报告即红。
  **对 `.ll` 直接 `clang -fsanitize=address` 什么都不检查**——clang
  只插桩带 `sanitize_address` 属性的函数，IR 输入没有这个属性。
  `tools/asan_run.py` 先给每个 `define` 加属性，并在任何程序计为
  干净之前，用一个已知的越界读证明本工具链确实会报告。
