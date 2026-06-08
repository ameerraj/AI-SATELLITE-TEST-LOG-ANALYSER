"""
Static mission-report renderer (matplotlib).

Produces a single PNG summarising a test session: telemetry channels with
limit bands and shaded anomaly windows, plus a triaged incident list. Useful as
offline presentation material (the kind of artefact attached to an AIT anomaly
review or a concept proposal) and as a preview of the live dashboard.

    python -m satlog.report --session TVAC01
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from satlog.config import TELEMETRY_PARAMS  # noqa: E402
from satlog.pipeline import run_pipeline  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = REPO_ROOT / "data" / "samples"

BG = "#0a0f16"; PANEL = "#111b27"; LINE = "#1c2a3a"
TXT = "#c9d6e3"; DIM = "#6b8199"; ACCENT = "#38e0c4"
RED = "#ff5b5b"; AMBER = "#ffb13d"; GREEN = "#46d28a"; CRIT = "#ff2e63"
SEV_COLOR = {"CRITICAL": CRIT, "ERROR": RED, "WARNING": AMBER}


def render(session: str, out_path: Path | None = None) -> Path:
    log = SAMPLE_DIR / f"test_session_{session}.log"
    tlm = SAMPLE_DIR / f"telemetry_{session}.csv"
    result = run_pipeline(log, tlm)
    prev = result.telemetry_preview
    t = prev["t_rel_s"]

    anom_by_param: dict[str, list] = {}
    for a in result.anomaly_events:
        anom_by_param.setdefault(a["parameter"], []).append(a)

    params = [k for k in prev if k != "t_rel_s"]
    n = len(params)
    ncols = 2
    nrows = (n + ncols - 1) // ncols

    fig = plt.figure(figsize=(15, 4 + 2.5 * nrows), facecolor=BG)
    gs = fig.add_gridspec(nrows + 1, ncols, height_ratios=[*([1] * nrows), 1.1],
                          hspace=0.55, wspace=0.18,
                          left=0.06, right=0.97, top=0.93, bottom=0.05)

    fig.suptitle(f"SatLog Analyzer  ·  Mission Report  ·  Session {session}",
                 color=ACCENT, fontsize=17, family="monospace",
                 fontweight="bold", x=0.06, ha="left", y=0.975)
    fig.text(0.06, 0.945,
             f"backend: {result.meta['llm_backend']}   |   "
             f"{result.meta['n_incidents']} incidents   |   "
             f"{result.meta['n_anomaly_events']} telemetry anomaly events   |   "
             f"{result.telemetry_stats['n_samples']} samples",
             color=DIM, fontsize=10, family="monospace")

    # --- telemetry panels ---
    for i, key in enumerate(params):
        ax = fig.add_subplot(gs[i // ncols, i % ncols])
        p = prev[key]
        lim = TELEMETRY_PARAMS[key]
        ax.set_facecolor(PANEL)
        ax.plot(t, p["values"], color=ACCENT, lw=1.2)
        ax.fill_between(t, p["values"], min(p["values"]),
                        color=ACCENT, alpha=0.06)
        for lv, col, ls in [(lim.red_high, RED, "--"), (lim.red_low, RED, "--"),
                            (lim.yellow_high, AMBER, ":"), (lim.yellow_low, AMBER, ":")]:
            ax.axhline(lv, color=col, lw=0.8, ls=ls, alpha=0.6)
        for w in anom_by_param.get(key, []):
            ax.axvspan(w["t_start_s"], w["t_end_s"],
                       color=RED if w["severity"] == "RED" else AMBER, alpha=0.14)
        ax.set_title(f"{key}  [{lim.unit}]", color=TXT, fontsize=10,
                     family="monospace", loc="left", pad=4)
        ax.tick_params(colors=DIM, labelsize=8)
        for sp in ax.spines.values():
            sp.set_color(LINE)
        ax.grid(color=LINE, alpha=0.4, lw=0.5)
        ax.margins(x=0)

    # --- incident panel ---
    axi = fig.add_subplot(gs[nrows, :])
    axi.set_facecolor(PANEL)
    axi.axis("off")
    for sp in axi.spines.values():
        sp.set_visible(False)
    axi.text(0.005, 0.96, "TRIAGED INCIDENTS  ·  OPERATOR BRIEFINGS",
             color=DIM, fontsize=10, family="monospace", weight="bold",
             transform=axi.transAxes, va="top")
    y = 0.86
    for inc, br in zip(result.incidents, result.briefings):
        col = SEV_COLOR.get(inc["severity"], AMBER)
        axi.text(0.005, y, f"#{inc['incident_id']}", color=DIM, fontsize=9,
                 family="monospace", transform=axi.transAxes, va="top")
        axi.text(0.035, y, inc["severity"], color="#0a0f16", fontsize=8.5,
                 family="monospace", weight="bold", transform=axi.transAxes, va="top",
                 bbox=dict(boxstyle="round,pad=0.3", fc=col, ec="none"))
        head = (f"{', '.join(inc['subsystems'])}  ·  {inc['n_events']} events  ·  "
                f"{inc['duration_s']}s  ·  {inc['representative_message'][:78]}")
        axi.text(0.115, y, head, color=TXT, fontsize=9, family="monospace",
                 transform=axi.transAxes, va="top")
        action = (br["recommended_actions"][0] if br["recommended_actions"] else "")
        axi.text(0.115, y - 0.05, "↳ " + action[:96], color=ACCENT, fontsize=8.2,
                 family="monospace", transform=axi.transAxes, va="top")
        y -= 0.135

    out_path = out_path or (REPO_ROOT / "outputs" / f"report_{session}.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor=BG)
    plt.close(fig)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render a static mission report PNG")
    ap.add_argument("--session", default="TVAC01")
    args = ap.parse_args()
    print("Wrote", render(args.session))
