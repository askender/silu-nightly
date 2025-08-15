# TODO List

- [x] 创建基础的 SiluInterpreter 类，继承自 ast.NodeVisitor
- [x] 实现执行环境 (Environment) 来管理变量和函数
- [x] 实现核心 AST 节点的 visit_* 方法 (Module, Expr, Assign, Name, Constant)
- [x] 实现数学运算和比较运算的 visit_* 方法 (BinOp, UnaryOp, BoolOp, Compare)
- [x] 添加对内置函数的支持 (print) 和命令行接口 (silu file.si)
- [x] 实现控制流的 visit_* 方法 (If, While)
- [x] 实现函数定义和调用的 visit_* 方法 (FunctionDef, Return, Call)
- [x] 添加对基础数据类型 (int, float, str, bool) 的支持
- [ ] 集成 LLVM 工具链以执行生成的 IR
- [ ] (低优先级) 实现 for 循环的 visit_For 方法