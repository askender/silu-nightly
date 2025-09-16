import json
import sys
from typing import Dict, List, Any, Optional
from silu.symbolic.z3_utils import check_path_satisfiability
debug = 0

def evaluate_expression_safely(expr: str, env: Dict[str, Any]) -> Optional[Any]:
    """安全地计算表达式的值"""
    try:
        # 创建一个安全的环境，只包含必要的运算符
        safe_env = {
            '__builtins__': {},
            'abs': abs,
            'min': min,
            'max': max,
            'pow': pow,
        }
        safe_env.update(env)
        # print(f"evaluating expression '{expr} env: {env}'")
        return eval(expr, safe_env)
    except ZeroDivisionError as e:
        # print(f"Error evaluating expression '{expr} env: {env}': {e}")
        return "ZeroDivisionError"
    except Exception as e:
        print(f"Error evaluating expression '{expr} env: {env}': {e}")
        return None

def generate_test_case(func_name: str, model_values: Dict[str, Any],
                      div_zero_expr: str, path_conditions: List[str]) -> str:
    """生成测试用例代码"""
    test_code = f"""
def test_{func_name}_division_by_zero():
    '''测试 {func_name} 函数的除零错误'''
    # 导致除零的参数值
    params = {model_values}

    # 路径条件: {path_conditions}
    # 除零表达式: {div_zero_expr} == 0

    try:
        result = {func_name}(**params)
        assert False, "应该抛出除零错误"
    except ZeroDivisionError:
        print(f"✓ 成功捕获除零错误，参数: {{params}}")
    except Exception as e:
        print(f"⚠ 捕获到其他错误: {{type(e).__name__}}: {{e}}")
"""
    return test_code.strip()

def solve_division_by_zero_cases(json_file_path: str) -> List[Dict]:
    """
    分析除零条件并使用Z3求解器找到具体的变量值
    """
    bug_cases = []
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    function_analyses = data['function_analyses']

    print("🔍 除零条件分析和测试用例生成")
    print("=" * 60)

    all_test_cases = []
    total_div_zero_cases = 0

    for func_name, func_info in function_analyses.items():
        print(f"\n📋 函数: {func_name}")
        print("-" * 50)

        func_div_zero_count = 0

        for path_idx, path in enumerate(func_info['paths']):
            conditions = path['conditions']
            division_by_zero_conditions = path['division_by_zero_conditions']
            variables = path['variables']
            variable_types = path['variable_types']

            if not division_by_zero_conditions:
                continue

            if debug:
                print(f"\n🛤️  路径 {path_idx + 1}:")
                if conditions:
                    print(f"   📝 路径条件: {conditions}")
                else:
                    print(f"   📝 路径条件: 无")
                    print(f"   ⚠️  除零条件: {division_by_zero_conditions}")

            # 为每个除零条件求解
            for div_idx, div_zero_cond in enumerate(division_by_zero_conditions):
                if debug:
                    print(f"\n   🔍 分析除零条件 #{div_idx + 1}: {div_zero_cond} == 0")

                # 构建完整的约束条件
                all_conditions = conditions.copy()
                all_conditions.append(f"({div_zero_cond}) == 0")

                if debug:
                    print(f"   📋 完整约束条件:")
                    for i, cond in enumerate(all_conditions):
                        print(f"      {i+1}. {cond}")

                # 准备变量环境
                var_env = {}
                try:
                    from z3 import Int, Bool

                    # 根据变量类型创建Z3变量
                    for var_name, var_type in variable_types.items():
                        if var_type == 'int':
                            var_env[var_name] = Int(var_name)
                        elif var_type == 'bool':
                            var_env[var_name] = Bool(var_name)
                        else:
                            var_env[var_name] = Int(var_name)  # 默认为整数

                    # 使用Z3求解器检查可满足性
                    is_satisfiable, model_values = check_path_satisfiability(
                        all_conditions, var_env
                    )

                    if is_satisfiable and model_values:
                        d = {}
                        d['func'] = func_name
                        d['vars'] = model_values
                        bug_cases.append(d)
                        if debug:
                            print(f"   ✅ 找到导致除零的变量值:")
                            for var_name, value in sorted(model_values.items()):
                                print(f"      {var_name} = {value}")

                        # 验证除零条件
                        div_result = evaluate_expression_safely(div_zero_cond, model_values)
                        if div_result is not None:
                            if div_result == 0 or div_result == "ZeroDivisionError":
                                if debug:
                                    print(f"   ✅ 验证成功: {div_zero_cond} = {div_result}")
                            else:
                                print(f"   ⚠️  验证异常: {div_zero_cond} = {div_result} (应该为0)")
                        else:
                            print(f"   ⚠️  无法验证表达式: {div_zero_cond}")

                        # 生成测试用例
                        test_case = generate_test_case(
                            func_name, model_values, div_zero_cond, conditions
                        )
                        all_test_cases.append(test_case)

                        func_div_zero_count += 1
                        total_div_zero_cases += 1

                    elif is_satisfiable:
                        print(f"   ⚠️  条件可满足，但未能提取具体值")
                    else:
                        print(f"   ❌ 条件不可满足（此除零情况不会发生）")

                except ImportError:
                    print(f"   ⚠️  Z3不可用，跳过求解")
                    print(f"   📋 原始条件组合:")
                    for cond in all_conditions:
                        print(f"      • {cond}")
                except Exception as e:
                    print(f"   ❌ 求解出错: {e}")
                    print(f"   📋 原始条件组合:")
                    for cond in all_conditions:
                        print(f"      • {cond}")

        alert = ''
        if func_div_zero_count > 0:
            alert = '⚠️⚠️⚠️'
        print(f"\n📊 函数 {func_name} 总计: {alert} {func_div_zero_count} 个可能的除零情况")
        if func_div_zero_count > 0:
            sys.exit(1)

    if debug:
        # 输出总结和测试用例
        print("\n" + "=" * 60)
        print(f"📊 总结: 发现 {total_div_zero_cases} 个可能导致除零错误的情况")

        if all_test_cases:
            print(f"\n🧪 生成的测试用例:")
            print("=" * 60)

            print("# 除零错误测试用例")
            print("# 自动生成的测试代码")
            print()

            for i, test_case in enumerate(all_test_cases):
                if i > 0:
                    print()
                print(test_case)

            print(f"\n# 总共生成了 {len(all_test_cases)} 个测试用例")

        print("\n" + "=" * 60)
    return bug_cases

def main():

    if len(sys.argv) != 2:
        print("🔧 用法: python get_case_divide_by_zero.py <json_file>")
        print("📝 示例: python get_case_divide_by_zero.py ucode_div_zero.py.ir.json.ret.json")
        print()
        print("📋 功能:")
        print("  • 分析符号执行结果中的除零条件")
        print("  • 使用Z3求解器找到导致除零的具体变量值")
        print("  • 生成可用于测试的Python代码")
        sys.exit(1)

    json_file = sys.argv[1]

    try:
        cases = solve_division_by_zero_cases(json_file)
        for case in cases:
            print(case)
    except FileNotFoundError:
        print(f"❌ 错误: 找不到文件 '{json_file}'")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ 错误: JSON文件格式不正确 - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
