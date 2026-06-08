"""
Flask web dashboard — mission-control view of a test-log analysis.

Run with::

    python -m satlog.dashboard.app
    # then open http://127.0.0.1:5000

The dashboard auto-discovers test sessions in ``data/samples`` (any
``telemetry_<id>.csv`` with a matching ``test_session_<id>.log``), runs the
analysis pipeline server-side, and renders telemetry charts with limit bands +
flagged anomalies, the clustered incident list, and the LLM operator briefings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

from satlog.pipeline import run_pipeline

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "data" / "samples"

app = Flask(__name__)
_CACHE: dict[str, dict] = {}


def discover_sessions() -> list[str]:
    """Return session ids that have both a telemetry CSV and a log file."""
    sessions = []
    for tlm in sorted(SAMPLE_DIR.glob("telemetry_*.csv")):
        sid = re.sub(r"^telemetry_|\.csv$", "", tlm.name)
        if (SAMPLE_DIR / f"test_session_{sid}.log").exists():
            sessions.append(sid)
    return sessions


def session_paths(sid: str) -> tuple[Path, Path]:
    log = SAMPLE_DIR / f"test_session_{sid}.log"
    tlm = SAMPLE_DIR / f"telemetry_{sid}.csv"
    if not (log.exists() and tlm.exists()):
        abort(404, f"Unknown session '{sid}'")
    return log, tlm


def analysis_for(sid: str) -> dict:
    if sid not in _CACHE:
        log, tlm = session_paths(sid)
        _CACHE[sid] = json.loads(run_pipeline(log, tlm).to_json())
    return _CACHE[sid]


@app.route("/")
def index():
    sessions = discover_sessions()
    if not sessions:
        return render_template("index.html", sessions=[], data=None, session=None)
    sid = request.args.get("session", sessions[0])
    if sid not in sessions:
        sid = sessions[0]
    return render_template("index.html", sessions=sessions, session=sid,
                           data=json.dumps(analysis_for(sid)))


@app.route("/api/analysis")
def api_analysis():
    sid = request.args.get("session") or (discover_sessions() or [None])[0]
    if not sid:
        return jsonify({"error": "no sessions found"}), 404
    return jsonify(analysis_for(sid))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Run the satlog dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    if not discover_sessions():
        print("No sessions found in data/samples. Generate data first:")
        print("  python -m satlog.cli generate --session TVAC01")
    print(f"Dashboard on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
