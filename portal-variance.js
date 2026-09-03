// ============================================================================
// THE HAMMER INDEX — PORTAL + VARIANCE LAB
// Self-contained IIFE. Reads from:
//   ./data/portal_2026.json
//   ./data/variance_historical.json
// Does NOT modify app.js or ux-v2.js globals.
// ============================================================================

(() => {
  "use strict";

  const PORTAL_URL    = "./data/portal_2026.json";
  const VARIANCE_URL  = "./data/variance_historical.json";

  let portalData    = null;
  let varianceData  = null;

  // ── Sub-tab state ───────────────────────────────────────────────────────────
  let portalSubTab    = "class";      // class | defensive | conference | juco | impact
  let varianceSubTab  = "full_reset"; // full_reset | qb_swap | coordinator
  let portalPosFilter = "ALL";
  let portalStarFilter = "ANY";
  let portalConfFilter = "ALL";
  let portalSearch    = "";

  // ── Helpers (scoped — don't conflict with app.js) ──────────────────────────
  function pEsc(v) {
    return String(v ?? "")
      .replace(/&/g,"&amp;").replace(/</g,"&lt;")
      .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#039;");
  }

  function pFmt(v, d=1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(d);
  }

  function pSign(v, d=1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    return n > 0 ? `+${n.toFixed(d)}` : n.toFixed(d);
  }

  function pPct(v, d=1) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
    return `${Number(v).toFixed(d)}%`;
  }

  function gradeClass(g) {
    if (!g) return "grade-na";
    const s = String(g).toUpperCase();
    if (s === "A") return "grade-a";
    if (s === "B") return "grade-b";
    if (s === "C") return "grade-c";
    if (s === "D") return "grade-d";
    if (s === "F") return "grade-f";
    return "grade-na";
  }

  function netClass(v) {
    if (v === null || v === undefined) return "";
    return Number(v) >= 0 ? "net-pos" : "net-neg";
  }

  function starDots(n) {
    const count = Math.min(5, Math.max(0, Number(n) || 0));
    return `<span class="stars">${"★".repeat(count)}${"☆".repeat(5-count)}</span>`;
  }

  function boomBustBadge(label) {
    const s = String(label || "").toUpperCase();
    if (s === "BOOM") return `<span class="vl-badge boom">BOOM</span>`;
    if (s === "BUST") return `<span class="vl-badge bust">BUST</span>`;
    if (s === "10W")  return `<span class="vl-badge ten-w">10W</span>`;
    return "";
  }

  // ── Styles ──────────────────────────────────────────────────────────────────
  function installPortalVarianceStyles() {
    if (document.getElementById("pv-styles")) return;
    const el = document.createElement("style");
    el.id = "pv-styles";
    el.textContent = `
      /* Sub-tab nav */
      .pv-subnav {
        display:flex; gap:4px; margin-bottom:20px;
        overflow-x:auto; padding-bottom:2px;
      }
      .pv-subtab {
        flex:0 0 auto; border:1px solid var(--border);
        background:var(--surface); color:var(--muted);
        border-radius:999px; padding:7px 14px;
        font-size:11px; font-weight:600; cursor:pointer;
      }
      .pv-subtab.active {
        background:var(--text); border-color:var(--text); color:#fff;
      }

      .vl-coming-soon {
        min-height:190px;
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        gap:8px;
        border:1px solid var(--border);
        border-radius:12px;
        background:var(--surface);
        text-align:center;
      }
      .vl-coming-soon-title {
        color:var(--text);
        font-size:20px;
        font-weight:750;
        letter-spacing:-.25px;
      }
      .vl-coming-soon-mark {
        font-size:20px;
        line-height:1;
      }

      /* Section header */
      .pv-section-header {
        margin-bottom:18px;
      }
      .pv-section-title {
        font-size:26px; font-weight:800; letter-spacing:-.6px;
      }
      .pv-section-sub {
        color:var(--muted); font-size:12px; margin-top:6px; line-height:1.55;
      }

      /* Filter bar */
      .pv-filters {
        display:flex; gap:8px; flex-wrap:wrap;
        align-items:flex-end; margin-bottom:16px;
      }
      .pv-filter {
        display:flex; flex-direction:column; gap:4px;
      }
      .pv-filter-label {
        font-family:var(--mono); font-size:8px; font-weight:700;
        letter-spacing:.9px; text-transform:uppercase; color:var(--muted);
      }
      .pv-filter input,
      .pv-filter select {
        min-height:36px; border:1px solid var(--border);
        background:var(--surface); color:var(--text);
        border-radius:8px; font-size:11px; font-weight:600;
        padding:0 11px; outline:none; min-width:120px;
      }
      .pv-filter input:focus,
      .pv-filter select:focus { border-color:#aeb5b0; }
      .pv-pos-group {
        display:flex; gap:4px; flex-wrap:wrap;
      }
      .pv-pos-btn {
        border:1px solid var(--border); background:var(--surface);
        color:var(--muted); border-radius:6px; padding:5px 10px;
        font-size:11px; font-weight:600; cursor:pointer;
      }
      .pv-pos-btn.active {
        background:var(--text); border-color:var(--text); color:#fff;
      }

      /* Summary cards */
      .pv-summary-grid {
        display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
        gap:10px; margin-bottom:20px;
      }
      .pv-card {
        background:var(--surface); border:1px solid var(--border);
        border-radius:12px; padding:16px;
      }
      .pv-card-label {
        font-family:var(--mono); color:var(--muted);
        font-size:9px; letter-spacing:1px; text-transform:uppercase;
      }
      .pv-card-value {
        font-size:22px; font-weight:800; letter-spacing:-.5px; margin-top:8px;
      }
      .pv-card-sub { color:var(--muted); font-size:11px; margin-top:4px; }

      /* Winners/losers split */
      .pv-split { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:20px; }
      .pv-split-card {
        background:var(--surface); border:1px solid var(--border);
        border-radius:12px; padding:14px;
      }
      .pv-split-title {
        font-family:var(--mono); font-size:9px; letter-spacing:1px;
        text-transform:uppercase; color:var(--muted); margin-bottom:10px;
      }
      .pv-split-row {
        display:grid; grid-template-columns:auto 1fr auto;
        gap:10px; align-items:center; padding:7px 0;
        border-bottom:1px solid #eeeeeb;
      }
      .pv-split-row:last-child { border-bottom:none; }
      .pv-split-rank {
        font-family:var(--mono); font-size:10px; color:var(--muted);
      }
      .pv-split-team { font-size:12px; font-weight:700; }
      .pv-split-val {
        font-family:var(--mono); font-size:12px; font-weight:700;
      }

      /* Net classes */
      .net-pos { color:var(--green); }
      .net-neg { color:var(--red); }

      /* Main table */
      .pv-table-wrap { overflow-x:auto; }
      .pv-table {
        width:100%; border-collapse:collapse;
        font-size:12px; min-width:700px;
      }
      .pv-table thead { background:#f7f7f5; border-bottom:1px solid var(--border); }
      .pv-table th {
        padding:10px 14px; text-align:left; color:var(--muted);
        font-size:9px; font-weight:700; letter-spacing:1px;
        text-transform:uppercase; white-space:nowrap;
      }
      .pv-table th.r { text-align:right; }
      .pv-table td { padding:11px 14px; border-bottom:1px solid #eeeeeb; }
      .pv-table tbody tr:hover { background:#fafaf8; }
      .pv-table tbody tr:last-child td { border-bottom:none; }
      .pv-team-name { font-weight:700; }
      .pv-conf { color:var(--muted); font-size:10px; }

      /* Grades */
      .grade-badge {
        display:inline-flex; align-items:center; justify-content:center;
        width:26px; height:26px; border-radius:6px;
        font-family:var(--mono); font-size:11px; font-weight:800;
      }
      .grade-a { background:#dff3e5; color:#146b32; border:1px solid #9fd1ad; }
      .grade-b { background:#e8f3ef; color:#176b55; border:1px solid #a8d4c7; }
      .grade-c { background:#f8e7a1; color:#4e3b00; border:1px solid #d9bd53; }
      .grade-d { background:#fff0df; color:#9a4d00; border:1px solid #e6b77d; }
      .grade-f { background:#fde5e2; color:#a22b20; border:1px solid #e9aaa4; }
      .grade-na { background:#f4f4f2; color:var(--muted); border:1px solid var(--border); }

      /* Stars */
      .stars { color:#c77700; font-size:10px; letter-spacing:1px; }

      /* Tags */
      .pv-tag {
        display:inline-flex; align-items:center;
        border-radius:999px; padding:3px 8px;
        font-family:var(--mono); font-size:9px; font-weight:700;
        letter-spacing:.3px; white-space:nowrap;
      }
      .tag-upgrade { background:#dff3e5; color:#146b32; border:1px solid #9fd1ad; }
      .tag-downgrade { background:#fde5e2; color:#a22b20; border:1px solid #e9aaa4; }
      .tag-neutral { background:#f4f4f2; color:var(--muted); border:1px solid var(--border); }

      /* Variance Lab */
      .vl-cohort-header {
        background:var(--surface); border:1px solid var(--border);
        border-radius:12px; padding:20px; margin-bottom:16px;
      }
      .vl-cohort-label {
        font-family:var(--mono); color:var(--green);
        font-size:9px; letter-spacing:1.2px; text-transform:uppercase;
        margin-bottom:6px;
      }
      .vl-cohort-title {
        font-size:18px; font-weight:800; letter-spacing:-.3px; margin-bottom:4px;
      }
      .vl-cohort-sub { color:var(--muted); font-size:11px; }

      .vl-stats-bar {
        display:grid;
        grid-template-columns:repeat(7,minmax(0,1fr));
        gap:8px; margin:16px 0;
      }
      .vl-stat {
        background:var(--surface); border:1px solid var(--border);
        border-radius:10px; padding:12px 10px;
      }
      .vl-stat-label {
        font-family:var(--mono); color:var(--muted);
        font-size:8px; letter-spacing:.8px; text-transform:uppercase;
      }
      .vl-stat-value {
        font-size:18px; font-weight:800; margin-top:6px; letter-spacing:-.3px;
      }
      .vl-stat-value.boom { color:var(--green); }
      .vl-stat-value.bust { color:var(--red); }

      /* Distribution bars */
      .vl-distribution { margin:16px 0; }
      .vl-dist-row {
        display:grid; grid-template-columns:90px minmax(0,1fr) 80px;
        gap:10px; align-items:center; margin-bottom:9px;
      }
      .vl-dist-label { font-family:var(--mono); font-size:10px; color:var(--muted); }
      .vl-dist-track {
        height:9px; border-radius:999px; background:#ecece8; overflow:hidden;
      }
      .vl-dist-fill { height:100%; border-radius:999px; }
      .vl-dist-fill.pos { background:var(--green); }
      .vl-dist-fill.neg { background:var(--red); }
      .vl-dist-fill.neu { background:#ccc; }
      .vl-dist-meta {
        font-family:var(--mono); font-size:10px; color:var(--muted); text-align:right;
      }

      /* QB split cards */
      .vl-qb-split {
        display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:16px 0;
      }
      .vl-qb-card {
        background:#fafaf8; border:1px solid var(--border);
        border-radius:10px; padding:14px;
      }
      .vl-qb-type {
        font-family:var(--mono); font-size:9px; font-weight:800;
        letter-spacing:1px; text-transform:uppercase; margin-bottom:4px;
      }
      .vl-qb-def { font-size:10px; color:var(--muted); margin-bottom:10px; }
      .vl-qb-stat {
        display:flex; justify-content:space-between;
        font-family:var(--mono); font-size:10px; padding:4px 0;
        border-bottom:1px solid #eeeeeb;
      }
      .vl-qb-stat:last-child { border-bottom:none; }
      .vl-qb-stat span:first-child { color:var(--muted); }

      /* Analysis copy */
      .vl-analysis {
        background:var(--surface); border:1px solid var(--border);
        border-radius:10px; padding:16px; margin:16px 0;
        font-size:12px; line-height:1.7; color:var(--text);
      }

      /* 2026 qualifying teams */
      .vl-teams-grid {
        display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
        gap:10px; margin:16px 0;
      }
      .vl-team-card {
        background:var(--surface); border:1px solid var(--border);
        border-radius:10px; padding:14px;
      }
      .vl-team-name { font-size:14px; font-weight:800; }
      .vl-team-conf { color:var(--muted); font-size:10px; margin-bottom:8px; }
      .vl-team-proj {
        font-family:var(--mono); font-size:11px; color:var(--muted); margin-bottom:3px;
      }
      .vl-team-detail { font-size:11px; color:var(--muted); }

      /* Biggest swings table */
      .vl-swings-title {
        font-family:var(--mono); font-size:9px; font-weight:700;
        letter-spacing:1px; text-transform:uppercase; color:var(--muted);
        margin:20px 0 10px;
      }

      /* Badges */
      .vl-badge {
        display:inline-flex; align-items:center; justify-content:center;
        border-radius:4px; padding:2px 7px;
        font-family:var(--mono); font-size:9px; font-weight:800;
        letter-spacing:.4px; margin-right:3px;
      }
      .vl-badge.boom { background:#dff3e5; color:#146b32; border:1px solid #9fd1ad; }
      .vl-badge.bust { background:#fde5e2; color:#a22b20; border:1px solid #e9aaa4; }
      .vl-badge.ten-w { background:#18212b; color:#fff; }

      /* Cross-cohort comparison */
      .vl-compare-grid {
        display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
        gap:12px; margin:16px 0;
      }
      .vl-compare-card {
        background:var(--surface); border:1px solid var(--border);
        border-radius:12px; overflow:hidden;
      }
      .vl-compare-header {
        padding:12px 14px; border-bottom:1px solid var(--border);
        background:#f7f7f5;
        font-family:var(--mono); font-size:9px; font-weight:700;
        letter-spacing:1px; text-transform:uppercase; color:var(--muted);
      }
      .vl-compare-body { padding:12px 14px; }
      .vl-compare-row {
        display:flex; justify-content:space-between;
        font-size:11px; padding:5px 0;
        border-bottom:1px solid #eeeeeb;
      }
      .vl-compare-row:last-child { border-bottom:none; }
      .vl-compare-row span:first-child { color:var(--muted); }
      .vl-compare-row span:last-child { font-family:var(--mono); font-weight:700; }

      /* JUCO status */
      .juco-status {
        display:inline-flex; border-radius:999px;
        padding:3px 9px; font-family:var(--mono);
        font-size:9px; font-weight:700;
        background:#dff3e5; color:#146b32; border:1px solid #9fd1ad;
      }

      /* Responsive */
      @media(max-width:900px){
        .pv-summary-grid { grid-template-columns:1fr 1fr; }
        .pv-split { grid-template-columns:1fr; }
        .vl-stats-bar { grid-template-columns:repeat(3,1fr); }
        .vl-qb-split { grid-template-columns:1fr; }
        .vl-teams-grid { grid-template-columns:1fr 1fr; }
        .vl-compare-grid { grid-template-columns:1fr; }
      }
      @media(max-width:600px){
        .pv-summary-grid { grid-template-columns:1fr; }
        .vl-stats-bar { grid-template-columns:1fr 1fr; }
        .vl-teams-grid { grid-template-columns:1fr; }
      }
    `;
    document.head.appendChild(el);
  }

  // ── TRANSFER PORTAL ─────────────────────────────────────────────────────────

  function renderPortalSubNav() {
    const tabs = [
      ["class","Class Rankings"],
      ["defensive","Def. Portal"],
      ["conference","Conf. Summary"],
      ["juco","JUCO"],
      ["impact","Impact"],
    ];
    return `<div class="pv-subnav">
      ${tabs.map(([id,label])=>`
        <button class="pv-subtab ${portalSubTab===id?"active":""}"
          onclick="pvPortalTab('${id}')">${pEsc(label)}</button>
      `).join("")}
    </div>`;
  }

  function renderPortalClassRankings() {
    const teams = portalData?.teams ?? [];
    const positions = ["ALL","QB","RB","WR","TE","OL","DL","LB","DB"];
    const conferences = ["ALL",...new Set(teams.map(t=>t.conference||"").filter(Boolean)).values()].sort();

    // Filter
    let filtered = teams.filter(t => {
      if (portalSearch && !t.team?.toLowerCase().includes(portalSearch.toLowerCase())) return false;
      if (portalConfFilter !== "ALL" && t.conference !== portalConfFilter) return false;
      return true;
    });

    // Top/bottom overall grade for summary
    const sorted = [...filtered].sort((a,b)=>(b.avg_ptr||0)-(a.avg_ptr||0));

    const rows = sorted.map(t => {
      const net = (t.in_count||0) - (t.out_count||0);
      const netStr = net > 0 ? `+${net}` : String(net);
      const tagLabel = t.portal_grade_tag || "";
      const tagCss = tagLabel.includes("Upgrade") ? "tag-upgrade" : tagLabel.includes("Downgrade") ? "tag-downgrade" : "tag-neutral";
      return `<tr>
        <td><div class="pv-team-name">${pEsc(t.team)}</div><div class="pv-conf">${pEsc(t.conference||"")}</div></td>
        <td>${t.in_count??0}</td>
        <td>${t.out_count??0}</td>
        <td class="${netClass(net)} r">${netStr}</td>
        <td class="r" style="font-weight:700">${pFmt(t.avg_ptr,1)}</td>
        <td class="r" style="color:var(--muted)">${pFmt(t.top_ptr,1)}</td>
        <td class="r"><span class="grade-badge ${gradeClass(t.portal_grade)}">${pEsc(t.portal_grade||"—")}</span></td>
      </tr>`;
    }).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">2026 Transfer Portal — Class Rankings</div>
        <div class="pv-section-sub">Team portal classes ranked by average PTR. PTR = Predictive Transfer Rating derived from recruiting rank, position leverage, and prior production. ${filtered.length} of ${teams.length} FBS teams shown.</div>
      </div>
      <div class="pv-filters">
        <div class="pv-filter">
          <div class="pv-filter-label">Search</div>
          <input type="search" placeholder="Search team..." value="${pEsc(portalSearch)}"
            oninput="pvPortalSearch(this.value)">
        </div>
        <div class="pv-filter">
          <div class="pv-filter-label">Conference</div>
          <select onchange="pvPortalConf(this.value)">
            ${conferences.map(c=>`<option value="${pEsc(c)}" ${portalConfFilter===c?"selected":""}>${pEsc(c==="ALL"?"All Conferences":c)}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="pv-table-wrap">
        <table class="pv-table">
          <thead><tr>
            <th>Team</th><th>IN</th><th>OUT</th>
            <th class="r">NET ★</th><th class="r">AVG PTR</th>
            <th class="r">TOP PTR</th><th class="r">GRADE</th>
          </tr></thead>
          <tbody>${rows||`<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">No teams match.</td></tr>`}</tbody>
        </table>
      </div>`;
  }

  function renderPortalDefensive() {
    const teams = portalData?.teams ?? [];
    const sorted = [...teams].sort((a,b)=>(b.def_net_ptr||0)-(a.def_net_ptr||0));
    const winners = sorted.slice(0,5);
    const losers  = [...teams].sort((a,b)=>(a.def_net_ptr||0)-(b.def_net_ptr||0)).slice(0,5);

    const splitRow = (t,i,isWinner) => `
      <div class="pv-split-row">
        <span class="pv-split-rank">${i+1}</span>
        <div>
          <div class="pv-split-team">${pEsc(t.team)}</div>
          <div class="pv-conf">${pEsc(t.conference||"")}</div>
        </div>
        <span class="pv-split-val ${isWinner?"net-pos":"net-neg"}">
          ${isWinner?"+":""}${pFmt(t.def_net_ptr,1)}
        </span>
      </div>`;

    const rows = sorted.map(t => {
      const tagLabel = t.def_tag || "";
      const tagCss = tagLabel.includes("Major") ? "tag-upgrade" : tagLabel.includes("Loss") ? "tag-downgrade" : "tag-neutral";
      return `<tr>
        <td><div class="pv-team-name">${pEsc(t.team)}</div><div class="pv-conf">${pEsc(t.conference||"")}</div></td>
        <td class="${netClass(t.dl_net)}">${pSign(t.dl_net,1)}</td>
        <td class="${netClass(t.lb_net)}">${pSign(t.lb_net,1)}</td>
        <td class="${netClass(t.db_net)}">${pSign(t.db_net,1)}</td>
        <td class="${netClass(t.def_net_ptr)} r" style="font-weight:700">${pSign(t.def_net_ptr,1)}</td>
        <td><span class="pv-tag ${tagCss}">${pEsc(tagLabel||"—")}</span></td>
      </tr>`;
    }).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">Defensive Portal Impact</div>
        <div class="pv-section-sub">PTR weighted by projected role and positional leverage. DL = defensive line, LB = linebackers, DB = defensive backs.</div>
      </div>
      <div class="pv-split">
        <div class="pv-split-card">
          <div class="pv-split-title">Biggest Winners</div>
          ${winners.map((t,i)=>splitRow(t,i,true)).join("")}
        </div>
        <div class="pv-split-card">
          <div class="pv-split-title">Biggest Losers</div>
          ${losers.map((t,i)=>splitRow(t,i,false)).join("")}
        </div>
      </div>
      <div class="pv-table-wrap">
        <table class="pv-table">
          <thead><tr>
            <th>Team</th><th>DL NET</th><th>LB NET</th>
            <th>DB NET</th><th class="r">OVERALL</th><th>TAG</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderPortalConference() {
    const conferences = portalData?.conference_summary ?? [];
    const confNames = conferences.map(c=>c.conference).filter(Boolean);
    const active = confNames[0] || "";

    const conf = conferences.find(c=>c.conference === (portalConfFilter !== "ALL" ? portalConfFilter : active));
    const teams = conf?.teams ?? [];

    const confTabs = confNames.map(name => `
      <button class="pv-subtab ${(portalConfFilter!=="ALL"?portalConfFilter:active)===name?"active":""}"
        style="font-size:10px;padding:5px 10px;"
        onclick="pvPortalConf('${pEsc(name)}')">${pEsc(name)}</button>
    `).join("");

    if (!conf) {
      return `<div class="pv-section-header">
        <div class="pv-section-title">Conference Summary</div>
        <div class="empty-state" style="padding:60px 20px;">No conference data available yet.</div>
      </div>`;
    }

    const teamCards = teams.map(t => `
      <div class="pv-card">
        <div style="font-weight:800;font-size:14px;margin-bottom:2px">${pEsc(t.team)}</div>
        <div class="pv-conf" style="margin-bottom:8px">${pEsc(t.grade_label||"")}</div>
        <div style="font-size:11px;color:var(--muted)">IN: ${t.in_count||0} · OUT: ${t.out_count||0}</div>
        ${t.qb_note?`<div style="font-size:11px;margin-top:5px;color:var(--muted)">${pEsc(t.qb_note)}</div>`:""}
        ${t.top_arrival?`<div style="font-size:11px;margin-top:5px"><strong>▲</strong> ${pEsc(t.top_arrival)}</div>`:""}
        ${t.top_departure?`<div style="font-size:11px"><strong>▼</strong> ${pEsc(t.top_departure)}</div>`:""}
      </div>
    `).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">Conference Portal Summary</div>
        <div class="pv-section-sub">Portal verdict by conference. Click a conference to view its teams.</div>
      </div>
      <div class="pv-subnav" style="margin-bottom:14px">${confTabs}</div>
      ${conf.verdict?`<div class="vl-analysis"><strong>${pEsc(conf.conference)} — Portal Verdict:</strong> ${pEsc(conf.verdict)}</div>`:""}
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px">
        ${teamCards || `<div class="empty-state" style="padding:40px">No team data for this conference yet.</div>`}
      </div>`;
  }

  function renderPortalJuco() {
    const players = portalData?.juco ?? [];
    const onRoster = players.filter(p=>p.status === "On roster");
    const allSignees = players;

    const active = ["on_roster","all","everyone"].includes(portalSearch) ? portalSearch : "on_roster";

    const list = portalSearch === "all" ? allSignees : onRoster;

    const rows = list.map((p,i) => `
      <tr>
        <td><strong>#${i+1}</strong> <span style="font-size:9px;background:#ecece8;padding:2px 5px;border-radius:3px;margin-left:4px;font-family:var(--mono)">JC</span></td>
        <td><div style="font-weight:700">${pEsc(p.player)}</div><div class="pv-conf">${pEsc(p.hometown||"")}</div></td>
        <td>${pEsc(p.position||"—")}</td>
        <td>${pEsc(p.juco_school||"—")}</td>
        <td>${pEsc(p.signed_with||"—")}</td>
        <td><span class="juco-status">${pEsc(p.status||"—")}</span></td>
        <td>${starDots(p.stars)}</td>
        <td class="r">${pFmt(p.rating,4)}</td>
        <td class="r" style="font-weight:700">${pFmt(p.talent,1)}</td>
      </tr>`).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">JUCO Signees</div>
        <div class="pv-section-sub">Junior college transfers signing with FBS programs. Sorted by talent score.</div>
      </div>
      <div class="pv-filters" style="margin-bottom:12px">
        <button class="pv-subtab ${portalSearch!=="all"?"active":""}" onclick="pvPortalSearch('on_roster')">On 2026 Roster (${onRoster.length})</button>
        <button class="pv-subtab ${portalSearch==="all"?"active":""}" onclick="pvPortalSearch('all')">All FBS Signees (${allSignees.length})</button>
      </div>
      <div class="pv-table-wrap">
        <table class="pv-table">
          <thead><tr>
            <th>Rank</th><th>Player</th><th>Pos</th><th>JUCO School</th>
            <th>Signed With</th><th>Status</th><th>Stars</th><th class="r">Rating</th><th class="r">Talent</th>
          </tr></thead>
          <tbody>${rows||`<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--muted)">No JUCO data available yet.</td></tr>`}</tbody>
        </table>
      </div>`;
  }

  function renderPortalImpact() {
    const teams = portalData?.teams ?? [];
    const sorted = [...teams].sort((a,b)=>(b.wins_impact||0)-(a.wins_impact||0));
    const best  = sorted[0];
    const worst = sorted[sorted.length-1];

    const rows = sorted.map((t,i) => `
      <tr>
        <td style="color:var(--muted);font-family:var(--mono);font-size:10px">${i+1}</td>
        <td><div class="pv-team-name">${pEsc(t.team)}</div><div class="pv-conf">${pEsc(t.conference||"")}</div></td>
        <td style="color:var(--muted)">${t.in_count||0} / ${t.out_count||0}</td>
        <td class="${netClass(t.rating_delta)}">${pSign(t.rating_delta,2)}</td>
        <td>${pSign(t.pts_per_game_impact,1)}</td>
        <td class="${netClass(t.wins_impact)}" style="font-weight:700">${pSign(t.wins_impact,2)}w</td>
        <td style="font-size:11px;color:var(--muted);max-width:180px">${pEsc(t.top_addition||"—")}</td>
        <td style="font-size:11px;color:var(--muted);max-width:180px">${pEsc(t.top_departure||"—")}</td>
      </tr>`).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">Portal Impact on 2026 Projections</div>
        <div class="pv-section-sub">Net PTR flow → rating delta → schedule re-run. Wins impact = projected 2026 wins with the class minus without it.</div>
      </div>
      <div class="pv-split" style="margin-bottom:20px">
        <div class="pv-split-card">
          <div class="pv-split-title">Biggest Portal Winner</div>
          <div style="font-size:20px;font-weight:800;margin:8px 0 2px">${pEsc(best?.team||"—")}</div>
          <div class="net-pos" style="font-size:14px;font-weight:700">${pSign(best?.wins_impact,2)} projected wins</div>
        </div>
        <div class="pv-split-card">
          <div class="pv-split-title">Biggest Portal Loser</div>
          <div style="font-size:20px;font-weight:800;margin:8px 0 2px">${pEsc(worst?.team||"—")}</div>
          <div class="net-neg" style="font-size:14px;font-weight:700">${pSign(worst?.wins_impact,2)} projected wins</div>
        </div>
      </div>
      <div class="pv-table-wrap">
        <table class="pv-table">
          <thead><tr>
            <th>#</th><th>Team</th><th>IN/OUT</th><th>Rating Δ</th>
            <th>PTS/Game</th><th>Wins Impact</th><th>Top Addition</th><th>Top Departure</th>
          </tr></thead>
          <tbody>${rows||`<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--muted)">Impact data not yet available.</td></tr>`}</tbody>
        </table>
      </div>`;
  }

  function renderPortal() {
    const container = document.getElementById("portal-content");
    if (!container) return;

    if (!portalData) {
      container.innerHTML = `
        <div class="empty-state" style="padding:80px 20px">
          <div class="spinner"></div>
          <div style="margin-top:14px">Loading Transfer Portal data...</div>
        </div>`;
      return;
    }

    let body = "";
    if (portalSubTab === "class")       body = renderPortalClassRankings();
    else if (portalSubTab === "defensive") body = renderPortalDefensive();
    else if (portalSubTab === "conference") body = renderPortalConference();
    else if (portalSubTab === "juco")    body = renderPortalJuco();
    else if (portalSubTab === "impact")  body = renderPortalImpact();

    container.innerHTML = renderPortalSubNav() + body;
  }

  // ── VARIANCE LAB ────────────────────────────────────────────────────────────

  function renderVarianceSubNav() {
    const tabs = [
      ["full_reset","Full Reset"],
      ["qb_swap","QB-Only Swap"],
      ["coordinator","Coordinator Change"],
      ["compare","Cross-Cohort"],
    ];
    return `<div class="pv-subnav">
      ${tabs.map(([id,label])=>`
        <button class="pv-subtab ${varianceSubTab===id?"active":""}"
          onclick="pvVarianceTab('${id}')">${pEsc(label)}</button>
      `).join("")}
    </div>`;
  }

  function renderCohort(cohortKey, label, description) {
    const cohort = varianceData?.cohorts?.[cohortKey];
    if (!cohort) return `<div class="empty-state" style="padding:60px 20px">No data for this cohort yet.</div>`;

    const stats = cohort.aggregate || {};
    const distribution = cohort.distribution || [];
    const qb_split = cohort.qb_split || {};
    const analysis = cohort.analysis || "";
    const qualifying = cohort.qualifying_2026 || [];
    const swings = cohort.biggest_swings || [];

    const maxBucket = Math.max(...distribution.map(d=>d.count||0), 1);

    const distRows = distribution.map(d => {
      const pct = ((d.count||0) / maxBucket) * 100;
      const isPos = String(d.bucket||"").includes("+") || String(d.bucket||"").startsWith("0");
      const isNeg = String(d.bucket||"").startsWith("-");
      const fillClass = isPos ? "pos" : isNeg ? "neg" : "neu";
      return `<div class="vl-dist-row">
        <div class="vl-dist-label">${pEsc(d.bucket)}</div>
        <div class="vl-dist-track"><div class="vl-dist-fill ${fillClass}" style="width:${pct}%"></div></div>
        <div class="vl-dist-meta">${d.count||0} · ${pPct(d.pct)}</div>
      </div>`;
    }).join("");

    const expTransfer = qb_split.experienced_transfer || {};
    const firstYear   = qb_split.first_year_starter   || {};

    const qualifyingCards = qualifying.map(t => `
      <div class="vl-team-card">
        <div class="vl-team-name">${pEsc(t.team)}</div>
        <div class="vl-team-conf">${pEsc(t.conference||"")} · ${pFmt(t.projected_wins,1)} proj W</div>
        ${t.hc_note?`<div class="vl-team-proj">HC: ${pEsc(t.hc_note)}</div>`:""}
        ${t.qb_note?`<div class="vl-team-detail">QB: ${pEsc(t.qb_note)}</div>`:""}
        ${t.oc_note?`<div class="vl-team-detail">OC: ${pEsc(t.oc_note)}</div>`:""}
      </div>`).join("");

    const swingRows = swings.map(s => `
      <tr>
        <td style="color:var(--muted);font-family:var(--mono);font-size:10px">${pEsc(s.season)}</td>
        <td><div class="pv-team-name">${pEsc(s.team)}</div><div class="pv-conf">${pEsc(s.conference||"")}</div></td>
        <td style="color:var(--muted)">${pEsc(s.head_coach||"—")}</td>
        <td>${pEsc(s.new_qb||s.new_oc||"—")} <span style="font-size:9px;color:var(--muted)">${pEsc(s.qb_type||s.change_type||"")}</span></td>
        <td style="color:var(--muted);font-family:var(--mono)">${s.prev_wins??""}</td>
        <td style="font-family:var(--mono);font-weight:700">${s.wins??""}</td>
        <td class="${netClass(s.delta)}" style="font-family:var(--mono);font-weight:700">${pSign(s.delta,0)}</td>
        <td>${boomBustBadge(s.result_boom_bust)} ${s.result_ap?`<span class="vl-badge ten-w">AP #${s.result_ap}</span>`:""}</td>
        <td style="color:var(--muted);font-size:11px;max-width:250px">${pEsc(s.what_happened||"")}</td>
      </tr>`).join("");

    return `
      <div class="vl-cohort-header">
        <div class="vl-cohort-label">${pEsc(label)}</div>
        <div class="vl-cohort-title">${pEsc(description)}</div>
        <div class="vl-cohort-sub">N=${stats.n||0} team-seasons since 2013</div>
      </div>

      <div class="vl-stats-bar">
        <div class="vl-stat"><div class="vl-stat-label">Avg Win Change</div><div class="vl-stat-value">${pSign(stats.avg_win_change,1)}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Std Dev</div><div class="vl-stat-value">±${pFmt(stats.std_dev,1)}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Best / Worst</div><div class="vl-stat-value">${stats.best_swing??""} / ${stats.worst_swing??""}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Boom Rate (3+w)</div><div class="vl-stat-value boom">${pPct(stats.boom_rate)}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Bust Rate (−3+w)</div><div class="vl-stat-value bust">${pPct(stats.bust_rate)}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Won 10+ Games</div><div class="vl-stat-value">${pPct(stats.won_10_plus)}</div></div>
        <div class="vl-stat"><div class="vl-stat-label">Finished AP 25</div><div class="vl-stat-value">${pPct(stats.finished_ap_25)}</div></div>
      </div>

      <div class="vl-distribution">${distRows}</div>

      ${qb_split.experienced_transfer||qb_split.first_year_starter ? `
      <div class="vl-qb-split">
        <div class="vl-qb-card">
          <div class="vl-qb-type">Experienced Transfer N=${expTransfer.n||0}</div>
          <div class="vl-qb-def">150+ attempts at prior school the year before</div>
          <div class="vl-qb-stat"><span>Avg Δ Wins</span><span class="${netClass(expTransfer.avg_delta)}">${pSign(expTransfer.avg_delta,1)}</span></div>
          <div class="vl-qb-stat"><span>Boom rate</span><span>${pPct(expTransfer.boom_rate)}</span></div>
          <div class="vl-qb-stat"><span>Bust rate</span><span>${pPct(expTransfer.bust_rate)}</span></div>
          <div class="vl-qb-stat"><span>Won 10+ games</span><span>${pPct(expTransfer.won_10_plus)}</span></div>
        </div>
        <div class="vl-qb-card">
          <div class="vl-qb-type">First-Year Starter N=${firstYear.n||0}</div>
          <div class="vl-qb-def">True freshman, redshirt, or promoted backup</div>
          <div class="vl-qb-stat"><span>Avg Δ Wins</span><span class="${netClass(firstYear.avg_delta)}">${pSign(firstYear.avg_delta,1)}</span></div>
          <div class="vl-qb-stat"><span>Boom rate</span><span>${pPct(firstYear.boom_rate)}</span></div>
          <div class="vl-qb-stat"><span>Bust rate</span><span>${pPct(firstYear.bust_rate)}</span></div>
          <div class="vl-qb-stat"><span>Won 10+ games</span><span>${pPct(firstYear.won_10_plus)}</span></div>
        </div>
      </div>` : ""}

      ${analysis ? `<div class="vl-analysis">${pEsc(analysis)}</div>` : ""}

      ${qualifying.length ? `
        <div class="vl-swings-title">2026 ${label} Teams · ${qualifying.length}</div>
        <div class="vl-teams-grid">${qualifyingCards}</div>` : ""}

      ${swings.length ? `
        <div class="vl-swings-title">Biggest Swings in the Cohort</div>
        <div class="pv-table-wrap">
          <table class="pv-table">
            <thead><tr>
              <th>Season</th><th>Team</th><th>Head Coach</th><th>New QB / Change</th>
              <th>Prev W</th><th>W</th><th>Δ</th><th>Result</th><th>What Happened</th>
            </tr></thead>
            <tbody>${swingRows}</tbody>
          </table>
        </div>` : ""}`;
  }

  function renderVarianceCrossComparison() {
    const cohorts = varianceData?.cohorts ?? {};
    const keys = [
      ["full_reset","Full Reset","New HC + New OC + New QB"],
      ["qb_swap","QB-Only Swap","Same HC + Same OC + New QB"],
      ["coordinator","Coordinator Change","New OC + Same HC + Same QB"],
    ];

    const cards = keys.map(([key,label,desc]) => {
      const s = cohorts[key]?.aggregate ?? {};
      return `<div class="vl-compare-card">
        <div class="vl-compare-header">${pEsc(label)}</div>
        <div class="vl-compare-body">
          <div style="font-size:10px;color:var(--muted);margin-bottom:10px">${pEsc(desc)} · N=${s.n||0}</div>
          <div class="vl-compare-row"><span>Avg win change</span><span class="${netClass(s.avg_win_change)}">${pSign(s.avg_win_change,1)}</span></div>
          <div class="vl-compare-row"><span>Std deviation</span><span>±${pFmt(s.std_dev,1)}</span></div>
          <div class="vl-compare-row"><span>Boom rate</span><span class="net-pos">${pPct(s.boom_rate)}</span></div>
          <div class="vl-compare-row"><span>Bust rate</span><span class="net-neg">${pPct(s.bust_rate)}</span></div>
          <div class="vl-compare-row"><span>Won 10+ games</span><span>${pPct(s.won_10_plus)}</span></div>
          <div class="vl-compare-row"><span>Finished AP 25</span><span>${pPct(s.finished_ap_25)}</span></div>
          <div class="vl-compare-row"><span>Best swing</span><span class="net-pos">${s.best_swing??""}</span></div>
          <div class="vl-compare-row"><span>Worst swing</span><span class="net-neg">${s.worst_swing??""}</span></div>
        </div>
      </div>`;
    }).join("");

    return `
      <div class="pv-section-header">
        <div class="pv-section-title">Cross-Cohort Comparison</div>
        <div class="pv-section-sub">Side-by-side aggregate stats across all three change cohorts. Full Reset carries the most variance; Coordinator Change shows the least.</div>
      </div>
      <div class="vl-compare-grid">${cards}</div>`;
  }

  function renderVariance() {
    const container = document.getElementById("variance-content");
    if (!container) return;

    if (!varianceData) {
      container.innerHTML = `
        <div class="empty-state" style="padding:80px 20px">
          <div class="spinner"></div>
          <div style="margin-top:14px">Loading Variance Lab data...</div>
        </div>`;
      return;
    }

    const hasPublishedVariance = ["full_reset", "qb_swap", "coordinator"]
      .some(key => Number(varianceData?.cohorts?.[key]?.aggregate?.n || 0) > 0);

    if (!hasPublishedVariance) {
      container.innerHTML = `
        <div class="vl-coming-soon">
          <div class="vl-coming-soon-title">Coming Soon.</div>
          <div class="vl-coming-soon-mark" aria-hidden="true">🔨</div>
        </div>`;
      return;
    }

    let body = "";
    if (varianceSubTab === "full_reset")
      body = renderCohort("full_reset","Full Reset Cohort","New head coach + new offensive coordinator + new starting quarterback");
    else if (varianceSubTab === "qb_swap")
      body = renderCohort("qb_swap","QB-Only Swap","New quarterback, staff intact: same head coach, same offensive coordinator");
    else if (varianceSubTab === "coordinator")
      body = renderCohort("coordinator","Coordinator Change","New offensive coordinator, same head coach, same starting quarterback");
    else if (varianceSubTab === "compare")
      body = renderVarianceCrossComparison();

    container.innerHTML = renderVarianceSubNav() + body;
  }

  // ── Public controls (called by onclick) ─────────────────────────────────────
  window.pvPortalTab = function(tab) {
    portalSubTab = tab;
    portalSearch = "";
    renderPortal();
  };
  window.pvPortalSearch = function(val) {
    portalSearch = val;
    renderPortal();
  };
  window.pvPortalConf = function(val) {
    portalConfFilter = val;
    renderPortal();
  };
  window.pvPortalPos = function(val) {
    portalPosFilter = val;
    renderPortal();
  };
  window.pvVarianceTab = function(tab) {
    varianceSubTab = tab;
    renderVariance();
  };

  // ── Inject content containers into existing stubs ───────────────────────────
  function installContainers() {
    const portalSection = document.getElementById("view-portal");
    if (portalSection && !document.getElementById("portal-content")) {
      portalSection.innerHTML = `
        <div class="eyebrow">Roster movement</div>
        <h1 class="page-title">Transfer Portal</h1>
        <div class="page-subtitle" style="margin-bottom:24px">
          Arrivals, departures, net roster impact and projected unit strength for every FBS program.
        </div>
        <div id="portal-content">
          <div class="loading-state"><div class="spinner"></div>Loading portal data...</div>
        </div>`;
    }

    const varianceSection = document.getElementById("view-variance");
    if (varianceSection && !document.getElementById("variance-content")) {
      varianceSection.innerHTML = `
        <div class="eyebrow">Historical distributions</div>
        <h1 class="page-title">Variance Lab</h1>
        <div class="page-subtitle" style="margin-bottom:24px">
          Historical base rates for coaching changes, quarterback transitions,
          coordinator turnover and full program resets. Coming soon 🔨.
        </div>
        <div id="variance-content">
          <div class="loading-state"><div class="spinner"></div>Loading Variance Lab data...</div>
        </div>`;
    }
  }

  // ── Data loading ─────────────────────────────────────────────────────────────
  async function loadPortalData() {
    try {
      const r = await fetch(`${PORTAL_URL}?v=${Date.now()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      portalData = await r.json();
    } catch(e) {
      console.warn("Transfer Portal data unavailable:", e);
      portalData = { teams:[], juco:[], conference_summary:[] };
    }
    renderPortal();
  }

  async function loadVarianceData() {
    try {
      const r = await fetch(`${VARIANCE_URL}?v=${Date.now()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      varianceData = await r.json();
    } catch(e) {
      console.warn("Variance Lab data unavailable:", e);
      varianceData = { cohorts:{} };
    }
    renderVariance();
  }

  // ── Boot ─────────────────────────────────────────────────────────────────────
  installPortalVarianceStyles();

  document.addEventListener("DOMContentLoaded", () => {
    installContainers();
    renderPortal();
    renderVariance();
    loadPortalData();
    loadVarianceData();
  });

})();
