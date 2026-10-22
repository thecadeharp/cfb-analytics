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
          <p>I have always loved finding the details inside a game that a final score, ranking, or headline can miss. Building THI gives me a place to turn that curiosity into useful research and make the process visible instead of asking readers to trust a number without context.</p>
          <p>My goal is to grow THI into a trusted independent home for college sports analysis. I want it to be useful to serious fans, bettors, writers, and anyone who wants a clearer explanation of why teams and players perform the way they do.</p>
        </div>
      `
    },
    methodology: {
      title: "How THI Works",
      html: `
        <p><strong>THI separates team strength, season accomplishment, game projection, player evaluation, and market comparison because they answer different questions.</strong></p>
        <div class="site-info-section">
          <h3>Team Ratings</h3>
          <p><strong>Power</strong> estimates current team strength on a neutral field. <strong>Current Form</strong> emphasizes recent opponent adjusted performance. <strong>Résumé</strong> measures what a team has earned through results. <strong>Schedule Strength</strong> describes the difficulty of the opponents a team has faced or is expected to face.</p>
        </div>
        <div class="site-info-section">
          <h3>Game Projections</h3>
          <p>Game projections combine team ratings with location, personnel availability, matchup context, and other sport specific inputs. Eligible projections are frozen before the game so the published output can be graded without rewriting history.</p>
        </div>
        <div class="site-info-section">
          <h3>Signals and Evidence</h3>
          <p>A model signal describes the distance between a THI projection and the available market. It is not a recommendation. Signal confidence reports the quality and quantity of prospective evidence supporting that category.</p>
          <p>Historical research, live production models, and experimental candidates remain separate. A promising backtest does not become a production model until it clears the published validation standard.</p>
        </div>
        <button class="site-info-action" type="button" data-site-action="model-tracking">Open Model Tracking</button>
      `
    },
    validation: {
      title: "Model Tracking and Validation",
      html: `
        <p><strong>THI treats model credibility as something that must be earned through recorded evidence.</strong></p>
        <p>Production projections are frozen before eligible games and graded after the result. Model Tracking reports accuracy, record, closing line information when captured, and other measures that help show where the model performs well and where it needs work.</p>
        <p>Research candidates remain isolated from production. Promotion requires verified inputs, reproducible versions, prospective evaluation, calibration checks, and a written decision. Routine code deployment does not promote an experimental model.</p>
        <p>Labels such as provisional, developing, validated, and production describe the level of evidence behind an output. They do not describe how interesting or confident a prediction may appear.</p>
        <button class="site-info-action" type="button" data-site-action="model-tracking">Open Model Tracking</button>
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
        <p>Follow THI, join the free community, read my weekly work, and find the Hammer Time Podcast across the platforms below.</p>
        <div class="site-social-grid">
          <a class="site-social-link" href="https://discord.gg/RTYnYuGDMq" target="_blank" rel="noopener noreferrer"><span class="site-social-label">THI Community</span><span class="site-social-platform">Discord</span></a>
          <a class="site-social-link" href="https://x.com/cad_loxx" target="_blank" rel="noopener noreferrer"><span class="site-social-label">@cad_loxx</span><span class="site-social-platform">X</span></a>
          <a class="site-social-link" href="https://cadloxx.substack.com" target="_blank" rel="noopener noreferrer"><span class="site-social-label">The Hammer Index</span><span class="site-social-platform">Substack</span></a>
          <a class="site-social-link" href="https://open.spotify.com/show/6fGji3nVj2icc18sF1dsKk" target="_blank" rel="noopener noreferrer"><span class="site-social-label">Hammer Time Podcast</span><span class="site-social-platform">Spotify</span></a>
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
  const menu = document.getElementById("site-menu-dialog");
  const menuOpen = document.getElementById("site-menu-open");
  const menuClose = document.getElementById("site-menu-close");

  if (!dialog || !title || !body || !close) return;

  function openInfo(key) {
    const entry = content[key];
    if (!entry) return;
    if (menu?.open) menu.close();
    title.textContent = entry.title;
    body.innerHTML = entry.html;
    body.scrollTop = 0;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  document.querySelectorAll("[data-site-info]").forEach((button) => {
    button.addEventListener("click", () => openInfo(button.dataset.siteInfo));
  });

  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  body.addEventListener("click", event => {
    const action = event.target.closest("[data-site-action]");
    if (!action) return;
    if (dialog.open) dialog.close();
    if (action.dataset.siteAction === "model-tracking") {
      window.requestAnimationFrame(() => {
        const selector = document.body.classList.contains("thi-sport-cbb")
          ? '[data-cbb-view="cbb-tracking"]'
          : '[data-view="model-tracking"]';
        document.querySelector(selector)?.click();
      });
    }
  });

  menuOpen?.addEventListener("click", () => {
    if (typeof menu?.showModal === "function" && !menu.open) menu.showModal();
    else menu?.setAttribute("open", "");
  });
  menuClose?.addEventListener("click", () => menu?.close());
  menu?.addEventListener("click", event => {
    if (event.target === menu) menu.close();
    const sport = event.target.closest("[data-sport]")?.dataset.sport;
    if (!sport) return;
    window.thiSetSport?.(sport);
    menu.close();
  });
})();
