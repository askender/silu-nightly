
fmt:
	ruff format .
	ruff check --fix

rm:
	rm -rf __pycache__

test:
	pytest tests/

cov:
	pytest tests/ --cov=silu --cov-report=term-missing
