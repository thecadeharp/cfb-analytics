(() => {
  "use strict";

  const FEEDS = [
    {
      label: "CFB projections",
      url: "data/projections.json",
      timestamps: ["meta.generated"],
      maxAgeHours: () => 30,
    },
    {
      label: "CFB scores",
      url: "data/live_scores.json",
      timestamps: ["meta.generated_at"],
      maxAgeHours: payload => (payload?.games?.length ? 0.75 : 6),
    },
    {
      label: "Availability reports",
      url: "data/roster_notes.json",
      timestamps: ["meta.generated_at_utc"],
      maxAgeHours: () => ([0, 4, 5, 6].includes(new Date().getDay()) ? 2.5 : 14),
    },
    {
      label: "CBB projections",
      url: "data/cbb/projection_board.json",
      timestamps: ["meta.generated_at_utc"],
      maxAgeHours: () => 15,
    },
    {
      label: "CBB platform",
      url: "data/cbb/platform_health.json",
      timestamps: ["meta.generated_at_utc"],
      maxAgeHours: () => 15,
      validate: payload => ["healthy", "attention_required"].includes(payload?.meta?.status),
    },
    {
      label: "Market monitoring",
      url: "data/market/rlm_monitor.json",
      timestamps: ["meta.generated_at_utc"],
      maxAgeHours: () => 8,
    },
  ];

  function nested(payload, path) {
    return path.split(".").reduce((value, key) => value?.[key], payload);
  }

  function parseTimestamp(value) {
    if (!value) return null;
    const text = String(value);
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`;
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function latestTimestamp(payload, paths) {
    for (const path of paths) {
      const parsed = parseTimestamp(nested(payload, path));
      if (parsed) return parsed;
    }
    return null;
  }

  function formatTimestamp(date) {
    if (!date) return "No valid update timestamp";
    return `Updated ${new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(date)}`;
  }

  async function inspectFeed(feed) {
    try {
      const bucket = Math.floor(Date.now() / 300000);
      const response = await fetch(`${feed.url}?status=${bucket}`, { cache: "no-cache" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const timestamp = latestTimestamp(payload, feed.timestamps);
      const ageHours = timestamp ? (Date.now() - timestamp.getTime()) / 3600000 : Infinity;
      const valid = feed.validate ? feed.validate(payload) : true;
      const current = valid && ageHours >= -0.25 && ageHours <= feed.maxAgeHours(payload);
      return {
        ...feed,
        state: current ? "current" : "delayed",
        timestamp,
      };
    } catch (_error) {
      return { ...feed, state: "unavailable", timestamp: null };
    }
  }

  function renderItem(feed) {
    const item = document.createElement("div");
    item.className = "data-health-item";

    const head = document.createElement("div");
    head.className = "data-health-item-head";
    const label = document.createElement("span");
    label.className = "data-health-label";
    label.textContent = feed.label;
    const state = document.createElement("span");
    state.className = `data-health-state ${feed.state}`;
    state.textContent = feed.state;
    head.append(label, state);

    const time = document.createElement("div");
    time.className = "data-health-time";
    time.textContent = feed.state === "unavailable"
      ? "Published feed could not be loaded"
      : formatTimestamp(feed.timestamp);
    item.append(head, time);
    return item;
  }

  async function renderStatus() {
    const panel = document.getElementById("data-health-panel");
    const grid = document.getElementById("data-health-grid");
    const headline = document.getElementById("data-health-headline");
    const count = document.getElementById("data-health-count");
    if (!panel || !grid || !headline || !count) return;

    const feeds = await Promise.all(FEEDS.map(inspectFeed));
    grid.replaceChildren(...feeds.map(renderItem));
    const unavailable = feeds.filter(feed => feed.state === "unavailable").length;
    const delayed = feeds.filter(feed => feed.state === "delayed").length;
    const current = feeds.length - unavailable - delayed;
    const overall = unavailable ? "unavailable" : delayed ? "delayed" : "current";
    panel.dataset.state = overall;
    headline.textContent = overall === "current" ? "Published data systems current" : "Published data needs attention";
    count.textContent = `${current}/${feeds.length} current${delayed ? ` · ${delayed} delayed` : ""}${unavailable ? ` · ${unavailable} unavailable` : ""}`;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderStatus, { once: true });
  } else {
    renderStatus();
  }
})();
