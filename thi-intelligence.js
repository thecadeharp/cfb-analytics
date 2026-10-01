/* THI Intelligence Layer: original display-only context built from THI data. */
((root, factory) => {
  'use strict';
  const core = factory();
  if (typeof module === 'object' && module.exports) module.exports = core;
  if (!root) return;

  const state = { outlook: null, loading: null };
  const safe = (value, fallback = null) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  };
  const html = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
  const fmt = (value, digits = 1) => safe(value) === null ? '—' : Number(value).toFixed(digits);
  const pct = (value, digits = 0) => safe(value) === null ? '—' : `${Number(value).toFixed(digits)}%`;
  const signed = (value, digits = 1) => {
    const number = safe(value);
    return number === null ? '—' : `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
  };

  function loadOutlook() {
    if (state.outlook) return Promise.resolve(state.outlook);
    if (!state.loading) state.loading = fetch(`./data/thi_season_outlook.json?v=${Date.now()}`)
      .then(response => {
        if (!response.ok) throw new Error(`Season outlook ${response.status}`);
        return response.json();
      })
      .then(data => (state.outlook = data))
      .catch(error => {
        console.warn('[THI Intelligence] Season outlook unavailable:', error);
        return null;
      });
    return state.loading;
  }

  function distributionBars(values, className = '') {
    const rows = Object.entries(values ?? {})
      .map(([wins, probability]) => ({ wins: Number(wins), probability: Number(probability) }))
      .filter(row => Number.isFinite(row.wins) && Number.isFinite(row.probability) && row.probability >= 0.5)
      .sort((a, b) => a.wins - b.wins);
    const max = Math.max(1, ...rows.map(row => row.probability));
    return `<div class="thi-intel-distribution ${className}">${rows.map(row => `
      <div class="thi-intel-dist-column">
        <span>${pct(row.probability)}</span>
        <div><i style="height:${Math.max(3, row.probability / max * 100)}%"></i></div>
        <strong>${row.wins}</strong>
      </div>`).join('')}</div>`;
  }

  function rangeText(range) {
    return Array.isArray(range) && range.length === 2 ? `${range[0]}–${range[1]}` : '—';
  }

  function historyFor(teamName) {
    return (state.outlook?.history ?? []).map(snapshot => ({
      week: snapshot.through_week,
      overall: safe(snapshot.teams?.[teamName]?.overall_expected_wins),
      conference: safe(snapshot.teams?.[teamName]?.conference_expected_wins),
    })).filter(row => row.overall !== null);
  }

  function trajectoryMarkup(teamName) {
    const history = historyFor(teamName);
    if (!history.length) return '<div class="thi-intel-empty">Weekly tracking begins with the first saved THI outlook.</div>';
    const current = history.at(-1);
    const previous = history.length > 1 ? history.at(-2) : null;
    const delta = previous ? current.overall - previous.overall : null;
    return `<div class="thi-intel-trajectory">
      <div class="thi-intel-trajectory-head"><span>Saved point</span><span>Overall</span><span>Conference</span></div>
      ${history.map(row => `<div><span>Week ${html(row.week)}</span><strong>${fmt(row.overall, 2)}</strong><strong>${fmt(row.conference, 2)}</strong></div>`).join('')}
      <p>${delta === null ? 'Baseline snapshot established.' : `${signed(delta, 2)} projected wins since last week.`}</p>
    </div>`;
  }

  function scheduleCard(game, teamName) {
    const completed = game.status === 'completed' || Number(game.win_probability) === 0 || Number(game.win_probability) === 100;
    const location = game.location === 'away' ? 'AT' : game.location === 'neutral' ? 'NEUTRAL' : 'VS';
    const gameRecord = (typeof scheduleGameRecord === 'function') ? scheduleGameRecord(game.game_id) : null;
    let result = 'UPCOMING';
    if (completed && gameRecord && typeof scheduleResult === 'function') {
      result = scheduleResult(teamName, gameRecord).text;
    } else if (completed) {
      result = Number(game.win_probability) === 100 ? 'WIN' : 'LOSS';
    }
    return `<article class="thi-intel-schedule-card ${completed ? 'completed' : ''}">
      <div class="thi-intel-schedule-top"><span>WEEK ${html(game.week)} · ${location}</span><span>${game.opponent_type === 'FCS' ? 'FCS FALLBACK' : html(game.probability_source === 'fbs_model' ? 'THI MODEL' : result)}</span></div>
      <strong>${html(game.opponent)}</strong>
      <div class="thi-intel-schedule-numbers"><span>${completed ? html(result) : `${pct(game.win_probability)} win`}</span><span>${completed || safe(game.team_line) === null ? '—' : `THI ${Number(game.team_line) > 0 ? '+' : ''}${fmt(game.team_line, 1)}`}</span></div>
      ${!completed ? `<div class="thi-intel-prob-track"><i style="width:${Math.max(0, Math.min(100, Number(game.win_probability)))}%"></i></div>` : ''}
    </article>`;
  }

  function outlookMarkup(teamName) {
    const row = state.outlook?.teams?.[teamName];
    if (!row) return '';
    const overall = row.overall ?? {};
    const conference = row.conference_outlook ?? {};
    const history = historyFor(teamName);
    const previous = history.length > 1 ? history.at(-2) : null;
    const weeklyDelta = previous ? Number(overall.expected_wins) - previous.overall : null;
    const remaining = (row.schedule ?? []).filter(game => !['completed'].includes(String(game.status).toLowerCase()) && ![0, 100].includes(Number(game.win_probability)));

    return `<section class="thi-intel-outlook">
      <header class="thi-intel-header">
        <div><div class="eyebrow">THI season path · display only</div><h2>Season Outlook</h2><p>Completed results are locked. Every remaining game uses the current THI win probability; distributions update after each weekly refresh.</p></div>
        <div class="thi-intel-week">THROUGH WEEK ${html(state.outlook?.meta?.through_week ?? '—')}</div>
      </header>
      <div class="thi-intel-summary">
        <article class="featured"><span>Projected season wins</span><strong>${fmt(overall.expected_wins, 2)}</strong><small>${fmt(overall.expected_remaining_wins, 2)} expected remaining · ${weeklyDelta === null ? 'baseline week' : `${signed(weeklyDelta, 2)} weekly`}</small></article>
        <article><span>Current record</span><strong>${overall.actual_wins ?? '—'}–${overall.actual_losses ?? '—'}</strong><small>Most likely ${html(overall.most_likely_record ?? '—')}</small></article>
        <article><span>Projected conference wins</span><strong>${conference.applicable ? fmt(conference.expected_wins, 2) : '—'}</strong><small>${conference.applicable ? `${conference.actual_wins}–${conference.actual_losses} current · most likely ${html(conference.most_likely_record)}` : 'Independent schedule'}</small></article>
        <article><span>Season range</span><strong>${rangeText(overall.range_50)}</strong><small>50% range · ${rangeText(overall.range_80)} at 80%</small></article>
        <article><span>Conference range</span><strong>${conference.applicable ? rangeText(conference.range_50) : '—'}</strong><small>${conference.applicable ? `50% range · ${rangeText(conference.range_80)} at 80%` : 'Not applicable'}</small></article>
        <article><span>Bowl probability</span><strong>${pct(overall.bowl_eligible_probability)}</strong><small>${pct(overall.at_least?.['10_wins'])} chance of 10+ wins</small></article>
      </div>
      <div class="thi-intel-grid">
        <article class="thi-intel-panel"><h3>Final regular-season wins</h3>${distributionBars(overall.exact_win_distribution)}<p>Probability of each exact win total.</p></article>
        <article class="thi-intel-panel"><h3>Final conference wins</h3>${conference.applicable ? distributionBars(conference.exact_win_distribution, 'conference') : '<div class="thi-intel-empty">Conference-win distribution does not apply.</div>'}<p>${conference.applicable ? `${fmt(conference.expected_remaining_wins, 2)} expected conference wins remaining.` : 'Independent program.'}</p></article>
        <article class="thi-intel-panel"><h3>Projection trail</h3>${trajectoryMarkup(teamName)}</article>
      </div>
      <div class="thi-intel-panel thi-intel-remaining"><div class="thi-intel-panel-head"><h3>Remaining path</h3><span>${remaining.length} games</span></div><div class="thi-intel-schedule-grid">${remaining.map(game => scheduleCard(game, teamName)).join('')}</div></div>
      <details class="thi-intel-method"><summary>How THI builds this outlook</summary><p>Expected wins are the sum of THI game win probabilities. Exact season and conference distributions use Poisson-binomial math, so every remaining matchup keeps its own probability. This layer does not refit, blend or modify Model A.</p></details>
    </section>`;
  }

  function enhanceDossier(teamName) {
    const legacy = document.querySelector('#dossier-container .season-outlook');
    if (!legacy || !teamName) return;
    const apply = () => {
      const markup = outlookMarkup(teamName);
      if (markup && document.querySelector('#dossier-container .season-outlook') === legacy) legacy.outerHTML = markup;
    };
    state.outlook ? apply() : loadOutlook().then(apply);
  }

  function quantile(values, q) {
    const sorted = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    if (!sorted.length) return null;
    const index = (sorted.length - 1) * q;
    const lower = Math.floor(index), upper = Math.ceil(index);
    return lower === upper ? sorted[lower] : sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
  }

  function conferenceRows() {
    const power = new Map((thiPowerRatingsData?.teams ?? []).map(row => [row.team, row]));
    const grouped = new Map();
    Object.values(teams ?? {}).forEach(team => {
      const conference = team.conference || 'FBS Independents';
      if (!grouped.has(conference)) grouped.set(conference, []);
      const rating = power.get(team.team);
      if (rating && safe(rating.rating) !== null) grouped.get(conference).push({ ...rating, conference });
    });
    const records = new Map();
    for (const game of scheduleData?.games ?? []) {
      if (String(game.status).toLowerCase() !== 'completed' || game.opponent_type !== 'FBS') continue;
      if (!game.home_conference || !game.away_conference || game.home_conference === game.away_conference) continue;
      for (const conference of [game.home_conference, game.away_conference]) if (!records.has(conference)) records.set(conference, { wins: 0, losses: 0 });
      const homeWon = Number(game.home_points) > Number(game.away_points);
      records.get(game.home_conference)[homeWon ? 'wins' : 'losses'] += 1;
      records.get(game.away_conference)[homeWon ? 'losses' : 'wins'] += 1;
    }
    return Array.from(grouped, ([conference, members]) => {
      const ratings = members.map(row => Number(row.rating));
      const topHalf = ratings.slice().sort((a, b) => b - a).slice(0, Math.ceil(ratings.length / 2));
      const current = ratings.reduce((a, b) => a + b, 0) / ratings.length;
      const priorValues = members.map(row => safe(row.previous_week_same_model_rating)).filter(v => v !== null);
      const prior = priorValues.length ? priorValues.reduce((a, b) => a + b, 0) / priorValues.length : null;
      return {
        conference, members: members.sort((a, b) => b.rating - a.rating),
        average: current, median: quantile(ratings, .5), low: quantile(ratings, .1), high: quantile(ratings, .9),
        floor: quantile(ratings, .25), topHalf: topHalf.reduce((a, b) => a + b, 0) / topHalf.length,
        top25: members.filter(row => Number(row.rank) <= 25).length,
        delta: prior === null ? null : current - prior,
        record: records.get(conference) ?? { wins: 0, losses: 0 },
      };
    }).filter(row => row.members.length >= 2).sort((a, b) => b.average - a.average);
  }

  function conferenceStrengthMarkup() {
    const rows = conferenceRows();
    if (!rows.length) return '<div class="empty-state">Conference landscape is awaiting THI Power data.</div>';
    const min = Math.floor(Math.min(...rows.flatMap(row => row.members.map(team => Number(team.rating)))) / 5) * 5;
    const max = Math.ceil(Math.max(...rows.flatMap(row => row.members.map(team => Number(team.rating)))) / 5) * 5;
    const position = value => `${Math.max(0, Math.min(100, (Number(value) - min) / Math.max(1, max - min) * 100))}%`;
    return `<section class="thi-conference-landscape">
      <header class="thi-intel-header"><div><div class="eyebrow">THI Power distribution</div><h2>Conference Landscape</h2><p>League Mark is the average THI Power Rating. The rail shows every program, the middle 80% band and the conference median.</p></div><div class="thi-intel-week">${signed(min, 0)} TO ${signed(max, 0)}</div></header>
      <div class="thi-conf-scale"><span>${signed(min, 0)}</span><span>FBS AVERAGE</span><span>${signed(max, 0)}</span></div>
      <div class="thi-conf-list">${rows.map((row, index) => `<article class="thi-conf-row">
        <div class="thi-conf-name"><span>#${index + 1}</span><strong>${html(row.conference)}</strong><small>${row.members.length} teams · ${row.record.wins}-${row.record.losses} nonconference</small></div>
        <div class="thi-conf-rail"><i class="thi-conf-zero" style="left:${position(0)}"></i><i class="thi-conf-band" style="left:${position(row.low)};width:${Math.max(1, parseFloat(position(row.high)) - parseFloat(position(row.low)))}%"></i><i class="thi-conf-median" style="left:${position(row.median)}"></i>${row.members.map(team => `<span class="thi-conf-team" style="left:${position(team.rating)}" title="${html(team.team)} ${signed(team.rating, 1)}">${typeof teamLogoMarkup === 'function' ? teamLogoMarkup(team.team, 'table') : html(team.team.slice(0, 2))}</span>`).join('')}</div>
        <div class="thi-conf-score"><strong>${signed(row.average, 1)}</strong><span>League Mark</span><small>${row.delta === null ? 'baseline' : `${signed(row.delta, 2)} weekly`}</small></div>
        <div class="thi-conf-depth"><span>Top-half ${signed(row.topHalf, 1)}</span><span>Floor ${signed(row.floor, 1)}</span><span>${row.top25} Top 25</span></div>
      </article>`).join('')}</div>
      <details class="thi-intel-method"><summary>How Conference Landscape works</summary><p>Every team is positioned by its current THI Power Rating. League Mark is the conference mean, the dark tick is its median and the shaded span contains the middle 80% of teams. No external rating enters the calculation.</p></details>
    </section>`;
  }

  function teamPercentile(teamName, field, side) {
    return safe(teamMetricProfilesData?.teams?.[teamName]?.[side]?.[field]?.percentile, 50);
  }

  function watchIndex(game) {
    const home = game?.home?.team, away = game?.away?.team;
    const homeWin = safe(game?.projection?.win_probability?.home, 50);
    const closeness = Math.max(0, 100 - 2 * Math.abs(homeWin - 50));
    const fieldSize = Math.max(2, Object.keys(teams ?? {}).length);
    const rankScore = rank => Math.max(0, 100 * (1 - (Math.max(1, safe(rank, fieldSize)) - 1) / (fieldSize - 1)));
    const homeQuality = rankScore(game?.home?.power_rating_rank), awayQuality = rankScore(game?.away?.power_rating_rank);
    const quality = ((homeQuality + awayQuality) / 2 * .65) + (Math.min(homeQuality, awayQuality) * .35);
    const homePace = safe(thiObservedRatingsData?.teams?.[home]?.ratings?.pace?.percentile, 50);
    const awayPace = safe(thiObservedRatingsData?.teams?.[away]?.ratings?.pace?.percentile, 50);
    const tempo = (homePace + awayPace) / 2;
    const awayAttack = teamPercentile(away, 'explosive_rate', 'offense');
    const homeExposure = 100 - teamPercentile(home, 'explosive_rate', 'defense');
    const homeAttack = teamPercentile(home, 'explosive_rate', 'offense');
    const awayExposure = 100 - teamPercentile(away, 'explosive_rate', 'defense');
    const breakaway = (awayAttack + homeExposure + homeAttack + awayExposure) / 4;
    const relevance = [home, away].map(name => {
      const season = seasonProjections?.[name];
      const ratio = safe(season?.expected_wins, 6) / Math.max(1, safe(season?.games, 12));
      return Math.max(0, Math.min(100, (ratio - .25) / .65 * 100));
    }).reduce((a, b) => a + b, 0) / 2;
    const score = Math.round(closeness * .45 + quality * .25 + tempo * .10 + breakaway * .10 + relevance * .10);
    const label = score >= 90 ? 'APPOINTMENT' : score >= 75 ? 'PRIME WINDOW' : score >= 55 ? 'ON THE RADAR' : 'STANDARD';
    return { score, label, components: { closeness, quality, tempo, breakaway, relevance } };
  }

  function watchMarkup(game, compact = true) {
    const watch = watchIndex(game);
    return `<div class="thi-watch ${compact ? 'compact' : ''}" title="THI Watch Index: contest tension, team standard, tempo pressure, breakaway potential and season weight"><strong>${watch.score}</strong><span>${html(watch.label)}</span></div>`;
  }

  function matchupWatchMarkup(game) {
    const watch = watchIndex(game);
    const c = watch.components;
    return `<section class="thi-watch-detail"><div><div class="eyebrow">THI viewing intelligence · frozen pregame</div><h3>Watch Index <strong>${watch.score}</strong></h3><p>${html(watch.label)} · a viewing guide, separate from Model Signal and betting value.</p></div><div class="thi-watch-components">${[['Contest tension', c.closeness], ['Team standard', c.quality], ['Tempo pressure', c.tempo], ['Breakaway potential', c.breakaway], ['Season weight', c.relevance]].map(([label, value]) => `<span><small>${html(label)}</small><strong>${Math.round(value)}</strong></span>`).join('')}</div></section>`;
  }

  root.THIIntelligence = { ...core, conferenceStrengthMarkup, watchIndex, watchMarkup, matchupWatchMarkup, outlookMarkup, enhanceDossier, loadOutlook };
  loadOutlook();

  const baseDossier = root.renderDossier;
  if (baseDossier) root.renderDossier = function(team) {
    const result = baseDossier.apply(this, arguments);
    enhanceDossier(team?.team);
    return result;
  };
})(typeof window !== 'undefined' ? window : null, () => {
  'use strict';
  return {
    probabilityDistribution(probabilities) {
      let distribution = [1];
      for (const raw of probabilities) {
        const p = Math.max(0, Math.min(1, Number(raw)));
        const next = Array(distribution.length + 1).fill(0);
        distribution.forEach((value, wins) => {
          next[wins] += value * (1 - p);
          next[wins + 1] += value * p;
        });
        distribution = next;
      }
      return distribution;
    },
  };
});
