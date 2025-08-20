#!/usr/bin/env python3
"""
Enhanced Symbolic Execution Engine for Silu Language

This module provides symbolic execution capabilities for Silu programs,
allowing analysis of all possible execution paths and generation of
path constraints for functions with improved Z3 integration and loop handling.
"""

from typing import Any, Dict, List, Tuple, Optional, Union
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum
import json
import ast
from copy import deepcopy

# Import enhanced symbolic execution utilities
from .symbolic.z3_utils import (
    Z3_AVAILABLE,
    to_z3_expr,
    check_path_satisfiability,
)
from .symbolic.loop_utils import LoopAnalyzer
from .symbolic.builtin_utils import (
    SymbolicValueType,
    SymbolicValue,
    create_concrete_value,
    create_symbolic_value,
    create_expression_value,
    create_builtin_functions_dict,
)
from .symbolic.condition_utils import (
    PathCondition,
    is_simple_variable_condition,
    group_conditions_by_variable,
)
from .symbolic.report_utils import (
    generate_comprehensive_report,
    enhance_paths_with_z3_test_cases,
    renumber_paths_sequentially,
)

# Import Z3 for enhanced symbolic execution
if Z3_AVAILABLE:
    from z3 import And, Or


# Configuration Constants
class Config:
    """Configuration constants for symbolic execution"""

    DEFAULT_MAX_PATHS = 100
    DEFAULT_MAX_LOOP_ITERATIONS = 5
    PERFORMANCE_MAX_PATHS = 50
    PERFORMANCE_MAX_LOOP_ITERATIONS = 3
    DEFAULT_PATH_PREFIX = "path_"
    DEFAULT_ENCODING = "utf-8"


class ExecutionPathState(Enum):
    """Enumeration of execution path states"""

    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"
    UNSATISFIABLE = "unsatisfiable"


@dataclass
class ExecutionPath:
    """Represents a single execution path through a function"""

    path_id: str
    conditions: List[PathCondition] = field(default_factory=list)
    statements: List[str] = field(default_factory=list)
    return_value: Optional[SymbolicValue] = None
    variables: Dict[str, SymbolicValue] = field(default_factory=dict)
    loop_iterations: Dict[str, int] = field(default_factory=dict)
    state: ExecutionPathState = ExecutionPathState.ACTIVE
    test_inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: Dict[str, Any] = field(default_factory=dict)
    z3_error: Optional[str] = None

    def add_condition(self, condition: PathCondition) -> None:
        """Add a path condition"""
        self.conditions.append(condition)

    def add_statement(self, statement: str) -> None:
        """Add an executed statement"""
        self.statements.append(statement)

    def is_satisfiable(self) -> bool:
        """Check if the path conditions are satisfiable using enhanced Z3 checking"""
        if not self.conditions:
            return True

        if self.state == ExecutionPathState.UNSATISFIABLE:
            return False

        # Use Z3-based satisfiability checking if available
        if Z3_AVAILABLE:
            condition_strs = [str(c) for c in self.conditions]
            is_sat_result, _ = check_path_satisfiability(condition_strs)
            if not is_sat_result:
                self.state = ExecutionPathState.UNSATISFIABLE
            return is_sat_result

        # Fallback to basic logical contradiction checking
        return self._check_basic_satisfiability()

    def _check_basic_satisfiability(self) -> bool:
        """Basic satisfiability check without Z3"""
        expressions = {}
        for condition in self.conditions:
            if condition.expression in expressions:
                if expressions[condition.expression] != condition.is_true:
                    self.state = ExecutionPathState.UNSATISFIABLE
                    return False
            expressions[condition.expression] = condition.is_true
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            "path_id": self.path_id,
            "conditions": [str(c) for c in self.conditions],
            "statements": self.statements,
            "return_value": str(self.return_value) if self.return_value else None,
            "variables": {k: str(v) for k, v in self.variables.items()},
            "satisfiable": self.is_satisfiable(),
            "loop_iterations": self.loop_iterations,
            "state": self.state.value,
        }

        # Add optional attributes if present
        for attr in ["test_inputs", "expected_outputs", "z3_error"]:
            if hasattr(self, attr) and getattr(self, attr):
                result[attr] = getattr(self, attr)

        return result


class SymbolicEnvironment:
    """Environment for symbolic execution with improved encapsulation"""

    def __init__(self, parent: Optional["SymbolicEnvironment"] = None):
        self.parent = parent
        self.variables: Dict[str, SymbolicValue] = {}
        self.functions: Dict[str, Any] = {}
        self.symbol_counter = 0
        self.z3_variables: Dict[str, Any] = {}

    def create_symbol(
        self, name: Optional[str] = None, var_type: str = "int"
    ) -> SymbolicValue:
        """Create a new symbolic value with optional Z3 variable"""
        if not name:
            name = f"sym_{self.symbol_counter}"
            self.symbol_counter += 1

        # Create Z3 variable if available
        if Z3_AVAILABLE and name not in self.z3_variables:
            self.z3_variables[name] = self._create_z3_variable(name, var_type)

        return create_symbolic_value(name)

    def _create_z3_variable(self, name: str, var_type: str) -> Any:
        """Create Z3 variable based on type"""
        from .symbolic.z3_utils import create_z3_variable

        return create_z3_variable(name, var_type)

    def get_variable(self, name: str) -> SymbolicValue:
        """Get a variable value with proper scoping"""
        if name in self.variables:
            return self.variables[name]
        elif self.parent:
            return self.parent.get_variable(name)
        else:
            # Create a symbolic variable for undefined variables
            symbol = self.create_symbol(name)
            self.variables[name] = symbol
            return symbol

    def set_variable(self, name: str, value: SymbolicValue) -> None:
        """Set a variable value"""
        self.variables[name] = value

    def copy(self) -> "SymbolicEnvironment":
        """Create a deep copy of the environment"""
        new_env = SymbolicEnvironment(self.parent)
        new_env.variables = deepcopy(self.variables)
        new_env.functions = deepcopy(self.functions)
        new_env.symbol_counter = self.symbol_counter
        new_env.z3_variables = self.z3_variables.copy()
        return new_env


