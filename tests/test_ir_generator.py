"""
Unit tests for the Silu IR generator module.
"""

import ast
from silu.ir_generator import SiluIRGenerator


class TestSiluIRGenerator:
    """Tests for the SiluIRGenerator class."""

    def test_process_name_load(self):
        """Test processing a name with load context."""
        generator = SiluIRGenerator()
        result = generator.process_name("x", ast.Load())
        expected = "x"
        assert result == expected

    def test_process_name_store(self):
        """Test processing a name with store context."""
        generator = SiluIRGenerator()
        result = generator.process_name("x", ast.Store())
        expected = "x"
        assert result == expected

    def test_process_name_unsupported_context(self):
        """Test processing a name with unsupported context."""
        generator = SiluIRGenerator()
        # Current implementation doesn't validate context, just returns name
        result = generator.process_name("x", ast.Del())
        assert result == "x"

    def test_process_operation_binary(self):
        """Test processing binary operations."""
        generator = SiluIRGenerator()

        # Test addition
        result = generator.process_operation("+", 5, 3)
        expected = ("+", 5, 3)
        assert result == expected

        # Test multiplication
        result = generator.process_operation("*", 4, 6)
        expected = ("*", 4, 6)
        assert result == expected

    def test_process_operation_unary(self):
        """Test processing unary operations."""
        generator = SiluIRGenerator()

        # Test unary minus
        result = generator.process_operation("-", 5)
        expected = ("-", 5)
        assert result == expected

        # Test not operation
        result = generator.process_operation("not", True)
        expected = ("not", True)
        assert result == expected

    def test_visit_module(self):
        """Test visiting a module."""
        generator = SiluIRGenerator()

        # Create a module with an assignment
        assign_target = ast.Name(id="x", ctx=ast.Store())
        assign_value = ast.Constant(value=42)
        assign_node = ast.Assign(targets=[assign_target], value=assign_value)
        module = ast.Module(body=[assign_node], type_ignores=[])

        result = generator.visit_Module(module)
        assert isinstance(result, tuple)
        assert result[0] == "module"
        assert len(result[1]) == 1

    def test_visit_assign(self):
        """Test visiting an assignment."""
        generator = SiluIRGenerator()

        # Create an assignment
        target = ast.Name(id="x", ctx=ast.Store())
        value = ast.Constant(value=42)
        assign = ast.Assign(targets=[target], value=value)

        result = generator.visit_Assign(assign)
        expected = ("assign", "x", 42, None)
        assert result == expected

    def test_visit_binop(self):
        """Test visiting binary operations."""
        generator = SiluIRGenerator()

        # Create a binary operation
        left = ast.Constant(value=5)
        right = ast.Constant(value=3)
        binop = ast.BinOp(left=left, op=ast.Add(), right=right)

        result = generator.visit_BinOp(binop)
        expected = ("+", 5, 3)
        assert result == expected

    def test_visit_unaryop(self):
        """Test visiting unary operations."""
        generator = SiluIRGenerator()

        # Create a unary operation
        operand = ast.Constant(value=5)
        unaryop = ast.UnaryOp(op=ast.USub(), operand=operand)

        result = generator.visit_UnaryOp(unaryop)
        expected = ("-", 5)
        assert result == expected

    def test_visit_compare(self):
        """Test visiting comparisons."""
        generator = SiluIRGenerator()

        # Create a comparison
        left = ast.Constant(value=5)
        comparators = [ast.Constant(value=3)]
        ops = [ast.Lt()]
        compare = ast.Compare(left=left, ops=ops, comparators=comparators)

        result = generator.visit_Compare(compare)
        expected = ("<", 5, 3)
        assert result == expected

    def test_visit_boolop(self):
        """Test visiting boolean operations."""
        generator = SiluIRGenerator()

        # Create a boolean operation
        values = [ast.Constant(value=True), ast.Constant(value=False)]
        boolop = ast.BoolOp(op=ast.And(), values=values)

        result = generator.visit_BoolOp(boolop)
        expected = ("and", True, False)
        assert result == expected

    def test_visit_name(self):
        """Test visiting names."""
        generator = SiluIRGenerator()

        # Test load context
        name_load = ast.Name(id="x", ctx=ast.Load())
        result = generator.visit_Name(name_load)
        expected = "x"
        assert result == expected

        # Test store context
        name_store = ast.Name(id="y", ctx=ast.Store())
        result = generator.visit_Name(name_store)
        expected = "y"
        assert result == expected

    def test_visit_constant(self):
        """Test visiting constants."""
        generator = SiluIRGenerator()

        # Test integer constant
        const_int = ast.Constant(value=42)
        assert generator.visit_Constant(const_int) == 42

        # Test string constant
        const_str = ast.Constant(value="hello")
        assert generator.visit_Constant(const_str) == "hello"

        # Test boolean constant
        const_bool = ast.Constant(value=True)
        assert generator.visit_Constant(const_bool) is True

        # Test float constant
        const_float = ast.Constant(value=3.14)
        assert generator.visit_Constant(const_float) == 3.14

    def test_visit_expr(self):
        """Test visiting expressions."""
        generator = SiluIRGenerator()

        # Create an expression
        value = ast.Constant(value=42)
        expr = ast.Expr(value=value)

        result = generator.visit_Expr(expr)
        assert result == 42

    def test_complex_expression(self):
        """Test visiting a complex expression."""
        generator = SiluIRGenerator()

        # Create: x = 10 + 5 * 2
        left = ast.Constant(value=10)
        mult_left = ast.Constant(value=5)
        mult_right = ast.Constant(value=2)
        mult = ast.BinOp(left=mult_left, op=ast.Mult(), right=mult_right)
        add = ast.BinOp(left=left, op=ast.Add(), right=mult)

        target = ast.Name(id="x", ctx=ast.Store())
        assign = ast.Assign(targets=[target], value=add)

        result = generator.visit_Assign(assign)
        expected = ("assign", "x", ("+", 10, ("*", 5, 2)), None)
        assert result == expected

    def test_chained_comparison(self):
        """Test visiting chained comparisons."""
        generator = SiluIRGenerator()

        # Create: 1 < x < 10
        left = ast.Constant(value=1)
        comparators = [ast.Name(id="x", ctx=ast.Load()), ast.Constant(value=10)]
        ops = [ast.Lt(), ast.Lt()]
        compare = ast.Compare(left=left, ops=ops, comparators=comparators)

        result = generator.visit_Compare(compare)
        expected = ("chained_compare", [("<", 1, "x"), ("<", "x", 10)])
        assert result == expected

    def test_nested_operations(self):
        """Test visiting nested operations."""
        generator = SiluIRGenerator()

        # Create: (a + b) * (c - d)
        # Left side: a + b
        left_a = ast.Name(id="a", ctx=ast.Load())
        left_b = ast.Name(id="b", ctx=ast.Load())
        left_add = ast.BinOp(left=left_a, op=ast.Add(), right=left_b)

        # Right side: c - d
        right_c = ast.Name(id="c", ctx=ast.Load())
        right_d = ast.Name(id="d", ctx=ast.Load())
        right_sub = ast.BinOp(left=right_c, op=ast.Sub(), right=right_d)

        # Multiply them
        mult = ast.BinOp(left=left_add, op=ast.Mult(), right=right_sub)

        result = generator.visit_BinOp(mult)
        expected = ("*", ("+", "a", "b"), ("-", "c", "d"))
        assert result == expected
