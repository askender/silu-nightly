#!/usr/bin/env python3
"""
Symbolic Execution Engine for Silu Language

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
        # Simple contradiction detection
        expressions = {}
        for condition in self.conditions:
            if condition.expression in expressions:
                if expressions[condition.expression] != condition.is_true:
                    return False
            expressions[condition.expression] = condition.is_true
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'path_id': self.path_id,
            'conditions': [str(c) for c in self.conditions],
            'statements': self.statements,
            'return_value': str(self.return_value) if self.return_value else None,
            'variables': {k: str(v) for k, v in self.variables.items()},
            'satisfiable': self.is_satisfiable()
        }


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
            # Create a new symbolic variable for undefined variables
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
        self.max_paths = 100  # Limit to prevent infinite path explosion

        # Initialize built-in functions
        self._init_builtins()

    def _init_builtins(self):
        """Initialize built-in functions"""
        builtins = {
            'print': self._symbolic_print,
            'int': self._symbolic_int,
            'float': self._symbolic_float,
            'str': self._symbolic_str,
            'bool': self._symbolic_bool,
            'type': self._symbolic_type,
            'isinstance': self._symbolic_isinstance,
            'len': self._symbolic_len,
        }
        self.global_env.functions.update(builtins)

    def execute_program(self, ir_program: Tuple) -> List[ExecutionPath]:
        """Execute an IR program symbolically and return all paths"""
        if not ir_program or ir_program[0] != "module":
            raise ValueError("Invalid IR program format")

        self.paths = []
        self.current_path = ExecutionPath(f"path_0")
        self.path_counter = 1

        # Execute the module
        try:
            self._execute_ir(ir_program)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"ERROR: {str(e)}")

        # Add the current path if it exists and we haven't added it yet
        if self.current_path and self.current_path.is_satisfiable():
            # Only add if not already in paths
            if self.current_path not in self.paths:
                self.paths.append(self.current_path)

        return self.paths

    def analyze_function(self, function_name: str, parameters: List[str]) -> List[ExecutionPath]:
        """Analyze a specific function symbolically"""
        if function_name not in self.global_env.functions:
            raise ValueError(f"Function '{function_name}' not found")

        # Create symbolic parameters
        self.current_path = ExecutionPath(f"path_0")
        param_env = SymbolicEnvironment(self.global_env)

        for param in parameters:
            symbol = param_env.create_symbol(param)
            param_env.set_variable(param, symbol)

        # Execute the function symbolically
        self.current_env = param_env
        func_ir = self.global_env.functions[function_name]

        try:
            self._execute_ir(func_ir)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"ERROR: {str(e)}")

        if self.current_path and self.current_path.is_satisfiable():
            self.paths.append(self.current_path)

        return self.paths

    def _execute_ir(self, ir_node: Any) -> SymbolicValue:
        """Execute an IR node symbolically"""
        if not isinstance(ir_node, tuple) or len(ir_node) == 0:
            if isinstance(ir_node, (int, float, str, bool)):
                return SymbolicValue(SymbolicValueType.CONCRETE, ir_node)
            elif isinstance(ir_node, str):
                # Variable reference
                return self.current_env.get_variable(ir_node)
            else:
                return SymbolicValue(SymbolicValueType.CONCRETE, ir_node)

        node_type = ir_node[0]

        # Dispatch to appropriate handler
        handler_name = f"_execute_{node_type}"
        if hasattr(self, handler_name):
            return getattr(self, handler_name)(ir_node)
        else:
            # Unknown node type, treat as concrete
            if self.current_path:
                self.current_path.add_statement(f"Unknown IR node: {node_type}")
            return SymbolicValue(SymbolicValueType.CONCRETE, ir_node)

    def _execute_module(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a module IR node"""
        _, statements = ir_node
        result = None
        for stmt in statements:
            result = self._execute_ir(stmt)
            # If we hit a return statement or the current path ended, break
            if self.current_path is None:
                break
        return result or SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_assign(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an assignment IR node"""
        _, var_name, value_ir, _ = ir_node
        value = self._execute_ir(value_ir)
        self.current_env.set_variable(var_name, value)

        if self.current_path:
            self.current_path.add_statement(f"{var_name} = {value}")
            self.current_path.variables[var_name] = value

        return value

    def _execute_if(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an if statement symbolically - creates multiple paths"""
        if len(ir_node) == 4:
            _, condition_ir, then_block, else_block = ir_node
        else:
            _, condition_ir, then_block = ir_node
            else_block = None

        condition = self._execute_ir(condition_ir)
        condition_str = str(condition)

        if len(self.paths) >= self.max_paths:
            # Path explosion prevention
            if self.current_path:
                self.current_path.add_statement(f"Path limit reached at if condition: {condition_str}")
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Store the current state
        original_path = self.current_path
        original_env = self.current_env.copy()
        paths_to_continue = []

        # True path
        true_path = ExecutionPath(f"path_{self.path_counter}")
        self.path_counter += 1
        if original_path:
            true_path.conditions = original_path.conditions.copy()
            true_path.statements = original_path.statements.copy()
            true_path.variables = original_path.variables.copy()

        true_condition = PathCondition(condition_str, True)
        true_path.add_condition(true_condition)

        self.current_path = true_path
        self.current_env = original_env.copy()

        if then_block:
            self._execute_ir(then_block)

        if self.current_path and self.current_path.is_satisfiable():
            paths_to_continue.append(self.current_path)

        # False path (if there's an else block)
        if else_block:
            false_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            if original_path:
                false_path.conditions = original_path.conditions.copy()
                false_path.statements = original_path.statements.copy()
                false_path.variables = original_path.variables.copy()

            false_condition = PathCondition(condition_str, False)
            false_path.add_condition(false_condition)

            self.current_path = false_path
            self.current_env = original_env.copy()

            self._execute_ir(else_block)

            if self.current_path and self.current_path.is_satisfiable():
                paths_to_continue.append(self.current_path)
        else:
            # No else block - create a path for the false condition
            false_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            if original_path:
                false_path.conditions = original_path.conditions.copy()
                false_path.statements = original_path.statements.copy()
                false_path.variables = original_path.variables.copy()

            false_condition = PathCondition(condition_str, False)
            false_path.add_condition(false_condition)
            paths_to_continue.append(false_path)

        # Store all paths and continue with the first one
        # In a real implementation, we would need to handle all paths
        # For now, we just pick one to continue the execution
        for path in paths_to_continue:
            if path not in self.paths:
                self.paths.append(path)

        # Continue with the first path for subsequent statements
        if paths_to_continue:
            self.current_path = paths_to_continue[0]
        else:
            self.current_path = None

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_while(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a while loop symbolically (simplified - may create multiple paths)"""
        _, condition_ir, body_ir = ir_node
        condition = self._execute_ir(condition_ir)
        condition_str = str(condition)

        if self.current_path:
            self.current_path.add_statement(f"while {condition_str}:")

        # For symbolic execution, we consider both entering and not entering the loop
        # This is a simplified approach - more sophisticated analysis would unroll loops

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
        _, func_name, params, body_ir = ir_node

        # Store the function IR for later symbolic analysis
        self.global_env.functions[func_name] = body_ir

        if self.current_path:
            self.current_path.add_statement(f"def {func_name}({', '.join(params)}):")

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_call(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function call symbolically"""
        _, func_name, args_ir = ir_node
        args = [self._execute_ir(arg) for arg in args_ir]

        if func_name in self.global_env.functions:
            func_handler = self.global_env.functions[func_name]
            if callable(func_handler):
                # Built-in function
                result = func_handler(*args)
                if self.current_path:
                    args_str = ", ".join(str(arg) for arg in args)
                    self.current_path.add_statement(f"{func_name}({args_str})")
                return result
            else:
                # User-defined function - create symbolic return value
                return_symbol = self.current_env.create_symbol(f"{func_name}_return")
                if self.current_path:
                    args_str = ", ".join(str(arg) for arg in args)
                    self.current_path.add_statement(f"{return_symbol} = {func_name}({args_str})")
                return return_symbol
        else:
            # Unknown function
            result = self.current_env.create_symbol(f"unknown_{func_name}")
            if self.current_path:
                args_str = ", ".join(str(arg) for arg in args)
                self.current_path.add_statement(f"{result} = {func_name}({args_str}) # unknown function")
            return result

    def _execute_return(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a return statement"""
        if len(ir_node) > 1:
            _, value_ir = ir_node
            value = self._execute_ir(value_ir)
        else:
            value = SymbolicValue(SymbolicValueType.CONCRETE, None)

        if self.current_path:
            self.current_path.return_value = value
            self.current_path.add_statement(f"return {value}")

        return value

    def _execute_binary_op(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a binary operation symbolically"""
        _, left_ir, op, right_ir = ir_node
        left = self._execute_ir(left_ir)
        right = self._execute_ir(right_ir)

        # Create symbolic expression
        expr = f"({left} {op} {right})"
        result = SymbolicValue(SymbolicValueType.EXPRESSION, expr)

        if self.current_path:
            self.current_path.add_statement(f"# Binary operation: {expr}")

        return result

    def _execute_chained_compare(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a chained comparison symbolically"""
        _, *comparisons = ir_node

        # Build the comparison expression
        expr_parts = []
        for i in range(0, len(comparisons), 2):
            if i + 1 < len(comparisons):
                left = self._execute_ir(comparisons[i])
                op = comparisons[i + 1]
                if i + 2 < len(comparisons):
                    right = self._execute_ir(comparisons[i + 2])
                    expr_parts.append(f"{left} {op} {right}")

        expr = " and ".join(expr_parts)
        result = SymbolicValue(SymbolicValueType.EXPRESSION, expr)

        return result

    def _execute_block(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a block of statements"""
        _, statements = ir_node
        result = None
        for stmt in statements:
            result = self._execute_ir(stmt)
        return result or SymbolicValue(SymbolicValueType.CONCRETE, None)

    # Built-in function handlers for symbolic execution
    def _symbolic_print(self, *args) -> SymbolicValue:
        """Symbolic version of print function"""
        args_str = ", ".join(str(arg) for arg in args)
        if self.current_path:
            self.current_path.add_statement(f"print({args_str})")
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _symbolic_int(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of int conversion"""
        if value.type == SymbolicValueType.CONCRETE:
            try:
                return SymbolicValue(SymbolicValueType.CONCRETE, int(value.value))
            except (ValueError, TypeError):
                return SymbolicValue(SymbolicValueType.EXPRESSION, f"int({value})")
        else:
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"int({value})")

    def _symbolic_float(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of float conversion"""
        if value.type == SymbolicValueType.CONCRETE:
            try:
                return SymbolicValue(SymbolicValueType.CONCRETE, float(value.value))
            except (ValueError, TypeError):
                return SymbolicValue(SymbolicValueType.EXPRESSION, f"float({value})")
        else:
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"float({value})")

    def _symbolic_str(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of str conversion"""
        if value.type == SymbolicValueType.CONCRETE:
            return SymbolicValue(SymbolicValueType.CONCRETE, str(value.value))
        else:
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"str({value})")

    def _symbolic_bool(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of bool conversion"""
        if value.type == SymbolicValueType.CONCRETE:
            return SymbolicValue(SymbolicValueType.CONCRETE, bool(value.value))
        else:
            return SymbolicValue(SymbolicValueType.EXPRESSION, f"bool({value})")

    def _symbolic_type(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of type function"""
        return SymbolicValue(SymbolicValueType.EXPRESSION, f"type({value})")

    def _symbolic_isinstance(self, value: SymbolicValue, type_obj: SymbolicValue) -> SymbolicValue:
        """Symbolic version of isinstance function"""
        return SymbolicValue(SymbolicValueType.EXPRESSION, f"isinstance({value}, {type_obj})")

    def _symbolic_len(self, value: SymbolicValue) -> SymbolicValue:
        """Symbolic version of len function"""
        return SymbolicValue(SymbolicValueType.EXPRESSION, f"len({value})")

    def generate_report(self, paths: List[ExecutionPath]) -> Dict[str, Any]:
        """Generate a comprehensive report of symbolic execution results"""
        return {
            'total_paths': len(paths),
            'satisfiable_paths': len([p for p in paths if p.is_satisfiable()]),
            'paths': [path.to_dict() for path in paths],
            'summary': {
                'functions_analyzed': len(self.global_env.functions),
                'max_path_length': max(len(p.statements) for p in paths) if paths else 0,
                'max_conditions': max(len(p.conditions) for p in paths) if paths else 0,
            }
        }


def execute_symbolic_from_file(file_path: str) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        # Try to parse as JSON first
        try:
            ir_program = json.loads(content)
            # Convert JSON lists to tuples for IR processing
            ir_program = _json_to_tuples(ir_program)
        except json.JSONDecodeError:
            # Try to evaluate as Python literal - handle None values
            content = content.replace('null', 'None')
            ir_program = ast.literal_eval(content)

        executor = SymbolicExecutor()
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from file '{file_path}': {e}")


def execute_symbolic_from_string(ir_string: str) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR string"""
    try:
        # Try to parse as JSON first
        try:
            ir_program = json.loads(ir_string)
            # Convert JSON lists to tuples for IR processing
            ir_program = _json_to_tuples(ir_program)
        except json.JSONDecodeError:
            # Try to evaluate as Python literal - handle None values
            ir_string = ir_string.replace('null', 'None')
            ir_program = ast.literal_eval(ir_string)

        executor = SymbolicExecutor()
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from string: {e}")


# Utility functions for JSON serialization
def _json_to_tuples(json_obj):
    """Convert JSON objects back to tuples for IR processing"""
    if isinstance(json_obj, list):
        return tuple(_json_to_tuples(item) for item in json_obj)
    elif isinstance(json_obj, dict):
        return {key: _json_to_tuples(value) for key, value in json_obj.items()}
    else:
        return json_obj
