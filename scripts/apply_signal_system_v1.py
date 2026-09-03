"""
CFB ANALYTICS
apply_signal_system_v1.py

ONE-TIME, GUARDED frontend migration for Signal System v1.

This script modifies ONLY:
    app.js
    index.html

It does not touch Model A, projections, frozen data, snapshots, closing lines,
or settlement logic. Legacy labels remain preserved in stored data.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.js"
INDEX = ROOT / "index.html"


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text, pattern, replacement, label, flags=0):
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 regex match, found {count}")
    return new_text


def main():
    app = APP.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    if "Signal System v1:" in app:
        raise RuntimeError("app.js already appears to contain Signal System v1.")

    app = replace_once(
        app,
        "// The Signal UI v3: ALIGNED / SLIGHT EDGE / EDGE / STRONG EDGE / OUTLIER",
        "// Signal System v1: ALIGNED / SMALL EDGE / PLAY / MATERIAL DISAGREEMENT / OUTLIER",
        "app header",
    )

    app = replace_once(
        app,
        '  projections: "./data/projections.json",\n};',
        '  projections: "./data/projections.json",\n  signalReport: "./data/reports/signal_report.json",\n};',
        "signal report URL",
    )

    app = replace_once(
        app,
        "let projectionsData = null;\n",
        "let projectionsData = null;\nlet signalReportData = null;\n",
        "signal report state",
    )

    helper_pattern = r"function statusClass\(status\) \{.*?function statusEdgeClass\(status\) \{.*?\n\}"
    helper_replacement = r"""function canonicalSignal(status) {
  if (!status || status === "NO MARKET") return "NO LINE";

  switch (status) {
    case "AGREE W/ MARKET":
    case "ALIGNED":
      return "ALIGNED";
    case "LEAN":
    case "SLIGHT EDGE":
    case "SMALL EDGE":
      return "SMALL EDGE";
    case "EDGE":
    case "PLAY":
      return "PLAY";
    case "STRONG EDGE":
    case "MATERIAL DISAGREEMENT":
      return "MATERIAL DISAGREEMENT";
    case "OUTLIER":
      return "OUTLIER";
    default:
      return status;
  }
}

function statusClass(status) {
  switch (canonicalSignal(status)) {
    case "MATERIAL DISAGREEMENT": return "material";
    case "PLAY": return "play";
    case "SMALL EDGE": return "small-edge";
    case "OUTLIER": return "outlier";
    case "ALIGNED": return "agree";
    default: return "inline";
  }
}

function displayStatus(status) {
  return canonicalSignal(status);
}

function signalStats(status) {
  const signal = canonicalSignal(status);
  return signalReportData?.signals?.[signal] ?? null;
}

function signalConfidence(status) {
  if (canonicalSignal(status) === "NO LINE") return "—";
  return signalStats(status)?.confidence ?? "DEVELOPING";
}

function confidenceClass(confidence) {
  switch (String(confidence || "").toUpperCase()) {
    case "ESTABLISHED": return "confidence-established";
    case "VALIDATED": return "confidence-validated";
    case "DEVELOPING": return "confidence-developing";
    default: return "agree";
  }
}

function signalRecordText(status) {
  if (canonicalSignal(status) === "NO LINE") return "—";
  return signalStats(status)?.record?.record_text ?? "0-0";
}

function signalAtsText(status) {
  if (canonicalSignal(status) === "NO LINE") return "No market";
  const pct = signalStats(status)?.record?.ats_win_pct_ex_pushes;
  return hasValue(pct) ? `${formatNumber(pct, 1)}% ATS` : "ATS tracking";
}

function signalClvText(status) {
  const clv = signalStats(status)?.clv?.average_clv_points;
  return hasValue(clv) ? `${formatSigned(clv, 2)} avg CLV` : "CLV tracking";
}

function signalBeatCloseText(status) {
  const pct = signalStats(status)?.clv?.beat_close_pct_ex_pushes;
  return hasValue(pct) ? `${formatNumber(pct, 1)}% beat close` : "Beat-close tracking";
}

function statusEdgeClass(status) {
  switch (canonicalSignal(status)) {
    case "MATERIAL DISAGREEMENT": return "edge-material";
    case "PLAY": return "edge-play";
    case "SMALL EDGE": return "edge-small";
    case "OUTLIER": return "edge-outlier";
    default: return "";
  }
}"""
    app = regex_once(app, helper_pattern, helper_replacement, "signal helper block", flags=re.S)

    app = replace_once(app, '  if (document.getElementById("cfb-status-ui-v2")) return;', '  if (document.getElementById("cfb-signal-system-v1")) return;', "style guard")
    app = replace_once(app, '  style.id = "cfb-status-ui-v2";', '  style.id = "cfb-signal-system-v1";', "style id")

    old_css = """    .status.edge {
      background: var(--green-light);
      color: var(--green);
      border: 1px solid #bfd9d0;
    }

    .status.lean {
      background: var(--amber-light);
      color: var(--amber);
      border: 1px solid #efd9b8;
    }

    .status.outlier {
      background: var(--red-light);
      color: var(--red);
      border: 1px solid #e9c2bd;
    }
