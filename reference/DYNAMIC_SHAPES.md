# calc.si 动态实例层：参考形状提取（T2c 实现蓝图）

> 来源：`./siluc1 < selfhost/calc.si` 去 const_prefix（尾 51,427B / 1,323 行，
> /tmp/calc_tail.ll）。本文是 T2c 的实现蓝图——形状已解剖，未实现。
> 实现顺序建议：构造器/字段 → 方法调用 → 实例参数/返回 → 字符索引 →
> str 比较/短路 → match → epilogue 清理 → main 包装。

## 1. 程序结构

```
Parser__peek / Parser__eat / Parser__parse_primary / Parser__parse_mul /
Parser__parse_add   : 方法 → define internal i8* @"Class__method"(i8* self, ...)
tokenize(i8*) → i8*  : str 参数函数（str 元素列表返回）
evaluate(i8*) → double : 实例参数 + float 返回 + match
__silu_user_main() → i64 : 用户的 def main() 被改名并包装
main() → i32          : 调 __silu_user_main
```

## 2. 实例布局与构造器

- 实例 = `malloc(nfields * 8)` 裸字节；字段按**声明序**偏移 0, 8, 16…
- 构造 `Token(Tok.END, "")`：
  ```
  %N = call i8* @"malloc"(i64 16)
  gep N,0 → bitcast i64* → store i64 7          // enum 字段 = 变体序号常量
  gep str_367 → create_str(·,0) → pystr_to_rawstr   // str 字段
  gep N,8 → bitcast i8** → store rawstr
  ptrtoint i8* N to i64 → rawlist_push(list, i64)   // 实例入列表
  ```
- 枚举 Tok：NUM=0, PLUS=1, MINUS=2, STAR=3, SLASH=4, LPAREN=5, RPAREN=6,
  END=7（变体声明序，i64 直接量）
- Node 构造带 None 参数：None → 什么？（待查 Node(Tok.NUM, f, None, None)）
- float 字段（Node.value）：store double（bitcast double*）？

## 3. 字段访问（Parser__peek 证据）

```
读 self.toks:  load self → gep i8 self,0 → bitcast i8** → load   (字段0)
读 self.pos:   load self → gep i8 self,8 → bitcast i64* → load   (字段1)
写/aug self.pos += 1: 同链 load → sadd → store 回 gep
读 t.kind:     load t → gep i8 t,0 → bitcast i64* → load i64
```

## 4. 函数前导（参数分轨——修正 spectral 模型）

- **int/float/实例 参数** + 全部局部：合一注册，**整体逆序** alloca 块
  （eat: 源序 self,kind,t → 逆序 t,kind,self ✓）
- **str 参数**：成对正序（alloca + `store i8* null` + store 参数值）
  （tokenize: src 在逆序块之末 + null + store）
- **list 参数**：成对正序（alloca + store，无 null）（spectral v/out ✓）
- **str 局部**（含未注解的 ch）：alloca 后紧跟 `store i8* null`
- i1 局部（keep: bool）= `alloca i1`
- 实例参数无 null；方法 self = 实例参数 → 逆序块

## 5. str 元素下标读 src[pos]（cv 机器，与 list 下标不同！）

```
bitcast src → {i64,i64,i8*,i64}*；gep f3→load len；gep f0→load cap；
gep f2→load chars
icmp slt idx,0 → add idx,len → select（负索引）
icmp sge adj,0；icmp slt adj,len；and → br cv_ok / cv_err
cv_err: panic（38B 串，IndexError 变体）
cv_ok:  icmp eq cap,len → br cv_ascii / cv_walk
cv_ascii: br cv_join
cv_walk:  %off = call i64 @"rawutf8_cp_offset"(chars, adj)；br cv_join
cv_join: %p = phi i64 [adj, cv_ascii], [off, cv_walk]        ← 语料首个 phi！
  gep chars,p → load i8 → and/icmp 224/192, 240/224, 248/240
  → select 宽度 4/3/2/1 → select(ascii?, 1, w)
  insertvalue {i8*,i64} ×2 → extract ×2 → call rawstr_char1 → 1 字符 str
  [若赋给 str 局部：先 load 旧值 → rawstr_free(旧) → store 新]
```

## 6a. and/or 短路 + truthy 机器（parse_mul: `t.kind==Tok.STAR or t.kind==Tok.SLASH` 已解剖）

```
sc_result = alloca {i32, i8*}*     // 命名临时，提升到 entry，多出现 .N 后缀
A 求值 → i1 .22
br .22 → sc_finish / sc_next       // or: A真→finish；and 应为 A假→finish
sc_finish: %x = call {i32,i8*}* @"create_bool"(i1 .22); store sc_result; br sc_end
sc_next:   B 求值（重新 load t/字段，无CSE）→ i1 → create_bool → store → br sc_end
sc_end:    %p = load sc_result; icmp eq {i32,i8*}* %p, null
           br → truthy_merge / truthy_call
truthy_call: %t = call i1 @"pyobj_truthy"({i32,i8*}* %p); br truthy_merge
truthy_merge: %b = phi i1 [0, %sc_end], [%t, %truthy_call]   ← 第二个 phi！
           br %b → if_then / if_else（正常 if 机器）
块创建序：sc_finish, sc_next, sc_end, truthy_call?, truthy_merge…（finish先）
```
`keep = A and B`（赋值给 bool 局部）与 `while keep:` 的形状待解剖。
bool 局部 = `alloca i1`（tokenize keep）。

