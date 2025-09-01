from pycparser import c_parser, c_ast


class CToSimpleIR(c_ast.NodeVisitor):
    def __init__(self, record_types=False):
        self.record_types = record_types

    # ---------------- Module ----------------
    def visit_FileAST(self, node):
        return [self.visit(ext) for ext in node.ext]

    # ---------------- Function ----------------
    def visit_FuncDef(self, node):
        name = node.decl.name
        params = []
        param_types = []
        if node.decl.type.args:
            for p in node.decl.type.args.params:
                params.append(p.name)
                if self.record_types:
                    param_types.append(self.visit(p.type))
        else:
            param_types = None

        # 返回类型
        if self.record_types:
            return_type = self.visit(node.decl.type.type)
        else:
            return_type = None

        body = (
            [self.visit(stmt) for stmt in node.body.block_items]
            if node.body.block_items
            else []
        )
        return ("func_def", name, params, body, param_types, return_type)

    # ---------------- Return ----------------
    def visit_Return(self, node):
        return ("return", self.visit(node.expr) if node.expr else None)

    # ---------------- Assignments ----------------
    def visit_Decl(self, node):
        # 处理局部变量声明
        name = node.name
        typ = self.visit(node.type) if self.record_types else None
        value = self.visit(node.init) if node.init else None
        return ("assign", name, value, typ)

    def visit_Assignment(self, node):
        lval = self.visit(node.lvalue)
        rval = self.visit(node.rvalue)
        op_map = {"=": "=", "+=": "+=", "-=": "-=", "*=": "*=", "/=": "/=", "%=": "%="}
        op = op_map[node.op]
        return ("aug_assign" if op != "=" else "assign", lval, rval, None)

    # ---------------- Control Flow ----------------
    def visit_If(self, node):
        cond = self.visit(node.cond)
        then_block = [self.visit(stmt) for stmt in node.iftrue] if node.iftrue else []
        else_block = [self.visit(stmt) for stmt in node.iffalse] if node.iffalse else []
        return ("if", cond, then_block, else_block)

    def visit_While(self, node):
        cond = self.visit(node.cond)
        body = (
            [self.visit(stmt) for stmt in node.stmt.block_items]
            if node.stmt.block_items
            else []
        )
        return ("while", cond, body)

    def visit_For(self, node):
        # C 风格 for-loop: for(init; cond; next) body
        init = self.visit(node.init) if node.init else None
        cond = self.visit(node.cond) if node.cond else None
        next_ = self.visit(node.next) if node.next else None
        body = (
            [self.visit(stmt) for stmt in node.stmt.block_items]
            if node.stmt.block_items
            else []
        )
        return ("for", init, cond, next_, body)

    # ---------------- Expressions ----------------
    def visit_BinaryOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        return [node.op, left, right]

    def visit_UnaryOp(self, node):
        operand = self.visit(node.expr)
        return [node.op, operand]

    def visit_ID(self, node):
        return node.name

    def visit_Constant(self, node):
        if node.type == "int":
            return int(node.value)
        elif node.type == "float":
            return float(node.value)
        elif node.type == "char":
            return node.value
        else:
            return node.value

    def visit_FuncCall(self, node):
        func = self.visit(node.name)
        args = [self.visit(a) for a in node.args.exprs] if node.args else []
        return ("func_call", func, args, {})

    def visit_DeclList(self, node):
        return [self.visit(decl) for decl in node.decls]

    # ---------------- Type Handling ----------------
    def visit_TypeDecl(self, node):
        # 返回类型名字符串
        if isinstance(node.type, c_ast.IdentifierType):
            return " ".join(node.type.names)
        else:
            return self.visit(node.type)

    def visit_PtrDecl(self, node):
        base = self.visit(node.type)
        return f"{base}*"

    # ---------------- Generic ----------------
    def generic_visit(self, node):
        return f"<{type(node).__name__}>"


# ---------------- Example ----------------
if __name__ == "__main__":
    code = """
    int add(int a, int b) {
        int c = a + b;
        return c;
    }
    """

    parser = c_parser.CParser()
    ast = parser.parse(code)

    converter = CToSimpleIR(record_types=True)
    ir = converter.visit(ast)
    from pprint import pprint

    pprint(ir)
