.PHONY: install test demo verify-clean-install

install:
	pip install -e ".[test]"

test:
	pytest

demo:
	python -m workflow_failure_lab report examples/payment-timeout.json

verify-clean-install:
	python3 scripts/verify_clean_install.py
