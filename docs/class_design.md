# Silu class 设计：dataclass 语义即 Rust struct + impl

状态：**阶段 A（解释器）与阶段 B（编译器：int/float/bool/str 字段）已实施**
（f41ccdf 起）。容器字段（list/dict）与装箱在编译路径明确报错，留待
阶段 C。本文档是实施依据，按阶段可直接执行。

## 1. 目标与非目标

**目标**：`class` 默认就是 `@dataclass` 语义——注解字段 + 方法，
对应 Rust 的 `struct` + `impl`：

```python
# Silu（@dataclass 可省略——所有 class 都是这个语义）
class JointState:
    position: float
    velocity: float

    def is_moving(self) -> bool:
        return self.velocity > 0.01

st = JointState(1.0, 2.0)     # 按字段声明顺序的位置参数构造
print(st.is_moving())          # 方法调用，self 自动绑定
```

```rust
// Rust 对应物
struct JointState { position: f32, velocity: f32 }
impl JointState {
    fn is_moving(&self) -> bool { self.velocity > 0.01 }
}
```

**非目标**（明确不支持，遇到即编译错误/解释器 TypeError）：

- 继承（无 bases，`class A(B)` 报错）
- 类变量（类体里只有字段注解与方法定义）
- 动态属性（`p.newfield = ...` 不存在的字段 → AttributeError）
- `__dict__`、`__class__` 运行时自省
- `@dataclass` 装饰器本身（语法上允许写、语义是默认的；第一版可
  直接拒绝装饰器语法）
- 方法外的 `def`（无嵌套函数字段）

理由：每一条砍掉的都是"Rust struct 没有对应物"的 Python 动态性，
符合项目"只做 Rust 有类似东西"的原则；同时静态字段是编译器生成
扁平布局、符号执行生成扁平约束的前提。

## 2. 语义定义（参考语义 = 解释器）

### 2.1 字段与构造

- 类体中的 `field: type` 注解语句按**声明顺序**定义字段。
- `JointState(1.0, 2.0)` 按**声明顺序**做位置参数构造；每个实参
  coerce 到字段注解类型（`x: int` 收到 float → 现有 int 契约：panic
  或转换，与普通赋值一致）。
- 无 `__init__` 方法：构造即按序字段赋值（dataclass 生成的
  `__init__` 的手工等价）。**第一版不支持用户写 `__init__`**——
  需要 `__init__` 的场景用普通字段 + 方法取代（Rust 也没有
  构造函数重载，惯例是 `JointState::new`）。后续可加
  `JointState.new(...)` 静态方法形式的静态工厂。
- 带默认值的字段（`x: int = 0`）：支持；带默认值的字段之后不能再
  出现无默认值字段（dataclass 规则）；构造时缺省实参取默认值。
- 关键字构造 `JointState(position=1.0, velocity=2.0)`：支持（按
  字段名匹配；与位置参数混用时位置在前）。

### 2.2 方法与 self

- 方法就是第一个参数为 `self` 的函数；`st.m(a, b)` 脱糖为
  `JointState.m(st, a, b)`。
- `self` 在方法体内是只读绑定（不能 `self = ...`）；`self.x` 读/
  写都走字段偏移。
- 方法内可调用同类其他方法（`self.other()`）。
- 无访问控制（Rust 字段默认私有但 Silu 第一版全公有，与 Python
  一致；`_` 前缀仅为约定）。

### 2.3 类型与表示契约

- 字段注解是**用户契约**（与 `x: int` 同一规则）：编译路径 coerce，
  违约 panic。
- 字段类型支持所有可注解类型：`int`/`float`/`bool`/`str`/
  `list[int]`/`list[float]`/`list[str]`/`dict[int, int]`/
  `dict[str, int]`/`dict[str, float]`（全部复用 raw 家族表示）。
- 未注解字段：拒绝（`class` 体里字段必须带注解——这是与 dataclass
  的显式差异，换来静态布局）。
- 实例相等 `==`：第一版不支持结构化相等（退化为标识比较）；
  `repr` 打印为 `JointState(field=value, ...)`。

## 3. 解释器实现（参考语义，先做）

现状：`ir_generator` 已把类体规整为 `ann_assign`（字段）+
`func_def`（方法）的 `class_def` 节点；`ir_interpreter` 的
`_execute_class_def` 把类建成 dict，但**没有实例化路径**（`P()`
调用 dict → `'dict' object is not callable`），也没有 self 绑定。

改动（约 200 行，全部在 `ir_interpreter.py` / `interpreter.py`）：

1. `_execute_class_def` 改为产出 **ClassInfo**（不是 dict）：
   `{name, fields: [(name, annotation, default)], methods: {name: func_def}}`，
   存入 `global_env[name]`。
2. 新增实例表示：沿用 dict 但加不可见标记
   `("class_instance", class_name)` 前缀键（`__silu_class__`），
   字段名 → 值。沿用 dict 让现有 attribute/容器代码继续工作。
