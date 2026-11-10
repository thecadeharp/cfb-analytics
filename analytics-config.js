(function () {
  "use strict";

  // This file contains public browser configuration only. The PostHog project
  // token is intentionally blank in source control and should be supplied by
  // the production deployment (see docs/engagement-analytics.md).
  window.THI_ANALYTICS_CONFIG = Object.freeze({
    enabled: true,
    posthogKey: window.THI_POSTHOG_KEY || "",
    posthogHost: window.THI_POSTHOG_HOST || "https://us.i.posthog.com"
  });
})();