class PathManager:
    """Manages execution paths and path operations"""

    def __init__(self, max_paths: int = Config.DEFAULT_MAX_PATHS):
        self.paths: List[ExecutionPath] = []
        self.path_counter = 0
        self.max_paths = max_paths

    def create_path(self, prefix: str = Config.DEFAULT_PATH_PREFIX) -> ExecutionPath:
        """Create a new execution path"""
        path_id = f"{prefix}{self.path_counter}"
        self.path_counter += 1
        return ExecutionPath(path_id)

    def add_path(self, path: ExecutionPath) -> bool:
        """Add path if within limits and satisfiable"""
        if len(self.paths) >= self.max_paths:
            return False

        if path.is_satisfiable() and path not in self.paths:
            self.paths.append(path)
            return True
        return False

    def copy_path(
        self, source_path: ExecutionPath, new_prefix: str = ""
    ) -> ExecutionPath:
        """Create a copy of an existing path"""
        new_path = self.create_path(new_prefix or Config.DEFAULT_PATH_PREFIX)
        new_path.conditions = source_path.conditions.copy()
        new_path.statements = source_path.statements.copy()
        new_path.variables = source_path.variables.copy()
        new_path.loop_iterations = source_path.loop_iterations.copy()
        new_path.state = source_path.state
        return new_path

    def get_satisfiable_paths(self) -> List[ExecutionPath]:
        """Get all satisfiable paths"""
        return [p for p in self.paths if p.is_satisfiable()]

    def finalize_paths(self) -> List[ExecutionPath]:
        """Finalize and return processed paths"""
        # Filter out empty paths
        valid_paths = [
            p for p in self.paths if p.statements or p.conditions or p.variables
        ]
        return renumber_paths_sequentially(valid_paths)


class IRNodeHandler(ABC):
    """Abstract base class for IR node handlers"""

    @abstractmethod
    def can_handle(self, ir_node: Tuple) -> bool:
        """Check if this handler can process the given IR node"""
        pass

    @abstractmethod
    def handle(self, ir_node: Tuple, executor: "SymbolicExecutor") -> SymbolicValue:
        """Handle the IR node and return its symbolic value"""
        pass


class AssignmentHandler(IRNodeHandler):
    """Handler for assignment operations"""

    def can_handle(self, ir_node: Tuple) -> bool:
        return (
            isinstance(ir_node, tuple) and len(ir_node) > 0 and ir_node[0] == "assign"
        )

    def handle(self, ir_node: Tuple, executor: "SymbolicExecutor") -> SymbolicValue:
        try:
            _, var_name, value_ir, _ = ir_node
            value = executor._execute_ir(value_ir)
            executor.current_env.set_variable(var_name, value)

            if executor.current_path:
                simplified_value = executor._simplify_display(value)
                executor.current_path.add_statement(f"{var_name} = {simplified_value}")
                executor.current_path.variables[var_name] = value

            return value
        except Exception as e:
            if executor.current_path:
                executor.current_path.add_statement(f"Error in assignment: {e}")
                executor.current_path.state = ExecutionPathState.ERROR
            return create_concrete_value(None)


