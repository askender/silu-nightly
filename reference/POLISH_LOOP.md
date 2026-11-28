# Silu 打磨循环手册（Polish Loop Playbook）

本文档是"语言打磨循环"的操作手册：夜间/闲时定时唤醒的代理（或人类
协作者）按此执行，无需重新推导规则。第一入口仍是
`reference/STATUS.md`（当前状态 + §四 TODO）与 `AGENTS.md`（硬约束 +
环境关键）；本文只回答"一轮怎么跑"。

## 0. 循环的由来（2026-11-27 用户授权）

> 按优先级依次修复 bug，从根源规避；写真实 Python 程序对拍以发现新
> bug/语法差异；可通宵运行，列出清晰计划并执行，除非用户打断；定时
> 器持续驱动；不引入新特性，注重代码整洁，从根源消除 bug。

定时器：ZCode automation `automation-a488e76d-c8bf-4ca3-8162-37839f217b7d`
（每 60 分钟，cron 表达式 `* * * * *` + interval 60）。用户随时可打断；
全部完成后循环优雅停机。

## 1. 唤醒后的判定树（每轮第一分钟）

1. `git status` + `git log -1 --format=%cr` + `gh run list`（CI 状态）。
2. **工作树脏** → 先 `tools/gates.sh --no-pytest` 收口；绿则把在途工作
   提交推送（见 §3 提交纪律）；红则先修。
3. **距最新提交 < 30 分钟** → 轻量轮：跳过重活，只做只读检查
   （git/CI 状态、可选重跑电池 `python3 /tmp/silu_night/battery.py`），
   然后优雅结束本轮。
4. **距最新提交 ≥ 30 分钟** → 重活轮：按 STATUS §四 首条的优先级开工
   （见 §2 轮次结构）。

## 2. 重活轮的结构（每轮一个主题）

1. **选题**：STATUS §四 首条的最靠前未完成项。不引入新特性——遇到
   未支持构造，响亮拒绝即是合规（硬约束 3）。
2. **差分先行**（硬约束 5）：改转换器/前端前先
   `./siluc1 < X.si > /tmp/ref.ll` 留参考；行为论断必须有 diff hunk 或
   探针输出背书，不靠读源码猜。
3. **探针先行**：写最小 `.si` 探针，五平面对拍
   （CPython / `silu interpret` / `siluc` / `silu build` / `siluc1`→clang；
   ir2c 行为也要看）。真 CPython 是唯一期望值来源（手写参照已被坑三次）。
4. **修复从根源**：改运行时 → Python 平面 + `selfhost/` 孪生 + rs +
   ir2c 四侧同步；**新运行时函数必须 `tools/regen_rust_prefix.py` 重生成
   前缀并 `cargo build`**（rs 经 include_str 内嵌前缀）。
5. **钉板**：稳定修复后，探针进 `tests/test_semantics_vs_cpython.py`
   （期望值真 CPython 现场生成），多字节/边界形状同时给 ASan 门禁
   当靶子。
6. **门禁**：`tools/gates.sh --no-pytest` 全绿（ir 33/33 ×2、ll 32/32
   ×2、前缀最新、ruff）+ 全量 `pytest tests/ -q`（约 15 分钟，后台跑）。
   **注意**：平面门禁必须整套跑——只跑"受影响子集"曾放过 f-string
   回归（6444a95 教训）。
7. **提交推送**（§3）+ STATUS/AGENTS 进展回写 + 必要时重钉版本。
8. 本轮结束，等下次唤醒。

## 3. 提交纪律（硬约束 1/2/4 的展开）

- 只推 `nightly` 远端的 `main`；**绝不推 askender/silu（origin）与
  silu-lang**。
- 每个 byte-identical / 全绿里程碑**立即**提交推送（历史上发生过
  checkout 回退丢工作树的事故）。
- **显式 `git add <文件列表>`**——`git add -A` 曾把两个 Mach-O 临时
  二进制带进历史（1de7407 之后的教训）。
- 输出语义变化 → 重钉版本：AGENTS.md 钉版行 + reference/README.md
  pinned version + CHANGELOG.md 新条目。
- 提交信息：第一行 = 根因 + 后果；正文 = 根源机制、四侧同步点、
  门禁数字。失败/弯路如实写（STATUS 是交接锚点，不是宣传稿）。
- 不擅自打 tag（触发 release 工流）；CI 手动 dispatch
  （`gh workflow run ci.yml -f gates=true -R askender/silu-nightly`）
  只在完成一个大轮次时做一次。

