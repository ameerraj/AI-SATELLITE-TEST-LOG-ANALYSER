"""
End-to-end analysis pipeline.

Ties the four capabilities together into a single, JSON-serialisable result:

    log  ─▶ parse ─┐
                   ├─▶ cluster incidents ─▶ LLM operator briefings
    tlm  ─▶ detect ┘            (correlated by time window)

The output dict is what both the CLI and the web dashboard consume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from satlog.anomaly import detect_anomalies, load_telemetry
from satlog.clustering import cluster_incidents
from satlog.llm import OperatorAssistant
from satlog.parsing import parse_log_file
from satlog.parsing.log_parser import parse_summary


@dataclass
class AnalysisResult:
    log_summary: dict
    telemetry_stats: dict
    anomaly_events: list[dict]
    incidents: list[dict]
    briefings: list[dict]
    telemetry_preview: dict          # downsampled series for plotting
    meta: dict

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.__dict__, indent=indent, default=str)


def _downsample_telemetry(df: pd.DataFrame, max_points: int = 600) -> dict:
    """Downsample each parameter for charting without shipping the full series."""
    from satlog.config import TELEMETRY_PARAMS

    step = max(1, len(df) // max_points)
    sl = df.iloc[::step]
    out = {"t_rel_s": sl["t_rel_s"].round(1).tolist()}
    for key, lim in TELEMETRY_PARAMS.items():
        if key in sl:
            out[key] = {
                "values": sl[key].round(4).tolist(),
                "unit": lim.unit,
                "nominal": lim.nominal,
                "red_low": lim.red_low, "red_high": lim.red_high,
                "yellow_low": lim.yellow_low, "yellow_high": lim.yellow_high,
            }
    return out


def run_pipeline(log_path: str | Path, telemetry_path: str | Path,
                 llm_backend: str = "auto") -> AnalysisResult:
    """Run the full analysis and return a structured result."""
    # 1) Parse logs
    log_df = parse_log_file(log_path)
    log_summary = parse_summary(log_df)

    # 2) Telemetry anomaly detection
    tlm_df = load_telemetry(telemetry_path)
    anomaly = detect_anomalies(tlm_df)

    # 3) Incident clustering
    incidents = cluster_incidents(log_df)
    incident_dicts = [inc.as_dict() for inc in incidents]

    # 4) LLM-assisted operator briefings (correlated with telemetry anomalies)
    assistant = OperatorAssistant(backend=llm_backend)
    briefings = [assistant.brief(inc, anomaly.events).as_dict()
                 for inc in incident_dicts]

    return AnalysisResult(
        log_summary=log_summary,
        telemetry_stats=anomaly.stats,
        anomaly_events=anomaly.events,
        incidents=incident_dicts,
        briefings=briefings,
        telemetry_preview=_downsample_telemetry(tlm_df),
        meta={
            "log_path": str(log_path),
            "telemetry_path": str(telemetry_path),
            "llm_backend": assistant.backend,
            "n_incidents": len(incident_dicts),
            "n_anomaly_events": len(anomaly.events),
        },
    )