class ConditionalHandler(IRNodeHandler):
    """Handler for if/elif/else statements"""

    def can_handle(self, ir_node: Tuple) -> bool:
        return isinstance(ir_node, tuple) and len(ir_node) > 0 and ir_node[0] == "if"

    def handle(self, ir_node: Tuple, executor: "SymbolicExecutor") -> SymbolicValue:
        if len(ir_node) == 4:
            _, condition_ir, then_block, else_block = ir_node
        else:
            _, condition_ir, then_block = ir_node
            else_block = None

        condition = executor._execute_ir(condition_ir)
        readable_condition = executor._make_condition_readable(condition)

        # Handle concrete conditions directly
        if condition.type == SymbolicValueType.CONCRETE:
            return self._execute_concrete_if(
                executor, condition, readable_condition, then_block, else_block
            )

        # Check path limits
        if len(executor.path_manager.paths) >= executor.path_manager.max_paths:
            if executor.current_path:
                executor.current_path.add_statement(
                    f"Path limit reached at if condition: {readable_condition}"
                )
            return create_concrete_value(None)

        # Execute symbolic if with path splitting
        return self._execute_symbolic_if(
            executor, condition, readable_condition, then_block, else_block
        )

    def _execute_concrete_if(
        self, executor, condition, readable_condition, then_block, else_block
    ):
        """Execute if statement with concrete condition"""
        if executor.current_path:
            executor.current_path.add_statement(f"if {readable_condition}:")

        if condition.value:
            if then_block:
                executor._execute_ir(then_block)
        else:
            if else_block:
                executor._execute_ir(else_block)
        return create_concrete_value(None)

    def _execute_symbolic_if(
        self, executor, condition, readable_condition, then_block, else_block
    ):
        """Execute if statement with symbolic condition by splitting paths"""
        original_path = executor.current_path
        original_env = executor.current_env.copy()

        # Generate Z3 constraint
        z3_constraint = executor._generate_z3_constraint(condition)

        # Execute true path
        true_path = self._execute_if_branch(
            executor,
            original_path,
            original_env,
            readable_condition,
            True,
            then_block,
            z3_constraint,
            "if",
        )

        # Execute false path
        false_path = self._execute_if_branch(
            executor,
            original_path,
            original_env,
            readable_condition,
            False,
            else_block,
            z3_constraint,
            "else",
        )

        # Continue with first satisfiable path
        satisfiable_paths = [
            p for p in [true_path, false_path] if p and p.is_satisfiable()
        ]
        executor.current_path = satisfiable_paths[0] if satisfiable_paths else None

        return create_concrete_value(None)

    def _execute_if_branch(
        self,
        executor,
        original_path,
        original_env,
        readable_condition,
        is_true_branch,
        block,
        z3_constraint,
        branch_name,
    ):
        """Execute a single branch of an if statement"""
        branch_path = executor.path_manager.copy_path(
            original_path or ExecutionPath("temp")
        )

        # Add condition
        condition_obj = PathCondition(
            readable_condition, is_true_branch, z3_constraint=z3_constraint
        )
        branch_path.add_condition(condition_obj)

        statement = (
            f"{branch_name} {readable_condition}:"
            if is_true_branch
            else f"else not {readable_condition}:"
        )
        branch_path.add_statement(statement)

        # Execute block
        executor.current_path = branch_path
        executor.current_env = original_env.copy()

        if block:
            try:
                executor._execute_ir(block)
            except Exception as e:
                if executor.current_path:
                    executor.current_path.add_statement(
                        f"Error in {branch_name} block: {e}"
                    )
                    executor.current_path.state = ExecutionPathState.ERROR

        # Store result if satisfiable
        if executor.current_path and executor.current_path.is_satisfiable():
            executor.path_manager.add_path(executor.current_path)
            return executor.current_path
        return None


