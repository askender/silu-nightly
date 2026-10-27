"""
Silu IR to Source Converter Module

This module provides functionality to convert Silu IR (Intermediate Representation)
back to readable source code. It can be used both as a standalone converter and
by other modules like the symbolic executor for displaying readable expressions.
"""

from typing import Any, Tuple
from .ir_utils import parse_ir_from_file, parse_ir_from_json_string, IRParseError


class IRToSourceConverter:
    """Converts IR tuples back to readable Silu/Python source code."""

    def __init__(self, indent_size: int = 4):
        self.indent_size = indent_size

    def convert_to_source(self, ir_node: Any, indent_level: int = 0) -> str:
        """Convert an IR node to source code string."""
        if isinstance(ir_node, tuple) and len(ir_node) >= 1:
            node_type = ir_node[0]

            # Source-line markers are backend metadata, not source
            if node_type == "line":
                return ""

            # Handle different IR node types
            if node_type == "name":
                return self._convert_name(ir_node)
            elif node_type == "const":
                return self._convert_const(ir_node)
            elif node_type == "const_b":
                return self._convert_const_b(ir_node)
            elif node_type == "module":
                return self._convert_module(ir_node, indent_level)
            elif node_type == "assign":
                return self._convert_assign(ir_node, indent_level)
            elif node_type == "ann_assign":
                return self._convert_ann_assign(ir_node, indent_level)
            elif node_type == "enum_def":
                return self._convert_enum_def(ir_node, indent_level)
            elif node_type == "class_def":
                return self._convert_class_def(ir_node, indent_level)
            elif node_type == "import":
                return self._convert_import(ir_node, indent_level)
            elif node_type == "from_import":
                return self._convert_from_import(ir_node, indent_level)
            elif node_type == "raise":
                return self._convert_raise(ir_node, indent_level)
            elif node_type == "match":
                return self._convert_match(ir_node, indent_level)
            elif node_type == "list_comp":
                return self._convert_list_comp(ir_node)
            elif node_type == "dict_comp":
                return self._convert_dict_comp(ir_node)
            elif node_type == "set_comp":
                return self._convert_set_comp(ir_node)
            elif node_type == "subscript_assign":
                return self._convert_subscript_assign(ir_node, indent_level)
            elif node_type == "aug_assign":
                return self._convert_aug_assign(ir_node, indent_level)
            elif node_type == "attribute_aug_assign":
                return self._convert_attribute_aug_assign(
                    ir_node, indent_level
                )
            elif node_type == "tuple_assign":
                return self._convert_tuple_assign(ir_node, indent_level)
            elif node_type == "multi_assign":
                return self._convert_multi_assign(ir_node, indent_level)
            elif node_type == "if":
                return self._convert_if(ir_node, indent_level)
            elif node_type == "while":
                return self._convert_while(ir_node, indent_level)
            elif node_type == "for":
                return self._convert_for(ir_node, indent_level)
            elif node_type == "func_def":
                return self._convert_func_def(ir_node, indent_level)
            elif node_type == "c_for":
                return self._convert_c_for(ir_node, indent_level)
            elif node_type == "aug_assign":
                return self._convert_aug_assign(ir_node, indent_level)
            elif node_type == "attribute_aug_assign":
                return self._convert_attribute_aug_assign(
                    ir_node, indent_level
                )
            elif node_type in ["p++", "p--", "++", "--"]:
                return self._convert_increment_decrement(ir_node, indent_level)
            elif node_type == "return":
                return self._convert_return(ir_node, indent_level)
            elif node_type == "call":
                return self._convert_call(ir_node, indent_level)
            elif node_type == "lambda":
                return self._convert_lambda(ir_node)
            elif node_type == "if_expr":
                return self._convert_if_expr(ir_node)
            elif node_type == "list":
                return self._convert_list(ir_node)
            elif node_type == "tuple":
                return self._convert_tuple(ir_node)
            elif node_type == "dict":
                return self._convert_dict(ir_node)
            elif node_type == "set":
                return self._convert_set(ir_node)
            elif node_type == "attribute":
                return self._convert_attribute(ir_node)
            elif node_type == "subscript":
                return self._convert_subscript(ir_node)
            elif node_type == "slice":
                return self._convert_slice(ir_node)
            elif node_type == "chained_compare":
                return self._convert_chained_compare(ir_node)
            elif node_type == "pass":
                return self._get_indent(indent_level) + "pass"
            elif node_type == "break":
                return self._get_indent(indent_level) + "break"
            elif node_type == "continue":
                return self._get_indent(indent_level) + "continue"
            elif node_type in ["==", "!=", "<", ">", "<=", ">="]:
                return self._convert_comparison(ir_node)
            elif node_type in ["and", "or"]:
                return self._convert_bool_op(ir_node)
            elif node_type == "not":
                return self._convert_unary_op(ir_node)
            elif node_type in ["+", "-", "*", "/", "//", "%", "**"]:
                # Check if it's unary or binary operation
                if len(ir_node) == 2:
                    return self._convert_unary_op(ir_node)
                else:
                    return self._convert_binary_op(ir_node)
            else:
                # Try to handle as generic expression
                return self._convert_expression(ir_node)
        elif isinstance(ir_node, str):
            # Handle string values - for standalone strings, check if identifier
            if ir_node.isidentifier():
                return ir_node
            else:
                return repr(ir_node)
        else:
            # Handle literals and simple values
            return self._convert_literal(ir_node)

    def _convert_module(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert module IR to source code. Line markers drive the
        emitted blank-line gaps so a re-parse reproduces the same IR
        (the IR fixed point)."""
        _, statements = ir_node
        self._out_line = 0
        self._pending_line = None
        lines = self._render_stmts(statements, indent_level)
        return "\n".join(lines)

    def _render_stmts(self, stmts, indent_level: int):
        """Render a statement list, honouring ('line', n) markers:
        blank lines are inserted so the statement lands on line n.
        Statements themselves may render multi-line; _out_line counts
        every emitted physical line."""
        lines = []
        indent = self._get_indent(indent_level)
        for stmt in stmts:
            if isinstance(stmt, (tuple, list)) and stmt and stmt[0] == "line":
                self._pending_line = stmt[1]
                continue
            if getattr(self, "_pending_line", None) is not None:
                gap = self._pending_line - getattr(self, "_out_line", 0) - 1
                for _ in range(max(0, gap)):
                    lines.append("")
                    self._out_line = getattr(self, "_out_line", 0) + 1
                self._pending_line = None
            before = getattr(self, "_out_line", 0)
            text = self.convert_to_source(stmt, indent_level)
            # bare expression statements (name/const/binop/call) carry
            # no leading indent at level 0 - add it positionally
            if stmt[0] in ("name", "const", "call") and not text.startswith(
                (" ", "\t")
            ):
                text = indent + text
            if getattr(self, "_out_line", 0) == before:
                # simple statement: no nested renderer advanced the
                # counter - count the emitted lines here
                for physical in text.split("\n"):
                    lines.append(physical)
                    self._out_line = getattr(self, "_out_line", 0) + 1
            else:
                # a nested renderer already counted every line it
                # produced (headers included) - emit without recount
                lines.append(text)
        return lines

    def _align_to(self, lines, target_line):
        """Blank-fill so the NEXT emitted line lands on target_line."""
        gap = target_line - getattr(self, "_out_line", 0) - 1
        for _ in range(max(0, gap)):
            lines.append("")
            self._out_line = getattr(self, "_out_line", 0) + 1

    def _convert_name(self, ir_node: Tuple) -> str:
        """Convert name IR node to identifier."""
        _, name = ir_node
        return name

    def _convert_const(self, ir_node: Tuple) -> str:
        """Convert constant IR node to literal value."""
        _, value = ir_node
        return self._convert_literal(value)

    def _convert_const_b(self, ir_node: Tuple) -> str:
        """Convert bytes constant IR node to bytes literal."""
        _, string_value = ir_node
        # Convert string back to bytes representation
        bytes_value = string_value.encode("latin-1")
        return repr(bytes_value)

    def _convert_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert assignment IR to source code."""
        _, target, value, _ = ir_node  # Fourth element is type info (can be None)
        indent = self._get_indent(indent_level)
        # Value in assignment could be literal or expression
        value_str = self._convert_value_in_context(value, "value")
        # Target is a name, or an attribute/subscript node (obj.f = v)
        if isinstance(target, (tuple, list)):
            target_str = self.convert_to_source(target)
        else:
            target_str = target
        return f"{indent}{target_str} = {value_str}"

    def _convert_subscript_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert subscript assignment IR to source code."""
        _, obj, key, value = ir_node
        indent = self._get_indent(indent_level)
        obj_str = self._convert_identifier_or_value(obj)
        key_str = self._convert_value_in_context(key, "value")
        value_str = self._convert_value_in_context(value, "value")
        return f"{indent}{obj_str}[{key_str}] = {value_str}"

    def _convert_aug_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert augmented assignment IR to source code."""
        _, target, op, value = ir_node
        indent = self._get_indent(indent_level)
        target_str = self.convert_to_source(target, 0).strip()
        value_str = self.convert_to_source(value, 0).strip()
        return f"{indent}{target_str} {op} {value_str}"

    def _convert_attribute_aug_assign(self, ir_node, indent_level: int) -> str:
        """obj.attr op= value: ("attribute_aug_assign", obj, attr, op, value)."""
        _, obj, attr, op, value = ir_node
        indent = self._get_indent(indent_level)
        obj_str = self.convert_to_source(obj)
        value_str = self.convert_to_source(value)
        return f"{indent}{obj_str}.{attr} {op} {value_str}"

    def _convert_tuple_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert tuple assignment IR to source code."""
        _, targets, value = ir_node
        indent = self._get_indent(indent_level)
        # Convert targets tuple to comma-separated string
        targets_str = ", ".join(targets)
        # Convert value to source code
        value_str = self._convert_value_in_context(value, "value")
        return f"{indent}{targets_str} = {value_str}"

    def _convert_multi_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert multiple assignment IR to source code."""
        _, assignments = ir_node

        # Extract the value from the first assignment
        first_assign = assignments[0]
        _, _, value, _ = first_assign  # (assign, target, value, type_info)
        value_str = self.convert_to_source(value)

        # Extract all target names
        targets = []
        for assign in assignments:
            _, target, _, _ = assign
            targets.append(target)

        # Create the multiple assignment string: a = b = c = value
        targets_str = " = ".join(targets)
        indent = self._get_indent(indent_level)

        return f"{indent}{targets_str} = {value_str}"

    def _convert_if(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert if statement IR to source code. Nested if-in-orelse
        stays nested (else: if ...) - re-parsing reproduces the exact
        same IR shape."""
        _, condition, body, orelse = ir_node
        lines = []

        condition_str = self.convert_to_source(condition)
        indent = self._get_indent(indent_level)
        lines.append(f"{indent}if {condition_str}:")
        self._out_line = getattr(self, "_out_line", 0) + 1

        lines.extend(self._render_stmts(body, indent_level + 1))

        self._render_tail(orelse, indent_level, lines)

        return "\n".join(lines)

    def _render_tail(self, orelse, indent_level: int, lines):
        """Render an if/for orelse: [line, if...] with a single nested
        if is an elif chain (one physical line per arm, so the IR line
        markers round-trip exactly); anything else is a plain else."""
        if not orelse:
            return
        first_line = None
        for st in orelse:
            if isinstance(st, (tuple, list)) and st and st[0] == "line":
                first_line = st[1]
            break
        stmts = [
            st
            for st in orelse
            if not (
                isinstance(st, (tuple, list)) and st and st[0] == "line"
            )
        ]
        indent = self._get_indent(indent_level)
        if (
            len(stmts) == 1
            and isinstance(stmts[0], (tuple, list))
            and stmts[0][0] == "if"
        ):
            # elif arm: its line marker is the elif keyword line
            if first_line is not None:
                self._align_to(lines, first_line)
            self._render_if_like("elif", stmts[0], indent_level, lines)
            return
        if first_line is not None:
            self._align_to(lines, first_line - 1)
        lines.append(f"{indent}else:")
        self._out_line = getattr(self, "_out_line", 0) + 1
        lines.extend(self._render_stmts(orelse, indent_level + 1))

    def _render_if_like(self, keyword, ir_node, indent_level: int, lines):
        """One if/elif header + body + (recursive) tail."""
        _, condition, body, orelse = ir_node
        indent = self._get_indent(indent_level)
        condition_str = self.convert_to_source(condition)
        lines.append(f"{indent}{keyword} {condition_str}:")
        self._out_line = getattr(self, "_out_line", 0) + 1
        lines.extend(self._render_stmts(body, indent_level + 1))
        self._render_tail(orelse, indent_level, lines)

    def _convert_while(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert while loop IR to source code."""
        _, condition, body = ir_node
        lines = []

        condition_str = self.convert_to_source(condition)
        indent = self._get_indent(indent_level)
        lines.append(f"{indent}while {condition_str}:")
        self._out_line = getattr(self, "_out_line", 0) + 1

        lines.extend(self._render_stmts(body, indent_level + 1))

        return "\n".join(lines)

    def _convert_for(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert for loop IR to source code."""
        _, target, iter_val, body, orelse = ir_node
        lines = []

        # Target is a name, or a tuple_unpack node (for i, x in ...)
        if isinstance(target, str):
            target_str = target
        elif (
            isinstance(target, (tuple, list))
            and target
            and target[0] == "tuple_unpack"
        ):
            target_str = ", ".join(str(n) for n in target[1])
        else:
            target_str = self.convert_to_source(target)
        iter_str = self._convert_identifier_or_value(iter_val)
        indent = self._get_indent(indent_level)
        lines.append(f"{indent}for {target_str} in {iter_str}:")
        self._out_line = getattr(self, "_out_line", 0) + 1

        lines.extend(self._render_stmts(body, indent_level + 1))

        self._render_tail(orelse, indent_level, lines)

        return "\n".join(lines)

    def _convert_func_def(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert function definition IR to source code."""
        # Handle both Silu format (4 elements) and C format (5-6 elements)
        if len(ir_node) == 4:
            # Silu format: ("func_def", name, args, body)
            _, name, args, body = ir_node
        elif len(ir_node) >= 5:
            # C format: ("func_def", name, args, body, param_types, [return_type])
            _, name, args, body = ir_node[:4]
        else:
            raise ValueError(
                f"Invalid func_def format: expected 4+ elements, got {len(ir_node)}"
            )
        lines = []

        annos = ir_node[4] if len(ir_node) > 4 else ()
        param_bits = []
        for index, arg in enumerate(args):
            anno = annos[index] if index < len(annos) else None
            if anno is not None:
                param_bits.append(f"{arg}: {self._annotation_str(anno)}")
            else:
                param_bits.append(str(arg))
        args_str = ", ".join(param_bits)
        ret_anno = ir_node[5] if len(ir_node) > 5 else None
        suffix = ""
        if ret_anno is not None:
            suffix = f" -> {self._annotation_str(ret_anno)}"
        indent = self._get_indent(indent_level)
        lines.append(f"{indent}def {name}({args_str}){suffix}:")
        self._out_line = getattr(self, "_out_line", 0) + 1

        lines.extend(self._render_stmts(body, indent_level + 1))

        return "\n".join(lines)

    def _annotation_str(self, ann) -> str:
        if ann is None:
            return ""
        if isinstance(ann, (tuple, list)):
            if ann[0] == "name":
                return str(ann[1])
            if ann[0] == "const" and len(ann) > 1 and ann[1] is None:
                return "None"
            if ann[0] == "subscript" and len(ann) >= 3:
                base = self._annotation_str(ann[1])
                inner = ann[2]
                if isinstance(inner, (tuple, list)) and inner and inner[0] == "tuple":
                    items = ", ".join(
                        self._annotation_str(e) for e in inner[1]
                    )
                else:
                    items = self._annotation_str(inner)
                return f"{base}[{items}]"
        return str(ann)

    def _convert_ann_assign(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert annotated assignment IR to source: x: int = 3."""
        _, target, value, ann = ir_node
        indent = self._get_indent(indent_level)
        ann_str = self._annotation_str(ann)
        if value is None:
            return f"{indent}{target}: {ann_str}"
        value_str = self._convert_value_in_context(value, "value")
        return f"{indent}{target}: {ann_str} = {value_str}"

    def _convert_enum_def(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert enum definition IR: class X(Enum): A = 0 (bare member
        when the IR value is None - re-parse reproduces the same IR)."""
        _, name, members = ir_node
        indent = self._get_indent(indent_level)
        lines = [f"{indent}class {name}(Enum):"]
        self._out_line = getattr(self, "_out_line", 0) + 1
        for member in members:
            mname, mvalue = member[0], member[1]
            if mvalue is None:
                lines.append(f"{indent}    {mname}")
            else:
                lines.append(
                    f"{indent}    {mname} = {self.convert_to_source(mvalue)}"
                )
            self._out_line = getattr(self, "_out_line", 0) + 1
        return "\n".join(lines)

    def _convert_import(self, ir_node: Tuple, indent_level: int) -> str:
        _, names = ir_node
        indent = self._get_indent(indent_level)
        parts = []
        for item in names:
            n, asname = item if isinstance(item, (tuple, list)) else (item, None)
            parts.append(str(n) if asname is None else f"{n} as {asname}")
        return f"{indent}import {', '.join(parts)}"

    def _convert_from_import(self, ir_node: Tuple, indent_level: int) -> str:
        _, module, names, _level = ir_node
        indent = self._get_indent(indent_level)
        parts = []
        for item in names:
            n, asname = item if isinstance(item, (tuple, list)) else (item, None)
            parts.append(str(n) if asname is None else f"{n} as {asname}")
        return f"{indent}from {module} import {', '.join(parts)}"

    def _convert_raise(self, ir_node: Tuple, indent_level: int) -> str:
        _, exc = ir_node if len(ir_node) > 1 else (ir_node[0], None)
        indent = self._get_indent(indent_level)
        if exc is None:
            return f"{indent}raise"
        return f"{indent}raise {self.convert_to_source(exc)}"

    def _convert_match(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert match IR: match/case with value/as/or patterns."""
        _, subject, cases = ir_node
        indent = self._get_indent(indent_level)
        lines = [f"{indent}match {self.convert_to_source(subject)}:"]
        self._out_line = getattr(self, "_out_line", 0) + 1
        for case in cases:
            pattern, guard, body = case[1], case[2], case[3]
            pat_str = self._pattern_str(pattern)
            # the case keyword sits one line above the body's first line
            first_line = None
            for st in body:
                if isinstance(st, (tuple, list)) and st and st[0] == "line":
                    first_line = st[1]
                break
            if first_line is not None:
                self._align_to(lines, first_line - 1)
            if guard is not None:
                lines.append(
                    f"{indent}    case {pat_str} if "
                    f"{self.convert_to_source(guard)}:"
                )
            else:
                lines.append(f"{indent}    case {pat_str}:")
            self._out_line = getattr(self, "_out_line", 0) + 1
            lines.extend(self._render_stmts(body, indent_level + 2))
        return "\n".join(lines)

    def _pattern_str(self, pattern) -> str:
        if isinstance(pattern, (tuple, list)) and pattern:
            kind = pattern[0]
            if kind == "match_value":
                return self.convert_to_source(pattern[1])
            if kind == "match_as":
                inner, name = pattern[1], pattern[2]
                if inner is None and name is None:
                    return "_"
                if inner is None:
                    return str(name)
                base = self._pattern_str(inner)
                return base if name is None else f"{base} as {name}"
            if kind == "match_or":
                return " | ".join(self._pattern_str(p) for p in pattern[1])
            if kind == "match_class":
                cls = self.convert_to_source(pattern[1])
                parts = [self._pattern_str(p) for p in (pattern[2] or [])]
                for attr, sub in zip(pattern[3] or [], pattern[4] or []):
                    parts.append(f"{attr}={self._pattern_str(sub)}")
                return f"{cls}({', '.join(parts)})"
        return str(pattern)

    def _convert_dict_comp(self, ir_node: Tuple) -> str:
        _, (key_node, value_node), generators = ir_node
        parts = []
        for gen in generators:
            target, iter_val, conds = gen[0], gen[1], gen[2]
            target_str = (
                target[1] if isinstance(target, (tuple, list)) else str(target)
            )
            bit = f"for {target_str} in {self.convert_to_source(iter_val)}"
            for cond in conds or ():
                bit += f" if {self.convert_to_source(cond)}"
            parts.append(bit)
        return (
            f"{{{self.convert_to_source(key_node)}: "
            f"{self.convert_to_source(value_node)} {' '.join(parts)}}}"
        )

    def _convert_set_comp(self, ir_node: Tuple) -> str:
        _, elt, generators = ir_node
        parts = []
        for gen in generators:
            target, iter_val, conds = gen[0], gen[1], gen[2]
            target_str = (
                target[1] if isinstance(target, (tuple, list)) else str(target)
            )
            bit = f"for {target_str} in {self.convert_to_source(iter_val)}"
            for cond in conds or ():
                bit += f" if {self.convert_to_source(cond)}"
            parts.append(bit)
        return (
            f"{{{self.convert_to_source(elt)} {' '.join(parts)}}}"
        )

    def _convert_list_comp(self, ir_node: Tuple) -> str:
        _, elt, generators = ir_node
        parts = []
        for gen in generators:
            target, iter_val, conds = gen[0], gen[1], gen[2]
            target_str = (
                target[1] if isinstance(target, (tuple, list)) else str(target)
            )
            bit = f"for {target_str} in {self.convert_to_source(iter_val)}"
            for cond in conds or ():
                bit += f" if {self.convert_to_source(cond)}"
            parts.append(bit)
        return f"[{self.convert_to_source(elt)} {' '.join(parts)}]"

    def _convert_class_def(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert class definition IR to source code."""
        _, name, bases, body = ir_node
        lines = []

        indent = self._get_indent(indent_level)

        # Handle base classes if present
        bases_str = ""
        if bases:
            bases_str = (
                "(" + ", ".join(self._convert_expression(base) for base in bases) + ")"
            )

        lines.append(f"{indent}class {name}{bases_str}:")
        self._out_line = getattr(self, "_out_line", 0) + 1

        if body:
            lines.extend(self._render_stmts(body, indent_level + 1))
        else:
            # Empty class needs a pass statement
            lines.append(f"{indent}    pass")

        return "\n".join(lines)

    def _convert_c_for(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert C-style for loop IR to source code."""
        _, init, condition, update, body = ir_node

        indent = self._get_indent(indent_level)
        lines = []

        # Convert components to string
        init_str = self.convert_to_source(init, 0).strip() if init else ""
        cond_str = self.convert_to_source(condition, 0).strip() if condition else ""
        update_str = self.convert_to_source(update, 0).strip() if update else ""

        lines.append(f"{indent}for {init_str}; {cond_str}; {update_str}:")

        # Convert body
        if isinstance(body, (list, tuple)):
            for stmt in body:
                lines.append(self.convert_to_source(stmt, indent_level + 1))
        else:
            lines.append(self.convert_to_source(body, indent_level + 1))

        return "\n".join(lines)

    def _convert_increment_decrement(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert increment/decrement operations IR to source code."""
        op, operand = ir_node

        indent = self._get_indent(indent_level)
        operand_str = self.convert_to_source(operand, 0).strip()

        if op == "p++":
            return f"{indent}{operand_str}++"
        elif op == "p--":
            return f"{indent}{operand_str}--"
        elif op == "++":
            return f"{indent}++{operand_str}"
        elif op == "--":
            return f"{indent}--{operand_str}"
        else:
            return f"{indent}{op} {operand_str}"

    def _convert_return(self, ir_node: Tuple, indent_level: int) -> str:
        """Convert return statement IR to source code."""
        _, value = ir_node
        indent = self._get_indent(indent_level)
        if value is None:
            return f"{indent}return"
        else:
            value_str = self.convert_to_source(value)
            return f"{indent}return {value_str}"

    def _convert_call(self, ir_node: Tuple, indent_level: int = 0) -> str:
        """Convert function call IR to source code."""
        _, func, args, keywords = ir_node
        func_str = self._convert_identifier_or_value(func)

        arg_strs = []
        for arg in args:
            arg_strs.append(self._convert_identifier_or_value(arg))

        # Handle keyword arguments
        for key, value in keywords:
            value_str = self.convert_to_source(value)
            arg_strs.append(f"{key}={value_str}")

        args_str = ", ".join(arg_strs)
        call_str = f"{func_str}({args_str})"

        # If indent_level is provided, treat this as a statement
        if indent_level > 0:
            return self._get_indent(indent_level) + call_str
        else:
            return call_str

    def _convert_lambda(self, ir_node: Tuple) -> str:
        """Convert lambda expression IR to source code."""
        _, args, body = ir_node

        # Convert arguments
        if isinstance(args, tuple):
            args_str = ", ".join(args)
        else:
            args_str = str(args)

        # Convert body expression
        body_str = self.convert_to_source(body)

        return f"lambda {args_str}: {body_str}"

    def _convert_if_expr(self, ir_node: Tuple) -> str:
        """Convert if expression (ternary operator) IR to source code."""
        _, condition, true_val, false_val = ir_node

        condition_str = self.convert_to_source(condition)
        true_str = self.convert_to_source(true_val)
        false_str = self.convert_to_source(false_val)

        return f"{true_str} if {condition_str} else {false_str}"

    def _convert_list(self, ir_node: Tuple) -> str:
        """Convert list IR to source code."""
        _, elements = ir_node
        element_strs = [
            self._convert_value_in_context(elem, "value") for elem in elements
        ]
        return f"[{', '.join(element_strs)}]"

    def _convert_tuple(self, ir_node: Tuple) -> str:
        """Convert tuple IR to source code."""
        _, elements = ir_node
        element_strs = [
            self._convert_value_in_context(elem, "value") for elem in elements
        ]
        if len(elements) == 1:
            return f"({element_strs[0]},)"
        return f"({', '.join(element_strs)})"

    def _convert_dict(self, ir_node: Tuple) -> str:
        """Convert dict IR to source code."""
        _, elements = ir_node
        pairs = []
        for key, value in elements:
            key_str = self._convert_value_in_context(key, "value")
            value_str = self._convert_value_in_context(value, "value")
            pairs.append(f"{key_str}: {value_str}")
        return f"{{{', '.join(pairs)}}}"

    def _convert_set(self, ir_node: Tuple) -> str:
        """Convert set IR to source code."""
        _, elements = ir_node
        element_strs = [
            self._convert_value_in_context(elem, "value") for elem in elements
        ]
        return f"{{{', '.join(element_strs)}}}"

    def _convert_attribute(self, ir_node: Tuple) -> str:
        """Convert attribute access IR to source code."""
        _, obj, attr = ir_node
        obj_str = self._convert_identifier_or_value(obj)
        return f"{obj_str}.{attr}"

    def _convert_subscript(self, ir_node: Tuple) -> str:
        """Convert subscript IR to source code."""
        _, obj, index = ir_node
        obj_str = self._convert_identifier_or_value(obj)
        index_str = self._convert_identifier_or_value(index)
        return f"{obj_str}[{index_str}]"

    def _convert_slice(self, ir_node: Tuple) -> str:
        """Convert slice IR to source code."""
        _, lower, upper, step = ir_node
        parts = []

        if lower is not None:
            parts.append(self.convert_to_source(lower))
        else:
            parts.append("")

        parts.append(":")

        if upper is not None:
            parts.append(self.convert_to_source(upper))
        else:
            parts.append("")

        if step is not None:
            parts.append(":")
            parts.append(self.convert_to_source(step))

        return "".join(parts)

    def _convert_chained_compare(self, ir_node: Tuple) -> str:
        """Convert chained comparison IR to source code."""
        _, comparisons = ir_node
        parts = []

        if comparisons:
            # First comparison
            op, left, right = comparisons[0]
            parts.append(self.convert_to_source(left))
            parts.append(f" {op} ")
            parts.append(self.convert_to_source(right))

            # Subsequent comparisons
            for op, left, right in comparisons[1:]:
                parts.append(f" {op} ")
                parts.append(self.convert_to_source(right))

        return "".join(parts)

    def _convert_binary_op(self, ir_node: Tuple) -> str:
        """Convert binary operation IR to source code."""
        op, left, right = ir_node
        left_str = self._convert_identifier_or_value(left)
        right_str = self._convert_identifier_or_value(right)

        # Add parentheses if needed for nested operations
        if self._needs_parentheses(left, op, side="left"):
            left_str = f"({left_str})"
        if self._needs_parentheses(right, op, side="right"):
            right_str = f"({right_str})"

        return f"{left_str} {op} {right_str}"

    def _convert_comparison(self, ir_node: Tuple) -> str:
        """Convert comparison IR to source code."""
        op, left, right = ir_node
        left_str = self._convert_identifier_or_value(left)
        right_str = self._convert_identifier_or_value(right)
        return f"{left_str} {op} {right_str}"

    def _convert_bool_op(self, ir_node: Tuple) -> str:
        """Convert boolean operation IR to source code. and/or are
        n-ary in the IR; they re-parse to the same n-ary node."""
        op = ir_node[0]
        parts = []
        for operand in ir_node[1:]:
            operand_str = self.convert_to_source(operand)
            if self._needs_parentheses(operand, op):
                operand_str = f"({operand_str})"
            parts.append(operand_str)
        return f" {op} ".join(parts)

    def _convert_unary_op(self, ir_node: Tuple) -> str:
        """Convert unary operation IR to source code."""
        op, operand = ir_node
        operand_str = self.convert_to_source(operand)

        # For 'not' operator, add parentheses if operand is a boolean operation
        # that has lower precedence than 'not'
        if op == "not" and self._needs_parentheses(operand, op):
            operand_str = f"({operand_str})"

        if op == "-":
            return f"-{operand_str}"
        elif op == "+":
            return f"+{operand_str}"
        elif op == "not":
            return f"not {operand_str}"
        else:
            return f"{op}{operand_str}"

    def _convert_expression(self, ir_node: Any) -> str:
        """Generic expression converter for unknown node types."""
        if isinstance(ir_node, tuple) and len(ir_node) >= 2:
            # Try to handle as operation
            op = ir_node[0]
            operands = ir_node[1:]

            if len(operands) == 1:
                # Unary operation
                return f"{op}({self.convert_to_source(operands[0])})"
            elif len(operands) == 2:
                # Binary operation
                left_str = self.convert_to_source(operands[0])
                right_str = self.convert_to_source(operands[1])
                return f"{left_str} {op} {right_str}"
            else:
                # Multiple operands
                operand_strs = [self.convert_to_source(op) for op in operands]
                return f"{op}({', '.join(operand_strs)})"

        return str(ir_node)

    def _convert_literal(self, value: Any) -> str:
        """Convert literal values to source code."""
        if isinstance(value, str):
            # Always treat strings that reach here as string literals
            return repr(value)
        elif value is None:
            return "None"
        elif isinstance(value, bool):
            return "True" if value else "False"
        else:
            return str(value)

    # Operator precedence (higher number = tighter binding)
    _PRECEDENCE = {
        "or": 1,
        "and": 2,
        "not": 3,
        "==": 4,
        "!=": 4,
        "<": 4,
        ">": 4,
        "<=": 4,
        ">=": 4,
        "is": 4,
        "is not": 4,
        "in": 4,
        "not in": 4,
        "+": 5,
        "-": 5,
        "*": 6,
        "/": 6,
        "//": 6,
        "%": 6,
        "**": 7,
    }
    _RIGHT_ASSOC = {"**"}

    def _needs_parentheses(
        self, operand: Any, parent_op: str, side: str = "right"
    ) -> bool:
        """Does the operand need parentheses under parent_op?

        Left-associative operators: a same-precedence RIGHT operand
        changes the tree (a - (b + c) vs a - b + c, a / (b * c) vs
        a / b * c) so it is parenthesized; a same-precedence left
        operand is not. ** is right-associative - the mirror image.
        Unary (not/-) callers use the conservative right-side rule."""
        if not isinstance(operand, tuple) or len(operand) < 1:
            return False
        operand_op = operand[0]
        if operand_op not in self._PRECEDENCE:
            return False
        parent_prec = self._PRECEDENCE.get(parent_op, 10)
        operand_prec = self._PRECEDENCE[operand_op]
        if parent_op in self._RIGHT_ASSOC:
            if side == "left":
                return operand_prec <= parent_prec
            return operand_prec < parent_prec
        if side == "right":
            return operand_prec <= parent_prec
        return operand_prec < parent_prec

    def _get_indent(self, level: int) -> str:
        """Get indentation string for given level."""
        return " " * (level * self.indent_size)

    def _convert_identifier_or_value(self, value: Any) -> str:
        """Convert a value that could be an identifier or a literal."""
        if isinstance(value, str):
            # Enhanced heuristics to distinguish identifiers from string literals
            if self._is_likely_identifier(value):
                return value  # Return as identifier
            else:
                return repr(value)  # Return as string literal
        else:
            return self.convert_to_source(value)

    def _is_likely_identifier(self, value: str) -> bool:
        """Determine if a string is likely an identifier rather than a literal."""
        # Must be a valid Python identifier
        if not value.isidentifier():
            return False

        # Common string literal patterns that should be quoted
        string_literal_indicators = [
            # Contains spaces or punctuation that suggests human-readable text
            " ",
            ".",
            "!",
            "?",
            ",",
            ";",
            ":",
            '"',
            "'",
            # Common greeting/message patterns
            "Hello",
            "Hi",
            "Hey",
            "Howdy",
            "Welcome",
            # Common words that appear in messages
            "message",
            "error",
            "warning",
            "info",
            "debug",
        ]

        # If it contains obvious string literal patterns, treat as literal
        for indicator in string_literal_indicators[:9]:  # punctuation/spaces
            if indicator in value:
                return False

        # If it starts with common greeting words, likely a message
        for greeting in string_literal_indicators[9:13]:  # greetings
            if value.startswith(greeting):
                return False

        # Common string literal words (case sensitive)
        literal_words = {
            "Alice",
            "Bob",
            "Charlie",
            "Diana",
            "John",
            "Jane",
            "Doe",
            "Hello",
            "Hi",
            "Hey",
            "Howdy",
            "Good",
            "Bad",
            "Error",
            "Success",
            "positive",
            "negative",
            "zero",
            "large",
            "small",
            "Excellent",
            "New York",
            "Engineer",
            "LOG_",
            "text",
            "more text",
        }

        # Common function names that should be treated as identifiers
        common_function_names = {
            "print",
            "len",
            "max",
            "min",
            "sum",
            "abs",
            "round",
            "sorted",
            "reversed",
            "enumerate",
            "zip",
            "map",
            "filter",
            "range",
            "list",
            "dict",
            "set",
            "tuple",
            "str",
            "int",
            "float",
            "bool",
            "type",
            "isinstance",
            "hasattr",
            "getattr",
            "setattr",
            "open",
            "close",
            "read",
            "write",
            "append",
            "split",
            "join",
            "strip",
            "replace",
            "find",
            "format",
            "upper",
            "lower",
            "startswith",
            "endswith",
            "isdigit",
            "isalpha",
            "isalnum",
            "isspace",
        }

        # If it's a common function name, treat as identifier
        if value in common_function_names:
            return True

        # Common dictionary keys that should be treated as string literals
        common_dict_keys = {
            "name",
            "age",
            "email",
            "id",
            "type",
            "value",
            "config",
            "settings",
            "users",
            "items",
            "title",
            "description",
            "content",
            "status",
            "error",
            "warning",
            "info",
            "debug",
            "log",
            "file",
            "path",
            "url",
            "link",
            "image",
            "html",
            "json",
            "xml",
            "csv",
            "theme",
            "lang",
            "language",
            "locale",
            "timezone",
            "format",
            "width",
            "height",
            "size",
            "length",
            "count",
            "total",
        }

        if value in literal_words or value in common_dict_keys:
            return False

        # Pattern-based checks
        # All caps with underscores (constants that are often string literals in config)
        if value.isupper() and "_" in value:
            return False

        # Capitalized words that aren't typical variable names
        if value[0].isupper() and len(value) > 1:
            # Names/proper nouns are usually string literals
            if not any(char.islower() for char in value[1:]):  # ALL_CAPS
                return False
            # Mixed case proper nouns
            return False

        # If none of the above, likely an identifier
        return True

    def _convert_value_in_context(self, value: Any, context: str) -> str:
        """Convert a value based on its context."""
        if isinstance(value, str):
            if context == "value":
                # In assignment value context, strings are typically literals
                return repr(value)
            elif context == "identifier":
                # In identifier context, return as-is
                return value
            else:
                # Default: check if identifier
                return value if value.isidentifier() else repr(value)
        else:
            return self.convert_to_source(value)


def convert_ir_file_to_source(ir_file_path: str, output_file_path: str = None) -> str:
    """Convert an IR file to source code file."""
    try:
        ir_data = parse_ir_from_file(ir_file_path)
    except (IRParseError, FileNotFoundError) as e:
        raise ValueError(f"Could not parse IR file: {e}")

    # Convert to source
    converter = IRToSourceConverter()
    source_code = converter.convert_to_source(ir_data)

    # Write to output file if specified
    if output_file_path:
        with open(output_file_path, "w") as f:
            f.write(source_code)
            f.write("\n")  # Add final newline

    return source_code


def convert_ir_string_to_source(ir_string: str) -> str:
    """Convert an IR string to source code."""
    try:
        ir_data = parse_ir_from_json_string(ir_string)
    except IRParseError as e:
        raise ValueError(f"Could not parse IR string: {e}")

    # Convert to source
    converter = IRToSourceConverter()
    return converter.convert_to_source(ir_data)


# Convenience functions for shared use with symbolic_executor
def make_expression_readable(expr: Any) -> str:
    """Convert IR expression to readable format (shared with symbolic executor)."""
    converter = IRToSourceConverter()
    return converter.convert_to_source(expr)


def simplify_value_display(value: Any) -> str:
    """Simplify value display for better readability (shared with symbolic executor)."""
    converter = IRToSourceConverter()
    return converter.convert_to_source(value)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ir_to_source.py <ir_file> [output_file]")
        sys.exit(1)

    ir_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        source_code = convert_ir_file_to_source(ir_file, output_file)
        if not output_file:
            print(source_code)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
