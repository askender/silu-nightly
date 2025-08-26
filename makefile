
fmt:
	ruff format .
	ruff check --fix

rm:
	rm -rf __pycache__

test:
	pytest tests/ -q --tb=short

cov:
	pytest tests/ -q --tb=short --cov=silu --cov-report=term-missing
