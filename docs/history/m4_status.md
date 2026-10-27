# M4 前端自举：完成（2026-10-15）

**M4 完成**：`selfhost/silu_fe.si`（Silu 写的 lexer + 递归下降 parser +
JSON 发射器，~900 行）编译后把**全部 selfhost 程序（含它自己）**解析成
与 `silu ir --format json` **完全一致**的 IR；M4 → M2（ir_interp.si）与
M4 → M3（ir2c.si）→ C → clang 两条端到端链路与 CPython 对拍通过。
自举闭环达成：silu_fe 能解析自己的源码。

测试：`tests/test_selfhost_m4.py`（23 项：IR 对拍 4 + 小输入 1 + M2/M3
端到端 10 + 语言面 6 + 退出码 2）。

## 本轮修复的编译器根因（都由 silu_fe 自举暴露）

1. **`x is True` 被编译成 truthy(x)**：`"s" is True` 恒真。修为
   bool 单例检查（OBJ: tag==3 且 payload 匹配；I1: 直接比较；其他
   representation 恒 False）。对称分支的原判断
   `isinstance(node[1], bool)` 对 list 恒假，是死代码，一并修正。
2. **未知函数/方法静默返回 null**：`isinstance`、`enumerate`、
   `SystemExit` 不存在时无声变 null，流入容器后在远处崩溃（ASan 栈
   指向 `list_length+0x0`，实参是 `null` 常量）。改为编译期
   NotImplementedError。**教训：静默 null 是最贵的错误模式。**
3. **`raise SystemExit` 语句被完全忽略**（无 `raise` 分支）：calc 的
   lexer 错误路径 raise 被吞 → `pos` 不前进 → 死循环（M1 测试超时、
   全量 pytest 61% 被 SIGKILL 的根因）。实现 `raise SystemExit(code)`
   → exit(code)；AST 解释器补 visit_Raise（原来被 generic_visit 吞）。
4. **裸 OBJ 上的 `isdigit/isalpha/isspace` 不存在**：`ch = self.peek()`
   未注解 → ch 装箱 → 谓词方法静默 null → `if null` 折成 false →
   数字 token 全部落入 OP 分支（kind=3 而非 1，即 docs 旧版记录的
   "enum kind bug"——与 enum 无关）。pyobj 运行时补三个谓词函数
   （ASCII 近似，空串 False）。
5. **`for ch in "abc"` 装箱后走 list 路径**：字面量装箱成 OBJ →
   `list_length(str_obj)` 读错布局 → -O2 崩。字面量迭代特判物化为
   rawstr 走码点循环。
6. 新语言面：`isinstance(x, T/(T1,T2))`（静态 kind 编译期答、装箱
   查 tag；bool⊂int，tuple≡list）；`for i, x in enumerate(seq)` 脱糖
   为隐藏计数器循环；`int(s, base)`（strtol）；`-> None` 注解；
   两解释器补 `tuple`/`list`/`dict`/`enumerate`/`input`/`SystemExit`
   名字与 `_execute_raise`。

## silu_fe 前端本身的修复（对拍逐项暴露）

- `accept/expect` 及一元/二元运算循环必须查 token **kind**——
  STR("+") 的 text 也是 "+"，裸 text 匹配会吞字符串字面量
- 括号深度跟踪：括号内换行是空白（Python 隐式续行）
- elif 链：每个臂只认领**同缩进**的 elif/else（内层 if 抢外层 else）
- 表达式语句不包 `expr_stmt`，直接返回表达式节点；and/or 折叠 n-ary
- `while` 三元组（无 orelse）；tuple_assign 目标为裸字符串列表
- 裸注解语句 `x: int`；十六进制/二进制/八进制字面量；`import`
  生成 IR 节点；列表推导 `[elt for t in iter if cond]`（iter/cond
  解析到 or 层，低于条件表达式）；三元表达式 `a if c else b`

## 调试经验（保留）

1. **printf 在管道下是全缓冲**：崩溃时缓冲丢失。用
   `script -q /dev/null cmd` 包 tty，或退出码做探针。
2. **ASan 是第一工具**；但注意 `silu llvm` 子命令走旧转换器
   （silu_ir_to_llvm），typed 后端要用
   `TypedCodegen().convert(json.dumps(SiluIRGenerator().visit(tree)))`
   生成再 ASan。
3. **`x.missing().field` 属性链包裹时缺失方法不报错**（attribute
   分支吞掉调用）——已知缺口，TODO。
4. 编译器 bug 的"最小复现"必须人工核验源码。

## 已知限制（后续里程碑）

- Python `exec`（IRInterpreter）对 class 程序支持不全
  （`src[pos].isdigit()` 属性链在参考路径同样失败）——M2/M3 的
  Silu 子集解释器是文档化的下游，不是它
- pyobj 谓词是 ASCII 近似；`1_000` 下划线数字 literal 进 NUM 但
  `int()` 不接受
- 装箱值（运行时 str）的 `for x in s` 仍走 list 假定路径（字面量
  已修，变量场景待 pyobj 迭代协议）
