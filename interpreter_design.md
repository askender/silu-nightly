# 方案：实现一个可以执行 Python 子集语法的解释器

## 1. 目标
创建一个能够解释执行 Python 语言核心特性的子集的解释器。这个解释器将能够处理变量、基本数据类型（整数、浮点数、字符串、布尔值）、基本数学运算、变量赋值、if/else 控制流、while 循环以及函数定义和调用。

## 2. 核心设计思路
- **直接使用 Python 的 `exec` 或 `eval`**：
  - 最简单的方法是直接利用 Python 自身的解释能力。我们可以将输入的 Silu 代码视为字符串，然后传递给 `exec()` 或 `eval()` 来执行。
  - 优点：实现极其简单，可以立即支持所有 Python 语法。
  - 缺点：失去了创建独立语言的意义，安全性依赖于 Python 的沙箱机制（这通常很困难）。
- **AST 解析与执行 (推荐)**：
  - 使用 Python 内置的 `ast` 模块来解析 Silu 代码并生成抽象语法树 (AST)。
  - 创建一个自定义的 AST 遍历器 (`ast.NodeVisitor` 或 `ast.NodeTransformer`) 来解释和执行 AST 节点。
  - 优点：可以精确控制支持哪些 Python 特性，更容易添加自定义行为，更安全（我们完全控制执行流程），为将来编译到 LLVM IR 奠定基础。
  - 缺点：比直接 `exec` 复杂一些。

## 3. 推荐方案：基于 AST 的解释器
我们将采用基于 AST 的方法来构建解释器。

### 3.1. 架构组件
1.  **Parser (解析器)**: 
    - 利用 `ast.parse()` 将 Silu 源码字符串转换为 Python AST。
2.  **Semantic Analyzer (语义分析器)** (可选，后期添加):
    - 遍历 AST，检查类型、变量声明等语义规则。
3.  **Interpreter (解释器)**:
    - 继承 `ast.NodeVisitor`。
    - 实现 `visit_*` 方法来处理不同的 AST 节点类型。
    - 维护一个执行环境 (Environment/Scope) 来存储变量和函数。

### 3.2. 实现步骤
1.  **定义执行环境 (Environment)**:
    *   创建一个类来管理变量和函数的存储。可以是一个简单的字典，或者更复杂的嵌套作用域结构。
2.  **创建解释器类**:
    *   `class SiluInterpreter(ast.NodeVisitor):`
    *   初始化时传入全局环境。
3.  **实现核心 `visit_*` 方法**:
    *   `visit_Module(self, node)`: 遍历模块中的所有语句。
    *   `visit_Expr(self, node)`: 处理表达式语句。
    *   `visit_Assign(self, node)`: 处理变量赋值。需要处理目标 (target) 和值 (value)。支持 `x = 10` 这样的简单赋值。
    *   `visit_Name(self, node)`: 处理变量名的加载 (Load) 和存储 (Store)。
    *   `visit_Constant(self, node)`: (Python 3.8+) 处理字面量值（数字、字符串、布尔值、None）。
    *   `visit_BinOp(self, node)`: 处理二元运算符（`+`, `-`, `*`, `/`, `//`, `%`, `**` 等）。需要根据 `node.op` 的类型调用相应的运算。
    *   `visit_UnaryOp(self, node)`: 处理一元运算符（`+`, `-`, `not` 等）。
    *   `visit_BoolOp(self, node)`: 处理布尔运算 (`and`, `or`)。
    *   `visit_Compare(self, node)`: 处理比较运算 (`==`, `!=`, `<`, `<=`, `>`, `>=`)。
    *   `visit_If(self, node)`: 处理 `if/elif/else` 语句。
    *   `visit_While(self, node)`: 处理 `while` 循环。
    *   `visit_For(self, node)`: 处理 `for` 循环 (如果需要)。
    *   `visit_List`, `visit_Tuple`, `visit_Dict` (如果需要基础数据结构)。
    *   `visit_FunctionDef(self, node)`: 处理函数定义。需要将函数对象存储在环境中。
    *   `visit_Return(self, node)`: 处理函数返回值。
    *   `visit_Call(self, node)`: 处理函数调用。需要解析函数名，评估参数，并执行函数。
4.  **执行流程**:
    *   用户提供 Silu 代码字符串。
    *   调用 `ast.parse(code)` 生成 AST。
    *   创建 `SiluInterpreter` 实例。
    *   调用 `interpreter.visit(ast_tree)` 开始执行。
5.  **错误处理**:
    *   在 `visit_*` 方法中捕获和处理执行时可能出现的错误，如变量未定义、类型错误等，并提供清晰的错误信息。

### 3.3. 初始支持的特性
- 变量声明与赋值 (`x = 10`)
- 基本数据类型 (int, float, str, bool)
- 基本数学运算 (`+`, `-`, `*`, `/`, `//`, `%`, `**`)
- 布尔运算 (`and`, `or`, `not`)
- 比较运算 (`==`, `!=`, `<`, `<=`, `>`, `>=`)
- `if/else` 控制流
- `while` 循环
- 函数定义 (`def`) 和调用

### 3.4. 安全性考量
- 由于我们自己控制 AST 的执行，可以禁止危险的节点，如 `ast.Import`, `ast.ImportFrom`, `ast.Call` (限制可调用的函数) 等，从而创建一个安全的执行环境。

## 4. 结论
基于 AST 的解释器方案是可行且推荐的。它提供了良好的控制力、可扩展性和安全性，同时也为项目的长期目标（如编译到 LLVM IR）打下了坚实的基础。