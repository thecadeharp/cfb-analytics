# THI engagement analytics

## What remains in place

Cloudflare Web Analytics remains embedded in `index.html` with its existing token. It continues to provide the aggregate visits, page views, geography and technical traffic view. The engagement layer complements it; it does not replace it.

## Event platform

THI uses manual PostHog product-analytics events because Cloudflare Web Analytics does not provide the custom-event, property, funnel, path and retention reporting needed for feature analytics. The browser SDK is loaded only when a PostHog public project token is present.

The PostHog configuration intentionally disables:

- autocapture
- automatic page views
- page-leave capture
- session recording
- anonymous person profiles

Development hosts (`localhost`, `127.0.0.1`, `file:` and blank hosts) do not send analytics.

## Production activation

1. Create a PostHog project in the preferred region.
2. Copy the **public project token** and ingestion host. Do not use a personal API key or private key in the browser.
3. Supply these public build/deployment variables before `analytics-config.js` loads:

```html
<script>
  window.THI_POSTHOG_KEY = "<public project token>";
  window.THI_POSTHOG_HOST = "https://us.i.posthog.com";
</script>
```

For a deployment system that supports environment substitution, map `POSTHOG_PROJECT_KEY` and `POSTHOG_HOST` to those two browser globals. The repository deliberately does not contain a project token because no production PostHog project was connected during implementation.

The token is public by design, but it should still be managed as deployment configuration so production and test projects cannot be confused. Cloudflare's existing beacon needs no change.

## Events and properties

The implemented event allowlist is:

| Event | Trigger |
| --- | --- |
| `session_start` | Once per browser-tab session |
| `section_view` | A meaningful CFB or CBB section change |
| `view_index25` | Opening the CFB THI Ratings / Index 25 view |
| `switch_rankings` | Choosing Power or Résumé sorting in Index 25 |
| `view_team` | Opening a CFB or CBB team profile |
| `view_matchup` | Opening a CFB matchup |
| `view_projection` | Opening the projection inside a CFB or CBB matchup detail |
| `view_cbb` | Switching into college basketball |
| `view_cbb_matchup` | Opening a CBB matchup |
| `click_subscribe` | Clicking a Substack destination |
| `click_outbound` | Clicking another external HTTP(S) destination |
| `search_used` | Using an existing search field; the search text is never sent |
| `filter_changed` | Changing an existing select/status/date filter |

`switch_matchup_tab` is reserved in the allowlist but is not emitted because the current matchup pages do not expose a true matchup tab control. It should be wired only if that interaction is added later.

Allowed properties include sport, team names/IDs, matchup ID, section, ranking type, filter/search category, virtual route, timestamp, referring host/source category, and the `utm_source`, `utm_medium`, `utm_campaign`, and `utm_content` values. Email addresses, passwords, account fields, raw search text, session replay, and arbitrary URL parameters are not collected.

## Virtual page paths

Manual virtual page views use stable paths such as:

- `/cfb/projections`
- `/cfb/thi-ratings`
- `/cfb/team/Notre%20Dame`
- `/cfb/matchup/401864524`
- `/cbb/projections`
- `/cbb/ratings`
- `/cbb/team/123`
- `/cbb/matchup/456`

The event layer deduplicates consecutive views of the same virtual path. CFB push-state/back-forward navigation and direct matchup hashes are handled by the existing router hooks. Direct CBB matchup URLs (`?sport=cbb&game=…`) are handled by the existing CBB loader. Component rerenders do not emit page views.

## Recommended PostHog dashboard

Create a dashboard named **THI Engagement** with these tiles:

1. **Visitors and sessions** — unique users and unique sessions on `$pageview`, daily trend with 7/30-day date controls.
2. **New vs returning** — `$pageview`, broken down by `visitor_status`.
3. **Index 25 reach** — unique users and total events for `view_index25`.
4. **Matchup researchers** — unique users for `view_matchup` + `view_cbb_matchup`.
5. **Top CFB matchups** — `view_matchup`, broken down by `matchup_id`, with `away_team` and `home_team` visible in the data table.
6. **Top CBB matchups** — `view_cbb_matchup`, same breakdown.
7. **Section engagement** — `section_view`, broken down by `section` and filterable by `sport`.
8. **Power vs Résumé switches** — `switch_rankings`, broken down by `ranking_type`.
9. **Acquisition quality** — `session_start` by `referral_source` or `utm_source`, plus a funnel from `session_start` to any of `view_index25`, `view_matchup`, `view_cbb_matchup`, or `click_subscribe`.
10. **Substack conversion** — `click_subscribe` totals, unique users, and funnel conversion from `session_start`.
11. **Return behavior** — a retention insight beginning with `session_start` and returning on `session_start`.
12. **Research path** — a paths insight beginning at `$pageview` or `section_view` and ending at `click_subscribe`.

PostHog's Lifecycle insight can also show new, returning, resurrecting and dormant anonymous visitors. Keep the Cloudflare dashboard as the high-level traffic source of truth during the first validation period; compare its visit totals with PostHog sessions rather than expecting exact equality because their session definitions and blocking behavior differ.

## Verification checklist

After adding the public token in a production or staging deployment:

1. Open the site with `?utm_source=test&utm_medium=qa&utm_campaign=analytics_validation`.
2. Confirm one `session_start` and one initial `$pageview` in PostHog Live Events.
3. Open Index 25, switch to Résumé, open a team, and verify the three named events.
4. Open one CFB and one CBB matchup and verify matchup IDs and team properties.
5. Use a search and confirm `search_category` exists but no search text is present.
6. Click the Substack link and confirm `click_subscribe` stores only the destination host/path.
7. Navigate back/forward through a CFB matchup and confirm one virtual page view per real navigation.
8. Confirm Cloudflare Web Analytics continues receiving traffic independently.

If THI later adds consent controls, wire them to `posthog.opt_in_capturing()` and `posthog.opt_out_capturing()`; do not create a second analytics identity system.
