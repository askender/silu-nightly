"""
C IR Generator Module

This module provides a C-to-IR generator that converts C programs into the same
intermediate representation format used by Silu, enabling symbolic execution
and analysis of C code.
"""

import json
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
import re
import os

# 继承当前环境
env = os.environ.copy()

pattern_comment = re.compile(r'/\*.*?\*/', re.DOTALL)  # re.DOTALL 让 . 可以匹配换行符


try:
    from pycparser import c_parser, c_ast
except ImportError:
    print("Error: pycparser is required for C IR generation.", file=sys.stderr)
    print("Install it with: pip install pycparser", file=sys.stderr)
    sys.exit(1)


class CIRGenerator(c_ast.NodeVisitor):
    """
    C IR generator that converts pycparser C AST to Silu IR format.

    This generator produces the same IR format as SiluIRGenerator, allowing
    C programs to be analyzed using the existing symbolic execution tools.
    """

    def __init__(self, record_types: bool = True):
        """
        Initialize the C IR generator.

        Args:
            record_types: Whether to record type information in the IR
        """
        self.record_types = record_types
        self.current_function = None
        self.typedefs = {}  # Maps typedef names to their underlying types
        self.struct_definitions = {}  # Maps struct names to their field information

    # ================== Top-level Constructs ==================

    def visit_FileAST(self, node: c_ast.FileAST) -> Tuple[str, Tuple]:
        """Convert file AST to module IR."""
        statements = []
        for ext in node.ext or []:
            result = self.visit(ext)
            if result is not None:
                statements.append(result)
        return ("module", tuple(statements))

    def visit_FuncDef(self, node: c_ast.FuncDef) -> Tuple:
        """Convert function definition to IR."""
        name = node.decl.name
        self.current_function = name

        # Extract parameters
        params = []
        param_types = []
        if hasattr(node.decl.type, 'args') and node.decl.type.args:
            for param in node.decl.type.args.params:
                if hasattr(param, 'name') and param.name:
                    params.append(param.name)
                    if self.record_types:
                        param_types.append(self._get_type_string(param.type))

        # Extract return type
        return_type = None
        if self.record_types and hasattr(node.decl.type, 'type'):
            return_type = self._get_type_string(node.decl.type.type)

        # Process function body
        body = []
        if node.body and hasattr(node.body, 'block_items') and node.body.block_items:
            for stmt in node.body.block_items:
                result = self.visit(stmt)
                if result is not None:
                    body.append(result)

        self.current_function = None

        # Return IR in format: ('func_def', name, params, body, param_types, return_type)
        if self.record_types:
            return ("func_def", name, tuple(params), tuple(body), tuple(param_types), return_type)
        else:
            return ("func_def", name, tuple(params), tuple(body))

    # ================== Statements ==================

    def visit_Decl(self, node: c_ast.Decl) -> Optional[Tuple]:
        """Convert variable declaration to IR."""
        if not node.name:
            return None

        name = node.name
        type_info = self._get_type_string(node.type) if self.record_types else None

        # Handle initialization
        value = None
        if node.init:
            value = self.visit(node.init)

        return ("assign", name, value, type_info)

    def visit_Typedef(self, node: c_ast.Typedef) -> Optional[Tuple]:
        """Convert typedef declaration to IR."""
        if not node.name:
            return None

        # Check if this is a struct typedef
        if isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Struct):
            struct_node = node.type.type
            struct_name = node.name

            # Extract struct fields
            fields = self._extract_struct_fields(struct_node)

            # Store struct definition
            self.struct_definitions[struct_name] = fields

            # Store the typedef mapping
            self.typedefs[struct_name] = f"struct_{struct_name}"

            # Return IR representation for struct typedef
            return ("typedef_struct", struct_name, fields)
        # Check if this is an enum typedef
        elif isinstance(node.type, c_ast.TypeDecl) and isinstance(node.type.type, c_ast.Enum):
            enum_node = node.type.type
            enum_name = node.name

            # Extract enum values
            enum_values = []
            if enum_node.values:
                for enumerator in enum_node.values.enumerators:
                    if enumerator.value:
                        # If explicit value is provided
                        value = self.visit(enumerator.value)
                        enum_values.append((enumerator.name, value))
                    else:
                        # If no explicit value, use auto-incrementing
                        if enum_values:
                            # Get the last value and increment
                            last_value = enum_values[-1][1]
                            if isinstance(last_value, tuple) and last_value[0] == "constant" and isinstance(last_value[1], int):
                                next_value = last_value[1] + 1
                            else:
                                next_value = len(enum_values)
                        else:
                            next_value = 0
                        enum_values.append((enumerator.name, ("constant", next_value)))

            # Store the typedef mapping
            self.typedefs[enum_name] = "enum"

            # Return IR representation for enum typedef
            return ("typedef_enum", enum_name, enum_values)
        else:
            # Extract the underlying type for regular typedefs
            underlying_type = self._get_type_string(node.type)

            # Store the mapping
            self.typedefs[node.name] = underlying_type

            # Return IR representation for typedef
            return ("typedef", node.name, underlying_type)

    def visit_Assignment(self, node: c_ast.Assignment) -> Tuple:
        """Convert assignment to IR."""
        lvalue = self.visit(node.lvalue)
        rvalue = self.visit(node.rvalue)

        # Map C assignment operators
        op_map = {
            '=': '=',
            '+=': '+=',
            '-=': '-=',
            '*=': '*=',
            '/=': '/=',
            '%=': '%=',
            '&=': '&=',
            '|=': '|=',
            '^=': '^=',
            '<<=': '<<=',
            '>>=': '>>='
        }

        op = op_map.get(node.op, node.op)

        if op == '=':
            return ("assign", lvalue, rvalue, None)
        else:
            return ("aug_assign", lvalue, op, rvalue)

    def visit_Return(self, node: c_ast.Return) -> Tuple:
        """Convert return statement to IR."""
        value = self.visit(node.expr) if node.expr else None
        return ("return", value)

    # ================== Control Flow ==================

    def visit_If(self, node: c_ast.If) -> Tuple:
        """Convert if statement to IR."""
        condition = self.visit(node.cond)

        # Process then block
        then_body = []
        if node.iftrue:
            if hasattr(node.iftrue, 'block_items') and node.iftrue.block_items:
                for stmt in node.iftrue.block_items:
                    result = self.visit(stmt)
                    if result is not None:
                        then_body.append(result)
            else:
                result = self.visit(node.iftrue)
                if result is not None:
                    then_body.append(result)

        # Process else block
        else_body = []
        if node.iffalse:
            if hasattr(node.iffalse, 'block_items') and node.iffalse.block_items:
                for stmt in node.iffalse.block_items:
                    result = self.visit(stmt)
                    if result is not None:
                        else_body.append(result)
            else:
                result = self.visit(node.iffalse)
                if result is not None:
                    else_body.append(result)

        return ("if", condition, tuple(then_body), tuple(else_body))

    def visit_While(self, node: c_ast.While) -> Tuple:
        """Convert while loop to IR."""
        condition = self.visit(node.cond)

        # Process body
        body = []
        if node.stmt:
            if hasattr(node.stmt, 'block_items') and node.stmt.block_items:
                for stmt in node.stmt.block_items:
                    result = self.visit(stmt)
                    if result is not None:
                        body.append(result)
            else:
                result = self.visit(node.stmt)
                if result is not None:
                    body.append(result)

        return ("while", condition, tuple(body))

    def visit_For(self, node: c_ast.For) -> Tuple:
        """Convert for loop to IR."""
        init = self.visit(node.init) if node.init else None
        condition = self.visit(node.cond) if node.cond else ("const", True)
        next_stmt = self.visit(node.next) if node.next else None

        # Process body
        body = []
        if node.stmt:
            if hasattr(node.stmt, 'block_items') and node.stmt.block_items:
                for stmt in node.stmt.block_items:
                    result = self.visit(stmt)
                    if result is not None:
                        body.append(result)
            else:
                result = self.visit(node.stmt)
                if result is not None:
                    body.append(result)

        return ("c_for", init, condition, next_stmt, tuple(body))

    def visit_Break(self, node: c_ast.Break) -> Tuple:
        """Convert break statement to IR."""
        return ("break",)

    def visit_Continue(self, node: c_ast.Continue) -> Tuple:
        """Convert continue statement to IR."""
        return ("continue",)

    def visit_Switch(self, node: c_ast.Switch) -> Tuple:
        """Convert switch statement to IR."""
        condition = self.visit(node.cond)

        # Process switch body
        cases = []
        if node.stmt and hasattr(node.stmt, 'block_items') and node.stmt.block_items:
            for stmt in node.stmt.block_items:
                result = self.visit(stmt)
                if result is not None:
                    cases.append(result)

        return ("switch", condition, tuple(cases))

    def visit_Case(self, node: c_ast.Case) -> Tuple:
        """Convert case label to IR."""
        # Get the case value
        value = self.visit(node.expr)

        # Collect statements in this case
        statements = []
        if hasattr(node, 'stmts') and node.stmts:
            for stmt in node.stmts:
                result = self.visit(stmt)
                if result is not None:
                    statements.append(result)

        return ("case", value, tuple(statements))

    def visit_Default(self, node: c_ast.Default) -> Tuple:
        """Convert default label to IR."""
        # Collect statements in this default case
        statements = []
        if hasattr(node, 'stmts') and node.stmts:
            for stmt in node.stmts:
                result = self.visit(stmt)
                if result is not None:
                    statements.append(result)

        return ("default", tuple(statements))

    # ================== Expressions ==================

    def visit_BinaryOp(self, node: c_ast.BinaryOp) -> Tuple:
        """Convert binary operation to IR."""
        left = self.visit(node.left)
        right = self.visit(node.right)

        # Map C operators to IR operators
        op_map = {
            '+': '+',
            '-': '-',
            '*': '*',
            '/': '/',
            '%': '%',
            '<<': '<<',
            '>>': '>>',
            '&': '&',
            '|': '|',
            '^': '^',
            '&&': 'and',
            '||': 'or',
            '==': '==',
            '!=': '!=',
            '<': '<',
            '<=': '<=',
            '>': '>',
            '>=': '>='
        }

        op = op_map.get(node.op, node.op)
        return (op, left, right)

    def visit_UnaryOp(self, node: c_ast.UnaryOp) -> Tuple:
        """Convert unary operation to IR."""
        operand = self.visit(node.expr)

        # Map C unary operators
        op_map = {
            '+': '+',
            '-': '-',
            '!': 'not',
            '~': '~',
            '++': '++',
            '--': '--',
            'p++': 'p++',  # post-increment
            'p--': 'p--',  # post-decrement
            '*': 'deref',
            '&': 'addr'
        }

        op = op_map.get(node.op, node.op)
        return (op, operand)

    def visit_ID(self, node: c_ast.ID) -> Tuple:
        """Convert identifier to IR."""
        return ("name", node.name)

    def visit_Constant(self, node: c_ast.Constant) -> Tuple:
        """Convert constant to IR."""
        value = node.value

        # Convert string constants
        if hasattr(node, 'type'):
            if node.type == 'int':
                try:
                    value = int(value)
                except ValueError:
                    # Handle hex, octal, etc.
                    value = int(value, 0)
            elif node.type == 'float':
                value = float(value)
            elif node.type == 'char':
                # Handle character literals
                if value.startswith("'") and value.endswith("'"):
                    if len(value) == 3:  # Simple character like 'a'
                        value = value[1]
                    else:  # Escape sequences like '\n'
                        value = value[1:-1].encode().decode('unicode_escape')
            elif node.type == 'string':
                # Handle string literals
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1].encode().decode('unicode_escape')

        return ("const", value)

    def visit_FuncCall(self, node: c_ast.FuncCall) -> Tuple:
        """Convert function call to IR."""
        func_name = self.visit(node.name)

        # Process arguments
        args = []
        if node.args and hasattr(node.args, 'exprs'):
            for arg in node.args.exprs:
                args.append(self.visit(arg))

        # Convert to format compatible with Silu IR
        return ("call", func_name, tuple(args), tuple())

    def visit_ArrayRef(self, node: c_ast.ArrayRef) -> Tuple:
        """Convert array reference to IR."""
        array = self.visit(node.name)
        subscript = self.visit(node.subscript)
        return ("subscript", array, subscript)

    def visit_StructRef(self, node: c_ast.StructRef) -> Tuple:
        """Convert struct member reference to IR."""
        struct = self.visit(node.name)
        field = node.field.name if hasattr(node.field, 'name') else str(node.field)
        return ("attribute", struct, field)

    # ================== Compound Statements ==================

    def visit_Compound(self, node: c_ast.Compound) -> List:
        """Convert compound statement (block) to list of IR statements."""
        statements = []
        if node.block_items:
            for stmt in node.block_items:
                result = self.visit(stmt)
                if result is not None:
                    statements.append(result)
        return statements

    def visit_ExprList(self, node: c_ast.ExprList) -> List:
        """Convert expression list to list of IR expressions."""
        return [self.visit(expr) for expr in node.exprs]

    # ================== Struct Handling ==================

    def _extract_struct_fields(self, struct_node: c_ast.Struct) -> List[Tuple[str, str]]:
        """Extract field information from a struct node."""
        fields = []
        if struct_node.decls:
            for decl in struct_node.decls:
                if isinstance(decl, c_ast.Decl) and decl.name:
                    field_name = decl.name
                    field_type = self._get_type_string(decl.type)
                    fields.append((field_name, field_type))
        return fields

    # ================== Type Handling ==================

    def _resolve_typedef(self, type_name: str) -> str:
        """Recursively resolve typedef aliases to their base types."""
        resolved = type_name
        visited = set()

        while resolved in self.typedefs and resolved not in visited:
            visited.add(resolved)
            resolved = self.typedefs[resolved]

        return resolved

    def _get_type_string(self, type_node) -> str:
        """Extract type information as a string."""
        if isinstance(type_node, c_ast.TypeDecl):
            if isinstance(type_node.type, c_ast.IdentifierType):
                type_name = ' '.join(type_node.type.names)
                # Recursively resolve typedef aliases
                return self._resolve_typedef(type_name)
            else:
                return self._get_type_string(type_node.type)
        elif isinstance(type_node, c_ast.PtrDecl):
            base_type = self._get_type_string(type_node.type)
            return f"{base_type}*"
        elif isinstance(type_node, c_ast.ArrayDecl):
            # For multi-dimensional arrays, we need to collect all dimensions first
            dimensions = []
            current_node = type_node

            # Traverse nested ArrayDecl nodes to collect dimensions in correct order
            while isinstance(current_node, c_ast.ArrayDecl):
                if current_node.dim:
                    dim_value = self._extract_array_dimension(current_node.dim)
                    dimensions.append(f"[{dim_value}]")
                else:
                    dimensions.append("[]")
                current_node = current_node.type

            # Get the base type
            base_type = self._get_type_string(current_node)

            # Build the type string with dimensions in correct order
            return base_type + ''.join(dimensions)
        elif isinstance(type_node, c_ast.FuncDecl):
            return "function"
        elif isinstance(type_node, c_ast.IdentifierType):
            type_name = ' '.join(type_node.names)
            # Recursively resolve typedef aliases
            return self._resolve_typedef(type_name)
        elif isinstance(type_node, c_ast.Struct):
            # Handle anonymous structs or named structs
            if type_node.name:
                return f"struct_{type_node.name}"
            else:
                # For anonymous structs, return a generic struct type
                return "struct"
        elif isinstance(type_node, c_ast.Enum):
            # Handle enum types
            if type_node.name:
                return f"enum_{type_node.name}"
            else:
                # For anonymous enums, return a generic enum type
                return "enum"
        else:
            return str(type(type_node).__name__)

    def _extract_array_dimension(self, dim_node) -> str:
        """Extract array dimension from dimension node."""
        if isinstance(dim_node, c_ast.Constant):
            return dim_node.value
        elif isinstance(dim_node, c_ast.ID):
            return dim_node.name
        elif isinstance(dim_node, c_ast.BinaryOp):
            # Handle expressions like n+1, etc.
            left = self._extract_array_dimension(dim_node.left)
            right = self._extract_array_dimension(dim_node.right)
            return f"{left}{dim_node.op}{right}"
        else:
            # For other complex expressions, visit the node
            result = self.visit(dim_node)
            if isinstance(result, tuple) and len(result) >= 2:
                return str(result[1]) if result[1] is not None else "?"
            return "?"

    # ================== Error Handling ==================

    def generic_visit(self, node: c_ast.Node) -> Optional[str]:
        """Handle unsupported AST nodes."""
        node_name = type(node).__name__
        # TODO
        # print(f"Warning: Unsupported C construct: {node_name}") # , file=sys.stderr
        return f"<unsupported:{node_name}>"


