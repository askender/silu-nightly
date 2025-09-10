import json
import sys

f = "zcase1.json"
f = sys.argv[1]



fout = f.replace(".json", "_case1.jsonl")
print(fout)
fout = open(fout, "w")

d = json.loads(open(f).read())
# ['PS_VC_CarMode_DecideNewMode']
d = d["function_analyses"]

func_name, func_info = next(iter(d.items()))

for j in func_info["paths"]:
    case = {}
    case["case_type"] = "type3"
    case["func_name"] = func_name
    # param output case_name group_name
    param = []
    init = []
    # variable_raw_types
    # for k, v in j["test_inputs"].items():
    for k, atype in j["variable_types"].items():
        v = j["test_inputs"][k]
        param.append(k)
        init.append(f"{atype} {k} = {v};")
    param = ", ".join(param)
    init = "\n".join(init)
    case["param"] = param
    case["init"] = init
    print(case)
    fout.write(json.dumps(case) + "\n")
