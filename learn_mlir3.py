from mlir import ir
from mlir.dialects import arith, func, builtin
from mlir.passmanager import PassManager


with ir.Context() as ctx:
    loc = ir.Location.unknown()
    module = ir.Module.create(loc=loc)

    # ===== 1. 定义 square 函数 =====
    f_type = ir.FunctionType.get([ir.IntegerType.get_signless(32)],
                                 [ir.IntegerType.get_signless(32)])
    square = func.FuncOp(name="square", type=f_type, loc=loc)
    entry_block = square.add_entry_block(arg_locs=[loc])
    with ir.InsertionPoint(entry_block):
        x = entry_block.arguments[0]
        y = arith.MulIOp(x, x, loc=loc)
        func.ReturnOp([y], loc=loc)
    module.body.append(square)

    # 声明 printf
    printf_type = ir.FunctionType.get([ir.IntegerType.get_signless(32)], [ir.IntegerType.get_signless(32)])
    printf_func = func.FuncOp(name="printf", type=printf_type, loc=loc)
    module.body.append(printf_func)

    # ===== 2. 定义 main 函数 =====
    main_type = ir.FunctionType.get([], [ir.IntegerType.get_signless(32)])
    main_func = func.FuncOp(name="main", type=main_type, loc=loc)
    main_block = main_func.add_entry_block(arg_locs=[])
    with ir.InsertionPoint(main_block):
        # 调用 square(5)
        const5 = arith.ConstantOp(ir.IntegerType.get_signless(32), 5, loc=loc)
        result = func.CallOp(square, [const5.result], loc=loc)
        func.CallOp(printf_func, [result.results[0]], loc=loc)  # 调用 printf
        # 返回 result
        func.ReturnOp([result.results[0]], loc=loc)
    module.body.append(main_func)

    # ===== 3. 保存 MLIR =====
    mlir_path = "square_with_main.mlir"
    with open(mlir_path, "w") as f_mlir:
        f_mlir.write(str(module))

    print(f"MLIR module saved to {mlir_path}")
