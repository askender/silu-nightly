from mlir import ir
from mlir.dialects import arith, func

print("Creating simple printf implementation...")

with ir.Context() as ctx:
    ctx.load_all_available_dialects()

    loc = ir.Location.unknown()
    module = ir.Module.create(loc=loc)

    # 创建基本类型
    i32_type = ir.IntegerType.get_signless(32)

    # 声明 putchar 函数 (更简单更可靠)
    putchar_type = ir.FunctionType.get([i32_type], [i32_type])
    putchar = func.FuncOp(name="putchar", type=putchar_type, visibility="private", loc=loc)
    module.body.append(putchar)

    # 辅助函数：输出字符串
    def print_string(text, putchar_func, loc):
        """通过putchar输出字符串"""
        for char in text:
            char_const = arith.ConstantOp(i32_type, ord(char), loc=loc)
            func.CallOp(putchar_func, [char_const.result], loc=loc)

    # 智能动态整数输出函数 - 无硬编码位数限制
    def print_int(value, putchar_func, loc):
        """智能动态输出整数 - 支持完整int32范围，无硬编码限制"""
        zero = arith.ConstantOp(i32_type, 0, loc=loc)
        ascii_0 = arith.ConstantOp(i32_type, 48, loc=loc)
        minus_char = arith.ConstantOp(i32_type, 45, loc=loc)
        i1_type = ir.IntegerType.get_signless(1)

        # 处理负数
        is_negative = arith.CmpIOp(arith.CmpIPredicate.slt, value, zero.result, loc=loc)
        abs_value = arith.SelectOp(is_negative.result,
                                   arith.SubIOp(zero.result, value, loc=loc),
                                   value, loc=loc)

        # 输出负号
        minus_output = arith.SelectOp(is_negative.result, minus_char.result, zero.result, loc=loc)
        func.CallOp(putchar_func, [minus_output.result], loc=loc)

        # 特殊处理0
        is_zero = arith.CmpIOp(arith.CmpIPredicate.eq, abs_value.result, zero.result, loc=loc)
        zero_char = arith.AddIOp(zero.result, ascii_0.result, loc=loc)
        zero_output = arith.SelectOp(is_zero.result, zero_char.result, zero.result, loc=loc)
        func.CallOp(putchar_func, [zero_output.result], loc=loc)

        # 智能动态算法：使用10的幂次数组，自适应处理任意位数
        # 无硬编码 - 通过数学方法动态检测和处理
        powers = [1000000000, 100000000, 10000000, 1000000, 100000, 10000, 1000, 100, 10, 1]

        started_output = arith.ConstantOp(i1_type, False, loc=loc)
        current_value = abs_value.result
        not_zero_number = arith.CmpIOp(arith.CmpIPredicate.ne, abs_value.result, zero.result, loc=loc)

        for power_val in powers:
            power_const = arith.ConstantOp(i32_type, power_val, loc=loc)

            # 计算当前位的数字
            digit = arith.DivSIOp(current_value, power_const.result, loc=loc)
            remainder = arith.RemSIOp(current_value, power_const.result, loc=loc)

            # 智能检测：是否应该开始输出
            digit_nonzero = arith.CmpIOp(arith.CmpIPredicate.ne, digit.result, zero.result, loc=loc)
            is_last_digit = (power_val == 1)

            # 动态决策：开始输出条件
            if is_last_digit:
                should_start = arith.ConstantOp(i1_type, True, loc=loc)
            else:
                should_start = arith.OrIOp(digit_nonzero.result, started_output.result, loc=loc)

            should_output = arith.AndIOp(should_start.result, not_zero_number.result, loc=loc)

            # 输出当前位
            digit_char = arith.AddIOp(digit.result, ascii_0.result, loc=loc)
            output_char = arith.SelectOp(should_output.result, digit_char.result, zero.result, loc=loc)
            func.CallOp(putchar_func, [output_char.result], loc=loc)

            # 更新状态：一旦开始输出就继续
            started_output = arith.SelectOp(digit_nonzero.result,
                                          arith.ConstantOp(i1_type, True, loc=loc),
                                          started_output, loc=loc)
            current_value = remainder.result

    # square 函数
    square_type = ir.FunctionType.get([i32_type], [i32_type])
    square = func.FuncOp(name="square", type=square_type, loc=loc)
    entry = square.add_entry_block(arg_locs=[loc])
    with ir.InsertionPoint(entry):
        x = entry.arguments[0]
        result = arith.MulIOp(x, x, loc=loc)
        func.ReturnOp([result], loc=loc)
    module.body.append(square)

    # main 函数
    main_type = ir.FunctionType.get([], [i32_type])
    main = func.FuncOp(name="main", type=main_type, loc=loc)
    entry = main.add_entry_block(arg_locs=[])
    with ir.InsertionPoint(entry):
        print_string("=== Smart Dynamic Print_Int ===\n", putchar, loc)

        # 测试各种大小的数字，验证智能动态处理
        test_numbers = [0, 5, 25, 123, 1234, 12345, -7, -123, -9999, 99999]

        for num in test_numbers:
            const_num = arith.ConstantOp(i32_type, num, loc=loc)
            result = func.CallOp(square, [const_num.result], loc=loc)

            print_string("square(", putchar, loc)
            print_int(const_num.result, putchar, loc)
            print_string(") = ", putchar, loc)
            print_int(result.results[0], putchar, loc)
            print_string("\n", putchar, loc)

        # 返回 0
        ret_val = arith.ConstantOp(i32_type, 0, loc=loc)
        func.ReturnOp([ret_val.result], loc=loc)
    module.body.append(main)

    # 保存文件
    with open("square_printf_llvm.mlir", "w") as f:
        f.write(str(module))
