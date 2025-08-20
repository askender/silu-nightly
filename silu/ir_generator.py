"""
Silu IR Generator Module - Simplified Implementation

This module provides a streamlined IR generator that extends BaseASTProcessor
to convert Silu programs into intermediate representation.
"""

import ast
from typing import Any, Dict, List, Tuple

from .ast_processor import BaseASTProcessor


class SiluIRGenerator(BaseASTProcessor):
    """Simplified Silu IR generator that converts AST to intermediate representation."""

    def __init__(self, record_types: bool = True):
        self.record_types = record_types

    # ================== Abstract Method Implementations ==================

    def process_assign(self, target: str, value: Any) -> Tuple[str, str, Any, None]:
        """Generate assignment IR node."""
        return ("assign", target, value, None)

    def process_subscript_assign(self, obj: Any, key: Any, value: Any) -> Tuple:
        """Generate subscript assignment IR node."""
        return ("subscript_assign", obj, key, value)

    def process_name(self, name: str, context: ast.AST) -> Tuple[str, str]:
        """Return identifier with type information for IR."""
        return ("name", name)

    def process_constant(self, value: Any) -> Tuple[str, Any]:
        """Return constant value with type information for IR."""
        return ("const", value)

    def process_operation(self, op: str, *operands) -> Tuple:
        """Generate operation IR nodes."""
        if len(operands) == 1:  # Unary
            return (op, operands[0])
        elif len(operands) == 2:  # Binary
            return (op, operands[0], operands[1])
        elif op == "compare":  # Comparison
            left, ops, comparators = operands
            if len(ops) == 1 and len(comparators) == 1:
                return (ops[0], left, comparators[0])
            else:
                # Chained comparisons
                comparisons = []
                current_left = left
                for op_str, comp in zip(ops, comparators):
                    comparisons.append((op_str, current_left, comp))
                    current_left = comp
                return ("chained_compare", tuple(comparisons))
        else:  # Boolean operation
            return tuple([op] + list(operands))

    def process_call(
        self, func: Any, args: List[Any], keywords: Dict[str, Any]
    ) -> Tuple:
        """Generate function call IR node."""
        # Convert to tuples for consistent IR format
        args_tuple = tuple(args)
        keywords_tuple = tuple(keywords.items()) if keywords else ()
        return ("call", func, args_tuple, keywords_tuple)

    def process_control_flow(self, node_type: str, **kwargs) -> Tuple:
        """Generate control flow IR nodes."""
        if node_type == "function_def":
            # Process function body statements
            body = tuple(self.visit(stmt) for stmt in kwargs["body"])
            return (
                "func_def",
                kwargs["name"],
                tuple(kwargs["args"]),
                body,
            )
        elif node_type == "return":
            return ("return", kwargs["value"])
        elif node_type == "if":
            # Process if statement body and orelse
            body = tuple(self.visit(stmt) for stmt in kwargs["body"])
            orelse = (
                tuple(self.visit(stmt) for stmt in kwargs["orelse"])
                if kwargs["orelse"]
                else ()
            )
            return ("if", kwargs["test"], body, orelse)
        elif node_type == "while":
            # Process test_node ourselves for IR generation
            test = self.visit(kwargs["test_node"])
            body = tuple(self.visit(stmt) for stmt in kwargs["body"])
            return ("while", test, body)
        elif node_type == "for":
            body = tuple(self.visit(stmt) for stmt in kwargs["body"])
            orelse = (
                tuple(self.visit(stmt) for stmt in kwargs["orelse"])
                if kwargs["orelse"]
                else ()
            )
            return ("for", kwargs["target"], kwargs["iter"], body, orelse)

    def process_container(self, container_type: str, elements: List[Any]) -> Tuple:
        """Generate container IR nodes."""
        if container_type == "list":
            return ("list", tuple(elements))
        elif container_type == "tuple":
            return self._make_node("tuple", tuple(elements))
        elif container_type == "dict":
            return self._make_node("dict", tuple(elements))
        elif container_type == "module":
            return ("module", tuple(elements))

    def process_expr(self, value: Any) -> Any:
        """Process expression statements."""
        return value

    def process_attribute(self, obj: Any, attr: str) -> str:
        """Process attribute access."""
        return f"{obj}.{attr}"

    def process_subscript(self, obj: Any, index: Any) -> Tuple:
        """Process subscript operation."""
        return self._make_node("subscript", obj, index)

    def process_break_continue(self, statement_type: str) -> Tuple:
        """Process break/continue statements."""
        return (statement_type,)

    def process_assert(self, test: Any, msg: Any = None) -> Tuple:
        """Process assert statements."""
        return self._make_node("assert", test, msg)

    def process_ann_assign(self, target: str, value: Any, annotation: Any) -> Tuple:
        """Process annotated assignment."""
        return self._make_node("ann_assign", target, value, annotation)

    def process_lambda(self, params: List[str], body_node: ast.AST) -> Tuple:
        """Process lambda function."""
        body = self.visit(body_node)
        return self._make_node("lambda", tuple(params), body)

    # ================== Additional IR Generation Methods ==================

    def visit_AugAssign(self, node: ast.AugAssign) -> Tuple:
        """Generate augmented assignment IR."""
        target = self.visit(node.target)
        op = self.OPERATORS.get(type(node.op), "?")
        value = self.visit(node.value)
        return self._make_node("aug_assign", target, f"{op}=", value)

    def visit_Slice(self, node: ast.Slice) -> Tuple:
        """Generate slice IR."""
        lower = self.visit(node.lower) if node.lower else None
        upper = self.visit(node.upper) if node.upper else None
        step = self.visit(node.step) if node.step else None
        return self._make_node("slice", lower, upper, step)

    def visit_Set(self, node: ast.Set) -> Tuple:
        """Generate set IR."""
        elements = tuple(self.visit(e) for e in node.elts)
        return self._make_node("set", elements)

    # ================== Control Flow Extensions ==================

    def visit_Pass(self, node: ast.Pass) -> Tuple:
        """Generate pass statement IR."""
        return ("pass",)

    # ================== Comprehensions ==================

    def _visit_comprehension(self, comp_type: str, node) -> Tuple:
        """Generic comprehension visitor."""
        if comp_type == "list":
            elt = self.visit(node.elt)
        elif comp_type == "set":
            elt = self.visit(node.elt)
        elif comp_type == "dict":
            key = self.visit(node.key)
            value = self.visit(node.value)
            elt = (key, value)

        generators = []
        for gen in node.generators:
            target = self.visit(gen.target)
            iter_val = self.visit(gen.iter)
            ifs = tuple(self.visit(cond) for cond in gen.ifs)
            generators.append((target, iter_val, ifs))

        return self._make_node(f"{comp_type}_comp", elt, tuple(generators))

    def visit_ListComp(self, node: ast.ListComp) -> Tuple:
        """Generate list comprehension IR."""
        return self._visit_comprehension("list", node)

    def visit_SetComp(self, node: ast.SetComp) -> Tuple:
        """Generate set comprehension IR."""
        return self._visit_comprehension("set", node)

    def visit_DictComp(self, node: ast.DictComp) -> Tuple:
        """Generate dictionary comprehension IR."""
        return self._visit_comprehension("dict", node)

    # ================== Advanced Features ==================

    def visit_IfExp(self, node: ast.IfExp) -> Tuple:
        """Generate conditional expression IR."""
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return self._make_node("if_expr", test, body, orelse)

    def visit_Starred(self, node: ast.Starred) -> Tuple:
        """Generate starred expression IR."""
        value = self.visit(node.value)
        return self._make_node("starred", value)

    def visit_Yield(self, node: ast.Yield) -> Tuple:
        """Generate yield expression IR."""
        value = self.visit(node.value) if node.value else None
        return self._make_node("yield", value)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> Tuple:
        """Generate yield from expression IR."""
        value = self.visit(node.value)
        return self._make_node("yield_from", value)

    # ================== Exception Handling ==================

    def visit_Try(self, node: ast.Try) -> Tuple:
        """Generate try-except IR."""
        body = tuple(self.visit(stmt) for stmt in node.body)
        handlers = tuple(self.visit(h) for h in node.handlers)
        orelse = tuple(self.visit(stmt) for stmt in node.orelse) if node.orelse else ()
        finalbody = (
            tuple(self.visit(stmt) for stmt in node.finalbody) if node.finalbody else ()
        )
        return self._make_node("try", body, handlers, orelse, finalbody)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Tuple:
        """Generate exception handler IR."""
        exc_type = self.visit(node.type) if node.type else None
        name = node.name if node.name else None
        body = tuple(self.visit(stmt) for stmt in node.body)
        return self._make_node("except", exc_type, name, body)

    def visit_Raise(self, node: ast.Raise) -> Tuple:
        """Generate raise statement IR."""
        exc = self.visit(node.exc) if node.exc else None
        return self._make_node("raise", exc)

    # ================== Import Statements ==================

    def visit_Import(self, node: ast.Import) -> Tuple:
        """Generate import statement IR."""
        names = [(alias.name, alias.asname) for alias in node.names]
        return self._make_node("import", tuple(names))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Tuple:
        """Generate from-import statement IR."""
        module = node.module
        names = [(alias.name, alias.asname) for alias in node.names]
        level = node.level
        return self._make_node("from_import", module, tuple(names), level)

    # ================== Context Managers ==================

    def visit_With(self, node: ast.With) -> Tuple:
        """Generate with statement IR."""
        items = []
        for item in node.items:
            context_expr = self.visit(item.context_expr)
            optional_vars = (
                self.visit(item.optional_vars) if item.optional_vars else None
            )
            items.append((context_expr, optional_vars))
        body = tuple(self.visit(stmt) for stmt in node.body)
        return self._make_node("with", tuple(items), body)

    # ================== Error Handling ==================

    def generic_visit(self, node: ast.AST) -> None:
        """Handle unsupported AST nodes."""
        raise NotImplementedError(
            f"Unsupported syntax for IR generation: {type(node).__name__}"
        )
