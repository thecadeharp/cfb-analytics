(() => {
  "use strict";

  const DATA_URL = "./data/projections.json";
  const STYLE_ID = "hammer-fcs-fallback-ui-styles";
  const DISCLOSURE_ID = "hammer-fcs-matchup-disclosure";

  let projectionGames = [];
  let boardQueued = false;
  let matchupQueued = false;

  function isFcsFallback(game) {
    return Boolean(
      game &&
      (
        game.model_type === "fcs_fallback" ||
        game.tracking_eligible === false
      )
    );
  }

  function teamName(game, side) {
    return String(game?.[side]?.team || "").trim();
  }

  function isFcsSide(game, side) {
    return (
      String(game?.[side]?.classification || "").toUpperCase() === "FCS" ||
      (
        isFcsFallback(game) &&
        !Number.isFinite(Number(game?.[side]?.power_rating))
      )
    );
  }

  function normalize(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/&/g, "and")
      .replace(/[^a-z0-9]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function findGameByTeams(away, home) {
    const awayKey = normalize(away);
    const homeKey = normalize(home);

    return projectionGames.find(game =>
      normalize(teamName(game, "away")) === awayKey &&
      normalize(teamName(game, "home")) === homeKey
    ) || null;
  }

  function findGameFromRow(row) {
    if (!row) return null;

    const names = Array.from(
      row.querySelectorAll(".team-name")
    )
      .map(el => String(el.textContent || "").trim())
      .filter(Boolean);

    if (names.length < 2) return null;

    return findGameByTeams(names[0], names[1]);
  }

  function findGameFromMatchup() {
    const container = document.getElementById("matchup-container");
    if (!container) return null;

    const title =
      container.querySelector(".matchup-title")?.textContent ||
      document.querySelector("#view-matchup .page-title")?.textContent ||
      "";

    const match = String(title).match(/^\s*(.+?)\s*@\s*(.+?)\s*$/);

    if (match) {
      return findGameByTeams(match[1], match[2]);
    }

    const names = Array.from(
      container.querySelectorAll(".team-name")
    )
      .map(el => String(el.textContent || "").trim())
      .filter(Boolean);

    if (names.length >= 2) {
      return findGameByTeams(names[0], names[1]);
    }

    return null;
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      .hammer-fcs-fallback-row {
        background: #fcfcfa;
      }

      .hammer-fcs-fallback-row:hover {
        box-shadow: inset 3px 0 0 #8a7a4a !important;
      }

      .hammer-fcs-badge,
      .hammer-fcs-untracked-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        padding: 6px 9px;
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
        letter-spacing: .45px;
        white-space: nowrap;
      }

      .hammer-fcs-badge {
        color: #5e5128;
        background: #f4eedb;
        border: 1px solid #d8c99a;
      }

      .hammer-fcs-untracked-badge {
        color: var(--muted);
        background: #f4f4f2;
        border: 1px solid var(--border);
      }

      .hammer-fcs-subtext {
        margin-top: 5px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        line-height: 1.35;
        white-space: normal;
      }

      .team-name.hammer-fcs-static-team {
        cursor: default !important;
        pointer-events: none !important;
        text-decoration: none !important;
      }

      .hammer-fcs-matchup-disclosure,
      .hammer-fcs-score-withheld {
        margin: 0 0 18px;
        padding: 14px 16px;
        border: 1px solid #d8c99a;
        border-radius: 11px;
        background: #faf7ed;
      }

      .hammer-fcs-matchup-disclosure {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 14px;
        align-items: center;
      }

      .hammer-fcs-matchup-disclosure-title,
      .hammer-fcs-score-withheld-title {
        color: #5e5128;
        font-family: var(--mono);
        font-size: 10px;
        font-weight: 800;
        letter-spacing: .8px;
        text-transform: uppercase;
      }

      .hammer-fcs-matchup-disclosure-copy,
      .hammer-fcs-score-withheld-copy {
        color: #6e6549;
        font-size: 11px;
        line-height: 1.55;
      }

      .hammer-fcs-score-withheld-title {
        margin-bottom: 5px;
      }

      .hammer-fcs-matchup-disclosure-copy strong,
      .hammer-fcs-score-withheld-copy strong {
        color: #4f4526;
      }

      @media (max-width: 600px) {
        .hammer-fcs-matchup-disclosure {
          grid-template-columns: 1fr;
          gap: 6px;
          padding: 13px 14px;
        }

        .hammer-fcs-badge,
        .hammer-fcs-untracked-badge {
          white-space: normal;
          text-align: center;
          line-height: 1.2;
        }
      }
    `;

    document.head.appendChild(style);
  }

  function markFcsTeamElement(element) {
    if (!element) return;

    element.classList.add("hammer-fcs-static-team");
    element.removeAttribute("onclick");
    element.removeAttribute("role");
    element.removeAttribute("tabindex");
    element.setAttribute(
      "title",
      "FCS team dossier is not available yet."
    );
  }

  function decorateProjectionRow(row) {
    const game = findGameFromRow(row);
    if (!isFcsFallback(game)) return;

    row.classList.add("hammer-fcs-fallback-row");
    row.dataset.hammerFcsFallback = "1";

    const cells = Array.from(row.querySelectorAll(":scope > td"));

    if (cells.length >= 7) {
      cells[5].innerHTML = `
        <span class="hammer-fcs-badge">FCS FALLBACK</span>
        <div class="hammer-fcs-subtext">
          Preliminary cross-division model
        </div>
      `;

      cells[6].innerHTML = `
        <span class="hammer-fcs-untracked-badge">UNTRACKED</span>
        <div class="signal-record hammer-fcs-subtext">
          FCS fallback
        </div>
      `;
    }

    const names = Array.from(row.querySelectorAll(".team-name"));

    if (names[0] && isFcsSide(game, "away")) {
      markFcsTeamElement(names[0]);
    }

    if (names[1] && isFcsSide(game, "home")) {
      markFcsTeamElement(names[1]);
    }
  }

  function decorateProjectionBoard() {
    document
      .querySelectorAll(
        "#projections-container .projection-table tbody tr.game-row"
      )
      .forEach(decorateProjectionRow);
  }

  function queueBoard() {
    if (boardQueued) return;
    boardQueued = true;

    requestAnimationFrame(() => {
      boardQueued = false;
      decorateProjectionBoard();
    });
  }

  function replaceBadge(element, type) {
    if (!element) return;

    element.className =
      type === "fallback"
        ? "hammer-fcs-badge"
        : "hammer-fcs-untracked-badge";

    element.textContent =
      type === "fallback"
        ? "FCS FALLBACK"
        : "UNTRACKED";
  }

  function removeFakeProjectedScore(container) {
    const cards = Array.from(
      container.querySelectorAll(
        ".projected-score-card, .score-card"
      )
    );

    cards.forEach(card => {
      const text = normalize(card.textContent);

      if (
        text.includes("projected final score") ||
        text.includes("projected score")
      ) {
        card.remove();
      }
    });

    if (
      !container.querySelector(
        ".hammer-fcs-score-withheld"
      )
    ) {
      const edgeBanner =
        container.querySelector(
          ".model-edge-banner"
        );

      const disclosure =
        document.createElement("div");

      disclosure.className =
        "hammer-fcs-score-withheld";

      disclosure.innerHTML = `
        <div class="hammer-fcs-score-withheld-title">
          Projected Score Withheld
        </div>
        <div class="hammer-fcs-score-withheld-copy">
          The FCS fallback publishes a fair spread and win probability,
          but <strong>does not publish a model total or projected final
          score</strong> until an opponent-specific FCS efficiency model
          exists.
        </div>
      `;

      if (edgeBanner) {
        edgeBanner.insertAdjacentElement(
          "afterend",
          disclosure
        );
      }
    }
  }

  function decorateMatchup() {
    const game = findGameFromMatchup();
    if (!isFcsFallback(game)) return;

    const container =
      document.getElementById("matchup-container");

    if (!container) return;

    container.dataset.hammerFcsFallback = "1";

    const header =
      container.querySelector(".matchup-header");

    if (
      header &&
      !container.querySelector(
        `#${DISCLOSURE_ID}`
      )
    ) {
      header.insertAdjacentHTML(
        "afterend",
        `
          <div
            id="${DISCLOSURE_ID}"
            class="hammer-fcs-matchup-disclosure"
          >
            <div class="hammer-fcs-matchup-disclosure-title">
              FCS FALLBACK
            </div>
            <div class="hammer-fcs-matchup-disclosure-copy">
              <strong>Preliminary cross-division model.</strong>
              The fair spread and market separation are shown for
              research, but this game is <strong>UNTRACKED</strong>
              and is not included in prospective ATS, CLV or Signal
              Confidence records.
            </div>
          </div>
        `
      );
    }

    const headerBadges =
      container.querySelectorAll(
        ".matchup-header .status"
      );

    replaceBadge(headerBadges[0], "fallback");
    replaceBadge(headerBadges[1], "untracked");

    const edgeBanner =
      container.querySelector(
        ".model-edge-banner"
      );

    if (edgeBanner) {
      const label =
        edgeBanner.querySelector(
          ".model-edge-label"
        );

      if (label) {
        label.textContent =
          "CROSS-DIVISION MODEL";
      }

      const bannerBadges =
        edgeBanner.querySelectorAll(
          ".status"
        );

      replaceBadge(
        bannerBadges[0],
        "fallback"
      );

      replaceBadge(
        bannerBadges[1],
        "untracked"
      );

      const context =
        edgeBanner.querySelector(
          ".model-edge-context"
        );

      if (context) {
        const disagreement =
          Number(game?.comparison?.disagreement);

        context.textContent =
          Number.isFinite(disagreement)
            ? `${disagreement.toFixed(1)}-point model-to-market separation. Research only; FCS fallback games are untracked.`
            : "Research only; FCS fallback games are untracked.";
      }
    }

    removeFakeProjectedScore(container);

    const analysisCards =
      container.querySelectorAll(
        ".analysis-grid .analysis-card"
      );

    analysisCards.forEach(card => {
      const label = normalize(
        card.querySelector(
          ".analysis-label"
        )?.textContent
      );

      if (label === "signal size") {
        const small =
          card.querySelector(
            ".analysis-small"
          );

        if (small) {
          small.innerHTML = `
            Market separation shown for research only.<br>
            <strong>UNTRACKED · FCS fallback</strong>
          `;
        }
      }

      if (
        label === "model total" ||
        label === "projected total"
      ) {
        const value =
          card.querySelector(
            ".analysis-value"
          );

        if (value) {
          value.textContent = "—";
        }

        const small =
          card.querySelector(
            ".analysis-small"
          );

        if (small) {
          small.textContent =
            "FCS fallback total withheld";
        }
      }
    });

    const panels =
      container.querySelectorAll(
        ".analysis-panel"
      );

    panels.forEach(panel => {
      const title = normalize(
        panel.querySelector(
          ".analysis-panel-title"
        )?.textContent
      );

      if (title === "live matchup layer") {
        const meta =
          panel.querySelector(
            ".team-meta"
          );

        if (meta) {
          meta.textContent =
            "NOT APPLICABLE";
        }

        const warning =
          panel.querySelector(
            ".sample-warning"
          );

        if (warning) {
          warning.textContent =
            "FCS fallback games do not use opponent-specific live matchup adjustments.";
        }
      }
    });
  }

  function queueMatchup() {
    if (matchupQueued) return;
    matchupQueued = true;

    requestAnimationFrame(() => {
      matchupQueued = false;
      decorateMatchup();
    });
  }

  function updateProjectionCopy() {
    const subtitle =
      document.querySelector(
        "#view-projections .page-subtitle"
      );

    if (subtitle) {
      subtitle.textContent =
        "FBS and FBS-v-FCS game projections, sorted by model edge versus the current market. Full FBS matchups use the tracked Hammer Index model; FBS-v-FCS rows use a preliminary, untracked cross-division fallback.";
    }

    const guideBody =
      document.querySelector(
        "#view-projections .signal-guide-body"
      );

    if (
      guideBody &&
      !document.getElementById(
        "hammer-fcs-guide-note"
      )
    ) {
      const note =
        document.createElement("div");

      note.id =
        "hammer-fcs-guide-note";

      note.className =
        "hammer-fcs-matchup-disclosure";

      note.innerHTML = `
        <div class="hammer-fcs-matchup-disclosure-title">
          FCS FALLBACK
        </div>
        <div class="hammer-fcs-matchup-disclosure-copy">
          FBS-v-FCS games use a preliminary cross-division fallback.
          Their fair line and market separation are shown for research,
          but they are <strong>UNTRACKED</strong> and do not count
          toward ATS, CLV or Signal Confidence records.
        </div>
      `;

      guideBody.appendChild(note);
    }
  }

  function installObservers() {
    const projectionContainer =
      document.getElementById(
        "projections-container"
      );

    if (projectionContainer) {
      new MutationObserver(queueBoard)
        .observe(
          projectionContainer,
          {
            childList: true,
            subtree: true
          }
        );
    }

    const matchupContainer =
      document.getElementById(
        "matchup-container"
      );

    if (matchupContainer) {
      new MutationObserver(queueMatchup)
        .observe(
          matchupContainer,
          {
            childList: true,
            subtree: true
          }
        );
    }
  }

  async function loadProjectionGames() {
    const response =
      await fetch(
        `${DATA_URL}?fcs_ui=${Date.now()}`,
        { cache: "no-store" }
      );

    if (!response.ok) {
      throw new Error(
        `FCS UI projection load failed: HTTP ${response.status}`
      );
    }

    const payload =
      await response.json();

    projectionGames =
      Array.isArray(payload?.games)
        ? payload.games
        : [];
  }

  async function start() {
    installStyles();

    try {
      await loadProjectionGames();
    } catch (error) {
      console.error(error);
      return;
    }

    updateProjectionCopy();
    installObservers();

    queueBoard();
    queueMatchup();

    document.addEventListener(
      "hammer:data-ready",
      () => {
        updateProjectionCopy();
        queueBoard();
        queueMatchup();
      }
    );

    window.setTimeout(queueBoard, 250);
    window.setTimeout(queueBoard, 800);
    window.setTimeout(queueBoard, 1600);

    window.setTimeout(queueMatchup, 250);
    window.setTimeout(queueMatchup, 800);
  }

  if (
    document.readyState === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
