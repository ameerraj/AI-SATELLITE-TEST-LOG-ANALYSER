"""
Lightweight knowledge base of common satellite AIT / test anomalies.

Maps log codes and message keywords to a plain-language explanation, likely
causes, and recommended operator actions. This serves two purposes:

  1. It powers the **offline fallback** of the operator assistant (no API key
     needed), so the prototype is always useful.
  2. When a real LLM backend is configured, these entries are injected as
     grounding context (retrieval-style), keeping the model's answers anchored
     to domain knowledge instead of free-floating speculation.
"""

from __future__ import annotations

# Each entry: keyword/code -> dict(summary, causes[list], actions[list], refs[list])
KNOWLEDGE_BASE: dict[str, dict] = {
    "EPS-810": {  # battery / power bus family
        "summary": "Battery bus voltage left its nominal band, indicating a power "
                   "anomaly on the primary bus during the test.",
        "causes": [
            "Excessive load step from a subsystem powering on",
            "EGSE power supply current limit / droop",
            "Battery state-of-charge lower than expected for this test phase",
            "Loose or high-resistance harness connection on the power bus",
        ],
        "actions": [
            "Cross-check EGSE power supply set-points and current limits",
            "Inspect the bus-current trace for the coincident load step",
            "Verify harness mating and contact resistance on the EPS interface (J1)",
            "Confirm whether any subsystem power-on coincides with the sag",
        ],
        "refs": ["EPS ICD power-bus limits", "Test procedure EPS_FUNCTIONAL"],
    },
    "OBC-311": {  # brown-out / reset family
        "summary": "The on-board computer experienced a brown-out / unexpected "
                   "reset, almost certainly secondary to the power anomaly.",
        "causes": [
            "Bus undervoltage dropping below OBC operating threshold",
            "Watchdog timeout triggered by the voltage transient",
        ],
        "actions": [
            "Correlate reset time with the EPS undervoltage event",
            "Retrieve and archive the OBC reset cause register",
            "Re-run the affected test step after power is confirmed stable",
        ],
        "refs": ["OBC reset-cause log", "Anomaly report template"],
    },
    "TCS-711": {  # thermal family
        "summary": "A thermal control parameter is rising toward / past its limit, "
                   "suggesting the control loop cannot reject heat fast enough.",
        "causes": [
            "Heater stuck on or control loop saturated",
            "Reduced radiator efficiency / TVAC chamber boundary condition",
            "Higher-than-modelled dissipation from an active unit",
        ],
        "actions": [
            "Check heater duty-cycle commands vs. measured temperature",
            "Review TVAC shroud temperature and chamber settings",
            "Hold the test step and notify the thermal engineer before red limit",
        ],
        "refs": ["TCS limit table", "TVAC test plan"],
    },
    "AOCS-611": {  # reaction wheel family
        "summary": "Reaction wheel speed exceeded its operating band, with torque "
                   "command oscillation indicating a control-loop instability.",
        "causes": [
            "Aggressive slew / pointing command in the test profile",
            "Controller gain or momentum-management configuration issue",
            "Sensor noise feeding back into the torque command",
        ],
        "actions": [
            "Inspect the commanded vs. measured wheel speed profile",
            "Verify momentum-management thresholds and safe-mode entry logic",
            "Coordinate with AOCS engineer before re-commanding the wheel",
        ],
        "refs": ["AOCS controller config", "Pointing test procedure"],
    },
    "COMMS-911": {  # downlink family
        "summary": "The S-band downlink dropped intermittently as RSSI fell below "
                   "the lock threshold.",
        "causes": [
            "RF cabling / connector issue between TX and EGSE receiver",
            "Antenna pointing or test-fixture alignment during the run",
            "External RF interference in the test area",
        ],
        "actions": [
            "Check RF chain connectors and attenuator settings",
            "Review RSSI trace for periodicity (mechanical vs. interference)",
            "Confirm test-area RF environment / spectrum monitor",
        ],
        "refs": ["COMMS RF check procedure", "Link budget"],
    },
    "EGSE-211": {  # ground equipment family
        "summary": "The EGSE lost its link to the check-out system; this is a "
                   "ground-segment issue, not a flight-hardware anomaly.",
        "causes": [
            "Network/TCP interruption between EGSE and CCS",
            "EGSE software hang or restart",
            "Cable / switch problem on the ground network",
        ],
        "actions": [
            "Confirm EGSE process health and restart if needed",
            "Check ground-network connectivity and switch logs",
            "Annotate the test log: flight-hardware data in this window is suspect",
        ],
        "refs": ["EGSE operations guide", "Ground network diagram"],
    },
}

# Keyword fallbacks when no code prefix matches.
KEYWORD_HINTS: dict[str, str] = {
    "voltage": "EPS-810",
    "current": "EPS-810",
    "brown-out": "OBC-311",
    "reset": "OBC-311",
    "temperature": "TCS-711",
    "panel": "TCS-711",
    "heater": "TCS-711",
    "wheel": "AOCS-611",
    "torque": "AOCS-611",
    "momentum": "AOCS-611",
    "downlink": "COMMS-911",
    "rssi": "COMMS-911",
    "egse": "EGSE-211",
    "link": "EGSE-211",
}


def lookup(codes: list[str], message: str) -> dict | None:
    """Find the best knowledge-base entry for a set of codes / a message."""
    for code in codes:
        for prefix, entry in KNOWLEDGE_BASE.items():
            if code.startswith(prefix):
                return entry
    low = message.lower()
    for kw, key in KEYWORD_HINTS.items():
        if kw in low:
            return KNOWLEDGE_BASE.get(key)
    return None
