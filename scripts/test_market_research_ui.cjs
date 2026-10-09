const fs = require('fs');
const assert = require('assert');

const market = fs.readFileSync('market-research.js', 'utf8');
const football = fs.readFileSync('app.js', 'utf8');
const basketball = fs.readFileSync('cbb-site.js', 'utf8');
const styles = fs.readFileSync('cbb-site.css', 'utf8');

assert(market.includes("const PENDING_PLAY_KEY = 'thi:pending-play:v1'"));
assert(market.includes('Start tracking play'));
assert(market.includes('Sportsbook'));
assert(market.includes('American odds'));
assert(market.includes('Units risked'));
assert(!market.includes('Current Odds Screen'));
assert(!market.includes('research-odds'));
assert(football.includes('Track a Play'));
assert(basketball.includes('Track a Play'));
assert(football.includes('sportsbookGrid(game, bookLines)'));
assert(basketball.includes('cbbOddsGrid(game, marketBooks)'));
assert(football.includes('thi-book-badge'));
assert(basketball.includes('thi-book-badge'));
assert(football.includes('novig: ["NVG", "Novig"]'));
assert(football.includes('prophetx: ["PX", "ProphetX"]'));
assert(football.includes('espnbet: ["SCR", "theScore Bet"]'));
assert(football.includes('["lowvig", "mybookieag"]'));
assert(basketball.includes('["lowvig","mybookieag"]'));
assert(styles.includes('.thi-book-draftkings{background:#087b45;color:#fff}'));
assert(styles.includes('.thi-book-espnbet,.thi-book-thescorebet{background:#101820;color:#39e75f}'));
assert(!football.includes('>Save game</button>'));
assert(!basketball.includes('>Save game</button>'));

console.log('market research play-slip UI contract passed');
