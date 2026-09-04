(() => {
  "use strict";

  const RESULTS_URL = "./data/results.json";
  const STYLE_ID = "hammer-final-matchup-styles";

  let finalGames = [];
  let lastMatchupKey = "";

  function canonical(value) {
    return String(value || "")
      .toLowerCase()
      .replaceAll(".", "")
      .replaceAll("'", "")
      .replaceAll("’", "")
      .replaceAll("-", " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function equivalentTeamName(a, b) {
    const left = canonical(a);
    const right = canonical(b);

    if (left === right) {
      return true;
    }

    const aliases = {
      "umass": "massachusetts",
      "massachusetts": "massachusetts",

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

      "southern california": "usc",
      "usc": "usc"
    };

    return (aliases[left] || left) === (aliases[right] || right);
  }

  function installStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }

    const style = document.createElement("style");
    style.id = STYLE_ID;

    style.textContent = `
      #view-matchup .projected-score-card.hammer-final-score-card {
        border-color: var(--border-dark);
      }

      #view-matchup .hammer-final-score-card .projected-score-title {
        color: var(--muted);
      }

      #view-matchup .hammer-final-score-status {
        display: inline-flex;
        align-items: center;
        justify-content: center;

        padding: 5px 10px;
        margin-bottom: 10px;

        border: 1px solid var(--border);
        border-radius: 999px;

        color: var(--text);
        background: var(--surface-soft);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.8px;
      }

      #view-matchup .hammer-pregame-projection {
        display: grid;
        grid-template-columns: 1fr auto 1fr;
        align-items: center;
        gap: 18px;

        margin-top: 14px;
        padding-top: 14px;

        border-top: 1px solid var(--border);
      }

      #view-matchup .hammer-pregame-team:last-child {
        text-align: right;
      }

      #view-matchup .hammer-pregame-label {
        margin-bottom: 8px;

        color: var(--muted);

        font-family: var(--mono);
        font-size: 8px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
      }

      #view-matchup .hammer-pregame-team-name {
        color: var(--muted);
        font-size: 11px;
        font-weight: 600;
      }

      #view-matchup .hammer-pregame-score {
        margin-top: 3px;

        color: var(--muted);

        font-family: var(--mono);
        font-size: 19px;
        font-weight: 700;
      }

      #view-matchup .hammer-pregame-divider {
        color: var(--muted);

        font-family: var(--mono);
        font-size: 10px;
        font-weight: 700;
      }

      #view-matchup .hammer-pregame-note {
        margin-top: 10px;

        color: var(--muted);

        font-family: var(--mono);
        font-size: 8px;
        line-height: 1.55;
      }

      @media (max-width: 600px) {
        #view-matchup .hammer-pregame-projection {
          gap: 10px;
        }

        #view-matchup .hammer-pregame-score {
          font-size: 17px;
        }

        #view-matchup .hammer-pregame-team-name {
          font-size: 10px;
        }
      }
    `;

    document.head.appendChild(style);
  }

  async function loadFinals() {
    try {
      const response = await fetch(
        `${RESULTS_URL}?v=${Date.now()}`,
        {
          cache: "no-store"
        }
      );

      if (!response.ok) {
        return;
      }

      const payload = await response.json();

      finalGames = Array.isArray(payload?.games)
        ? payload.games.filter(game =>
            String(game?.game_state || "").toLowerCase() === "final"
          )
        : [];
    } catch (error) {
      console.warn(
        "[Hammer Final Matchup] Could not load finals.",
        error
      );
    }
  }

  function currentMatchupTeams() {
    const title =
      document.querySelector(
        "#view-matchup .page-title"
      ) ||
      document.querySelector(
        "#view-matchup h1"
      );

    if (!title) {
      return null;
    }

    const text =
      String(title.textContent || "")
        .replace(/\s+/g, " ")
        .trim();

    if (!text) {
      return null;
    }

    const separators = [
      " @ ",
      " vs. ",
      " vs "
    ];

    for (const separator of separators) {
      if (text.includes(separator)) {
        const [away, home] =
          text.split(separator);

        if (away && home) {
          return {
            away: away.trim(),
            home: home.trim()
          };
        }
      }
    }

    return null;
  }

  function findFinalForCurrentMatchup() {
    const teams =
      currentMatchupTeams();

    if (!teams) {
      return null;
    }

    return finalGames.find(game =>
      equivalentTeamName(
        game?.away_team,
        teams.away
      ) &&
      equivalentTeamName(
        game?.home_team,
        teams.home
      )
    ) || null;
  }

  function getProjectedScore(card) {
    if (!card) {
      return null;
    }

    const teams =
      Array.from(
        card.querySelectorAll(
          ".projected-team"
        )
      );

    if (teams.length < 2) {
      return null;
    }

    const awayName =
      teams[0]
        .querySelector(
          ".projected-team-name"
        )
        ?.textContent
        ?.trim();

    const awayScore =
      teams[0]
        .querySelector(
          ".projected-team-score"
        )
        ?.textContent
        ?.trim();

    const homeName =
      teams[1]
        .querySelector(
          ".projected-team-name"
        )
        ?.textContent
        ?.trim();

    const homeScore =
      teams[1]
        .querySelector(
          ".projected-team-score"
        )
        ?.textContent
        ?.trim();

    if (
      !awayName ||
      !homeName ||
      awayScore === undefined ||
      homeScore === undefined
    ) {
      return null;
    }

    return {
      awayName,
      awayScore,
      homeName,
      homeScore
    };
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function applyFinalScore() {
    const view =
      document.querySelector(
        "#view-matchup"
      );

    if (
      !view ||
      !view.classList.contains("active")
    ) {
      lastMatchupKey = "";
      return;
    }

    const final =
      findFinalForCurrentMatchup();

    if (!final) {
      return;
    }

    const card =
      view.querySelector(
        ".projected-score-card"
      );

    if (!card) {
      return;
    }

    const matchupKey =
      [
        canonical(final.away_team),
        canonical(final.home_team),
        final.away_points,
        final.home_points
      ].join("|");

    if (
      card.dataset.hammerFinalApplied ===
        matchupKey &&
      lastMatchupKey === matchupKey
    ) {
      return;
    }

    const projection =
      getProjectedScore(card);

    if (!projection) {
      return;
    }

    const title =
      card.querySelector(
        ".projected-score-title"
      );

    const scoreTeams =
      Array.from(
        card.querySelectorAll(
          ".projected-team"
        )
      );

    if (
      !title ||
      scoreTeams.length < 2
    ) {
      return;
    }

    title.textContent =
      "Final Score";

    scoreTeams[0]
      .querySelector(
        ".projected-team-name"
      )
      .textContent =
        final.away_team;

    scoreTeams[0]
      .querySelector(
        ".projected-team-score"
      )
      .textContent =
        String(final.away_points);

    scoreTeams[1]
      .querySelector(
        ".projected-team-name"
      )
      .textContent =
        final.home_team;

    scoreTeams[1]
      .querySelector(
        ".projected-team-score"
      )
      .textContent =
        String(final.home_points);

    const middle =
      card.querySelector(
        ".projected-score-vs"
      ) ||
      card.querySelector(
        ".projected-score-middle"
      );

    if (middle) {
      middle.textContent = "FINAL";
    }

    let status =
      card.querySelector(
        ".hammer-final-score-status"
      );

    if (!status) {
      status =
        document.createElement("div");

      status.className =
        "hammer-final-score-status";

      status.textContent =
        "FINAL";

      title.insertAdjacentElement(
        "afterend",
        status
      );
    }

    const existing =
      card.querySelector(
        ".hammer-pregame-projection"
      );

    if (existing) {
      existing.remove();
    }

    const pregame =
      document.createElement("div");

    pregame.className =
      "hammer-pregame-projection";

    pregame.innerHTML = `
      <div class="hammer-pregame-team">
        <div class="hammer-pregame-label">
          Pregame Projection
        </div>

        <div class="hammer-pregame-team-name">
          ${escapeHtml(projection.awayName)}
        </div>

        <div class="hammer-pregame-score">
          ${escapeHtml(projection.awayScore)}
        </div>
      </div>

      <div class="hammer-pregame-divider">
        —
      </div>

      <div class="hammer-pregame-team">
        <div class="hammer-pregame-label">
          Pregame Projection
        </div>

        <div class="hammer-pregame-team-name">
          ${escapeHtml(projection.homeName)}
        </div>

        <div class="hammer-pregame-score">
          ${escapeHtml(projection.homeScore)}
        </div>
      </div>
    `;

    const note =
      document.createElement("div");

    note.className =
      "hammer-pregame-note";

    note.textContent =
      "Pregame model projection preserved for reference. Final score shown above.";

    card.appendChild(pregame);
    card.appendChild(note);

    card.classList.add(
      "hammer-final-score-card"
    );

    card.dataset.hammerFinalApplied =
      matchupKey;

    lastMatchupKey =
      matchupKey;
  }

  function scheduleApply() {
    requestAnimationFrame(() => {
      applyFinalScore();
    });

    setTimeout(
      applyFinalScore,
      75
    );

    setTimeout(
      applyFinalScore,
      250
    );
  }

  function installObserver() {
    const target =
      document.querySelector(
        "#view-matchup"
      );

    if (!target) {
      setTimeout(
        installObserver,
        250
      );

      return;
    }

    const observer =
      new MutationObserver(() => {
        scheduleApply();
      });

    observer.observe(
      target,
      {
        childList: true,
        subtree: true
      }
    );
  }

  async function start() {
    installStyles();

    await loadFinals();

    installObserver();

    scheduleApply();

    setInterval(
      async () => {
        await loadFinals();
        scheduleApply();
      },
      60000
    );
  }

  if (
    document.readyState === "loading"
  ) {
    document.addEventListener(
      "DOMContentLoaded",
      start,
      {
        once: true
      }
    );
  } else {
    start();
  }
})();
