/* SatLog dashboard — renders the analysis JSON embedded by the Flask template. */
(function () {
  "use strict";

  const el = document.getElementById("analysis-data");
  if (!el) return;
  const A = JSON.parse(el.textContent);

  const COLORS = {
    accent: "#38e0c4", accent2: "#4ea3ff", red: "#ff5b5b",
    amber: "#ffb13d", green: "#46d28a", crit: "#ff2e63",
    dim: "#6b8199", grid: "rgba(80,130,180,0.10)", txt: "#c9d6e3",
  };

  // ---- live UTC clock ----
  function tick() {
    const d = new Date();
    document.getElementById("clock").textContent =
      d.toISOString().substr(11, 8);
  }
  setInterval(tick, 1000); tick();

  document.getElementById("backend-tag").textContent = A.meta.llm_backend;

  // ---- KPIs ----
  const ts = A.telemetry_stats, ls = A.log_summary;
  const nCrit = A.incidents.filter(i => i.severity === "CRITICAL").length;
  const kpis = [
    { v: A.incidents.length, l: "Incidents", c: A.incidents.length ? "amber" : "green" },
    { v: nCrit, l: "Critical", c: nCrit ? "red" : "green" },
    { v: ts.n_ool_red, l: "OOL Red Samples", c: ts.n_ool_red ? "red" : "green" },
    { v: A.anomaly_events.length, l: "Anomaly Events", c: "amber" },
    { v: ls.parsed + "/" + ls.total, l: "Log Lines Parsed", c: "green" },
    { v: ts.n_samples, l: "Telemetry Samples", c: "" },
  ];
  document.getElementById("kpis").innerHTML = kpis.map(k =>
    `<div class="kpi ${k.c}"><div class="v">${k.v}</div><div class="l">${k.l}</div></div>`
  ).join("");

  // ---- anomaly windows per parameter (for chart shading) ----
  const anomByParam = {};
  A.anomaly_events.forEach(a => {
    (anomByParam[a.parameter] = anomByParam[a.parameter] || []).push(a);
  });

  // Chart.js plugin: shade anomaly time windows.
  const shadePlugin = {
    id: "shade",
    beforeDatasetsDraw(chart, _args, opts) {
      const { ctx, chartArea: ca, scales: { x } } = chart;
      (opts.windows || []).forEach(w => {
        const x0 = x.getPixelForValue(w.t_start_s);
        const x1 = x.getPixelForValue(w.t_end_s);
        ctx.save();
        ctx.fillStyle = w.severity === "RED"
          ? "rgba(255,91,91,0.13)" : "rgba(255,177,61,0.12)";
        ctx.fillRect(x0, ca.top, Math.max(x1 - x0, 2), ca.bottom - ca.top);
        ctx.restore();
      });
    },
  };

  function limitDataset(label, value, color, t) {
    return {
      label, data: t.map(() => value), borderColor: color, borderWidth: 1,
      borderDash: [5, 4], pointRadius: 0, fill: false, tension: 0,
    };
  }

  // ---- telemetry charts ----
  const prev = A.telemetry_preview, t = prev.t_rel_s;
  const wrap = document.getElementById("charts");
  Object.keys(prev).filter(k => k !== "t_rel_s").forEach(key => {
    const p = prev[key];
    const wins = anomByParam[key] || [];
    const status = wins.some(w => w.severity === "RED") ? "red"
      : wins.length ? "amber" : "green";
    const card = document.createElement("div");
    card.className = "chart-card";
    card.innerHTML = `
      <div class="chart-head">
        <span class="name">${key}</span>
        <span class="unit">[${p.unit}]</span>
        <span class="badge ${status}">${status === "green" ? "nominal"
          : status === "red" ? "OOL red" : "flagged"}</span>
      </div>
      <div class="chart-wrap"><canvas></canvas></div>`;
    wrap.appendChild(card);

    new Chart(card.querySelector("canvas"), {
      type: "line",
      data: {
        labels: t,
        datasets: [
          { label: key, data: p.values, borderColor: COLORS.accent,
            borderWidth: 1.4, pointRadius: 0, fill: true, tension: 0.15,
            backgroundColor: "rgba(56,224,196,0.06)" },
          limitDataset("red_high", p.red_high, "rgba(255,91,91,0.6)", t),
          limitDataset("red_low", p.red_low, "rgba(255,91,91,0.6)", t),
          limitDataset("yellow_high", p.yellow_high, "rgba(255,177,61,0.45)", t),
          limitDataset("yellow_low", p.yellow_low, "rgba(255,177,61,0.45)", t),
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          shade: { windows: wins },
          tooltip: {
            backgroundColor: "#0c1521", borderColor: "#1c2a3a", borderWidth: 1,
            titleColor: COLORS.dim, bodyColor: COLORS.txt,
            callbacks: { title: it => "t = " + it[0].label + " s" },
            filter: it => it.datasetIndex === 0,
          },
        },
        scales: {
          x: { type: "linear", grid: { color: COLORS.grid },
            ticks: { color: COLORS.dim, font: { family: "IBM Plex Mono", size: 9 },
              maxTicksLimit: 6, callback: v => v + "s" } },
          y: { grid: { color: COLORS.grid },
            ticks: { color: COLORS.dim, font: { family: "IBM Plex Mono", size: 9 } } },
        },
      },
      plugins: [shadePlugin],
    });
  });

  // ---- incidents + briefings ----
  const list = document.getElementById("incidents");
  if (!A.incidents.length) {
    list.innerHTML = `<div class="empty">No incidents detected — all nominal.</div>`;
  }
  A.incidents.forEach((inc, i) => {
    const b = A.briefings[i] || {};
    const causes = (b.likely_causes || []).map(c => `<li>${esc(c)}</li>`).join("");
    const actions = (b.recommended_actions || [])
      .map(a => `<li><span>${esc(a)}</span></li>`).join("");
    const refs = (b.references || []).join(" · ") || "n/a";
    const node = document.createElement("div");
    node.className = "incident " + inc.severity;
    node.innerHTML = `
      <div class="inc-head">
        <span class="sev-tag sev-${inc.severity}">${inc.severity}</span>
        <span class="inc-id">#${inc.incident_id}</span>
        <span class="inc-title">${esc(inc.representative_message)}</span>
        <span class="inc-meta">
          <span class="subs">${inc.subsystems.join(", ")}</span><br>
          ${inc.n_events} events · ${inc.duration_s}s · t+${Math.round(inc.t_start_s)}s
        </span>
        <span class="chevron">▶</span>
      </div>
      <div class="inc-body">
        <div class="codes">codes: ${(inc.codes || []).join(", ") || "—"}
          &nbsp;·&nbsp; <span class="backend-tag">assist: ${esc(b.backend || "—")}</span></div>
        <div class="brief">
          <p>${esc(b.explanation || "")}</p>
          <div><h4>Likely Causes</h4><ul>${causes}</ul></div>
          <div><h4>Recommended Actions</h4><ol>${actions}</ol></div>
          <div class="refs">References: ${esc(refs)}</div>
        </div>
      </div>`;
    node.querySelector(".inc-head").addEventListener("click",
      () => node.classList.toggle("open"));
    list.appendChild(node);
  });
  // open the most severe incident by default
  const first = document.querySelector(".incident");
  if (first) first.classList.add("open");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
})();
