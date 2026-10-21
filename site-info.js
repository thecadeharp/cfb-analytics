(function () {
  "use strict";

  const content = {
    about: {
      title: "About THI",
      html: `
        <p><strong>The Hammer Index is an independent college football and college basketball analytics platform built by Cade Harper.</strong></p>
        <p>THI publishes ratings, projections, player research, market context, and public model tracking. The standard is simple. Every number should be explainable, current, and accountable.</p>
        <p>Production models and research candidates remain separate. Model status, data freshness, and known limitations are displayed wherever they materially affect interpretation.</p>
      `
    },
    contact: {
      title: "Contact",
      html: `
        <p>For partnerships, media, data corrections, or general questions, contact Cade Harper.</p>
        <p><a href="mailto:cadeharper513@gmail.com">cadeharper513@gmail.com</a></p>
        <p>Please include the relevant sport, page, team, or data point when reporting an issue. Specific details make corrections faster and easier to verify.</p>
      `
    },
    disclosure: {
      title: "Affiliate Disclosure",
      html: `
        <p>THI may receive compensation when an eligible user registers or participates through certain links on this site.</p>
        <p><strong>Commercial relationships do not determine THI ratings, projections, research conclusions, or editorial coverage.</strong> Any compensated relationship will be identified near the relevant link or placement.</p>
        <p>THI does not guarantee outcomes. Model signals describe analytical disagreement and should not be interpreted as a promise of future performance.</p>
      `
    },
    privacy: {
      title: "Privacy",
      html: `
        <p>THI uses Cloudflare Web Analytics to understand site traffic, product usage, and technical performance.</p>
        <p>If you contact THI, the information you provide is used to review and respond to your request. THI does not sell personal information.</p>
        <p>This notice will be updated before account, payment, or subscription features collect additional information.</p>
      `
    },
    terms: {
      title: "Terms of Use",
      html: `
        <p>THI provides independent analytical information for research, education, and commentary. Nothing published by THI guarantees a result.</p>
        <p>Users remain responsible for their own decisions and for following the laws, age requirements, and participation rules that apply in their location.</p>
        <p>THI models, writing, graphics, data presentation, and original research may not be copied, republished, scraped, or sold without written permission from Cade Harper.</p>
      `
    },
    responsible: {
      title: "Responsible Use",
      html: `
        <p>THI publishes analytics and research. It does not provide individualized wagering advice or guarantee profitable results.</p>
        <p>Sports markets should be approached with limits, discipline, and a clear understanding of risk. Participation is restricted by age and location.</p>
        <p>If participation stops feeling manageable, step away and seek support through the <a href="https://www.ncpgambling.org/help-treatment/" target="_blank" rel="noopener noreferrer">National Council on Problem Gambling</a>.</p>
      `
    }
  };

  const dialog = document.getElementById("site-info-dialog");
  const title = document.getElementById("site-info-title");
  const body = document.getElementById("site-info-body");
  const close = document.getElementById("site-info-close");

  if (!dialog || !title || !body || !close) return;

  function openInfo(key) {
    const entry = content[key];
    if (!entry) return;
    title.textContent = entry.title;
    body.innerHTML = entry.html;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  document.querySelectorAll("[data-site-info]").forEach((button) => {
    button.addEventListener("click", () => openInfo(button.dataset.siteInfo));
  });

  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();
