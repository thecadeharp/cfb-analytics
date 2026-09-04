// THE HAMMER INDEX — Variance Lab coming-soon cleanup
// Drop-in presentation-only override. Does not touch Portal or future Variance data.

(() => {
  "use strict";

  function cleanVarianceComingSoon() {
    const section = document.getElementById("view-variance");
    if (!section) return;

    const subtitle = section.querySelector(".page-subtitle");
    if (subtitle) {
      subtitle.textContent =
        "Historical base rates for coaching changes, quarterback transitions, coordinator turnover and full program resets.";
    }

    const card = section.querySelector(".vl-coming-soon");
    if (!card) return;

    card.innerHTML = `<div class="vl-coming-soon-title">Coming soon 🔨</div>`;

    const title = card.querySelector(".vl-coming-soon-title");
    if (title) {
      title.style.fontFamily = "inherit";
      title.style.fontSize = "20px";
      title.style.fontWeight = "750";
      title.style.letterSpacing = "-.25px";
      title.style.lineHeight = "1.2";
    }
  }

  function boot() {
    cleanVarianceComingSoon();

    const section = document.getElementById("view-variance");
    if (!section) return;

    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        cleanVarianceComingSoon();
      });
    });

    observer.observe(section, {
      childList: true,
      subtree: true,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }

  document.addEventListener("hammer:data-ready", cleanVarianceComingSoon);
})();
