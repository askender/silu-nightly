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

## 12. 仍待解剖（实现时顺手读区段）

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
