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
- [x] 实现 IR 到源代码转换功能，支持双向转换 (源码 ↔ IR)，CLI支持 `silu to-source` 命令
- [x] IR 到源代码转换器支持智能字符串字面量识别，正确区分标识符和字符串常量
- [x] 与符号执行器共享转换函数，确保表达式显示的一致性和可读性

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
- ✅ IR 到源代码转换器：**100% 完成**
- ✅ 符号执行器：**100% 完成**
- 🔄 LLVM 集成：**0% 完成**
- 📈 总体进度：**约 95% 核心功能完成**

## 🎯 下一步重点

1. **增强错误处理** - 提供更好的开发者体验
2. **扩展内置函数** - 使语言更实用
3. **面向对象支持** - 添加现代编程语言的核心特性
4. **LLVM 集成** - 实现真正的编译器后端

## 📅 具体实施计划

### Phase 1: IR 解释器实现 ✅ (已完成)

- ✅ 实现完整的 `IRInterpreter` 类和 `silu exec` 命令
- ✅ 支持所有 IR 指令和语言特性
- ✅ 详细文档：`docs/simple_ir_design.md`

### Phase 2: 符号执行引擎实现 ✅ (已完成)

- ✅ 实现完整的 `SymbolicExecutor` 类和 `silu symbolic` 命令
- ✅ 支持路径条件跟踪、Z3 求解器集成和测试用例生成
- ✅ 详细文档：`docs/symbolic_execution.md`

### Phase 3: IR 到源代码转换器实现 ✅ (已完成)

- ✅ 实现完整的 `IRToSourceConverter` 类和 `silu to-source` 命令
- ✅ 支持双向转换和智能字符串字面量识别
- ✅ 详细文档：`docs/ir_to_source.md`

### Phase 4: 错误处理增强 (当前优先级)

**目标**: 提供更友好的错误信息和调试支持
- 添加行号追踪和自定义异常类
- 实现调试模式和堆栈跟踪

### Phase 5: 内置函数扩展 (预计 1 天)

**目标**: 添加常用的内置函数
- 数学函数：`abs`, `min`, `max`, `round`
- 字符串函数：`len`, `split`, `join`
- 列表函数：`append`, `pop`, `sort`
- 输入输出：`input`

### Phase 6: 面向对象基础 (预计 3-4 天)

**目标**: 添加基本的类和对象支持
- 类定义和实例化
- 方法调用和属性访问
- 构造方法和简单继承

## 🔄 开发原则

- **测试驱动开发** - 每个功能先写测试再实现
- **小步迭代** - 每次提交一个小功能，确保系统稳定
- **向后兼容** - 新功能不破坏现有代码
- **文档同步** - 代码变更时同步更新文档
