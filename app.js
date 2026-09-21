            Display-only statistics
            · not used by Model A
          </div>
        </div>

        <div
          class="ratings-toggle"
          style="padding:0; border:0; margin-left:auto;"
        >
          <button
            type="button"
            class="ratings-toggle-button ${
              currentAdvancedSample ===
              "non_garbage"
                ? "active"
                : ""
            }"
            onclick="setAdvancedSample('non_garbage')"
          >
            Garbage Time Excluded
          </button>

          <button
            type="button"
            class="ratings-toggle-button ${
              currentAdvancedSample ===
              "all_plays"
                ? "active"
                : ""
            }"
            onclick="setAdvancedSample('all_plays')"
          >
            All Plays
          </button>
        </div>
      </div>

      <div
        class="sample-warning"
        style="margin:12px 16px 0;"
      >
        Current-season samples are descriptive
        and can move sharply early in the season.
        A dash means the minimum four-play sample
        has not been reached.
      </div>

      <div
        class="dossier-layout"
        style="padding:12px 16px 16px;"
      >
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Offense · Downs & Disruption
            </div>
          </div>

          <div class="panel-body">
            ${advancedMetricRows(
              team.team,
              "offense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Defense · Downs & Disruption
            </div>
          </div>

          <div class="panel-body">
            ${advancedMetricRows(
              team.team,
              "defense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Offense · Situational Splits
            </div>
          </div>

          <div class="panel-body">
            ${advancedSplitRows(
              team.team,
              "offense"
            )}
          </div>
        </div>

        <div class="panel">
          <div class="panel-header">
            <div class="panel-title">
              Defense · Situational Splits
            </div>
          </div>

          <div class="panel-body">
            ${advancedSplitRows(
              team.team,
              "defense"
            )}
          </div>
        </div>
      </div>
    </div>
  `;
}


// ============================================================================
// EVENTS / START
// ============================================================================

function attachEvents() {
  const search =
    document.getElementById(
      "team-search"
    );

  if (!search) return;

  search.addEventListener(
    "input",
    event => {
      currentSearch =
        event.target.value.trim();

      renderProjections();
    }
  );
}

document.addEventListener(
  "DOMContentLoaded",
  init
);
