declare i8* @malloc(i64)
declare i32 @printf(i8*, ...)

define {i32, i8*}* @create_int(i64 %v) {
entry:
  %box = call i8* @malloc(i64 16)
  %b = bitcast i8* %box to {i32, i8*}*
  %g1 = getelementptr {i32, i8*}, {i32, i8*}* %b, i32 0, i32 0
  store i32 0, i32* %g1
  %payload = call i8* @malloc(i64 8)
  %pb = bitcast i8* %payload to i64*
  store i64 %v, i64* %pb
  %g2 = getelementptr {i32, i8*}, {i32, i8*}* %b, i32 0, i32 1
  store i8* %payload, i8** %g2
  ret {i32, i8*}* %b
}

@fmt = private constant [5 x i8] c"%ld\0A\00"

define i32 @main() {
entry:
  br label %loop
loop:
  %i = phi i64 [0, %entry], [%next, %body]
  %acc = phi i64 [0, %entry], [%acc2, %body]
  %done = icmp sge i64 %i, 3000000
  br i1 %done, label %out, label %body
body:
  %v = call {i32, i8*}* @create_int(i64 %i)
  %p = ptrtoint {i32, i8*}* %v to i64
  %acc2 = add i64 %acc, %p
  %next = add i64 %i, 1
  br label %loop
out:
  %h = getelementptr [5 x i8], [5 x i8]* @fmt, i32 0, i32 0
  call i32 (i8*, ...) @printf(i8* %h, i64 %acc)
  ret i32 0
}
