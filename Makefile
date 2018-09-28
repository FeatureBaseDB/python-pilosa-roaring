.PHONY: build clean cover release test upload

test:
	py.test tests/

cover:
	py.test --cov-report term-missing --cov=roaring

build:
	python setup.py sdist && python setup.py bdist_wheel --universal

upload:
	twine upload dist/*

release: build upload

clean:
	rm -rf build dist pilosa_roaring.egg-info