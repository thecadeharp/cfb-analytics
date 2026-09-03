(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // sort-tables.js
  //
  // 1) Keeps Team Ratings / Portal / Variance tables sortable.
  // 2) Adds a presentation-only game-status layer to the Projections board.
  //
  // Game status rules:
  //   UPCOMING -> normal projection row
  //   LIVE     -> red LIVE badge + current score; pregame model stays frozen
  //   FINAL    -> existing settled renderer wins when available
  //            -> otherwise show FINAL · NOT GRADED for pre-tracking games
  //
  // Model A is NEVER recalculated here.
  // ==========================================================================

  const TABLE_SELECTOR = [
    "#view-ratings table",
    "#view-portal table",
    "#view-variance table"
  ].join(", ");

  const LIVE_URL =
    "./data/live_scores.json";

  const RESULTS_URL =
    "./data/results.json";

  const state =
    new WeakMap();

  let liveGames = [];
  let completedGames = [];

  let statusRefreshTimer = null;
  let decorationQueued = false;
  let decorating = false;

  const TEAM_ALIASES =
    new Map([
      ["miamifla", "miamifl"],
      ["miamiflorida", "miamifl"],
      ["olemiss", "mississippi"],
      [
        "southernmiss",
        "southernmississippi"
      ],
      ["utsa", "texassanantonio"],
      ["utep", "texaselpaso"],
      ["ucf", "centralflorida"],
      ["byu", "brighamyoung"],
      ["lsu", "louisianastate"],
      ["smu", "southernmethodist"],
      ["tcu", "texaschristian"],
      ["usc", "southerncalifornia"]
    ]);

  function installStyles() {
    if (
      document.getElementById(
        "hammer-sortable-table-styles"
      )
    ) {
      return;
    }

    const style =
      document.createElement(
        "style"
      );

    style.id =
      "hammer-sortable-table-styles";

    style.textContent = `
      .hammer-sortable-table thead th[data-sortable-column] {
        position: relative;
        cursor: pointer;
        user-select: none;
        transition:
          color 0.15s ease,
          background 0.15s ease;
      }

      .hammer-sortable-table thead th[data-sortable-column]:hover {
        color: var(--text);
        background: rgba(24, 33, 43, 0.035);
      }

      .hammer-sort-label {
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }

      .hammer-sort-arrow {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 13px;
        height: 13px;
        color: var(--muted-light);
        font-family: var(--mono);
        font-size: 10px;
        font-weight: 700;
        line-height: 1;
        opacity: 0.55;
        transition:
          opacity 0.15s ease,
          color 0.15s ease;
      }

      .hammer-sortable-table
      thead
      th[data-sortable-column]:hover
      .hammer-sort-arrow {
        opacity: 1;
      }

      .hammer-sortable-table
      thead
      th[data-sort-direction="asc"],
      .hammer-sortable-table
      thead
      th[data-sort-direction="desc"] {
        color: var(--text);
        background: rgba(24, 33, 43, 0.045);
      }

      .hammer-sortable-table
      thead
      th[data-sort-direction="asc"]
      .hammer-sort-arrow,
      .hammer-sortable-table
      thead
      th[data-sort-direction="desc"]
      .hammer-sort-arrow {
        color: var(--green);
        opacity: 1;
      }

      .hammer-live-row {
        background: #fffafa !important;
      }

      .hammer-live-row:hover {
        background: #fff6f6 !important;
        box-shadow:
          inset 3px 0 0 #c62828
          !important;
      }

      .hammer-live-badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 5px;

        margin-top: 6px;
        padding: 4px 7px;

        border:
          1px solid #e2a1a1;
        border-radius: 999px;

        background: #fdeaea;
        color: #b71c1c;

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 1px;
        line-height: 1;
        text-transform: uppercase;
      }

      .hammer-live-dot {
        width: 6px;
        height: 6px;

        border-radius: 999px;
        background: #d71920;

        box-shadow:
          0 0 0 3px
          rgba(215, 25, 32, 0.10);
      }

      .hammer-live-detail {
        margin-left: 6px;

        color: #9b3131;

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.25px;
      }

      .hammer-live-score,
      .hammer-final-score {
        margin-left: auto;
        padding-left: 10px;

        font-family: var(--mono);
        font-size: 15px;
        font-weight: 900;

        color: var(--ink);
      }

      .hammer-final-untracked-row {
        background:
          #fafaf8 !important;
      }

      .hammer-final-untracked-label {
        display: inline-flex;
        align-items: center;

        margin-top: 6px;
        padding: 4px 7px;

        border:
          1px solid var(--border);
        border-radius: 999px;

        background: #f1f1ee;
        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 900;
        letter-spacing: 0.8px;
        line-height: 1;
        text-transform: uppercase;
      }

      .hammer-untracked-status {
        display: inline-flex;
        justify-content: center;

        border:
          1px solid var(--border);
        border-radius: 999px;

        padding: 5px 8px;

        background: #f4f4f2;
        color: var(--muted);

        font-family: var(--mono);
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.4px;

        white-space: nowrap;
      }

      @media (max-width: 600px) {
        .hammer-sortable-table thead th[data-sortable-column] {
          touch-action: manipulation;
        }

        .hammer-sort-label {
          gap: 5px;
        }

        .hammer-sort-arrow {
          width: 12px;
          font-size: 9px;
        }
      }
    `;

    document.head.appendChild(
      style
    );
  }

  // ==========================================================================
  // SORTABLE TABLES
  // ==========================================================================

  function cleanText(value) {
    return String(
      value ?? ""
    )
      .replace(
        /\s+/g,
        " "
      )
      .trim();
  }

  function isMissing(value) {
    const text =
      cleanText(value)
        .toLowerCase();

    return (
      text === "" ||
      text === "—" ||
      text === "-" ||
      text === "n/a" ||
      text === "na" ||
      text === "null" ||
      text === "undefined"
    );
  }

  function numericValue(value) {
    const text =
      cleanText(value);

    if (isMissing(text)) {
      return null;
    }

    const match =
      text.match(
        /[+-]?(?:\d+(?:,\d{3})*|\d*\.\d+)/
      );

    if (!match) {
      return null;
    }

    const number =
      Number(
        match[0]
          .replace(
            /,/g,
            ""
          )
      );

    return (
      Number.isFinite(number)
        ? number
        : null
    );
  }

  function columnLooksNumeric(
    rows,
    columnIndex
  ) {
    let numeric = 0;
    let text = 0;

    rows
      .slice(
        0,
        25
      )
      .forEach(row => {
        const cell =
          row.cells[
            columnIndex
          ];

        if (!cell) {
          return;
        }

        const value =
          cleanText(
            cell.textContent
          );

        if (isMissing(value)) {
          return;
        }

        if (
          numericValue(value)
          !== null
        ) {
          numeric += 1;
        } else {
          text += 1;
        }
      });

    return (
      numeric > 0 &&
      numeric >= text
    );
  }

  function compareMissing(
    aMissing,
    bMissing
  ) {
    if (
      aMissing &&
      bMissing
    ) {
      return 0;
    }

    if (aMissing) {
      return 1;
    }

    if (bMissing) {
      return -1;
    }

    return null;
  }

  function compareNumeric(
    a,
    b,
    direction
  ) {
    const aNumber =
      numericValue(a);

    const bNumber =
      numericValue(b);

    const missingResult =
      compareMissing(
        aNumber === null,
        bNumber === null
      );

    if (
      missingResult
      !== null
    ) {
      return missingResult;
    }

    return (
      direction === "asc"
        ? aNumber - bNumber
        : bNumber - aNumber
    );
  }

  function compareText(
    a,
    b,
    direction
  ) {
    const aText =
      cleanText(a);

    const bText =
      cleanText(b);

    const missingResult =
      compareMissing(
        isMissing(aText),
        isMissing(bText)
      );

    if (
      missingResult
      !== null
    ) {
      return missingResult;
    }

    const result =
      aText.localeCompare(
        bText,
        undefined,
        {
          numeric: true,
          sensitivity: "base"
        }
      );

    return (
      direction === "asc"
        ? result
        : -result
    );
  }

  function resetHeaders(
    table,
    activeHeader
  ) {
    table
      .querySelectorAll(
        "thead th[data-sortable-column]"
      )
      .forEach(header => {
        if (
          header
          === activeHeader
        ) {
          return;
        }

        header.removeAttribute(
          "data-sort-direction"
        );

        const arrow =
          header.querySelector(
            ".hammer-sort-arrow"
          );

        if (arrow) {
          arrow.textContent =
            "↕";
        }

        header.setAttribute(
          "aria-sort",
          "none"
        );
      });
  }

  function updateActiveHeader(
    header,
    direction
  ) {
    header.setAttribute(
      "data-sort-direction",
      direction
    );

    header.setAttribute(
      "aria-sort",
      direction === "asc"
        ? "ascending"
        : "descending"
    );

    const arrow =
      header.querySelector(
        ".hammer-sort-arrow"
      );

    if (arrow) {
      arrow.textContent =
        direction === "asc"
          ? "↑"
          : "↓";
    }
  }

  function sortTable(
    table,
    columnIndex
  ) {
    const tbody =
      table.tBodies?.[0];

    if (!tbody) {
      return;
    }

    const rows =
      Array.from(
        tbody.rows
      );

    if (
      rows.length < 2
    ) {
      return;
    }

    const currentState =
      state.get(table) ?? {
        column: null,
        direction: null
      };

    const numeric =
      columnLooksNumeric(
        rows,
        columnIndex
      );

    let direction;

    if (
      currentState.column
      === columnIndex
    ) {
      direction =
        currentState.direction
          === "desc"
          ? "asc"
          : "desc";
    } else {
      direction =
        numeric
          ? "desc"
          : "asc";
    }

    const decoratedRows =
      rows.map(
        (
          row,
          originalIndex
        ) => ({
          row,
          originalIndex,
          value:
            row.cells[
              columnIndex
            ]?.textContent ?? ""
        })
      );

    decoratedRows.sort(
      (a, b) => {
        const result =
          numeric
            ? compareNumeric(
                a.value,
                b.value,
                direction
              )
            : compareText(
                a.value,
                b.value,
                direction
              );

        if (
          result === 0
        ) {
          return (
            a.originalIndex -
            b.originalIndex
          );
        }

        return result;
      }
    );

    const fragment =
      document
        .createDocumentFragment();

    decoratedRows
      .forEach(item => {
        fragment.appendChild(
          item.row
        );
      });

    tbody.appendChild(
      fragment
    );

    const header =
      table.tHead
        ?.rows?.[0]
        ?.cells?.[
          columnIndex
        ];

    if (header) {
      resetHeaders(
        table,
        header
      );

      updateActiveHeader(
        header,
        direction
      );
    }

    state.set(
      table,
      {
        column:
          columnIndex,
        direction
      }
    );
  }

  function makeHeaderSortable(
    table,
    header,
    columnIndex
  ) {
    if (
      header.hasAttribute(
        "data-sortable-column"
      )
    ) {
      return;
    }

    header.setAttribute(
      "data-sortable-column",
      String(columnIndex)
    );

    header.setAttribute(
      "role",
      "button"
    );

    header.setAttribute(
      "tabindex",
      "0"
    );

    header.setAttribute(
      "aria-sort",
      "none"
    );

    const originalContent =
      header.innerHTML;

    header.innerHTML = `
      <span class="hammer-sort-label">
        <span class="hammer-sort-title">
          ${originalContent}
        </span>

        <span
          class="hammer-sort-arrow"
          aria-hidden="true"
        >↕</span>
      </span>
    `;

    function activate(event) {
      if (
        event.type
          === "keydown" &&
        event.key
          !== "Enter" &&
        event.key
          !== " "
      ) {
        return;
      }

      if (
        event.type
        === "keydown"
      ) {
        event.preventDefault();
      }

      sortTable(
        table,
        columnIndex
      );
    }

    header.addEventListener(
      "click",
      activate
    );

    header.addEventListener(
      "keydown",
      activate
    );
  }

  function enhanceTable(
    table
  ) {
    if (!table?.tHead) {
      return;
    }

    if (
      table.dataset
        .hammerSortable
      === "true"
    ) {
      return;
    }

    const headerRow =
      table.tHead
        .rows?.[0];

    if (!headerRow) {
      return;
    }

    const bodyRows =
      Array.from(
        table
          .tBodies?.[0]
          ?.rows ?? []
      );

    if (
      !bodyRows.length
    ) {
      return;
    }

    table.classList.add(
      "hammer-sortable-table"
    );

    Array.from(
      headerRow.cells
    ).forEach(
      (
        header,
        columnIndex
      ) => {
        makeHeaderSortable(
          table,
          header,
          columnIndex
        );
      }
    );

    table.dataset
      .hammerSortable =
      "true";
  }

  function enhanceTables(
    root = document
  ) {
    root
      .querySelectorAll(
        TABLE_SELECTOR
      )
      .forEach(
        enhanceTable
      );
  }

  function observeTables() {
    const targets = [
      document.getElementById(
        "ratings-container"
      ),
      document.getElementById(
        "view-portal"
      ),
      document.getElementById(
        "view-variance"
      )
    ].filter(Boolean);

    targets.forEach(
      target => {
        const observer =
          new MutationObserver(
            () => {
              window
                .requestAnimationFrame(
                  () =>
                    enhanceTables(
                      document
                    )
                );
            }
          );

        observer.observe(
          target,
          {
            childList: true,
            subtree: true
          }
        );
      }
    );
  }

  // ==========================================================================
  // GAME STATUS
  // ==========================================================================

  function canonicalTeam(
    value
  ) {
    let text =
      String(
        value ?? ""
      )
        .trim()
        .toLowerCase()
        .replace(
          /&/g,
          "and"
        )
        .replace(
          /\buniversity\b/g,
          ""
        )
        .replace(
          /[^a-z0-9]+/g,
          ""
        );

    text =
      TEAM_ALIASES.get(
        text
      ) ?? text;

    return text;
  }

  function matchupKey(
    away,
    home
  ) {
    const awayKey =
      canonicalTeam(away);

    const homeKey =
      canonicalTeam(home);

    if (
      !awayKey ||
      !homeKey
    ) {
      return "";
    }

    return (
      `${awayKey}@${homeKey}`
    );
  }

  function gameMap(rows) {
    const map =
      new Map();

    (
      Array.isArray(rows)
        ? rows
        : []
    ).forEach(game => {
      if (
        !game ||
        typeof game
          !== "object"
      ) {
        return;
      }

      const key =
        matchupKey(
          game.away_team
            ?? game.awayTeam
            ?? game.away,
          game.home_team
            ?? game.homeTeam
            ?? game.home
        );

      if (key) {
        map.set(
          key,
          game
        );
      }
    });

    return map;
  }

  function projectionRowTeams(
    row
  ) {
    const names =
      Array.from(
        row.querySelectorAll(
          ".matchup-cell .team-name"
        )
      ).map(
        node =>
          cleanText(
            node.textContent
          )
      );

    if (
      names.length < 2
    ) {
      return null;
    }

    return {
      away: names[0],
      home: names[1]
    };
  }

  function rowKey(row) {
    const teams =
      projectionRowTeams(
        row
      );

    return teams
      ? matchupKey(
          teams.away,
          teams.home
        )
      : "";
  }

  function periodText(
    period
  ) {
    const text =
      cleanText(period);

    if (!text) {
      return "";
    }

    if (
      /^\d+$/.test(text)
    ) {
      const number =
        Number(text);

      if (
        number <= 4
      ) {
        return `Q${number}`;
      }

      return (
        number === 5
          ? "OT"
          : `${number - 4}OT`
      );
    }

    return text
      .toUpperCase();
  }

  function liveDetail(
    game
  ) {
    const parts = [];

    const period =
      periodText(
        game?.period
          ?? game
            ?.currentPeriod
          ?? game?.quarter
      );

    const clock =
      cleanText(
        game?.clock
          ?? game
            ?.contestClock
          ?? ""
      );

    if (period) {
      parts.push(
        period
      );
    }

    if (clock) {
      parts.push(
        clock
      );
    }

    return parts.join(
      " · "
    );
  }

  function setSecondary(
    cell,
    text
  ) {
    if (!cell) {
      return;
    }

    let secondary =
      cell.querySelector(
        ".line-secondary"
      );

    if (!secondary) {
      secondary =
        document
          .createElement(
            "div"
          );

      secondary.className =
        "line-secondary";

      cell.appendChild(
        secondary
      );
    }

    secondary.textContent =
      text;
  }

  function setPrimary(
    cell,
    text
  ) {
    if (!cell) {
      return;
    }

    let primary =
      cell.querySelector(
        ".line-primary"
      );

    if (!primary) {
      primary =
        document
          .createElement(
            "div"
          );

      primary.className =
        "line-primary";

      cell.prepend(
        primary
      );
    }

    primary.textContent =
      text;
  }

  function removeStatusArtifacts(
    row
  ) {
    row
      .querySelectorAll(
        ".hammer-live-score, " +
        ".hammer-final-score, " +
        ".hammer-live-badge, " +
        ".hammer-live-detail, " +
        ".hammer-final-untracked-label"
      )
      .forEach(
        node =>
          node.remove()
      );

    row.classList.remove(
      "hammer-live-row",
      "hammer-final-untracked-row"
    );
  }

  function appendTeamScores(
    row,
    awayPoints,
    homePoints,
    className
  ) {
    const lines =
      row.querySelectorAll(
        ".matchup-cell .team-line"
      );

    if (
      lines.length < 2
    ) {
      return;
    }

    const awayScore =
      document.createElement(
        "span"
      );

    awayScore.className =
      className;

    awayScore.textContent =
      Number.isFinite(
        Number(
          awayPoints
        )
      )
        ? String(
            Number(
              awayPoints
            )
          )
        : "—";

    const homeScore =
      document.createElement(
        "span"
      );

    homeScore.className =
      className;

    homeScore.textContent =
      Number.isFinite(
        Number(
          homePoints
        )
      )
        ? String(
            Number(
              homePoints
            )
          )
        : "—";

    lines[0].appendChild(
      awayScore
    );

    lines[1].appendChild(
      homeScore
    );
  }

  function statusMetaContainer(
    row
  ) {
    const matchupCell =
      row.querySelector(
        ".matchup-cell"
      );

    if (!matchupCell) {
      return null;
    }

    let container =
      matchupCell
        .querySelector(
          ".hammer-game-status-meta"
        );

    if (!container) {
      container =
        document.createElement(
          "div"
        );

      container.className =
        "hammer-game-status-meta";

      matchupCell.appendChild(
        container
      );
    } else {
      container.innerHTML =
        "";
    }

    return container;
  }

  function decorateLiveRow(
    row,
    game
  ) {
    removeStatusArtifacts(
      row
    );

    row.dataset
      .hammerGameState =
      "live";

    row.classList.add(
      "hammer-live-row"
    );

    appendTeamScores(
      row,
      game?.away_points,
      game?.home_points,
      "hammer-live-score"
    );

    const meta =
      statusMetaContainer(
        row
      );

    if (meta) {
      const badge =
        document.createElement(
          "span"
        );

      badge.className =
        "hammer-live-badge";

      badge.innerHTML =
        '<span class="hammer-live-dot"></span>LIVE';

      meta.appendChild(
        badge
      );

      const detail =
        liveDetail(game);

      if (detail) {
        const detailNode =
          document.createElement(
            "span"
          );

        detailNode.className =
          "hammer-live-detail";

        detailNode.textContent =
          detail;

        meta.appendChild(
          detailNode
        );
      }
    }

    const cells =
      row.cells;

    setSecondary(
      cells?.[1],
      "Pregame Hammer fair line"
    );

    const marketPrimary =
      cleanText(
        cells?.[2]
          ?.querySelector(
            ".line-primary"
          )
          ?.textContent
      );

    setSecondary(
      cells?.[2],
      isMissing(
        marketPrimary
      )
        ? "Pregame market unavailable"
        : "Pregame market snapshot"
    );

    setSecondary(
      cells?.[3],
      "Pregame projected total"
    );

    const note =
      cells?.[4]
        ?.querySelector(
          ".disagreement-note"
        );

    if (
      note &&
      !note.textContent
        .startsWith(
          "Pregame · "
        )
    ) {
      note.textContent =
        `Pregame · ${
          cleanText(
            note.textContent
          )
        }`;
    }
  }

  function decorateUntrackedFinalRow(
    row,
    game
  ) {
    removeStatusArtifacts(
      row
    );

    row.dataset
      .hammerGameState =
      "final";

    row.classList.add(
      "hammer-final-untracked-row"
    );

    appendTeamScores(
      row,
      game?.away_points,
      game?.home_points,
      "hammer-final-score"
    );

    const meta =
      statusMetaContainer(
        row
      );

    if (meta) {
      const label =
        document.createElement(
          "span"
        );

      label.className =
        "hammer-final-untracked-label";

      label.textContent =
        "FINAL · NOT GRADED";

      meta.appendChild(
        label
      );
    }

    const cells =
      row.cells;

    setSecondary(
      cells?.[1],
      "Historical model fair line"
    );

    setPrimary(
      cells?.[2],
      "NOT TRACKED"
    );

    setSecondary(
      cells?.[2],
      "No prospective market snapshot"
    );

    setSecondary(
      cells?.[3],
      "Historical projected total"
    );

    if (cells?.[4]) {
      cells[4].innerHTML = `
        <span class="hammer-untracked-status">
          NOT GRADED
        </span>

        <div class="disagreement-note">
          Pre-tracking game
        </div>
      `;
    }

    if (cells?.[5]) {
      cells[5].innerHTML = `
        <span class="hammer-untracked-status">
          UNTRACKED
        </span>
      `;
    }

    if (cells?.[6]) {
      cells[6].innerHTML = `
        <span class="hammer-untracked-status">
          —
        </span>

        <div class="signal-record">
          Not included in prospective record
        </div>
      `;
    }
  }

  function markSettledRow(
    row
  ) {
    row.dataset
      .hammerGameState =
      "final";
  }

  function reorderProjectionRows() {
    const tbody =
      document.querySelector(
        "#projections-container " +
        ".projection-table tbody"
      );

    if (!tbody) {
      return;
    }

    const rows =
      Array.from(
        tbody.querySelectorAll(
          ":scope > tr.game-row"
        )
      );

    if (
      rows.length < 2
    ) {
      return;
    }

    const priority = {
      upcoming: 0,
      live: 1,
      final: 2
    };

    const decorated =
      rows.map(
        (
          row,
          index
        ) => ({
          row,
          index,
          priority:
            priority[
              row.dataset
                .hammerGameState
              ?? "upcoming"
            ]
            ?? 0
        })
      );

    const ordered =
      [...decorated]
        .sort(
          (a, b) =>
            a.priority -
              b.priority ||
            a.index -
              b.index
        );

    const changed =
      ordered.some(
        (
          item,
          index
        ) =>
          item.row
          !== rows[index]
      );

    if (!changed) {
      return;
    }

    const fragment =
      document
        .createDocumentFragment();

    ordered.forEach(
      item =>
        fragment.appendChild(
          item.row
        )
    );

    tbody.appendChild(
      fragment
    );
  }

  function decorateProjectionRows() {
    if (decorating) {
      return;
    }

    decorating = true;

    try {
      const liveByMatchup =
        gameMap(
          liveGames
        );

      const finalByMatchup =
        gameMap(
          completedGames
        );

      const rows =
        document.querySelectorAll(
          "#projections-container " +
          ".projection-table tbody " +
          "tr.game-row"
        );

      rows.forEach(
        row => {
          // A prospectively settled game already has
          // the richer ux-v2 FINAL renderer.
          if (
            row.classList
              .contains(
                "completed-row"
              )
          ) {
            markSettledRow(
              row
            );

            return;
          }

          const key =
            rowKey(row);

          if (!key) {
            row.dataset
              .hammerGameState =
              "upcoming";

            return;
          }

          const live =
            liveByMatchup.get(
              key
            );

          if (live) {
            decorateLiveRow(
              row,
              live
            );

            return;
          }

          const final =
            finalByMatchup.get(
              key
            );

          if (final) {
            decorateUntrackedFinalRow(
              row,
              final
            );

            return;
          }

          row.dataset
            .hammerGameState =
            "upcoming";
        }
      );

      reorderProjectionRows();

    } finally {
      decorating = false;
    }
  }

  function queueProjectionDecoration() {
    if (
      decorationQueued
    ) {
      return;
    }

    decorationQueued =
      true;

    window
      .requestAnimationFrame(
        () => {
          decorationQueued =
            false;

          decorateProjectionRows();
        }
      );
  }

  async function fetchJson(
    url
  ) {
    const separator =
      url.includes("?")
        ? "&"
        : "?";

    const response =
      await fetch(
        `${url}${separator}t=${
          Date.now()
        }`,
        {
          cache: "no-store"
        }
      );

    if (!response.ok) {
      throw new Error(
        `${url} returned ${
          response.status
        }`
      );
    }

    return response.json();
  }

  async function refreshGameStatusData() {
    const [
      liveResult,
      finalResult
    ] =
      await Promise.allSettled(
        [
          fetchJson(
            LIVE_URL
          ),
          fetchJson(
            RESULTS_URL
          )
        ]
      );

    if (
      liveResult.status
      === "fulfilled"
    ) {
      liveGames =
        Array.isArray(
          liveResult.value
            ?.games
        )
          ? liveResult
              .value
              .games
          : [];
    }

    if (
      finalResult.status
      === "fulfilled"
    ) {
      completedGames =
        Array.isArray(
          finalResult.value
            ?.games
        )
          ? finalResult
              .value
              .games
          : [];
    }

    queueProjectionDecoration();
  }

  function observeProjectionRows() {
    const target =
      document.getElementById(
        "projections-container"
      );

    if (!target) {
      return;
    }

    const observer =
      new MutationObserver(
        () => {
          if (decorating) {
            return;
          }

          queueProjectionDecoration();
        }
      );

    observer.observe(
      target,
      {
        childList: true,
        subtree: true
      }
    );
  }

  function startGameStatusPolling() {
    refreshGameStatusData()
      .catch(
        () => {}
      );

    if (
      statusRefreshTimer
    ) {
      window.clearInterval(
        statusRefreshTimer
      );
    }

    // Open browsers check once a minute.
    // The actual source workflow refreshes every 10 minutes.
    statusRefreshTimer =
      window.setInterval(
        () => {
          refreshGameStatusData()
            .catch(
              () => {}
            );
        },
        60_000
      );
  }

  // ==========================================================================
  // STARTUP
  // ==========================================================================

  function start() {
    installStyles();

    enhanceTables(
      document
    );

    observeTables();

    observeProjectionRows();

    startGameStatusPolling();

    window.setTimeout(
      () => {
        enhanceTables(
          document
        );

        queueProjectionDecoration();
      },
      250
    );

    window.setTimeout(
      () => {
        enhanceTables(
          document
        );

        queueProjectionDecoration();
      },
      1000
    );
  }

  document.addEventListener(
    "hammer:data-ready",
    () => {
      window
        .requestAnimationFrame(
          () => {
            enhanceTables(
              document
            );

            queueProjectionDecoration();
          }
        );
    }
  );

  if (
    document.readyState
    === "loading"
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
