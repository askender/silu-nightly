from mlir import ir
from mlir.dialects import arith, func, builtin, llvm
from mlir.passmanager import PassManager

print("MLIR Python bindings found, generating MLIR...")

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

    # ===== 2. 使用 putchar 函数输出数字 =====
    putchar_type = ir.FunctionType.get([ir.IntegerType.get_signless(32)], [ir.IntegerType.get_signless(32)])
    putchar_func = func.FuncOp(name="putchar", type=putchar_type, loc=loc, visibility="private")
    module.body.append(putchar_func)

    # ===== 3. 定义 main 函数 =====
    main_type = ir.FunctionType.get([], [ir.IntegerType.get_signless(32)])
    main_func = func.FuncOp(name="main", type=main_type, loc=loc)
    main_block = main_func.add_entry_block(arg_locs=[])
    with ir.InsertionPoint(main_block):
        # 调用 square(5)
        const5 = arith.ConstantOp(ir.IntegerType.get_signless(32), 5, loc=loc)
        result = func.CallOp(square, [const5.result], loc=loc)

        # 输出数字25：需要输出 '2' 然后 '5'
        # 对于25，我们需要分别输出十位数和个位数

        # 获取十位数：25 / 10 = 2
        ten = arith.ConstantOp(ir.IntegerType.get_signless(32), 10, loc=loc)
        tens_digit = arith.DivSIOp(result.results[0], ten.result, loc=loc)

        # 获取个位数：25 % 10 = 5
        ones_digit = arith.RemSIOp(result.results[0], ten.result, loc=loc)

        # 转换为ASCII字符：加上48 ('0'的ASCII值)
        ascii_offset = arith.ConstantOp(ir.IntegerType.get_signless(32), 48, loc=loc)
        tens_char = arith.AddIOp(tens_digit.result, ascii_offset.result, loc=loc)
        ones_char = arith.AddIOp(ones_digit.result, ascii_offset.result, loc=loc)

        # 输出十位数字符
        func.CallOp(putchar_func, [tens_char.result], loc=loc)

        # 输出个位数字符
        func.CallOp(putchar_func, [ones_char.result], loc=loc)

        # 输出换行符
        newline = arith.ConstantOp(ir.IntegerType.get_signless(32), 10, loc=loc)
        func.CallOp(putchar_func, [newline.result], loc=loc)

        # 返回0表示成功
        return_val = arith.ConstantOp(ir.IntegerType.get_signless(32), 0, loc=loc)
        func.ReturnOp([return_val.result], loc=loc)
    module.body.append(main_func)

    # ===== 4. 保存 MLIR =====
    mlir_path = "square_with_main.mlir"
    with open(mlir_path, "w") as f_mlir:
        f_mlir.write(str(module))

    print(f"Fixed MLIR module saved to {mlir_path}")
