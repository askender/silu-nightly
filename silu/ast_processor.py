"""
Abstract Base Class for AST Processing

This module provides a common base class for both interpretation and IR generation,
extracting shared AST traversal logic while allowing customization of processing behavior.
"""

import ast
from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseASTProcessor(ast.NodeVisitor, ABC):
    """
    Abstract base class for AST processing.

    This class provides common AST traversal logic and defines abstract methods
    that subclasses must implement to customize processing behavior.
    """

    # Consolidated operators mapping
    OPERATORS = {
        # Binary operators
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
        # Unary operators
        ast.UAdd: "+",
        ast.USub: "-",
        ast.Not: "not",
        # Comparison operators
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
        # Boolean operators
        ast.And: "and",
        ast.Or: "or",
    }

    # ================== Abstract Methods ==================

    @abstractmethod
    def process_assign(self, target: str, value: Any) -> Any:
        """Process an assignment operation."""
        pass

    @abstractmethod
    def process_name(self, name: str, context: ast.AST) -> Any:
        """Process a name/variable reference."""
        pass

    @abstractmethod
    def process_constant(self, value: Any) -> Any:
        """Process a constant value."""
        pass

    @abstractmethod
    def process_operation(self, op: str, *operands) -> Any:
        """Process any operation (binary, unary, boolean, comparison)."""
        pass

    @abstractmethod
    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Any:
        """Process a function call."""
        pass

    @abstractmethod
    def process_control_flow(self, node_type: str, **kwargs) -> Any:
        """Process control flow statements (if, while, for, return, function def)."""
        pass

    @abstractmethod
    def process_container(self, container_type: str, elements: List[Any]) -> Any:
        """Process containers (list, tuple, etc.)."""
        pass

    @abstractmethod
    def process_expr(self, value: Any) -> Any:
        """Process an expression statement."""
        pass

    # ================== Generic Visit Methods ==================

    def visit_Module(self, node: ast.Module) -> Any:
        """Visit a module node."""
        statements = [self.visit(stmt) for stmt in node.body]
        return self.process_container("module", statements)

    def visit_Expr(self, node: ast.Expr) -> Any:
        """Visit an expression statement."""
        return self.process_expr(self.visit(node.value))

    def visit_Assign(self, node: ast.Assign) -> Any:
        """Visit an assignment node."""
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            raise NotImplementedError(
                "Only single simple variable assignments supported"
            )

        target = node.targets[0].id
        value = self.visit(node.value)
        return self.process_assign(target, value)

    def visit_Name(self, node: ast.Name) -> Any:
        """Visit a name node."""
        return self.process_name(node.id, node.ctx)

    def visit_Constant(self, node: ast.Constant) -> Any:
        """Visit a constant node."""
        return self.process_constant(node.value)

    # ================== Operation Handlers ==================

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        """Visit a binary operation node."""
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = self._get_operator(node.op)
        return self.process_operation(op, left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """Visit a unary operation node."""
        operand = self.visit(node.operand)
        op = self._get_operator(node.op)
        return self.process_operation(op, operand)

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """Visit a boolean operation node."""
        values = [self.visit(value) for value in node.values]
        op = self._get_operator(node.op)
        return self.process_operation(op, *values)

    def visit_Compare(self, node: ast.Compare) -> Any:
        """Visit a comparison node."""
        left = self.visit(node.left)
        comparators = [self.visit(comp) for comp in node.comparators]
        ops = [self._get_operator(op) for op in node.ops]
        return self.process_operation("compare", left, ops, comparators)

    def visit_Call(self, node: ast.Call) -> Any:
        """Visit a function call node."""
        func = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        keywords = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        return self.process_call(func, args, keywords)

    # ================== Control Flow Handlers ==================

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Visit a function definition node."""
        args = [arg.arg for arg in node.args.args]
        body = node.body
        return self.process_control_flow(
            "function_def", name=node.name, args=args, body=body
        )

    def visit_Return(self, node: ast.Return) -> Any:
        """Visit a return statement node."""
        value = self.visit(node.value) if node.value else None
        return self.process_control_flow("return", value=value)

    def visit_If(self, node: ast.If) -> Any:
        """Visit an if statement node."""
        test = self.visit(node.test)
        body = node.body
        orelse = node.orelse if node.orelse else []
        return self.process_control_flow("if", test=test, body=body, orelse=orelse)

    def visit_While(self, node: ast.While) -> Any:
        """Visit a while loop node."""
        test_node = node.test
        body = node.body
        return self.process_control_flow("while", test_node=test_node, body=body)

    def visit_For(self, node: ast.For) -> Any:
        """Visit a for loop node."""
        target = self.visit(node.target)
        iter_ = self.visit(node.iter)
        body = node.body
        orelse = node.orelse if node.orelse else []
        return self.process_control_flow("for", target=target, iter=iter_, body=body, orelse=orelse)

    def visit_List(self, node: ast.List) -> Any:
        """Visit a list literal node."""
        elements = [self.visit(element) for element in node.elts]
        return self.process_container("list", elements)

    # ================== Helper Methods ==================

    def _get_operator(self, op: ast.AST) -> str:
        """Get the string representation of an operator."""
        op_str = self.OPERATORS.get(type(op))
        if op_str is None:
            raise NotImplementedError(f"Unsupported operator: {type(op).__name__}")
        return op_str


def create_processor(processor_type: str, **kwargs) -> BaseASTProcessor:
    """Factory function to create AST processors."""
    if processor_type == "interpreter":
        from .interpreter import SiluInterpreter

        return SiluInterpreter(**kwargs)
    elif processor_type == "ir_generator":
        from .ir_generator import SiluIRGenerator

        return SiluIRGenerator(**kwargs)
    else:
        raise ValueError(f"Unsupported processor type: {processor_type}")


def process_code(
    source_code: str, processor_type: str = "interpreter", **kwargs
) -> Any:
    """Process source code using the specified processor type."""
    tree = ast.parse(source_code)
    processor = create_processor(processor_type, **kwargs)
    return processor.visit(tree)
