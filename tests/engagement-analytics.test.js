const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class MemoryStorage {
  constructor() { this.values = new Map(); }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null; }
  setItem(key, value) { this.values.set(key, String(value)); }
}

class MockElement {}

const location = new URL("https://thehammerindex.com/?utm_source=x&utm_medium=social&utm_campaign=week_10&private=do-not-send");
const documentListeners = new Map();
const document = {
  readyState: "complete",
  referrer: "https://t.co/example?private=hidden",
  body: { classList: { contains: () => false } },
  head: { appendChild: () => {} },
  createElement: () => ({}),
  querySelector: selector => selector === ".view.active" ? { id: "view-projections" } : null,
  addEventListener: (name, handler) => documentListeners.set(name, handler)
};
const window = {
  location,
  THI_ANALYTICS_CONFIG: {
    enabled: true,
    posthogKey: "phc_test_public_key",
    posthogHost: "https://us.i.posthog.com"
  },
  setTimeout: callback => { callback(); return 1; }
};
window.window = window;

const context = vm.createContext({
  window,
  document,
  localStorage: new MemoryStorage(),
  sessionStorage: new MemoryStorage(),
  URL,
  URLSearchParams,
  HTMLElement: MockElement,
  console
});

const source = fs.readFileSync(path.join(__dirname, "..", "engagement-analytics.js"), "utf8");
vm.runInContext(source, context, { filename: "engagement-analytics.js" });

window.THIAnalytics.viewMatchup({
  sport: "CFB",
  matchup_id: "401864524",
  away_team: "Notre Dame",
  home_team: "Miami"
});

const captures = window.posthog.filter(item => Array.isArray(item) && item[0] === "capture");
const names = captures.map(item => item[1]);
assert.ok(names.includes("session_start"));
assert.ok(names.includes("section_view"));
assert.ok(names.includes("view_matchup"));
assert.ok(names.includes("view_projection"));
assert.equal(names.filter(name => name === "$pageview").length, 2);

const matchup = captures.find(item => item[1] === "view_matchup")[2];
assert.equal(matchup.matchup_id, "401864524");
assert.equal(matchup.referral_source, "x");
assert.equal(matchup.utm_campaign, "week_10");
assert.equal(matchup.route, "/cfb/matchup/401864524");
assert.equal(Object.values(matchup).includes("do-not-send"), false);
assert.equal(Object.values(matchup).some(value => String(value).includes("private=hidden")), false);

const search = new MockElement();
search.id = "team-search";
search.value = "private search text";
search.matches = selector => selector === 'input[type="search"]';
search.closest = () => null;
documentListeners.get("change")({ target: search });
const searchCapture = window.posthog.filter(item => Array.isArray(item) && item[0] === "capture" && item[1] === "search_used").at(-1)[2];
assert.equal(searchCapture.search_category, "team_search");
assert.equal(Object.values(searchCapture).includes("private search text"), false);

const substackAnchor = { href: "https://cadloxx.substack.com/subscribe?email=private@example.com" };
const clickTarget = {
  closest: selector => selector === "a[href]" ? substackAnchor : null
};
documentListeners.get("click")({ target: clickTarget });
const subscribeCapture = window.posthog.filter(item => Array.isArray(item) && item[0] === "capture" && item[1] === "click_subscribe").at(-1)[2];
assert.equal(subscribeCapture.destination_host, "cadloxx.substack.com");
assert.equal(subscribeCapture.destination_path, "/subscribe");
assert.equal(Object.values(subscribeCapture).some(value => String(value).includes("private@example.com")), false);

window.THIAnalytics.navigate({ sport: "CFB", section: "projections" });
const afterDuplicate = window.posthog.filter(item => Array.isArray(item) && item[0] === "capture");
assert.equal(afterDuplicate.filter(item => item[1] === "$pageview").length, 3);
window.THIAnalytics.navigate({ sport: "CFB", section: "projections" });
const afterSecondDuplicate = window.posthog.filter(item => Array.isArray(item) && item[0] === "capture");
assert.equal(afterSecondDuplicate.filter(item => item[1] === "$pageview").length, 3);

console.log("engagement analytics tests passed");
