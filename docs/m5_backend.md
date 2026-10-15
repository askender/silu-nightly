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

## 7. 实施顺序（每步可验证）

1. C runtime 前导 + str 字面量/拼接/比较（calc 不需要，先给
   ir_interp 铺路）
2. enum 展开 + match（calc.si 达标 → 提交）
3. class struct/构造/方法/字段 + 类解析链（ir_interp.si 达标 → 提交）
4. 容器运行时 + 容器字段（ir2c.si 自身达标 → 提交）
5. silu_fe.si 冲刺（借用路径等 typed 特有优化的 C 直译）