"""
    new_css = """    .status.small-edge {
      background:#edf3fb;
      color:#355f91;
      border:1px solid #c9d7e8;
    }

    .status.play {
      background:var(--green);
      color:#ffffff;
      border:1px solid var(--green);
    }

    .status.material {
      background:#0f5c49;
      color:#ffffff;
      border:1px solid #0f5c49;
    }

    .status.outlier {
      background:#fff0df;
      color:#9a4d00;
      border:1px solid #e6b77d;
    }

    .confidence-developing {
      background:#f8e7a1 !important;
      color:#4e3b00 !important;
      border:1px solid #d9bd53 !important;
    }

    .confidence-validated {
      background:var(--green) !important;
      color:#ffffff !important;
      border:1px solid var(--green) !important;
    }

    .confidence-established {
      background:#5b4bc4 !important;
      color:#ffffff !important;
      border:1px solid #4a3cab !important;
      box-shadow:0 0 0 1px rgba(91,75,196,.08);
    }
"""
    app = replace_once(app, old_css, new_css, "status CSS")

    old_summary_css = """    .disagreement-number.edge { color: var(--green); }
    .disagreement-number.lean { color: var(--amber); }
    .disagreement-number.outlier { color: var(--red); }
    .disagreement-number.agree { color: var(--muted); }

    .summary-play { color:var(--green); font-weight:500; }
    .summary-edge { color:var(--green); font-weight:500; }
    .summary-lean { color:var(--amber); font-weight:500; }
    .summary-outlier { color:var(--red); font-weight:500; }
