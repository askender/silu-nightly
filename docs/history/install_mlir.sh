


mlir-opt square_with_main.mlir -canonicalize -cse > square_with_main_opt.mlir

mlir-opt square_with_main_opt.mlir \
  -convert-arith-to-llvm \
  -convert-func-to-llvm \
  -convert-cf-to-llvm \
  -reconcile-unrealized-casts \
  | mlir-translate --mlir-to-llvmir > square_with_main.ll


# 克隆 LLVM/MLIR 源码
git clone https://github.com/llvm/llvm-project.git
cd llvm-project

# 创建构建目录
mkdir build && cd build

# 配置 CMake，开启 MLIR、Python bindings
cmake -G Ninja ../llvm \
  -DLLVM_ENABLE_PROJECTS="mlir" \
  -DLLVM_TARGETS_TO_BUILD="host" \
  -DLLVM_ENABLE_BINDINGS=ON \
  -DMLIR_ENABLE_BINDINGS_PYTHON=ON \
  -DCMAKE_BUILD_TYPE=Release

# 编译 mlir-translate
ninja mlir-translate



cmake -G Ninja ../llvm \
  -DLLVM_ENABLE_PROJECTS="mlir" \
  -DLLVM_TARGETS_TO_BUILD="host" \
  -DLLVM_ENABLE_BINDINGS=ON \
  -DMLIR_ENABLE_BINDINGS_PYTHON=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=../install \
  -DPython3_EXECUTABLE=$(which python3) \
  -DMLIR_PYTHON_BINDINGS_INSTALL_PREFIX=$(python3 -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")

ninja

# if MLIR_PYTHON_BINDINGS_INSTALL_PREFIX is not set:

python3 -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"

VENV=$(python3 -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
echo $VENV

mkdir -p $VENV/mlir

cp -rL ./tools/mlir/python_packages/mlir_core/mlir/_mlir_libs  \
$VENV/mlir/

cp -rL /Users/askender/aix1/llvm-project/mlir/python/mlir/* \
$VENV/mlir/

cp -rL ./tools/mlir/python_packages/mlir_core/mlir/dialects \
      $VENV/mlir/




Registered dialects:
builtin
func
llvm

acc
arm_neon
arm_sme
arm_sve
dlti
gpu
nvvm
omp
rocdl
spirv
vcix
xevm

Arith
MemRef

| 方言        | 对应 CMake Target      | 用途                    |
| --------- | -------------------- | --------------------- |
| `Builtin` | `MLIRBuiltinDialect` | 所有 MLIR 模块必需，内建类型和操作  |
| `Func`    | `MLIRFuncDialect`    | 函数定义、调用、模块结构          |
| `Arith`   | `MLIRArithDialect`   | 算术操作，如 `addi`, `muli` |
| `MemRef`  | `MLIRMemRefDialect`  | 内存访问，多维数组操作           |
| `SCF`     | `MLIRSCFDialect`     | 控制流（for/while）        |
| `Vector`  | `MLIRVectorDialect`  | SIMD 矢量操作             |
| `LLVMIR`  | `MLIRLLVMDialect`    | LLVM IR 生成和 Lowering  |
| `Affine`  | `MLIRAffineDialect`  | 静态循环优化、内存访问模式分析       |

次优选择（根据目标添加）
Linalg → 数学、线性代数 ops，Tensor/MatMul 常用
Math → 高级数学函数，如 sin/cos/exp
Index → 标量索引类型操作
ControlFlow → 更底层的 control flow ops（部分情况下可替代 SCF）

Arith
MemRef
SCF
Vector
Affine
Linalg
Math
Index
ControlFlow


vim mlir/tools/mlir-translate/CMakeLists.txt

mlir/CMakeLists.txt
get_property(dialect_libs GLOBAL PROPERTY MLIR_DIALECT_LIBS)

# 手动追加通用方言
list(APPEND dialect_libs
  MLIRArithDialect
  MLIRMemRefDialect
  MLIRSCFDialect
  MLIRVectorDialect
  MLIRAffineDialect
  MLIRLinalgDialect
  MLIRMathDialect
  MLIRIndexDialect
  MLIRControlFlowDialect
)



Affine
AMDGPU
AMX
Arith
ArmNeon
ArmSME
ArmSVE
Async
Bufferization
CMakeLists.txt
Complex
ControlFlow
DLTI
EmitC
Func
GPU
Index
IRDL
Linalg
LLVMIR
Math
MemRef
MLProgram
MPI
NVGPU
OpenACC
OpenACCMPCommon
OpenMP
PDL
PDLInterp
Ptr
Quant
SCF
Shape
Shard
SMT
SparseTensor
SPIRV
Tensor
Tosa
Traits.cpp
Transform
UB
Utils
Vector
WasmSSA
X86Vector
XeGPU


  MLIRArithDialect
  MLIRMemRefDialect
  MLIRSCFDialect
  MLIRVectorDialect
  MLIRAffineDialect
  MLIRLinalgDialect
  MLIRMathDialect
  MLIRIndexDialect
  MLIRControlFlowDialect
