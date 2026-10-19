# 自举收尾 TODO 与计划（v0.15.0 → v0.16.0，2026-10-19）

> compact 后的单一入口。当前状态：**原生自举闭环已通**（fib
> 字节一致），16 程序原生门禁 **9/16**；全部语义差异的根源框架
> 见 `selfhost_semantic_divergence.md`（六根源 + 盲区分析 +
> 求同原则）。本文件只管"接下来做什么、按什么顺序"。

## P0：16 程序原生门禁收尾（7 个待过）

按"一个家族解锁多个程序"的收益排序：

1. **object 字段丢实例 cid**（spectral / calc / ir_interp）
   - 症状：`AttributeError: no field 'element'`，flat:988
     （`_load_dict_parts` → gep → `.type.element` 链）
   - 归因：根源六——注解为 `object` 的字段读回时未按值域盖章
     （instance-kind 盖章目前只在已知类标注处生效）
   - 思路：`_emit_dyn_attr_read` 对 object 字段按 tag-6 运行时
     盖章（读出裸实例指针时包 cid 边车），或写入侧统一存盒
2. **pyobj_contains 列表扫描崩**（jsonparse / knucleotide，+284）
   - 归因候选：根源三（null 元素）或根源六（异类元素比较）
   - 已有工具：nullcheck 哈尼斯一步定位
3. **wordcount：247 行块序差异**
   - 症状：`str_view.N` 的 alloca 摆放、块顺序不同——非崩溃，
     纯输出分叉；对比 diff 找第一个分叉点反推发射顺序差异
4. **nbody：rc=0 但 stdout 为空**
   - 先查：print 缓冲/exit 路径（printf 到管道全缓冲的教训）、
     read_stdin 是否提前返回
5. **门禁固化**：全过后写成
     `test_si_converter_native_parity`（原生执行 vs Python 执行
     .ll 字节对拍，16 程序参数化）——第一层跨对象模型门禁，
     堵住"四层门禁全在 Python 对象模型里"的盲区

## P1：正确性收尾

6. **O2 误编译**：O0 全绿、O2 崩、ASan(O1) 无堆损坏报告
   - 路线：对 flat .ll 做 `-O1/-O2` 差分 + 按函数关优化定位
     （`opt -O2 -print-after-all` 或逐 attribute）；嫌疑是生成
     IR 里某处 UB 约定（gep/load 指针类型）；拿到最小 .ll 复现
     后再判断是自身 UB 还是 clang bug
7. **混合 ABI funcref 分发**（根源四通用修复）
   - `pyobj_fn_callN` 分发臂按目标 `_dyn_func_kinds` 逐参
     装换（对照直呼路径 11471-11488 的 coercе 逻辑）
   - 补 funcref 表的专项测试（表恒空时 27 项全绿——测试盲区）
8. **pyobj_\* 静默 null 系统化改 panic**（根源三收尾）
   - "Error case - return null for now" 全量清单化；改完 .ll
     会变（两侧一致），全部门禁重跑

## P2：语言覆盖缺口（公共子集约束的反向清单）

9. **超大整数字面量**：>i64::MAX 的十进制/hex（现状：源码改
   带符号等价写法绕过）；可选 u64 位型视图或字面量按位解释
10. **真 bytes 类型**：与 str 分离（独立 tag 或显式 latin1
    标记贯穿运行时，而非仅 Constant.latin1）
11. （按需）真实集合语义：当前 set 按列表盒承载，仅支持
    成员测试/迭代

## P3：性能与工程

12. **测试提速**（现状全量 ~9.5 分钟）：
    - 三个 ~85s 解释器门禁（跑 16 程序 × flat 转换器）加缓存
      或并行；ir2c build 测试合并 clang 调用（每次 ~5.5s）
13. **ir2c.si 结构收敛**（funcref/boxing 补丁收进类型层）
14. **typed_codegen.py 拆分重构**（老 P1，不变量：全部 .ll
    字节不变）

## 工作流（每个缺陷的标准循环）

探针先行 → 用六根源框架归因（机械判定：Python 下不可达=语义差；
两平面都该工作=新 bug；Python 靠对象模型天然正确=被掩盖缺陷）→
修复（**原生语义向 Python 对齐优先**；bigint/真类型承载处才用
公共子集约束）→ 门禁（llvmlite_text 27 项 + class/cli/typed
子集 + 全量 pytest）→ twin 字节锁 → 文档一笔 → 提交。

诊断工具箱（按可靠性）：crash report 符号栈（注意
`usedImages[0].base` 重算偏移；lldb 会挂起时首选）→ C 信号旁路
（`/tmp/silu_signal_diag.c`：sigaltstack + `__silu_line` +
backtrace；`.ll` 里把 internal 的 `__silu_line` 改 external 才能
链接）→ raise 式诊断（exit 会 flush；printf 到管道不行）→
**O 级别二分**（先排除堆损坏再追"非确定性"）。

陷阱提醒：/tmp 探针前必须 `cp selfhost/llvmlite.si /tmp/llvmlite.si`；
twin 相对行号（≤1057 是 llvmlite.si 的行）；flat 文件被
.gitignore（产物，重新生成即可）。

## 状态快照（打此文档时）

- tag **v0.15.0**（8370385）；门禁 9/16；全量 1069 passed；
  llvmlite_text 27/27；twin 锁定
- 近三个提交：ecffc28（fib 闭环 + 13 修复）→ 2f8b5b4（9/16 +
  4 修复）→ 8370385（根源文档）
