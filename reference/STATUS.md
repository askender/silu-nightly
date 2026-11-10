# 会话状态与 TODO（2026-11-10 凌晨，交接锚点）

> 交接快照：当前状态、未决事项、调查现场、关键教训。
> 规约细节锚点仍是 `reference/PROGRESS.md`；本文负责"接下来做什么"。

## 一、已提交状态

**HEAD = `bced6d9`（v1.18.1，tag 已推 nightly）**，内容：
- cp-offset 双层缓存（rawstr 结构指针键 + pystr 数据指针键）
- 动态层 str 码点语义（len/下标/切片 CPython 对齐）
- 分号拒绝化（三前端对齐）+ 4 测试
- 孪生渲染器 _rstrip/_escape_latin1 线性化（m8 355s 回归修复）
- 前缀重钉×2、CHANGELOG/pyproject/README/PROGRESS/AGENTS 版本四件套
- 提交时门禁：ll 19/19、conv/pyll 19/19、ir 20/20、pytest 1359 通过/2 跳过

## 二、本轮内容（utf8 语料钉板 + 孪生热点扫尾，**已整体提交**）

主题：**非 ASCII 语料钉板 + 孪生热点扫尾**。改动清单：

| 文件 | 内容 | 状态 |
|---|---|---|
| `selfhost/utf8_probe.si`（新） | 非 ASCII 语义探针，双平面字节一致，已入 CORPUS_IR | ✅ |
| `reference/diff_harness.py` | corpus += utf8_probe（ir 21/21、ll 20/20×2 实测绿） | ✅ |
| `reference/rust/src/bin/silu-conv.rs` | ① 15 处 chars().count()→.len()（字节数组定尺寸按字节）② typed str 步进切片臂（原先**静默丢步进参数=输出错误字节**，违反铁律）③ len(切片表达式) 非 name 兜底 | ✅ 门禁绿 |
| `silu/llvmlite_text.py` + `selfhost/llvmlite.si` | 新增 utf8_byte_len（含 bytes/bytearray 快分支，与 utf8_len 对齐）；_escape_str/_escape_bytes 改 append+join | ✅ |
| `tools/flatten_codegen.py` | 改写表 3 行：len(…encode)→utf8_byte_len；string_bytes ArrayType 同 | ⚠️ 见三 |
| `tools/siluc_main.c` | rt.o↔rt.ll mtime 配对校验；rt.clang 身份戳（conda LLVM21 vs Apple ld17 LTO 位码不兼容）；run_quiet 失败输出 stderr | ✅ 实测修复链接失败 |
| `tests/test_selfhost_m4.py`（另行提交 bdd39fc） | Linux gates 链接 benchmark 生成 C 补 `-lm`（schedule 层首跑暴露的潜伏缺陷，nbody 的 pow）；Linux gates dispatch 全绿验证 | ✅ |
| `.gitignore`（另行提交） | 加 `.zcode/`（代理会话目录）与 `test.txt`（scratch，内容仅 "test"） | ✅ |
| `tests/test_utf8_runtime.py`（新） | 动态码点九项对 CPython / free-reuse 陷阱 / 50K 线性走查 | ✅ 3/3 |
| `silu/cli.py` | SILU_TB=1 可选 traceback（调试钩子，可保留） | ✅ |
| `AGENTS.md` / `reference/PROGRESS.md` | 本轮记录 | ✅ |

**门禁现状（未提交态）**：ll conv rustconv **20/20** ✅；ll conv pyll **20/20** ✅；
ir fe rustfe **21/21** ✅；性能 m8 0.47s ✅；
pytest **1 failed**（见下）, 1360 passed, 3 skipped。

## 三、已解决：解释器 parity 真回归（本轮修复）

`tests/test_llvmlite_text.py::test_si_converter_interpreter_parity`
曾**真失败**（standalone 可复现，此前两次被误判为竞态）：
`silu interpret <临时目录的 flat+孪生+wrapper>`，喂 jsonparse.si 的 IR JSON，
报 `Runtime Error: ord() expected string of length 1, but int found`。

**✅ 已修复（2026-11-10）**：头号嫌疑坐实——双孪生 `utf8_byte_len`
缺 bytes/bytearray 快分支（`utf8_len` 有）；改写表把 `bytearray(b'…')`
重写成裸 bytes 后，`ArrayType(…, utf8_byte_len(string_bytes))` 以 bytes
调用 → 迭代 bytes 得 int → `ord(int)` 崩。修法：双孪生各补
`if isinstance(s,(bytes,bytearray)): return len(s)`。
验证：定向 28 全绿 → ll conv rustconv 20/20 → ir fe rustfe 21/21 →
全量 pytest 绿 → 整体提交。

**调查现场（历史记录）**：
- 直接 `interpret selfhost/silu_conv_main.si < benchmarks/jsonparse.si`（喂**源码**）**正常出 .ll** —— 孪生/flat 大体没坏；
- 该测试每次现场重新生成 flat（flatten --si）并拷贝当前 llvmlite.si；
- v1.18.1 时此测试绿；本轮改动后开始红。本轮涉解释器平面的改动只有
  改写表 3 行 + 孪生 utf8_byte_len/_escape_* 重写。

**验证次序**（已照此执行完毕）：
1. `$PY312 -m pytest tests/test_llvmlite_text.py -q`（28 全绿）
2. `$PY312 reference/diff_harness.py ll conv rustconv`（20/20）
3. `$PY312 -m pytest tests/ -q` 全量
4. 全绿后**整体提交**（含 utf8_probe/驱动器/测试/文档），消息主题
   "utf8 corpus probe + byte-domain fixes + driver cache hardening"

