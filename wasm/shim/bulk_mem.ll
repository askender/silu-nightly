;; bulk_mem.ll - wasm64 bulk-memory implementations of memcpy/memmove/memset
;; for the shim: the C byte-loop versions cap every runtime string copy at
;; ~60MB/s (the wasm64 module's 1.9GB tokenize copy cost ~30s), while
;; memory.copy/memory.fill are the VM's native block ops.  memory.copy is
;; defined to behave like memmove (overlap-safe), so memcpy/memmove share
;; one body.  Compiled by clang from IR text (no llc needed) and linked
;; before shim_libc.o, which no longer defines these symbols.
target triple = "wasm64-unknown-unknown"

declare void @llvm.wasm.memory.copy(ptr, ptr, i64, i32)
declare void @llvm.wasm.memory.fill(ptr, i8, i64, i32)

define ptr @memcpy(ptr %d, ptr %s, i64 %n) #0 {
entry:
  call void @llvm.wasm.memory.copy(ptr %d, ptr %s, i64 %n, i32 0)
  ret ptr %d
}

define ptr @memmove(ptr %d, ptr %s, i64 %n) #0 {
entry:
  call void @llvm.wasm.memory.copy(ptr %d, ptr %s, i64 %n, i32 0)
  ret ptr %d
}

define ptr @memset(ptr %d, i32 %c, i64 %n) #0 {
entry:
  %b = trunc i32 %c to i8
  call void @llvm.wasm.memory.fill(ptr %d, i8 %b, i64 %n, i32 0)
  ret ptr %d
}

attributes #0 = { "target-features"="+bulk-memory" }
