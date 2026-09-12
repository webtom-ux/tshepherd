.PHONY: test check

PYTHON ?= python3

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test
	$(PYTHON) -m compileall -q tshepherd.py primary_identity.py tests
	git diff --check
