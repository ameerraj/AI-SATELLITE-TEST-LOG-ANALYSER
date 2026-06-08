# Architecture & Design Notes

This document explains *how* the analyzer is built and *why* the main design
decisions were made. For the *why-it-matters* (objectives, scope, risks,
benefits) see [`CONCEPT.md`](CONCEPT.md); for how to run it see the repository
`README.md`.

---

## 1. High-level data flow

```
  test log  ─▶  parsing  ─────────────▶  log events ─────┐
                                                          ▼
                                                 incident clustering ──▶ operator
                                                 (TF-IDF + DBSCAN)        assistant
  telemetry ─▶  anomaly detection ─▶ anomaly events ──┘                  (LLM | rules)
                (OOL · z-score ·                                              │
                 IsolationForest)                                            ▼
                                                              pipeline → JSON → dashboard / report
```

The four analysis stages are independent and composable; `pipeline.py` wires
them into a single `AnalysisResult` that everything downstream consumes.

---

## 2. Module map

| Module | Responsibility | Key types / functions |
|---|---|---|
| `satlog/config.py` | Declarative domain knowledge: telemetry limits + subsystems | `ParamLimits`, `TELEMETRY_PARAMS`, `SUBSYSTEMS` |
| `satlog/parsing/log_parser.py` | Raw log → tidy `DataFrame` (tolerant) | `parse_log_file`, `parse_summary` |
| `satlog/anomaly/detector.py` | Telemetry → anomaly events | `detect_anomalies`, `AnomalyResult` |
| `satlog/clustering/incidents.py` | Log events → incidents | `cluster_incidents`, `Incident` |
| `satlog/llm/knowledge_base.py` | Curated AIT fault signatures | `KNOWLEDGE_BASE`, `lookup` |
| `satlog/llm/operator_assistant.py` | Incident → operator briefing | `OperatorAssistant`, `OperatorBriefing` |
| `satlog/pipeline.py` | Orchestrates the four stages | `run_pipeline`, `AnalysisResult` |
| `satlog/cli.py` | `generate` / `analyze` commands | `main` |
| `satlog/report.py` | Static matplotlib PNG report | `build_report` |
| `satlog/dashboard/` | Flask + Chart.js UI | `app.py`, `templates/`, `static/` |
| `data/generate_data.py` | Reproducible synthetic data | — |

---

## 3. Design decisions & rationale

### 3.1 Limits live in one declarative config
`config.py` holds nominal/yellow/red limits per parameter, mirroring how a real
CCS separates the **limit definition** (MIB) from the **monitoring logic**. This
keeps the detector generic and makes re-targeting to another spacecraft a
config change, not a code change.

### 3.2 The parser never drops data
Malformed log lines are kept and flagged (`parsed=False`) rather than silently
discarded. In a test/qualification context, *losing* a line is worse than
keeping a messy one — the engineer must be able to trust that the structured
view is complete.

### 3.3 Three anomaly layers, all explainable
Out-of-limit, rolling z-score, and IsolationForest were chosen to cover three
*different* failure shapes (hard breach, in-limit drift, odd combination). Each
anomaly carries the method that raised it. Explainability was prioritised over a
single more powerful black-box model, because a tool used during qualification
has to be **trusted and auditable**.

### 3.4 Clustering features
Incident clustering combines: number-masked **TF-IDF** of the message (so
`EPS-810 at 27.1V` and `EPS-810 at 26.9V` cluster together), a **subsystem**
one-hot, and a **scaled time** feature. DBSCAN (cosine metric) is used because
the number of incidents is *not known in advance* and DBSCAN treats isolated
one-off events as their own clusters rather than forcing them into a group.

### 3.5 Dual assistant backend (offline-first)
`OperatorAssistant` auto-selects: a real LLM (Anthropic) **if** a key + SDK are
present, otherwise a deterministic offline backend over the curated knowledge
base. The knowledge base also *grounds* the LLM. This makes the prototype run
on an air-gapped test network by default, while still able to use a frontier
model when permitted. LLM failures fall back to rules rather than erroring.

### 3.6 Advisory only
No stage can act on the spacecraft. The output is structured advice for a human.
This is a deliberate safety boundary, reflected throughout the design.

### 3.7 Mission-control aesthetic
The dashboard uses a dark, monospace, instrument-panel style — appropriate to a
control-room context and easy to scan for severity at a glance.

---

## 4. Key data structures

- **Parsed log** — `DataFrame`: `timestamp, t_rel_s, level, subsystem, message, code, parsed`.
- **`AnomalyResult`** — per-sample `flags`, consolidated `events`
  (start/end/parameter/severity/method), and summary `stats`.
- **`Incident`** — id, severity, subsystem, time window, member events,
  representative message, code.
- **`OperatorBriefing`** — summary, likely cause, recommended actions list,
  references; `to_text()` for console/report rendering.
- **`AnalysisResult`** — log summary, telemetry stats, anomaly events,
  incidents, briefings, downsampled telemetry preview, and run metadata;
  `to_json()` is the single contract the dashboard and report consume.

---

## 5. Extensibility

- **New parameter** → add a `ParamLimits` entry in `config.py`.
- **New fault signature** → add an entry to `KNOWLEDGE_BASE`.
- **New detection method** → add a function in `detector.py` that contributes
  flags; consolidation into events is shared.
- **Real data source** → replace `generate_data.py` / point the parser and
  `load_telemetry` at real files. The pipeline contract is unchanged.

---

## 6. Testing

`tests/test_core.py` covers the parser (including malformed-line tolerance and
relative-time computation), anomaly detection (red-OOL recovery and a
clean-telemetry baseline that must raise nothing), incident clustering
(grouping + severity ordering), and the offline assistant (known signature →
briefing, unknown signature → escalation). Run with `pytest -q`.

---

## 7. Known limitations

- Synthetic data only; thresholds are illustrative, not calibrated on real runs.
- ML components are unvalidated for qualification use.
- Single-session, in-memory; no persistence or multi-user state.
- Time alignment between log and telemetry is assumed, not enforced.

These are intentional, consistent with a proof-of-concept; see
[`CONCEPT.md`](CONCEPT.md) §4.2 and §8 for the path beyond them.