class LoopHandler(IRNodeHandler):
    """Handler for loop operations"""

    def can_handle(self, ir_node: Tuple) -> bool:
        return (
            isinstance(ir_node, tuple)
            and len(ir_node) > 0
            and ir_node[0] in ["while", "for"]
        )

    def handle(self, ir_node: Tuple, executor: "SymbolicExecutor") -> SymbolicValue:
        if ir_node[0] == "while":
            return self._handle_while_loop(ir_node, executor)
        elif ir_node[0] == "for":
            return self._handle_for_loop(ir_node, executor)
        return create_concrete_value(None)

    def _handle_while_loop(
        self, ir_node: Tuple, executor: "SymbolicExecutor"
    ) -> SymbolicValue:
        """Handle while loop with enhanced constraint analysis"""
        _, condition_ir, body_ir = ir_node
        condition = executor._execute_ir(condition_ir)
        readable_condition = executor._make_condition_readable(condition)

        if executor.current_path:
            executor.current_path.add_statement(f"while {readable_condition}:")

        # For concrete false conditions, skip the loop entirely
        if condition.type == SymbolicValueType.CONCRETE and not condition.value:
            if executor.current_path:
                executor.current_path.add_statement(
                    "# Loop not entered (condition false)"
                )
            return create_concrete_value(None)

        return self._execute_while_iterations(
            executor, ir_node, condition, readable_condition, body_ir
        )

    def _execute_while_iterations(
        self, executor, ir_node, condition, readable_condition, body_ir
    ):
        """Execute while loop iterations"""
        original_path = executor.current_path
        original_env = executor.current_env.copy()

        # Create exit path (condition false)
        exit_path = executor.path_manager.copy_path(
            original_path or ExecutionPath("temp")
        )
        exit_condition = PathCondition(readable_condition, False)
        exit_path.add_condition(exit_condition)
        exit_path.add_statement("# Loop not entered/exited")

        if exit_path.is_satisfiable():
            executor.path_manager.add_path(exit_path)

        # Create iteration paths
        for i in range(executor.max_loop_iterations):
            iter_path = executor.path_manager.copy_path(
                original_path or ExecutionPath("temp")
            )

            iter_condition = PathCondition(readable_condition, True)
            iter_path.add_condition(iter_condition)
            iter_path.add_statement(f"# Loop iteration {i}")
            iter_path.loop_iterations[f"while_{id(ir_node)}"] = i

            if not iter_path.is_satisfiable():
                continue

            executor.current_path = iter_path
            executor.current_env = original_env.copy()

            try:
                executor._execute_ir(body_ir)
            except Exception as e:
                if executor.current_path:
                    executor.current_path.add_statement(f"Error in loop body: {e}")
                    executor.current_path.state = ExecutionPathState.ERROR

            if executor.current_path and executor.current_path.is_satisfiable():
                executor.path_manager.add_path(executor.current_path)

        executor.current_path = None
        return create_concrete_value(None)

    def _handle_for_loop(
        self, ir_node: Tuple, executor: "SymbolicExecutor"
    ) -> SymbolicValue:
        """Handle for loop with enhanced range analysis"""
        if len(ir_node) < 4:
            return create_concrete_value(None)

        _, var_name, iter_expr, body_ir = ir_node[:4]

        if executor.current_path:
            executor.current_path.add_statement(f"for {var_name} in {iter_expr}:")

        # Check if it's a range call
        if (
            isinstance(iter_expr, tuple)
            and len(iter_expr) >= 3
            and iter_expr[0] == "call"
            and iter_expr[1] == "range"
        ):
            bounds = executor.loop_analyzer.extract_range_bounds(iter_expr)
            if bounds:
                return self._execute_range_loop(
                    executor, var_name, bounds, body_ir, ir_node
                )

        # Fallback to simple iteration
        return self._execute_generic_for(executor, var_name, iter_expr, body_ir)

    def _execute_range_loop(self, executor, var_name, bounds, body_ir, loop_node):
        """Execute range-based for loop"""
        original_path = executor.current_path
        original_env = executor.current_env.copy()

        # Extract literal values
        start_val = self._extract_literal(bounds.start) if bounds.start else 0
        stop_val = self._extract_literal(bounds.stop) if bounds.stop else 0
        step_val = self._extract_literal(bounds.step) if bounds.step else 1

        for k in range(executor.max_loop_iterations):
            # Check if iteration is valid
            if not self._is_valid_iteration(k, start_val, stop_val, step_val):
                break

            iter_path = executor.path_manager.copy_path(
                original_path or ExecutionPath("temp")
            )

            # Calculate iteration value
            iter_val = (
                start_val + k * step_val
                if isinstance(start_val, int) and isinstance(step_val, int)
                else f"{start_val} + {k} * {step_val}"
            )
            loop_var = (
                create_concrete_value(iter_val)
                if isinstance(iter_val, int)
                else create_expression_value(iter_val)
            )
            loop_var.name = var_name

            iter_path.variables[var_name] = loop_var
            iter_path.add_statement(f"# Range iteration {k}: {var_name} = {iter_val}")
            iter_path.loop_iterations[f"for_{id(loop_node)}"] = k

            if not iter_path.is_satisfiable():
                continue

            executor.current_path = iter_path
            executor.current_env = original_env.copy()
            executor.current_env.set_variable(var_name, loop_var)

            try:
                self._execute_loop_body(executor, body_ir)
            except Exception as e:
                if executor.current_path:
                    executor.current_path.add_statement(f"Error in loop body: {e}")
                    executor.current_path.state = ExecutionPathState.ERROR

            if executor.current_path and executor.current_path.is_satisfiable():
                executor.path_manager.add_path(executor.current_path)

        executor.current_path = None
        return create_concrete_value(None)

    def _extract_literal(self, expr) -> Union[int, Any]:
        """Extract literal value from expression"""
        if isinstance(expr, int):
            return expr
        if isinstance(expr, tuple) and len(expr) >= 2 and expr[0] == "literal":
            return expr[1]
        return expr

    def _is_valid_iteration(self, k: int, start: Any, stop: Any, step: Any) -> bool:
        """Check if iteration k is valid for the given range"""
        if not all(isinstance(x, int) for x in [start, stop, step]):
            return k < 3  # Fallback for symbolic values

        current_val = start + k * step
        return (step > 0 and current_val < stop) or (step < 0 and current_val > stop)

    def _execute_loop_body(self, executor, body_ir):
        """Execute loop body statements"""
        if isinstance(body_ir, (tuple, list)) and len(body_ir) > 0:
            if isinstance(body_ir[0], str):  # Single statement
                executor._execute_ir(body_ir)
            else:  # Multiple statements
                for stmt in body_ir:
                    executor._execute_ir(stmt)
        else:
            executor._execute_ir(body_ir)

    def _execute_generic_for(self, executor, var_name, iter_expr, body_ir):
        """Execute generic for loop (fallback)"""
        loop_var = executor.current_env.create_symbol(f"{var_name}_iter")
        executor.current_env.set_variable(var_name, loop_var)

        if executor.current_path:
            executor.current_path.add_statement(
                f"# Generic for loop: {var_name} = {loop_var}"
            )

        self._execute_loop_body(executor, body_ir)
        return create_concrete_value(None)


