define i8* @"tagged_new_scalar"(i32 %".1", i64 %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 16)
  %".5" = bitcast i8* %".4" to {i32, i64}*
  %".6" = getelementptr {i32, i64}, {i32, i64}* %".5", i32 0, i32 0
  store i32 %".1", i32* %".6"
  %".8" = getelementptr {i32, i64}, {i32, i64}* %".5", i32 0, i32 1
  store i64 %".2", i64* %".8"
  %".10" = bitcast {i32, i64}* %".5" to i8*
  ret i8* %".10"
}

define i8* @"tagged_new_ptr"(i32 %".1", i8* %".2")
{
entry:
  %".4" = call i8* @"malloc"(i64 16)
  %".5" = bitcast i8* %".4" to {i32, i64}*
  %".6" = getelementptr {i32, i64}, {i32, i64}* %".5", i32 0, i32 0
  store i32 %".1", i32* %".6"
  %".8" = ptrtoint i8* %".2" to i64
  %".9" = getelementptr {i32, i64}, {i32, i64}* %".5", i32 0, i32 1
  store i64 %".8", i64* %".9"
  %".11" = bitcast {i32, i64}* %".5" to i8*
  ret i8* %".11"
}

define i32 @"tagged_tag"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  ret i32 %".5"
}

define i64 @"tagged_bits"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".5" = load i64, i64* %".4"
  ret i64 %".5"
}

define i8* @"tagged_ptr"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".5" = load i64, i64* %".4"
  %".6" = inttoptr i64 %".5" to i8*
  ret i8* %".6"
}

define void @"tagged_free"(i8* %".1", i32 %".2", i32 %".3", i32 %".4")
{
entry:
  %".6" = ptrtoint i8* %".1" to i64
  %".7" = icmp eq i64 %".6", 0
  br i1 %".7", label %"drop_block", label %"chk_str"
chk_str:
  %".9" = bitcast i8* %".1" to {i32, i64}*
  %".10" = getelementptr {i32, i64}, {i32, i64}* %".9", i32 0, i32 0
  %".11" = load i32, i32* %".10"
  %".12" = getelementptr {i32, i64}, {i32, i64}* %".9", i32 0, i32 1
  %".13" = load i64, i64* %".12"
  %".14" = inttoptr i64 %".13" to i8*
  %".15" = icmp eq i32 %".11", %".2"
  br i1 %".15", label %"drop_str", label %"chk_list"
chk_list:
  %".17" = icmp eq i32 %".11", %".3"
  br i1 %".17", label %"drop_list", label %"chk_dict"
drop_str:
  call void @"rawstr_free"(i8* %".14")
  br label %"drop_block"
drop_list:
  call void @"tagged_list_free"(i8* %".14", i32 %".2", i32 %".3", i32 %".4")
  br label %"drop_block"
drop_dict:
  call void @"tagged_dict_free"(i8* %".14", i32 %".2", i32 %".3", i32 %".4")
  br label %"drop_block"
drop_block:
  call void @"free"(i8* %".1")
  ret void
chk_dict:
  %".19" = icmp eq i32 %".11", %".4"
  br i1 %".19", label %"drop_dict", label %"drop_block"
}

define void @"tagged_list_free"(i8* %".1", i32 %".2", i32 %".3", i32 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i8*}*
  %".7" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 2
  %".8" = load i8*, i8** %".7"
  %".9" = getelementptr {i64, i64, i8*}, {i64, i64, i8*}* %".6", i32 0, i32 0
  %".10" = load i64, i64* %".9"
  %"tl_i" = alloca i64
  store i64 0, i64* %"tl_i"
  br label %"cond"
cond:
  %".13" = load i64, i64* %"tl_i"
  %".14" = icmp slt i64 %".13", %".10"
  br i1 %".14", label %"body", label %"done"
body:
  %".16" = bitcast i8* %".8" to i64*
  %".17" = getelementptr i64, i64* %".16", i64 %".13"
  %".18" = load i64, i64* %".17"
  %".19" = icmp ne i64 %".18", 0
  br i1 %".19", label %"free_el", label %"skip"
