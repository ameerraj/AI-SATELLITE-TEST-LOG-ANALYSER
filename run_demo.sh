#!/usr/bin/env bash
# One-shot demo: generate data, run analysis, render report, launch dashboard.
set -e
export PYTHONPATH="$(pwd)"
echo "[1/4] Generating synthetic test data..."
python -m satlog.cli generate --session TVAC01
echo "[2/4] Running analysis pipeline..."
python -m satlog.cli analyze \
  --log data/samples/test_session_TVAC01.log \
  --telemetry data/samples/telemetry_TVAC01.csv \
  --json outputs/result_TVAC01.json --quiet
echo "[3/4] Rendering mission report PNG..."
python -m satlog.report --session TVAC01
echo "[4/4] Launching dashboard at http://127.0.0.1:5000 (Ctrl+C to stop)..."
python -m satlog.dashboard.app
