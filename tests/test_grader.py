"""Grade My Reason: input guards, the Nemotron request/reply contract, and the limiter.

No test here touches the network. `grade()` takes an injectable opener so the
HTTP call can be faked, and the limiter takes an injectable clock.
"""

import io
import json
import urllib.error

import pytest

import grader
from grader import (
    GradeLimiter,
    GraderUnavailable,
    InvalidReason,
    build_body,
    clean_reason,
    client_key,
    parse_reply,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    # A developer machine may carry a real key; no test here may reach the network.
    monkeypatch.delenv(grader.KEY_ENV, raising=False)


GOOD_REASON = ("RSI came off 30 and MACD crossed up. $60 probe out of a $300 pot. "
               "Stop at -50%, take profit at +32%.")
SOLID_JSON = '{"setup": true, "size": true, "exit": true, "hype": false, "grade": 2}'
THIN_JSON = '{"setup": true, "size": true, "exit": false, "hype": false, "grade": 1}'


def reply(content):
    return {"choices": [{"message": {"content": content}}]}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_returning(payload, captured=None):
    def _open(req, timeout=None):
        if captured is not None:
            captured["req"] = req
            captured["timeout"] = timeout
        return FakeResponse(json.dumps(payload).encode("utf-8"))
    return _open


class TestCleanReason:
    def test_accepts_a_normal_reason(self):
        assert clean_reason(GOOD_REASON) == GOOD_REASON

    def test_collapses_whitespace_and_trims(self):
        assert clean_reason("  RSI   bounced\n\n off 30,  small size  ") == \
            "RSI bounced off 30, small size"

    def test_strips_control_characters(self):
        assert clean_reason("RSI bounced\x00\x07 off 30 today") == "RSI bounced off 30 today"

    @pytest.mark.parametrize("raw", [None, 42, ["a list"], {"a": "dict"}])
    def test_rejects_non_strings(self, raw):
        with pytest.raises(InvalidReason):
            clean_reason(raw)

    @pytest.mark.parametrize("raw", ["", "   ", "moon"])
    def test_rejects_too_short(self, raw):
        with pytest.raises(InvalidReason):
            clean_reason(raw)

    def test_rejects_too_long(self):
        with pytest.raises(InvalidReason):
            clean_reason("x" * (grader.MAX_REASON_CHARS + 1))

    def test_accepts_exactly_the_max(self):
        assert len(clean_reason("x" * grader.MAX_REASON_CHARS)) == grader.MAX_REASON_CHARS


class TestBuildBody:
    def test_uses_the_paid_lane_with_thinking_off(self):
        body = build_body(GOOD_REASON)
        assert body["model"] == grader.MODEL and not body["model"].endswith(":free")
        assert body["reasoning"] == {"enabled": False}
        assert GOOD_REASON in body["messages"][-1]["content"]

    def test_asks_every_checklist_question_and_the_grade(self):
        system = build_body(GOOD_REASON)["messages"][0]["content"]
        for question in grader.CHECKS.values():
            assert question in system
        for criterion in grader.GRADE_CRITERIA:
            assert criterion in system

    def test_never_asks_about_price_or_direction(self):
        # This grades the plan, not the trade. A question about where price is
        # going would turn a teaching tool into a signal.
        text = build_body(GOOD_REASON)["messages"][0]["content"].lower()
        for word in ("will it go up", "will the price", "buy or sell", "bullish", "bearish"):
            assert word not in text


class TestParseReply:
    def test_solid_plan(self):
        out = parse_reply(SOLID_JSON)
        assert out["label"] == "solid" and out["grade"] == 2.0
        assert out["missing"] == [] and out["hype"] is False

    def test_thin_plan_names_what_is_missing(self):
        out = parse_reply(THIN_JSON)
        assert out["label"] == "thin" and out["missing"] == ["exit"]

    def test_hype_trade(self):
        out = parse_reply('{"setup": false, "size": false, "exit": false, "hype": true, "grade": 0}')
        assert out["label"] == "no plan"
        assert out["missing"] == ["setup", "size", "exit"] and out["hype"] is True

    def test_checks_are_plain_yes_no(self):
        # No confidence numbers: the model gives none, so the page must not invent one.
        assert parse_reply(THIN_JSON)["checks"] == {"setup": True, "size": True, "exit": False, "hype": False}

    def test_reads_json_inside_other_text(self):
        assert parse_reply("Here you go:\n```json\n" + THIN_JSON + "\n```")["label"] == "thin"

    @pytest.mark.parametrize("text", [
        None,
        "",
        "Sorry, I can't help with that.",
        '{"setup": true}',
        '{"setup": "yes", "size": true, "exit": true, "hype": false, "grade": 2}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": 3}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": -1}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": true}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": "2"}',
        '{"setup": true, "size": true, "exit": true, "grade": 2}',
    ])
    def test_rejects_anything_off_contract(self, text):
        with pytest.raises(GraderUnavailable):
            parse_reply(text)


class TestGrade:
    def test_posts_to_openrouter_with_the_key(self):
        captured = {}
        out = grader.grade(GOOD_REASON, key="sk-or-test",
                           opener=opener_returning(reply(SOLID_JSON), captured))
        req = captured["req"]
        assert req.full_url == grader.GRADER_URL
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer sk-or-test"
        assert GOOD_REASON in json.loads(req.data)["messages"][-1]["content"]
        assert captured["timeout"] == grader.TIMEOUT_S
        assert out["label"] == "solid"

    def test_cleans_the_reason_before_sending(self):
        captured = {}
        grader.grade("  " + GOOD_REASON + "  ", key="sk-or-test",
                     opener=opener_returning(reply(SOLID_JSON), captured))
        assert json.loads(captured["req"].data)["messages"][-1]["content"] == f"Trade reason: {GOOD_REASON}"

    def test_no_key_is_unavailable_and_sends_nothing(self):
        def _never(req, timeout=None):
            raise AssertionError("must not call the network without a key")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="", opener=_never)

    def test_invalid_reason_sends_nothing(self):
        def _never(req, timeout=None):
            raise AssertionError("must not call the network for bad input")
        with pytest.raises(InvalidReason):
            grader.grade("", key="sk-or-test", opener=_never)

    def test_http_error_becomes_unavailable(self):
        def _fail(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                         io.BytesIO(b'{"error":"high demand"}'))
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="sk-or-test", opener=_fail)
        assert "429" in str(exc.value)

    def test_network_error_becomes_unavailable(self):
        def _fail(req, timeout=None):
            raise urllib.error.URLError("timed out")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="sk-or-test", opener=_fail)

    def test_non_json_reply_becomes_unavailable(self):
        def _open(req, timeout=None):
            return FakeResponse(b"<html>gateway error</html>")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="sk-or-test", opener=_open)

    def test_reply_without_choices_becomes_unavailable(self):
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="sk-or-test", opener=opener_returning({"error": "nope"}))

    def test_off_contract_answer_becomes_unavailable(self):
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="sk-or-test", opener=opener_returning(reply("I think it's fine!")))

    def test_key_never_appears_in_an_error(self):
        def _fail(req, timeout=None):
            raise urllib.error.URLError("boom")
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="sk-or-secret-value", opener=_fail)
        assert "sk-or-secret-value" not in str(exc.value)


