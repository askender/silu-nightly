import sys
import ast
import json
import pprint


class PyToSimpleIR(ast.NodeVisitor):
    def __init__(self, record_types=True):
        self.record_types = record_types  # 控制是否记录类型信息

    # ---------------- Module & Statements ----------------
    def visit_Module(self, node):
        return tuple([self.visit(stmt) for stmt in node.body])

    def visit_Expr(self, node):
        return self.visit(node.value)

    # ---------------- Function ----------------
    def visit_FunctionDef(self, node):
        name = node.name
        params = [arg.arg for arg in node.args.args]
        params = tuple(params)

        if self.record_types:
            param_types = [
                self.visit(arg.annotation) if arg.annotation else None
                for arg in node.args.args
            ]
            param_types = tuple(param_types)
            if node.returns is None:
                return_type = None  # 无返回注解
            elif isinstance(node.returns, ast.Constant) and node.returns.value is None:
                return_type = "annotated_None"  # 明确注解为 None
            else:
                return_type = self.visit(node.returns)
        else:
            param_types = None
            return_type = None

        body = [self.visit(stmt) for stmt in node.body]
        body = tuple(body)
        return ("func_def", name, params, body, param_types, return_type)

    # ---------------- Class ----------------
    def visit_ClassDef(self, node):
        name = node.name
        bases = [self.visit(base) for base in node.bases] if node.bases else []
        body = [self.visit(stmt) for stmt in node.body]
        decorators = (
            [self.visit(d) for d in node.decorator_list] if node.decorator_list else []
        )
        return ("class_def", name, bases, body, decorators)

    # ---------------- Return ----------------
    def visit_Return(self, node):
        return ("return", self.visit(node.value) if node.value else None)

    # ---------------- Assignments ----------------
    def visit_Assign(self, node):
        if len(node.targets) == 1:
            target = self.visit(node.targets[0])
            value = self.visit(node.value)
            return ("assign", target, value, None)
        else:
            targets = [self.visit(t) for t in node.targets]
            value = self.visit(node.value)
            return ("multi_assign", targets, value, None)

    def visit_AnnAssign(self, node):
        target = self.visit(node.target)
        value = self.visit(node.value) if node.value else None
        typ = self.visit(node.annotation)
        return ("assign", target, value, typ)

    def visit_AugAssign(self, node):
        target = self.visit(node.target)
        op_map = {ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*=", ast.Div: "/="}
        op = op_map[type(node.op)]
        value = self.visit(node.value)
        return ("aug_assign", target, op, value)

    # ---------------- Control Flow ----------------
    def visit_If(self, node):
        cond = self.visit(node.test)
        then_block = [self.visit(stmt) for stmt in node.body]
        else_block = [self.visit(stmt) for stmt in node.orelse] if node.orelse else []
        return ("if", cond, then_block, else_block)

    def visit_While(self, node):
        cond = self.visit(node.test)
        body = [self.visit(stmt) for stmt in node.body]
        return ("while", cond, body)

    def visit_For(self, node):
        target = self.visit(node.target)
        iter_ = self.visit(node.iter)
        body = [self.visit(stmt) for stmt in node.body]
        return ("for", target, iter_, body)

    def visit_Break(self, node):
        return ("break",)

    def visit_Continue(self, node):
        return ("continue",)

    # ---------------- Expressions ----------------
    def visit_Call(self, node):
        func = self.visit(node.func)  # 可以是 Name, Attribute, Subscript, Call 等
        args = [self.visit(arg) for arg in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        return ("func_call", func, args, kwargs)

    def visit_BinOp(self, node):
        op_map = {
            ast.Add: "+",
            ast.Sub: "-",
            ast.Mult: "*",
            ast.Div: "/",
            ast.FloorDiv: "//",
            ast.Mod: "%",
            ast.Pow: "**",
            ast.LShift: "<<",
            ast.RShift: ">>",
            ast.BitOr: "|",
            ast.BitAnd: "&",
            ast.BitXor: "^",
        }
        op = op_map[type(node.op)]
        left = self.visit(node.left)
        right = self.visit(node.right)
        return tuple([op, left, right])

    def visit_Compare(self, node):
        op_map = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.GtE: ">=",
            ast.Is: "is",
            ast.IsNot: "is not",
            ast.In: "in",
            ast.NotIn: "not in",
        }
        # 支持多重比较 a < b < c
        left = self.visit(node.left)
        comparisons = []
        for op_node, comp in zip(node.ops, node.comparators):
            op = op_map[type(op_node)]
            right = self.visit(comp)
            comparisons.append([op, left, right])
            left = right  # 下一个比较链条
        return comparisons if len(comparisons) > 1 else comparisons[0]

    def visit_BoolOp(self, node):
        op_map = {ast.And: "and", ast.Or: "or"}
        op = op_map[type(node.op)]
        values = [self.visit(v) for v in node.values]
        r = [op] + values
        return tuple(r)

    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.Not):
            return tuple(["not", self.visit(node.operand)])
        else:
            raise Exception(f"Unsupported unary op: {type(node.op).__name__}")

    def visit_Subscript(self, node):
        value = self.visit(node.value)
        slice_ = self.visit(node.slice)
        return ("subscript", value, slice_)

    def visit_Index(self, node):
        return self.visit(node.value)

    def visit_Slice(self, node):
        lower = self.visit(node.lower) if node.lower else None
        upper = self.visit(node.upper) if node.upper else None
        step = self.visit(node.step) if node.step else None
        return ("slice", lower, upper, step)

    def visit_List(self, node):
        return tuple([self.visit(elt) for elt in node.elts])

    def visit_Tuple(self, node):
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node):
        keys = [self.visit(k) for k in node.keys]
        values = [self.visit(v) for v in node.values]
        return ("dict", list(zip(keys, values)))

    def visit_Set(self, node):
        elements = [self.visit(e) for e in node.elts]
        return ("set", elements)

    def visit_Attribute(self, node):
        value = self.visit(node.value)
        return f"{value}.{node.attr}"

    def visit_Name(self, node):
        return node.id

    def visit_Constant(self, node):
        return node.value

    # ---------------- Exception Handling ----------------
    def visit_Try(self, node):
        body = [self.visit(stmt) for stmt in node.body]
        handlers = [self.visit(h) for h in node.handlers]
        orelse = [self.visit(stmt) for stmt in node.orelse] if node.orelse else []
        finalbody = (
            [self.visit(stmt) for stmt in node.finalbody] if node.finalbody else []
        )
        return ("try", body, handlers, orelse, finalbody)

    def visit_ExceptHandler(self, node):
        typ = self.visit(node.type) if node.type else None
        name = node.name if node.name else None
        body = [self.visit(stmt) for stmt in node.body]
        return ("except", typ, name, body)

    def visit_Raise(self, node):
        exc = self.visit(node.exc) if node.exc else None
        return ("raise", exc)

    # ---------------- Others ----------------
    def visit_Pass(self, node):
        return ("pass",)

    def visit_Ellipsis(self, node):
        return "..."

    def visit_Import(self, node):
        # node.names 是 alias 列表，每个 alias 有 name 和 asname
        names = [(alias.name, alias.asname) for alias in node.names]
        return ("import", names)

    def visit_ImportFrom(self, node):
        module = node.module  # 模块名
        names = [(alias.name, alias.asname) for alias in node.names]
        level = node.level  # 相对导入级别
        return ("from_import", module, names, level)

    def visit_ListComp(self, node):
        elt = self.visit(node.elt)
        generators = []
        for gen in node.generators:
            target = self.visit(gen.target)
            iter_ = self.visit(gen.iter)
            ifs = [self.visit(cond) for cond in gen.ifs]
            generators.append((target, iter_, ifs))
        return ("list_comp", elt, generators)

    def visit_SetComp(self, node):
        elt = self.visit(node.elt)
        generators = [
            (self.visit(g.target), self.visit(g.iter), [self.visit(c) for c in g.ifs])
            for g in node.generators
        ]
        return ("set_comp", elt, generators)

    def visit_DictComp(self, node):
        key = self.visit(node.key)
        value = self.visit(node.value)
        generators = [
            (self.visit(g.target), self.visit(g.iter), [self.visit(c) for c in g.ifs])
            for g in node.generators
        ]
        return ("dict_comp", key, value, generators)

    def visit_GeneratorExp(self, node):
        elt = self.visit(node.elt)
        generators = [
            (self.visit(g.target), self.visit(g.iter), [self.visit(c) for c in g.ifs])
            for g in node.generators
        ]
        return ("gen_exp", elt, generators)

    def visit_IfExp(self, node):
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return ("if_expr", test, body, orelse)

    def visit_JoinedStr(self, node):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(v.value)  # 字符串常量
            elif isinstance(v, ast.FormattedValue):
                val = self.visit(v.value)
                parts.append(("expr", val))
            else:
                raise Exception(f"Unsupported JoinedStr part: {type(v).__name__}")
        return ("fstring", parts)

    def visit_With(self, node):
        items = []
        for item in node.items:
            ctx = self.visit(item.context_expr)
            var = self.visit(item.optional_vars) if item.optional_vars else None
            items.append((ctx, var))
        body = [self.visit(stmt) for stmt in node.body]
        return ("with", items, body)

    def visit_Starred(self, node):
        value = self.visit(node.value)
        return ("starred", value)

    def visit_Lambda(self, node):
        params = [arg.arg for arg in node.args.args]
        params = tuple(params)
        body = self.visit(node.body)
        body = tuple(body)
        if self.record_types:
            param_types = [
                self.visit(arg.annotation) if arg.annotation else None
                for arg in node.args.args
            ]
            return_type = None  # Lambda 返回类型推断可选
            param_types = tuple(param_types)
        else:
            param_types = None
            return_type = None
        return ("lambda", params, body, param_types, return_type)

    def visit_Assert(self, node):
        test = self.visit(node.test)
        msg = self.visit(node.msg) if node.msg else None
        return ("assert", test, msg)

    # 可选异步支持
    def visit_AsyncFunctionDef(self, node):
        func_ir = self.visit_FunctionDef(node)  # 基本复用 FunctionDef
        return ("async_func_def",) + func_ir[1:]

    def visit_AsyncFor(self, node):
        target = self.visit(node.target)
        iter_ = self.visit(node.iter)
        body = [self.visit(stmt) for stmt in node.body]
        return ("async_for", target, iter_, body)

    def visit_AsyncWith(self, node):
        items = []
        for item in node.items:
            ctx = self.visit(item.context_expr)
            var = self.visit(item.optional_vars) if item.optional_vars else None
            items.append((ctx, var))
        body = [self.visit(stmt) for stmt in node.body]
        return ("async_with", items, body)

    def visit_Await(self, node):
        value = self.visit(node.value)
        return ("await", value)

    def visit_Yield(self, node):
        value = self.visit(node.value) if node.value else None
        return ("yield", value)

    def visit_YieldFrom(self, node):
        value = self.visit(node.value)
        return ("yield_from", value)

    # ---------------- Generic ----------------
    def generic_visit(self, node):
        raise Exception(f"Unsupported syntax: {type(node).__name__}")


# def fact(n):
#     if n == 0:
#         return 1
#     else:
#         return n * fact(n - 1)

# result = fact(5)
# print(result)
source_code = """
def add(a: int, b: int) -> int:
    c: int = a + b
    return c
"""


def test():
    # 用法示例
    tree = ast.parse(source_code)
    converter = PyToSimpleIR()
    program = converter.visit(tree)

    from pprint import pprint

    pprint(program)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        test()
    else:
        f = sys.argv[1]
        with open(f, "r") as file:
            source_code = file.read()

            tree = ast.parse(source_code)
            converter = PyToSimpleIR()
            program = converter.visit(tree)
            # print(program)
            print(json.dumps(program, indent=4))
            print(pprint.pprint(program))