## 4. 本轮已验证的坑（新会话必读，血泪浓缩）

1. **陈旧二进制幻影**：`siluc1`/`silu_conv`/`silu_fe` 是构建产物，
   改源后必须 `rm -f` 再 ensure（selfhost_build 的 mtime 判断会被
   多版本 flat 干扰）；"同一现象两次测量不同"先怀疑二进制身份，
   `silu build` 产物**逐字节不可复现**（5 次构建 5 个 md5，行为一致
   ——md5 不能证明"同一二进制"）。
2. **自举消费者**：给"编译器编译自己"的表示层改常量时（如 tuple
   tag），必须全库 grep 全部消费者——`_ISINSTANCE_TAGS["tuple"]` 漏改
   使孪生自己的 `isinstance(result, tuple)` 恒假，语句级 free 静默
   失效，ll 门禁以 conv-vs-pyll 分歧的形式红。
3. **IR 形状判断**：assign 的纯名字目标是字符串 JValue、属性目标是
   列表节点；对字符串调 `tag()` = 段错误（arr[0] 下标 None）——用
   `.kind == JKind.STR`。
4. **扁平孪生的语法子集**：无闭包捕获（嵌套函数改方法传参）、无
   `setattr`（dict 收集后显式赋值）、无反斜杠续行（括号内续行）、
   alloca 必须在 entry 块（循环块内 alloca = 每次迭代重置 + 死循环）。
5. **C 字符串列表顺序敏感**（ir2c）：helper 被后面的函数调用时必须
   先声明；顺序错了 = clang 拒绝（响亮但红门禁，m5 曾 50 红）。
6. **rawstr_append 是 void**：原地改缓冲，无返回值；链式 append 用
   同一 acc 多次调用。
7. **ASan 门禁是活的**：新钉板当天抓获过越界（find start=9 于
   8-cp 串）——新运行时函数的边界契约必须写进注释并让门禁验证。
8. **crash 报告目录**：`~/Library/Logs/DiagnosticReports/*-*.ips` 是
   "瞬态失败"的证伪证据；`siluc1` 段错误先看这里，别重跑放行。
9. **期望值唯一来源是真 CPython**：手写/记忆的期望值三次被证伪
   （sorted(key=)、m4 isinstance、先删后插的 CPython 行为）。
10. **battery 电池**：`/tmp/silu_night/battery.py`（五平面，含
    pybuild；`regression` 参数只跑回归探针）。/tmp 会被清——电池脚本
    的最新副本随轮次归档在 STATUS 提及的路径；若丢失，按
    tests/test_semantics_vs_cpython.py 的钉板重建即可。

## 5. 当前轮次状态速查（compact 后从这里续）

- **repr 轮（2026-11-28 凌晨，进行中——本 commit 落盘时的状态）**：
  `repr(x)` 值形式已实现 pybuild + siluc1（`pyobj_repr_value` 运行时：
  码点引号选择 pyobj_repr_dquote、转义写入器 rawstr_repr_escape、
  递归写入器 pyobj_repr_append；str 单引号/含 ' 无 " 时双引号、
  \\n\\r\\t\\\\ 与 C0/DEL 的 \\xXX、容器递归、tuple 尾逗号在括号内）+
  **rs 双分派臂已加**（pyobj_repr_value 调用，探针 'a' / [1, 'a'] /
  (2,) 全对）。**余项**：①ir2c 的 repr 目前生成坏 C（clang 拒绝，
  响亮合规）——按 typed str 接收者实现或显式 ValueError；②
  `len(repr(x))` 组合在 rs 响亮 bail（len 只按静态形状分派）——字母
  表缺口，非 bug；③钉板 repr_value 探针进语义门禁；④全量 pytest。
- 探针文件：`/tmp/reprtest.si`（八行 repr 矩阵）、`/tmp/repempty.si`
  （replace 空针）、`/tmp/findargs.si` + `/tmp/findmb.si`（find 参数）。
- 上一轮已完成：find/startswith 的 start/end（237bf0b）、replace
  空针（bafe227）、tuple tag-9（2a65c62，1.25.1 重钉）等，见 git log
  与 STATUS §3.38 续二/续三。

## 6. 完成判定（循环停机条件）

STATUS §四 首条全部 ✅、电池无新 findings、钉板面覆盖本轮全部修复
→ 更新 STATUS（"打磨循环完成于 <commit>"）→ 提交推送 → 停机等用户。
用户随时打断优先于一切。