"""
    new_summary_css = """    .disagreement-number.material { color:#0f5c49; }
    .disagreement-number.play { color:var(--green); }
    .disagreement-number.small-edge { color:#355f91; }
    .disagreement-number.outlier { color:#9a4d00; }
    .disagreement-number.agree { color:var(--muted); }

    .summary-material { color:#0f5c49; font-weight:600; }
    .summary-play { color:var(--green); font-weight:600; }
    .summary-small { color:#355f91; font-weight:600; }
    .summary-outlier { color:#9a4d00; font-weight:600; }

    .signal-guide {
      margin:16px 0 18px;
      background:var(--surface);
      border:1px solid var(--border);
      border-radius:12px;
      overflow:hidden;
    }

    .signal-guide summary {
      list-style:none;
      cursor:pointer;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:14px 16px;
      font-weight:700;
      font-size:12px;
    }

    .signal-guide summary::-webkit-details-marker { display:none; }
    .signal-guide summary::after { content:"+"; font-family:var(--mono); color:var(--muted); font-size:16px; }
    .signal-guide[open] summary::after { content:"−"; }
    .signal-guide-body { border-top:1px solid var(--border); padding:16px; }
    .signal-guide-copy { color:var(--muted); font-size:11px; line-height:1.6; margin-bottom:14px; max-width:960px; }
    .signal-legend-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin-bottom:14px; }
    .signal-legend-item { border:1px solid var(--border); border-radius:9px; padding:11px; min-width:0; }
    .signal-legend-name { font-family:var(--mono); font-size:9px; font-weight:700; letter-spacing:.5px; }
    .signal-legend-range { margin-top:5px; color:var(--muted); font-size:10px; }
    .confidence-legend { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; }
    .confidence-legend-note { color:var(--muted); font-size:10px; line-height:1.5; }
    .signal-record { color:var(--muted); font-size:9px; margin-top:5px; font-family:var(--mono); white-space:nowrap; }
"""
    app = replace_once(app, old_summary_css, new_summary_css, "summary/legend CSS")

    app = replace_once(
        app,
        "    .edge-play, .edge-edge { color:var(--green); }\n    .edge-lean { color:var(--amber); }\n    .edge-outlier { color:var(--red); }",
        "    .edge-material { color:#0f5c49; }\n    .edge-play { color:var(--green); }\n    .edge-small { color:#355f91; }\n    .edge-outlier { color:#9a4d00; }",
        "edge color CSS",
    )

    app = replace_once(app, "    @media (max-width:900px) {\n      .analysis-grid, .season-summary-grid {", "    @media (max-width:900px) {\n      .signal-legend-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }\n      .analysis-grid, .season-summary-grid {", "responsive legend")
    app = replace_once(app, "    @media (max-width:520px) {\n      .analysis-grid, .season-summary-grid { grid-template-columns:1fr; }", "    @media (max-width:520px) {\n      .signal-legend-grid { grid-template-columns:1fr; }\n      .analysis-grid, .season-summary-grid { grid-template-columns:1fr; }", "mobile legend")

    old_init = """    [metricsData, scheduleData, oddsData, projectionsData] = await Promise.all([
      loadJson(DATA_URLS.metrics),
      loadJson(DATA_URLS.schedule),
      loadJson(DATA_URLS.odds),
      loadJson(DATA_URLS.projections),
    ]);

    teams = metricsData?.teams ?? {};
"""
    new_init = """    [metricsData, scheduleData, oddsData, projectionsData, signalReportData] = await Promise.all([
      loadJson(DATA_URLS.metrics),
      loadJson(DATA_URLS.schedule),
      loadJson(DATA_URLS.odds),
      loadJson(DATA_URLS.projections),
      loadJson(DATA_URLS.signalReport).catch(() => null),
    ]);

    teams = metricsData?.teams ?? {};
"""
    app = replace_once(app, old_init, new_init, "init data load")

    summary_pattern = r'  const strongEdges = statusCount\(games, "STRONG EDGE", "PLAY"\);.*?\n  \}'
    summary_replacement = """  const material = statusCount(games, "STRONG EDGE", "MATERIAL DISAGREEMENT");
  const plays = statusCount(games, "EDGE", "PLAY");
  const smallEdges = statusCount(games, "SLIGHT EDGE", "LEAN", "SMALL EDGE");
  const outliers = statusCount(games, "OUTLIER");

  if (summary) {
    summary.innerHTML = `
      ${games.length} games
      · ${marketGames.length} lined
      · <span class="summary-material">${material} material disagreements</span>
      · <span class="summary-play">${plays} plays</span>
      · <span class="summary-small">${smallEdges} small edges</span>
      ${outliers ? `· <span class="summary-outlier">${outliers} outliers</span>` : ""}
    `;
  }"""
    app = regex_once(app, summary_pattern, summary_replacement, "projection summary", flags=re.S)

    app = replace_once(
        app,
        '          <th class="align-right">Disagreement</th>\n          <th class="align-right">The Signal</th>\n          <th class="align-right">Bet Status</th>',
        '          <th class="align-right">Model Edge</th>\n          <th class="align-right">Model Signal</th>\n          <th class="align-right">Signal Confidence</th>',
        "table headers",
    )

    app = replace_once(
        app,
        '  const betStatus =\n    game?.comparison?.bet_status ??\n    (hasValue(marketSpread) ? "TRACKING" : null);\n  const cssStatus = statusClass(status);',
        '  const confidence = signalConfidence(status);\n  const cssStatus = statusClass(status);\n  const confidenceCss = confidenceClass(confidence);',
        "row confidence vars",
    )

    app = replace_once(
        app,
        '      <td class="status-cell">\n        <span class="status ${cssStatus}">\n          ${escapeHtml(displayStatus(status))}\n        </span>\n      </td>\n\n      <td class="status-cell">\n        <span class="status agree">\n          ${escapeHtml(displayBetStatus(betStatus))}\n        </span>\n      </td>',
        '      <td class="status-cell">\n        <span class="status ${cssStatus}">\n          ${escapeHtml(displayStatus(status))}\n        </span>\n      </td>\n\n      <td class="status-cell">\n        <span class="status ${confidenceCss}">\n          ${escapeHtml(confidence)}\n        </span>\n        <div class="signal-record">\n          ${escapeHtml(signalRecordText(status))} · ${escapeHtml(signalAtsText(status))}\n        </div>\n      </td>',
        "row signal confidence",
    )

    app = replace_once(
        app,
        '  const betStatus =\n    comparison?.bet_status ??\n    (hasValue(marketSpread) ? "TRACKING" : null);\n  const statusCss = statusClass(status);\n  const edgeClass = statusEdgeClass(status);',
        '  const confidence = signalConfidence(status);\n  const statusCss = statusClass(status);\n  const confidenceCss = confidenceClass(confidence);\n  const edgeClass = statusEdgeClass(status);',
        "matchup confidence vars",
    )

    app = replace_once(app, '        <span class="status agree">\n          Bet Status: ${escapeHtml(displayBetStatus(betStatus))}\n        </span>', '        <span class="status ${confidenceCss}">\n          Signal Confidence: ${escapeHtml(confidence)}\n        </span>', "matchup header confidence")
    app = replace_once(app, '        <div class="model-edge-title">The Signal</div>', '        <div class="model-edge-title">Model Signal</div>', "signal title")

    app = replace_once(
        app,
        '          ${hasValue(edgeSize)\n            ? `${formatNumber(edgeSize, 1)}-point difference between the model fair line and current market.`\n            : "No current market line is available."}',
        '          ${hasValue(edgeSize)\n            ? `${formatNumber(edgeSize, 1)}-point model edge versus the current market. Signal tier measures separation; confidence measures evidence.`\n            : "No current market line is available."}',
        "signal context",
    )

    app = replace_once(app, '        <span class="status agree">\n          ${escapeHtml(displayBetStatus(betStatus))}\n        </span>', '        <span class="status ${confidenceCss}">\n          ${escapeHtml(confidence)}\n        </span>', "banner confidence")

    app = replace_once(
        app,
        '        <div class="analysis-small">\n          ${preferred\n            ? `Market side: ${escapeHtml(modelEdgeSide)}`\n            : "No current directional signal"}\n        </div>',
        '        <div class="analysis-small">\n          ${preferred\n            ? `Market side: ${escapeHtml(modelEdgeSide)}`\n            : "No current directional signal"}\n          <br>\n          ${escapeHtml(signalRecordText(status))} · ${escapeHtml(signalAtsText(status))} ·\n          ${escapeHtml(signalClvText(status))} · ${escapeHtml(signalBeatCloseText(status))}\n        </div>',
        "matchup evidence",
    )

    old_subtitle = """      <div class="page-subtitle">
        Every FBS matchup, sorted by how far the model sits from the market.
        A game is only flagged when the disagreement clears the threshold.
      </div>
"""
    new_subtitle = """      <div class="page-subtitle">
        Every FBS matchup, sorted by model edge versus the current market.
        Model Signal measures the size of that separation. Signal Confidence
        separately measures how much prospective evidence supports each tier.
      </div>

      <details class="signal-guide">
        <summary>
          <span>How Signals Work</span>
          <span style="font-family:var(--mono);font-size:9px;color:var(--muted);font-weight:500;">
            METHODOLOGY + CONFIDENCE KEY
          </span>
        </summary>

        <div class="signal-guide-body">
          <div class="signal-guide-copy">
            <strong>Model Signal</strong> classifies the absolute difference between
            our fair line and the current market. A larger signal means the model
            and market are farther apart; it does not automatically mean the bet is
            more historically reliable. <strong>Signal Confidence</strong> is a
            separate evidence grade earned prospectively from sample size, ATS
            performance, closing-line value and beat-close rate.
          </div>

          <div class="signal-legend-grid">
            <div class="signal-legend-item"><div class="signal-legend-name" style="color:var(--muted);">ALIGNED</div><div class="signal-legend-range">0–2.5 pts</div></div>
            <div class="signal-legend-item"><div class="signal-legend-name" style="color:#355f91;">SMALL EDGE</div><div class="signal-legend-range">3.0–5.0 pts</div></div>
            <div class="signal-legend-item"><div class="signal-legend-name" style="color:var(--green);">PLAY</div><div class="signal-legend-range">5.5–7.0 pts</div></div>
            <div class="signal-legend-item"><div class="signal-legend-name" style="color:#0f5c49;">MATERIAL DISAGREEMENT</div><div class="signal-legend-range">7.5–10.0 pts</div></div>
            <div class="signal-legend-item"><div class="signal-legend-name" style="color:#9a4d00;">OUTLIER</div><div class="signal-legend-range">10.5+ pts</div></div>
          </div>

          <div class="confidence-legend">
            <span class="status confidence-developing">DEVELOPING</span>
            <span class="confidence-legend-note">Evidence accumulating.</span>
            <span class="status confidence-validated">VALIDATED</span>
            <span class="confidence-legend-note">50+ decisions · ≥52.5% ATS · positive avg CLV · ≥52.5% beat close.</span>
            <span class="status confidence-established">ESTABLISHED</span>
            <span class="confidence-legend-note">100+ decisions · ≥53.0% ATS · positive avg CLV · ≥55% beat close.</span>
          </div>
        </div>
      </details>
"""
    index = replace_once(index, old_subtitle, new_subtitle, "How Signals Work")

    APP.write_text(app, encoding="utf-8")
    INDEX.write_text(index, encoding="utf-8")

    print("=" * 72)
    print("SIGNAL SYSTEM V1 FRONTEND MIGRATION COMPLETE")
    print("=" * 72)
    print("Updated: app.js")
    print("Updated: index.html")
    print("Model / projection data: untouched")


if __name__ == "__main__":
    main()
