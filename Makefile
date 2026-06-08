.PHONY: install data analyze dashboard report test clean demo

install:
	pip install -r requirements.txt

data:
	python -m satlog.cli generate --session TVAC01

analyze:
	python -m satlog.cli analyze \
		--log data/samples/test_session_TVAC01.log \
		--telemetry data/samples/telemetry_TVAC01.csv \
		--json outputs/result_TVAC01.json

report:
	python -m satlog.report --session TVAC01

dashboard:
	python -m satlog.dashboard.app

test:
	pytest -q

demo: data analyze report
	@echo "Demo complete. Open the dashboard with: make dashboard"

clean:
	rm -rf outputs/*.json outputs/*.png __pycache__ .pytest_cache
