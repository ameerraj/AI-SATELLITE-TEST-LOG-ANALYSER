# Concept Proposal — AI-Assisted Test Log Analysis for Satellite AIT

**Document type:** Technical concept / proof-of-concept proposal
**Status:** Prototype delivered (this repository)
**Author:** *(working-student candidate)*
**Context:** Automation & AI activities within Assembly, Integration & Test (AIT)

---

## 1. Summary

During satellite Assembly, Integration & Test (AIT), every functional and
environmental test campaign produces large volumes of **test logs** (from the
Central Check-Out System / EGSE) and **telemetry** from the spacecraft under
test. Today this data is reviewed largely by hand: an engineer scrolls through
thousands of log lines and telemetry plots to confirm a test passed, or to
understand *why* it failed.

This is exactly the kind of **manual, repetitive, high-volume** task that scales
badly toward constellation-scale production, and exactly the kind of task where
**data analysis and AI** can assist a human operator without replacing their
judgement.

This proposal describes a small, end-to-end **proof-of-concept** that ingests a
test session, automatically surfaces anomalies, groups related events into a
small number of **incidents**, and generates a plain-language **operator
briefing** for each one. It is implemented and runnable (see the repository
root `README.md`); this document captures the *why*, the *scope*, the *risks*,
and the *expected benefits* in proposal form.

---

## 2. Problem statement

| Pain point | Current state | Impact |
|---|---|---|
| Log review is manual | Engineer reads raw CCS/EGSE logs line by line | Slow, fatiguing, error-prone |
| Anomalies hide *within* limits | Hard limits catch hard failures, but slow drifts and odd parameter *combinations* slip through | Issues found late, sometimes only at review |
| Repeated faults re-investigated | The same signature recurs across runs and units with no shared memory | Duplicated effort across the team |
| Knowledge is tribal | "What does `EPS-810` mean and what do I do?" lives in senior engineers' heads | Onboarding is slow; bus factor risk |

As production moves toward **constellations** (many near-identical units, many
repeated test sequences), each of these costs is multiplied.

---

## 3. Objectives

**Primary objective.** Demonstrate that a lightweight, explainable software tool
can reduce the manual effort of reviewing a satellite test session, while
keeping the human engineer fully in control of the verdict.

Concrete, measurable objectives for the prototype:

1. **Parse** a raw CCS/EGSE-style test log into structured, queryable events
   without discarding malformed lines.
2. **Detect** telemetry anomalies using more than one method, and make every
   anomaly **explainable** (which method flagged it, and why).
3. **Cluster** the noisy stream of warnings/errors into a *small* number of
   distinct incidents, so the engineer reads ~5 incidents instead of ~250 lines.
4. **Assist** the operator with a structured briefing per incident (likely
   cause, recommended actions, references), grounded in domain knowledge.
5. **Present** all of the above in a dashboard and a static report suitable for
   internal or customer-facing review.
6. Run **fully offline** (air-gapped test network friendly) while still being
   able to use a frontier LLM when one is available.

---

## 4. Scope

### 4.1 In scope

- A reproducible **synthetic** data generator (no proprietary or flight data),
  producing a CCS-style log plus multi-parameter telemetry with injected faults.
- A four-stage analysis pipeline: **parsing → anomaly detection → incident
  clustering → operator assistant**, orchestrated into a single JSON result.
- Two assistant backends (offline rule/knowledge-base, and optional real LLM),
  selected automatically.
- A Flask + Chart.js **dashboard** and a matplotlib **PNG mission report**.
- Unit tests for the core logic and developer tooling (`Makefile`, demo script).

### 4.2 Out of scope (deliberately)

- Integration with any **real** CCS/EGSE, MIB import, or live data feed.
- Production-grade auth, multi-user state, persistence/database.
- Any autonomous action on the spacecraft. The tool **advises**; it never
  commands. This is a hard boundary, not a missing feature.
- Formal model validation/qualification of the ML components.

### 4.3 Assumptions

- Telemetry is roughly time-synchronised and sampled at ~1 Hz.
- Per-parameter red/yellow limits are available (here held in
  `satlog/config.py`, mirroring a CCS parameter database / MIB).
