PYTHON ?= python3
PACKAGE := looop

.PHONY: install uninstall test lint clean

install:
	$(PYTHON) scripts/install.py install

uninstall:
	$(PYTHON) scripts/install.py uninstall

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m compileall -q looop tests scripts

clean:
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
