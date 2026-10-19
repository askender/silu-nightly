# 自举收尾 TODO 与计划（v0.15.0 → v0.16.0，2026-10-19）

> compact 后的单一入口。当前状态：**16/16 原生门禁全通**（2026-10-19
> 傍晚，见 `progress_2026_10_16.md` 末节）——原生自举转换器对全部
> 16 个基准程序产出与 Python 转换器逐字节一致的 .ll。语义差异根源
> 框架见 `selfhost_semantic_divergence.md`（六根源 + 盲区分析 +
> 求同原则）。本文件只管"接下来做什么、按什么顺序"。

## P0：16 程序原生门禁收尾 —— ✅ 已完成

全部 7 个程序的归因与修复（细节见 progress 末节 18-21）：

1. ~~object 字段丢实例 cid~~（spectral/calc/ir_interp）——真凶是
   **list_insert 不写 capacity** 的堆越界写（布局敏感，ASan 测不出）
2. ~~pyobj_contains 列表扫描崩~~（jsonparse/knucleotide）——
   pyobj_eq 异型 tag 返 null + dict.keys() 错路由到 items
3. ~~wordcount 块序差异~~——同 2 的 eq 级联
4. ~~nbody 空输出~~——同 2/3
5. ~~门禁固化~~——`tests/test_si_converter_native_parity.py`（16 程序
   参数化字节对拍，模块级一次构建转换器）

## P1：正确性收尾（当前优先）

6. ~~**O2 误编译**~~ —— ✅ 已解决（2026-10-19 傍晚）：所谓 O2 误编译
   实为 list_insert 的堆越界写（O0/O2 只是布局不同）。原生门禁
   16/16 在 O2 下同样字节一致；`silu build`（默认 -O2）产出的
   转换器现已可靠。门禁测试已切到 -O2 锁定该性质。
7. **混合 ABI funcref 分发**（根源四通用修复）
   - `pyobj_fn_callN` 分发臂按目标 `_dyn_func_kinds` 逐参
     装换（对照直呼路径 11471-11488 的 coercе 逻辑）
   - 补 funcref 表的专项测试（表恒空时 27 项全绿——测试盲区）
8. **pyobj_\* 静默 null 系统化改 panic**（根源三收尾）
   - "Error case - return null for now" 全量清单化；改完 .ll
     会变（两侧一致），全部门禁重跑
   - 本轮已做一部分：pyobj_eq 异型 tag 不再返 null（==/!= 返
     False/True）；剩余的是排序（< 等）与算术错误路径
9. **enumerate 反糖的回归测试**：`continue`/`break` 在枚举循环体里
   的计数器语义（本轮修复的的直接回归锁；现在只有门禁间接覆盖）

## P2：语言覆盖缺口（公共子集约束的反向清单）

10. **超大整数字面量**：>i64::MAX 的十进制/hex（现状：源码改
    带符号等价写法绕过）；可选 u64 位型视图或字面量按位解释
11. **真 bytes 类型**：与 str 分离（独立 tag 或显式 latin1
    标记贯穿运行时，而非仅 Constant.latin1）
12. （按需）真实集合语义：当前 set 按列表盒承载，仅支持
    成员测试/迭代

## P3：性能与工程

13. **测试提速**（现状全量 ~10 分钟 + 原生门禁 ~4 分钟）：
    - 三个 ~85s 解释器门禁（跑 16 程序 × flat 转换器）加缓存
      或并行；ir2c build 测试合并 clang 调用（每次 ~5.5s）
    - 原生门禁的转换器构建（~3min）可考虑缓存到 .pytest_cache
      （按源文件哈希失效）
14. **ir2c.si 结构收敛**（funcref/boxing 补丁收进类型层）
15. **typed_codegen.py 拆分重构**（老 P1，不变量：全部 .ll
    字节不变）

## 工作流（每个缺陷的标准循环）

探针先行 → 用六根源框架归因（机械判定：Python 下不可达=语义差；
两平面都该工作=新 bug；Python 靠对象模型天然正确=被掩盖缺陷）→
修复（**原生语义向 Python 对齐优先**；bigint/真类型承载处才用
公共子集约束）→ 门禁（llvmlite_text 27 项 + class/cli/typed
子集 + 全量 pytest + 原生门禁）→ twin 字节锁 → 文档一笔 → 提交。

诊断工具箱（按可靠性）：
1. **panic/raise 原生回溯**：silu_panic 里 backtrace +
   backtrace_symbols_fd 到 stderr（或 exit_func 包一层，非零退出
   才打，可抓 raise 路径）。注意 twin 的 alloca 不接受裸 int size
   （operands 渲染崩），缓冲用 malloc+bitcast。
2. **崩溃偏移反汇编定位**：回溯拿到 `fn + 偏移` → `nm` 拿基址 →
   `otool -tv` 在该偏移前找 `bl 目标` = 调用点。
3. **错盒画像**：panic 路径打印 cid（pyobj_instance_cid）+ 实例
   槽位内容（opname/name 字段）→ 对照参考 .ll 锁定是哪条指令。
4. **两平面转储对比**：`_inferred_sigs` / `_class_layouts` 两侧
   各打印再 diff——排除"推断分歧"假设比审计快。
5. **布局敏感判定**：加打印/ASan/换 O 级别任一改变布局——崩溃
   漂移即堆数据依赖；**ASan 全绿不排除 bug**（合法地址的错值
   ASan 测不出）。MallocScribble/MallocPreScribble 变化可坐实。
6. crash report 符号栈（注意 `usedImages[0].base` 重算偏移；
   lldb 会挂起时首选）→ C 信号旁路（`/tmp/silu_signal_diag.c`：
   sigaltstack + `__silu_line` + backtrace；`.ll` 里把 internal
   的 `__silu_line` 改 external 才能链接）→ raise 式诊断（exit
   会 flush；printf 到管道不行）→ O 级别二分。

陷阱提醒：/tmp 探针前必须 `cp selfhost/llvmlite.si /tmp/llvmlite.si`；
twin 相对行号（≤1057 是 llvmlite.si 的行）；flat 文件被
.gitignore（产物，用 tools/flatten_codegen.py --si 重新生成）；
**改动 silu_ir_to_llvm.py / typed_codegen.py 会同时影响两个平面**
（Python 转换器与 flat .si 同源），门禁的 ref.ll 每次重新生成，
不存在陈旧参考的问题。

## 状态快照（16/16 时）

- 基准：tag v0.15.0（0b9dc99）时是 9/16
- 本段修复：list_insert capacity / pyobj_eq 列表相等+异型 False /
  dict keys-values 路由 / enumerate 计数器位置 / 运行时创建顺序
- 门禁：16/16 原生字节一致；llvmlite_text 27/27；全量 pytest 见提交
- 新门禁：tests/test_si_converter_native_parity.py（跨对象模型）