def clean_comment(astr):
    if '//' in astr:
        return astr.split('//')[0].strip()
    return astr

# ================== Main Functions ==================

def generate_ir_from_c_code(c_code: str, record_types: bool = True) -> Tuple|None:
    """
    Generate IR from C source code.

    Args:
        c_code: C source code as a string
        record_types: Whether to include type information in IR

    Returns:
        IR tuple representing the C program
    """
    try:
        parser = c_parser.CParser()
        # c_code = c_code.replace("#include <stdlib.h>", "")
        c_code = c_code.replace("#include <stdio.h>", "")
        c_code = c_code.replace('__signed', 'signed')
        c_code = re.sub(pattern_comment, '', c_code)
        c_code = [j for j in c_code.split('\n') if not j.strip().startswith('#')]
        c_code = [j for j in c_code if not j.strip().startswith('//')]

        c_code = [j for j in c_code if "__darwin_" not in j.strip()]
        c_code = [clean_comment(j) for j in c_code ]
        c_code = '\n'.join(c_code)
        # print(f"c_code:\n{c_code}")

        try:
            ast = parser.parse(c_code)
        except Exception as e:
            print(f"Error2 parsing C code: {e}") # , file=sys.stderr
            return

        print("ast.show:")
        ast.show()

        generator = CIRGenerator(record_types=record_types)
        ir = generator.visit(ast)

        return ir
    except Exception as e:
        print(f"Error generating IR from C code: {e}", file=sys.stderr)
        raise


