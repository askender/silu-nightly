"""
Silu IR Generator Module - Based on BaseASTProcessor

This module provides an IR generator that extends BaseASTProcessor
to convert Silu programs into intermediate representation.
"""

import ast
from typing import Any, Dict, List, Optional, Tuple

from .ast_processor import BaseASTProcessor


class SiluIRGenerator(BaseASTProcessor):
    """A Silu IR generator that converts AST to intermediate representation."""

    def __init__(self, record_types: bool = True):
        super().__init__()
        self.record_types = record_types

    # ================== Implementation of Abstract Methods ==================

    def process_module(self, statements: List[Any]) -> Tuple[Any, ...]:
        """Process a module by returning tuple of all statements."""
        return tuple(statements)

    def process_assign(self, target: Any, value: Any) -> Tuple[str, Any, Any, None]:
        """Process an assignment by creating an assign IR node."""
        return ('assign', target, value, None)

    def process_name(self, name: str, context: ast.AST) -> str:
        """Process a name by returning the identifier string."""
        return name

    def process_constant(self, value: Any) -> Any:
        """Process a constant by returning its value."""
        return value

    def process_binop(self, op: str, left: Any, right: Any) -> Tuple[str, Any, Any]:
        """Process a binary operation by creating a binop IR node."""
        return (op, left, right)

    def process_unaryop(self, op: str, operand: Any) -> Tuple[str, Any]:
        """Process a unary operation by creating a unaryop IR node."""
        return (op, operand)

    def process_boolop(self, op: str, values: List[Any]) -> Tuple[str, ...]:
        """Process a boolean operation by creating a boolop IR node."""
        return tuple([op] + values)

    def process_compare(self, left: Any, ops: List[str], comparators: List[Any]) -> Any:
        """Process comparison operations, supporting chained comparisons."""
        if len(ops) == 1 and len(comparators) == 1:
            # Simple comparison
            return [ops[0], left, comparators[0]]
        else:
            # Chained comparisons: a < b < c
            comparisons = []
            current_left = left
            for op, comp in zip(ops, comparators):
                comparisons.append([op, current_left, comp])
                current_left = comp
            return comparisons

    def process_call(self, func: Any, args: List[Any], keywords: Dict[str, Any]) -> Tuple[str, Any, List[Any], Dict[str, Any]]:
        """Process a function call by creating a call IR node."""
        return ('func_call', func, args, keywords)

    def process_functiondef(self, name: str, args: List[str], body: List[Any]) -> Tuple[str, str, Tuple[str, ...], Tuple[Any, ...], Optional[Tuple], Optional[Any]]:
        """Process a function definition by creating a func_def IR node."""
        params = tuple(args)
        body_tuple = tuple(body)

        if self.record_types:
            # For now, we don't have type annotation info in the simplified version
            param_types = None
            return_type = None
        else:
            param_types = None
            return_type = None

        return ('func_def', name, params, body_tuple, param_types, return_type)

    def process_return(self, value: Any) -> Tuple[str, Any]:
        """Process a return statement by creating a return IR node."""
        return ('return', value)

    def process_if(self, test: Any, body: List[Any], orelse: List[Any]) -> Tuple[str, Any, List[Any], List[Any]]:
        """Process an if statement by creating an if IR node."""
        return ('if', test, body, orelse)

    def process_while(self, test: Any, body: List[Any]) -> Tuple[str, Any, List[Any]]:
        """Process a while loop by creating a while IR node."""
        return ('while', test, body)

    def process_for(self, target: Any, iter_: Any, body: List[Any]) -> Tuple[str, Any, Any, List[Any]]:
        """Process a for loop by creating a for IR node."""
        return ('for', target, iter_, body)

    def process_list(self, elements: List[Any]) -> Tuple[Any, ...]:
        """Process a list literal by creating a tuple of elements."""
        return tuple(elements)

    def process_expr(self, value: Any) -> Any:
        """Process an expression statement by returning the expression value."""
        return value

    # ================== Additional Visit Methods for IR Generation ==================

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Tuple[str, Any, Any, Any]:
        """Visit an annotated assignment node."""
        target = self.visit(node.target)
        value = self.visit(node.value) if node.value else None
        annotation = self.visit(node.annotation) if node.annotation else None
        return ('assign', target, value, annotation)

    def visit_AugAssign(self, node: ast.AugAssign) -> Tuple[str, Any, str, Any]:
        """Visit an augmented assignment node."""
        target = self.visit(node.target)
        op_map = {
            ast.Add: '+=', ast.Sub: '-=', ast.Mult: '*=',
            ast.Div: '/=', ast.FloorDiv: '//=', ast.Mod: '%='
        }
        op = op_map.get(type(node.op), '?=')
        value = self.visit(node.value)
        return ('aug_assign', target, op, value)

    def visit_Break(self, node: ast.Break) -> Tuple[str]:
        """Visit a break statement."""
        return ('break',)

    def visit_Continue(self, node: ast.Continue) -> Tuple[str]:
        """Visit a continue statement."""
        return ('continue',)

    def visit_Pass(self, node: ast.Pass) -> Tuple[str]:
        """Visit a pass statement."""
        return ('pass',)

    def visit_Attribute(self, node: ast.Attribute) -> str:
        """Visit an attribute access node."""
        value = self.visit(node.value)
        return f"{value}.{node.attr}"

    def visit_Subscript(self, node: ast.Subscript) -> Tuple[str, Any, Any]:
        """Visit a subscript node (indexing)."""
        value = self.visit(node.value)
        slice_val = self.visit(node.slice)
        return ('subscript', value, slice_val)

    def visit_Slice(self, node: ast.Slice) -> Tuple[str, Any, Any, Any]:
        """Visit a slice node."""
        lower = self.visit(node.lower) if node.lower else None
        upper = self.visit(node.upper) if node.upper else None
        step = self.visit(node.step) if node.step else None
        return ('slice', lower, upper, step)

    def visit_Tuple(self, node: ast.Tuple) -> Tuple[Any, ...]:
        """Visit a tuple literal node."""
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node: ast.Dict) -> Tuple[str, List[Tuple[Any, Any]]]:
        """Visit a dictionary literal node."""
        pairs = []
        for key, value in zip(node.keys, node.values):
            key_ir = self.visit(key) if key else None
            value_ir = self.visit(value)
            pairs.append((key_ir, value_ir))
        return ('dict', pairs)

    def visit_Set(self, node: ast.Set) -> Tuple[str, List[Any]]:
        """Visit a set literal node."""
        elements = [self.visit(e) for e in node.elts]
        return ('set', elements)

    def visit_ListComp(self, node: ast.ListComp) -> Tuple[str, Any, List[Tuple]]:
        """Visit a list comprehension node."""
        elt = self.visit(node.elt)
        generators = []
        for gen in node.generators:
            target = self.visit(gen.target)
            iter_val = self.visit(gen.iter)
            ifs = [self.visit(cond) for cond in gen.ifs]
            generators.append((target, iter_val, ifs))
        return ('list_comp', elt, generators)

    def visit_SetComp(self, node: ast.SetComp) -> Tuple[str, Any, List[Tuple]]:
        """Visit a set comprehension node."""
        elt = self.visit(node.elt)
        generators = []
        for gen in node.generators:
            target = self.visit(gen.target)
            iter_val = self.visit(gen.iter)
            ifs = [self.visit(cond) for cond in gen.ifs]
            generators.append((target, iter_val, ifs))
        return ('set_comp', elt, generators)

    def visit_DictComp(self, node: ast.DictComp) -> Tuple[str, Any, Any, List[Tuple]]:
        """Visit a dictionary comprehension node."""
        key = self.visit(node.key)
        value = self.visit(node.value)
        generators = []
        for gen in node.generators:
            target = self.visit(gen.target)
            iter_val = self.visit(gen.iter)
            ifs = [self.visit(cond) for cond in gen.ifs]
            generators.append((target, iter_val, ifs))
        return ('dict_comp', key, value, generators)

    def visit_IfExp(self, node: ast.IfExp) -> Tuple[str, Any, Any, Any]:
        """Visit a conditional expression (ternary operator)."""
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return ('if_expr', test, body, orelse)

    def visit_Lambda(self, node: ast.Lambda) -> Tuple[str, Tuple[str, ...], Any, Optional[Tuple], Optional[Any]]:
        """Visit a lambda function node."""
        params = tuple(arg.arg for arg in node.args.args)
        body = self.visit(node.body)

        if self.record_types:
            param_types = tuple(
                self.visit(arg.annotation) if arg.annotation else None
                for arg in node.args.args
            )
            return_type = None  # Lambda return type inference is optional
        else:
            param_types = None
            return_type = None

        return ('lambda', params, body, param_types, return_type)

    def visit_Try(self, node: ast.Try) -> Tuple[str, List[Any], List[Any], List[Any], List[Any]]:
        """Visit a try-except block."""
        body = [self.visit(stmt) for stmt in node.body]
        handlers = [self.visit(h) for h in node.handlers]
        orelse = [self.visit(stmt) for stmt in node.orelse] if node.orelse else []
        finalbody = [self.visit(stmt) for stmt in node.finalbody] if node.finalbody else []
        return ('try', body, handlers, orelse, finalbody)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Tuple[str, Any, Optional[str], List[Any]]:
        """Visit an exception handler."""
        exc_type = self.visit(node.type) if node.type else None
        name = node.name if node.name else None
        body = [self.visit(stmt) for stmt in node.body]
        return ('except', exc_type, name, body)

    def visit_Raise(self, node: ast.Raise) -> Tuple[str, Any]:
        """Visit a raise statement."""
        exc = self.visit(node.exc) if node.exc else None
        return ('raise', exc)

    def visit_Assert(self, node: ast.Assert) -> Tuple[str, Any, Any]:
        """Visit an assert statement."""
        test = self.visit(node.test)
        msg = self.visit(node.msg) if node.msg else None
        return ('assert', test, msg)

    def visit_Import(self, node: ast.Import) -> Tuple[str, List[Tuple[str, Optional[str]]]]:
        """Visit an import statement."""
        names = [(alias.name, alias.asname) for alias in node.names]
        return ('import', names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Tuple[str, Optional[str], List[Tuple[str, Optional[str]]], int]:
        """Visit a from-import statement."""
        module = node.module
        names = [(alias.name, alias.asname) for alias in node.names]
        level = node.level
        return ('from_import', module, names, level)

    def visit_With(self, node: ast.With) -> Tuple[str, List[Tuple[Any, Any]], List[Any]]:
        """Visit a with statement."""
        items = []
        for item in node.items:
            context_expr = self.visit(item.context_expr)
            optional_vars = self.visit(item.optional_vars) if item.optional_vars else None
            items.append((context_expr, optional_vars))
        body = [self.visit(stmt) for stmt in node.body]
        return ('with', items, body)

    def visit_Starred(self, node: ast.Starred) -> Tuple[str, Any]:
        """Visit a starred expression (*args)."""
        value = self.visit(node.value)
        return ('starred', value)

    def visit_Yield(self, node: ast.Yield) -> Tuple[str, Any]:
        """Visit a yield expression."""
        value = self.visit(node.value) if node.value else None
        return ('yield', value)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> Tuple[str, Any]:
        """Visit a yield from expression."""
        value = self.visit(node.value)
        return ('yield_from', value)

    # ================== Generic Visit for Unsupported Nodes ==================

    def generic_visit(self, node: ast.AST) -> None:
        """Handle unsupported AST nodes."""
        raise NotImplementedError(f"Unsupported syntax for IR generation: {type(node).__name__}")


def main() -> None:
    """Entry point for the Silu IR generator."""
    print("Silu IR Generator")


if __name__ == "__main__":
    main()
