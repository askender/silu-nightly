# M5：class 编译到 C 的设计（ir2c.si 全后端化）

目标：`selfhost/ir2c.si`（Silu 写的 IR→C 编译器）从 int 子集扩展到
覆盖 class/enum/方法/match/字符串/容器，最终能**编译 silu_fe.si
自身**为 C → clang → 二进制，与 typed 后端二进制对拍——至此
"任意 .si → 二进制"的工具链 100% 由 Silu 写成（自举编译闭环）。

蓝图不是新发明：把 `silu/typed_codegen.py` 已验证的表示与布局
翻译成 C 文本生成策略。

## 1. 数据表示（kind → C 类型）

| IR kind | C 类型 | 说明 |
|---|---|---|
| `i64` | `int64_t` | |
| `f64` | `double` | |
| `i1` | `int`（0/1） | printf 按 bool 打印 |
| `rawstr` | `Str*` | `typedef struct {int64_t len, cap; char* data; int64_t cp;} Str;` |
| `rawlist_i64/f64/str` | `ListI/ListF/ListS` | `typedef struct {int64_t len, cap; T* items;}`（str 为 `Str**`） |
| `rawdict_*` | `DictII/DictIF/DictSI/DictSF` | 开放寻址 `typedef struct {int64_t count, tombstones; Entry* entries;}`（typed 后端同构） |
| `instance` | `void*`（强类型处用 `X*`） | 8 字节槽堆块，无 header/vtable |
| `obj`（动态） | 本阶段不支持，编译期报错 | M5 白名单外的 opcode 同样显式报错 |

## 2. class 布局、构造与方法

typed 后端语义（docs/class_design.md）逐一映射：

- **布局**：`class X: a: int; b: str; c: X` →
  ```c
  typedef struct X { int64_t a; Str* b; struct X* c; } X;
  ```
  字段按声明顺序；实例字段（含自引用）是指针，容器字段是
  指针（引用语义）。
- **构造（dataclass 语义）**：`X(v1, v2, v3)` →
  `X* X__new(int64_t v1, Str* v2, struct X* v3)`，malloc + 按序赋值。
  生成点：class_def 处先 emit 前向 struct，再 emit 构造器
  （两遍扫描，支持前向/自引用——与 `_register_class` 两遍注册同理）。
- **方法**：`def m(self, y): ...` → `RET X__m(X* self, ...)`
  （名字 mangling 与 typed 后端一致：`X__m`）。`x.m(a)` 调用点改写为
  `X__m(x, a)`；接收者类型由 `_var_class` 等价物——ir2c 需要维护
  同样的类解析链：参数注解 → 变量注解 → 构造调用 → 返回注解 →
  字段类（`X.c` 的类是 c 的注解类）。**这条链是 ir2c 的主要新逻辑**
  （typed_codegen 的 `_class_of_node` 子集）。
- **字段读写**：`x.f = v` → `x->f = v`；读 str 字段 → 直接传指针
  （M5 内存模型见 §5，不做 copy-on-read 的 C 复刻——typed 后端拷贝
  是 LLVM 槽所有权的需要，C 侧指针共享语义等价，因为 M5 不 free）。
- **enum**：`class E(Enum): A = 0` → `enum { E_A = 0, ... };`
  成员引用 `E.A` → `E_A`；裸成员（值为 None）按 auto 序号展开
  （与前端一致）。`t.kind == E.A` → 整数比较。

## 3. 语句/表达式 → C

沿用 M3 现有骨架（vars 集合区分声明/重赋值），新增：

- `ann_assign` → 声明（带类型）；`attribute_aug_assign` →
  `self->pos += 1`；`tuple_assign` → 逗号展开
- `if`（含 elif 链/orelse 嵌套）、`while`、`for`（range/列表迭代/
  enumerate 脱糖后的形式——**M4 产出的 IR 已是脱糖后形态**，
  ir2c 只需处理 IR 本身）
- `match`：subject 静态类型已知 → switch/if 链展开
  （match_value 比较常量；match_as 捕获；guard 接 &&）
- `raise SystemExit(n)` → `exit(n)`
- 调用 print/len/ord/chr/str/int/float/read_stdin/read_file/
  str 谓词 → 预生成 C runtime 函数（§4）
