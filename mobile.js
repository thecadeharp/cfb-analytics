(() => {
  "use strict";

  const mobileQuery =
    window.matchMedia("(max-width: 600px)");

  let buildTimer = null;
  let buildFrame = null;
  let matchupTimer = null;
  let lastSignature = "";


  // ==========================================================================
  // MOBILE-ONLY STYLES
  // ==========================================================================

  function installMobileStyles() {
    if (
      document.getElementById(
        "hammer-mobile-styles"
      )
    ) {
      return;
    }

    const style =
      document.createElement("style");

    style.id =
      "hammer-mobile-styles";

    style.textContent = `
      #mobile-projection-cards,
      .mobile-viewing-tip {
        display: none;
      }

      @media (max-width: 600px) {

        html,
        body {
          max-width: 100%;
          overflow-x: hidden;
        }

        body {
          -webkit-text-size-adjust: 100%;
        }

        .page {
          width: 100%;
          max-width: 100%;
          padding-left: 12px;
          padding-right: 12px;
        }


        .mobile-viewing-tip {
          display: block;
          margin: 16px 0 18px;
          padding: 14px 15px;

          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 10px;
        }

        .mobile-viewing-tip-title {
          margin-bottom: 5px;

          color: var(--text);

          font-family: var(--mono);
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.08em;

          text-transform: uppercase;
        }

        .mobile-viewing-tip-copy {
          color: var(--muted);

          font-size: 11px;
          line-height: 1.55;
        }


        #view-projections > .table-card {
          display: none !important;
        }


        #mobile-projection-cards {
          display: grid;
          gap: 12px;
