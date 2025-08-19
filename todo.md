# TODO List

## 🎯 AI Roadmap Priorities

### 2025-2028: Logic Mastery Phase (High Priority)
- [ ] **CFG & Static Analysis Integration**
  - Implement context-free grammar validation
  - Add static analysis capabilities to IR generator
  - Target: Pass LLVM IR test suites, SPEC Benchmarks
  
- [ ] **Data Flow & Control Flow Analysis**
  - Enhance symbolic executor with advanced flow analysis
  - Implement Code Property Graph (CPG) generation
  - Target: Juliet Test Suite compliance for vulnerability detection

- [ ] **SMT & Logic Verification**
  - Integrate SMT solver capabilities
  - Add formal verification support to symbolic executor
  - Target: 20-50% improvement over SMT-LIB benchmarks

### 2028-2032: Logic + Probabilistic Fusion (Medium-High Priority)
- [ ] **Probabilistic Reasoning Integration**
  - Combine symbolic execution with uncertainty modeling
  - Implement Bayesian inference capabilities
  - Target: 10x improvement in experimental design efficiency

- [ ] **Causal Inference Support**
  - Add causal reasoning to language constructs
  - Support for causal graph modeling
  - Target: Causal Inference Competition benchmarks

### 2032-2036: Self-Bootstrapping (Medium Priority)
- [ ] **Self-Modification Capabilities**
  - Enable AI to symbolically execute and modify its own code
  - Implement automated bug detection and fixing
  - Target: >80% accuracy in self-bug-fixing

- [ ] **Code Generation & Optimization**
  - Self-improving compiler optimizations
  - Automated refactoring capabilities
  - Target: Maintain 100M+ LOC codebases

## 🎯 Technical Benchmarks to Target
- **Logic**: SV-COMP, SMT-LIB, TPTP theorem proving
- **Optimization**: DIMACS, TSPLIB, SAT competitions  
- **Probabilistic**: Kaggle datasets, Bayesian network benchmarks
- **Graph Analysis**: LDBC benchmarks for graph databases

# TODO List

## ✅ 已完成功能

- [x] 创建基础的 SiluInterpreter 类，继承自 ast.NodeVisitor
- [x] 实现执行环境 (Environment) 来管理变量和函数
- [x] 实现核心 AST 节点的 visit_* 方法 (Module, Expr, Assign, Name, Constant)
- [x] 实现数学运算和比较运算的 visit_* 方法 (BinOp, UnaryOp, BoolOp, Compare)
- [x] 添加对内置函数的支持 (print) 和命令行接口 (silu file.si)
- [x] 实现控制流的 visit_* 方法 (If, While)
- [x] 实现函数定义和调用的 visit_* 方法 (FunctionDef, Return, Call)
- [x] 添加对基础数据类型 (int, float, str, bool) 的支持
- [x] 实现 Simple IR 转换器，将 AST 转换为中间表示
- [x] 实现 for 循环的 visit_For 方法
- [x] 创建统一的 BaseASTProcessor 基类架构
- [x] 实现 CLI 工具支持解释和 IR 生成双模式
- [x] 添加对列表、元组、字典等容器类型的支持
- [x] 实现链式比较 (3 < 5 < 7)
- [x] 支持 lambda 表达式
- [x] 添加 break/continue 语句支持
- [x] 实现 Simple IR 解释器，可以直接执行 IR
- [x] 添加uv包管理器支持和相关文档更新
- [x] 实现符号执行功能，支持符号值和路径条件跟踪，CLI支持 `silu symbolic` 命令
- [x] silu symbolic 支持可选的 --simplify 选项，可以将多个条件合并为单个更简洁的条件
- [x] silu symbolic 支持可选的 --solve 选项，使用z3等求解器来进行求解，特别是对于函数的求解，每条路径求解后都生成testcase

## 🔄 正在进行的功能





## 🎯 高优先级功能

- [ ] 集成 LLVM 工具链以执行生成的 IR
  - 研究 LLVM-Python 绑定
  - 实现 IR 到 LLVM IR 的转换
  - 添加编译到机器码的支持

- [ ] 增强错误处理和调试功能
  - 改进错误消息，包含行号和列号信息
  - 添加调试模式 (`--debug` 标志)
  - 实现堆栈跟踪显示
  - 添加语法高亮的错误显示

- [ ] 扩展内置函数库
  - 数学函数：abs, min, max, round, pow
  - 字符串函数：len, split, join, replace
  - 列表函数：append, extend, pop, sort
  - 输入函数：input

## 🚀 中优先级功能

- [ ] 面向对象编程支持
  - 类定义和实例化 (class, __init__)
  - 方法调用和属性访问
  - 继承和多态
  - 特殊方法 (__str__, __repr__, __add__ 等)

- [ ] 模块系统
  - import 语句支持
  - from...import 语句支持
  - 模块搜索路径
  - 标准库模块

- [ ] 异常处理机制
  - try/except/finally 语句
  - raise 语句
  - 自定义异常类
  - 异常链

- [ ] 高级控制流
  - with 语句（上下文管理器）
  - 生成器和 yield
  - 装饰器支持

## 🔧 低优先级功能

- [ ] 性能优化
  - 字节码编译
  - 常量折叠优化
  - 尾递归优化
  - 内存使用优化

- [ ] 开发工具集成
  - 语法高亮支持
  - LSP (Language Server Protocol) 实现
  - 代码格式化工具
  - 静态类型检查

- [ ] 跨平台代码生成
  - 转译到 Python
  - 转译到 JavaScript
  - 转译到 C++
  - WebAssembly 支持

- [ ] 包管理系统
  - 包定义文件格式
  - 依赖管理
  - 包仓库和分发
  - 版本管理