- 字符串字面量：全局 `static const char L_N[] = "...";` + `Str` 包装
  （转义规则与 json_quote 一致）

## 4. C runtime（预生成前导）

一段固定 C 前导（~300 行），提供：`Str* str_new/str_add/str_cmp/
str_slice/str_at/str_ord ...`；四个 List 与四个 Dict 的 new/push/
get/len/has；`print` 家族（int/float/bool/str 的 Python 格式化——
复用 typed 后端 float 打印规则）；I/O（read_stdin/read_file）。
**关键：这段前导本身是手写 C，一次性投入；ir2c 只管生成用户程序。**

## 5. 内存模型与明确限制

- **process-lifetime**：不生成任何 free（与 typed 后端 rawlist/
  rawdict 一致）。rawstr 同样不 free——长跑程序泄漏，限制记录；
  后续可加 arena。
- 无异常/恢复；越界/类型错 → C runtime 里 `fprintf(stderr)+exit(1)`
  （对应 panic）。
- 动态 obj、闭包、生成器：不支持，编译期报错（白名单制）。

## 6. 验收

1. ir2c 编译 M2/M3 现有程序集——输出不变（回归）
2. ir2c 编译 `selfhost/calc.si` → 二进制与 typed 版对拍（首个含
   class/enum/match 的目标）
3. ir2c 编译 `selfhost/ir_interp.si`、`ir2c.si` 自身
4. **最终验收：ir2c 编译 `selfhost/silu_fe.si`** → 二进制解析
   calc.si 的 IR 与 typed 版一致；至此
   `cat x.si | ./silu_fe | ./ir2c > x.c && clang x.c` 全程无 Python
5. 每步 pytest 全绿 + 新增对拍测试固化

## 0. 进度

- **阶段 2+3 完成（2026-10-15）**：ir2c.si 重写为类型化生成器
  （~880 行）——两遍类收集（自引用/互引用）、enum→C 常量、
  class→struct + `X__new` 构造器 + `X__m` 前缀方法（含原型）、
  match→if 链、str（at/slice/eq/isdigit/add + `%.15g→%.17g` 最短
  往返浮点打印，与 typed 对拍一致）、list 槽模型、truediv 走
  double、`raise SystemExit`→exit、`[]`→list_new。
  **calc.si 全链达标**（silu_fe → ir2c → C → clang，16 表达式 +
  错误路径与 CPython 对拍），M2/M3 核心程序集回归 4/4，
  `tests/test_selfhost_m4.py::test_m5_ir2c_compiles_calc` 固化。
  沿途修复：typed 的 `return None`→实例字段 coerce（null 指针）、
  silu_fe 的 `s[:hi]` 缺 lo 切片错位。
- **阶段 4 完成（2026-10-15）**：dict 运行时（str 键开放寻址 +
  FNV 哈希，8 字节值槽）、dict 字面量/下标读写/`in`、
  `print(end="")`（kwargs 是 (name, const-value) 数组对）、
  `subscript_assign`。**ir_interp.si 全链达标**——M5 链编译的
  M2 解释器跑通 M2 全部程序集（5/5，含 30 万次循环的程序）。
  途中修的语义坑：**字符串的 < <= > >= 必须走字典序 str_cmp**
  （C 指针比较是错的——`ch >= "0"` 全部失真，Json.number 死循环
  的根因）；类解析链补 subscript（`node.arr[i].s` 型链）。
- **阶段 5 部分完成（2026-10-15）**：ir2c 获得动态值层（PObj
  tagged union：nil/int/float/bool/str/list + pint/pstr/plist/pget/
  plen/p_eq/p_truthy/pconcat/pappend）、`-> object` 函数（return
  处装箱、isinstance/x[i]/x is None|True|False/转发参数推断两轮）、
  for-in-range/str/obj/类实例迭代、enumerate(obj|str)、tuple 与
  混合元素列表字面量（DLIT 静态构造）、`in`（dict/list/str 三种）、
  容器真值、obj 参与的序比较、print(end=)、调用边界 obj↔静态
  箱拆、call 边 str_mod（% 格式化）。
  **状态**：`x`/`x=1`/`x: int=5`/顶层 class/enum/嵌套 def 等简单
  程序经全链正确；**calc.si 级复杂输入在 json_emit 阶段有一个
  未定位崩溃**；**typed 编译版 ir2c 与 pycompat 版存在字面量池
  行为差异（278 vs 370 项）导致自举输出尚有 diff**。两项为 M5
  收尾的最后缺口，记录待续。
