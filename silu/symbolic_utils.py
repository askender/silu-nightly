from enum import Enum
from loguru import logger
import sys
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple
from abc import ABC, abstractmethod


from .symbolic.builtin_utils import (
    SymbolicValueType,
    SymbolicValue,
    create_symbolic_value,
)

from .symbolic.z3_utils import (
    Z3_AVAILABLE,
)

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

logger.remove()  # 移除默认的 handler
logger.add(
    sink=sys.stderr,   # 或 sys.stdout
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{file.path}</cyan>:<cyan>{line}</cyan>:<cyan>{function}</cyan>: - "
        "<level>{message}</level>"
    ),
    colorize=True
)

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

    def has_variable(self, name: str) -> bool:
        """Check if a variable exists in the current or parent scope"""
        if name in self.variables:
            return True
        elif self.parent:
            return self.parent.has_variable(name)
        return False

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
