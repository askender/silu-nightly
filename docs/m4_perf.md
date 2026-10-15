# M4 前端性能改进（2026-10-15 完成）

## 结果

`selfhost/silu_fe.si`（979 行）自解析：**529ms → 33.7ms（15.7x）**，
IR 对拍（tests/test_selfhost_m4.py）字节级不变。对 Python 版
`silu ir`（177ms）从 0.3x 反超为 **5.2x**。

## 瓶颈定位过程（按实测修正了两轮误判）

1. 阶段分解：tokenize 494ms（93%），JSON 拼接仅 ~35ms——
   "O(n²) 拼接是瓶颈"的第一判断错误。
2. 字符访问模式微基准（312k 字符）：装箱 `ch = s[i]; ch == "+"`
   609ms；注解槽 472ms；`ord(s[i])` + 整数比较 35ms——字符串表示
   本身（每字符 2-4 次 rawstr 物化）是瓶颈，第二判断
   （"只需 ord 直通"）只对了一半。
3. 字段版微基准：`h.src[i]` 同样的整数循环 **39.6s**——
   `_emit_field_read` 对 RAWSTR 字段**无条件 copy-on-read**，
   每字符整串拷贝（979 行源码 = 每字符 ~30KB）。

## 落地的三项改动

1. **ord(char-view) 直通**（typed_codegen.py）：新运行时函数
   `view_ord(i8* data, i64 seq)` 原地解码 UTF-8 序列，`ord(s[i])`
   对 RAWCHAR_VIEW 零分配返回 i64。
2. **实例 str 字段借用读**（typed_codegen.py）：
   `_borrowed_field_str` 在**下标/len** 的 base 是实例 str 字段时
   直接 load 槽指针，跳过 copy-on-read。安全边界：key 表达式
   call-free（call 可能中途改写字段释放缓冲）；借用值只作为
   view 基址或 slice 源消费（都只读），不作为 owned RAWSTR 逃逸。
   微基准：字段访问从 39.6s → 9ms（与局部变量一致）。
3. **lexer 整数化**（silu_fe.si，~90 行）：peek_cp/peek2_cp 返回
   码点 int，advance 跟踪行列用码点比较，名字/数字/空白/括号
   分支全部整数区间判断；token 文本仅在 token 结束时切片一次
   （每 token 一次物化，而非每字符 2-4 次）。

## 新基线（5 次最优）

| 输入 | Python `silu ir` | M4 silu_fe | 加速比 |
|---|---|---|---|
| calc.si (154 行) | 171ms | ~5ms | ~34x |
| silu_fe.si (979 行) | 177ms | 33.7ms | 5.2x |

## 后续已做

- ~~json_dumps 的 O(n²) 拼接~~：`sep.join(list[str])` 内建已落地
  （rawlist_str_join 运行时，一次分配两遍扫描），silu_fe 的
  json_dumps/json_quote 改用 join，自解析 33.7ms → **27.2ms**。
- 沿途发现的编译器缺口（记录待修）：
  - **未定义名在函数体中静默通过**（本轮 `ch` 引用残留变成了
    垃圾值而非编译错误，与"未知函数静默 null"同类）
  - 计时教训：**构建后首次运行有数百 ms 冷启动**（页错误），
    基准必须取多次最优，单次计时会把 9ms 读成 584ms
