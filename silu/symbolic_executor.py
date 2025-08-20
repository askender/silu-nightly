#!/usr/bin/env python3
"""
Enhanced Symbolic Execution Engine for Silu Language

This module provides symbolic execution capabilities for Silu programs,
allowing analysis of all possible execution paths and generation of
path constraints for functions with improved Z3 integration and loop handling.
"""

from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import ast
from copy import deepcopy

# Import enhanced symbolic execution utilities
from .symbolic.z3_utils import (
    Z3_AVAILABLE, to_z3_expr, simplify_range_cond, is_sat,
    get_boolop_func, get_cmp_func, get_binop_func, check_path_satisfiability
)
from .symbolic.loop_utils import (
    LoopAnalyzer, LoopBound
)
from .symbolic.builtin_utils import (
    create_builtin_functions_dict, symbolic_print, simplify_args_display
)
from .symbolic.condition_utils import (
    extract_variable_from_condition, is_simple_variable_condition,
    group_conditions_by_variable, merge_conditions_for_variable, make_condition_readable,
    simplify_conditions_list
)
from .symbolic.report_utils import (
    generate_report, generate_fast_report, ReportFormat, extract_test_cases
)

# Import shared conversion functions
from .ir_to_source import make_expression_readable, simplify_value_display

# Import Z3 for enhanced symbolic execution
if Z3_AVAILABLE:
    from z3 import Int, IntVal, BoolVal, simplify, And, Not, Or, If, ArrayRef, Store, BoolSort


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
    original_ir: Optional[Tuple] = None

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
    z3_constraint: Optional[Any] = None

    def __str__(self) -> str:
        if self.is_true:
            return self.expression
        return f"not ({self.expression})"

    def negate(self) -> 'PathCondition':
        """Return the negated condition"""
        negated_constraint = None
        if self.z3_constraint is not None and Z3_AVAILABLE:
            from z3 import Not
            negated_constraint = Not(self.z3_constraint)

        return PathCondition(
            expression=self.expression,
            is_true=not self.is_true,
            source_line=self.source_line,
            z3_constraint=negated_constraint
        )


@dataclass
class ExecutionPath:
    """Represents a single execution path through a function"""
    path_id: str
    conditions: List[PathCondition] = field(default_factory=list)
    statements: List[str] = field(default_factory=list)
    return_value: Optional[SymbolicValue] = None
    variables: Dict[str, SymbolicValue] = field(default_factory=dict)
    loop_iterations: Dict[str, int] = field(default_factory=dict)
    satisfiable: bool = True
    test_inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: Dict[str, Any] = field(default_factory=dict)
    z3_error: Optional[str] = None

    def add_condition(self, condition: PathCondition):
        """Add a path condition"""
        self.conditions.append(condition)

    def add_statement(self, statement: str):
        """Add an executed statement"""
        self.statements.append(statement)

    def is_satisfiable(self) -> bool:
        """Check if the path conditions are satisfiable using enhanced Z3 checking"""
        if not self.conditions:
            return True

        # Use Z3-based satisfiability checking if available
        if Z3_AVAILABLE:
            condition_strs = [str(c) for c in self.conditions]
            is_sat, _ = check_path_satisfiability(condition_strs)
            return is_sat

        # Fallback to basic logical contradiction checking
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
            'satisfiable': getattr(self, 'satisfiable', True),
            'loop_iterations': self.loop_iterations
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
        self.z3_variables: Dict[str, Any] = {}

    def create_symbol(self, name: str = None, var_type: str = "int") -> SymbolicValue:
        """Create a new symbolic value with optional Z3 variable"""
        if not name:
            name = f"sym_{self.symbol_counter}"
            self.symbol_counter += 1

        # Create Z3 variable if available
        if Z3_AVAILABLE and name not in self.z3_variables:
            from .symbolic.z3_utils import create_z3_variable
            self.z3_variables[name] = create_z3_variable(name, var_type)

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
        new_env.z3_variables = self.z3_variables.copy()
        return new_env


