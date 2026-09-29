"""The Trade desk's HTTP API: the browser's only way into the money core.

It exists on the buyer's own computer and nowhere else. Every request must
pass all of these, in order:

  1. Local only. Refused (404) when the server is bound to anything but
     loopback, or runs on Render. The hosted site can never place an order.
  2. Host header is 127.0.0.1 / localhost / [::1] with THIS server's port.
     That stops DNS rebinding: evil.example re-pointed at 127.0.0.1 still
     sends "Host: evil.example".
  3. Browser fetch metadata. Sec-Fetch-Site, when sent, is same-origin (or
     "none" for a GET typed into the address bar); a POST must carry an
     Origin equal to http://<Host>. Cross-site forms and fetches are refused.
  4. The desk token in the X-MP-Desk header on every call but /ping. It lives
     in an owner-only file (agent/data/desk_token) and reaches the browser only
     through the launcher: app.py opens an owner-only local page that forwards
     to /app#desk=<token>. A fragment never reaches a server or a log. There
     is deliberately NO endpoint that hands the token out: any local program,
     or another user on this computer, could fake a browser's headers to ask.
     The custom header also forces a CORS preflight, which this server never
     grants (there is no OPTIONS handler).

Keys are write-only: the browser can hand them over, never read them back.
All money decisions stay in agent/desk.py and agent/guardrails.py; this file
only checks who is asking and translates HTTP to those calls.
"""
from __future__ import annotations

import hmac
import json
import os
import pathlib
import re
import secrets
import sys
import threading
import time

import agent_config as config
import broker
import credentials
import desk
import licensing
import pilot
import store

LOOPBACK_BIND = ("127.0.0.1", "::1", "localhost")
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
TOKEN_HEADER = "X-MP-Desk"
TOKEN_FILE = "desk_token"
OPEN_PAGE = "open_desk.html"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,}$")
_TOKEN_CACHE: dict = {}
_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
GRANT_S = 3600                               # a verified Pro license covers the loop for an hour
_GRANT = {"until": 0.0}
_LOOP = {"every_min": 0, "last": None, "last_result": None, "thread": None}

LIVE_NEEDS = ("Real money needs MarketPulse Pro (or the owner's pilot). "
              "Paper trading is always available.")


# ------------------------------------------------------------------ the token
def _owner_only_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    credentials._lock_to_this_user(tmp)      # Windows ignores 0600; icacls instead
    os.replace(tmp, path)


