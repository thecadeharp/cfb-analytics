const METRICS_URL='https://thecadeharp.github.io/cfb-analytics/data/cfb_metrics.json';
const CFBD_KEY='Cc1tNdU6zu7dSX/c5DzpoL9X25p07Gao6SITBOzABwxgO1I1WKhoWsHBl9uw0Omr';
const CFBD_BASE='https://api.collegefootballdata.com';
const HFA=2.5,PLAY_THR=5,LEAN_THR=2;
let metricsData=null,allTeams=[],currentGames=[],currentLines=[],plays=JSON.parse(localStorage.getItem('ht_plays')||'[]'),editingPlayId=null,currentEffView='offense',playoffData=null;

const cfbd=path=>fetch(CFBD_BASE+path,{headers:{'Authorization':`Bearer ${CFBD_KEY}`}}).then(r=>r.ok?r.json():Promise.reject(r.status));
const fmt=n=>n==null?'—':(n>0?'+':'')+parseFloat(n).toFixed(1);
const fmtEPA=n=>n==null?'—':(n>0?'+':'')+parseFloat(n).toFixed(3);

function rankBadge(rank,total=136){
  if(!rank)return'<span class="rank-badge r-neu">—</span>';
  const cls=rank<=total*0.15?'r-elite':rank<=total*0.40?'r-good':rank<=total*0.70?'r-mid':'r-bad';
  return`<span class="rank-badge ${cls}">#${rank}</span>`;
}
function mc(val,higherBetter=true){
  if(val==null)return'mv-neu';
  const v=parseFloat(val);
  if(isNaN(v))return'mv-neu';
  return higherBetter?(v>0?'mv-pos':v<0?'mv-neg':'mv-neu'):(v<0?'mv-pos':v>0?'mv-neg':'mv-neu');
}

function switchTab(tab){
  const tabs=['ratings','efficiency','lines','plays','playoff','dossier'];
  document.querySelectorAll('.nav-tab').forEach((t,i)=>t.classList.toggle('active',tabs[i]===tab));
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.getElementById('view-'+tab).classList.add('active');
  if(tab==='plays')renderPlays();
  if(tab==='lines'&&!currentGames.length)loadGames();
  if(tab==='playoff')loadPlayoff();
  if(tab==='efficiency'&&metricsData&&allTeams.length)filterEff();
}
function switchEff(side,el){
  currentEffView=side;
  document.querySelectorAll('.eff-tab').forEach(t=>t.classList.remove('active'));
  el.classList.add('active');
  if(metricsData&&allTeams.length)filterEff();
}

async function init(){
  try{
    const res=await fetch(METRICS_URL);
    if(!res.ok)throw new Error(`HTTP ${res.status}`);
    metricsData=await res.json();
    allTeams=Object.values(metricsData.teams);
    const gen=metricsData.meta?.generated;
    if(gen){const d=new Date(gen);document.getElementById('data-updated').textContent=`Data: ${d.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}`;}
    const confs=[...new Set(allTeams.map(t=>t.conference).filter(Boolean))].sort();
    ['conf-filter','eff-conf'].forEach(id=>{
      const sel=document.getElementById(id);
      if(!sel)return;
      confs.forEach(c=>{const o=document.createElement('option');o.value=o.textContent=c;sel.appendChild(o);});
    });
    const sorted=[...allTeams].sort((a,b)=>b.power_rating-a.power_rating);
    document.getElementById('ov-teams').textContent=allTeams.length;
    if(sorted[0]){document.getElementById('ov-top').textContent=sorted[0].team;document.getElementById('ov-top-sub').textContent=`Rating: ${sorted[0].power_rating?.toFixed(2)}`;}
    const topOff=[...allTeams].sort((a,b)=>(b.offense?.epa_play||0)-(a.offense?.epa_play||0))[0];
    const topDef=[...allTeams].sort((a,b)=>(a.defense?.epa_play||0)-(b.defense?.epa_play||0))[0];
    if(topOff){document.getElementById('ov-off').textContent=topOff.team;document.getElementById('ov-off-sub').textContent=`EPA/play: ${fmtEPA(topOff.offense?.epa_play)}`;}
    if(topDef){document.getElementById('ov-def').textContent=topDef.team;document.getElementById('ov-def-sub').textContent=`EPA/play: ${fmtEPA(topDef.defense?.epa_play)}`;}
    filterRatings();renderPlays();
  }catch(e){
    document.getElementById('ratings-container').innerHTML=`<div class="empty-state" style="color:var(--red)">Failed to load metrics: ${e}<br><small>URL: ${METRICS_URL}</small></div>`;
    console.error('Init error:',e);
  }
}

