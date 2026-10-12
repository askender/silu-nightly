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
- **可变性的幻觉**：Python 的 str 不可变，Silu 的 rawstr 槽用
  Rust String 式所有权模拟：`s = s + x` 摊销 O(1) 原地追加，但
  `t = s` 是**拷贝**——之后改 `t` 不影响 `s`，与 Python 一致。
- **内存**：槽被覆写时释放旧缓冲（drop-on-assign）；表达式临时量
  （拼接/比较/包含的操作数、被丢弃的表达式语句结果）在使用后立即释放；
  函数退出时释放其全部 rawstr 局部槽与参数槽。重赋值循环与高频调用
  均为常量内存。

## 3. 容器语义

- **list / dict 是 Python 引用语义**：`b = a` 共享同一对象，
  函数参数传入的也是引用。这与 rawstr 的拷贝语义**有意不同**，
  因为 Python 程序员对容器的预期就是共享。
- 因此 rawlist/rawdict **不做作用域 drop**：参数、名字赋值、返回值
  都可能共享指针，没有逃逸分析就释放会是 use-after-free。其缓冲区
  随进程生命周期存在（无 GC）。需要严格内存上限的长驻程序应注意。
- `dict[int, int]` / `dict[int, float]` 的键序不保证与 CPython 一致
  （开放寻址哈希表，`print(d)` 的顺序是表序而非插入序）；`len`、
  查找、`del` 语义一致。
- 边界检查：默认 panic 并报行号；`SILU_CHECKS=0` 时下标越界是
  未定义行为（UB）——只在已验证的程序上关。

## 4. 类型推断契约

- 注解（`x: int`、`def f(a: int) -> int`）是**用户契约**：编译器
  无条件相信，违背注解的改绑会被强制转换或 panic。
- 未注解的名字经**保守推断**升级为原始类型：只有证明该作用域内
  所有赋值都产生同一类型时才升级；任何冲突（如 `x = 7` 后 `x = x / 2`）
  都回落 PyObject 动态存储，Python 改绑语义完整保留。
- 跨函数推断同样保守：参数从未在函数体内改绑、且所有调用点传同一
  原始类型才非装箱传递；返回表达式全部解析为同一类型才非装箱返回。
  递归、关键字参数、元数不符、调用点类型冲突一律回落动态 ABI。

## 5. 检查开关

| 配置 | 溢出 | 边界 | 除零 | 适用 |
|---|---|---|---|---|
| `SILU_CHECKS=1`（默认） | panic | panic | panic | 开发、调试、正确性优先 |
| `SILU_CHECKS=0` | 回绕 | UB | panic | 已验证程序的最后几个百分点 |

`SILU_CODEGEN=dynamic` 可回到全 PyObject 的旧后端用于对照调试。

## 6. 验证工具

- `silu verify program.si`：解释器（参考语义）与编译产物对拍，
  任何分歧都是编译器 bug。
- 运行时错误带源码行号：`IndexError: list index out of range (line 3)`。
- `silu symbolic program.si`：Z3 符号执行，枚举路径并生成测试输入。
