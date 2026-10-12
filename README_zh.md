# Silu（斯路）编程语言

[English](README.md) | **简体中文**

**Python 语法进，原生二进制出。** Silu（斯路）采用 Python 兼容的语法子集，
让同一个程序拥有三种运行方式：参考语义解释器、基于 Z3 的符号执行器，
以及 LLVM 编译器——其产物运行速度达到手写 Rust 的水平。

| 程序 | CPython | silu 二进制 | Rust |
|---|---|---|---|
| n-body（5 万步） | 0.21s | 0.0065s | 0.0075s |
| spectral-norm（n=300） | 0.29s | 0.0068s | 0.0056s |
| string（4.8 万次拼接） | 0.049s | 0.0032s | 0.0031s |
| mandelbrot（80x24） | 0.044s | 0.0034s | 0.0033s |

在 11 个基准程序（含 5 个 Benchmarks Game 经典）上，编译产物平均达到
**手写 Rust 的约 1.0 倍、CPython 的约 16 倍、树遍历解释器的约 600 倍**——
完整数据与方法见 [benchmarks/README.md](benchmarks/README.md)。

## 为什么选择 Silu

- **Rust 速度的原生编译** — 类型注解直接驱动非装箱的机器表示
  （`int`/`float`/`bool` 标量、`list[int]`/`list[float]` 数组、
  `dict[int, int]`/`dict[int, float]` 哈希表、`str` 为 Rust String 风格的
  独占缓冲），保守的类型推断在可证明安全时让未注解代码享受同样待遇；
  证明不到的地方完整保留 Python 语义。
- **内置符号执行** — 自动探索函数的所有执行路径，用 Z3 生成路径约束，
  并自动产生命中每条路径的具体测试输入。在 Python 子集编译器中，
  这种"速度 + 形式化分析"的组合是独一无二的。
- **一份 IR，多个后端** — 所有程序都会降级到一种轻量的元组式中间表示（IR），
  它可以直接解释执行、反向转回源码、做符号分析，也可以经 LLVM 编译为原生代码。
- **Python 语法子集** — Silu 直接复用 Python 的解析器，大多数简单的
  Python 程序无需修改即可运行。`silu check program.py` 会明确告诉你
  哪些特性受支持、哪些不受支持。
- **不局限于 Silu 源码** — 同一套 IR 与符号执行工具链也能处理
  **C 语言程序**（基于 pycparser），可对既有 C 代码做路径分析和测试用例生成。

## 安装

要求 Python 3.11 及以上。

```bash
# 使用 pip
pip install -e .

# 使用 uv（开发环境推荐）
uv sync && uv pip install -e .
```

运行时依赖：`llvmlite`、`pycparser`、`z3-solver`、`loguru`、`mlir`。

## 快速开始

```bash
# 运行 Silu 程序（解释执行）
silu hello.si

# 检查 Python 代码是否与 Silu 兼容
silu check program.py

# 单行交互执行
silu interpret --source "print('Hello, World!')"
```

Hello world（`hello.si`）：

```python
name = "Silu"
version = 1.0

print("Hello from", name, version)

def greet(person):
    return "Welcome to " + person + "!"

print(greet("Silu Programming"))
```

## 执行模式

| 命令 | 功能 |
|---|---|
| `silu program.si` | 直接解释执行源码 |
| `silu check program.py` | 校验 Python 兼容性，给出精确的错误原因 |
| `silu ir program.si --output program.ir.json` | 生成 IR（支持 JSON 与 Python 字面量格式） |
| `silu exec program.ir.json` | 直接执行 IR |
| `silu to-source program.ir.json` | 将 IR 转回可读源码 |
| `silu symbolic program.si` | 符号执行分析 |
| `silu llvm program.ir.json --output program.ll` | 将 IR 降级为 LLVM IR |
| `silu build program.si -o program` | 一条命令编译出原生可执行文件 |

### 符号执行

```bash
silu symbolic symbolic_demo.si
```

符号执行器会报告每个函数的所有可行路径：路径条件、返回值，以及能命中
该路径的具体测试输入。安装了 Z3 时路径约束会被精确求解；未安装时也能
正常运行（优雅降级）。

### 原生编译

```bash
silu build program.si -o program   # 一条命令：IR -> LLVM -> clang
./program
```

（分步管线——`silu ir`、`silu llvm`、`llc`、`clang`——仍可用于
逐阶段检查中间产物）