- 过程修复：silu_fe 不支持 `\` 续行（ir2c 源码 9 处合并单行）。

## 7. 实施顺序（每步可验证）

1. C runtime 前导 + str 字面量/拼接/比较（calc 不需要，先给
   ir_interp 铺路）
2. enum 展开 + match（calc.si 达标 → 提交）
3. class struct/构造/方法/字段 + 类解析链（ir_interp.si 达标 → 提交）
4. 容器运行时 + 容器字段（ir2c.si 自身达标 → 提交）
5. silu_fe.si 冲刺（借用路径等 typed 特有优化的 C 直译）

## 8. M5 完成（2026-10-15 深夜）

两个收尾缺口解决，**全自举闭环达成**：

1. "池差异"实为陈旧构建产物——typed 与 pycompat 生成的 C 完全一致（278 项池两边相同）。
2. json_emit 崩溃是六个连环根因（每修一个暴露下一个）：
   - **混合常量列表**（`["const", None]`）走静态 LITL 路径——裸 Str*/int 槽混入 PObj 世界，"const" 的 ASCII（0x74736e6f63）被当 PObj 解引用。修：非纯 str 常量列表一律 DLIT 装箱。
   - **空列表 `[]` 进 obj 语境**（`orelse = []` 后接 parse_block 的 PObj）——静态 `List*` 变量收到 PObj，`plist()` 双重包装。修：空列表字面量归入 obj（`plist(list_new())`）；注解 `x: list[T] = []` 保留静态表示。
   - **JSON true/false 曾解析成 jnum(1/0)**——bool 身份丢失，`is True/is False` 全部退化成同一个 `p_is(x,3)`。修：jbool + BOOL kind 贯通到 const 生成与 is-branches。
   - **int(s, base)**（to_int 的 16 进制）曾静默返回 0——0x20 字面量全变 0。修：str_to_i64_base。
   - **plist_strs**：静态 list[str] 进动态世界时逐元素装箱（`["or"] + parts` 的裸 Str* 混入）。
   - **dict 字面量**（op_map）值需要装箱（dict:obj）。
   - **自举 miscompile 根因**：args_text_typed 的 ptypes 参数无注解 → 动态化 → pget 返回 PObj 却按 Str* 比较（内存布局巧合在 typed 版"能跑"，自举版损坏）。修：`ptypes: list[str]` 注解 + 空表替代 None。

**最终验证**：silu_fe（前端）→ 解析自己 → **自举版 ir2c**（ir2c 编译自己产出的 C 编译的 ir2c）→ C → clang → 新前端，对全部 selfhost 程序输出与 `silu ir --format json` 逐字节一致。`test_m5_self_hosted_toolchain` 固化，869 passed。

## 9. 后端性能（2026-10-15 深夜二）

纯 Silu 链（ir2c → C → clang -O2）对比 typed LLVM 后端（llvmlite →
clang -O2），13 个 benchmark（jsonparse 除外）：

- **几何平均 0.97x**——纯 Silu 链与 Python 写的 typed 后端整体持平
- wordcount 0.45x、nbody 0.80x（更快）；knucleotide 1.44x（每轮
  两次 str 切片分配，唯一显著差距）

三项优化：
1. **按需 PObj 前导**：benchmark 用户代码已零动态调用；后处理扫描
   发现代码无 obj 家族调用时剥离动态运行时（fib.c 20→0 处 PObj）
2. **摊销 str_add**：`s = s + lit` 循环内当左操作数有富余容量时
   原地追加（capacity 翻倍预分配）——string.si 624ms → 2.8ms。
   注意：C 后端无所有权检查，`t = s` 别名后 `s + x` 会波及 t
   （typed 后端经槽所有权证明无此问题）——文档化为已知语义边界
3. **小块 bump 分配器**：运行时从不 free（进程生命周期模型），
   ≤64 字节分配走 64KB bump chunk——knucleotide 43.7ms → 20.2ms
