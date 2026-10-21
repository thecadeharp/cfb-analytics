(function () {
  "use strict";

  const content = {
    about: {
      title: "About THI",
      html: `
        <p><strong>The Hammer Index is my independent college football and college basketball analytics platform.</strong></p>
        <p>I built THI to create an original view of teams, players, matchups, and market movement. The site publishes ratings, projections, player research, schedule context, and public model tracking. Every number should be explainable, current, and accountable.</p>
        <p>The goal is not to copy a poll or dress an opinion up as math. I want THI to show its work, explain where the model disagrees, track the results, and be direct when the evidence is still developing.</p>
        <p>Production models and research candidates remain separate. Model status, data freshness, and known limitations are displayed wherever they materially affect interpretation.</p>
        <div class="site-info-section">
          <h3>Meet the Creator</h3>
          <p><strong>I am Cade Harper, the creator of The Hammer Index.</strong> Before building THI, I spent three years covering Notre Dame athletics for The Irish Tribune. That experience shaped how I approach this platform. Start with the full context, verify the details, and be willing to challenge the obvious answer.</p>
          <p>I also host the Hammer Time Podcast and write The Hammer Index on Substack. THI brings that work together in one place, with deeper data, clearer standards, and a public record of what the models actually produce.</p>
        </div>
      `
    },
    contact: {
      title: "Contact",
      html: `
        <p>For partnerships, media, data corrections, questions about the models, or anything else related to THI, contact me below.</p>
        <p><a href="mailto:cadeharper513@gmail.com">cadeharper513@gmail.com</a></p>
        <p>If you are reporting an issue, please include the relevant sport, page, team, or data point. Specific details make corrections faster and easier for me to verify.</p>
      `
    },
    socials: {
      title: "Follow My Work",
      html: `
        <p>Follow THI, read my weekly work, and find the Hammer Time Podcast across the platforms below.</p>
        <div class="site-social-grid">
          <a class="site-social-link" href="https://x.com/cad_loxx" target="_blank" rel="noopener noreferrer"><span class="site-social-label">@cad_loxx</span><span class="site-social-platform">X</span></a>
          <a class="site-social-link" href="https://cadloxx.substack.com" target="_blank" rel="noopener noreferrer"><span class="site-social-label">The Hammer Index</span><span class="site-social-platform">Substack</span></a>
          <a class="site-social-link" href="https://www.buzzsprout.com/2397955/about" target="_blank" rel="noopener noreferrer"><span class="site-social-label">Hammer Time Podcast</span><span class="site-social-platform">Podcast</span></a>
          <a class="site-social-link" href="https://www.youtube.com/channel/UCadEUqcxAcKJ65AAJfNCPgw" target="_blank" rel="noopener noreferrer"><span class="site-social-label">Hammer Time Podcast</span><span class="site-social-platform">YouTube</span></a>
          <a class="site-social-link" href="https://x.com/HammerTime_Pod" target="_blank" rel="noopener noreferrer"><span class="site-social-label">@HammerTime_Pod</span><span class="site-social-platform">X</span></a>
          <a class="site-social-link" href="https://www.twitch.tv/cad_loxx" target="_blank" rel="noopener noreferrer"><span class="site-social-label">@cad_loxx</span><span class="site-social-platform">Twitch</span></a>
        </div>
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
