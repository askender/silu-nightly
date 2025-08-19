#!/usr/bin/env python3
"""
Unit tests for the symbolic execution engine.
"""

import pytest
import json
from silu.symbolic_executor import (
    SymbolicExecutor,
    SymbolicValue,
    SymbolicValueType,
    PathCondition,
    ExecutionPath,
    SymbolicEnvironment,
    execute_symbolic_from_string,
)


class TestSymbolicValue:
    """Test SymbolicValue class"""

    def test_concrete_value(self):
        """Test concrete symbolic value"""
        val = SymbolicValue(SymbolicValueType.CONCRETE, 42)
        assert str(val) == "42"
        assert val.type == SymbolicValueType.CONCRETE

    def test_symbolic_value(self):
        """Test symbolic variable"""
        val = SymbolicValue(SymbolicValueType.SYMBOLIC, None, "x")
        assert str(val) == "x"
        assert val.type == SymbolicValueType.SYMBOLIC

    def test_expression_value(self):
        """Test symbolic expression"""
        val = SymbolicValue(SymbolicValueType.EXPRESSION, "(x + 1)")
        assert str(val) == "(x + 1)"
        assert val.type == SymbolicValueType.EXPRESSION


class TestPathCondition:
    """Test PathCondition class"""

    def test_true_condition(self):
        """Test true path condition"""
        cond = PathCondition("x > 5", True)
        assert str(cond) == "(x > 5)"

    def test_false_condition(self):
        """Test false path condition"""
        cond = PathCondition("x > 5", False)
        assert str(cond) == "not (x > 5)"

    def test_negate(self):
        """Test condition negation"""
        cond = PathCondition("x > 5", True)
        negated = cond.negate()
        assert negated.is_true == False
        assert negated.expression == "x > 5"


class TestExecutionPath:
    """Test ExecutionPath class"""

    def test_empty_path(self):
        """Test empty execution path"""
        path = ExecutionPath("path_0")
        assert path.path_id == "path_0"
        assert len(path.conditions) == 0
        assert len(path.statements) == 0
        assert path.is_satisfiable() == True

    def test_add_conditions(self):
        """Test adding conditions to path"""
        path = ExecutionPath("path_0")
        cond1 = PathCondition("x > 0", True)
        cond2 = PathCondition("x < 10", True)

        path.add_condition(cond1)
        path.add_condition(cond2)

        assert len(path.conditions) == 2
        assert path.is_satisfiable() == True

    def test_contradictory_conditions(self):
        """Test contradictory conditions"""
        path = ExecutionPath("path_0")
        cond1 = PathCondition("x > 5", True)
        cond2 = PathCondition("x > 5", False)

        path.add_condition(cond1)
        path.add_condition(cond2)

        assert path.is_satisfiable() == False

    def test_to_dict(self):
        """Test path serialization"""
        path = ExecutionPath("path_0")
        path.add_condition(PathCondition("x > 5", True))
        path.add_statement("print(x)")

        result = path.to_dict()
        assert result['path_id'] == "path_0"
        assert len(result['conditions']) == 1
        assert len(result['statements']) == 1


class TestSymbolicEnvironment:
    """Test SymbolicEnvironment class"""

    def test_create_symbol(self):
        """Test symbol creation"""
        env = SymbolicEnvironment()
        sym = env.create_symbol("x")
        assert sym.name == "x"
        assert sym.type == SymbolicValueType.SYMBOLIC

    def test_variable_storage(self):
        """Test variable storage and retrieval"""
        env = SymbolicEnvironment()
        sym = env.create_symbol("x")
        env.set_variable("x", sym)

        retrieved = env.get_variable("x")
        assert retrieved.name == "x"

    def test_undefined_variable(self):
        """Test access to undefined variable"""
        env = SymbolicEnvironment()
        sym = env.get_variable("undefined")
        assert sym.name == "undefined"
        assert sym.type == SymbolicValueType.SYMBOLIC

    def test_environment_copy(self):
        """Test environment copying"""
        env = SymbolicEnvironment()
        env.set_variable("x", env.create_symbol("x"))

        copy_env = env.copy()
        assert "x" in copy_env.variables
        assert copy_env.variables["x"].name == "x"


