(() => {
  const $ = id => document.getElementById(id);
  const fmt = (value, digits = 1) => value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits);
  const esc = value => String(value ?? '').replace(/[&<>"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]));
  const csvCell = value => `"${String(value ?? '').replaceAll('"','""')}"`;
  const state = { observations: [], filtered: [], teams: [] };

  function normalizeTeam(row, team) {
    const home = row.home_team === team;
    const predicted = Number(row.predicted_margin);
    const actual = Number(row.actual_margin);
    return { predicted: home ? predicted : -predicted, actual: home ? actual : -actual };
  }
  function profile(team) {
    const rows = state.observations.filter(row => row.home_team === team || row.away_team === team);
    let wins = 0, correct = 0, marginError = 0, totalError = 0, bias = 0;
    rows.forEach(row => { const n = normalizeTeam(row, team); if (n.actual > 0) wins++; if ((n.predicted > 0) === (n.actual > 0)) correct++; marginError += Math.abs(n.actual - n.predicted); bias += n.predicted - n.actual; totalError += Math.abs(Number(row.actual_total) - Number(row.predicted_total)); });
    return { team, n: rows.length, wins, losses: rows.length - wins, accuracy: rows.length ? correct / rows.length * 100 : 0, marginMae: rows.length ? marginError / rows.length : 0, totalMae: rows.length ? totalError / rows.length : 0, bias: rows.length ? bias / rows.length : 0, latest: rows.map(r => r.date).sort().at(-1) || '—' };
  }
  function teamCard(p) { return `<article class="team-card"><div class="eyebrow">Frozen historical profile</div><h3>${esc(p.team)}</h3><div class="comparison-metrics"><div><span>Games</span><strong>${p.n}</strong></div><div><span>SU record</span><strong>${p.wins}-${p.losses}</strong></div><div><span>Winner accuracy</span><strong>${fmt(p.accuracy)}%</strong></div><div><span>Margin MAE</span><strong>${fmt(p.marginMae)}</strong></div><div><span>Total MAE</span><strong>${fmt(p.totalMae)}</strong></div><div><span>Signed margin bias</span><strong>${p.bias > 0 ? '+' : ''}${fmt(p.bias)}</strong></div></div><p class="table-note">Latest frozen game: ${esc(p.latest)}</p></article>`; }
  function renderCompare() { $('compare-grid').innerHTML = teamCard(profile($('compare-a').value)) + teamCard(profile($('compare-b').value)); }
  function applyFilters() {
    const sport = $('archive-sport').value, team = $('archive-team').value.trim().toLowerCase(), from = $('archive-from').value, to = $('archive-to').value, venue = $('archive-venue').value, env = $('archive-env').value;
    state.filtered = state.observations.filter(row => (sport === 'all' || row.sport === sport) && (!team || row.home_team.toLowerCase().includes(team) || row.away_team.toLowerCase().includes(team)) && (!from || row.date >= from) && (!to || row.date <= to) && (venue === 'all' || row.venue === venue) && (env === 'all' || row.env_status === env));
    $('archive-count').textContent = `${state.filtered.length.toLocaleString()} frozen rows`;
    $('archive-rows').innerHTML = state.filtered.slice().reverse().slice(0, 200).map(row => { const url = row.sport === 'cbb' ? `/?sport=cbb&game=${encodeURIComponent(row.game_id)}` : `/#matchup=${encodeURIComponent(row.game_id)}`; return `<tr><td>${esc(row.date)}</td><td><a href="${url}">${esc(row.away_team)} @ ${esc(row.home_team)}</a></td><td>${fmt(row.predicted_margin)}</td><td>${fmt(row.actual_margin)}</td><td>${fmt(row.margin_error)}</td><td>${fmt(row.predicted_total)} / ${fmt(row.actual_total)}</td><td>${fmt(Number(row.home_win_probability) * (Number(row.home_win_probability) <= 1 ? 100 : 1))}%</td><td>${esc(row.signal || '—')}</td><td>${esc(row.env_status)}</td></tr>`; }).join('');
    $('archive-note').textContent = state.filtered.length > 200 ? `Showing the 200 most recent of ${state.filtered.length.toLocaleString()} matching rows. Export includes every match.` : `Showing all ${state.filtered.length.toLocaleString()} matching rows.`;
  }
  function exportFiltered() {
    const fields = ['season','sport','game_id','date','venue','away_team','home_team','predicted_margin','actual_margin','margin_error','predicted_total','actual_total','total_error','home_win_probability','signal','preferred_side','ats_result','clv','line_source','model_version','freeze_ts','market_policy_version','grading_policy_version','env_status'];
    const csv = [fields.join(','), ...state.filtered.map(row => fields.map(field => csvCell(row[field])).join(','))].join('\n');
    const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'})); link.download = 'thi-filtered-frozen-archive.csv'; link.click(); URL.revokeObjectURL(link.href);
  }
  function metric(label, value, note, cls='') { return `<article class="metric"><div class="metric-label">${esc(label)}</div><div class="metric-value ${cls}">${esc(value)}</div><small>${esc(note)}</small></article>`; }
  function coverageCard(label, value, copy, status) { return `<article class="coverage-card ${status}"><div class="eyebrow">${esc(label)}</div><strong>${esc(value)}</strong><p>${esc(copy)}</p></article>`; }
  async function init() {
    try {
      const [benchmark, outlook, bracket, health, registry] = await Promise.all(['data/reports/benchmark_center.json','data/thi_season_outlook.json','data/cbb/bracketology.json','data/cbb/platform_health.json','data/research_registry.json'].map(path => fetch(path, {cache:'no-store'}).then(r => { if (!r.ok) throw new Error(path); return r.json(); })));
      state.observations = benchmark.observations || [];
      state.filtered = state.observations;
      state.teams = [...new Set(state.observations.flatMap(row => [row.away_team,row.home_team]))].filter(Boolean).sort();
      $('status-grid').innerHTML = metric('Frozen observations', state.observations.length.toLocaleString(), 'Every public benchmark row', 'positive') + metric('CFB contract', benchmark.meta.contracts.cfb.env_status.toUpperCase(), benchmark.meta.contracts.cfb.model_version, 'blue') + metric('CBB contract', benchmark.meta.contracts.cbb.env_status.toUpperCase(), benchmark.meta.contracts.cbb.model_version, 'yellow') + metric('CBB platform health', health.meta.status.toUpperCase(), `${health.coverage.games.toLocaleString()} games · ${health.coverage.teams} teams`, health.meta.status === 'healthy' ? 'positive' : 'yellow');
      $('team-options').innerHTML = state.teams.map(t => `<option value="${esc(t)}"></option>`).join('');
      const opts = state.teams.map(t => `<option>${esc(t)}</option>`).join(''); $('compare-a').innerHTML = opts; $('compare-b').innerHTML = opts; $('compare-a').value = state.teams[0]; $('compare-b').value = state.teams[1] || state.teams[0];
      const cfbTeams = Object.values(outlook.teams || {}).sort((a,b) => Number(b.overall.expected_wins)-Number(a.overall.expected_wins)).slice(0,8);
      $('cfb-sim-status').textContent = outlook.meta.status; $('cfb-sim-copy').textContent = `Through Week ${outlook.meta.through_week}. ${outlook.meta.method}. Fixed probabilities only; this does not alter Model A.`; $('cfb-sim-list').innerHTML = cfbTeams.map((t,i) => `<div class="rank-row"><b>${i+1}</b><span>${esc(t.team)} <small>${esc(t.conference)}</small></span><strong>${fmt(t.overall.expected_wins,2)} EW · ${esc(t.overall.most_likely_record)}</strong></div>`).join('');
      $('cbb-sim-status').textContent = bracket.meta.forecast_type.replaceAll('_',' '); $('cbb-sim-copy').textContent = bracket.meta.limitations; $('cbb-sim-list').innerHTML = (bracket.field || []).slice().sort((a,b)=>a.overall_rank-b.overall_rank).slice(0,8).map(t => `<div class="rank-row"><b>${t.overall_rank}</b><span>${esc(t.team)} <small>${esc(t.conference?.abbreviation || '')}</small></span><strong>${esc(t.bid_type)} · ${fmt(t.selection_score,2)}</strong></div>`).join('');
      $('coverage-grid').innerHTML = coverageCard('Verified roster layer', health.coverage.published_roster_players.toLocaleString(), `${health.coverage.teams} teams; provider-verified and THI roster audit ${health.coverage.roster_audit_status}.`, 'ready') + coverageCard('Projected core lineups', 'Research-ready', 'Player ratings support projected rotation context. They are not claimed as observed possession-level on/off lineups.', 'ready') + coverageCard('Verified availability', `${health.coverage.verified_availability_reports} reports`, 'No timestamped reports means no injury adjustment is applied. THI withholds unsupported impact claims.', 'withheld');
      $('research-registry').innerHTML = `<h3>Public research cadence</h3><p class="table-note">${esc(registry.meta.cadence)}</p>` + registry.notes.map(note => `<div class="registry-entry"><a href="${esc(note.url)}">${esc(note.title)} →</a><p>${esc(note.question)}</p><small>${esc(note.method)} · Production effect: ${esc(note.production_effect)}</small></div>`).join('');
      $('generated').textContent = `Audit generated ${benchmark.meta.generated_at_utc}`;
      ['archive-sport','archive-team','archive-from','archive-to','archive-venue','archive-env'].forEach(id => $(id).addEventListener(id === 'archive-team' ? 'input' : 'change', applyFilters)); $('archive-export').addEventListener('click', exportFiltered); $('compare-a').addEventListener('change', renderCompare); $('compare-b').addEventListener('change', renderCompare);
      applyFilters(); renderCompare(); $('workbench-loading').hidden = true; $('workbench-app').hidden = false;
    } catch (error) { $('workbench-loading').textContent = 'The public research contracts could not be loaded. Please refresh shortly.'; console.error(error); }
  }
  init();
})();
