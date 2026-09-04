(() => {
  "use strict";

  // ==========================================================================
  // THE HAMMER INDEX
  // dossier-ranks.js
  //
  // Purpose:
  // Add an FBS overall rank beside every rankable numerical metric
  // in Team Dossier.
  //
  // Existing stored ranks are preserved.
  // Missing ranks are calculated dynamically from the same dataset
  // used to display the metric.
  // ==========================================================================


  // ==========================================================================
  // BASIC HELPERS
  // ==========================================================================

  function hasNumericValue(value) {
    return (
      value !== null &&
      value !== undefined &&
      value !== "" &&
      Number.isFinite(Number(value))
    );
  }


  function teamList() {
    try {
      return Object.values(teams || {});
    } catch (_) {
      return [];
    }
  }


  function rosterTeams() {
    try {
      return rosterFoundationData?.teams || {};
    } catch (_) {
      return {};
    }
  }


  function externalTeams() {
    try {
      return externalRatingsData?.teams || {};
    } catch (_) {
      return {};
    }
  }


  function currentRoster(teamName) {
    return rosterTeams()?.[teamName] || null;
  }


  function currentExternal(teamName) {
    return externalTeams()?.[teamName] || null;
  }


  // ==========================================================================
  // RANK ENGINE
  // ==========================================================================

  function numericRank(
    targetValue,
    comparisonValues,
    higherIsBetter = true
  ) {
    if (!hasNumericValue(targetValue)) {
      return null;
    }

    const target =
      Number(targetValue);

    const values =
      comparisonValues
        .filter(hasNumericValue)
        .map(Number);

    if (!values.length) {
      return null;
    }

    const betterCount =
      values.filter(value =>
        higherIsBetter
          ? value > target
          : value < target
      ).length;

    return betterCount + 1;
  }


  function formattedRank(rank) {
    if (
      !rank ||
      !Number.isFinite(Number(rank))
    ) {
      return "";
    }

    return `#${Number(rank)} Overall`;
  }


  function rankFromTeams(
    currentTeam,
    getter,
    higherIsBetter = true,
    eligibility = null
  ) {
    if (!currentTeam) {
      return "";
    }

    const target =
      getter(currentTeam);

    if (!hasNumericValue(target)) {
      return "";
    }

    const eligibleTeams =
      teamList().filter(team => {
        if (
          typeof eligibility ===
          "function" &&
          !eligibility(team)
        ) {
          return false;
        }

        return hasNumericValue(
          getter(team)
        );
      });

    return formattedRank(
      numericRank(
        target,
        eligibleTeams.map(getter),
        higherIsBetter
      )
    );
  }


  function rankFromRoster(
    teamName,
    field,
    higherIsBetter = true
  ) {
    const rows =
      rosterTeams();

    const current =
      rows?.[teamName];

    const target =
      current?.[field];

    if (!hasNumericValue(target)) {
      return "";
    }

    return formattedRank(
      numericRank(
        target,
        Object.values(rows)
          .map(row => row?.[field])
          .filter(hasNumericValue),
        higherIsBetter
      )
    );
  }


  function rankFromExternal(
    teamName,
    field,
    higherIsBetter = true
  ) {
    const rows =
      externalTeams();

    const current =
      rows?.[teamName];

    const target =
      current?.[field];

    if (!hasNumericValue(target)) {
      return "";
    }

    return formattedRank(
      numericRank(
        target,
        Object.values(rows)
          .map(row => row?.[field])
          .filter(hasNumericValue),
        higherIsBetter
      )
    );
  }


  // ==========================================================================
  // LIVE 2026 HELPERS
  // ==========================================================================

  function liveSection(
    team,
    side
  ) {
    return (
      team?.[side]?.live_2026 ||
      {}
    );
  }


  function liveNumber(
    team,
    side,
    field
  ) {
    const value =
      liveSection(
        team,
        side
      )?.[field];

    return hasNumericValue(value)
      ? Number(value)
      : null;
  }


  function livePlays(
    team,
    side
  ) {
    const value =
      liveSection(
        team,
        side
      )?.n_plays;

    return hasNumericValue(value)
      ? Number(value)
      : 0;
  }


  function hasLiveSample(
    team,
    side
  ) {
    return (
      livePlays(
        team,
        side
      ) > 0
    );
  }


  function liveRank(
    currentTeam,
    side,
    field,
    higherIsBetter = true
  ) {
    return rankFromTeams(
      currentTeam,
      team =>
        liveNumber(
          team,
          side,
          field
        ),
      higherIsBetter,
      team =>
        hasLiveSample(
          team,
          side
        )
    );
  }


  // ==========================================================================
  // NET HELPERS
  // ==========================================================================

  function liveNet(
    team,
    field
  ) {
    const offense =
      liveNumber(
        team,
        "offense",
        field
      );

    const defense =
      liveNumber(
        team,
        "defense",
        field
      );

    if (
      !hasNumericValue(offense) ||
      !hasNumericValue(defense)
    ) {
      return null;
    }

    return (
      Number(offense) -
      Number(defense)
    );
  }


  function hasTwoSidedLiveSample(
    team
  ) {
    return (
      hasLiveSample(
        team,
        "offense"
      ) &&
      hasLiveSample(
        team,
        "defense"
      )
    );
  }


  function liveNetRank(
    currentTeam,
    field
  ) {
    return rankFromTeams(
      currentTeam,
      team =>
        liveNet(
          team,
          field
        ),
      true,
      hasTwoSidedLiveSample
    );
  }


  // ==========================================================================
  // MODEL / PRESEASON RANK HELPERS
  // ==========================================================================

  function modelOffenseRank(
    currentTeam,
    field,
    higherIsBetter = true
  ) {
    return rankFromTeams(
      currentTeam,
      team =>
        team?.offense?.[field],
      higherIsBetter
    );
  }


  function modelDefenseRank(
    currentTeam,
    field,
    lowerIsBetter = true
  ) {
    return rankFromTeams(
      currentTeam,
      team =>
        team?.defense?.[field],
      !lowerIsBetter
    );
  }


  function modelNetRank(
    currentTeam,
    field,
    higherIsBetter = true
  ) {
    return rankFromTeams(
      currentTeam,
      team =>
        team?.net?.[field],
      higherIsBetter
    );
  }


  // ==========================================================================
  // PANEL / ROW HELPERS
  // ==========================================================================

  function normalizedText(value) {
    return String(
      value || ""
    )
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }


  function panelTitleForRow(row) {
    const panel =
      row.closest(
        ".panel"
      );

    const title =
      panel?.querySelector(
        ".panel-title"
      );

    return normalizedText(
      title?.textContent
    );
  }


  function metricNameForRow(row) {
    const name =
      row.querySelector(
        ".metric-name"
      );

    return normalizedText(
      name?.textContent
    );
  }


  function metricValueForRow(row) {
    const value =
      row.querySelector(
        ".metric-value"
      );

    return String(
      value?.textContent || ""
    ).trim();
  }


  function rankCellForRow(row) {
    return row.querySelector(
      ".metric-rank"
    );
  }


  function rankCellHasUsefulContent(
    rankCell
  ) {
    if (!rankCell) {
      return false;
    }

    const text =
      String(
        rankCell.textContent || ""
      ).trim();

    return text.length > 0;
  }


  // ==========================================================================
  // RANK LOOKUP
  // ==========================================================================

  function calculatedRankForRow(
    team,
    row
  ) {
    const teamName =
      team?.team;

    const panel =
      panelTitleForRow(
        row
      );

    const metric =
      metricNameForRow(
        row
      );


    // ========================================================================
    // OFFENSIVE PROFILE
    // ========================================================================

    if (
      panel.includes(
        "offensive profile"
      )
    ) {
      switch (metric) {

        case "model epa / play":
          return modelOffenseRank(
            team,
            "epa_play",
            true
          );

        case "model success rate":
          return modelOffenseRank(
            team,
            "success_rate",
            true
          );

        case "2026 epa / pass":
          return liveRank(
            team,
            "offense",
            "epa_pass",
            true
          );

        case "2026 epa / rush":
          return liveRank(
            team,
            "offense",
            "epa_rush",
            true
          );

        case "2026 success rate":
          return liveRank(
            team,
            "offense",
            "success_rate",
            true
          );

        case "2026 explosive rate":
          return liveRank(
            team,
            "offense",
            "explosive_rate",
            true
          );

        case "2026 havoc allowed":
          return liveRank(
            team,
            "offense",
            "havoc_rate",
            false
          );

        default:
          return "";
      }
    }


    // ========================================================================
    // DEFENSIVE PROFILE
    // ========================================================================

    if (
      panel.includes(
        "defensive profile"
      )
    ) {
      switch (metric) {

        case "model epa / play":
          return modelDefenseRank(
            team,
            "epa_play",
            true
          );

        case "model success rate allowed":
          return modelDefenseRank(
            team,
            "success_rate",
            true
          );

        case "2026 epa / pass allowed":
          return liveRank(
            team,
            "defense",
            "epa_pass",
            false
          );

        case "2026 epa / rush allowed":
          return liveRank(
            team,
            "defense",
            "epa_rush",
            false
          );

        case "2026 success rate allowed":
          return liveRank(
            team,
            "defense",
            "success_rate",
            false
          );

        case "2026 explosive rate allowed":
          return liveRank(
            team,
            "defense",
            "explosive_rate",
            false
          );

        case "2026 havoc created":
          return liveRank(
            team,
            "defense",
            "havoc_rate",
            true
          );

        default:
          return "";
      }
    }


    // ========================================================================
    // NET EFFICIENCY
    // ========================================================================

    if (
      panel.includes(
        "net efficiency"
      )
    ) {
      switch (metric) {

        case "model net epa / play":
          return modelNetRank(
            team,
            "epa",
            true
          );

        case "model net success rate":
          return modelNetRank(
            team,
            "sr",
            true
          );

        case "2026 net epa / pass":
          return liveNetRank(
            team,
            "epa_pass"
          );

        case "2026 net epa / rush":
          return liveNetRank(
            team,
            "epa_rush"
          );

        case "2026 net success rate":
          return liveNetRank(
            team,
            "success_rate"
          );

        default:
          return "";
      }
    }


    // ========================================================================
    // RETURNING PRODUCTION
    // ========================================================================

    if (
      panel.includes(
        "returning production"
      )
    ) {
      switch (metric) {

        case "combined":
          return rankFromRoster(
            teamName,
            "returning_production_pct",
            true
          );

        case "offense":
          return rankFromRoster(
            teamName,
            "returning_offense_pct",
            true
          );

        case "defense":
          return rankFromRoster(
            teamName,
            "returning_defense_pct",
            true
          );

        case "returning players":
          return rankFromRoster(
            teamName,
            "returning_players",
            true
          );

        default:
          return "";
      }
    }


    // ========================================================================
    // TEAM TALENT
    // ========================================================================

    if (
      panel.includes(
        "team talent"
      )
    ) {
      switch (metric) {

        case "talent composite":
          return rankFromRoster(
            teamName,
            "talent_composite",
            true
          );

        case "blue-chip ratio":
          return rankFromRoster(
            teamName,
            "blue_chip_ratio_pct",
            true
          );

        case "rated recruits":
          return rankFromRoster(
            teamName,
            "rated_recruits",
            true
          );

        default:
          return "";
      }
    }


    // ========================================================================
    // STRENGTH & RESUME
    // ========================================================================

    if (
      panel.includes(
        "strength & resume"
      )
    ) {
      switch (metric) {

        case "fpi":
          return rankFromExternal(
            teamName,
            "fpi",
            true
          );

        /*
          ESPN only supplies the rank for these fields in our current
          snapshot, not an underlying public numerical rating.
          Existing rank-only display is therefore preserved.
        */

        default:
          return "";
      }
    }


    // ========================================================================
    // FPI COMPONENTS
    // ========================================================================

    if (
      panel.includes(
        "fpi components"
      )
    ) {
      switch (metric) {

        case "offensive component":
          return rankFromExternal(
            teamName,
            "fpi_offense",
            true
          );

        case "defensive component":
          return rankFromExternal(
            teamName,
            "fpi_defense",
            true
          );

        case "special teams component":
          return rankFromExternal(
            teamName,
            "fpi_special_teams",
            true
          );

        default:
          return "";
      }
    }


    return "";
  }


  // ==========================================================================
  // APPLY TO DOSSIER
  // ==========================================================================

  function applyDossierRanks(
    team
  ) {
    const container =
      document.getElementById(
        "dossier-container"
      );

    if (
      !container ||
      !team
    ) {
      return;
    }

    const rows =
      Array.from(
        container.querySelectorAll(
          ".metric-row"
        )
      );

    rows.forEach(row => {
      const rankCell =
        rankCellForRow(
          row
        );

      if (!rankCell) {
        return;
      }


      /*
        Preserve existing valid rank/context output.

        Example:
          #30
          #4 Overall
          #17 · 92 plays
      */

      if (
        rankCellHasUsefulContent(
          rankCell
        )
      ) {
        return;
      }


      /*
        If the displayed value itself is unavailable,
        do not create a fake rank.
      */

      const valueText =
        metricValueForRow(
          row
        );

      if (
        !valueText ||
        valueText === "—" ||
        valueText.toLowerCase() ===
          "pending"
      ) {
        return;
      }


      const rank =
        calculatedRankForRow(
          team,
          row
        );

      if (!rank) {
        return;
      }

      rankCell.textContent =
        rank;
    });
  }


  // ==========================================================================
  // WRAP THE EXISTING DOSSIER RENDERER
  // ==========================================================================

  function installDossierRankSystem() {
    if (
      typeof renderDossier !==
      "function"
    ) {
      window.setTimeout(
        installDossierRankSystem,
        100
      );

      return;
    }

    if (
      renderDossier
        .__hammerRanksInstalled
    ) {
      return;
    }

    const baseRenderDossier =
      renderDossier;

    const rankedRenderer =
      function rankedRenderDossier(
        team
      ) {
        baseRenderDossier(
          team
        );

        /*
          Apply immediately and again next frame in case
          another frontend layer modifies the dossier DOM.
        */

        applyDossierRanks(
          team
        );

        window.requestAnimationFrame(
          () => {
            applyDossierRanks(
              team
            );
          }
        );
      };

    rankedRenderer
      .__hammerRanksInstalled =
      true;

    renderDossier =
      rankedRenderer;
  }


  // ==========================================================================
  // EXTRA DOM SAFETY
  // ==========================================================================

  function installDossierObserver() {
    const container =
      document.getElementById(
        "dossier-container"
      );

    if (!container) {
      window.setTimeout(
        installDossierObserver,
        150
      );

      return;
    }

    let queued =
      false;

    const observer =
      new MutationObserver(
        () => {
          if (queued) {
            return;
          }

          queued =
            true;

          window.requestAnimationFrame(
            () => {
              queued =
                false;

              try {
                if (
                  currentDossierTeamName &&
                  typeof getTeam ===
                    "function"
                ) {
                  const team =
                    getTeam(
                      currentDossierTeamName
                    );

                  if (team) {
                    applyDossierRanks(
                      team
                    );
                  }
                }
              } catch (_) {
                // Dossier not active yet.
              }
            }
          );
        }
      );

    observer.observe(
      container,
      {
        childList: true,
        subtree: true
      }
    );
  }


  // ==========================================================================
  // START
  // ==========================================================================

  function start() {
    installDossierRankSystem();
    installDossierObserver();
  }


  if (
    document.readyState ===
    "loading"
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
