/* MarketPulse Pro license.
 *
 * Paste the key from the Gumroad receipt once: the server consumes one device
 * seat and returns a signed token for THIS device. Key + token + device id then
 * ride in headers on Pro-only calls (window.mpLicenseHeaders), never in a URL.
 *
 * The card stays hidden until the server reports licensing switched on, so no
 * one sees a license box before there is anything to buy. mp_license and
 * mp_device are deliberately NOT in the backup/export list: restoring them on
 * another phone would clone this device's seat.
 */
(function () {
  const LS_LICENSE = "mp_license";
  const LS_DEVICE = "mp_device";
  // The Classes pass is its own key: a Pro buyer adds it without replacing Pro.
  // Like mp_license it stays out of backups (restoring it would clone a seat).
  const LS_CLASSES = "mp_license_classes";
  const TIER_NAME = { pro: "Pro", proplus: "Pro+", classes: "Classes pass" };

  function read(k) {
    try { return JSON.parse(localStorage.getItem(k) || "null"); } catch (e) { return null; }
  }
  function write(k, v) {
    try {
      if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v));
    } catch (e) { /* storage blocked (private mode): the device simply stays unlicensed */ }
  }
  function deviceId() {
    let d = read(LS_DEVICE);
    if (!d) {
      const raw = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
        : Date.now().toString(36) + Math.random().toString(36).slice(2);
      d = raw.replace(/[^A-Za-z0-9_-]/g, "");
      write(LS_DEVICE, d);
    }
    return d;
  }
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(body) });
    let j = {};
    try { j = await r.json(); } catch (e) { j = { message: "The server sent an unreadable reply." }; }
    return Object.assign({ status: r.status }, j);
  }

  /* Headers for a license-gated request. scope "classes" prefers the Classes pass and
   * falls back to the main key (Pro+ includes classes). Empty when unlicensed. */
  window.mpLicenseHeaders = function (scope) {
    const l = (scope === "classes" && read(LS_CLASSES)) || read(LS_LICENSE);
    return l ? { "X-MP-License-Key": l.key, "X-MP-License-Token": l.token, "X-MP-Device": deviceId() } : {};
  };

  /* Activate a key on this device and file it by tier. Returns the server's answer. */
  async function activate(key) {
    const r = await post("/api/license/activate", { key, device: deviceId() });
    if (r.ok) write(r.tier === "classes" ? LS_CLASSES : LS_LICENSE,
                    { key, token: r.token, tier: r.tier, billing: r.billing });
    return r;
  }
  window.mpLicenseActivate = activate;
  window.mpClassesPass = function () { return read(LS_CLASSES); };
  /* Release the Classes pass seat on this device. */
  window.mpClassesRelease = async function () {
    const l = read(LS_CLASSES);
    if (!l) return { ok: true };                    // nothing stored on this device
    const r = await post("/api/license/deactivate", { key: l.key, token: l.token, device: deviceId() });
    if (r.ok) write(LS_CLASSES, null);
    return r;
  };
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function renderForm(card, message) {
    card.replaceChildren();
    card.append(el("div", "hc-head", "MarketPulse Pro"));
    card.append(el("p", "lic-note", "Paste the license key from your Gumroad receipt. It activates this device."));
    const row = el("form", "lic-row");
    const input = el("input", "add-input lic-key");
    Object.assign(input, { type: "text", placeholder: "XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX",
                           autocomplete: "off", spellcheck: false, maxLength: 64 });
    input.setAttribute("aria-label", "License key");
    const btn = el("button", "add-btn", "Activate");
    btn.type = "submit";
    row.append(input, btn);
    card.append(row);
    const msg = el("p", "lic-msg", message || "");
    card.append(msg);
    row.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const key = input.value.trim();
      if (!key) return;
      btn.disabled = true;
      msg.textContent = "Checking with Gumroad…";
      try {
        const r = await activate(key);
        if (r.ok && r.tier === "classes") {
          const note = "Classes pass activated on this device. Find your lessons on the Classes tab.";
          const main = read(LS_LICENSE);         // a Pro license here keeps its own card and controls
          if (main) { renderActive(card, main); card.append(el("p", "lic-msg", note)); return; }
          return renderForm(card, note);
        }
        if (r.ok) return renderActive(card, { tier: r.tier, billing: r.billing });
        msg.textContent = r.message || "That key could not be activated.";
      } catch (e) {
        msg.textContent = "Could not reach MarketPulse. Check your connection and try again.";
      } finally {
        btn.disabled = false;
      }
    });
  }

  function renderActive(card, state) {
    card.replaceChildren();
    card.append(el("div", "hc-head", "MarketPulse Pro"));
    const line = el("p", "lic-active");
    line.append(el("b", null, (TIER_NAME[state.tier] || "Pro") + " active"));
    line.append(document.createTextNode(" · " + (state.billing === "monthly" ? "monthly" : "lifetime")
                                         + " · this device"));
    card.append(line);
    const msg = el("p", "lic-msg", "");
    const off = el("button", "add-btn ghost", "Deactivate this device");
    off.type = "button";
    off.addEventListener("click", async () => {
      const l = read(LS_LICENSE) || {};
      off.disabled = true;
      try {
        const r = await post("/api/license/deactivate", { key: l.key, token: l.token, device: deviceId() });
        if (r.ok) { write(LS_LICENSE, null); return renderForm(card, "Seat released on this device."); }
        msg.textContent = r.message || "Could not release the seat.";
      } catch (e) {
        msg.textContent = "Could not reach MarketPulse. Try again.";
      } finally {
        off.disabled = false;
      }
    });
    card.append(off, msg);
  }

  async function init() {
    const card = document.getElementById("licenseCard");
    if (!card) return;
    let info;
    try { info = await (await fetch("/api/license")).json(); } catch (e) { return; }
    if (!info || !info.enabled) return;          // licensing not switched on: stay hidden
    card.hidden = false;
    const l = read(LS_LICENSE);
    if (!l) return renderForm(card);
    try {
      const s = await post("/api/license/status", { key: l.key, token: l.token, device: deviceId() });
      if (s.active) return renderActive(card, s);
      // Gumroad could not be reached: that is not a "no". Keep the license.
      if (s.unreachable) return renderActive(card, l);
      write(LS_LICENSE, null);
      renderForm(card, s.reason || "This license is no longer active on this device.");
    } catch (e) {
      renderActive(card, l);                       // offline: show the last known state
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
