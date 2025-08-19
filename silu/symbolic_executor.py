#!/usr/bin/env python3
"""
Simplified Symbolic Execution Engine for Silu Language

This module provides symbolic execution capabilities for Silu programs,
allowing analysis of all possible execution paths and generation of
path constraints for functions.
"""

from typing import Any, Dict, List, Tuple, Union, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import json
import ast
from copy import deepcopy

try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False
    z3 = None

# Import shared conversion functions
from .ir_to_source import make_expression_readable, simplify_value_display


class SymbolicValueType(Enum):
    """Types of symbolic values"""
    SYMBOLIC = "symbolic"
    CONCRETE = "concrete"
    EXPRESSION = "expression"


@dataclass
class SymbolicValue:
    """Represents a symbolic value in the execution"""
    type: SymbolicValueType
    value: Any
    name: Optional[str] = None
    constraints: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.type == SymbolicValueType.CONCRETE:
            return str(self.value)
        elif self.type == SymbolicValueType.SYMBOLIC:
            return self.name or f"sym_{id(self)}"
        else:  # EXPRESSION
            return str(self.value)

    def __repr__(self) -> str:
        return f"SymbolicValue({self.type.value}, {self.value}, {self.name})"


@dataclass
class PathCondition:
    """Represents a condition that must be satisfied for a path to be taken"""
    expression: str
    is_true: bool
    source_line: Optional[int] = None

    def __str__(self) -> str:
        prefix = "" if self.is_true else "not "
        return f"{prefix}({self.expression})"

    def negate(self) -> 'PathCondition':
        """Return the negated condition"""
        return PathCondition(
            expression=self.expression,
            is_true=not self.is_true,
            source_line=self.source_line
        )


@dataclass
class ExecutionPath:
    """Represents a single execution path through a function"""
    path_id: str
    conditions: List[PathCondition] = field(default_factory=list)
    statements: List[str] = field(default_factory=list)
    return_value: Optional[SymbolicValue] = None
    variables: Dict[str, SymbolicValue] = field(default_factory=dict)

    def add_condition(self, condition: PathCondition):
        """Add a path condition"""
        self.conditions.append(condition)

    def add_statement(self, statement: str):
        """Add an executed statement"""
        self.statements.append(statement)

    def is_satisfiable(self) -> bool:
        """Check if the path conditions are satisfiable (basic check)"""
        expressions = {}
        for condition in self.conditions:
            if condition.expression in expressions:
                if expressions[condition.expression] != condition.is_true:
                    return False
            expressions[condition.expression] = condition.is_true
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            'path_id': self.path_id,
            'conditions': [str(c) for c in self.conditions],
            'statements': self.statements,
            'return_value': str(self.return_value) if self.return_value else None,
            'variables': {k: str(v) for k, v in self.variables.items()},
            'satisfiable': getattr(self, 'satisfiable', True)
        }

        # Add optional attributes if present
        for attr in ['test_inputs', 'expected_outputs', 'z3_error', 'z3_errors']:
            if hasattr(self, attr):
                result[attr] = getattr(self, attr)

        return result


class SymbolicEnvironment:
    """Environment for symbolic execution"""

    def __init__(self, parent: Optional['SymbolicEnvironment'] = None):
        self.parent = parent
        self.variables: Dict[str, SymbolicValue] = {}
        self.functions: Dict[str, Any] = {}
        self.symbol_counter = 0

    def create_symbol(self, name: str = None) -> SymbolicValue:
        """Create a new symbolic value"""
        if not name:
            name = f"sym_{self.symbol_counter}"
            self.symbol_counter += 1
        return SymbolicValue(SymbolicValueType.SYMBOLIC, None, name)

    def get_variable(self, name: str) -> SymbolicValue:
        """Get a variable value"""
        if name in self.variables:
            return self.variables[name]
        elif self.parent:
            return self.parent.get_variable(name)
        else:
            symbol = self.create_symbol(name)
            self.variables[name] = symbol
            return symbol

    def set_variable(self, name: str, value: SymbolicValue):
        """Set a variable value"""
        self.variables[name] = value

    def copy(self) -> 'SymbolicEnvironment':
        """Create a deep copy of the environment"""
        new_env = SymbolicEnvironment(self.parent)
        new_env.variables = deepcopy(self.variables)
        new_env.functions = deepcopy(self.functions)
        new_env.symbol_counter = self.symbol_counter
        return new_env