function filterRatings(q=''){
  if(!metricsData){return;}
  const search=q||document.querySelector('#view-ratings input')?.value||'';
  const conf=document.getElementById('conf-filter').value;
  const sortKey=document.getElementById('sort-ratings').value;
  let data=[...allTeams].filter(t=>t.team?.toLowerCase().includes(search.toLowerCase())).filter(t=>!conf||t.conference===conf);
  data.sort((a,b)=>{
    if(sortKey==='off_epa')return(b.offense?.epa_play||0)-(a.offense?.epa_play||0);
    if(sortKey==='def_epa')return(a.defense?.epa_play||0)-(b.defense?.epa_play||0);
    if(sortKey==='net_epa')return(b.net?.epa||0)-(a.net?.epa||0);
    return(b.power_rating||0)-(a.power_rating||0);
  });
  if(!data.length){document.getElementById('ratings-container').innerHTML='<div class="empty-state">No teams match.</div>';return;}
  const total=allTeams.length;
  const rows=data.map((t,i)=>{
    const rec=t.record?`${t.record.wins}-${t.record.losses}`:'—';
    return`<tr onclick="openDossier('${t.team.replace(/'/g,"\\'")}')">
      <td><span class="mono" style="color:var(--muted)">${i+1}</span></td>
      <td style="font-weight:700">${t.team} <span style="font-size:10px;padding:2px 6px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted);margin-left:6px">${t.conference||'—'}</span></td>
      <td class="mono" style="color:var(--text)">${rec}</td>
      <td><span class="mono ${t.power_rating>0?'mv-pos':t.power_rating<0?'mv-neg':'mv-neu'}">${t.power_rating?.toFixed(2)??'—'}</span></td>
      <td><span class="mono ${mc(t.offense?.epa_play)}">${fmtEPA(t.offense?.epa_play)}</span> ${rankBadge(t.offense?.epa_play_rank,total)}</td>
      <td><span class="mono ${mc(t.defense?.epa_play,false)}">${fmtEPA(t.defense?.epa_play)}</span> ${rankBadge(t.defense?.epa_play_rank,total)}</td>
      <td><span class="mono ${mc(t.net?.epa)}">${fmtEPA(t.net?.epa)}</span></td>
      <td class="mono" style="color:var(--muted)">${t.offense?.success_rate?.toFixed(1)??'—'}%</td>
      <td class="mono" style="color:var(--muted)">${t.defense?.success_rate?.toFixed(1)??'—'}%</td>
      <td class="mono" style="color:var(--muted)">${t.defense?.havoc_created?.toFixed(1)??'—'}%</td>
    </tr>`;
  }).join('');
  document.getElementById('ratings-container').innerHTML=`<div class="tbl-wrap"><table>
    <thead><tr><th>#</th><th>Team</th><th>Record</th><th>Power Rtg</th><th>Off EPA/Play</th><th>Def EPA/Play</th><th>Net EPA</th><th>Off SR%</th><th>Def SR%</th><th>Def Havoc%</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function filterEff(q=''){
  if(!metricsData||!allTeams.length){
    document.getElementById('eff-container').innerHTML='<div class="empty-state">Loading data...</div>';
    return;
  }
  const search=q||document.querySelector('#view-efficiency input')?.value||'';
  const conf=document.getElementById('eff-conf').value;
  const side=currentEffView;
  let data=[...allTeams].filter(t=>t.team?.toLowerCase().includes(search.toLowerCase())).filter(t=>!conf||t.conference===conf);
  const total=allTeams.length;
  if(side==='offense'){
    data.sort((a,b)=>(b.offense?.epa_play||0)-(a.offense?.epa_play||0));
    const rows=data.map((t,i)=>{const o=t.offense||{};return`<tr onclick="openDossier('${t.team.replace(/'/g,"\\'")}')">
      <td class="mono" style="color:var(--muted)">${i+1}</td>
      <td style="font-weight:700">${t.team} <span style="font-size:10px;padding:2px 5px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted)">${t.conference||''}</span></td>
      <td><span class="mono ${mc(o.epa_play)}">${fmtEPA(o.epa_play)}</span> ${rankBadge(o.epa_play_rank,total)}</td>
      <td><span class="mono ${mc(o.epa_pass)}">${fmtEPA(o.epa_pass)}</span> ${rankBadge(o.epa_pass_rank,total)}</td>
      <td><span class="mono ${mc(o.epa_rush)}">${fmtEPA(o.epa_rush)}</span> ${rankBadge(o.epa_rush_rank,total)}</td>
      <td><span class="mono">${o.success_rate?.toFixed(1)??'—'}%</span> ${rankBadge(o.sr_rank,total)}</td>
      <td><span class="mono">${o.pass_sr?.toFixed(1)??'—'}%</span> ${rankBadge(o.pass_sr_rank,total)}</td>
      <td><span class="mono">${o.rush_sr?.toFixed(1)??'—'}%</span> ${rankBadge(o.rush_sr_rank,total)}</td>
      <td><span class="mono">${o.explosive_rate?.toFixed(1)??'—'}%</span> ${rankBadge(o.expl_rank,total)}</td>
      <td><span class="mono ${mc(o.havoc_allowed,false)}">${o.havoc_allowed?.toFixed(1)??'—'}%</span></td>
    </tr>`;}).join('');
    document.getElementById('eff-container').innerHTML=`<div class="tbl-wrap"><table>
      <thead><tr><th>#</th><th>Team</th><th>EPA/Play</th><th>EPA/Pass</th><th>EPA/Rush</th><th>SR%</th><th>Pass SR%</th><th>Rush SR%</th><th>Expl%</th><th>Havoc Allowed%</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }else if(side==='defense'){
    data.sort((a,b)=>(a.defense?.epa_play||0)-(b.defense?.epa_play||0));
    const rows=data.map((t,i)=>{const d=t.defense||{};return`<tr onclick="openDossier('${t.team.replace(/'/g,"\\'")}')">
      <td class="mono" style="color:var(--muted)">${i+1}</td>
      <td style="font-weight:700">${t.team} <span style="font-size:10px;padding:2px 5px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted)">${t.conference||''}</span></td>
      <td><span class="mono ${mc(d.epa_play,false)}">${fmtEPA(d.epa_play)}</span> ${rankBadge(d.epa_play_rank,total)}</td>
      <td><span class="mono ${mc(d.epa_pass,false)}">${fmtEPA(d.epa_pass)}</span> ${rankBadge(d.epa_pass_rank,total)}</td>
      <td><span class="mono ${mc(d.epa_rush,false)}">${fmtEPA(d.epa_rush)}</span> ${rankBadge(d.epa_rush_rank,total)}</td>
      <td><span class="mono">${d.success_rate?.toFixed(1)??'—'}%</span> ${rankBadge(d.sr_rank,total)}</td>
      <td><span class="mono">${d.pass_sr?.toFixed(1)??'—'}%</span> ${rankBadge(d.pass_sr_rank,total)}</td>
      <td><span class="mono">${d.rush_sr?.toFixed(1)??'—'}%</span> ${rankBadge(d.rush_sr_rank,total)}</td>
      <td><span class="mono">${d.explosive_rate?.toFixed(1)??'—'}%</span> ${rankBadge(d.expl_rank,total)}</td>
      <td><span class="mono ${mc(d.havoc_created)}">${d.havoc_created?.toFixed(1)??'—'}%</span> ${rankBadge(d.havoc_rank,total)}</td>
    </tr>`;}).join('');
    document.getElementById('eff-container').innerHTML=`<div class="tbl-wrap"><table>
      <thead><tr><th>#</th><th>Team</th><th>EPA/Play</th><th>EPA/Pass</th><th>EPA/Rush</th><th>SR%</th><th>Pass SR%</th><th>Rush SR%</th><th>Expl%</th><th>Havoc Created%</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }else{
    data.sort((a,b)=>(b.net?.epa||0)-(a.net?.epa||0));
    const rows=data.map((t,i)=>{const n=t.net||{};return`<tr onclick="openDossier('${t.team.replace(/'/g,"\\'")}')">
      <td class="mono" style="color:var(--muted)">${i+1}</td>
      <td style="font-weight:700">${t.team} <span style="font-size:10px;padding:2px 5px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted)">${t.conference||''}</span></td>
      <td><span class="mono ${mc(n.epa)}">${fmtEPA(n.epa)}</span> ${rankBadge(n.epa_rank,total)}</td>
      <td><span class="mono ${mc(n.epa_pass)}">${fmtEPA(n.epa_pass)}</span></td>
      <td><span class="mono ${mc(n.epa_rush)}">${fmtEPA(n.epa_rush)}</span></td>
      <td><span class="mono ${mc(n.sr)}">${n.sr?.toFixed(1)??'—'}%</span></td>
    </tr>`;}).join('');
    document.getElementById('eff-container').innerHTML=`<div class="tbl-wrap"><table>
      <thead><tr><th>#</th><th>Team</th><th>Net EPA/Play</th><th>Net EPA/Pass</th><th>Net EPA/Rush</th><th>Net SR%</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
  }
}

function getPR(team){return metricsData?.teams?.[team]?.power_rating??null;}
function projSpread(h,a){const hp=getPR(h),ap=getPR(a);if(hp==null||ap==null)return null;return-((hp-ap)+HFA*0.3);}
function winProb(h,a){const hp=getPR(h)??0,ap=getPR(a)??0,diff=(hp-ap)+HFA*0.3,wp=Math.round(50+diff*5);return{home:Math.min(99,Math.max(1,wp)),away:Math.min(99,Math.max(1,100-wp))};}

const ODDS_KEY='ea5ecbb48466b55c9d83a78d520afba3';
const ODDS_BASE='https://api.the-odds-api.com/v4';