def generate_ir_from_c_file(file_path: str, record_types: bool = True) -> Tuple:
    """
    Generate IR from C source file.

    Args:
        file_path: Path to C source file
        record_types: Whether to include type information in IR

    Returns:
        IR tuple representing the C program
    """
    try:
        tmp_file = f"{file_path}.v2.c"
        with open(file_path, 'r', encoding='utf-8') as f:
            c_code = f.read()
            c_code = c_code.replace("#include <stdio.h>", "")
            # c_code = re.sub(r'#include\s+<[^>]+>', '', c_code)
            with open(tmp_file, 'w', encoding='utf-8') as f:
                f.write(c_code)

        import os
        # if os.path.isfile(f"{file_path}.i"):
        #     with open(f"{file_path}.i", 'r', encoding='utf-8') as f:
        #         c_code = f.read()

        import subprocess
        # "-nostdinc", "-nostdlib", cpp gcc clang
        # "-nostdinc", "-Iutils/fake_libc_include",
        # r'-I/path/to/pycparser/utils/fake_libc_include'
        cmd = ["clang", "-E", "-Imystdint", "-I./.venv/lib/python3.13/site-packages/pycparser/utils/fake_libc_include", tmp_file]
        # print(' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode != 0:
            # TODO
            print(f"[Error1] cpp failed on {file_path}.v2.c with return code {result.returncode}")
            print(f"stderr output:\n{result.stderr}")
            return

        c_code = result.stdout
        # with open(f"{file_path}.i", 'w', encoding='utf-8') as f:
        #     f.write(c_code)

        if os.path.exists(tmp_file):
            os.remove(tmp_file)

        return generate_ir_from_c_code(c_code, record_types)

    except FileNotFoundError:
        print(f"Error: C file '{file_path}' not found.", file=sys.stderr)
        raise
    except IOError as e:
        print(f"Error reading C file '{file_path}': {e}", file=sys.stderr)
        raise


