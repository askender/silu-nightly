# 1. 使用python生成mlir
python learn_run_mlir4.py

# 2. 优化并转换为 LLVM IR
mlir-opt square_printf_llvm.mlir \
  --convert-func-to-llvm \
  --convert-arith-to-llvm \
  --reconcile-unrealized-casts \
  | mlir-translate --mlir-to-llvmir > square_minimal.ll

# 3. 编译为可执行文件
clang square_minimal.ll -o square_minimal

# 4. 运行
./square_minimal  # 输出: 25
