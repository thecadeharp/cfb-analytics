/* Research-only possession profiles. Never mutates model, rating or projection data. */
(() => {
  'use strict';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);

  const aliases = {
    appalachianstate: 'appstate', appstate: 'appstate',
    louisianamonroe: 'ulmonroe', ulm: 'ulmonroe', ulmonroe: 'ulmonroe',
    miamifl: 'miami', miamiflorida: 'miami', miami: 'miami',
    miamiohio: 'miamioh', miamioh: 'miamioh',
    southerncalifornia: 'usc', usc: 'usc',
    hawaii: 'hawaii',
    texaselpaso: 'utep', texassanantonio: 'utsa',
    centralflorida: 'ucf', brighamyoung: 'byu',
    southernmethodist: 'smu', texaschristian: 'tcu',
  };

  function teamKey(name) {
    const raw = String(name ?? '').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]/g, '');
    return aliases[raw] || raw;
  }

  function profileIndex(teams) {
    const index = new Map();
    (Array.isArray(teams) ? teams : []).forEach(team => {
      if (team?.team) index.set(teamKey(team.team), team);
    });
    return index;
  }

  function findProfile(index, name) {
    return index.get(teamKey(name)) || null;
  }

  function number(value, digits = 3) {
    return value !== null && value !== '' && Number.isFinite(Number(value))
      ? Number(value).toFixed(digits) : '—';
  }

  function signed(value, digits = 3) {
    if (value === null || value === '' || !Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    return `${numeric > 0 ? '+' : ''}${numeric.toFixed(digits)}`;
  }

  function percent(value) {
    return value !== null && value !== '' && Number.isFinite(Number(value))
      ? `${(Number(value) * 100).toFixed(1)}%` : '—';
  }

  const api = { teamKey, profileIndex, findProfile, number, signed, percent };
  window.THISituationalProfilesUI = api;
  if (typeof document === 'undefined') return;

  let report = null;
  let index = new Map();
  let gameIndex = new Map();
  let status = 'Loading verified possession profiles…';
  let activeDossierTeam = null;

  function metric(label, value, note = '') {
    return `<div class="thi-sp-metric"><div class="thi-sp-label">${esc(label)}</div><div class="thi-sp-value">${esc(value)}</div>${note ? `<div class="thi-sp-note">${esc(note)}</div>` : ''}</div>`;
  }

  function reliability(profile) {
    const labels = { limited: 'Limited sample', developing: 'Developing sample', established: 'Established sample' };
    return labels[profile?.reliability] || 'Sample unavailable';
  }

  function stateRows(profile, side) {
    const source = profile?.[side]?.by_score_state || {};
    const valueField = side === 'offense'
      ? 'points_over_expected_per_possession'
      : 'points_prevented_over_expected_per_possession';
    return ['leading', 'tied', 'trailing'].map(state => {
      const row = source[state] || {};
      return `<tr><th scope="row">${esc(state[0].toUpperCase() + state.slice(1))}</th><td>${esc(row.possessions ?? 0)}</td><td>${esc(number(row.actual_points_per_possession))}</td><td>${esc(signed(row[valueField]))}</td></tr>`;
    }).join('');
  }

  function halfRows(profile, side) {
    const source = profile?.[side]?.by_half || {};
    const valueField = side === 'offense'
      ? 'points_over_expected_per_possession'
      : 'points_prevented_over_expected_per_possession';
    return ['first_half', 'second_half'].map(half => {
      const row = source[half] || {};
      const label = half === 'first_half' ? 'First half' : 'Second half';
      return `<tr><th scope="row">${label}</th><td>${esc(row.possessions ?? 0)}</td><td>${esc(number(row.actual_points_per_possession))}</td><td>${esc(signed(row[valueField]))}</td></tr>`;
    }).join('');
  }

  function sidePanel(profile, side) {
    const values = profile[side];
    const defense = side === 'defense';
    const valueField = defense
      ? 'points_prevented_over_expected_per_possession'
      : 'points_over_expected_per_possession';
    return `<section class="thi-sp-side" aria-label="${defense ? 'Defensive' : 'Offensive'} possession profile">
      <div class="thi-sp-side-head"><h4>${defense ? 'Defense' : 'Offense'}</h4><span>${esc(values.possessions)} possessions · ${esc(values.games)} games</span></div>
      <div class="thi-sp-metrics">
        ${metric(defense ? 'Points allowed / possession' : 'Points / possession', number(values.actual_points_per_possession))}
        ${metric(defense ? 'Points prevented vs expected' : 'Points over expected', signed(values[valueField]), 'per possession')}
        ${metric('Scoring possession rate', percent(values.scoring_possession_rate))}
        ${metric('Empty possession rate', percent(values.empty_possession_rate))}
        ${metric('Average start field position', number(values.average_start_field_position, 1))}
        ${metric('Short-field points / possession', number(values.short_field_points_per_possession), `${values.short_field_possessions} possessions`)}
      </div>
      <details class="thi-sp-splits"><summary>Score-state and half splits</summary>
        <div class="thi-sp-table-wrap"><table><thead><tr><th>Situation</th><th>Poss</th><th>${defense ? 'Allowed' : 'Actual'}</th><th>${defense ? 'Prevented' : 'Vs exp.'}</th></tr></thead><tbody>${stateRows(profile, side)}${halfRows(profile, side)}</tbody></table></div>
      </details>
    </section>`;
  }

  function unavailable(name) {
    return `<section class="thi-situational-panel"><div class="thi-sp-header"><div><div class="thi-sp-eyebrow">Observed possession context</div><h3>Situational Profile</h3></div></div><p class="thi-sp-empty">${esc(status || `No fully admitted possession sample is available for ${name}.`)}</p></section>`;
  }

  function dossierMarkup(name) {
    const profile = findProfile(index, name);
    if (!profile) return unavailable(name);
    return `<section class="thi-situational-panel">
      <div class="thi-sp-header"><div><div class="thi-sp-eyebrow">Observed possession context</div><h3>Situational Profile</h3></div><div class="thi-sp-badges"><span>${esc(reliability(profile))}</span><span>Through Week ${esc(report.meta.through_week)}</span></div></div>
      <p class="thi-sp-intro">Completed-game possession value from independently verified scores and exact drive-start context. Descriptive only; excluded from Model A and THI ratings.</p>
      <div class="thi-sp-net">${metric('Net possession value', signed(profile.net_possession_value), 'offensive value plus defensive prevention')}</div>
      <div class="thi-sp-grid">${sidePanel(profile, 'offense')}${sidePanel(profile, 'defense')}</div>
      <p class="thi-sp-foot">${esc(profile.games)} admitted games · ${esc(reliability(profile))}. Quarantined games are omitted rather than repaired or estimated.</p>
    </section>`;
  }

  function matchupCard(name) {
    const profile = findProfile(index, name);
    if (!profile) return `<article class="thi-sp-match-card"><h4>${esc(name)}</h4><p>No fully admitted possession sample.</p></article>`;
    return `<article class="thi-sp-match-card"><div class="thi-sp-side-head"><h4>${esc(name)}</h4><span>${esc(reliability(profile))}</span></div>
      <div class="thi-sp-match-metrics">
        ${metric('Net possession value', signed(profile.net_possession_value))}
        ${metric('Offense vs expected', signed(profile.offense.points_over_expected_per_possession), `${profile.offense.possessions} possessions`)}
        ${metric('Defense prevented', signed(profile.defense.points_prevented_over_expected_per_possession), `${profile.defense.possessions} possessions`)}
        ${metric('Offensive scoring rate', percent(profile.offense.scoring_possession_rate))}
      </div></article>`;
  }

  function matchupMarkup(teamA, teamB) {
    return `<section class="thi-situational-panel"><div class="thi-sp-header"><div><div class="thi-sp-eyebrow">Research-only comparison</div><h3>Situational Profiles</h3></div>${report ? `<div class="thi-sp-badges"><span>Through Week ${esc(report.meta.through_week)}</span></div>` : ''}</div>
      <p class="thi-sp-intro">Side-by-side postgame context only. These values do not adjust the hypothetical projection above.</p>
      <div class="thi-sp-match-grid">${matchupCard(teamA)}${matchupCard(teamB)}</div></section>`;
  }

  function gameKey(away, home) {
    return `${teamKey(away)}@${teamKey(home)}`;
  }

  function gameLogRow(label, away, home) {
    return `<div class="thi-gel-row"><div>${esc(label)}</div><div>${esc(away)}</div><div>${esc(home)}</div></div>`;
  }

  function excitementComponent(label, value, max) {
    const numeric = Number(value);
    const width = Number.isFinite(numeric) && max > 0
      ? Math.max(0, Math.min(100, numeric / max * 100)) : 0;
    return `<div class="thi-gel-component"><div><span>${esc(label)}</span><strong>${esc(number(value, 1))}/${esc(max)}</strong></div><div class="thi-gel-track"><i style="width:${width.toFixed(1)}%"></i></div></div>`;
  }

  function gameLogMarkup(game) {
    if (!game) {
      return `<section class="thi-game-efficiency"><div class="thi-sp-eyebrow">Verified possession ledger</div><h3>Game Efficiency Log</h3><p class="thi-sp-empty">This game is not in the fully admitted possession sample. THI withholds the log when final-score, ownership or possession-start checks are incomplete.</p></section>`;
    }
    const away = game.away || {};
    const home = game.home || {};
    const excitement = game.excitement || {};
    const components = excitement.components || {};
    const edge = Number(game.possession_value_edge);
    const edgeText = Number.isFinite(edge)
      ? `${edge >= 0 ? game.home_team : game.away_team} ${Math.abs(edge).toFixed(3)}` : '—';
    return `<section class="thi-game-efficiency">
      <div class="thi-gel-head"><div><div class="thi-sp-eyebrow">Verified possession ledger</div><h3>Game Efficiency Log</h3><p>What each offense produced relative to its independently verified possession starts.</p></div><div class="thi-gel-excitement"><span>THI Excitement Score</span><strong>${esc(excitement.score ?? '—')}</strong><em>${esc(excitement.label || 'Unavailable')}</em></div></div>
      <div class="thi-gel-score"><span>${esc(game.away_team)} <strong>${esc(game.away_points)}</strong></span><small>FINAL</small><span><strong>${esc(game.home_points)}</strong> ${esc(game.home_team)}</span></div>
      <div class="thi-gel-table">
        <div class="thi-gel-row thi-gel-columns"><div>POSSESSION MEASURE</div><div>${esc(game.away_team)}</div><div>${esc(game.home_team)}</div></div>
        ${gameLogRow('Possessions', away.possessions ?? '—', home.possessions ?? '—')}
        ${gameLogRow('Points / possession', number(away.points_per_possession), number(home.points_per_possession))}
        ${gameLogRow('Expected at possession start', number(away.expected_start_points_per_possession), number(home.expected_start_points_per_possession))}
        ${gameLogRow('Value over expected / possession', signed(away.points_over_expected_per_possession), signed(home.points_over_expected_per_possession))}
        ${gameLogRow('Scoring possession rate', percent(away.scoring_possession_rate), percent(home.scoring_possession_rate))}
        ${gameLogRow('Empty possession rate', percent(away.empty_possession_rate), percent(home.empty_possession_rate))}
        ${gameLogRow('Average starting field position', number(away.average_start_field_position, 1), number(home.average_start_field_position, 1))}
        ${gameLogRow('Short-field points / possession', number(away.short_field_points_per_possession), number(home.short_field_points_per_possession))}
      </div>
      <div class="thi-gel-edge"><span>Possession value edge</span><strong>${esc(edgeText)} pts/possession</strong></div>
      <div class="thi-gel-components">
        ${excitementComponent('Final-score tension', components.final_score_tension, 35)}
        ${excitementComponent('Late-game pressure', components.late_game_pressure, 25)}
        ${excitementComponent('Lead exchange', components.lead_exchange, 20)}
        ${excitementComponent('Scoring activity', components.scoring_activity, 20)}
      </div>
      <p class="thi-sp-foot">Excitement is retrospective and descriptive. It combines final-score tension, fourth-quarter one-score possession share, lead exchanges and scoring activity. The efficiency log and score do not alter Model A, THI ratings or the frozen pregame projection.</p>
    </section>`;
  }

  function refreshGameLog() {
    const slot = document.getElementById('thi-game-efficiency-log');
    if (!slot) return;
    const key = gameKey(slot.dataset.awayTeam, slot.dataset.homeTeam);
    const renderKey = `${key}:${report?.meta?.generated_at || status}`;
    if (slot.dataset.renderKey === renderKey) return;
    slot.innerHTML = gameLogMarkup(gameIndex.get(key) || null);
    slot.dataset.renderKey = renderKey;
  }

  function mount(container, id, markup) {
    if (!container) return;
    let panel = container.querySelector(`#${id}`);
    if (!panel) {
      panel = document.createElement('div');
      panel.id = id;
      container.append(panel);
    }
    panel.innerHTML = markup;
  }

  function refreshDossier() {
    if (!activeDossierTeam) return;
    mount(document.getElementById('dossier-container'), 'thi-situational-dossier', dossierMarkup(activeDossierTeam));
  }

  function currentTapeTeams() {
    if (typeof tapeTeamA === 'undefined' || typeof tapeTeamB === 'undefined') return null;
    return tapeTeamA && tapeTeamB ? [tapeTeamA, tapeTeamB] : null;
  }

  function refreshMatchup() {
    const teams = currentTapeTeams();
    const container = document.getElementById('tape-container');
    if (!teams || !container?.querySelector('.tape-result')) return;
    mount(container, 'thi-situational-matchup', matchupMarkup(teams[0], teams[1]));
  }

  const dossierBase = window.renderDossier;
  if (dossierBase) window.renderDossier = function(team) {
    const result = dossierBase.apply(this, arguments);
    activeDossierTeam = team?.team || null;
    refreshDossier();
    return result;
  };

  const matchupBase = window.renderMatchupAnalysis;
  if (matchupBase) window.renderMatchupAnalysis = function() {
    const result = matchupBase.apply(this, arguments);
    refreshMatchup();
    return result;
  };

  fetch('./data/research/situational_profiles_2026.json', { cache: 'no-store' })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      if (data?.meta?.status !== 'research_only_situational_profiles_v1'
          || data?.meta?.model_a_touched !== false
          || !Array.isArray(data?.teams)) throw new Error('Invalid profile contract');
      report = data;
      index = profileIndex(data.teams);
      gameIndex = new Map((Array.isArray(data.games) ? data.games : []).map(game => [
        gameKey(game.away_team, game.home_team), game
      ]));
      status = '';
    })
    .catch(() => {
      status = 'Verified situational profiles are not available yet.';
    })
    .finally(() => {
      refreshDossier();
      refreshMatchup();
      refreshGameLog();
    });

  new MutationObserver(refreshGameLog).observe(document.body, {
    childList: true,
    subtree: true,
  });
})();
