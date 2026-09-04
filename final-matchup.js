(() => {
  "use strict";

  const RESULTS_URL = "./data/results.json";
  const STYLE_ID = "hammer-final-matchup-styles";

  let finalGames = [];
  let observer = null;

  // ==========================================================================
  // HELPERS
  // ==========================================================================

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/&/g, "and")
      .replace(/[.'’(),_-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizedTeam(value) {
    const text = canonical(value);

    const aliases = {
      "umass": "massachusetts",
      "massachusetts": "massachusetts",

      "usc": "southern california",
      "southern cal": "southern california",
      "southern california": "southern california",

      "jacksonville st": "jacksonville state",
      "jacksonville state": "jacksonville state",

      "north dakota st": "north dakota state",
      "north dakota state": "north dakota state",

      "new mexico st": "new mexico state",
      "new mexico state": "new mexico state",

      "florida st": "florida state",
      "florida state": "florida state",

      "sacramento st": "sacramento state",
      "sacramento state": "sacramento state",

      "eastern mich": "eastern michigan",
      "eastern michigan": "eastern michigan",

      "san jose st": "san jose state",
      "san jose state": "san jose state",

      "hawaii": "hawaii",
      "hawai i": "hawaii"
    };

    return aliases[text] || text;
  }

  function sameTeam(a, b) {
    return normalizedTeam(a) === normalizedTeam(b);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  // ==========================================================================
  // STYLES
  // ==========================================================================

  function installStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      #matchup-container .projected-score-card.hammer-final-score-card {
        border-color: var(--border-dark);
      }

      #matchup-container .hammer-final-score-card .projected-score-title {
        color: var(--muted);
      }

      #matchup-container .hammer-final-pregame-block {
        margin-top: 13px;
        padding-top: 12px;
        border-top: 1px solid #eeeeeb;
      }

      #matchup-container .hammer-final-pregame-heading {
        margin-bottom: 9px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
      }

      #matchup-container .hammer-final-pregame-score {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
        gap: 12px;
        align-items: center;
      }

      #matchup-container .hammer-final-pregame-team {
        min-width: 0;
      }

      #matchup-container .hammer-final-pregame-team:last-child {
        text-align: right;
      }

      #matchup-container .hammer-final-pregame-name {
        color: var(--muted);
        font-size: 10px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      #matchup-container .hammer-final-pregame-points {
        margin-top: 3px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 17px;
        font-weight: 700;
      }

      #matchup-container .hammer-final-pregame-separator {
        color: var(--muted);
        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
      }

      #matchup-container .hammer-final-pregame-note {
        margin-top: 9px;
        color: var(--muted);
        font-family: var(--mono);
        font-size: 8px;
        line-height: 1.5;
      }

      @media (max-width: 600px) {
        #matchup-container .hammer-final-pregame-score {
          gap: 8px;
        }

        #matchup-container .hammer-final-pregame-points {
          font-size: 15px;
        }
      }
    `;

    document.head.appendChild(style);
  }

  // ==========================================================================
  // RESULTS
  // ==========================================================================

  async function loadFinalResults() {
    try {
      const response = await fetch(
        `${RESULTS_URL}?v=${Date.now()}`,
        {
          cache: "no-store"
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json();

      finalGames = Array.isArray(payload?.games)
        ? payload.games.filter(game =>
            String(game?.game_state || "").toLowerCase() === "final"
          )
        : [];

      applyFinalToCurrentMatchup();
    } catch (error) {
      console.warn(
        "[Hammer Final Matchup] Results unavailable:",
        error
      );
    }
  }

  // ==========================================================================
  // SCORE CARD
  // ==========================================================================

  function currentScoreCard() {
    return document.querySelector(
      "#matchup-container .projected-score-card"
    );
  }

  function scoreCardTeams(card) {
    if (!card) return null;

    const teams = Array.from(
      card.querySelectorAll(".projected-team")
    );

    if (teams.length < 2) return null;

    const awayName = teams[0]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    const homeName = teams[1]
      .querySelector(".projected-team-name")
      ?.textContent
      ?.trim();

    if (!awayName || !homeName) return null;

    return {
      awayName,
      homeName,
      awayNode: teams[0],
      homeNode: teams[1]
    };
  }

  function findFinal(awayName, homeName) {
    return (
      finalGames.find(game =>
        sameTeam(game?.away_team, awayName) &&
        sameTeam(game?.home_team, homeName)
      ) || null
    );
  }

  function readPregameProjection(nodes) {
    const awayScore = nodes.awayNode
      .querySelector(".projected-team-score")
      ?.textContent
      ?.trim();

    const homeScore = nodes.homeNode
      .querySelector(".projected-team-score")
      ?.textContent
      ?.trim();

    if (
      awayScore === undefined ||
      awayScore === null ||
      homeScore === undefined ||
      homeScore === null
    ) {
      return null;
    }

    return {
      awayName: nodes.awayName,
      homeName: nodes.homeName,
      awayScore,
      homeScore
    };
  }

  function pregameMarkup(projection) {
    return `
      <div class="hammer-final-pregame-block">
        <div class="hammer-final-pregame-heading">
          Pregame Model Projection
        </div>

        <div class="hammer-final-pregame-score">
          <div class="hammer-final-pregame-team">
            <div class="hammer-final-pregame-name">
              ${escapeHtml(projection.awayName)}
            </div>
            <div class="hammer-final-pregame-points">
              ${escapeHtml(projection.awayScore)}
            </div>
          </div>

          <div class="hammer-final-pregame-separator">
            —
          </div>

          <div class="hammer-final-pregame-team">
            <div class="hammer-final-pregame-name">
              ${escapeHtml(projection.homeName)}
            </div>
            <div class="hammer-final-pregame-points">
              ${escapeHtml(projection.homeScore)}
            </div>
          </div>
        </div>

        <div class="hammer-final-pregame-note">
          Pregame projection preserved for reference. Actual final score shown above.
        </div>
      </div>
    `;
  }

  function applyFinalToCurrentMatchup() {
    const card = currentScoreCard();

    if (!card) return;

    // If this exact rendered card has already been converted,
    // do not touch it again.
    if (card.dataset.hammerFinalApplied === "true") {
      return;
    }

    const nodes = scoreCardTeams(card);

    if (!nodes) return;

    const final = findFinal(
      nodes.awayName,
      nodes.homeName
    );

    if (!final) {
      return;
    }

    const projection = readPregameProjection(nodes);

    if (!projection) return;

    const awayPoints = Number(final.away_points);
    const homePoints = Number(final.home_points);

    if (
      !Number.isFinite(awayPoints) ||
      !Number.isFinite(homePoints)
    ) {
      return;
    }

    const title = card.querySelector(
      ".projected-score-title"
    );

    const separator = card.querySelector(
      ".projected-score-separator"
    );

    const awayNameNode = nodes.awayNode.querySelector(
      ".projected-team-name"
    );

    const awayScoreNode = nodes.awayNode.querySelector(
      ".projected-team-score"
    );

    const homeNameNode = nodes.homeNode.querySelector(
      ".projected-team-name"
    );

    const homeScoreNode = nodes.homeNode.querySelector(
      ".projected-team-score"
    );

    if (
      !title ||
      !awayNameNode ||
      !awayScoreNode ||
      !homeNameNode ||
      !homeScoreNode
    ) {
      return;
    }

    // Mark FIRST so our own DOM changes cannot cause an observer loop.
    card.dataset.hammerFinalApplied = "true";

    title.textContent = "Final Score";

    awayNameNode.textContent =
      final.away_team || projection.awayName;

    awayScoreNode.textContent =
      String(awayPoints);

    homeNameNode.textContent =
      final.home_team || projection.homeName;

    homeScoreNode.textContent =
      String(homePoints);

    if (separator) {
      separator.textContent = "FINAL";
    }

    // Keep the existing fair-line / projected-total metadata untouched.
    // It is still valuable as the pregame model audit.

    const oldPregame = card.querySelector(
      ".hammer-final-pregame-block"
    );

    if (oldPregame) {
      oldPregame.remove();
    }

    card.insertAdjacentHTML(
      "beforeend",
      pregameMarkup(projection)
    );

    card.classList.add(
      "hammer-final-score-card"
    );
  }

  // ==========================================================================
  // OBSERVER
  // ==========================================================================

  function scheduleApply() {
    requestAnimationFrame(
      applyFinalToCurrentMatchup
    );
  }

  function installObserver() {
    const container = document.getElementById(
      "matchup-container"
    );

    if (!container) {
      setTimeout(
        installObserver,
        250
      );

      return;
    }

    if (observer) {
      observer.disconnect();
    }

    observer = new MutationObserver(() => {
      scheduleApply();
    });

    observer.observe(
      container,
      {
        childList: true,
        subtree: true
      }
    );

    scheduleApply();
  }

  // ==========================================================================
  // START
  // ==========================================================================

  async function start() {
    installStyles();

    await loadFinalResults();

    installObserver();

    // Keep results current so a game that goes final while
    // the site is open can convert automatically.
    setInterval(
      loadFinalResults,
      60000
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
