(() => {
  "use strict";

  const STYLE_ID = "hammer-fcs-fallback-ui-styles";
  const DISCLOSURE_ID = "hammer-fcs-matchup-disclosure";

  function isFcsFallback(game) {
    return Boolean(
      game &&
      (
        game.model_type === "fcs_fallback" ||
        game.tracking_eligible === false
      )
    );
  }

  function classificationFor(game, side) {
    return String(game?.[side]?.classification || "").toUpperCase();
  }

  function gameById(gameId) {
    if (!Array.isArray(window.projections)) return null;
    return window.projections.find(
      game => String(game?.game_id ?? "") === String(gameId ?? "")
    ) ?? null;
  }

  function gameIdFromRow(row) {
    if (!row) return "";

    if (row.dataset.gameId) {
      return String(row.dataset.gameId);
    }

    const onclick = String(row.getAttribute("onclick") || "");
    const match = onclick.match(
      /openMatchup\(\s*['"]([^'"]+)['"]\s*\)/
    );

    return match?.[1] || "";
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

      .hammer-fcs-matchup-disclosure {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 14px;
        align-items: center;
        margin: 0 0 18px;
        padding: 14px 16px;
        border: 1px solid #d8c99a;
        border-radius: 11px;
        background: #faf7ed;
      }

      .hammer-fcs-matchup-disclosure-title {
        color: #5e5128;
        font-family: var(--mono);
        font-size: 10px;
        font-weight: 800;
        letter-spacing: .8px;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .hammer-fcs-matchup-disclosure-copy {
        color: #6e6549;
        font-size: 11px;
        line-height: 1.55;
      }

      .hammer-fcs-matchup-disclosure-copy strong {
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

  function fcsTeamMarkup(name, rank, isFcs) {
    if (!isFcs) return;

    const escapedName = String(name || "").trim();
    if (!escapedName) return;

    document
      .querySelectorAll(".team-name")
      .forEach(element => {
        if (String(element.textContent || "").trim() !== escapedName) return;

        const row = element.closest("tr.game-row");
        if (!row?.classList.contains("hammer-fcs-fallback-row")) return;

        element.classList.add("hammer-fcs-static-team");
        element.removeAttribute("onclick");
        element.removeAttribute("role");
        element.removeAttribute("tabindex");
        element.setAttribute(
          "title",
          "FCS team dossier is not available yet."
        );
      });
  }

  function decorateProjectionRow(row) {
    const gameId = gameIdFromRow(row);
    if (!gameId) return;

    const game = gameById(gameId);
    if (!isFcsFallback(game)) return;

    row.classList.add("hammer-fcs-fallback-row");
    row.dataset.hammerFcsFallback = "1";

    const cells = Array.from(
      row.querySelectorAll(":scope > td")
    );

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

    const homeName = game?.home?.team ?? "";
    const awayName = game?.away?.team ?? "";

    fcsTeamMarkup(
      homeName,
      game?.home?.power_rating_rank,
      classificationFor(game, "home") === "FCS"
    );

    fcsTeamMarkup(
      awayName,
      game?.away?.power_rating_rank,
      classificationFor(game, "away") === "FCS"
    );
  }

  function decorateProjectionBoard() {
    document
      .querySelectorAll(
        "#projections-container .projection-table tbody tr.game-row"
      )
      .forEach(decorateProjectionRow);
  }

  function replaceStatusBadge(element, type) {
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

  function decorateMatchup(game) {
    if (!isFcsFallback(game)) return;

    const container =
      document.getElementById("matchup-container");

    if (!container) return;

    container.dataset.hammerFcsFallback = "1";

    const header =
      container.querySelector(".matchup-header");

    if (
      header &&
      !document.getElementById(DISCLOSURE_ID)
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
              This game uses the generic FBS-v-FCS fallback rather than
              a fully calibrated opponent-specific FCS rating. The fair
              spread and market separation are shown for research, but
              this game is <strong>UNTRACKED</strong> and is not included
              in prospective ATS, CLV or Signal Confidence records.
            </div>
          </div>
        `
      );
    }

    const headerBadges =
      container.querySelectorAll(
        ".matchup-header .status"
      );

    replaceStatusBadge(
      headerBadges[0],
      "fallback"
    );

    replaceStatusBadge(
      headerBadges[1],
      "untracked"
    );

    const edgeBanner =
      container.querySelector(
        ".model-edge-banner"
      );

    if (edgeBanner) {
      const title =
        edgeBanner.querySelector(
          ".model-edge-title"
        );

      if (title) {
        title.textContent =
          "Cross-Division Model Edge";
      }

      const context =
        edgeBanner.querySelector(
          ".model-edge-context"
        );

      if (context) {
        const comparison =
          game?.comparison ?? {};

        const disagreement =
          Number(comparison?.disagreement);

        context.textContent =
          Number.isFinite(disagreement)
            ? `${disagreement.toFixed(1)}-point model-to-market separation. Research only; FCS fallback games are not tracked as official Hammer Index signals.`
            : "No current market line is available. FCS fallback games are not tracked as official Hammer Index signals.";
      }

      const bannerBadges =
        edgeBanner.querySelectorAll(
          ".status"
        );

      replaceStatusBadge(
        bannerBadges[0],
        "fallback"
      );

      replaceStatusBadge(
        bannerBadges[1],
        "untracked"
      );
    }

    const signalCards =
      container.querySelectorAll(
        ".analysis-grid .analysis-card"
      );

    signalCards.forEach(card => {
      const label =
        String(
          card.querySelector(
            ".analysis-label"
          )?.textContent || ""
        )
          .trim()
          .toLowerCase();

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
    });

    const panels =
      container.querySelectorAll(
        ".analysis-panel"
      );

    panels.forEach(panel => {
      const title =
        String(
          panel.querySelector(
            ".analysis-panel-title"
          )?.textContent || ""
        )
          .trim()
          .toLowerCase();

      if (
        title === "live matchup layer"
      ) {
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

  function wrapMatchupRenderer() {
    if (
      window.__hammerFcsRendererWrapped
    ) {
      return;
    }

    if (
      typeof window.renderMatchup !==
      "function"
    ) {
      window.setTimeout(
        wrapMatchupRenderer,
        100
      );
      return;
    }

    const baseRenderMatchup =
      window.renderMatchup;

    window.renderMatchup =
      function renderMatchupWithFcsUi(game) {
        baseRenderMatchup(game);

        if (isFcsFallback(game)) {
          decorateMatchup(game);
        }
      };

    window.__hammerFcsRendererWrapped =
      true;
  }

  function watchProjectionBoard() {
    const container =
      document.getElementById(
        "projections-container"
      );

    if (!container) {
      window.setTimeout(
        watchProjectionBoard,
        100
      );
      return;
    }

    let queued = false;

    const queue = () => {
      if (queued) return;
      queued = true;

      requestAnimationFrame(() => {
        queued = false;
        decorateProjectionBoard();
      });
    };

    const observer =
      new MutationObserver(queue);

    observer.observe(
      container,
      {
        childList: true,
        subtree: true
      }
    );

    queue();

    window.addEventListener(
      "hammer:data-ready",
      () => {
        updateProjectionCopy();
        queue();
      }
    );
  }


  function updateProjectionCopy() {
    const subtitle =
      document.querySelector(
        "#view-projections .page-subtitle"
      );

    if (subtitle) {
      subtitle.innerHTML = `
        FBS and FBS-v-FCS game projections, sorted by model edge versus the
        current market. Full FBS matchups use the tracked Hammer Index model.
        FBS-v-FCS rows use a preliminary, untracked cross-division fallback.
      `;
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
          but they are <strong>UNTRACKED</strong> and do not count toward
          ATS, CLV or Signal Confidence records.
        </div>
      `;

      guideBody.appendChild(note);
    }
  }

  function start() {
    installStyles();
    updateProjectionCopy();
    wrapMatchupRenderer();
    watchProjectionBoard();

    window.setTimeout(
      decorateProjectionBoard,
      250
    );

    window.setTimeout(
      decorateProjectionBoard,
      800
    );

    window.setTimeout(
      decorateProjectionBoard,
      1600
    );
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