class TestEnabled:
    def test_off_without_a_key(self):
        assert grader.enabled() is False

    def test_off_with_a_blank_key(self, monkeypatch):
        monkeypatch.setenv(grader.KEY_ENV, "   ")
        assert grader.enabled() is False

    def test_on_with_a_key(self, monkeypatch):
        monkeypatch.setenv(grader.KEY_ENV, "sk-or-test")
        assert grader.enabled() is True

    def test_a_leftover_jev_key_does_nothing(self, monkeypatch):
        monkeypatch.setenv("AI_GATEWAY_API_KEY", "vck_left_over")
        assert grader.enabled() is False


class TestClientKey:
    def test_prefers_cloudflare_connecting_ip(self):
        headers = {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"}
        assert client_key(headers, "10.0.0.1") == "203.0.113.7"

    def test_falls_back_to_leftmost_forwarded_for(self):
        headers = {"X-Forwarded-For": "198.51.100.1, 10.1.2.3"}
        assert client_key(headers, "10.0.0.1") == "198.51.100.1"

    def test_falls_back_to_the_peer(self):
        assert client_key({}, "10.0.0.1") == "10.0.0.1"

    @pytest.mark.parametrize("junk", ["not an ip", "x" * 80, "1.2.3.4; drop", ""])
    def test_ignores_junk_headers(self, junk):
        assert client_key({"X-Forwarded-For": junk}, "10.0.0.1") == "10.0.0.1"

    def test_accepts_ipv6(self):
        assert client_key({"X-Forwarded-For": "2001:db8::1"}, "10.0.0.1") == "2001:db8::1"


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestGradeLimiter:
    def test_allows_up_to_the_per_client_limit(self):
        lim = GradeLimiter(per_client=3, window_s=600, daily_cap=100, clock=Clock())
        assert [lim.allow("a")[0] for _ in range(4)] == [True, True, True, False]

    def test_clients_are_counted_separately(self):
        lim = GradeLimiter(per_client=1, window_s=600, daily_cap=100, clock=Clock())
        assert lim.allow("a")[0] and lim.allow("b")[0]
        assert lim.allow("a")[0] is False

    def test_window_slides(self):
        clock = Clock()
        lim = GradeLimiter(per_client=1, window_s=600, daily_cap=100, clock=clock)
        assert lim.allow("a")[0]
        assert lim.allow("a")[0] is False
        clock.t += 601
        assert lim.allow("a")[0]

    def test_daily_cap_stops_everyone(self):
        lim = GradeLimiter(per_client=100, window_s=600, daily_cap=2, clock=Clock())
        assert lim.allow("a")[0] and lim.allow("b")[0]
        ok, why = lim.allow("c")
        assert ok is False and "today" in why

    def test_daily_cap_resets_at_the_next_utc_day(self):
        clock = Clock()
        lim = GradeLimiter(per_client=100, window_s=600, daily_cap=1, clock=clock)
        assert lim.allow("a")[0]
        assert lim.allow("b")[0] is False
        clock.t += 86_400
        assert lim.allow("b")[0]

    def test_refusal_does_not_spend_the_daily_cap(self):
        lim = GradeLimiter(per_client=1, window_s=600, daily_cap=2, clock=Clock())
        assert lim.allow("a")[0]
        assert lim.allow("a")[0] is False     # per-client refusal
        assert lim.allow("b")[0]              # the refused call did not use a slot

    def test_tracked_clients_stay_bounded(self):
        lim = GradeLimiter(per_client=5, window_s=600, daily_cap=10_000,
                           max_clients=10, clock=Clock())
        for i in range(50):
            lim.allow(f"client-{i}")
        assert lim.tracked_clients() <= 10