## 6. str 相等比较 + or 短路链（ch == " " or ch == "\t"）

```
%"sc_result" = alloca {i32, i8*}*     // 命名临时（sc = short-circuit?）
load ch；create_str(常量) …
call i1 @"rawstr_eq_cstr"(ch, 常量ptr, len) → br sc_finish / sc_next
sc_finish: …存 sc_result；br sc_end
sc_next:   下一比较 → …
sc_end:    load sc_result → icmp eq null → br truthy_merge / truthy_call
truthy_*:  pyobj_truthy 机器（布尔化）
```
（elif 链 = 嵌套 if，走既有 if 机器）

## 7. str 方法：ch.isdigit() → call i1 @"rawstr_isdigit"(ch)
   （rawstr_eq_cstr/isdigit/to_cstr/slice/free/copy 均为裸调用）

## 8. epilogue：函数返回前清理 str 局部

```
ret 前：逐个 str 局部（含参数 src？待确认范围）：load → call rawstr_free
（tokenize: free(ch) 但不 free(src)；返回值 toks 不清）
```

## 9. __silu_user_main 包装

用户的 `def main() -> int:` → `define internal i64 @"__silu_user_main"() 
alwaysinline`；真实 main() 体极薄：调它 + ret i32 0（待抄）。
仅当程序有 def main 时出现（其余语料是模块级代码直出 main）。

## 10. match 形状（已解剖，evaluate 证据）

```
scrutinee 字段读一次（load→gep0→bitcast i64*→load i64 → %v）
case 0: icmp eq i64 %v, 0 → br case_body / case_next
  块创建序：case_body, match_end, case_next, case_body.1, case_next.1, ...
case_body.N: 语句（通常 return）
case_next.N: icmp eq %v, K → br case_body.(N+1) / case_next.(N+1)
通配 case _: case_next.4 直接 br case_body.5（无 icmp）
match_end: 全部落空兜底 ret double 0x0（类型化零值）
node.right is None → load 字段 → icmp eq i8* null → if_then/if_else
```

## 11. 其它已确认形状

- raise SystemExit(1) → `call void @"exit"(i32 …)`（参数求值后）
- input() → `call {i32,i8*}* @"pyobj_input"()` → pystr_to_rawstr →
  赋给 str 局部时走 free旧+存新 模式
- 构造器内联：`parser = Parser(tokenize(line), 0)` → malloc(16) 先行，
  再逐参求值，再逐字段 store（toks@0 i8*、pos@8 i64）
- __silu_user_main：用户 def main → internal i64 __silu_user_main()
  alwaysinline；真实 main = call i64 @__silu_user_main() + ret i32 0
- str 赋值到已有 str 局部：load 旧 → rawstr_free(旧) → store 新
  （ch = src[pos] 与 line = input() 均此模式）

## 12. 仍待解剖（下一窗口从这里继续）

- **已提交骨架 9ea5fe7**：enum/class 收集、Typed::Inst 字段/构造器/方法
  调用、str 参数成对+null、FN_S、cv 字符索引（含 phi）、match、
  str 赋值 free-old。calc 现卡在 `keep = pos < n and src[pos].isdigit()`
  （bail: assign type）→ 下一步实现 §6a and 变体 + isdigit 方法
  （call i1 @"rawstr_isdigit"(str)）+ bool 局部/cond
- str 切片 src[start:pos]（应复用 cv 机器 + rawstr_slice）
- float(t.text)/int(result) 转换调用形状（str_318 ValueError 分支在旁）
- input()（§11 已记）/ exit(i32) / str 局部 epilogue free 范围
- __silu_user_main 包装 + 真 main 薄壳
- jsonparse ×2 复用同层

## 12b. 原"仍待解剖"

- 方法调用 parser.parse_add()（应直调 Parser__parse_add(ptr)）
- int(result)/float(t.text) 转换调用形状
- result == truncated（float==int 比较；fcmp + sitofp?）
- while True: cond 形状；str 切片 src[start:pos] 复用 §5 机器?
- jsonparse/jsonparse_json 应复用同层（先跑 calc）

## 13. 实现落点（silu-conv.rs）

- class_def/enum_def 收集：CLS_FIELDS(name→[(field,ty,off)])、
  ENUM_VALS(name→{variant: i64})、方法体抽出（Class__method，self 首参）
- 新 Typed 变体或 Inst(String)（i8* 实例引用）；字段读写/构造/方法调用
- conv_block 增加：class_def/enum_def/match/raise/method 调用
- str 比较 = rawstr_eq_cstr + sc 链；bool 局部 i1
- epilogue free 清单（str 局部）
- def main → __silu_user_main 包装


