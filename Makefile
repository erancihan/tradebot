.PHONY: help install install-live test demo backtest run status clean

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

help:
	@echo "Targets:"
	@echo "  install       create venv + install core deps (backtest/test only)"
	@echo "  install-live  also install Alpaca SDK for paper/live trading"
	@echo "  test          run the test suite"
	@echo "  demo          offline backtest on synthetic data (no creds needed)"
	@echo "  backtest      backtest config.yaml (needs creds or --csv)"
	@echo "  dryrun        offline real-time forward-test on replayed data (no creds)"
	@echo "  arena         run the example algo competition (no creds)"
	@echo "  web           build the frontend and serve the dashboard"
	@echo "  run           paper/live trading loop (needs creds)"
	@echo "  status        print broker account snapshot"

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: $(VENV)
	$(PIP) install -e ".[dev]"

install-live: $(VENV)
	$(PIP) install -e ".[dev,live]"

install-web: $(VENV)
	$(PIP) install -e ".[dev,web]"
	cd frontend && npm install

test:
	$(PY) -m pytest

demo:
	$(PY) -m tradebot.cli demo --strategy sma_crossover
	$(PY) -m tradebot.cli demo --strategy rsi_reversion

backtest:
	$(PY) -m tradebot.cli backtest --config config.yaml --out equity.csv

dryrun:
	$(PY) -m tradebot.cli run --config config.yaml --replay --replay-periods 300

arena:
	$(PY) -m tradebot.cli arena run --algos ./algos --scenario scenarios/default.yaml --score sharpe

web-build:
	cd frontend && npm run build

web: web-build
	$(PY) -m tradebot.web.server

run:
	$(PY) -m tradebot.cli run --config config.yaml

status:
	$(PY) -m tradebot.cli status --config config.yaml

clean:
	rm -rf $(VENV) *.egg-info .pytest_cache __pycache__ */__pycache__ */*/__pycache__
	rm -f *.db equity*.csv
