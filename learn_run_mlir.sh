# 1. 使用python生成mlir
python learn_mlir4.py

# 2. 优化并转换为 LLVM IR
mlir-opt square_with_main.mlir \
  -convert-arith-to-llvm \
  -convert-func-to-llvm \
  -convert-cf-to-llvm \
  -reconcile-unrealized-casts \
  | mlir-translate --mlir-to-llvmir > square_with_main.ll

# 3. 编译为可执行文件
clang square_with_main.ll -o square_with_main

# 4. 运行
./square_with_main  # 输出: 25
