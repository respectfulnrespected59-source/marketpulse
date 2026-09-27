"""Gumroad license keys: entitlement rules, seat limits, activation tokens.

Every call to Gumroad goes through an injected `post`, so these tests never
touch the network. Facts pinned from Gumroad's open-source controller
(antiwork/gumroad app/controllers/api/v2/licenses_controller.rb):
  - verify INCREMENTS the uses counter unless increment_uses_count=false is sent
  - a refunded purchase still verifies success:true (only disabled keys and
    manually revoked access are rejected), so refunds must be checked here
  - a bad key answers 404 with success:false and a message
"""

import json

import pytest

import licensing as lic

pytestmark = pytest.mark.unit

PRO_MONTHLY, PRO_LIFE, PLUS_LIFE = "pid-pro-m", "pid-pro-l", "pid-plus-l"
PLANS = lic.parse_plans(json.dumps({
    PRO_MONTHLY: {"tier": "pro", "billing": "monthly"},
    PRO_LIFE: {"tier": "pro", "billing": "lifetime"},
    PLUS_LIFE: {"tier": "proplus", "billing": "lifetime"},
}))
KEY = "A1B2C3D4-E5F60718-9ABCDEF0-1234ABCD"
SECRET = "test-secret-" + "x" * 40
NOW = 1_790_000_000.0


def purchase(**over):
    base = {"refunded": False, "chargebacked": False, "disputed": False,
            "subscription_ended_at": None, "subscription_cancelled_at": None,
            "subscription_failed_at": None}
    base.update(over)
    return base


class FakeGumroad:
    """Holds uses per product and records every request it was sent."""

    def __init__(self, owner=PRO_LIFE, uses=0, purchase_fields=None, disabled=False, down=False):
        self.owner, self.uses, self.disabled, self.down = owner, uses, disabled, down
        self.purchase = purchase(**(purchase_fields or {}))
        self.calls = []
        self.status_override = None

    def post(self, url, data, headers=None):
        self.calls.append((url, dict(data)))
        if self.down:
            raise OSError("network down")
        if url.endswith("/decrement_uses_count"):
            if data.get("access_token") != "tok":
                return 401, {"success": False, "message": "The access token is invalid."}
            self.uses = max(0, self.uses - 1)
            return 200, {"success": True, "uses": self.uses}
        if self.status_override:
            return self.status_override
        if data.get("product_id") != self.owner or data.get("license_key") != KEY:
            return 404, {"success": False, "message": "That license does not exist for the provided product."}
        if self.disabled:
            return 404, {"success": False, "message": "This license key has been disabled."}
        if data.get("increment_uses_count") != "false":
            self.uses += 1
        return 200, {"success": True, "uses": self.uses, "purchase": dict(self.purchase)}


# ------------------------------------------------------------------ plans
def test_plans_come_from_config_and_bad_entries_are_dropped():
    plans = lic.parse_plans(json.dumps({"a": {"tier": "pro", "billing": "monthly"},
                                        "b": {"tier": "gold", "billing": "monthly"},
                                        "c": {"tier": "pro", "billing": "weekly"}}))
    assert list(plans) == ["a"]
    assert plans["a"].devices == 2 and plans["a"].accounts == 1


def test_proplus_gets_five_devices_and_three_accounts():
    assert PLANS[PLUS_LIFE].devices == 5 and PLANS[PLUS_LIFE].accounts == 3


def test_unconfigured_licensing_is_simply_off():
    assert lic.parse_plans("") == {}
    assert lic.parse_plans("not json") == {}


# ------------------------------------------------------------------ entitlement rules
@pytest.mark.parametrize("fields,active,reason", [
    ({}, True, "active"),
    ({"refunded": True}, False, "refunded"),
    ({"chargebacked": True}, False, "chargeback"),
    ({"disputed": True}, False, "disputed"),
])
def test_one_time_purchase_rules(fields, active, reason):
    e = lic.entitlement_from({"success": True, "uses": 1, "purchase": purchase(**fields)},
                             PLANS[PRO_LIFE], NOW)
    assert e.active is active and e.reason == reason


