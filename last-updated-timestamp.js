(() => {
  "use strict";

  // THE HAMMER INDEX — LAST UPDATED TIMESTAMP
  // Display-only. Uses the actual generated timestamp already loaded by app.js.

  function formatUpdatedTimestamp(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;

    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true
    }).formatToParts(date);

    const get = type => parts.find(part => part.type === type)?.value ?? "";
    const month = get("month").toUpperCase();
    const day = get("day");
    const year = get("year");
    const hour = get("hour");
    const minute = get("minute");
    const dayPeriod = get("dayPeriod").toUpperCase();

    if (!month || !day || !year || !hour || !minute || !dayPeriod) return null;
    return `LAST UPDATED · ${month} ${day}, ${year} · ${hour}:${minute} ${dayPeriod} ET`;
  }

  function applyTimestamp() {
    const header = document.getElementById("data-updated");
    if (!header) return;

    const generated =
      (typeof projectionsData !== "undefined" ? projectionsData?.meta?.generated : null) ||
      (typeof metricsData !== "undefined" ? metricsData?.meta?.generated : null);

    const formatted = formatUpdatedTimestamp(generated);
    if (formatted) {
      header.textContent = formatted;
      header.title = "Timestamp shown in Eastern Time";
    }
  }

  document.addEventListener("hammer:data-ready", applyTimestamp);

  if (document.readyState !== "loading") {
    window.setTimeout(applyTimestamp, 0);
  } else {
    document.addEventListener("DOMContentLoaded", () => {
      window.setTimeout(applyTimestamp, 0);
    }, { once: true });
  }
})();
