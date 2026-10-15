# M4 前端自举：进行中状态与经验（2026-10-15）

状态：**实现完成 ~95%，调试收尾中**。本文档供压缩上下文后无缝继续。

## 1. 已完成

- 设计文档 `docs/m4_frontend.md`（节点白名单 43 种、缩进算法、IR 发射约定）
- 实现 `selfhost/silu_fe.si`（~830 行）：lexer + 缩进块 + 递归下降 + JSON 输出
- 已通过 `silu build` 编译，**解析逻辑已验证正确**（静态输入下 parse_module
  产出正确 IR 树，如 `['module', [['expr_stmt', ['name', 'x']]]]`）

## 2. 当前卡点（下一个要修的 bug）

**symptom**：`echo '1' | ./silu_fe` —— lexer 把数字 `1` 分词为 kind=3(OP)，
应为 1(NUM)。名字 token（`x`）正常。

**已排除**：
- `ch.isdigit()` 对 "1" 返回 True（单测通过）
- 枚举 TokKind 定义顺序正确（NAME=0, NUM=1, STR=2, OP=3, KW=4, NL=5, END=6）
- tokenize 静态输入下：`"1\n"` → kinds [3, 5, 6] —— 第一个 token 就错了
- `next_token` 源码逻辑正确（人工核对）
- `Lexer("1",0,1,0)` + `next_token()` 的隔离复现稳定

**关键线索**：`print(TokKind.NUM, TokKind.OP)` 输出 `true true`——
**`print` 一个 enum 成员（i64 常量）输出了 `true`**！说明 enum 常量在
`print` 的装箱路径被当成 I1（bool）。**强怀疑：enum 成员常量折叠的 kind
标记错误**（`_register_enum` 或 `_convert_node` 的 attribute 折叠返回了
I1 而非 I64），或者 `Token(TokKind.NUM, ...)` 构造时 kind 字段（注解
`kind: TokKind` → I64 槽）被写入了错误值。

**下一个动作**：
1. `python3 -c` 里直接检查 `_register_enum` 后 `_enums['TokKind']` 的值表
2. 检查 `t.kind == TokKind.NUM`（I64==I64）与构造 store 的 IR
3. 若 enum 折叠有 bug，修复后跑 `selfhost` 全部程序的端到端

## 3. 本轮已修的编译器根因（都已提交或待提交）

- **`is`/`is not` 分支颠倒**（本轮修，未提交）：`x is None` 走
  `is_null(right)`（拿 None 字面量自比，恒真）——应为 `is_null(left)`。
  这是 M4 调试中 ASan+trace 双重定位的。**提交信息要点**：比较
  None 字面量与自身恒真，导致所有 `is None` 判断失效。
- 早前已提交：float/int 的 rawstr_free 误用（e3e7f4c）、
  rawstr_eq_cstr 不短路越界读 + 分支局部 RAWSTR 槽未初始化 + print(end=)
  忽略（53bd7dc）、`_call_ret_class`/`_field_elem_class`/INSTANCE 链
  （dff466a 起）。

## 4. 调试经验（写下来避免重复踩坑）

1. **printf 在管道下是全缓冲**：崩溃时缓冲丢失，"print 探针没输出"
   会误导定位（以为崩在更早）。对策：用 `script -q /dev/null cmd`
   包一层 tty，或用退出码/返回值做探针。
2. **ASan 是第一工具**：所有"随机崩/加 print 就好"最终都是内存错误。
   `clang -O0 -fsanitize=address` + 符号化帧可直接指出函数。
3. **alwaysinline 让 ASan 帧名不可靠**（帧归因到调用者）；临时注释
   `func.attributes.add("alwaysinline")` 可获得准确帧。
4. **编译器 bug 的"最小复现"必须人工核验源码**：字符串 replace 生成
   测试变体曾把 arm 重复插入，导致两轮错误结论。
5. **动态（装箱）body 的 `self.method()`/字段链** 需要
   `_class_of_node` 全链支持（name → attribute → subscript → call），
   已逐环补齐。
6. **`-> object` 返回注解 = dynamic body**，dynamic body 里 instance
   字段访问已可用（self 保持 raw INSTANCE 槽）。

## 5. M4 剩余工作（修完 §2 后）

1. 对拍：`selfhost/*.si` 全部程序的 M4 输出 vs `silu ir --format json`
   逐字节一致（当前 parse 已验证对 `x`/表达式正确，未跑全量）
2. 端到端：M4 产出 IR → M2 解释 / M3 编译，与 CPython 对拍
3. 自举自洽：silu_fe.si 自身能被 M4 解析（它就是 Silu 程序）
4. 测试 `tests/test_selfhost_m4.py` + 全量 pytest + 提交
5. 未提交的变更：`silu/typed_codegen.py`（is 颠倒修复 + list-of-instance
   字面量 + unannotated instance assign + enum ret_kind 缺省）与
   `docs/m4_frontend.md`、`selfhost/silu_fe.si`——**修完 §2 一并提交**