3. `_execute_call` 增加分支：被调值是 ClassInfo → 实例化：
   - 位置参数按 fields 顺序绑定，kwargs 按名绑定，缺省取默认；
   - 缺失且无默认 → TypeError。
4. `attribute` 读：实例 → 字段 dict 查；方法名 → ClassInfo.methods。
5. `attribute` 写（`self.x = ...`）：实例 → 字段 dict 写；
   写不存在的字段 → AttributeError。
6. 方法调用的 self 绑定：`st.m(...)` 脱糖为 `m(st, ...)` —— 在
   `_execute_call` 的 attribute 分支里做。
7. `ast_processor.visit_Assign` 的 `Assignment to Attribute` 限制
   解除（转 `process_attribute_assign` → ir_generator 产
   `attribute_assign` 节点）。

验收：`JointState` 例子逐字节等于手写 Python 语义；dataclass 规则
（默认值顺序、kw 构造、类型违约 TypeError）有专项测试。

## 4. 编译器实现（typed 后端，价值兑现）

### 4.1 布局

注解 → 8 字节槽（与 raw 家族一致）：

| 注解 | 槽内容 |
|---|---|
| int / bool | i64（bool 0/1） |
| float | f64 位模式 |
| str | rawstr 指针（i8*，实例拥有拷贝） |
| list[int/float/str] | rawlist 指针（实例拥有） |
| dict[int,*] / dict[str,*] | rawdict 指针（实例拥有） |

实例 = 一块 `8 * n_fields` 字节的堆缓冲（类名关联的 opaque i8*）。
所有指针字段实例拥有（写时 copy-in，实例释放时逐槽 drop——复用
rawstr 槽与 str 键字典的同一套纪律；第一版实例本身不 drop，随进程）。

### 4.2 代码生成

- `class_def` 处理器：收集 fields → 每类一个
  `{name: (offset, kind)}` 布局表 `self._class_layouts[name]`；
  方法提前注册为普通函数（名字改写 `P__m`，第一参数为实例指针）。
- `P(a, b)` 构造：malloc 布局大小 → 逐字段 coerce + store（含
  str/list/dict 的 copy-in）→ 返回 opaque 指针（装箱场景包成
  PyObject，tag 可用 dict 槽位+隐藏标记，或第一版禁止实例装箱——
  逢边界 coerce 字段）。
- `p.x` 读：offset load（kind 决定 i64/f64/指针）。
- `p.x = v` 写：coerce + offset store（指针字段 copy-in/free 旧值）。
- `p.m(args)`：`P__m(p, args...)`——方法体走现有函数生成路径，
  `self` 参数类型 = 实例指针；self.x 读写在方法内即偏移访问。
  跨函数推断对方法自动生效（参数 self 是 opaque，其余字段类参数
  照常提升）。
- 装箱边界：第一版实例不可装箱（print(p) 打印
  `<JointState>`；传给动态函数报错）。字段值装箱即可满足
  print(p.x) 等常见场景。

### 4.3 与现有机制的交互

- 跨函数签名推断：方法的 self 参数是 opaque——跳过提升（保持
  指针直传，零成本）；字段类参数照旧。
- 别名/视图：`ch = s[i]` 的 s 若是 `self.s`（字段）——第一版
  不提升（attribute 形状不在 char-alias 检测内），行为=拷贝，
  正确性不受影响。
- `_param_shared_names`：字段不涉及。

### 4.4 工作量

| 部分 | 行数估计 |
|---|---|
| 解释器（语义参考） | ~200 |
| 布局表 + 构造/读/写 codegen | ~350 |
| 方法改写 + self 绑定 | ~150 |
| 装箱边界与错误 | ~80 |
| 测试（对拍/类型违约/多字节/方法链） | ~250 |
| **合计** | **~1030** |

## 5. 阶段划分

1. **阶段 A（解释器）**：实例化 + self 绑定 + 属性读写 + 默认值/
   kwargs。验收 = JointState 例子 + dataclass 规则测试。
2. **阶段 B（编译器基本）**：布局 + 构造 + 字段读写 + 方法调用，
   仅 int/float/bool/str 字段。验收 = 与解释器对拍。
3. **阶段 C（容器字段）**：list/dict 字段的 copy-in/drop 纪律。
   验收 = 含容器字段的实战改造（jsonparse 的解析结果改 `data[i].id`）。
4. **阶段 D（可选后续）**：结构化 `==`、`repr`、实例 drop、
   `JointState.new` 静态工厂。

## 6. 测试清单（每阶段提交前全绿）

- JointState 全例（构造/方法/打印字段）
- 默认值 + kwargs + 位置混用
- 类型违约（int 字段收 float）→ 解释器 TypeError / 编译器 panic
- 方法内 self.x 读写、方法互调
- str/list/dict 字段的拷贝隔离（写副本不影响实例）
- 多字节字符串字段
- 未知字段写 → AttributeError/编译错误
- 解释器与编译产物输出逐字节对拍（verify 命令）
