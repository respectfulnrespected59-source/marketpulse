"""Gumroad license keys for MarketPulse Pro / Pro+.

How a key becomes Pro:
  1. The buyer pastes their key once. `activate` asks Gumroad whether the key
     belongs to one of our plans and whether the purchase still entitles them,
     then consumes ONE seat (Gumroad's `uses` counter) and returns a signed
     token bound to that device.
  2. Every gated request carries key + token + device id. `check` verifies the
     token's signature and binding, then asks Gumroad for the CURRENT state of
     the purchase (cached) without touching the seat counter.

Facts taken from Gumroad's own controller (antiwork/gumroad,
app/controllers/api/v2/licenses_controller.rb + config/routes.rb):
  - POST /v2/licenses/verify needs no access token, but needs `product_id`
  - it INCREMENTS `uses` unless increment_uses_count=false is sent
  - it answers success:true for a REFUNDED purchase; only disabled keys and
    manually revoked access fail, so refunds/chargebacks/subscriptions are
    judged here
  - PUT /v2/licenses/decrement_uses_count needs the seller's access token

No database: the seat count lives at Gumroad and the device binding lives in
an HMAC-signed token, because the hosted server's disk is wiped on deploy.
Everything fails closed: no secret, no plans, or no answer from Gumroad for
a key we have never seen means NOT entitled.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
from collections import OrderedDict
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"
DECREMENT_URL = "https://api.gumroad.com/v2/licenses/decrement_uses_count"
_METHOD = {VERIFY_URL: "POST", DECREMENT_URL: "PUT"}

TIER_LIMITS = {"pro": {"devices": 2, "accounts": 1}, "proplus": {"devices": 5, "accounts": 3},
               "classes": {"devices": 2, "accounts": 1}}
BILLINGS = ("monthly", "lifetime")
# Who may open a paid lesson: the Classes pass, and Pro+ which includes it.
# Plain Pro does not; a Classes key unlocks lessons only, never Pro features
# (desk_api.live_permission checks for pro/proplus by name).
CLASS_TIERS = frozenset({"classes", "proplus"})
# Who gets Pro features (live execution, the desk). Named explicitly so no gate
# ever falls back to "any active license", which would let a Classes key in.
PRO_TIERS = frozenset({"pro", "proplus"})

TOKEN_TTL_S = 30 * 24 * 3600      # a device re-activates at most monthly
FRESH_S = 3600                    # re-ask Gumroad about an ACTIVE key at most hourly
FRESH_DENIED_S = 60               # ...but a denial is re-checked within a minute (card fixed)
GRACE_S = 72 * 3600               # a known-good key survives a Gumroad outage this long
HTTP_TIMEOUT_S = 10

KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
MIN_SECRET_LEN = 32
MAX_CACHE_ENTRIES = 10_000

Post = Callable[..., tuple]


@dataclass(frozen=True)
class Plan:
    product_id: str
    tier: str
    billing: str
    devices: int
    accounts: int


@dataclass(frozen=True)
class Entitlement:
    active: bool
    reason: str
    tier: str | None = None
    billing: str | None = None
    product_id: str | None = None
    uses: int = 0
    checked_at: float = 0.0
    unreachable: bool = False


# ------------------------------------------------------------------ config
def parse_plans(raw: str | None) -> dict[str, Plan]:
    """MP_GUMROAD_PLANS = {"<product_id>": {"tier": "pro"|"proplus"|"classes", "billing": "monthly"|"lifetime"}}.
    Anything unrecognised is dropped; an empty result means licensing is off."""
    try:
        data = json.loads(raw or "")
    except ValueError:
        return {}
    plans: dict[str, Plan] = {}
    for pid, spec in (data.items() if isinstance(data, dict) else []):
        if not isinstance(spec, dict):
            continue
        tier, billing = spec.get("tier"), spec.get("billing")
        if tier in TIER_LIMITS and billing in BILLINGS and isinstance(pid, str) and pid:
            plans[pid] = Plan(pid, tier, billing, **TIER_LIMITS[tier])
    return plans


def license_secret(env: dict | None = None, data_dir: Path | None = None) -> str | None:
    """Signing secret for activation tokens.
    Hosted: must come from MP_LICENSE_SECRET (a secret regenerated on every
    deploy would void every activation and burn buyers' seats again). It must
    be CSPRNG output (e.g. secrets.token_hex(32)); only the length is checked.
    Local download: generated once into data/.license_secret, but ONLY when
    run.bat / run.sh say so (MP_LICENSE_LOCAL=1). "Not on Render" is not proof
    of "on the buyer's computer", so without that signal licensing stays off."""
    env = os.environ if env is None else env
    configured = (env.get("MP_LICENSE_SECRET") or "").strip()
    if configured:
        return configured if len(configured) >= MIN_SECRET_LEN else None
    host = (env.get("HOST") or "127.0.0.1").strip().lower()
    is_local = (env.get("MP_LICENSE_LOCAL") == "1" and not env.get("RENDER")
                and host in ("127.0.0.1", "localhost", "::1", ""))
    if not is_local:
        return None
    path = Path(data_dir or Path(__file__).resolve().parent / "data") / ".license_secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:  # atomic + owner-only: two first-run requests cannot mint two secrets
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_text(encoding="utf-8").strip()
        return value if len(value) >= MIN_SECRET_LEN else None
    value = secrets.token_hex(32)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return value


# ------------------------------------------------------------------ transport
def http_post(url: str, data: dict, headers: dict | None = None) -> tuple[int, dict]:
    """Real Gumroad call. Returns (status, json body) for 2xx AND 4xx: a bad key
    is a 404 with {"success": false, "message": ...}, which is an answer, not an
    outage. Network failure raises OSError."""
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method=_METHOD.get(url, "POST"),
                                 headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            raise OSError(f"gumroad {exc.code}") from exc
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {"success": False, "message": f"HTTP {exc.code}"}


# ------------------------------------------------------------------ entitlement
def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def grants_classes(e: Entitlement) -> bool:
    """True only for an ACTIVE entitlement on a tier that includes classes."""
    return bool(e.active) and e.tier in CLASS_TIERS


def grants_pro(e: Entitlement) -> bool:
    """True only for an ACTIVE Pro or Pro+ entitlement."""
    return bool(e.active) and e.tier in PRO_TIERS


def entitlement_from(resp: dict, plan: Plan, now: float) -> Entitlement:
    """Does this Gumroad answer still entitle the buyer? Judged on the purchase,
    because Gumroad itself says success:true for refunds."""
    base = {"tier": plan.tier, "billing": plan.billing, "product_id": plan.product_id,
            "uses": int(resp.get("uses") or 0), "checked_at": now}
    if not resp.get("success"):
        return Entitlement(False, resp.get("message") or "not recognised", **base)
    p = resp.get("purchase") or {}
    if p.get("refunded"):
        return Entitlement(False, "refunded", **base)
    if p.get("chargebacked"):
        return Entitlement(False, "chargeback", **base)
    if p.get("disputed"):
        return Entitlement(False, "disputed", **base)
    if p.get("subscription_failed_at"):
        return Entitlement(False, "payment failed", **base)
    raw_end = p.get("subscription_ended_at")
    ended = parse_time(raw_end)
    if raw_end and ended is None:          # unreadable date: fail closed, never open
        return Entitlement(False, "subscription ended", **base)
    if ended is not None and ended <= now:
        return Entitlement(False, "subscription ended", **base)
    return Entitlement(True, "active", **base)


def _ask(key: str, plan: Plan, post: Post, now: float, increment: bool) -> Entitlement | str:
    """One product. Entitlement = Gumroad answered for this product; a string =
    Gumroad refused the key for this product (404: wrong product, disabled or
    revoked; the wording is Gumroad's and may change, so it only decorates the
    refusal, it never decides it); raises OSError when there was no real answer
    (outage, 429, any other 4xx)."""
    status, body = post(VERIFY_URL, {"product_id": plan.product_id, "license_key": key,
                                     "increment_uses_count": "true" if increment else "false"})
    if status == 404:
        return str(body.get("message") or "")
    if status != 200 or "success" not in body:
        raise OSError(f"gumroad answered {status}")
    return entitlement_from(body, plan, now)


def verify(key: str, plans: dict[str, Plan], *, post: Post = http_post,
           now: float | None = None, increment: bool = False, only: str | None = None) -> Entitlement:
    """Which plan (if any) does this key belong to, and is it entitled right now?"""
    now = time.time() if now is None else now
    if not isinstance(key, str) or not KEY_RE.match(key):
        return Entitlement(False, "That doesn't look like a MarketPulse license key.", checked_at=now)
    unreachable = False
    refusals: list[str] = []
    for pid, plan in plans.items():
        if only and pid != only:
            continue
        try:
            found = _ask(key, plan, post, now, increment)
        except (OSError, ValueError):
            unreachable = True
            continue
        if isinstance(found, Entitlement):
            return found
        refusals.append(found)
    special = [m for m in refusals if m and "does not exist" not in m]
    if special:  # e.g. "This license key has been disabled." for the right product
        return Entitlement(False, special[0], checked_at=now)
    if unreachable:
        return Entitlement(False, "The license server could not be reached. Try again shortly.",
                           checked_at=now, unreachable=True)
    return Entitlement(False, "That key is not recognised for any MarketPulse plan.", checked_at=now)


# ------------------------------------------------------------------ tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def issue_token(secret: str, key: str, device_id: str, tier: str, product_id: str, now: float) -> str:
    """Signed claim: this key activated this device for this plan. The key itself
    is never inside, only its fingerprint."""
    claims = {"k": key_fingerprint(key), "d": device_id, "t": tier, "p": product_id,
              "iat": int(now), "exp": int(now + TOKEN_TTL_S)}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(secret: str, token: str, now: float) -> dict | None:
    try:
        body, sig = token.split(".")
        want = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, AttributeError, TypeError):
        return None
    return claims if claims.get("exp", 0) > now else None


# ------------------------------------------------------------------ activation
def _refuse(message: str, e: Entitlement | None = None) -> dict:
    return {"ok": False, "message": message, "reason": e.reason if e else None}


def activate(key: str, device_id: str, plans: dict[str, Plan], secret: str | None, *,
             post: Post = http_post, now: float | None = None, seller_token: str | None = None) -> dict:
    """Consume one seat for this device and return a signed token."""
    now = time.time() if now is None else now
    if not isinstance(device_id, str) or not DEVICE_RE.match(device_id):
        return _refuse("This device has no id yet. Reload the app and try again.")
    if not secret or not plans:
        return _refuse("Licensing is not switched on for this copy of MarketPulse yet.")
    current = verify(key, plans, post=post, now=now)
    if not current.active:
        return _refuse(explain(current), current)
    plan = plans[current.product_id]
    if current.uses >= plan.devices:
        return _refuse(f"This license is already active on all {plan.devices} devices. "
                       "Deactivate one first.", current)
    after = verify(key, plans, post=post, now=now, increment=True, only=plan.product_id)
    if not after.active:
        if after.uses > current.uses:  # our increment landed on a now-refunded purchase
            _release_seat(key, plan.product_id, post, seller_token)
        return _refuse(explain(after), after)
    if after.uses > plan.devices:  # another device won the race for the last seat
        _release_seat(key, plan.product_id, post, seller_token)
        return _refuse(f"Another device just took the last of your {plan.devices} seats.", after)
    token = issue_token(secret, key, device_id, plan.tier, plan.product_id, now)
    return {"ok": True, "token": token, "tier": plan.tier, "billing": plan.billing,
            "devices": plan.devices, "accounts": plan.accounts, "seats_used": after.uses}


def deactivate(key: str, token: str, device_id: str, plans: dict[str, Plan], secret: str | None, *,
               seller_token: str | None, post: Post = http_post, now: float | None = None) -> dict:
    """Free this device's seat. Needs the seller's Gumroad token (decrement is a
    seller-only call); without it the buyer is told how to get a seat back."""
    now = time.time() if now is None else now
    claims = read_token(secret, token, now) if secret else None
    if not claims or claims.get("k") != key_fingerprint(key) or claims.get("d") != device_id:
        return _refuse("This device is not activated with that key.")
    if not seller_token:
        return _refuse("Seat release is not available on this copy. Contact support to free a seat.")
    # The product comes from the signed token, so a seat can be released even
    # after that plan is no longer offered.
    outcome = _release_seat(key, claims["p"], post, seller_token)
    if outcome == "released":
        return {"ok": True}
    if outcome == "unreachable":
        return _refuse("Could not reach the license server. Try again shortly.")
    return _refuse("The license server refused to release the seat. Contact support.")


def _release_seat(key: str, product_id: str, post: Post, seller_token: str | None) -> str:
    """'released' | 'unreachable' | 'rejected'. Every failure is logged (key
    fingerprint only), because an unreleased seat is a buyer locked out."""
    outcome = "rejected"
    if seller_token:
        try:
            _, body = post(DECREMENT_URL, {"access_token": seller_token, "product_id": product_id,
                                           "license_key": key})
            outcome = "released" if body.get("success") else "rejected"
        except (OSError, ValueError):
            outcome = "unreachable"
    if outcome != "released":
        why = "no MP_GUMROAD_TOKEN" if not seller_token else outcome
        print(f"[warn] license seat NOT released for key {key_fingerprint(key)[:12]} "
              f"product {product_id} ({why})", file=sys.stderr)
    return outcome


def explain(e: Entitlement) -> str:
    return {
        "refunded": "This purchase was refunded, so the license is no longer active.",
        "chargeback": "This purchase was charged back, so the license is no longer active.",
        "disputed": "This purchase is under dispute, so the license is paused.",
        "payment failed": "The last subscription payment failed. Update your card on Gumroad.",
        "subscription ended": "This subscription has ended. Renew on Gumroad to reactivate.",
    }.get(e.reason, e.reason)


# ------------------------------------------------------------------ gated check
class StatusCache:
    """Last Gumroad answer per key fingerprint (never the key itself). Bounded:
    the least recently used entries fall off past max_entries."""

    def __init__(self, max_entries: int = MAX_CACHE_ENTRIES) -> None:
        self._seen: OrderedDict[str, Entitlement] = OrderedDict()
        self._max = max_entries
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)

    def get(self, fp: str) -> Entitlement | None:
        with self._lock:
            e = self._seen.get(fp)
            if e is not None:
                self._seen.move_to_end(fp)
            return e

    def put(self, fp: str, e: Entitlement) -> None:
        with self._lock:
            self._seen[fp] = e
            self._seen.move_to_end(fp)
            while len(self._seen) > self._max:
                self._seen.popitem(last=False)


def check(key: str, token: str, device_id: str, plans: dict[str, Plan], secret: str | None,
          cache: StatusCache, *, post: Post = http_post, now: float | None = None) -> Entitlement:
    """Is this request entitled to Pro right now? Signature, binding, then the
    live purchase state (hourly), with a grace window for a key we have already
    seen active if Gumroad itself is down."""
    now = time.time() if now is None else now
    denied = Entitlement(False, "Not activated on this device.", checked_at=now)
    if not secret or not plans or not isinstance(key, str):
        return denied
    claims = read_token(secret, token, now)
    fp = key_fingerprint(key)
    if not claims or claims.get("k") != fp or claims.get("d") != device_id or claims.get("p") not in plans:
        return denied
    last = cache.get(fp)
    if last and now - last.checked_at < (FRESH_S if last.active else FRESH_DENIED_S):
        return last
    fresh = verify(key, plans, post=post, now=now, only=claims["p"])
    if fresh.unreachable and last and last.active and now - last.checked_at < GRACE_S:
        print(f"[warn] Gumroad unreachable; outage grace used for key {fp[:12]}", file=sys.stderr)
        return last
    cache.put(fp, fresh)
    return fresh
