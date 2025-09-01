"""
64 文件 cpp预处理错误
6 pycparse 报错，不属于c89/c99标准
150 完全解析
"""

import os
from ir_generator_for_c import generate_ir_from_c_file

# 162
# void foos(int x[static 5]);

# 129 210 213
"""
#define s s
int
main(void)
{
#undef s
	goto s;

typedef union Unaligned16a {
  uint16_t u;
  uint8_t b[2];
} __attribute__((packed)) Unaligned16a;

       ({
	int i = 1;
	while (1)
	  while (i--)
	    some_label:
	      printf("error\n");
	goto some_label;
	})
"""

# 40 cpp err
l_int = "40 129 137 141 162 210 213".split(" ")
l_int = [int(j) for j in l_int]

for i in range(1, 221):
    # make 0 to 00001
    i_str = f"{i:05d}"
    f = f"aokc/{i_str}.c"
    if not os.path.isfile(f):
        print(f"File {f} not exists")

    input_file = f
    no_types = False

    # Generate IR
    print(f"Generating IR from {input_file}...")
    try:
        ir = generate_ir_from_c_file(input_file, record_types=not no_types)
        # if ir:
        #     print('ookk')
    except Exception as e:
        print(f"Error generating IR from {input_file}: {e}")
        raise

    # Save IR
    # print(f"Saving IR to {output_file}...")
    # save_ir_to_file(ir, output_file, format)
    # print(f"IR generation complete. Output saved to {output_file}")

    # Print summary
    # print(f"\nIR Summary:")
    # print(f"  Format: {format}")
    # print(f"  Type info: {'No' if no_types else 'Yes'}")