类型注解直接驱动原生表示：带注解的 `int` / `float` / `bool` 编译为
非装箱的机器值，`list[int]` / `list[float]` 编译为原始元素数组，
`dict[int, int]` / `dict[int, float]` 编译为机器字哈希字典（开放寻址
加墓碑删除，`del d[k]` / `d.pop(k)` 原生执行，负载因子触发压缩式重哈希），
带注解的 `str` 编译为 Rust String 风格的独占缓冲（赋值即拷贝、追加原地
扩容、覆写释放旧缓冲）——这些路径上没有 PyObject 装箱。未注解的标量在
保守推断证明"所有赋值都产生同一类型"时也享受同样待遇；两遍签名分析还能
整体提升函数：从未被改绑且所有调用点传入同一原始类型的参数以非装箱方式
传入，所有返回表达式解析为同一原始类型的函数以非装箱方式返回（冲突则
保持动态 ABI，Python 改绑语义不变）。字符串全面遵循 Python 码点语义——
`len`、`s[i]`、`s[a:b]`（含步进切片）、`sub in s` 和 `for ch in s`
都原生执行，且在多字节文本上与 CPython 完全一致。`SILU_CHECKS=0`
可将溢出与边界检查切换为 Rust release 模式，为下标密集的热循环
换取最后几个百分点的性能。

### 分析 C 程序（实验性）

同一套 IR 与符号执行工具链可通过 pycparser 处理 C 源码：

```bash
# C 源码 → Silu 格式 IR → 符号路径 / 测试用例
python get_ret_from_json.py my_program.c      # 对比 IR 执行结果与编译后 C 的执行结果
python run_symbolic_tool.py my_program.c.ir.json
```

目前该能力被用于分析嵌入式/车载风格的状态机代码（参见 `car_*_core*.c` 示例与 `ir_generator_for_c.py`）。

## 语言特性

- **数据类型**：int、float、str（完整码点语义）、bool、bytes、list、dict
- **控制流**：if/elif/else、while、for（配合 `range()`）、match/case 完整结构化模式匹配（值、序列、映射、或模式、guard、捕获、星号模式）
- **赋值**：简单赋值、链式赋值（`a = b = 1`）、元组解包（`for key, value in d.items()`）、下标删除（`del d[k]`）
- **运算符**：算术/比较/位运算、成员判断 `in` / `not in`（字符串、列表、字典）、字符串索引与含步长切片
- **函数**：用户自定义函数、默认参数、纯闭包（只读捕获定义作用域的变量）
- **内建函数**：`print`、`type`、`isinstance`、类型转换、`len`、字典方法（`.keys()`、`.values()`、`.items()`、`.get()`、`.pop()`、`.setdefault()`、`.clear()`）、列表方法（`.append()`、`.pop()`、`.clear()`）
- **安全性**：默认开启边界/溢出/除零 panic（Rust debug 模式），可用 `SILU_CHECKS=0` 切换 release 模式；另内置内存保护，阻止失控的序列乘法与超大的 `range()`/`extend()` 操作

完整语法参考见[语言特性指南](docs/language_features.md)。

## 项目结构

```
silu/                    # 语言实现包
├── cli.py               # 统一命令行接口
├── interpreter.py       # AST 解释器（参考语义）
├── ir_generator.py      # AST → Silu IR
├── ir_interpreter.py    # IR 直接执行
├── ir_to_source.py      # IR → 源码（往返转换）
├── symbolic_executor.py # 符号执行引擎（含 silu/symbolic/）
├── typed_codegen.py     # Silu IR → LLVM IR（typed 主后端）
└── silu_ir_to_llvm.py   # Silu IR → LLVM IR（动态基础运行时）
tests/                   # 630+ 个 pytest 测试
benchmarks/              # 11 个程序的基准套件（对比 CPython 与 Rust 镜像）
docs/                    # 技术文档
examples/                # 示例程序
ir_generator_for_c.py    # C → Silu IR（基于 pycparser）
```

## 文档

- [AI 开发计划](docs/plan.md) — 长期推理路线图与基准测试
- [CLI 使用指南](docs/cli_usage.md) — 完整的命令行参考
- [语言特性](docs/language_features.md) — 语法与示例
- [IR 设计](docs/simple_ir_design.md) — 中间表示格式
- [符号执行](docs/symbolic_execution.md) — 程序分析能力
- [LLVM IR 生成](docs/llvm_ir_generation.md) — 基于 LLVM 的原生编译
- [解释器规范](docs/interpreter_spec.md) — 核心实现细节
- [开发指南](docs/development.md) — 环境搭建、测试与贡献

## 愿景与 AI 路线图

Silu 的长期判断是：严格的逻辑推理与学习型概率推理应当住在同一个
语言运行时里。具体的地基已经就位——控制流图 IR、SMT 驱动的符号执行器，
以及一个可信到能与参考解释器逐字节对拍的原生编译器。在此之上，路线图
逐层叠加概率推理、自我纠错与假设驱动的实验；各阶段的里程碑以及每阶段
如何复用下层的验证工具链，见 [AI 开发计划](docs/plan.md)。

## 开发

```bash
uv sync && uv pip install -e .  # 环境搭建

make test    # 运行全部测试
make cov     # 带覆盖率的测试
make fmt     # 使用 ruff 格式化
```

欢迎贡献！详见[开发指南](docs/development.md)。

## 许可证

MIT License — 见 [LICENSE](LICENSE)。
