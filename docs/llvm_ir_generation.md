# Silu IR to LLVM IR Generation

This document describes the Silu IR to LLVM IR converter, which enables compilation of Silu programs to native machine code through the LLVM infrastructure.

## Overview

The Silu IR to LLVM IR converter bridges the gap between Silu's high-level, dynamically-typed intermediate representation and LLVM's low-level, statically-typed IR. This enables Silu programs to be compiled to efficient native code using the LLVM toolchain.

### Key Features

- **Dynamic Type Support**: Implements a runtime object system to handle Silu's dynamic typing
- **Memory Management**: Automatic memory allocation and management for Python-like objects
- **Built-in Operations**: Support for arithmetic, string operations, and I/O
- **Control Flow**: Basic support for conditionals and loops
- **Function Calls**: Support for function definitions and calls
- **CLI Integration**: Seamless integration with the Silu command-line interface

## Architecture

### Runtime Object System

The converter implements a runtime system that represents Python-like objects in LLVM IR:

```c
// PyObject structure: { i32 type_tag, i8* data }
struct PyObject {
    i32 type_tag;    // 0=int, 1=float, 2=str, 3=bool, 4=list, 5=dict, 6=none
    i8* data;        // Pointer to actual data
};

// String structure: { i32 length, i8* chars }
struct String {
    i32 length;
    i8* chars;
};
```

### Type System

| Silu Type | Type Tag | LLVM Representation |
|-----------|----------|-------------------|
| `int` | 0 | `i64*` (pointer to 64-bit integer) |
| `float` | 1 | `double*` (pointer to double) |
| `str` | 2 | `String*` (pointer to string structure) |
| `bool` | 3 | `i1*` (pointer to boolean) |
| `list` | 4 | `List*` (pointer to list structure) |
| `dict` | 5 | `Dict*` (pointer to dictionary structure) |
| `none` | 6 | `null` |

### Runtime Functions

The converter generates several runtime support functions:

- **Object Creation**: `create_int(i64)`, `create_str(i8*, i32)`
- **Operations**: `pyobj_add(PyObject*, PyObject*)`
- **I/O**: `pyobj_print(PyObject*)`
- **Memory**: Uses standard `malloc`/`free` for dynamic allocation

## Usage

### Command Line Interface

#### Generate LLVM IR from Silu IR

```bash
# Convert IR file to LLVM IR
python -m silu.cli llvm program.ir.json --output program.ll

# Convert IR string to LLVM IR (stdout)
python -m silu.cli llvm --source '[["module", [["assign", "x", ["const", 5], null]]]]'

# Pipe IR generation to LLVM conversion
python -m silu.cli ir program.si | python -m silu.cli llvm --source
```

#### Complete Workflow

```bash
# 1. Generate Silu IR from source
python -m silu.cli ir program.si --output program.ir.json

# 2. Convert to LLVM IR
python -m silu.cli llvm program.ir.json --output program.ll

# 3. Compile with LLVM tools
llc program.ll -o program.s      # Generate assembly
clang program.s -o program       # Link to executable
./program                        # Run the program
```

### Programmatic API

```python
from silu_ir_to_llvm import SiluToLLVMConverter
import json

# Load Silu IR
with open('program.ir.json', 'r') as f:
    ir_json = f.read()

# Convert to LLVM IR
converter = SiluToLLVMConverter()
llvm_ir = converter.convert(ir_json)

# Save result
converter.save_to_file(llvm_ir, 'program.ll')
```

## Supported Features

### ✅ Currently Supported

- **Basic Data Types**: Integers, strings
- **Variable Assignment**: Simple assignment statements
- **Arithmetic Operations**: Addition (others planned)
- **Function Calls**: `print()` function
- **Control Flow**: Basic if statements and loops (simplified)
- **String Literals**: Null-terminated string constants
- **Memory Management**: Dynamic allocation for objects

### 🚧 Partially Supported

- **Conditionals**: Basic structure (always takes true branch)
- **Loops**: Basic structure (executes body once)
- **Function Definitions**: Parsed but not fully implemented

### ❌ Not Yet Supported

- **Advanced Arithmetic**: Multiplication, division, modulo
- **Comparison Operations**: Equality, inequality, ordering
- **Boolean Operations**: AND, OR, NOT
- **Container Types**: Lists, dictionaries
- **Exception Handling**: Try/catch blocks
- **Advanced Control Flow**: Break, continue, nested loops
- **Closures**: Function closures and lexical scoping

## Examples

### Simple Arithmetic

**Silu Source:**
```python
x = 5
y = 3
result = x + y
print("Result:", result)
```

**Generated LLVM IR Key Parts:**
```llvm
; Create integers
%x = call {i32, i8*}* @create_int(i64 5)
%y = call {i32, i8*}* @create_int(i64 3)

; Perform addition
%result = call {i32, i8*}* @pyobj_add({i32, i8*}* %x, {i32, i8*}* %y)

; Print result
call void @pyobj_print({i32, i8*}* %result)
```

### String Operations

