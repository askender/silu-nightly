# Development Guide

This guide covers installation, development setup, testing, and contributing to the Silu programming language project.

## Prerequisites

- Python 3.11 or later
- `uv` (recommended) or `pip` for package management

## Installation

### For Users

#### Using pip (Standard Installation)
```bash
# Install from source
git clone <repository-url>
cd silu
pip install .

# Or install in development mode
pip install -e .
```

#### Using uv (Recommended for Development)
```bash
# Clone repository
git clone <repository-url>
cd silu

# Install with uv (handles virtual environment automatically)
uv sync

# Install in development mode
uv pip install -e .
```

### For Developers

#### Setup Development Environment
```bash
# Clone the repository
git clone <repository-url>
cd silu

# Using uv (recommended)
uv sync                # Install all dependencies
uv pip install -e .    # Install in development mode

# Using pip (alternative)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
pip install pytest ruff  # Development dependencies
```

## Development Workflow

### Project Structure
```
silu/
├── silu/                   # Main package
│   ├── __main__.py        # Entry point
│   ├── cli.py            # Command-line interface
│   ├── ast_processor.py  # Base AST processor
│   ├── interpreter.py    # Core interpreter
│   ├── ir_generator.py   # IR generation
│   └── symbolic_executor.py # Symbolic execution
├── tests/                 # Test suite
├── docs/                  # Documentation
├── demo*.si              # Example programs
├── makefile              # Build automation
└── pyproject.toml        # Project configuration
```

### Common Development Tasks

#### Running Tests
```bash
# Using make (recommended)
make test         # Run all tests
make cov          # Run tests with coverage report

# Using uv
uv run pytest tests/

# Using pytest directly
pytest tests/     # Run all tests
pytest tests/test_interpreter.py  # Run specific test file
pytest -v         # Verbose output
pytest --cov      # With coverage
```

#### Code Formatting
```bash
# Format code with ruff
make fmt

# Or manually
ruff format silu/ tests/
ruff check silu/ tests/
```

#### Running Silu Programs
```bash
# Traditional usage
silu program.si

# Different modes
silu interpret program.si --debug
silu ir program.si --format json
silu symbolic program.si

# From source
silu interpret --source "print('Hello')"
```

#### Cleaning Build Artifacts
```bash
make rm          # Remove Python bytecode caches
# Native build artifacts live in the repository or the user cache;
# remove them manually only when you intend to rebuild.
```

## Testing

### Test Structure
```
tests/
├── test_interpreter.py    # Core interpreter tests
├── test_cli.py           # CLI interface tests
├── test_main.py          # Main module tests
└── test_*.py            # Additional test modules
```

### Writing Tests
```python
import pytest
from silu.interpreter import SiluInterpreter

def test_new_feature():
    """Test description."""
    interpreter = SiluInterpreter()
    # Test implementation
    assert expected_result == actual_result

def test_error_handling():
    """Test error conditions."""
    interpreter = SiluInterpreter()
    with pytest.raises(ExpectedError):
        # Code that should raise error
        pass
```

### Test Categories
- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **End-to-End Tests**: Test complete program execution
- **CLI Tests**: Test command-line interface
- **Error Handling Tests**: Test error conditions and recovery

### Coverage Requirements
- Aim for >90% code coverage
- Critical paths should have 100% coverage
- All error conditions should be tested

## Code Architecture

### Design Principles
1. **Single Responsibility**: Each class has one clear purpose
2. **Open/Closed**: Open for extension, closed for modification
3. **DRY (Don't Repeat Yourself)**: Shared logic in base classes
4. **Separation of Concerns**: Clear boundaries between components

### Key Components

#### BaseASTProcessor
- Abstract base class for all AST processing
- Shared traversal logic and operator mappings
- Extensible design for new processor types

#### SiluInterpreter
- Concrete implementation for program execution
- Manages execution environment and variable scope
- Handles built-in functions and error conditions

#### SiluIRGenerator
- Converts AST to intermediate representation
- Supports multiple output formats (JSON, pretty, compact)
- Enables analysis and optimization passes

#### SymbolicExecutor
- Performs symbolic program analysis
- Discovers all execution paths
- Generates constraints and path conditions

### Adding New Features

#### Extending Language Syntax
1. Update `BaseASTProcessor` with new node visitor methods
2. Implement behavior in concrete processors (interpreter, IR generator)
3. Add comprehensive tests
4. Update documentation

#### Adding New AST Processors
1. Extend `BaseASTProcessor`
2. Implement required abstract methods
3. Add to CLI interface if needed
4. Include factory functions for easy instantiation

## Debugging

### Debug Mode
```bash
# Enable debug output
silu interpret program.si --debug

# Debug with source code
silu interpret --source "x = 5; print(x)" --debug
```

### Common Debugging Techniques
1. **Print Debugging**: Add print statements to trace execution
2. **AST Inspection**: Examine parsed AST structure
3. **Environment Inspection**: Check variable states and scopes
4. **Step-by-Step Execution**: Use debug mode for detailed traces

### Logging
The interpreter supports debug logging for development:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
# Run interpreter with detailed logs
```

## Contributing

### Contribution Workflow
1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and add tests
4. Run full test suite: `make test`
5. Format code: `make fmt`
6. Commit changes with clear messages
7. Push branch and create pull request

### Commit Messages
Follow conventional commit format:
```
type(scope): description

Examples:
feat(interpreter): add support for list comprehensions
fix(cli): handle missing file error gracefully
test(interpreter): add tests for error handling
docs(readme): update installation instructions
```

### Code Review Process
1. All changes require review
2. Tests must pass
3. Code coverage should not decrease
4. Documentation should be updated for new features

## Performance Considerations

### Benchmarking
```bash
# Compare interpretation vs IR execution
time silu interpret large_program.si
time silu exec large_program.ir.json

# Profile memory usage
python -m memory_profiler silu interpret program.si
```

### Optimization Guidelines
1. Minimize AST traversals
2. Cache frequently accessed data
3. Use efficient data structures
4. Consider IR execution for performance-critical applications

## Release Process

### Version Management
- Follow semantic versioning (MAJOR.MINOR.PATCH)
- Update version in `pyproject.toml`
- Tag releases in git

### Release Checklist
1. Run full test suite
2. Update documentation
3. Update changelog
4. Create git tag
5. Build and test package
6. Deploy to package repository

## Troubleshooting

### Common Issues

#### Import Errors
```bash
# Ensure package is installed in development mode
pip install -e .
# Or with uv
uv pip install -e .
```

#### Test Failures
```bash
# Reinstall the development checkout
uv sync
make test
```

#### Performance Issues
```bash
# Use IR execution for better performance
silu ir program.si --output program.ir.json
silu exec program.ir.json
```

## Resources

- [Language Features](language_features.md)
- [CLI Usage Guide](cli_usage.md)
- [Symbolic Execution](symbolic_execution.md)
- [IR Design](simple_ir_design.md)
- [Interpreter Specification](interpreter_spec.md)