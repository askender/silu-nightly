# Silu Simple IR 设计文档

## 概述

Silu Simple IR 是一种高级编程语言的共同语法子集，更接近高级语言的中间表示。采用接近 Python 的语法，在算术和逻辑运算等部分地方使用前缀表达式，结合缩进语法表示嵌套结构。

## 基本格式

每个表达式使用4空格缩进表示嵌套，缩进与括号有明确对应关系：

```
操作符 参数1 参数2
    子表达式1
    子表达式2
```

**缩进与括号的对应关系**：
```
; 缩进形式 (前缀表达式)
+ a
    * b c

; 等价的括号形式
(+ a (* b c))

; 控制流也可展开 (if-elif-else 展开为嵌套的条件表达式)
if (> x 0)
    print "positive"
elif (== x 0)
    print "zero"
else
    print "negative"

; 等价展开形式
(if (> x 0) 
    (print "positive")
    (if (== x 0)
        (print "zero")
        (print "negative")))
```

## 数据类型

### 基本类型
- `int` `float` `str` `bool` `none`
- `list` `dict`

### 字面量
```
42
3.14
"hello"
true
false
none
[1 2 3]
{"name": "Alice", "age": 30}
```

## 基本操作

### 变量赋值
```
= x 10
= name "Alice"
= result (+ x y)
```

### 算术运算
```
+ a b
- 10 5
* x 2
/ total count
% n 2
** 2 8

; 复杂表达式使用缩进，也可以用括号
= result (+ (* a b) (/ (- x 5) (+ y 2)))
; 或使用缩进形式（两者等价）
= result
    +
        * a b
        /
            - x 5
            + y 2
```

### 比较运算
```
== x 10
!= name ""
< age 18
>= count 1

; 复合条件
and (> x 0) (< x 100)
```

### 布尔运算
```
; 布尔运算
and true false
or x y
not condition
and (> x 0) (< x 100)
or (== status "ok") (== status "ready")
```

## 控制流

### 条件语句
```
if (> x 0)
    print "positive"
elif (== x 0)
    print "zero"
else
    print "negative"
```

### 循环语句
```
while (< i 10)
    = i (+ i 1)
    print i

for i in (range 0 10)
    print i

for item in numbers
    print item
```

### 循环控制
```
for i in numbers
    if (== i 0)
        continue
    if (== i target)
        break
    print i
```

## 函数

### 函数定义
```
; 无类型注解
func add a b
    = c (+ a b)
    return c

; 带类型注解 (推荐语法)
func add (a: int) (b: int) -> int
    = c (+ a b)
    return c
```

### 函数调用
```
; 简单调用
add 10 20
print "Hello"
greet              ; 无参函数调用

; 变量引用需要赋值
= f greet          ; 将函数赋值给变量
= x value          ; 获取变量值

; 嵌套调用
print
    add 10 20
= result
    multiply
        add a b
        subtract c d
```

## 数据结构

### 列表
```
= numbers [1 2 3 4]
= mixed [1 "hello" true]
```

### 字典
```
= person {"name": "Alice", "age": 30}
= config {"debug": true, "port": 8080}
```

### 访问和修改
```
= first (l_get numbers 0)
= name (d_get person "name")
l_set numbers 0 100
d_set person "name" "Bob"
```

### 列表操作
```
append numbers 5
prepend numbers 0
remove numbers 2
```

### 切片操作
```
= slice1 (slice numbers 1 3)
= slice2 (slice numbers 0 2)
= slice3 (slice numbers 2 -1)
```

## 完整示例

### 递归函数
```
func factorial n int -> int
    if (<= n 1)
        return 1
    else
        return (* n (factorial (- n 1)))

= result (factorial 5)
print result
```

### 数据处理
```
= students
    [
        {"name": "Alice", "score": 95}
        {"name": "Bob", "score": 87}
        {"name": "Carol", "score": 92}
    ]

for student in students
    = name (d_get student "name")
    = score (d_get student "score")
    if (>= score 90)
        print name "gets an A"
    elif (>= score 80)
        print name "gets a B"
    else
        print name "needs improvement"
```

## 关键字列表

