# THI Playoff Projection v0.1

The Playoff Projection is a display-only research surface. It does not modify
Model A, ratings, tracked projections, signals or results.

## Projected field

The weekly selection score combines:

- 40% THI projected regular-season record;
- 40% THI power rating;
- 10% ESPN Strength of Record rank; and
- 10% ESPN Strength of Schedule rank.

The score projects the order rather than claiming to reproduce the CFP
committee. The field then applies the 2026 CFP access rules: projected ACC,
Big Ten, Big 12 and SEC champions; the highest-ranked projected champion from
the American, Conference USA, MAC, Mountain West, Pac-12 and Sun Belt; and the
best remaining at-large teams. Notre Dame receives its special automatic place
when it is in the projected top 12. The first four seeds receive byes, seeds
5-8 host first-round games and the bracket is not reseeded.

## Bracket simulation

Each game calls the existing hypothetical matchup engine. First-round games
use the higher seed's home field; later rounds are neutral. The displayed fair
spread, total, projected score and win probability remain hypothetical and are
excluded from prospective Model A tracking. The favorite advances in v0.1.

## Team dossiers

The Schedule & Resume Context panel retains Strength of Record, Strength of
Schedule, Remaining SOS and Game Control. THI Projected Record replaces ESPN
Projected Record and reads the existing `season_projections` output. The FPI,
offensive, defensive and special-teams components are removed from that panel.
