
fmt:
	ruff format . --exclude aok,test_examples
	ruff check --fix --exclude aok,test_examples

rm:
	rm -rf __pycache__

test:
	pytest tests/ -q --tb=short

cov:
	pytest tests/ -q --tb=short --cov=silu --cov-report=term-missing