def save_ir_to_file(ir: Tuple, output_path: str, format_type: str = "json") -> None:
    """
    Save IR to file.

    Args:
        ir: IR tuple to save
        output_path: Output file path
        format_type: Output format ("json" or "pretty")
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            if format_type == "json":
                json.dump(ir, f, indent=2, default=str)
            else:
                import pprint
                f.write(pprint.pformat(ir, width=80))
    except IOError as e:
        print(f"Error writing IR file '{output_path}': {e}", file=sys.stderr)
        raise


# ================== Command Line Interface ==================

def main():
    """Command line interface for C IR generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate IR from C source code for symbolic execution"
    )
    parser.add_argument("input_file", help="Input C source file")
    parser.add_argument("-o", "--output", help="Output IR file (default: input.ir.json)")
    parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--no-types",
        action="store_true",
        help="Don't record type information in IR"
    )

    args = parser.parse_args()

    # Determine output file name
    output_file = args.output
    if not output_file:
        input_path = args.input_file
        if input_path.endswith('.c'):
            output_file = input_path[:-2] + '.ir.json'
        else:
            output_file = input_path + '.ir.json'

    try:
        # Generate IR
        # print(f"Generating IR from {args.input_file}...")
        ir = generate_ir_from_c_file(args.input_file, record_types=not args.no_types)

        # Save IR
        print(f"Saving IR to {output_file}...")
        save_ir_to_file(ir, output_file, args.format)

        print(f"IR generation complete. Output saved to {output_file}")

        # Print summary
        print(f"\nIR Summary:")
        print(f"  Format: {args.format}")
        print(f"  Type info: {'No' if args.no_types else 'Yes'}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
