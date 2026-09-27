/* MarketPulse Trade desk — the screen for the Alpaca agent.
 *
 * It only exists on the buyer's own computer: the tab stays hidden unless the
 * local server answers /api/desk/ping, which the hosted site never does.
 * Every other call carries the desk token in X-MP-Desk. The token arrives
 * once, in the #desk= fragment of the link the launcher opens (a fragment is
 * never sent to a server), and is kept in this browser's localStorage. It is
 * deliberately not in the backup/export list.
 *
 * Keys are write-only from here: the secret goes to the local server once and
 * is never shown again, never stored in the browser, never in a URL.
 * Everything is rendered with textContent — proposal reasons come from market
 * data and must never be parsed as HTML.
 */
(function () {
  const POLL_MS = 20000;
  const LS_TOKEN = "mp_desk_token";
  const TOKEN_RE = /^[A-Za-z0-9_-]{40,}$/;
  let token = null;
  let locked = false;
  let state = null;
  let timer = null;
  let busy = false;
  let showKeyForm = false;
  let flash = { text: "", bad: false };

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function money(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString(undefined, { style: "currency", currency: "USD" }) : "—";
  }
  function ago(ts) {
    if (!ts) return "never";
    const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)}m ago` : `${Math.round(s / 3600)}h ago`;
  }

  function saveToken(t) {
    token = t && TOKEN_RE.test(t) ? t : null;
    try {
      if (token) localStorage.setItem(LS_TOKEN, token); else localStorage.removeItem(LS_TOKEN);
    } catch (e) { /* storage blocked: the token lives until the tab closes */ }
    locked = !token;
    return !!token;
  }

  // Take the token from #desk=... once, then wipe it from the address bar.
  function adoptFragment() {
    const m = /(?:^#|&)desk=([A-Za-z0-9_-]{40,})/.exec(location.hash || "");
    if (m) {
      saveToken(m[1]);
      history.replaceState(null, "", location.pathname + location.search);
      return;
    }
    try { saveToken(localStorage.getItem(LS_TOKEN)); } catch (e) { saveToken(null); }
  }

  async function ping() {
    try {
      const r = await fetch("/api/desk/ping", { cache: "no-store" });
      return r.ok;
    } catch (e) {
      return false;
    }
  }

  async function api(method, path, body) {
    const opts = { method, cache: "no-store", headers: { "X-MP-Desk": token || "" } };
    if (method === "POST") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    let r;
    try {
      r = await fetch(path, opts);
    } catch (e) {
      return { ok: false, message: "The app's local server isn't answering. Is MarketPulse still running?" };
    }
    if (r.status === 401) {
      saveToken(null);
      return { ok: false, unlock: true, message: "" };
    }
    try {
      return Object.assign({ httpStatus: r.status }, await r.json());
    } catch (e) {
      return { ok: false, message: "The desk sent an unreadable reply." };
    }
  }

  async function refresh() {
    if (locked) { render(); return; }
    const s = await api("GET", "/api/desk/state");
    if (s && s.ok) state = s;
    else if (!s.unlock) flash = { text: (s && s.message) || "Couldn't load the desk.", bad: true };
    render();
  }

  async function act(path, body, confirmText) {
    if (busy) return;
    if (confirmText && !window.confirm(confirmText)) return;
    busy = true;
    render();
    const r = await api("POST", path, body);
    busy = false;
    flash = { text: r.message || (r.ok ? "Done." : "That didn't work."), bad: r.ok === false && r.status !== "submitted" };
    if (r.status === "submitted" && r.order_id) flash.text += ` Order ${r.order_id}.`;
    await refresh();
  }

  // ------------------------------------------------------------------ pieces
  function header(s) {
    const h = el("div", "desk-head");
    h.append(el("h2", "panel-title", "Trade desk"));
    const badge = el("span", "desk-mode " + (s.mode === "live" ? "is-live" : "is-paper"),
      s.mode === "live" ? "LIVE · real money" : "PAPER · practice money");
    h.append(badge);
    const loop = s.loop || {};
    const every = loop.every_min ? `Scans every ${loop.every_min} min · last ${ago(loop.last)}` : "Background scan off";
    h.append(el("span", "desk-loop", every));
    return h;
  }

  function alerts(s) {
    const box = el("div", "desk-alerts");
    if (s.halted) {
      const a = el("div", "desk-alert bad");
      a.append(el("b", null, "Kill switch is ON. Nothing will be sent. "), el("span", null, s.halt_reason || ""));
      const b = el("button", "ltc-tool", "Release kill switch");
      b.type = "button";
      b.onclick = () => act("/api/desk/resume", {}, "Release the kill switch? Approved orders will be able to send again.");
      a.append(b);
      box.append(a);
    }
    if (s.error) box.append(el("div", "desk-alert bad", s.error));
    if (s.connected && s.connected.overrides_saved_file) {
      box.append(el("div", "desk-alert warn",
        "Keys from environment variables are overriding the keys saved here. Unset MP_ALPACA_KEY_ID / MP_ALPACA_SECRET to use these."));
    }
    if (s.mode === "live") {
      box.append(el("div", "desk-alert " + (s.live.permitted ? "warn" : "bad"),
        s.live.permitted ? `Real money is ON (${s.live.why}). Every order is capped at ${money(s.caps.per_trade)}, ${money(s.caps.daily)} a day.`
          : s.live.why));
    }
    if (flash.text) box.append(el("div", "desk-alert " + (flash.bad ? "bad" : "ok"), flash.text));
    return box;
  }

  function stats(s) {
    const row = el("div", "pot-stats desk-stats");
    const stat = (label, val, sub, cls) => {
      const d = el("div", "stat");
      d.append(el("div", "label", label), el("div", "val" + (cls ? " " + cls : ""), val));
      if (sub) d.append(el("div", "sub", sub));
      row.append(d);
    };
    const a = s.account || {};
    const change = Number(a.equity) - Number(a.last_equity);
    stat("Equity", s.account ? money(a.equity) : "—",
      s.account && Number.isFinite(change) ? `${change >= 0 ? "+" : ""}${money(change)} today` : "",
      Number.isFinite(change) && change !== 0 ? (change > 0 ? "pos" : "neg") : "");
    stat("Buying power", s.account ? money(a.buying_power) : "—");
    stat("Spent (24h)", s.spent_24h == null ? "?" : money(s.spent_24h), `cap ${money(s.caps.daily)} a day`);
    stat("Per trade", money(s.caps.per_trade), s.mode === "live" ? "live ceiling" : "paper size limit");
    return row;
  }

  function controls(s) {
    const bar = el("div", "paper-actions desk-controls");
    const scan = el("button", "ltc-tool", busy ? "Working…" : "Scan now");
    scan.type = "button";
    scan.disabled = busy || !s.connected.connected;
    scan.onclick = () => act("/api/desk/scan", {});
    bar.append(scan);

    const lab = el("label", "desk-toggle");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !!(s.settings && s.settings.auto_exits);
    box.disabled = busy;
    box.onchange = () => act("/api/desk/auto", { on: box.checked },
      box.checked ? "Turn on auto-exits? The desk will CLOSE a position by itself when your exit rule fires. It never buys on its own." : null);
    lab.append(box, el("span", null, " Auto-exits (closes positions by itself; never buys)"));
    bar.append(lab);

    if (!s.halted) {
      const kill = el("button", "ltc-tool desk-kill", "Kill switch");
      kill.type = "button";
      kill.onclick = () => act("/api/desk/halt", { reason: "kill switch from the Trade desk" },
        "Engage the kill switch? Nothing will be sent until you release it.");
      bar.append(kill);
    }
    return bar;
  }

  function proposalRow(p, s) {
    const row = el("div", "paper-row desk-prop " + (p.side === "buy" ? "is-buy" : "is-sell"));
    row.append(el("b", null, p.side.toUpperCase()), el("span", "desk-sym", p.symbol));
    row.append(el("span", null, p.side === "buy" ? money(p.notional) : "close position"));
    if (p.label) row.append(el("span", "desk-label", `${p.label}${p.score != null ? " · " + p.score : ""}`));
    const left = Math.round(((p.ts || 0) + (s.ttl_s || 1800) - Date.now() / 1000) / 60);
    row.append(el("span", "muted", left > 0 ? `expires in ${left}m` : "expiring"));
    const approve = el("button", "ltc-tool desk-approve", "Approve");
    approve.type = "button";
    approve.disabled = busy || s.halted;
    const what = p.side === "buy" ? `BUY ${money(p.notional)} of ${p.symbol}` : `SELL (close) ${p.symbol}`;
    approve.onclick = () => act("/api/desk/approve", { id: p.id },
      s.mode === "live" ? `REAL MONEY: ${what}? This sends a live order to Alpaca.` : null);
    const reject = el("button", "ltc-tool ghost", "Reject");
    reject.type = "button";
    reject.disabled = busy;
    reject.onclick = () => act("/api/desk/reject", { id: p.id });
    row.append(approve, reject);
    if (p.reasons && p.reasons.length) row.append(el("div", "desk-why", "why: " + p.reasons.join(" · ")));
    if (p.note) row.append(el("div", "desk-why", p.note));
    return row;
  }

  function recentRow(p) {
    const cls = p.status === "submitted" ? "win" : p.status === "blocked" ? "loss" : "";
    const row = el("div", "paper-row " + cls);
    row.append(el("b", null, p.side.toUpperCase()), el("span", "desk-sym", p.symbol));
    const f = p.fill || {};
    let what = p.status;
    if (p.status === "submitted") {
      what = f.status === "filled" ? `filled ${f.qty} @ ${money(f.avg_price)}` : `sent${f.status ? " · " + f.status : ""}`;
      if (p.mode === "live") what += " · LIVE";
      if (p.auto) what += " · auto";
    }
    row.append(el("span", null, what));
    row.append(el("span", "muted", ago(p.ts)));
    if (p.status === "blocked" && p.note) row.append(el("div", "desk-why", p.note));
    return row;
  }

  function positionsBlock(s) {
    const wrap = el("div");
    wrap.append(el("h3", "paper-h3", "Open positions"));
    if (!s.positions.length) wrap.append(el("div", "hc-empty", "No open positions."));
    for (const p of s.positions) {
      const pl = Number(p.unrealized_pl);
      const row = el("div", "paper-row " + (pl > 0 ? "win" : pl < 0 ? "loss" : ""));
      row.append(el("b", null, p.symbol), el("span", null, `${p.qty} @ ${money(p.avg_entry_price)}`),
        el("span", null, `worth ${money(p.market_value)}`),
        el("span", "muted", `${pl >= 0 ? "+" : ""}${money(pl)}`));
      wrap.append(row);
    }
    return wrap;
  }

  function reportBlock(s) {
    const r = s.report || {};
    const wrap = el("div", "desk-report");
    wrap.append(el("h3", "paper-h3", "Last 7 days"));
    const modes = Object.keys(r.modes || {});
    if (!modes.length) {
      wrap.append(el("div", "hc-empty", `${r.proposed || 0} proposals, nothing sent yet.`));
      return wrap;
    }
    for (const m of modes.sort()) {
      const x = r.modes[m];
      const pl = (r.exit_pl_usd || {})[m];
      wrap.append(el("div", "paper-row",
        `${m.toUpperCase()}: ${x.buys} buys (${money(x.bought_usd)}), ${x.sells} sells` +
        `${x.auto_sells ? ` (${x.auto_sells} auto)` : ""}, ${x.filled} filled` +
        (pl != null ? ` · P/L at exit ${pl >= 0 ? "+" : ""}${money(pl)}` : "")));
    }
    const bs = r.by_status || {};
    wrap.append(el("div", "desk-why", Object.keys(bs).map((k) => `${k} ${bs[k]}`).join(" · ")));
    return wrap;
  }

  function keysBlock(s) {
    const card = el("div", "home-card desk-keys");
    card.append(el("div", "hc-head", "Alpaca connection"));
    const c = s.connected || {};
    if (c.connected && !showKeyForm) {
      card.append(el("p", "lic-note",
        `Connected · ${c.mode.toUpperCase()} · key …${c.key_id_last4}${c.source === "env" ? " (from environment)" : ""}`));
      const row = el("div", "lic-row");
      const replace = el("button", "ltc-tool", "Replace keys");
      replace.type = "button";
      replace.onclick = () => { showKeyForm = true; render(); };
      const off = el("button", "ltc-tool ghost", "Disconnect");
      off.type = "button";
      off.onclick = () => act("/api/desk/disconnect", {}, "Disconnect Alpaca? The keys are deleted from this computer.");
      row.append(replace, off);
      card.append(row);
      return card;
    }
    card.append(el("p", "lic-note",
      "Paste the API keys from your Alpaca dashboard. They are checked with Alpaca, then saved only on this computer. Start with PAPER keys."));
    const form = el("form", "desk-form");
    form.autocomplete = "off";
    const keyIn = document.createElement("input");
    keyIn.className = "lic-key"; keyIn.placeholder = "API key ID"; keyIn.required = true;
    keyIn.autocomplete = "off"; keyIn.spellcheck = false;
    const secIn = document.createElement("input");
    secIn.className = "lic-key"; secIn.type = "password"; secIn.placeholder = "Secret key"; secIn.required = true;
    secIn.autocomplete = "new-password";
    const modes = el("div", "desk-modes");
    let mode = "paper";
    for (const m of ["paper", "live"]) {
      const lab = el("label", "desk-toggle");
      const r = document.createElement("input");
      r.type = "radio"; r.name = "deskMode"; r.value = m; r.checked = m === "paper";
      r.onchange = () => { mode = m; };
      lab.append(r, el("span", null, m === "paper" ? " Paper (practice)" : " Live (real money)"));
      modes.append(lab);
    }
    const go = el("button", "ltc-tool", "Check & save");
    go.type = "submit";
    form.append(keyIn, secIn, modes, go);
    if (c.connected) {
      const cancel = el("button", "ltc-tool ghost", "Cancel");
      cancel.type = "button";
      cancel.onclick = () => { showKeyForm = false; render(); };
      form.append(cancel);
    }
    form.onsubmit = async (e) => {
      e.preventDefault();
      const body = { key_id: keyIn.value.trim(), secret: secIn.value.trim(), mode };
      secIn.value = "";
      await act("/api/desk/keys", body,
        mode === "live" ? "Save LIVE keys? Real-money orders still need the owner pilot or MarketPulse Pro, and stay capped at $25 a trade / $100 a day." : null);
      if (state && state.connected && state.connected.connected) showKeyForm = false;
      render();
    };
    card.append(form);
    return card;
  }

  function unlockCard() {
    const card = el("div", "home-card desk-keys");
    card.append(el("div", "hc-head", "Unlock the Trade desk"));
    card.append(el("p", "lic-note",
      "Start MarketPulse with run.bat (Windows) or run.sh (Mac/Linux): it opens this page with the desk unlocked. " +
      "Opened some other way? Copy the \"Trade desk\" link printed in the MarketPulse window and paste it here."));
    const form = el("form", "desk-form");
    const input = document.createElement("input");
    input.className = "lic-key"; input.placeholder = "http://127.0.0.1:8000/app#desk=..."; input.required = true;
    input.autocomplete = "off"; input.spellcheck = false;
    const go = el("button", "ltc-tool", "Unlock");
    go.type = "submit";
    form.append(input, go);
    form.onsubmit = (e) => {
      e.preventDefault();
      const m = /desk=([A-Za-z0-9_-]{40,})/.exec(input.value) || /^([A-Za-z0-9_-]{40,})$/.exec(input.value.trim());
      input.value = "";
      if (!m || !saveToken(m[1])) {
        flash = { text: "That isn't a Trade desk link.", bad: true };
        render();
        return;
      }
      flash = { text: "", bad: false };
      refresh();
    };
    card.append(form);
    if (flash.text) card.append(el("div", "desk-alert " + (flash.bad ? "bad" : "ok"), flash.text));
    return card;
  }

  function render() {
    const panel = document.getElementById("tradePanel");
    if (!panel || panel.hidden) return;
    panel.replaceChildren();
    if (locked) {
      panel.append(el("h2", "panel-title", "Trade desk"), unlockCard());
      return;
    }
    if (!state) {
      panel.append(el("div", "hc-empty", "Loading the desk…"));
      return;
    }
    const s = state;
    panel.append(header(s), alerts(s));
    panel.append(el("p", "panel-sub",
      "The agent proposes; you approve. Every order passes the kill switch, market hours, a fresh-price slippage check and the spend caps before it reaches Alpaca."));
    if (s.connected.connected) {
      panel.append(stats(s), controls(s));
      panel.append(el("h3", "paper-h3", `Waiting for you (${s.pending.length})`));
      if (!s.pending.length) panel.append(el("div", "hc-empty", "No proposals right now. The desk scans on its own, or press Scan now."));
      for (const p of s.pending) panel.append(proposalRow(p, s));
      panel.append(positionsBlock(s));
      panel.append(el("h3", "paper-h3", "Recent"));
      if (!s.recent.length) panel.append(el("div", "hc-empty", "Nothing yet."));
      for (const p of s.recent) panel.append(recentRow(p));
      panel.append(reportBlock(s));
    }
    panel.append(keysBlock(s));
  }

  // A refresh rebuilds the panel, which would wipe keys someone is typing.
  function typing() {
    const inputs = document.querySelectorAll("#tradePanel .desk-form input.lic-key");  // key or unlock form
    return Array.prototype.some.call(inputs, (i) => i.value);
  }

  function stop() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  window.mpDeskShow = function () {
    flash = { text: "", bad: false };
    render();
    refresh();
    stop();
    timer = setInterval(() => { if (!document.hidden && !busy && !typing()) refresh(); }, POLL_MS);
  };
  window.mpDeskHide = stop;

  // The tab appears only where a local desk answers (never on the hosted site).
  adoptFragment();
  ping().then((ok) => {
    const tab = document.querySelector('.tab[data-view="trade"]');
    if (ok && tab) tab.hidden = false;
  });
})();