**Silu Source:**
```python
message = "Hello, World!"
print(message)
```

**Generated LLVM IR Key Parts:**
```llvm
; Create string constant
@str_const = constant [14 x i8] c"Hello, World!\00"

; Create string object
%message = call {i32, i8*}* @create_str(i8* @str_const, i32 13)

; Print string
call void @pyobj_print({i32, i8*}* %message)
```

## Performance Considerations

### Memory Management

- **Dynamic Allocation**: All objects are heap-allocated using `malloc`
- **No Garbage Collection**: Manual memory management (potential for leaks)
- **Tagged Unions**: Type checking at runtime adds overhead

### Optimization Opportunities

1. **Escape Analysis**: Stack-allocate objects that don't escape
2. **Type Specialization**: Generate specialized code for known types
3. **Inlining**: Inline simple operations like integer addition
4. **Dead Code Elimination**: Remove unused object creations

## Error Handling

### Conversion Errors

The converter handles various error conditions:

```python
try:
    llvm_ir = converter.convert(ir_json)
except ValueError as e:
    print(f"Invalid JSON: {e}")
except Exception as e:
    print(f"Conversion error: {e}")
```

### Common Issues

1. **Invalid JSON**: Malformed Silu IR JSON
2. **Unsupported Operations**: IR nodes not yet implemented
3. **Type Mismatches**: Unexpected IR structure
4. **LLVM Errors**: Invalid IR generation

## Development and Extension

### Adding New Operations

To add support for a new operation (e.g., multiplication):

1. **Add Runtime Function**:
```python
def _create_pyobj_multiply(self):
    multiply_ty = ir.FunctionType(
        ir.PointerType(self.pyobj.pyobj_type),
        [ir.PointerType(self.pyobj.pyobj_type), ir.PointerType(self.pyobj.pyobj_type)]
    )
    self.pyobj_multiply = ir.Function(self.module, multiply_ty, name="pyobj_multiply")
    # Implementation...
```

2. **Handle in Converter**:
```python
elif op == "*":
    if len(node) >= 3:
        left = self._convert_node(node[1])
        right = self._convert_node(node[2])
        if left and right:
            return self.current_builder.call(self.pyobj_multiply, [left, right])
```

### Adding New Types

To add support for a new type (e.g., boolean):

1. **Update Type System**: Add new type tag
2. **Create Constructor**: `create_bool(i1)`
3. **Update Operations**: Handle boolean in existing operations
4. **Update Print Function**: Add boolean case to `pyobj_print`

## Testing

### Unit Tests

```bash
# Run LLVM converter tests
python test_llvm_converter.py
```

### Integration Tests

```bash
# Test complete workflow
python demo_silu_to_llvm.py --save-files

# Test CLI integration
python -m silu.cli llvm test_minimal.ir.json --output test.ll
```

### Validation

The generated LLVM IR can be validated using LLVM tools:

```bash
# Validate LLVM IR syntax
llvm-as program.ll -o program.bc

# Optimize and analyze
opt -O2 program.bc -o program_opt.bc
llvm-dis program_opt.bc -o program_opt.ll
```

## Future Enhancements

### Short Term

- [ ] Complete arithmetic operations (*, /, %, **)
- [ ] Comparison operations (==, !=, <, >, <=, >=)
- [ ] Boolean operations (and, or, not)
- [ ] Proper conditional and loop implementation

### Medium Term

- [ ] Container types (lists, dictionaries)
- [ ] Exception handling
- [ ] Function definitions and calls
- [ ] Garbage collection or reference counting

### Long Term

- [ ] JIT compilation support
- [ ] Optimization passes
- [ ] Debug information generation
- [ ] Native library integration

## Dependencies

- **llvmlite**: LLVM Python bindings
- **Python 3.8+**: Core language support
- **LLVM 14+**: Target LLVM version

## Installation

The LLVM IR converter is included with Silu and automatically available when `llvmlite` is installed:

```bash
# Install with LLVM support
uv add llvmlite

# Verify installation
python -c "from silu_ir_to_llvm import SiluToLLVMConverter; print('LLVM converter available')"
```

## Troubleshooting

### Common Problems

1. **ImportError: No module named 'llvmlite'**
   - Solution: Install llvmlite with `uv add llvmlite`

2. **LLVM IR compilation fails**
   - Check IR syntax with `llvm-as`
   - Verify target triple compatibility

3. **Runtime crashes**
   - Check for null pointer dereferences
   - Verify memory allocation/deallocation

4. **Incorrect output**
   - Compare with Silu interpreter output
   - Check type handling in runtime functions

### Getting Help

- Review generated LLVM IR for debugging
- Use LLVM tools for validation and analysis
- Check Silu IR format and structure
- Report issues with minimal reproduction cases

## References

- [LLVM Language Reference Manual](https://llvm.org/docs/LangRef.html)
- [llvmlite Documentation](https://llvmlite.readthedocs.io/)
- [Silu Simple IR Design](simple_ir_design.md)
- [Silu CLI Usage](cli_usage.md)