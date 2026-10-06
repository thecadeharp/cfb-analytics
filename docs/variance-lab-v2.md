# THI Variance Lab v2

Variance Lab publishes every predefined test, including losing hypotheses. A
historical system enters **Verified** only with at least 200 graded decisions,
positive estimated ROI at -110 and a 95% separation from a 50% hit rate.
Prospective decisions are frozen at their first eligible pregame capture.

## Context sources

- CFBD `/games`: exact kickoff, conference and subdivision for each season.
- CFBD `/rankings`: the poll available before each football game.
- CFBD `/games/weather`: kickoff wind, temperature, precipitation and indoor status.
- CBBD `/rankings`: the AP poll published before each basketball game.
- THI settled warehouses: final scores, opening lines and closing lines.

Missing or unauthorized inputs remain **Source pending**. The builder does not
substitute final rankings, current conference membership or forecast weather for
historical point-in-time facts.

## Reverse Line Movement contract

An alert requires all of the following:

1. A licensed public-ticket percentage and named public side.
2. An opening and current spread from the same named sharp book.
3. Odds and split snapshots captured within five minutes of each other.
4. At least 65% of tickets on one side.
5. A spread move of at least 0.5 points toward the opponent.

Crossing 3, 7 or 10, or combining 75% tickets with a move of at least 1.5
points, raises the alert to `max`. Handle percentage is displayed when supplied
but never replaces the required ticket percentage.

The feed bridge uses four repository secrets:

- `THI_ODDS_FEED_URL`
- `THI_ODDS_FEED_TOKEN`
- `THI_SPLITS_FEED_URL`
- `THI_SPLITS_FEED_TOKEN`

The URLs must return canonical event arrays keyed by `sport` and `event_id`.
The odds rows include `captured_at_utc`, teams, start date, named book, opening
home spread and current home spread. Split rows include `captured_at_utc`, named
source, public side and public ticket percentage. Provider credentials remain in
GitHub secrets and are never written to site data.