// Team name mapping from Odds API format to our metrics format
const TEAM_MAP={
  'Ohio State Buckeyes':'Ohio State','Michigan Wolverines':'Michigan','Georgia Bulldogs':'Georgia',
  'Alabama Crimson Tide':'Alabama','Notre Dame Fighting Irish':'Notre Dame','Texas Longhorns':'Texas',
  'Penn State Nittany Lions':'Penn State','Oregon Ducks':'Oregon','Indiana Hoosiers':'Indiana',
  'Miami Hurricanes':'Miami','LSU Tigers':'LSU','Tennessee Volunteers':'Tennessee',
  'Oklahoma Sooners':'Oklahoma','Clemson Tigers':'Clemson','Utah Utes':'Utah',
  'Florida State Seminoles':'Florida State','TCU Horned Frogs':'TCU','USC Trojans':'USC',
  'Wisconsin Badgers':'Wisconsin','Iowa Hawkeyes':'Iowa','Ole Miss Rebels':'Ole Miss',
  'Texas A&M Aggies':'Texas A&M','Kansas State Wildcats':'Kansas State','Washington Huskies':'Washington',
  'North Carolina Tar Heels':'North Carolina','Missouri Tigers':'Missouri','Arkansas Razorbacks':'Arkansas',
  'Mississippi State Bulldogs':'Mississippi State','Louisville Cardinals':'Louisville',
  'Pittsburgh Panthers':'Pittsburgh','Cincinnati Bearcats':'Cincinnati','UCF Knights':'UCF',
  'Houston Cougars':'Houston','BYU Cougars':'BYU','Baylor Bears':'Baylor',
  'Iowa State Cyclones':'Iowa State','Oklahoma State Cowboys':'Oklahoma State',
  'Kansas Jayhawks':'Kansas','West Virginia Mountaineers':'West Virginia',
  'Texas Tech Red Raiders':'Texas Tech','Colorado Buffaloes':'Colorado',
  'Arizona Wildcats':'Arizona','Arizona State Sun Devils':'Arizona State',
  'Utah Utes':'Utah','Air Force Falcons':'Air Force','Boise State Broncos':'Boise State',
  'Colorado State Rams':'Colorado State','Fresno State Bulldogs':'Fresno State',
  'Hawaii Rainbow Warriors':'Hawaii','Nevada Wolf Pack':'Nevada',
  'New Mexico Lobos':'New Mexico','San Diego State Aztecs':'San Diego State',
  'San Jose State Spartans':'San Jose State','UNLV Rebels':'UNLV',
  'Utah State Aggies':'Utah State','Wyoming Cowboys':'Wyoming',
  'Appalachian State Mountaineers':'Appalachian State','Arkansas State Red Wolves':'Arkansas State',
  'Georgia Southern Eagles':'Georgia Southern','Georgia State Panthers':'Georgia State',
  'Louisiana Ragin Cajuns':'Louisiana','Louisiana Monroe Warhawks':'Louisiana Monroe',
  'South Alabama Jaguars':'South Alabama','Texas State Bobcats':'Texas State',
  'Troy Trojans':'Troy','Marshall Thundering Herd':'Marshall',
  'Middle Tennessee Blue Raiders':'Middle Tennessee','Florida Atlantic Owls':'Florida Atlantic',
  'Florida International Panthers':'FIU','Louisiana Tech Bulldogs':'Louisiana Tech',
  'North Texas Mean Green':'North Texas','Old Dominion Monarchs':'Old Dominion',
  'Rice Owls':'Rice','Southern Miss Golden Eagles':'Southern Miss',
  'UTEP Miners':'UTEP','UTSA Roadrunners':'UTSA','Western Kentucky Hilltoppers':'Western Kentucky',
  'Akron Zips':'Akron','Ball State Cardinals':'Ball State','Bowling Green Falcons':'Bowling Green',
  'Buffalo Bulls':'Buffalo','Central Michigan Chippewas':'Central Michigan',
  'Eastern Michigan Eagles':'Eastern Michigan','Kent State Golden Flashes':'Kent State',
  'Miami Ohio RedHawks':'Miami (OH)','Northern Illinois Huskies':'Northern Illinois',
  'Ohio Bobcats':'Ohio','Toledo Rockets':'Toledo','Western Michigan Broncos':'Western Michigan',
  'Charlotte 49ers':'Charlotte','East Carolina Pirates':'East Carolina',
  'Memphis Tigers':'Memphis','Navy Midshipmen':'Navy','South Florida Bulls':'South Florida',
  'Temple Owls':'Temple','Tulane Green Wave':'Tulane','Tulsa Golden Hurricane':'Tulsa',
  'Wichita State Shockers':'Wichita State','Duke Blue Devils':'Duke',
  'Florida State Seminoles':'Florida State','Georgia Tech Yellow Jackets':'Georgia Tech',
  'Miami Hurricanes':'Miami','North Carolina State Wolfpack':'NC State',
  'Syracuse Orange':'Syracuse','Virginia Cavaliers':'Virginia','Virginia Tech Hokies':'Virginia Tech',
  'Wake Forest Demon Deacons':'Wake Forest','Boston College Eagles':'Boston College',
  'California Golden Bears':'California','Stanford Cardinal':'Stanford',
  'Army Black Knights':'Army','Liberty Flames':'Liberty',
  'New Mexico State Aggies':'New Mexico State','Sam Houston Bearkats':'Sam Houston',
  'Jacksonville State Gamecocks':'Jacksonville State','Kennesaw State Owls':'Kennesaw State',
  'Western Kentucky Hilltoppers':'Western Kentucky',
};

function mapTeam(name){return TEAM_MAP[name]||name.replace(/ (Buckeyes|Wolverines|Bulldogs|Crimson Tide|Fighting Irish|Longhorns|Nittany Lions|Ducks|Hoosiers|Hurricanes|Tigers|Volunteers|Sooners|Wildcats|Utes|Seminoles|Horned Frogs|Trojans|Badgers|Hawkeyes|Rebels|Aggies|Huskies|Tar Heels|Cardinals|Panthers|Bearcats|Knights|Cougars|Bears|Cyclones|Cowboys|Jayhawks|Mountaineers|Red Raiders|Buffaloes|Sun Devils|Falcons|Broncos|Rams|Wolf Pack|Lobos|Aztecs|Spartans|Rebels|Rainbow Warriors|Cowboys|Eagles|Warhawks|Jaguars|Bobcats|Thundering Herd|Blue Raiders|Owls|Panthers|Bulldogs|Mean Green|Monarchs|Owls|Golden Eagles|Miners|Roadrunners|Hilltoppers|Zips|Cardinals|Falcons|Bulls|Chippewas|Eagles|Golden Flashes|RedHawks|Huskies|Bobcats|Rockets|Broncos|49ers|Pirates|Tigers|Midshipmen|Bulls|Owls|Green Wave|Golden Hurricane|Blue Devils|Yellow Jackets|Wolfpack|Orange|Cavaliers|Hokies|Demon Deacons|Golden Bears|Cardinal|Black Knights|Flames|Bearkats|Gamecocks)$/,'').trim();}

async function loadGames(){
  const week=document.getElementById('lines-week').value;
  document.getElementById('lines-container').innerHTML=`<div class="loading-state"><div class="spinner"></div><p>Loading Week ${week} games + live odds...</p></div>`;
  try{
    // Pull live CFB odds from The Odds API
    const oddsUrl=`${ODDS_BASE}/sports/americanfootball_ncaaf/odds/?apiKey=${ODDS_KEY}&regions=us&markets=spreads&oddsFormat=american&bookmakers=draftkings,fanduel,caesars,betmgm`;
    const oddsRes=await fetch(`https://api.allorigins.win/get?url=${encodeURIComponent(oddsUrl)}`);
    if(!oddsRes.ok)throw new Error(`Odds API: ${oddsRes.status}`);
    const oddsWrapper=await oddsRes.json();
    const oddsData=JSON.parse(oddsWrapper.contents);

    // Also try to get games from CFBD for schedule structure
    let cfbdGames=[];
    try{cfbdGames=await cfbd(`/games?year=2026&week=${week}&division=fbs`);}catch(e){console.log('CFBD unavailable, using Odds API only');}

    // Build game list from odds data
    const oddsGames=oddsData.map(g=>({
      id:g.id,
      home_team:mapTeam(g.home_team),
      away_team:mapTeam(g.away_team),
      start_time:g.commence_time,
      week:parseInt(week),
      bookmakers:g.bookmakers||[],
    }));

    // Merge CFBD games with odds if available, otherwise use odds data directly
    if(cfbdGames.length>0){
      // Match odds to CFBD games by team name
      currentGames=cfbdGames.filter(g=>g.home_team&&g.away_team);
      currentLines=oddsGames; // store odds separately
    }else{
      // Use odds API games directly
      currentGames=oddsGames;
      currentLines=oddsGames;
    }

    renderGames();
  }catch(e){
    document.getElementById('lines-container').innerHTML=`<div class="empty-state" style="color:var(--red)">Failed to load odds: ${e}<br><small>The Odds API may be at its request limit for today.</small></div>`;
  }
}