## 四、其余 TODO（优先级序）

1. **发布 v1.18.1 到公开仓——根因已找到（11-10 用户在 UI 上看到报错）**：
   `The configuration 'macos-14-arm64-us-default' is not supported`
   ——**GitHub 平台侧退役/不支持该 runner 池**。此前 7 次"确定性秒杀"
   全部由此解释：release.yml 是唯一用 `macos-14` 的 workflow（gates
   runs-on: macos-14；binaries 第一档也是 macos-14），job 落到该池即被
   平台拒绝取消，无 runner 日志、无取消署名；与账号 App/自动化/代理
   均无关（此前的账号级排查方向可关闭）。
   - **修法（下次会话第一件事）**：release.yml 两处 `macos-14` →
     `macos-15`（gates 的 runs-on + binaries macos-arm64 档的 os）；
     macos-15-intel（Intel 档）不动。改完跑一遍重推 tag 验证（gates
     ~1h + 4 平台 binaries）。
   - 全绿后：`sh tools/promote_release.sh v1.18.1 <run-id>` → 公开
     release。**注意**：promote 脚本校验 run 必须
     `release completed success v1.18.1`（headBranch=tag），勿用
     workflow_dispatch 绕过。
   - 前置已备齐：源 tag 链完整、主仓 CHANGELOG 四件套齐、silu-lang
     README 全占位符、CHANGELOG 三版条目已补推（silu-lang 30d1de7）。
2. pytest 全量其余偶发单失败（m4/driver/pipeline 簇）：**本轮调查未复现**
   ——串行 ×1 + xdist -n4（缓存态）×1 + 强制 touch 源造并发重建 ×1，
   74 测试全绿（2026-11-10）。代码审查确认竞态面存在：tools/selfhost_build.py
   的 ensure_* 无锁，CONV_FLAT/FE_BIN/CONV_BIN/siluc1/siluc 均在最终路径
   非原子直写（对照 silu/runtime_cache.py:97 有 os.replace 原子写），
   并发重建时读方可撕读。**修复设计已备**：flock 串行化 ensure_* +
   构建到临时路径 os.replace 落位；**无复现证据不动构建工具链**（release
   链正用），等真复现（CI 慢机器窗口更宽）再实施。另注意教训 5：本簇
   历史偶发可能是 parity 真回归的误判，已被 02b53a3/bdd39fc 顺手消灭。
3. g-清单 #10：未注解局部从 chr()/concat 初始化的推断分歧（Python 保持
   pyobj vs Oracle 推 str；`object` 注解 Oracle 空 bail）→ utf8_probe 因此
   无动态段；动态语义由 tests/test_utf8_runtime.py 执行级守护。深水区，
   等需要时再做。
4. g-清单其余（PROGRESS.md"Oracle 未钉形状清单"）：等语料压力（T3）。
5. P7（Rust 独立编译器）：T1/T2/T3 未触发（reference/P7_RUST_STANDALONE.md）。
6. 小项：pyobj_utf8_cp_offset 死函数（**纯 Python 运行时独有**，孪生
   llvmlite.si 与 Rust 参照均无此函数；删除后 .ll 变化需重钉一轮门禁
   ——下次动前缀时顺手）。docs/ UTF-8 码点语义声明**已核实存在**
   （主仓 docs/semantics.md §2 + 公开仓 semantics_zh.md），此项完成。

## 五、环境关键（换客户端必读，AGENTS.md 已同步）

- **$PY312 = `/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3`**
  ——裸 `/opt/homebrew/bin/python3` 无 llvmlite，silu CLI 会**静默隐藏**
  build/llvm/verify 子命令，门禁以 "invalid choice" 全红（实证踩过）。
- `export PATH="$HOME/.cargo/bin:$PATH"`（cargo 不在默认 PATH）。
- 一切从仓库根执行；siluc rt 缓存 `~/.cache/silu-runtime/driver/`（自带
  内容校验+clang 身份戳，异常可整删）。
- SSH 降级：`GIT_SSH_COMMAND="ssh -i $HOME/.ssh/lb_ali_18 -o IdentitiesOnly=yes"
git push ssh://git@ssh.github.com:443/askender/silu-nightly.git main`
- git 推送三档路径（11-10 实证）：①直连 `ssh.github.com:443` 通常可用；
  ②直连失败且代理已开：HTTPS/gh 用 `export https_proxy=http://127.0.0.1:7897
  http_proxy=http://127.0.0.1:7897 all_proxy=socks5://127.0.0.1:7897`，
  SSH 用 `GIT_SSH_COMMAND="ssh -o ProxyCommand='nc -X 5 -x 127.0.0.1:7897 %h %p'"`
  （两条均实测通）；③代理也未开时用上面 lb_ali_18 直连降级。

## 六、本会话教训（新增四条）

1. **手写测试期望必须真跑 CPython 生成**——三次被自己的手写参照误导。
2. **Oracle 新 arm 位置敏感**：len 兜底首版放臂首短路 dict/list 的 pyobj
   臂，打破 8 个旧文件；插臂后必跑全量 ll 门禁。
3. **改运行时函数复杂度要同步审视编译期消费者**（.ll 渲染器孪生）——
   m8 一度 0.41s→355s。
4. **语料探针性价比极高**：utf8_probe 首跑抓获 3 个真 bug（含一个违反
   "宁报 ERROR"铁律的静默错误字节：步进切片丢步进）。
5. （补充）**"偶发竞态"结论要复现验证**：本失败两次被误判为竞态，
   standalone 复现后才确认真回归——全量跑失败先定向重跑一次再下结论。
