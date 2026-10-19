const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const cfb = read("thi-visual-explorer.js");
const cbb = read("cbb-site.js");
const html = read("index.html");

assert.match(cfb, /data-explorer-power-rank=/, "CFB points must expose the THI rank");
assert.match(cfb, /thi-chart-tooltip/, "CFB charts must render the hover tooltip");
assert.match(cfb, /pointerover/, "CFB charts must respond to pointer hover");
assert.match(cfb, /focusin/, "CFB charts must support keyboard focus");
assert.match(cfb, /is-below/, "CFB tooltips must avoid clipping at the chart top");

assert.match(cbb, /ratingChart: "efficiency"/, "CBB chart selection must have a default");
for (const option of ["efficiency", "roster", "continuity"]) {
  assert.match(cbb, new RegExp(`${option}: \\{`), `CBB must provide the ${option} chart`);
}
assert.match(cbb, /cbb-chart-tooltip/, "CBB charts must render the hover tooltip");
assert.match(cbb, /data-chart-rank=/, "CBB points must expose the THI rank");
assert.match(cbb, /focusin/, "CBB charts must support keyboard focus");
assert.match(cbb, /Click to open the team dossier/, "CBB points must retain dossier navigation");

assert.match(html, /thi-visual-explorer\.js\?v=2026-chart-tooltips-v02/, "CFB cache key must publish the new interaction");
assert.match(html, /cbb-site\.js\?v=2027-rating-charts-v01/, "CBB cache key must publish the new charts");

console.log("visual research UI contract passed");