function getMarketSpread(homeTeam, awayTeam){
  // Find this game in odds data
  const g=currentLines.find(l=>{
    const h=l.home_team||'',a=l.away_team||'';
    return(h===homeTeam&&a===awayTeam)||(h===awayTeam&&a===homeTeam);
  });
  if(!g||!g.bookmakers)return{dk:null,fd:null,market:null,flipped:false};

  const flipped=g.home_team===awayTeam; // odds API has teams reversed
  let dk=null,fd=null,cs=null,mgm=null;

  g.bookmakers.forEach(bk=>{
    const spreads=bk.markets?.find(m=>m.key==='spreads');
    if(!spreads)return;
    const homeOutcome=spreads.outcomes?.find(o=>o.name===g.home_team);
    if(!homeOutcome)return;
    let spread=homeOutcome.point;
    if(flipped)spread=-spread; // flip if teams are reversed

    if(/draftkings/i.test(bk.key))dk=spread;
    else if(/fanduel/i.test(bk.key))fd=spread;
    else if(/caesars/i.test(bk.key))cs=spread;
    else if(/betmgm/i.test(bk.key))mgm=spread;
  });

  const market=dk??fd??cs??mgm??null;
  return{dk,fd,cs,mgm,market};
}

function getBooks(gameId){
  // Legacy function for CFBD lines — now replaced by getMarketSpread
  return{dk:null,fd:null,cons:null,market:null};
}

