done
- x, y = 1, 2;  x, y = y, x
- y = 1 if x else 2
- 函数作为值返回
- Only single target assignments supported
- print('a' if x else 'b') rust c 支持。
a=b=1  对于可变对象的行为（共享引用）
- 闭包容易在捕获变量上产生意外副作用（尤其是可变状态）。
只支持非纯闭包。需要状态管理时可以使用：
- **对象/类**: 明确的状态封装
- **全局变量**: 显式的共享状态
- **参数传递**: 显式的状态传递
- return 1 if x else 2

- is


- 默认参数的支持
- Assignment to Attribute
- del
- slice
- try raise
- iter yield
- async await
- while else
- Silu 不支持 `enumerate`

d = dict({1:2}, a=3)

- 避免“运算符行为过载”。行为和py有差异 # short circuit expressions outside if conditionals print(() or 1)
- Rust 和 Go 追求零成本抽象。


!!!!!
- 不支持 l = []; l += range(6, 10)
- del
- class

问题的根本原因是**输出处理方式的不同**：

1. **Python的subprocess**：会将`\r`（回车符，ASCII 13）转换为`\n`（换行符，ASCII 10）
2. **Silu的contextlib.redirect_stdout**：保留原始的`\r`字符不变

这是一个**平台和终端处理的差异**，而不是Silu解释器本身的问题。


❌ aok/andor.py: MISMATCH
❌ aok/bytes_escape_unicode.py: MISMATCH
❌ aok/list_extend.py: MISMATCH
❌ aok/return1.py: MISMATCH
❌ aok/string_escape_invalid.py: MISMATCH
❌ aok/string_upperlow.py: MISMATCH
❌ aok/ifexpr.py: MISMATCH



❌ aok/bytes_add.py: MISMATCH
❌ aok/bytes_compare.py: MISMATCH
❌ aok/bytes_compare2.py: MISMATCH
❌ aok/bytes_compare3.py: MISMATCH
❌ aok/bytes_escape_unicode.py: MISMATCH
❌ aok/bytes_find.py: MISMATCH
❌ aok/bytes_large.py: MISMATCH
❌ aok/bytes_mult.py: MISMATCH
❌ aok/bytes_replace.py: MISMATCH

❌ aok/dict_construct.py: MISMATCH
❌ aok/dict_fromkeys.py: MISMATCH

❌ aok/for_break.py: MISMATCH
❌ aok/list_extend.py: MISMATCH
❌ aok/return1.py: MISMATCH
❌ aok/string_escape_invalid.py: MISMATCH
❌ aok/string_mult.py: MISMATCH
❌ aok/string_upperlow.py: MISMATCH
❌ aok/ifexpr.py: MISMATCH


print(1, 2, sep='', end='')
builtin_override.py bad: unsupported feature: Assignment to Attribute not supported

dict_del.py bad: unsupported feature: Unsupported operator: In

string_fstring.py bad: unsupported feature: Assignment to Tuple not supported

x, y = y, x

del_name.py bad: unsupported feature: Unsupported name context: <class 'ast.Del'>



python test_ir_roundtrip.py aok/decorator.py
python test_ir_roundtrip.py aok/del_subscr.py
python test_ir_roundtrip.py aok/int_bytes_optional_args_cp311.py
python test_ir_roundtrip.py aok/scope.py
python test_ir_roundtrip.py aok/while_cond.py
python test_ir_roundtrip.py aok/while_nest_exc.py

silu ir aok/decorator.py
silu ir aok/del_subscr.py
silu ir aok/scope.py

try
silu ir aok/while_nest_exc.py
err
silu ir aok/int_bytes_optional_args_cp311.py