class SymbolicExecutor:
    """Symbolic execution engine for Silu IR"""

    def __init__(self):
        self.global_env = SymbolicEnvironment()
        self.current_env = self.global_env
        self.paths: List[ExecutionPath] = []
        self.current_path: Optional[ExecutionPath] = None
        self.path_counter = 0
        self.max_paths = 100

        # Initialize built-in functions
        self._init_builtins()

    def _init_builtins(self):
        """Initialize built-in functions with unified handler"""
        builtin_names = ['print', 'int', 'float', 'str', 'bool', 'type', 'isinstance', 'len']
        for name in builtin_names:
            self.global_env.functions[name] = lambda *args, fn=name: self._handle_builtin(fn, *args)

    def _handle_builtin(self, func_name: str, *args) -> SymbolicValue:
        """Unified handler for built-in functions"""
        # Record function call in current path
        if self.current_path:
            args_str = ', '.join(str(arg) for arg in args)
            self.current_path.add_statement(f"{func_name}({args_str})")

        if func_name == 'print':
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        if len(args) == 0:
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"{func_name}()")

        arg = args[0]
        if func_name in ['int', 'float', 'str', 'bool'] and arg.type == SymbolicValueType.CONCRETE:
            converters = {'int': int, 'float': float, 'str': str, 'bool': bool}
            return SymbolicValue(SymbolicValueType.CONCRETE, converters[func_name](arg.value))

        args_str = ', '.join(str(arg) for arg in args)
        return SymbolicValue(SymbolicValueType.EXPRESSION, f"{func_name}({args_str})")

    def execute_program(self, ir_program: Tuple) -> List[ExecutionPath]:
        """Execute an IR program symbolically and return all paths"""
        if not ir_program or ir_program[0] != "module":
            raise ValueError("Invalid IR program format")

        self.paths = []
        self.current_path = ExecutionPath("path_0")
        self.path_counter = 1

        try:
            self._execute_ir(ir_program)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"Error: {e}")

        if self.current_path and self.current_path not in self.paths:
            self.paths.append(self.current_path)

        # Filter out empty paths and renumber
        self.paths = [p for p in self.paths if p.statements or p.conditions or p.variables]
        return self.renumber_paths_sequentially(self.paths)

    def analyze_function(self, func_name: str, param_names: List[str], ir_program: Tuple) -> List[ExecutionPath]:
        """Analyze a specific function with symbolic parameters"""
        self.paths = []
        self.current_path = ExecutionPath("path_0")
        self.path_counter = 1

        # Create symbolic parameters
        for param in param_names:
            symbol = self.current_env.create_symbol(param)
            self.current_env.set_variable(param, symbol)

        try:
            self._execute_ir(ir_program)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"Error: {e}")

        if self.current_path and self.current_path not in self.paths:
            self.paths.append(self.current_path)

        return self.renumber_paths_sequentially(self.paths)

    def analyze_function_definition(self, ir_node: Tuple) -> List[ExecutionPath]:
        """Analyze a function definition IR node"""
        if len(ir_node) < 4:
            return []

        func_name = ir_node[1]
        params = ir_node[2] if ir_node[2] else []
        body = ir_node[3]

        return self.analyze_function(func_name, params, body)

    def _execute_ir(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an IR node and return its symbolic value"""
        if not isinstance(ir_node, tuple) or not ir_node:
            return SymbolicValue(SymbolicValueType.CONCRETE, ir_node)

        op = ir_node[0]

        # Dispatch to specific handlers
        handlers = {
            "module": self._execute_module,
            "assign": self._execute_assign,
            "if": self._execute_if,
            "while": self._execute_while,
            "func_def": self._execute_func_def,
            "call": self._execute_call,
            "return": self._execute_return,
            "block": self._execute_block,
            "literal": self._execute_literal,
            "binary_op": self._execute_binary_op,
        }

        if op in handlers:
            return handlers[op](ir_node)
        elif op in ['+', '-', '*', '/', '//', '%', '**', '==', '!=', '<', '>', '<=', '>=', 'and', 'or', 'not']:
            return self._execute_binary_op(ir_node)
        elif op == "chained_compare":
            return self._execute_chained_compare(ir_node)
        elif op == "comparison":
            return self._execute_comparison(ir_node)
        elif isinstance(op, str) and op.isdigit():
            return SymbolicValue(SymbolicValueType.CONCRETE, int(op))
        else:
            # Variable reference or literal
            if isinstance(op, str):
                return self.current_env.get_variable(op)
            return SymbolicValue(SymbolicValueType.CONCRETE, op)

    def _execute_module(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a module IR node"""
        for stmt in ir_node[1]:
            self._execute_ir(stmt)
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_assign(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an assignment IR node"""
        _, var_name, value_ir, _ = ir_node
        value = self._execute_ir(value_ir)
        self.current_env.set_variable(var_name, value)

        if self.current_path:
            simplified_value = self._simplify_display(value)
            self.current_path.add_statement(f"{var_name} = {simplified_value}")
            self.current_path.variables[var_name] = value

        return value

    def _execute_literal(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a literal IR node"""
        if len(ir_node) > 1:
            return SymbolicValue(SymbolicValueType.CONCRETE, ir_node[1])
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_if(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an if statement symbolically - creates multiple paths"""
        if len(ir_node) == 4:
            _, condition_ir, then_block, else_block = ir_node
        else:
            _, condition_ir, then_block = ir_node
            else_block = None

        condition = self._execute_ir(condition_ir)
        condition_str = str(condition)
        readable_condition = self._make_readable(condition)

        if len(self.paths) >= self.max_paths:
            if self.current_path:
                self.current_path.add_statement(f"Path limit reached at if condition: {condition_str}")
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Store current state
        original_path = self.current_path
        original_env = self.current_env.copy()

        # True path
        true_path = ExecutionPath(f"path_{self.path_counter}")
        self.path_counter += 1
        if original_path:
            true_path.conditions = original_path.conditions.copy()
            true_path.statements = original_path.statements.copy()
            true_path.variables = original_path.variables.copy()

        true_condition = PathCondition(condition_str, True)
        true_path.add_condition(true_condition)
        true_path.add_statement(f"if {readable_condition}:")

        self.current_path = true_path
        self.current_env = original_env.copy()

        if then_block:
            self._execute_ir(then_block)

        # Store the true path result
        true_path_result = self.current_path
        if true_path_result and true_path_result.is_satisfiable():
            if true_path_result not in self.paths:
                self.paths.append(true_path_result)

        # False path
        false_path = ExecutionPath(f"path_{self.path_counter}")
        self.path_counter += 1
        if original_path:
            false_path.conditions = original_path.conditions.copy()
            false_path.statements = original_path.statements.copy()
            false_path.variables = original_path.variables.copy()

        false_condition = PathCondition(condition_str, False)
        false_path.add_condition(false_condition)
        false_path.add_statement(f"else (not {readable_condition}):")

        self.current_path = false_path
        self.current_env = original_env.copy()

        if else_block:
            self._execute_ir(else_block)

        # Store the false path result
        false_path_result = self.current_path
        if false_path_result and false_path_result.is_satisfiable():
            if false_path_result not in self.paths:
                self.paths.append(false_path_result)

        # Continue with first satisfiable path for subsequent statements in same block
        satisfiable_paths = [p for p in [true_path_result, false_path_result] if p and p.is_satisfiable()]
        if satisfiable_paths:
            self.current_path = satisfiable_paths[0]
        else:
            self.current_path = None

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_while(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a while loop symbolically (simplified - may create multiple paths)"""
        _, condition_ir, body_ir = ir_node
        condition = self._execute_ir(condition_ir)
        condition_str = str(condition)
        readable_condition = self._make_readable(condition)

        if self.current_path:
            self.current_path.add_statement(f"while {readable_condition}:")

        # For symbolic execution, we consider both entering and not entering the loop
        original_path = self.current_path
        original_env = self.current_env.copy()
        collected_paths = []

        # Path 1: Loop condition is false initially
        false_condition = PathCondition(condition_str, False)
        if original_path:
            false_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            false_path.conditions = original_path.conditions.copy()
            false_path.statements = original_path.statements.copy()
            false_path.variables = original_path.variables.copy()
            false_path.add_condition(false_condition)
            false_path.add_statement("# Loop not entered")
            collected_paths.append(false_path)

        # Path 2: Loop condition is true (execute body once)
        true_condition = PathCondition(condition_str, True)
        if original_path:
            true_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            true_path.conditions = original_path.conditions.copy()
            true_path.statements = original_path.statements.copy()
            true_path.variables = original_path.variables.copy()
            true_path.add_condition(true_condition)
            true_path.add_statement("# Loop entered")

            self.current_path = true_path
            self.current_env = original_env.copy()

            # Execute the body
            self._execute_ir(body_ir)

            if self.current_path and self.current_path.is_satisfiable():
                self.current_path.add_statement("# Loop iteration completed")
                collected_paths.append(self.current_path)

        # Add all collected paths
        for path in collected_paths:
            if path not in self.paths:
                self.paths.append(path)

        # End current path as we've split into multiple paths
        self.current_path = None

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_func_def(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function definition"""
        _, func_name, params, body = ir_node

        # Store function in global environment
        self.global_env.functions[func_name] = (params, body)

        if self.current_path:
            params_str = ', '.join(params) if params else ''
            self.current_path.add_statement(f"def {func_name}({params_str}):")

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_call(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function call"""
        _, func_ir, args_ir = ir_node

        func_name = func_ir if isinstance(func_ir, str) else str(func_ir)
        args = [self._execute_ir(arg) for arg in args_ir] if args_ir else []

        # Handle built-in functions
        if func_name in self.global_env.functions:
            builtin_func = self.global_env.functions[func_name]
            if callable(builtin_func):
                return builtin_func(*args)

        # For user-defined functions, create symbolic result
        args_str = ', '.join(str(arg) for arg in args)
        if self.current_path:
            self.current_path.add_statement(f"{func_name}({args_str})")

        return SymbolicValue(SymbolicValueType.EXPRESSION, f"{func_name}({args_str})")

    def _execute_return(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a return statement"""
        if len(ir_node) > 1:
            value = self._execute_ir(ir_node[1])
        else:
            value = SymbolicValue(SymbolicValueType.CONCRETE, None)

        if self.current_path:
            self.current_path.return_value = value
            self.current_path.add_statement(f"return {self._simplify_display(value)}")

        return value

    def _execute_binary_op(self, ir_node: Tuple) -> SymbolicValue:
        """Execute binary operations"""
        if len(ir_node) == 4:
            # Format: ("binary_op", left, op, right)
            _, left_ir, op, right_ir = ir_node
            left = self._execute_ir(left_ir)
            right = self._execute_ir(right_ir)
        elif len(ir_node) == 3:
            # Format: (op, left, right)
            op, left_ir, right_ir = ir_node
            left = self._execute_ir(left_ir)
            right = self._execute_ir(right_ir)
        elif len(ir_node) == 2:
            # Unary operation
            op, operand_ir = ir_node
            operand = self._execute_ir(operand_ir)
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"{op}{operand}")
        else:
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Try concrete evaluation if both operands are concrete
        if left.type == SymbolicValueType.CONCRETE and right.type == SymbolicValueType.CONCRETE:
            try:
                operators = {
                    '+': lambda a, b: a + b, '-': lambda a, b: a - b,
                    '*': lambda a, b: a * b, '/': lambda a, b: a / b,
                    '//': lambda a, b: a // b, '%': lambda a, b: a % b,
                    '**': lambda a, b: a ** b, '==': lambda a, b: a == b,
                    '!=': lambda a, b: a != b, '<': lambda a, b: a < b,
                    '>': lambda a, b: a > b, '<=': lambda a, b: a <= b,
                    '>=': lambda a, b: a >= b, 'and': lambda a, b: a and b,
                    'or': lambda a, b: a or b
                }
                if op in operators:
                    result = operators[op](left.value, right.value)
                    return SymbolicValue(SymbolicValueType.CONCRETE, result)
            except (ZeroDivisionError, TypeError, ValueError):
                pass

        # Create symbolic expression
        return SymbolicValue(SymbolicValueType.EXPRESSION, (op, left, right))

    def _execute_chained_compare(self, ir_node: Tuple) -> SymbolicValue:
        """Execute chained comparison"""
        if len(ir_node) >= 4:
            # Format: ("chained_compare", left, op, right, ...)
            _, left_ir, op, right_ir = ir_node[:4]
            left = self._execute_ir(left_ir)
            right = self._execute_ir(right_ir)

            # Create comparison expression
            return SymbolicValue(SymbolicValueType.EXPRESSION, (op, left, right))
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_comparison(self, ir_node: Tuple) -> SymbolicValue:
        """Execute comparison operations"""
        return self._execute_binary_op(ir_node)

    def _execute_block(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a block of statements"""
        result = SymbolicValue(SymbolicValueType.CONCRETE, None)
        if len(ir_node) > 1:
            statements = ir_node[1] if isinstance(ir_node[1], (tuple, list)) else ir_node[1:]
            for stmt in statements:
                result = self._execute_ir(stmt)
        return result

    def _make_readable(self, condition) -> str:
        """Convert condition to readable format"""
        if hasattr(condition, 'value') and hasattr(condition, 'type'):
            return self._make_readable(condition.value)

        try:
            return make_expression_readable(condition)
        except Exception:
            return str(condition)

    def _simplify_display(self, value) -> str:
        """Simplify value display for better readability"""
        if hasattr(value, 'type') and hasattr(value, 'value'):
            if value.type == SymbolicValueType.CONCRETE:
                return str(value.value)
            elif value.type == SymbolicValueType.SYMBOLIC:
                return getattr(value, 'name', str(value.value)) or str(value.value)
            else:  # EXPRESSION
                return self._simplify_display(value.value)

        try:
            return simplify_value_display(value)
        except Exception:
            return str(value)

    def generate_report(self, paths: List[ExecutionPath]) -> Dict[str, Any]:
        """Generate a comprehensive report of symbolic execution results"""
        return {
            'total_paths': len(paths),
            'satisfiable_paths': len([p for p in paths if p.is_satisfiable()]),
            'paths': [path.to_dict() for path in paths],
            'summary': {
                'functions_analyzed': len(self.global_env.functions),
                'max_path_length': max((len(p.statements) for p in paths), default=0),
                'max_conditions': max((len(p.conditions) for p in paths), default=0),
            }
        }

    def renumber_paths_sequentially(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Renumber paths sequentially starting from 1"""
        for i, path in enumerate(paths, 1):
            path.path_id = f"path_{i}"
        return paths

    def enhance_paths_with_test_cases(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Enhanced version with Z3 solver (simplified)"""
        if not Z3_AVAILABLE:
            for path in paths:
                path.satisfiable = True
                path.z3_error = "Z3 solver not available"
            return paths

        for path in paths:
            try:
                solver = z3.Solver()
                var_map = {}

                # Add constraints
                for condition in path.conditions:
                    z3_constraint = self._condition_to_z3(condition, var_map, solver)
                    if z3_constraint is not None:
                        solver.add(z3_constraint)

                # Check satisfiability
                result = solver.check()
                path.satisfiable = (result == z3.sat)

                if result == z3.sat:
                    model = solver.model()
                    path.test_inputs = {str(var): str(model[var]) for var in model.decls()}
                    path.expected_outputs = self._extract_outputs_from_path(path)
                else:
                    path.test_inputs = {}
                    path.expected_outputs = {}

            except Exception as e:
                path.satisfiable = True
                path.z3_error = str(e)

        return paths

    def _condition_to_z3(self, condition: PathCondition, var_map: Dict[str, Any], solver: z3.Solver) -> Any:
        """Convert condition to Z3 constraint (simplified)"""
        try:
            # Simple pattern matching for basic conditions
            import re
            expr = condition.expression.strip()

            # Handle simple comparisons like "x > 5"
            pattern = r'(\w+)\s*([><=!]+)\s*(.+)'
            match = re.match(pattern, expr)

            if match:
                var_name, op, value_str = match.groups()

                if var_name not in var_map:
                    var_map[var_name] = z3.Int(var_name)

                var = var_map[var_name]

                try:
                    value = z3.IntVal(int(value_str))
                except ValueError:
                    try:
                        value = z3.RealVal(float(value_str))
                    except ValueError:
                        return None

                ops = {
                    '>': lambda a, b: a > b, '<': lambda a, b: a < b,
                    '>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b,
                    '==': lambda a, b: a == b, '!=': lambda a, b: a != b
                }

                if op in ops:
                    constraint = ops[op](var, value)
                    return constraint if condition.is_true else z3.Not(constraint)

        except Exception:
            pass

        return None

    def _extract_outputs_from_path(self, path: ExecutionPath) -> Dict[str, Any]:
        """Extract expected outputs from a path"""
        outputs = {}

        if path.return_value:
            outputs['return_value'] = str(path.return_value)

        print_outputs = [stmt for stmt in path.statements if 'print(' in stmt]
        if print_outputs:
            outputs['print_statements'] = print_outputs

        if path.variables:
            outputs['final_variables'] = {k: str(v) for k, v in path.variables.items()}

        return outputs


# Utility functions
def execute_symbolic_from_file(file_path: str) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        try:
            ir_program = json.loads(content)
            ir_program = _json_to_tuples(ir_program)
        except json.JSONDecodeError:
            content = content.replace('null', 'None')
            ir_program = ast.literal_eval(content)

        executor = SymbolicExecutor()
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from file '{file_path}': {e}")


def execute_symbolic_from_string(ir_string: str) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR string"""
    try:
        try:
            ir_program = json.loads(ir_string)
            ir_program = _json_to_tuples(ir_program)
        except json.JSONDecodeError:
            ir_string = ir_string.replace('null', 'None')
            ir_program = ast.literal_eval(ir_string)

        executor = SymbolicExecutor()
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from string: {e}")


def _json_to_tuples(json_obj):
    """Convert JSON objects back to tuples for IR processing"""
    if isinstance(json_obj, list):
        return tuple(_json_to_tuples(item) for item in json_obj)
    elif isinstance(json_obj, dict):
        return {key: _json_to_tuples(value) for key, value in json_obj.items()}
    else:
        return json_obj
