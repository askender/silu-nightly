# Rust 参照实现：进展与 TODO（2026-11-01）

> 钉住版本：silu 1.16.2 / commit 87df40f。本文是唯一的状态锚点——
> compact 后从这里继续。规约细节在 `reference/README.md`。

## 总体架构

```
silu-fe  (Rust 前端)      : .si → IR JSON     ✅ 19/19 与 silu_fe 逐字节一致
silu-conv (Rust 转换器)   : .si → 完整 .ll     ✅ 4/18 语料逐字节一致
diff_harness.py           : 平面对拍基架       ✅ 自校验通过
const_prefix.ll           : 365,264B 常量前缀   ✅ 跨语料恒定
```

- 位置：`reference/rust/`（cargo，零外部依赖，`src/main.rs` = silu-fe，
  `src/bin/silu-conv.rs` = 转换器）
- 运行：`cd reference/rust && cargo build`；对拍 `python reference/diff_harness.py ll conv rustconv`
- silu-conv 通过子进程调 silu-fe 取 IR（前端已独立验证）
- **非目标**：不做产品编译器、不进自举链、不做同步镜像（版本快照神谕）

## 当前状态：转换器 4/18

| 文件 | 能力面 | 状态 |
|---|---|---|
| fib | 提升函数/if/递归/溢出检查/print(int) | ✅ |
| arith | 模块全局/while/panic续体/%/ | ✅ |
| float | F64算术/sitofp提升/fdiv检查/float_repr | ✅ |
| string | rawstr全路径/append惯用法/len字段读 | ✅ |
| 其余 14 | 容器/类/match/复杂程序 | 未实现（exit 3） |

最近提交：`05fd782`（string）。之前：`ea377e4` float、`a491739` 块列表重构、
`2065595` fib、`dea0a70` arith 规约。

## 核心实现模型（已在代码中验证）

1. **FnBuilder 块列表**：块按创建序=输出序；游标定位；panic 对自动建
   panic_bad/panic_ok 块且**续体流进 panic_ok**（循环体余下语句在续块里）。
2. **槽位规则**：每条指令恰好消耗一个匿名槽；void 指令（store/br/cbr/
   ret/void-call/unreachable）静默消耗。序言 = N参数名 + 1返回槽 + N参数
   存储 + 1首行存储（2N+2 公式的分解）。
3. **类型化求值**：`Typed::{I64,F64,Str}` 三态；int/float 混合经 sitofp 提升；
   int/int `/` 产生 float（Python 语义）；str 名字查 STR_SLOTS 表。
4. **字符串计数**：模块级绑定各耗一槽；**str 绑定先造 init 常量串再耗槽**；
   函数体在模块遍历**之后**转换（print 串编号低于函数体 panic 串）。
5. **尾部全局块 = 创建序**：str-init 常量先于其全局声明（PRE_GLOBAL_STRS），
   模块全局随后，其余串跟随。最后一条后无换行。
6. **常量前缀**：365,264B（头+29 extern+全部运行时函数+运行时字符串全局）
   以 include_str! 嵌入，转换器只生成用户函数+main+用户全局。
   用户串计数基数 297（runtime 用 0..296）。

## 已发现的隐式规约（19 项，全部差分实证）

strtod接受十六进制 / enum提取序 / 空名槽位 / 常量前缀边界 / 幻影槽公式 /
**槽位机制（每指令一槽，权威）** / 字符串计数顺序 / panic后缀数标签定义行 /
尾部无换行 / 模块绑定耗槽 / panic-ok续体 / 模块全局领先尾部 /
Python mod-floordiv形状 / floordiv修正加在商上 / alloca在entry标签后 /
llvmlite双精度hex空格填充 / str绑定先造常量再耗槽 /
有值调用只耗一槽 / 创建序全局块。

## TODO（优先级序）

### T1 容器族（list.si → dict.si → trees.si …）
- [ ] list.si：rawlist 运行时调用族（init/append/下标访问的调用形状从
      参考尾直接读出：`./siluc1 < benchmarks/list.si` 后截取 const_prefix 之后）
- [ ] dict.si：rawdict 族 + KeyError 检查
- [ ] trees.si：class（记录类型）+ 方法调用

### T2 复杂程序
- [ ] jsonparse / spectral / mandelbrot / nbody / wordcount /
      knucleotide / fannkuch / list / calc / ir_interp / silu_fe 自身
- [ ] silu_fe.si 是最终关卡（2,183 行全特性）

### T3 校准报告（R3）
- [ ] 分组件行数对照表（前端已有：2509 Rust vs 2183 Silu +15%）
- [ ] 省/费热点归因（enum+match 省 vs 所有权/错误处理样板费）
- [ ] 发现的 bug 清单分诊（两侧任一 bug 或语料越界）
- [ ] 语言设计建议（和类型/pattern match 的实测价值）

### 方法提醒
- 每个新文件：读参考尾 → 实现子集 → 差分迭代（1-3 轮可达）
- 差分命令（单文件快速验证）：
  ```bash
  cd reference/rust && cargo build
  ./target/debug/silu-conv ../../benchmarks/X.si > /tmp/r_X.ll
  # 与 ./siluc1 < benchmarks/X.si | tail 对比（去 const_prefix 前缀后）
  ```
- 未支持构造一律 `bail()` → exit 3（宁报 ERROR 不出错误字节）
- python 补丁脚本注意：heredoc 内 `\n` 转义与 Rust 字符串字面量的
  双层转义冲突是本轮多次返工的根源——补丁用 pyEOF heredoc 并断言锚点存在

## R0 以来产出

- 差分基架 + 契约（4a3f446）
- Rust 前端 19/19（b43a7cf）
- .ll 解剖 + 常量前缀（fd2bef1）
- 序言规约（751d6be）/ 槽位机制（101561c）
- arith 规约（dea0a70）/ fib 里程碑（2065595）
- 块列表重构（a491739）/ float（ea377e4）/ string（05fd782）
