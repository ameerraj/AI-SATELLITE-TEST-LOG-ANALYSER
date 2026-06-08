"""
Synthetic satellite test-campaign data generator.

Generates two artefacts that mimic what a Central Check-Out System (CCS) /
EGSE setup produces during a functional or thermal-vacuum (TVAC) test run:

  1. A raw text log file  (data/samples/test_session_<id>.log)
  2. A telemetry CSV file  (data/samples/telemetry_<id>.csv)

Several realistic *incidents* are injected so the downstream anomaly detector
and incident-clustering modules have meaningful structure to recover:

  - EPS battery undervoltage sag (power) -> OBC brown-out
  - TCS +Y panel thermal runaway
  - AOCS reaction-wheel over-speed / oscillation
  - COMMS intermittent downlink dropouts
  - EGSE / CCS connection loss (log-only noise)

Everything is seeded for reproducibility.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from satlog.config import TELEMETRY_PARAMS

SAMPLE_DIR = Path(__file__).resolve().parent / "samples"

START_TIME = datetime(2026, 3, 14, 9, 0, 0, tzinfo=timezone.utc)
DURATION_S = 3600          # 1 hour campaign
SAMPLE_PERIOD_S = 1        # 1 Hz telemetry


# --------------------------------------------------------------------------------------
# Telemetry generation
# --------------------------------------------------------------------------------------
def _nominal_series(n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Create nominal (in-family) telemetry for every configured parameter."""
    series: dict[str, np.ndarray] = {}
    for key, lim in TELEMETRY_PARAMS.items():
        base = rng.normal(lim.nominal, lim.std, size=n)
        # Add a slow drift so it does not look perfectly stationary.
        drift = np.linspace(0, lim.std * 1.5, n) * rng.choice([-1, 1])
        series[key] = base + drift
    return series


def _inject_incidents(series: dict[str, np.ndarray], rng: np.random.Generator) -> list[dict]:
    """Mutate telemetry to embed physical anomalies. Returns the ground truth."""
    truth: list[dict] = []

    # 1) EPS undervoltage sag with current spike (t = 900..1010 s)
    s, e = 900, 1010
    sag = np.linspace(0, -1.6, e - s)
    series["eps_battery_voltage_v"][s:e] += sag
    series["eps_bus_current_a"][s:e] += np.linspace(0, 4.2, e - s)
    truth.append({"start": s, "end": e, "subsystem": "EPS",
                  "label": "battery_undervoltage"})

    # 2) TCS +Y panel thermal runaway (t = 1800..2050 s)
    s, e = 1800, 2050
    ramp = np.linspace(0, 32.0, e - s)
    series["tcs_panel_temp_c"][s:e] += ramp
    truth.append({"start": s, "end": e, "subsystem": "TCS",
                  "label": "panel_overtemperature"})

    # 3) AOCS reaction wheel over-speed + oscillation (t = 2600..2720 s)
    s, e = 2600, 2720
    t = np.arange(e - s)
    series["aocs_rw_rpm"][s:e] += 3600 + 500 * np.sin(t / 4.0)
    truth.append({"start": s, "end": e, "subsystem": "AOCS",
                  "label": "reaction_wheel_overspeed"})

    # 4) COMMS intermittent dropouts (t = 3000..3150 s)
    s, e = 3000, 3150
    mask = rng.random(e - s) < 0.45
    drop = np.where(mask, -36.0, 0.0)
    series["comms_rssi_dbm"][s:e] += drop
    truth.append({"start": s, "end": e, "subsystem": "COMMS",
                  "label": "downlink_dropout"})

    return truth


# --------------------------------------------------------------------------------------
# Log generation
# --------------------------------------------------------------------------------------
NOMINAL_TEMPLATES = [
    ("INFO", "CCS", "Test step {step} '{proc}' started", "CCS-1001"),
    ("INFO", "CCS", "Test step {step} '{proc}' completed nominally", "CCS-1002"),
    ("DEBUG", "EGSE", "EGSE heartbeat ok, link latency {lat} ms", "EGSE-2000"),
    ("INFO", "OBC", "Telemetry frame {frame} acquired, CRC ok", "OBC-3000"),
    ("INFO", "PAYLOAD", "Instrument calibration table loaded", "PL-4000"),
    ("DEBUG", "HARNESS", "Interface {iface} continuity check passed", "HW-5000"),
    ("INFO", "AOCS", "Reaction wheel speed within band ({rpm} rpm)", "AOCS-6000"),
    ("INFO", "TCS", "Thermistor sweep nominal", "TCS-7000"),
]

PROC_NAMES = [
    "EPS_FUNCTIONAL", "TCS_THERMAL_CYCLE", "AOCS_POINTING", "COMMS_RF_CHECK",
    "PAYLOAD_IMAGING", "OBC_BOOT_SEQUENCE", "HARNESS_ISOLATION",
]


