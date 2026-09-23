/* Public first-snapshot scorecard and gated private market portfolio. */
(() => {
  const config = window.THI_PORTFOLIO_CONFIG || {};
  const nav = document.querySelector('.main-nav');
  const main = document.querySelector('main.page');
  if (!nav || !main) return;
  const style = document.createElement('style');
  style.textContent = `
    .research-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:14px;margin:18px 0}
    .research-card{background:var(--surface,#fff);border:1px solid var(--border,#ddd);border-radius:12px;padding:18px}
    .research-card h2{font-size:17px;margin:0 0 10px;color:var(--text,#1d2730)}
    .research-card p,.research-muted{color:var(--muted,#5b6974);font-size:13px;line-height:1.6}
    .research-card strong{font-size:24px;color:var(--text,#1d2730)}
    .research-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
    .research-form label{display:grid;gap:5px;font-size:13px;font-weight:600}
    .research-form [hidden]{display:none!important}
    .research-form input,.research-form select,.research-form textarea{width:100%;padding:11px;border:1px solid var(--border,#ccc);border-radius:7px;font:inherit;background:white;color:#202a32}
    .research-form textarea{min-height:78px;resize:vertical}
    .research-wide{grid-column:1/-1}.research-action{background:#135a48;color:white;border:0;border-radius:8px;padding:11px 16px;cursor:pointer;font:inherit;font-size:13px;font-weight:600}
    .research-row{border-top:1px solid var(--border,#ddd);padding:12px 0;font-size:13px;line-height:1.6}
    .research-delete{background:transparent;color:#a32728;border:1px solid #d9a4a5;border-radius:7px;padding:7px 10px;cursor:pointer;font:inherit;margin-top:8px}
    .research-preview{grid-column:1/-1;border:1px solid var(--border,#ddd);border-radius:8px;padding:11px;font-size:13px;font-weight:600;background:#f5f8f7}
    .research-row:last-child{padding-bottom:0}.research-stack{display:grid;gap:16px;margin:18px 0}
    .research-error{color:#a32728}.research-positive{color:#116b4a;font-weight:700}
  `;
  document.head.appendChild(style);
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'nav-item'; button.dataset.view = 'research';
  button.textContent = 'Market Research'; button.onclick = () => switchView('research');
  nav.append(button);
  const view = document.createElement('section');
  view.id = 'view-research'; view.className = 'view';
  view.innerHTML = `<div class="eyebrow">THI research</div><h1 class="page-title">Market Research</h1>
    <p class="page-subtitle">First-snapshot model accountability and a private workspace for evaluating your line selection.</p>
    <div id="research-scorecard" aria-live="polite"><p class="research-muted">Loading weekly scorecard…</p></div>
    <div class="research-card"><h2>Private portfolio</h2><div id="research-private" aria-live="polite"></div></div>`;
  main.append(view);
  const $ = selector => view.querySelector(selector);
  const privateBox = $('#research-private');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const number = value => Number.isFinite(Number(value)) && value !== null ? Number(value).toFixed(2) : '—';
  const time = value => value ? new Date(value).toLocaleString() : '—';
  const line = value => Number(value) > 0 ? `+${number(value)}` : number(value);
  let client, games = [], history = {}, closings = {};

  fetch('./data/reports/weekly_model_scorecard.json', {cache:'no-store'}).then(r => {
    if (!r.ok) throw Error('Scorecard not published yet'); return r.json();
  }).then(data => {
    $('#research-scorecard').innerHTML = `<h2>Weekly Model A scorecard</h2>
      <p class="research-muted">${esc(data.definition)}</p><div class="research-grid">${data.weeks.filter(w => w.settled_games || w.week <= Math.max(0, ...data.weeks.filter(s => s.settled_games).map(s => s.week)) + 1).map(w => `
      <div class="research-card"><h2>Week ${esc(w.week)}</h2>
      <strong>${esc(w.settled_games)} settled</strong>
      <p>Margin MAE: ${number(w.margin_mae_points)} pts (${esc(w.margin_sample)} games)<br>
      Total MAE: ${number(w.total_mae_points)} pts (${esc(w.total_sample)} games)<br>
      Unsettled or unmatched: ${esc(w.unsettled_or_unmatched)} of ${esc(w.games_with_frozen_snapshots)} captured.</p></div>`).join('')}</div>
      <p class="research-muted">Latest included kickoff: ${esc(time(data.latest_settled_kickoff_utc))}. Metrics use the first captured prospective projection for each game.</p>`;
  }).catch(() => { $('#research-scorecard').innerHTML = '<p class="research-muted">Weekly scorecard pending its first settlement run.</p>'; });

  if (!config.enabled || !/^https:\/\/[^/]+\.supabase\.co$/.test(config.url || '') || !config.publishableKey) {
    privateBox.innerHTML = '<p class="research-muted">Private play logging is being set up. The weekly scorecard above is available now.</p>';
    return;
  }
  const library = document.createElement('script');
  library.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
  library.onload = async () => {
    if (!window.supabase?.createClient) { privateBox.textContent = 'Sign-in library unavailable.'; return; }
    client = window.supabase.createClient(config.url, config.publishableKey);
    client.auth.onAuthStateChange(() => setTimeout(refresh, 0));
    await refresh();
  };
  library.onerror = () => { privateBox.textContent = 'Sign-in library unavailable.'; };
  document.head.append(library);

  async function refresh() {
    const {data:{user}, error} = await client.auth.getUser();
    if (error || !user) {
      privateBox.innerHTML = `<p class="research-muted">Sign in by email to keep your plays and research notes private.</p>
      <form id="research-login" class="research-form"><label>Email<input name="email" type="email" required autocomplete="email"></label>
      <button class="research-action" type="submit">Email me a sign-in link</button></form><p id="research-message" role="status"></p>`;
      $('#research-login').onsubmit = async ev => {
        ev.preventDefault();
        const email = new FormData(ev.currentTarget).get('email');
        const {error: sendError} = await client.auth.signInWithOtp({email, options:{emailRedirectTo:location.origin + location.pathname}});
        $('#research-message').textContent = sendError ? sendError.message : 'Check your email for your sign-in link.';
      };
      return;
    }
    try { await Promise.all([loadGames(), loadMarket()]); }
    catch (_) { privateBox.innerHTML = '<p class="research-error">Game or market data unavailable. Try again shortly.</p>'; return; }
    const {data: plays, error: readError} = await client.from('portfolio_plays').select('*').order('recorded_at', {ascending:false}).limit(100);
    if (readError) { privateBox.innerHTML = `<p class="research-error">Portfolio unavailable: ${esc(readError.message)}</p>`; return; }
    const future = games.filter(g => g.game_id != null && new Date(g.start_date).getTime() > Date.now());
    privateBox.innerHTML = `<p class="research-muted">Signed in as ${esc(user.email)}. These entries are self-reported; the server timestamp records when you logged them, not when a sportsbook accepted a wager.</p>
      <button type="button" id="research-logout">Sign out</button>
      <div class="research-stack"><div><h3>Log a line</h3>
      <form id="research-entry" class="research-form">
      <label class="research-wide">Upcoming game<select name="game_id" required><option value="">Choose game</option>${future.map(g => `<option value="${esc(g.game_id)}">${esc(g.away?.team)} at ${esc(g.home?.team)} · ${esc(time(g.start_date))}</option>`).join('')}</select></label>
      <label>Market<select name="market"><option value="spread">Spread</option><option value="moneyline">Moneyline</option><option value="total">Total</option></select></label>
      <label>Selection<select name="selection" required></select></label>
      <label id="research-line-field">Spread for selected team (− favorite / + underdog)<input name="line" type="number" min="-150" max="150" step="0.5" required></label>
      <label>Sportsbook<input name="sportsbook" maxlength="100" required></label>
      <label>American odds<input name="american_odds" type="number" min="-10000" max="10000" step="1" placeholder="−110 or +120" required></label>
      <label>Units risked<input name="units_risked" type="number" min="0.01" max="1000" step="0.01" placeholder="1.00" required></label>
      <div id="research-preview" class="research-preview" aria-live="polite"></div>
      <label class="research-wide">Private research notes<textarea name="note" maxlength="5000"></textarea></label>
      <button class="research-action" type="submit">Save private entry</button></form><p id="research-message" role="status"></p></div>
      <div><h3>Your entries</h3><div id="research-entries"></div></div></div>`;
    $('#research-logout').onclick = () => client.auth.signOut();
    const entry = $('#research-entry');
    const marketInput = entry.elements.market, sideInput = entry.elements.selection;
    const lineInput = entry.elements.line, oddsInput = entry.elements.american_odds;
    const updateEntry = () => {
      const market = marketInput.value;
      const selectedGame = future.find(g => String(g.game_id) === entry.elements.game_id.value);
      const options = market === 'total' ? [['over', 'Over'], ['under', 'Under']] :
        [['away', selectedGame?.away?.team || 'Away'], ['home', selectedGame?.home?.team || 'Home']];
      const previous = sideInput.value;
      sideInput.innerHTML = options.map(([value, label]) => `<option value="${value}">${esc(label)}</option>`).join('');
      if (options.some(([value]) => value === previous)) sideInput.value = previous;
      const lineField = $('#research-line-field');
      lineField.hidden = market === 'moneyline';
      lineInput.required = market !== 'moneyline';
      if (market === 'moneyline') lineInput.value = '';
      else lineField.firstChild.textContent = market === 'total' ? 'Game total (points)' : 'Spread for selected team (− favorite / + underdog)';
      lineInput.min = market === 'total' ? '0.5' : '-150';
      oddsInput.required = true;
      const spread = lineInput.value === '' ? null : Number(lineInput.value);
      const odds = oddsInput.value === '' ? null : Number(oddsInput.value);
      const type = market === 'spread' && spread !== null ? (spread < 0 ? 'Favorite' : spread > 0 ? 'Underdog' : 'Pick’em') :
        market === 'moneyline' && odds !== null ? (odds < 0 ? 'Moneyline favorite' : odds > 0 ? 'Moneyline underdog' : 'Enter American odds') : '';
      const side = sideInput.selectedOptions[0]?.textContent || 'Choose a side';
      const priceText = odds === null ? '' : ` · ${odds > 0 ? '+' : ''}${odds} odds`;
      $('#research-preview').textContent = `${market === 'total' ? side + ' total' : side + (type ? ' · ' + type : '')}${spread !== null && market !== 'moneyline' ? ' ' + (spread > 0 ? '+' : '') + spread : ''}${priceText}`;
    };
    ['change', 'input'].forEach(eventName => entry.addEventListener(eventName, updateEntry));
    updateEntry();
    $('#research-entry').onsubmit = async ev => {
      ev.preventDefault(); const form = new FormData(ev.currentTarget);
      const game = future.find(g => String(g.game_id) === form.get('game_id'));
      if (!game || new Date(game.start_date).getTime() <= Date.now()) { $('#research-message').textContent = 'Game is no longer upcoming.'; return; }
      const market = form.get('market'), selection = form.get('selection');
      const price = Number(form.get('american_odds'));
      const units = Number(form.get('units_risked'));
      const spread = form.get('line') === '' ? null : Number(form.get('line'));
      if (!Number.isInteger(price) || (price > -100 && price < 100) || Math.abs(price) > 10000 ||
          !Number.isFinite(units) || units <= 0 || units > 1000 ||
          (market !== 'moneyline' && (spread === null || !Number.isFinite(spread) ||
            (market === 'total' && spread <= 0)))) {
        $('#research-message').textContent = 'Check your odds, line, and units before saving.'; return;
      }
      const item = {game_id:String(game.game_id), away_team:game.away.team,home_team:game.home.team,
        kickoff_at:game.start_date, market, selection,
        line:market === 'moneyline' ? null : spread, sportsbook:String(form.get('sportsbook')).trim(),note:String(form.get('note')).trim(),
        american_odds:price, units_risked:units};
      const {error: saveError} = await client.from('portfolio_plays').insert(item);
      if (saveError) $('#research-message').textContent = saveError.message;
      else await refresh();
    };
    $('#research-entries').innerHTML = plays.length ? plays.map(p => {
      const close = closings[p.game_id];
      const closingSpread = Number(close?.closing_market?.home_spread);
      const closingTotal = Number(close?.closing_market?.total);
      const qualifies = close && new Date(p.recorded_at) <= new Date(close.captured_at_utc) &&
        new Date(close.captured_at_utc) < new Date(close.scheduled_kickoff_utc);
      const comparison = qualifies && p.market === 'spread' && Number.isFinite(closingSpread) && close?.closing_market?.home_spread != null ?
        Number(p.line) - (p.selection === 'home' ? closingSpread : -closingSpread) :
        qualifies && p.market === 'total' && Number.isFinite(closingTotal) && close?.closing_market?.total != null ?
          (p.selection === 'over' ? closingTotal - Number(p.line) : Number(p.line) - closingTotal) : null;
      const trail = history[p.game_id]?.snapshots || [];
      const selectedTeam = p.selection === 'home' ? p.home_team : p.selection === 'away' ? p.away_team : p.selection;
      const ticket = `${selectedTeam}${p.line == null ? '' : ' ' + line(p.line)}`;
      const priceLabel = p.american_odds == null ? 'odds not logged' : `${p.american_odds > 0 ? '+' : ''}${p.american_odds} odds`;
      const unitsLabel = p.units_risked == null ? 'units not logged' : `${number(p.units_risked)}u risked`;
      return `<div class="research-row"><strong>${esc(p.away_team)} at ${esc(p.home_team)} · ${esc(ticket)}</strong><br>
        ${esc(p.sportsbook)} · logged ${esc(time(p.recorded_at))} · ${esc(p.market)} · ${esc(priceLabel)} · ${esc(unitsLabel)}<br>
        ${p.market === 'moneyline' ? 'Moneyline closing comparison unavailable with current snapshots' : comparison === null ? 'No qualifying pre-kickoff closing proxy after entry' : `<span class="${comparison > 0 ? 'research-positive' : ''}">Line difference vs near-kickoff proxy: ${line(comparison)} pts</span>`}
        ${comparison !== null ? ` · captured ${esc(time(close.captured_at_utc))} · proxy book: ${esc(close.closing_market?.bookmaker || 'unknown')}` : ''}<br>
        <span class="research-muted">Logged entry is unverified user input. Line difference is descriptive; a different sportsbook may have supplied the proxy.</span>
        <details><summary>Market chronology (${trail.length} captures)</summary>${trail.length ? trail.slice(-30).map(s => `<div>${esc(time(s.captured_at))} · home ${line(s.home_spread)} · ${new Date(s.captured_at) <= new Date(p.recorded_at) ? 'before entry' : 'after entry'}</div>`).join('') : 'No market history captured.'}</details>
        <details><summary>Private research note</summary><textarea data-note="${esc(p.id)}" maxlength="5000">${esc(p.note)}</textarea><button type="button" data-save="${esc(p.id)}">Save note</button></details>
        <button type="button" class="research-delete" data-delete="${esc(p.id)}">Delete entry</button></div>`;
    }).join('') : '<p class="research-muted">No plays logged yet.</p>';
    $('#research-entries').onclick = async ev => {
      const deleteId = ev.target.dataset.delete;
      if (deleteId) {
        if (!confirm('Delete this private entry permanently?')) return;
        ev.target.disabled = true;
        const {error: deleteError} = await client.from('portfolio_plays').delete().eq('id', deleteId);
        if (deleteError) { alert(deleteError.message); ev.target.disabled = false; }
        else await refresh();
        return;
      }
      const id = ev.target.dataset.save; if (!id) return;
      const note = [...$('#research-entries').querySelectorAll('textarea[data-note]')].find(el => el.dataset.note === id)?.value;
      const {error: updateError} = await client.from('portfolio_plays').update({note}).eq('id', id);
      if (updateError) alert(updateError.message); else ev.target.textContent = 'Saved';
    };
  }

  async function loadGames() {
    if (games.length) return;
    const response = await fetch('./data/projections.json');
    if (response.ok) { const data = await response.json(); games = data.games || data.projections || []; }
  }
  async function loadMarket() {
    if (!Object.keys(history).length) {
      const response = await fetch('./data/market_history.json');
      if (response.ok) history = (await response.json()).games || {};
    }
    if (!Object.keys(closings).length) {
      const response = await fetch('./data/snapshots/closing_lines.jsonl');
      if (response.ok) for (const raw of (await response.text()).split('\n')) {
        if (!raw.trim()) continue;
        try { const item = JSON.parse(raw); if (item.game_key) closings[String(item.game_key)] = item; } catch (_) { /* Skip incomplete line. */ }
      }
    }
  }
})();
