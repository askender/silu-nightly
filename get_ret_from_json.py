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
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    raw_code_file = json_file_path.replace('.sym.json', '')
    testcases_file = json_file_path.replace('.sym.json', '.cases.jsonl')
    testcases_file_handler = open(testcases_file, "w")
    lang = None
    if raw_code_file.endswith('.c'):
        lang = 'c'
    elif raw_code_file.endswith('.py'):
        lang = 'python'
    assert lang
    raw_code = open(raw_code_file, 'r', encoding='utf-8').read()

    raw_code = raw_code.replace("#include <stdio.h>", "")
    raw_code = raw_code.replace("#include <stdbool.h>", "")
    raw_code = raw_code.replace("#include <math.h>", "")
    raw_code = raw_code.replace("#include <stdint.h>", '#include "stdint.h"')

    raw_h_code = None
    raw_h_file = raw_code_file[:-2]+'.h'
    if os.path.isfile(raw_h_file):
        raw_h_code = open(raw_h_file, 'r', encoding='utf-8').read()

        raw_h_code = raw_h_code.replace("#include <stdio.h>", "")
        raw_h_code = raw_h_code.replace("#include <stdbool.h>", "")
        raw_h_code = raw_h_code.replace("#include <math.h>", "")
        raw_h_code = raw_h_code.replace("#include <stdint.h>", '#include "stdint.h"')

    function_analyses = data['function_analyses']

    for func_name, func_info in function_analyses.items():
        print(f"\n📋 函数: {func_name}")
        paths = func_info['paths']
        case = None
        for path in paths:
            main_code = []
            l_var = []
            # print("-" * 50)
            # print(f"路径: {path}")
            return_type = path['return_type']
            assert return_type is not None, f"Return type {_return_type} is not valid"

            test_inputs = path['test_inputs']
            # variables = path['variables']
            variable_types = path['variable_types']
            for k, t in variable_types.items():
                v = test_inputs[k]
                assign = f'{t} {k} = {v};'
                # print(f"assign: {assign}")
                main_code.append(assign)
                l_var.append(k)
            l_var = ', '.join(l_var)

            prefix = 'void main(){'
            _return_type = return_type
            # if return_type.startswith('struct_'):
            #     _return_type = return_type[7:]

            if isinstance(return_type, dict):
                _return_type = return_type['name']
                # struct_def = f'struct {return_type["name"]} {{\n'
                # for field in return_type['fields']:
                #     struct_def += f'    {field["type"]} {field["name"]};\n'
                # struct_def += '};\n'

            output_type = None
            if return_type == 'int':
                output_type = 'int'
                prefix = 'int main(){'
            # print(prefix)

            main_code.append(prefix)
            assert _return_type is not None, f"Return type {_return_type} is not valid"
            exec_code = f'  {_return_type} ret = {func_name}({l_var});'
            # print(exec_code)
            main_code.append(exec_code)

            # if return_type == 'int':
            #     print_code = f'  printf("%d", ret);'
            # else:
            #     print_code = f'  printf("%s", ret);'

            # if return_type.startswith('struct_'):
            if isinstance(return_type, dict):
                assert return_type['kind'] == 'struct'
                output_type = 'struct'
                print_code = ''
                # print_code += f'\n  printf("ret.status = %d\\n", ret.status);'
                # print_code += f'\n  printf("ret.VehSpdabs = %d\\n", ret.VehSpdabs);'
                return_fields = return_type['fields']
                for name,atype in return_fields:
                    print_code += f'\n  printf("ret.{name} = %d\\n", ret.{name});'
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

            merged_code_file = 'gen_merged_code.c'
            with open(merged_code_file, 'w') as f:
                if raw_h_code:
                    f.write(raw_h_code+'\n')
                f.write(raw_code+'\n'+c_code)

            cmd = [
                "clang",
                "-E",
                "-Imystdint",
                "-I./.venv/lib/python3.13/site-packages/pycparser/utils/fake_libc_include",
                merged_code_file,
            ]
            # print(' '.join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True, env=env)
            assert result.returncode == 0, f"[Error1] cpp failed on {raw_code_file} with return code {result.returncode}"
            c_code = result.stdout
            if os.path.exists(merged_code_file):
                os.remove(merged_code_file)


            c_ir = generate_ir_from_c_code(c_code)
            assert c_ir, f"[Error] c_ir is empty"
            c_ir = json.dumps(c_ir, indent=2, default=str)
            # ret = execute_ir_from_string(c_ir)
            captured_output, ret = capture_print(execute_ir_from_string, c_ir)
            if ret is None:
                ret = captured_output

            # print(ret)
            return_value = path['return_value']

            if isinstance(return_value, int):
                if return_value == ret:
                    # print('ok 1')
                    pass
                else:
                    # pass
                    raise ValueError(f"Expected int: {ret} but got {return_value}")
            elif return_value in test_inputs:
                return_value = test_inputs[return_value]
                assert return_value == ret, f"Expected {return_value} but got {ret}"
                # print('ok 2')
                # continue
            else:
                assert return_value.startswith('struct_')

            # path['output'] = ret
            # print(data)

            case = {}
            case["case_type"] = "type3"
            case["func_name"] = func_name

            param = []
            init = []
            for k, atype in variable_types.items():
                v = test_inputs[k]
                param.append(k)
                init.append(f"{atype} {k} = {v};")

            param = ", ".join(param)
            init = "\n".join(init)
            case["param"] = param
            case["init"] = init
            case["output"] = ret
            case["output_type"] = output_type
            if output_type == 'struct':
                case["output_name"] = return_type['name']
                case["output_fields"] = return_type['fields']
            # print(case)
            testcases_file_handler.write(json.dumps(case) + "\n")
        print(f'case example: {case}')
    print(f'testcases_file generated ok: {testcases_file}')

def main():
    if len(sys.argv) != 2:
        print("Usage: python get_ret_from_json.py <json_file_path>")
        sys.exit(1)

    json_file_path = sys.argv[1]
    result = get_ret_from_json(json_file_path)
    # print(result)

if __name__ == "__main__":
    main()
