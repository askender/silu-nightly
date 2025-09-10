import json
import sys

f = "zcase1.json"
f = sys.argv[1]

lang = "c"
if len(sys.argv)>2:
    lang = sys.argv[2]

fout = f.replace(".json", "_case1.jsonl")
print(f"fout: {fout}")

fout = open(fout, "w")

d = json.loads(open(f).read())
# ['PS_VC_CarMode_DecideNewMode']
d = d["function_analyses"]
# TODO: 目前一个json只测试一个函数，后续覆盖多个函数
func_name, func_info = next(iter(d.items()))


if lang == "c":
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
elif lang.lower() in "py python".split():
    for j in func_info["paths"]:
        case = {}
        # case["case_type"] = "" # 未定义
        case["func_name"] = func_name
        # param output case_name group_name
        param_names = []
        params = []
        for k, atype in j["variable_types"].items():
            v = j["test_inputs"].get(k, 0)
            param_names.append(k)
            params.append(v)

        param_names = ", ".join(param_names)
        case["param_names"] = param_names
        case["params"] = params
        if 'return_value' in j and j['return_value'] is not None:
            case['output'] = j['return_value']
        print(case)
        fout.write(json.dumps(case) + "\n")