### 控制关键字 (17个)
- `=` `if` `elif` `else` `while` `for` `in` `func` `return`
- `break` `continue` `append` `prepend` `remove` `l_get` `l_set` `d_get` `d_set`

### 运算符 (16个)
- 算术：`+` `-` `*` `/` `//` `%` `**`
- 比较：`==` `!=` `<` `<=` `>` `>=`
- 逻辑：`and` `or` `not`

### 数据类型 (7个)
- `int` `float` `str` `bool` `none` `list` `dict`

**总计：40个关键字**

## 设计评估

### 图灵完备性
✅ 支持条件分支、循环、递归、无限存储

### 设计原则
- **无内存管理抽象**：不提供显式的内存管理操作
- **高级IR定位**：作为高级编程语言的共同语法子集
- **Python语义一致**：变量作用域、循环控制等行为与Python一致
- **简化类型系统**：当前版本不包含类型推导机制（后续扩展）

### 优点
- 语法极简：只有40个关键字
- 缩进清晰：层次分明
- 混合语法：Python风格 + 前缀表达式的平衡
- 实用性：支持常用数据结构和类型系统
- 定位清晰：高级编程语言的共同语法子集

### 主要局限（后续扩展）
- 类型推导系统（计划扩展）
- 模块化系统（计划扩展）
- 异常处理（计划扩展）
- 标准库（计划扩展）
- 并发支持（计划扩展）
- 调试能力（计划扩展）

**当前定位**：高级编程语言的共同语法子集，更接近高级语言的中间表示

## 设计说明

### 语法规则
1. **混合语法设计**：基础语法接近 Python，算术和逻辑运算使用前缀表达式
2. **缩进语法**：4空格缩进替代括号，与括号有明确对应关系
   - 每层缩进对应一层括号嵌套
   - 数值计算可用括号或缩进，优先级遵循括号规则
   - 控制流可展开为嵌套的条件表达式
3. **数据访问区分**：使用 `l_get/l_set` 操作列表，`d_get/d_set` 操作字典
4. **类型注解**：`func name (param1: type1) (param2: type2) -> return_type`
5. **标识符命名**：遵循Python命名规则，关键字冲突处理参考Python
6. **字符串表示**：使用引号，支持Python转义规则
7. **函数调用语义**：无参函数调用与变量引用通过上下文区分（参考Python）

### 类型系统
- **可选静态类型**：函数参数和返回值可以标注类型
- **类型推导**：未标注的变量类型通过赋值推导
- **类型检查**：在编译时进行静态类型检查（如果有类型注解）

### 作用域规则  
- **全局作用域**：支持全局变量，模块级别变量
- **函数作用域**：函数内部变量优先级高于全局变量
- **循环变量作用域**：for循环变量和while循环变量行为与Python一致
- **参数传递**：基本类型值传递，复合类型引用传递（与Python一致）
- **循环控制**：`break`/`continue`仅在循环内使用，嵌套行为与Python一致

### 基础操作

#### 有返回值的内置函数（必须使用赋值接收）
```
= length (len numbers)
= num (int "123")
= text (str 456)
= decimal (float "3.14")
= is_num (isinstance x int)
= obj_type (type x)
= first (l_get numbers 0)
= name (d_get person "name")
```

#### 有副作用的数据操作（原地修改，无返回值）
```
append numbers 5              ; 在列表末尾添加元素
prepend numbers 0             ; 在列表开头添加元素
remove numbers 2              ; 删除指定值的第一个匹配项
l_set numbers 0 100           ; 设置列表元素
d_set person "name" "Bob"     ; 设置字典键值
```

#### 无副作用的输出函数
```
print "Hello"                 ; 输出内容，无返回值，不需要赋值
print x y z                   ; 输出多个值
```

**重要说明：**
- 有返回值的函数必须使用赋值语句接收结果
- 数据修改操作（append、prepend、remove、l_set、d_set）的副作用行为与Python一致
- print 等输出函数无返回值，不需要也不能赋值
- 使用 l_* 和 d_* 前缀明确区分列表和字典操作，提高代码可读性和类型安全
- 字典字面量使用冒号分隔键值对：`{"key": "value", "num": 42}`