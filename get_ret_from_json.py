import sys
import json

from ir_generator_for_c import generate_ir_from_c_code
from silu.ir_interpreter import execute_ir_from_string


import os
import subprocess


import io
from contextlib import redirect_stdout


env = os.environ.copy()


def capture_print(func, *args, **kwargs):
    """
    运行func并捕获其中的print输出，返回(print输出的字符串, func的返回值)
    """
    buffer = io.StringIO()
    # redirect_stdout 可以安全地临时重定向print输出
    with redirect_stdout(buffer):
        result = func(*args, **kwargs)
    output = buffer.getvalue()
    return output, result

def get_ret_from_json(json_file_path):
    with open(json_file_path, 'r') as f:
        data = json.load(f)

    raw_code_file = json_file_path.replace('.ir.json.ret.json', '.c')
    raw_code = open(raw_code_file, 'r').read()

    # new_d = {}
    function_analyses = data['function_analyses']

    for func_name, func_info in function_analyses.items():
        # new_d[func_name] = {}
        # new_d[func_name]['paths'] = []
        print(f"\n📋 函数: {func_name}")
        paths = func_info['paths']
        for path in paths:
            main_code = []
            l_var = []
            print("-" * 50)
            # print(f"路径: {path}")
            return_type = path['return_type']
            test_inputs = path['test_inputs']
            # variables = path['variables']
            variable_types = path['variable_types']
            for k, v in test_inputs.items():
                t = variable_types[k]
                assign = f'{t} {k} = {v};'
                # print(assign)
                main_code.append(assign)
                l_var.append(k)
            l_var = ', '.join(l_var)

            prefix = 'void main(){'
            _return_type = return_type
            if return_type.startswith('struct_'):
                _return_type = return_type[7:]

            if return_type == 'int':
                prefix = 'int main(){'
            # print(prefix)

            main_code.append(prefix)
            exec_code = f'  {_return_type} ret = {func_name}({l_var});'
            # print(exec_code)
            main_code.append(exec_code)

            # if return_type == 'int':
            #     print_code = f'  printf("%d", ret);'
            # else:
            #     print_code = f'  printf("%s", ret);'
            #
            if return_type.startswith('struct_'):
                print_code = ''
                print_code += f'\n  printf("ret.status = %d\\n", ret.status);'
                print_code += f'\n  printf("ret.VehSpdabs = %d\\n", ret.VehSpdabs);'
                main_code.append(print_code)

            # print(print_code)

            # main_code.append('printf("hello\\n");')
            if return_type == 'int':
                # main_code.append('  return 2;')
                main_code.append('  return ret;')
            # print('}')
            main_code.append('}')

            c_code = '\n'.join(main_code)

            raw_code = raw_code.replace('../mystdint/', '')
            raw_code = raw_code.replace("#include <stdio.h>", "")

            raw_code_file = 'raw_code.c'
            with open(raw_code_file, 'w') as f:
                f.write(raw_code+'\n'+c_code)

            cmd = [
                "clang",
                "-E",
                "-Imystdint",
                "-I./.venv/lib/python3.13/site-packages/pycparser/utils/fake_libc_include",
                raw_code_file,
            ]
            # print(' '.join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            assert result.returncode == 0, f"[Error1] cpp failed on {raw_code_file} with return code {result.returncode}"
            c_code = result.stdout

            c_ir = generate_ir_from_c_code(c_code)
            c_ir = json.dumps(c_ir, indent=2, default=str)
            # print(c_ir)
            # ret = execute_ir_from_string(c_ir)
            captured_output, ret = capture_print(execute_ir_from_string, c_ir)
            if ret is None:
                ret = captured_output

            # print(ret)
            return_value = path['return_value']
            if return_value == ret:
                # print('ok 1')
                continue
            if return_value in test_inputs:
                return_value = test_inputs[return_value]
                assert return_value == ret, f"Expected {return_value} but got {ret}"
                # print('ok 2')
                continue
            assert return_value.startswith('struct_')
            path['output'] = ret

            print(data)

def main():
    if len(sys.argv) != 2:
        print("Usage: python get_ret_from_json.py <json_file_path>")
        sys.exit(1)

    json_file_path = sys.argv[1]
    result = get_ret_from_json(json_file_path)
    # print(result)

if __name__ == "__main__":
    main()
