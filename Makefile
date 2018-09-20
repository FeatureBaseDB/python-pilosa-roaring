.PHONY: cover test

test:
	py.test tests/

cover:
	py.test --cov-report term-missing --cov=roaring