## 📋 代码质量改进

- [ ] 测试覆盖率提升
  - 增加边界情况测试
  - 集成测试案例
  - 性能基准测试
  - 错误处理测试

- [ ] 文档完善
  - API 文档生成
  - 教程和示例
  - 语言规范文档
  - 贡献指南

- [ ] 代码重构
  - 进一步模块化
  - 代码风格统一
  - 性能瓶颈识别和优化
  - 技术债务清理

## 📊 当前状态总结

- ✅ 核心解释器功能：**100% 完成**
- ✅ IR 生成器：**100% 完成**
- ✅ IR 执行器：**100% 完成**
- ✅ 符号执行器：**100% 完成**
- 🔄 LLVM 集成：**0% 完成**
- 📈 总体进度：**约 90% 核心功能完成**

## 🎯 下一步重点

1. **实现 IR 解释器** - 允许直接执行生成的 IR，为编译器后端奠定基础
2. **增强错误处理** - 提供更好的开发者体验
3. **扩展内置函数** - 使语言更实用
4. **面向对象支持** - 添加现代编程语言的核心特性

## 📅 具体实施计划

### Phase 1: IR 解释器实现 ✅ (已完成)

**已实现功能**:
1. ✅ 创建了完整的 `ir_interpreter.py` 模块
2. ✅ 实现了 `IRInterpreter` 类，支持所有IR指令：
   - 变量赋值和访问
   - 算术和逻辑运算
   - 函数定义和调用
   - 控制流（if/while/for）
   - 容器类型（list/dict/tuple）
   - Lambda 表达式
   - Break/continue 语句
3. ✅ 在 CLI 中添加了 `exec` 子命令
4. ✅ 编写了 25 个测试用例，全部通过
5. ✅ 支持 JSON 和元组格式的 IR 文件
6. ✅ 智能的字符串字面量识别

**性能验证**:
- ✅ 可以执行完整的 demo.si 程序
- ✅ 支持递归函数（阶乘、斐波那契）
- ✅ 支持所有语言特性
- ✅ 200个测试全部通过

### Phase 2: 符号执行引擎实现 ✅ (已完成)

**已实现功能**:
1. ✅ 创建了完整的 `symbolic_executor.py` 模块
2. ✅ 实现了 `SymbolicExecutor` 类，支持符号值和路径条件：
   - 符号变量创建和管理
   - 路径条件跟踪和约束生成
   - 控制流分支分析（if/else, while）
   - 函数定义和调用的符号处理
   - 内置函数的符号版本
3. ✅ 在 CLI 中添加了 `symbolic` 子命令
4. ✅ 编写了 31 个测试用例，全部通过
5. ✅ 支持 JSON 和元组格式的 IR 输入
6. ✅ 智能的路径可满足性检查

**性能验证**:
- ✅ 可以分析包含分支的程序
- ✅ 生成所有可能的执行路径
- ✅ 检测路径条件冲突
- ✅ 31个符号执行测试全部通过

**使用示例**:
```bash
# 符号执行 Silu 源代码
silu symbolic program.si

# 符号执行 IR 文件
silu symbolic program.ir.json

# 符号执行源代码字符串
silu symbolic --source "if x > 5: y = 1 else: y = 2"

# 符号执行 IR 字符串
silu symbolic --source '("module", (("if", ("chained_compare", "x", ">", 5), ("assign", "y", 1, null), ("assign", "y", 2, null)),))'
```

### Phase 3: 错误处理增强 (当前优先级)

**目标**: 提供更友好的错误信息和调试支持

**实施步骤**:
1. 在 `BaseASTProcessor` 中添加行号追踪
2. 创建自定义异常类 `SiluError`, `SiluSyntaxError`, `SiluRuntimeError`
3. 在解释器中改进错误消息格式
4. 添加 `--debug` 模式支持变量状态输出
5. 实现简单的堆栈跟踪

**验收标准**:
- 错误信息包含行号和列号
- 调试模式可以显示变量状态
- 错误消息对用户友好且有帮助

### Phase 3: 内置函数扩展 (预计 1 天)

**目标**: 添加常用的内置函数

**实施步骤**:
1. 在 `Environment` 类中添加新的内置函数：
   - 数学：`abs`, `min`, `max`, `round`
   - 字符串：`len`, `split`, `join`
   - 列表：`append`, `pop`, `sort`
   - 输入输出：`input`
2. 更新测试用例覆盖新函数
3. 更新文档和示例

**验收标准**:
- 所有新函数正确工作
- 与 Python 标准库行为一致
- 完整的测试覆盖

### Phase 4: 面向对象基础 (预计 3-4 天)

**目标**: 添加基本的类和对象支持

**实施步骤**:
1. 在 AST 处理器中添加 `visit_ClassDef` 方法
2. 创建 `Class` 和 `Instance` 类来表示类和实例
3. 实现方法调用和属性访问
4. 支持 `__init__` 构造方法
5. 添加基本的继承支持

**验收标准**:
- 可以定义类和创建实例
- 支持方法调用和属性访问
- 构造方法正确工作
- 简单继承功能可用

## 🔄 迭代开发原则

1. **测试驱动开发** - 每个功能先写测试再实现
2. **小步迭代** - 每次提交一个小功能，确保系统稳定
3. **向后兼容** - 新功能不破坏现有代码
4. **文档同步** - 代码变更时同步更新文档
5. **性能关注** - 在功能实现时考虑性能影响

## 📈 成功指标

- ✅ 所有测试通过，覆盖率 > 90%
- ✅ CLI 功能完整且易用
- ✅ 错误信息清晰友好
- ✅ 代码结构清晰，易于扩展
- ✅ 文档完整，示例丰富
