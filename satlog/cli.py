"""
Command-line interface.

Examples
--------
    # generate synthetic data
    python -m satlog.cli generate --session TVAC01

    # run the full analysis and print a report
    python -m satlog.cli analyze \\
        --log data/samples/test_session_TVAC01.log \\
        --telemetry data/samples/telemetry_TVAC01.csv

    # write the machine-readable result to outputs/
    python -m satlog.cli analyze --log ... --telemetry ... --json outputs/result.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from satlog.pipeline import run_pipeline


def _cmd_generate(args: argparse.Namespace) -> int:
    from data.generate_data import generate
    log_path, tlm_path = generate(args.session, args.seed)
    print(f"Generated:\n  {log_path}\n  {tlm_path}")
    return 0


def _print_report(result) -> None:
    from satlog.llm.operator_assistant import OperatorBriefing

    s = result.log_summary
    print("=" * 70)
    print("  AI-ASSISTED SATELLITE TEST LOG ANALYSIS")
    print("=" * 70)
    print(f"Log events parsed : {s.get('parsed', 0)}/{s.get('total', 0)} "
          f"(unparsed: {s.get('unparsed', 0)})")
    print(f"By level          : {s.get('by_level', {})}")
    ts = result.telemetry_stats
    print(f"Telemetry samples : {ts.get('n_samples', 0)}")
    print(f"  OOL red / yellow: {ts.get('n_ool_red', 0)} / {ts.get('n_ool_yellow', 0)}")
    print(f"  z-score / iso   : {ts.get('n_zscore', 0)} / {ts.get('n_iso_outliers', 0)}")
    print(f"LLM backend       : {result.meta.get('llm_backend')}")
    print()
    print(f"--- TELEMETRY ANOMALY EVENTS ({len(result.anomaly_events)}) ---")
    for a in result.anomaly_events:
        print(f"  [{a['severity']:<6}] {a['parameter']:<24} "
              f"t={a['t_start_s']:.0f}-{a['t_end_s']:.0f}s  via {a['method']}")
    print()
    print(f"--- INCIDENTS ({len(result.incidents)}) + OPERATOR BRIEFINGS ---")
    for inc, br in zip(result.incidents, result.briefings):
        b = OperatorBriefing(**br)
        print()
        print(b.to_text())


def _cmd_analyze(args: argparse.Namespace) -> int:
    result = run_pipeline(args.log, args.telemetry, llm_backend=args.backend)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(result.to_json(), encoding="utf-8")
        print(f"Wrote {args.json}")
    if not args.quiet:
        _print_report(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="satlog",
                                 description="AI-assisted satellite test log analyzer")
    sub = ap.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate synthetic test data")
    g.add_argument("--session", default="TVAC01")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=_cmd_generate)

    a = sub.add_parser("analyze", help="run the full analysis pipeline")
    a.add_argument("--log", required=True)
    a.add_argument("--telemetry", required=True)
    a.add_argument("--backend", default="auto", choices=["auto", "rules", "llm"])
    a.add_argument("--json", help="write JSON result to this path")
    a.add_argument("--quiet", action="store_true", help="suppress console report")
    a.set_defaults(func=_cmd_analyze)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
