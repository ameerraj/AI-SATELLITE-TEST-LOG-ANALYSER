"""Unit tests for the core analysis modules."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from satlog.anomaly import detect_anomalies
from satlog.clustering import cluster_incidents
from satlog.config import TELEMETRY_PARAMS
from satlog.llm import OperatorAssistant
from satlog.parsing import parse_log_text


# --------------------------------------------------------------------- parsing
SAMPLE_LOG = """\
# header comment
2026-03-14T09:00:00+00:00 [INFO    ] CCS     | Test step 1 started (CCS-1001)
2026-03-14T09:00:30+00:00 [ERROR   ] EPS     | Battery bus voltage out-of-limit RED LOW (26.4 V) (EPS-8102)
this line is malformed and should not crash the parser
2026-03-14T09:01:02+00:00 [CRITICAL] OBC     | Unexpected processor reset (OBC-3111)
"""


def test_parser_extracts_fields():
    df = parse_log_text(SAMPLE_LOG)
    assert len(df) == 4
    row = df[df["code"] == "EPS-8102"].iloc[0]
    assert row["level"] == "ERROR"
    assert row["subsystem"] == "EPS"
    assert "out-of-limit" in row["message"].lower()


def test_parser_is_tolerant_of_malformed_lines():
    df = parse_log_text(SAMPLE_LOG)
    assert (~df["parsed"]).sum() == 1  # the malformed line is kept, flagged unparsed
    assert df["parsed"].sum() == 3


def test_parser_relative_time():
    df = parse_log_text(SAMPLE_LOG)
    assert df["t_rel_s"].min() == 0
    assert df["t_rel_s"].max() == pytest.approx(62.0)


# -------------------------------------------------------------------- anomaly
def _telemetry_with_spike():
    n = 600
    ts = pd.date_range("2026-03-14T09:00:00Z", periods=n, freq="1s")
    data = {"timestamp": ts}
    rng = np.random.default_rng(0)
    for key, lim in TELEMETRY_PARAMS.items():
        data[key] = rng.normal(lim.nominal, lim.std, n)
    df = pd.DataFrame(data)
    # force a clear RED out-of-limit on battery voltage
    df.loc[300:320, "eps_battery_voltage_v"] = TELEMETRY_PARAMS[
        "eps_battery_voltage_v"].red_low - 0.5
    df["t_rel_s"] = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds()
    return df


def test_anomaly_detects_red_ool():
    df = _telemetry_with_spike()
    res = detect_anomalies(df)
    assert res.stats["n_ool_red"] > 0
    params = {e["parameter"] for e in res.events}
    assert "eps_battery_voltage_v" in params
    reds = [e for e in res.events if e["severity"] == "RED"]
    assert reds, "expected at least one RED-severity anomaly event"


def test_anomaly_clean_telemetry_few_events():
    df = _telemetry_with_spike()
    df["eps_battery_voltage_v"] = TELEMETRY_PARAMS["eps_battery_voltage_v"].nominal
    res = detect_anomalies(df)
    assert res.stats["n_ool_red"] == 0


# ------------------------------------------------------------------ clustering
def _significant_log():
    rows = []
    base = pd.Timestamp("2026-03-14T09:00:00Z")
    # one EPS incident (several related lines), one COMMS incident
    eps = [
        ("WARNING", "EPS", "Battery bus voltage below soft limit", "EPS-8101", 5),
        ("ERROR", "EPS", "Battery bus voltage out-of-limit RED LOW", "EPS-8102", 30),
        ("ERROR", "EPS", "Bus current exceeds nominal envelope", "EPS-8103", 35),
    ]
    comms = [
        ("ERROR", "COMMS", "S-band downlink lost, RSSI below threshold", "COMMS-9110", 500),
        ("ERROR", "COMMS", "S-band downlink lost, RSSI below threshold", "COMMS-9110", 520),
        ("ERROR", "COMMS", "S-band downlink lost, RSSI below threshold", "COMMS-9110", 540),
    ]
    for lvl, sub, msg, code, off in eps + comms:
        rows.append({"timestamp": base + pd.Timedelta(seconds=off), "level": lvl,
                     "subsystem": sub, "message": msg, "code": code,
                     "raw": msg, "parsed": True, "t_rel_s": float(off)})
    return pd.DataFrame(rows)


def test_clustering_groups_related_events():
    df = _significant_log()
    incidents = cluster_incidents(df, eps=0.5, min_samples=2)
    assert len(incidents) >= 2
    subs = {tuple(inc.subsystems) for inc in incidents}
    assert ("EPS",) in subs
    assert ("COMMS",) in subs


def test_clustering_severity_is_highest_in_group():
    df = _significant_log()
    incidents = cluster_incidents(df, eps=0.5, min_samples=2)
    eps_inc = next(i for i in incidents if i.subsystems == ["EPS"])
    assert eps_inc.severity == "ERROR"


# ------------------------------------------------------------------- assistant
def test_assistant_offline_backend_produces_briefing():
    assistant = OperatorAssistant(backend="rules")
    incident = {
        "incident_id": 1, "subsystems": ["EPS"], "severity": "ERROR",
        "n_events": 3, "t_start_s": 5.0, "t_end_s": 35.0,
        "representative_message": "Battery bus voltage out-of-limit RED LOW",
        "codes": ["EPS-8102"],
    }
    b = assistant.brief(incident)
    assert b.backend == "rules"
    assert b.likely_causes and b.recommended_actions
    assert "power" in b.explanation.lower() or "voltage" in b.explanation.lower()


def test_assistant_unknown_signature_escalates():
    assistant = OperatorAssistant(backend="rules")
    incident = {"incident_id": 9, "subsystems": ["PAYLOAD"], "severity": "WARNING",
                "n_events": 1, "t_start_s": 0, "t_end_s": 0,
                "representative_message": "completely novel situation xyzzy",
                "codes": []}
    b = assistant.brief(incident)
    assert any("escalate" in a.lower() for a in b.recommended_actions)
