(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX — MATCHUP MARKET LAYER
  //
  // Performance + presentation pass:
  // - Keeps directional movement relative to THI.
  // - Collapses long alt ladders to a compact 8-row default.
  // - Keeps MAIN + THI-nearby lines prioritized in the compact view.
  // - Avoids destroying/rebuilding the market layer when nothing changed.
  // - Ignores its own DOM mutations.
  // - Lazy-loads market JSON only when a matchup is actually present.
  // - Uses browser revalidation instead of cache-busting every request.
  // - Does NOT alter Model A or projection calculations.
  // ==========================================================================

  const PROJECTIONS_URL = "./data/projections.json";
  const ALTS_URL = "./data/alternate_spreads.json";
  const HISTORY_URL = "./data/market_history.json";

  const ROOT_ID = "thi-market-story";
  const STYLE_ID = "thi-market-layer-styles-v2";
  const COMPACT_ALT_ROWS = 8;
  const REFRESH_MS = 5 * 60 * 1000;

  let projectionGames = [];
  let altGames = {};
  let historyGames = {};

  let containerObserver = null;
  let titleObserver = null;
  let refreshTimer = null;
  let renderTimer = null;

  let dataLoaded = false;
  let dataLoading = null;
  let lastRenderSignature = "";
  let lastMatchupKey = "";
  let expandedGameKey = null;

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
    const response = await fetch(url, {
      cache: "no-cache",
    });
    if (!response.ok) {
      throw new Error(`${url}: HTTP ${response.status}`);
    }
    return response.json();
  }

  async function loadData(force = false) {
    if (dataLoading) return dataLoading;
    if (dataLoaded && !force) return;

    dataLoading = (async () => {
      const [p, a, h] = await Promise.allSettled([
        fetchJson(PROJECTIONS_URL),
        fetchJson(ALTS_URL),
        fetchJson(HISTORY_URL),
      ]);

      if (p.status === "fulfilled") {
        projectionGames = payloadGames(p.value);
      }

      if (a.status === "fulfilled") {
        altGames =
          a.value?.games && typeof a.value.games === "object"
            ? a.value.games
            : {};
      }

      if (h.status === "fulfilled") {
        historyGames =
          h.value?.games && typeof h.value.games === "object"
            ? h.value.games
            : {};
      }

      dataLoaded = projectionGames.length > 0;
    })();

    try {
      await dataLoading;
    } finally {
      dataLoading = null;
    }
  }

  function matchupContainer() {
    return document.getElementById("matchup-container");
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

  function matchupKey(teams) {
    if (!teams) return "";
    return `${canonical(teams.away)}@${canonical(teams.home)}`;
  }

  function findProjection(away, home) {
    return (
      projectionGames.find((game) => {
        const gameAway = game?.away?.team ?? game?.away_team;
        const gameHome = game?.home?.team ?? game?.home_team;
        return sameTeam(gameAway, away) && sameTeam(gameHome, home);
      }) || null
    );
  }

  function isFcsFallback(game) {
    return String(game?.model_type || "").toLowerCase() === "fcs_fallback";
  }

  function modelHomeSpread(game) {
    return num(game?.projection?.home_spread);
  }

  function marketHomeSpread(game) {
    return num(game?.market?.home_spread);
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

    return (
      Object.values(rows).find(
        (row) =>
          sameTeam(row?.away_team, away) && sameTeam(row?.home_team, home)
      ) || null
    );
  }

  function sideSpread(homeSpread, preferred, home, away) {
    const hs = num(homeSpread);
    if (hs === null || !preferred) return null;
    if (sameTeam(preferred, home)) return hs;
    if (sameTeam(preferred, away)) return -hs;
    return null;
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const oldStyle = document.getElementById("thi-market-layer-styles-v1");
    if (oldStyle) oldStyle.remove();

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
        align-items: start;
      }

      #${ROOT_ID} .analysis-panel {
        margin: 0;
      }

      #${ROOT_ID} .thi-market-panel {
        overflow: hidden;
        border: 1px solid var(--border);
        border-radius: var(--radius);
        background: var(--surface);
        contain: layout paint;
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

      #${ROOT_ID} .thi-alt-table tbody tr:last-child td {
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

      #${ROOT_ID} .thi-alt-toggle-wrap {
        padding: 9px 14px 11px;
        border-top: 1px solid #eeeeeb;
        background: #fafaf8;
      }

      #${ROOT_ID} .thi-alt-toggle {
        width: 100%;
        min-height: 34px;
        border: 1px solid var(--border);
        border-radius: 7px;
        background: #fff;
        color: var(--text);
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
        letter-spacing: .35px;
        cursor: pointer;
      }

      #${ROOT_ID} .thi-alt-toggle:hover {
        background: #f5f5f2;
        border-color: var(--border-dark);
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

      #${ROOT_ID} .thi-move-direction {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 12px;
        padding: 6px 8px;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: #fafaf8;
        color: var(--text);
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
      }

      #${ROOT_ID} .thi-move-callout {
        margin-top: 11px;
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
      row?.book_abbr || row?.bookmaker || "BOOK"
    )
      .slice(0, 5)
      .toUpperCase();

    const css = BOOK_CLASS[key] || "";
    return `<span class="thi-book ${esc(css)}" title="${esc(
      row?.bookmaker || abbr
    )}">${esc(abbr)}</span>`;
  }

  function linePoint(row) {
    return num(row?.point);
  }

  function compactAltLines(lines, modelSide) {
    if (!Array.isArray(lines) || lines.length <= COMPACT_ALT_ROWS) {
      return lines || [];
    }

    const main = lines.find((row) => row?.is_main) || null;
    const mainPoint = linePoint(main);

    const ranked = lines
      .map((row, index) => {
        const point = linePoint(row);

        const modelDistance =
          point === null || modelSide === null
            ? Number.POSITIVE_INFINITY
            : Math.abs(point - modelSide);

        const mainDistance =
          point === null || mainPoint === null
            ? Number.POSITIVE_INFINITY
            : Math.abs(point - mainPoint);

        return {
          row,
          index,
          score: Math.min(modelDistance, mainDistance),
          mustKeep: Boolean(row?.is_main),
        };
      })
      .sort((a, b) => {
        if (a.mustKeep !== b.mustKeep) return a.mustKeep ? -1 : 1;
        if (a.score !== b.score) return a.score - b.score;
        return a.index - b.index;
      })
      .slice(0, COMPACT_ALT_ROWS)
      .sort((a, b) => a.index - b.index);

    return ranked.map((item) => item.row);
  }

  function altRowsHtml(lines, preferred) {
    return lines
      .map((row) => {
        const distance = num(row.distance_from_thi);
        const inside = distance !== null && distance >= 0;

        const label =
          row.distance_label ||
          (distance === null
            ? "—"
            : `${Math.abs(distance).toFixed(1)} pts ${
                inside ? "inside" : "beyond"
              } THI`);

        return `
          <tr class="${row.is_main ? "main" : ""}">
            <td>
              <span class="thi-alt-line">${esc(preferred)} ${esc(
          fmtSpread(row.point)
        )}</span>
              ${
                row.is_main
                  ? `<span class="thi-main-pill">Main</span>`
                  : ""
              }
            </td>
            <td class="thi-alt-price">${esc(fmtPrice(row.price))}</td>
            <td>${bookBadge(row)}</td>
            <td class="thi-alt-distance ${inside ? "inside" : ""}">
              ${esc(label)}
            </td>
          </tr>
        `;
      })
      .join("");
  }

  function altPanel(game, altRow, preferred, home, away, expanded) {
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
              <div class="thi-market-title">Alternate spreads — ${esc(
                preferred || "THI preferred side"
              )}</div>
            </div>
            <div class="thi-market-reference">
              <div class="thi-market-reference-label">THI Spread</div>
              <div class="thi-market-reference-value">
                ${
                  preferred && modelSide !== null
                    ? `${esc(preferred)} ${esc(fmtSpread(modelSide))}`
                    : "—"
                }
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

    const allLines = altRow.lines;
    const visibleLines = expanded
      ? allLines
      : compactAltLines(allLines, modelSide);

    const hiddenCount = Math.max(0, allLines.length - visibleLines.length);

    return `
      <div class="thi-market-panel" data-thi-alt-panel>
        <div class="thi-market-head">
          <div>
            <div class="thi-market-kicker">What the market offers on THI's side</div>
            <div class="thi-market-title">Alternate spreads — ${esc(
              preferred
            )}</div>
          </div>
          <div class="thi-market-reference">
            <div class="thi-market-reference-label">THI Spread</div>
            <div class="thi-market-reference-value">${esc(
              preferred
            )} ${esc(fmtSpread(modelSide))}</div>
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
          <tbody>${altRowsHtml(visibleLines, preferred)}</tbody>
        </table>

        ${
          allLines.length > COMPACT_ALT_ROWS
            ? `
          <div class="thi-alt-toggle-wrap">
            <button
              type="button"
              class="thi-alt-toggle"
              data-thi-alt-toggle
              aria-expanded="${expanded ? "true" : "false"}"
            >
              ${
                expanded
                  ? "Show compact alternate spreads"
                  : `Show all alternate spreads (${allLines.length}) · ${hiddenCount} more`
              }
            </button>
          </div>
        `
            : ""
        }
      </div>
    `;
  }

  function movementState(firstCaptured, current, model) {
    if (
      firstCaptured === null ||
      current === null ||
      model === null
    ) {
      return {
        kind: "unknown",
        label: "Direction pending",
        summary: "Not enough captured market history yet.",
      };
    }

    const actualDelta = current - firstCaptured;
    const targetDelta = model - firstCaptured;

    if (Math.abs(actualDelta) < 0.05) {
      return {
        kind: "flat",
        label: "↔ Unchanged vs first capture",
        summary: "Market is unchanged from THI's first captured line.",
      };
    }

    if (Math.abs(targetDelta) < 0.05) {
      return {
        kind: "aligned",
        label: "↔ THI was aligned at first capture",
        summary: "The first captured market was already aligned with the THI spread.",
      };
    }

    const sameDirection =
      Math.sign(actualDelta) === Math.sign(targetDelta);

    const crossed =
      sameDirection &&
      Math.abs(actualDelta) > Math.abs(targetDelta);

    if (crossed) {
      return {
        kind: "through",
        label: `↗ ${Math.abs(actualDelta).toFixed(1)} pts through THI`,
        summary: `Market moved through the THI spread and is now ${Math.abs(
          current - model
        ).toFixed(1)} pts beyond it.`,
      };
    }

    if (sameDirection) {
      return {
        kind: "toward",
        label: `↗ ${Math.abs(actualDelta).toFixed(1)} pts toward THI`,
        summary: `Market has moved ${Math.abs(actualDelta).toFixed(
          1
        )} pts toward THI.`,
      };
    }

    return {
      kind: "away",
      label: `↘ ${Math.abs(actualDelta).toFixed(1)} pts away from THI`,
      summary: `Market has moved ${Math.abs(actualDelta).toFixed(
        1
      )} pts away from THI.`,
    };
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
      historyRow.first_captured_home_spread ??
        historyRow.open_home_spread,
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

    const movement = movementState(firstCaptured, current, model);

    return `
      <div class="thi-market-panel">
        <div class="thi-market-head">
          <div>
            <div class="thi-market-kicker">Market movement</div>
            <div class="thi-market-title">${esc(
              preferred || "Market"
            )} line history</div>
          </div>
        </div>

        <div class="thi-movement-body">
          <div class="thi-movement-track">
            <div class="thi-move-point">
              <div class="thi-move-label">First Captured</div>
              <div class="thi-move-value">${esc(
                fmtSpread(firstCaptured)
              )}</div>
            </div>

            <div class="thi-move-arrow">→</div>

            <div class="thi-move-point">
              <div class="thi-move-label">Current</div>
              <div class="thi-move-value">${esc(
                fmtSpread(current)
              )}</div>
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

          <div class="thi-move-direction">
            ${esc(movement.label)}
          </div>

          <div class="thi-move-callout">
            <strong>${esc(movement.summary)}</strong>
          </div>
        </div>
      </div>
    `;
  }

  function findWhyPanel(container) {
    const panels = [...container.querySelectorAll(".analysis-panel")];

    return (
      panels.find((panel) => {
        const title = panel.querySelector(".analysis-panel-title");
        const text = String(title?.textContent || "")
          .trim()
          .toLowerCase();

        return (
          text === "why the model differs" ||
          text.startsWith("why thi leans ") ||
          text === "why thi differs"
        );
      }) || null
    );
  }

  function renderSignature(game, historyRow, altRow, preferred, expanded) {
    const altLines = Array.isArray(altRow?.lines)
      ? altRow.lines.map((row) => [
          row?.point,
          row?.price,
          row?.bookmaker_key,
          row?.is_main,
          row?.distance_from_thi,
        ])
      : [];

    return JSON.stringify({
      game: gameId(game),
      preferred,
      model: modelHomeSpread(game),
      market: marketHomeSpread(game),
      first:
        historyRow?.first_captured_home_spread ??
        historyRow?.open_home_spread ??
        null,
      current: historyRow?.current_home_spread ?? null,
      close: historyRow?.close_home_spread ?? null,
      alt: altLines,
      expanded,
    });
  }

  function renderMarketLayer(game, teams) {
    const container = matchupContainer();
    if (!container) return;

    const preferred = preferredSide(game);
    const regularMarketGame =
      !isFcsFallback(game) && marketHomeSpread(game) !== null;

    const historyRow = findDataRow(
      historyGames,
      game,
      teams.away,
      teams.home
    );

    const altRow =
      regularMarketGame && preferred
        ? findDataRow(
            altGames,
            game,
            teams.away,
            teams.home
          )
        : null;

    const key = gameId(game) || matchupKey(teams);
    const expanded = expandedGameKey === key;

    const signature = renderSignature(
      game,
      historyRow,
      altRow,
      preferred,
      expanded
    );

    const analysisGrid = container.querySelector(".analysis-grid");
    if (!analysisGrid) return;

    const existingRoot = document.getElementById(ROOT_ID);

    // Critical performance guard:
    // if the actual game/market payload has not changed, do nothing.
    if (
      existingRoot &&
      lastRenderSignature === signature &&
      existingRoot.isConnected
    ) {
      return;
    }

    let root = existingRoot;

    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      analysisGrid.insertAdjacentElement("afterend", root);
    }

    const why = findWhyPanel(container);
    if (why && !root.contains(why)) {
      const whyTitle = why.querySelector(".analysis-panel-title");

      if (whyTitle) {
        whyTitle.textContent = preferred
          ? `Why THI leans ${preferred}`
          : "Why THI differs";
      }

      root.appendChild(why);
    }

    let marketHtml = "";

    if (regularMarketGame && preferred) {
      marketHtml = `
        <div class="thi-market-grid">
          ${altPanel(
            game,
            altRow,
            preferred,
            teams.home,
            teams.away,
            expanded
          )}
          ${movementPanel(
            game,
            historyRow,
            preferred,
            teams.home,
            teams.away
          )}
        </div>
      `;
    } else if (regularMarketGame && historyRow) {
      marketHtml = `
        <div class="thi-market-grid">
          ${movementPanel(
            game,
            historyRow,
            preferred,
            teams.home,
            teams.away
          )}
        </div>
      `;
    }

    const oldGrid = root.querySelector(".thi-market-grid");
    if (oldGrid) {
      oldGrid.outerHTML = marketHtml;
    } else if (marketHtml) {
      root.insertAdjacentHTML("beforeend", marketHtml);
    }

    lastRenderSignature = signature;
  }

  async function apply(forceDataRefresh = false) {
    const teams = currentMatchupTeams();

    if (!teams) {
      lastMatchupKey = "";
      lastRenderSignature = "";
      return;
    }

    const key = matchupKey(teams);

    if (key !== lastMatchupKey) {
      lastMatchupKey = key;
      lastRenderSignature = "";
      expandedGameKey = null;
    }

    await loadData(forceDataRefresh);

    const game = findProjection(teams.away, teams.home);
    if (!game) return;

    renderMarketLayer(game, teams);
  }

  function scheduleApply(delay = 45) {
    window.clearTimeout(renderTimer);
    renderTimer = window.setTimeout(() => {
      apply(false).catch(() => {});
    }, delay);
  }

  function mutationIsOnlyOurLayer(mutations) {
    return mutations.every((mutation) => {
      const target =
        mutation.target?.nodeType === Node.ELEMENT_NODE
          ? mutation.target
          : mutation.target?.parentElement;

      return Boolean(target?.closest?.(`#${ROOT_ID}`));
    });
  }

  function bindTitleObserver() {
    if (titleObserver) {
      titleObserver.disconnect();
      titleObserver = null;
    }

    const title = document.querySelector(
      "#matchup-container .matchup-title"
    );

    if (!title) return;

    titleObserver = new MutationObserver((mutations) => {
      if (mutationIsOnlyOurLayer(mutations)) return;
      scheduleApply(20);
    });

    titleObserver.observe(title, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }

  function bindContainerObserver() {
    const container = matchupContainer();
    if (!container) return;

    if (containerObserver) containerObserver.disconnect();

    containerObserver = new MutationObserver((mutations) => {
      if (mutationIsOnlyOurLayer(mutations)) return;

      // Only use the container observer to detect route/page structure changes.
      // Heavy subtree observation is intentionally avoided.
      bindTitleObserver();
      scheduleApply(45);
    });

    containerObserver.observe(container, {
      childList: true,
      subtree: false,
    });

    bindTitleObserver();
  }

  function bindRootEvents() {
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-thi-alt-toggle]");
      if (!button) return;

      const teams = currentMatchupTeams();
      if (!teams) return;

      const game = findProjection(teams.away, teams.home);
      if (!game) return;

      const key = gameId(game) || matchupKey(teams);
      expandedGameKey =
        expandedGameKey === key ? null : key;

      lastRenderSignature = "";
      renderMarketLayer(game, teams);
    });
  }

  async function init() {
    installStyles();
    bindRootEvents();
    bindContainerObserver();

    // Lazy: if there is no matchup open, do not download market-layer data yet.
    if (currentMatchupTeams()) {
      await apply(false);
    }

    refreshTimer = window.setInterval(async () => {
      if (!currentMatchupTeams()) return;

      try {
        await apply(true);
      } catch (_) {
        // Keep the last good rendered state if a refresh fails.
      }
    }, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, {
      once: true,
    });
  } else {
    init();
  }
})();
