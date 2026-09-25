"""Grade My Reason: score a trader's written reason against the pre-buy checklist.

The trader types WHY before taking a trade. Jev (TypeSafe AI's evaluation
model, reached through Vercel AI Gateway) answers four yes/no checks and one
0-2 grade. It returns typed probabilities, never free text, so the only thing
it can report is how the reason measures up against the checklist below.

It is never asked where price is going. This grades the plan, not the trade:
a model that "agreed" with a bullish reason would be a signal wearing a
teaching hat, and Proof Mode already shows the signals have no validated edge.

Standard library only (urllib), like the rest of the server. The key lives in
AI_GATEWAY_API_KEY; with no key the feature reports itself off and the UI
hides it, so buyer packs without a key are unaffected.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque

GATEWAY_URL = "https://ai-gateway.vercel.sh/v1/evaluate"
MODEL = "typesafe-ai/jev"
KEY_ENV = "AI_GATEWAY_API_KEY"
TIMEOUT_S = 15
MAX_RESPONSE_BYTES = 64 * 1024   # a typed answer is well under 2 KB

MIN_REASON_CHARS = 12      # shorter than this is a word, not a reason
MAX_REASON_CHARS = 1200    # a paragraph; also bounds what one call can cost

# The checklist, in the order the UI shows it. Each is a yes/no question.
CHECKS = {
    "setup": ("Does the trader name a concrete chart setup or signal, such as RSI, "
              "MACD, a moving average, a breakout, a squeeze, support or resistance, "
              "rather than a tip or a feeling?"),
    "size": ("Does the trader say how much they are putting in, as a dollar amount, "
             "a share of their pot, or a number of shares or contracts?"),
    "exit": "Does the trader name a stop, a maximum loss, or a take-profit target?",
    "hype": ("Is the reason mainly hype, a tip, social media, or fear of missing out "
             "rather than their own read of the chart?"),
}
PLAN_CHECKS = ("setup", "size", "exit")     # the three a solid plan needs

GRADE_LABELS = ("no plan", "thin", "solid")
GRADE_CRITERIA = [
    "no plan: hype, a tip or a hunch",
    "thin: a real reason, but no size or no exit",
    "solid: a setup, a size and an exit",
]

# Limits. The per-client limit is politeness, not security: a whole class on
# one school network shares one address, so it is set high enough for ~30
# students grading several times in ten minutes. The forwarding headers it
# keys on can be forged off-Cloudflare, so the real guards are DAILY_CAP here
# and the spend budget on the gateway key itself. At ~450 input tokens a call,
# a full day at the cap costs about eight cents.
PER_CLIENT_LIMIT = 120
WINDOW_S = 600
DAILY_CAP = 4000
MAX_TRACKED_CLIENTS = 5000

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class InvalidReason(ValueError):
    """The caller's text is not something worth sending to the grader."""


class GraderUnavailable(RuntimeError):
    """The grader could not produce an answer. The message is for the server log."""


def api_key() -> str:
    return os.environ.get(KEY_ENV, "").strip()


def enabled() -> bool:
    return bool(api_key())


def clean_reason(raw: object) -> str:
    """Return the reason with control characters stripped and whitespace collapsed."""
    if not isinstance(raw, str):
        raise InvalidReason("Type your reason as text.")
    text = " ".join(_CONTROL_CHARS.sub("", raw).split())
    if len(text) < MIN_REASON_CHARS:
        raise InvalidReason("Write a full sentence: what you see, how much, and when you get out.")
    if len(text) > MAX_REASON_CHARS:
        raise InvalidReason(f"Keep it under {MAX_REASON_CHARS} characters.")
    return text


def build_body(reason: str) -> dict:
    questions = {key: {"type": "boolean", "instructions": text}
                 for key, text in CHECKS.items()}
    questions["quality"] = {
        "type": "score",
        "instructions": "Rate this trade reason against a pro trader's pre-buy checklist.",
        "criteria": list(GRADE_CRITERIA),
    }
    return {"model": MODEL, "state": reason, "questions": questions}


