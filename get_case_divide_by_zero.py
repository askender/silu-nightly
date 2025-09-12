import json
import sys

f = sys.argv[1]


d = json.loads(open(f).read())


function_analyses = d['function_analyses']

for func_name, func_info in function_analyses.items():
    for path in func_info['paths']:
        conditions = path['conditions']
        division_by_zero_conditions = path['division_by_zero_conditions']
        variables = path['variables']
        variable_types = path['variable_types']
        for cond in division_by_zero_conditions:
            all_conds = conditions.copy()
            all_conds.append(f"{cond} = 0")
            print('\n'.join(all_conds))
            print('====')
