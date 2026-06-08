"""
Telemetry anomaly detection.

Three complementary methods are combined, mirroring how a real CCS/AIT setup
layers checks from cheap-and-explainable to learned-and-broad:

  1. **Out-of-limit (OOL) check** — compares each sample against the red/yellow
     limits from :mod:`satlog.config`. This is the classic, fully explainable
     check every check-out system performs.

  2. **Rolling z-score** — flags samples that deviate strongly from their recent
     local behaviour, catching drifts/spikes that stay *within* absolute limits
     (e.g. a slow ramp that has not yet breached a red limit).

  3. **IsolationForest (multivariate)** — an unsupervised model over all
     parameters jointly, catching anomalies that only show up as an unusual
     *combination* of otherwise-in-family values.

Each detected anomaly carries the method(s) that flagged it and a severity, so
an operator can see *why* something was raised — important for trust in an
AI-assisted tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from satlog.config import TELEMETRY_PARAMS


@dataclass
class AnomalyResult:
    """Container for the outcome of an anomaly-detection run."""

    flags: pd.DataFrame                 # per-sample boolean/severity flags
    events: list[dict] = field(default_factory=list)  # consolidated anomaly events
    stats: dict = field(default_factory=dict)


def load_telemetry(path: str | Path) -> pd.DataFrame:
    """Load a telemetry CSV with a parsed timestamp index column ``t_rel_s``."""
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    first = df["timestamp"].min()
    df["t_rel_s"] = (df["timestamp"] - first).dt.total_seconds()
    return df


def _ool_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Per-sample out-of-limit classification ('NOMINAL'|'YELLOW'|'RED')."""
    out = pd.DataFrame(index=df.index)
    for key, lim in TELEMETRY_PARAMS.items():
        if key not in df:
            continue
        out[key] = df[key].apply(lim.classify)
    return out


def _rolling_z(df: pd.DataFrame, window: int = 60, z_thresh: float = 4.0) -> pd.DataFrame:
    """Flag samples whose rolling z-score magnitude exceeds ``z_thresh``."""
    out = pd.DataFrame(index=df.index)
    for key in TELEMETRY_PARAMS:
        if key not in df:
            continue
        s = df[key]
        mu = s.rolling(window, min_periods=window // 2).mean()
        sd = s.rolling(window, min_periods=window // 2).std().replace(0, np.nan)
        z = (s - mu) / sd
        out[key] = z.abs() > z_thresh
    return out.fillna(False)


def _isolation_forest(df: pd.DataFrame, contamination: float = 0.02) -> np.ndarray:
    """Return a boolean array; True = multivariate outlier."""
    cols = [c for c in TELEMETRY_PARAMS if c in df]
    X = StandardScaler().fit_transform(df[cols].to_numpy())
    model = IsolationForest(
        n_estimators=200, contamination=contamination, random_state=0
    )
    pred = model.fit_predict(X)  # -1 = outlier, 1 = inlier
    return pred == -1


def _consolidate_events(df: pd.DataFrame, ool: pd.DataFrame, zf: pd.DataFrame,
                        iso: np.ndarray, gap_s: float = 15.0) -> list[dict]:
    """Collapse per-sample flags into discrete anomaly events per parameter,
    merging samples that are close in time into a single event."""
    events: list[dict] = []

    # Per-parameter events from OOL + z-score.
    for key, lim in TELEMETRY_PARAMS.items():
        if key not in df:
            continue
        flagged = (ool[key] != "NOMINAL") | zf[key]
        if not flagged.any():
            continue
        idx = df.index[flagged].to_numpy()
        t = df["t_rel_s"].to_numpy()
        # group consecutive flagged samples within gap_s
        groups: list[list[int]] = []
        for i in idx:
            if groups and (t[i] - t[groups[-1][-1]]) <= gap_s:
                groups[-1].append(i)
            else:
                groups.append([i])
        for grp in groups:
            sub = df.loc[grp, key]
            sev = "RED" if (ool[key].loc[grp] == "RED").any() else "YELLOW"
            peak_i = sub.idxmax() if abs(sub.max() - lim.nominal) >= abs(sub.min() - lim.nominal) else sub.idxmin()
            events.append({
                "parameter": key,
                "unit": lim.unit,
                "subsystem": key.split("_")[0].upper(),
                "severity": sev,
                "method": "OOL/z-score",
                "t_start_s": float(df["t_rel_s"].loc[grp[0]]),
                "t_end_s": float(df["t_rel_s"].loc[grp[-1]]),
                "peak_value": float(df[key].loc[peak_i]),
                "nominal": lim.nominal,
                "n_samples": len(grp),
            })

    # Multivariate events (IsolationForest) summarised as windows.
    iso_idx = df.index[iso].to_numpy()
    if len(iso_idx):
        t = df["t_rel_s"].to_numpy()
        groups = []
        for i in iso_idx:
            if groups and (t[i] - t[groups[-1][-1]]) <= gap_s:
                groups[-1].append(i)
            else:
                groups.append([i])
        for grp in groups:
            if len(grp) < 3:   # ignore isolated single-sample blips
                continue
            events.append({
                "parameter": "multivariate",
                "unit": "",
                "subsystem": "SYSTEM",
                "severity": "YELLOW",
                "method": "IsolationForest",
                "t_start_s": float(df["t_rel_s"].loc[grp[0]]),
                "t_end_s": float(df["t_rel_s"].loc[grp[-1]]),
                "peak_value": float("nan"),
                "nominal": float("nan"),
                "n_samples": len(grp),
            })

    events.sort(key=lambda e: e["t_start_s"])
    return events


def detect_anomalies(df: pd.DataFrame, z_window: int = 60, z_thresh: float = 4.0,
                     contamination: float = 0.02) -> AnomalyResult:
    """Run the full three-method detection pipeline on a telemetry DataFrame."""
    ool = _ool_flags(df)
    zf = _rolling_z(df, window=z_window, z_thresh=z_thresh)
    iso = _isolation_forest(df, contamination=contamination)

    flags = pd.DataFrame({"t_rel_s": df["t_rel_s"], "timestamp": df["timestamp"]})
    flags["ool_any"] = (ool != "NOMINAL").any(axis=1)
    flags["ool_red"] = (ool == "RED").any(axis=1)
    flags["zscore_any"] = zf.any(axis=1)
    flags["iso_outlier"] = iso

    events = _consolidate_events(df, ool, zf, iso)
    stats = {
        "n_samples": int(len(df)),
        "n_ool_red": int(flags["ool_red"].sum()),
        "n_ool_yellow": int((flags["ool_any"] & ~flags["ool_red"]).sum()),
        "n_zscore": int(flags["zscore_any"].sum()),
        "n_iso_outliers": int(iso.sum()),
        "n_events": len(events),
    }
    return AnomalyResult(flags=flags, events=events, stats=stats)
