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

    # Binary operators mapping - shared across all processors
    BINARY_OPERATORS = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "//",
        ast.Mod: "%",
        ast.Pow: "**",
    }

    # Unary operators mapping
    UNARY_OPERATORS = {
        ast.UAdd: "+",
        ast.USub: "-",
        ast.Not: "not",
    }

    # Comparison operators mapping
    COMPARISON_OPERATORS = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }

    # Boolean operators mapping
    BOOLEAN_OPERATORS = {
        ast.And: "and",
        ast.Or: "or",
    }

    def __init__(self):
        super().__init__()

    # ================== Abstract Methods ==================

    @abstractmethod
    def process_module(self, statements: List[Any]) -> Any:
        """Process a module with its statements."""
        pass

    @abstractmethod
    def process_assign(self, target: Any, value: Any) -> Any:
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
    def process_binop(self, op: str, left: Any, right: Any) -> Any:
        """Process a binary operation."""
        pass

    @abstractmethod
    def process_unaryop(self, op: str, operand: Any) -> Any:
        """Process a unary operation."""
        pass

    @abstractmethod
    def process_boolop(self, op: str, values: List[Any]) -> Any:
        """Process a boolean operation."""
        pass

    @abstractmethod
    def process_compare(self, left: Any, ops: List[str], comparators: List[Any]) -> Any:
        """Process a comparison operation."""
        pass

    @abstractmethod
    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Any:
        """Process a function call."""
        pass

    @abstractmethod
    def process_functiondef(self, name: str, args: List[str], body: List[Any]) -> Any:
        """Process a function definition."""
        pass

    @abstractmethod
    def process_return(self, value: Any) -> Any:
        """Process a return statement."""
        pass

    @abstractmethod
    def process_if(self, test: Any, body: List[Any], orelse: List[Any]) -> Any:
        """Process an if statement."""
        pass

    @abstractmethod
    def process_while(self, test: Any, body: List[Any]) -> Any:
        """Process a while loop."""
        pass

    @abstractmethod
    def process_for(self, target: Any, iter_: Any, body: List[Any]) -> Any:
        """Process a for loop."""
        pass

    @abstractmethod
    def process_list(self, elements: List[Any]) -> Any:
        """Process a list literal."""
        pass

    @abstractmethod
    def process_expr(self, value: Any) -> Any:
        """Process an expression statement."""
        pass

    # ================== Concrete Visit Methods ==================

    def visit_Module(self, node: ast.Module) -> Any:
        """Visit a module node and delegate to process_module."""
        statements = [self.visit(stmt) for stmt in node.body]
        return self.process_module(statements)

    def visit_Expr(self, node: ast.Expr) -> Any:
        """Visit an expression statement."""
        value = self.visit(node.value)
        return self.process_expr(value)

    def visit_Assign(self, node: ast.Assign) -> Any:
        """Visit an assignment node."""
        # For simplicity, handle single target assignments only
        if len(node.targets) != 1:
            raise NotImplementedError("Only single target assignments are supported")

        target = node.targets[0]
        if not isinstance(target, ast.Name):
            raise NotImplementedError("Only simple variable assignments are supported")

        target_processed = self.visit(target)
        value_processed = self.visit(node.value)
        return self.process_assign(target_processed, value_processed)

    def visit_Name(self, node: ast.Name) -> Any:
        """Visit a name node."""
        return self.process_name(node.id, node.ctx)

    def visit_Constant(self, node: ast.Constant) -> Any:
        """Visit a constant node."""
        return self.process_constant(node.value)

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        """Visit a binary operation node."""
        left = self.visit(node.left)
        right = self.visit(node.right)

        if type(node.op) in self.BINARY_OPERATORS:
            op = self.BINARY_OPERATORS[type(node.op)]
            return self.process_binop(op, left, right)

        raise NotImplementedError(f"Unsupported binary operator: {type(node.op)}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """Visit a unary operation node."""
        operand = self.visit(node.operand)

        if type(node.op) in self.UNARY_OPERATORS:
            op = self.UNARY_OPERATORS[type(node.op)]
            return self.process_unaryop(op, operand)

        raise NotImplementedError(f"Unsupported unary operator: {type(node.op)}")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """Visit a boolean operation node."""
        values = [self.visit(value) for value in node.values]

        if type(node.op) in self.BOOLEAN_OPERATORS:
            op = self.BOOLEAN_OPERATORS[type(node.op)]
            return self.process_boolop(op, values)

        raise NotImplementedError(f"Unsupported boolean operator: {type(node.op)}")

    def visit_Compare(self, node: ast.Compare) -> Any:
        """Visit a comparison node."""
        left = self.visit(node.left)
        comparators = [self.visit(comp) for comp in node.comparators]

        ops = []
        for op in node.ops:
            if type(op) in self.COMPARISON_OPERATORS:
                ops.append(self.COMPARISON_OPERATORS[type(op)])
            else:
                raise NotImplementedError(
                    f"Unsupported comparison operator: {type(op)}"
                )

        return self.process_compare(left, ops, comparators)

    def visit_Call(self, node: ast.Call) -> Any:
        """Visit a function call node."""
        func = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        keywords = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        return self.process_call(func, args, keywords)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        """Visit a function definition node."""
        name = node.name
        args = [arg.arg for arg in node.args.args]
        body = [self.visit(stmt) for stmt in node.body]
        return self.process_functiondef(name, args, body)

    def visit_Return(self, node: ast.Return) -> Any:
        """Visit a return statement node."""
        value = self.visit(node.value) if node.value else None
        return self.process_return(value)

    def visit_If(self, node: ast.If) -> Any:
        """Visit an if statement node."""
        test = self.visit(node.test)
        body = [self.visit(stmt) for stmt in node.body]
        orelse = [self.visit(stmt) for stmt in node.orelse] if node.orelse else []
        return self.process_if(test, body, orelse)

    def visit_While(self, node: ast.While) -> Any:
        """Visit a while loop node."""
        test = self.visit(node.test)
        body = [self.visit(stmt) for stmt in node.body]
        return self.process_while(test, body)

    def visit_For(self, node: ast.For) -> Any:
        """Visit a for loop node."""
        target = self.visit(node.target)
        iter_ = self.visit(node.iter)
        body = [self.visit(stmt) for stmt in node.body]
        return self.process_for(target, iter_, body)

    def visit_List(self, node: ast.List) -> Any:
        """Visit a list literal node."""
        elements = [self.visit(element) for element in node.elts]
        return self.process_list(elements)

    # ================== Helper Methods ==================

    def get_operator_symbol(self, op_type: type, operator_dict: Dict[type, str]) -> str:
        """Get the string representation of an operator."""
        if op_type in operator_dict:
            return operator_dict[op_type]
        raise NotImplementedError(f"Unsupported operator: {op_type}")

    def is_supported_node(self, node: ast.AST) -> bool:
        """Check if a node type is supported by this processor."""
        method_name = f"visit_{type(node).__name__}"
        return hasattr(self, method_name)

    def validate_single_target_assignment(self, node: ast.Assign) -> None:
        """Validate that an assignment has a single simple target."""
        if len(node.targets) != 1:
            raise NotImplementedError("Only single target assignments are supported")

        target = node.targets[0]
        if not isinstance(target, ast.Name):
            raise NotImplementedError("Only simple variable assignments are supported")


class ProcessingMode:
    """Enumeration of different processing modes."""

    INTERPRET = "interpret"
    GENERATE_IR = "generate_ir"


class ProcessorFactory:
    """Factory class for creating AST processors."""

    @staticmethod
    def create_processor(mode: str, **kwargs) -> BaseASTProcessor:
        """Create an AST processor based on the specified mode."""
        if mode == ProcessingMode.INTERPRET:
            from .interpreter import SiluInterpreter

            return SiluInterpreter(**kwargs)
        elif mode == ProcessingMode.GENERATE_IR:
            from .ir_generator import SiluIRGenerator

            return SiluIRGenerator(**kwargs)
        else:
            raise ValueError(f"Unsupported processing mode: {mode}")


def process_ast(
    source_code: str, mode: str = ProcessingMode.INTERPRET, **kwargs
) -> Any:
    """
    Process source code using the specified mode.

    Args:
        source_code: The source code to process
        mode: Processing mode ("interpret" or "generate_ir")
        **kwargs: Additional arguments passed to the processor

    Returns:
        The result of processing (execution result or IR)
    """
    tree = ast.parse(source_code)
    processor = ProcessorFactory.create_processor(mode, **kwargs)
    return processor.visit(tree)
