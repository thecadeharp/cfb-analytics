(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — MATCHUP MARKET LAYER
  //
  // Additive frontend only:
  // - Moves the existing "Why the model differs" panel higher on matchup pages.
  // - Adds THI preferred-side alternate spread ladder.
  // - Adds factual "Distance From THI" labels.
  // - Adds open/current/close line movement.
  // - Does NOT alter Model A or projection calculations.
  // ==========================================================================

  const PROJECTIONS_URL = "./data/projections.json";
  const ALTS_URL = "./data/alternate_spreads.json";
  const HISTORY_URL = "./data/market_history.json";

  const ROOT_ID = "thi-market-story";
  const STYLE_ID = "thi-market-layer-styles-v1";

  let projectionGames = [];
  let altGames = {};
  let historyGames = {};
  let observer = null;
  let applying = false;

  const BOOK_CLASS = {
    draftkings: "book-dk",
    fanduel: "book-fd",
    betmgm: "book-mgm",
    caesars: "book-czr",
    betrivers: "book-br",
    fanatics: "book-fan",
    espnbet: "book-espn",
    hardrockbet: "book-hr",
  };

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, "and")
      .replace(/[.'’(),_-]/g, " ")
      .replace(/\buniversity\b/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function sameTeam(a, b) {
    const x = canonical(a);
    const y = canonical(b);
    if (!x || !y) return false;
    return x === y || x.startsWith(`${y} `) || y.startsWith(`${x} `);
  }

  function num(value) {
    if (value === null || value === undefined || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function fmtSpread(value) {
    const n = num(value);
    if (n === null) return "—";
    if (Math.abs(n) < 0.001) return "PK";
    return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
  }

  function fmtPrice(value) {
    const n = num(value);
    if (n === null) return "—";
    return n > 0 ? `+${Math.round(n)}` : String(Math.round(n));
  }

  function payloadGames(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.games)) return payload.games;
    return [];
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}?v=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json();
  }

  async function loadData() {
    const [p, a, h] = await Promise.allSettled([
      fetchJson(PROJECTIONS_URL),
      fetchJson(ALTS_URL),
      fetchJson(HISTORY_URL),
    ]);

    if (p.status === "fulfilled") {
      projectionGames = payloadGames(p.value);
    }

    if (a.status === "fulfilled") {
      altGames = a.value?.games && typeof a.value.games === "object"
        ? a.value.games
        : {};
    }

    if (h.status === "fulfilled") {
      historyGames = h.value?.games && typeof h.value.games === "object"
        ? h.value.games
        : {};
    }
  }

  function currentMatchupTeams() {
    const title = document.querySelector("#matchup-container .matchup-title");
    const text = String(title?.textContent || "").trim();
    if (!text.includes("@")) return null;

    const parts = text.split("@");
    if (parts.length < 2) return null;

    return {
      away: parts[0].trim(),
      home: parts.slice(1).join("@").trim(),
    };
  }

  function findProjection(away, home) {
    return projectionGames.find(game => {
      const gameAway = game?.away?.team ?? game?.away_team;
      const gameHome = game?.home?.team ?? game?.home_team;
      return sameTeam(gameAway, away) && sameTeam(gameHome, home);
    }) || null;
  }

  function canonicalSignal(value) {
    const raw = String(value || "").toUpperCase().trim();
    const aliases = {
      "AGREE W/ MARKET": "ALIGNED",
      "ALIGNED": "ALIGNED",
      "LEAN": "SMALL EDGE",
      "SLIGHT EDGE": "SMALL EDGE",
      "SMALL EDGE": "SMALL EDGE",
      "EDGE": "PLAY",
      "PLAY": "PLAY",
      "STRONG EDGE": "MATERIAL DISAGREEMENT",
      "MATERIAL DISAGREEMENT": "MATERIAL DISAGREEMENT",
      "OUTLIER": "OUTLIER",
    };
    return aliases[raw] || raw;
  }

  function signalName(game) {
    return canonicalSignal(
      game?.comparison?.signal ??
      game?.comparison?.status ??
      ""
    );
  }

  function isFcsFallback(game) {
    return String(game?.model_type || "").toLowerCase() === "fcs_fallback";
  }

  function preferredSide(game) {
    const explicit = game?.comparison?.preferred_side;
    if (explicit) return explicit;

    const home = game?.home?.team ?? game?.home_team;
    const away = game?.away?.team ?? game?.away_team;
    const model = modelHomeSpread(game);
    const market = marketHomeSpread(game);

    if (!home || !away || model === null || market === null) return null;

    const delta = model - market;
    if (Math.abs(delta) < 0.001) return null;

    return delta < 0 ? home : away;
  }

  function gameId(game) {
    return String(game?.game_id ?? game?.id ?? "");
  }

  function findDataRow(rows, game, away, home) {
    const id = gameId(game);
    if (id && rows[id]) return rows[id];

    return Object.values(rows).find(row =>
      sameTeam(row?.away_team, away) &&
      sameTeam(row?.home_team, home)
    ) || null;
  }

  function sideSpread(homeSpread, preferred, home, away) {
    const hs = num(homeSpread);
    if (hs === null || !preferred) return null;
    if (sameTeam(preferred, home)) return hs;
    if (sameTeam(preferred, away)) return -hs;
    return null;
  }

  function modelHomeSpread(game) {
    return num(game?.projection?.home_spread);
  }

  function marketHomeSpread(game) {
    return num(game?.market?.home_spread);
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      #${ROOT_ID} {
        margin-top: 14px;
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: 12px;
      }

      #${ROOT_ID} .thi-market-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr);
        gap: 12px;
      }

      #${ROOT_ID} .analysis-panel {
        margin: 0;
      }

      #${ROOT_ID} .thi-market-panel {
        overflow: hidden;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--surface);
      }

      #${ROOT_ID} .thi-market-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        padding: 14px 16px;
        border-bottom: 1px solid var(--border);
        background: #fafaf8;
      }

      #${ROOT_ID} .thi-market-kicker {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 800;
        letter-spacing: .95px;
        text-transform: uppercase;
      }

      #${ROOT_ID} .thi-market-title {
        margin-top: 4px;
        color: var(--text);
        font-size: 15px;
        font-weight: 800;
      }

      #${ROOT_ID} .thi-market-reference {
        text-align: right;
        white-space: nowrap;
      }

      #${ROOT_ID} .thi-market-reference-label {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        letter-spacing: .7px;
        text-transform: uppercase;
      }

      #${ROOT_ID} .thi-market-reference-value {
        margin-top: 4px;
        font-family: var(--mono);
        font-size: 14px;
        font-weight: 800;
      }

      #${ROOT_ID} .thi-alt-table {
        width: 100%;
        border-collapse: collapse;
      }

      #${ROOT_ID} .thi-alt-table th {
        padding: 9px 14px;
        color: var(--muted);
        background: #fff;
        border-bottom: 1px solid #eeeeeb;
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: .7px;
        text-align: left;
        text-transform: uppercase;
      }

      #${ROOT_ID} .thi-alt-table th:nth-child(2),
      #${ROOT_ID} .thi-alt-table td:nth-child(2) {
        text-align: right;
      }

      #${ROOT_ID} .thi-alt-table td {
        padding: 10px 14px;
        border-bottom: 1px solid #f0f0ed;
        font-size: 11px;
        vertical-align: middle;
      }

      #${ROOT_ID} .thi-alt-table tr:last-child td {
        border-bottom: none;
      }

      #${ROOT_ID} .thi-alt-table tr.main {
        background: #f7f7f3;
      }

      #${ROOT_ID} .thi-alt-line {
        font-family: var(--mono);
        font-weight: 800;
      }

      #${ROOT_ID} .thi-alt-price {
        font-family: var(--mono);
        font-size: 12px;
        font-weight: 800;
      }

      #${ROOT_ID} .thi-alt-distance {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 9px;
      }

      #${ROOT_ID} .thi-alt-distance.inside {
        color: var(--green);
      }

      #${ROOT_ID} .thi-main-pill {
        display: inline-flex;
        margin-left: 6px;
        padding: 3px 6px;
        border: 1px solid var(--border-dark);
        border-radius: 999px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 7px;
        font-weight: 800;
        letter-spacing: .6px;
        text-transform: uppercase;
      }

      #${ROOT_ID} .thi-book {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 34px;
        padding: 4px 6px;
        border-radius: 5px;
        border: 1px solid #d8d8d3;
        background: #f5f5f2;
        color: #363c42;
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 900;
        letter-spacing: .25px;
      }

      #${ROOT_ID} .thi-book.book-dk { color:#187b42; border-color:#bddcca; background:#eef8f2; }
      #${ROOT_ID} .thi-book.book-fd { color:#1553a4; border-color:#bfd1ea; background:#eff5fc; }
      #${ROOT_ID} .thi-book.book-mgm { color:#8a6415; border-color:#dfd0a5; background:#fbf7ea; }
      #${ROOT_ID} .thi-book.book-czr { color:#1d5c66; border-color:#bfd7db; background:#eff7f8; }
      #${ROOT_ID} .thi-book.book-br { color:#294c83; border-color:#c5d1e3; background:#f1f4f9; }
      #${ROOT_ID} .thi-book.book-fan { color:#6a3590; border-color:#d6c4e2; background:#f7f1fb; }
      #${ROOT_ID} .thi-book.book-espn { color:#a22f25; border-color:#e1c2bd; background:#fbf1ef; }
      #${ROOT_ID} .thi-book.book-hr { color:#6d4b20; border-color:#dfceb3; background:#fbf6ef; }

      #${ROOT_ID} .thi-market-empty {
        padding: 14px 16px;
        color: var(--muted);
        font-size: 10px;
        line-height: 1.55;
      }

      #${ROOT_ID} .thi-movement-body {
        padding: 14px 16px;
      }

      #${ROOT_ID} .thi-movement-track {
        display: grid;
        grid-template-columns: 1fr auto 1fr auto 1fr;
        gap: 8px;
        align-items: center;
      }

      #${ROOT_ID} .thi-move-point {
        min-width: 0;
      }

      #${ROOT_ID} .thi-move-label {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        letter-spacing: .7px;
        text-transform: uppercase;
      }

      #${ROOT_ID} .thi-move-value {
        margin-top: 4px;
        font-family: var(--mono);
        font-size: 13px;
        font-weight: 900;
      }

      #${ROOT_ID} .thi-move-arrow {
        color: var(--muted-light);
        font-family: var(--mono);
        font-size: 12px;
      }

      #${ROOT_ID} .thi-move-callout {
        margin-top: 13px;
        padding-top: 11px;
        border-top: 1px solid #eeeeeb;
        color: var(--muted);
        font-size: 10px;
        line-height: 1.5;
      }

      #${ROOT_ID} .thi-move-callout strong {
        color: var(--text);
      }

      #${ROOT_ID} .thi-thi-marker {
        margin-top: 10px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 9px;
      }

      #${ROOT_ID} .thi-thi-marker strong {
        color: var(--text);
      }

      @media (max-width: 900px) {
        #${ROOT_ID} .thi-market-grid {
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 600px) {
        #${ROOT_ID} .thi-market-head {
          padding: 12px;
        }

        #${ROOT_ID} .thi-alt-table th,
        #${ROOT_ID} .thi-alt-table td {
          padding-left: 10px;
          padding-right: 10px;
        }

        #${ROOT_ID} .thi-alt-table th:nth-child(4),
        #${ROOT_ID} .thi-alt-table td:nth-child(4) {
          display: none;
        }

        #${ROOT_ID} .thi-movement-body {
          padding: 12px;
        }

        #${ROOT_ID} .thi-movement-track {
          gap: 5px;
        }

        #${ROOT_ID} .thi-move-value {
          font-size: 11px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  function bookBadge(row) {
    const key = String(row?.bookmaker_key || "");
    const abbr = String(
      row?.book_abbr ||
      row?.bookmaker ||
      "BOOK"
    ).slice(0, 5).toUpperCase();

    const css = BOOK_CLASS[key] || "";
    return `<span class="thi-book ${esc(css)}" title="${esc(row?.bookmaker || abbr)}">${esc(abbr)}</span>`;
  }

  function altPanel(game, altRow, preferred, home, away) {
    const modelSide = sideSpread(
      modelHomeSpread(game),
      preferred,
      home,
      away
    );

    if (!altRow || !Array.isArray(altRow.lines) || !altRow.lines.length) {
      return `
        <div class="thi-market-panel">
          <div class="thi-market-head">
            <div>
              <div class="thi-market-kicker">Market options</div>
              <div class="thi-market-title">Alternate spreads — ${esc(preferred || "THI preferred side")}</div>
            </div>
            <div class="thi-market-reference">
              <div class="thi-market-reference-label">THI Spread</div>
              <div class="thi-market-reference-value">
                ${preferred && modelSide !== null ? `${esc(preferred)} ${esc(fmtSpread(modelSide))}` : "—"}
              </div>
            </div>
          </div>
          <div class="thi-market-empty">
            Alternate prices have not been refreshed for this matchup yet.
            Main THI analysis is unaffected.
          </div>
        </div>
      `;
    }

    const rows = altRow.lines.map(row => {
      const distance = num(row.distance_from_thi);
      const inside = distance !== null && distance >= 0;
      const label = row.distance_label || (
        distance === null
          ? "—"
          : `${Math.abs(distance).toFixed(1)} pts ${inside ? "inside" : "beyond"} THI`
      );

      return `
        <tr class="${row.is_main ? "main" : ""}">
          <td>
            <span class="thi-alt-line">${esc(preferred)} ${esc(fmtSpread(row.point))}</span>
            ${row.is_main ? `<span class="thi-main-pill">Main</span>` : ""}
          </td>
          <td class="thi-alt-price">${esc(fmtPrice(row.price))}</td>
          <td>${bookBadge(row)}</td>
          <td class="thi-alt-distance ${inside ? "inside" : ""}">
            ${esc(label)}
          </td>
        </tr>
      `;
    }).join("");

    return `
      <div class="thi-market-panel">
        <div class="thi-market-head">
          <div>
            <div class="thi-market-kicker">What the market offers on THI's side</div>
            <div class="thi-market-title">Alternate spreads — ${esc(preferred)}</div>
          </div>
          <div class="thi-market-reference">
            <div class="thi-market-reference-label">THI Spread</div>
            <div class="thi-market-reference-value">${esc(preferred)} ${esc(fmtSpread(modelSide))}</div>
          </div>
        </div>

        <table class="thi-alt-table">
          <thead>
            <tr>
              <th>Line</th>
              <th>Price</th>
              <th>Book</th>
              <th>Distance From THI</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  function movementSummary(open, current, model, close) {
    if (open === null || current === null || model === null) {
      return "Not enough captured market history yet.";
    }

    const actualDelta = current - open;
    const targetDelta = model - open;

    if (Math.abs(actualDelta) < 0.05) {
      return "Market is unchanged from THI's first captured line.";
    }

    if (Math.abs(targetDelta) < 0.05) {
      return "The opening market was already aligned with the THI spread.";
    }

    const sameDirection = Math.sign(actualDelta) === Math.sign(targetDelta);
    const crossed =
      sameDirection &&
      Math.abs(actualDelta) > Math.abs(targetDelta);

    if (crossed) {
      return `Market moved through the THI spread and is now ${Math.abs(current - model).toFixed(1)} pts beyond it.`;
    }

    if (sameDirection) {
      return `Market has moved ${Math.abs(actualDelta).toFixed(1)} pts toward THI.`;
    }

    return `Market has moved ${Math.abs(actualDelta).toFixed(1)} pts away from THI.`;
  }

  function movementPanel(game, historyRow, preferred, home, away) {
    const model = sideSpread(
      modelHomeSpread(game),
      preferred,
      home,
      away
    );

    if (!historyRow) {
      return `
        <div class="thi-market-panel">
          <div class="thi-market-head">
            <div>
              <div class="thi-market-kicker">Market movement</div>
              <div class="thi-market-title">First Captured → Current → Close</div>
            </div>
          </div>
          <div class="thi-market-empty">
            THI has not captured a market-history snapshot for this matchup yet.
          </div>
        </div>
      `;
    }

    const firstCaptured = sideSpread(
      historyRow.first_captured_home_spread ?? historyRow.open_home_spread,
      preferred,
      home,
      away
    );
    const current = sideSpread(
      historyRow.current_home_spread,
      preferred,
      home,
      away
    );
    const close = sideSpread(
      historyRow.close_home_spread,
      preferred,
      home,
      away
    );

    const summary = movementSummary(firstCaptured, current, model, close);

    return `
      <div class="thi-market-panel">
        <div class="thi-market-head">
          <div>
            <div class="thi-market-kicker">Market movement</div>
            <div class="thi-market-title">${esc(preferred || "Market")} line history</div>
          </div>
        </div>

        <div class="thi-movement-body">
          <div class="thi-movement-track">
            <div class="thi-move-point">
              <div class="thi-move-label">First Captured</div>
              <div class="thi-move-value">${esc(fmtSpread(firstCaptured))}</div>
            </div>

            <div class="thi-move-arrow">→</div>

            <div class="thi-move-point">
              <div class="thi-move-label">Current</div>
              <div class="thi-move-value">${esc(fmtSpread(current))}</div>
            </div>

            <div class="thi-move-arrow">→</div>

            <div class="thi-move-point">
              <div class="thi-move-label">Close</div>
              <div class="thi-move-value">${esc(fmtSpread(close))}</div>
            </div>
          </div>

          <div class="thi-thi-marker">
            🔨 THI <strong>${esc(fmtSpread(model))}</strong>
          </div>

          <div class="thi-move-callout">
            <strong>${esc(summary)}</strong>
          </div>
        </div>
      </div>
    `;
  }

  function findWhyPanel(container) {
    const panels = [...container.querySelectorAll(".analysis-panel")];
    return panels.find(panel => {
      const title = panel.querySelector(".analysis-panel-title");
      return String(title?.textContent || "").trim().toLowerCase() === "why the model differs";
    }) || null;
  }

  function apply() {
    if (applying) return;
    applying = true;

    try {
      const container = document.getElementById("matchup-container");
      if (!container) return;

      const teams = currentMatchupTeams();
      if (!teams) return;

      const game = findProjection(teams.away, teams.home);
      if (!game) return;

      const preferred = preferredSide(game);
      const signal = signalName(game);

      const existingRoot = document.getElementById(ROOT_ID);
      if (existingRoot) existingRoot.remove();

      const analysisGrid = container.querySelector(".analysis-grid");
      if (!analysisGrid) return;

      const root = document.createElement("div");
      root.id = ROOT_ID;

      const why = findWhyPanel(container);
      if (why) {
        const whyTitle = why.querySelector(".analysis-panel-title");
        if (whyTitle) {
          whyTitle.textContent = preferred
            ? `Why THI leans ${preferred}`
            : "Why THI differs";
        }
        root.appendChild(why);
      }

      const historyRow = findDataRow(
        historyGames,
        game,
        teams.away,
        teams.home
      );

      // Market tools are context, not betting instructions. Every regular
      // FBS-v-FBS matchup with a valid market can receive them regardless of
      // ALIGNED / SMALL EDGE / PLAY / MATERIAL DISAGREEMENT / OUTLIER.
      // FCS fallback remains intentionally excluded.
      const regularMarketGame =
        !isFcsFallback(game) &&
        marketHomeSpread(game) !== null;

      if (regularMarketGame && preferred) {
        const altRow = findDataRow(
          altGames,
          game,
          teams.away,
          teams.home
        );

        const grid = document.createElement("div");
        grid.className = "thi-market-grid";
        grid.innerHTML =
          altPanel(
            game,
            altRow,
            preferred,
            teams.home,
            teams.away
          ) +
          movementPanel(
            game,
            historyRow,
            preferred,
            teams.home,
            teams.away
          );

        root.appendChild(grid);
      } else if (regularMarketGame && historyRow) {
        // Exact THI/market alignment can have no honest preferred side.
        // Keep the factual market-history panel, but do not manufacture an
        // alternate-spread direction.
        const grid = document.createElement("div");
        grid.className = "thi-market-grid";
        grid.innerHTML = movementPanel(
          game,
          historyRow,
          preferred,
          teams.home,
          teams.away
        );
        root.appendChild(grid);
      }

      analysisGrid.insertAdjacentElement("afterend", root);
    } finally {
      applying = false;
    }
  }

  async function init() {
    installStyles();
    await loadData();
    apply();

    const container = document.getElementById("matchup-container");
    if (!container) return;

    observer = new MutationObserver(() => {
      window.clearTimeout(observer._thiTimer);
      observer._thiTimer = window.setTimeout(apply, 35);
    });

    observer.observe(container, {
      childList: true,
      subtree: true,
    });

    window.setInterval(async () => {
      await loadData();
      apply();
    }, 5 * 60 * 1000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
