.PHONY: install test demo

install:
	pip install -e ".[test]"

test:
	pytest

demo:
	python -m workflow_failure_lab report examples/payment-timeout.json