def test_cancelled_subscription_stays_active_until_it_ends():
    later = "2026-12-01T00:00:00Z"
    e = lic.entitlement_from({"success": True, "uses": 1, "purchase": purchase(
        subscription_cancelled_at="2026-09-01T00:00:00Z", subscription_ended_at=later)},
        PLANS[PRO_MONTHLY], lic.parse_time("2026-10-01T00:00:00Z"))
    assert e.active


def test_ended_subscription_is_not_active():
    e = lic.entitlement_from({"success": True, "uses": 1, "purchase": purchase(
        subscription_ended_at="2026-09-01T00:00:00Z")},
        PLANS[PRO_MONTHLY], lic.parse_time("2026-10-01T00:00:00Z"))
    assert not e.active and e.reason == "subscription ended"


def test_failed_subscription_payment_is_not_active():
    e = lic.entitlement_from({"success": True, "uses": 1, "purchase": purchase(
        subscription_failed_at="2026-09-01T00:00:00Z")}, PLANS[PRO_MONTHLY], NOW)
    assert not e.active and e.reason == "payment failed"


def test_success_false_is_never_active():
    e = lic.entitlement_from({"success": False, "message": "disabled"}, PLANS[PRO_LIFE], NOW)
    assert not e.active


# ------------------------------------------------------------------ verify
def test_status_checks_never_consume_a_seat():
    g = FakeGumroad(uses=1)
    e = lic.verify(KEY, PLANS, post=g.post, now=NOW)
    assert e.active and e.tier == "pro" and g.uses == 1
    assert all(d.get("increment_uses_count") == "false" for _, d in g.calls)


def test_verify_finds_the_product_the_key_belongs_to():
    g = FakeGumroad(owner=PLUS_LIFE)
    e = lic.verify(KEY, PLANS, post=g.post, now=NOW)
    assert e.active and e.tier == "proplus" and e.product_id == PLUS_LIFE


def test_unknown_key_is_rejected_with_a_plain_message():
    g = FakeGumroad(owner="some-other-product")
    e = lic.verify(KEY, PLANS, post=g.post, now=NOW)
    assert not e.active and "not recognised" in e.reason


def test_a_malformed_key_never_reaches_gumroad():
    g = FakeGumroad()
    e = lic.verify("x'; drop--", PLANS, post=g.post, now=NOW)
    assert not e.active and g.calls == []


# ------------------------------------------------------------------ activation + seats
def test_activation_consumes_exactly_one_seat_and_issues_a_token():
    g = FakeGumroad(uses=0)
    r = lic.activate(KEY, "dev-1", PLANS, SECRET, post=g.post, now=NOW)
    assert r["ok"] and g.uses == 1
    claims = lic.read_token(SECRET, r["token"], NOW)
    assert claims["d"] == "dev-1" and claims["t"] == "pro"
    assert KEY not in r["token"]  # the key itself never rides in the token


def test_activation_is_refused_when_every_seat_is_taken():
    g = FakeGumroad(uses=2)  # Pro = 2 devices
    r = lic.activate(KEY, "dev-3", PLANS, SECRET, post=g.post, now=NOW)
    assert not r["ok"] and "2 devices" in r["message"] and g.uses == 2


def test_a_race_past_the_limit_is_rolled_back():
    g = FakeGumroad(uses=1)
    real = g.post

    def racing(url, data, headers=None):  # another device activates between our read and increment
        if data.get("increment_uses_count") != "false" and "decrement" not in url:
            g.uses += 1
        return real(url, data, headers)

    r = lic.activate(KEY, "dev-2", PLANS, SECRET, post=racing, now=NOW, seller_token="tok")
    assert not r["ok"] and g.uses == 2