def session_token() -> str:
    """The desk token: made once, kept in an owner-only file, so a bookmark
    keeps working across restarts while other users on this PC can't read it."""
    cached = _TOKEN_CACHE.get(config.DATA_DIR)
    if cached:
        return cached
    path = os.path.join(config.DATA_DIR, TOKEN_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            token = fh.read().strip()
    except OSError:
        token = ""
    if not _TOKEN_RE.match(token):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        token = secrets.token_urlsafe(32)
        _owner_only_write(path, token)
    _TOKEN_CACHE[config.DATA_DIR] = token
    return token


def desk_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/app#desk={session_token()}"


def open_page(host: str, port: int) -> str:
    """An owner-only local page that forwards the browser to the desk URL, so
    the token never appears on a command line (which other users can read on
    some systems). Returns its file:// URL for webbrowser.open."""
    target = json.dumps(desk_url(host, port))
    path = os.path.join(config.DATA_DIR, OPEN_PAGE)
    _owner_only_write(path, "<!doctype html><meta charset=utf-8><title>MarketPulse</title>"
                            f"<script>location.replace({target});</script>")
    return pathlib.Path(path).resolve().as_uri()


# ------------------------------------------------------------------ who may ask
def enabled(server_address) -> bool:
    if os.environ.get("RENDER"):
        return False
    return bool(server_address) and server_address[0] in LOOPBACK_BIND


def _host_ok(host: str, port: int) -> bool:
    host = (host or "").strip().lower()
    allowed = {f"{name}:{port}" for name in LOOPBACK_NAMES}
    if port == 80:
        allowed |= set(LOOPBACK_NAMES)
    return host in allowed


def _refusal(method: str, path: str, headers, port: int) -> tuple[int, dict] | None:
    host = headers.get("Host") or ""
    if not _host_ok(host, port):
        return 403, {"ok": False, "message": "The Trade desk only answers on this computer."}
    site = headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        return 403, {"ok": False, "message": "Cross-site request refused."}
    origin = headers.get("Origin")
    expected = f"http://{host.strip().lower()}"
    if method == "POST" and (origin or "").lower() != expected:
        return 403, {"ok": False, "message": "Cross-site request refused."}
    if origin is not None and origin.lower() != expected:
        return 403, {"ok": False, "message": "Cross-site request refused."}
    if path != "/api/desk/ping":
        sent = headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(sent.encode(), session_token().encode()):
            return 401, {"ok": False, "message": "Reload the app to reconnect the Trade desk."}
    return None


# ------------------------------------------------------------------ live permission
def live_permission(headers, license_check, now: float | None = None) -> tuple[bool, str]:
    """The owner's pilot, or a verified Pro / Pro+ license on this request."""
    now = time.time() if now is None else now
    if pilot.active(now):
        return True, f"Owner pilot, ends {pilot.status(now)['ends']} UTC"
    ent = None
    if license_check is not None:
        try:
            ent = license_check(headers)
        except Exception as exc:  # noqa: BLE001 — a licensing hiccup means "not proven", never "allowed"
            print(f"[desk] license check failed: {type(exc).__name__}", file=sys.stderr)
    # By name, never "any active license": a Classes pass must not unlock live trading.
    if ent is not None and licensing.grants_pro(ent):
        _GRANT["until"] = now + GRANT_S
        return True, "MarketPulse Pro"
    return False, LIVE_NEEDS


def loop_live_permitted(now: float | None = None) -> bool:
    """The background loop has no request to read a license from, so it uses
    the pilot, or a license verified on a desk request within the last hour."""
    now = time.time() if now is None else now
    return pilot.active(now) or now < _GRANT["until"]


# ------------------------------------------------------------------ views
_PROPOSAL_FIELDS = ("id", "ts", "kind", "symbol", "side", "notional", "ref_price", "label",
                    "score", "status", "note", "broker_order_id", "mode", "auto", "fill")


def _view(p: dict) -> dict:
    out = {k: p.get(k) for k in _PROPOSAL_FIELDS}
    out["reasons"] = [str(r) for r in (p.get("reasons") or [])][:5]
    return out


def _state(headers, license_check) -> dict:
    creds = credentials.load()
    mode = creds.mode if creds else "paper"
    single, daily = config.caps(mode)
    permitted, why = live_permission(headers, license_check)
    live_bits, broker_error = _broker_view(creds)     # also settles fills, so the list below is current
    proposals = store.load_proposals()
    out = {
        "ok": True,
        "connected": credentials.masked(creds),
        "mode": mode,
        "caps": {"per_trade": str(single), "daily": str(daily)},
        "ttl_s": config.PROPOSAL_TTL,
        "halted": store.is_halted(),
        "halt_reason": store.load_circuit().get("reason") or "",
        "live": {"permitted": permitted, "why": why},
        "pilot": pilot.status(),
        "settings": desk.settings(),
        "loop": {**{k: _LOOP[k] for k in ("every_min", "last", "last_result")},
                 "heartbeat": desk.last_tick()},    # the app loop OR the scheduled task
        "pending": [_view(p) for p in proposals if p.get("status") == "pending"],
        "recent": [_view(p) for p in proposals if p.get("status") != "pending"][-15:][::-1],
        "report": desk.report(7),
        **live_bits, "error": broker_error,
    }
    try:
        out["spent_24h"] = store.spend_last_24h(mode)
    except store.LedgerError as exc:
        out["spent_24h"], out["error"] = None, str(exc)
    return out


def _broker_view(creds) -> tuple[dict, str | None]:
    bits = {"account": None, "positions": [], "clock": None}
    if creds is None:
        return bits, None
    try:
        a = broker.account()
        bits["account"] = {k: a.get(k) for k in ("status", "equity", "last_equity", "cash", "buying_power")}
        bits["positions"] = [{k: p.get(k) for k in ("symbol", "qty", "market_value", "avg_entry_price",
                                                      "unrealized_pl", "unrealized_plpc")}
                             for p in broker.positions()]
        c = broker.clock()
        bits["clock"] = {k: c.get(k) for k in ("is_open", "next_open", "next_close")}
        desk.refresh_fills(limit=5)
    except broker.AuthError:
        return bits, "Alpaca did not accept the saved keys. Reconnect them below."
    except broker.BrokerError:
        return bits, "Couldn't reach Alpaca just now. Trading is paused until it answers."
    return bits, None


# ------------------------------------------------------------------ actions
def _save_keys(body: dict) -> tuple[int, dict]:
    fields = [body.get(k) for k in ("key_id", "secret", "mode")]
    if not all(isinstance(v, str) for v in fields):
        return 400, {"ok": False, "message": "key_id, secret and mode are required."}
    key_id, secret, mode = (v.strip() for v in fields)
    try:
        creds = credentials.Credentials(key_id, secret, mode)
    except ValueError as exc:
        return 400, {"ok": False, "message": str(exc)}
    try:
        broker.verify(creds)
    except broker.AuthError:
        return 400, {"ok": False, "message": f"Alpaca didn't accept these as {mode.upper()} keys. "
                                              "Paper keys only work in paper mode, live keys only in live."}
    except broker.BrokerError:
        return 502, {"ok": False, "message": "Couldn't reach Alpaca to check the keys. Try again."}
    credentials.save(creds)
    store.audit("keys_saved", {"mode": mode, "key_id_last4": key_id[-4:]})
    return 200, {"ok": True, "connected": credentials.masked(credentials.load())}


def _pid(body: dict) -> str | None:
    pid = body.get("id")
    return pid if isinstance(pid, str) and _ID.match(pid) else None


def _post(path: str, body: dict, headers, license_check) -> tuple[int, dict]:
    if path == "/api/desk/keys":
        return _save_keys(body)
    if path == "/api/desk/disconnect":
        credentials.clear()
        store.audit("keys_cleared", {})
        return 200, {"ok": True, "message": "Disconnected. The keys were deleted from this computer."}
    if path in ("/api/desk/approve", "/api/desk/reject"):
        pid = _pid(body)
        if pid is None:
            return 400, {"ok": False, "message": "Which proposal? (missing or malformed id)"}
        if path.endswith("reject"):
            return 200, desk.reject(pid)
        permitted, _ = live_permission(headers, license_check)
        return 200, desk.approve(pid, live_permitted=permitted)
    if path == "/api/desk/scan":
        import proposer
        new = proposer.scan()
        return 200, {"ok": True, "new": len(new),
                     "message": f"{len(new)} new proposal(s)." if new else "Nothing new right now."}
    if path == "/api/desk/halt":
        reason = body.get("reason") if isinstance(body.get("reason"), str) else ""
        store.engage_halt((reason.strip() or "kill switch from the Trade desk")[:200])
        return 200, {"ok": True, "message": "Kill switch ON. Nothing will be sent."}
    if path == "/api/desk/resume":
        store.release_halt()
        return 200, {"ok": True, "message": "Kill switch released."}
    if path == "/api/desk/auto":
        if not isinstance(body.get("on"), bool):
            return 400, {"ok": False, "message": "on must be true or false"}
        return 200, {"ok": True, "settings": desk.set_auto_exits(body["on"])}
    return 404, {"ok": False, "message": "Not found"}


def handle(method: str, path: str, headers, body: dict | None, *, port: int,
           license_check=None) -> tuple[int, dict]:
    refused = _refusal(method, path, headers, port)
    if refused:
        return refused
    try:
        if method == "GET" and path == "/api/desk/ping":
            return 200, {"ok": True}          # "a desk lives here"; says nothing else
        if method == "GET" and path == "/api/desk/state":
            return 200, _state(headers, license_check)
        if method == "POST":
            return _post(path, body or {}, headers, license_check)
        return 404, {"ok": False, "message": "Not found"}
    except Exception as exc:  # noqa: BLE001 — the detail goes to the console, never the page
        print(f"[desk] {method} {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        store.audit("desk_error", {"path": path, "error": type(exc).__name__})
        return 500, {"ok": False, "message": "Something went wrong on the desk; nothing was sent "
                                             "unless the list says so. Check the console."}


# ------------------------------------------------------------------ background loop
def start_loop(every_min: float) -> threading.Thread | None:
    """Scan every `every_min` minutes while the app runs; auto-exits only if
    the owner switched them on. 0 turns the loop off."""
    if every_min <= 0 or _LOOP["thread"] is not None:
        return None
    _LOOP["every_min"] = every_min

    def run() -> None:
        time.sleep(min(60.0, every_min * 60))        # let the app finish starting first
        while True:
            try:
                result = desk.tick(live_permitted=loop_live_permitted())
                _LOOP["last_result"] = result
            except Exception as exc:  # noqa: BLE001 — one bad pass must not kill the loop
                print(f"[desk] loop: {type(exc).__name__}: {exc}", file=sys.stderr)
                _LOOP["last_result"] = {"ran": False, "why": type(exc).__name__}
            _LOOP["last"] = int(time.time())
            time.sleep(every_min * 60)

    t = threading.Thread(target=run, name="desk-loop", daemon=True)
    _LOOP["thread"] = t
    t.start()
    return t
