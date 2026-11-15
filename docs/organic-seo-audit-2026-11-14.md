# THI Organic SEO Audit — November 14, 2026

## Scope and confirmed architecture

- Production is a static, framework-free single-page application served by GitHub Pages at `https://thehammerindex.com/`.
- CFB detail views use fragment routes such as `#matchup=401864524` and `#dossier=Team Name`.
- CBB shared matchup views use query parameters such as `?sport=cbb&game=...`.
- Major section controls are JavaScript buttons rather than distinct crawlable documents.
- There is no server-side rendering, prerendering, static route generator, application backend or route-aware HTML metadata.
- Cloudflare Web Analytics is loaded once. A separate privacy-conscious engagement layer publishes virtual page views and approved custom events when a public PostHog key is supplied.

## Confirmed findings

### High priority

1. `robots.txt` and `sitemap.xml` returned HTTP 404 before this change.
2. The live site map exposed only the homepage. Matchups, team profiles, rankings and CBB sections did not have distinct crawlable URLs in the public URL inventory.
3. Fragment identifiers are not sent to the web server. A request for `/#matchup=401864524` receives the same HTML document, title, description and canonical URL as `/`.
4. All current SPA states declare the root homepage as canonical. That is correct for the present one-document architecture, but it means those states are not candidates for distinct indexing.
5. Crawler rendering can access a substantial amount of app content after JavaScript runs. The site is therefore not invisible to crawlers, but that content is consolidated under one document and one search result.

### Medium priority

1. The homepage title and description accurately described THI but did not directly target the strongest existing search intents: college football and basketball power ratings, matchup projections, résumé rankings and strength of schedule.
2. The homepage did not publish Organization, WebSite or WebPage structured data.
3. The repository contains no Google Search Console verification token.
4. Team-profile controls and major navigation controls are buttons, so there is no conventional internal-link graph for crawlers.

### Performance and analytics

- No additional analytics script was added by this SEO work.
- No model, rating, projection, data pipeline or historical result was changed.
- The implementation adds only small static text files and head metadata; it adds no runtime dependency or rendering work.
- Existing Google Fonts remain render-blocking. They were left unchanged because altering font delivery could affect visual rendering and is outside this nonvisual SEO pass.

## Safe improvements implemented

- Rewrote homepage title and description around content THI actually publishes.
- Added explicit crawl/snippet directives, author metadata and consistent Open Graph/Twitter copy.
- Added truthful Organization, WebSite and WebPage JSON-LD without ratings, reviews or performance claims.
- Added `robots.txt`, allowing public rendering assets while excluding internal documentation, scripts and tests from crawl targets.
- Added a valid root-only XML sitemap. Hash routes were deliberately omitted because fragments are not distinct HTTP resources.
- Added an automated SEO contract test to the existing public-release canary.

## Indexability after this pass

- **Distinctly indexable now:** the homepage at `https://thehammerindex.com/`.
- **Render-accessible within the homepage:** CFB and CBB tools and data that load successfully in the browser.
- **Not distinctly indexable yet:** individual CFB matchups, individual CFB team dossiers, CBB matchups, CBB team profiles, CFB/CBB ratings sections, résumé rankings and strength-of-schedule sections.

Creating separate indexable documents for those areas would be a meaningful routing/content architecture change. The lowest-risk next step is a small set of static, high-quality landing pages for the major evergreen sections, followed later by selected matchup/team pages only where the content is substantial and remains current. Existing hash links can remain supported during that work.

## Google Search Console manual setup

Google Search Console is free. Prefer a **Domain property** for `thehammerindex.com`, which covers HTTP/HTTPS and all subdomains.

1. Open `https://search.google.com/search-console/` and add a Domain property for `thehammerindex.com`.
2. Google will provide a TXT verification value.
3. Add that TXT value in the DNS provider currently authoritative for the domain. Do not remove existing DNS records.
4. Return to Search Console and click **Verify**. DNS propagation can take time.
5. In **Sitemaps**, submit `https://thehammerindex.com/sitemap.xml`.
6. Use **URL inspection** for `https://thehammerindex.com/`, test the live URL and request indexing after the deployment is confirmed.
7. Monitor **Pages** for crawl/indexing errors and **Performance → Search results** for queries, pages, countries, devices, impressions, clicks, CTR and average position.

Search Console reports Google organic search discovery and search-result performance. Cloudflare reports aggregate traffic and page requests. THI's engagement analytics reports in-product actions and virtual SPA page views. None replaces the others.

## Recommended next phase requiring approval

1. Create four to seven crawlable evergreen landing pages for CFB power ratings, CBB power ratings, CFB projections, CBB projections, résumé/SOS methodology and model tracking.
2. Preserve the SPA and all shared hash/query links, while letting landing pages open the same existing tools.
3. Add normal internal links to those pages in an existing low-impact navigation area.
4. Evaluate a deliberately limited set of crawlable matchup/team pages only after defining freshness, canonical and thin-content rules.

This phase would remain compatible with GitHub Pages and require no paid service, but it changes public URL architecture and visible internal navigation, so it was not implemented without approval.

## Cost

- Implemented changes: **$0**.
- GitHub Pages files, robots.txt, sitemap.xml, JSON-LD and Google Search Console: **$0** under the existing setup.
- No paid API, SEO platform, hosting upgrade, advertisement or new dependency is required.