class TestSymbolicExecutor:
    """Test SymbolicExecutor class"""

    def test_simple_assignment(self):
        """Test symbolic execution of simple assignment"""
        ir = ("module", (("assign", "x", 42, None),))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert "x" in paths[0].variables
        assert paths[0].variables["x"].value == 42

    def test_simple_if_statement(self):
        """Test symbolic execution of if statement"""
        # if x > 5: y = 1 else: y = 2
        ir = ("module", (
            ("if",
             ("chained_compare", "x", ">", 5),
             ("block", (("assign", "y", 1, None),)),
             ("block", (("assign", "y", 2, None),))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        # Should create two paths: true and false
        assert len(paths) == 2

        # Check that both paths have different conditions
        conditions = [path.conditions[0].is_true for path in paths]
        assert True in conditions
        assert False in conditions

    def test_function_definition(self):
        """Test symbolic execution of function definition"""
        ir = ("module", (
            ("func_def", "test_func", ["x"],
             ("block", (("return", ("binary_op", "x", "+", 1)),))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert "test_func" in executor.global_env.functions

    def test_function_call(self):
        """Test symbolic execution of function call"""
        ir = ("module", (
            ("call", "print", ("x",)),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert "print(x)" in paths[0].statements

    def test_binary_operations(self):
        """Test symbolic execution of binary operations"""
        ir = ("module", (
            ("assign", "z", ("binary_op", "x", "+", "y"), None),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert "z" in paths[0].variables
        assert "x" in str(paths[0].variables["z"])
        assert "y" in str(paths[0].variables["z"])

    def test_while_loop(self):
        """Test symbolic execution of while loop"""
        ir = ("module", (
            ("while",
             ("chained_compare", "x", ">", 0),
             ("block", (("assign", "x", ("binary_op", "x", "-", 1), None),))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        # Should create paths for loop entry and non-entry
        assert len(paths) >= 2

    def test_return_statement(self):
        """Test symbolic execution of return statement"""
        ir = ("module", (
            ("return", 42),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert paths[0].return_value.value == 42

    def test_nested_if_statements(self):
        """Test symbolic execution of nested if statements"""
        ir = ("module", (
            ("if",
             ("chained_compare", "x", ">", 0),
             ("block", (
                 ("if",
                  ("chained_compare", "x", ">", 10),
                  ("block", (("assign", "y", 1, None),)),
                  ("block", (("assign", "y", 2, None),))
                 ),
             )),
             ("block", (("assign", "y", 0, None),))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        # Should create multiple paths for different combinations
        assert len(paths) >= 3

    def test_builtin_functions(self):
        """Test symbolic execution with builtin functions"""
        ir = ("module", (
            ("call", "int", ("3.14",)),
            ("call", "str", (42,)),
            ("call", "len", ("hello",)),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        # Check that builtin function calls are recorded
        statements = " ".join(paths[0].statements)
        assert "int" in statements or "str" in statements or "len" in statements

    def test_chained_comparisons(self):
        """Test symbolic execution of chained comparisons"""
        ir = ("module", (
            ("assign", "result", ("chained_compare", 1, "<", "x", "<", 10), None),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        assert len(paths) == 1
        assert "result" in paths[0].variables

    def test_report_generation(self):
        """Test symbolic execution report generation"""
        ir = ("module", (
            ("assign", "x", 5, None),
            ("if",
             ("chained_compare", "x", ">", 0),
             ("block", (("assign", "y", 1, None),)),
             ("block", (("assign", "y", 0, None),))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)
        report = executor.generate_report(paths)

        assert "total_paths" in report
        assert "satisfiable_paths" in report
        assert "paths" in report
        assert "summary" in report
        assert report["total_paths"] > 0

    def test_path_limit(self):
        """Test that path explosion is limited"""
        # Create a deeply nested if structure that would explode paths
        ir = ("module", (
            ("if", ("chained_compare", "a", ">", 0),
             ("block", (
                 ("if", ("chained_compare", "b", ">", 0),
                  ("block", (
                      ("if", ("chained_compare", "c", ">", 0),
                       ("block", (("assign", "x", 1, None),)),
                       ("block", (("assign", "x", 2, None),))
                      ),
                  )),
                  ("block", (("assign", "x", 3, None),))
                 ),
             )),
             ("block", (("assign", "x", 4, None),))
            ),
        ))

        executor = SymbolicExecutor()
        executor.max_paths = 10  # Set a low limit for testing
        paths = executor.execute_program(ir)

        # Should be limited by max_paths
        assert len(paths) <= executor.max_paths


class TestSymbolicExecutionFromString:
    """Test symbolic execution from IR strings"""

    def test_simple_ir_string(self):
        """Test executing symbolic analysis from IR string"""
        ir_string = '("module", (("assign", "x", 42, null),))'
        paths = execute_symbolic_from_string(ir_string)

        assert len(paths) == 1
        assert "x" in paths[0].variables

    def test_json_ir_string(self):
        """Test executing symbolic analysis from JSON IR string"""
        ir_dict = ["module", [["assign", "x", 42, None]]]
        ir_string = json.dumps(ir_dict)
        paths = execute_symbolic_from_string(ir_string)

        assert len(paths) == 1
        assert "x" in paths[0].variables

    def test_invalid_ir_string(self):
        """Test handling of invalid IR string"""
        with pytest.raises(RuntimeError):
            execute_symbolic_from_string("invalid ir")


class TestIntegration:
    """Integration tests for symbolic execution"""

    def test_factorial_function_symbolic(self):
        """Test symbolic execution of factorial function"""
        ir = ("module", (
            ("func_def", "factorial", ["n"],
             ("block", (
                 ("if",
                  ("chained_compare", "n", "<=", 1),
                  ("block", (("return", 1),)),
                  ("block", (
                      ("return", ("binary_op", "n", "*",
                                  ("call", "factorial", (("binary_op", "n", "-", 1),)))),
                  ))
                 ),
             ))
            ),
            ("assign", "result", ("call", "factorial", (5,)), None),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        # Should have paths for the recursive calls
        assert len(paths) > 0
        assert "factorial" in executor.global_env.functions

    def test_complex_control_flow(self):
        """Test symbolic execution with complex control flow"""
        ir = ("module", (
            ("assign", "x", 10, None),
            ("while",
             ("chained_compare", "x", ">", 0),
             ("block", (
                 ("if",
                  ("chained_compare", "x", "%", 2, "==", 0),
                  ("block", (("assign", "x", ("binary_op", "x", "/", 2), None),)),
                  ("block", (("assign", "x", ("binary_op", "x", "-", 1), None),))
                 ),
                 ("call", "print", ("x",)),
             ))
            ),
        ))

        executor = SymbolicExecutor()
        paths = executor.execute_program(ir)

        # Should generate multiple paths due to control flow
        assert len(paths) > 0

        # Verify that paths contain expected statements
        all_statements = []
        for path in paths:
            all_statements.extend(path.statements)

        assert any("while" in stmt for stmt in all_statements)
        assert any("print" in stmt for stmt in all_statements)


if __name__ == "__main__":
    pytest.main([__file__])
