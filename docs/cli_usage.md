# CLI Usage Guide

The Silu CLI provides multiple modes of operation for different use cases.

## Command Structure

```bash
silu <command> [options] [file]
```

## Available Commands

### 1. Traditional Usage (Interpretation)

The default mode interprets and executes Silu programs directly:

```bash
# Run a Silu program
silu your_program.si

# Equivalent explicit form
silu interpret your_program.si
```

### 2. Interpret Command

Explicit interpretation mode with additional options:

```bash
# Interpret a Silu file
silu interpret your_program.si

# Interpret source code directly from command line
silu interpret --source "x = 5; print(x)"

# Enable debug mode for detailed execution information
silu interpret your_program.si --debug

# Combine source and debug
silu interpret --source "print('Debug test')" --debug
```

**Options:**
- `--source TEXT`: Execute source code directly instead of reading from file
- `--debug`: Enable debug output showing execution details

### 3. IR Generation Command

Generate intermediate representation (IR) from Silu programs:

```bash
# Generate IR in pretty format (default, human-readable)
silu ir your_program.si

# Generate IR in JSON format (machine-readable)
silu ir your_program.si --format json

# Generate IR in compact format (minimal whitespace)
silu ir your_program.si --format compact

# Save IR to a specific file
silu ir your_program.si --output program.ir.json --format json

# Generate IR from source code directly
silu ir --source "x = 5; print(x)" --format json
```

**Options:**
- `--format [pretty|json|compact]`: Output format (default: pretty)
- `--output PATH`: Save output to specified file
- `--source TEXT`: Process source code directly instead of reading from file

**Output Formats:**
- `pretty`: Human-readable format with indentation
- `json`: Valid JSON format for programmatic processing
- `compact`: Minimal format without extra whitespace

### 4. Execute IR Command

Execute pre-generated IR files directly:

```bash
# Execute IR file
silu exec program.ir.json

# Execute IR from source string
silu exec --source '("module", (("assign", "x", 42, null),))'

# Alternative execution method
python -m silu exec program.ir.json
```

**Options:**
- `--source TEXT`: Execute IR directly from command line

### 5. Symbolic Execution Command

Perform symbolic analysis to discover all possible execution paths:

```bash
# Analyze a Silu program
silu symbolic your_program.si

# Analyze pre-generated IR directly
silu symbolic program.ir.json

# Analyze source code directly
silu symbolic --source "if x > 5: y = 1 else: y = 2"

# Simplify path conditions to reduce complexity
silu symbolic your_program.si --simplify
```

**Options:**
- `--source TEXT`: Analyze source code directly instead of reading from file
- `--simplify`: Simplify and merge path conditions where possible (reduces condition complexity)

**Output:** JSON report containing:
- All discovered execution paths
- Path conditions and constraints
- Branch coverage information
- Symbolic variable states

## Global Options

```bash
# Show general help
silu --help

# Show help for specific commands
silu interpret --help
silu ir --help
silu exec --help
silu symbolic --help

# Show version information
silu --version
```

## Common Workflows

### Development Workflow
```bash
# 1. Write and test your program
silu interpret my_program.si --debug

# 2. Generate IR for analysis
silu ir my_program.si --format json --output my_program.ir

# 3. Execute IR directly (faster for repeated runs)
silu exec my_program.ir

# 4. Perform symbolic analysis
silu symbolic my_program.si

# 4a. Perform symbolic analysis with condition simplification
silu symbolic my_program.si --simplify
```

### Performance Testing Workflow
```bash
# Compare interpretation vs IR execution performance
time silu interpret large_program.si
time silu exec large_program.ir
```

### Analysis Workflow
```bash
# Generate all analysis outputs
silu ir program.si --format json --output program.ir
silu symbolic program.si > analysis_report.json

# Generate simplified analysis for cleaner output
silu symbolic program.si --simplify > simplified_analysis.json
```

## File Extensions

- `.si`: Silu source files
- `.ir`: IR files (any format)
- `.ir.json`: JSON-format IR files (recommended for programmatic use)

## Error Handling

All commands provide meaningful error messages for:
- File not found errors
- Syntax errors in source code
- Invalid IR format
- Runtime errors during execution
- Invalid command line options

Use `--debug` with interpret command for detailed error information.