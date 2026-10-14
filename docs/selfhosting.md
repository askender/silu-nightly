# Silu 自举（Self-hosting）规划

状态：**规划定稿，进行中**。目标：Silu 能写出 Silu 自己的解释器和
编译器。本文档按"Rust 有对应物才做"的原则筛选语言特性，避免垂直于
某一个语言的语法。

## 1. 自举的两种形态与路线选择

- **解释器自举**：用 Silu 写 Silu 的树遍历解释器。动态风格（装箱
  dict/list 表示 AST）即可起步，工作量主要在程序本身。
- **编译器自举**：用 Silu 写编译器。完整复刻 typed pipeline（kind
  推断、所有权纪律、LLVM 文本生成）是天量工程；**现实形态是
  "Silu 写前端 + emit C"**——Silu 程序读源码、产 C 文本，shell
  调 clang/gcc 兜底。emit C 同样兑现"AOT 编译"的价值。

## 2. 语言特性缺口（按必要性排序，全部有 Rust 对应物）

| # | 特性 | Rust 对应 | 状态 |
|---|---|---|---|
| 1 | 文件读取 / stdin 全读 | `fs::read_to_string` | ✅ `read_file` / `read_stdin` |
| 2 | 字符串/字符内建：`ord`/`chr`/`split`/`strip`/`startswith`/`endswith`/`isdigit`/`isalpha`/`isspace` | `char::is_numeric`、`str::split` 等 | ✅ 已实现 |
| 3 | 嵌套/递归实例字段 | struct 含 `Box<T>` | ✅ 已实现 |
| 4 | enum（无负载判别值，`class Color(Enum): RED = 1`）| `enum`（无数据变体） | ✅ 已实现；带负载的标签联合（`X = A \| B` 式）留作后续设计 |
| 5 | 编译路径 match | `match` | ✅ 已实现（值/or/捕获/通配/guard；序列/映射/类模式仅解释器） |

已具备：递归函数、class（struct+impl）、容器家族、rawstr 码点语义、
`int(s)`/`str(x)`、`input()`、panic 错误出口。

## 3. 里程碑

- **M1：Silu 写表达式计算器**（递归下降 lexer + parser + eval，
  动态风格）。验证 1、2 的完备性，暴露语义缺口。
- **M2：Silu 写 IR 树遍历解释器**。IR 是 JSON（jsonparse 基准已有
  手写解析底子）；AST 节点用装箱 dict 或 3 的实例树。
- **M3：Silu 写 IR→C 文本生成器**。输出 C 源码经管道交 clang——
  绕开"调用外部命令"的需求。
- **M4：前端自举**（Silu 源码 → IR）。需要 4+5（enum + match）。

## 4. 明确不做

- `system()`/子进程内建：emit 文本 + shell 管道已够，不引入安全
  与可移植性负担。
- 异常机制：编译器遇错 panic（带行号）已够；错误恢复是另一个量级
  的工程设计，与"通用性"无关。
- 为自举牺牲既有语义：任何特性先过"Rust 有对应物"这关。