def test_refunded_key_cannot_activate():
    g = FakeGumroad(purchase_fields={"refunded": True})
    r = lic.activate(KEY, "dev-1", PLANS, SECRET, post=g.post, now=NOW)
    assert not r["ok"] and g.uses == 0


def test_activation_needs_a_device_id():
    g = FakeGumroad()
    r = lic.activate(KEY, "", PLANS, SECRET, post=g.post, now=NOW)
    assert not r["ok"] and g.calls == []


# ------------------------------------------------------------------ tokens
def test_a_tampered_token_is_rejected():
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    body, sig = tok.split(".")
    forged = lic.issue_token(SECRET, KEY, "dev-1", "proplus", PLUS_LIFE, NOW).split(".")[0] + "." + sig
    assert lic.read_token(SECRET, forged, NOW) is None
    assert lic.read_token("another-secret-" + "y" * 40, tok, NOW) is None


def test_an_expired_token_is_rejected():
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    assert lic.read_token(SECRET, tok, NOW + lic.TOKEN_TTL_S + 1) is None


# ------------------------------------------------------------------ gated check
def test_check_requires_matching_key_device_and_live_entitlement():
    g = FakeGumroad(uses=1)
    cache = lic.StatusCache()
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    ok = lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW)
    assert ok.active and ok.tier == "pro"
    assert not lic.check(KEY, tok, "dev-2", PLANS, SECRET, cache, post=g.post, now=NOW).active
    assert not lic.check("OTHER-KEY-0000-0000", tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW).active


def test_a_refund_after_activation_turns_pro_off():
    g = FakeGumroad(uses=1)
    cache = lic.StatusCache()
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    assert lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW).active
    g.purchase["refunded"] = True
    later = NOW + lic.FRESH_S + 1
    assert not lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=later).active


def test_gumroad_outage_gets_a_grace_window_only_for_a_known_good_key():
    g = FakeGumroad(uses=1)
    cache = lic.StatusCache()
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    assert lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW).active
    g.down = True
    assert lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW + lic.FRESH_S + 1).active
    assert not lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW + lic.GRACE_S + 1).active


def test_outage_with_no_history_fails_closed():
    g = FakeGumroad(down=True)
    assert not lic.verify(KEY, PLANS, post=g.post, now=NOW).active


# ------------------------------------------------------------------ secret
def test_public_host_without_a_secret_turns_licensing_off(tmp_path):
    assert lic.license_secret({"RENDER": "1"}, tmp_path) is None


def test_local_download_generates_and_keeps_its_own_secret(tmp_path):
    env = {"MP_LICENSE_LOCAL": "1"}
    first = lic.license_secret(env, tmp_path)
    assert first and len(first) >= 32
    assert lic.license_secret(env, tmp_path) == first


def test_no_explicit_local_signal_means_off_even_on_loopback(tmp_path):
    # "Not on Render" is not proof of "local download": another host would
    # silently mint its own secret. Only run.bat / run.sh say MP_LICENSE_LOCAL=1.
    assert lic.license_secret({}, tmp_path) is None
    assert not (tmp_path / ".license_secret").exists()


def test_a_hosted_env_never_generates_a_secret_even_if_flagged_local(tmp_path):
    assert lic.license_secret({"MP_LICENSE_LOCAL": "1", "RENDER": "1"}, tmp_path) is None


def test_the_local_secret_file_is_owner_only(tmp_path):
    import os, stat
    lic.license_secret({"MP_LICENSE_LOCAL": "1"}, tmp_path)
    mode = stat.S_IMODE(os.stat(tmp_path / ".license_secret").st_mode)
    if os.name != "nt":  # Windows has no POSIX group/other bits
        assert mode & 0o077 == 0


def test_status_cache_is_bounded():
    cache = lic.StatusCache(max_entries=3)
    for i in range(10):
        cache.put(f"fp{i}", lic.Entitlement(True, "active", checked_at=NOW))
    assert len(cache) == 3 and cache.get("fp9") and cache.get("fp0") is None


