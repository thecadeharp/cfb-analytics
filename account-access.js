/* Global free-account access backed by Supabase Auth. Sessions persist in local storage. */
(() => {
  "use strict";
  const config = window.THI_PORTFOLIO_CONFIG || {};
  if (!config.enabled || !config.url || !config.publishableKey) return;

  const style = document.createElement("style");
  style.textContent = `
    .thi-account-button{border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:999px;padding:8px 12px;font:700 10px var(--mono,monospace);cursor:pointer;white-space:nowrap}
    .thi-account-overlay{position:fixed;inset:0;z-index:11000;display:grid;place-items:center;padding:20px;background:rgba(5,10,16,.78);backdrop-filter:blur(5px)}
    .thi-account-dialog{width:min(460px,100%);background:#111820;color:#f4f7fa;border:1px solid #34414d;border-radius:15px;padding:24px;box-shadow:0 25px 80px rgba(0,0,0,.45)}
    .thi-account-dialog h2{margin:7px 0 8px;font-size:25px;color:#fff}.thi-account-dialog p{margin:0 0 15px;color:#bac5cf;line-height:1.55;font-size:13px}
    .thi-account-dialog label{display:grid;gap:6px;color:#e9eef2;font-size:12px;font-weight:700}.thi-account-dialog input{width:100%;box-sizing:border-box;padding:12px;border:1px solid #465562;border-radius:8px;background:#0b1117;color:#fff;font:inherit}
    .thi-account-actions{display:flex;gap:9px;margin-top:14px}.thi-account-primary,.thi-account-secondary{border-radius:8px;padding:11px 14px;font:700 12px var(--mono,monospace);cursor:pointer}.thi-account-primary{border:0;background:#e0c45a;color:#14110a}.thi-account-secondary{border:1px solid #465562;background:transparent;color:#e7edf2}.thi-account-status{min-height:20px;margin-top:10px!important;color:#d8c66c!important}
    @media(max-width:800px){.thi-account-button{padding:7px 9px;font-size:9px}}
  `;
  document.head.appendChild(style);

  let client = null;
  let currentUser = null;
  let resolveReady;
  const ready = new Promise(resolve => { resolveReady = resolve; });

  function ensureButton() {
    const header = document.querySelector(".header-inner");
    if (!header || document.getElementById("thi-account-button")) return;
    const button = document.createElement("button");
    button.id = "thi-account-button";
    button.type = "button";
    button.className = "thi-account-button";
    button.textContent = currentUser ? "Account" : "Free account";
    button.addEventListener("click", open);
    header.appendChild(button);
  }

  function updateButton() {
    ensureButton();
    const button = document.getElementById("thi-account-button");
    if (button) button.textContent = currentUser ? "Account" : "Free account";
  }

  function close() { document.getElementById("thi-account-overlay")?.remove(); }

  async function open() {
    await ready;
    close();
    const overlay = document.createElement("div");
    overlay.id = "thi-account-overlay";
    overlay.className = "thi-account-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML = `<div class="thi-account-dialog">
      <div style="font:700 10px var(--mono,monospace);letter-spacing:.12em;text-transform:uppercase;color:#d8c66c">The Hammer Index</div>
      <h2>${currentUser ? "Your account" : "Create a free account"}</h2>
      ${currentUser ? `<p>Signed in as <strong>${escapeHtml(currentUser.email || "THI member")}</strong>. Your logged plays and private notes stay connected to this account.</p><div class="thi-account-actions"><button class="thi-account-primary" data-account-market>Open Market Research</button><button class="thi-account-secondary" data-account-signout>Sign out</button><button class="thi-account-secondary" data-account-close>Close</button></div>` : `<p>Use a secure email link to sign in. Your session is saved on this device, and your Market Research plays and notes remain private.</p><form data-account-form><label>Email address<input name="email" type="email" autocomplete="email" required placeholder="you@example.com"></label><div class="thi-account-actions"><button class="thi-account-primary" type="submit">Email my sign-in link</button><button class="thi-account-secondary" type="button" data-account-close>Continue exploring</button></div><p class="thi-account-status" role="status"></p></form>`}
    </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", event => { if (event.target === overlay || event.target.closest("[data-account-close]")) close(); });
    overlay.querySelector("[data-account-signout]")?.addEventListener("click", async () => { await client.auth.signOut(); close(); });
    overlay.querySelector("[data-account-market]")?.addEventListener("click", () => { close(); window.switchView?.("research"); });
    overlay.querySelector("form")?.addEventListener("submit", async event => {
      event.preventDefault();
      const email = new FormData(event.currentTarget).get("email");
      const status = overlay.querySelector(".thi-account-status");
      status.textContent = "Sending secure link…";
      const { error } = await client.auth.signInWithOtp({email, options:{emailRedirectTo:location.origin + location.pathname, data:{signup_source:"global_account_prompt"}}});
      status.textContent = error ? error.message : "Check your email. The sign-in link will return you to THI.";
    });
  }

  function escapeHtml(value) { return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch])); }

  async function initialize() {
    client = window.THI_SUPABASE_CLIENT || window.supabase.createClient(config.url, config.publishableKey, {auth:{persistSession:true,autoRefreshToken:true,detectSessionInUrl:true}});
    window.THI_SUPABASE_CLIENT = client;
    const { data } = await client.auth.getUser();
    currentUser = data?.user || null;
    client.auth.onAuthStateChange((_event, session) => { currentUser = session?.user || null; updateButton(); document.dispatchEvent(new CustomEvent("thi:auth-change", {detail:{user:currentUser}})); });
    updateButton();
    resolveReady(client);
  }

  window.THIAccount = { ready, open, close, getClient: () => client, getUser: () => currentUser };
  ensureButton();
  if (window.supabase?.createClient) initialize();
  else {
    const library = document.createElement("script");
    library.src = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2";
    library.onload = initialize;
    library.onerror = () => resolveReady(null);
    document.head.appendChild(library);
  }
})();
