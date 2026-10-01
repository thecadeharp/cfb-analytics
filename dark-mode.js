(() => {
  "use strict";

  const STORAGE_KEY = "thi-color-theme";
  const root = document.documentElement;
  const system = window.matchMedia("(prefers-color-scheme: dark)");

  function savedTheme() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === "dark" || value === "light" ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function applyTheme(theme, persist = false) {
    const next = theme === "dark" ? "dark" : "light";
    root.dataset.theme = next;
    root.style.colorScheme = next;
    if (persist) {
      try { localStorage.setItem(STORAGE_KEY, next); } catch (_error) {}
    }
    const button = document.getElementById("thi-theme-toggle");
    if (!button) return;
    const dark = next === "dark";
    button.setAttribute("aria-pressed", String(dark));
    button.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
    button.title = `Switch to ${dark ? "light" : "dark"} mode`;
    button.innerHTML = `<span aria-hidden="true">${dark ? "☀" : "☾"}</span><span class="thi-theme-label">${dark ? "Light" : "Dark"}</span>`;
  }

  function mountToggle() {
    if (document.getElementById("thi-theme-toggle")) return;
    const header = document.querySelector(".header-inner");
    const status = document.querySelector(".header-status");
    if (!header) return;
    const button = document.createElement("button");
    button.id = "thi-theme-toggle";
    button.className = "thi-theme-toggle";
    button.type = "button";
    button.addEventListener("click", () => {
      applyTheme(root.dataset.theme === "dark" ? "light" : "dark", true);
    });
    if (status) header.insertBefore(button, status);
    else header.appendChild(button);
    applyTheme(root.dataset.theme || (system.matches ? "dark" : "light"));
  }

  system.addEventListener?.("change", event => {
    if (!savedTheme()) applyTheme(event.matches ? "dark" : "light");
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountToggle, { once: true });
  } else {
    mountToggle();
  }
})();