class SymbolicExecutor:
    """Enhanced symbolic execution engine for Silu IR with improved architecture"""

    def __init__(
        self, include_function_paths: bool = False, performance_mode: bool = False, debug: bool = False
    ):
        self.global_env = SymbolicEnvironment()
        self.current_env = self.global_env
        self.current_path: Optional[ExecutionPath] = None

        # Configure limits based on mode
        max_paths = (
            Config.PERFORMANCE_MAX_PATHS
            if performance_mode
            else Config.DEFAULT_MAX_PATHS
        )
        self.max_loop_iterations = (
            Config.PERFORMANCE_MAX_LOOP_ITERATIONS
            if performance_mode
            else Config.DEFAULT_MAX_LOOP_ITERATIONS
        )

        self.path_manager = PathManager(max_paths)
        self.loop_analyzer = LoopAnalyzer(max_iterations=self.max_loop_iterations)
        self.function_analyses: Dict[str, List[ExecutionPath]] = {}
        self.include_function_paths = include_function_paths
        self.performance_mode = performance_mode
        self.debug = debug

        # Initialize handlers
        self._init_handlers()

        # Initialize built-in functions
        self._init_builtins()

    def _init_handlers(self):
        """Initialize IR node handlers"""
        self.handlers = [
            AssignmentHandler(),
            ConditionalHandler(),
            LoopHandler(),
        ]

    def _init_builtins(self):
        """Initialize built-in functions"""
        builtins = create_builtin_functions_dict(current_path=self.current_path)
        self.global_env.functions.update(builtins)

    def execute_program(
        self, ir_program: Tuple, include_function_paths: Optional[bool] = None
    ) -> List[ExecutionPath]:
        """Execute an IR program symbolically and return all paths"""
        if not ir_program or ir_program[0] != "module":
            raise ValueError("Invalid IR program format")

        if include_function_paths is not None:
            self.include_function_paths = include_function_paths

        self.current_path = self.path_manager.create_path()

        try:
            self._execute_ir(ir_program)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"Error: {e}")
                self.current_path.state = ExecutionPathState.ERROR

        if self.current_path:
            self.path_manager.add_path(self.current_path)

        return self.path_manager.finalize_paths()

    def analyze_function(
        self, func_name: str, param_names: List[str], ir_program: Tuple
    ) -> List[ExecutionPath]:
        """Analyze a specific function with symbolic parameters"""
        self.current_path = self.path_manager.create_path()

        # Create symbolic parameters
        for param in param_names:
            symbol = self.current_env.create_symbol(param)
            self.current_env.set_variable(param, symbol)

        try:
            self._execute_ir(ir_program)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"Error: {e}")
                self.current_path.state = ExecutionPathState.ERROR

        if self.current_path:
            self.path_manager.add_path(self.current_path)

        return self.path_manager.finalize_paths()

    def _execute_ir(self, ir_node: Union[Tuple, str, Any]) -> SymbolicValue:
        """Execute an IR node and return its symbolic value"""
        if not isinstance(ir_node, (tuple, list)) or not ir_node:
            return self._handle_non_tuple_node(ir_node)

        # Try handlers first
        for handler in self.handlers:
            if handler.can_handle(ir_node):
                return handler.handle(ir_node, self)

        # Fallback to direct dispatch
        return self._dispatch_ir_node(ir_node)

    def _handle_non_tuple_node(self, ir_node: Any) -> SymbolicValue:
        """Handle non-tuple IR nodes"""
        if isinstance(ir_node, str) and ir_node.isidentifier():
            return self.current_env.get_variable(ir_node)
        return create_concrete_value(ir_node)

    def _dispatch_ir_node(self, ir_node: Tuple) -> SymbolicValue:
        """Dispatch IR node to appropriate handler method"""
        op = ir_node[0]

        # Binary operations that should use _execute_binary_op
        binary_ops = {
            "+", "-", "*", "/", "//", "%", "**",
            "==", "!=", "<", ">", "<=", ">=",
            "and", "or", "not"
        }

        dispatch_table = {
            "module": self._execute_module,
            "name": self._execute_name,
            "const": self._execute_const,
            "literal": self._execute_literal,
            "func_def": self._execute_func_def,
            "call": self._execute_call,
            "return": self._execute_return,
            "block": self._execute_block,
            "binary_op": self._execute_binary_op,
            "chained_compare": self._execute_chained_compare,
            "comparison": self._execute_comparison,
        }

        # Add binary operations to dispatch table
        for binary_op in binary_ops:
            dispatch_table[binary_op] = self._execute_binary_op

        if op in dispatch_table:
            return dispatch_table[op](ir_node)
        elif isinstance(op, str) and op.isdigit():
            return create_concrete_value(int(op))
        else:
            # Variable reference or literal
            if isinstance(op, str):
                return self.current_env.get_variable(op)
            return create_concrete_value(op)

    def _execute_module(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a module IR node"""
        for stmt in ir_node[1]:
            self._execute_ir(stmt)
        return create_concrete_value(None)

    def _execute_name(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a name (variable reference) IR node"""
        _, var_name = ir_node
        return self.current_env.get_variable(var_name)

    def _execute_const(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a constant IR node"""
        _, value = ir_node
        result = create_concrete_value(value)
        result.original_ir = ir_node
        return result

    def _execute_literal(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a literal IR node"""
        if len(ir_node) > 1:
            return create_concrete_value(ir_node[1])
        return create_concrete_value(None)

    def _execute_func_def(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a function definition"""
        _, func_name, params, body = ir_node
        self.global_env.functions[func_name] = (params, body)

        if self.current_path:
            params_str = ", ".join(params) if params else ""
            self.current_path.add_statement(f"def {func_name}({params_str}):")

        # Always analyze function for reporting purposes
        function_paths = self._analyze_function_definition(func_name, params, body)
        self.function_analyses[func_name] = function_paths

        # Only add to main paths if requested
        if self.include_function_paths:
            self._add_function_paths_to_main(func_name, params, function_paths)

        return create_concrete_value(None)

    def _analyze_function_definition(
        self, func_name: str, params: List[str], body_ir: Any
    ) -> List[ExecutionPath]:
        """Analyze all paths within a function definition"""
        # Save current state
        original_path_manager = self.path_manager
        original_current_path = self.current_path
        original_env = self.current_env

        # Reset for function analysis
        self.path_manager = PathManager()
        self.current_path = self.path_manager.create_path(f"func_{func_name}_")

        # Create function environment with symbolic parameters
        func_env = SymbolicEnvironment(self.global_env)
        for param in params:
            symbol = func_env.create_symbol(param)
            func_env.set_variable(param, symbol)
            self.current_path.variables[param] = symbol

        self.current_env = func_env

        try:
            self._execute_function_body(body_ir)
        except Exception as e:
            if self.current_path:
                self.current_path.add_statement(f"ERROR: {str(e)}")
                self.current_path.state = ExecutionPathState.ERROR

        # Collect function paths
        if self.current_path and self.current_path.is_satisfiable():
            self.path_manager.add_path(self.current_path)

        function_paths = self.path_manager.finalize_paths()

        # Restore original state
        self.path_manager = original_path_manager
        self.current_path = original_current_path
        self.current_env = original_env

        return function_paths

    def _execute_function_body(self, body_ir: Any) -> None:
        """Execute function body statements"""
        if isinstance(body_ir, (tuple, list)):
            for stmt in body_ir:
                if isinstance(stmt, str):  # Skip docstrings
                    continue
                self._execute_ir(stmt)
                if self.current_path is None:  # Return statement ended path
                    break
        else:
            self._execute_ir(body_ir)

    def _add_function_paths_to_main(
        self, func_name: str, params: List[str], function_paths: List[ExecutionPath]
    ) -> None:
        """Add function paths to main path collection"""
        for func_path in function_paths:
            func_path.path_id = f"func_{func_name}_{func_path.path_id}"
            context_stmt = f"# Function: {func_name}({', '.join(params)})"
            func_path.statements.insert(0, context_stmt)
            self.path_manager.add_path(func_path)

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
                    self.current_path.add_statement(
                        f"{return_symbol} = {func_name}({args_str})"
                    )
                return return_symbol
        else:
            # Unknown function
            result = self.current_env.create_symbol(f"unknown_{func_name}")
            if self.current_path:
                args_str = ", ".join(str(arg) for arg in args)
                self.current_path.add_statement(
                    f"{result} = {func_name}({args_str}) # unknown function"
                )
            return result

    def _execute_return(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a return statement"""
        if len(ir_node) > 1:
            value = self._execute_ir(ir_node[1])
        else:
            value = create_concrete_value(None)

        if self.current_path:
            self.current_path.return_value = value
            self.current_path.add_statement(f"return {self._simplify_display(value)}")
            self.current_path.state = ExecutionPathState.COMPLETED

        return value

    def _execute_block(self, ir_node: Tuple) -> SymbolicValue:
        """Execute a block of statements"""
        result = create_concrete_value(None)
        if len(ir_node) > 1:
            statements = (
                ir_node[1] if isinstance(ir_node[1], (tuple, list)) else ir_node[1:]
            )
            for stmt in statements:
                result = self._execute_ir(stmt)
        return result

    def _execute_binary_op(self, ir_node: Tuple) -> SymbolicValue:
        """Execute binary operations with enhanced Z3 constraint generation"""
        try:
            if len(ir_node) == 4:
                _, left_ir, op, right_ir = ir_node
                left = self._execute_ir(left_ir)
                right = self._execute_ir(right_ir)
            elif len(ir_node) == 3:
                op, left_ir, right_ir = ir_node
                left = self._execute_ir(left_ir)
                right = self._execute_ir(right_ir)
            elif len(ir_node) == 2:
                op, operand_ir = ir_node
                operand = self._execute_ir(operand_ir)
                return create_expression_value(f"{op}{operand}")
            else:
                return create_concrete_value(None)

            # Always create symbolic expressions for operations involving symbolic variables
            # This prevents boolean casting errors
            if (
                left.type == SymbolicValueType.SYMBOLIC
                or right.type == SymbolicValueType.SYMBOLIC
                or left.type == SymbolicValueType.EXPRESSION
                or right.type == SymbolicValueType.EXPRESSION
            ):
                expr = (op, left, right)
                return create_expression_value(expr)

            # Try concrete evaluation only if both operands are concrete
            if (
                left.type == SymbolicValueType.CONCRETE
                and right.type == SymbolicValueType.CONCRETE
            ):
                concrete_result = self._try_concrete_operation(
                    op, left.value, right.value
                )
                if concrete_result is not None:
                    return create_concrete_value(concrete_result)

            # Default to symbolic expression
            expr = (op, left, right)
            return create_expression_value(expr)

        except Exception as e:
            # Create a symbolic expression as fallback to avoid errors
            if len(ir_node) >= 3:
                if len(ir_node) == 4:
                    _, left_ir, op, right_ir = ir_node
                else:
                    op, left_ir, right_ir = ir_node
                # Create fallback symbolic expression
                left_sym = create_symbolic_value(str(left_ir))
                right_sym = create_symbolic_value(str(right_ir))
                expr = (op, left_sym, right_sym)
                return create_expression_value(expr)

            if self.current_path:
                self.current_path.add_statement(f"Error in binary operation: {e}")
                self.current_path.state = ExecutionPathState.ERROR
            return create_concrete_value(None)

    def _try_concrete_operation(
        self, op: str, left_val: Any, right_val: Any
    ) -> Optional[Any]:
        """Try to perform concrete operation"""
        try:
            operations = {
                "+": lambda a, b: a + b,
                "-": lambda a, b: a - b,
                "*": lambda a, b: a * b,
                "/": lambda a, b: a / b,
                "//": lambda a, b: a // b,
                "%": lambda a, b: a % b,
                "**": lambda a, b: a**b,
                "==": lambda a, b: a == b,
                "!=": lambda a, b: a != b,
                "<": lambda a, b: a < b,
                ">": lambda a, b: a > b,
                "<=": lambda a, b: a <= b,
                ">=": lambda a, b: a >= b,
                "and": lambda a, b: a and b,
                "or": lambda a, b: a or b,
            }
            if op in operations:
                return operations[op](left_val, right_val)
        except (ZeroDivisionError, TypeError, ValueError):
            pass
        return None




    def _execute_chained_compare(self, ir_node: Tuple) -> SymbolicValue:
        """Execute chained comparison"""
        if len(ir_node) >= 4:
            _, left_ir, op, right_ir = ir_node[:4]
            left = self._execute_ir(left_ir)
            right = self._execute_ir(right_ir)
            return create_expression_value((op, left, right))
        return create_concrete_value(None)

    def _execute_comparison(self, ir_node: Tuple) -> SymbolicValue:
        """Execute comparison operations"""
        return self._execute_binary_op(ir_node)

    def _generate_z3_constraint(self, condition: SymbolicValue) -> Optional[Any]:
        """Generate Z3 constraint from condition"""
        if Z3_AVAILABLE and hasattr(condition, "value"):
            try:
                return to_z3_expr(condition.value, self.current_env.z3_variables)
            except (TypeError, AttributeError, ValueError) as e:
                # Z3 constraint generation failed, will proceed without constraint
                if self.debug:
                    print(f"Debug: Z3 constraint generation failed: {e}")
        return None

    def _make_condition_readable(self, condition: Any) -> str:
        """Convert IR condition to readable format with recursive tuple handling"""
        if hasattr(condition, "value") and hasattr(condition, "type"):
            if condition.type == SymbolicValueType.EXPRESSION:
                return self._make_condition_readable(condition.value)
            elif condition.type == SymbolicValueType.SYMBOLIC:
                return condition.name or str(condition.value)
            elif condition.type == SymbolicValueType.CONCRETE:
                return str(condition.value)
            else:
                return str(condition)

        if isinstance(condition, tuple) and len(condition) >= 3:
            op, left, right = condition[0], condition[1], condition[2]
            left_readable = self._make_condition_readable(left)
            right_readable = self._make_condition_readable(right)
            return f"{left_readable} {op} {right_readable}"

        try:
            return self._convert_expression_readable(condition)
        except (AttributeError, TypeError, ValueError) as e:
            # Expression conversion failed, use string representation
            if self.debug:
                print(f"Debug: Condition readability conversion failed: {e}")
            return str(condition)

    def _simplify_display(self, value: Any) -> str:
        """Simplify value display for better readability"""
        if hasattr(value, "type") and hasattr(value, "value"):
            if hasattr(value, "original_ir") and value.original_ir:
                try:
                    return self._convert_value_display(value.original_ir)
                except (AttributeError, TypeError, ValueError):
                    # Original IR conversion failed, continue with other display options
                    pass

            if value.type == SymbolicValueType.CONCRETE:
                return str(value.value)
            elif value.type == SymbolicValueType.SYMBOLIC:
                return getattr(value, "name", str(value.value)) or str(value.value)
            else:  # EXPRESSION
                return self._simplify_display(value.value)

        try:
            return self._convert_value_display(value)
        except (AttributeError, TypeError, ValueError) as e:
            # Value display conversion failed, use string representation
            if self.debug:
                print(f"Debug: Value display conversion failed: {e}")
            return str(value)

    def _convert_expression_readable(self, expr: Any) -> str:
        """Internal simplified expression to readable format converter"""
        if isinstance(expr, str):
            return expr
        elif isinstance(expr, (int, float, bool)):
            return str(expr)
        elif isinstance(expr, tuple) and len(expr) >= 1:
            if len(expr) == 3 and isinstance(expr[0], str):
                op, left, right = expr
                left_str = self._convert_expression_readable(left)
                right_str = self._convert_expression_readable(right)
                return f"{left_str} {op} {right_str}"
            elif len(expr) == 2 and isinstance(expr[0], str):
                op, operand = expr
                operand_str = self._convert_expression_readable(operand)
                return f"{op}({operand_str})"
        return str(expr)

    def _convert_value_display(self, value: Any) -> str:
        """Internal simplified value display converter"""
        if isinstance(value, str):
            return value
        elif isinstance(value, (int, float, bool)):
            return str(value)
        elif isinstance(value, tuple):
            return self._convert_expression_readable(value)
        elif isinstance(value, list):
            items = [self._convert_value_display(item) for item in value]
            return f"[{', '.join(items)}]"
        return str(value)

    def generate_report(self, paths: List[ExecutionPath]) -> Dict[str, Any]:
        """Generate a comprehensive report of symbolic execution results"""
        report = generate_comprehensive_report(
            paths=paths,
            performance_mode=self.performance_mode,
            global_env_functions=self.global_env.functions,
            function_analyses=getattr(self, "function_analyses", None),
        )

        # Update symbolic variables count if available
        if hasattr(self.current_env, "z3_variables"):
            report["summary"]["constraint_analysis"]["symbolic_variables"] = len(
                self.current_env.z3_variables
            )

        return report

    def simplify_path_conditions(
        self, paths: List[ExecutionPath]
    ) -> List[ExecutionPath]:
        """Simplify and merge path conditions where possible"""
        simplified_paths = []

        for path in paths:
            if not path.conditions:
                simplified_paths.append(path)
                continue

            # Group conditions by variable for potential simplification
            grouped_conditions = group_conditions_by_variable(path.conditions)

            # Simplify conditions for each variable group
            simplified_conditions = []
            for var_name, conditions in grouped_conditions.items():
                if var_name and len(conditions) > 1:
                    merged_conditions = self._merge_conditions_for_variable(
                        var_name, conditions
                    )
                    simplified_conditions.extend(merged_conditions)
                else:
                    simplified_conditions.extend(conditions)

            # Add any conditions that couldn't be grouped by variable
            for condition in path.conditions:
                if not is_simple_variable_condition(condition.expression):
                    simplified_conditions.append(condition)

            # Create new path with simplified conditions
            simplified_path = ExecutionPath(path.path_id)
            simplified_path.conditions = simplified_conditions
            simplified_path.statements = path.statements
            simplified_path.return_value = path.return_value
            simplified_path.variables = path.variables
            simplified_path.loop_iterations = path.loop_iterations
            simplified_path.state = path.state
            simplified_path.test_inputs = path.test_inputs
            simplified_path.expected_outputs = path.expected_outputs
            simplified_path.z3_error = path.z3_error

            simplified_paths.append(simplified_path)

        return simplified_paths

    def _merge_conditions_for_variable(
        self, variable: str, conditions: List[PathCondition]
    ) -> List[PathCondition]:
        """Merge conditions for a single variable"""
        if len(conditions) <= 1:
            return conditions

        # Separate positive and negative conditions
        positive_conditions = [c for c in conditions if c.is_true]
        negative_conditions = [c for c in conditions if not c.is_true]

        # Try to merge negative conditions
        merged_negative = self._merge_negative_conditions(variable, negative_conditions)

        result = positive_conditions + merged_negative
        return result if result else conditions

    def _merge_negative_conditions(
        self, var_name: str, conditions: List[PathCondition]
    ) -> List[PathCondition]:
        """Merge negative conditions for the same variable"""
        import re

        negative_gt_conditions = []
        other_conditions = []

        for condition in conditions:
            if not condition.is_true and var_name in condition.expression:
                pattern = rf"{re.escape(var_name)}\s*>\s*(.+)"
                match = re.search(pattern, condition.expression)
                if match:
                    try:
                        value = float(match.group(1))
                        negative_gt_conditions.append((condition, value))
                    except ValueError:
                        other_conditions.append(condition)
                else:
                    other_conditions.append(condition)
            else:
                other_conditions.append(condition)

        # If we have multiple "not (var > value)" conditions, merge them
        if len(negative_gt_conditions) > 1:
            min_value = min(value for _, value in negative_gt_conditions)
            merged_condition = PathCondition(f"{var_name} <= {min_value}", True)
            other_conditions.append(merged_condition)
        elif len(negative_gt_conditions) == 1:
            other_conditions.append(negative_gt_conditions[0][0])

        return other_conditions

    def enhance_paths_with_test_cases(
        self, paths: List[ExecutionPath]
    ) -> List[ExecutionPath]:
        """Enhance execution paths with Z3-generated test case information"""
        return enhance_paths_with_z3_test_cases(paths)


# Utility functions for external access
def execute_symbolic_from_file(
    file_path: str, include_function_paths: bool = False, performance_mode: bool = False, debug: bool = False
) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR file"""
    try:
        with open(file_path, "r", encoding=Config.DEFAULT_ENCODING) as f:
            content = f.read().strip()

        ir_program = _parse_ir_content(content)
        executor = SymbolicExecutor(
            include_function_paths=include_function_paths,
            performance_mode=performance_mode,
            debug=debug,
        )
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from file '{file_path}': {e}")


def execute_symbolic_from_string(
    ir_string: str, include_function_paths: bool = False, performance_mode: bool = False, debug: bool = False
) -> List[ExecutionPath]:
    """Execute symbolic analysis from an IR string"""
    try:
        ir_program = _parse_ir_content(ir_string)
        executor = SymbolicExecutor(
            include_function_paths=include_function_paths,
            performance_mode=performance_mode,
            debug=debug,
        )
        return executor.execute_program(ir_program)

    except Exception as e:
        raise RuntimeError(f"Error in symbolic execution from string: {e}")


def _parse_ir_content(content: str) -> Tuple:
    """Parse IR content from string"""
    try:
        ir_program = json.loads(content)
        return _json_to_tuples(ir_program)
    except json.JSONDecodeError:
        content = content.replace("null", "None")
        return ast.literal_eval(content)


def _json_to_tuples(json_obj: Any) -> Any:
    """Convert JSON objects back to tuples for IR processing"""
    if isinstance(json_obj, list):
        return tuple(_json_to_tuples(item) for item in json_obj)
    elif isinstance(json_obj, dict):
        return {key: _json_to_tuples(value) for key, value in json_obj.items()}
    else:
        return json_obj
