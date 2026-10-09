# THI commercial launch readiness

Last reviewed: 2026-10-09

This is the permanent pre-paywall checklist for The Hammer Index. It records product and data-rights work; it is not legal advice or a substitute for counsel reviewing the final product, customer terms, and launch jurisdictions.

## Current decision

THI can be positioned as paid college-sports research, model transparency, team intelligence, and decision support after the blocking items below are resolved. Do not position it as a proven profitable picks product unless prospective, price-aware validation clears the published promotion gate.

Do not launch a paywall over the current static site unchanged. GitHub Pages serves public JSON assets directly, so hiding navigation or requiring a browser login would not protect licensed or subscriber-only data.

## Rights register

| Source or asset | Status | Commercial conditions |
| --- | --- | --- |
| THI models, ratings, projections, written analysis, and visualizations | Eligible | Preserve methodology and validation disclosures. Do not make unsupported profitability claims. |
| CollegeFootballData and CollegeBasketballData | Permitted with limits | Paid applications and derived outputs are permitted. Do not expose keys, raw responses, bulk mirrors, substitute feeds, or substantially equivalent datasets. These terms do not grant third-party logo, trademark, player-likeness, broadcast, or media rights. [Terms](https://collegefootballdata.com/terms) |
| The Odds API | Permitted with limits | Commercial UI display, storage, research, and derived analytics are permitted when the feed is not the primary standalone product being resold. Do not publish a raw odds feed, download, or substitute API. [Terms](https://the-odds-api.com/terms-and-conditions.html) |
| OpenStreetMap | Permitted with attribution | Show linked `© OpenStreetMap contributors` attribution and identify the ODbL. Review share-alike obligations if THI distributes an OSM-derived database rather than only produced research outputs. [Copyright and license](https://www.openstreetmap.org/copyright) |
| Novig | Approval pending | Odds-screen and deeplink integration begins only after affiliate approval, Partner ID, credentials, and the governing agreement confirm paywalled display, caching, historical storage, and permitted branding. [Affiliate documentation](https://docs.novig.com/affiliates/overview) |
| Public ticket and handle splits | Provider pending | Do not display, cache, derive RLM alerts from, or place behind a paywall until the selected license expressly permits commercial subscriber display, historical retention, derived signals, and the intended polling frequency. |
| SportsDataverse datasets | Source review required | Record the exact dataset and license, satisfy CC BY attribution where applicable, and separately review rights in upstream ESPN/NCAA-derived content. A package code license does not automatically clear every underlying dataset. |
| ESPN endpoints and ESPN-hosted assets | Blocking | Replace or obtain a commercial license. Current Disney/ESPN terms restrict automated extraction and commercial use. [Terms](https://disneytermsofuse.com/english/) |
| School, conference, tournament, and broadcaster logos | Blocking unless licensed | Replace with THI-neutral text or monograms, or obtain documented permission. Provider access alone does not grant mark or artwork rights. |
| Team and player factual references | Counsel review | Use descriptively, avoid endorsement or affiliation implications, and review publicity/trademark risk in the final paid presentation. |

## Engineering requirements before payment launch

- Move subscriber-only data and entitlements behind an authenticated server or protected API. Do not rely on client-side hiding.
- Keep provider credentials exclusively in server-side secrets.
- Publish only the minimum factual fields needed for the product; keep raw provider responses private.
- Maintain a versioned source register with the license, retrieval method, attribution, retention limits, and last review date for every production dependency.
- Add automated checks preventing source-pending fields and unlicensed assets from entering paid builds.
- Preserve immutable projection, selection, price, closing-line, and grading records so performance claims are reproducible.
- Retain a fail-closed mode for stale odds, missing prices, unmatched events, delayed splits, and provider outages.

## RLM and odds-screen launch requirements

- Canonically match events using sport, normalized teams, scheduled time, and venue; vendor event IDs cannot be assumed to match.
- Validate percentage ranges, public-side orientation, timestamps, duplicate records, line orientation, and market type.
- Freeze the first qualifying opening line and never overwrite it with later polls.
- Display explicit `Live`, `Delayed`, `Stale`, `Provider down`, and `Unmatched` states.
- Run new splits and RLM integrations in internal shadow mode before publishing alerts.
- Store the exact provider, split, sharp-book price, timestamps, matching evidence, and rule that produced every alert.
- Never infer ticket or handle percentages from price movement or exchange liquidity.

## Customer and business requirements

- Obtain legal review of the source register, product claims, Terms of Service, Privacy Policy, refund policy, subscription disclosures, cancellation flow, age policy, and launch jurisdictions.
- Obtain payment-processor approval for the exact college-sports research product before accepting payments.
- Provide clear recurring-price, renewal, cancellation, and refund terms before checkout; maintain easy online cancellation and records of consent.
- Add responsible-wagering language and keep THI framed as informational research rather than a sportsbook or wager-taking service.
- Place clear, conspicuous compensation disclosures beside sportsbook or Novig affiliate links. [FTC affiliate guidance](https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking)
- Add a rights/takedown contact and an incident process for incorrect or improperly sourced material.

## Go-live gate

Commercial launch is ready only when all blocking source rows are removed or licensed, subscriber data is protected server-side, the selected market/splits agreements are recorded, legal/customer pages are live, the payment processor has approved the business, and counsel has reviewed the final implementation.
