from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

# Import symbolic execution utilities
from .symbolic_utils import (
    Config,
    ExecutionPathState,
    logger,
)
from .symbolic.condition_utils import PathCondition

from .symbolic.z3_utils import (
    Z3_AVAILABLE,
    check_path_satisfiability,
)

from .symbolic.builtin_utils import SymbolicValue

from .symbolic.report_utils import renumber_paths_sequentially

if Z3_AVAILABLE:
    import z3


@dataclass
class ExecutionPath:
    """Represents a single execution path through a function"""

    path_id: str
    conditions: List[PathCondition] = field(default_factory=list)
    statements: List[str] = field(default_factory=list)
    return_value: Optional[SymbolicValue] = None
    variables: Dict[str, SymbolicValue] = field(default_factory=dict)
    variable_types: Dict[str, str] = field(default_factory=dict)
    loop_iterations: Dict[str, int] = field(default_factory=dict)
    state: ExecutionPathState = ExecutionPathState.ACTIVE
    test_inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: Dict[str, Any] = field(default_factory=dict)
    z3_error: Optional[str] = None
    satisfiable: Optional[bool] = None

    def add_statement(self, statement: str) -> None:
        """Add an executed statement"""
        pass
        # TODO: temp disable show statements
        # self.statements.append(statement)

    def add_condition(self, condition: PathCondition) -> None:
        """Add a path condition"""
        self.conditions.append(condition)

    def is_satisfiable(self) -> bool:
        """Check if the path conditions are satisfiable using enhanced Z3 checking"""
        if not self.conditions:
            return True

        if self.state == ExecutionPathState.UNSATISFIABLE:
            return False

        # Use Z3-based satisfiability checking if available
        if Z3_AVAILABLE:
            # logger.debug(f"Z3 condition self.conditions: {self.conditions}")
            condition_strs = [str(c) for c in self.conditions]
            # logger.debug(f"Z3 condition strings: {condition_strs}")

            variable_z3_map = {}
            for k in self.variables:
                if k in self.variable_types:
                    atype = self.variable_types[k]
                    if atype == "int":
                        variable_z3_map[k] = z3.Int(k)
                    elif atype == "float":
                        variable_z3_map[k] = z3.Real(k)
                    elif atype == "bool":
                        variable_z3_map[k] = z3.Bool(k)
                    elif atype == "str":
                        variable_z3_map[k] = z3.String(k)
                    # elif atype == 'list':
                    #     variable_z3_map[k] = z3.Array(k, z3.IntSort(), z3.IntSort())
                    # elif atype == 'dict':
                    #     variable_z3_map[k] = z3.Array(k, z3.IntSort(), z3.IntSort())
                    # elif atype == 'tuple':
                    #     variable_z3_map[k] = z3.Array(k, z3.IntSort(), z3.IntSort())
                    # elif atype == 'set':
                    #     variable_z3_map[k] = z3.Array(k, z3.IntSort(), z3.IntSort())
                    # elif atype == 'frozenset':
                    #     variable_z3_map[k] = z3.Array(k, z3.IntSort(), z3.IntSort())
                else:
                    variable_z3_map[k] = z3.Int(k)

            is_sat_result, model_values = check_path_satisfiability(
                condition_strs, variable_z3_map
            )
            # logger.debug(f"Z3 is_sat_result: {is_sat_result}")
            # # logger.debug(f"Z3 model values: {model_values}")
            if not is_sat_result:
                self.state = ExecutionPathState.UNSATISFIABLE
            elif model_values:
                self.test_inputs = model_values  # Store test inputs from Z3 model
            else:
                # raise ValueError(f"Z3 model values are empty: {model_values}")
                logger.trace(f"Z3 model values are empty: {model_values}")
            # logger.debug(f"Z3 model values: {model_values}")
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

    def to_dict(path: Any) -> Dict[str, Any]:
        """Convert execution path to dictionary"""
        if path.satisfiable is None:
            path.satisfiable = path.is_satisfiable()
        path_dict = {
            "path_id": path.path_id,
            "conditions": [str(c) for c in path.conditions],
            "statements": path.statements,
            "return_value": path.return_value.value
            if hasattr(path.return_value, "value")
            else path.return_value,
            "variables": path.variables,
            "satisfiable": path.satisfiable,
            "loop_iterations": path.loop_iterations,
            "state": path.state.value,
            "test_inputs": path.test_inputs,
            "expected_outputs": getattr(path, "expected_outputs", {}),
            "z3_error": getattr(path, "z3_error", None),
        }
        return path_dict


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

        if path not in self.paths:
            path.satisfiable = path.is_satisfiable()
            if path.satisfiable:
                self.paths.append(path)
                return True
            else:
                raise ValueError("Path is not satisfiable")
                # TODO: if is_satisfiable is False, it is dead code?
        return False

    def copy_path(
        self, source_path: ExecutionPath, new_prefix: str = ""
    ) -> ExecutionPath:
        """Create a copy of an existing path"""
        new_path = self.create_path(new_prefix or Config.DEFAULT_PATH_PREFIX)
        new_path.conditions = source_path.conditions.copy()
        new_path.statements = source_path.statements.copy()
        new_path.variables = source_path.variables.copy()
        new_path.variable_types = source_path.variable_types.copy()
        new_path.loop_iterations = source_path.loop_iterations.copy()
        new_path.state = source_path.state
        return new_path

    def finalize_paths(self) -> List[ExecutionPath]:
        """Finalize and return processed paths"""
        # Remove duplicates and filter out empty paths
        seen_paths = set()
        unique_paths = []

        for path in self.paths:
            # Create a signature for the path based on conditions and final variables
            # Convert keys to strings and sort to avoid tuple comparison issues
            variable_items = []
            for k, v in path.variables.items():
                # Ensure the key is a string to avoid comparison issues
                key_str = str(k) if not isinstance(k, str) else k
                try:
                    variable_items.append((key_str, str(v)))
                except Exception as e:
                    logger.error(f"Error: {e}")
                    # Handle cases where str(v) might fail
                    variable_items.append((key_str, repr(v)))

            # Sort by string keys only
            sorted_variables = sorted(variable_items, key=lambda x: x[0])

            path_signature = (
                tuple(str(c) for c in path.conditions),
                tuple(sorted_variables),
            )

            if path_signature not in seen_paths and (
                path.statements or path.conditions or path.variables
            ):
                seen_paths.add(path_signature)
                unique_paths.append(path)

        # TODO: 确保至少返回一个路径
        if not unique_paths and self.paths:
            # 如果有原始路径但都被过滤掉了，返回第一个
            unique_paths = [self.paths[0]]

        return renumber_paths_sequentially(unique_paths)

    def __get_satisfiable_paths(self) -> List[ExecutionPath]:
        """Get all satisfiable paths"""
        return [p for p in self.paths if p.is_satisfiable()]
