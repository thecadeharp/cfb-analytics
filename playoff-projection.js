/* THI Playoff Projection: display-only postseason research. Never mutates Model A. */
((root, factory) => {
  'use strict';

  const core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  if (root) root.THIPlayoffProjectionCore = core;
  if (typeof document === 'undefined') return;

  const MAJOR_AUTO_CONFERENCES = ['ACC', 'Big Ten', 'Big 12', 'SEC'];
  const GROUP_AUTO_CONFERENCES = [
    'American Athletic', 'Conference USA', 'Mid-American',
    'Mountain West', 'Pac-12', 'Sun Belt'
  ];

  function safe(value, fallback = null) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function html(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function rankPercentile(rank, fieldSize) {
    const value = safe(rank);
    if (value === null || value <= 0) return 0.45;
    return Math.max(0, Math.min(1, 1 - ((value - 1) / Math.max(1, fieldSize - 1))));
  }

  function teamRows() {
    const powerRows = Array.isArray(thiPowerRatingsData?.teams)
      ? thiPowerRatingsData.teams
      : [];
    const powerByTeam = new Map(powerRows.map(row => [row.team, row]));
    const names = Object.keys(teams ?? {});
    const fieldSize = Math.max(names.length, 1);

    return names.map(name => {
      const team = teams[name] ?? {};
      const season = seasonProjections?.[name] ?? {};
      const resume = externalRatingsData?.teams?.[name] ?? {};
      const power = powerByTeam.get(name) ?? {};
      const games = Math.max(1, safe(season.games, 12));
      const expectedWins = safe(season.expected_wins, safe(team?.record?.wins, 0));
      const expectedLosses = safe(season.expected_losses, Math.max(0, games - expectedWins));
      const projectedWinPct = Math.max(0, Math.min(1, expectedWins / games));
      const powerRank = safe(power.rank, safe(team.power_rating_rank, fieldSize));
      const sorRank = safe(resume.sor_rank, powerRank);
      const sosRank = safe(resume.sos_rank, Math.ceil(fieldSize / 2));

      // Projected results and THI quality lead; resume and schedule break ties.
      const selectionScore = (
        (projectedWinPct * 0.40) +
        (rankPercentile(sorRank, fieldSize) * 0.10) +
        (rankPercentile(powerRank, fieldSize) * 0.40) +
        (rankPercentile(sosRank, fieldSize) * 0.10)
      );

      return {
        team: name,
        conference: team.conference || 'FBS Independents',
        expectedWins,
        expectedLosses,
        mostLikelyRecord: season.most_likely_record || null,
        projectedWinPct,
        powerRank,
        sorRank,
        sosRank,
        selectionScore,
      };
    }).sort((a, b) =>
      b.selectionScore - a.selectionScore ||
      a.sorRank - b.sorRank ||
      a.powerRank - b.powerRank ||
      a.team.localeCompare(b.team)
    ).map((row, index) => ({ ...row, projectedRank: index + 1 }));
  }

  function projectionData() {
    return core.selectField(teamRows(), MAJOR_AUTO_CONFERENCES, GROUP_AUTO_CONFERENCES);
  }

  function recordText(row) {
    return `${row.expectedWins.toFixed(1)}-${row.expectedLosses.toFixed(1)}`;
  }

  function projectedRecordFor(teamName) {
    const season = seasonProjections?.[teamName];
    if (!season || !Number.isFinite(Number(season.expected_wins))) return null;
    return {
      expected: `${Number(season.expected_wins).toFixed(1)}–${Number(season.expected_losses).toFixed(1)}`,
      mostLikely: season.most_likely_record || null,
    };
  }

  function lineText(projection) {
    if (!projection || !Number.isFinite(Number(projection.homeSpread))) return 'Line unavailable';
    const spread = Number(projection.homeSpread);
    if (spread === 0) return 'Pick';
    const favorite = spread < 0 ? projection.homeName : projection.awayName;
    return `${favorite} -${Math.abs(spread).toFixed(1)}`;
  }

  function simulateGame(entryA, entryB, venue = 'neutral') {
    if (!entryA || !entryB) return null;
    let projection = null;
    try {
      projection = buildInteractiveProjection(entryA.team, entryB.team, venue);
    } catch (_) {
      projection = null;
    }
    const winA = safe(projection?.teamAWin, 50);
    const winner = winA >= 50 ? entryA : entryB;
    return { entryA, entryB, projection, winner };
  }

  function simulateBracket(field) {
    const seed = number => field.find(row => row.seed === number);
    const firstRound = [
      simulateGame(seed(5), seed(12), 'team_a_home'),
      simulateGame(seed(6), seed(11), 'team_a_home'),
      simulateGame(seed(7), seed(10), 'team_a_home'),
      simulateGame(seed(8), seed(9), 'team_a_home'),
    ];
    const byPair = (a, b) => firstRound.find(game =>
      game?.entryA?.seed === a && game?.entryB?.seed === b
    )?.winner;
    const quarterfinals = [
      simulateGame(seed(1), byPair(8, 9)),
      simulateGame(seed(4), byPair(5, 12)),
      simulateGame(seed(2), byPair(7, 10)),
      simulateGame(seed(3), byPair(6, 11)),
    ];
    const semifinals = [
      simulateGame(quarterfinals[0]?.winner, quarterfinals[1]?.winner),
      simulateGame(quarterfinals[2]?.winner, quarterfinals[3]?.winner),
    ];
    const title = simulateGame(semifinals[0]?.winner, semifinals[1]?.winner);
    return { firstRound, quarterfinals, semifinals, title, champion: title?.winner ?? null };
  }

  function teamLine(entry, game) {
    const projection = game?.projection;
    const probability = entry.team === projection?.teamA?.team
      ? projection.teamAWin
      : projection?.teamBWin;
    const winner = game?.winner?.team === entry.team;
    return `<div class="thi-cfp-team ${winner ? 'projected-winner' : ''}">
      <div class="thi-cfp-seed">${entry.seed ?? entry.projectedRank}</div>
      <div class="thi-cfp-team-name">${typeof teamLogoMarkup === 'function' ? teamLogoMarkup(entry.team, 'projection') : ''}<strong>${html(entry.team)}</strong></div>
      <div class="thi-cfp-probability">${Number.isFinite(Number(probability)) ? `${Number(probability).toFixed(0)}%` : '—'}</div>
    </div>`;
  }

  function gameCard(game) {
    if (!game) return '';
    const projection = game.projection;
    return `<article class="thi-cfp-game">
      ${teamLine(game.entryA, game)}
      ${teamLine(game.entryB, game)}
      <div class="thi-cfp-game-meta">
        <span>${html(lineText(projection))}</span>
        <span>Total ${Number.isFinite(Number(projection?.total)) ? Number(projection.total).toFixed(1) : '—'}</span>
        <span>${projection ? `${projection.scoreA}-${projection.scoreB}` : '—'}</span>
      </div>
    </article>`;
  }

  function fieldRow(entry) {
    const autoLabel = entry.autoBid
      ? (entry.autoBid === 'group' ? 'AUTO · HIGHEST G6 CHAMPION' : `AUTO · ${entry.conference.toUpperCase()} CHAMPION`)
      : (entry.team === 'Notre Dame' && entry.notreDameAuto ? 'AUTO · NOTRE DAME TOP 12' : 'AT-LARGE');
    return `<div class="thi-cfp-field-row">
      <span class="thi-cfp-field-seed">${entry.seed}</span>
      <span class="thi-cfp-field-team">${typeof teamLogoMarkup === 'function' ? teamLogoMarkup(entry.team, 'projection') : ''}<strong>${html(entry.team)}</strong></span>
      <span class="thi-cfp-field-record">THI ${html(recordText(entry))}</span>
      <span class="thi-cfp-field-label">${html(autoLabel)}</span>
    </div>`;
  }

  function roundColumn(title, games) {
    return `<section class="thi-cfp-round"><h3>${html(title)}</h3>${games.map(gameCard).join('')}</section>`;
  }

  function renderProjection() {
    const container = document.getElementById('thi-playoff-container');
    if (!container) return;
    const data = projectionData();
    if (data.field.length < 12) {
      container.innerHTML = '<div class="empty-state">Playoff projection data is not available.</div>';
      return;
    }
    const simulation = simulateBracket(data.field);
    const week = thiPowerRatingsData?.meta?.through_week ?? metricsData?.meta?.through_week ?? '—';

    container.innerHTML = `
      <div class="thi-cfp-summary">
        <div><div class="eyebrow">Research simulation · through Week ${html(week)}</div><h2>Projected 12-Team Field</h2></div>
        <div class="thi-cfp-summary-copy">Selection score: 40% THI projected record, 40% THI power, 10% strength of record and 10% strength of schedule. Conference champion slots follow the 2026 CFP format.</div>
      </div>
      <div class="thi-cfp-layout">
        <section class="thi-cfp-field"><h3>Projected field</h3>${data.field.map(fieldRow).join('')}
          <div class="thi-cfp-bubble"><div><span>First team out</span><strong>${html(data.firstOut?.team ?? '—')}</strong></div><div><span>Second team out</span><strong>${html(data.secondOut?.team ?? '—')}</strong></div></div>
        </section>
        <section class="thi-cfp-champion"><span>Projected champion</span>${simulation.champion ? `${typeof teamLogoMarkup === 'function' ? teamLogoMarkup(simulation.champion.team, 'dossier') : ''}<strong>${html(simulation.champion.team)}</strong><small>Favorite advances in each hypothetical matchup</small>` : '—'}</section>
      </div>
      <div class="thi-cfp-bracket" aria-label="THI simulated College Football Playoff bracket">
        ${roundColumn('First Round · Campus', simulation.firstRound)}
        ${roundColumn('Quarterfinals', simulation.quarterfinals)}
        ${roundColumn('Semifinals', simulation.semifinals)}
        ${roundColumn('Championship', simulation.title ? [simulation.title] : [])}
      </div>
      <details class="thi-cfp-method"><summary>How this projection works</summary><p>This is a weekly THI research view, not the CFP committee ranking. The projected field balances accomplishment, schedule and team quality, then applies the official automatic-bid and seeding rules. Matchups use the site's existing hypothetical spread, total and win-probability engine. They are not official Model A plays and are excluded from tracking.</p></details>`;
  }

  function mountNavigation() {
    const nav = document.querySelector('.main-nav');
    if (!nav || nav.querySelector('[data-view="playoff"]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'nav-item';
    button.dataset.view = 'playoff';
    button.textContent = 'Playoff Projection';
    button.addEventListener('click', () => {
      switchView('playoff');
      renderProjection();
    });
    const anchor = nav.querySelector('[data-view="thi-ratings"]') || nav.querySelector('[data-view="ratings"]');
    anchor?.after(button);

    const ratings = document.getElementById('view-ratings');
    if (!ratings) return;
    const view = document.createElement('section');
    view.id = 'view-playoff';
    view.className = 'view';
    view.innerHTML = `<div class="eyebrow">Postseason outlook</div><h1 class="page-title">Playoff Projection</h1><p class="page-subtitle">A weekly THI view of the projected 12-team field and how that bracket plays out through hypothetical matchups.</p><div id="thi-playoff-container"><div class="loading-state"><div class="spinner"></div>Building playoff projection…</div></div>`;
    ratings.after(view);

    const cta = document.createElement('button');
    cta.type = 'button';
    cta.className = 'thi-cfp-ratings-link';
    cta.innerHTML = '<span><strong>Projected CFP Bracket</strong><small>View the field, first two out and simulated matchups</small></span><span aria-hidden="true">View bracket →</span>';
    cta.addEventListener('click', () => {
      switchView('playoff');
      renderProjection();
    });
    ratings.querySelector('.page-subtitle')?.after(cta);
  }

  function replaceDossierResume(teamName) {
    const container = document.getElementById('dossier-container');
    if (!container) return;
    const panels = Array.from(container.querySelectorAll(':scope > .panel'));
    const target = panels.find(panel => panel.querySelector('.panel-title')?.textContent.trim() === 'External Ratings & Resume');
    if (!target) return;
    const resume = externalRatingsData?.teams?.[teamName] ?? {};
    const projected = projectedRecordFor(teamName);
    const rank = value => Number.isFinite(Number(value)) ? `#${Number(value).toFixed(0)}` : '—';
    target.classList.add('thi-resume-context');
    target.innerHTML = `<div class="panel-header"><div><div class="panel-title">Schedule & Resume Context</div><div class="team-meta" style="margin-top:5px;">Schedule and résumé measures through ESPN Week ${html(externalRatingsData?.meta?.week ?? '—')} · THI projected record · display only</div></div><button type="button" class="thi-cfp-inline-link">View projected CFP bracket →</button></div>
      <div class="thi-resume-grid">
        <div class="thi-resume-item"><span>Strength of Record</span><strong>${rank(resume.sor_rank)}</strong></div>
        <div class="thi-resume-item"><span>Strength of Schedule</span><strong>${rank(resume.sos_rank)}</strong></div>
        <div class="thi-resume-item"><span>Remaining SOS</span><strong>${rank(resume.remaining_sos_rank)}</strong></div>
        <div class="thi-resume-item"><span>Game Control</span><strong>${rank(resume.game_control_rank)}</strong></div>
        <div class="thi-resume-item featured"><span>THI Projected Record</span><strong>${html(projected?.expected ?? '—')}</strong><small>${projected?.mostLikely ? `Most likely ${html(projected.mostLikely)}` : 'Weekly projection unavailable'}</small></div>
      </div>`;
    target.querySelector('.thi-cfp-inline-link')?.addEventListener('click', () => {
      switchView('playoff');
      renderProjection();
    });
  }

  mountNavigation();

  const baseDossier = window.renderDossier;
  if (baseDossier) window.renderDossier = function(team) {
    const result = baseDossier.apply(this, arguments);
    replaceDossierResume(team?.team);
    return result;
  };

  document.addEventListener('hammer:data-ready', renderProjection);
  if (typeof teams !== 'undefined' && Object.keys(teams ?? {}).length) renderProjection();
})(typeof window !== 'undefined' ? window : null, () => {
  'use strict';

  function selectField(rows, majorConferences, groupConferences) {
    const ranked = Array.isArray(rows) ? rows.slice() : [];
    const bestIn = conference => ranked.find(row => row.conference === conference) ?? null;
    const majorChampions = majorConferences.map(bestIn).filter(Boolean).map(row => ({ ...row, autoBid: 'major' }));
    const groupChampion = ranked.find(row => groupConferences.includes(row.conference));
    const automatic = groupChampion
      ? [...majorChampions, { ...groupChampion, autoBid: 'group' }]
      : majorChampions;
    const byTeam = new Map(automatic.map(row => [row.team, row]));
    const notreDame = ranked.find(row => row.team === 'Notre Dame' && row.projectedRank <= 12);
    if (notreDame) byTeam.set(notreDame.team, { ...notreDame, notreDameAuto: true });
    for (const row of ranked) {
      if (byTeam.size >= 12) break;
      if (!byTeam.has(row.team)) byTeam.set(row.team, { ...row });
    }
    const field = Array.from(byTeam.values())
      .sort((a, b) => a.projectedRank - b.projectedRank)
      .slice(0, 12)
      .map((row, index) => ({ ...row, seed: index + 1 }));
    const selected = new Set(field.map(row => row.team));
    const bubble = ranked.filter(row => !selected.has(row.team));
    return { field, firstOut: bubble[0] ?? null, secondOut: bubble[1] ?? null };
  }

  return { selectField };
});
