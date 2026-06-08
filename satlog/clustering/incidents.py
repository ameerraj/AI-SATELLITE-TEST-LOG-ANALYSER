"""
Incident clustering.

During a test run, a single physical problem usually generates *many* related
log lines (a power sag triggers EPS warnings, an OBC reset, recovery messages,
etc.). Reviewing them one-by-one is exactly the kind of manual, repetitive work
the AIT automation team wants to reduce.

This module groups related WARNING/ERROR/CRITICAL log events into a small number
of **incidents** so an operator reasons about *events*, not *lines*.

Approach
--------
Each significant log event is embedded from two feature groups:

  * **Text**: TF-IDF over the (lightly normalised) message — captures *what*
    happened. Numbers are masked so "27.0 V" and "26.4 V" look alike.
  * **Context**: subsystem (one-hot) and a scaled timestamp — captures *where*
    and *roughly when*.

The combined feature matrix is clustered with **DBSCAN** (cosine metric), which
needs no pre-set cluster count and naturally treats one-off lines as noise.
Each resulting cluster is summarised into an :class:`Incident`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.sparse import hstack, csr_matrix
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder

from satlog.config import LEVEL_SEVERITY

SIGNIFICANT_LEVELS = {"WARNING", "ERROR", "CRITICAL"}
_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class Incident:
    """A cluster of related log events representing one operational incident."""

    incident_id: int
    subsystems: list[str]
    severity: str
    n_events: int
    t_start_s: float
    t_end_s: float
    representative_message: str
    codes: list[str]
    sample_messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "subsystems": self.subsystems,
            "severity": self.severity,
            "n_events": self.n_events,
            "t_start_s": self.t_start_s,
            "t_end_s": self.t_end_s,
            "duration_s": round(self.t_end_s - self.t_start_s, 1),
            "representative_message": self.representative_message,
            "codes": self.codes,
            "sample_messages": self.sample_messages,
        }


def _normalise(msg: str) -> str:
    """Mask numbers so messages differing only in values cluster together."""
    return _NUM_RE.sub("<num>", msg.lower())


def _highest_severity(levels: pd.Series) -> str:
    return max(levels, key=lambda lv: LEVEL_SEVERITY.get(lv, 0))


def cluster_incidents(log_df: pd.DataFrame, eps: float = 0.45,
                      min_samples: int = 2, time_weight: float = 0.6) -> list[Incident]:
    """Cluster significant log events into incidents.

    Parameters
    ----------
    eps, min_samples
        DBSCAN parameters (cosine distance).
    time_weight
        Relative weight of the temporal feature vs. text/subsystem features.
    """
    if log_df.empty:
        return []

    sig = log_df[log_df["level"].isin(SIGNIFICANT_LEVELS)].copy()
    if sig.empty:
        return []
    sig = sig.reset_index(drop=True)

    # --- text features ---
    norm = sig["message"].map(_normalise)
    tfidf = TfidfVectorizer(min_df=1, ngram_range=(1, 2))
    X_text = tfidf.fit_transform(norm)

    # --- subsystem one-hot ---
    enc = OneHotEncoder(handle_unknown="ignore")
    X_sub = enc.fit_transform(sig[["subsystem"]])

    # --- temporal feature (scaled 0..time_weight) ---
    t = sig["t_rel_s"].fillna(0).to_numpy(dtype=float)
    span = (t.max() - t.min()) or 1.0
    t_scaled = ((t - t.min()) / span) * time_weight
    X_time = csr_matrix(t_scaled.reshape(-1, 1))

    X = hstack([X_text, X_sub, X_time]).tocsr()

    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine").fit_predict(X)
    sig["cluster"] = labels

    incidents: list[Incident] = []
    next_id = 1
    for lab in sorted(set(labels)):
        if lab == -1:
            continue  # noise / singleton lines
        grp = sig[sig["cluster"] == lab]
        # representative = most severe, then earliest
        grp_sorted = grp.sort_values(
            by=["level", "t_rel_s"],
            key=lambda c: c.map(LEVEL_SEVERITY) if c.name == "level" else c,
            ascending=[False, True],
        )
        rep = grp_sorted.iloc[0]
        incidents.append(Incident(
            incident_id=next_id,
            subsystems=sorted(grp["subsystem"].unique().tolist()),
            severity=_highest_severity(grp["level"]),
            n_events=int(len(grp)),
            t_start_s=float(grp["t_rel_s"].min()),
            t_end_s=float(grp["t_rel_s"].max()),
            representative_message=str(rep["message"]),
            codes=sorted(c for c in grp["code"].dropna().unique().tolist()),
            sample_messages=grp_sorted["message"].head(4).tolist(),
        ))
        next_id += 1

    # Order incidents by severity then time for operator triage.
    incidents.sort(key=lambda inc: (-LEVEL_SEVERITY.get(inc.severity, 0), inc.t_start_s))
    # Renumber after sorting so IDs reflect triage order.
    for new_id, inc in enumerate(incidents, start=1):
        inc.incident_id = new_id
    return incidents
