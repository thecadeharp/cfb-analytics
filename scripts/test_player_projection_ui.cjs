const fs = require("fs");
const assert = require("assert");

const ui = fs.readFileSync("player-intelligence.js", "utf8");
const cbb = fs.readFileSync("cbb-site.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
const payload = JSON.parse(fs.readFileSync("data/player_projections.json", "utf8"));

assert(ui.includes('data-player-section="ratings"'), "CFB ratings subtab is missing");
assert(ui.includes('data-player-section="projections"'), "CFB projections subtab is missing");
assert(ui.includes("Projected means are matchup-aware estimates"), "Research disclosure is missing");
assert(ui.includes("pass_yards") && ui.includes("interceptions") && ui.includes("rush_attempts") && ui.includes("receiving_yards"), "Position projection metrics are incomplete");
assert(ui.includes("data-thi-player-id"), "Projection cards must retain player-detail access");
assert(cbb.includes('data-cbb-player-section="projections"'), "CBB future projection slot is missing");
assert(cbb.includes("CBB player projections follow roster verification"), "CBB verification gate is missing");
assert(html.includes("player-intelligence.js?v=2026-player-projections-v01"), "CFB asset cache key is stale");
assert(html.includes("cbb-site.js?v=2027-player-projections-v01"), "CBB asset cache key is stale");
assert.strictEqual(payload.meta.status, "research_only");
assert.strictEqual(payload.meta.model_usage, "display_only_not_used_by_model_a");
assert(payload.projections.length >= 500, "Projection board coverage is unexpectedly low");
assert(payload.projections.every(row => ["QB", "RB", "WR", "TE"].includes(row.position_group)));
assert(payload.projections.every(row => row.matchup && row.projection && row.confidence));

console.log("player projection UI contract passed");
