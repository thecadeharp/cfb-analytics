const assert = require("node:assert/strict");
const impact = require("../availability-impact.js");

const roster = {
  teams: {
    Example: {
      players: [
        {athlete_id:"1", name:"Starting Quarterback", position:"QB", jersey:"7", usage:{pass_attempts:240,rush_attempts:55}},
        {athlete_id:"2", name:"Reserve Quarterback", position:"QB", jersey:"12", usage:{pass_attempts:12,rush_attempts:4}},
        {athlete_id:"3", name:"Lead Receiver", position:"WR", jersey:"1", usage:{targets:82,receptions:51}},
        {athlete_id:"4", name:"Reserve Receiver", position:"WR", jersey:"18", usage:{targets:8,receptions:4}},
      ]
    }
  }
};

const intelligence = {
  players: {
    "1": {position_group:"QB", rating:96},
    "2": {position_group:"QB", rating:35},
    "3": {position_group:"WR", rating:88},
    "4": {position_group:"WR", rating:30},
  }
};

const notes = [
  {player:"Starting Quarterback", position:"QB", status:"Out"},
  {player:"Lead Receiver", position:"WR", status:"Questionable"},
  {player:"Reserve Receiver", position:"WR", status:"Available"},
  {player:"Unknown Lineman", position:"OL", status:"Doubtful"},
];

const rated = impact.rateTeam(notes, "Example", roster, intelligence);

assert.equal(rated.methodVersion, "thi-availability-impact-v1");
assert.equal(rated.noteCount, 4);
assert.equal(rated.matchedPlayers, 3);
assert.equal(rated.players[2].score, 0, "available players must add no impact");
assert.ok(rated.players[0].score > rated.players[1].score, "out starting QB must rate above questionable WR");
assert.ok(rated.players[0].absenceValuePoints > rated.players[1].absenceValuePoints, "starting QB point sensitivity must exceed WR sensitivity");
assert.equal(rated.players[0].absenceValuePoints, 6, "only an elite QB with a major replacement gap may reach six points");
assert.equal(rated.players[0].sixPointEligible, true);
assert.ok(rated.players[1].absenceValuePoints <= 1.3, "wide receiver sensitivity must respect its conservative cap");
assert.equal(rated.players[2].currentExposurePoints, 0, "available players add no current report exposure");
assert.ok(rated.reportExposurePoints > 0 && rated.reportExposurePoints <= 8, "team report exposure must respect its ceiling");
assert.equal(rated.players[3].confidence, "low", "unmatched player must disclose low evidence confidence");
assert.ok(rated.byPosition.QB > rated.byPosition.WR);
assert.ok(rated.total > 0 && rated.total <= 100);
assert.equal(impact.statusSeverity("Probable"), 0.14);
assert.equal(impact.positionGroup("K/P"), "ST");
assert.equal(impact.normalizeName("D.J. O'Brien Jr."), "d j o brien jr");

const solidStarterRoster = {teams:{MidTier:{players:[
  {athlete_id:"10",name:"Solid Starter",position:"QB",usage:{pass_attempts:220,rush_attempts:35}},
  {athlete_id:"11",name:"Experienced Backup",position:"QB",usage:{pass_attempts:45,rush_attempts:8}},
]}}};
const solidStarterIntelligence = {players:{
  "10":{position_group:"QB",rating:81.4},
  "11":{position_group:"QB",rating:45.6},
}};
const solidStarter = impact.rateTeam(
  [{player:"Solid Starter",position:"QB",status:"Out"}],
  "MidTier",
  solidStarterRoster,
  solidStarterIntelligence
);
assert.ok(solidStarter.players[0].absenceValuePoints >= 3.5 && solidStarter.players[0].absenceValuePoints <= 4.1,
  "a good non-elite starter with an observed backup should remain near four points");
assert.equal(solidStarter.players[0].sixPointEligible, false);

console.log("availability impact tests passed");
