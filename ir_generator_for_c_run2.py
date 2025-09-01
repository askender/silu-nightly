"""
64 文件 cpp预处理错误
6 pycparse 报错，不属于c89/c99标准
150 完全解析
结果一致 78 89 56 73 75 98
不一致 6
"""

import os
import io
import contextlib
from ir_generator_for_c import generate_ir_from_c_file
from silu.ir_interpreter import IRInterpreter
# execute_ir_from_string, _json_to_tuples


l_skip_char = """
static
goto
|
^
~
charfunc(99.0);
nest
struct T;
} s = {
struct S s = {
struct T { int x; } s1;
enum
S a[1] = {{1, {2, 3}}};
struct S2 { struct S1 s1; };
myint x = (myint)1;
if (s[3] !=
struct fred jones[2];
} while (
int b = 01234567;
LL
struct S arr[2]
int arr[][3][5]
p[0] -
s = "abc" "def";
void*
int a[] = {5, [2] = 2, 3};
sizeof(int)
(*(*p)
""".strip().split("\n")
# if (s[3] != '\0') out of range
# } while (     do while
# int b = 01234567;   8进制
# static 函数内部的static：副作用隐蔽、可读性差的设计
# charfunc(99.0); print("char: %c\n" % (99.1)): TypeError: %c requires int or char

n_all = 0
n_ir = 0
n_ok = 0
n_diff = 0
n_empty = 0
for i in range(1, 221):
    # make 0 to 00001
    i_str = f"{i:05d}"
    f = f"aokc/{i_str}.c"
    if not os.path.isfile(f):
        print(f"File {f} not exists")
        raise

    gold_result = None
    f_result = f"aokc/{i_str}.c.expected"
    if not os.path.isfile(f_result):
        print(f"File {f_result} not exists")
        raise
    gold_result = open(f_result).read()

    input_file = f
    # 暂时跳过指针和引用
    input_data = open(input_file).read()
    # if '*' in input_data:
    #     print('==== *')
    #     continue
    if "&" in input_data:
        # print('==== &')
        continue
    should_skip = False
    for achar in l_skip_char:
        if achar in input_data:
            # print(f'==== {achar}')
            should_skip = True
            break
    if should_skip:
        continue
    # continue

    print(f"input_file: {input_file}")
    n_all += 1
    no_types = False

    ir = None
    # Generate IR
    # print(f"Generating IR from {input_file}...")
    try:
        ir = generate_ir_from_c_file(input_file, record_types=not no_types)
        # if ir:
        #     print('ookk')
    except Exception:
        # print(f"Error generating IR from {input_file}: {e}")
        raise

    # Save IR
    # print(f"Saving IR to {output_file}...")
    # save_ir_to_file(ir, output_file, format)
    # print(f"IR generation complete. Output saved to {output_file}")

    # Print summary
    # print(f"\nIR Summary:")
    # print(f"  Format: {format}")
    # print(f"  Type info: {'No' if no_types else 'Yes'}")

    if not ir:
        continue

    ir_data = ir
    n_ir += 1
    # ir_data = _json_to_tuples(ir)

    try:
        # if 1:
        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout_capture),
            contextlib.redirect_stderr(stderr_capture),
        ):
            # execute_ir_from_string(ir)
            interpreter = IRInterpreter()
            output = interpreter.execute_program(ir_data)

        # print(f"input_file: {input_file}")
        my_result = stdout_capture.getvalue()
        if my_result == gold_result:
            n_ok += 1
        else:
            if my_result.strip():
                print(f"==== {input_file}")
                print(my_result)
                print("----")
                print(gold_result)
                n_diff += 1
            else:
                n_empty += 1
            # sys.exit(1)
            # raise Exception(f"Result mismatch: {my_result} != {gold_result}")
        # print(f"output: {output}")
    except Exception:
        # print(f"Error executing IR from {input_file}: {e}")
        continue

print("==")
print(n_all)
print(n_ir)
print(n_ok)
print(n_diff)
print(n_empty)
