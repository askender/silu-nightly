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
        result = {
            'path_id': self.path_id,
            'conditions': [str(c) for c in self.conditions],
            'statements': self.statements,
            'return_value': str(self.return_value) if self.return_value else None,
            'variables': {k: str(v) for k, v in self.variables.items()},
            'satisfiable': True  # Default to True for backward compatibility
        }

        # Add test case information if available (from --solve option)
        if hasattr(self, 'satisfiable'):
            result['satisfiable'] = self.satisfiable
        if hasattr(self, 'test_inputs'):
            result['test_inputs'] = self.test_inputs
        if hasattr(self, 'expected_outputs'):
            result['expected_outputs'] = self.expected_outputs
        if hasattr(self, 'z3_error'):
            result['z3_error'] = self.z3_error
        if hasattr(self, 'z3_errors'):
            result['z3_errors'] = self.z3_errors

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

    def analyze_function_definition(self, func_name: str, params: List[str], body_ir: Any) -> List[ExecutionPath]:
        """Analyze all paths within a function definition"""
        # Save current state
        original_paths = self.paths
        original_current_path = self.current_path
        original_env = self.current_env
        original_counter = self.path_counter

        # Reset for function analysis
        self.paths = []
        self.current_path = ExecutionPath(f"func_{func_name}_path_0")
        self.path_counter = 1

        # Create function environment with symbolic parameters
        func_env = SymbolicEnvironment(self.global_env)
        for param in params:
            symbol = func_env.create_symbol(param)
            func_env.set_variable(param, symbol)
            self.current_path.variables[param] = symbol
            # Don't record parameter initialization - it's implicit

        self.current_env = func_env

        try:
            # Analyze function body - iterate through statements
            if isinstance(body_ir, tuple):
                for stmt in body_ir:
                    self._execute_ir(stmt)
                    # If current path ended (e.g., return statement), break
                    if self.current_path is None:
                        break
            else:
                self._execute_ir(body_ir)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"ERROR: {str(e)}")

        # Collect function paths
        if self.current_path and self.current_path.is_satisfiable():
            if self.current_path not in self.paths:
                self.paths.append(self.current_path)

        function_paths = self.paths.copy()

        # Restore original state
        self.paths = original_paths
        self.current_path = original_current_path
        self.current_env = original_env
        self.path_counter = original_counter

        return function_paths

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

        # Handle comparison operators directly
        if node_type in ['>', '<', '>=', '<=', '==', '!=']:
            return self._execute_comparison(ir_node)

        # Handle special cases for nodes that might not have handlers
        if node_type == "assign":
            return self._execute_assign(ir_node)

        # Dispatch to appropriate handler
        handler_name = f"_execute_{node_type}"
        if hasattr(self, handler_name):
            return getattr(self, handler_name)(ir_node)
        else:
            # Unknown node type, treat as concrete
            # Handle common IR nodes without cluttering statements
            if node_type in ['+', '-', '*', '/', '//', '%', '**',
                           '==', '!=', '<', '>', '<=', '>=',
                           'and', 'or', 'not']:
                # These are handled elsewhere, don't add confusing statements
                pass
            elif self.current_path:
                self.current_path.add_statement(f"# Unhandled operation: {node_type}")
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
            # Record assignments with simplified display
            simplified_value = self._simplify_value_display(value)
            self.current_path.add_statement(f"{var_name} = {simplified_value}")
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
        readable_condition = self._make_condition_readable(condition)

        if len(self.paths) >= self.max_paths:
            # Path explosion prevention
            if self.current_path:
                self.current_path.add_statement(f"Path limit reached at if condition: {condition_str}")
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Store the current state
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
            # Execute then block - check if it's a single statement or block
            if isinstance(then_block, tuple) and len(then_block) > 0 and isinstance(then_block[0], tuple):
                # It's a tuple of statements
                for stmt in then_block:
                    self._execute_ir(stmt)
                    # If current path ended (e.g., return statement), break
                    if self.current_path is None:
                        break
            else:
                # It's a single statement
                self._execute_ir(then_block)

        # Add the true path if it has content
        if self.current_path and self.current_path.is_satisfiable():
            if self.current_path not in self.paths:
                self.paths.append(self.current_path)

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
            false_path.add_statement(f"else:")

            self.current_path = false_path
            self.current_env = original_env.copy()

            # Execute else block - check if it's a single statement or block
            if isinstance(else_block, tuple) and len(else_block) > 0 and isinstance(else_block[0], tuple):
                # It's a tuple of statements
                for stmt in else_block:
                    self._execute_ir(stmt)
                    # If current path ended (e.g., return statement), break
                    if self.current_path is None:
                        break
            else:
                # It's a single statement
                self._execute_ir(else_block)

            # Add the false path if it has content
            if self.current_path and self.current_path.is_satisfiable():
                if self.current_path not in self.paths:
                    self.paths.append(self.current_path)
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
            false_path.add_statement(f"# (implicit else for if {readable_condition})")
            if false_path not in self.paths:
                self.paths.append(false_path)

        # In block context, continue with one of the paths for subsequent statements
        # Choose the first satisfiable path to continue execution
        satisfiable_paths = [path for path in self.paths if path.is_satisfiable()]
        if satisfiable_paths:
            self.current_path = satisfiable_paths[0]
        else:
            self.current_path = None
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_while(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a while loop symbolically (simplified - may create multiple paths)"""
        _, condition_ir, body_ir = ir_node
        condition = self._execute_ir(condition_ir)
        # Process the if condition to create path conditions
        condition_str = str(condition)
        readable_condition = self._make_condition_readable(condition)

        if self.current_path:
            self.current_path.add_statement(f"while {readable_condition}:")

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
        """Execute a function definition and analyze its internal paths"""
        _, func_name, params, body_ir = ir_node

        # Store the function IR for later symbolic analysis
        self.global_env.functions[func_name] = body_ir

        # Don't record function definition in statements - it's not part of execution flow
        pass

        # Analyze function's internal paths
        function_paths = self.analyze_function_definition(func_name, params, body_ir)

        # Store function paths for reporting
        if not hasattr(self, 'function_analyses'):
            self.function_analyses = {}
        self.function_analyses[func_name] = function_paths

        # Don't record path count analysis - not useful for understanding program flow
        pass

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_call(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function call symbolically"""
        if len(ir_node) == 4:
            _, func_name, args_ir, kwargs_ir = ir_node
        else:
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
            simplified_value = self._simplify_value_display(value)
            self.current_path.add_statement(f"return {simplified_value}")

            # Add current path to paths list if not already there
            if self.current_path not in self.paths:
                self.paths.append(self.current_path)

        # End current path on return
        self.current_path = None
        return value

    def _execute_binary_op(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a binary operation symbolically"""
        _, left_ir, op, right_ir = ir_node
        left = self._execute_ir(left_ir)
        right = self._execute_ir(right_ir)

        # Create symbolic expression
        expr = f"({left} {op} {right})"
        result = SymbolicValue(SymbolicValueType.EXPRESSION, expr)

        # Don't record every binary operation - too verbose
        pass

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
            # If current path ended, stop execution
            if self.current_path is None:
                break
        return result or SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_comparison(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a comparison operation"""
        op, left_ir, right_ir = ir_node
        left = self._execute_ir(left_ir)
        right = self._execute_ir(right_ir)

        # Create comparison expression
        expr = f"{left} {op} {right}"
        return SymbolicValue(SymbolicValueType.EXPRESSION, expr)

    # Built-in function handlers for symbolic execution
    def _symbolic_print(self, *args) -> SymbolicValue:
        """Symbolic version of print function"""
        args_str = ", ".join(str(arg) for arg in args)
        if self.current_path:
            self.current_path.add_statement(f"print({self._simplify_args_display(args)})")
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
        report = {
            'total_paths': len(paths),
            'satisfiable_paths': len([p for p in paths if p.is_satisfiable()]),
            'paths': [path.to_dict() for path in paths],
            'summary': {
                'functions_analyzed': len(self.global_env.functions),
                'max_path_length': max(len(p.statements) for p in paths) if paths else 0,
                'max_conditions': max(len(p.conditions) for p in paths) if paths else 0,
            }
        }

        # Add function analysis details if available
        if hasattr(self, 'function_analyses'):
            report['function_analyses'] = {}
            for func_name, func_paths in self.function_analyses.items():
                report['function_analyses'][func_name] = {
                    'total_paths': len(func_paths),
                    'satisfiable_paths': len([p for p in func_paths if p.is_satisfiable()]),
                    'paths': [path.to_dict() for path in func_paths]
                }

        return report

    def simplify_path_conditions(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Simplify and merge path conditions where possible"""
        simplified_paths = []

        for path in paths:
            if not path.conditions:
                simplified_paths.append(path)
                continue

            # Create a new path with simplified conditions
            new_path = ExecutionPath(path.path_id)
            new_path.statements = path.statements.copy()
            new_path.return_value = path.return_value
            new_path.variables = path.variables.copy()

            # Group conditions by variable
            condition_groups = self._group_conditions_by_variable(path.conditions)

            # Simplify each group
            simplified_conditions = []
            for variable, conditions in condition_groups.items():
                if len(conditions) > 1:
                    merged = self._merge_conditions_for_variable(variable, conditions)
                    simplified_conditions.extend(merged)
                else:
                    simplified_conditions.extend(conditions)

            # Add ungrouped conditions (those that don't involve simple variable comparisons)
            for condition in path.conditions:
                if not self._is_simple_variable_condition(condition.expression):
                    simplified_conditions.append(condition)

            new_path.conditions = simplified_conditions
            simplified_paths.append(new_path)

        return simplified_paths

    def _group_conditions_by_variable(self, conditions: List[PathCondition]) -> Dict[str, List[PathCondition]]:
        """Group conditions by the variable they constrain"""
        groups = {}

        for condition in conditions:
            variable = self._extract_variable_from_condition(condition.expression)
            if variable:
                if variable not in groups:
                    groups[variable] = []
                groups[variable].append(condition)

        return groups

    def _extract_variable_from_condition(self, expression: str) -> Optional[str]:
        """Extract variable name from simple comparison expressions"""
        import re

        # Match patterns like "x > 5", "x <= 10", etc. with optional whitespace
        pattern = r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*([><=!]+)\s*(.+)\s*$'
        match = re.match(pattern, expression.strip())
        if match:
            return match.group(1)

        return None

    def _is_simple_variable_condition(self, expression: str) -> bool:
        """Check if condition is a simple variable comparison"""
        return self._extract_variable_from_condition(expression) is not None

    def _merge_conditions_for_variable(self, variable: str, conditions: List[PathCondition]) -> List[PathCondition]:
        """Merge conditions for a single variable"""
        if len(conditions) <= 1:
            return conditions

        # For now, implement basic merging for common patterns
        # Example: "not (x > 10)" and "not (x > 0)" -> "x <= 0"

        # Separate positive and negative conditions
        positive_conditions = [c for c in conditions if c.is_true]
        negative_conditions = [c for c in conditions if not c.is_true]

        # Try to merge negative conditions (not operators)
        merged_negative = self._merge_negative_conditions(variable, negative_conditions)

        # For now, keep positive conditions as-is
        # In a more advanced implementation, we could merge these too

        result = positive_conditions + merged_negative
        return result if result else conditions

    def _merge_negative_conditions(self, variable: str, conditions: List[PathCondition]) -> List[PathCondition]:
        """Merge negative conditions like 'not (x > 10)' and 'not (x > 0)'"""
        if len(conditions) <= 1:
            return conditions

        import re

        # Extract comparison operations and values
        greater_than_values = []
        greater_equal_values = []
        less_than_values = []
        less_equal_values = []

        for condition in conditions:
            # Pattern: variable operator value
            pattern = f'^{re.escape(variable)}\\s*([><=]+)\\s*(.+)$'
            match = re.match(pattern, condition.expression)

            if match:
                operator = match.group(1).strip()
                try:
                    value = float(match.group(2).strip())

                    if operator == '>':
                        greater_than_values.append(value)
                    elif operator == '>=':
                        greater_equal_values.append(value)
                    elif operator == '<':
                        less_than_values.append(value)
                    elif operator == '<=':
                        less_equal_values.append(value)
                except ValueError:
                    # If we encounter non-numeric values, return original conditions
                    return conditions

        # Merge logic: not (x > a) and not (x > b) -> not (x > min(a,b)) -> x <= min(a,b)
        if greater_than_values:
            min_value = min(greater_than_values)
            merged_expr = f"{variable} <= {min_value}"
            return [PathCondition(merged_expr, True)]

        # Similar logic for other operators could be added here

        # If we can't merge, return original conditions
        return conditions

    def enhance_paths_with_test_cases(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Enhance execution paths with Z3-generated test case information"""
        if not Z3_AVAILABLE:
            # Just return paths with a note that Z3 is not available
            for path in paths:
                if not hasattr(path, 'z3_error'):
                    path.z3_error = "Z3 solver not available. Install with: pip install z3-solver"
            return paths

        enhanced_paths = []

        for path in paths:
            # Create a copy of the path
            enhanced_path = ExecutionPath(path.path_id)
            enhanced_path.conditions = path.conditions.copy()
            enhanced_path.statements = path.statements.copy()
            enhanced_path.return_value = path.return_value
            enhanced_path.variables = path.variables.copy()

            if not path.conditions:
                # No conditions, mark as satisfiable with empty test inputs
                enhanced_path.satisfiable = True
                enhanced_path.test_inputs = {}
                enhanced_path.expected_outputs = self._extract_outputs_from_path(path)
            else:
                # Create Z3 solver
                solver = z3.Solver()
                var_map = {}

                # Convert conditions to Z3 constraints
                for condition in path.conditions:
                    try:
                        z3_constraint = self._condition_to_z3(condition, var_map, solver)
                        if z3_constraint is not None:
                            solver.add(z3_constraint)
                    except Exception as e:
                        # Mark conversion error
                        if not hasattr(enhanced_path, 'z3_errors'):
                            enhanced_path.z3_errors = []
                        enhanced_path.z3_errors.append(f"Condition '{condition}': {e}")

                # Check satisfiability
                if solver.check() == z3.sat:
                    enhanced_path.satisfiable = True
                    model = solver.model()
                    test_inputs = {}

                    # Extract concrete values from the model
                    for var_name, z3_var in var_map.items():
                        if model[z3_var] is not None:
                            value = model[z3_var]
                            # Convert Z3 value to Python value
                            if z3.is_int_value(value):
                                test_inputs[var_name] = value.as_long()
                            elif z3.is_real_value(value):
                                test_inputs[var_name] = float(value.as_fraction())
                            elif z3.is_bool(value):
                                test_inputs[var_name] = z3.is_true(value)
                            else:
                                test_inputs[var_name] = str(value)

                    enhanced_path.test_inputs = test_inputs
                    enhanced_path.expected_outputs = self._extract_outputs_from_path(path)
                else:
                    enhanced_path.satisfiable = False
                    enhanced_path.test_inputs = None
                    enhanced_path.expected_outputs = None

            enhanced_paths.append(enhanced_path)

        return enhanced_paths

    def _condition_to_z3(self, condition: PathCondition, var_map: Dict[str, Any], solver: z3.Solver) -> Any:
        """Convert a path condition to Z3 constraint"""
        expr = condition.expression.strip()

        # Try to parse the expression as a tuple (symbolic expression)
        try:
            if expr.startswith("(") and expr.endswith(")"):
                # Try to evaluate as Python literal to get the tuple structure
                parsed_expr = ast.literal_eval(expr)
                z3_constraint = self._tuple_expr_to_z3(parsed_expr, var_map, solver)
                if z3_constraint is not None:
                    return z3_constraint if condition.is_true else z3.Not(z3_constraint)
        except (ValueError, SyntaxError):
            pass

        # Handle basic comparison operations
        for op in ['>=', '<=', '==', '!=', '>', '<']:
            if op in expr:
                left, right = expr.split(op, 1)
                left = left.strip()
                right = right.strip()

                # Get or create Z3 variables
                left_z3 = self._expr_to_z3(left, var_map, solver)
                right_z3 = self._expr_to_z3(right, var_map, solver)

                if left_z3 is None or right_z3 is None:
                    return None

                # Create Z3 constraint
                if op == '>=':
                    constraint = left_z3 >= right_z3
                elif op == '<=':
                    constraint = left_z3 <= right_z3
                elif op == '==':
                    constraint = left_z3 == right_z3
                elif op == '!=':
                    constraint = left_z3 != right_z3
                elif op == '>':
                    constraint = left_z3 > right_z3
                elif op == '<':
                    constraint = left_z3 < right_z3

                # Apply negation if needed
                return constraint if condition.is_true else z3.Not(constraint)

        # Handle boolean expressions
        if expr in var_map:
            z3_var = var_map[expr]
            return z3_var if condition.is_true else z3.Not(z3_var)

        return None

    def _expr_to_z3(self, expr, var_map: Dict[str, Any], solver: z3.Solver) -> Any:
        """Convert an expression to Z3 variable or constant"""

        # Handle tuple expressions (from symbolic execution)
        if isinstance(expr, tuple):
            return self._tuple_expr_to_z3(expr, var_map, solver)

        # Handle string expressions
        if not isinstance(expr, str):
            expr = str(expr)

        expr = expr.strip()

        # Try to parse as integer
        try:
            return z3.IntVal(int(expr))
        except ValueError:
            pass

        # Try to parse as float
        try:
            return z3.RealVal(float(expr))
        except ValueError:
            pass

        # Try to parse as boolean
        if expr.lower() in ['true', 'false']:
            return z3.BoolVal(expr.lower() == 'true')

        # Treat as variable name
        if expr not in var_map:
            # Create appropriate Z3 variable based on context
            # For now, assume integer variables (could be enhanced with type inference)
            var_map[expr] = z3.Int(expr)

        return var_map[expr]

    def _extract_outputs_from_path(self, path: ExecutionPath) -> Dict[str, Any]:
        """Extract expected outputs from a path (e.g., print statements, return values)"""
        outputs = {}

        # Extract return value
        if path.return_value:
            outputs['return_value'] = str(path.return_value)

        # Extract print statements
        print_outputs = []
        for statement in path.statements:
            if 'print(' in statement:
                # Simple extraction - could be enhanced
                print_outputs.append(statement)

        if print_outputs:
            outputs['print_statements'] = print_outputs

        # Extract final variable values
        final_vars = {}
        for var_name, var_value in path.variables.items():
            final_vars[var_name] = str(var_value)

        if final_vars:
            outputs['final_variables'] = final_vars

        return outputs

    def renumber_paths_sequentially(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Renumber paths sequentially starting from 1 for cleaner output"""
        renumbered_paths = []
        for i, path in enumerate(paths, 1):
            new_path = ExecutionPath(f"path_{i}")
            new_path.conditions = path.conditions
            new_path.statements = path.statements
            new_path.return_value = path.return_value
            new_path.variables = path.variables
            renumbered_paths.append(new_path)
        return renumbered_paths

    def _tuple_expr_to_z3(self, expr, var_map: Dict[str, Any], solver: z3.Solver) -> Any:
        """Convert tuple expression to Z3 constraint"""
        if not isinstance(expr, tuple) or len(expr) < 2:
            return None

        op = expr[0]

        if op == 'and':
            # Handle logical AND
            if len(expr) >= 3:
                left = self._tuple_expr_to_z3(expr[1], var_map, solver)
                right = self._tuple_expr_to_z3(expr[2], var_map, solver)
                if left is not None and right is not None:
                    return z3.And(left, right)

        elif op == 'or':
            # Handle logical OR
            if len(expr) >= 3:
                left = self._tuple_expr_to_z3(expr[1], var_map, solver)
                right = self._tuple_expr_to_z3(expr[2], var_map, solver)
                if left is not None and right is not None:
                    return z3.Or(left, right)

        elif op in ['>', '<', '>=', '<=', '==', '!=']:
            # Handle comparison operations
            if len(expr) >= 3:
                left = self._expr_to_z3(expr[1], var_map, solver)
                right = self._expr_to_z3(expr[2], var_map, solver)
                if left is not None and right is not None:
                    if op == '>':
                        return left > right
                    elif op == '<':
                        return left < right
                    elif op == '>=':
                        return left >= right
                    elif op == '<=':
                        return left <= right
                    elif op == '==':
                        return left == right
                    elif op == '!=':
                        return left != right

        return None

    def _expr_to_z3(self, expr, var_map: Dict[str, Any], solver: z3.Solver) -> Any:
        """Convert an expression to Z3 variable or constant"""

        # Handle tuple expressions (from symbolic execution)
        if isinstance(expr, tuple):
            return self._tuple_expr_to_z3(expr, var_map, solver)

        # Handle string expressions
        if not isinstance(expr, str):
            expr = str(expr)

        expr = expr.strip()

        # Try to parse as integer
        try:
            return z3.IntVal(int(expr))
        except ValueError:
            pass

        # Try to parse as float
        try:
            return z3.RealVal(float(expr))
        except ValueError:
            pass

        # Try to parse as boolean
        if expr.lower() in ['true', 'false']:
            return z3.BoolVal(expr.lower() == 'true')

        # Treat as variable name
        if expr not in var_map:
            # Create appropriate Z3 variable based on context
            # For now, assume integer variables (could be enhanced with type inference)
            var_map[expr] = z3.Int(expr)

        return var_map[expr]

    def _make_condition_readable(self, condition) -> str:
        """Convert IR condition to readable format with recursive tuple handling"""
        # Handle SymbolicValue objects first
        if hasattr(condition, 'value') and hasattr(condition, 'type'):
            return self._make_condition_readable(condition.value)

        # Use shared conversion function for basic cases
        try:
            return make_expression_readable(condition)
        except Exception:
            pass

        # Handle string representations of complex expressions
        if isinstance(condition, str):
            # Handle expressions like "('+', 'a', 'b') > ('+', 'c', 'd')"
            import re

            # Pattern to match expressions with operators between tuple-like structures
            pattern = r"(\([^)]+\))\s*([><=!]+)\s*(\([^)]+\))"
            match = re.match(pattern, condition.strip())

            if match:
                left_expr, operator, right_expr = match.groups()
                try:
                    left_parsed = eval(left_expr)
                    right_parsed = eval(right_expr)
                    left_readable = self._make_condition_readable(left_parsed)
                    right_readable = self._make_condition_readable(right_parsed)
                    return f"{left_readable} {operator} {right_readable}"
                except:
                    pass

            # Handle simple tuple-like expressions
            elif condition.startswith("(") and condition.endswith(")") and "', '" in condition:
                try:
                    parsed = eval(condition)
                    if isinstance(parsed, tuple):
                        return self._make_condition_readable(parsed)
                except:
                    pass

        return str(condition)


    def _simplify_value_display(self, value) -> str:
        """Simplify value display for better readability in statements"""
        # Handle SymbolicValue objects first
        if hasattr(value, 'type') and hasattr(value, 'value'):
            if value.type == SymbolicValueType.CONCRETE:
                return str(value.value)
            elif value.type == SymbolicValueType.SYMBOLIC:
                return value.name if hasattr(value, 'name') and value.name else str(value.value)
            elif value.type == SymbolicValueType.EXPRESSION:
                # Recursively process the expression value
                return self._simplify_value_display(value.value)

        # Handle simple SymbolicValue objects by name
        elif hasattr(value, 'name') and value.name:
            return value.name

        # Use shared conversion function for other cases
        try:
            return simplify_value_display(value)
        except Exception:
            pass

        # Handle tuple-like expressions in string format: "('+', 'x', 1)"
        if isinstance(value, str) and value.startswith("(") and value.endswith(")") and "', '" in value:
            try:
                # Try to parse as tuple and recursively process
                parsed = eval(value)
                if isinstance(parsed, tuple):
                    return self._simplify_value_display(parsed)
            except:
                # If parsing fails, return as is
                pass

        # Default string representation
        return str(value)

    def _simplify_args_display(self, args) -> str:
        """Simplify argument display for function calls"""
        simplified_args = []
        for arg in args:
            simplified_args.append(self._simplify_value_display(arg))
        return ", ".join(simplified_args)





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
