declare i8* @malloc(i64)
declare i32 @printf(i8*, ...)

define {i32, i64}* @tagged_new_scalar(i32 %tag, i64 %bits) {
entry:
  %m = call i8* @malloc(i64 16)
  %b = bitcast i8* %m to {i32, i64}*
  %g1 = getelementptr {i32, i64}, {i32, i64}* %b, i32 0, i32 0
  store i32 %tag, i32* %g1
  %g2 = getelementptr {i32, i64}, {i32, i64}* %b, i32 0, i32 1
  store i64 %bits, i64* %g2
  ret {i32, i64}* %b
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
  %v = call {i32, i64}* @tagged_new_scalar(i32 3, i64 %i)
  %p = ptrtoint {i32, i64}* %v to i64
  %acc2 = add i64 %acc, %p
  %next = add i64 %i, 1
  br label %loop
out:
  %h = getelementptr [5 x i8], [5 x i8]* @fmt, i32 0, i32 0
  call i32 (i8*, ...) @printf(i8* %h, i64 %acc)
  ret i32 0
}