# jsonparse 的 pyobj 装箱动态层（T2c 第二台阶蓝图）

> 来源：`./siluc1 < benchmarks/jsonparse.si`（尾 77KB，/tmp/jp_ref.ll）。
> 与 calc 的静态实例层**并存于同一编译器**：判别点 = 值是否为无注解
> （untyped）——untyped 值一律装箱为 pyobj。

## 核心模型

- **pyobj = `{i32, i8*}*`**（即 none 类型作为值载体）。无注解返回/赋值
  的值全是 pyobj。`def parse_value(...)`（无返回注解）→
  `define internal {i32, i8*}*`（**无 alwaysinline**，同 none 规则）。
- **untyped 容器**：`result = []` → `create_list()` → pyobj；`result = {}`
  → `create_dict()`（parse_object 证据）。
- **自动声明**：pyobj rhs 的裸赋值 → 全局 `@"x" = global {i32, i8*}* null`
  （main 的 data）。

## 动态类构造（与 calc 静态 malloc 的分岔）

```
JArr(result):  # result 是 pyobj list
  %p = malloc(nfields*8)
  load result ({i32,i8*}*) → gep p,0 → bitcast {i32,i8*}** → store
  %m = call {i32, i8*}* @"pyobj_make_instance"(i64 CID, i8* %p)
  ret %m
CID = class 定义序（JInt=1, JStr=2, JArr=3, JObj=4 —— 全源码 class_def 次序）
```
判别：ctor 实参为 pyobj（untyped list/dict）→ 走 make_instance；
calc 的静态字段（int/str/float/静态list）→ 裸 malloc。待验证：
> 混合情况（某字段静态某字段动态）未见于语料。

## match_class（带捕获的类匹配）

```
match data:                      # scrutinee = pyobj
  case JArr(items=items):
%v  = load {i32, i8*}*, {i32, i8*}** @"data"
%cid = call i64 @"pyobj_instance_cid"({i32, i8*}* %v)
%eq  = icmp eq i64 %cid, 3       # JArr 的 CID
br → case_body / case_next       # 与 calc match 同链
case_body:
  %ptr = call i8* @"pyobj_instance_ptr"({i32, i8*}* %v)
  gep ptr, OFFSET → bitcast {i32, i8*}** → load
  store → @"items"               # 捕获名 = 自动全局 {i32,i8*}* null
```
AST: ["match_class",["name","JArr"],[],["items"],[["match_as",null,"items"]]]
(= 类名, kwargs, 捕获字段名表, 绑定列表)

## pyobj 运行时族（本次实际用到的）

- `list_append(pyobj_list, pyobj)` — 动态 append
- `pyobj_len_raw(pyobj)` — len(动态容器)
- `pyobj_subscript(pyobj, pyobj_key)` — 动态下标读（键先 create_str？待查）
- parse_object 的 `result[key] = v` → 大概率 pyobj_subscript_set（待查）
- `pyobj_instance_cid/ptr` — 类匹配/字段提取

## 静态层复用（已实现，直接可用）

- `pos: list[int]`/`s: str` 参数 = i8* 对儿（splice 正序）；局部逆序在前 ✓
- `pos[0]` 读取 = get_ok/get_err 边界检查对（list_get elem=int）✓
- `pos[0] += 1` = **无检查**直接 gep 链（aug-subscript 既有形状），
  panic_ok 里**复用** gep（不重载 pos）——与 attr_aug 的重载不同！
- `s[pos[0]] != '"'` = 链式：list_get → cv 字符机器 → eq_cstr ✓
- `digit_value(s[pos[0]])`：char1 结果直接 i8* 传给 str 参数 ✓
- digit_value 的 if 链 = 既有 str== 形状（create_str 弃值 + 新常量 gep
  + eq_cstr）✓

## 待解剖（下一轮入口）

1. parse_number 的 `s[pos[0]] >= "0" and <= "9"`：str 的 >=/<= 比较形状
   （sc_next 块内，非 eq_cstr——可能是 pyobj_ge 或字符序）
2. parse_object 的 `result[key] = v` IR（subscript_set?）
3. main 的 `o["id"]` 字面量键动态下标
4. `while s[pos[0]] != '"'` 中 cv 与 list_get 的 get_ok/get_err 编号交错
5. jsonparse_json.si（同目录伴生文件，应基本复用）

## 实现落点（silu-conv.rs）

- PYOBJ 表：untyped 值跟踪（auto-decl 时按 rhs 是否 pyobj 决定
  `{i32, i8*}*` 存储）；PY_FNS：返回 pyobj 的函数签名（untyped ret）
- ctor 分岔：实参含 pyobj → make_instance 路径（CID 表 = CLASSES 序+1）
- match_class 臂：cid 比较 + instance_ptr 捕获链
- len/subscript/append 的 pyobj 分支
- 现有静态路径一律不动（calc 已锁定）
