"""
Log parsing.

Turns semi-structured CCS / EGSE test-log text into a tidy ``pandas`` DataFrame
that downstream modules can analyse. The parser is tolerant: lines that do not
match the expected grammar are captured as ``unparsed`` rather than dropped, so
nothing is silently lost (important in a test/qualification context).

Expected line grammar (produced by ``data/generate_data.py``)::

    2026-03-14T09:15:00+00:00 [ERROR   ] EPS     | message text (EPS-8102)

The regex below is deliberately permissive about spacing so it also copes with
mildly different real-world formats.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

# Matches:  <iso-timestamp> [LEVEL] SUBSYS | message (CODE)
LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?)"
    r"\s+\[(?P<level>[A-Z]+)\s*\]"
    r"\s+(?P<subsystem>[A-Z0-9_]+)"
    r"\s*\|\s*"
    r"(?P<message>.*?)"
    r"(?:\s+\((?P<code>[A-Z]+-\d+)\))?\s*$"
)


@dataclass
class LogEvent:
    """One structured log event."""

    timestamp: pd.Timestamp | None
    level: str
    subsystem: str
    message: str
    code: str | None
    raw: str
    parsed: bool


def _parse_line(line: str) -> LogEvent:
    line = line.rstrip("\n")
    m = LINE_RE.match(line)
    if not m:
        return LogEvent(None, "UNKNOWN", "UNKNOWN", line.strip(), None, line, False)
    g = m.groupdict()
    try:
        ts = pd.to_datetime(g["timestamp"], utc=True)
    except (ValueError, TypeError):
        ts = None
    return LogEvent(
        timestamp=ts,
        level=g["level"].strip(),
        subsystem=g["subsystem"].strip(),
        message=g["message"].strip(),
        code=g["code"],
        raw=line,
        parsed=True,
    )


def parse_log_text(text: str) -> pd.DataFrame:
    """Parse a block of log text into a DataFrame, skipping comment/blank lines."""
    events: list[LogEvent] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        events.append(_parse_line(line))

    df = pd.DataFrame([asdict(e) for e in events])
    if df.empty:
        return df
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
    # Relative seconds from first event — convenient for plotting / correlation.
    first = df["timestamp"].dropna().min()
    if pd.notna(first):
        df["t_rel_s"] = (df["timestamp"] - first).dt.total_seconds()
    return df


def parse_log_file(path: str | Path) -> pd.DataFrame:
    """Parse a log file from disk."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_log_text(text)


def parse_summary(df: pd.DataFrame) -> dict:
    """Quick health summary of a parsed log (used by the dashboard header)."""
    if df.empty:
        return {"total": 0, "parsed": 0, "by_level": {}, "by_subsystem": {}}
    return {
        "total": int(len(df)),
        "parsed": int(df["parsed"].sum()),
        "unparsed": int((~df["parsed"]).sum()),
        "by_level": df["level"].value_counts().to_dict(),
        "by_subsystem": df["subsystem"].value_counts().to_dict(),
        "time_span_s": float(df["t_rel_s"].max()) if "t_rel_s" in df else 0.0,
    }
