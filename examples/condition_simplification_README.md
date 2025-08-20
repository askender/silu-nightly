# Condition Simplification Feature

This directory contains examples and documentation for the condition simplification feature in Silu's symbolic executor.

## What is Condition Simplification?

The `--simplify` option in `silu symbolic` command merges and simplifies path conditions to make the symbolic execution output more readable and concise. Instead of showing multiple related conditions, it combines them into single, equivalent conditions.

## Example

### Without Simplification
```bash
silu symbolic condition_simplification_demo.si
```

This produces paths with complex conditions like:
```json
{
  "path_id": "path_4",
  "conditions": [
    "not (x > 10)",
    "not (x > 5)", 
    "not (x > 0)"
  ]
}
```

### With Simplification
```bash
silu symbolic condition_simplification_demo.si --simplify
```

This produces the same path with a simplified condition:
```json
{
  "path_id": "path_4", 
  "conditions": [
    "(x <= 0.0)"
  ]
}
```

## How It Works

The simplification algorithm:

1. **Groups conditions by variable**: Identifies conditions that constrain the same variable
2. **Analyzes negated comparisons**: Converts patterns like `not (x > a)` to `x <= a`
3. **Merges overlapping constraints**: Combines multiple constraints on the same variable
4. **Preserves complex expressions**: Leaves non-simple expressions unchanged for safety

## Supported Simplification Patterns

### Basic Range Narrowing
- `not (x > 10)` and `not (x > 0)` → `x <= 0.0`
- `not (x > 20)`, `not (x > 15)`, `not (x > 10)` → `x <= 10.0`

### Multiple Variable Constraints
Each variable is simplified independently:
- Variable `x`: `not (x > 5)`, `not (x > 0)` → `x <= 0.0`
- Variable `y`: `not (y > 10)` → `not (y > 10)` (single condition, no change)

## Limitations

Current implementation focuses on:
- Simple variable comparisons (`x > value`)
- Numeric comparison values only
- Negated greater-than operations primarily

Complex expressions are preserved as-is to ensure correctness:
- Function calls: `func(x) > 0`
- Arithmetic: `x + y > 5`
- Boolean combinations: `x > 0 and y < 10`

## Usage Examples

### Basic Usage
```bash
# Analyze with simplification
silu symbolic your_program.si --simplify

# Compare with and without simplification
silu symbolic your_program.si > without_simplify.json
silu symbolic your_program.si --simplify > with_simplify.json
```

### Integration with Other Tools
```bash
# Generate simplified analysis and process with jq
silu symbolic program.si --simplify | jq '.paths[] | select(.satisfiable) | .conditions'

# Save simplified output for further analysis
silu symbolic complex_program.si --simplify --output simplified_analysis.json
```

## Benefits

1. **Improved Readability**: Fewer, more meaningful conditions
2. **Easier Analysis**: Simpler conditions are easier to understand and reason about
3. **Reduced Complexity**: Fewer conditions reduce cognitive load when analyzing paths
4. **Better Integration**: Simplified output is easier to process with external tools

## Testing

Run the unit tests to verify simplification behavior:
```bash
python -m pytest test_simplify_unit.py -v
```

## Demo Program

The `condition_simplification_demo.si` file demonstrates various scenarios where simplification is beneficial. Run it with and without `--simplify` to see the difference.