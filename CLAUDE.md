# CLAUDE.md

**代理上下文以 [AGENTS.md](AGENTS.md) 为准**——本文件已过时
（描述的是早期纯解释器形态），仅作指向保留。

需要了解的要点（详见 AGENTS.md）：

- Silu 是 Python 语法子集的**自举编译型语言**：`.si → silu_fe（前端）→
  IR JSON → typed_codegen（转换器）→ .ll → clang`，另有参考解释器与
  Z3 符号执行/证明。
- `reference/rust/` 是第二实现（差分 Oracle，钉住 1.16.2/87df40f），
  已达成全语料逐字节一致（前端 IR 19/19、完整 .ll 18/18）。
- 状态锚点与隐式规约清单：`reference/PROGRESS.md`；校准报告：
  `reference/CALIBRATION.md`；改进提案（待用户决策，勿擅自实施）：
  `reference/PROPOSALS.md`。
- Git 纪律：源码提交/标签只推 `nightly` main；`silu-lang` 公开仓不
  merge；旧 `origin` 暂停不推不删。
- 差分命令（仓库根执行）：
  `python3 reference/diff_harness.py ir fe rustfe` 与
  `python3 reference/diff_harness.py ll conv rustconv`。