def _incident_log_lines(truth: list[dict]) -> list[tuple[int, str, str, str, str]]:
    """Produce correlated log lines (t_offset, level, subsystem, message, code) for
    each injected incident. These are what the clustering module should group."""
    lines: list[tuple[int, str, str, str, str]] = []

    for inc in truth:
        s, e, sub = inc["start"], inc["end"], inc["subsystem"]
        label = inc["label"]

        if label == "battery_undervoltage":
            lines += [
                (s + 5, "WARNING", "EPS", "Battery bus voltage below soft limit (27.0 V)", "EPS-8101"),
                (s + 30, "ERROR", "EPS", "Battery bus voltage out-of-limit RED LOW (26.4 V)", "EPS-8102"),
                (s + 35, "WARNING", "EPS", "Bus current exceeds nominal envelope (8.1 A)", "EPS-8103"),
                (s + 60, "ERROR", "OBC", "Brown-out detected, watchdog reset triggered", "OBC-3110"),
                (s + 62, "CRITICAL", "OBC", "Unexpected processor reset during test step", "OBC-3111"),
                (s + 90, "WARNING", "EPS", "Battery voltage recovering, trend nominal", "EPS-8104"),
            ]
        elif label == "panel_overtemperature":
            for k, off in enumerate(range(20, e - s, 45)):
                lvl = "WARNING" if k < 2 else "ERROR"
                lines.append((s + off, lvl, "TCS",
                              f"+Y panel temperature rising, gradient {2 + k} degC/min", "TCS-7110"))
            lines.append((e - 20, "CRITICAL", "TCS",
                          "+Y panel temperature out-of-limit RED HIGH (54 degC)", "TCS-7115"))
            lines.append((e - 18, "ERROR", "TCS",
                          "Heater control loop saturated, cannot regulate", "TCS-7116"))
        elif label == "reaction_wheel_overspeed":
            lines += [
                (s + 8, "WARNING", "AOCS", "Reaction wheel #1 speed above soft limit (5900 rpm)", "AOCS-6110"),
                (s + 25, "ERROR", "AOCS", "Reaction wheel #1 over-speed RED (6250 rpm)", "AOCS-6111"),
                (s + 40, "ERROR", "AOCS", "Wheel torque command oscillation detected", "AOCS-6112"),
                (s + 70, "WARNING", "AOCS", "Momentum management entering safe mode", "AOCS-6113"),
            ]
        elif label == "downlink_dropout":
            for off in range(10, e - s, 20):
                lines.append((s + off, "ERROR", "COMMS",
                              "S-band downlink lost, RSSI below threshold", "COMMS-9110"))
            lines.append((e - 5, "WARNING", "COMMS",
                          "Downlink re-acquired after intermittent loss", "COMMS-9111"))

    # EGSE/CCS connection-loss noise unrelated to telemetry (log-only incident)
    for off in (1450, 1452, 1458, 1465):
        lines.append((off, "ERROR", "EGSE", "EGSE TCP link timeout, retrying connection", "EGSE-2110"))
    lines.append((1480, "WARNING", "CCS", "Test sequence paused awaiting EGSE reconnect", "CCS-1110"))
    lines.append((1495, "INFO", "EGSE", "EGSE link re-established", "EGSE-2111"))

    return lines


def generate(session_id: str = "TVAC01", seed: int = 42) -> tuple[Path, Path]:
    """Generate one log file and one telemetry CSV. Returns their paths."""
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    random.seed(seed)

    n = DURATION_S // SAMPLE_PERIOD_S
    series = _nominal_series(n, rng)
    truth = _inject_incidents(series, rng)

    # --- write telemetry CSV ---
    tlm_path = SAMPLE_DIR / f"telemetry_{session_id}.csv"
    cols = list(TELEMETRY_PARAMS.keys())
    with tlm_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", *cols])
        for i in range(n):
            ts = (START_TIME + timedelta(seconds=i * SAMPLE_PERIOD_S)).isoformat()
            w.writerow([ts, *[f"{series[c][i]:.4f}" for c in cols]])

    # --- build log lines (nominal background + incident lines) ---
    log_lines: list[tuple[int, str, str, str, str]] = []
    step = 1
    for t in range(0, DURATION_S, 17):  # a background log line roughly every 17 s
        lvl, sub, tmpl, code = random.choice(NOMINAL_TEMPLATES)
        msg = tmpl.format(step=step, proc=random.choice(PROC_NAMES),
                          lat=random.randint(2, 18), frame=random.randint(1000, 9999),
                          iface=random.choice(["J1", "J2", "J3", "TM/TC"]),
                          rpm=random.randint(2200, 2600))
        log_lines.append((t, lvl, sub, msg, code))
        if "started" in msg:
            step += 1

    log_lines += _incident_log_lines(truth)
    log_lines.sort(key=lambda x: x[0])

    log_path = SAMPLE_DIR / f"test_session_{session_id}.log"
    with log_path.open("w") as f:
        f.write(f"# CCS test session {session_id} | UUT: SAT-DM-001 | "
                f"start={START_TIME.isoformat()}\n")
        for t, lvl, sub, msg, code in log_lines:
            ts = (START_TIME + timedelta(seconds=t)).isoformat()
            f.write(f"{ts} [{lvl:<8}] {sub:<7} | {msg} ({code})\n")

    # --- write ground-truth (handy for evaluation / demo narrative) ---
    truth_path = SAMPLE_DIR / f"ground_truth_{session_id}.csv"
    with truth_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_s", "end_s", "subsystem", "label"])
        for inc in truth:
            w.writerow([inc["start"], inc["end"], inc["subsystem"], inc["label"]])

    return log_path, tlm_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate synthetic satellite test data")
    ap.add_argument("--session", default="TVAC01")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    lp, tp = generate(args.session, args.seed)
    print(f"Wrote {lp}")
    print(f"Wrote {tp}")
