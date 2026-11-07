; ModuleID = "silu_module"
target triple = "arm64-apple-darwin24.6.0"
target datalayout = "e-m:o-i64:64-i128:128-n32:64-S128"

declare i32 @"printf"(i8* %".1", ...)

declare i8* @"malloc"(i64 %".1")

declare i8* @"calloc"(i64 %".1", i64 %".2")

declare void @"free"(i8* %".1")

declare void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".1", i8* %".2", i64 %".3", i1 %".4")

declare void @"llvm.memmove.p0i8.p0i8.i64"(i8* %".1", i8* %".2", i64 %".3", i1 %".4")

declare void @"llvm.memset.p0i8.i64"(i8* %".1", i8 %".2", i64 %".3", i1 %".4")

declare void @"exit"(i32 %".1")

@"__silu_line" = internal global i64 0
define void @"silu_panic"(i8* %".1")
{
entry:
  %".3" = getelementptr [3 x i8], [3 x i8]* @"str._25s", i32 0, i32 0
  %".4" = call i32 (i8*, ...) @"printf"(i8* %".3", i8* %".1")
  %".5" = load i64, i64* @"__silu_line"
  %".6" = icmp sgt i64 %".5", 0
  br i1 %".6", label %"with_line", label %"no_line"
with_line:
  %".8" = getelementptr [12 x i8], [12 x i8]* @"str._20_28line_20_25d_29_0a", i32 0, i32 0
  %".9" = call i32 (i8*, ...) @"printf"(i8* %".8", i64 %".5")
  call void @"exit"(i32 1)
  unreachable
no_line:
  %".12" = getelementptr [2 x i8], [2 x i8]* @"str._0a", i32 0, i32 0
  %".13" = call i32 (i8*, ...) @"printf"(i8* %".12")
  call void @"exit"(i32 1)
  unreachable
}

@"str._25s" = constant [3 x i8] c"%s\00"
@"str._20_28line_20_25d_29_0a" = constant [12 x i8] c" (line %d)\0a\00"
@"str._0a" = constant [2 x i8] c"\0a\00"
declare i32 @"snprintf"(i8* %".1", i64 %".2", i8* %".3", ...)

declare double @"strtod"(i8* %".1", i8** %".2")

declare i8* @"memchr"(i8* %".1", i32 %".2", i64 %".3")

declare i64 @"strlen"(i8* %".1")

declare i32 @"memcmp"(i8* %".1", i8* %".2", i64 %".3")

declare double @"llvm.floor.f64"(double %".1")

declare {i64, i1} @"llvm.sadd.with.overflow.i64"(i64 %".1", i64 %".2")

declare {i64, i1} @"llvm.ssub.with.overflow.i64"(i64 %".1", i64 %".2")

declare {i64, i1} @"llvm.smul.with.overflow.i64"(i64 %".1", i64 %".2")

define {i32, i8*}* @"create_int"(i64 %".1")
{
entry:
  %".3" = call i8* @"malloc"(i64 16)
  %".4" = bitcast i8* %".3" to {i32, i8*}*
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 0
  store i32 0, i32* %".5"
  %".7" = call i8* @"malloc"(i64 8)
  %".8" = bitcast i8* %".7" to i64*
  store i64 %".1", i64* %".8"
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 1
  store i8* %".7", i8** %".10"
  ret {i32, i8*}* %".4"
}

define {i32, i8*}* @"create_str"(i8* %".1", i32 %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 16)
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  store i32 2, i32* %".6"
  %".8" = call i8* @"malloc"(i64 16)
  %".9" = bitcast i8* %".8" to {i32, i8*}*
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 0
  store i32 %".2", i32* %".10"
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 1
  store i8* %".1", i8** %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  store i8* %".8", i8** %".14"
  ret {i32, i8*}* %".5"
}

define {i32, i8*}* @"create_bool"(i1 %".1")
{
entry:
  %".3" = call i8* @"malloc"(i64 16)
  %".4" = bitcast i8* %".3" to {i32, i8*}*
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 0
  store i32 3, i32* %".5"
  %".7" = call i8* @"malloc"(i64 8)
  %".8" = bitcast i8* %".7" to i64*
  %".9" = zext i1 %".1" to i64
  store i64 %".9", i64* %".8"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 1
  store i8* %".7", i8** %".11"
  ret {i32, i8*}* %".4"
}

define {i32, i8*}* @"create_float"(double %".1")
{
entry:
  %".3" = call i8* @"malloc"(i64 16)
  %".4" = bitcast i8* %".3" to {i32, i8*}*
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 0
  store i32 1, i32* %".5"
  %".7" = call i8* @"malloc"(i64 8)
  %".8" = bitcast i8* %".7" to double*
  store double %".1", double* %".8"
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".4", i32 0, i32 1
  store i8* %".7", i8** %".10"
  ret {i32, i8*}* %".4"
}

define {i32, i8*}* @"create_list"()
{
entry:
  %".2" = call i8* @"malloc"(i64 16)
  %".3" = bitcast i8* %".2" to {i32, i8*}*
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 0
  store i32 4, i32* %".4"
  %".6" = call i8* @"malloc"(i64 24)
  %".7" = bitcast i8* %".6" to {i64, i64, {i32, i8*}**}*
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 0
  store i64 0, i64* %".8"
  %".10" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 1
  store i64 0, i64* %".10"
  %".12" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 2
  store {i32, i8*}** null, {i32, i8*}*** %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 1
  store i8* %".6", i8** %".14"
  ret {i32, i8*}* %".3"
}

define {i32, i8*}* @"pyobj_add"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".6" = load i32, i32* %".4"
  %".7" = load i32, i32* %".5"
  %".8" = icmp eq i32 %".6", 0
  %".9" = icmp eq i32 %".6", 1
  %".10" = icmp eq i32 %".6", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"float_check", label %"str_check"
float_check:
  %".20" = icmp eq i32 %".6", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"float_add", label %"int_add"
str_check:
  %".66" = icmp eq i32 %".6", 2
  %".67" = icmp eq i32 %".7", 2
  %".68" = and i1 %".66", %".67"
  br i1 %".68", label %"str_concat", label %"list_check"
str_concat:
  %".117" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".118" = load i8*, i8** %".117"
  %".119" = bitcast i8* %".118" to {i32, i8*}*
  %".120" = getelementptr {i32, i8*}, {i32, i8*}* %".119", i32 0, i32 0
  %".121" = load i32, i32* %".120"
  %".122" = getelementptr {i32, i8*}, {i32, i8*}* %".119", i32 0, i32 1
  %".123" = load i8*, i8** %".122"
  %".124" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".125" = load i8*, i8** %".124"
  %".126" = bitcast i8* %".125" to {i32, i8*}*
  %".127" = getelementptr {i32, i8*}, {i32, i8*}* %".126", i32 0, i32 0
  %".128" = load i32, i32* %".127"
  %".129" = getelementptr {i32, i8*}, {i32, i8*}* %".126", i32 0, i32 1
  %".130" = load i8*, i8** %".129"
  %".131" = zext i32 %".121" to i64
  %".132" = zext i32 %".128" to i64
  %".133" = add i64 %".131", %".132"
  %".134" = add i64 %".133", 1
  %".135" = call i8* @"malloc"(i64 %".134")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".135", i8* %".123", i64 %".131", i1 0)
  %".137" = getelementptr i8, i8* %".135", i64 %".131"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".137", i8* %".130", i64 %".132", i1 0)
  %".139" = getelementptr i8, i8* %".135", i64 %".133"
  store i8 0, i8* %".139"
  %".141" = trunc i64 %".133" to i32
  %".142" = call {i32, i8*}* @"create_str"(i8* %".135", i32 %".141")
  ret {i32, i8*}* %".142"
error:
  %".144" = getelementptr [43 x i8], [43 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20_2b", i32 0, i32 0
  call void @"silu_panic"(i8* %".144")
  unreachable
int_add:
  %".49" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".50" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".51" = load i8*, i8** %".49"
  %".52" = load i8*, i8** %".50"
  %".53" = bitcast i8* %".51" to i64*
  %".54" = bitcast i8* %".52" to i64*
  %".55" = load i64, i64* %".53"
  %".56" = load i64, i64* %".54"
  %".57" = call {i64, i1} @"llvm.sadd.with.overflow.i64"(i64 %".55", i64 %".56")
  %".58" = extractvalue {i64, i1} %".57", 0
  %".59" = extractvalue {i64, i1} %".57", 1
  br i1 %".59", label %"overflow", label %"success"
float_add:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to double*
  %".27" = load double, double* %".26"
  %".28" = bitcast i8* %".25" to i64*
  %".29" = load i64, i64* %".28"
  %".30" = sitofp i64 %".29" to double
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = icmp eq i32 %".32", 1
  %".34" = select  i1 %".33", double %".27", double %".30"
  %".35" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".36" = load i8*, i8** %".35"
  %".37" = bitcast i8* %".36" to double*
  %".38" = load double, double* %".37"
  %".39" = bitcast i8* %".36" to i64*
  %".40" = load i64, i64* %".39"
  %".41" = sitofp i64 %".40" to double
  %".42" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".43" = load i32, i32* %".42"
  %".44" = icmp eq i32 %".43", 1
  %".45" = select  i1 %".44", double %".38", double %".41"
  %".46" = fadd double %".34", %".45"
  %".47" = call {i32, i8*}* @"create_float"(double %".46")
  ret {i32, i8*}* %".47"
overflow:
  %".61" = getelementptr [36 x i8], [36 x i8]* @"str.Error_3a_20Integer_20overflow_20in_20addition", i32 0, i32 0
  call void @"silu_panic"(i8* %".61")
  unreachable
success:
  %".64" = call {i32, i8*}* @"create_int"(i64 %".58")
  ret {i32, i8*}* %".64"
list_check:
  %".70" = icmp eq i32 %".6", 4
  %".71" = icmp eq i32 %".7", 4
  %".72" = and i1 %".70", %".71"
  br i1 %".72", label %"list_concat", label %"error"
list_concat:
  %".74" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".75" = load i8*, i8** %".74"
  %".76" = bitcast i8* %".75" to {i64, i64, {i32, i8*}**}*
  %".77" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".78" = load i8*, i8** %".77"
  %".79" = bitcast i8* %".78" to {i64, i64, {i32, i8*}**}*
  %".80" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".76", i32 0, i32 0
  %".81" = load i64, i64* %".80"
  %".82" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".79", i32 0, i32 0
  %".83" = load i64, i64* %".82"
  %".84" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".76", i32 0, i32 2
  %".85" = load {i32, i8*}**, {i32, i8*}*** %".84"
  %".86" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".79", i32 0, i32 2
  %".87" = load {i32, i8*}**, {i32, i8*}*** %".86"
  %".88" = add i64 %".81", %".83"
  %".89" = call {i32, i8*}* @"create_list"()
  %".90" = getelementptr {i32, i8*}, {i32, i8*}* %".89", i32 0, i32 1
  %".91" = load i8*, i8** %".90"
  %".92" = bitcast i8* %".91" to {i64, i64, {i32, i8*}**}*
  %".93" = mul i64 %".88", 8
  %".94" = call i8* @"malloc"(i64 %".93")
  %".95" = icmp sgt i64 %".81", 0
  br i1 %".95", label %"concat_copy_left", label %"concat_after_left"
concat_copy_left:
  %".97" = bitcast {i32, i8*}** %".85" to i8*
  %".98" = mul i64 %".81", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".94", i8* %".97", i64 %".98", i1 0)
  br label %"concat_after_left"
concat_after_left:
  %".101" = icmp sgt i64 %".83", 0
  br i1 %".101", label %"concat_copy_right", label %"concat_after_right"
concat_copy_right:
  %".103" = mul i64 %".81", 8
  %".104" = getelementptr i8, i8* %".94", i64 %".103"
  %".105" = bitcast {i32, i8*}** %".87" to i8*
  %".106" = mul i64 %".83", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".104", i8* %".105", i64 %".106", i1 0)
  br label %"concat_after_right"
concat_after_right:
  %".109" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".92", i32 0, i32 0
  store i64 %".88", i64* %".109"
  %".111" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".92", i32 0, i32 1
  store i64 %".88", i64* %".111"
  %".113" = bitcast i8* %".94" to {i32, i8*}**
  %".114" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".92", i32 0, i32 2
  store {i32, i8*}** %".113", {i32, i8*}*** %".114"
  ret {i32, i8*}* %".89"
}

@"str.Error_3a_20Integer_20overflow_20in_20addition" = constant [36 x i8] c"Error: Integer overflow in addition\00"
@"str.TypeError_3a_20unsupported_20operand_20types_20for_20_2b" = constant [43 x i8] c"TypeError: unsupported operand types for +\00"
define {i32, i8*}* @"str_repeat"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = sext i32 %".8" to i64
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to i64*
  %".15" = load i64, i64* %".14"
  %".16" = icmp slt i64 %".15", 0
  %".17" = select  i1 %".16", i64 0, i64 %".15"
  %".18" = mul i64 %".11", %".17"
  %".19" = add i64 %".18", 1
  %".20" = call i8* @"malloc"(i64 %".19")
  %"rep_i" = alloca i64
  store i64 0, i64* %"rep_i"
  br label %"rep_cond"
rep_cond:
  %".23" = load i64, i64* %"rep_i"
  %".24" = icmp slt i64 %".23", %".17"
  br i1 %".24", label %"rep_body", label %"rep_done"
rep_body:
  %".26" = load i64, i64* %"rep_i"
  %".27" = mul i64 %".26", %".11"
  %".28" = getelementptr i8, i8* %".20", i64 %".27"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".28", i8* %".10", i64 %".11", i1 0)
  %".30" = load i64, i64* %"rep_i"
  %".31" = add i64 %".30", 1
  store i64 %".31", i64* %"rep_i"
  br label %"rep_cond"
rep_done:
  %".34" = getelementptr i8, i8* %".20", i64 %".18"
  store i8 0, i8* %".34"
  %".36" = trunc i64 %".18" to i32
  %".37" = call {i32, i8*}* @"create_str"(i8* %".20", i32 %".36")
  ret {i32, i8*}* %".37"
}

define {i32, i8*}* @"list_repeat"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".10" = load {i32, i8*}**, {i32, i8*}*** %".9"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to i64*
  %".14" = load i64, i64* %".13"
  %".15" = icmp slt i64 %".14", 0
  %".16" = select  i1 %".15", i64 0, i64 %".14"
  %".17" = mul i64 %".8", %".16"
  %".18" = mul i64 %".17", 8
  %".19" = call i8* @"malloc"(i64 %".18")
  %"lrep_i" = alloca i64
  store i64 0, i64* %"lrep_i"
  br label %"lrep_cond"
lrep_cond:
  %".22" = load i64, i64* %"lrep_i"
  %".23" = icmp slt i64 %".22", %".16"
  br i1 %".23", label %"lrep_body", label %"lrep_done"
lrep_body:
  %".25" = load i64, i64* %"lrep_i"
  %".26" = mul i64 %".25", %".8"
  %".27" = bitcast i8* %".19" to {i32, i8*}**
  %".28" = getelementptr {i32, i8*}*, {i32, i8*}** %".27", i64 %".26"
  %".29" = bitcast {i32, i8*}** %".28" to i8*
  %".30" = bitcast {i32, i8*}** %".10" to i8*
  %".31" = mul i64 %".8", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".29", i8* %".30", i64 %".31", i1 0)
  %".33" = load i64, i64* %"lrep_i"
  %".34" = add i64 %".33", 1
  store i64 %".34", i64* %"lrep_i"
  br label %"lrep_cond"
lrep_done:
  %".37" = call i8* @"malloc"(i64 16)
  %".38" = bitcast i8* %".37" to {i32, i8*}*
  %".39" = getelementptr {i32, i8*}, {i32, i8*}* %".38", i32 0, i32 0
  store i32 4, i32* %".39"
  %".41" = call i8* @"malloc"(i64 24)
  %".42" = bitcast i8* %".41" to {i64, i64, {i32, i8*}**}*
  %".43" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".42", i32 0, i32 0
  store i64 %".17", i64* %".43"
  %".45" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".42", i32 0, i32 1
  store i64 %".17", i64* %".45"
  %".47" = bitcast i8* %".19" to {i32, i8*}**
  %".48" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".42", i32 0, i32 2
  store {i32, i8*}** %".47", {i32, i8*}*** %".48"
  %".50" = getelementptr {i32, i8*}, {i32, i8*}* %".38", i32 0, i32 1
  store i8* %".41", i8** %".50"
  ret {i32, i8*}* %".38"
}

define {i32, i8*}* @"pyobj_sub"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"float_op", label %"int_op"
float_op:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to double*
  %".27" = load double, double* %".26"
  %".28" = bitcast i8* %".25" to i64*
  %".29" = load i64, i64* %".28"
  %".30" = sitofp i64 %".29" to double
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = icmp eq i32 %".32", 1
  %".34" = select  i1 %".33", double %".27", double %".30"
  %".35" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".36" = load i8*, i8** %".35"
  %".37" = bitcast i8* %".36" to double*
  %".38" = load double, double* %".37"
  %".39" = bitcast i8* %".36" to i64*
  %".40" = load i64, i64* %".39"
  %".41" = sitofp i64 %".40" to double
  %".42" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".43" = load i32, i32* %".42"
  %".44" = icmp eq i32 %".43", 1
  %".45" = select  i1 %".44", double %".38", double %".41"
  %".46" = fsub double %".34", %".45"
  %".47" = call {i32, i8*}* @"create_float"(double %".46")
  ret {i32, i8*}* %".47"
int_op:
  %".49" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".50" = load i8*, i8** %".49"
  %".51" = bitcast i8* %".50" to i64*
  %".52" = load i64, i64* %".51"
  %".53" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".54" = load i8*, i8** %".53"
  %".55" = bitcast i8* %".54" to i64*
  %".56" = load i64, i64* %".55"
  %".57" = call {i64, i1} @"llvm.ssub.with.overflow.i64"(i64 %".52", i64 %".56")
  %".58" = extractvalue {i64, i1} %".57", 0
  %".59" = extractvalue {i64, i1} %".57", 1
  br i1 %".59", label %"int_overflow", label %"int_no_overflow"
error:
  %".66" = getelementptr [45 x i8], [45 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20sub", i32 0, i32 0
  call void @"silu_panic"(i8* %".66")
  unreachable
int_overflow:
  %".61" = getelementptr [39 x i8], [39 x i8]* @"str.OverflowError_3a_20integer_20overflow_20in_20sub", i32 0, i32 0
  call void @"silu_panic"(i8* %".61")
  unreachable
int_no_overflow:
  %".64" = call {i32, i8*}* @"create_int"(i64 %".58")
  ret {i32, i8*}* %".64"
}

@"str.OverflowError_3a_20integer_20overflow_20in_20sub" = constant [39 x i8] c"OverflowError: integer overflow in sub\00"
@"str.TypeError_3a_20unsupported_20operand_20types_20for_20sub" = constant [45 x i8] c"TypeError: unsupported operand types for sub\00"
define {i32, i8*}* @"pyobj_mul"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  %".19" = icmp eq i32 %".5", 2
  %".20" = icmp eq i32 %".7", 0
  %".21" = icmp eq i32 %".7", 3
  %".22" = or i1 %".20", %".21"
  %".23" = and i1 %".19", %".22"
  %".24" = icmp eq i32 %".7", 2
  %".25" = icmp eq i32 %".5", 0
  %".26" = icmp eq i32 %".5", 3
  %".27" = or i1 %".25", %".26"
  %".28" = and i1 %".24", %".27"
  %".29" = or i1 %".23", %".28"
  br i1 %".29", label %"str_op", label %"str_gate"
num_check:
  %".54" = icmp eq i32 %".5", 1
  %".55" = icmp eq i32 %".7", 1
  %".56" = or i1 %".54", %".55"
  br i1 %".56", label %"float_op", label %"int_op"
float_op:
  %".58" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".59" = load i8*, i8** %".58"
  %".60" = bitcast i8* %".59" to double*
  %".61" = load double, double* %".60"
  %".62" = bitcast i8* %".59" to i64*
  %".63" = load i64, i64* %".62"
  %".64" = sitofp i64 %".63" to double
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".66" = load i32, i32* %".65"
  %".67" = icmp eq i32 %".66", 1
  %".68" = select  i1 %".67", double %".61", double %".64"
  %".69" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".70" = load i8*, i8** %".69"
  %".71" = bitcast i8* %".70" to double*
  %".72" = load double, double* %".71"
  %".73" = bitcast i8* %".70" to i64*
  %".74" = load i64, i64* %".73"
  %".75" = sitofp i64 %".74" to double
  %".76" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".77" = load i32, i32* %".76"
  %".78" = icmp eq i32 %".77", 1
  %".79" = select  i1 %".78", double %".72", double %".75"
  %".80" = fmul double %".68", %".79"
  %".81" = call {i32, i8*}* @"create_float"(double %".80")
  ret {i32, i8*}* %".81"
int_op:
  %".83" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".84" = load i8*, i8** %".83"
  %".85" = bitcast i8* %".84" to i64*
  %".86" = load i64, i64* %".85"
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = bitcast i8* %".88" to i64*
  %".90" = load i64, i64* %".89"
  %".91" = call {i64, i1} @"llvm.smul.with.overflow.i64"(i64 %".86", i64 %".90")
  %".92" = extractvalue {i64, i1} %".91", 0
  %".93" = extractvalue {i64, i1} %".91", 1
  br i1 %".93", label %"int_overflow", label %"int_no_overflow"
str_op:
  %".31" = icmp eq i32 %".5", 2
  %".32" = select  i1 %".31", {i32, i8*}* %".1", {i32, i8*}* %".2"
  %".33" = select  i1 %".31", {i32, i8*}* %".2", {i32, i8*}* %".1"
  %".34" = call {i32, i8*}* @"str_repeat"({i32, i8*}* %".32", {i32, i8*}* %".33")
  ret {i32, i8*}* %".34"
error:
  %".100" = getelementptr [45 x i8], [45 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20mul", i32 0, i32 0
  call void @"silu_panic"(i8* %".100")
  unreachable
str_gate:
  %".36" = icmp eq i32 %".5", 4
  %".37" = icmp eq i32 %".7", 0
  %".38" = icmp eq i32 %".7", 3
  %".39" = or i1 %".37", %".38"
  %".40" = and i1 %".36", %".39"
  %".41" = icmp eq i32 %".7", 4
  %".42" = icmp eq i32 %".5", 0
  %".43" = icmp eq i32 %".5", 3
  %".44" = or i1 %".42", %".43"
  %".45" = and i1 %".41", %".44"
  %".46" = or i1 %".40", %".45"
  br i1 %".46", label %"list_op", label %"list_gate"
list_op:
  %".48" = icmp eq i32 %".5", 4
  %".49" = select  i1 %".48", {i32, i8*}* %".1", {i32, i8*}* %".2"
  %".50" = select  i1 %".48", {i32, i8*}* %".2", {i32, i8*}* %".1"
  %".51" = call {i32, i8*}* @"list_repeat"({i32, i8*}* %".49", {i32, i8*}* %".50")
  ret {i32, i8*}* %".51"
list_gate:
  br i1 %".18", label %"num_check", label %"error"
int_overflow:
  %".95" = getelementptr [39 x i8], [39 x i8]* @"str.OverflowError_3a_20integer_20overflow_20in_20mul", i32 0, i32 0
  call void @"silu_panic"(i8* %".95")
  unreachable
int_no_overflow:
  %".98" = call {i32, i8*}* @"create_int"(i64 %".92")
  ret {i32, i8*}* %".98"
}

@"str.OverflowError_3a_20integer_20overflow_20in_20mul" = constant [39 x i8] c"OverflowError: integer overflow in mul\00"
@"str.TypeError_3a_20unsupported_20operand_20types_20for_20mul" = constant [45 x i8] c"TypeError: unsupported operand types for mul\00"
define {i32, i8*}* @"pyobj_truediv"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br label %"float_op"
float_op:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to double*
  %".27" = load double, double* %".26"
  %".28" = bitcast i8* %".25" to i64*
  %".29" = load i64, i64* %".28"
  %".30" = sitofp i64 %".29" to double
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = icmp eq i32 %".32", 1
  %".34" = select  i1 %".33", double %".27", double %".30"
  %".35" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".36" = load i8*, i8** %".35"
  %".37" = bitcast i8* %".36" to double*
  %".38" = load double, double* %".37"
  %".39" = bitcast i8* %".36" to i64*
  %".40" = load i64, i64* %".39"
  %".41" = sitofp i64 %".40" to double
  %".42" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".43" = load i32, i32* %".42"
  %".44" = icmp eq i32 %".43", 1
  %".45" = select  i1 %".44", double %".38", double %".41"
  %".46" = fcmp oeq double %".45",              0x0
  br i1 %".46", label %"float_zero", label %"float_ok"
error:
  %".54" = getelementptr [49 x i8], [49 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20truediv", i32 0, i32 0
  call void @"silu_panic"(i8* %".54")
  unreachable
float_zero:
  %".48" = getelementptr [36 x i8], [36 x i8]* @"str.ZeroDivisionError_3a_20division_20by_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".48")
  unreachable
float_ok:
  %".51" = fdiv double %".34", %".45"
  %".52" = call {i32, i8*}* @"create_float"(double %".51")
  ret {i32, i8*}* %".52"
}

@"str.ZeroDivisionError_3a_20division_20by_20zero" = constant [36 x i8] c"ZeroDivisionError: division by zero\00"
@"str.TypeError_3a_20unsupported_20operand_20types_20for_20truediv" = constant [49 x i8] c"TypeError: unsupported operand types for truediv\00"
define {i32, i8*}* @"pyobj_floordiv"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"float_op", label %"int_op"
float_op:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to double*
  %".27" = load double, double* %".26"
  %".28" = bitcast i8* %".25" to i64*
  %".29" = load i64, i64* %".28"
  %".30" = sitofp i64 %".29" to double
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = icmp eq i32 %".32", 1
  %".34" = select  i1 %".33", double %".27", double %".30"
  %".35" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".36" = load i8*, i8** %".35"
  %".37" = bitcast i8* %".36" to double*
  %".38" = load double, double* %".37"
  %".39" = bitcast i8* %".36" to i64*
  %".40" = load i64, i64* %".39"
  %".41" = sitofp i64 %".40" to double
  %".42" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".43" = load i32, i32* %".42"
  %".44" = icmp eq i32 %".43", 1
  %".45" = select  i1 %".44", double %".38", double %".41"
  %".46" = fcmp oeq double %".45",              0x0
  br i1 %".46", label %"float_zero", label %"float_ok"
int_op:
  %".55" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".56" = load i8*, i8** %".55"
  %".57" = bitcast i8* %".56" to i64*
  %".58" = load i64, i64* %".57"
  %".59" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".60" = load i8*, i8** %".59"
  %".61" = bitcast i8* %".60" to i64*
  %".62" = load i64, i64* %".61"
  %".63" = icmp eq i64 %".62", 0
  br i1 %".63", label %"int_zero", label %"int_ok"
error:
  %".79" = getelementptr [50 x i8], [50 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20floordiv", i32 0, i32 0
  call void @"silu_panic"(i8* %".79")
  unreachable
float_zero:
  %".48" = getelementptr [36 x i8], [36 x i8]* @"str.ZeroDivisionError_3a_20division_20by_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".48")
  unreachable
float_ok:
  %".51" = fdiv double %".34", %".45"
  %".52" = call double @"llvm.floor.f64"(double %".51")
  %".53" = call {i32, i8*}* @"create_float"(double %".52")
  ret {i32, i8*}* %".53"
int_zero:
  %".65" = getelementptr [36 x i8], [36 x i8]* @"str.ZeroDivisionError_3a_20division_20by_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".65")
  unreachable
int_ok:
  %".68" = sdiv i64 %".58", %".62"
  %".69" = srem i64 %".58", %".62"
  %".70" = icmp ne i64 %".69", 0
  %".71" = icmp slt i64 %".69", 0
  %".72" = icmp slt i64 %".62", 0
  %".73" = xor i1 %".71", %".72"
  %".74" = and i1 %".70", %".73"
  %".75" = select  i1 %".74", i64 -1, i64 0
  %".76" = add i64 %".68", %".75"
  %".77" = call {i32, i8*}* @"create_int"(i64 %".76")
  ret {i32, i8*}* %".77"
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20floordiv" = constant [50 x i8] c"TypeError: unsupported operand types for floordiv\00"
define {i32, i8*}* @"pyobj_mod"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"float_op", label %"int_op"
float_op:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to double*
  %".27" = load double, double* %".26"
  %".28" = bitcast i8* %".25" to i64*
  %".29" = load i64, i64* %".28"
  %".30" = sitofp i64 %".29" to double
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = icmp eq i32 %".32", 1
  %".34" = select  i1 %".33", double %".27", double %".30"
  %".35" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".36" = load i8*, i8** %".35"
  %".37" = bitcast i8* %".36" to double*
  %".38" = load double, double* %".37"
  %".39" = bitcast i8* %".36" to i64*
  %".40" = load i64, i64* %".39"
  %".41" = sitofp i64 %".40" to double
  %".42" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".43" = load i32, i32* %".42"
  %".44" = icmp eq i32 %".43", 1
  %".45" = select  i1 %".44", double %".38", double %".41"
  %".46" = fcmp oeq double %".45",              0x0
  br i1 %".46", label %"float_zero", label %"float_ok"
int_op:
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".62" = load i8*, i8** %".61"
  %".63" = bitcast i8* %".62" to i64*
  %".64" = load i64, i64* %".63"
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".66" = load i8*, i8** %".65"
  %".67" = bitcast i8* %".66" to i64*
  %".68" = load i64, i64* %".67"
  %".69" = icmp eq i64 %".68", 0
  br i1 %".69", label %"int_zero", label %"int_ok"
error:
  %".84" = getelementptr [45 x i8], [45 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20mod", i32 0, i32 0
  call void @"silu_panic"(i8* %".84")
  unreachable
float_zero:
  %".48" = getelementptr [36 x i8], [36 x i8]* @"str.ZeroDivisionError_3a_20division_20by_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".48")
  unreachable
float_ok:
  %".51" = frem double %".34", %".45"
  %".52" = fcmp one double %".51",              0x0
  %".53" = fcmp olt double %".51",              0x0
  %".54" = fcmp olt double %".45",              0x0
  %".55" = xor i1 %".53", %".54"
  %".56" = and i1 %".52", %".55"
  %".57" = fadd double %".51", %".45"
  %".58" = select  i1 %".56", double %".57", double %".51"
  %".59" = call {i32, i8*}* @"create_float"(double %".58")
  ret {i32, i8*}* %".59"
int_zero:
  %".71" = getelementptr [36 x i8], [36 x i8]* @"str.ZeroDivisionError_3a_20division_20by_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".71")
  unreachable
int_ok:
  %".74" = srem i64 %".64", %".68"
  %".75" = icmp ne i64 %".74", 0
  %".76" = icmp slt i64 %".74", 0
  %".77" = icmp slt i64 %".68", 0
  %".78" = xor i1 %".76", %".77"
  %".79" = and i1 %".75", %".78"
  %".80" = select  i1 %".79", i64 %".68", i64 0
  %".81" = add i64 %".74", %".80"
  %".82" = call {i32, i8*}* @"create_int"(i64 %".81")
  ret {i32, i8*}* %".82"
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20mod" = constant [45 x i8] c"TypeError: unsupported operand types for mod\00"
define {i32, i8*}* @"pyobj_bitor"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"error", label %"int_op"
float_op:
  unreachable
int_op:
  %".25" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".26" = load i8*, i8** %".25"
  %".27" = bitcast i8* %".26" to i64*
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".30" = load i8*, i8** %".29"
  %".31" = bitcast i8* %".30" to i64*
  %".32" = load i64, i64* %".31"
  %".33" = or i64 %".28", %".32"
  %".34" = call {i32, i8*}* @"create_int"(i64 %".33")
  ret {i32, i8*}* %".34"
error:
  %".36" = getelementptr [47 x i8], [47 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitor", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitor" = constant [47 x i8] c"TypeError: unsupported operand types for bitor\00"
define {i32, i8*}* @"pyobj_bitand"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"error", label %"int_op"
float_op:
  unreachable
int_op:
  %".25" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".26" = load i8*, i8** %".25"
  %".27" = bitcast i8* %".26" to i64*
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".30" = load i8*, i8** %".29"
  %".31" = bitcast i8* %".30" to i64*
  %".32" = load i64, i64* %".31"
  %".33" = and i64 %".28", %".32"
  %".34" = call {i32, i8*}* @"create_int"(i64 %".33")
  ret {i32, i8*}* %".34"
error:
  %".36" = getelementptr [48 x i8], [48 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitand", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitand" = constant [48 x i8] c"TypeError: unsupported operand types for bitand\00"
define {i32, i8*}* @"pyobj_bitxor"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"error", label %"int_op"
float_op:
  unreachable
int_op:
  %".25" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".26" = load i8*, i8** %".25"
  %".27" = bitcast i8* %".26" to i64*
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".30" = load i8*, i8** %".29"
  %".31" = bitcast i8* %".30" to i64*
  %".32" = load i64, i64* %".31"
  %".33" = xor i64 %".28", %".32"
  %".34" = call {i32, i8*}* @"create_int"(i64 %".33")
  ret {i32, i8*}* %".34"
error:
  %".36" = getelementptr [48 x i8], [48 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitxor", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20bitxor" = constant [48 x i8] c"TypeError: unsupported operand types for bitxor\00"
define {i32, i8*}* @"pyobj_shl"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"error", label %"int_op"
float_op:
  unreachable
int_op:
  %".25" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".26" = load i8*, i8** %".25"
  %".27" = bitcast i8* %".26" to i64*
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".30" = load i8*, i8** %".29"
  %".31" = bitcast i8* %".30" to i64*
  %".32" = load i64, i64* %".31"
  %".33" = shl i64 %".28", %".32"
  %".34" = call {i32, i8*}* @"create_int"(i64 %".33")
  ret {i32, i8*}* %".34"
error:
  %".36" = getelementptr [45 x i8], [45 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20shl", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20shl" = constant [45 x i8] c"TypeError: unsupported operand types for shl\00"
define {i32, i8*}* @"pyobj_shr"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = icmp eq i32 %".5", 0
  %".9" = icmp eq i32 %".5", 1
  %".10" = icmp eq i32 %".5", 3
  %".11" = or i1 %".9", %".10"
  %".12" = or i1 %".8", %".11"
  %".13" = icmp eq i32 %".7", 0
  %".14" = icmp eq i32 %".7", 1
  %".15" = icmp eq i32 %".7", 3
  %".16" = or i1 %".14", %".15"
  %".17" = or i1 %".13", %".16"
  %".18" = and i1 %".12", %".17"
  br i1 %".18", label %"num_check", label %"error"
num_check:
  %".20" = icmp eq i32 %".5", 1
  %".21" = icmp eq i32 %".7", 1
  %".22" = or i1 %".20", %".21"
  br i1 %".22", label %"error", label %"int_op"
float_op:
  unreachable
int_op:
  %".25" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".26" = load i8*, i8** %".25"
  %".27" = bitcast i8* %".26" to i64*
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".30" = load i8*, i8** %".29"
  %".31" = bitcast i8* %".30" to i64*
  %".32" = load i64, i64* %".31"
  %".33" = ashr i64 %".28", %".32"
  %".34" = call {i32, i8*}* @"create_int"(i64 %".33")
  ret {i32, i8*}* %".34"
error:
  %".36" = getelementptr [45 x i8], [45 x i8]* @"str.TypeError_3a_20unsupported_20operand_20types_20for_20shr", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.TypeError_3a_20unsupported_20operand_20types_20for_20shr" = constant [45 x i8] c"TypeError: unsupported operand types for shr\00"
define {i32, i8*}* @"pyobj_make_instance"(i64 %".1", i8* %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 16)
  %".5" = bitcast i8* %".4" to {i64, i8*}*
  %".6" = getelementptr {i64, i8*}, {i64, i8*}* %".5", i32 0, i32 0
  store i64 %".1", i64* %".6"
  %".8" = getelementptr {i64, i8*}, {i64, i8*}* %".5", i32 0, i32 1
  store i8* %".2", i8** %".8"
  %".10" = call i8* @"malloc"(i64 16)
  %".11" = bitcast i8* %".10" to {i32, i8*}*
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".11", i32 0, i32 0
  store i32 6, i32* %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".11", i32 0, i32 1
  store i8* %".4", i8** %".14"
  ret {i32, i8*}* %".11"
}

define i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i8*}*
  %".6" = getelementptr {i64, i8*}, {i64, i8*}* %".5", i32 0, i32 1
  %".7" = load i8*, i8** %".6"
  ret i8* %".7"
}

@"silu_no_cid" = global i64 -1
define i64 @"pyobj_instance_cid"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 6
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".7" = load i8*, i8** %".6"
  %".8" = bitcast i8* %".7" to {i64, i8*}*
  %".9" = getelementptr {i64, i8*}, {i64, i8*}* %".8", i32 0, i32 0
  %".10" = select  i1 %".5", i64* %".9", i64* @"silu_no_cid"
  %".11" = load i64, i64* %".10"
  ret i64 %".11"
}

define {i32, i8*}* @"pyobj_fnref"(i64 %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 16)
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  store i32 7, i32* %".6"
  %".8" = call i8* @"malloc"(i64 16)
  %".9" = bitcast i8* %".8" to {i64, {i32, i8*}*}*
  %".10" = getelementptr {i64, {i32, i8*}*}, {i64, {i32, i8*}*}* %".9", i32 0, i32 0
  store i64 %".1", i64* %".10"
  %".12" = getelementptr {i64, {i32, i8*}*}, {i64, {i32, i8*}*}* %".9", i32 0, i32 1
  store {i32, i8*}* %".2", {i32, i8*}** %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  store i8* %".8", i8** %".14"
  ret {i32, i8*}* %".5"
}

define {i32, i8*}* @"pyobj_fn_self"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, {i32, i8*}*}*
  %".6" = getelementptr {i64, {i32, i8*}*}, {i64, {i32, i8*}*}* %".5", i32 0, i32 1
  %".7" = load {i32, i8*}*, {i32, i8*}** %".6"
  ret {i32, i8*}* %".7"
}

define i64 @"pyobj_fn_index"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to i64*
  %".6" = load i64, i64* %".5"
  ret i64 %".6"
}

define i8* @"float_repr"(double %".1")
{
entry:
  %".3" = call i8* @"malloc"(i64 40)
  %".4" = getelementptr [6 x i8], [6 x i8]* @"str._25.15g", i32 0, i32 0
  %".5" = call i32 (i8*, i64, i8*, ...) @"snprintf"(i8* %".3", i64 40, i8* %".4", double %".1")
  %".6" = call i8* @"malloc"(i64 8)
  %".7" = bitcast i8* %".6" to i8**
  %".8" = call double @"strtod"(i8* %".3", i8** %".7")
  %".9" = fcmp oeq double %".8", %".1"
  br i1 %".9", label %"finish", label %"retry"
retry:
  %".11" = call i8* @"malloc"(i64 40)
  %".12" = getelementptr [6 x i8], [6 x i8]* @"str._25.16g", i32 0, i32 0
  %".13" = call i32 (i8*, i64, i8*, ...) @"snprintf"(i8* %".11", i64 40, i8* %".12", double %".1")
  %".14" = call i8* @"malloc"(i64 8)
  %".15" = bitcast i8* %".14" to i8**
  %".16" = call double @"strtod"(i8* %".11", i8** %".15")
  %".17" = fcmp oeq double %".16", %".1"
  br i1 %".17", label %"finish", label %"more_digits"
more_digits:
  %".19" = call i8* @"malloc"(i64 40)
  %".20" = getelementptr [6 x i8], [6 x i8]* @"str._25.17g", i32 0, i32 0
  %".21" = call i32 (i8*, i64, i8*, ...) @"snprintf"(i8* %".19", i64 40, i8* %".20", double %".1")
  br label %"finish"
finish:
  %".23" = phi  i8* [%".3", %"entry"], [%".11", %"retry"], [%".19", %"more_digits"]
  %".24" = call i64 @"strlen"(i8* %".23")
  %".25" = call i8* @"memchr"(i8* %".23", i32 46, i64 %".24")
  %".26" = icmp ne i8* %".25", null
  %".27" = xor i1 %".26", -1
  %".28" = call i64 @"strlen"(i8* %".23")
  %".29" = call i8* @"memchr"(i8* %".23", i32 101, i64 %".28")
  %".30" = icmp ne i8* %".29", null
  %".31" = xor i1 %".30", -1
  %".32" = call i64 @"strlen"(i8* %".23")
  %".33" = call i8* @"memchr"(i8* %".23", i32 110, i64 %".32")
  %".34" = icmp ne i8* %".33", null
  %".35" = xor i1 %".34", -1
  %".36" = call i64 @"strlen"(i8* %".23")
  %".37" = call i8* @"memchr"(i8* %".23", i32 105, i64 %".36")
  %".38" = icmp ne i8* %".37", null
  %".39" = xor i1 %".38", -1
  %".40" = and i1 %".35", %".39"
  %".41" = and i1 %".31", %".40"
  %".42" = and i1 %".27", %".41"
  br i1 %".42", label %"append_dot", label %"done"
append_dot:
  %".44" = call i64 @"strlen"(i8* %".23")
  %".45" = getelementptr i8, i8* %".23", i64 %".44"
  store i8 46, i8* %".45"
  %".47" = add i64 %".44", 1
  %".48" = getelementptr i8, i8* %".23", i64 %".47"
  store i8 48, i8* %".48"
  %".50" = add i64 %".44", 2
  %".51" = getelementptr i8, i8* %".23", i64 %".50"
  store i8 0, i8* %".51"
  br label %"done"
done:
  ret i8* %".23"
}

@"str._25.15g" = constant [6 x i8] c"%.15g\00"
@"str._25.16g" = constant [6 x i8] c"%.16g\00"
@"str._25.17g" = constant [6 x i8] c"%.17g\00"
define void @"pyobj_print"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"print_null", label %"dispatch"
print_null:
  %".5" = getelementptr [5 x i8], [5 x i8]* @"str.None", i32 0, i32 0
  %".6" = call i32 (i8*, ...) @"printf"(i8* %".5")
  ret void
dispatch:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".9" = load i32, i32* %".8"
  switch i32 %".9", label %"default" [i32 0, label %"print_int" i32 1, label %"print_float" i32 2, label %"print_str" i32 3, label %"print_bool" i32 4, label %"print_list" i32 8, label %"print_list" i32 5, label %"print_dict"]
print_int:
  %".103" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".104" = load i8*, i8** %".103"
  %".105" = bitcast i8* %".104" to i64*
  %".106" = load i64, i64* %".105"
  %".107" = getelementptr [4 x i8], [4 x i8]* @"str._25ld", i32 0, i32 0
  %".108" = call i32 (i8*, ...) @"printf"(i8* %".107", i64 %".106")
  ret void
print_float:
  %".85" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".86" = load i8*, i8** %".85"
  %".87" = bitcast i8* %".86" to double*
  %".88" = load double, double* %".87"
  %".89" = call i8* @"float_repr"(double %".88")
  %".90" = getelementptr [3 x i8], [3 x i8]* @"str._25s", i32 0, i32 0
  %".91" = call i32 (i8*, ...) @"printf"(i8* %".90", i8* %".89")
  ret void
print_str:
  %".110" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".111" = load i8*, i8** %".110"
  %".112" = bitcast i8* %".111" to {i32, i8*}*
  %".113" = getelementptr {i32, i8*}, {i32, i8*}* %".112", i32 0, i32 1
  %".114" = load i8*, i8** %".113"
  %".115" = getelementptr {i32, i8*}, {i32, i8*}* %".112", i32 0, i32 0
  %".116" = load i32, i32* %".115"
  %".117" = getelementptr [5 x i8], [5 x i8]* @"str._25._2as", i32 0, i32 0
  %".118" = call i32 (i8*, ...) @"printf"(i8* %".117", i32 %".116", i8* %".114")
  ret void
print_bool:
  %".93" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".94" = load i8*, i8** %".93"
  %".95" = bitcast i8* %".94" to i64*
  %".96" = load i64, i64* %".95"
  %".97" = icmp ne i64 %".96", 0
  %".98" = getelementptr [5 x i8], [5 x i8]* @"str.True", i32 0, i32 0
  %".99" = getelementptr [6 x i8], [6 x i8]* @"str.False", i32 0, i32 0
  %".100" = select  i1 %".97", i8* %".98", i8* %".99"
  %".101" = call i32 (i8*, ...) @"printf"(i8* %".100")
  ret void
print_list:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i64, i64, {i32, i8*}**}*
  %".14" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 0
  %".15" = load i64, i64* %".14"
  %".16" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 2
  %".17" = load {i32, i8*}**, {i32, i8*}*** %".16"
  %".18" = getelementptr [2 x i8], [2 x i8]* @"str._5b", i32 0, i32 0
  %".19" = call i32 (i8*, ...) @"printf"(i8* %".18")
  %"list_print_idx" = alloca i64
  store i64 0, i64* %"list_print_idx"
  br label %"list_loop_check"
print_dict:
  %".40" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".41" = load i8*, i8** %".40"
  %".42" = bitcast i8* %".41" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".43" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".42", i32 0, i32 1
  %".44" = load i64, i64* %".43"
  %".45" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".42", i32 0, i32 4
  %".46" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".45"
  %".47" = getelementptr [2 x i8], [2 x i8]* @"str._7b", i32 0, i32 0
  %".48" = call i32 (i8*, ...) @"printf"(i8* %".47")
  %"dict_print_idx" = alloca i64
  %"dict_printed" = alloca i64
  store i64 0, i64* %"dict_print_idx"
  store i64 0, i64* %"dict_printed"
  br label %"dict_check"
default:
  %".120" = getelementptr [17 x i8], [17 x i8]* @"str._3cunknown_20object_3e", i32 0, i32 0
  %".121" = call i32 (i8*, ...) @"printf"(i8* %".120")
  ret void
list_loop_check:
  %".22" = load i64, i64* %"list_print_idx"
  %".23" = icmp slt i64 %".22", %".15"
  br i1 %".23", label %"list_loop_body", label %"list_done"
list_loop_body:
  %".25" = icmp sgt i64 %".22", 0
  br i1 %".25", label %"list_sep", label %"list_elem"
list_loop_incr:
  %".34" = add i64 %".22", 1
  store i64 %".34", i64* %"list_print_idx"
  br label %"list_loop_check"
list_done:
  %".37" = getelementptr [2 x i8], [2 x i8]* @"str._5d", i32 0, i32 0
  %".38" = call i32 (i8*, ...) @"printf"(i8* %".37")
  ret void
list_sep:
  %".27" = getelementptr [3 x i8], [3 x i8]* @"str._2c_20", i32 0, i32 0
  %".28" = call i32 (i8*, ...) @"printf"(i8* %".27")
  br label %"list_elem"
list_elem:
  %".30" = getelementptr {i32, i8*}*, {i32, i8*}** %".17", i64 %".22"
  %".31" = load {i32, i8*}*, {i32, i8*}** %".30"
  call void @"pyobj_repr_print"({i32, i8*}* %".31")
  br label %"list_loop_incr"
dict_check:
  %".52" = load i64, i64* %"dict_print_idx"
  %".53" = icmp slt i64 %".52", %".44"
  br i1 %".53", label %"dict_body", label %"dict_done"
dict_body:
  %".55" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".46", i32 0, i64 %".52"
  %".56" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".55", i32 0, i32 0
  %".57" = load {i32, i8*}*, {i32, i8*}** %".56"
  %".58" = icmp ne {i32, i8*}* %".57", null
  br i1 %".58", label %"dict_live", label %"dict_skip"
dict_sep:
  %".66" = getelementptr [3 x i8], [3 x i8]* @"str._2c_20", i32 0, i32 0
  %".67" = call i32 (i8*, ...) @"printf"(i8* %".66")
  br label %"dict_key"
dict_key:
  %".69" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".55", i32 0, i32 1
  %".70" = load {i32, i8*}*, {i32, i8*}** %".69"
  call void @"pyobj_repr_print"({i32, i8*}* %".57")
  %".72" = getelementptr [3 x i8], [3 x i8]* @"str._3a_20", i32 0, i32 0
  %".73" = call i32 (i8*, ...) @"printf"(i8* %".72")
  call void @"pyobj_repr_print"({i32, i8*}* %".70")
  br label %"dict_incr"
dict_incr:
  %".76" = load i64, i64* %"dict_printed"
  %".77" = add i64 %".76", 1
  store i64 %".77", i64* %"dict_printed"
  %".79" = add i64 %".52", 1
  store i64 %".79", i64* %"dict_print_idx"
  br label %"dict_check"
dict_done:
  %".82" = getelementptr [2 x i8], [2 x i8]* @"str._7d", i32 0, i32 0
  %".83" = call i32 (i8*, ...) @"printf"(i8* %".82")
  ret void
dict_skip:
  %".60" = add i64 %".52", 1
  store i64 %".60", i64* %"dict_print_idx"
  br label %"dict_check"
dict_live:
  %".63" = load i64, i64* %"dict_printed"
  %".64" = icmp sgt i64 %".63", 0
  br i1 %".64", label %"dict_sep", label %"dict_key"
}

define void @"pyobj_repr_print"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 2
  br i1 %".5", label %"repr_str", label %"repr_other"
repr_str:
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to {i32, i8*}*
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 1
  %".11" = load i8*, i8** %".10"
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 0
  %".13" = load i32, i32* %".12"
  %".14" = getelementptr [7 x i8], [7 x i8]* @"str._27_25._2as_27", i32 0, i32 0
  %".15" = call i32 (i8*, ...) @"printf"(i8* %".14", i32 %".13", i8* %".11")
  ret void
repr_other:
  call void @"pyobj_print"({i32, i8*}* %".1")
  ret void
}

@"str._27_25._2as_27" = constant [7 x i8] c"'%.*s'\00"
@"str.None" = constant [5 x i8] c"None\00"
@"str._5b" = constant [2 x i8] c"[\00"
@"str._2c_20" = constant [3 x i8] c", \00"
@"str._5d" = constant [2 x i8] c"]\00"
@"str._7b" = constant [2 x i8] c"{\00"
@"str._3a_20" = constant [3 x i8] c": \00"
@"str._7d" = constant [2 x i8] c"}\00"
@"str.True" = constant [5 x i8] c"True\00"
@"str.False" = constant [6 x i8] c"False\00"
@"str._25ld" = constant [4 x i8] c"%ld\00"
@"str._25._2as" = constant [5 x i8] c"%.*s\00"
@"str._3cunknown_20object_3e" = constant [17 x i8] c"<unknown object>\00"
define {i32, i8*}* @"list_append"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 1
  %".10" = load i64, i64* %".9"
  %".11" = icmp eq i64 %".8", %".10"
  br i1 %".11", label %"grow", label %"do_append"
grow:
  %".13" = icmp eq i64 %".10", 0
  %".14" = mul i64 %".10", 2
  %".15" = select  i1 %".13", i64 4, i64 %".14"
  %".16" = mul i64 %".15", 8
  %".17" = call i8* @"malloc"(i64 %".16")
  %".18" = icmp sgt i64 %".10", 0
  br i1 %".18", label %"grow_copy", label %"grow_after_copy"
do_append:
  %".32" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".33" = load {i32, i8*}**, {i32, i8*}*** %".32"
  %".34" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".35" = load i64, i64* %".34"
  %".36" = getelementptr {i32, i8*}*, {i32, i8*}** %".33", i64 %".35"
  store {i32, i8*}* %".2", {i32, i8*}** %".36"
  %".38" = add i64 %".35", 1
  %".39" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  store i64 %".38", i64* %".39"
  ret {i32, i8*}* %".1"
grow_copy:
  %".20" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".21" = load {i32, i8*}**, {i32, i8*}*** %".20"
  %".22" = bitcast {i32, i8*}** %".21" to i8*
  %".23" = mul i64 %".10", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".17", i8* %".22", i64 %".23", i1 0)
  br label %"grow_after_copy"
grow_after_copy:
  %".26" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 1
  store i64 %".15", i64* %".26"
  %".28" = bitcast i8* %".17" to {i32, i8*}**
  %".29" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  store {i32, i8*}** %".28", {i32, i8*}*** %".29"
  br label %"do_append"
}

define i64 @"list_length"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  ret i64 %".7"
}

define i64 @"pyobj_iter_len"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 2
  br i1 %".5", label %"str_len_case", label %"list_len_case"
str_len_case:
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to {i32, i8*}*
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 0
  %".11" = load i32, i32* %".10"
  %".12" = sext i32 %".11" to i64
  ret i64 %".12"
list_len_case:
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".15" = load i8*, i8** %".14"
  %".16" = bitcast i8* %".15" to {i64, i64, {i32, i8*}**}*
  %".17" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".16", i32 0, i32 0
  %".18" = load i64, i64* %".17"
  ret i64 %".18"
}

define {i32, i8*}* @"list_get"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = bitcast i8* %".10" to i64*
  %".12" = load i64, i64* %".11"
  %".13" = icmp slt i64 %".12", 0
  br i1 %".13", label %"negative", label %"bounds"
bounds:
  %".17" = phi  i64 [%".12", %"entry"], [%".15", %"negative"]
  %".18" = icmp sge i64 %".17", 0
  %".19" = icmp slt i64 %".17", %".8"
  %".20" = and i1 %".18", %".19"
  br i1 %".20", label %"ok", label %"index_error"
negative:
  %".15" = add i64 %".12", %".8"
  br label %"bounds"
ok:
  %".25" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".26" = load {i32, i8*}**, {i32, i8*}*** %".25"
  %".27" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 %".17"
  %".28" = load {i32, i8*}*, {i32, i8*}** %".27"
  ret {i32, i8*}* %".28"
index_error:
  %".22" = getelementptr [36 x i8], [36 x i8]* @"str.IndexError_3a_20list_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".22")
  unreachable
}

@"str.IndexError_3a_20list_20index_20out_20of_20range" = constant [36 x i8] c"IndexError: list index out of range\00"
define void @"list_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, {i32, i8*}**}*
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".11" = load i8*, i8** %".10"
  %".12" = bitcast i8* %".11" to i64*
  %".13" = load i64, i64* %".12"
  %".14" = icmp slt i64 %".13", 0
  br i1 %".14", label %"negative", label %"bounds"
negative:
  %".16" = add i64 %".13", %".9"
  br label %"bounds"
bounds:
  %".18" = phi  i64 [%".13", %"entry"], [%".16", %"negative"]
  %".19" = icmp sge i64 %".18", 0
  %".20" = icmp slt i64 %".18", %".9"
  %".21" = and i1 %".19", %".20"
  br i1 %".21", label %"ok", label %"index_error"
ok:
  %".26" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 2
  %".27" = load {i32, i8*}**, {i32, i8*}*** %".26"
  %".28" = getelementptr {i32, i8*}*, {i32, i8*}** %".27", i64 %".18"
  store {i32, i8*}* %".3", {i32, i8*}** %".28"
  ret void
index_error:
  %".23" = getelementptr [47 x i8], [47 x i8]* @"str.IndexError_3a_20list_20assignment_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".23")
  unreachable
}

@"str.IndexError_3a_20list_20assignment_20index_20out_20of_20range" = constant [47 x i8] c"IndexError: list assignment index out of range\00"
define {i32, i8*}* @"pyobj_len"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 4
  %".6" = icmp eq i32 %".4", 8
  %".7" = or i1 %".5", %".6"
  br i1 %".7", label %"len_list", label %"str_check"
len_list:
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = bitcast i8* %".10" to {i64, i64, {i32, i8*}**}*
  %".12" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".11", i32 0, i32 0
  %".13" = load i64, i64* %".12"
  %".14" = call {i32, i8*}* @"create_int"(i64 %".13")
  ret {i32, i8*}* %".14"
str_check:
  %".16" = icmp eq i32 %".4", 2
  br i1 %".16", label %"len_str", label %"dict_check"
len_str:
  %".18" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".19" = load i8*, i8** %".18"
  %".20" = bitcast i8* %".19" to {i32, i8*}*
  %".21" = getelementptr {i32, i8*}, {i32, i8*}* %".20", i32 0, i32 0
  %".22" = load i32, i32* %".21"
  %".23" = sext i32 %".22" to i64
  %".24" = call {i32, i8*}* @"create_int"(i64 %".23")
  ret {i32, i8*}* %".24"
dict_check:
  %".26" = icmp eq i32 %".4", 5
  br i1 %".26", label %"len_dict", label %"error"
len_dict:
  %".28" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".29" = load i8*, i8** %".28"
  %".30" = bitcast i8* %".29" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".31" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".30", i32 0, i32 0
  %".32" = load i64, i64* %".31"
  %".33" = call {i32, i8*}* @"create_int"(i64 %".32")
  ret {i32, i8*}* %".33"
error:
  ret {i32, i8*}* null
}

define i64 @"pyobj_len_raw"({i32, i8*}* %".1")
{
rlr_entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 4
  %".6" = icmp eq i32 %".4", 8
  %".7" = or i1 %".5", %".6"
  br i1 %".7", label %"rlr_list", label %"rlr_str_chk"
rlr_list:
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = bitcast i8* %".10" to {i64, i64, {i32, i8*}**}*
  %".12" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".11", i32 0, i32 0
  %".13" = load i64, i64* %".12"
  ret i64 %".13"
rlr_str_chk:
  %".15" = icmp eq i32 %".4", 2
  br i1 %".15", label %"rlr_str", label %"rlr_dict_chk"
rlr_str:
  %".17" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".18" = load i8*, i8** %".17"
  %".19" = bitcast i8* %".18" to {i32, i8*}*
  %".20" = getelementptr {i32, i8*}, {i32, i8*}* %".19", i32 0, i32 0
  %".21" = load i32, i32* %".20"
  %".22" = sext i32 %".21" to i64
  ret i64 %".22"
rlr_dict_chk:
  %".24" = icmp eq i32 %".4", 5
  br i1 %".24", label %"rlr_dict", label %"rlr_zero"
rlr_dict:
  %".26" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".27" = load i8*, i8** %".26"
  %".28" = bitcast i8* %".27" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".29" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".28", i32 0, i32 0
  %".30" = load i64, i64* %".29"
  ret i64 %".30"
rlr_zero:
  ret i64 0
}

define i1 @"pyobj_truthy"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"truthy_false", label %"dispatch"
dispatch:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  switch i32 %".6", label %"truthy_true" [i32 0, label %"truthy_int" i32 1, label %"truthy_float" i32 2, label %"truthy_str" i32 3, label %"truthy_int" i32 4, label %"truthy_list" i32 8, label %"truthy_list" i32 5, label %"truthy_dict"]
truthy_int:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = bitcast i8* %".9" to i64*
  %".11" = load i64, i64* %".10"
  %".12" = icmp ne i64 %".11", 0
  ret i1 %".12"
truthy_float:
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".15" = load i8*, i8** %".14"
  %".16" = bitcast i8* %".15" to double*
  %".17" = load double, double* %".16"
  %".18" = bitcast i8* %".15" to i64*
  %".19" = load i64, i64* %".18"
  %".20" = sitofp i64 %".19" to double
  %".21" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".22" = load i32, i32* %".21"
  %".23" = icmp eq i32 %".22", 1
  %".24" = select  i1 %".23", double %".17", double %".20"
  %".25" = fcmp one double %".24",              0x0
  ret i1 %".25"
truthy_str:
  %".27" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".28" = load i8*, i8** %".27"
  %".29" = bitcast i8* %".28" to {i32, i8*}*
  %".30" = getelementptr {i32, i8*}, {i32, i8*}* %".29", i32 0, i32 0
  %".31" = load i32, i32* %".30"
  %".32" = icmp ne i32 %".31", 0
  ret i1 %".32"
truthy_list:
  %".34" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".35" = load i8*, i8** %".34"
  %".36" = bitcast i8* %".35" to {i64, i64, {i32, i8*}**}*
  %".37" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".36", i32 0, i32 0
  %".38" = load i64, i64* %".37"
  %".39" = icmp ne i64 %".38", 0
  ret i1 %".39"
truthy_dict:
  %".41" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".42" = load i8*, i8** %".41"
  %".43" = bitcast i8* %".42" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".44" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".43", i32 0, i32 0
  %".45" = load i64, i64* %".44"
  %".46" = icmp ne i64 %".45", 0
  ret i1 %".46"
truthy_true:
  ret i1 1
truthy_false:
  ret i1 0
}

define i1 @"pyobj_deep_eq"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = and i1 %".4", %".5"
  %".7" = or i1 %".4", %".5"
  br i1 %".7", label %"null_check", label %"tag_check"
dispatch:
  %".28" = icmp eq i32 %".11", 0
  %".29" = icmp eq i32 %".11", 1
  %".30" = icmp eq i32 %".11", 3
  %".31" = or i1 %".29", %".30"
  %".32" = or i1 %".28", %".31"
  %".33" = icmp eq i32 %".11", 2
  %".34" = icmp eq i32 %".11", 4
  br i1 %".32", label %"num_check", label %"str_check"
num_check:
  %".36" = icmp eq i32 %".11", 1
  %".37" = icmp eq i32 %".13", 1
  %".38" = or i1 %".36", %".37"
  br i1 %".38", label %"num_float", label %"num_int"
num_float:
  %".40" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".41" = load i8*, i8** %".40"
  %".42" = bitcast i8* %".41" to double*
  %".43" = load double, double* %".42"
  %".44" = bitcast i8* %".41" to i64*
  %".45" = load i64, i64* %".44"
  %".46" = sitofp i64 %".45" to double
  %".47" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".48" = load i32, i32* %".47"
  %".49" = icmp eq i32 %".48", 1
  %".50" = select  i1 %".49", double %".43", double %".46"
  %".51" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".52" = load i8*, i8** %".51"
  %".53" = bitcast i8* %".52" to double*
  %".54" = load double, double* %".53"
  %".55" = bitcast i8* %".52" to i64*
  %".56" = load i64, i64* %".55"
  %".57" = sitofp i64 %".56" to double
  %".58" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".59" = load i32, i32* %".58"
  %".60" = icmp eq i32 %".59", 1
  %".61" = select  i1 %".60", double %".54", double %".57"
  %".62" = fcmp oeq double %".50", %".61"
  ret i1 %".62"
num_int:
  %".64" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".65" = load i8*, i8** %".64"
  %".66" = bitcast i8* %".65" to i64*
  %".67" = load i64, i64* %".66"
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".69" = load i8*, i8** %".68"
  %".70" = bitcast i8* %".69" to i64*
  %".71" = load i64, i64* %".70"
  %".72" = icmp eq i64 %".67", %".71"
  ret i1 %".72"
str_check:
  br i1 %".33", label %"str_body", label %"list_check"
str_body:
  %".75" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".76" = load i8*, i8** %".75"
  %".77" = bitcast i8* %".76" to {i32, i8*}*
  %".78" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".79" = load i8*, i8** %".78"
  %".80" = bitcast i8* %".79" to {i32, i8*}*
  %".81" = getelementptr {i32, i8*}, {i32, i8*}* %".77", i32 0, i32 0
  %".82" = load i32, i32* %".81"
  %".83" = getelementptr {i32, i8*}, {i32, i8*}* %".80", i32 0, i32 0
  %".84" = load i32, i32* %".83"
  %".85" = getelementptr {i32, i8*}, {i32, i8*}* %".77", i32 0, i32 1
  %".86" = load i8*, i8** %".85"
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".80", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = icmp eq i32 %".82", %".84"
  br i1 %".89", label %"str_cmp", label %"eq_false"
list_check:
  %".95" = icmp eq i32 %".11", 6
  br i1 %".34", label %"list_body", label %"inst_gate"
list_body:
  %".102" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".103" = load i8*, i8** %".102"
  %".104" = bitcast i8* %".103" to {i64, i64, {i32, i8*}**}*
  %".105" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".106" = load i8*, i8** %".105"
  %".107" = bitcast i8* %".106" to {i64, i64, {i32, i8*}**}*
  %".108" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".104", i32 0, i32 0
  %".109" = load i64, i64* %".108"
  %".110" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".107", i32 0, i32 0
  %".111" = load i64, i64* %".110"
  %".112" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".104", i32 0, i32 2
  %".113" = load {i32, i8*}**, {i32, i8*}*** %".112"
  %".114" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".107", i32 0, i32 2
  %".115" = load {i32, i8*}**, {i32, i8*}*** %".114"
  %".116" = icmp eq i64 %".109", %".111"
  br i1 %".116", label %"list_len_bad", label %"eq_false"
list_len_bad:
  %"deep_diff" = alloca i1
  store i1 0, i1* %"deep_diff"
  %"deep_i" = alloca i64
  store i64 0, i64* %"deep_i"
  br label %"deep_cond"
eq_false:
  ret i1 0
tag_check:
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".11" = load i32, i32* %".10"
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".13" = load i32, i32* %".12"
  %".14" = icmp eq i32 %".11", %".13"
  %".15" = icmp eq i32 %".11", 0
  %".16" = icmp eq i32 %".11", 1
  %".17" = icmp eq i32 %".11", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".13", 0
  %".21" = icmp eq i32 %".13", 1
  %".22" = icmp eq i32 %".13", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  %".26" = or i1 %".14", %".25"
  br i1 %".26", label %"dispatch", label %"eq_false"
null_check:
  ret i1 %".6"
str_cmp:
  %".91" = sext i32 %".82" to i64
  %".92" = call i32 @"memcmp"(i8* %".86", i8* %".88", i64 %".91")
  %".93" = icmp eq i32 %".92", 0
  ret i1 %".93"
inst_body:
  %".98" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".99" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".100" = icmp eq i8* %".98", %".99"
  ret i1 %".100"
inst_gate:
  br i1 %".95", label %"inst_body", label %"eq_false"
deep_cond:
  %".121" = load i64, i64* %"deep_i"
  %".122" = icmp slt i64 %".121", %".109"
  br i1 %".122", label %"deep_body", label %"deep_after"
deep_body:
  %".124" = getelementptr {i32, i8*}*, {i32, i8*}** %".113", i64 %".121"
  %".125" = load {i32, i8*}*, {i32, i8*}** %".124"
  %".126" = getelementptr {i32, i8*}*, {i32, i8*}** %".115", i64 %".121"
  %".127" = load {i32, i8*}*, {i32, i8*}** %".126"
  %".128" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".125", {i32, i8*}* %".127")
  %".129" = xor i1 %".128", -1
  br i1 %".129", label %"deep_set_diff", label %"deep_next"
deep_after:
  %".136" = load i1, i1* %"deep_diff"
  %".137" = xor i1 %".136", -1
  ret i1 %".137"
deep_set_diff:
  store i1 1, i1* %"deep_diff"
  br label %"deep_next"
deep_next:
  %".133" = add i64 %".121", 1
  store i64 %".133", i64* %"deep_i"
  br label %"deep_cond"
}

define i64 @"pyobj_list_cmp"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to {i64, i64, {i32, i8*}**}*
  %".10" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".9", i32 0, i32 0
  %".13" = load i64, i64* %".12"
  %".14" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".15" = load {i32, i8*}**, {i32, i8*}*** %".14"
  %".16" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".9", i32 0, i32 2
  %".17" = load {i32, i8*}**, {i32, i8*}*** %".16"
  %"lc_i" = alloca i64
  store i64 0, i64* %"lc_i"
  br label %"lc_cond"
lc_cond:
  %".20" = load i64, i64* %"lc_i"
  %".21" = icmp slt i64 %".11", %".13"
  %".22" = select  i1 %".21", i64 %".11", i64 %".13"
  %".23" = icmp slt i64 %".20", %".22"
  br i1 %".23", label %"lc_body", label %"lc_after"
lc_body:
  %".25" = getelementptr {i32, i8*}*, {i32, i8*}** %".15", i64 %".20"
  %".26" = load {i32, i8*}*, {i32, i8*}** %".25"
  %".27" = getelementptr {i32, i8*}*, {i32, i8*}** %".17", i64 %".20"
  %".28" = load {i32, i8*}*, {i32, i8*}** %".27"
  %".29" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".26", {i32, i8*}* %".28")
  br i1 %".29", label %"lc_step", label %"lc_neq"
lc_step:
  %".112" = add i64 %".20", 1
  store i64 %".112", i64* %"lc_i"
  br label %"lc_cond"
lc_after:
  %".115" = icmp slt i64 %".11", %".13"
  %".116" = icmp sgt i64 %".11", %".13"
  %".117" = select  i1 %".116", i64 1, i64 0
  %".118" = select  i1 %".115", i64 -1, i64 %".117"
  ret i64 %".118"
lc_neq:
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".26", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = getelementptr {i32, i8*}, {i32, i8*}* %".28", i32 0, i32 0
  %".34" = load i32, i32* %".33"
  %".35" = icmp eq i32 %".32", 4
  %".36" = icmp eq i32 %".34", 4
  %".37" = and i1 %".35", %".36"
  %".38" = icmp eq i32 %".32", 0
  %".39" = icmp eq i32 %".32", 1
  %".40" = icmp eq i32 %".32", 3
  %".41" = or i1 %".39", %".40"
  %".42" = or i1 %".38", %".41"
  %".43" = icmp eq i32 %".34", 0
  %".44" = icmp eq i32 %".34", 1
  %".45" = icmp eq i32 %".34", 3
  %".46" = or i1 %".44", %".45"
  %".47" = or i1 %".43", %".46"
  %".48" = and i1 %".42", %".47"
  %".49" = icmp eq i32 %".32", 2
  %".50" = icmp eq i32 %".34", 2
  %".51" = and i1 %".49", %".50"
  br i1 %".37", label %"lc_as_list", label %"lc_not_list"
lc_as_list:
  %".53" = call i64 @"pyobj_list_cmp"({i32, i8*}* %".26", {i32, i8*}* %".28")
  ret i64 %".53"
lc_not_list:
  br i1 %".48", label %"lc_as_num", label %"lc_not_num"
lc_as_num:
  %".56" = getelementptr {i32, i8*}, {i32, i8*}* %".26", i32 0, i32 1
  %".57" = load i8*, i8** %".56"
  %".58" = bitcast i8* %".57" to double*
  %".59" = load double, double* %".58"
  %".60" = bitcast i8* %".57" to i64*
  %".61" = load i64, i64* %".60"
  %".62" = sitofp i64 %".61" to double
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".26", i32 0, i32 0
  %".64" = load i32, i32* %".63"
  %".65" = icmp eq i32 %".64", 1
  %".66" = select  i1 %".65", double %".59", double %".62"
  %".67" = getelementptr {i32, i8*}, {i32, i8*}* %".28", i32 0, i32 1
  %".68" = load i8*, i8** %".67"
  %".69" = bitcast i8* %".68" to double*
  %".70" = load double, double* %".69"
  %".71" = bitcast i8* %".68" to i64*
  %".72" = load i64, i64* %".71"
  %".73" = sitofp i64 %".72" to double
  %".74" = getelementptr {i32, i8*}, {i32, i8*}* %".28", i32 0, i32 0
  %".75" = load i32, i32* %".74"
  %".76" = icmp eq i32 %".75", 1
  %".77" = select  i1 %".76", double %".70", double %".73"
  %".78" = fcmp olt double %".66", %".77"
  %".79" = select  i1 %".78", i64 -1, i64 1
  ret i64 %".79"
lc_not_num:
  br i1 %".51", label %"lc_as_str", label %"lc_bad"
lc_as_str:
  %".82" = getelementptr {i32, i8*}, {i32, i8*}* %".26", i32 0, i32 1
  %".83" = load i8*, i8** %".82"
  %".84" = bitcast i8* %".83" to {i32, i8*}*
  %".85" = getelementptr {i32, i8*}, {i32, i8*}* %".84", i32 0, i32 0
  %".86" = load i32, i32* %".85"
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".84", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = getelementptr {i32, i8*}, {i32, i8*}* %".28", i32 0, i32 1
  %".90" = load i8*, i8** %".89"
  %".91" = bitcast i8* %".90" to {i32, i8*}*
  %".92" = getelementptr {i32, i8*}, {i32, i8*}* %".91", i32 0, i32 0
  %".93" = load i32, i32* %".92"
  %".94" = getelementptr {i32, i8*}, {i32, i8*}* %".91", i32 0, i32 1
  %".95" = load i8*, i8** %".94"
  %".96" = icmp slt i32 %".86", %".93"
  %".97" = select  i1 %".96", i32 %".86", i32 %".93"
  %".98" = sext i32 %".97" to i64
  %".99" = call i32 @"memcmp"(i8* %".88", i8* %".95", i64 %".98")
  %".100" = sext i32 %".99" to i64
  %".101" = icmp eq i64 %".100", 0
  %".102" = sext i32 %".86" to i64
  %".103" = sext i32 %".93" to i64
  %".104" = sub i64 %".102", %".103"
  %".105" = select  i1 %".101", i64 %".104", i64 %".100"
  %".106" = icmp slt i64 %".105", 0
  %".107" = select  i1 %".106", i64 -1, i64 1
  ret i64 %".107"
lc_bad:
  %".109" = getelementptr [52 x i8], [52 x i8]* @"str.TypeError_3a_20_27_3c_27_20not_20supported_20between_20these_20operands", i32 0, i32 0
  call void @"silu_panic"(i8* %".109")
  unreachable
}

@"str.TypeError_3a_20_27_3c_27_20not_20supported_20between_20these_20operands" = constant [52 x i8] c"TypeError: '<' not supported between these operands\00"
define {i32, i8*}* @"list_reverse"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %".10" = sdiv i64 %".7", 2
  %"rev_i" = alloca i64
  store i64 0, i64* %"rev_i"
  br label %"rev_cond"
rev_cond:
  %".13" = load i64, i64* %"rev_i"
  %".14" = icmp slt i64 %".13", %".10"
  br i1 %".14", label %"rev_body", label %"rev_done"
rev_body:
  %".16" = sub i64 %".7", 1
  %".17" = load i64, i64* %"rev_i"
  %".18" = sub i64 %".16", %".17"
  %".19" = load i64, i64* %"rev_i"
  %".20" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".19"
  %".21" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".18"
  %".22" = load {i32, i8*}*, {i32, i8*}** %".20"
  %".23" = load {i32, i8*}*, {i32, i8*}** %".21"
  store {i32, i8*}* %".23", {i32, i8*}** %".20"
  store {i32, i8*}* %".22", {i32, i8*}** %".21"
  %".26" = load i64, i64* %"rev_i"
  %".27" = add i64 %".26", 1
  store i64 %".27", i64* %"rev_i"
  br label %"rev_cond"
rev_done:
  ret {i32, i8*}* %".1"
}

define {i32, i8*}* @"list_insert"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, {i32, i8*}**}*
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 2
  %".11" = load {i32, i8*}**, {i32, i8*}*** %".10"
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to i64*
  %".15" = load i64, i64* %".14"
  %".16" = icmp slt i64 %".15", 0
  %".17" = add i64 %".15", %".9"
  %".18" = select  i1 %".16", i64 %".17", i64 %".15"
  %".19" = icmp slt i64 %".18", 0
  %".20" = select  i1 %".19", i64 0, i64 %".18"
  %".21" = icmp sgt i64 %".20", %".9"
  %".22" = select  i1 %".21", i64 %".9", i64 %".20"
  %".23" = add i64 %".9", 1
  %".24" = mul i64 %".23", 8
  %".25" = call i8* @"malloc"(i64 %".24")
  %".26" = bitcast i8* %".25" to {i32, i8*}**
  %"ins1_i" = alloca i64
  store i64 0, i64* %"ins1_i"
  br label %"ins1_cond"
ins1_cond:
  %".29" = load i64, i64* %"ins1_i"
  %".30" = icmp slt i64 %".29", %".22"
  br i1 %".30", label %"ins1_body", label %"ins1_done"
ins1_body:
  %".32" = load i64, i64* %"ins1_i"
  %".33" = getelementptr {i32, i8*}*, {i32, i8*}** %".11", i64 %".32"
  %".34" = load {i32, i8*}*, {i32, i8*}** %".33"
  %".35" = load i64, i64* %"ins1_i"
  %".36" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 %".35"
  store {i32, i8*}* %".34", {i32, i8*}** %".36"
  %".38" = load i64, i64* %"ins1_i"
  %".39" = add i64 %".38", 1
  store i64 %".39", i64* %"ins1_i"
  br label %"ins1_cond"
ins1_done:
  %".42" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 %".22"
  store {i32, i8*}* %".3", {i32, i8*}** %".42"
  %"ins2_i" = alloca i64
  store i64 %".22", i64* %"ins2_i"
  br label %"ins2_cond"
ins2_cond:
  %".46" = load i64, i64* %"ins2_i"
  %".47" = icmp slt i64 %".46", %".9"
  br i1 %".47", label %"ins2_body", label %"ins2_done"
ins2_body:
  %".49" = load i64, i64* %"ins2_i"
  %".50" = add i64 %".49", 1
  %".51" = load i64, i64* %"ins2_i"
  %".52" = getelementptr {i32, i8*}*, {i32, i8*}** %".11", i64 %".51"
  %".53" = load {i32, i8*}*, {i32, i8*}** %".52"
  %".54" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 %".50"
  store {i32, i8*}* %".53", {i32, i8*}** %".54"
  %".56" = load i64, i64* %"ins2_i"
  %".57" = add i64 %".56", 1
  store i64 %".57", i64* %"ins2_i"
  br label %"ins2_cond"
ins2_done:
  %".60" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 0
  store i64 %".23", i64* %".60"
  %".62" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 1
  store i64 %".23", i64* %".62"
  %".64" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 2
  store {i32, i8*}** %".26", {i32, i8*}*** %".64"
  ret {i32, i8*}* %".1"
}

define {i32, i8*}* @"list_count"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".10" = load {i32, i8*}**, {i32, i8*}*** %".9"
  %"count_acc" = alloca i64
  store i64 0, i64* %"count_acc"
  %"cnt_i" = alloca i64
  store i64 0, i64* %"cnt_i"
  br label %"cnt_cond"
cnt_cond:
  %".14" = load i64, i64* %"cnt_i"
  %".15" = icmp slt i64 %".14", %".8"
  br i1 %".15", label %"cnt_body", label %"cnt_done"
cnt_body:
  %".17" = load i64, i64* %"cnt_i"
  %".18" = getelementptr {i32, i8*}*, {i32, i8*}** %".10", i64 %".17"
  %".19" = load {i32, i8*}*, {i32, i8*}** %".18"
  %".20" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".19", {i32, i8*}* %".2")
  br i1 %".20", label %"cnt_acc", label %"cnt_next"
cnt_done:
  %".30" = load i64, i64* %"count_acc"
  %".31" = call {i32, i8*}* @"create_int"(i64 %".30")
  ret {i32, i8*}* %".31"
cnt_acc:
  %".22" = load i64, i64* %"count_acc"
  %".23" = add i64 %".22", 1
  store i64 %".23", i64* %"count_acc"
  br label %"cnt_next"
cnt_next:
  %".26" = load i64, i64* %"cnt_i"
  %".27" = add i64 %".26", 1
  store i64 %".27", i64* %"cnt_i"
  br label %"cnt_cond"
}

define {i32, i8*}* @"list_copy"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %".10" = call {i32, i8*}* @"create_list"()
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".10", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i64, i64, {i32, i8*}**}*
  %".14" = icmp eq i64 %".7", 0
  br i1 %".14", label %"cpy_after", label %"cpy_do"
cpy_do:
  %".16" = mul i64 %".7", 8
  %".17" = call i8* @"malloc"(i64 %".16")
  %".18" = bitcast {i32, i8*}** %".9" to i8*
  %".19" = mul i64 %".7", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".17", i8* %".18", i64 %".19", i1 0)
  %".21" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 0
  store i64 %".7", i64* %".21"
  %".23" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 1
  store i64 %".7", i64* %".23"
  %".25" = bitcast i8* %".17" to {i32, i8*}**
  %".26" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 2
  store {i32, i8*}** %".25", {i32, i8*}*** %".26"
  br label %"cpy_after"
cpy_after:
  ret {i32, i8*}* %".10"
}

define void @"list_clear"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  store i64 0, i64* %".6"
  ret void
}

define {i32, i8*}* @"list_sum"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %"sum_acc" = alloca {i32, i8*}*
  %".10" = call {i32, i8*}* @"create_int"(i64 0)
  store {i32, i8*}* %".10", {i32, i8*}** %"sum_acc"
  %"sum_i" = alloca i64
  store i64 0, i64* %"sum_i"
  br label %"sum_cond"
sum_cond:
  %".14" = load i64, i64* %"sum_i"
  %".15" = icmp slt i64 %".14", %".7"
  br i1 %".15", label %"sum_body", label %"sum_done"
sum_body:
  %".17" = load i64, i64* %"sum_i"
  %".18" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".17"
  %".19" = load {i32, i8*}*, {i32, i8*}** %".18"
  %".20" = load {i32, i8*}*, {i32, i8*}** %"sum_acc"
  %".21" = call {i32, i8*}* @"pyobj_add"({i32, i8*}* %".20", {i32, i8*}* %".19")
  store {i32, i8*}* %".21", {i32, i8*}** %"sum_acc"
  %".23" = load i64, i64* %"sum_i"
  %".24" = add i64 %".23", 1
  store i64 %".24", i64* %"sum_i"
  br label %"sum_cond"
sum_done:
  %".27" = load {i32, i8*}*, {i32, i8*}** %"sum_acc"
  ret {i32, i8*}* %".27"
}

define {i32, i8*}* @"str_upper"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = sext i32 %".7" to i64
  %".11" = add i64 %".10", 1
  %".12" = call i8* @"malloc"(i64 %".11")
  %".13" = sext i32 %".7" to i64
  %"fold_i" = alloca i64
  store i64 0, i64* %"fold_i"
  br label %"fold_cond"
fold_cond:
  %".16" = load i64, i64* %"fold_i"
  %".17" = icmp slt i64 %".16", %".13"
  br i1 %".17", label %"fold_body", label %"fold_done"
fold_body:
  %".19" = load i64, i64* %"fold_i"
  %".20" = getelementptr i8, i8* %".9", i64 %".19"
  %".21" = load i8, i8* %".20"
  %".22" = sext i8 %".21" to i32
  %".23" = icmp sge i32 %".22", 97
  %".24" = icmp sle i32 %".22", 122
  %".25" = and i1 %".23", %".24"
  %".26" = sub i8 %".21", 32
  %".27" = select  i1 %".25", i8 %".26", i8 %".21"
  %".28" = load i64, i64* %"fold_i"
  %".29" = getelementptr i8, i8* %".12", i64 %".28"
  store i8 %".27", i8* %".29"
  %".31" = load i64, i64* %"fold_i"
  %".32" = add i64 %".31", 1
  store i64 %".32", i64* %"fold_i"
  br label %"fold_cond"
fold_done:
  %".35" = sext i32 %".7" to i64
  %".36" = getelementptr i8, i8* %".12", i64 %".35"
  store i8 0, i8* %".36"
  %".38" = call {i32, i8*}* @"create_str"(i8* %".12", i32 %".7")
  ret {i32, i8*}* %".38"
}

define {i32, i8*}* @"str_lower"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = sext i32 %".7" to i64
  %".11" = add i64 %".10", 1
  %".12" = call i8* @"malloc"(i64 %".11")
  %".13" = sext i32 %".7" to i64
  %"fold_i" = alloca i64
  store i64 0, i64* %"fold_i"
  br label %"fold_cond"
fold_cond:
  %".16" = load i64, i64* %"fold_i"
  %".17" = icmp slt i64 %".16", %".13"
  br i1 %".17", label %"fold_body", label %"fold_done"
fold_body:
  %".19" = load i64, i64* %"fold_i"
  %".20" = getelementptr i8, i8* %".9", i64 %".19"
  %".21" = load i8, i8* %".20"
  %".22" = sext i8 %".21" to i32
  %".23" = icmp sge i32 %".22", 65
  %".24" = icmp sle i32 %".22", 90
  %".25" = and i1 %".23", %".24"
  %".26" = add i8 %".21", 32
  %".27" = select  i1 %".25", i8 %".26", i8 %".21"
  %".28" = load i64, i64* %"fold_i"
  %".29" = getelementptr i8, i8* %".12", i64 %".28"
  store i8 %".27", i8* %".29"
  %".31" = load i64, i64* %"fold_i"
  %".32" = add i64 %".31", 1
  store i64 %".32", i64* %"fold_i"
  br label %"fold_cond"
fold_done:
  %".35" = sext i32 %".7" to i64
  %".36" = getelementptr i8, i8* %".12", i64 %".35"
  store i8 0, i8* %".36"
  %".38" = call {i32, i8*}* @"create_str"(i8* %".12", i32 %".7")
  ret {i32, i8*}* %".38"
}

define {i32, i8*}* @"str_isdigit"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = sext i32 %".7" to i64
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = icmp eq i64 %".8", 0
  br i1 %".11", label %"pred_ret", label %"pred_loop"
pred_ret:
  %".33" = call {i32, i8*}* @"create_bool"(i1 1)
  ret {i32, i8*}* %".33"
pred_loop:
  %"pred_i" = alloca i64
  store i64 0, i64* %"pred_i"
  br label %"pred_cond"
pred_cond:
  %".15" = load i64, i64* %"pred_i"
  %".16" = icmp slt i64 %".15", %".8"
  br i1 %".16", label %"pred_body", label %"pred_ret"
pred_body:
  %".18" = load i64, i64* %"pred_i"
  %".19" = getelementptr i8, i8* %".10", i64 %".18"
  %".20" = load i8, i8* %".19"
  %".21" = icmp sge i8 %".20", 48
  %".22" = icmp sle i8 %".20", 57
  %".23" = and i1 %".21", %".22"
  %".24" = or i1 %".23", 0
  %".25" = or i1 0, %".24"
  br i1 %".25", label %"pred_step", label %"pred_false"
pred_false:
  %".27" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".27"
pred_step:
  %".29" = load i64, i64* %"pred_i"
  %".30" = add i64 %".29", 1
  store i64 %".30", i64* %"pred_i"
  br label %"pred_cond"
}

define {i32, i8*}* @"str_isalpha"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = sext i32 %".7" to i64
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = icmp eq i64 %".8", 0
  br i1 %".11", label %"pred_ret", label %"pred_loop"
pred_ret:
  %".38" = call {i32, i8*}* @"create_bool"(i1 1)
  ret {i32, i8*}* %".38"
pred_loop:
  %"pred_i" = alloca i64
  store i64 0, i64* %"pred_i"
  br label %"pred_cond"
pred_cond:
  %".15" = load i64, i64* %"pred_i"
  %".16" = icmp slt i64 %".15", %".8"
  br i1 %".16", label %"pred_body", label %"pred_ret"
pred_body:
  %".18" = load i64, i64* %"pred_i"
  %".19" = getelementptr i8, i8* %".10", i64 %".18"
  %".20" = load i8, i8* %".19"
  %".21" = icmp sge i8 %".20", 65
  %".22" = icmp sle i8 %".20", 90
  %".23" = and i1 %".21", %".22"
  %".24" = or i1 %".23", 0
  %".25" = or i1 0, %".24"
  %".26" = icmp sge i8 %".20", 97
  %".27" = icmp sle i8 %".20", 122
  %".28" = and i1 %".26", %".27"
  %".29" = or i1 %".28", 0
  %".30" = or i1 %".25", %".29"
  br i1 %".30", label %"pred_step", label %"pred_false"
pred_false:
  %".32" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".32"
pred_step:
  %".34" = load i64, i64* %"pred_i"
  %".35" = add i64 %".34", 1
  store i64 %".35", i64* %"pred_i"
  br label %"pred_cond"
}

define {i32, i8*}* @"str_isspace"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i32, i8*}*
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = sext i32 %".7" to i64
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".5", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = icmp eq i64 %".8", 0
  br i1 %".11", label %"pred_ret", label %"pred_loop"
pred_ret:
  %".40" = call {i32, i8*}* @"create_bool"(i1 1)
  ret {i32, i8*}* %".40"
pred_loop:
  %"pred_i" = alloca i64
  store i64 0, i64* %"pred_i"
  br label %"pred_cond"
pred_cond:
  %".15" = load i64, i64* %"pred_i"
  %".16" = icmp slt i64 %".15", %".8"
  br i1 %".16", label %"pred_body", label %"pred_ret"
pred_body:
  %".18" = load i64, i64* %"pred_i"
  %".19" = getelementptr i8, i8* %".10", i64 %".18"
  %".20" = load i8, i8* %".19"
  %".21" = icmp eq i8 %".20", 32
  %".22" = or i1 0, %".21"
  %".23" = icmp eq i8 %".20", 9
  %".24" = or i1 %".22", %".23"
  %".25" = icmp eq i8 %".20", 10
  %".26" = or i1 %".24", %".25"
  %".27" = icmp eq i8 %".20", 11
  %".28" = or i1 %".26", %".27"
  %".29" = icmp eq i8 %".20", 12
  %".30" = or i1 %".28", %".29"
  %".31" = icmp eq i8 %".20", 13
  %".32" = or i1 %".30", %".31"
  br i1 %".32", label %"pred_step", label %"pred_false"
pred_false:
  %".34" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".34"
pred_step:
  %".36" = load i64, i64* %"pred_i"
  %".37" = add i64 %".36", 1
  store i64 %".37", i64* %"pred_i"
  br label %"pred_cond"
}

define {i32, i8*}* @"str_find"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = sext i32 %".8" to i64
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to {i32, i8*}*
  %".15" = getelementptr {i32, i8*}, {i32, i8*}* %".14", i32 0, i32 0
  %".16" = load i32, i32* %".15"
  %".17" = getelementptr {i32, i8*}, {i32, i8*}* %".14", i32 0, i32 1
  %".18" = load i8*, i8** %".17"
  %".19" = sext i32 %".16" to i64
  %".20" = icmp sgt i64 %".19", %".11"
  br i1 %".20", label %"search_miss", label %"search_scan"
search_miss:
  %".22" = call {i32, i8*}* @"create_int"(i64 -1)
  ret {i32, i8*}* %".22"
search_scan:
  %".24" = sub i64 %".11", %".19"
  %".25" = add i64 %".24", 1
  %"search_i" = alloca i64
  store i64 0, i64* %"search_i"
  br label %"search_cond"
search_cond:
  %".28" = load i64, i64* %"search_i"
  %".29" = icmp slt i64 %".28", %".25"
  br i1 %".29", label %"search_body", label %"search_after"
search_body:
  %".31" = load i64, i64* %"search_i"
  %".32" = getelementptr i8, i8* %".10", i64 %".31"
  %".33" = call i32 @"memcmp"(i8* %".32", i8* %".18", i64 %".19")
  %".34" = icmp eq i32 %".33", 0
  br i1 %".34", label %"search_hit", label %"search_step"
search_after:
  %".41" = call {i32, i8*}* @"create_int"(i64 -1)
  ret {i32, i8*}* %".41"
search_hit:
  %".36" = call {i32, i8*}* @"create_int"(i64 %".31")
  ret {i32, i8*}* %".36"
search_step:
  %".38" = add i64 %".31", 1
  store i64 %".38", i64* %"search_i"
  br label %"search_cond"
}

define {i32, i8*}* @"str_rfind"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = sext i32 %".8" to i64
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to {i32, i8*}*
  %".15" = getelementptr {i32, i8*}, {i32, i8*}* %".14", i32 0, i32 0
  %".16" = load i32, i32* %".15"
  %".17" = getelementptr {i32, i8*}, {i32, i8*}* %".14", i32 0, i32 1
  %".18" = load i8*, i8** %".17"
  %".19" = sext i32 %".16" to i64
  %".20" = icmp sgt i64 %".19", %".11"
  br i1 %".20", label %"search_miss", label %"search_scan"
search_miss:
  %".22" = call {i32, i8*}* @"create_int"(i64 -1)
  ret {i32, i8*}* %".22"
search_scan:
  %".24" = sub i64 %".11", %".19"
  %".25" = add i64 %".24", 1
  %".26" = sub i64 %".25", 1
  %"search_i" = alloca i64
  store i64 %".26", i64* %"search_i"
  br label %"search_cond"
search_cond:
  %".29" = load i64, i64* %"search_i"
  %".30" = icmp sge i64 %".29", 0
  br i1 %".30", label %"search_body", label %"search_after"
search_body:
  %".32" = load i64, i64* %"search_i"
  %".33" = getelementptr i8, i8* %".10", i64 %".32"
  %".34" = call i32 @"memcmp"(i8* %".33", i8* %".18", i64 %".19")
  %".35" = icmp eq i32 %".34", 0
  br i1 %".35", label %"search_hit", label %"search_step"
search_after:
  %".42" = call {i32, i8*}* @"create_int"(i64 -1)
  ret {i32, i8*}* %".42"
search_hit:
  %".37" = call {i32, i8*}* @"create_int"(i64 %".32")
  ret {i32, i8*}* %".37"
search_step:
  %".39" = sub i64 %".32", 1
  store i64 %".39", i64* %"search_i"
  br label %"search_cond"
}

define {i32, i8*}* @"list_index"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".10" = load {i32, i8*}**, {i32, i8*}*** %".9"
  %"idx_found" = alloca i64
  store i64 -1, i64* %"idx_found"
  %"lidx_i" = alloca i64
  store i64 0, i64* %"lidx_i"
  br label %"lidx_cond"
lidx_cond:
  %".14" = load i64, i64* %"lidx_i"
  %".15" = icmp slt i64 %".14", %".8"
  br i1 %".15", label %"lidx_body", label %"lidx_done"
lidx_body:
  %".17" = load i64, i64* %"lidx_i"
  %".18" = getelementptr {i32, i8*}*, {i32, i8*}** %".10", i64 %".17"
  %".19" = load {i32, i8*}*, {i32, i8*}** %".18"
  %".20" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".19", {i32, i8*}* %".2")
  br i1 %".20", label %"lidx_hit", label %"lidx_next"
lidx_done:
  %".29" = load i64, i64* %"idx_found"
  %".30" = call {i32, i8*}* @"create_int"(i64 %".29")
  ret {i32, i8*}* %".30"
lidx_hit:
  %".22" = load i64, i64* %"lidx_i"
  store i64 %".22", i64* %"idx_found"
  br label %"lidx_done"
lidx_next:
  %".25" = load i64, i64* %"lidx_i"
  %".26" = add i64 %".25", 1
  store i64 %".26", i64* %"lidx_i"
  br label %"lidx_cond"
}

define {i32, i8*}* @"pyobj_iter_keys"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 4
  %".6" = icmp eq i32 %".4", 8
  %".7" = or i1 %".5", %".6"
  br i1 %".7", label %"as_list", label %"as_dict"
as_list:
  ret {i32, i8*}* %".1"
as_dict:
  %".10" = icmp eq i32 %".4", 5
  br i1 %".10", label %"dict_walk", label %"as_other"
as_other:
  %".42" = icmp eq i32 %".4", 2
  br i1 %".42", label %"as_str", label %"as_empty"
as_str:
  %".46" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".47" = load i8*, i8** %".46"
  %".48" = bitcast i8* %".47" to {i32, i8*}*
  %".49" = getelementptr {i32, i8*}, {i32, i8*}* %".48", i32 0, i32 0
  %".50" = load i32, i32* %".49"
  %".51" = getelementptr {i32, i8*}, {i32, i8*}* %".48", i32 0, i32 1
  %".52" = load i8*, i8** %".51"
  %".53" = sext i32 %".50" to i64
  %".54" = call {i32, i8*}* @"create_list"()
  %"ik_str_pos" = alloca i64
  store i64 0, i64* %"ik_str_pos"
  br label %"ik_str_cond"
as_empty:
  %".44" = call {i32, i8*}* @"create_list"()
  ret {i32, i8*}* %".44"
dict_walk:
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".15" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".14", i32 0, i32 0
  %".16" = load i64, i64* %".15"
  %".17" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".14", i32 0, i32 1
  %".18" = load i64, i64* %".17"
  %".19" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".14", i32 0, i32 2
  %".20" = load i64, i64* %".19"
  %".21" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".14", i32 0, i32 3
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".14", i32 0, i32 4
  %".24" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".23"
  %".25" = call {i32, i8*}* @"create_list"()
  %"ik_pos" = alloca i64
  store i64 0, i64* %"ik_pos"
  br label %"ik_cond"
ik_cond:
  %".28" = load i64, i64* %"ik_pos"
  %".29" = icmp slt i64 %".28", %".18"
  br i1 %".29", label %"ik_body", label %"ik_done"
ik_body:
  %".31" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".24", i32 0, i64 %".28"
  %".32" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".31", i32 0, i32 0
  %".33" = load {i32, i8*}*, {i32, i8*}** %".32"
  %".34" = icmp ne {i32, i8*}* %".33", null
  br i1 %".34", label %"ik_live", label %"ik_step"
ik_live:
  %".36" = call {i32, i8*}* @"list_append"({i32, i8*}* %".25", {i32, i8*}* %".33")
  br label %"ik_step"
ik_step:
  %".38" = add i64 %".28", 1
  store i64 %".38", i64* %"ik_pos"
  br label %"ik_cond"
ik_done:
  ret {i32, i8*}* %".25"
ik_str_cond:
  %".57" = load i64, i64* %"ik_str_pos"
  %".58" = icmp slt i64 %".57", %".53"
  br i1 %".58", label %"ik_str_body", label %"ik_str_done"
ik_str_body:
  %".60" = getelementptr i8, i8* %".52", i64 %".57"
  %".61" = load i8, i8* %".60"
  %".62" = and i8 %".61", 224
  %".63" = icmp eq i8 %".62", 192
  %".64" = and i8 %".61", 240
  %".65" = icmp eq i8 %".64", 224
  %".66" = and i8 %".61", 248
  %".67" = icmp eq i8 %".66", 240
  %".68" = select  i1 %".67", i64 4, i64 1
  %".69" = select  i1 %".65", i64 3, i64 %".68"
  %".70" = select  i1 %".63", i64 2, i64 %".69"
  %".71" = getelementptr i8, i8* %".52", i64 %".57"
  %".72" = trunc i64 %".70" to i32
  %".73" = call {i32, i8*}* @"create_str"(i8* %".71", i32 %".72")
  %".74" = call {i32, i8*}* @"list_append"({i32, i8*}* %".54", {i32, i8*}* %".73")
  %".75" = add i64 %".57", %".70"
  store i64 %".75", i64* %"ik_str_pos"
  br label %"ik_str_cond"
ik_str_done:
  ret {i32, i8*}* %".54"
}

define i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
ss_entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".10" = load {i32, i8*}**, {i32, i8*}*** %".9"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i64, i64, {i32, i8*}**}*
  %".14" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 0
  %".15" = load i64, i64* %".14"
  %".16" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".13", i32 0, i32 2
  %".17" = load {i32, i8*}**, {i32, i8*}*** %".16"
  %"ss_i" = alloca i64
  %"ss_j" = alloca i64
  store i64 0, i64* %"ss_i"
  br label %"ss_cond"
ss_cond:
  %".20" = load i64, i64* %"ss_i"
  %".21" = icmp slt i64 %".20", %".8"
  br i1 %".21", label %"ss_body", label %"ss_done"
ss_body:
  %".23" = getelementptr {i32, i8*}*, {i32, i8*}** %".10", i64 %".20"
  %".24" = load {i32, i8*}*, {i32, i8*}** %".23"
  store i64 0, i64* %"ss_j"
  br label %"ss_ic"
ss_ic:
  %".27" = load i64, i64* %"ss_j"
  %".28" = icmp slt i64 %".27", %".15"
  br i1 %".28", label %"ss_ib", label %"ss_miss"
ss_ib:
  %".30" = getelementptr {i32, i8*}*, {i32, i8*}** %".17", i64 %".27"
  %".31" = load {i32, i8*}*, {i32, i8*}** %".30"
  %".32" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".24", {i32, i8*}* %".31")
  br i1 %".32", label %"ss_ostep", label %"ss_istep"
ss_istep:
  %".34" = add i64 %".27", 1
  store i64 %".34", i64* %"ss_j"
  br label %"ss_ic"
ss_ostep:
  %".37" = add i64 %".20", 1
  store i64 %".37", i64* %"ss_i"
  br label %"ss_cond"
ss_miss:
  ret i1 0
ss_done:
  ret i1 1
}

define i1 @"pyobj_str_eq_cstr"({i32, i8*}* %".1", i8* %".2", i64 %".3")
{
sec_entry:
  %".5" = icmp ne {i32, i8*}* %".1", null
  br i1 %".5", label %"sec_nn", label %"sec_out"
sec_nn:
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = icmp eq i32 %".8", 2
  br i1 %".9", label %"sec_len_ok", label %"sec_out"
sec_len_ok:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i32, i8*}*
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 0
  %".15" = load i32, i32* %".14"
  %".16" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 1
  %".17" = load i8*, i8** %".16"
  %".18" = sext i32 %".15" to i64
  %".19" = icmp eq i64 %".18", %".3"
  br i1 %".19", label %"sec_mem", label %"sec_out"
sec_mem:
  %".21" = call i32 @"memcmp"(i8* %".17", i8* %".2", i64 %".3")
  %".22" = icmp eq i32 %".21", 0
  br label %"sec_out"
sec_out:
  %".24" = phi  i1 [0, %"sec_entry"], [0, %"sec_nn"], [0, %"sec_len_ok"], [%".22", %"sec_mem"]
  ret i1 %".24"
}

define {i32, i8*}* @"pyobj_eq"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".83" = icmp eq i32 %".12", 1
  %".84" = icmp eq i32 %".14", 1
  %".85" = or i1 %".83", %".84"
  br i1 %".85", label %"float_op", label %"int_op"
float_op:
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = bitcast i8* %".88" to double*
  %".90" = load double, double* %".89"
  %".91" = bitcast i8* %".88" to i64*
  %".92" = load i64, i64* %".91"
  %".93" = sitofp i64 %".92" to double
  %".94" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".95" = load i32, i32* %".94"
  %".96" = icmp eq i32 %".95", 1
  %".97" = select  i1 %".96", double %".90", double %".93"
  %".98" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".99" = load i8*, i8** %".98"
  %".100" = bitcast i8* %".99" to double*
  %".101" = load double, double* %".100"
  %".102" = bitcast i8* %".99" to i64*
  %".103" = load i64, i64* %".102"
  %".104" = sitofp i64 %".103" to double
  %".105" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".106" = load i32, i32* %".105"
  %".107" = icmp eq i32 %".106", 1
  %".108" = select  i1 %".107", double %".101", double %".104"
  %".109" = fcmp oeq double %".97", %".108"
  %".110" = call {i32, i8*}* @"create_bool"(i1 %".109")
  ret {i32, i8*}* %".110"
int_op:
  %".112" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".113" = load i8*, i8** %".112"
  %".114" = bitcast i8* %".113" to i64*
  %".115" = load i64, i64* %".114"
  %".116" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".117" = load i8*, i8** %".116"
  %".118" = bitcast i8* %".117" to i64*
  %".119" = load i64, i64* %".118"
  %".120" = icmp eq i64 %".115", %".119"
  %".121" = call {i32, i8*}* @"create_bool"(i1 %".120")
  ret {i32, i8*}* %".121"
error:
  %".123" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".123"
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = call {i32, i8*}* @"create_bool"(i1 %".8")
  ret {i32, i8*}* %".9"
tags:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".14" = load i32, i32* %".13"
  %".15" = icmp eq i32 %".12", 0
  %".16" = icmp eq i32 %".12", 1
  %".17" = icmp eq i32 %".12", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".14", 0
  %".21" = icmp eq i32 %".14", 1
  %".22" = icmp eq i32 %".14", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  br i1 %".25", label %"num_check", label %"str_check"
str_check:
  %".27" = icmp eq i32 %".12", 6
  %".28" = icmp eq i32 %".14", 6
  %".29" = and i1 %".27", %".28"
  br i1 %".29", label %"inst_check", label %"str_gate"
inst_check:
  %".31" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".33" = icmp eq i8* %".31", %".32"
  %".34" = call {i32, i8*}* @"create_bool"(i1 %".33")
  ret {i32, i8*}* %".34"
str_gate:
  %".36" = icmp eq i32 %".12", 2
  %".37" = icmp eq i32 %".14", 2
  %".38" = and i1 %".36", %".37"
  br i1 %".38", label %"str_op", label %"list_gate"
str_op:
  %".56" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".57" = load i8*, i8** %".56"
  %".58" = bitcast i8* %".57" to {i32, i8*}*
  %".59" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 0
  %".60" = load i32, i32* %".59"
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 1
  %".62" = load i8*, i8** %".61"
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".64" = load i8*, i8** %".63"
  %".65" = bitcast i8* %".64" to {i32, i8*}*
  %".66" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 0
  %".67" = load i32, i32* %".66"
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 1
  %".69" = load i8*, i8** %".68"
  %".70" = icmp slt i32 %".60", %".67"
  %".71" = select  i1 %".70", i32 %".60", i32 %".67"
  %".72" = sext i32 %".71" to i64
  %".73" = call i32 @"memcmp"(i8* %".62", i8* %".69", i64 %".72")
  %".74" = sext i32 %".73" to i64
  %".75" = icmp eq i64 %".74", 0
  %".76" = sext i32 %".60" to i64
  %".77" = sext i32 %".67" to i64
  %".78" = sub i64 %".76", %".77"
  %".79" = select  i1 %".75", i64 %".78", i64 %".74"
  %".80" = icmp eq i64 %".79", 0
  %".81" = call {i32, i8*}* @"create_bool"(i1 %".80")
  ret {i32, i8*}* %".81"
list_gate:
  %".40" = icmp eq i32 %".12", 4
  %".41" = icmp eq i32 %".14", 4
  %".42" = and i1 %".40", %".41"
  %".43" = icmp eq i32 %".12", 8
  %".44" = icmp eq i32 %".14", 8
  %".45" = and i1 %".43", %".44"
  br i1 %".42", label %"list_op", label %"seq_gate"
list_op:
  %".47" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".48" = call {i32, i8*}* @"create_bool"(i1 %".47")
  ret {i32, i8*}* %".48"
set_op:
  %".51" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".52" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".53" = and i1 %".51", %".52"
  %".54" = call {i32, i8*}* @"create_bool"(i1 %".53")
  ret {i32, i8*}* %".54"
seq_gate:
  br i1 %".45", label %"set_op", label %"error"
}

define {i32, i8*}* @"pyobj_ne"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".87" = icmp eq i32 %".13", 1
  %".88" = icmp eq i32 %".15", 1
  %".89" = or i1 %".87", %".88"
  br i1 %".89", label %"float_op", label %"int_op"
float_op:
  %".91" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".92" = load i8*, i8** %".91"
  %".93" = bitcast i8* %".92" to double*
  %".94" = load double, double* %".93"
  %".95" = bitcast i8* %".92" to i64*
  %".96" = load i64, i64* %".95"
  %".97" = sitofp i64 %".96" to double
  %".98" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".99" = load i32, i32* %".98"
  %".100" = icmp eq i32 %".99", 1
  %".101" = select  i1 %".100", double %".94", double %".97"
  %".102" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".103" = load i8*, i8** %".102"
  %".104" = bitcast i8* %".103" to double*
  %".105" = load double, double* %".104"
  %".106" = bitcast i8* %".103" to i64*
  %".107" = load i64, i64* %".106"
  %".108" = sitofp i64 %".107" to double
  %".109" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".110" = load i32, i32* %".109"
  %".111" = icmp eq i32 %".110", 1
  %".112" = select  i1 %".111", double %".105", double %".108"
  %".113" = fcmp une double %".101", %".112"
  %".114" = call {i32, i8*}* @"create_bool"(i1 %".113")
  ret {i32, i8*}* %".114"
int_op:
  %".116" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".117" = load i8*, i8** %".116"
  %".118" = bitcast i8* %".117" to i64*
  %".119" = load i64, i64* %".118"
  %".120" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".121" = load i8*, i8** %".120"
  %".122" = bitcast i8* %".121" to i64*
  %".123" = load i64, i64* %".122"
  %".124" = icmp ne i64 %".119", %".123"
  %".125" = call {i32, i8*}* @"create_bool"(i1 %".124")
  ret {i32, i8*}* %".125"
error:
  %".127" = call {i32, i8*}* @"create_bool"(i1 1)
  ret {i32, i8*}* %".127"
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = xor i1 %".8", -1
  %".10" = call {i32, i8*}* @"create_bool"(i1 %".9")
  ret {i32, i8*}* %".10"
tags:
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".13" = load i32, i32* %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".15" = load i32, i32* %".14"
  %".16" = icmp eq i32 %".13", 0
  %".17" = icmp eq i32 %".13", 1
  %".18" = icmp eq i32 %".13", 3
  %".19" = or i1 %".17", %".18"
  %".20" = or i1 %".16", %".19"
  %".21" = icmp eq i32 %".15", 0
  %".22" = icmp eq i32 %".15", 1
  %".23" = icmp eq i32 %".15", 3
  %".24" = or i1 %".22", %".23"
  %".25" = or i1 %".21", %".24"
  %".26" = and i1 %".20", %".25"
  br i1 %".26", label %"num_check", label %"str_check"
str_check:
  %".28" = icmp eq i32 %".13", 6
  %".29" = icmp eq i32 %".15", 6
  %".30" = and i1 %".28", %".29"
  br i1 %".30", label %"inst_check", label %"str_gate"
inst_check:
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".33" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".34" = icmp eq i8* %".32", %".33"
  %".35" = xor i1 %".34", -1
  %".36" = call {i32, i8*}* @"create_bool"(i1 %".35")
  ret {i32, i8*}* %".36"
str_gate:
  %".38" = icmp eq i32 %".13", 2
  %".39" = icmp eq i32 %".15", 2
  %".40" = and i1 %".38", %".39"
  br i1 %".40", label %"str_op", label %"list_gate"
str_op:
  %".60" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".61" = load i8*, i8** %".60"
  %".62" = bitcast i8* %".61" to {i32, i8*}*
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".62", i32 0, i32 0
  %".64" = load i32, i32* %".63"
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".62", i32 0, i32 1
  %".66" = load i8*, i8** %".65"
  %".67" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".68" = load i8*, i8** %".67"
  %".69" = bitcast i8* %".68" to {i32, i8*}*
  %".70" = getelementptr {i32, i8*}, {i32, i8*}* %".69", i32 0, i32 0
  %".71" = load i32, i32* %".70"
  %".72" = getelementptr {i32, i8*}, {i32, i8*}* %".69", i32 0, i32 1
  %".73" = load i8*, i8** %".72"
  %".74" = icmp slt i32 %".64", %".71"
  %".75" = select  i1 %".74", i32 %".64", i32 %".71"
  %".76" = sext i32 %".75" to i64
  %".77" = call i32 @"memcmp"(i8* %".66", i8* %".73", i64 %".76")
  %".78" = sext i32 %".77" to i64
  %".79" = icmp eq i64 %".78", 0
  %".80" = sext i32 %".64" to i64
  %".81" = sext i32 %".71" to i64
  %".82" = sub i64 %".80", %".81"
  %".83" = select  i1 %".79", i64 %".82", i64 %".78"
  %".84" = icmp ne i64 %".83", 0
  %".85" = call {i32, i8*}* @"create_bool"(i1 %".84")
  ret {i32, i8*}* %".85"
list_gate:
  %".42" = icmp eq i32 %".13", 4
  %".43" = icmp eq i32 %".15", 4
  %".44" = and i1 %".42", %".43"
  %".45" = icmp eq i32 %".13", 8
  %".46" = icmp eq i32 %".15", 8
  %".47" = and i1 %".45", %".46"
  br i1 %".44", label %"list_op", label %"seq_gate"
list_op:
  %".49" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".50" = xor i1 %".49", -1
  %".51" = call {i32, i8*}* @"create_bool"(i1 %".50")
  ret {i32, i8*}* %".51"
set_op:
  %".54" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".55" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".56" = and i1 %".54", %".55"
  %".57" = xor i1 %".56", -1
  %".58" = call {i32, i8*}* @"create_bool"(i1 %".57")
  ret {i32, i8*}* %".58"
seq_gate:
  br i1 %".47", label %"set_op", label %"error"
}

define {i32, i8*}* @"pyobj_lt"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".85" = icmp eq i32 %".12", 1
  %".86" = icmp eq i32 %".14", 1
  %".87" = or i1 %".85", %".86"
  br i1 %".87", label %"float_op", label %"int_op"
float_op:
  %".89" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".90" = load i8*, i8** %".89"
  %".91" = bitcast i8* %".90" to double*
  %".92" = load double, double* %".91"
  %".93" = bitcast i8* %".90" to i64*
  %".94" = load i64, i64* %".93"
  %".95" = sitofp i64 %".94" to double
  %".96" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".97" = load i32, i32* %".96"
  %".98" = icmp eq i32 %".97", 1
  %".99" = select  i1 %".98", double %".92", double %".95"
  %".100" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".101" = load i8*, i8** %".100"
  %".102" = bitcast i8* %".101" to double*
  %".103" = load double, double* %".102"
  %".104" = bitcast i8* %".101" to i64*
  %".105" = load i64, i64* %".104"
  %".106" = sitofp i64 %".105" to double
  %".107" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".108" = load i32, i32* %".107"
  %".109" = icmp eq i32 %".108", 1
  %".110" = select  i1 %".109", double %".103", double %".106"
  %".111" = fcmp olt double %".99", %".110"
  %".112" = call {i32, i8*}* @"create_bool"(i1 %".111")
  ret {i32, i8*}* %".112"
int_op:
  %".114" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".115" = load i8*, i8** %".114"
  %".116" = bitcast i8* %".115" to i64*
  %".117" = load i64, i64* %".116"
  %".118" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".119" = load i8*, i8** %".118"
  %".120" = bitcast i8* %".119" to i64*
  %".121" = load i64, i64* %".120"
  %".122" = icmp slt i64 %".117", %".121"
  %".123" = call {i32, i8*}* @"create_bool"(i1 %".122")
  ret {i32, i8*}* %".123"
error:
  %".125" = getelementptr [52 x i8], [52 x i8]* @"str.TypeError_3a_20_27_3c_27_20not_20supported_20between_20these_20operands", i32 0, i32 0
  call void @"silu_panic"(i8* %".125")
  unreachable
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".9"
tags:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".14" = load i32, i32* %".13"
  %".15" = icmp eq i32 %".12", 0
  %".16" = icmp eq i32 %".12", 1
  %".17" = icmp eq i32 %".12", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".14", 0
  %".21" = icmp eq i32 %".14", 1
  %".22" = icmp eq i32 %".14", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  br i1 %".25", label %"num_check", label %"str_check"
str_check:
  %".27" = icmp eq i32 %".12", 6
  %".28" = icmp eq i32 %".14", 6
  %".29" = and i1 %".27", %".28"
  br i1 %".29", label %"inst_check", label %"str_gate"
inst_check:
  %".31" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".33" = icmp eq i8* %".31", %".32"
  br i1 %".33", label %"inst_op", label %"error"
str_gate:
  %".36" = icmp eq i32 %".12", 2
  %".37" = icmp eq i32 %".14", 2
  %".38" = and i1 %".36", %".37"
  br i1 %".38", label %"str_op", label %"list_gate"
inst_op:
  br label %"error"
str_op:
  %".58" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".59" = load i8*, i8** %".58"
  %".60" = bitcast i8* %".59" to {i32, i8*}*
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".60", i32 0, i32 0
  %".62" = load i32, i32* %".61"
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".60", i32 0, i32 1
  %".64" = load i8*, i8** %".63"
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".66" = load i8*, i8** %".65"
  %".67" = bitcast i8* %".66" to {i32, i8*}*
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 0
  %".69" = load i32, i32* %".68"
  %".70" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 1
  %".71" = load i8*, i8** %".70"
  %".72" = icmp slt i32 %".62", %".69"
  %".73" = select  i1 %".72", i32 %".62", i32 %".69"
  %".74" = sext i32 %".73" to i64
  %".75" = call i32 @"memcmp"(i8* %".64", i8* %".71", i64 %".74")
  %".76" = sext i32 %".75" to i64
  %".77" = icmp eq i64 %".76", 0
  %".78" = sext i32 %".62" to i64
  %".79" = sext i32 %".69" to i64
  %".80" = sub i64 %".78", %".79"
  %".81" = select  i1 %".77", i64 %".80", i64 %".76"
  %".82" = icmp slt i64 %".81", 0
  %".83" = call {i32, i8*}* @"create_bool"(i1 %".82")
  ret {i32, i8*}* %".83"
list_gate:
  %".40" = icmp eq i32 %".12", 4
  %".41" = icmp eq i32 %".14", 4
  %".42" = and i1 %".40", %".41"
  %".43" = icmp eq i32 %".12", 8
  %".44" = icmp eq i32 %".14", 8
  %".45" = and i1 %".43", %".44"
  br i1 %".42", label %"list_op", label %"seq_gate"
list_op:
  %".47" = call i64 @"pyobj_list_cmp"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".48" = icmp slt i64 %".47", 0
  %".49" = call {i32, i8*}* @"create_bool"(i1 %".48")
  ret {i32, i8*}* %".49"
set_op:
  %".52" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".53" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".54" = xor i1 %".53", -1
  %".55" = and i1 %".52", %".54"
  %".56" = call {i32, i8*}* @"create_bool"(i1 %".55")
  ret {i32, i8*}* %".56"
seq_gate:
  br i1 %".45", label %"set_op", label %"error"
}

define {i32, i8*}* @"pyobj_le"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".83" = icmp eq i32 %".12", 1
  %".84" = icmp eq i32 %".14", 1
  %".85" = or i1 %".83", %".84"
  br i1 %".85", label %"float_op", label %"int_op"
float_op:
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = bitcast i8* %".88" to double*
  %".90" = load double, double* %".89"
  %".91" = bitcast i8* %".88" to i64*
  %".92" = load i64, i64* %".91"
  %".93" = sitofp i64 %".92" to double
  %".94" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".95" = load i32, i32* %".94"
  %".96" = icmp eq i32 %".95", 1
  %".97" = select  i1 %".96", double %".90", double %".93"
  %".98" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".99" = load i8*, i8** %".98"
  %".100" = bitcast i8* %".99" to double*
  %".101" = load double, double* %".100"
  %".102" = bitcast i8* %".99" to i64*
  %".103" = load i64, i64* %".102"
  %".104" = sitofp i64 %".103" to double
  %".105" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".106" = load i32, i32* %".105"
  %".107" = icmp eq i32 %".106", 1
  %".108" = select  i1 %".107", double %".101", double %".104"
  %".109" = fcmp ole double %".97", %".108"
  %".110" = call {i32, i8*}* @"create_bool"(i1 %".109")
  ret {i32, i8*}* %".110"
int_op:
  %".112" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".113" = load i8*, i8** %".112"
  %".114" = bitcast i8* %".113" to i64*
  %".115" = load i64, i64* %".114"
  %".116" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".117" = load i8*, i8** %".116"
  %".118" = bitcast i8* %".117" to i64*
  %".119" = load i64, i64* %".118"
  %".120" = icmp sle i64 %".115", %".119"
  %".121" = call {i32, i8*}* @"create_bool"(i1 %".120")
  ret {i32, i8*}* %".121"
error:
  %".123" = getelementptr [53 x i8], [53 x i8]* @"str.TypeError_3a_20_27_3c_3d_27_20not_20supported_20between_20these_20operands", i32 0, i32 0
  call void @"silu_panic"(i8* %".123")
  unreachable
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".9"
tags:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".14" = load i32, i32* %".13"
  %".15" = icmp eq i32 %".12", 0
  %".16" = icmp eq i32 %".12", 1
  %".17" = icmp eq i32 %".12", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".14", 0
  %".21" = icmp eq i32 %".14", 1
  %".22" = icmp eq i32 %".14", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  br i1 %".25", label %"num_check", label %"str_check"
str_check:
  %".27" = icmp eq i32 %".12", 6
  %".28" = icmp eq i32 %".14", 6
  %".29" = and i1 %".27", %".28"
  br i1 %".29", label %"inst_check", label %"str_gate"
inst_check:
  %".31" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".33" = icmp eq i8* %".31", %".32"
  br i1 %".33", label %"inst_op", label %"error"
str_gate:
  %".36" = icmp eq i32 %".12", 2
  %".37" = icmp eq i32 %".14", 2
  %".38" = and i1 %".36", %".37"
  br i1 %".38", label %"str_op", label %"list_gate"
inst_op:
  br label %"error"
str_op:
  %".56" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".57" = load i8*, i8** %".56"
  %".58" = bitcast i8* %".57" to {i32, i8*}*
  %".59" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 0
  %".60" = load i32, i32* %".59"
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 1
  %".62" = load i8*, i8** %".61"
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".64" = load i8*, i8** %".63"
  %".65" = bitcast i8* %".64" to {i32, i8*}*
  %".66" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 0
  %".67" = load i32, i32* %".66"
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 1
  %".69" = load i8*, i8** %".68"
  %".70" = icmp slt i32 %".60", %".67"
  %".71" = select  i1 %".70", i32 %".60", i32 %".67"
  %".72" = sext i32 %".71" to i64
  %".73" = call i32 @"memcmp"(i8* %".62", i8* %".69", i64 %".72")
  %".74" = sext i32 %".73" to i64
  %".75" = icmp eq i64 %".74", 0
  %".76" = sext i32 %".60" to i64
  %".77" = sext i32 %".67" to i64
  %".78" = sub i64 %".76", %".77"
  %".79" = select  i1 %".75", i64 %".78", i64 %".74"
  %".80" = icmp sle i64 %".79", 0
  %".81" = call {i32, i8*}* @"create_bool"(i1 %".80")
  ret {i32, i8*}* %".81"
list_gate:
  %".40" = icmp eq i32 %".12", 4
  %".41" = icmp eq i32 %".14", 4
  %".42" = and i1 %".40", %".41"
  %".43" = icmp eq i32 %".12", 8
  %".44" = icmp eq i32 %".14", 8
  %".45" = and i1 %".43", %".44"
  br i1 %".42", label %"list_op", label %"seq_gate"
list_op:
  %".47" = call i64 @"pyobj_list_cmp"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".48" = icmp sle i64 %".47", 0
  %".49" = call {i32, i8*}* @"create_bool"(i1 %".48")
  ret {i32, i8*}* %".49"
set_op:
  %".52" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".53" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".54" = call {i32, i8*}* @"create_bool"(i1 %".52")
  ret {i32, i8*}* %".54"
seq_gate:
  br i1 %".45", label %"set_op", label %"error"
}

@"str.TypeError_3a_20_27_3c_3d_27_20not_20supported_20between_20these_20operands" = constant [53 x i8] c"TypeError: '<=' not supported between these operands\00"
define {i32, i8*}* @"pyobj_gt"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".85" = icmp eq i32 %".12", 1
  %".86" = icmp eq i32 %".14", 1
  %".87" = or i1 %".85", %".86"
  br i1 %".87", label %"float_op", label %"int_op"
float_op:
  %".89" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".90" = load i8*, i8** %".89"
  %".91" = bitcast i8* %".90" to double*
  %".92" = load double, double* %".91"
  %".93" = bitcast i8* %".90" to i64*
  %".94" = load i64, i64* %".93"
  %".95" = sitofp i64 %".94" to double
  %".96" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".97" = load i32, i32* %".96"
  %".98" = icmp eq i32 %".97", 1
  %".99" = select  i1 %".98", double %".92", double %".95"
  %".100" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".101" = load i8*, i8** %".100"
  %".102" = bitcast i8* %".101" to double*
  %".103" = load double, double* %".102"
  %".104" = bitcast i8* %".101" to i64*
  %".105" = load i64, i64* %".104"
  %".106" = sitofp i64 %".105" to double
  %".107" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".108" = load i32, i32* %".107"
  %".109" = icmp eq i32 %".108", 1
  %".110" = select  i1 %".109", double %".103", double %".106"
  %".111" = fcmp ogt double %".99", %".110"
  %".112" = call {i32, i8*}* @"create_bool"(i1 %".111")
  ret {i32, i8*}* %".112"
int_op:
  %".114" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".115" = load i8*, i8** %".114"
  %".116" = bitcast i8* %".115" to i64*
  %".117" = load i64, i64* %".116"
  %".118" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".119" = load i8*, i8** %".118"
  %".120" = bitcast i8* %".119" to i64*
  %".121" = load i64, i64* %".120"
  %".122" = icmp sgt i64 %".117", %".121"
  %".123" = call {i32, i8*}* @"create_bool"(i1 %".122")
  ret {i32, i8*}* %".123"
error:
  %".125" = getelementptr [52 x i8], [52 x i8]* @"str.TypeError_3a_20_27_3e_27_20not_20supported_20between_20these_20operands", i32 0, i32 0
  call void @"silu_panic"(i8* %".125")
  unreachable
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".9"
tags:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".14" = load i32, i32* %".13"
  %".15" = icmp eq i32 %".12", 0
  %".16" = icmp eq i32 %".12", 1
  %".17" = icmp eq i32 %".12", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".14", 0
  %".21" = icmp eq i32 %".14", 1
  %".22" = icmp eq i32 %".14", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  br i1 %".25", label %"num_check", label %"str_check"
str_check:
  %".27" = icmp eq i32 %".12", 6
  %".28" = icmp eq i32 %".14", 6
  %".29" = and i1 %".27", %".28"
  br i1 %".29", label %"inst_check", label %"str_gate"
inst_check:
  %".31" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".33" = icmp eq i8* %".31", %".32"
  br i1 %".33", label %"inst_op", label %"error"
str_gate:
  %".36" = icmp eq i32 %".12", 2
  %".37" = icmp eq i32 %".14", 2
  %".38" = and i1 %".36", %".37"
  br i1 %".38", label %"str_op", label %"list_gate"
inst_op:
  br label %"error"
str_op:
  %".58" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".59" = load i8*, i8** %".58"
  %".60" = bitcast i8* %".59" to {i32, i8*}*
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".60", i32 0, i32 0
  %".62" = load i32, i32* %".61"
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".60", i32 0, i32 1
  %".64" = load i8*, i8** %".63"
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".66" = load i8*, i8** %".65"
  %".67" = bitcast i8* %".66" to {i32, i8*}*
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 0
  %".69" = load i32, i32* %".68"
  %".70" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 1
  %".71" = load i8*, i8** %".70"
  %".72" = icmp slt i32 %".62", %".69"
  %".73" = select  i1 %".72", i32 %".62", i32 %".69"
  %".74" = sext i32 %".73" to i64
  %".75" = call i32 @"memcmp"(i8* %".64", i8* %".71", i64 %".74")
  %".76" = sext i32 %".75" to i64
  %".77" = icmp eq i64 %".76", 0
  %".78" = sext i32 %".62" to i64
  %".79" = sext i32 %".69" to i64
  %".80" = sub i64 %".78", %".79"
  %".81" = select  i1 %".77", i64 %".80", i64 %".76"
  %".82" = icmp sgt i64 %".81", 0
  %".83" = call {i32, i8*}* @"create_bool"(i1 %".82")
  ret {i32, i8*}* %".83"
list_gate:
  %".40" = icmp eq i32 %".12", 4
  %".41" = icmp eq i32 %".14", 4
  %".42" = and i1 %".40", %".41"
  %".43" = icmp eq i32 %".12", 8
  %".44" = icmp eq i32 %".14", 8
  %".45" = and i1 %".43", %".44"
  br i1 %".42", label %"list_op", label %"seq_gate"
list_op:
  %".47" = call i64 @"pyobj_list_cmp"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".48" = icmp sgt i64 %".47", 0
  %".49" = call {i32, i8*}* @"create_bool"(i1 %".48")
  ret {i32, i8*}* %".49"
set_op:
  %".52" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".53" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".54" = xor i1 %".52", -1
  %".55" = and i1 %".53", %".54"
  %".56" = call {i32, i8*}* @"create_bool"(i1 %".55")
  ret {i32, i8*}* %".56"
seq_gate:
  br i1 %".45", label %"set_op", label %"error"
}

@"str.TypeError_3a_20_27_3e_27_20not_20supported_20between_20these_20operands" = constant [52 x i8] c"TypeError: '>' not supported between these operands\00"
define {i32, i8*}* @"pyobj_ge"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", null
  %".5" = icmp eq {i32, i8*}* %".2", null
  %".6" = or i1 %".4", %".5"
  br i1 %".6", label %"null_check", label %"tags"
num_check:
  %".83" = icmp eq i32 %".12", 1
  %".84" = icmp eq i32 %".14", 1
  %".85" = or i1 %".83", %".84"
  br i1 %".85", label %"float_op", label %"int_op"
float_op:
  %".87" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".88" = load i8*, i8** %".87"
  %".89" = bitcast i8* %".88" to double*
  %".90" = load double, double* %".89"
  %".91" = bitcast i8* %".88" to i64*
  %".92" = load i64, i64* %".91"
  %".93" = sitofp i64 %".92" to double
  %".94" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".95" = load i32, i32* %".94"
  %".96" = icmp eq i32 %".95", 1
  %".97" = select  i1 %".96", double %".90", double %".93"
  %".98" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".99" = load i8*, i8** %".98"
  %".100" = bitcast i8* %".99" to double*
  %".101" = load double, double* %".100"
  %".102" = bitcast i8* %".99" to i64*
  %".103" = load i64, i64* %".102"
  %".104" = sitofp i64 %".103" to double
  %".105" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".106" = load i32, i32* %".105"
  %".107" = icmp eq i32 %".106", 1
  %".108" = select  i1 %".107", double %".101", double %".104"
  %".109" = fcmp oge double %".97", %".108"
  %".110" = call {i32, i8*}* @"create_bool"(i1 %".109")
  ret {i32, i8*}* %".110"
int_op:
  %".112" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".113" = load i8*, i8** %".112"
  %".114" = bitcast i8* %".113" to i64*
  %".115" = load i64, i64* %".114"
  %".116" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".117" = load i8*, i8** %".116"
  %".118" = bitcast i8* %".117" to i64*
  %".119" = load i64, i64* %".118"
  %".120" = icmp sge i64 %".115", %".119"
  %".121" = call {i32, i8*}* @"create_bool"(i1 %".120")
  ret {i32, i8*}* %".121"
error:
  %".123" = getelementptr [53 x i8], [53 x i8]* @"str.TypeError_3a_20_27_3e_3d_27_20not_20supported_20between_20these_20operands", i32 0, i32 0
  call void @"silu_panic"(i8* %".123")
  unreachable
null_check:
  %".8" = and i1 %".4", %".5"
  %".9" = call {i32, i8*}* @"create_bool"(i1 0)
  ret {i32, i8*}* %".9"
tags:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".14" = load i32, i32* %".13"
  %".15" = icmp eq i32 %".12", 0
  %".16" = icmp eq i32 %".12", 1
  %".17" = icmp eq i32 %".12", 3
  %".18" = or i1 %".16", %".17"
  %".19" = or i1 %".15", %".18"
  %".20" = icmp eq i32 %".14", 0
  %".21" = icmp eq i32 %".14", 1
  %".22" = icmp eq i32 %".14", 3
  %".23" = or i1 %".21", %".22"
  %".24" = or i1 %".20", %".23"
  %".25" = and i1 %".19", %".24"
  br i1 %".25", label %"num_check", label %"str_check"
str_check:
  %".27" = icmp eq i32 %".12", 6
  %".28" = icmp eq i32 %".14", 6
  %".29" = and i1 %".27", %".28"
  br i1 %".29", label %"inst_check", label %"str_gate"
inst_check:
  %".31" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".32" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".33" = icmp eq i8* %".31", %".32"
  br i1 %".33", label %"inst_op", label %"error"
str_gate:
  %".36" = icmp eq i32 %".12", 2
  %".37" = icmp eq i32 %".14", 2
  %".38" = and i1 %".36", %".37"
  br i1 %".38", label %"str_op", label %"list_gate"
inst_op:
  br label %"error"
str_op:
  %".56" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".57" = load i8*, i8** %".56"
  %".58" = bitcast i8* %".57" to {i32, i8*}*
  %".59" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 0
  %".60" = load i32, i32* %".59"
  %".61" = getelementptr {i32, i8*}, {i32, i8*}* %".58", i32 0, i32 1
  %".62" = load i8*, i8** %".61"
  %".63" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".64" = load i8*, i8** %".63"
  %".65" = bitcast i8* %".64" to {i32, i8*}*
  %".66" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 0
  %".67" = load i32, i32* %".66"
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".65", i32 0, i32 1
  %".69" = load i8*, i8** %".68"
  %".70" = icmp slt i32 %".60", %".67"
  %".71" = select  i1 %".70", i32 %".60", i32 %".67"
  %".72" = sext i32 %".71" to i64
  %".73" = call i32 @"memcmp"(i8* %".62", i8* %".69", i64 %".72")
  %".74" = sext i32 %".73" to i64
  %".75" = icmp eq i64 %".74", 0
  %".76" = sext i32 %".60" to i64
  %".77" = sext i32 %".67" to i64
  %".78" = sub i64 %".76", %".77"
  %".79" = select  i1 %".75", i64 %".78", i64 %".74"
  %".80" = icmp sge i64 %".79", 0
  %".81" = call {i32, i8*}* @"create_bool"(i1 %".80")
  ret {i32, i8*}* %".81"
list_gate:
  %".40" = icmp eq i32 %".12", 4
  %".41" = icmp eq i32 %".14", 4
  %".42" = and i1 %".40", %".41"
  %".43" = icmp eq i32 %".12", 8
  %".44" = icmp eq i32 %".14", 8
  %".45" = and i1 %".43", %".44"
  br i1 %".42", label %"list_op", label %"seq_gate"
list_op:
  %".47" = call i64 @"pyobj_list_cmp"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".48" = icmp sge i64 %".47", 0
  %".49" = call {i32, i8*}* @"create_bool"(i1 %".48")
  ret {i32, i8*}* %".49"
set_op:
  %".52" = call i1 @"pyobj_set_subset"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".53" = call i1 @"pyobj_set_subset"({i32, i8*}* %".2", {i32, i8*}* %".1")
  %".54" = call {i32, i8*}* @"create_bool"(i1 %".53")
  ret {i32, i8*}* %".54"
seq_gate:
  br i1 %".45", label %"set_op", label %"error"
}

@"str.TypeError_3a_20_27_3e_3d_27_20not_20supported_20between_20these_20operands" = constant [53 x i8] c"TypeError: '>=' not supported between these operands\00"
define i64 @"pyobj_hash"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"hash_zero", label %"dispatch"
dispatch:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  switch i32 %".6", label %"hash_int" [i32 1, label %"hash_float" i32 2, label %"hash_str" i32 5, label %"hash_zero" i32 6, label %"hash_inst"]
hash_int:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to i64*
  %".14" = load i64, i64* %".13"
  ret i64 %".14"
hash_float:
  %".16" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".17" = load i8*, i8** %".16"
  %".18" = bitcast i8* %".17" to i64*
  %".19" = load i64, i64* %".18"
  %".20" = icmp eq i64 %".19", -9223372036854775808
  %".21" = select  i1 %".20", i64 0, i64 %".19"
  ret i64 %".21"
hash_str:
  %".23" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".24" = load i8*, i8** %".23"
  %".25" = bitcast i8* %".24" to {i32, i8*}*
  %".26" = getelementptr {i32, i8*}, {i32, i8*}* %".25", i32 0, i32 0
  %".27" = load i32, i32* %".26"
  %".28" = getelementptr {i32, i8*}, {i32, i8*}* %".25", i32 0, i32 1
  %".29" = load i8*, i8** %".28"
  %"fnv_h" = alloca i64
  %"fnv_i" = alloca i64
  store i64 -3750763034362895579, i64* %"fnv_h"
  store i64 0, i64* %"fnv_i"
  br label %"fnv_cond"
hash_zero:
  ret i64 0
hash_inst:
  %".8" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".9" = ptrtoint i8* %".8" to i64
  ret i64 %".9"
fnv_cond:
  %".33" = load i64, i64* %"fnv_i"
  %".34" = sext i32 %".27" to i64
  %".35" = icmp slt i64 %".33", %".34"
  br i1 %".35", label %"fnv_body", label %"fnv_done"
fnv_body:
  %".37" = getelementptr i8, i8* %".29", i64 %".33"
  %".38" = load i8, i8* %".37"
  %".39" = load i64, i64* %"fnv_h"
  %".40" = zext i8 %".38" to i64
  %".41" = xor i64 %".39", %".40"
  %".42" = mul i64 %".41", 1099511628211
  store i64 %".42", i64* %"fnv_h"
  %".44" = add i64 %".33", 1
  store i64 %".44", i64* %"fnv_i"
  br label %"fnv_cond"
fnv_done:
  %".47" = load i64, i64* %"fnv_h"
  ret i64 %".47"
}

define i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 2
  %".13" = load i64, i64* %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 3
  %".15" = load i64*, i64** %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 4
  %".17" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".16"
  %".18" = call i64 @"pyobj_hash"({i32, i8*}* %".2")
  %"probe_slot" = alloca i64
  %"probe_tomb.1" = alloca i64
  %".19" = and i64 %".18", %".13"
  store i64 %".19", i64* %"probe_slot"
  store i64 -1, i64* %"probe_tomb.1"
  br label %"probe_cond"
probe_cond:
  %".23" = load i64, i64* %"probe_slot"
  %".24" = getelementptr i64, i64* %".15", i64 %".23"
  %".25" = load i64, i64* %".24"
  %".26" = icmp eq i64 %".25", 0
  %".27" = icmp eq i64 %".25", -1
  br i1 %".26", label %"probe_empty", label %"probe_body"
probe_body:
  br i1 %".27", label %"probe_tomb", label %"probe_hit"
probe_hit:
  %".40" = sub i64 %".25", 1
  %".41" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".17", i32 0, i64 %".40"
  %".42" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".41", i32 0, i32 0
  %".43" = load {i32, i8*}*, {i32, i8*}** %".42"
  %".44" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".43", {i32, i8*}* %".2")
  br i1 %".44", label %"probe_match", label %"probe_step"
probe_empty:
  %".29" = load i64, i64* %"probe_tomb.1"
  %".30" = icmp sge i64 %".29", 0
  %".31" = select  i1 %".30", i64 %".29", i64 %".23"
  store i64 %".31", i64* %".3"
  ret i64 -1
probe_tomb:
  %".35" = load i64, i64* %"probe_tomb.1"
  %".36" = icmp slt i64 %".35", 0
  %".37" = select  i1 %".36", i64 %".23", i64 %".35"
  store i64 %".37", i64* %"probe_tomb.1"
  br label %"probe_step"
probe_step:
  %".49" = load i64, i64* %"probe_slot"
  %".50" = add i64 %".49", 1
  %".51" = and i64 %".50", %".13"
  store i64 %".51", i64* %"probe_slot"
  br label %"probe_cond"
probe_match:
  store i64 %".23", i64* %".3"
  %".47" = sub i64 %".25", 1
  ret i64 %".47"
}

define void @"dict_rehash"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".6" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  %".15" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".14"
  %".16" = add i64 %".11", 1
  %".17" = icmp eq i64 %".16", 0
  %".18" = mul i64 %".16", 2
  %".19" = select  i1 %".17", i64 4, i64 %".18"
  %".20" = sub i64 %".19", 1
  %".21" = call i8* @"calloc"(i64 %".19", i64 8)
  %".22" = bitcast i8* %".21" to i64*
  %".23" = mul i64 %".19", 16
  %".24" = call i8* @"malloc"(i64 %".23")
  %".25" = bitcast i8* %".24" to [0 x {{i32, i8*}*, {i32, i8*}*}]*
  %"reh_j" = alloca i64
  %"reh_i" = alloca i64
  store i64 0, i64* %"reh_j"
  store i64 0, i64* %"reh_i"
  br label %"reh_scan_cond"
reh_scan_cond:
  %".29" = load i64, i64* %"reh_i"
  %".30" = icmp slt i64 %".29", %".9"
  br i1 %".30", label %"reh_scan_body", label %"reh_scan_done"
reh_scan_body:
  %".32" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".15", i32 0, i64 %".29"
  %".33" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".32", i32 0, i32 0
  %".34" = load {i32, i8*}*, {i32, i8*}** %".33"
  %".35" = icmp ne {i32, i8*}* %".34", null
  br i1 %".35", label %"reh_scan_live", label %"reh_scan_dead"
reh_scan_dead:
  %".37" = load i64, i64* %"reh_i"
  %".38" = add i64 %".37", 1
  store i64 %".38", i64* %"reh_i"
  br label %"reh_scan_cond"
reh_scan_live:
  %".41" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".32", i32 0, i32 1
  %".42" = load {i32, i8*}*, {i32, i8*}** %".41"
  %".43" = call i64 @"pyobj_hash"({i32, i8*}* %".34")
  %"reh_s" = alloca i64
  %".44" = and i64 %".43", %".20"
  store i64 %".44", i64* %"reh_s"
  br label %"reh_place_cond"
reh_place_cond:
  %".47" = load i64, i64* %"reh_s"
  %".48" = getelementptr i64, i64* %".22", i64 %".47"
  %".49" = load i64, i64* %".48"
  %".50" = icmp ne i64 %".49", 0
  br i1 %".50", label %"reh_place_adv", label %"reh_place_do"
reh_scan_done:
  %".71" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  store i64 %".20", i64* %".71"
  %".73" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  store i64* %".22", i64** %".73"
  %".75" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  store [0 x {{i32, i8*}*, {i32, i8*}*}]* %".25", [0 x {{i32, i8*}*, {i32, i8*}*}]** %".75"
  %".77" = load i64, i64* %"reh_j"
  %".78" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  store i64 %".77", i64* %".78"
  ret void
reh_place_adv:
  %".52" = add i64 %".47", 1
  %".53" = and i64 %".52", %".20"
  store i64 %".53", i64* %"reh_s"
  br label %"reh_place_cond"
reh_place_do:
  %".56" = load i64, i64* %"reh_j"
  %".57" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".25", i32 0, i64 %".56"
  %".58" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".57", i32 0, i32 0
  store {i32, i8*}* %".34", {i32, i8*}** %".58"
  %".60" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".57", i32 0, i32 1
  store {i32, i8*}* %".42", {i32, i8*}** %".60"
  %".62" = add i64 %".56", 1
  %".63" = getelementptr i64, i64* %".22", i64 %".47"
  store i64 %".62", i64* %".63"
  %".65" = add i64 %".56", 1
  store i64 %".65", i64* %"reh_j"
  %".67" = load i64, i64* %"reh_i"
  %".68" = add i64 %".67", 1
  store i64 %".68", i64* %"reh_i"
  br label %"reh_scan_cond"
}

define {i32, i8*}* @"create_dict"()
{
entry:
  %".2" = call i8* @"malloc"(i64 16)
  %".3" = bitcast i8* %".2" to {i32, i8*}*
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 0
  store i32 5, i32* %".4"
  %".6" = call i8* @"malloc"(i64 40)
  %".7" = bitcast i8* %".6" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".8" = call i8* @"calloc"(i64 4, i64 8)
  %".9" = bitcast i8* %".8" to i64*
  %".10" = call i8* @"malloc"(i64 64)
  %".11" = bitcast i8* %".10" to [0 x {{i32, i8*}*, {i32, i8*}*}]*
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  store i64 0, i64* %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  store i64 0, i64* %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 2
  store i64 3, i64* %".16"
  %".18" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 3
  store i64* %".9", i64** %".18"
  %".20" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 4
  store [0 x {{i32, i8*}*, {i32, i8*}*}]* %".11", [0 x {{i32, i8*}*, {i32, i8*}*}]** %".20"
  %".22" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 1
  store i8* %".6", i8** %".22"
  ret {i32, i8*}* %".3"
}

define {i32, i8*}* @"dict_get_or"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 2
  %".13" = load i64, i64* %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 3
  %".15" = load i64*, i64** %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 4
  %".17" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".16"
  %"get_slot" = alloca i64
  %".18" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"get_slot")
  %".19" = icmp sge i64 %".18", 0
  br i1 %".19", label %"found", label %"missing"
found:
  %".21" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".17", i32 0, i64 %".18"
  %".22" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".21", i32 0, i32 1
  %".23" = load {i32, i8*}*, {i32, i8*}** %".22"
  ret {i32, i8*}* %".23"
missing:
  ret {i32, i8*}* %".3"
}

define void @"dict_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 2
  %".13" = load i64, i64* %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 3
  %".15" = load i64*, i64** %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 4
  %".17" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".16"
  %"set_slot" = alloca i64
  %".18" = add i64 %".13", 1
  %".19" = add i64 %".11", 1
  %".20" = mul i64 %".19", 3
  %".21" = mul i64 %".18", 2
  %".22" = icmp sgt i64 %".20", %".21"
  br i1 %".22", label %"do_rehash", label %"capacity_check"
capacity_check:
  br label %"probe"
do_rehash:
  call void @"dict_rehash"({i32, i8*}* %".1")
  br label %"capacity_check"
probe:
  %".27" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".28" = load i8*, i8** %".27"
  %".29" = bitcast i8* %".28" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".30" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".29", i32 0, i32 0
  %".31" = load i64, i64* %".30"
  %".32" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".29", i32 0, i32 1
  %".33" = load i64, i64* %".32"
  %".34" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".29", i32 0, i32 2
  %".35" = load i64, i64* %".34"
  %".36" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".29", i32 0, i32 3
  %".37" = load i64*, i64** %".36"
  %".38" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".29", i32 0, i32 4
  %".39" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".38"
  %".40" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"set_slot")
  %".41" = icmp sge i64 %".40", 0
  br i1 %".41", label %"replace", label %"insert"
replace:
  %".43" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".39", i32 0, i64 %".40"
  %".44" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".43", i32 0, i32 1
  store {i32, i8*}* %".3", {i32, i8*}** %".44"
  ret void
insert:
  %".47" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".48" = load i8*, i8** %".47"
  %".49" = bitcast i8* %".48" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".50" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".49", i32 0, i32 0
  %".51" = load i64, i64* %".50"
  %".52" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".49", i32 0, i32 1
  %".53" = load i64, i64* %".52"
  %".54" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".49", i32 0, i32 2
  %".55" = load i64, i64* %".54"
  %".56" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".49", i32 0, i32 3
  %".57" = load i64*, i64** %".56"
  %".58" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".49", i32 0, i32 4
  %".59" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".58"
  %".60" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"set_slot")
  %".61" = load i64, i64* %"set_slot"
  %".62" = add i64 %".53", 1
  %".63" = getelementptr i64, i64* %".57", i64 %".61"
  store i64 %".62", i64* %".63"
  %".65" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".59", i32 0, i64 %".53"
  %".66" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".65", i32 0, i32 0
  store {i32, i8*}* %".2", {i32, i8*}** %".66"
  %".68" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".65", i32 0, i32 1
  store {i32, i8*}* %".3", {i32, i8*}** %".68"
  %".70" = add i64 %".53", 1
  %".71" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  store i64 %".70", i64* %".71"
  %".73" = add i64 %".51", 1
  %".74" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  store i64 %".73", i64* %".74"
  ret void
}

define {i32, i8*}* @"dict_pop"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".7" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 1
  %".10" = load i64, i64* %".9"
  %".11" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 2
  %".12" = load i64, i64* %".11"
  %".13" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 3
  %".14" = load i64*, i64** %".13"
  %".15" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 4
  %".16" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".15"
  %"pop_slot" = alloca i64
  %".17" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"pop_slot")
  %".18" = icmp sge i64 %".17", 0
  br i1 %".18", label %"found", label %"missing"
found:
  %".20" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".16", i32 0, i64 %".17"
  %".21" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".20", i32 0, i32 1
  %".22" = load {i32, i8*}*, {i32, i8*}** %".21"
  %".23" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".20", i32 0, i32 0
  store {i32, i8*}* null, {i32, i8*}** %".23"
  %".25" = load i64, i64* %"pop_slot"
  %".26" = getelementptr i64, i64* %".14", i64 %".25"
  store i64 -1, i64* %".26"
  %".28" = sub i64 %".8", 1
  %".29" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".6", i32 0, i32 0
  store i64 %".28", i64* %".29"
  ret {i32, i8*}* %".22"
missing:
  ret {i32, i8*}* null
}

define i1 @"pyobj_contains"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 5
  br i1 %".6", label %"dict_case", label %"str_check"
str_check:
  %".8" = icmp eq i32 %".5", 2
  br i1 %".8", label %"str_case", label %"list_check"
list_check:
  %".10" = icmp eq i32 %".5", 4
  %".11" = icmp eq i32 %".5", 8
  %".12" = or i1 %".10", %".11"
  br i1 %".12", label %"list_case", label %"type_error"
dict_case:
  %"contains_slot" = alloca i64
  %".14" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"contains_slot")
  %".15" = icmp sge i64 %".14", 0
  ret i1 %".15"
str_case:
  %".17" = call {i32, i8*}* @"str_find"({i32, i8*}* %".1", {i32, i8*}* %".2")
  %".18" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 1
  %".19" = load i8*, i8** %".18"
  %".20" = bitcast i8* %".19" to i64*
  %".21" = load i64, i64* %".20"
  %".22" = icmp sge i64 %".21", 0
  ret i1 %".22"
list_case:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = bitcast i8* %".25" to {i64, i64, {i32, i8*}**}*
  %".27" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".26", i32 0, i32 0
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".26", i32 0, i32 2
  %".30" = load {i32, i8*}**, {i32, i8*}*** %".29"
  %"contains_i" = alloca i64
  store i64 0, i64* %"contains_i"
  br label %"contains_cond"
contains_cond:
  %".33" = load i64, i64* %"contains_i"
  %".34" = icmp slt i64 %".33", %".28"
  br i1 %".34", label %"contains_body", label %"contains_miss"
contains_body:
  %".36" = getelementptr {i32, i8*}*, {i32, i8*}** %".30", i64 %".33"
  %".37" = load {i32, i8*}*, {i32, i8*}** %".36"
  %".38" = call {i32, i8*}* @"pyobj_eq"({i32, i8*}* %".37", {i32, i8*}* %".2")
  %".39" = getelementptr {i32, i8*}, {i32, i8*}* %".38", i32 0, i32 1
  %".40" = load i8*, i8** %".39"
  %".41" = bitcast i8* %".40" to i64*
  %".42" = load i64, i64* %".41"
  %".43" = icmp ne i64 %".42", 0
  br i1 %".43", label %"contains_hit", label %"contains_step"
contains_hit:
  ret i1 1
contains_step:
  %".46" = add i64 %".33", 1
  store i64 %".46", i64* %"contains_i"
  br label %"contains_cond"
contains_miss:
  ret i1 0
type_error:
  %".50" = getelementptr [44 x i8], [44 x i8]* @"str.TypeError_3a_20argument_20of_20type_20is_20not_20iterable", i32 0, i32 0
  call void @"silu_panic"(i8* %".50")
  unreachable
}

@"str.TypeError_3a_20argument_20of_20type_20is_20not_20iterable" = constant [44 x i8] c"TypeError: argument of type is not iterable\00"
define {i32, i8*}* @"create_set"()
{
entry:
  %".2" = call i8* @"malloc"(i64 16)
  %".3" = bitcast i8* %".2" to {i32, i8*}*
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 0
  store i32 8, i32* %".4"
  %".6" = call i8* @"malloc"(i64 24)
  %".7" = bitcast i8* %".6" to {i64, i64, {i32, i8*}**}*
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 0
  store i64 0, i64* %".8"
  %".10" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 1
  store i64 0, i64* %".10"
  %".12" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".7", i32 0, i32 2
  store {i32, i8*}** null, {i32, i8*}*** %".12"
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".3", i32 0, i32 1
  store i8* %".6", i8** %".14"
  ret {i32, i8*}* %".3"
}

define {i32, i8*}* @"pyobj_set_discard"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
sd_entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i64, i64, {i32, i8*}**}*
  %".7" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  br label %"sd_loop"
sd_loop:
  %".10" = phi  i64 [0, %"sd_entry"], [%".19", %"sd_next"]
  %".11" = icmp slt i64 %".10", %".8"
  br i1 %".11", label %"sd_body", label %"sd_done"
sd_shift:
  %".21" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".22" = load {i32, i8*}**, {i32, i8*}*** %".21"
  %".23" = add i64 %".10", 1
  %".24" = getelementptr {i32, i8*}*, {i32, i8*}** %".22", i64 %".23"
  %".25" = getelementptr {i32, i8*}*, {i32, i8*}** %".22", i64 %".10"
  %".26" = add i64 %".10", 1
  %".27" = sub i64 %".8", %".26"
  %".28" = bitcast {i32, i8*}** %".25" to i8*
  %".29" = bitcast {i32, i8*}** %".24" to i8*
  %".30" = mul i64 %".27", 8
  call void @"llvm.memmove.p0i8.p0i8.i64"(i8* %".28", i8* %".29", i64 %".30", i1 0)
  %".32" = sub i64 %".8", 1
  %".33" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 0
  store i64 %".32", i64* %".33"
  br label %"sd_done"
sd_done:
  ret {i32, i8*}* %".1"
sd_body:
  %".13" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".6", i32 0, i32 2
  %".14" = load {i32, i8*}**, {i32, i8*}*** %".13"
  %".15" = getelementptr {i32, i8*}*, {i32, i8*}** %".14", i64 %".10"
  %".16" = load {i32, i8*}*, {i32, i8*}** %".15"
  %".17" = call i1 @"pyobj_deep_eq"({i32, i8*}* %".16", {i32, i8*}* %".2")
  br i1 %".17", label %"sd_shift", label %"sd_next"
sd_next:
  %".19" = add i64 %".10", 1
  br label %"sd_loop"
}

define {i32, i8*}* @"pyobj_set_add"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = call i1 @"pyobj_contains"({i32, i8*}* %".1", {i32, i8*}* %".2")
  br i1 %".4", label %"sa_done", label %"sa_add"
sa_add:
  %".6" = call {i32, i8*}* @"list_append"({i32, i8*}* %".1", {i32, i8*}* %".2")
  br label %"sa_done"
sa_done:
  ret {i32, i8*}* %".1"
}

define {i32, i8*}* @"pyobj_str_conv"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"str_null", label %"dispatch"
str_float:
  %".22" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".23" = load i8*, i8** %".22"
  %".24" = bitcast i8* %".23" to double*
  %".25" = load double, double* %".24"
  %".26" = bitcast i8* %".23" to i64*
  %".27" = load i64, i64* %".26"
  %".28" = sitofp i64 %".27" to double
  %".29" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".30" = load i32, i32* %".29"
  %".31" = icmp eq i32 %".30", 1
  %".32" = select  i1 %".31", double %".25", double %".28"
  %".33" = call i8* @"float_repr"(double %".32")
  %".34" = call i64 @"strlen"(i8* %".33")
  %".35" = trunc i64 %".34" to i32
  %".36" = call {i32, i8*}* @"create_str"(i8* %".33", i32 %".35")
  ret {i32, i8*}* %".36"
str_bool:
  %".39" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".40" = load i8*, i8** %".39"
  %".41" = bitcast i8* %".40" to i64*
  %".42" = load i64, i64* %".41"
  %".43" = icmp ne i64 %".42", 0
  %".44" = getelementptr [5 x i8], [5 x i8]* @"str.True", i32 0, i32 0
  %".45" = getelementptr [6 x i8], [6 x i8]* @"str.False", i32 0, i32 0
  %".46" = select  i1 %".43", i8* %".44", i8* %".45"
  %".47" = select  i1 %".43", i32 4, i32 5
  %".48" = call {i32, i8*}* @"create_str"(i8* %".46", i32 %".47")
  ret {i32, i8*}* %".48"
str_str:
  ret {i32, i8*}* %".1"
str_fail:
  %".50" = getelementptr [47 x i8], [47 x i8]* @"str.TypeError_3a_20str_28_29_20of_20this_20type_20is_20not_20supported", i32 0, i32 0
  call void @"silu_panic"(i8* %".50")
  unreachable
str_null:
  %".5" = getelementptr [5 x i8], [5 x i8]* @"str.None", i32 0, i32 0
  %".6" = call {i32, i8*}* @"create_str"(i8* %".5", i32 4)
  ret {i32, i8*}* %".6"
dispatch:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".9" = load i32, i32* %".8"
  switch i32 %".9", label %"str_fail" [i32 0, label %"str_int" i32 1, label %"str_float" i32 2, label %"str_str" i32 3, label %"str_bool" i32 6, label %"str_null"]
str_int:
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to i64*
  %".14" = load i64, i64* %".13"
  %".15" = call i8* @"malloc"(i64 24)
  %".16" = getelementptr [5 x i8], [5 x i8]* @"str._25lld", i32 0, i32 0
  %".17" = call i32 (i8*, i64, i8*, ...) @"snprintf"(i8* %".15", i64 24, i8* %".16", i64 %".14")
  %".18" = call i64 @"strlen"(i8* %".15")
  %".19" = trunc i64 %".18" to i32
  %".20" = call {i32, i8*}* @"create_str"(i8* %".15", i32 %".19")
  ret {i32, i8*}* %".20"
}

@"str._25lld" = constant [5 x i8] c"%lld\00"
@"str.TypeError_3a_20str_28_29_20of_20this_20type_20is_20not_20supported" = constant [47 x i8] c"TypeError: str() of this type is not supported\00"
declare i32 @"getchar"()

declare i8* @"realloc"(i8* %".1", i64 %".2")

define {i32, i8*}* @"pyobj_input"()
{
entry:
  %"in_cap" = alloca i64
  %"in_len" = alloca i64
  %"in_buf" = alloca i8*
  store i64 64, i64* %"in_cap"
  store i64 0, i64* %"in_len"
  %".4" = call i8* @"malloc"(i64 64)
  store i8* %".4", i8** %"in_buf"
  br label %"read_cond"
read_cond:
  %".7" = call i32 @"getchar"()
  %".8" = icmp eq i32 %".7", -1
  %".9" = icmp eq i32 %".7", 10
  %".10" = or i1 %".8", %".9"
  br i1 %".10", label %"read_eof", label %"read_body"
read_body:
  %".12" = load i64, i64* %"in_len"
  %".13" = load i64, i64* %"in_cap"
  %".14" = icmp eq i64 %".12", %".13"
  br i1 %".14", label %"read_grow", label %"read_store"
read_eof:
  %".30" = load i8*, i8** %"in_buf"
  %".31" = load i64, i64* %"in_len"
  %".32" = trunc i64 %".31" to i32
  %".33" = call {i32, i8*}* @"create_str"(i8* %".30", i32 %".32")
  ret {i32, i8*}* %".33"
read_grow:
  %".16" = mul i64 %".13", 2
  %".17" = load i8*, i8** %"in_buf"
  %".18" = call i8* @"realloc"(i8* %".17", i64 %".16")
  store i64 %".16", i64* %"in_cap"
  store i8* %".18", i8** %"in_buf"
  br label %"read_store"
read_store:
  %".22" = load i8*, i8** %"in_buf"
  %".23" = load i64, i64* %"in_len"
  %".24" = trunc i32 %".7" to i8
  %".25" = getelementptr i8, i8* %".22", i64 %".23"
  store i8 %".24", i8* %".25"
  %".27" = add i64 %".23", 1
  store i64 %".27", i64* %"in_len"
  br label %"read_cond"
}

define {i32, i8*}* @"pyobj_read_stdin"()
{
entry:
  %"rs_cap" = alloca i64
  %"rs_len" = alloca i64
  %"rs_buf" = alloca i8*
  store i64 4096, i64* %"rs_cap"
  store i64 0, i64* %"rs_len"
  %".4" = call i8* @"malloc"(i64 4096)
  store i8* %".4", i8** %"rs_buf"
  br label %"rs_cond"
rs_cond:
  %".7" = call i32 @"getchar"()
  %".8" = icmp eq i32 %".7", -1
  br i1 %".8", label %"rs_done", label %"rs_body"
rs_body:
  %".10" = load i64, i64* %"rs_len"
  %".11" = load i64, i64* %"rs_cap"
  %".12" = icmp eq i64 %".10", %".11"
  br i1 %".12", label %"rs_grow", label %"rs_store"
rs_grow:
  %".14" = mul i64 %".11", 2
  %".15" = load i8*, i8** %"rs_buf"
  %".16" = call i8* @"realloc"(i8* %".15", i64 %".14")
  store i64 %".14", i64* %"rs_cap"
  store i8* %".16", i8** %"rs_buf"
  br label %"rs_store"
rs_store:
  %".20" = trunc i32 %".7" to i8
  %".21" = load i8*, i8** %"rs_buf"
  %".22" = load i64, i64* %"rs_len"
  %".23" = getelementptr i8, i8* %".21", i64 %".22"
  store i8 %".20", i8* %".23"
  %".25" = load i64, i64* %"rs_len"
  %".26" = add i64 %".25", 1
  store i64 %".26", i64* %"rs_len"
  br label %"rs_cond"
rs_done:
  %".29" = load i8*, i8** %"rs_buf"
  %".30" = load i64, i64* %"rs_len"
  %".31" = trunc i64 %".30" to i32
  %".32" = call {i32, i8*}* @"create_str"(i8* %".29", i32 %".31")
  ret {i32, i8*}* %".32"
}

declare i8* @"fopen"(i8* %".1", i8* %".2")

declare i64 @"fread"(i8* %".1", i64 %".2", i64 %".3", i8* %".4")

declare i32 @"fseek"(i8* %".1", i64 %".2", i32 %".3")

declare i64 @"ftell"(i8* %".1")

declare i32 @"fclose"(i8* %".1")

define {i32, i8*}* @"pyobj_read_file"(i8* %".1", i64 %".2")
{
entry:
  %".4" = add i64 %".2", 1
  %".5" = call i8* @"malloc"(i64 %".4")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".5", i8* %".1", i64 %".2", i1 0)
  %".7" = getelementptr i8, i8* %".5", i64 %".2"
  store i8 0, i8* %".7"
  %".9" = getelementptr [2 x i8], [2 x i8]* @"str.r", i32 0, i32 0
  %".10" = call i8* @"fopen"(i8* %".5", i8* %".9")
  %".11" = icmp eq i8* %".10", null
  br i1 %".11", label %"rf_fail", label %"rf_ok"
rf_fail:
  %".13" = getelementptr [26 x i8], [26 x i8]* @"str.OSError_3a_20cannot_20open_20file", i32 0, i32 0
  call void @"silu_panic"(i8* %".13")
  unreachable
rf_ok:
  %".16" = call i32 @"fseek"(i8* %".10", i64 0, i32 2)
  %".17" = call i64 @"ftell"(i8* %".10")
  %".18" = call i32 @"fseek"(i8* %".10", i64 0, i32 0)
  %".19" = add i64 %".17", 1
  %".20" = call i8* @"malloc"(i64 %".19")
  %".21" = call i64 @"fread"(i8* %".20", i64 1, i64 %".17", i8* %".10")
  %".22" = call i32 @"fclose"(i8* %".10")
  %".23" = trunc i64 %".17" to i32
  %".24" = call {i32, i8*}* @"create_str"(i8* %".20", i32 %".23")
  ret {i32, i8*}* %".24"
}

@"str.r" = constant [2 x i8] c"r\00"
@"str.OSError_3a_20cannot_20open_20file" = constant [26 x i8] c"OSError: cannot open file\00"
define i1 @"silu_path_exists"(i8* %".1", i64 %".2")
{
pe_entry:
  %".4" = add i64 %".2", 1
  %".5" = call i8* @"malloc"(i64 %".4")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".5", i8* %".1", i64 %".2", i1 0)
  %".7" = getelementptr i8, i8* %".5", i64 %".2"
  store i8 0, i8* %".7"
  %".9" = getelementptr [2 x i8], [2 x i8]* @"str.r", i32 0, i32 0
  %".10" = call i8* @"fopen"(i8* %".5", i8* %".9")
  %".11" = icmp eq i8* %".10", null
  br i1 %".11", label %"pe_no", label %"pe_yes"
pe_yes:
  %".13" = call i32 @"fclose"(i8* %".10")
  ret i1 1
pe_no:
  ret i1 0
}

define void @"dict_clear_entries"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".6" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  %".15" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  store i64 0, i64* %".16"
  %".18" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  store i64 0, i64* %".18"
  %"wipe_i" = alloca i64
  store i64 0, i64* %"wipe_i"
  br label %"wipe_cond"
wipe_cond:
  %".22" = load i64, i64* %"wipe_i"
  %".23" = icmp sle i64 %".22", %".11"
  br i1 %".23", label %"wipe_body", label %"wipe_done"
wipe_body:
  %".25" = getelementptr i64, i64* %".13", i64 %".22"
  store i64 0, i64* %".25"
  %".27" = add i64 %".22", 1
  store i64 %".27", i64* %"wipe_i"
  br label %"wipe_cond"
wipe_done:
  ret void
}

define {i32, i8*}* @"dict_setdefault"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 1
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 2
  %".13" = load i64, i64* %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 3
  %".15" = load i64*, i64** %".14"
  %".16" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".7", i32 0, i32 4
  %".17" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".16"
  %"sd_slot" = alloca i64
  %".18" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"sd_slot")
  %".19" = icmp sge i64 %".18", 0
  br i1 %".19", label %"found", label %"insert"
found:
  %".21" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".17", i32 0, i64 %".18"
  %".22" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".21", i32 0, i32 1
  %".23" = load {i32, i8*}*, {i32, i8*}** %".22"
  ret {i32, i8*}* %".23"
insert:
  call void @"dict_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
  ret {i32, i8*}* %".3"
}

define {i32, i8*}* @"dict_items_rt"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".6" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  %".15" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".14"
  %".16" = call {i32, i8*}* @"create_list"()
  %"dict_items_rt_i" = alloca i64
  store i64 0, i64* %"dict_items_rt_i"
  br label %"dict_items_rt_cond"
dict_items_rt_cond:
  %".19" = load i64, i64* %"dict_items_rt_i"
  %".20" = icmp slt i64 %".19", %".9"
  br i1 %".20", label %"dict_items_rt_body", label %"dict_items_rt_done"
dict_items_rt_body:
  %".22" = load i64, i64* %"dict_items_rt_i"
  %".23" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".15", i32 0, i64 %".22"
  %".24" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 0
  %".25" = load {i32, i8*}*, {i32, i8*}** %".24"
  %".26" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 1
  %".27" = load {i32, i8*}*, {i32, i8*}** %".26"
  %".28" = icmp ne {i32, i8*}* %".25", null
  br i1 %".28", label %"dict_items_rt_live", label %"dict_items_rt_step"
dict_items_rt_done:
  ret {i32, i8*}* %".16"
dict_items_rt_live:
  %".30" = call {i32, i8*}* @"create_list"()
  %".31" = call {i32, i8*}* @"list_append"({i32, i8*}* %".30", {i32, i8*}* %".25")
  %".32" = call {i32, i8*}* @"list_append"({i32, i8*}* %".30", {i32, i8*}* %".27")
  %".33" = call {i32, i8*}* @"list_append"({i32, i8*}* %".16", {i32, i8*}* %".30")
  br label %"dict_items_rt_step"
dict_items_rt_step:
  %".35" = load i64, i64* %"dict_items_rt_i"
  %".36" = add i64 %".35", 1
  store i64 %".36", i64* %"dict_items_rt_i"
  br label %"dict_items_rt_cond"
}

define {i32, i8*}* @"dict_keys_rt"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".6" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  %".15" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".14"
  %".16" = call {i32, i8*}* @"create_list"()
  %"dict_keys_rt_i" = alloca i64
  store i64 0, i64* %"dict_keys_rt_i"
  br label %"dict_keys_rt_cond"
dict_keys_rt_cond:
  %".19" = load i64, i64* %"dict_keys_rt_i"
  %".20" = icmp slt i64 %".19", %".9"
  br i1 %".20", label %"dict_keys_rt_body", label %"dict_keys_rt_done"
dict_keys_rt_body:
  %".22" = load i64, i64* %"dict_keys_rt_i"
  %".23" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".15", i32 0, i64 %".22"
  %".24" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 0
  %".25" = load {i32, i8*}*, {i32, i8*}** %".24"
  %".26" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 1
  %".27" = load {i32, i8*}*, {i32, i8*}** %".26"
  %".28" = icmp ne {i32, i8*}* %".25", null
  br i1 %".28", label %"dict_keys_rt_live", label %"dict_keys_rt_step"
dict_keys_rt_done:
  ret {i32, i8*}* %".16"
dict_keys_rt_live:
  %".30" = call {i32, i8*}* @"list_append"({i32, i8*}* %".16", {i32, i8*}* %".25")
  br label %"dict_keys_rt_step"
dict_keys_rt_step:
  %".32" = load i64, i64* %"dict_keys_rt_i"
  %".33" = add i64 %".32", 1
  store i64 %".33", i64* %"dict_keys_rt_i"
  br label %"dict_keys_rt_cond"
}

define {i32, i8*}* @"dict_values_rt"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".6" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 2
  %".11" = load i64, i64* %".10"
  %".12" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 3
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".5", i32 0, i32 4
  %".15" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".14"
  %".16" = call {i32, i8*}* @"create_list"()
  %"dict_values_rt_i" = alloca i64
  store i64 0, i64* %"dict_values_rt_i"
  br label %"dict_values_rt_cond"
dict_values_rt_cond:
  %".19" = load i64, i64* %"dict_values_rt_i"
  %".20" = icmp slt i64 %".19", %".9"
  br i1 %".20", label %"dict_values_rt_body", label %"dict_values_rt_done"
dict_values_rt_body:
  %".22" = load i64, i64* %"dict_values_rt_i"
  %".23" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".15", i32 0, i64 %".22"
  %".24" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 0
  %".25" = load {i32, i8*}*, {i32, i8*}** %".24"
  %".26" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".23", i32 0, i32 1
  %".27" = load {i32, i8*}*, {i32, i8*}** %".26"
  %".28" = icmp ne {i32, i8*}* %".25", null
  br i1 %".28", label %"dict_values_rt_live", label %"dict_values_rt_step"
dict_values_rt_done:
  ret {i32, i8*}* %".16"
dict_values_rt_live:
  %".30" = call {i32, i8*}* @"list_append"({i32, i8*}* %".16", {i32, i8*}* %".27")
  br label %"dict_values_rt_step"
dict_values_rt_step:
  %".32" = load i64, i64* %"dict_values_rt_i"
  %".33" = add i64 %".32", 1
  store i64 %".33", i64* %"dict_values_rt_i"
  br label %"dict_values_rt_cond"
}

define void @"dict_update"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 4
  br i1 %".6", label %"upd_src_list", label %"upd_src_check"
upd_src_check:
  %".36" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".37" = load i8*, i8** %".36"
  %".38" = bitcast i8* %".37" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".39" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".38", i32 0, i32 0
  %".40" = load i64, i64* %".39"
  %".41" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".38", i32 0, i32 1
  %".42" = load i64, i64* %".41"
  %".43" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".38", i32 0, i32 2
  %".44" = load i64, i64* %".43"
  %".45" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".38", i32 0, i32 3
  %".46" = load i64*, i64** %".45"
  %".47" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".38", i32 0, i32 4
  %".48" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".47"
  %"upd_i" = alloca i64
  store i64 0, i64* %"upd_i"
  br label %"upd_check"
upd_src_list:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = bitcast i8* %".9" to {i64, i64, {i32, i8*}**}*
  %".11" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".10", i32 0, i32 0
  %".12" = load i64, i64* %".11"
  %".13" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".10", i32 0, i32 2
  %".14" = load {i32, i8*}**, {i32, i8*}*** %".13"
  %"upd_pair_i" = alloca i64
  store i64 0, i64* %"upd_pair_i"
  br label %"upd_pair_check"
upd_check:
  %".51" = load i64, i64* %"upd_i"
  %".52" = icmp slt i64 %".51", %".42"
  br i1 %".52", label %"upd_body", label %"upd_done"
upd_body:
  %".54" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".48", i32 0, i64 %".51"
  %".55" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".54", i32 0, i32 0
  %".56" = load {i32, i8*}*, {i32, i8*}** %".55"
  %".57" = icmp ne {i32, i8*}* %".56", null
  %".58" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".54", i32 0, i32 1
  %".59" = load {i32, i8*}*, {i32, i8*}** %".58"
  br i1 %".57", label %"upd_live", label %"upd_step"
upd_step:
  %".63" = add i64 %".51", 1
  store i64 %".63", i64* %"upd_i"
  br label %"upd_check"
upd_done:
  ret void
upd_pair_check:
  %".17" = load i64, i64* %"upd_pair_i"
  %".18" = icmp slt i64 %".17", %".12"
  br i1 %".18", label %"upd_pair_body", label %"upd_pair_done"
upd_pair_body:
  %".20" = getelementptr {i32, i8*}*, {i32, i8*}** %".14", i64 %".17"
  %".21" = load {i32, i8*}*, {i32, i8*}** %".20"
  %".22" = getelementptr {i32, i8*}, {i32, i8*}* %".21", i32 0, i32 1
  %".23" = load i8*, i8** %".22"
  %".24" = bitcast i8* %".23" to {i64, i64, {i32, i8*}**}*
  %".25" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".24", i32 0, i32 2
  %".26" = load {i32, i8*}**, {i32, i8*}*** %".25"
  %".27" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 0
  %".28" = load {i32, i8*}*, {i32, i8*}** %".27"
  %".29" = getelementptr {i32, i8*}*, {i32, i8*}** %".26", i64 1
  %".30" = load {i32, i8*}*, {i32, i8*}** %".29"
  call void @"dict_set"({i32, i8*}* %".1", {i32, i8*}* %".28", {i32, i8*}* %".30")
  %".32" = add i64 %".17", 1
  store i64 %".32", i64* %"upd_pair_i"
  br label %"upd_pair_check"
upd_pair_done:
  ret void
upd_live:
  call void @"dict_set"({i32, i8*}* %".1", {i32, i8*}* %".56", {i32, i8*}* %".59")
  br label %"upd_step"
}

define {i32, i8*}* @"pyobj_update_dispatch"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 4
  %".7" = icmp eq i32 %".5", 8
  %".8" = or i1 %".6", %".7"
  br i1 %".8", label %"ud_set", label %"ud_dict"
ud_set:
  %".12" = call {i32, i8*}* @"pyobj_iter_keys"({i32, i8*}* %".2")
  %".13" = call i64 @"list_length"({i32, i8*}* %".12")
  %"ud_i" = alloca i64
  store i64 0, i64* %"ud_i"
  br label %"ud_cond"
ud_dict:
  call void @"dict_update"({i32, i8*}* %".1", {i32, i8*}* %".2")
  ret {i32, i8*}* %".1"
ud_cond:
  %".16" = load i64, i64* %"ud_i"
  %".17" = icmp slt i64 %".16", %".13"
  br i1 %".17", label %"ud_body", label %"ud_done"
ud_body:
  %".19" = load i64, i64* %"ud_i"
  %".20" = call {i32, i8*}* @"create_int"(i64 %".19")
  %".21" = call {i32, i8*}* @"list_get"({i32, i8*}* %".12", {i32, i8*}* %".20")
  %".22" = call {i32, i8*}* @"pyobj_set_add"({i32, i8*}* %".1", {i32, i8*}* %".21")
  %".23" = load i64, i64* %"ud_i"
  %".24" = add i64 %".23", 1
  store i64 %".24", i64* %"ud_i"
  br label %"ud_cond"
ud_done:
  ret {i32, i8*}* %".1"
}

define {i32, i8*}* @"pyobj_str_char_at"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to i64*
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = bitcast i8* %".9" to {i32, i8*}*
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".10", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = sext i32 %".12" to i64
  %".14" = icmp slt i64 %".7", 0
  %".15" = add i64 %".7", %".13"
  %".16" = select  i1 %".14", i64 %".15", i64 %".7"
  %".17" = icmp sge i64 %".16", 0
  %".18" = icmp slt i64 %".16", %".13"
  %".19" = and i1 %".17", %".18"
  br i1 %".19", label %"ok", label %"index_error"
ok:
  %".24" = getelementptr {i32, i8*}, {i32, i8*}* %".10", i32 0, i32 1
  %".25" = load i8*, i8** %".24"
  %".26" = call i8* @"malloc"(i64 1)
  %".27" = getelementptr i8, i8* %".25", i64 %".16"
  %".28" = load i8, i8* %".27"
  store i8 %".28", i8* %".26"
  %".30" = call {i32, i8*}* @"create_str"(i8* %".26", i32 1)
  ret {i32, i8*}* %".30"
index_error:
  %".21" = getelementptr [38 x i8], [38 x i8]* @"str.IndexError_3a_20string_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".21")
  unreachable
}

@"str.IndexError_3a_20string_20index_20out_20of_20range" = constant [38 x i8] c"IndexError: string index out of range\00"
define {i32, i8*}* @"pyobj_str_slice"({i32, i8*}* %".1", i64 %".2", i64 %".3", i64 %".4", i1 %".5", i1 %".6")
{
entry:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".9" = load i32, i32* %".8"
  %".10" = icmp ne i32 %".9", 2
  br i1 %".10", label %"tag_error", label %"str_case"
step_ok:
  %".28" = icmp slt i64 %".4", 0
  %".29" = sub i64 %".20", 1
  %".30" = select  i1 %".28", i64 %".29", i64 0
  %".31" = select  i1 %".28", i64 %".29", i64 %".20"
  %".32" = icmp slt i64 %".2", 0
  %".33" = add i64 %".2", %".20"
  %".34" = select  i1 %".32", i64 %".33", i64 %".2"
  %".35" = select  i1 %".5", i64 %".34", i64 %".30"
  %".36" = icmp slt i64 %".35", 0
  %".37" = select  i1 %".36", i64 0, i64 %".35"
  %".38" = icmp sgt i64 %".37", %".31"
  %".39" = select  i1 %".38", i64 %".31", i64 %".37"
  %".40" = select  i1 %".28", i64 -1, i64 %".20"
  %".41" = select  i1 %".28", i64 -1, i64 0
  %".42" = select  i1 %".28", i64 %".29", i64 %".20"
  %".43" = icmp slt i64 %".3", 0
  %".44" = add i64 %".3", %".20"
  %".45" = select  i1 %".43", i64 %".44", i64 %".3"
  %".46" = select  i1 %".6", i64 %".45", i64 %".40"
  %".47" = icmp slt i64 %".46", %".41"
  %".48" = select  i1 %".47", i64 %".41", i64 %".46"
  %".49" = icmp sgt i64 %".48", %".42"
  %".50" = select  i1 %".49", i64 %".42", i64 %".48"
  %".51" = sub i64 %".50", %".39"
  %".52" = sub i64 %".51", 1
  %".53" = sdiv i64 %".52", %".4"
  %".54" = icmp sgt i64 %".51", 0
  %".55" = add i64 %".53", 1
  %".56" = select  i1 %".54", i64 %".55", i64 0
  %".57" = sub i64 0, %".4"
  %".58" = sub i64 %".39", %".50"
  %".59" = sub i64 %".58", 1
  %".60" = sdiv i64 %".59", %".57"
  %".61" = icmp sgt i64 %".58", 0
  %".62" = add i64 %".60", 1
  %".63" = select  i1 %".61", i64 %".62", i64 0
  %".64" = select  i1 %".28", i64 %".63", i64 %".56"
  %".65" = icmp sgt i64 %".64", 0
  %".66" = select  i1 %".65", i64 %".64", i64 1
  %".67" = call i8* @"malloc"(i64 %".66")
  %"slice_i" = alloca i64
  store i64 0, i64* %"slice_i"
  br label %"copy_cond"
zero_step:
  %".25" = getelementptr [38 x i8], [38 x i8]* @"str.ValueError_3a_20slice_20step_20cannot_20be_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".25")
  unreachable
copy_cond:
  %".70" = load i64, i64* %"slice_i"
  %".71" = icmp slt i64 %".70", %".64"
  br i1 %".71", label %"copy_body", label %"copy_done"
copy_body:
  %".73" = mul i64 %".70", %".4"
  %".74" = add i64 %".39", %".73"
  %".75" = getelementptr i8, i8* %".22", i64 %".74"
  %".76" = load i8, i8* %".75"
  %".77" = getelementptr i8, i8* %".67", i64 %".70"
  store i8 %".76", i8* %".77"
  %".79" = add i64 %".70", 1
  store i64 %".79", i64* %"slice_i"
  br label %"copy_cond"
copy_done:
  %".82" = trunc i64 %".64" to i32
  %".83" = call {i32, i8*}* @"create_str"(i8* %".67", i32 %".82")
  ret {i32, i8*}* %".83"
tag_error:
  %".12" = getelementptr [41 x i8], [41 x i8]* @"str.TypeError_3a_20only_20str_20slicing_20is_20supported", i32 0, i32 0
  call void @"silu_panic"(i8* %".12")
  unreachable
str_case:
  %".15" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".16" = load i8*, i8** %".15"
  %".17" = bitcast i8* %".16" to {i32, i8*}*
  %".18" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 0
  %".19" = load i32, i32* %".18"
  %".20" = sext i32 %".19" to i64
  %".21" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 1
  %".22" = load i8*, i8** %".21"
  %".23" = icmp eq i64 %".4", 0
  br i1 %".23", label %"zero_step", label %"step_ok"
}

@"str.TypeError_3a_20only_20str_20slicing_20is_20supported" = constant [41 x i8] c"TypeError: only str slicing is supported\00"
@"str.ValueError_3a_20slice_20step_20cannot_20be_20zero" = constant [38 x i8] c"ValueError: slice step cannot be zero\00"
define {i32, i8*}* @"pyobj_list_slice"({i32, i8*}* %".1", i64 %".2", i64 %".3", i64 %".4", i1 %".5", i1 %".6")
{
entry:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".9" = load i32, i32* %".8"
  %".10" = icmp ne i32 %".9", 4
  br i1 %".10", label %"ls_tag_error", label %"lst_case"
lst_case:
  %".15" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".16" = load i8*, i8** %".15"
  %".17" = bitcast i8* %".16" to {i64, i64, {i32, i8*}**}*
  %".18" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".17", i32 0, i32 0
  %".19" = load i64, i64* %".18"
  %".20" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".17", i32 0, i32 2
  %".21" = load {i32, i8*}**, {i32, i8*}*** %".20"
  %".22" = icmp eq i64 %".4", 0
  br i1 %".22", label %"ls_zero_step", label %"ls_step_ok"
ls_zero_step:
  %".24" = getelementptr [38 x i8], [38 x i8]* @"str.ValueError_3a_20slice_20step_20cannot_20be_20zero", i32 0, i32 0
  call void @"silu_panic"(i8* %".24")
  unreachable
ls_step_ok:
  %".27" = icmp slt i64 %".4", 0
  %".28" = sub i64 %".19", 1
  %".29" = select  i1 %".27", i64 %".28", i64 0
  %".30" = select  i1 %".27", i64 %".28", i64 %".19"
  %".31" = icmp slt i64 %".2", 0
  %".32" = add i64 %".2", %".19"
  %".33" = select  i1 %".31", i64 %".32", i64 %".2"
  %".34" = select  i1 %".5", i64 %".33", i64 %".29"
  %".35" = icmp slt i64 %".34", 0
  %".36" = select  i1 %".35", i64 0, i64 %".34"
  %".37" = icmp sgt i64 %".36", %".30"
  %".38" = select  i1 %".37", i64 %".30", i64 %".36"
  %".39" = select  i1 %".27", i64 -1, i64 %".19"
  %".40" = select  i1 %".27", i64 -1, i64 0
  %".41" = select  i1 %".27", i64 %".28", i64 %".19"
  %".42" = icmp slt i64 %".3", 0
  %".43" = add i64 %".3", %".19"
  %".44" = select  i1 %".42", i64 %".43", i64 %".3"
  %".45" = select  i1 %".6", i64 %".44", i64 %".39"
  %".46" = icmp slt i64 %".45", %".40"
  %".47" = select  i1 %".46", i64 %".40", i64 %".45"
  %".48" = icmp sgt i64 %".47", %".41"
  %".49" = select  i1 %".48", i64 %".41", i64 %".47"
  %".50" = sub i64 %".49", %".38"
  %".51" = sub i64 %".50", 1
  %".52" = sdiv i64 %".51", %".4"
  %".53" = icmp sgt i64 %".50", 0
  %".54" = add i64 %".52", 1
  %".55" = select  i1 %".53", i64 %".54", i64 0
  %".56" = sub i64 0, %".4"
  %".57" = sub i64 %".38", %".49"
  %".58" = sub i64 %".57", 1
  %".59" = sdiv i64 %".58", %".56"
  %".60" = icmp sgt i64 %".57", 0
  %".61" = add i64 %".59", 1
  %".62" = select  i1 %".60", i64 %".61", i64 0
  %".63" = select  i1 %".27", i64 %".62", i64 %".55"
  %".64" = call {i32, i8*}* @"create_list"()
  %"ls_i" = alloca i64
  store i64 0, i64* %"ls_i"
  br label %"ls_cond"
ls_cond:
  %".67" = load i64, i64* %"ls_i"
  %".68" = icmp slt i64 %".67", %".63"
  br i1 %".68", label %"ls_body", label %"ls_done"
ls_body:
  %".70" = mul i64 %".67", %".4"
  %".71" = add i64 %".38", %".70"
  %".72" = mul i64 %".67", %".56"
  %".73" = sub i64 %".38", %".72"
  %".74" = select  i1 %".27", i64 %".73", i64 %".71"
  %".75" = getelementptr {i32, i8*}*, {i32, i8*}** %".21", i64 %".74"
  %".76" = load {i32, i8*}*, {i32, i8*}** %".75"
  %".77" = call {i32, i8*}* @"list_append"({i32, i8*}* %".64", {i32, i8*}* %".76")
  %".78" = add i64 %".67", 1
  store i64 %".78", i64* %"ls_i"
  br label %"ls_cond"
ls_done:
  ret {i32, i8*}* %".64"
ls_tag_error:
  %".12" = getelementptr [42 x i8], [42 x i8]* @"str.TypeError_3a_20only_20list_20slicing_20is_20supported", i32 0, i32 0
  call void @"silu_panic"(i8* %".12")
  unreachable
}

@"str.TypeError_3a_20only_20list_20slicing_20is_20supported" = constant [42 x i8] c"TypeError: only list slicing is supported\00"
define {i32, i8*}* @"pyobj_slice_any"({i32, i8*}* %".1", i64 %".2", i64 %".3", i64 %".4", i1 %".5", i1 %".6")
{
entry:
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".9" = load i32, i32* %".8"
  %".10" = icmp eq i32 %".9", 2
  br i1 %".10", label %"sa_str", label %"sa_lst_chk"
sa_str:
  %".12" = call {i32, i8*}* @"pyobj_str_slice"({i32, i8*}* %".1", i64 %".2", i64 %".3", i64 %".4", i1 %".5", i1 %".6")
  ret {i32, i8*}* %".12"
sa_lst_chk:
  %".14" = icmp eq i32 %".9", 4
  br i1 %".14", label %"sa_do_list", label %"sa_error"
sa_do_list:
  %".16" = call {i32, i8*}* @"pyobj_list_slice"({i32, i8*}* %".1", i64 %".2", i64 %".3", i64 %".4", i1 %".5", i1 %".6")
  ret {i32, i8*}* %".16"
sa_error:
  %".18" = getelementptr [35 x i8], [35 x i8]* @"str.TypeError_3a_20object_20is_20not_20sliceable", i32 0, i32 0
  call void @"silu_panic"(i8* %".18")
  unreachable
}

@"str.TypeError_3a_20object_20is_20not_20sliceable" = constant [35 x i8] c"TypeError: object is not sliceable\00"
define {i32, i8*}* @"pyobj_subscript"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 4
  br i1 %".6", label %"sub_list", label %"sub_str_check"
sub_list:
  %".12" = call {i32, i8*}* @"list_get"({i32, i8*}* %".1", {i32, i8*}* %".2")
  ret {i32, i8*}* %".12"
sub_str_check:
  %".8" = icmp eq i32 %".5", 2
  br i1 %".8", label %"sub_str_do", label %"sub_dict_check"
sub_str_do:
  %".10" = call {i32, i8*}* @"pyobj_str_char_at"({i32, i8*}* %".1", {i32, i8*}* %".2")
  ret {i32, i8*}* %".10"
sub_dict_check:
  %".14" = icmp eq i32 %".5", 5
  br i1 %".14", label %"sub_dict_do", label %"sub_error"
sub_dict_do:
  %"sub_slot" = alloca i64
  %".16" = call i64 @"dict_find_probe"({i32, i8*}* %".1", {i32, i8*}* %".2", i64* %"sub_slot")
  %".17" = icmp sge i64 %".16", 0
  br i1 %".17", label %"sub_dict_hit", label %"sub_key_error"
sub_error:
  %".39" = getelementptr [39 x i8], [39 x i8]* @"str.TypeError_3a_20object_20is_20not_20subscriptable", i32 0, i32 0
  call void @"silu_panic"(i8* %".39")
  unreachable
sub_dict_hit:
  %".19" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".20" = load i8*, i8** %".19"
  %".21" = bitcast i8* %".20" to {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}*
  %".22" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".21", i32 0, i32 0
  %".23" = load i64, i64* %".22"
  %".24" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".21", i32 0, i32 1
  %".25" = load i64, i64* %".24"
  %".26" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".21", i32 0, i32 2
  %".27" = load i64, i64* %".26"
  %".28" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".21", i32 0, i32 3
  %".29" = load i64*, i64** %".28"
  %".30" = getelementptr {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}, {i64, i64, i64, i64*, [0 x {{i32, i8*}*, {i32, i8*}*}]*}* %".21", i32 0, i32 4
  %".31" = load [0 x {{i32, i8*}*, {i32, i8*}*}]*, [0 x {{i32, i8*}*, {i32, i8*}*}]** %".30"
  %".32" = getelementptr [0 x {{i32, i8*}*, {i32, i8*}*}], [0 x {{i32, i8*}*, {i32, i8*}*}]* %".31", i32 0, i64 %".16"
  %".33" = getelementptr {{i32, i8*}*, {i32, i8*}*}, {{i32, i8*}*, {i32, i8*}*}* %".32", i32 0, i32 1
  %".34" = load {i32, i8*}*, {i32, i8*}** %".33"
  ret {i32, i8*}* %".34"
sub_key_error:
  %".36" = getelementptr [24 x i8], [24 x i8]* @"str.KeyError_3a_20key_20not_20found", i32 0, i32 0
  call void @"silu_panic"(i8* %".36")
  unreachable
}

@"str.KeyError_3a_20key_20not_20found" = constant [24 x i8] c"KeyError: key not found\00"
@"str.TypeError_3a_20object_20is_20not_20subscriptable" = constant [39 x i8] c"TypeError: object is not subscriptable\00"
define void @"pyobj_subscript_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
{
entry:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  %".7" = icmp eq i32 %".6", 4
  br i1 %".7", label %"sub_list", label %"sub_dict_check"
sub_list:
  call void @"list_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
  ret void
sub_dict_check:
  %".11" = icmp eq i32 %".6", 5
  br i1 %".11", label %"sub_dict_do", label %"sub_error"
sub_dict_do:
  call void @"dict_set"({i32, i8*}* %".1", {i32, i8*}* %".2", {i32, i8*}* %".3")
  ret void
sub_error:
  %".15" = getelementptr [51 x i8], [51 x i8]* @"str.TypeError_3a_20object_20does_20not_20support_20item_20assignment", i32 0, i32 0
  call void @"silu_panic"(i8* %".15")
  unreachable
}

@"str.TypeError_3a_20object_20does_20not_20support_20item_20assignment" = constant [51 x i8] c"TypeError: object does not support item assignment\00"
define void @"pyobj_clear"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 4
  br i1 %".5", label %"clear_list", label %"clear_dict_check"
clear_list:
  call void @"list_clear"({i32, i8*}* %".1")
  ret void
clear_dict_check:
  %".9" = icmp eq i32 %".4", 5
  br i1 %".9", label %"clear_dict", label %"clear_error"
clear_dict:
  call void @"dict_clear_entries"({i32, i8*}* %".1")
  ret void
clear_error:
  %".13" = getelementptr [38 x i8], [38 x i8]* @"str.AttributeError_3a_20object_20has_20no_20clear_28_29", i32 0, i32 0
  call void @"silu_panic"(i8* %".13")
  unreachable
}

@"str.AttributeError_3a_20object_20has_20no_20clear_28_29" = constant [38 x i8] c"AttributeError: object has no clear()\00"
declare double @"llvm.sqrt.f64"(double %".1")

declare double @"pow"(double %".1", double %".2")

define i64 @"unbox_int"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"unbox_bad", label %"unbox_ok"
unbox_ok:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to i64*
  %".10" = load i64, i64* %".9"
  ret i64 %".10"
unbox_bad:
  %".12" = getelementptr [33 x i8], [33 x i8]* @"str.TypeError_3a_20expected_20an_20int_20value", i32 0, i32 0
  call void @"silu_panic"(i8* %".12")
  unreachable
}

@"str.TypeError_3a_20expected_20an_20int_20value" = constant [33 x i8] c"TypeError: expected an int value\00"
define double @"unbox_float"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"unbox_bad", label %"unbox_ok"
unbox_ok:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to i64*
  %".10" = load i64, i64* %".9"
  %".11" = icmp eq i32 %".6", 1
  %".12" = bitcast i8* %".8" to double*
  %".13" = load double, double* %".12"
  %".14" = sitofp i64 %".10" to double
  %".15" = select  i1 %".11", double %".13", double %".14"
  ret double %".15"
unbox_bad:
  %".17" = getelementptr [34 x i8], [34 x i8]* @"str.TypeError_3a_20expected_20a_20float_20value", i32 0, i32 0
  call void @"silu_panic"(i8* %".17")
  unreachable
}

@"str.TypeError_3a_20expected_20a_20float_20value" = constant [34 x i8] c"TypeError: expected a float value\00"
define i1 @"unbox_bool"({i32, i8*}* %".1")
{
entry:
  %".3" = icmp eq {i32, i8*}* %".1", null
  br i1 %".3", label %"unbox_bad", label %"unbox_ok"
unbox_ok:
  %".5" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".6" = load i32, i32* %".5"
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to i64*
  %".10" = load i64, i64* %".9"
  %".11" = icmp ne i64 %".10", 0
  ret i1 %".11"
unbox_bad:
  %".13" = getelementptr [33 x i8], [33 x i8]* @"str.TypeError_3a_20expected_20a_20bool_20value", i32 0, i32 0
  call void @"silu_panic"(i8* %".13")
  unreachable
}

@"str.TypeError_3a_20expected_20a_20bool_20value" = constant [33 x i8] c"TypeError: expected a bool value\00"
define i1 @"pyobj_identity_eq"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = icmp eq {i32, i8*}* %".1", %".2"
  %".5" = icmp eq {i32, i8*}* %".1", null
  %".6" = icmp eq {i32, i8*}* %".2", null
  %".7" = or i1 %".5", %".6"
  br i1 %".7", label %"merge", label %"tags"
tags:
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".10" = load i32, i32* %".9"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".12" = load i32, i32* %".11"
  %".13" = icmp eq i32 %".10", 6
  %".14" = icmp eq i32 %".12", 6
  %".15" = and i1 %".13", %".14"
  br i1 %".15", label %"both_inst", label %"merge"
both_inst:
  %".17" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".1")
  %".18" = call i8* @"pyobj_instance_ptr"({i32, i8*}* %".2")
  %".19" = icmp eq i8* %".17", %".18"
  br label %"merge"
merge:
  %".21" = phi  i1 [%".4", %"entry"], [%".4", %"tags"], [%".19", %"both_inst"]
  ret i1 %".21"
}

define {i32, i8*}* @"pyobj_pop_dispatch"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 4
  br i1 %".6", label %"list_case", label %"dict_case"
list_case:
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".11" = load i8*, i8** %".10"
  %".12" = bitcast i8* %".11" to {i64, i64, {i32, i8*}**}*
  %".13" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".12", i32 0, i32 0
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq {i32, i8*}* %".2", null
  br i1 %".15", label %"pop_idx", label %"pop_bounds"
dict_case:
  %".8" = call {i32, i8*}* @"dict_pop"({i32, i8*}* %".1", {i32, i8*}* %".2")
  ret {i32, i8*}* %".8"
pop_empty:
  %".32" = getelementptr [32 x i8], [32 x i8]* @"str.IndexError_3a_20pop_20from_20empty_20list", i32 0, i32 0
  call void @"silu_panic"(i8* %".32")
  unreachable
pop_idx:
  %".17" = sub i64 %".14", 1
  br label %"pop_bad"
pop_bounds:
  %".19" = call i64 @"unbox_int"({i32, i8*}* %".2")
  %".20" = icmp slt i64 %".19", 0
  %".21" = add i64 %".19", %".14"
  %".22" = select  i1 %".20", i64 %".21", i64 %".19"
  br label %"pop_bad"
pop_bad:
  %".24" = phi  i64 [%".17", %"pop_idx"], [%".22", %"pop_bounds"]
  %".25" = icmp sge i64 %".24", 0
  %".26" = icmp slt i64 %".24", %".14"
  %".27" = and i1 %".25", %".26"
  %".28" = icmp eq i64 %".14", 0
  %".29" = xor i1 %".27", -1
  %".30" = or i1 %".28", %".29"
  br i1 %".30", label %"pop_empty", label %"pop_ok"
pop_ok:
  %".35" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".12", i32 0, i32 2
  %".36" = load {i32, i8*}**, {i32, i8*}*** %".35"
  %".37" = getelementptr {i32, i8*}*, {i32, i8*}** %".36", i64 %".24"
  %".38" = load {i32, i8*}*, {i32, i8*}** %".37"
  %".39" = sub i64 %".14", 1
  %".40" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".12", i32 0, i32 0
  store i64 %".39", i64* %".40"
  %"pop_i" = alloca i64
  store i64 %".24", i64* %"pop_i"
  br label %"pop_shift_cond"
pop_shift_cond:
  %".44" = load i64, i64* %"pop_i"
  %".45" = sub i64 %".14", 1
  %".46" = icmp slt i64 %".44", %".45"
  br i1 %".46", label %"pop_shift", label %"pop_done"
pop_shift:
  %".48" = load i64, i64* %"pop_i"
  %".49" = add i64 %".48", 1
  %".50" = getelementptr {i32, i8*}*, {i32, i8*}** %".36", i64 %".49"
  %".51" = load {i32, i8*}*, {i32, i8*}** %".50"
  %".52" = getelementptr {i32, i8*}*, {i32, i8*}** %".36", i64 %".48"
  store {i32, i8*}* %".51", {i32, i8*}** %".52"
  %".54" = add i64 %".48", 1
  store i64 %".54", i64* %"pop_i"
  br label %"pop_shift_cond"
pop_done:
  ret {i32, i8*}* %".38"
}

@"str.IndexError_3a_20pop_20from_20empty_20list" = constant [32 x i8] c"IndexError: pop from empty list\00"
define {i32, i8*}* @"pyobj_copy_dispatch"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 5
  br i1 %".5", label %"dict_case", label %"list_case"
dict_case:
  %".9" = call {i32, i8*}* @"create_dict"()
  call void @"dict_update"({i32, i8*}* %".9", {i32, i8*}* %".1")
  ret {i32, i8*}* %".9"
list_case:
  %".7" = call {i32, i8*}* @"list_copy"({i32, i8*}* %".1")
  ret {i32, i8*}* %".7"
}

define i8* @"rawlist_new"(i64 %".1")
{
entry:
  %".3" = call i8* @"malloc"(i64 24)
  %".4" = bitcast i8* %".3" to {i64, i64, i8*}*
  %".5" = mul i64 %".1", 4
  %".6" = call i8* @"malloc"(i64 %".5")
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  store i64 0, i64* %".7"
  %".9" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 1
  store i64 4, i64* %".9"
  %".11" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  store i8* %".6", i8** %".11"
  %".13" = bitcast {i64, i64, i8*}* %".4" to i8*
  ret i8* %".13"
}

define i64 @"rawlist_push"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 1
  %".8" = load i64, i64* %".7"
  %".9" = icmp eq i64 %".6", %".8"
  br i1 %".9", label %"grow", label %"do_push"
grow:
  %".11" = mul i64 %".8", 2
  %".12" = mul i64 %".11", 8
  %".13" = call i8* @"malloc"(i64 %".12")
  %".14" = icmp sgt i64 %".6", 0
  br i1 %".14", label %"grow_copy", label %"do_push"
grow_copy:
  %".16" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".17" = load i8*, i8** %".16"
  %".18" = mul i64 %".6", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".13", i8* %".17", i64 %".18", i1 0)
  %".20" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 1
  store i64 %".11", i64* %".20"
  %".22" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  store i8* %".13", i8** %".22"
  br label %"do_push"
do_push:
  %".25" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".26" = load i8*, i8** %".25"
  %".27" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".28" = load i64, i64* %".27"
  %".29" = bitcast i8* %".26" to i64*
  %".30" = getelementptr i64, i64* %".29", i64 %".28"
  store i64 %".2", i64* %".30"
  %".32" = add i64 %".28", 1
  %".33" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  store i64 %".32", i64* %".33"
  ret i64 %".32"
}

define i64 @"rawlist_pop"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".4" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = icmp eq i64 %".5", 0
  br i1 %".6", label %"pop_empty", label %"pop_ok"
pop_empty:
  %".8" = getelementptr [32 x i8], [32 x i8]* @"str.IndexError_3a_20pop_20from_20empty_20list", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
pop_ok:
  %".11" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 2
  %".12" = load i8*, i8** %".11"
  %".13" = sub i64 %".5", 1
  %".14" = bitcast i8* %".12" to i64*
  %".15" = getelementptr i64, i64* %".14", i64 %".13"
  %".16" = load i64, i64* %".15"
  %".17" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  store i64 0, i64* %".17"
  ret i64 %".16"
}

define {i32, i8*}* @"rawlist_to_pylist"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".6" = load i8*, i8** %".5"
  %".7" = call {i32, i8*}* @"create_list"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".2"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = bitcast i8* %".6" to i64*
  %".14" = getelementptr i64, i64* %".13", i64 %".10"
  %".15" = load i64, i64* %".14"
  %".16" = call {i32, i8*}* @"create_int"(i64 %".15")
  %".17" = call {i32, i8*}* @"list_append"({i32, i8*}* %".7", {i32, i8*}* %".16")
  %".18" = add i64 %".10", 1
  store i64 %".18", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define {i32, i8*}* @"rawlist_to_pylist_f64"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".6" = load i8*, i8** %".5"
  %".7" = call {i32, i8*}* @"create_list"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".2"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = bitcast i8* %".6" to i64*
  %".14" = getelementptr i64, i64* %".13", i64 %".10"
  %".15" = load i64, i64* %".14"
  %".16" = bitcast i64 %".15" to double
  %".17" = call {i32, i8*}* @"create_float"(double %".16")
  %".18" = call {i32, i8*}* @"list_append"({i32, i8*}* %".7", {i32, i8*}* %".17")
  %".19" = add i64 %".10", 1
  store i64 %".19", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define i8* @"pylist_to_rawlist"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %".10" = call i8* @"rawlist_new"(i64 8)
  %"p2r_i" = alloca i64
  store i64 0, i64* %"p2r_i"
  br label %"p2r_check"
p2r_check:
  %".13" = load i64, i64* %"p2r_i"
  %".14" = icmp slt i64 %".13", %".7"
  br i1 %".14", label %"p2r_body", label %"p2r_done"
p2r_body:
  %".16" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".13"
  %".17" = load {i32, i8*}*, {i32, i8*}** %".16"
  %".18" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 0
  %".19" = load i32, i32* %".18"
  %".20" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 1
  %".21" = load i8*, i8** %".20"
  %".22" = bitcast i8* %".21" to i64*
  %".23" = load i64, i64* %".22"
  %".24" = call i64 @"rawlist_push"(i8* %".10", i64 %".23")
  %".25" = add i64 %".13", 1
  store i64 %".25", i64* %"p2r_i"
  br label %"p2r_check"
p2r_done:
  ret i8* %".10"
}

define i8* @"pylist_to_rawlist_f64"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %".10" = call i8* @"rawlist_new"(i64 8)
  %"p2rf_i" = alloca i64
  store i64 0, i64* %"p2rf_i"
  br label %"p2rf_check"
p2rf_check:
  %".13" = load i64, i64* %"p2rf_i"
  %".14" = icmp slt i64 %".13", %".7"
  br i1 %".14", label %"p2rf_body", label %"p2rf_done"
p2rf_body:
  %".16" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".13"
  %".17" = load {i32, i8*}*, {i32, i8*}** %".16"
  %".18" = getelementptr {i32, i8*}, {i32, i8*}* %".17", i32 0, i32 1
  %".19" = load i8*, i8** %".18"
  %".20" = bitcast i8* %".19" to double*
  %".21" = load double, double* %".20"
  %".22" = bitcast double %".21" to i64
  %".23" = call i64 @"rawlist_push"(i8* %".10", i64 %".22")
  %".24" = add i64 %".13", 1
  store i64 %".24", i64* %"p2rf_i"
  br label %"p2rf_check"
p2rf_done:
  ret i8* %".10"
}

define i64 @"rawlist_len"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".4" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  ret i64 %".5"
}

@"str_keyerr" = constant [24 x i8] c"KeyError: key not found\00"
@"str_idxerr" = constant [38 x i8] c"IndexError: string index out of range\00"
define void @"rawdict_reindex"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %".7" = add i64 %".6", 1
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".9" = load i64*, i64** %".8"
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".11" = load i64*, i64** %".10"
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 2
  %".15" = load i64, i64* %".14"
  %".16" = sub i64 %".2", 1
  %".17" = call i8* @"calloc"(i64 %".2", i64 8)
  %".18" = bitcast i8* %".17" to i64*
  %".19" = mul i64 %".15", 8
  %".20" = call i8* @"malloc"(i64 %".19")
  %".21" = bitcast i8* %".20" to i64*
  %".22" = call i8* @"malloc"(i64 %".19")
  %".23" = bitcast i8* %".22" to i64*
  %".24" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  store i64 %".16", i64* %".24"
  %".26" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  store i64* %".18", i64** %".26"
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  store i64* %".21", i64** %".28"
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  store i64* %".23", i64** %".30"
  %"re_i" = alloca i64
  %"re_live" = alloca i64
  %"re_slot" = alloca i64
  store i64 0, i64* %"re_i"
  store i64 0, i64* %"re_live"
  br label %"scan_cond"
scan_cond:
  %".35" = load i64, i64* %"re_i"
  %".36" = icmp slt i64 %".35", %".7"
  br i1 %".36", label %"scan_body", label %"scan_done"
scan_body:
  %".38" = getelementptr i64, i64* %".9", i64 %".35"
  %".39" = load i64, i64* %".38"
  %".40" = icmp sgt i64 %".39", 0
  br i1 %".40", label %"place_start", label %"scan_step"
place_start:
  %".42" = sub i64 %".39", 1
  %".43" = getelementptr i64, i64* %".11", i64 %".42"
  %".44" = load i64, i64* %".43"
  %".45" = getelementptr i64, i64* %".13", i64 %".42"
  %".46" = load i64, i64* %".45"
  %".47" = load i64, i64* %"re_live"
  %".48" = getelementptr i64, i64* %".21", i64 %".47"
  store i64 %".44", i64* %".48"
  %".50" = getelementptr i64, i64* %".23", i64 %".47"
  store i64 %".46", i64* %".50"
  %".52" = and i64 %".44", %".16"
  store i64 %".52", i64* %"re_slot"
  br label %"place_probe"
place_probe:
  %".55" = load i64, i64* %"re_slot"
  %".56" = getelementptr i64, i64* %".18", i64 %".55"
  %".57" = load i64, i64* %".56"
  %".58" = icmp ne i64 %".57", 0
  br i1 %".58", label %"place_step", label %"place_store"
place_store:
  %".60" = add i64 %".47", 1
  %".61" = getelementptr i64, i64* %".18", i64 %".55"
  store i64 %".60", i64* %".61"
  %".63" = add i64 %".47", 1
  store i64 %".63", i64* %"re_live"
  br label %"scan_step"
place_step:
  %".66" = add i64 %".55", 1
  %".67" = and i64 %".66", %".16"
  store i64 %".67", i64* %"re_slot"
  br label %"place_probe"
scan_step:
  %".70" = add i64 %".35", 1
  store i64 %".70", i64* %"re_i"
  br label %"scan_cond"
scan_done:
  %".73" = load i64, i64* %"re_live"
  %".74" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 1
  store i64 %".73", i64* %".74"
  %".76" = bitcast i64* %".9" to i8*
  call void @"free"(i8* %".76")
  %".78" = bitcast i64* %".11" to i8*
  call void @"free"(i8* %".78")
  %".80" = bitcast i64* %".13" to i8*
  call void @"free"(i8* %".80")
  ret void
}

define i8* @"rawdict_new"()
{
entry:
  %".2" = call i8* @"malloc"(i64 56)
  %".3" = bitcast i8* %".2" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 0
  store i64 0, i64* %".4"
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 1
  store i64 0, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 2
  store i64 8, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  store i64 7, i64* %".10"
  %".12" = call i8* @"calloc"(i64 8, i64 8)
  %".13" = bitcast i8* %".12" to i64*
  %".14" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  store i64* %".13", i64** %".14"
  %".16" = call i8* @"malloc"(i64 64)
  %".17" = bitcast i8* %".16" to i64*
  %".18" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  store i64* %".17", i64** %".18"
  %".20" = call i8* @"malloc"(i64 64)
  %".21" = bitcast i8* %".20" to i64*
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 6
  store i64* %".21", i64** %".22"
  %".24" = bitcast {i64, i64, i64, i64, i64*, i64*, i64*}* %".3" to i8*
  ret i8* %".24"
}

define void @"rawdict_set"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".9" = load i64, i64* %".8"
  %".10" = add i64 %".9", 1
  %".11" = add i64 %".7", 1
  %".12" = mul i64 %".11", 3
  %".13" = mul i64 %".10", 2
  %".14" = icmp sgt i64 %".12", %".13"
  %"rd_slot" = alloca i64
  %"rd_tomb" = alloca i64
  %"rd_size" = alloca i64
  br i1 %".14", label %"rehash", label %"probe_start"
rehash:
  %".16" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  %".17" = load i64, i64* %".16"
  store i64 8, i64* %"rd_size"
  br label %"size_check"
size_check:
  %".20" = load i64, i64* %"rd_size"
  %".21" = add i64 %".17", 1
  %".22" = mul i64 %".21", 3
  %".23" = mul i64 %".20", 2
  %".24" = icmp sgt i64 %".22", %".23"
  br i1 %".24", label %"size_grow", label %"size_done"
size_grow:
  %".26" = mul i64 %".20", 2
  store i64 %".26", i64* %"rd_size"
  br label %"size_check"
size_done:
  %".29" = load i64, i64* %"rd_size"
  call void @"rawdict_reindex"(i8* %".1", i64 %".29")
  br label %"probe_start"
probe_start:
  store i64 -1, i64* %"rd_tomb"
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = and i64 %".2", %".34"
  store i64 %".35", i64* %"rd_slot"
  br label %"probe_test"
probe_test:
  %".38" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".39" = load i64*, i64** %".38"
  %".40" = load i64, i64* %"rd_slot"
  %".41" = getelementptr i64, i64* %".39", i64 %".40"
  %".42" = load i64, i64* %".41"
  %".43" = icmp eq i64 %".42", 0
  br i1 %".43", label %"insert", label %"probe_tomb"
probe_tomb:
  %".45" = icmp eq i64 %".42", -1
  br i1 %".45", label %"tomb_note", label %"probe_match"
tomb_note:
  %".47" = load i64, i64* %"rd_tomb"
  %".48" = icmp eq i64 %".47", -1
  br i1 %".48", label %"tomb_store", label %"probe_step"
tomb_store:
  store i64 %".40", i64* %"rd_tomb"
  br label %"probe_step"
probe_match:
  %".52" = sub i64 %".42", 1
  %".53" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".54" = load i64*, i64** %".53"
  %".55" = getelementptr i64, i64* %".54", i64 %".52"
  %".56" = load i64, i64* %".55"
  %".57" = icmp eq i64 %".56", %".2"
  br i1 %".57", label %"overwrite", label %"probe_step"
overwrite:
  %".59" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".60" = load i64*, i64** %".59"
  %".61" = getelementptr i64, i64* %".60", i64 %".52"
  store i64 %".3", i64* %".61"
  ret void
probe_step:
  %".64" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".65" = load i64, i64* %".64"
  %".66" = add i64 %".40", 1
  %".67" = and i64 %".66", %".65"
  store i64 %".67", i64* %"rd_slot"
  br label %"probe_test"
insert:
  %".70" = load i64, i64* %"rd_tomb"
  %".71" = icmp ne i64 %".70", -1
  %".72" = load i64, i64* %"rd_slot"
  %".73" = select  i1 %".71", i64 %".70", i64 %".72"
  store i64 %".73", i64* %"rd_slot"
  %".75" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  %".76" = load i64, i64* %".75"
  %".77" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 2
  %".78" = load i64, i64* %".77"
  %".79" = icmp eq i64 %".76", %".78"
  br i1 %".79", label %"grow", label %"do_insert"
grow:
  %".81" = mul i64 %".78", 2
  %".82" = mul i64 %".81", 8
  %".83" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".84" = load i64*, i64** %".83"
  %".85" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".86" = load i64*, i64** %".85"
  %".87" = call i8* @"malloc"(i64 %".82")
  %".88" = bitcast i8* %".87" to i64*
  %".89" = call i8* @"malloc"(i64 %".82")
  %".90" = bitcast i8* %".89" to i64*
  %".91" = mul i64 %".76", 8
  %".92" = bitcast i64* %".88" to i8*
  %".93" = bitcast i64* %".84" to i8*
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".92", i8* %".93", i64 %".91", i1 0)
  %".95" = bitcast i64* %".90" to i8*
  %".96" = bitcast i64* %".86" to i8*
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".95", i8* %".96", i64 %".91", i1 0)
  %".98" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 2
  store i64 %".81", i64* %".98"
  %".100" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  store i64* %".88", i64** %".100"
  %".102" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  store i64* %".90", i64** %".102"
  %".104" = bitcast i64* %".84" to i8*
  call void @"free"(i8* %".104")
  %".106" = bitcast i64* %".86" to i8*
  call void @"free"(i8* %".106")
  br label %"do_insert"
do_insert:
  %".109" = load i64, i64* %"rd_slot"
  %".110" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".111" = load i64*, i64** %".110"
  %".112" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".113" = load i64*, i64** %".112"
  %".114" = getelementptr i64, i64* %".111", i64 %".76"
  store i64 %".2", i64* %".114"
  %".116" = getelementptr i64, i64* %".113", i64 %".76"
  store i64 %".3", i64* %".116"
  %".118" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".119" = load i64*, i64** %".118"
  %".120" = add i64 %".76", 1
  %".121" = getelementptr i64, i64* %".119", i64 %".109"
  store i64 %".120", i64* %".121"
  %".123" = add i64 %".76", 1
  %".124" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  store i64 %".123", i64* %".124"
  %".126" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  %".127" = load i64, i64* %".126"
  %".128" = add i64 %".127", 1
  %".129" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  store i64 %".128", i64* %".129"
  ret void
}

define i64 @"rawdict_get"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"rdg_slot" = alloca i64
  %".7" = and i64 %".2", %".6"
  store i64 %".7", i64* %"rdg_slot"
  br label %"probe_test"
probe_test:
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".11" = load i64*, i64** %".10"
  %".12" = load i64, i64* %"rdg_slot"
  %".13" = getelementptr i64, i64* %".11", i64 %".12"
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq i64 %".14", 0
  br i1 %".15", label %"key_error", label %"probe_tomb"
probe_tomb:
  %".17" = icmp eq i64 %".14", -1
  br i1 %".17", label %"probe_step", label %"probe_match"
probe_match:
  %".19" = sub i64 %".14", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr i64, i64* %".21", i64 %".19"
  %".23" = load i64, i64* %".22"
  %".24" = icmp eq i64 %".23", %".2"
  br i1 %".24", label %"found", label %"probe_step"
found:
  %".26" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  %".27" = load i64*, i64** %".26"
  %".28" = getelementptr i64, i64* %".27", i64 %".19"
  %".29" = load i64, i64* %".28"
  ret i64 %".29"
probe_step:
  %".31" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".32" = load i64, i64* %".31"
  %".33" = add i64 %".12", 1
  %".34" = and i64 %".33", %".32"
  store i64 %".34", i64* %"rdg_slot"
  br label %"probe_test"
key_error:
  %".37" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".37")
  unreachable
}

define i64 @"rawdict_del"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"rdd_slot" = alloca i64
  %".7" = and i64 %".2", %".6"
  store i64 %".7", i64* %"rdd_slot"
  br label %"probe_test"
probe_test:
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".11" = load i64*, i64** %".10"
  %".12" = load i64, i64* %"rdd_slot"
  %".13" = getelementptr i64, i64* %".11", i64 %".12"
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq i64 %".14", 0
  br i1 %".15", label %"key_error", label %"probe_tomb"
probe_tomb:
  %".17" = icmp eq i64 %".14", -1
  br i1 %".17", label %"probe_step", label %"probe_match"
probe_match:
  %".19" = sub i64 %".14", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr i64, i64* %".21", i64 %".19"
  %".23" = load i64, i64* %".22"
  %".24" = icmp eq i64 %".23", %".2"
  br i1 %".24", label %"found", label %"probe_step"
found:
  %".26" = getelementptr i64, i64* %".11", i64 %".12"
  store i64 -1, i64* %".26"
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 0
  %".29" = load i64, i64* %".28"
  %".30" = sub i64 %".29", 1
  %".31" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 0
  store i64 %".30", i64* %".31"
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  %".34" = load i64*, i64** %".33"
  %".35" = getelementptr i64, i64* %".34", i64 %".19"
  %".36" = load i64, i64* %".35"
  ret i64 %".36"
probe_step:
  %".38" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".39" = load i64, i64* %".38"
  %".40" = add i64 %".12", 1
  %".41" = and i64 %".40", %".39"
  store i64 %".41", i64* %"rdd_slot"
  br label %"probe_test"
key_error:
  %".44" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".44")
  unreachable
}

define {i32, i8*}* @"rawdict_to_pydict_ii"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  %".5" = load i64, i64* %".4"
  %".6" = add i64 %".5", 1
  %".7" = call {i32, i8*}* @"create_dict"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".6"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  %".14" = load i64*, i64** %".13"
  %".15" = getelementptr i64, i64* %".14", i64 %".10"
  %".16" = load i64, i64* %".15"
  %".17" = icmp sgt i64 %".16", 0
  br i1 %".17", label %"cvt_emit", label %"cvt_step"
cvt_emit:
  %".19" = sub i64 %".16", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 6
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".21", i64 %".19"
  %".25" = load i64, i64* %".24"
  %".26" = call {i32, i8*}* @"create_int"(i64 %".25")
  %".27" = getelementptr i64, i64* %".23", i64 %".19"
  %".28" = load i64, i64* %".27"
  %".29" = call {i32, i8*}* @"create_int"(i64 %".28")
  call void @"dict_set"({i32, i8*}* %".7", {i32, i8*}* %".26", {i32, i8*}* %".29")
  br label %"cvt_step"
cvt_step:
  %".32" = add i64 %".10", 1
  store i64 %".32", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define {i32, i8*}* @"rawdict_to_pydict_if"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  %".5" = load i64, i64* %".4"
  %".6" = add i64 %".5", 1
  %".7" = call {i32, i8*}* @"create_dict"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".6"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  %".14" = load i64*, i64** %".13"
  %".15" = getelementptr i64, i64* %".14", i64 %".10"
  %".16" = load i64, i64* %".15"
  %".17" = icmp sgt i64 %".16", 0
  br i1 %".17", label %"cvt_emit", label %"cvt_step"
cvt_emit:
  %".19" = sub i64 %".16", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 6
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".21", i64 %".19"
  %".25" = load i64, i64* %".24"
  %".26" = call {i32, i8*}* @"create_int"(i64 %".25")
  %".27" = getelementptr i64, i64* %".23", i64 %".19"
  %".28" = load i64, i64* %".27"
  %".29" = bitcast i64 %".28" to double
  %".30" = call {i32, i8*}* @"create_float"(double %".29")
  call void @"dict_set"({i32, i8*}* %".7", {i32, i8*}* %".26", {i32, i8*}* %".30")
  br label %"cvt_step"
cvt_step:
  %".33" = add i64 %".10", 1
  store i64 %".33", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

@"char1_pool" = global [256 x i8*] zeroinitializer
@"str_typeerr" = constant [24 x i8] c"TypeError: expected str\00"
define i64 @"rawutf8_cp_count"(i8* %".1", i64 %".2")
{
entry:
  %"cpc_i" = alloca i64
  %"cpc_n" = alloca i64
  store i64 0, i64* %"cpc_i"
  store i64 0, i64* %"cpc_n"
  br label %"count_cond"
count_cond:
  %".7" = load i64, i64* %"cpc_i"
  %".8" = icmp slt i64 %".7", %".2"
  br i1 %".8", label %"count_body", label %"count_done"
count_body:
  %".10" = getelementptr i8, i8* %".1", i64 %".7"
  %".11" = load i8, i8* %".10"
  %".12" = and i8 %".11", 192
  %".13" = icmp ne i8 %".12", 128
  %".14" = load i64, i64* %"cpc_n"
  %".15" = add i64 %".14", 1
  %".16" = select  i1 %".13", i64 %".15", i64 %".14"
  store i64 %".16", i64* %"cpc_n"
  %".18" = add i64 %".7", 1
  store i64 %".18", i64* %"cpc_i"
  br label %"count_cond"
count_done:
  %".21" = load i64, i64* %"cpc_n"
  ret i64 %".21"
}

define i8* @"rawstr_new_copy"(i8* %".1", i64 %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 %".2")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".4", i8* %".1", i64 %".2", i1 0)
  %".6" = call i64 @"rawutf8_cp_count"(i8* %".1", i64 %".2")
  %".7" = call i8* @"malloc"(i64 32)
  %".8" = bitcast i8* %".7" to {i64, i64, i8*, i64}*
  %".9" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".8", i32 0, i32 0
  store i64 %".2", i64* %".9"
  %".11" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".8", i32 0, i32 1
  store i64 %".2", i64* %".11"
  %".13" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".8", i32 0, i32 2
  store i8* %".4", i8** %".13"
  %".15" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".8", i32 0, i32 3
  store i64 %".6", i64* %".15"
  %".17" = bitcast {i64, i64, i8*, i64}* %".8" to i8*
  ret i8* %".17"
}

define i8* @"rawstr_copy"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 3
  %".9" = load i64, i64* %".8"
  %".10" = call i8* @"malloc"(i64 %".5")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".10", i8* %".7", i64 %".5", i1 0)
  %".12" = call i8* @"malloc"(i64 32)
  %".13" = bitcast i8* %".12" to {i64, i64, i8*, i64}*
  %".14" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".13", i32 0, i32 0
  store i64 %".5", i64* %".14"
  %".16" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".13", i32 0, i32 1
  store i64 %".5", i64* %".16"
  %".18" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".13", i32 0, i32 2
  store i8* %".10", i8** %".18"
  %".20" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".13", i32 0, i32 3
  store i64 %".9", i64* %".20"
  %".22" = bitcast {i64, i64, i8*, i64}* %".13" to i8*
  ret i8* %".22"
}

define i8* @"rawstr_char1"(i8* %".1", i64 %".2")
{
entry:
  %".4" = icmp eq i64 %".2", 1
  br i1 %".4", label %"fill", label %"copy"
fill:
  %".6" = load i8, i8* %".1"
  %".7" = zext i8 %".6" to i64
  %".8" = getelementptr [256 x i8*], [256 x i8*]* @"char1_pool", i64 0, i64 %".7"
  %".9" = load i8*, i8** %".8"
  %".10" = ptrtoint i8* %".9" to i64
  %".11" = icmp ne i64 %".10", 0
  br i1 %".11", label %"probe_hit", label %"hit"
hit:
  %".13" = call i8* @"malloc"(i64 2)
  store i8 %".6", i8* %".13"
  %".15" = getelementptr i8, i8* %".13", i64 1
  store i8 0, i8* %".15"
  %".17" = call i8* @"malloc"(i64 32)
  %".18" = bitcast i8* %".17" to {i64, i64, i8*, i64}*
  %".19" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".18", i32 0, i32 0
  store i64 1, i64* %".19"
  %".21" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".18", i32 0, i32 1
  store i64 -1, i64* %".21"
  %".23" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".18", i32 0, i32 2
  store i8* %".13", i8** %".23"
  %".25" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".18", i32 0, i32 3
  store i64 1, i64* %".25"
  %".27" = bitcast {i64, i64, i8*, i64}* %".18" to i8*
  store i8* %".27", i8** %".8"
  br label %"probe_hit"
copy:
  %".32" = call i8* @"rawstr_new_copy"(i8* %".1", i64 %".2")
  ret i8* %".32"
probe_hit:
  %".30" = phi  i8* [%".9", %"fill"], [%".27", %"hit"]
  ret i8* %".30"
}

define void @"rawstr_free"(i8* %".1")
{
entry:
  %".3" = ptrtoint i8* %".1" to i64
  %".4" = icmp eq i64 %".3", 0
  br i1 %".4", label %"free_done", label %"do_free"
do_free:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".7" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 1
  %".8" = load i64, i64* %".7"
  %".9" = icmp slt i64 %".8", 0
  br i1 %".9", label %"free_done", label %"real_free"
free_done:
  ret void
real_free:
  %".11" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 2
  %".12" = load i8*, i8** %".11"
  call void @"free"(i8* %".12")
  call void @"free"(i8* %".1")
  br label %"free_done"
}

define i8* @"rawstr_concat"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".5" = bitcast i8* %".2" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = add i64 %".7", %".9"
  %".11" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 3
  %".12" = load i64, i64* %".11"
  %".13" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 3
  %".14" = load i64, i64* %".13"
  %".15" = add i64 %".12", %".14"
  %".16" = call i8* @"malloc"(i64 %".10")
  %".17" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 2
  %".18" = load i8*, i8** %".17"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".16", i8* %".18", i64 %".7", i1 0)
  %".20" = getelementptr i8, i8* %".16", i64 %".7"
  %".21" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".22" = load i8*, i8** %".21"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".20", i8* %".22", i64 %".9", i1 0)
  %".24" = call i8* @"malloc"(i64 32)
  %".25" = bitcast i8* %".24" to {i64, i64, i8*, i64}*
  %".26" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".25", i32 0, i32 0
  store i64 %".10", i64* %".26"
  %".28" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".25", i32 0, i32 1
  store i64 %".10", i64* %".28"
  %".30" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".25", i32 0, i32 2
  store i8* %".16", i8** %".30"
  %".32" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".25", i32 0, i32 3
  store i64 %".15", i64* %".32"
  %".34" = bitcast {i64, i64, i8*, i64}* %".25" to i8*
  ret i8* %".34"
}

define void @"rawstr_append"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 1
  %".9" = load i64, i64* %".8"
  %".10" = add i64 %".7", %".3"
  %".11" = icmp sgt i64 %".10", %".9"
  br i1 %".11", label %"grow", label %"do_append"
grow:
  %".13" = mul i64 %".9", 2
  %".14" = icmp sge i64 %".13", %".10"
  %".15" = select  i1 %".14", i64 %".13", i64 %".10"
  %".16" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".17" = load i8*, i8** %".16"
  %".18" = call i8* @"realloc"(i8* %".17", i64 %".15")
  %".19" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 1
  store i64 %".15", i64* %".19"
  %".21" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  store i8* %".18", i8** %".21"
  br label %"do_append"
do_append:
  %".24" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".25" = load i8*, i8** %".24"
  %".26" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".27" = load i64, i64* %".26"
  %".28" = getelementptr i8, i8* %".25", i64 %".27"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".28", i8* %".2", i64 %".3", i1 0)
  %".30" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  store i64 %".10", i64* %".30"
  %".32" = call i64 @"rawutf8_cp_count"(i8* %".2", i64 %".3")
  %".33" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = add i64 %".34", %".32"
  %".36" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 3
  store i64 %".35", i64* %".36"
  ret void
}

define i1 @"rawstr_eq"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".5" = bitcast i8* %".2" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = icmp eq i64 %".7", %".9"
  br i1 %".10", label %"len_ok", label %"eq_out"
len_ok:
  %".12" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 2
  %".13" = load i8*, i8** %".12"
  %".14" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".15" = load i8*, i8** %".14"
  %".16" = call i32 @"memcmp"(i8* %".13", i8* %".15", i64 %".7")
  %".17" = icmp eq i32 %".16", 0
  br label %"eq_out"
eq_out:
  %".19" = phi  i1 [0, %"entry"], [%".17", %"len_ok"]
  ret i1 %".19"
}

define i64 @"rawstr_cmp"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".5" = bitcast i8* %".2" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = icmp slt i64 %".7", %".9"
  %".11" = select  i1 %".10", i64 %".7", i64 %".9"
  %".12" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 2
  %".13" = load i8*, i8** %".12"
  %".14" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".15" = load i8*, i8** %".14"
  %".16" = call i32 @"memcmp"(i8* %".13", i8* %".15", i64 %".11")
  %".17" = sext i32 %".16" to i64
  %".18" = icmp eq i64 %".17", 0
  %".19" = sub i64 %".7", %".9"
  %".20" = select  i1 %".18", i64 %".19", i64 %".17"
  ret i64 %".20"
}

define i1 @"rawstr_eq_cstr"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp eq i64 %".7", %".3"
  br i1 %".8", label %"eq_bytes", label %"eq_out"
eq_bytes:
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %".12" = call i32 @"memcmp"(i8* %".11", i8* %".2", i64 %".3")
  %".13" = icmp eq i32 %".12", 0
  br label %"eq_out"
eq_out:
  %".15" = phi  i1 [0, %"entry"], [%".13", %"eq_bytes"]
  ret i1 %".15"
}

define i64 @"rawstr_cmp_cstr"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp slt i64 %".7", %".3"
  %".9" = select  i1 %".8", i64 %".7", i64 %".3"
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %".12" = call i32 @"memcmp"(i8* %".11", i8* %".2", i64 %".9")
  %".13" = sext i32 %".12" to i64
  %".14" = icmp eq i64 %".13", 0
  %".15" = sub i64 %".7", %".3"
  %".16" = select  i1 %".14", i64 %".15", i64 %".13"
  ret i64 %".16"
}

define i64 @"rawutf8_cp_offset"(i8* %".1", i64 %".2")
{
entry:
  %"cpo_off" = alloca i64
  %"cpo_seen" = alloca i64
  store i64 0, i64* %"cpo_off"
  store i64 0, i64* %"cpo_seen"
  br label %"off_cond"
off_cond:
  %".7" = load i64, i64* %"cpo_seen"
  %".8" = icmp slt i64 %".7", %".2"
  br i1 %".8", label %"off_body", label %"off_done"
off_body:
  %".10" = load i64, i64* %"cpo_off"
  %".11" = getelementptr i8, i8* %".1", i64 %".10"
  %".12" = load i8, i8* %".11"
  %".13" = and i8 %".12", 224
  %".14" = icmp eq i8 %".13", 192
  %".15" = and i8 %".12", 240
  %".16" = icmp eq i8 %".15", 224
  %".17" = and i8 %".12", 248
  %".18" = icmp eq i8 %".17", 240
  %".19" = select  i1 %".18", i64 4, i64 1
  %".20" = select  i1 %".16", i64 3, i64 %".19"
  %".21" = select  i1 %".14", i64 2, i64 %".20"
  %".22" = add i64 %".10", %".21"
  store i64 %".22", i64* %"cpo_off"
  %".24" = add i64 %".7", 1
  store i64 %".24", i64* %"cpo_seen"
  br label %"off_cond"
off_done:
  %".27" = load i64, i64* %"cpo_off"
  ret i64 %".27"
}

define i1 @"rawstr_at_eq_cstr"(i8* %".1", i64 %".2", i8* %".3", i64 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".7" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 3
  %".8" = load i64, i64* %".7"
  %".9" = icmp slt i64 %".2", 0
  %".10" = add i64 %".2", %".8"
  %".11" = select  i1 %".9", i64 %".10", i64 %".2"
  %".12" = icmp sge i64 %".11", 0
  %".13" = icmp slt i64 %".11", %".8"
  %".14" = and i1 %".12", %".13"
  br i1 %".14", label %"ok", label %"index_error"
ok:
  %".19" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 2
  %".20" = load i8*, i8** %".19"
  %".21" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 0
  %".22" = load i64, i64* %".21"
  %".23" = icmp eq i64 %".22", %".8"
  br i1 %".23", label %"ascii", label %"walk"
index_error:
  %".16" = getelementptr [38 x i8], [38 x i8]* @"str_idxerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".16")
  unreachable
ascii:
  br label %"join"
walk:
  %".26" = call i64 @"rawutf8_cp_offset"(i8* %".20", i64 %".11")
  br label %"join"
join:
  %".28" = phi  i64 [%".11", %"ascii"], [%".26", %"walk"]
  %".29" = getelementptr i8, i8* %".20", i64 %".28"
  %".30" = load i8, i8* %".29"
  %".31" = and i8 %".30", 224
  %".32" = icmp eq i8 %".31", 192
  %".33" = and i8 %".30", 240
  %".34" = icmp eq i8 %".33", 224
  %".35" = and i8 %".30", 248
  %".36" = icmp eq i8 %".35", 240
  %".37" = select  i1 %".36", i64 4, i64 1
  %".38" = select  i1 %".34", i64 3, i64 %".37"
  %".39" = select  i1 %".32", i64 2, i64 %".38"
  %".40" = select  i1 %".23", i64 1, i64 %".39"
  %".41" = icmp eq i64 %".40", %".4"
  br i1 %".41", label %"cmp", label %"neq"
cmp:
  %".43" = getelementptr i8, i8* %".20", i64 %".28"
  %".44" = call i32 @"memcmp"(i8* %".43", i8* %".3", i64 %".4")
  %".45" = icmp eq i32 %".44", 0
  ret i1 %".45"
neq:
  ret i1 0
}

define i64 @"rawstr_at_cmp_cstr"(i8* %".1", i64 %".2", i8* %".3", i64 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".7" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 3
  %".8" = load i64, i64* %".7"
  %".9" = icmp slt i64 %".2", 0
  %".10" = add i64 %".2", %".8"
  %".11" = select  i1 %".9", i64 %".10", i64 %".2"
  %".12" = icmp sge i64 %".11", 0
  %".13" = icmp slt i64 %".11", %".8"
  %".14" = and i1 %".12", %".13"
  br i1 %".14", label %"ok", label %"index_error"
ok:
  %".19" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 2
  %".20" = load i8*, i8** %".19"
  %".21" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".6", i32 0, i32 0
  %".22" = load i64, i64* %".21"
  %".23" = icmp eq i64 %".22", %".8"
  br i1 %".23", label %"ascii", label %"walk"
index_error:
  %".16" = getelementptr [38 x i8], [38 x i8]* @"str_idxerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".16")
  unreachable
ascii:
  br label %"join"
walk:
  %".26" = call i64 @"rawutf8_cp_offset"(i8* %".20", i64 %".11")
  br label %"join"
join:
  %".28" = phi  i64 [%".11", %"ascii"], [%".26", %"walk"]
  %".29" = getelementptr i8, i8* %".20", i64 %".28"
  %".30" = load i8, i8* %".29"
  %".31" = and i8 %".30", 224
  %".32" = icmp eq i8 %".31", 192
  %".33" = and i8 %".30", 240
  %".34" = icmp eq i8 %".33", 224
  %".35" = and i8 %".30", 248
  %".36" = icmp eq i8 %".35", 240
  %".37" = select  i1 %".36", i64 4, i64 1
  %".38" = select  i1 %".34", i64 3, i64 %".37"
  %".39" = select  i1 %".32", i64 2, i64 %".38"
  %".40" = select  i1 %".23", i64 1, i64 %".39"
  %".41" = icmp slt i64 %".40", %".4"
  %".42" = select  i1 %".41", i64 %".40", i64 %".4"
  %".43" = getelementptr i8, i8* %".20", i64 %".28"
  %".44" = call i32 @"memcmp"(i8* %".43", i8* %".3", i64 %".42")
  %".45" = sext i32 %".44" to i64
  %".46" = icmp eq i64 %".45", 0
  %".47" = sub i64 %".40", %".4"
  %".48" = select  i1 %".46", i64 %".47", i64 %".45"
  ret i64 %".48"
}

define i8* @"rawstr_slice"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".9" = load i8*, i8** %".8"
  %".10" = icmp slt i64 %".2", 0
  %".11" = add i64 %".2", %".7"
  %".12" = select  i1 %".10", i64 %".11", i64 %".2"
  %".13" = icmp slt i64 %".12", 0
  %".14" = select  i1 %".13", i64 0, i64 %".12"
  %".15" = icmp sgt i64 %".14", %".7"
  %".16" = select  i1 %".15", i64 %".7", i64 %".14"
  %".17" = icmp slt i64 %".3", 0
  %".18" = add i64 %".3", %".7"
  %".19" = select  i1 %".17", i64 %".18", i64 %".3"
  %".20" = icmp slt i64 %".19", 0
  %".21" = select  i1 %".20", i64 0, i64 %".19"
  %".22" = icmp sgt i64 %".21", %".7"
  %".23" = select  i1 %".22", i64 %".7", i64 %".21"
  %".24" = sub i64 %".23", %".16"
  %".25" = icmp sgt i64 %".24", 0
  %".26" = select  i1 %".25", i64 %".24", i64 0
  %".27" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".28" = load i64, i64* %".27"
  %".29" = icmp eq i64 %".28", %".7"
  br i1 %".29", label %"ascii", label %"walk"
ascii:
  br label %"join"
walk:
  %".32" = call i64 @"rawutf8_cp_offset"(i8* %".9", i64 %".16")
  %".33" = call i64 @"rawutf8_cp_offset"(i8* %".9", i64 %".23")
  br label %"join"
join:
  %".35" = phi  i64 [%".16", %"ascii"], [%".32", %"walk"]
  %".36" = phi  i64 [%".23", %"ascii"], [%".33", %"walk"]
  %".37" = sub i64 %".36", %".35"
  %".38" = icmp sgt i64 %".26", 0
  %".39" = select  i1 %".38", i64 %".37", i64 0
  %".40" = icmp sgt i64 %".39", 0
  %".41" = select  i1 %".40", i64 %".39", i64 1
  %".42" = call i8* @"malloc"(i64 %".41")
  %".43" = getelementptr i8, i8* %".9", i64 %".35"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".42", i8* %".43", i64 %".39", i1 0)
  %".45" = call i8* @"malloc"(i64 32)
  %".46" = bitcast i8* %".45" to {i64, i64, i8*, i64}*
  %".47" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".46", i32 0, i32 0
  store i64 %".39", i64* %".47"
  %".49" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".46", i32 0, i32 1
  store i64 %".39", i64* %".49"
  %".51" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".46", i32 0, i32 2
  store i8* %".42", i8** %".51"
  %".53" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".46", i32 0, i32 3
  store i64 %".26", i64* %".53"
  %".55" = bitcast {i64, i64, i8*, i64}* %".46" to i8*
  ret i8* %".55"
}

define {i8*, i64} @"rawstr_slice_parts"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".9" = load i8*, i8** %".8"
  %".10" = icmp slt i64 %".2", 0
  %".11" = add i64 %".2", %".7"
  %".12" = select  i1 %".10", i64 %".11", i64 %".2"
  %".13" = icmp slt i64 %".12", 0
  %".14" = select  i1 %".13", i64 0, i64 %".12"
  %".15" = icmp sgt i64 %".14", %".7"
  %".16" = select  i1 %".15", i64 %".7", i64 %".14"
  %".17" = icmp slt i64 %".3", 0
  %".18" = add i64 %".3", %".7"
  %".19" = select  i1 %".17", i64 %".18", i64 %".3"
  %".20" = icmp slt i64 %".19", 0
  %".21" = select  i1 %".20", i64 0, i64 %".19"
  %".22" = icmp sgt i64 %".21", %".7"
  %".23" = select  i1 %".22", i64 %".7", i64 %".21"
  %".24" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".25" = load i64, i64* %".24"
  %".26" = icmp eq i64 %".25", %".7"
  br i1 %".26", label %"ascii", label %"walk"
ascii:
  br label %"join"
walk:
  %".29" = call i64 @"rawutf8_cp_offset"(i8* %".9", i64 %".16")
  %".30" = call i64 @"rawutf8_cp_offset"(i8* %".9", i64 %".23")
  br label %"join"
join:
  %".32" = phi  i64 [%".16", %"ascii"], [%".29", %"walk"]
  %".33" = phi  i64 [%".23", %"ascii"], [%".30", %"walk"]
  %".34" = sub i64 %".23", %".16"
  %".35" = icmp sgt i64 %".34", 0
  %".36" = sub i64 %".33", %".32"
  %".37" = select  i1 %".35", i64 %".36", i64 0
  %".38" = getelementptr i8, i8* %".9", i64 %".32"
  %".39" = select  i1 %".35", i8* %".38", i8* %".9"
  %".40" = insertvalue {i8*, i64} undef, i8* %".39", 0
  %".41" = insertvalue {i8*, i64} %".40", i64 %".37", 1
  ret {i8*, i64} %".41"
}

define i1 @"rawstr_contains"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".5" = bitcast i8* %".2" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".4", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %".12" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".13" = load i8*, i8** %".12"
  %"rsc_i" = alloca i64
  store i64 0, i64* %"rsc_i"
  %".15" = icmp eq i64 %".9", 0
  br i1 %".15", label %"contains_hit", label %"len_check"
len_check:
  %".17" = icmp sgt i64 %".9", %".7"
  br i1 %".17", label %"contains_miss", label %"contains_cond"
contains_cond:
  %".19" = load i64, i64* %"rsc_i"
  %".20" = sub i64 %".7", %".9"
  %".21" = icmp sle i64 %".19", %".20"
  br i1 %".21", label %"contains_body", label %"contains_miss"
contains_body:
  %".23" = getelementptr i8, i8* %".11", i64 %".19"
  %".24" = call i32 @"memcmp"(i8* %".23", i8* %".13", i64 %".9")
  %".25" = icmp eq i32 %".24", 0
  br i1 %".25", label %"contains_hit", label %"contains_step"
contains_step:
  %".27" = add i64 %".19", 1
  store i64 %".27", i64* %"rsc_i"
  br label %"contains_cond"
contains_hit:
  ret i1 1
contains_miss:
  ret i1 0
}

define i1 @"rawdict_has"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"rdh_slot" = alloca i64
  %".7" = and i64 %".2", %".6"
  store i64 %".7", i64* %"rdh_slot"
  br label %"probe_test"
probe_test:
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".11" = load i64*, i64** %".10"
  %".12" = load i64, i64* %"rdh_slot"
  %".13" = getelementptr i64, i64* %".11", i64 %".12"
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq i64 %".14", 0
  br i1 %".15", label %"missing", label %"probe_tomb"
probe_tomb:
  %".17" = icmp eq i64 %".14", -1
  br i1 %".17", label %"probe_step", label %"probe_match"
probe_match:
  %".19" = sub i64 %".14", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr i64, i64* %".21", i64 %".19"
  %".23" = load i64, i64* %".22"
  %".24" = icmp eq i64 %".23", %".2"
  br i1 %".24", label %"found", label %"probe_step"
found:
  ret i1 1
probe_step:
  %".27" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".28" = load i64, i64* %".27"
  %".29" = add i64 %".12", 1
  %".30" = and i64 %".29", %".28"
  store i64 %".30", i64* %"rdh_slot"
  br label %"probe_test"
missing:
  ret i1 0
}

define i64 @"rawdict_get_or"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"probe_slot" = alloca i64
  %".8" = and i64 %".2", %".7"
  store i64 %".8", i64* %"probe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"probe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = icmp eq i64 %".24", %".2"
  br i1 %".25", label %"hit", label %"probe_step"
hit:
  %".27" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".27", i32 0, i32 6
  %".29" = load i64*, i64** %".28"
  %".30" = getelementptr i64, i64* %".29", i64 %".20"
  %".31" = load i64, i64* %".30"
  ret i64 %".31"
probe_step:
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = add i64 %".13", 1
  %".36" = and i64 %".35", %".34"
  store i64 %".36", i64* %"probe_slot"
  br label %"probe_test"
miss:
  ret i64 %".3"
}

define i64 @"rawdict_pop_or"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"probe_slot" = alloca i64
  %".8" = and i64 %".2", %".7"
  store i64 %".8", i64* %"probe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"probe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = icmp eq i64 %".24", %".2"
  br i1 %".25", label %"hit", label %"probe_step"
hit:
  %".27" = getelementptr i64, i64* %".12", i64 %".13"
  store i64 -1, i64* %".27"
  %".29" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 0
  %".31" = load i64, i64* %".30"
  %".32" = sub i64 %".31", 1
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 0
  store i64 %".32", i64* %".33"
  %".35" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".36" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".35", i32 0, i32 6
  %".37" = load i64*, i64** %".36"
  %".38" = getelementptr i64, i64* %".37", i64 %".20"
  %".39" = load i64, i64* %".38"
  ret i64 %".39"
probe_step:
  %".41" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".42" = load i64, i64* %".41"
  %".43" = add i64 %".13", 1
  %".44" = and i64 %".43", %".42"
  store i64 %".44", i64* %"probe_slot"
  br label %"probe_test"
miss:
  ret i64 %".3"
}

define i64 @"rawdict_setdefault"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"probe_slot" = alloca i64
  %".8" = and i64 %".2", %".7"
  store i64 %".8", i64* %"probe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"probe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = icmp eq i64 %".24", %".2"
  br i1 %".25", label %"hit", label %"probe_step"
hit:
  %".27" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".27", i32 0, i32 6
  %".29" = load i64*, i64** %".28"
  %".30" = getelementptr i64, i64* %".29", i64 %".20"
  %".31" = load i64, i64* %".30"
  ret i64 %".31"
probe_step:
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = add i64 %".13", 1
  %".36" = and i64 %".35", %".34"
  store i64 %".36", i64* %"probe_slot"
  br label %"probe_test"
miss:
  call void @"rawdict_set"(i8* %".1", i64 %".2", i64 %".3")
  ret i64 %".3"
}

define i8* @"rawdict_int_slotof"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"probe_slot" = alloca i64
  %".7" = and i64 %".2", %".6"
  store i64 %".7", i64* %"probe_slot"
  br label %"probe_test"
probe_test:
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".11" = load i64*, i64** %".10"
  %".12" = load i64, i64* %"probe_slot"
  %".13" = getelementptr i64, i64* %".11", i64 %".12"
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq i64 %".14", 0
  br i1 %".15", label %"miss", label %"probe_tomb"
probe_tomb:
  %".17" = icmp eq i64 %".14", -1
  br i1 %".17", label %"probe_step", label %"probe_match"
probe_match:
  %".19" = sub i64 %".14", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr i64, i64* %".21", i64 %".19"
  %".23" = load i64, i64* %".22"
  %".24" = icmp eq i64 %".23", %".2"
  br i1 %".24", label %"hit", label %"probe_step"
hit:
  %".26" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".27" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".26", i32 0, i32 6
  %".28" = load i64*, i64** %".27"
  %".29" = getelementptr i64, i64* %".28", i64 %".19"
  %".30" = bitcast i64* %".29" to i8*
  ret i8* %".30"
probe_step:
  %".32" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".33" = load i64, i64* %".32"
  %".34" = add i64 %".12", 1
  %".35" = and i64 %".34", %".33"
  store i64 %".35", i64* %"probe_slot"
  br label %"probe_test"
miss:
  %".38" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".38")
  unreachable
}

define i8* @"rawdict_int_entry"(i8* %".1", i64 %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"probe_slot" = alloca i64
  %".8" = and i64 %".2", %".7"
  store i64 %".8", i64* %"probe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"probe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = icmp eq i64 %".24", %".2"
  br i1 %".25", label %"hit", label %"probe_step"
hit:
  %".27" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".27", i32 0, i32 6
  %".29" = load i64*, i64** %".28"
  %".30" = getelementptr i64, i64* %".29", i64 %".20"
  %".31" = bitcast i64* %".30" to i8*
  ret i8* %".31"
probe_step:
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = add i64 %".13", 1
  %".36" = and i64 %".35", %".34"
  store i64 %".36", i64* %"probe_slot"
  br label %"probe_test"
miss:
  call void @"rawdict_set"(i8* %".1", i64 %".2", i64 %".3")
  %".40" = call i8* @"rawdict_int_slotof"(i8* %".1", i64 %".2")
  ret i8* %".40"
}

define void @"rawdict_clear"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 0
  store i64 0, i64* %".4"
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 1
  store i64 0, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  %".11" = load i64*, i64** %".10"
  %".12" = bitcast i64* %".11" to i8*
  %".13" = add i64 %".9", 1
  %".14" = mul i64 %".13", 8
  call void @"llvm.memset.p0i8.i64"(i8* %".12", i8 0, i64 %".14", i1 0)
  ret void
}

define void @"rawlist_clear"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".4" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  store i64 0, i64* %".4"
  ret void
}

define i64 @"rawlist_str_push"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 1
  %".8" = load i64, i64* %".7"
  %".9" = icmp eq i64 %".6", %".8"
  br i1 %".9", label %"grow", label %"do_push"
grow:
  %".11" = mul i64 %".8", 2
  %".12" = mul i64 %".11", 8
  %".13" = call i8* @"malloc"(i64 %".12")
  %".14" = icmp sgt i64 %".6", 0
  br i1 %".14", label %"grow_copy", label %"do_push"
grow_copy:
  %".16" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".17" = load i8*, i8** %".16"
  %".18" = mul i64 %".6", 8
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".13", i8* %".17", i64 %".18", i1 0)
  %".20" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 1
  store i64 %".11", i64* %".20"
  %".22" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  store i8* %".13", i8** %".22"
  br label %"do_push"
do_push:
  %".25" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".26" = load i8*, i8** %".25"
  %".27" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".28" = load i64, i64* %".27"
  %".29" = bitcast i8* %".26" to i64*
  %".30" = call i8* @"rawstr_copy"(i8* %".2")
  %".31" = ptrtoint i8* %".30" to i64
  %".32" = getelementptr i64, i64* %".29", i64 %".28"
  store i64 %".31", i64* %".32"
  %".34" = add i64 %".28", 1
  %".35" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  store i64 %".34", i64* %".35"
  ret i64 %".34"
}

define i8* @"rawlist_str_join"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = bitcast i8* %".2" to {i64, i64, i8*, i64}*
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".7", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".7", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %"join_total" = alloca i64
  store i64 0, i64* %"join_total"
  %"join_si" = alloca i64
  store i64 0, i64* %"join_si"
  %"join_out" = alloca i8*
  br label %"join_size_cond"
join_size_cond:
  %".15" = load i64, i64* %"join_si"
  %".16" = icmp slt i64 %".15", %".6"
  br i1 %".16", label %"join_size", label %"join_alloc"
join_size:
  %".18" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".19" = load i8*, i8** %".18"
  %".20" = bitcast i8* %".19" to i64*
  %".21" = getelementptr i64, i64* %".20", i64 %".15"
  %".22" = load i64, i64* %".21"
  %".23" = inttoptr i64 %".22" to i8*
  %".24" = bitcast i8* %".23" to {i64, i64, i8*, i64}*
  %".25" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".24", i32 0, i32 0
  %".26" = load i64, i64* %".25"
  %".27" = load i64, i64* %"join_total"
  %".28" = add i64 %".27", %".26"
  %".29" = add i64 %".15", 1
  %".30" = icmp slt i64 %".29", %".6"
  %".31" = add i64 %".28", %".9"
  %".32" = select  i1 %".30", i64 %".31", i64 %".28"
  store i64 %".32", i64* %"join_total"
  %".34" = add i64 %".15", 1
  store i64 %".34", i64* %"join_si"
  br label %"join_size_cond"
join_alloc:
  %".37" = load i64, i64* %"join_total"
  %".38" = call i8* @"malloc"(i64 %".37")
  store i8* %".38", i8** %"join_out"
  store i64 0, i64* %"join_si"
  br label %"join_copy_cond"
join_copy_cond:
  %".42" = load i64, i64* %"join_si"
  %".43" = icmp slt i64 %".42", %".6"
  br i1 %".43", label %"join_body", label %"join_done"
join_body:
  %".45" = icmp sgt i64 %".42", 0
  %".46" = load i8*, i8** %"join_out"
  %".47" = getelementptr i8, i8* %".46", i64 %".9"
  %".48" = select  i1 %".45", i8* %".47", i8* %".46"
  br i1 %".45", label %"join_sepblk", label %"join_itemblk"
join_done:
  %".70" = call i64 @"rawutf8_cp_count"(i8* %".38", i64 %".37")
  %".71" = call i8* @"malloc"(i64 32)
  %".72" = bitcast i8* %".71" to {i64, i64, i8*, i64}*
  %".73" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".72", i32 0, i32 0
  store i64 %".37", i64* %".73"
  %".75" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".72", i32 0, i32 1
  store i64 %".37", i64* %".75"
  %".77" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".72", i32 0, i32 2
  store i8* %".38", i8** %".77"
  %".79" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".72", i32 0, i32 3
  store i64 %".70", i64* %".79"
  %".81" = bitcast {i64, i64, i8*, i64}* %".72" to i8*
  ret i8* %".81"
join_sepblk:
  %".50" = load i8*, i8** %"join_out"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".50", i8* %".11", i64 %".9", i1 0)
  br label %"join_itemblk"
join_itemblk:
  %".53" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".54" = load i8*, i8** %".53"
  %".55" = bitcast i8* %".54" to i64*
  %".56" = getelementptr i64, i64* %".55", i64 %".42"
  %".57" = load i64, i64* %".56"
  %".58" = inttoptr i64 %".57" to i8*
  %".59" = bitcast i8* %".58" to {i64, i64, i8*, i64}*
  %".60" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".59", i32 0, i32 2
  %".61" = load i8*, i8** %".60"
  %".62" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".59", i32 0, i32 0
  %".63" = load i64, i64* %".62"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".48", i8* %".61", i64 %".63", i1 0)
  %".65" = getelementptr i8, i8* %".48", i64 %".63"
  store i8* %".65", i8** %"join_out"
  %".67" = add i64 %".42", 1
  store i64 %".67", i64* %"join_si"
  br label %"join_copy_cond"
}

define i8* @"rawlist_str_pop"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".4" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = icmp eq i64 %".5", 0
  br i1 %".6", label %"pop_empty", label %"pop_ok"
pop_empty:
  %".8" = getelementptr [32 x i8], [32 x i8]* @"str.IndexError_3a_20pop_20from_20empty_20list", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
pop_ok:
  %".11" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 2
  %".12" = load i8*, i8** %".11"
  %".13" = sub i64 %".5", 1
  %".14" = bitcast i8* %".12" to i64*
  %".15" = getelementptr i64, i64* %".14", i64 %".13"
  %".16" = load i64, i64* %".15"
  %".17" = inttoptr i64 %".16" to i8*
  %".18" = call i8* @"rawstr_copy"(i8* %".17")
  %".19" = inttoptr i64 %".16" to i8*
  call void @"rawstr_free"(i8* %".19")
  store i64 0, i64* %".15"
  %".22" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  store i64 %".13", i64* %".22"
  ret i8* %".18"
}

define i64 @"rawstr_ord"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 3
  %".5" = load i64, i64* %".4"
  %".6" = icmp eq i64 %".5", 1
  br i1 %".6", label %"ord_ok", label %"ord_panic"
ord_panic:
  %".8" = getelementptr [38 x i8], [38 x i8]* @"str.TypeError_3a_20ord_28_29_20expected_20a_20character", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
ord_ok:
  %".11" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".12" = load i8*, i8** %".11"
  %".13" = getelementptr i8, i8* %".12", i64 0
  %".14" = load i8, i8* %".13"
  %".15" = zext i8 %".14" to i64
  %".16" = icmp slt i64 %".15", 128
  br i1 %".16", label %"ord_ascii", label %"ord_multi"
ord_ascii:
  ret i64 %".15"
ord_multi:
  %".19" = and i8 %".14", 224
  %".20" = icmp eq i8 %".19", 192
  %".21" = and i8 %".14", 240
  %".22" = icmp eq i8 %".21", 224
  %".23" = and i8 %".14", 248
  %".24" = icmp eq i8 %".23", 240
  %".25" = select  i1 %".24", i64 4, i64 1
  %".26" = select  i1 %".22", i64 3, i64 %".25"
  %".27" = select  i1 %".20", i64 2, i64 %".26"
  %".28" = icmp eq i64 %".27", 2
  br i1 %".28", label %"ord_two", label %"ord_more"
ord_two:
  %".30" = and i64 %".15", 31
  %".31" = shl i64 %".30", 6
  %".32" = getelementptr i8, i8* %".12", i64 1
  %".33" = load i8, i8* %".32"
  %".34" = zext i8 %".33" to i64
  %".35" = and i64 %".34", 63
  %".36" = or i64 %".31", %".35"
  br label %"ord_join"
ord_more:
  %".38" = icmp eq i64 %".27", 3
  br i1 %".38", label %"ord_three", label %"ord_four"
ord_three:
  %".40" = and i64 %".15", 15
  %".41" = shl i64 %".40", 12
  %".42" = getelementptr i8, i8* %".12", i64 1
  %".43" = load i8, i8* %".42"
  %".44" = zext i8 %".43" to i64
  %".45" = and i64 %".44", 63
  %".46" = shl i64 %".45", 6
  %".47" = or i64 %".41", %".46"
  %".48" = getelementptr i8, i8* %".12", i64 2
  %".49" = load i8, i8* %".48"
  %".50" = zext i8 %".49" to i64
  %".51" = and i64 %".50", 63
  %".52" = or i64 %".47", %".51"
  br label %"ord_join"
ord_four:
  %".54" = and i64 %".15", 7
  %".55" = shl i64 %".54", 18
  %".56" = getelementptr i8, i8* %".12", i64 1
  %".57" = load i8, i8* %".56"
  %".58" = zext i8 %".57" to i64
  %".59" = and i64 %".58", 63
  %".60" = shl i64 %".59", 12
  %".61" = or i64 %".55", %".60"
  %".62" = getelementptr i8, i8* %".12", i64 2
  %".63" = load i8, i8* %".62"
  %".64" = zext i8 %".63" to i64
  %".65" = and i64 %".64", 63
  %".66" = shl i64 %".65", 6
  %".67" = getelementptr i8, i8* %".12", i64 3
  %".68" = load i8, i8* %".67"
  %".69" = zext i8 %".68" to i64
  %".70" = and i64 %".69", 63
  %".71" = or i64 %".66", %".70"
  %".72" = or i64 %".61", %".71"
  br label %"ord_join"
ord_join:
  %".74" = phi  i64 [%".36", %"ord_two"], [%".52", %"ord_three"], [%".72", %"ord_four"]
  ret i64 %".74"
}

@"str.TypeError_3a_20ord_28_29_20expected_20a_20character" = constant [38 x i8] c"TypeError: ord() expected a character\00"
define i64 @"view_ord"(i8* %".1", i64 %".2")
{
entry:
  %".4" = icmp eq i64 %".2", 1
  br i1 %".4", label %"v_one", label %"v_two"
v_one:
  %".6" = getelementptr i8, i8* %".1", i64 0
  %".7" = load i8, i8* %".6"
  %".8" = zext i8 %".7" to i64
  ret i64 %".8"
v_two:
  %".10" = getelementptr i8, i8* %".1", i64 0
  %".11" = load i8, i8* %".10"
  %".12" = zext i8 %".11" to i64
  %".13" = getelementptr i8, i8* %".1", i64 1
  %".14" = load i8, i8* %".13"
  %".15" = zext i8 %".14" to i64
  %".16" = and i64 %".15", 63
  %".17" = and i64 %".12", 31
  %".18" = shl i64 %".17", 6
  %".19" = or i64 %".18", %".16"
  %".20" = icmp eq i64 %".2", 2
  br i1 %".20", label %"v_join", label %"v_more"
v_more:
  %".22" = getelementptr i8, i8* %".1", i64 2
  %".23" = load i8, i8* %".22"
  %".24" = zext i8 %".23" to i64
  %".25" = and i64 %".24", 63
  %".26" = and i64 %".12", 15
  %".27" = shl i64 %".26", 12
  %".28" = shl i64 %".16", 6
  %".29" = or i64 %".27", %".28"
  %".30" = or i64 %".29", %".25"
  %".31" = icmp eq i64 %".2", 3
  br i1 %".31", label %"v_three", label %"v_four"
v_three:
  br label %"v_join"
v_four:
  %".34" = and i64 %".12", 7
  %".35" = shl i64 %".34", 18
  %".36" = shl i64 %".16", 12
  %".37" = or i64 %".35", %".36"
  %".38" = shl i64 %".25", 6
  %".39" = getelementptr i8, i8* %".1", i64 3
  %".40" = load i8, i8* %".39"
  %".41" = zext i8 %".40" to i64
  %".42" = and i64 %".41", 63
  %".43" = or i64 %".38", %".42"
  %".44" = or i64 %".37", %".43"
  br label %"v_join"
v_join:
  %".46" = phi  i64 [%".19", %"v_two"], [%".30", %"v_three"], [%".44", %"v_four"]
  ret i64 %".46"
}

define i8* @"rawstr_chr"(i64 %".1")
{
entry:
  %".3" = icmp sge i64 %".1", 0
  %".4" = icmp sle i64 %".1", 1114111
  %".5" = and i1 %".3", %".4"
  br i1 %".5", label %"chr_ok", label %"chr_panic"
chr_panic:
  %".7" = getelementptr [35 x i8], [35 x i8]* @"str.ValueError_3a_20chr_28_29_20arg_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".7")
  unreachable
chr_ok:
  %"chr_buf" = alloca i8, i32 4
  %".10" = icmp slt i64 %".1", 128
  br i1 %".10", label %"chr_one", label %"chr_more1"
chr_one:
  %".12" = trunc i64 %".1" to i8
  %".13" = getelementptr i8, i8* %"chr_buf", i32 0
  store i8 %".12", i8* %".13"
  br label %"chr_make"
chr_more1:
  %".16" = icmp slt i64 %".1", 2048
  br i1 %".16", label %"chr_two", label %"chr_more2"
chr_two:
  %".18" = lshr i64 %".1", 6
  %".19" = or i64 192, %".18"
  %".20" = trunc i64 %".19" to i8
  %".21" = getelementptr i8, i8* %"chr_buf", i32 0
  store i8 %".20", i8* %".21"
  %".23" = and i64 %".1", 63
  %".24" = or i64 128, %".23"
  %".25" = trunc i64 %".24" to i8
  %".26" = getelementptr i8, i8* %"chr_buf", i32 1
  store i8 %".25", i8* %".26"
  br label %"chr_make"
chr_more2:
  %".29" = icmp slt i64 %".1", 65536
  br i1 %".29", label %"chr_three", label %"chr_four"
chr_three:
  %".31" = lshr i64 %".1", 12
  %".32" = or i64 224, %".31"
  %".33" = trunc i64 %".32" to i8
  %".34" = getelementptr i8, i8* %"chr_buf", i32 0
  store i8 %".33", i8* %".34"
  %".36" = lshr i64 %".1", 6
  %".37" = and i64 %".36", 63
  %".38" = or i64 128, %".37"
  %".39" = trunc i64 %".38" to i8
  %".40" = getelementptr i8, i8* %"chr_buf", i32 1
  store i8 %".39", i8* %".40"
  %".42" = and i64 %".1", 63
  %".43" = or i64 128, %".42"
  %".44" = trunc i64 %".43" to i8
  %".45" = getelementptr i8, i8* %"chr_buf", i32 2
  store i8 %".44", i8* %".45"
  br label %"chr_make"
chr_four:
  %".48" = lshr i64 %".1", 18
  %".49" = or i64 240, %".48"
  %".50" = trunc i64 %".49" to i8
  %".51" = getelementptr i8, i8* %"chr_buf", i32 0
  store i8 %".50", i8* %".51"
  %".53" = lshr i64 %".1", 12
  %".54" = and i64 %".53", 63
  %".55" = or i64 128, %".54"
  %".56" = trunc i64 %".55" to i8
  %".57" = getelementptr i8, i8* %"chr_buf", i32 1
  store i8 %".56", i8* %".57"
  %".59" = lshr i64 %".1", 6
  %".60" = and i64 %".59", 63
  %".61" = or i64 128, %".60"
  %".62" = trunc i64 %".61" to i8
  %".63" = getelementptr i8, i8* %"chr_buf", i32 2
  store i8 %".62", i8* %".63"
  %".65" = and i64 %".1", 63
  %".66" = or i64 128, %".65"
  %".67" = trunc i64 %".66" to i8
  %".68" = getelementptr i8, i8* %"chr_buf", i32 3
  store i8 %".67", i8* %".68"
  br label %"chr_make"
chr_make:
  %".71" = phi  i64 [1, %"chr_one"], [2, %"chr_two"], [3, %"chr_three"], [4, %"chr_four"]
  %".72" = call i8* @"rawstr_new_copy"(i8* %"chr_buf", i64 %".71")
  ret i8* %".72"
}

@"str.ValueError_3a_20chr_28_29_20arg_20out_20of_20range" = constant [35 x i8] c"ValueError: chr() arg out of range\00"
define i8* @"rawstr_strip"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".5" = load i8*, i8** %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %"strip_lo" = alloca i64
  %"strip_hi" = alloca i64
  store i64 0, i64* %"strip_lo"
  store i64 %".7", i64* %"strip_hi"
  br label %"strip_lo_cond"
strip_lo_cond:
  %".11" = load i64, i64* %"strip_lo"
  %".12" = load i64, i64* %"strip_hi"
  %".13" = icmp slt i64 %".11", %".12"
  %".14" = getelementptr i8, i8* %".5", i64 %".11"
  %".15" = load i8, i8* %".14"
  %".16" = icmp eq i8 %".15", 32
  %".17" = icmp sge i8 %".15", 9
  %".18" = icmp sle i8 %".15", 13
  %".19" = and i1 %".17", %".18"
  %".20" = or i1 %".16", %".19"
  %".21" = and i1 %".13", %".20"
  br i1 %".21", label %"strip_lo_body", label %"strip_hi_cond"
strip_lo_body:
  %".23" = add i64 %".11", 1
  store i64 %".23", i64* %"strip_lo"
  br label %"strip_lo_cond"
strip_hi_cond:
  %".26" = load i64, i64* %"strip_hi"
  %".27" = load i64, i64* %"strip_lo"
  %".28" = icmp sgt i64 %".26", %".27"
  %".29" = sub i64 %".26", 1
  %".30" = getelementptr i8, i8* %".5", i64 %".29"
  %".31" = load i8, i8* %".30"
  %".32" = icmp eq i8 %".31", 32
  %".33" = icmp sge i8 %".31", 9
  %".34" = icmp sle i8 %".31", 13
  %".35" = and i1 %".33", %".34"
  %".36" = or i1 %".32", %".35"
  %".37" = and i1 %".28", %".36"
  br i1 %".37", label %"strip_hi_body", label %"strip_done"
strip_hi_body:
  %".39" = sub i64 %".26", 1
  store i64 %".39", i64* %"strip_hi"
  br label %"strip_hi_cond"
strip_done:
  %".42" = load i64, i64* %"strip_lo"
  %".43" = load i64, i64* %"strip_hi"
  %".44" = getelementptr i8, i8* %".5", i64 %".42"
  %".45" = sub i64 %".43", %".42"
  %".46" = call i8* @"rawstr_new_copy"(i8* %".44", i64 %".45")
  ret i8* %".46"
}

define i1 @"rawstr_starts_with"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp sle i64 %".3", %".7"
  br i1 %".8", label %"affix_cmp", label %"affix_false"
affix_cmp:
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %".12" = call i32 @"memcmp"(i8* %".11", i8* %".2", i64 %".3")
  %".13" = icmp eq i32 %".12", 0
  br label %"affix_join"
affix_false:
  br label %"affix_join"
affix_join:
  %".16" = phi  i1 [%".13", %"affix_cmp"], [0, %"affix_false"]
  ret i1 %".16"
}

define i1 @"rawstr_ends_with"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp sle i64 %".3", %".7"
  br i1 %".8", label %"affix_cmp", label %"affix_false"
affix_cmp:
  %".10" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".11" = load i8*, i8** %".10"
  %".12" = sub i64 %".7", %".3"
  %".13" = getelementptr i8, i8* %".11", i64 %".12"
  %".14" = call i32 @"memcmp"(i8* %".13", i8* %".2", i64 %".3")
  %".15" = icmp eq i32 %".14", 0
  br label %"affix_join"
affix_false:
  br label %"affix_join"
affix_join:
  %".18" = phi  i1 [%".15", %"affix_cmp"], [0, %"affix_false"]
  ret i1 %".18"
}

define i1 @"str_starts_with"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i32, i8*}*
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 0
  %".15" = load i32, i32* %".14"
  %".16" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 1
  %".17" = load i8*, i8** %".16"
  %".18" = sext i32 %".8" to i64
  %".19" = sext i32 %".15" to i64
  %"boxed_affix_s" = alloca {i64, i64, i8*, i64}
  %".20" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 0
  store i64 %".18", i64* %".20"
  %".22" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 1
  store i64 %".18", i64* %".22"
  %".24" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 2
  store i8* %".10", i8** %".24"
  %".26" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 3
  store i64 %".18", i64* %".26"
  %".28" = bitcast {i64, i64, i8*, i64}* %"boxed_affix_s" to i8*
  %".29" = call i1 @"rawstr_starts_with"(i8* %".28", i8* %".17", i64 %".19")
  ret i1 %".29"
}

define i1 @"str_ends_with"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".12" = load i8*, i8** %".11"
  %".13" = bitcast i8* %".12" to {i32, i8*}*
  %".14" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 0
  %".15" = load i32, i32* %".14"
  %".16" = getelementptr {i32, i8*}, {i32, i8*}* %".13", i32 0, i32 1
  %".17" = load i8*, i8** %".16"
  %".18" = sext i32 %".8" to i64
  %".19" = sext i32 %".15" to i64
  %"boxed_affix_s" = alloca {i64, i64, i8*, i64}
  %".20" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 0
  store i64 %".18", i64* %".20"
  %".22" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 1
  store i64 %".18", i64* %".22"
  %".24" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 2
  store i8* %".10", i8** %".24"
  %".26" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %"boxed_affix_s", i32 0, i32 3
  store i64 %".18", i64* %".26"
  %".28" = bitcast {i64, i64, i8*, i64}* %"boxed_affix_s" to i8*
  %".29" = call i1 @"rawstr_ends_with"(i8* %".28", i8* %".17", i64 %".19")
  ret i1 %".29"
}

define i1 @"rawstr_isdigit"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %"cls_i" = alloca i64
  store i64 0, i64* %"cls_i"
  %".9" = icmp eq i64 %".5", 0
  br i1 %".9", label %"cls_fail", label %"cls_cond"
cls_cond:
  %".11" = load i64, i64* %"cls_i"
  %".12" = icmp slt i64 %".11", %".5"
  br i1 %".12", label %"cls_body", label %"cls_done"
cls_body:
  %".14" = getelementptr i8, i8* %".7", i64 %".11"
  %".15" = load i8, i8* %".14"
  %".16" = icmp sge i8 %".15", 48
  %".17" = icmp sle i8 %".15", 57
  %".18" = and i1 %".16", %".17"
  br i1 %".18", label %"cls_ok", label %"cls_fail"
cls_fail:
  ret i1 0
cls_done:
  ret i1 1
cls_ok:
  %".20" = add i64 %".11", 1
  store i64 %".20", i64* %"cls_i"
  br label %"cls_cond"
}

define i1 @"rawstr_isalpha"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %"cls_i" = alloca i64
  store i64 0, i64* %"cls_i"
  %".9" = icmp eq i64 %".5", 0
  br i1 %".9", label %"cls_fail", label %"cls_cond"
cls_cond:
  %".11" = load i64, i64* %"cls_i"
  %".12" = icmp slt i64 %".11", %".5"
  br i1 %".12", label %"cls_body", label %"cls_done"
cls_body:
  %".14" = getelementptr i8, i8* %".7", i64 %".11"
  %".15" = load i8, i8* %".14"
  %".16" = or i8 %".15", 32
  %".17" = icmp sge i8 %".16", 97
  %".18" = icmp sle i8 %".16", 122
  %".19" = and i1 %".17", %".18"
  %".20" = and i8 %".15", 128
  %".21" = icmp ne i8 %".20", 0
  %".22" = or i1 %".19", %".21"
  br i1 %".22", label %"cls_ok", label %"cls_fail"
cls_fail:
  ret i1 0
cls_done:
  ret i1 1
cls_ok:
  %".24" = add i64 %".11", 1
  store i64 %".24", i64* %"cls_i"
  br label %"cls_cond"
}

define i1 @"rawstr_isspace"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %"cls_i" = alloca i64
  store i64 0, i64* %"cls_i"
  %".9" = icmp eq i64 %".5", 0
  br i1 %".9", label %"cls_fail", label %"cls_cond"
cls_cond:
  %".11" = load i64, i64* %"cls_i"
  %".12" = icmp slt i64 %".11", %".5"
  br i1 %".12", label %"cls_body", label %"cls_done"
cls_body:
  %".14" = getelementptr i8, i8* %".7", i64 %".11"
  %".15" = load i8, i8* %".14"
  %".16" = icmp eq i8 %".15", 32
  %".17" = icmp sge i8 %".15", 9
  %".18" = icmp sle i8 %".15", 13
  %".19" = and i1 %".17", %".18"
  %".20" = or i1 %".16", %".19"
  br i1 %".20", label %"cls_ok", label %"cls_fail"
cls_fail:
  ret i1 0
cls_done:
  ret i1 1
cls_ok:
  %".22" = add i64 %".11", 1
  store i64 %".22", i64* %"cls_i"
  br label %"cls_cond"
}

define i8* @"rawstr_split_ws"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".5" = load i8*, i8** %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = call i8* @"rawlist_new"(i64 8)
  %"sw_i" = alloca i64
  %"sw_start" = alloca i64
  store i64 0, i64* %"sw_i"
  store i64 0, i64* %"sw_start"
  br label %"sw_cond"
sw_cond:
  %".12" = load i64, i64* %"sw_i"
  %".13" = icmp slt i64 %".12", %".7"
  br i1 %".13", label %"sw_body", label %"sw_tail"
sw_body:
  %".15" = load i64, i64* %"sw_i"
  %".16" = getelementptr i8, i8* %".5", i64 %".15"
  %".17" = load i8, i8* %".16"
  %".18" = icmp eq i8 %".17", 32
  %".19" = icmp sge i8 %".17", 9
  %".20" = icmp sle i8 %".17", 13
  %".21" = and i1 %".19", %".20"
  %".22" = or i1 %".18", %".21"
  br i1 %".22", label %"sw_ws", label %"sw_adv"
sw_ws:
  %".24" = load i64, i64* %"sw_start"
  %".25" = icmp slt i64 %".24", %".15"
  br i1 %".25", label %"sw_push", label %"sw_skip"
sw_push:
  %".27" = load i64, i64* %"sw_start"
  %".28" = getelementptr i8, i8* %".5", i64 %".27"
  %".29" = load i64, i64* %"sw_start"
  %".30" = sub i64 %".15", %".29"
  %".31" = call i8* @"rawstr_new_copy"(i8* %".28", i64 %".30")
  %".32" = call i64 @"rawlist_str_push"(i8* %".8", i8* %".31")
  call void @"rawstr_free"(i8* %".31")
  br label %"sw_skip"
sw_skip:
  %".35" = add i64 %".15", 1
  store i64 %".35", i64* %"sw_i"
  %".37" = add i64 %".15", 1
  store i64 %".37", i64* %"sw_start"
  br label %"sw_cond"
sw_adv:
  %".40" = add i64 %".15", 1
  store i64 %".40", i64* %"sw_i"
  br label %"sw_cond"
sw_tail:
  %".43" = load i64, i64* %"sw_start"
  %".44" = icmp slt i64 %".43", %".7"
  br i1 %".44", label %"sw_tail_push", label %"sw_done"
sw_tail_push:
  %".46" = getelementptr i8, i8* %".5", i64 %".43"
  %".47" = sub i64 %".7", %".43"
  %".48" = call i8* @"rawstr_new_copy"(i8* %".46", i64 %".47")
  %".49" = call i64 @"rawlist_str_push"(i8* %".8", i8* %".48")
  call void @"rawstr_free"(i8* %".48")
  br label %"sw_done"
sw_done:
  ret i8* %".8"
}

define i8* @"rawstr_split_sep"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %".8" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".5", i32 0, i32 0
  %".9" = load i64, i64* %".8"
  %".10" = icmp eq i64 %".3", 0
  br i1 %".10", label %"ss_panic", label %"ss_cond"
ss_panic:
  %".12" = getelementptr [28 x i8], [28 x i8]* @"str.ValueError_3a_20empty_20separator", i32 0, i32 0
  call void @"silu_panic"(i8* %".12")
  unreachable
ss_cond:
  %".15" = call i8* @"rawlist_new"(i64 8)
  %"ss_i" = alloca i64
  %"ss_start" = alloca i64
  %"ss_j" = alloca i64
  store i64 0, i64* %"ss_i"
  store i64 0, i64* %"ss_start"
  br label %"ss_try"
ss_try:
  %".19" = load i64, i64* %"ss_i"
  %".20" = add i64 %".19", %".3"
  %".21" = icmp sle i64 %".20", %".9"
  br i1 %".21", label %"ss_mcond", label %"ss_tail"
ss_mcond:
  store i64 0, i64* %"ss_j"
  br label %"ss_mbody"
ss_mbody:
  %".25" = load i64, i64* %"ss_j"
  %".26" = icmp slt i64 %".25", %".3"
  br i1 %".26", label %"ss_mcmp", label %"ss_match"
ss_mcmp:
  %".28" = load i64, i64* %"ss_i"
  %".29" = add i64 %".28", %".25"
  %".30" = getelementptr i8, i8* %".7", i64 %".29"
  %".31" = load i8, i8* %".30"
  %".32" = getelementptr i8, i8* %".2", i64 %".25"
  %".33" = load i8, i8* %".32"
  %".34" = icmp eq i8 %".31", %".33"
  br i1 %".34", label %"ss_mnext", label %"ss_adv"
ss_mnext:
  %".36" = add i64 %".25", 1
  store i64 %".36", i64* %"ss_j"
  br label %"ss_mbody"
ss_match:
  %".39" = load i64, i64* %"ss_i"
  %".40" = load i64, i64* %"ss_start"
  %".41" = getelementptr i8, i8* %".7", i64 %".40"
  %".42" = load i64, i64* %"ss_start"
  %".43" = sub i64 %".39", %".42"
  %".44" = call i8* @"rawstr_new_copy"(i8* %".41", i64 %".43")
  %".45" = call i64 @"rawlist_str_push"(i8* %".15", i8* %".44")
  call void @"rawstr_free"(i8* %".44")
  %".47" = add i64 %".39", %".3"
  store i64 %".47", i64* %"ss_i"
  store i64 %".47", i64* %"ss_start"
  br label %"ss_try"
ss_adv:
  %".51" = load i64, i64* %"ss_i"
  %".52" = add i64 %".51", 1
  store i64 %".52", i64* %"ss_i"
  br label %"ss_try"
ss_tail:
  %".55" = load i64, i64* %"ss_start"
  %".56" = getelementptr i8, i8* %".7", i64 %".55"
  %".57" = load i64, i64* %"ss_start"
  %".58" = sub i64 %".9", %".57"
  %".59" = call i8* @"rawstr_new_copy"(i8* %".56", i64 %".58")
  %".60" = call i64 @"rawlist_str_push"(i8* %".15", i8* %".59")
  call void @"rawstr_free"(i8* %".59")
  ret i8* %".15"
}

@"str.ValueError_3a_20empty_20separator" = constant [28 x i8] c"ValueError: empty separator\00"
define void @"rawlist_str_set"(i8* %".1", i64 %".2", i8* %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".6" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp slt i64 %".2", 0
  br i1 %".8", label %"negative", label %"bounds"
negative:
  %".10" = add i64 %".2", %".7"
  br label %"bounds"
bounds:
  %".12" = phi  i64 [%".2", %"entry"], [%".10", %"negative"]
  %".13" = icmp slt i64 %".12", %".7"
  br i1 %".13", label %"ok", label %"index_error"
ok:
  %".18" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".5", i32 0, i32 2
  %".19" = load i8*, i8** %".18"
  %".20" = bitcast i8* %".19" to i64*
  %".21" = getelementptr i64, i64* %".20", i64 %".12"
  %".22" = load i64, i64* %".21"
  %".23" = icmp eq i64 %".22", 0
  br i1 %".23", label %"set_dead", label %"set_live"
index_error:
  %".15" = getelementptr [47 x i8], [47 x i8]* @"str.IndexError_3a_20list_20assignment_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".15")
  unreachable
set_dead:
  br label %"set_store"
set_live:
  %".26" = inttoptr i64 %".22" to i8*
  call void @"rawstr_free"(i8* %".26")
  br label %"set_store"
set_store:
  %".29" = call i8* @"rawstr_copy"(i8* %".3")
  %".30" = ptrtoint i8* %".29" to i64
  store i64 %".30", i64* %".21"
  ret void
}

define i8* @"rawlist_str_get"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = icmp slt i64 %".2", 0
  br i1 %".7", label %"negative", label %"bounds"
negative:
  %".9" = add i64 %".2", %".6"
  br label %"bounds"
bounds:
  %".11" = phi  i64 [%".2", %"entry"], [%".9", %"negative"]
  %".12" = icmp sge i64 %".11", 0
  %".13" = icmp slt i64 %".11", %".6"
  %".14" = and i1 %".12", %".13"
  br i1 %".14", label %"ok", label %"index_error"
ok:
  %".19" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".20" = load i8*, i8** %".19"
  %".21" = bitcast i8* %".20" to i64*
  %".22" = getelementptr i64, i64* %".21", i64 %".11"
  %".23" = load i64, i64* %".22"
  %".24" = inttoptr i64 %".23" to i8*
  %".25" = call i8* @"rawstr_copy"(i8* %".24")
  ret i8* %".25"
index_error:
  %".16" = getelementptr [36 x i8], [36 x i8]* @"str.IndexError_3a_20list_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".16")
  unreachable
}

define i8* @"rawlist_str_copy_into"(i8* %".1", i64 %".2", i8* %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".6" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = icmp slt i64 %".2", 0
  br i1 %".8", label %"negative", label %"bounds"
negative:
  %".10" = add i64 %".2", %".7"
  br label %"bounds"
bounds:
  %".12" = phi  i64 [%".2", %"entry"], [%".10", %"negative"]
  %".13" = icmp sge i64 %".12", 0
  %".14" = icmp slt i64 %".12", %".7"
  %".15" = and i1 %".13", %".14"
  br i1 %".15", label %"ok", label %"index_error"
ok:
  %".20" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".5", i32 0, i32 2
  %".21" = load i8*, i8** %".20"
  %".22" = bitcast i8* %".21" to i64*
  %".23" = getelementptr i64, i64* %".22", i64 %".12"
  %".24" = load i64, i64* %".23"
  %".25" = inttoptr i64 %".24" to i8*
  %".26" = bitcast i8* %".25" to {i64, i64, i8*, i64}*
  %".27" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".26", i32 0, i32 0
  %".28" = load i64, i64* %".27"
  %".29" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".26", i32 0, i32 3
  %".30" = load i64, i64* %".29"
  %".31" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".26", i32 0, i32 2
  %".32" = load i8*, i8** %".31"
  %".33" = ptrtoint i8* %".3" to i64
  %".34" = icmp eq i64 %".33", 0
  br i1 %".34", label %"fresh", label %"fit"
index_error:
  %".17" = getelementptr [36 x i8], [36 x i8]* @"str.IndexError_3a_20list_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".17")
  unreachable
fresh:
  %".36" = call i8* @"malloc"(i64 %".28")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".36", i8* %".32", i64 %".28", i1 0)
  %".38" = call i8* @"malloc"(i64 32)
  %".39" = bitcast i8* %".38" to {i64, i64, i8*, i64}*
  %".40" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".39", i32 0, i32 0
  store i64 %".28", i64* %".40"
  %".42" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".39", i32 0, i32 1
  store i64 %".28", i64* %".42"
  %".44" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".39", i32 0, i32 2
  store i8* %".36", i8** %".44"
  %".46" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".39", i32 0, i32 3
  store i64 %".30", i64* %".46"
  %".48" = bitcast {i64, i64, i8*, i64}* %".39" to i8*
  ret i8* %".48"
fit:
  %".50" = bitcast i8* %".3" to {i64, i64, i8*, i64}*
  %".51" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 1
  %".52" = load i64, i64* %".51"
  %".53" = icmp sge i64 %".52", %".28"
  br i1 %".53", label %"copy", label %"grow"
grow:
  %".55" = mul i64 %".52", 2
  %".56" = icmp sge i64 %".55", %".28"
  %".57" = select  i1 %".56", i64 %".55", i64 %".28"
  %".58" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 2
  %".59" = load i8*, i8** %".58"
  %".60" = call i8* @"realloc"(i8* %".59", i64 %".57")
  %".61" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 2
  store i8* %".60", i8** %".61"
  %".63" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 1
  store i64 %".57", i64* %".63"
  br label %"copy"
copy:
  %".66" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 2
  %".67" = load i8*, i8** %".66"
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".67", i8* %".32", i64 %".28", i1 0)
  %".69" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 0
  store i64 %".28", i64* %".69"
  %".71" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".50", i32 0, i32 3
  store i64 %".30", i64* %".71"
  ret i8* %".3"
}

define i8* @"rawlist_str_ptr"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".6" = load i8*, i8** %".5"
  %".7" = bitcast i8* %".6" to i64*
  %".8" = getelementptr i64, i64* %".7", i64 %".2"
  %".9" = load i64, i64* %".8"
  %".10" = inttoptr i64 %".9" to i8*
  ret i8* %".10"
}

define i1 @"rawlist_str_contains"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".8" = load i8*, i8** %".7"
  %"rlsc_i" = alloca i64
  store i64 0, i64* %"rlsc_i"
  br label %"scan_cond"
scan_cond:
  %".11" = load i64, i64* %"rlsc_i"
  %".12" = icmp slt i64 %".11", %".6"
  br i1 %".12", label %"scan_body", label %"miss"
scan_body:
  %".14" = bitcast i8* %".8" to i64*
  %".15" = getelementptr i64, i64* %".14", i64 %".11"
  %".16" = load i64, i64* %".15"
  %".17" = inttoptr i64 %".16" to i8*
  %".18" = call i1 @"rawstr_eq"(i8* %".17", i8* %".2")
  br i1 %".18", label %"found", label %"scan_step"
scan_step:
  %".20" = add i64 %".11", 1
  store i64 %".20", i64* %"rlsc_i"
  br label %"scan_cond"
found:
  ret i1 1
miss:
  ret i1 0
}

define void @"rawlist_str_clear"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".4" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %"rlcl_i" = alloca i64
  store i64 0, i64* %"rlcl_i"
  br label %"clear_cond"
clear_cond:
  %".10" = load i64, i64* %"rlcl_i"
  %".11" = icmp slt i64 %".10", %".5"
  br i1 %".11", label %"clear_body", label %"clear_done"
clear_body:
  %".13" = bitcast i8* %".7" to i64*
  %".14" = getelementptr i64, i64* %".13", i64 %".10"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"cl_dead", label %"cl_live"
clear_skip:
  %".24" = add i64 %".10", 1
  store i64 %".24", i64* %"rlcl_i"
  br label %"clear_cond"
clear_done:
  %".27" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".3", i32 0, i32 0
  store i64 0, i64* %".27"
  ret void
cl_dead:
  br label %"clear_skip"
cl_live:
  %".19" = inttoptr i64 %".15" to i8*
  call void @"rawstr_free"(i8* %".19")
  %".21" = getelementptr i64, i64* %".13", i64 %".10"
  store i64 0, i64* %".21"
  br label %"clear_skip"
}

define i1 @"rawlist_contains_bits"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 0
  %".6" = load i64, i64* %".5"
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to i64*
  %"rlc_i" = alloca i64
  store i64 0, i64* %"rlc_i"
  br label %"scan_cond"
scan_cond:
  %".12" = load i64, i64* %"rlc_i"
  %".13" = icmp slt i64 %".12", %".6"
  br i1 %".13", label %"scan_body", label %"miss"
scan_body:
  %".15" = getelementptr i64, i64* %".9", i64 %".12"
  %".16" = load i64, i64* %".15"
  %".17" = icmp eq i64 %".16", %".2"
  br i1 %".17", label %"found", label %"scan_step"
scan_step:
  %".19" = add i64 %".12", 1
  store i64 %".19", i64* %"rlc_i"
  br label %"scan_cond"
found:
  ret i1 1
miss:
  ret i1 0
}

define {i32, i8*}* @"rawstr_to_pystr"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %".8" = call i8* @"malloc"(i64 %".5")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".8", i8* %".7", i64 %".5", i1 0)
  %".10" = trunc i64 %".5" to i32
  %".11" = call {i32, i8*}* @"create_str"(i8* %".8", i32 %".10")
  ret {i32, i8*}* %".11"
}

define i8* @"pystr_to_rawstr"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".4" = load i32, i32* %".3"
  %".5" = icmp eq i32 %".4", 2
  br i1 %".5", label %"ok", label %"type_error"
ok:
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".8" = load i8*, i8** %".7"
  %".9" = bitcast i8* %".8" to {i32, i8*}*
  %".10" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 0
  %".11" = load i32, i32* %".10"
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".9", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = sext i32 %".11" to i64
  %".15" = call i8* @"malloc"(i64 %".14")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".15", i8* %".13", i64 %".14", i1 0)
  %".17" = call i64 @"rawutf8_cp_count"(i8* %".13", i64 %".14")
  %".18" = call i8* @"malloc"(i64 32)
  %".19" = bitcast i8* %".18" to {i64, i64, i8*, i64}*
  %".20" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".19", i32 0, i32 0
  store i64 %".14", i64* %".20"
  %".22" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".19", i32 0, i32 1
  store i64 %".14", i64* %".22"
  %".24" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".19", i32 0, i32 2
  store i8* %".15", i8** %".24"
  %".26" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".19", i32 0, i32 3
  store i64 %".17", i64* %".26"
  %".28" = bitcast {i64, i64, i8*, i64}* %".19" to i8*
  ret i8* %".28"
type_error:
  %".30" = getelementptr [24 x i8], [24 x i8]* @"str_typeerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".30")
  unreachable
}

define i8* @"rawstr_to_cstr"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %".8" = add i64 %".5", 1
  %".9" = call i8* @"malloc"(i64 %".8")
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".9", i8* %".7", i64 %".5", i1 0)
  %".11" = getelementptr i8, i8* %".9", i64 %".5"
  store i8 0, i8* %".11"
  ret i8* %".9"
}

declare i64 @"strtol"(i8* %".1", i8** %".2", i32 %".3")

define i64 @"rawstr_fnv"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i8*, i64}*
  %".4" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 0
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i8*, i64}, {i64, i64, i8*, i64}* %".3", i32 0, i32 2
  %".7" = load i8*, i8** %".6"
  %"fnv_i" = alloca i64
  %"fnv_h" = alloca i64
  store i64 0, i64* %"fnv_i"
  store i64 1469598103934665603, i64* %"fnv_h"
  br label %"fnv_cond"
fnv_cond:
  %".11" = load i64, i64* %"fnv_i"
  %".12" = icmp slt i64 %".11", %".5"
  br i1 %".12", label %"fnv_body", label %"fnv_done"
fnv_body:
  %".14" = getelementptr i8, i8* %".7", i64 %".11"
  %".15" = load i8, i8* %".14"
  %".16" = zext i8 %".15" to i64
  %".17" = load i64, i64* %"fnv_h"
  %".18" = xor i64 %".17", %".16"
  %".19" = mul i64 %".18", 1099511628211
  store i64 %".19", i64* %"fnv_h"
  %".21" = add i64 %".11", 1
  store i64 %".21", i64* %"fnv_i"
  br label %"fnv_cond"
fnv_done:
  %".24" = load i64, i64* %"fnv_h"
  ret i64 %".24"
}

define i64 @"rawdict_str_get"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"sprobe_slot" = alloca i64
  %".7" = call i64 @"rawstr_fnv"(i8* %".2")
  %".8" = and i64 %".7", %".6"
  store i64 %".8", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"sprobe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = inttoptr i64 %".24" to i8*
  %".26" = call i1 @"rawstr_eq"(i8* %".25", i8* %".2")
  br i1 %".26", label %"hit", label %"probe_step"
hit:
  %".28" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".29" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".28", i32 0, i32 6
  %".30" = load i64*, i64** %".29"
  %".31" = getelementptr i64, i64* %".30", i64 %".20"
  %".32" = load i64, i64* %".31"
  ret i64 %".32"
probe_step:
  %".34" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".35" = load i64, i64* %".34"
  %".36" = add i64 %".13", 1
  %".37" = and i64 %".36", %".35"
  store i64 %".37", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  %".40" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".40")
  unreachable
}

define i64 @"rawdict_str_del"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"sprobe_slot" = alloca i64
  %".7" = call i64 @"rawstr_fnv"(i8* %".2")
  %".8" = and i64 %".7", %".6"
  store i64 %".8", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"sprobe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = inttoptr i64 %".24" to i8*
  %".26" = call i1 @"rawstr_eq"(i8* %".25", i8* %".2")
  br i1 %".26", label %"hit", label %"probe_step"
hit:
  %".28" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".29" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".28", i32 0, i32 5
  %".30" = load i64*, i64** %".29"
  %".31" = getelementptr i64, i64* %".30", i64 %".20"
  %".32" = load i64, i64* %".31"
  %".33" = inttoptr i64 %".32" to i8*
  call void @"rawstr_free"(i8* %".33")
  %".35" = getelementptr i64, i64* %".30", i64 %".20"
  store i64 0, i64* %".35"
  %".37" = getelementptr i64, i64* %".12", i64 %".13"
  store i64 -1, i64* %".37"
  %".39" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".40" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".39", i32 0, i32 0
  %".41" = load i64, i64* %".40"
  %".42" = sub i64 %".41", 1
  %".43" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".39", i32 0, i32 0
  store i64 %".42", i64* %".43"
  %".45" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".46" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".45", i32 0, i32 6
  %".47" = load i64*, i64** %".46"
  %".48" = getelementptr i64, i64* %".47", i64 %".20"
  %".49" = load i64, i64* %".48"
  ret i64 %".49"
probe_step:
  %".51" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".52" = load i64, i64* %".51"
  %".53" = add i64 %".13", 1
  %".54" = and i64 %".53", %".52"
  store i64 %".54", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  %".57" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".57")
  unreachable
}

define i1 @"rawdict_str_has"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"sprobe_slot" = alloca i64
  %".7" = call i64 @"rawstr_fnv"(i8* %".2")
  %".8" = and i64 %".7", %".6"
  store i64 %".8", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"sprobe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = inttoptr i64 %".24" to i8*
  %".26" = call i1 @"rawstr_eq"(i8* %".25", i8* %".2")
  br i1 %".26", label %"hit", label %"probe_step"
hit:
  ret i1 1
probe_step:
  %".29" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".30" = load i64, i64* %".29"
  %".31" = add i64 %".13", 1
  %".32" = and i64 %".31", %".30"
  store i64 %".32", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  ret i1 0
}

define i64 @"rawdict_str_get_or"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"sprobe_slot" = alloca i64
  %".8" = call i64 @"rawstr_fnv"(i8* %".2")
  %".9" = and i64 %".8", %".7"
  store i64 %".9", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".13" = load i64*, i64** %".12"
  %".14" = load i64, i64* %"sprobe_slot"
  %".15" = getelementptr i64, i64* %".13", i64 %".14"
  %".16" = load i64, i64* %".15"
  %".17" = icmp eq i64 %".16", 0
  br i1 %".17", label %"miss", label %"probe_tomb"
probe_tomb:
  %".19" = icmp eq i64 %".16", -1
  br i1 %".19", label %"probe_step", label %"probe_match"
probe_match:
  %".21" = sub i64 %".16", 1
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".23", i64 %".21"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call i1 @"rawstr_eq"(i8* %".26", i8* %".2")
  br i1 %".27", label %"hit", label %"probe_step"
hit:
  %".29" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 6
  %".31" = load i64*, i64** %".30"
  %".32" = getelementptr i64, i64* %".31", i64 %".21"
  %".33" = load i64, i64* %".32"
  ret i64 %".33"
probe_step:
  %".35" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".36" = load i64, i64* %".35"
  %".37" = add i64 %".14", 1
  %".38" = and i64 %".37", %".36"
  store i64 %".38", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  ret i64 %".3"
}

define i64 @"rawdict_str_pop_or"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"sprobe_slot" = alloca i64
  %".8" = call i64 @"rawstr_fnv"(i8* %".2")
  %".9" = and i64 %".8", %".7"
  store i64 %".9", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".13" = load i64*, i64** %".12"
  %".14" = load i64, i64* %"sprobe_slot"
  %".15" = getelementptr i64, i64* %".13", i64 %".14"
  %".16" = load i64, i64* %".15"
  %".17" = icmp eq i64 %".16", 0
  br i1 %".17", label %"miss", label %"probe_tomb"
probe_tomb:
  %".19" = icmp eq i64 %".16", -1
  br i1 %".19", label %"probe_step", label %"probe_match"
probe_match:
  %".21" = sub i64 %".16", 1
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".23", i64 %".21"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call i1 @"rawstr_eq"(i8* %".26", i8* %".2")
  br i1 %".27", label %"hit", label %"probe_step"
hit:
  %".29" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 5
  %".31" = load i64*, i64** %".30"
  %".32" = getelementptr i64, i64* %".31", i64 %".21"
  %".33" = load i64, i64* %".32"
  %".34" = inttoptr i64 %".33" to i8*
  call void @"rawstr_free"(i8* %".34")
  %".36" = getelementptr i64, i64* %".31", i64 %".21"
  store i64 0, i64* %".36"
  %".38" = getelementptr i64, i64* %".13", i64 %".14"
  store i64 -1, i64* %".38"
  %".40" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".41" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".40", i32 0, i32 0
  %".42" = load i64, i64* %".41"
  %".43" = sub i64 %".42", 1
  %".44" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".40", i32 0, i32 0
  store i64 %".43", i64* %".44"
  %".46" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".47" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".46", i32 0, i32 6
  %".48" = load i64*, i64** %".47"
  %".49" = getelementptr i64, i64* %".48", i64 %".21"
  %".50" = load i64, i64* %".49"
  ret i64 %".50"
probe_step:
  %".52" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".53" = load i64, i64* %".52"
  %".54" = add i64 %".14", 1
  %".55" = and i64 %".54", %".53"
  store i64 %".55", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  ret i64 %".3"
}

define void @"rawdict_str_reindex"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %".7" = add i64 %".6", 1
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".9" = load i64*, i64** %".8"
  %".10" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".11" = load i64*, i64** %".10"
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  %".13" = load i64*, i64** %".12"
  %".14" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 2
  %".15" = load i64, i64* %".14"
  %".16" = sub i64 %".2", 1
  %".17" = call i8* @"calloc"(i64 %".2", i64 8)
  %".18" = bitcast i8* %".17" to i64*
  %".19" = mul i64 %".15", 8
  %".20" = call i8* @"malloc"(i64 %".19")
  %".21" = bitcast i8* %".20" to i64*
  %".22" = call i8* @"malloc"(i64 %".19")
  %".23" = bitcast i8* %".22" to i64*
  %".24" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  store i64 %".16", i64* %".24"
  %".26" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  store i64* %".18", i64** %".26"
  %".28" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  store i64* %".21", i64** %".28"
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 6
  store i64* %".23", i64** %".30"
  %"sre_i" = alloca i64
  %"sre_live" = alloca i64
  %"sre_slot" = alloca i64
  store i64 0, i64* %"sre_i"
  store i64 0, i64* %"sre_live"
  br label %"scan_cond"
scan_cond:
  %".35" = load i64, i64* %"sre_i"
  %".36" = icmp slt i64 %".35", %".7"
  br i1 %".36", label %"scan_body", label %"scan_done"
scan_body:
  %".38" = getelementptr i64, i64* %".9", i64 %".35"
  %".39" = load i64, i64* %".38"
  %".40" = icmp sgt i64 %".39", 0
  br i1 %".40", label %"place_start", label %"scan_step"
place_start:
  %".42" = sub i64 %".39", 1
  %".43" = getelementptr i64, i64* %".11", i64 %".42"
  %".44" = load i64, i64* %".43"
  %".45" = getelementptr i64, i64* %".13", i64 %".42"
  %".46" = load i64, i64* %".45"
  %".47" = load i64, i64* %"sre_live"
  %".48" = getelementptr i64, i64* %".21", i64 %".47"
  store i64 %".44", i64* %".48"
  %".50" = getelementptr i64, i64* %".23", i64 %".47"
  store i64 %".46", i64* %".50"
  %".52" = inttoptr i64 %".44" to i8*
  %".53" = call i64 @"rawstr_fnv"(i8* %".52")
  %".54" = and i64 %".53", %".16"
  store i64 %".54", i64* %"sre_slot"
  br label %"place_probe"
place_probe:
  %".57" = load i64, i64* %"sre_slot"
  %".58" = getelementptr i64, i64* %".18", i64 %".57"
  %".59" = load i64, i64* %".58"
  %".60" = icmp ne i64 %".59", 0
  br i1 %".60", label %"place_step", label %"place_store"
place_store:
  %".62" = add i64 %".47", 1
  %".63" = getelementptr i64, i64* %".18", i64 %".57"
  store i64 %".62", i64* %".63"
  %".65" = add i64 %".47", 1
  store i64 %".65", i64* %"sre_live"
  br label %"scan_step"
place_step:
  %".68" = add i64 %".57", 1
  %".69" = and i64 %".68", %".16"
  store i64 %".69", i64* %"sre_slot"
  br label %"place_probe"
scan_step:
  %".72" = add i64 %".35", 1
  store i64 %".72", i64* %"sre_i"
  br label %"scan_cond"
scan_done:
  %".75" = load i64, i64* %"sre_live"
  %".76" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 1
  store i64 %".75", i64* %".76"
  %".78" = bitcast i64* %".9" to i8*
  call void @"free"(i8* %".78")
  %".80" = bitcast i64* %".11" to i8*
  call void @"free"(i8* %".80")
  %".82" = bitcast i64* %".13" to i8*
  call void @"free"(i8* %".82")
  ret void
}

define void @"rawdict_str_set"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".9" = load i64, i64* %".8"
  %".10" = add i64 %".9", 1
  %".11" = add i64 %".7", 1
  %".12" = mul i64 %".11", 3
  %".13" = mul i64 %".10", 2
  %".14" = icmp sgt i64 %".12", %".13"
  %"rds_slot" = alloca i64
  %"rds_tomb" = alloca i64
  %"rds_size" = alloca i64
  br i1 %".14", label %"rehash", label %"probe_start"
rehash:
  %".16" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  %".17" = load i64, i64* %".16"
  store i64 8, i64* %"rds_size"
  br label %"size_check"
size_check:
  %".20" = load i64, i64* %"rds_size"
  %".21" = add i64 %".17", 1
  %".22" = mul i64 %".21", 3
  %".23" = mul i64 %".20", 2
  %".24" = icmp sgt i64 %".22", %".23"
  br i1 %".24", label %"size_grow", label %"size_done"
size_grow:
  %".26" = mul i64 %".20", 2
  store i64 %".26", i64* %"rds_size"
  br label %"size_check"
size_done:
  %".29" = load i64, i64* %"rds_size"
  call void @"rawdict_str_reindex"(i8* %".1", i64 %".29")
  br label %"probe_start"
probe_start:
  store i64 -1, i64* %"rds_tomb"
  %".33" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".34" = load i64, i64* %".33"
  %".35" = call i64 @"rawstr_fnv"(i8* %".2")
  %".36" = and i64 %".35", %".34"
  store i64 %".36", i64* %"rds_slot"
  br label %"probe_test"
probe_test:
  %".39" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".40" = load i64*, i64** %".39"
  %".41" = load i64, i64* %"rds_slot"
  %".42" = getelementptr i64, i64* %".40", i64 %".41"
  %".43" = load i64, i64* %".42"
  %".44" = icmp eq i64 %".43", 0
  br i1 %".44", label %"insert", label %"probe_tomb"
probe_tomb:
  %".46" = icmp eq i64 %".43", -1
  br i1 %".46", label %"tomb_note", label %"probe_match"
tomb_note:
  %".48" = load i64, i64* %"rds_tomb"
  %".49" = icmp eq i64 %".48", -1
  br i1 %".49", label %"tomb_store", label %"probe_step"
tomb_store:
  store i64 %".41", i64* %"rds_tomb"
  br label %"probe_step"
probe_match:
  %".53" = sub i64 %".43", 1
  %".54" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".55" = load i64*, i64** %".54"
  %".56" = getelementptr i64, i64* %".55", i64 %".53"
  %".57" = load i64, i64* %".56"
  %".58" = inttoptr i64 %".57" to i8*
  %".59" = call i1 @"rawstr_eq"(i8* %".58", i8* %".2")
  br i1 %".59", label %"overwrite", label %"probe_step"
overwrite:
  %".61" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".62" = load i64*, i64** %".61"
  %".63" = getelementptr i64, i64* %".62", i64 %".53"
  store i64 %".3", i64* %".63"
  ret void
probe_step:
  %".66" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".67" = load i64, i64* %".66"
  %".68" = add i64 %".41", 1
  %".69" = and i64 %".68", %".67"
  store i64 %".69", i64* %"rds_slot"
  br label %"probe_test"
insert:
  %".72" = load i64, i64* %"rds_tomb"
  %".73" = icmp ne i64 %".72", -1
  %".74" = load i64, i64* %"rds_slot"
  %".75" = select  i1 %".73", i64 %".72", i64 %".74"
  store i64 %".75", i64* %"rds_slot"
  %".77" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  %".78" = load i64, i64* %".77"
  %".79" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 2
  %".80" = load i64, i64* %".79"
  %".81" = icmp eq i64 %".78", %".80"
  br i1 %".81", label %"grow", label %"do_insert"
grow:
  %".83" = mul i64 %".80", 2
  %".84" = mul i64 %".83", 8
  %".85" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".86" = load i64*, i64** %".85"
  %".87" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".88" = load i64*, i64** %".87"
  %".89" = call i8* @"malloc"(i64 %".84")
  %".90" = bitcast i8* %".89" to i64*
  %".91" = call i8* @"malloc"(i64 %".84")
  %".92" = bitcast i8* %".91" to i64*
  %".93" = mul i64 %".78", 8
  %".94" = bitcast i64* %".90" to i8*
  %".95" = bitcast i64* %".86" to i8*
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".94", i8* %".95", i64 %".93", i1 0)
  %".97" = bitcast i64* %".92" to i8*
  %".98" = bitcast i64* %".88" to i8*
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".97", i8* %".98", i64 %".93", i1 0)
  %".100" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 2
  store i64 %".83", i64* %".100"
  %".102" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  store i64* %".90", i64** %".102"
  %".104" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  store i64* %".92", i64** %".104"
  %".106" = bitcast i64* %".86" to i8*
  call void @"free"(i8* %".106")
  %".108" = bitcast i64* %".88" to i8*
  call void @"free"(i8* %".108")
  br label %"do_insert"
do_insert:
  %".111" = load i64, i64* %"rds_slot"
  %".112" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".113" = load i64*, i64** %".112"
  %".114" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 6
  %".115" = load i64*, i64** %".114"
  %".116" = call i8* @"rawstr_copy"(i8* %".2")
  %".117" = ptrtoint i8* %".116" to i64
  %".118" = getelementptr i64, i64* %".113", i64 %".78"
  store i64 %".117", i64* %".118"
  %".120" = getelementptr i64, i64* %".115", i64 %".78"
  store i64 %".3", i64* %".120"
  %".122" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".123" = load i64*, i64** %".122"
  %".124" = add i64 %".78", 1
  %".125" = getelementptr i64, i64* %".123", i64 %".111"
  store i64 %".124", i64* %".125"
  %".127" = add i64 %".78", 1
  %".128" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 1
  store i64 %".127", i64* %".128"
  %".130" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  %".131" = load i64, i64* %".130"
  %".132" = add i64 %".131", 1
  %".133" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 0
  store i64 %".132", i64* %".133"
  ret void
}

define i64 @"rawdict_str_setdefault"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"sprobe_slot" = alloca i64
  %".8" = call i64 @"rawstr_fnv"(i8* %".2")
  %".9" = and i64 %".8", %".7"
  store i64 %".9", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".13" = load i64*, i64** %".12"
  %".14" = load i64, i64* %"sprobe_slot"
  %".15" = getelementptr i64, i64* %".13", i64 %".14"
  %".16" = load i64, i64* %".15"
  %".17" = icmp eq i64 %".16", 0
  br i1 %".17", label %"miss", label %"probe_tomb"
probe_tomb:
  %".19" = icmp eq i64 %".16", -1
  br i1 %".19", label %"probe_step", label %"probe_match"
probe_match:
  %".21" = sub i64 %".16", 1
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".23", i64 %".21"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call i1 @"rawstr_eq"(i8* %".26", i8* %".2")
  br i1 %".27", label %"hit", label %"probe_step"
hit:
  %".29" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 6
  %".31" = load i64*, i64** %".30"
  %".32" = getelementptr i64, i64* %".31", i64 %".21"
  %".33" = load i64, i64* %".32"
  ret i64 %".33"
probe_step:
  %".35" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".36" = load i64, i64* %".35"
  %".37" = add i64 %".14", 1
  %".38" = and i64 %".37", %".36"
  store i64 %".38", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  call void @"rawdict_str_set"(i8* %".1", i8* %".2", i64 %".3")
  ret i64 %".3"
}

define i8* @"rawdict_str_slotof"(i8* %".1", i8* %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".5" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".6" = load i64, i64* %".5"
  %"sprobe_slot" = alloca i64
  %".7" = call i64 @"rawstr_fnv"(i8* %".2")
  %".8" = and i64 %".7", %".6"
  store i64 %".8", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 4
  %".12" = load i64*, i64** %".11"
  %".13" = load i64, i64* %"sprobe_slot"
  %".14" = getelementptr i64, i64* %".12", i64 %".13"
  %".15" = load i64, i64* %".14"
  %".16" = icmp eq i64 %".15", 0
  br i1 %".16", label %"miss", label %"probe_tomb"
probe_tomb:
  %".18" = icmp eq i64 %".15", -1
  br i1 %".18", label %"probe_step", label %"probe_match"
probe_match:
  %".20" = sub i64 %".15", 1
  %".21" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 5
  %".22" = load i64*, i64** %".21"
  %".23" = getelementptr i64, i64* %".22", i64 %".20"
  %".24" = load i64, i64* %".23"
  %".25" = inttoptr i64 %".24" to i8*
  %".26" = call i1 @"rawstr_eq"(i8* %".25", i8* %".2")
  br i1 %".26", label %"hit", label %"probe_step"
hit:
  %".28" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".29" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".28", i32 0, i32 6
  %".30" = load i64*, i64** %".29"
  %".31" = getelementptr i64, i64* %".30", i64 %".20"
  %".32" = bitcast i64* %".31" to i8*
  ret i8* %".32"
probe_step:
  %".34" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".4", i32 0, i32 3
  %".35" = load i64, i64* %".34"
  %".36" = add i64 %".13", 1
  %".37" = and i64 %".36", %".35"
  store i64 %".37", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  %".40" = getelementptr [24 x i8], [24 x i8]* @"str_keyerr", i32 0, i32 0
  call void @"silu_panic"(i8* %".40")
  unreachable
}

define i8* @"rawdict_str_entry"(i8* %".1", i8* %".2", i64 %".3")
{
entry:
  %".5" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".7" = load i64, i64* %".6"
  %"sprobe_slot" = alloca i64
  %".8" = call i64 @"rawstr_fnv"(i8* %".2")
  %".9" = and i64 %".8", %".7"
  store i64 %".9", i64* %"sprobe_slot"
  br label %"probe_test"
probe_test:
  %".12" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 4
  %".13" = load i64*, i64** %".12"
  %".14" = load i64, i64* %"sprobe_slot"
  %".15" = getelementptr i64, i64* %".13", i64 %".14"
  %".16" = load i64, i64* %".15"
  %".17" = icmp eq i64 %".16", 0
  br i1 %".17", label %"miss", label %"probe_tomb"
probe_tomb:
  %".19" = icmp eq i64 %".16", -1
  br i1 %".19", label %"probe_step", label %"probe_match"
probe_match:
  %".21" = sub i64 %".16", 1
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 5
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".23", i64 %".21"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call i1 @"rawstr_eq"(i8* %".26", i8* %".2")
  br i1 %".27", label %"hit", label %"probe_step"
hit:
  %".29" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".30" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".29", i32 0, i32 6
  %".31" = load i64*, i64** %".30"
  %".32" = getelementptr i64, i64* %".31", i64 %".21"
  %".33" = bitcast i64* %".32" to i8*
  ret i8* %".33"
probe_step:
  %".35" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".5", i32 0, i32 3
  %".36" = load i64, i64* %".35"
  %".37" = add i64 %".14", 1
  %".38" = and i64 %".37", %".36"
  store i64 %".38", i64* %"sprobe_slot"
  br label %"probe_test"
miss:
  call void @"rawdict_str_set"(i8* %".1", i8* %".2", i64 %".3")
  %".42" = call i8* @"rawdict_str_slotof"(i8* %".1", i8* %".2")
  ret i8* %".42"
}

define void @"rawdict_str_clear"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 1
  %".5" = load i64, i64* %".4"
  %".6" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  %".7" = load i64*, i64** %".6"
  %"rdc_i" = alloca i64
  store i64 0, i64* %"rdc_i"
  br label %"clear_cond"
clear_cond:
  %".10" = load i64, i64* %"rdc_i"
  %".11" = icmp slt i64 %".10", %".5"
  br i1 %".11", label %"clear_body", label %"clear_done"
clear_body:
  %".13" = getelementptr i64, i64* %".7", i64 %".10"
  %".14" = load i64, i64* %".13"
  %".15" = icmp eq i64 %".14", 0
  br i1 %".15", label %"clear_skip", label %"clear_free"
clear_done:
  call void @"rawdict_clear"(i8* %".1")
  ret void
clear_skip:
  %".20" = add i64 %".10", 1
  store i64 %".20", i64* %"rdc_i"
  br label %"clear_cond"
clear_free:
  %".17" = inttoptr i64 %".14" to i8*
  call void @"rawstr_free"(i8* %".17")
  br label %"clear_skip"
}

define {i32, i8*}* @"rawdict_to_pydict_si"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  %".5" = load i64, i64* %".4"
  %".6" = add i64 %".5", 1
  %".7" = call {i32, i8*}* @"create_dict"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".6"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  %".14" = load i64*, i64** %".13"
  %".15" = getelementptr i64, i64* %".14", i64 %".10"
  %".16" = load i64, i64* %".15"
  %".17" = icmp sgt i64 %".16", 0
  br i1 %".17", label %"cvt_emit", label %"cvt_step"
cvt_emit:
  %".19" = sub i64 %".16", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 6
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".21", i64 %".19"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call {i32, i8*}* @"rawstr_to_pystr"(i8* %".26")
  %".28" = getelementptr i64, i64* %".23", i64 %".19"
  %".29" = load i64, i64* %".28"
  %".30" = call {i32, i8*}* @"create_int"(i64 %".29")
  call void @"dict_set"({i32, i8*}* %".7", {i32, i8*}* %".27", {i32, i8*}* %".30")
  br label %"cvt_step"
cvt_step:
  %".33" = add i64 %".10", 1
  store i64 %".33", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define {i32, i8*}* @"rawdict_to_pydict_sf"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".4" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 3
  %".5" = load i64, i64* %".4"
  %".6" = add i64 %".5", 1
  %".7" = call {i32, i8*}* @"create_dict"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".6"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 4
  %".14" = load i64*, i64** %".13"
  %".15" = getelementptr i64, i64* %".14", i64 %".10"
  %".16" = load i64, i64* %".15"
  %".17" = icmp sgt i64 %".16", 0
  br i1 %".17", label %"cvt_emit", label %"cvt_step"
cvt_emit:
  %".19" = sub i64 %".16", 1
  %".20" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 5
  %".21" = load i64*, i64** %".20"
  %".22" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".3", i32 0, i32 6
  %".23" = load i64*, i64** %".22"
  %".24" = getelementptr i64, i64* %".21", i64 %".19"
  %".25" = load i64, i64* %".24"
  %".26" = inttoptr i64 %".25" to i8*
  %".27" = call {i32, i8*}* @"rawstr_to_pystr"(i8* %".26")
  %".28" = getelementptr i64, i64* %".23", i64 %".19"
  %".29" = load i64, i64* %".28"
  %".30" = bitcast i64 %".29" to double
  %".31" = call {i32, i8*}* @"create_float"(double %".30")
  call void @"dict_set"({i32, i8*}* %".7", {i32, i8*}* %".27", {i32, i8*}* %".31")
  br label %"cvt_step"
cvt_step:
  %".34" = add i64 %".10", 1
  store i64 %".34", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define {i32, i8*}* @"rawlist_str_to_pylist"(i8* %".1", i64 %".2")
{
entry:
  %".4" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".5" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".4", i32 0, i32 2
  %".6" = load i8*, i8** %".5"
  %".7" = call {i32, i8*}* @"create_list"()
  %"cvt_i" = alloca i64
  store i64 0, i64* %"cvt_i"
  br label %"cvt_check"
cvt_check:
  %".10" = load i64, i64* %"cvt_i"
  %".11" = icmp slt i64 %".10", %".2"
  br i1 %".11", label %"cvt_body", label %"cvt_done"
cvt_body:
  %".13" = bitcast i8* %".6" to i64*
  %".14" = getelementptr i64, i64* %".13", i64 %".10"
  %".15" = load i64, i64* %".14"
  %".16" = inttoptr i64 %".15" to i8*
  %".17" = call {i32, i8*}* @"rawstr_to_pystr"(i8* %".16")
  %".18" = call {i32, i8*}* @"list_append"({i32, i8*}* %".7", {i32, i8*}* %".17")
  %".19" = add i64 %".10", 1
  store i64 %".19", i64* %"cvt_i"
  br label %"cvt_check"
cvt_done:
  ret {i32, i8*}* %".7"
}

define i8* @"pylist_to_rawlist_str"({i32, i8*}* %".1")
{
entry:
  %".3" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".4" = load i8*, i8** %".3"
  %".5" = bitcast i8* %".4" to {i64, i64, {i32, i8*}**}*
  %".6" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 0
  %".7" = load i64, i64* %".6"
  %".8" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".5", i32 0, i32 2
  %".9" = load {i32, i8*}**, {i32, i8*}*** %".8"
  %".10" = call i8* @"rawlist_new"(i64 8)
  %"p2s_i" = alloca i64
  store i64 0, i64* %"p2s_i"
  br label %"p2s_check"
p2s_check:
  %".13" = load i64, i64* %"p2s_i"
  %".14" = icmp slt i64 %".13", %".7"
  br i1 %".14", label %"p2s_body", label %"p2s_done"
p2s_body:
  %".16" = getelementptr {i32, i8*}*, {i32, i8*}** %".9", i64 %".13"
  %".17" = load {i32, i8*}*, {i32, i8*}** %".16"
  %".18" = call i8* @"pystr_to_rawstr"({i32, i8*}* %".17")
  %".19" = call i64 @"rawlist_str_push"(i8* %".10", i8* %".18")
  %".20" = add i64 %".13", 1
  store i64 %".20", i64* %"p2s_i"
  br label %"p2s_check"
p2s_done:
  ret i8* %".10"
}

define void @"rawlist_get"(i8* %".1", i64 %".2", i8* %".3", i64 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = icmp slt i64 %".2", 0
  br i1 %".9", label %"negative", label %"bounds"
bounds:
  %".13" = phi  i64 [%".2", %"entry"], [%".11", %"negative"]
  %".14" = icmp slt i64 %".13", %".8"
  br i1 %".14", label %"ok", label %"index_error"
negative:
  %".11" = add i64 %".2", %".8"
  br label %"bounds"
ok:
  %".19" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 2
  %".20" = load i8*, i8** %".19"
  %".21" = bitcast i8* %".20" to i64*
  %".22" = getelementptr i64, i64* %".21", i64 %".13"
  %".23" = load i64, i64* %".22"
  %".24" = bitcast i8* %".3" to i64*
  store i64 %".23", i64* %".24"
  ret void
index_error:
  %".16" = getelementptr [36 x i8], [36 x i8]* @"str.IndexError_3a_20list_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".16")
  unreachable
}

define void @"rawlist_set"(i8* %".1", i64 %".2", i8* %".3", i64 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 0
  %".8" = load i64, i64* %".7"
  %".9" = icmp slt i64 %".2", 0
  br i1 %".9", label %"negative", label %"bounds"
negative:
  %".11" = add i64 %".2", %".8"
  br label %"bounds"
bounds:
  %".13" = phi  i64 [%".2", %"entry"], [%".11", %"negative"]
  %".14" = icmp slt i64 %".13", %".8"
  br i1 %".14", label %"ok", label %"index_error"
ok:
  %".19" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 2
  %".20" = load i8*, i8** %".19"
  %".21" = bitcast i8* %".20" to i64*
  %".22" = getelementptr i64, i64* %".21", i64 %".13"
  %".23" = bitcast i8* %".3" to i64*
  %".24" = load i64, i64* %".23"
  store i64 %".24", i64* %".22"
  ret void
index_error:
  %".16" = getelementptr [47 x i8], [47 x i8]* @"str.IndexError_3a_20list_20assignment_20index_20out_20of_20range", i32 0, i32 0
  call void @"silu_panic"(i8* %".16")
  unreachable
}

define {i32, i8*}* @"str_join_boxed"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".5" = load i8*, i8** %".4"
  %".6" = bitcast i8* %".5" to {i32, i8*}*
  %".7" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 0
  %".8" = load i32, i32* %".7"
  %".9" = getelementptr {i32, i8*}, {i32, i8*}* %".6", i32 0, i32 1
  %".10" = load i8*, i8** %".9"
  %".11" = sext i32 %".8" to i64
  %".12" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".13" = load i8*, i8** %".12"
  %".14" = bitcast i8* %".13" to {i64, i64, {i32, i8*}**}*
  %".15" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".14", i32 0, i32 0
  %".16" = load i64, i64* %".15"
  %".17" = getelementptr {i64, i64, {i32, i8*}**}, {i64, i64, {i32, i8*}**}* %".14", i32 0, i32 2
  %".18" = load {i32, i8*}**, {i32, i8*}*** %".17"
  %"sjoin_total" = alloca i64
  store i64 0, i64* %"sjoin_total"
  %"sjoin_sz_i" = alloca i64
  store i64 0, i64* %"sjoin_sz_i"
  br label %"sjoin_sz_cond"
sjoin_sz_cond:
  %".22" = load i64, i64* %"sjoin_sz_i"
  %".23" = icmp slt i64 %".22", %".16"
  br i1 %".23", label %"sjoin_sz_body", label %"sjoin_sz_done"
sjoin_sz_body:
  %".25" = load i64, i64* %"sjoin_sz_i"
  %".26" = getelementptr {i32, i8*}*, {i32, i8*}** %".18", i64 %".25"
  %".27" = load {i32, i8*}*, {i32, i8*}** %".26"
  %".28" = getelementptr {i32, i8*}, {i32, i8*}* %".27", i32 0, i32 1
  %".29" = load i8*, i8** %".28"
  %".30" = bitcast i8* %".29" to {i32, i8*}*
  %".31" = getelementptr {i32, i8*}, {i32, i8*}* %".30", i32 0, i32 0
  %".32" = load i32, i32* %".31"
  %".33" = getelementptr {i32, i8*}, {i32, i8*}* %".30", i32 0, i32 1
  %".34" = load i8*, i8** %".33"
  %".35" = sext i32 %".32" to i64
  %".36" = add i64 %".25", 1
  %".37" = icmp slt i64 %".36", %".16"
  %".38" = add i64 %".35", %".11"
  %".39" = select  i1 %".37", i64 %".38", i64 %".35"
  %".40" = load i64, i64* %"sjoin_total"
  %".41" = add i64 %".40", %".39"
  store i64 %".41", i64* %"sjoin_total"
  %".43" = load i64, i64* %"sjoin_sz_i"
  %".44" = add i64 %".43", 1
  store i64 %".44", i64* %"sjoin_sz_i"
  br label %"sjoin_sz_cond"
sjoin_sz_done:
  %".47" = load i64, i64* %"sjoin_total"
  %".48" = call i8* @"malloc"(i64 %".47")
  %"sjoin_out" = alloca i8*
  store i8* %".48", i8** %"sjoin_out"
  %"sjoin_cp_i" = alloca i64
  store i64 0, i64* %"sjoin_cp_i"
  br label %"sjoin_cp_cond"
sjoin_cp_cond:
  %".52" = load i64, i64* %"sjoin_cp_i"
  %".53" = icmp slt i64 %".52", %".16"
  br i1 %".53", label %"sjoin_cp_body", label %"sjoin_cp_done"
sjoin_cp_body:
  %".55" = load i64, i64* %"sjoin_cp_i"
  %".56" = icmp sgt i64 %".55", 0
  %".57" = load i8*, i8** %"sjoin_out"
  %".58" = getelementptr i8, i8* %".57", i64 %".11"
  %".59" = select  i1 %".56", i8* %".58", i8* %".57"
  br i1 %".56", label %"sjoin_sep", label %"sjoin_item"
sjoin_cp_done:
  %".80" = call i8* @"rawstr_new_copy"(i8* %".48", i64 %".47")
  %".81" = call {i32, i8*}* @"rawstr_to_pystr"(i8* %".80")
  ret {i32, i8*}* %".81"
sjoin_sep:
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".57", i8* %".10", i64 %".11", i1 0)
  br label %"sjoin_item"
sjoin_item:
  %".63" = getelementptr {i32, i8*}*, {i32, i8*}** %".18", i64 %".55"
  %".64" = load {i32, i8*}*, {i32, i8*}** %".63"
  %".65" = getelementptr {i32, i8*}, {i32, i8*}* %".64", i32 0, i32 1
  %".66" = load i8*, i8** %".65"
  %".67" = bitcast i8* %".66" to {i32, i8*}*
  %".68" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 0
  %".69" = load i32, i32* %".68"
  %".70" = getelementptr {i32, i8*}, {i32, i8*}* %".67", i32 0, i32 1
  %".71" = load i8*, i8** %".70"
  %".72" = sext i32 %".69" to i64
  call void @"llvm.memcpy.p0i8.p0i8.i64"(i8* %".59", i8* %".71", i64 %".72", i1 0)
  %".74" = getelementptr i8, i8* %".59", i64 %".72"
  store i8* %".74", i8** %"sjoin_out"
  %".76" = load i64, i64* %"sjoin_cp_i"
  %".77" = add i64 %".76", 1
  store i64 %".77", i64* %"sjoin_cp_i"
  br label %"sjoin_cp_cond"
}

define {i32, i8*}* @"pyobj_pow"({i32, i8*}* %".1", {i32, i8*}* %".2")
{
entry:
  %".4" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".7" = load i32, i32* %".6"
  %".8" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 1
  %".9" = load i8*, i8** %".8"
  %".10" = bitcast i8* %".9" to double*
  %".11" = load double, double* %".10"
  %".12" = bitcast i8* %".9" to i64*
  %".13" = load i64, i64* %".12"
  %".14" = sitofp i64 %".13" to double
  %".15" = getelementptr {i32, i8*}, {i32, i8*}* %".1", i32 0, i32 0
  %".16" = load i32, i32* %".15"
  %".17" = icmp eq i32 %".16", 1
  %".18" = select  i1 %".17", double %".11", double %".14"
  %".19" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 1
  %".20" = load i8*, i8** %".19"
  %".21" = bitcast i8* %".20" to double*
  %".22" = load double, double* %".21"
  %".23" = bitcast i8* %".20" to i64*
  %".24" = load i64, i64* %".23"
  %".25" = sitofp i64 %".24" to double
  %".26" = getelementptr {i32, i8*}, {i32, i8*}* %".2", i32 0, i32 0
  %".27" = load i32, i32* %".26"
  %".28" = icmp eq i32 %".27", 1
  %".29" = select  i1 %".28", double %".22", double %".25"
  %".30" = call double @"pow"(double %".18", double %".29")
  %".31" = icmp eq i32 %".5", 0
  %".32" = icmp eq i32 %".5", 3
  %".33" = or i1 %".31", %".32"
  %".34" = icmp eq i32 %".7", 0
  %".35" = icmp eq i32 %".7", 3
  %".36" = or i1 %".34", %".35"
  %".37" = and i1 %".33", %".36"
  %".38" = fptosi double %".30" to i64
  %".39" = sitofp i64 %".38" to double
  %".40" = fcmp oeq double %".30", %".39"
  %".41" = and i1 %".37", %".40"
  %".42" = call {i32, i8*}* @"create_int"(i64 %".38")
  %".43" = call {i32, i8*}* @"create_float"(double %".30")
  %".44" = select  i1 %".41", {i32, i8*}* %".42", {i32, i8*}* %".43"
  ret {i32, i8*}* %".44"
}

