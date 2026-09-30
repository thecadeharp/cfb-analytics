function installObserver() {
  observer?.disconnect();
  observer = new MutationObserver(() => {
    requestAnimationFrame(() => {
      wrapSelectWeek();
      applyPerformanceScorecard();
      addAvailabilityIndicators();
      applyPanel();
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
}

async function load() {
  const stamp = Date.now();
  const [analyticsResult, settledResult, signalResult] = await Promise.allSettled([
    fetch(`${DATA_URL}?v=${stamp}`, { cache: "no-store" }),
    fetch(`${SETTLED_URL}?v=${stamp}`, { cache: "no-store" }),
    fetch(`${SIGNAL_URL}?v=${stamp}`, { cache: "no-store" }),
  ]);

  try {
    const analyticsResponse = analyticsResult.value;
    if (!analyticsResponse?.ok) throw new Error(`Postgame HTTP ${analyticsResponse?.status ?? "unavailable"}`);
    const parsed = await analyticsResponse.json();
    payload = parsed && typeof parsed === "object"
      ? normalizePayload(parsed)
      : { meta: {}, games: {} };
  } catch (error) {
    console.warn("[Hammer Postgame Analytics] Optional postgame data unavailable:", error);
    payload = { meta: {}, games: {} };
  }

  try {
    const settledResponse = settledResult.value;
    if (settledResponse?.ok) {
      const settled = await settledResponse.json();
      const rows = (settled?.rows || []).filter(row => row?.result_settled);
      const earliest = new Map();

      rows.forEach(row => {
        const id = String(row.game_key || "");
        if (!id) return;
        const current = earliest.get(id);
        if (!current || String(row.captured_at_utc || "") < String(current.captured_at_utc || "")) {
          earliest.set(id, row);
        }
      });

      settledByGame = earliest;
    }
  } catch (error) {
    console.warn("[Hammer Postgame Analytics] Settlement data unavailable:", error);
  }

  try {
    const signalResponse = signalResult.value;
    if (signalResponse?.ok) signalReport = await signalResponse.json();
  } catch (error) {
    console.warn("[Hammer Postgame Analytics] Signal report unavailable:", error);
  }

  wrapSelectWeek();
  applyPerformanceScorecard();
}