class SymbolicExecutor:
    """Enhanced symbolic execution engine for Silu IR"""

    def __init__(self, include_function_paths=False, performance_mode=False):
        self.global_env = SymbolicEnvironment()
        self.current_env = self.global_env
        self.paths: List[ExecutionPath] = []
        self.current_path: Optional[ExecutionPath] = None
        self.path_counter = 0
        self.max_paths = 100
        self.max_loop_iterations = 5
        self.loop_analyzer = LoopAnalyzer(max_iterations=self.max_loop_iterations)
        self.function_analyses: Dict[str, List[ExecutionPath]] = {}
        self.include_function_paths = include_function_paths
        self.performance_mode = performance_mode

        # Performance optimizations
        if performance_mode:
            self.max_loop_iterations = 3
            self.max_paths = 50

        # Initialize built-in functions
        self._init_builtins()

    def _init_builtins(self):
        """Initialize built-in functions using utility module"""
        builtins = create_builtin_functions_dict(self.current_path)
        self.global_env.functions.update(builtins)

    def _enhanced_ast_to_z3(self, node, var_dict):
        """Enhanced AST to Z3 conversion with support for more node types"""
        if not Z3_AVAILABLE:
            return None

        if isinstance(node, ast.BoolOp):
            return simplify(get_boolop_func(node.op)(*[self._enhanced_ast_to_z3(v, var_dict) for v in node.values]))

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                operand = self._enhanced_ast_to_z3(node.operand, var_dict)
                if operand and Z3_AVAILABLE:
                    try:
                        if hasattr(operand, 'sort') and operand.sort() != BoolSort():
                            operand = operand != 0
                    except:
                        pass
                return Not(operand) if operand else None
            return None

        if isinstance(node, ast.Compare):
            left = self._enhanced_ast_to_z3(node.left, var_dict)
            if not left:
                return None

            op = node.ops[0]
            right_node = node.comparators[0]

            if isinstance(op, (ast.In, ast.NotIn)):
                return self._handle_in_notin(left, op, right_node, var_dict)

            right = self._enhanced_ast_to_z3(right_node, var_dict)
            if not right:
                return None

            return get_cmp_func(op)(left, right)

        if isinstance(node, ast.BinOp):
            left = self._enhanced_ast_to_z3(node.left, var_dict)
            right = self._enhanced_ast_to_z3(node.right, var_dict)
            if not left or not right:
                return None
            return get_binop_func(node.op)(left, right)

        if isinstance(node, ast.Subscript):
            value = self._enhanced_ast_to_z3(node.value, var_dict)
            if not value:
                return None

            # Handle different slice types
            if isinstance(node.slice, ast.Slice):
                # Slice operations - simplified handling
                return value  # For now, return the original value
            elif isinstance(node.slice, ast.Constant):
                idx = node.slice.value
                return self._handle_subscript(value, idx, var_dict)
            elif isinstance(node.slice, ast.Name):
                idx = var_dict.get(node.slice.id)
                if idx is None:
                    idx = Int(node.slice.id)
                    var_dict[node.slice.id] = idx
                return self._handle_subscript(value, idx, var_dict)
            else:
                idx = self._enhanced_ast_to_z3(node.slice, var_dict)
                return self._handle_subscript(value, idx, var_dict) if idx else None

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return None

            func_name = node.func.id

            if func_name == 'int':
                if node.args:
                    return self._enhanced_ast_to_z3(node.args[0], var_dict)
                return IntVal(0)

            if func_name == 'len':
                # Simplified length handling - assume known length
                return IntVal(3)  # Default length for symbolic lists

            if func_name in ['min', 'max']:
                args_z3 = [self._enhanced_ast_to_z3(arg, var_dict) for arg in node.args]
                args_z3 = [arg for arg in args_z3 if arg is not None]
                if not args_z3:
                    return None

                if len(args_z3) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    # min([a,b,c]) or max([a,b,c])
                    elts = node.args[0].elts
                    elts_z3 = [self._enhanced_ast_to_z3(e, var_dict) for e in elts]
                    elts_z3 = [e for e in elts_z3 if e is not None]
                    if func_name == 'min':
                        return self._z3_min_list(elts_z3)
                    else:
                        return self._z3_max_list(elts_z3)
                else:
                    # min(a,b,c) or max(a,b,c)
                    if func_name == 'min':
                        return self._z3_min_list(args_z3)
                    else:
                        return self._z3_max_list(args_z3)

            return None

        if isinstance(node, ast.Name):
            if node.id not in var_dict:
                var_dict[node.id] = Int(node.id)
            return var_dict[node.id]

        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                return BoolVal(v)
            if isinstance(v, int):
                return IntVal(v)
            if v is None:
                return BoolVal(False)
            return None

        if isinstance(node, (ast.Tuple, ast.List)):
            return [self._enhanced_ast_to_z3(elt, var_dict) for elt in node.elts]

        return None

    def _handle_subscript(self, value, idx, var_dict):
        """Handle subscript access for lists and arrays"""
        if isinstance(value, list):
            if isinstance(idx, int):
                if 0 <= idx < len(value):
                    return value[idx]
                return IntVal(0)  # Default for out of bounds
            else:
                # Symbolic index - create conditional chain
                result = value[-1] if value else IntVal(0)
                for i in reversed(range(len(value) - 1)):
                    result = If(idx == IntVal(i), value[i], result)
                return result
        elif Z3_AVAILABLE and isinstance(value, ArrayRef):
            from z3 import Select
            return Select(value, idx if not isinstance(idx, int) else IntVal(idx))
        else:
            return IntVal(0)  # Default fallback

    def _handle_in_notin(self, left, op, right_node, var_dict):
        """Handle 'in' and 'not in' operations"""
        # Simplified handling for membership tests
        if isinstance(right_node, (ast.List, ast.Tuple)):
            elts = [self._enhanced_ast_to_z3(elt, var_dict) for elt in right_node.elts]
            elts = [elt for elt in elts if elt is not None]
            if not elts:
                return BoolVal(False)

            # Create disjunction for 'in', conjunction of negations for 'not in'
            conditions = [left == elt for elt in elts]
            if isinstance(op, ast.In):
                return Or(*conditions) if len(conditions) > 1 else conditions[0]
            else:  # ast.NotIn
                return And(*[Not(cond) for cond in conditions])

        return BoolVal(False)  # Default fallback

    def _z3_min_list(self, lst):
        """Compute minimum of a list using Z3 If expressions"""
        if not lst:
            return IntVal(0)
        current_min = lst[0]
        for v in lst[1:]:
            current_min = If(current_min <= v, current_min, v)
        return current_min

    def _z3_max_list(self, lst):
        """Compute maximum of a list using Z3 If expressions"""
        if not lst:
            return IntVal(0)
        current_max = lst[0]
        for v in lst[1:]:
            current_max = If(current_max >= v, current_max, v)
        return current_max

    def _append_exit_path(self, exited_paths, vars_dict, path_cond, extra=None):
        """Unified method to add exit paths with simplified conditions"""
        if not Z3_AVAILABLE:
            # Fallback without Z3 simplification
            path_dict = {'vars': vars_dict, 'path_cond': path_cond, 'may_continue': False}
        else:
            simplified_cond = simplify(path_cond) if hasattr(path_cond, 'sort') else path_cond
            path_dict = {'vars': vars_dict, 'path_cond': simplified_cond, 'may_continue': False}

        if extra:
            path_dict.update(extra)
        exited_paths.append(path_dict)

    def _process_enhanced_for_loop(self, loop_var_name, iterable_type, iterable_data, body_ir, loop_level):
        """Enhanced for loop processing with precise Z3 constraint generation"""
        if not self.current_path:
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        original_path = self.current_path
        original_env = self.current_env.copy()
        collected_paths = []

        var_dict = {}
        # Prepare Z3 variable dictionary from current environment
        if hasattr(self.current_env, 'variables'):
            for name, sym_val in self.current_env.variables.items():
                if Z3_AVAILABLE and sym_val.type == SymbolicValueType.SYMBOLIC:
                    var_dict[name] = Int(name)

        if iterable_type == 'range':
            start, stop, step = iterable_data

            # Use enhanced range loop processing
            for k in range(self.max_loop_iterations):
                # Generate Z3 constraint for k-th iteration
                iter_constraint = None
                if Z3_AVAILABLE:
                    iter_constraint = simplify_range_cond(k, start, stop, step, var_dict)
                    if iter_constraint is None:
                        break  # No more valid iterations

                    # Check constraint satisfiability
                    if not is_sat(iter_constraint):
                        continue
                else:
                    # Fallback constraint check
                    if step is not None and start is not None and stop is not None:
                        if step > 0 and start + k * step >= stop:
                            break
                        elif step < 0 and start + k * step <= stop:
                            break

                # Create iteration path
                iter_path = ExecutionPath(f"path_{self.path_counter}")
                self.path_counter += 1
                if original_path:
                    iter_path.conditions = original_path.conditions.copy()
                    iter_path.statements = original_path.statements.copy()
                    iter_path.variables = original_path.variables.copy()
                    iter_path.loop_iterations = original_path.loop_iterations.copy()

                # Set loop variable value
                iter_val = start + k * step if isinstance(start, int) and isinstance(step, int) else f"{start} + {k} * {step}"
                loop_var = SymbolicValue(
                    SymbolicValueType.CONCRETE if isinstance(iter_val, int) else SymbolicValueType.EXPRESSION,
                    iter_val,
                    loop_var_name
                )

                if Z3_AVAILABLE and iter_constraint is not None:
                    constraint_condition = PathCondition(
                        expression=str(iter_constraint),
                        is_true=True,
                        z3_constraint=iter_constraint
                    )
                    iter_path.add_condition(constraint_condition)

                iter_path.variables[loop_var_name] = loop_var
                iter_path.add_statement(f"# Enhanced range iteration {k}: {loop_var_name} = {iter_val}")
                iter_path.loop_iterations[f"enhanced_for_{loop_level}"] = k

                # Execute body with this path
                self.current_path = iter_path
                self.current_env = original_env.copy()
                self.current_env.set_variable(loop_var_name, loop_var)

                try:
                    if isinstance(body_ir, (list, tuple)):
                        for stmt in body_ir:
                            self._execute_ir(stmt)
                    else:
                        self._execute_ir(body_ir)
                except Exception as e:
                    if self.current_path:
                        self.current_path.add_statement(f"Error in loop body: {e}")

                if self.current_path and self.current_path.is_satisfiable():
                    collected_paths.append(self.current_path)

        # Add collected paths to global path list
        for path in collected_paths:
            if path not in self.paths:
                self.paths.append(path)

        # Reset current path
        self.current_path = None
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def execute_program(self, ir_program: Tuple, include_function_paths=None) -> List[ExecutionPath]:
        """Execute an IR program symbolically and return all paths"""
        if not ir_program or ir_program[0] != "module":
            raise ValueError("Invalid IR program format")

        # Override instance setting if parameter provided
        if include_function_paths is not None:
            self.include_function_paths = include_function_paths

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

        self.current_env = func_env

        try:
            # Analyze function body - iterate through statements
            if isinstance(body_ir, (tuple, list)):
                for stmt in body_ir:
                    # Skip docstrings
                    if isinstance(stmt, str):
                        continue
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

    def _execute_ir(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an IR node and return its symbolic value"""
        if not isinstance(ir_node, (tuple, list)) or not ir_node:
            # Handle string identifiers as variable references
            if isinstance(ir_node, str) and ir_node.isidentifier():
                return self.current_env.get_variable(ir_node)
            return SymbolicValue(SymbolicValueType.CONCRETE, ir_node)

        op = ir_node[0]

        # Dispatch to specific handlers
        handlers = {
            "module": self._execute_module,
            "assign": self._execute_assign,
            "if": self._execute_if,
            "while": self._execute_while,
            "for": self._execute_for,
            "func_def": self._execute_func_def,
            "call": self._execute_call,
            "return": self._execute_return,
            "block": self._execute_block,
            "literal": self._execute_literal,
            "binary_op": self._execute_binary_op,
            "name": self._execute_name,
            "const": self._execute_const,
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

    def _execute_name(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a name (variable reference) IR node"""
        _, var_name = ir_node
        return self.current_env.get_variable(var_name)

    def _execute_const(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a constant IR node"""
        _, value = ir_node
        return SymbolicValue(SymbolicValueType.CONCRETE, value, original_ir=ir_node)

    def _execute_literal(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a literal IR node"""
        if len(ir_node) > 1:
            return SymbolicValue(SymbolicValueType.CONCRETE, ir_node[1])
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_if(self, ir_node: Tuple) -> SymbolicValue:
        """Execute an if statement symbolically - creates multiple paths with enhanced Z3 constraints"""
        if len(ir_node) == 4:
            _, condition_ir, then_block, else_block = ir_node
        else:
            _, condition_ir, then_block = ir_node
            else_block = None

        condition = self._execute_ir(condition_ir)
        readable_condition = self._make_condition_readable(condition)
        condition_str = readable_condition


        # For concrete conditions, take the appropriate branch directly
        if condition.type == SymbolicValueType.CONCRETE:
            if self.current_path:
                self.current_path.add_statement(f"if {readable_condition}:")

            if condition.value:
                if then_block:
                    self._execute_ir(then_block)
            else:
                if else_block:
                    self._execute_ir(else_block)
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        if len(self.paths) >= self.max_paths:
            if self.current_path:
                self.current_path.add_statement(f"Path limit reached at if condition: {condition_str}")
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Store current state
        original_path = self.current_path
        original_env = self.current_env.copy()

        # Generate Z3 constraint for condition
        z3_constraint = None
        if Z3_AVAILABLE and hasattr(condition, 'value'):
            try:
                z3_constraint = to_z3_expr(condition.value, self.current_env.z3_variables)
            except Exception:
                pass

        # True path
        true_path = ExecutionPath(f"path_{self.path_counter}")
        self.path_counter += 1
        if original_path:
            true_path.conditions = original_path.conditions.copy()
            true_path.statements = original_path.statements.copy()
            true_path.variables = original_path.variables.copy()
            true_path.loop_iterations = original_path.loop_iterations.copy()

        true_condition = PathCondition(readable_condition, True, z3_constraint=z3_constraint)
        true_path.add_condition(true_condition)
        true_path.add_statement(f"if {readable_condition}:")

        self.current_path = true_path
        self.current_env = original_env.copy()

        if then_block:
            try:
                self._execute_ir(then_block)
            except Exception as e:
                if self.current_path:
                    self.current_path.add_statement(f"Error in then block: {e}")

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
            false_path.loop_iterations = original_path.loop_iterations.copy()

        false_condition = PathCondition(readable_condition, False, z3_constraint=z3_constraint)
        false_path.add_condition(false_condition)
        false_path.add_statement(f"else (not {readable_condition}):")

        self.current_path = false_path
        self.current_env = original_env.copy()

        if else_block:
            try:
                self._execute_ir(else_block)
            except Exception as e:
                if self.current_path:
                    self.current_path.add_statement(f"Error in else block: {e}")

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
        """Execute a while loop symbolically with enhanced Z3 constraint analysis"""
        _, condition_ir, body_ir = ir_node
        condition = self._execute_ir(condition_ir)
        readable_condition = self._make_condition_readable(condition)
        condition_str = readable_condition

        if self.current_path:
            self.current_path.add_statement(f"while {readable_condition}:")

        # For concrete false conditions, skip the loop entirely
        if condition.type == SymbolicValueType.CONCRETE and not condition.value:
            if self.current_path:
                self.current_path.add_statement("# Loop not entered (condition false)")
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        original_path = self.current_path
        original_env = self.current_env.copy()
        collected_paths = []

        # Prepare Z3 variable dictionary
        var_dict = {}
        if hasattr(self.current_env, 'variables'):
            for name, sym_val in self.current_env.variables.items():
                if Z3_AVAILABLE and sym_val.type == SymbolicValueType.SYMBOLIC:
                    var_dict[name] = Int(name)

        # Create exit path (condition false) with Z3 constraint
        exit_path = ExecutionPath(f"path_{self.path_counter}")
        self.path_counter += 1
        if original_path:
            exit_path.conditions = original_path.conditions.copy()
            exit_path.statements = original_path.statements.copy()
            exit_path.variables = original_path.variables.copy()
            exit_path.loop_iterations = original_path.loop_iterations.copy()

        # Generate Z3 constraint for exit condition
        exit_z3_constraint = None
        if Z3_AVAILABLE and readable_condition:
            try:
                # Simple Z3 constraint creation for exit condition
                exit_z3_constraint = f"not ({readable_condition})"
            except:
                pass

        exit_condition = PathCondition(
            expression=readable_condition,
            is_true=False,
            z3_constraint=exit_z3_constraint
        )
        exit_path.add_condition(exit_condition)
        exit_path.add_statement("# Loop not entered/exited")

        # Only add exit path if it's satisfiable
        if exit_path.is_satisfiable():
            collected_paths.append(exit_path)

        # Create iteration paths with enhanced constraint checking
        for i in range(min(self.max_loop_iterations, 3)):
            iter_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            if original_path:
                iter_path.conditions = original_path.conditions.copy()
                iter_path.statements = original_path.statements.copy()
                iter_path.variables = original_path.variables.copy()
                iter_path.loop_iterations = original_path.loop_iterations.copy()

            # Generate Z3 constraint for iteration condition
            iter_z3_constraint = None
            if Z3_AVAILABLE and condition_str:
                try:
                    # Simple Z3 constraint creation for iteration condition
                    iter_z3_constraint = condition_str
                except:
                    pass

            iter_condition = PathCondition(
                expression=readable_condition,
                is_true=True,
                z3_constraint=iter_z3_constraint
            )
            iter_path.add_condition(iter_condition)
            iter_path.add_statement(f"# Enhanced loop iteration {i}")
            iter_path.loop_iterations[f"while_{id(ir_node)}"] = i

            # Check path satisfiability before execution
            if not iter_path.is_satisfiable():
                continue

            self.current_path = iter_path
            self.current_env = original_env.copy()

            # Execute the body
            try:
                self._execute_ir(body_ir)
            except Exception as e:
                if self.current_path:
                    self.current_path.add_statement(f"Error in loop body: {e}")

            if self.current_path and self.current_path.is_satisfiable():
                collected_paths.append(self.current_path)

        # Add all collected paths
        for path in collected_paths:
            if path not in self.paths:
                self.paths.append(path)

        # End current path as we've split into multiple paths
        self.current_path = None

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_for(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a for loop symbolically with enhanced range analysis"""
        if len(ir_node) < 4:
            return SymbolicValue(SymbolicValueType.CONCRETE, None)

        # Handle different IR formats: ('for', var, iter_expr, body, extras...)
        _, var_name, iter_expr, body_ir = ir_node[:4]

        if self.current_path:
            self.current_path.add_statement(f"for {var_name} in {iter_expr}:")

        # Check if it's a range call
        if (isinstance(iter_expr, tuple) and len(iter_expr) >= 3 and
            iter_expr[0] == 'call' and iter_expr[1] == 'range'):

            bounds = self.loop_analyzer.extract_range_bounds(iter_expr)
            if bounds:
                return self._execute_range_loop(var_name, bounds, body_ir, ir_node)

        # Fallback to simple iteration
        return self._execute_generic_for(var_name, iter_expr, body_ir)

    def _execute_range_loop(self, var_name: str, bounds: LoopBound, body_ir: Tuple, loop_node: Tuple) -> SymbolicValue:
        """Execute a range-based for loop with enhanced precision using Z3 constraints"""
        original_path = self.current_path
        original_env = self.current_env.copy()
        collected_paths = []

        # Extract values for range bounds
        start_val = self._extract_literal_value(bounds.start) if bounds.start else 0
        stop_val = self._extract_literal_value(bounds.stop) if bounds.stop else 0
        step_val = self._extract_literal_value(bounds.step) if bounds.step else 1

        # Create variable dictionary for Z3 constraint generation
        var_dict = {}
        if hasattr(self.current_env, 'variables'):
            for name, sym_val in self.current_env.variables.items():
                if Z3_AVAILABLE and sym_val.type == SymbolicValueType.SYMBOLIC:
                    var_dict[name] = Int(name)

        # Generate precise iterations using Z3 constraints
        for k in range(self.max_loop_iterations):
            # Generate Z3 constraint for k-th iteration
            if Z3_AVAILABLE:
                iter_constraint = simplify_range_cond(k, start_val, stop_val, step_val, var_dict)
                if iter_constraint is None:
                    # No more valid iterations
                    break
            else:
                # Fallback: simple range check
                # Fallback constraint check
                if (step_val is not None and start_val is not None and stop_val is not None):
                    if step_val > 0 and start_val + k * step_val >= stop_val:
                        break
                    elif step_val < 0 and start_val + k * step_val <= stop_val:
                        break

            # Create path for this iteration
            iter_path = ExecutionPath(f"path_{self.path_counter}")
            self.path_counter += 1
            if original_path:
                iter_path.conditions = original_path.conditions.copy()
                iter_path.statements = original_path.statements.copy()
                iter_path.variables = original_path.variables.copy()
                iter_path.loop_iterations = original_path.loop_iterations.copy()

            # Calculate iteration value
            if isinstance(start_val, int) and isinstance(step_val, int):
                iter_val = start_val + k * step_val
                loop_var = SymbolicValue(SymbolicValueType.CONCRETE, iter_val, var_name)
            else:
                # Symbolic iteration value
                loop_var = self.current_env.create_symbol(f"{var_name}_{k}")
                if Z3_AVAILABLE and iter_constraint is not None:
                    loop_var.constraints.append(str(iter_constraint))

            # Add iteration constraint as path condition
            if Z3_AVAILABLE and 'iter_constraint' in locals() and iter_constraint is not None:
                constraint_condition = PathCondition(
                    expression=str(iter_constraint),
                    is_true=True,
                    z3_constraint=iter_constraint
                )
                iter_path.add_condition(constraint_condition)

            iter_path.variables[var_name] = loop_var
            iter_path.add_statement(f"# Range iteration {k}: {var_name} = {loop_var}")
            iter_path.loop_iterations[f"for_{id(loop_node)}"] = k

            # Check path satisfiability
            if not iter_path.is_satisfiable():
                continue

            self.current_path = iter_path
            self.current_env = original_env.copy()
            self.current_env.set_variable(var_name, loop_var)

            # Execute the body
            try:
                if isinstance(body_ir, tuple) and len(body_ir) > 0:
                    for stmt in body_ir:
                        self._execute_ir(stmt)
                else:
                    self._execute_ir(body_ir)
            except Exception as e:
                if self.current_path:
                    self.current_path.add_statement(f"Error in loop body: {e}")

            if self.current_path and self.current_path.is_satisfiable():
                collected_paths.append(self.current_path)

        # Add all collected paths
        for path in collected_paths:
            if path not in self.paths:
                self.paths.append(path)

        # End current path
        self.current_path = None
        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _extract_literal_value(self, expr):
        """Extract literal value from IR expression"""
        if isinstance(expr, int):
            return expr
        if isinstance(expr, tuple) and len(expr) >= 2 and expr[0] == 'literal':
            return expr[1]
        return None

    def _execute_generic_for(self, var_name: str, iter_expr: Tuple, body_ir: Tuple) -> SymbolicValue:
        """Execute a generic for loop (fallback)"""
        # Create a symbolic value for the loop variable
        loop_var = self.current_env.create_symbol(f"{var_name}_iter")
        self.current_env.set_variable(var_name, loop_var)

        if self.current_path:
            self.current_path.add_statement(f"# Generic for loop: {var_name} = {loop_var}")

        # Execute body once symbolically - handle tuple format
        if isinstance(body_ir, tuple) and len(body_ir) > 0:
            for stmt in body_ir:
                self._execute_ir(stmt)
        else:
            self._execute_ir(body_ir)

        return SymbolicValue(SymbolicValueType.CONCRETE, None)

    def _execute_func_def(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function definition and analyze its internal paths"""
        _, func_name, params, body = ir_node

        # Store function in global environment
        self.global_env.functions[func_name] = (params, body)

        if self.current_path:
            params_str = ', '.join(params) if params else ''
            self.current_path.add_statement(f"def {func_name}({params_str}):")

        # Analyze function's internal paths
        function_paths = self.analyze_function_definition(func_name, params, body)

        # Store function paths for reporting
        self.function_analyses[func_name] = function_paths

        # If include_function_paths is enabled, add function paths to main path collection
        if self.include_function_paths and function_paths:
            for func_path in function_paths:
                # Create a unique path ID to avoid conflicts
                func_path.path_id = f"func_{func_name}_{func_path.path_id}"
                # Add function context to statements
                context_stmt = f"# Function: {func_name}({', '.join(params)})"
                func_path.statements.insert(0, context_stmt)
                # Add to main paths if not already present
                if func_path not in self.paths:
                    self.paths.append(func_path)

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
        """Execute binary operations with enhanced Z3 constraint generation"""
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

        # Create symbolic expression with Z3 constraint if possible
        expr = (op, left, right)

        # For symbolic comparisons, always create symbolic expressions
        if (left.type == SymbolicValueType.SYMBOLIC or right.type == SymbolicValueType.SYMBOLIC) and op in ['==', '!=', '<', '>', '<=', '>=']:
            # This is a symbolic comparison, always return an expression
            return SymbolicValue(SymbolicValueType.EXPRESSION, expr)

        # Try to create Z3 expression for constraint generation
        if Z3_AVAILABLE:
            try:
                var_dict = getattr(self.current_env, 'z3_variables', {})

                # Fix: For symbolic values, use the name instead of value (which is None)
                left_z3_input = left.name if left.type == SymbolicValueType.SYMBOLIC else (left.value if hasattr(left, 'value') else left)
                right_z3_input = right.name if right.type == SymbolicValueType.SYMBOLIC else (right.value if hasattr(right, 'value') else right)

                left_z3 = to_z3_expr(left_z3_input, var_dict)
                right_z3 = to_z3_expr(right_z3_input, var_dict)

                if left_z3 is not None and right_z3 is not None:
                    # Create Z3 expression based on operator
                    z3_ops = {
                        '+': lambda l, r: l + r, '-': lambda l, r: l - r,
                        '*': lambda l, r: l * r, '/': lambda l, r: l / r,
                        '%': lambda l, r: l % r, '==': lambda l, r: l == r,
                        '!=': lambda l, r: l != r, '<': lambda l, r: l < r,
                        '>': lambda l, r: l > r, '<=': lambda l, r: l <= r,
                        '>=': lambda l, r: l >= r, 'and': lambda l, r: And(l, r),
                        'or': lambda l, r: Or(l, r)
                    }

                    if op in z3_ops:
                        z3_expr = z3_ops[op](left_z3, right_z3)
                        # Store the tuple representation instead of Z3 expression to avoid conversion issues
                        result = SymbolicValue(SymbolicValueType.EXPRESSION, expr)
                        result.constraints.append(str(z3_expr))
                        return result

            except Exception:
                pass

        return SymbolicValue(SymbolicValueType.EXPRESSION, expr)

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

    def _make_condition_readable(self, condition) -> str:
        """Convert IR condition to readable format with recursive tuple handling"""
        # Handle SymbolicValue objects first
        if hasattr(condition, 'value') and hasattr(condition, 'type'):
            # For EXPRESSION type, use the tuple representation for readability
            if condition.type == SymbolicValueType.EXPRESSION:
                return self._make_condition_readable(condition.value)
            elif condition.type == SymbolicValueType.SYMBOLIC:
                return condition.name or str(condition.value)
            elif condition.type == SymbolicValueType.CONCRETE:
                return str(condition.value)

        # Use utility function for making conditions readable
        return make_condition_readable(str(condition))

    def _simplify_display(self, value) -> str:
        """Simplify value display for better readability using utility functions"""
        if hasattr(value, 'type') and hasattr(value, 'value'):
            # Check if we have original IR to preserve formatting
            if hasattr(value, 'original_ir') and value.original_ir:
                try:
                    return simplify_value_display(value.original_ir)
                except Exception:
                    pass

            if value.type == SymbolicValueType.CONCRETE:
                return str(value.value)
            else:
                return str(value)

        try:
            return simplify_value_display(value)
        except Exception:
            return str(value)

    def generate_report(self, paths: List[ExecutionPath]) -> Dict[str, Any]:
        """Generate a comprehensive report of symbolic execution results with enhanced analysis"""
        if self.performance_mode:
            return self._generate_fast_report(paths)

        satisfiable_paths = [p for p in paths if p.is_satisfiable()]

        # Enhanced loop analysis
        loop_info = {}
        for path in paths:
            for loop_id, iteration in path.loop_iterations.items():
                if loop_id not in loop_info:
                    loop_info[loop_id] = {'max_iteration': 0, 'paths': 0}
                loop_info[loop_id]['max_iteration'] = max(loop_info[loop_id]['max_iteration'], iteration)
                loop_info[loop_id]['paths'] += 1

        # Enhanced constraint analysis
        constraint_analysis = {
            'total_constraints': sum(len(p.conditions) for p in paths),
            'z3_constraints': sum(1 for p in paths for c in p.conditions if c.z3_constraint is not None),
            'symbolic_variables': len(self.current_env.z3_variables) if hasattr(self.current_env, 'z3_variables') else 0,
            'satisfiable_constraint_ratio': len(satisfiable_paths) / len(paths) if paths else 0
        }

        # Path complexity metrics
        path_metrics = {
            'average_path_length': sum(len(p.statements) for p in paths) / len(paths) if paths else 0,
            'average_conditions_per_path': sum(len(p.conditions) for p in paths) / len(paths) if paths else 0,
            'paths_with_loops': sum(1 for p in paths if p.loop_iterations),
            'paths_with_returns': sum(1 for p in paths if p.return_value is not None)
        }

        report = {
            'total_paths': len(paths),
            'satisfiable_paths': len(satisfiable_paths),
            'paths': [path.to_dict() for path in paths],
            'summary': {
                'functions_analyzed': len(self.global_env.functions),
                'max_path_length': max((len(p.statements) for p in paths), default=0),
                'max_conditions': max((len(p.conditions) for p in paths), default=0),
                'z3_available': Z3_AVAILABLE,
                'loop_analysis': loop_info,
                'constraint_analysis': constraint_analysis,
                'path_metrics': path_metrics,
                'enhanced_features': {
                    'z3_constraint_generation': Z3_AVAILABLE,
                    'range_loop_precision': True,
                    'enhanced_ast_conversion': True,
                    'path_satisfiability_checking': Z3_AVAILABLE
                }
            }
        }

        # Add function analysis details if available
        if hasattr(self, 'function_analyses') and self.function_analyses:
            report['function_analyses'] = {}
            for func_name, func_paths in self.function_analyses.items():
                report['function_analyses'][func_name] = {
                    'total_paths': len(func_paths),
                    'satisfiable_paths': len([p for p in func_paths if p.is_satisfiable()]),
                    'paths': [path.to_dict() for path in func_paths]
                }

        return report

    def _generate_fast_report(self, paths: List[ExecutionPath]) -> Dict[str, Any]:
        """Generate simplified report for performance mode"""
        satisfiable_paths = [p for p in paths if p.is_satisfiable()]

        report = {
            'total_paths': len(paths),
            'satisfiable_paths': len(satisfiable_paths),
            'paths': [path.to_dict() for path in paths],
            'summary': {
                'functions_analyzed': len(self.global_env.functions),
                'max_path_length': max((len(p.statements) for p in paths), default=0),
                'max_conditions': max((len(p.conditions) for p in paths), default=0),
                'performance_mode': True
            }
        }

        # Add function analysis if available
        if self.function_analyses:
            report['function_analyses'] = {}
            for func_name, func_paths in self.function_analyses.items():
                report['function_analyses'][func_name] = {
                    'total_paths': len(func_paths),
                    'satisfiable_paths': len([p for p in func_paths if p.is_satisfiable()]),
                    'paths': [path.to_dict() for path in func_paths]
                }

        return report

    def renumber_paths_sequentially(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Renumber paths sequentially starting from 1"""
        for i, path in enumerate(paths, 1):
            path.path_id = f"path_{i}"
        return paths

    # Add methods for test compatibility
    def _extract_variable_from_condition(self, condition_str: str) -> Optional[str]:
        """Extract variable name from a simple condition (compatibility method)"""
        return extract_variable_from_condition(condition_str)

    def _is_simple_variable_condition(self, condition_str: str) -> bool:
        """Check if condition is a simple variable comparison (compatibility method)"""
        return is_simple_variable_condition(condition_str)

    def _group_conditions_by_variable(self, conditions: List[PathCondition]) -> Dict[str, List[PathCondition]]:
        """Group conditions by variable (compatibility method)"""
        return group_conditions_by_variable(conditions)

    def _merge_negative_conditions(self, variable: str, conditions: List[PathCondition]) -> List[PathCondition]:
        """Merge negative conditions for a variable (compatibility method)"""
        from .symbolic.condition_utils import merge_negative_conditions
        return merge_negative_conditions(variable, conditions)

    def simplify_path_conditions(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Simplify and merge path conditions using utility functions"""
        simplified_paths = []

        for path in paths:
            if not path.conditions:
                simplified_paths.append(path)
                continue

            # Use utility functions for condition processing
            simplified_conditions = simplify_conditions_list(path.conditions)

            # Create new path with simplified conditions
            simplified_path = ExecutionPath(path.path_id)
            simplified_path.conditions = simplified_conditions
            simplified_path.statements = path.statements
            simplified_path.return_value = path.return_value
            simplified_path.variables = path.variables
            simplified_path.loop_iterations = path.loop_iterations
            simplified_path.satisfiable = path.satisfiable
            simplified_path.test_inputs = getattr(path, 'test_inputs', {})
            simplified_path.expected_outputs = getattr(path, 'expected_outputs', {})
            simplified_path.z3_error = getattr(path, 'z3_error', None)

            simplified_paths.append(simplified_path)

        return simplified_paths

    def enhance_paths_with_test_cases(self, paths: List[ExecutionPath]) -> List[ExecutionPath]:
        """Enhance execution paths with Z3-generated test case information using utility functions"""
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
            enhanced_path.loop_iterations = getattr(path, 'loop_iterations', {}).copy()

            if not path.conditions:
                # No conditions, mark as satisfiable with empty test inputs
                enhanced_path.satisfiable = True
                enhanced_path.test_inputs = {}
                enhanced_path.expected_outputs = self._extract_outputs_from_path(path)
            else:
                # Use utility function for path satisfiability checking
                condition_strings = [str(cond) for cond in path.conditions]
                is_satisfiable, model_values = check_path_satisfiability(condition_strings)

                enhanced_path.satisfiable = is_satisfiable
                enhanced_path.test_inputs = model_values if model_values else {}
                enhanced_path.expected_outputs = self._extract_outputs_from_path(path) if is_satisfiable else {}

            enhanced_paths.append(enhanced_path)

        return enhanced_paths

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

        if getattr(path, 'loop_iterations', None):
            outputs['loop_iterations'] = path.loop_iterations

        return outputs


# Utility functions
def execute_symbolic_from_file(file_path: str, include_function_paths=False, performance_mode=False) -> List[ExecutionPath]:
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

        executor = SymbolicExecutor(include_function_paths=include_function_paths, performance_mode=performance_mode)
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from file '{file_path}': {e}")


def execute_symbolic_from_string(ir_string: str, include_function_paths=False, performance_mode=False) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR string"""
    try:
        try:
            ir_program = json.loads(ir_string)
            ir_program = _json_to_tuples(ir_program)
        except json.JSONDecodeError:
            ir_string = ir_string.replace('null', 'None')
            ir_program = ast.literal_eval(ir_string)

        executor = SymbolicExecutor(include_function_paths=include_function_paths, performance_mode=performance_mode)
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
