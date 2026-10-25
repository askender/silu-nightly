# Memory Management: Silu 的两套纪律（2026-10-25, v1.9.0 实测）

> Silu 没有 GC。静态世界（typed 路径）用 **Rust 式所有权规则**，
> 动态世界（pyobj）**故意泄漏**。本文给出机制、实测数据与
> "为什么静态世界不需要借用检查器"的分析。

## 一、静态世界：所有权规则（无 GC，无借用检查器）

类型化路径不产生需要追踪的垃圾——每块内存从出生就有唯一主人：

| 类型 | 表示 | 生命周期管理 |
|---|---|---|
| `int` / `float` / `bool` | 栈值（i64/double/i1） | 无堆分配 |
| `str`（rawstr） | 独占堆缓冲 `{len,cap,data,cp}` | **完整 drop 体系**：赋值拷贝时旧缓冲 free；函数退出统一 drop 全部局部槽（`_emit_local_rawstr_drops`）；传参**借用零拷贝**（被调方只读，`s += x` 重绑走 concat 新建——Python 别名语义精确成立：`h(d)` 返回 "abx" 而 `d` 保持 "ab"） |
| `list[int]` 等 rawlist | 独占结构体 | 赋值即所有权转移；无作用域 drop（静态程序容器通常一次构建） |
| `dict[int,int]` 等 rawdict | 独占哈希表 | 同上 |

**实测**（Apple Silicon）：

- 200 万次纯标量循环：RSS 1MB（零分配）
- 20 万次字符串拼接循环：RSS 27MB（瞬态拷贝正常回收）
- 5 万次 `row = row + "*"`：2.3ms（amortized O(1) 原地 append）

## 二、动态世界：故意泄漏（leak by design）

pyobj 盒（`{i32 tag, i8* data}`；`create_int/str/list/dict/instance`）
malloc 后**永不 free**——运行时不存在用户盒的释放路径。

**实测**：30 万次循环、每次建一个小 list + dict，RSS 172MB
（~570B/迭代，纯泄漏）。

这是有意的取舍：

- 引用计数 = 每次赋值/传参/装箱插计数指令，恰好在已优化到
  0.9× Rust 的热路径上全部买单；
- 基准与 CLI 风格程序活动集有界，泄漏可接受——**批处理哲学**
  （程序结束，操作系统统一回收；类 arena 分配器用法）。

## 三、解释器平面

`silu interpret` / `silu exec` / pycompat 跑在 CPython 上：
Python 的引用计数 + 分代 GC，与语言语义一致（四平面验证因此
能抓住编译面的内存 bug——例如 v1.7.1 写回回归就是解释器平面
先暴露的）。

## 四、为什么静态世界不需要借用检查器？

Rust 借用检查器解决的问题是：**同一块内存可能有多个名字且
都可能写**。Rust 的答案是编译期证明"要么唯一写者，要么多个
只读者"（borrow checker）。

Silu 静态世界不需要它，因为语言语义更保守——三个根本差异：

1. **不可变值语义**。`str` 逻辑上不可变（Python 语义）：`s += x`
   是重绑（新串），不是原地写。原地 append 只是编译器在
   **槽独占**前提下的优化发射；一旦槽可能是借来的（str 参数），
   发射退回 concat 新建（`_borrowed_strs` 集合跟踪）。"写"这个
   动作永远不发生在共享内存上。
2. **共享即只读**。str 传参借用 = 被调方拿到指针但类型系统保证
   它只能读（`s[i]`、`len`、切片都产新值）。这是借用检查器的
   核心规则，但 Silu 不需要检查器来强制——**语言里根本没有
   通过共享引用写的语法**（无 `&mut`，无原地变异方法）。Rust
   需要检查器是因为它*提供*了 `&mut T`；Silu 不提供。
3. **容器的引用语义对齐 Python**。`list`/`dict` 赋值是别名
   （Python 语义），共享可变——但这正是 Python/Rust-`Rc<RefCell>`
   式的运行时对象，靠独占 malloc + 程序员心智模型管理，静态
   程序里它们通常一次构建终身使用（基准 8/14 静态程序里容器
   装载后从不重新绑类型）。

一句话：**Rust 要检查借用，因为它把"可变别名"作为语言能力
交给你；Silu 静态子集不给你这个能力，所以无从检查、也无需
检查。**代价是表达力上限（写不了 Rust 那种零拷贝原地算法的
通用形式——原地 append 只对槽独占这个窄窗口成立）；换来的是
编译器无需借用检查器即可保证内存安全。

## 五、将来要治吗（按性价比）

1. **sum-type 路线二**：收窄动态世界，泄漏表面积随 pyobj 用量
   一起缩（3-4 周级，也是 jsonparse/wordcount 性能的根治）。
2. **rawlist/rawdict 作用域 drop**：照抄 rawstr 的
   `_emit_local_rawstr_drops` 配方（1-2 天）。
3. **pyobj 引用计数**：盒布局加计数头、全部装箱/传递插桩——
   代价最大，仅长期驻留服务需要；当前无动机。

三项均不在 todo（无性能/正确性压力）。

---

附：复现命令——

```bash
python -m silu build /tmp/gc1.si -o gc1 && /usr/bin/time -l ./gc1   # 标量 1MB
python -m silu build /tmp/gc2.si -o gc2 && /usr/bin/time -l ./gc2   # str 27MB
python -m silu build /tmp/gc3.si -o gc3 && /usr/bin/time -l ./gc3   # pyobj 172MB（泄漏）
```
