.PHONY: check lint types test eval

check: lint types test   ## everything CI runs that doesn't need the network

lint:
	ruff check .

types:
	mypy

test:
	pytest --cov=ctxrelay --cov-fail-under=80

eval:   ## needs `pip install jedi`, node + typescript, and network for eval/fetch.sh
	eval/fetch.sh
	python eval/graph_eval.py pytest --n 60
	python eval/graph_eval.py nest --n 60
	python eval/check_thresholds.py pytest nest