function renderGames(){
  const ef=document.getElementById('lines-edge').value;
  if(!currentGames.length){document.getElementById('lines-container').innerHTML='<div class="empty-state">No games found.</div>';return;}
  const enriched=currentGames.map(g=>{
    if(!g.home_team||!g.away_team)return null;
    const proj=projSpread(g.home_team,g.away_team);
    const books=getMarketSpread(g.home_team,g.away_team);
    const market=books.market;
    const edge=proj!=null&&market!=null?Math.abs(market-proj):0;
    const wp=winProb(g.home_team,g.away_team);
    return{g,proj,books,market,edge,wp};
  }).filter(Boolean).sort((a,b)=>b.edge-a.edge);
  const rows=enriched.map(({g,proj,books,market,edge,wp})=>{
    if(!g.home_team||!g.away_team)return'';
    if(ef==='play'&&ec!=='play')return'';
    if(ef==='lean'&&ec==='flat')return'';
    const projStr=fmt(proj),marketStr=fmt(market);
    const logged=plays.some(p=>p.game===`${g.away_team} @ ${g.home_team}`);
    const sl=logged?'✓ Logged':ec==='play'?'PLAY':ec==='lean'?'WATCH':'IN LINE';
    const sc=logged?'logged':ec==='play'?'play':ec==='lean'?'watch':'inline';
    let disLbl='—';
    if(proj!=null&&market!=null){const diff=market-proj;if(Math.abs(diff)>=LEAN_THR){const fs=diff>0?g.home_team:g.away_team;disLbl=`${fs} · ${ec==='play'?'clears the gate':'under the gate'}`;}else{disLbl='we agree with the market';}}
    const bp=[];
    if(books.dk!=null)bp.push(`DK ${fmt(books.dk)}`);
    if(books.fd!=null)bp.push(`FD ${fmt(books.fd)}`);
    if(books.cs!=null)bp.push(`CZR ${fmt(books.cs)}`);
    if(books.mgm!=null)bp.push(`MGM ${fmt(books.mgm)}`);
    const gk=(g.away_team+' @ '+g.home_team).replace(/'/g,"\\'"),me=marketStr.replace(/'/g,"\\'");
    return`<tr>
      <td style="min-width:200px">
        <div style="display:flex;align-items:center;margin-bottom:5px"><span style="font-weight:700">${g.away_team}</span><span style="font-size:11px;color:var(--muted);margin-left:6px">${wp.away}%</span></div>
        <div style="display:flex;align-items:center"><span style="font-size:10px;color:var(--muted);margin-right:3px">@</span><span style="font-weight:700">${g.home_team}</span><span style="font-size:11px;color:var(--muted);margin-left:6px">${wp.home}%</span></div>
      </td>
      <td style="min-width:100px"><div class="mono" style="font-size:15px;font-weight:700">${projStr}</div><div style="font-size:10px;color:var(--muted);margin-top:3px">Home line</div></td>
      <td style="min-width:150px"><div class="mono" style="font-size:15px;font-weight:600">${marketStr}</div><div style="font-size:10px;color:var(--muted);margin-top:4px;line-height:1.7">${bp.join(' &nbsp; ')||'—'}</div></td>
      <td style="min-width:180px;text-align:right"><div class="dis-val ${ec}">${edge>0?edge.toFixed(1)+' pts':'—'}</div><div class="dis-lbl">${disLbl}</div></td>
      <td style="text-align:right;min-width:110px">
        <span class="status-badge ${sc}" onclick="openLogger({game:'${gk}',line:'${me}'})">${sl}</span>
        <div style="margin-top:6px"><span style="font-size:11px;color:var(--blue);cursor:pointer;text-decoration:underline" onclick="openTape('${g.away_team.replace(/'/g,"\\'")}','${g.home_team.replace(/'/g,"\\'")}')">Tale of Tape</span></div>
      </td>
    </tr>`;
  }).filter(Boolean).join('');
  document.getElementById('lines-container').innerHTML=rows?`<div class="gt-wrap"><table class="gt">
    <thead><tr><th>Matchup</th><th>Our Line · Home</th><th>Market · Home</th><th class="right">Disagreement</th><th class="right">Status</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`:'<div class="empty-state">No games match your filter.</div>';
}

function openTape(aw,hw){
  const away=metricsData?.teams?.[aw],home=metricsData?.teams?.[hw];
  document.getElementById('tape-title').textContent=`${aw} @ ${hw}`;
  if(!away||!home){document.getElementById('tape-container').innerHTML='<div class="empty-state">No data for one or both teams.</div>';document.getElementById('tape-modal').classList.add('open');return;}
  const awayPR=away.power_rating??0,homePR=home.power_rating??0,baseline=homePR-awayPR,hfaAdj=HFA*0.3,finalPred=-(baseline+hfaAdj),homeWP=Math.round(50+(baseline+hfaAdj)*5);
  const mets=[
    {l:'EPA/Play',av:fmtEPA(away.offense?.epa_play),hv:fmtEPA(home.offense?.epa_play),ar:away.offense?.epa_play_rank,hr:home.offense?.epa_play_rank},
    {l:'EPA/Pass',av:fmtEPA(away.offense?.epa_pass),hv:fmtEPA(home.offense?.epa_pass),ar:away.offense?.epa_pass_rank,hr:home.offense?.epa_pass_rank},
    {l:'EPA/Rush',av:fmtEPA(away.offense?.epa_rush),hv:fmtEPA(home.offense?.epa_rush),ar:away.offense?.epa_rush_rank,hr:home.offense?.epa_rush_rank},
    {l:'Success Rate',av:(away.offense?.success_rate?.toFixed(1)??'—')+'%',hv:(home.offense?.success_rate?.toFixed(1)??'—')+'%',ar:away.offense?.sr_rank,hr:home.offense?.sr_rank},
    {l:'Explosive%',av:(away.offense?.explosive_rate?.toFixed(1)??'—')+'%',hv:(home.offense?.explosive_rate?.toFixed(1)??'—')+'%',ar:away.offense?.expl_rank,hr:home.offense?.expl_rank},
  ];
  const dmets=[
    {l:'EPA/Play',av:fmtEPA(away.defense?.epa_play),hv:fmtEPA(home.defense?.epa_play),ar:away.defense?.epa_play_rank,hr:home.defense?.epa_play_rank},
    {l:'EPA/Pass',av:fmtEPA(away.defense?.epa_pass),hv:fmtEPA(home.defense?.epa_pass),ar:away.defense?.epa_pass_rank,hr:home.defense?.epa_pass_rank},
    {l:'EPA/Rush',av:fmtEPA(away.defense?.epa_rush),hv:fmtEPA(home.defense?.epa_rush),ar:away.defense?.epa_rush_rank,hr:home.defense?.epa_rush_rank},
    {l:'Success Rate',av:(away.defense?.success_rate?.toFixed(1)??'—')+'%',hv:(home.defense?.success_rate?.toFixed(1)??'—')+'%',ar:away.defense?.sr_rank,hr:home.defense?.sr_rank},
    {l:'Havoc Created',av:(away.defense?.havoc_created?.toFixed(1)??'—')+'%',hv:(home.defense?.havoc_created?.toFixed(1)??'—')+'%',ar:away.defense?.havoc_rank,hr:home.defense?.havoc_rank},
  ];
  const tapeRow=m=>`<div style="display:grid;grid-template-columns:50px 1fr 140px 1fr 50px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border);font-size:12px">
    <span style="text-align:right">${m.ar?rankBadge(m.ar,allTeams.length):''}</span>
    <span class="mono" style="text-align:right;font-weight:600">${m.av}</span>
    <span style="text-align:center;color:var(--muted);font-size:11px">${m.l}</span>
    <span class="mono" style="font-weight:600">${m.hv}</span>
    <span>${m.hr?rankBadge(m.hr,allTeams.length):''}</span>
  </div>`;
  document.getElementById('tape-container').innerHTML=`
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
      <div class="card"><div class="card-title">Score Calculation</div>
        <div class="stat-row"><span class="stat-label">Baseline Prediction</span><span class="stat-value">${hw} ${fmt(-baseline)}</span></div>
        <div class="stat-row"><span class="stat-label">Home Field Adjust</span><span class="stat-value" style="color:var(--green)">+${hfaAdj.toFixed(2)}</span></div>
        <div class="stat-row"><span class="stat-label" style="font-weight:700">Final Prediction</span><span class="stat-value" style="font-size:15px">${hw} ${fmt(finalPred)}</span></div>
        <div class="stat-row"><span class="stat-label">Win Probability</span><span class="stat-value">${hw} ${Math.min(99,Math.max(1,homeWP))}%</span></div>
      </div>
      <div class="card"><div class="card-title">Season Context</div>
        <div class="stat-row"><span class="stat-label">Power Rank</span><span class="stat-value">#${away.power_rating_rank??'—'} vs #${home.power_rating_rank??'—'}</span></div>
        <div class="stat-row"><span class="stat-label">Record</span><span class="stat-value">${away.record?.wins??0}-${away.record?.losses??0} vs ${home.record?.wins??0}-${home.record?.losses??0}</span></div>
        <div class="stat-row"><span class="stat-label">Net EPA</span><span class="stat-value">${fmtEPA(away.net?.epa)} vs ${fmtEPA(home.net?.epa)}</span></div>
      </div>
    </div>
    <div style="font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:8px">${aw} Offense vs ${hw} Defense</div>
    <div style="background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:16px">
      <div style="display:grid;grid-template-columns:50px 1fr 140px 1fr 50px;padding:8px 16px;background:var(--bg3);border-bottom:1px solid var(--border)">
        <span style="font-size:10px;font-weight:700;text-align:right;color:var(--muted)">Rank</span>
        <span style="font-size:10px;font-weight:700;text-align:right;color:var(--muted)">${aw}</span>
        <span style="font-size:10px;font-weight:700;text-align:center;color:var(--muted)">Metric</span>
        <span style="font-size:10px;font-weight:700;color:var(--muted)">${hw}</span>
        <span style="font-size:10px;font-weight:700;color:var(--muted)">Rank</span>
      </div>
      ${mets.map(tapeRow).join('')}
    </div>
    <div style="font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:8px">${hw} Offense vs ${aw} Defense</div>
    <div style="background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden">
      <div style="display:grid;grid-template-columns:50px 1fr 140px 1fr 50px;padding:8px 16px;background:var(--bg3);border-bottom:1px solid var(--border)">
        <span style="font-size:10px;font-weight:700;text-align:right;color:var(--muted)">Rank</span>
        <span style="font-size:10px;font-weight:700;text-align:right;color:var(--muted)">${hw}</span>
        <span style="font-size:10px;font-weight:700;text-align:center;color:var(--muted)">Metric</span>
        <span style="font-size:10px;font-weight:700;color:var(--muted)">${aw}</span>
        <span style="font-size:10px;font-weight:700;color:var(--muted)">Rank</span>
      </div>
      ${dmets.map(m=>`<div style="display:grid;grid-template-columns:50px 1fr 140px 1fr 50px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border);font-size:12px">
        <span style="text-align:right">${m.hr?rankBadge(m.hr,allTeams.length):''}</span>
        <span class="mono" style="text-align:right;font-weight:600">${m.hv}</span>
        <span style="text-align:center;color:var(--muted);font-size:11px">${m.l}</span>
        <span class="mono" style="font-weight:600">${m.av}</span>
        <span>${m.ar?rankBadge(m.ar,allTeams.length):''}</span>
      </div>`).join('')}
    </div>`;
  document.getElementById('tape-modal').classList.add('open');
}
function closeTape(){document.getElementById('tape-modal').classList.remove('open');}

async function openDossier(school){
  switchTab('dossier');
  document.getElementById('dossier-container').innerHTML=`<div class="loading-state"><div class="spinner"></div><p>Loading ${school}...</p></div>`;
  const t=metricsData?.teams?.[school];
  if(!t){document.getElementById('dossier-container').innerHTML='<div class="empty-state">No data found.</div>';return;}
  try{
    const schedule=await cfbd(`/games?year=2026&team=${encodeURIComponent(school)}`);
    const total=allTeams.length,o=t.offense||{},d=t.defense||{};
    const schedRows=schedule.map(g=>{
      const isHome=g.home_team===school,opp=isHome?g.away_team:g.home_team;
      const proj=isHome?projSpread(school,opp):projSpread(opp,school);
      const projAdj=isHome?proj:(proj!=null?-proj:null);
      const result=g.home_points!=null?(isHome?(g.home_points>g.away_points?`W ${g.home_points}-${g.away_points}`:`L ${g.home_points}-${g.away_points}`):(g.away_points>g.home_points?`W ${g.away_points}-${g.home_points}`:`L ${g.away_points}-${g.home_points}`)):'—';
      const rc=result.startsWith('W')?'mv-pos':result.startsWith('L')?'mv-neg':'mv-neu';
      const date=g.start_date?new Date(g.start_date).toLocaleDateString('en-US',{month:'short',day:'numeric'}):'—';
      return`<tr><td class="mono" style="color:var(--muted);font-size:11px">Wk ${g.week}</td><td><span style="font-size:10px;color:var(--muted);margin-right:4px">${isHome?'vs':'@'}</span>${opp}</td><td class="mono" style="color:var(--muted)">${projAdj!=null?fmt(projAdj):'—'}</td><td class="mono ${rc}">${result}</td><td class="mono" style="color:var(--muted);font-size:11px">${date}</td></tr>`;
    }).join('');
    document.getElementById('dossier-container').innerHTML=`
      <div style="margin-bottom:20px"><div style="font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:2px">${school}</div>
      <div style="font-size:13px;color:var(--muted)">${t.conference||''} · ${t.record?.wins??0}-${t.record?.losses??0} · Power Rank #${t.power_rating_rank??'—'}</div></div>
      <div class="dossier-grid">
        <div style="display:flex;flex-direction:column;gap:16px">
          <div class="card"><div class="card-title">Power Rating</div>
            <div class="big-num">${t.power_rating?.toFixed(2)??'—'}</div>
            <div class="big-num-sub">Rank #${t.power_rating_rank??'—'} of ${total}</div>
          </div>
          <div class="card"><div class="card-title">Offense</div>
            <div class="stat-row"><span class="stat-label">EPA/Play</span><span class="stat-value ${mc(o.epa_play)}">${fmtEPA(o.epa_play)} ${rankBadge(o.epa_play_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">EPA/Pass</span><span class="stat-value ${mc(o.epa_pass)}">${fmtEPA(o.epa_pass)} ${rankBadge(o.epa_pass_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">EPA/Rush</span><span class="stat-value ${mc(o.epa_rush)}">${fmtEPA(o.epa_rush)} ${rankBadge(o.epa_rush_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Success Rate</span><span class="stat-value">${o.success_rate?.toFixed(1)??'—'}% ${rankBadge(o.sr_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Explosive%</span><span class="stat-value">${o.explosive_rate?.toFixed(1)??'—'}% ${rankBadge(o.expl_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Havoc Allowed</span><span class="stat-value ${mc(o.havoc_allowed,false)}">${o.havoc_allowed?.toFixed(1)??'—'}%</span></div>
          </div>
          <div class="card"><div class="card-title">Defense</div>
            <div class="stat-row"><span class="stat-label">EPA/Play</span><span class="stat-value ${mc(d.epa_play,false)}">${fmtEPA(d.epa_play)} ${rankBadge(d.epa_play_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">EPA/Pass</span><span class="stat-value ${mc(d.epa_pass,false)}">${fmtEPA(d.epa_pass)} ${rankBadge(d.epa_pass_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">EPA/Rush</span><span class="stat-value ${mc(d.epa_rush,false)}">${fmtEPA(d.epa_rush)} ${rankBadge(d.epa_rush_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Success Rate</span><span class="stat-value">${d.success_rate?.toFixed(1)??'—'}% ${rankBadge(d.sr_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Explosive%</span><span class="stat-value">${d.explosive_rate?.toFixed(1)??'—'}% ${rankBadge(d.expl_rank,total)}</span></div>
            <div class="stat-row"><span class="stat-label">Havoc Created</span><span class="stat-value ${mc(d.havoc_created)}">${d.havoc_created?.toFixed(1)??'—'}% ${rankBadge(d.havoc_rank,total)}</span></div>
          </div>
        </div>
        <div class="card"><div class="card-title">2026 Schedule + Model Projections</div>
          ${schedule.length?`<table style="width:100%;border-collapse:collapse;font-size:13px">
            <thead><tr>${['Wk','Opponent','Proj Spread','Result','Date'].map(h=>`<th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">${h}</th>`).join('')}</tr></thead>
            <tbody>${schedRows}</tbody></table>`:'<div class="empty-state" style="padding:30px">Schedule not yet available.</div>'}
        </div>
      </div>`;
  }catch(e){document.getElementById('dossier-container').innerHTML=`<div class="empty-state" style="color:var(--red)">Failed: ${e}</div>`;}
}

function updateLoggerFields(){
  const type=document.getElementById('log-type').value;
  document.getElementById('fields-spread').style.display=type==='spread'?'block':'none';
  document.getElementById('fields-total').style.display=(type==='total'||type==='team_total')?'block':'none';
  document.getElementById('fields-ml').style.display=type==='ml'?'block':'none';
  document.getElementById('fields-prop').style.display=type==='prop'?'block':'none';
}

function openLogger(prefill){
  editingPlayId=null;
  ['log-game','log-side','log-line','log-close','log-book','log-notes',
   'log-total-num','log-close-total','log-ml-odds','log-close-ml','log-prop-line'].forEach(id=>{
    const el=document.getElementById(id);if(el)el.value='';
  });
  document.getElementById('log-game').value=prefill?.game??'';
  document.getElementById('log-line').value=prefill?.line??'';
  document.getElementById('log-units').value='1';
  document.getElementById('log-result').value='pending';
  document.getElementById('log-type').value='spread';
  updateLoggerFields();
  document.getElementById('log-modal').classList.add('open');
}
function closeLogger(){document.getElementById('log-modal').classList.remove('open');}

function savePlay(){
  const betType=document.getElementById('log-type').value;
  const units=parseFloat(document.getElementById('log-units').value)||1;
  const result=document.getElementById('log-result').value;
  let line=0,closingLine=null,clv=null,winUnits=units*0.909,lineDisplay='',closeDisplay='';

  if(betType==='spread'){
    line=parseFloat(document.getElementById('log-line').value)||0;
    const cv=document.getElementById('log-close').value;
    closingLine=cv!==''?parseFloat(cv):null;
    clv=closingLine!==null?(line-closingLine):null;
    lineDisplay=(line>=0?'+':'')+line;
    closeDisplay=closingLine!=null?(closingLine>=0?'+':'')+closingLine:'';

  }else if(betType==='total'||betType==='team_total'){
    const num=parseFloat(document.getElementById('log-total-num').value)||0;
    const ou=document.getElementById('log-ou').value;
    line=num;
    lineDisplay=`${ou==='over'?'O':'U'} ${num}`;
    const closeNum=document.getElementById('log-close-total').value;
    const closeOu=document.getElementById('log-close-ou').value;
    if(closeNum!==''){
      closingLine=parseFloat(closeNum);
      closeDisplay=`${closeOu==='over'?'O':'U'} ${closingLine}`;
      // CLV for totals: if you bet Over and line moves up, that's negative CLV
      clv=ou==='over'?(line-closingLine):(closingLine-line);
    }

  }else if(betType==='ml'){
    line=parseFloat(document.getElementById('log-ml-odds').value)||0;
    lineDisplay=(line>=0?'+':'')+line;
    const cv=document.getElementById('log-close-ml').value;
    closingLine=cv!==''?parseFloat(cv):null;
    closeDisplay=closingLine!=null?(closingLine>=0?'+':'')+closingLine:'';
    // CLV for ML: getting a better number means closer to 0 for favorites, higher for dogs
    if(closingLine!==null){
      // Convert both to implied prob and compare
      const toProb=o=>o<0?Math.abs(o)/(Math.abs(o)+100):100/(o+100);
      clv=toProb(closingLine)-toProb(line); // positive = you got better of it
      clv=parseFloat((clv*100).toFixed(2));
    }
    // P/L calculation from actual ML odds
    if(line<0) winUnits=units*(100/Math.abs(line));
    else winUnits=units*(line/100);

  }else if(betType==='prop'){
    line=parseFloat(document.getElementById('log-prop-line').value)||0;
    const dir=document.getElementById('log-prop-dir').value;
    lineDisplay=`${dir} ${line}`;
  }

  const play={
    id:editingPlayId??Date.now(),
    game:document.getElementById('log-game').value,
    side:document.getElementById('log-side').value,
    betType,line,lineDisplay:lineDisplay||(line>=0?'+':'')+line,
    closingLine,closeDisplay,clv,units,winUnits,
    book:document.getElementById('log-book').value,
    result,
    notes:document.getElementById('log-notes').value,
    ts:Date.now()
  };
  if(editingPlayId){const idx=plays.findIndex(p=>p.id===editingPlayId);if(idx!==-1)plays[idx]=play;}else{plays.unshift(play);}
  localStorage.setItem('ht_plays',JSON.stringify(plays));
  closeLogger();renderPlays();
}
function deletePlay(id){plays=plays.filter(p=>p.id!==id);localStorage.setItem('ht_plays',JSON.stringify(plays));renderPlays();}
function editPlay(id){
  const p=plays.find(p=>p.id===id);if(!p)return;
  editingPlayId=id;
  document.getElementById('log-game').value=p.game;
  document.getElementById('log-side').value=p.side;
  document.getElementById('log-type').value=p.betType||'spread';
  document.getElementById('log-units').value=p.units;
  document.getElementById('log-book').value=p.book;
  document.getElementById('log-result').value=p.result;
  document.getElementById('log-notes').value=p.notes;
  updateLoggerFields();

  if(p.betType==='ml'){
    document.getElementById('log-ml-odds').value=p.line||'';
    document.getElementById('log-close-ml').value=p.closingLine??'';
  }else if(p.betType==='total'||p.betType==='team_total'){
    document.getElementById('log-total-num').value=p.line||'';
    document.getElementById('log-close-total').value=p.closingLine??'';
  }else if(p.betType==='prop'){
    document.getElementById('log-prop-line').value=p.line||'';
  }else{
    document.getElementById('log-line').value=p.line||'';
    document.getElementById('log-close').value=p.closingLine??'';
  }
  document.getElementById('log-modal').classList.add('open');
}

function renderPlays(){
  const wins=plays.filter(p=>p.result==='W'),losses=plays.filter(p=>p.result==='L'),pending=plays.filter(p=>p.result==='pending');
  const unitsWon=wins.reduce((s,p)=>s+(p.winUnits??p.units*0.909),0);
  const unitsLost=losses.reduce((s,p)=>s+p.units,0);
  const netUnits=unitsWon-unitsLost;
  const cp=plays.filter(p=>p.clv!=null),avgCLV=cp.length?cp.reduce((s,p)=>s+p.clv,0)/cp.length:null;
  const clvPct=cp.length?Math.round(cp.filter(p=>p.clv>0).length/cp.length*100):null;
  const cc=avgCLV===null?'var(--muted)':avgCLV>=1?'#16a34a':avgCLV>=0?'#d97706':'#dc2626';
  document.getElementById('pl-record').innerHTML=`
    <div class="pl-stat"><div class="pl-stat-val g">${wins.length}-${losses.length}</div><div class="pl-stat-label">Record</div></div>
    <div class="pl-stat"><div class="pl-stat-val ${netUnits>=0?'g':'r'}">${netUnits>=0?'+':''}${netUnits.toFixed(2)}u</div><div class="pl-stat-label">Net Units</div></div>
    <div class="pl-stat"><div class="pl-stat-val">${plays.length}</div><div class="pl-stat-label">Total Plays</div></div>
    <div class="pl-stat"><div class="pl-stat-val" style="color:var(--muted)">${pending.length}</div><div class="pl-stat-label">Pending</div></div>
    <div class="pl-stat" style="border-left:2px solid var(--green);padding-left:16px"><div class="pl-stat-val" style="color:${cc}">${avgCLV===null?'—':(avgCLV>=0?'+':'')+avgCLV.toFixed(2)}</div><div class="pl-stat-label">Avg CLV</div></div>
    <div class="pl-stat"><div class="pl-stat-val" style="color:${clvPct===null?'var(--muted)':clvPct>=55?'#16a34a':'#d97706'}">${clvPct===null?'—':clvPct+'%'}</div><div class="pl-stat-label">+CLV Rate</div></div>`;
  if(!plays.length){document.getElementById('plays-container').innerHTML='<div class="empty-state"><div style="font-size:32px;margin-bottom:12px">🎯</div><p style="margin-bottom:8px;color:var(--text)">No plays logged yet.</p><p>Click + Add Play or log from Lines & Edges.</p></div>';return;}

  const typeLabel={spread:'Spread',total:'Total',team_total:'Team Total',ml:'ML',prop:'Prop'};

  const rows=plays.map(p=>{
    const rc=p.result==='W'?'W':p.result==='L'?'L':p.result==='P'?'P':'pending';
    const wu=p.winUnits??p.units*0.909;
    const pu=p.result==='W'?`+${wu.toFixed(2)}u`:p.result==='L'?`-${p.units}u`:p.result==='P'?'0u':'—';
    const puC=p.result==='W'?'mv-pos':p.result==='L'?'mv-neg':'mv-neu';
    const rowLineDisplay=p.lineDisplay||(p.line>=0?'+':'')+p.line;
    const clvLabel=p.betType==='ml'?'odds pts':'pts';
    const clvD=p.clv!=null?`<span class="${p.clv>=0?'mv-pos':'mv-neg'}">${p.clv>=0?'+':''}${p.clv.toFixed(1)}${p.betType==='ml'?'%':''}</span>`:'<span style="font-size:10px;color:var(--muted)">Add close</span>';
    const lineDisplay=p.betType==='ml'?(p.line>=0?'+':'')+p.line:(p.line>=0?'+':'')+p.line;
    const tl=typeLabel[p.betType]||'Spread';
    return`<tr>
      <td style="font-weight:600;max-width:160px;overflow:hidden;text-overflow:ellipsis">${p.game||'—'}</td>
      <td><span style="font-size:10px;padding:2px 6px;border-radius:3px;background:var(--bg3);border:1px solid var(--border);color:var(--muted)">${tl}</span></td>
      <td class="mono">${p.side||'—'}</td>
      <td class="mono">${rowLineDisplay}</td>
      <td class="mono">${clvD}</td>
      <td class="mono">${p.units}u</td>
      <td>${p.book||'—'}</td>
      <td><span class="result-badge ${rc}">${p.result==='pending'?'Pending':p.result}</span></td>
      <td class="mono ${puC}">${pu}</td>
      <td style="white-space:nowrap">
        <button class="btn ghost" style="padding:4px 10px;font-size:11px" onclick="editPlay(${p.id})">Edit</button>
        <button class="btn danger" style="padding:4px 10px;font-size:11px;margin-left:4px" onclick="deletePlay(${p.id})">✕</button>
      </td>
    </tr>`;
  }).join('');

  document.getElementById('plays-container').innerHTML=`
    <div style="font-size:11px;color:var(--muted);margin-bottom:10px">CLV = Closing Line Value. Positive = beat the close. Enter closing line by editing after kickoff. ML P/L calculated from actual odds.</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Game</th><th>Type</th><th>Side</th><th>Line</th><th style="color:var(--green)">CLV</th><th>Units</th><th>Book</th><th>Result</th><th>P/L</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`;
}

function simWP(a,b,homeA=false){const pa=getPR(a)??0,pb=getPR(b)??0,diff=(pa-pb)+(homeA?HFA*0.3:0);return 1/(1+Math.exp(-diff*0.15));}

async function loadPlayoff(){
  document.getElementById('playoff-container').innerHTML='<div class="loading-state"><div class="spinner"></div><p>Running 5,000 simulations...</p></div>';
  try{
    const records=await cfbd('/records?year=2026').catch(()=>[]);
    const rl={};records.forEach(r=>{rl[r.team]=r;});
    const field=allTeams.map(t=>{const rec=rl[t.team],wins=rec?.total?.wins??0,losses=rec?.total?.losses??0;return{...t,ePR:(t.power_rating??0)+(wins-losses)*0.15,wins,losses};}).sort((a,b)=>b.ePR-a.ePR).slice(0,12).map((t,i)=>({...t,seed:i+1}));
    const N=5000,counts={};field.forEach(t=>{counts[t.team]={r1:0,qf:0,sf:0,champ:0,title:0};});
    for(let i=0;i<N;i++){
      const byes=field.slice(0,4);
      const r1w=[[4,11],[5,10],[6,9],[7,8]].map(([hi,lo])=>{const a=field[hi],b=field[lo];counts[a.team].r1++;counts[b.team].r1++;return Math.random()<simWP(a.team,b.team)?a:b;});
      r1w.sort((a,b)=>a.seed-b.seed);
      const qfw=[[byes[0],r1w[3]],[byes[1],r1w[2]],[byes[2],r1w[1]],[byes[3],r1w[0]]].map(([a,b])=>{counts[a.team].qf++;counts[b.team].qf++;return Math.random()<simWP(a.team,b.team,true)?a:b;});
      const sfw=[[qfw[0],qfw[3]],[qfw[1],qfw[2]]].map(([a,b])=>{counts[a.team].sf++;counts[b.team].sf++;return Math.random()<simWP(a.team,b.team)?a:b;});
      counts[sfw[0].team].champ++;counts[sfw[1].team].champ++;
      const ch=Math.random()<simWP(sfw[0].team,sfw[1].team)?sfw[0]:sfw[1];counts[ch.team].title++;
    }
    playoffData={field,counts,N};renderPlayoff();
    document.getElementById('playoff-updated').textContent=`Updated ${new Date().toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'})}`;
  }catch(e){document.getElementById('playoff-container').innerHTML=`<div class="empty-state" style="color:var(--red)">Failed: ${e}</div>`;}
}

function renderPlayoff(){
  if(!playoffData)return;
  const{field,counts,N}=playoffData;
  const tf=[...field].sort((a,b)=>(counts[b.team]?.title||0)-(counts[a.team]?.title||0))[0];
  const oddsRows=field.map(t=>{
    const s=counts[t.team]||{},tp=((s.title||0)/N*100).toFixed(1),tn=parseFloat(tp),pc=tn>=15?'high':tn>=5?'mid':'low',isBye=t.seed<=4;
    return`<tr><td><span class="seed-num ${isBye?'bye':''}">${t.seed}</span></td><td style="font-weight:600">${t.team} <span style="font-size:10px;color:var(--muted)">${t.conference||''}</span></td><td class="mono" style="color:var(--muted)">${t.wins}-${t.losses}</td><td class="mono" style="color:var(--muted)">${t.power_rating?.toFixed(2)??'—'}</td>
    <td><div class="prob-bar-wrap"><div class="prob-bar"><div class="prob-bar-fill" style="width:${Math.min(100,tn*3)}%"></div></div><span class="prob-pct ${pc}">${tp}%</span></div></td>
    <td style="text-align:right">${isBye?'<span style="color:var(--green);font-size:11px;font-weight:700">BYE</span>':'—'}</td></tr>`;
  }).join('');
  function muCard(label,s1,s2,home=false){
    const t1=field.find(t=>t.seed===s1),t2=field.find(t=>t.seed===s2);
    if(!t1||!t2)return'';
    const wp1=Math.round(simWP(t1.team,t2.team,home)*100),wp2=100-wp1;
    const proj=projSpread(t1.team,t2.team),ps=proj!=null?(proj<0?`${t1.team} ${fmt(proj)}`:`${t2.team} ${fmt(-proj)}`):'—';
    return`<div class="mu-card"><div class="mu-card-hdr"><span>${label}</span><span style="color:var(--green)">${ps}</span></div>
      <div class="mu-team-row ${wp1>=50?'fav':''}"><div class="mt-left"><span class="mt-seed">${s1}</span><span class="mt-name">${t1.team}</span><span class="mt-rec">${t1.wins}-${t1.losses}</span></div><span class="mt-wp ${wp1>=50?'fav':''}">${wp1}%</span></div>
      <div class="mu-team-row ${wp2>=50?'fav':''}"><div class="mt-left"><span class="mt-seed">${s2}</span><span class="mt-name">${t2.team}</span><span class="mt-rec">${t2.wins}-${t2.losses}</span></div><span class="mt-wp ${wp2>=50?'fav':''}">${wp2}%</span></div></div>`;
  }
  const[c1,c2]=[...field].sort((a,b)=>(counts[b.team]?.champ||0)-(counts[a.team]?.champ||0)).slice(0,2);
  document.getElementById('playoff-container').innerHTML=`
    <div class="champ-card"><div class="champ-label">🏆 Projected National Champion</div><div class="champ-team">${tf.team}</div>
    <div class="champ-prob">${((counts[tf.team]?.title||0)/N*100).toFixed(1)}% title probability · ${tf.wins}-${tf.losses} · Rating ${tf.power_rating?.toFixed(2)}</div></div>
    <div class="playoff-layout">
      <div class="po-table"><table><thead><tr><th>#</th><th>Team</th><th>Record</th><th>Rating</th><th>Title %</th><th>Status</th></tr></thead><tbody>${oddsRows}</tbody></table></div>
      <div class="card"><div class="card-title">How to read this</div><div style="font-size:12px;color:var(--muted);line-height:1.9">
        <div>• <strong style="color:var(--green)">Title %</strong> — probability across 5,000 simulated brackets</div>
        <div>• <strong style="color:var(--green)">BYE</strong> — seeds 1–4 skip first round</div>
        <div>• Projected spreads shown for every matchup</div>
        <div>• Updates every Tuesday automatically via GitHub Actions</div>
      </div></div>
    </div>
    <div class="round-tabs">
      <div class="round-tab active" onclick="showRound('r1',this)">First Round</div>
      <div class="round-tab" onclick="showRound('qf',this)">Quarterfinals</div>
      <div class="round-tab" onclick="showRound('sf',this)">Semifinals</div>
      <div class="round-tab" onclick="showRound('champ',this)">Championship</div>
    </div>
    <div id="bracket-r1" class="bracket-section"><div class="bracket-lbl">First Round — Campus Sites (Seeds 5–12)</div>
      <div class="bracket-grid" style="grid-template-columns:1fr 1fr">${muCard('5 vs 12',5,12,true)}${muCard('8 vs 9',8,9,true)}${muCard('6 vs 11',6,11,true)}${muCard('7 vs 10',7,10,true)}</div></div>
    <div id="bracket-qf" class="bracket-section" style="display:none"><div class="bracket-lbl">Quarterfinals — Campus Sites (Seeds 1–4 host)</div>
      <div class="bracket-grid" style="grid-template-columns:1fr 1fr">${muCard('1 vs Lowest R1',1,12,true)}${muCard('4 vs Highest R1',4,9,true)}${muCard('2 vs R1',2,11,true)}${muCard('3 vs R1',3,10,true)}</div></div>
    <div id="bracket-sf" class="bracket-section" style="display:none"><div class="bracket-lbl">Projected Semifinal — Neutral</div>
      <div class="bracket-grid" style="grid-template-columns:1fr 1fr">${c1&&c2?muCard(`#${c1.seed} vs #${c2.seed}`,c1.seed,c2.seed):''}
      <div class="card" style="display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);font-size:13px">Other semifinal bracket-dependent</div></div></div>
    <div id="bracket-champ" class="bracket-section" style="display:none"><div class="bracket-lbl">Projected Championship — Neutral</div>
      <div class="bracket-grid" style="grid-template-columns:1fr">${c1&&c2?muCard(`#${c1.seed} vs #${c2.seed} · Most Likely`,c1.seed,c2.seed):''}</div></div>`;
}

function showRound(r,el){
  document.querySelectorAll('.round-tab').forEach(t=>t.classList.remove('active'));el.classList.add('active');
  ['r1','qf','sf','champ'].forEach(id=>{const e=document.getElementById('bracket-'+id);if(e)e.style.display=id===r?'block':'none';});
}

document.getElementById('log-modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeLogger();});
document.getElementById('tape-modal').addEventListener('click',e=>{if(e.target===e.currentTarget)closeTape();});
document.getElementById('log-type').addEventListener('change',updateLoggerFields);
init();