def _probability(answers: dict, key: str) -> float:
    value = (answers.get(key) or {}).get("probability")
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not 0.0 <= value <= 1.0:
        raise GraderUnavailable(f"unexpected answer for {key!r}")
    return float(value)


def parse_answers(answers: object) -> dict:
    """Turn Jev's typed answers into what the Coach card shows."""
    if not isinstance(answers, dict):
        raise GraderUnavailable("answers missing")
    checks = {key: _probability(answers, key) for key in CHECKS}

    score = (answers.get("quality") or {}).get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or math.isnan(score):
        raise GraderUnavailable("unexpected answer for 'quality'")
    top = len(GRADE_LABELS) - 1
    grade = min(max(float(score), 0.0), float(top))

    return {
        "grade": round(grade, 2),
        "label": GRADE_LABELS[int(math.floor(grade + 0.5))],
        "checks": {key: round(p, 2) for key, p in checks.items()},
        "missing": [key for key in PLAN_CHECKS if checks[key] < 0.5],
        "hype": checks["hype"] >= 0.5,
    }


def grade(reason: object, *, key: str | None = None,
          opener=urllib.request.urlopen) -> dict:
    """Grade one reason. Raises InvalidReason for bad input, GraderUnavailable otherwise."""
    text = clean_reason(reason)
    key = api_key() if key is None else key.strip()
    if not key:
        raise GraderUnavailable("grader is not configured")

    req = urllib.request.Request(
        GATEWAY_URL,
        data=json.dumps(build_body(text)).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        detail = exc.read(200).decode("utf-8", "replace")
        raise GraderUnavailable(f"gateway HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as exc:
        reason_text = getattr(exc, "reason", exc)
        raise GraderUnavailable(f"gateway unreachable: {reason_text}") from None

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GraderUnavailable("gateway returned something that is not JSON") from None
    if not isinstance(data, dict):
        raise GraderUnavailable("gateway returned an unexpected shape")
    return parse_answers(data.get("answers"))


def _valid_ip(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 45:
        return None
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def client_key(headers, peer: str) -> str:
    """Best-effort client address for rate limiting.

    Cloudflare refuses a client-supplied CF-Connecting-IP, so that header is
    preferred when present. The fallbacks can be forged, which only lets
    someone dodge the per-client limit, not the daily cap.
    """
    for name in ("CF-Connecting-IP", "True-Client-IP"):
        ip = _valid_ip(headers.get(name))
        if ip:
            return ip
    forwarded = headers.get("X-Forwarded-For")
    if isinstance(forwarded, str):
        ip = _valid_ip(forwarded.split(",")[0])
        if ip:
            return ip
    return peer


class GradeLimiter:
    """Sliding-window limit per client, plus a daily cap across everyone."""

    def __init__(self, per_client: int = PER_CLIENT_LIMIT, window_s: float = WINDOW_S,
                 daily_cap: int = DAILY_CAP, max_clients: int = MAX_TRACKED_CLIENTS,
                 clock=time.time):
        self._per_client = per_client
        self._window = window_s
        self._daily_cap = daily_cap
        self._max_clients = max_clients
        self._clock = clock
        self._hits: OrderedDict[str, deque] = OrderedDict()
        self._day: int | None = None
        self._day_count = 0
        self._lock = threading.Lock()

    def allow(self, client: str) -> tuple[bool, str | None]:
        with self._lock:
            now = self._clock()
            day = int(now // 86_400)
            if day != self._day:
                self._day, self._day_count = day, 0
            if self._day_count >= self._daily_cap:
                return False, ("The class has used today's grading allowance. "
                               "It resets at midnight UTC.")

            hits = self._hits.get(client)
            if hits is None:
                hits = self._hits[client] = deque()
            else:
                self._hits.move_to_end(client)
            cutoff = now - self._window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._per_client:
                return False, ("Too many grades from this network in the last few "
                               "minutes. Give it a moment and try again.")

            hits.append(now)
            self._day_count += 1
            while len(self._hits) > self._max_clients:
                self._hits.popitem(last=False)
            return True, None

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._hits)
