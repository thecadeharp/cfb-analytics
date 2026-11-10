(function () {
  "use strict";

  const config = window.THI_ANALYTICS_CONFIG || {};
  const EVENT_NAMES = new Set([
    "session_start",
    "section_view",
    "view_index25",
    "switch_rankings",
    "view_team",
    "view_matchup",
    "switch_matchup_tab",
    "view_projection",
    "view_cbb",
    "view_cbb_matchup",
    "click_subscribe",
    "click_outbound",
    "search_used",
    "filter_changed"
  ]);
  const SAFE_PROPERTIES = new Set([
    "sport", "team_name", "team_id", "away_team", "away_team_id",
    "home_team", "home_team_id", "matchup_id", "section", "tab_name",
    "ranking_type", "search_category", "filter_category", "filter_value",
    "route", "route_hash", "referral_source", "referral_host", "utm_source",
    "utm_medium", "utm_campaign", "utm_content", "destination_host",
    "destination_path", "surface", "timestamp", "visitor_status"
  ]);
  const DEVELOPMENT_HOSTS = new Set(["", "localhost", "127.0.0.1", "::1"]);
  const SESSION_KEY = "thi:analytics:session";
  const RETURNING_KEY = "thi:analytics:returning";
  const ATTRIBUTION_KEY = "thi:analytics:attribution";
  const MAX_VALUE_LENGTH = 160;
  const queue = [];
  const lastSearchSignatures = new Map();
  let providerReady = false;
  let lastPageKey = "";
  const visitorStatus = safeStorage(localStorage, "get", RETURNING_KEY) === "1" ? "returning" : "new";

  function safeStorage(storage, method, key, value) {
    try {
      return method === "get" ? storage.getItem(key) : storage.setItem(key, value);
    } catch (_error) {
      return null;
    }
  }

  function cleanValue(value) {
    if (value === null || value === undefined || value === "") return undefined;
    if (typeof value === "number" || typeof value === "boolean") return value;
    return String(value).replace(/[\r\n\t]+/g, " ").trim().slice(0, MAX_VALUE_LENGTH);
  }

  function referralCategory(host) {
    const value = String(host || "").toLowerCase().replace(/^www\./, "");
    if (!value) return "unattributed";
    if (value === window.location.hostname.toLowerCase().replace(/^www\./, "")) return "internal";
    if (value === "t.co" || value === "x.com" || value === "twitter.com") return "x";
    if (value.endsWith("substack.com")) return "substack";
    if (value.endsWith("google.com")) return "google";
    if (value.endsWith("bing.com")) return "bing";
    if (value.endsWith("duckduckgo.com")) return "duckduckgo";
    return "other";
  }

  function readAttribution() {
    const url = new URL(window.location.href);
    let referralHost = "";
    try { referralHost = document.referrer ? new URL(document.referrer).hostname : ""; }
    catch (_error) { referralHost = ""; }

    const captured = {
      referral_source: referralCategory(referralHost),
      referral_host: cleanValue(referralHost),
      utm_source: cleanValue(url.searchParams.get("utm_source")),
      utm_medium: cleanValue(url.searchParams.get("utm_medium")),
      utm_campaign: cleanValue(url.searchParams.get("utm_campaign")),
      utm_content: cleanValue(url.searchParams.get("utm_content"))
    };
    const hasCampaign = captured.utm_source || captured.utm_medium || captured.utm_campaign || captured.utm_content;
    const stored = safeStorage(sessionStorage, "get", ATTRIBUTION_KEY);
    if (!hasCampaign && stored) {
      try { return JSON.parse(stored); } catch (_error) { /* Use current attribution. */ }
    }
    safeStorage(sessionStorage, "set", ATTRIBUTION_KEY, JSON.stringify(captured));
    return captured;
  }

  const attribution = readAttribution();

  function baseProperties() {
    return {
      timestamp: new Date().toISOString(),
      route: safeCurrentRoute(),
      route_hash: safeRouteHash(),
      visitor_status: visitorStatus,
      ...attribution
    };
  }

  function safeCurrentRoute() {
    const url = new URL(window.location.href);
    const sport = url.searchParams.get("sport");
    const game = url.searchParams.get("game");
    if (sport === "cbb" && /^\d+$/.test(game || "")) return `${url.pathname}?sport=cbb&game=${game}`;
    return url.pathname.slice(0, MAX_VALUE_LENGTH);
  }

  function safeRouteHash() {
    const match = window.location.hash.match(/^#(matchup|dossier)=([^&]{1,120})$/);
    return match ? `#${match[1]}=${match[2]}` : undefined;
  }

  function sanitizeProperties(properties) {
    const sanitized = {};
    for (const [key, value] of Object.entries({ ...baseProperties(), ...(properties || {}) })) {
      if (!SAFE_PROPERTIES.has(key)) continue;
      const clean = cleanValue(value);
      if (clean !== undefined) sanitized[key] = clean;
    }
    return sanitized;
  }

  function productionCaptureAllowed() {
    if (config.enabled === false) return false;
    if (window.location.protocol === "file:") return false;
    return !DEVELOPMENT_HOSTS.has(window.location.hostname.toLowerCase());
  }

  function send(eventName, properties) {
    if (!providerReady || !window.posthog?.capture) {
      queue.push([eventName, properties]);
      return;
    }
    window.posthog.capture(eventName, properties);
  }

  function track(eventName, properties) {
    if (!EVENT_NAMES.has(eventName) || !productionCaptureAllowed()) return;
    send(eventName, sanitizeProperties(properties));
  }

  function virtualPageView(virtualPath, properties) {
    if (!productionCaptureAllowed()) return false;
    const pageKey = cleanValue(virtualPath) || "/";
    if (pageKey === lastPageKey) return false;
    lastPageKey = pageKey;
    send("$pageview", {
      ...sanitizeProperties(properties),
      $current_url: `${window.location.origin}${pageKey}`,
      $pathname: pageKey,
      virtual_path: pageKey
    });
    return true;
  }

  function sectionPath(sport, section) {
    const normalizedSport = String(sport || "CFB").toLowerCase();
    const normalizedSection = String(section || "home").replace(/^cbb-/, "").replace(/[^a-z0-9-]+/gi, "-").toLowerCase();
    return `/${normalizedSport}/${normalizedSection}`;
  }

  function navigate(properties) {
    const sport = String(properties?.sport || "CFB").toUpperCase();
    const section = properties?.section || "home";
    const route = properties?.virtual_path || sectionPath(sport, section);
    const changed = virtualPageView(route, { ...properties, sport, section });
    if (!changed) return;
    track("section_view", { ...properties, sport, section, route });
    if (sport === "CFB" && section === "thi-ratings") track("view_index25", { sport, section, route });
  }

  function viewTeam(properties) {
    const sport = String(properties?.sport || "CFB").toUpperCase();
    const id = cleanValue(properties?.team_id || properties?.team_name || "team");
    const virtualPath = `/${sport.toLowerCase()}/team/${encodeURIComponent(id)}`;
    virtualPageView(virtualPath, { ...properties, sport, section: "team-profile" });
    track("view_team", { ...properties, sport, section: "team-profile", route: virtualPath });
  }

  function viewMatchup(properties) {
    const sport = String(properties?.sport || "CFB").toUpperCase();
    const id = cleanValue(properties?.matchup_id || "matchup");
    const virtualPath = `/${sport.toLowerCase()}/matchup/${encodeURIComponent(id)}`;
    virtualPageView(virtualPath, { ...properties, sport, section: "matchup" });
    track(sport === "CBB" ? "view_cbb_matchup" : "view_matchup", { ...properties, sport, section: "matchup", route: virtualPath });
    track("view_projection", { ...properties, sport, section: "matchup", surface: "matchup_detail", route: virtualPath });
  }

  function initPostHog() {
    const key = cleanValue(config.posthogKey);
    if (!key || !productionCaptureAllowed()) return;
    const host = cleanValue(config.posthogHost) || "https://us.i.posthog.com";
    if (!window.posthog?.__SV) {
      const posthog = window.posthog = window.posthog || [];
      posthog._i = posthog._i || [];
      posthog.init = function (token, options, name) {
        const instance = name ? (posthog[name] = posthog[name] || []) : posthog;
        const methods = "capture identify alias people.set people.set_once register register_once register_for_session unregister unregister_for_session opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing reset get_distinct_id get_session_id".split(" ");
        for (const method of methods) {
          const parts = method.split(".");
          let target = instance;
          let methodName = method;
          if (parts.length === 2) {
            target[parts[0]] = target[parts[0]] || [];
            target = target[parts[0]];
            methodName = parts[1];
          }
          target[methodName] = function () { target.push([methodName, ...arguments]); };
        }
        posthog._i.push([token, options, name]);
      };
      posthog.__SV = 1;
      const script = document.createElement("script");
      script.async = true;
      script.crossOrigin = "anonymous";
      script.src = `${host.replace(".i.posthog.com", "-assets.i.posthog.com")}/static/array.js`;
      document.head.appendChild(script);
    }
    window.posthog.init(key, {
      api_host: host,
      defaults: "2026-08-30",
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      disable_session_recording: true,
      person_profiles: "identified_only",
      persistence: "localStorage"
    });
    providerReady = true;
    while (queue.length) {
      const [eventName, properties] = queue.shift();
      window.posthog.capture(eventName, properties);
    }
  }

  function outboundDetails(anchor) {
    try {
      const destination = new URL(anchor.href, window.location.href);
      if (!["http:", "https:"].includes(destination.protocol)) return null;
      if (destination.hostname === window.location.hostname) return null;
      return {
        destination_host: destination.hostname,
        destination_path: destination.pathname.slice(0, MAX_VALUE_LENGTH),
        section: activeSection()
      };
    } catch (_error) {
      return null;
    }
  }

  function activeSection() {
    return document.querySelector(".view.active")?.id?.replace(/^view-/, "") || "unknown";
  }

  function filterCategory(element) {
    const raw = element.id || element.name || element.dataset.filterCategory || element.dataset.cbbStatus || element.dataset.cbbDate || element.dataset.thiSort || "filter";
    return String(raw).replace(/^(cbb-|thi-)/, "").replace(/[^a-z0-9]+/gi, "_").toLowerCase().slice(0, 64);
  }

  function safeFilterValue(element) {
    if (element.dataset.cbbStatus) return element.dataset.cbbStatus;
    if (element.dataset.cbbDate) return element.dataset.cbbDate;
    if (element.dataset.thiSort) return element.dataset.thiSort;
    if (element.tagName === "SELECT") return element.value;
    return element.getAttribute("aria-pressed") || element.dataset.value || "selected";
  }

  function bindDelegatedEvents() {
    document.addEventListener("click", event => {
      const anchor = event.target.closest("a[href]");
      if (anchor) {
        const details = outboundDetails(anchor);
        if (details) {
          const isSubstack = details.destination_host.endsWith("substack.com");
          track(isSubstack ? "click_subscribe" : "click_outbound", details);
        }
      }

      const ranking = event.target.closest("[data-thi-sort]");
      if (ranking && ["index_rank", "resume_rank"].includes(ranking.dataset.thiSort)) {
        track("switch_rankings", {
          sport: "CFB",
          section: "thi-ratings",
          ranking_type: ranking.dataset.thiSort === "resume_rank" ? "resume" : "power"
        });
      }

      const filter = event.target.closest("[data-cbb-status], [data-cbb-date]");
      if (filter) {
        track("filter_changed", {
          sport: "CBB",
          section: activeSection(),
          filter_category: filterCategory(filter),
          filter_value: safeFilterValue(filter)
        });
      }
    }, true);

    document.addEventListener("change", event => {
      const element = event.target;
      if (!(element instanceof HTMLElement)) return;

      if (element.matches("#thi-ratings-mobile-sort") && /^(index_rank|resume_rank):/.test(element.value)) {
        track("switch_rankings", {
          sport: "CFB",
          section: "thi-ratings",
          ranking_type: element.value.startsWith("resume_rank") ? "resume" : "power"
        });
      }

      if (element.matches("select") && !element.closest("[data-no-analytics]")) {
        track("filter_changed", {
          sport: document.body.classList.contains("thi-sport-cbb") ? "CBB" : "CFB",
          section: activeSection(),
          filter_category: filterCategory(element),
          filter_value: safeFilterValue(element)
        });
      }

      if (element.matches('input[type="search"]')) recordSearch(element);
    }, true);

    document.addEventListener("keydown", event => {
      if (event.key === "Enter" && event.target instanceof HTMLElement && event.target.matches('input[type="search"]')) recordSearch(event.target);
    }, true);
  }

  function recordSearch(input) {
    const present = Boolean(String(input.value || "").trim());
    if (!present) return;
    const category = filterCategory(input);
    const signature = `${activeSection()}:${category}`;
    if (lastSearchSignatures.get(signature) === input.value) return;
    lastSearchSignatures.set(signature, input.value);
    track("search_used", {
      sport: document.body.classList.contains("thi-sport-cbb") ? "CBB" : "CFB",
      section: activeSection(),
      search_category: category
    });
  }

  const api = Object.freeze({ track, navigate, viewTeam, viewMatchup, virtualPageView });
  window.THIAnalytics = api;
  initPostHog();
  bindDelegatedEvents();

  function trackInitialView() {
    const sharedCfbMatchup = /^#matchup=/.test(window.location.hash);
    const params = new URLSearchParams(window.location.search);
    const sharedCbbMatchup = params.get("sport") === "cbb" && /^\d+$/.test(params.get("game") || "");
    if (sharedCfbMatchup || sharedCbbMatchup) return;
    const active = document.querySelector(".view.active");
    const section = active?.id?.replace(/^view-/, "") || "projections";
    const sport = document.body.classList.contains("thi-sport-cbb") ? "CBB" : "CFB";
    navigate({ sport, section });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => window.setTimeout(trackInitialView, 0), { once: true });
  } else {
    window.setTimeout(trackInitialView, 0);
  }

  if (!safeStorage(sessionStorage, "get", SESSION_KEY)) {
    track("session_start", { section: "landing" });
    safeStorage(sessionStorage, "set", SESSION_KEY, "1");
  }
  safeStorage(localStorage, "set", RETURNING_KEY, "1");
})();
