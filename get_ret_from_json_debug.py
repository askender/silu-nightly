import sys
import json

from ir_generator_for_c import generate_ir_from_c_code
from silu.ir_interpreter import execute_ir_from_string



import os
import subprocess
# 继承当前环境
env = os.environ.copy()



def get_ret_from_json(raw_code_file):
    raw_code = open(raw_code_file, 'r').read()

    cmd = [
        "clang",
        "-E",
        "-Imystdint",
        "-I./.venv/lib/python3.13/site-packages/pycparser/utils/fake_libc_include",
        raw_code_file,
    ]
    # print(' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)

    if result.returncode != 0:
        # TODO
        print(
            f"[Error1] cpp failed on {raw_code_file} with return code {result.returncode}"
        )
        print(f"stderr output:\n{result.stderr}")
        return

    c_code = result.stdout
    with open(f'{raw_code_file}.i', 'w') as f:
        f.write(c_code)


    c_ir = generate_ir_from_c_code(c_code+'\n')
    c_ir = json.dumps(c_ir, indent=2, default=str)
    print(c_ir)

def main():
    if len(sys.argv) != 2:
        print("Usage: python get_ret_from_json.py <raw_code_file>")
        sys.exit(1)

    raw_code_file = sys.argv[1]
    result = get_ret_from_json(raw_code_file)
    # print(result)

if __name__ == "__main__":
    main()