- A human engineer reviews and owns the final pass/fail decision.

---

## 5. Approach

The prototype is built around the principle **"assist, don't replace"**, with
explainability prioritised over raw model sophistication — because a tool used
during qualification must be *trusted*.

1. **Parsing** — a tolerant regex parser turns log lines into a tidy
   `DataFrame`. Malformed lines are *kept* and flagged rather than dropped, so
   nothing is silently lost.
2. **Anomaly detection** — three complementary layers:
   - **Out-of-limit (OOL)** against red/yellow limits — the classic CCS check.
   - **Rolling z-score** — catches drifts/spikes that are still *within* limits.
   - **IsolationForest** — unsupervised, over all parameters jointly, catching
     anomalies that only appear as an unusual *combination* of values.
   Each anomaly records *which* method raised it.
3. **Incident clustering** — warnings/errors are embedded using number-masked
   TF-IDF + subsystem + time features and grouped with **DBSCAN**, collapsing a
   noisy event stream into a handful of triaged incidents.
4. **Operator assistant** — for each incident it produces a structured briefing
   (summary, likely cause, recommended actions, references). The offline backend
   uses a curated knowledge base of AIT fault signatures; the optional LLM
   backend is *grounded* with that same knowledge base so answers stay anchored.

---

## 6. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **False sense of trust** in AI output | Med | High | Every anomaly is explainable (method shown); the tool advises only, the engineer decides. |
| **False negatives** (missed anomaly) | Med | High | Three independent detection layers; OOL guarantees hard breaches are always caught regardless of the ML layer. |
| **False positives / alert fatigue** | Med | Med | Clustering + severity ranking surface a *small* triaged list; z-score window and contamination are tunable. |
| **Model drift / non-determinism (LLM)** | Med | Med | Deterministic offline backend is the default; LLM is optional and grounded in the knowledge base. |
| **Data confidentiality** | Low | High | Prototype uses only synthetic data; runs fully offline with no network egress. |
| **Limits/MIB unavailable for a new spacecraft** | Med | Med | Limits are isolated in one declarative config module, easy to re-target. |
| **Scope creep toward "autonomous test"** | Med | Med | "Assist, don't replace" stated as a hard boundary in section 4.2. |

---

## 7. Expected benefits

- **Faster review** — engineer reads a handful of ranked incidents with context
  instead of scrolling raw logs and plots.
- **Earlier detection** — drift/combination anomalies are surfaced before they
  breach a hard limit.
- **Shared memory** — a curated knowledge base captures fault signatures so the
  same issue isn't re-investigated from scratch, and onboarding is faster.
- **Scales with the constellation** — the same automated pass works identically
  across many near-identical units and repeated test sequences.
- **Low adoption risk** — explainable, advisory-only, offline-capable, and built
  on a standard, well-understood Python data/ML stack.

---

## 8. Indicative effort & next steps

This proof-of-concept was scoped as a small, self-contained build. A realistic
path from here, in rough task-breakdown form:

| Step | Goal | Indicative effort |
|---|---|---|
| 1 | Replace synthetic data with a **real CCS log + MIB import** for one campaign | 1–2 weeks |
| 2 | Calibrate limits/thresholds on **historical** passing runs | 1 week |
| 3 | Validate detection against known **labelled** past anomalies | 1–2 weeks |
| 4 | Engineer-in-the-loop **trial** on a live campaign (advisory only) | 2–4 weeks |
| 5 | Harden, document, and integrate into the team's tooling | ongoing |

Dependencies: access to representative historical logs/telemetry; agreement on
which subsystems/parameters to monitor first; sign-off that the tool remains
strictly advisory during any trial.

---

## 9. Conclusion

The prototype shows that the manual log/telemetry review bottleneck in AIT is a
realistic, low-risk target for AI-assisted automation. By keeping the design
**explainable, advisory, and offline-capable**, it can be trialled inside a test
environment with minimal risk, while offering a clear path toward the
review-effort savings that constellation-scale production will require.