skip:
  %".24" = add i64 %".13", 1
  store i64 %".24", i64* %"tl_i"
  br label %"cond"
free_el:
  %".21" = inttoptr i64 %".18" to i8*
  call void @"tagged_free"(i8* %".21", i32 %".2", i32 %".3", i32 %".4")
  br label %"skip"
done:
  call void @"free"(i8* %".8")
  call void @"free"(i8* %".1")
  ret void
}

define void @"tagged_dict_free"(i8* %".1", i32 %".2", i32 %".3", i32 %".4")
{
entry:
  %".6" = bitcast i8* %".1" to {i64, i64, i64, i64, i64*, i64*, i64*}*
  %".7" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".6", i32 0, i32 1
  %".8" = load i64, i64* %".7"
  %".9" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".6", i32 0, i32 5
  %".10" = load i64*, i64** %".9"
  %".11" = getelementptr {i64, i64, i64, i64, i64*, i64*, i64*}, {i64, i64, i64, i64, i64*, i64*, i64*}* %".6", i32 0, i32 6
  %".12" = load i64*, i64** %".11"
  %"td_i" = alloca i64
  store i64 0, i64* %"td_i"
  br label %"cond"
cond:
  %".15" = load i64, i64* %"td_i"
  %".16" = icmp slt i64 %".15", %".8"
  br i1 %".16", label %"body", label %"done"
body:
  %".18" = getelementptr i64, i64* %".10", i64 %".15"
  %".19" = load i64, i64* %".18"
  %".20" = getelementptr i64, i64* %".12", i64 %".15"
  %".21" = load i64, i64* %".20"
  %".22" = icmp ne i64 %".19", 0
  br i1 %".22", label %"free_entry", label %"skip"
skip:
  %".29" = add i64 %".15", 1
  store i64 %".29", i64* %"td_i"
  br label %"cond"
free_entry:
  %".24" = inttoptr i64 %".19" to i8*
  call void @"rawstr_free"(i8* %".24")
  %".26" = inttoptr i64 %".21" to i8*
  call void @"tagged_free"(i8* %".26", i32 %".2", i32 %".3", i32 %".4")
  br label %"skip"
done:
  %".32" = bitcast i64* %".10" to i8*
  call void @"free"(i8* %".32")
  %".34" = bitcast i64* %".12" to i8*
  call void @"free"(i8* %".34")
  call void @"free"(i8* %".1")
  ret void
}

@"str.TypeError_3a_20wrong_20Json_20member" = constant [29 x i8] c"TypeError: wrong Json member\00"
define i64 @"json_unwrap_int"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 1
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  ret i64 %".12"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}

define double @"json_unwrap_float"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 2
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  %".13" = bitcast i64 %".12" to double
  ret double %".13"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}

define i1 @"json_unwrap_bool"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 3
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  %".13" = trunc i64 %".12" to i1
  ret i1 %".13"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}

define i8* @"json_unwrap_str"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 4
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  %".13" = inttoptr i64 %".12" to i8*
  ret i8* %".13"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}

define i8* @"json_unwrap_list"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 5
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  %".13" = inttoptr i64 %".12" to i8*
  ret i8* %".13"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}

define i8* @"json_unwrap_dict"(i8* %".1")
{
entry:
  %".3" = bitcast i8* %".1" to {i32, i64}*
  %".4" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 0
  %".5" = load i32, i32* %".4"
  %".6" = icmp eq i32 %".5", 6
  br i1 %".6", label %"ok", label %"bad"
ok:
  %".11" = getelementptr {i32, i64}, {i32, i64}* %".3", i32 0, i32 1
  %".12" = load i64, i64* %".11"
  %".13" = inttoptr i64 %".12" to i8*
  ret i8* %".13"
bad:
  %".8" = getelementptr [29 x i8], [29 x i8]* @"str.TypeError_3a_20wrong_20Json_20member", i32 0, i32 0
  call void @"silu_panic"(i8* %".8")
  unreachable
}