def test_a_failed_seat_release_is_logged_without_the_key(capsys):
    g = FakeGumroad(uses=1)
    real = g.post

    def racing(url, data, headers=None):
        if data.get("increment_uses_count") != "false" and "decrement" not in url:
            g.uses += 1
        return real(url, data, headers)

    lic.activate(KEY, "dev-2", PLANS, SECRET, post=racing, now=NOW, seller_token=None)
    err = capsys.readouterr().err
    assert "seat" in err and lic.key_fingerprint(KEY)[:12] in err and KEY not in err


def test_configured_secret_wins_but_must_be_long_enough(tmp_path):
    assert lic.license_secret({"MP_LICENSE_SECRET": "s" * 40, "RENDER": "1"}, tmp_path) == "s" * 40
    assert lic.license_secret({"MP_LICENSE_SECRET": "short", "RENDER": "1"}, tmp_path) is None



# ------------------------------------------------------------------ review round 1
def test_unreadable_subscription_end_date_fails_closed():
    e = lic.entitlement_from({"success": True, "uses": 1, "purchase": purchase(
        subscription_ended_at="sometime last week")}, PLANS[PRO_MONTHLY], NOW)
    assert not e.active


def test_a_refund_between_the_two_reads_gives_the_seat_back():
    g = FakeGumroad(uses=0)
    real = g.post

    def flips(url, data, headers=None):
        out = real(url, data, headers)
        if data.get("increment_uses_count") == "false" and out[0] == 200:
            g.purchase["refunded"] = True     # refunded right after our successful first read
        return out

    r = lic.activate(KEY, "dev-1", PLANS, SECRET, post=flips, now=NOW, seller_token="tok")
    assert not r["ok"] and g.uses == 0


def test_differently_worded_404_still_moves_on_to_the_right_plan():
    g = FakeGumroad(owner=PLUS_LIFE)
    real = g.post

    def reworded(url, data, headers=None):
        status, body = real(url, data, headers)
        if status == 404:
            body = {"success": False, "message": "No such license for this product"}
        return status, body

    e = lic.verify(KEY, PLANS, post=reworded, now=NOW)
    assert e.active and e.product_id == PLUS_LIFE


def test_a_disabled_key_is_still_refused():
    g = FakeGumroad(disabled=True)
    e = lic.verify(KEY, PLANS, post=g.post, now=NOW)
    assert not e.active and "disabled" in e.reason


def test_rate_limited_by_gumroad_counts_as_unreachable():
    g = FakeGumroad()
    g.status_override = (429, {"success": False, "message": "Too many requests"})
    e = lic.verify(KEY, PLANS, post=g.post, now=NOW)
    assert not e.active and e.unreachable


def test_a_denial_is_rechecked_within_a_minute_not_an_hour():
    g = FakeGumroad(uses=1, purchase_fields={"subscription_failed_at": "2026-09-01T00:00:00Z"})
    cache = lic.StatusCache()
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    assert not lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=NOW).active
    g.purchase["subscription_failed_at"] = None          # buyer fixed their card
    later = NOW + lic.FRESH_DENIED_S + 1
    assert lic.check(KEY, tok, "dev-1", PLANS, SECRET, cache, post=g.post, now=later).active


def test_deactivate_says_when_gumroad_rejected_the_seller_token():
    g = FakeGumroad(uses=1)
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    r = lic.deactivate(KEY, tok, "dev-1", PLANS, SECRET, seller_token="wrong", post=g.post, now=NOW)
    assert not r["ok"] and "reach" not in r["message"] and g.uses == 1


def test_deactivate_works_even_after_the_plan_left_the_config():
    g = FakeGumroad(uses=1)
    tok = lic.issue_token(SECRET, KEY, "dev-1", "pro", PRO_LIFE, NOW)
    r = lic.deactivate(KEY, tok, "dev-1", {}, SECRET, seller_token="tok", post=g.post, now=NOW)
    assert r["ok"] and g.uses == 0
