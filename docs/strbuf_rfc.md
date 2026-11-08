# RFC：strbuf——显式可增长字符串缓冲（P1 决策 1b-lite）

> 状态：**待用户确认**（确认后按批实施）。研究依据：
> `reference/P1_STRING_RESEARCH.md`（实测：局部 `a = a + c` 的 O(1)
> append 是窄窗——同样的拼接走实例字段或函数边界退化 ~1100×；
> "跨函数共享的可增长缓冲"目前在 silu 里写不出来）。

## 0. 一句话

**str 的语义与实现一行不动**，新增一个引用语义的可变缓冲类型
`strbuf`，把 O(1) 摊还拼接从"编译器对局部变量窄窗的隐式识别"变成
**显式、上下文无关的语言契约**。

## 1. 语法与 API（最小集）

```python
b: strbuf = strbuf()          # 空缓冲；strbuf(s) 从 str 拷贝构造
b.push("hello")               # 追加一个 str（单字符即 push("x")）
b.push(other_str)             # 任意长度；O(1) 摊还，原地扩写
n: int = len(b)               # 当前长度（字节数，与 len(str) 同口径）
s: str = b.to_str()           # 物化为不可变 str（值拷贝；buf 保留可继续 push）
```

不做的事（显式拒绝，留给未来按需加）：

- **算术/传参无隐式转换**：`b + s` 编译期报错；`f(b)`（f 收 str）
  报错。互转只有 `strbuf(x)` 与 `b.to_str()`。`strbuf(x)` **总是**
  独立新缓冲（x 是 str 或另一个 buf 都拷贝内容）；别名写作 `b = a`。
- **不做单字符特化 push_ch**：`push("x")` 已覆盖；Rust 式
  push/push_str 二分不引入。
- **str 专属方法拒绝**：`b.strip()` 等报错，提示走 `to_str()`。

**v1 放宽（实施裁决）**：`b[0]`、`b == "x"`、`for ch in b`、`print(b)`
不报错也不拒绝——它们读取 buf 的**内容快照**（与 `to_str()` 同源），
语义正确且无错误字节风险；显式拒绝的拦截点分散在 subscript 推断、
比较融合、for 五族三处，回归风险大于收益。v2 若要收紧再统一收。

## 2. 语义决策（每条附推荐理由）

### D1 渐进式，不动 str 【推荐：渐进】
原 PROPOSALS P1-1b 是革命式（str 彻底改不可变 + arena + buf）。
本 RFC 收窄为**纯增量**：str 的三态表示、copy 规则、窄窗优化全部
保留。理由：研究显示现有热循环已全部落在窄窗内（silu_fe 实测
0.03s 与纯循环同级），痛点只在"窄窗之外的写法"——补洞即可，
不值得为它重写全部字符串形状（那是六条提案中回归面最大的一步，
收益却已被窄窗覆盖）。革命式的额外收益（删 copy 规则层）以
180 个非热路径 copy 点的现状维持成本换 30K+ 行形状重写，不划算。

### D2 引用语义，与 list/dict 容器族一致 【推荐：引用】
`b2 = b` 之后 `b2.push("x")` 两个名字都看得见（与 Python 的
io.StringIO、与 silu 自己的 list 一致）。可变对象用值语义会造成
"每次赋值深拷贝"的隐性 O(n)，恰是本 RFC 要消灭的东西。

### D3 不做 free / 作用域回收 【推荐：不 free】
silu 现状的可变容器（rawlist/rawdict/pyobj）一律不释放（程序期
回收），strbuf 对齐容器族。原案"strbuf 显式 free"被否：引用语义
下 free 的归属（哪个别名负责？）无法干净回答，double-free 风险
真实；且 strbuf 的生命周期典型就是"构建→to_str→弃"，程序期回收
完全够。str 域的现有 rawstr_free 管理不变。

### D4 表示复用 rawstr 【推荐：复用】
strbuf 就是 `{i64 len, i64 cap, i8* data, i64 cp}` 头的 i8*——
**rawstr 本来就是可变缓冲**，strbuf 只是把它作为一个显式类型暴露。
运行时零新增：`strbuf()` = rawstr_new_copy("")、`strbuf(s)` =
rawstr_copy(s)、`b.push(s)` = rawstr_append(b, s.data, s.len)、
`b.to_str()` = rawstr_copy(b)。这与 P5 单例"审计后无冲突"同款
论证：rawstr_append 原地改 buf，str 的 copy 规则保证没有人别名
buf（str 侧永远是拷贝出去的值）。

### D5 第一期不改自举源码 【推荐：不改】
silu_fe.si 的热循环继续用 `lit = lit + ch`（已在窄窗内）。好处：
**现有全部语料的 .ll 输出逐字节不变**——strbuf 落地的验收就是
"18/18 + 19/19 保持 byte-identical"（零回归面的最强证明）。
自举迁移作为批 2 演示（改一个函数、跑 fixed-point、量化收益），
不与语言落地混在同一 commit。

## 3. 实施面（批 1）

| 部件 | 改动 |
|---|---|
| Python 前端（ir_generator） | `strbuf` 注解原样进 IR（注解是字符串，无需新节点） |
| 自举前端（silu_fe.si） | 同上（若注解透传则零改动，待验证） |
| Rust 前端（silu-fe） | 同步 |
| Python 转换器（7 文件族） | `_annotation_kind` 增 BUF kind；`strbuf()` 构造 / `push`/`to_str` 方法分派 / `len(buf)`；buf 变量的 assign/传参走指针（无 copy）；buf 上的 str 操作（+、[]、比较）编译期报错 |
| Rust 参照（silu-conv） | 同步（Oracle 完整性） |
| 运行时 / 三层 llvmlite | **零改动**（D4） |
| 语料 | 新增 `benchmarks/strbuf_probe.si` 进差分 corpus（19 个 ll 语料） |
| 测试 | 单元（构造/push/to_str/len/引用语义/非法操作报错）+ 差分 19/19 |

预期输出变化：**仅新增语料自身**；现有 18 语料逐字节不变。

## 4. 批 2（可选，落地后另立）

silu_fe 的 `parse_fstring`/`unescape` 类函数改 strbuf + 字段场景
（`b.s = b.s + c` 形态 34.9s → buf.push 0.03s 的演示）、fixed-point
重钉、基准对比写入研究文档。

## 5. 开放问题（默认按推荐执行，除非你否决）

1. 类型名 `strbuf`（备选：`StringBuf`/`buffer`）——推荐小写与
   `str`/`int` 一致。
2. `to_str` 命名（备选 `str()` 内建转换/`freeze()`）——推荐方法
   形式，避免与内建 `str()` 装箱语义混淆。
3. `push` 的参数放宽到 `strbuf`（buf 追加 buf）？——第一期不做，
   `b.push(c.to_str())` 可达。
