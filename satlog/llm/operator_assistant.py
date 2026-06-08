"""
LLM-assisted operator support.

Given a detected incident (and optionally correlated telemetry anomalies), the
assistant produces an operator-facing briefing:

  * a plain-language explanation of what happened,
  * the most likely causes,
  * concrete recommended next actions,
  * a suggested severity / triage call.

Design choice — graceful degradation
-------------------------------------
The assistant has two backends:

  * ``llm``  — calls a real model (Anthropic by default) when an API key is set
    in the environment. The knowledge base is injected as grounding context.
  * ``rules`` — a fully offline, deterministic backend built on the curated
    knowledge base. Always available, no network, no key.

The backend is selected automatically, so the prototype runs anywhere (including
an air-gapped test network — common in AIT) while still being able to use a
frontier model when one is available. This mirrors the kind of pragmatic,
deployable tooling the AIT automation team values.
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass

from satlog.llm.knowledge_base import KNOWLEDGE_BASE, lookup


@dataclass
class OperatorBriefing:
    incident_id: int
    backend: str
    severity: str
    explanation: str
    likely_causes: list[str]
    recommended_actions: list[str]
    references: list[str]

    def as_dict(self) -> dict:
        return self.__dict__.copy()

    def to_text(self) -> str:
        lines = [
            f"Incident #{self.incident_id}  [{self.severity}]  (backend: {self.backend})",
            "-" * 60,
            *textwrap.wrap(self.explanation, width=70),
            "",
            "Likely causes:",
            *[f"  - {c}" for c in self.likely_causes],
            "",
            "Recommended actions:",
            *[f"  {i}. {a}" for i, a in enumerate(self.recommended_actions, 1)],
            "",
            f"References: {', '.join(self.references) if self.references else 'n/a'}",
        ]
        return "\n".join(lines)


class OperatorAssistant:
    """Produces operator briefings for incidents, with auto backend selection."""

    def __init__(self, backend: str = "auto", model: str | None = None):
        self.model = model or os.environ.get("SATLOG_LLM_MODEL", "claude-sonnet-4-5")
        self.backend = self._resolve_backend(backend)

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        if backend in ("rules", "llm"):
            return backend
        # auto: use LLM only if a key and the SDK are both present
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic  # noqa: F401
                return "llm"
            except ImportError:
                return "rules"
        return "rules"

    # ------------------------------------------------------------------ public
    def brief(self, incident: dict, anomalies: list[dict] | None = None) -> OperatorBriefing:
        if self.backend == "llm":
            try:
                return self._brief_llm(incident, anomalies or [])
            except Exception as exc:  # robust: never let the tool crash on LLM issues
                fb = self._brief_rules(incident, anomalies or [])
                fb.explanation = (f"[LLM backend failed: {exc}. Showing offline "
                                  f"analysis.]\n\n" + fb.explanation)
                fb.backend = "rules(fallback)"
                return fb
        return self._brief_rules(incident, anomalies or [])

    # ------------------------------------------------------------------ rules
    def _brief_rules(self, incident: dict, anomalies: list[dict]) -> OperatorBriefing:
        codes = incident.get("codes", [])
        message = incident.get("representative_message", "")
        entry = lookup(codes, message)

        if entry is None:
            entry = {
                "summary": "An anomaly was detected but does not match a known "
                           "signature. Manual review by the responsible engineer "
                           "is recommended.",
                "causes": ["Unknown — outside the current knowledge base"],
                "actions": ["Escalate to the responsible subsystem engineer",
                            "Capture full context (telemetry window + log excerpt)"],
                "refs": [],
            }

        sub = ", ".join(incident.get("subsystems", [])) or "unknown"
        dur = round(incident.get("t_end_s", 0) - incident.get("t_start_s", 0), 1)
        corr = self._correlation_note(incident, anomalies)
        explanation = (
            f"Incident on the {sub} subsystem spanning ~{dur} s "
            f"({incident.get('n_events', 0)} correlated log events). "
            f"{entry['summary']}{corr}"
        )
        return OperatorBriefing(
            incident_id=incident.get("incident_id", 0),
            backend="rules",
            severity=incident.get("severity", "WARNING"),
            explanation=explanation,
            likely_causes=list(entry["causes"]),
            recommended_actions=list(entry["actions"]),
            references=list(entry.get("refs", [])),
        )

    @staticmethod
    def _correlation_note(incident: dict, anomalies: list[dict]) -> str:
        """Note any telemetry anomaly overlapping the incident time window."""
        ts, te = incident.get("t_start_s", 0), incident.get("t_end_s", 0)
        hits = [a for a in anomalies
                if not (a["t_end_s"] < ts - 30 or a["t_start_s"] > te + 30)]
        if not hits:
            return ""
        params = sorted({a["parameter"] for a in hits})
        return (f" Correlated telemetry anomalies in the same window: "
                f"{', '.join(params)}.")

    # ------------------------------------------------------------------ llm
    def _brief_llm(self, incident: dict, anomalies: list[dict]) -> OperatorBriefing:
        import json
        import anthropic

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        grounding = json.dumps(
            {k: v for k, v in KNOWLEDGE_BASE.items()}, indent=2
        )
        prompt = textwrap.dedent(f"""\
            You are an assistant for satellite Assembly, Integration & Test (AIT)
            operators. Using the incident data and the domain knowledge base,
            write a concise operator briefing.

            Respond ONLY with JSON of the form:
            {{"severity": "...", "explanation": "...",
              "likely_causes": ["..."], "recommended_actions": ["..."],
              "references": ["..."]}}

            INCIDENT:
            {json.dumps(incident, indent=2)}

            CORRELATED TELEMETRY ANOMALIES:
            {json.dumps(anomalies, indent=2)}

            DOMAIN KNOWLEDGE BASE:
            {grounding}
            """)
        resp = client.messages.create(
            model=self.model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return OperatorBriefing(
            incident_id=incident.get("incident_id", 0),
            backend=f"llm:{self.model}",
            severity=data.get("severity", incident.get("severity", "WARNING")),
            explanation=data.get("explanation", ""),
            likely_causes=data.get("likely_causes", []),
            recommended_actions=data.get("recommended_actions", []),
            references=data.get("references", []),
        )


def assist_incident(incident: dict, anomalies: list[dict] | None = None,
                    backend: str = "auto") -> dict:
    """Convenience one-shot helper used by the pipeline / dashboard."""
    return OperatorAssistant(backend=backend).brief(incident, anomalies).as_dict()
