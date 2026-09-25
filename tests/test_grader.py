"""Grade My Reason: input guards, the Jev request/response contract, and the limiter.

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
    parse_answers,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    # A developer machine may carry real keys; no test here may reach the network.
    monkeypatch.delenv(grader.KEY_ENV, raising=False)
    monkeypatch.delenv(grader.BACKUP_KEY_ENV, raising=False)


GOOD_REASON =("RSI came off 30 and MACD crossed up. $60 probe out of a $300 pot. "
               "Stop at -50%, take profit at +32%.")


def jev_answers(setup=0.9, size=0.9, exit_=0.9, hype=0.05, score=2.0):
    return {
        "setup": {"type": "boolean", "probability": setup},
        "size": {"type": "boolean", "probability": size},
        "exit": {"type": "boolean", "probability": exit_},
        "hype": {"type": "boolean", "probability": hype},
        "quality": {"type": "score", "score": score,
                    "probabilities": {"0": 0, "1": 0, "2": 1}},
    }


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
    def test_targets_jev_with_the_reason_as_state(self):
        body = build_body(GOOD_REASON)
        assert body["model"] == "typesafe-ai/jev"
        assert body["state"] == GOOD_REASON

    def test_asks_every_checklist_question_and_the_grade(self):
        qs = build_body(GOOD_REASON)["questions"]
        assert set(qs) == {"setup", "size", "exit", "hype", "quality"}
        for key in ("setup", "size", "exit", "hype"):
            assert qs[key]["type"] == "boolean"
        assert qs["quality"]["type"] == "score"
        assert len(qs["quality"]["criteria"]) == len(grader.GRADE_LABELS)

    def test_never_asks_about_price_or_direction(self):
        # This grades the plan, not the trade. A question about where price is
        # going would turn a teaching tool into a signal.
        text = json.dumps(build_body(GOOD_REASON)["questions"]).lower()
        for word in ("will it go up", "will the price", "buy or sell", "bullish", "bearish"):
            assert word not in text


class TestParseAnswers:
    def test_solid_plan(self):
        out = parse_answers(jev_answers())
        assert out["label"] == "solid"
        assert out["grade"] == 2.0
        assert out["missing"] == []
        assert out["hype"] is False

    def test_hype_trade(self):
        out = parse_answers(jev_answers(setup=0.1, size=0.05, exit_=0.02, hype=0.97, score=0.0))
        assert out["label"] == "no plan"
        assert out["missing"] == ["setup", "size", "exit"]
        assert out["hype"] is True

    def test_thin_plan_names_what_is_missing(self):
        out = parse_answers(jev_answers(setup=0.95, size=0.1, exit_=0.2, score=1.1))
        assert out["label"] == "thin"
        assert out["missing"] == ["size", "exit"]

    def test_checks_are_rounded_probabilities(self):
        out = parse_answers(jev_answers(setup=0.98765))
        assert out["checks"]["setup"] == 0.99

    @pytest.mark.parametrize("score,label", [(0.4, "no plan"), (0.6, "thin"), (1.4, "thin"),
                                             (1.6, "solid"), (-3, "no plan"), (9, "solid"),
                                             (float("inf"), "solid"),
                                             (float("-inf"), "no plan")])
    def test_label_follows_the_score_and_clamps(self, score, label):
        assert parse_answers(jev_answers(score=score))["label"] == label

    @pytest.mark.parametrize("broken", [
        {},
        None,
        {"setup": {"probability": "high"}},
        {**jev_answers(), "exit": {"type": "boolean"}},
        {**jev_answers(), "quality": {"type": "score"}},
        {**jev_answers(), "size": {"type": "boolean", "probability": 1.5}},
        {**jev_answers(), "hype": {"type": "boolean", "probability": True}},
        {**jev_answers(), "setup": {"type": "boolean", "probability": float("nan")}},
        {**jev_answers(), "quality": {"type": "score", "score": float("nan")}},
    ])
    def test_malformed_answers_raise_unavailable(self, broken):
        with pytest.raises(GraderUnavailable):
            parse_answers(broken)


class TestGrade:
    def test_posts_to_the_gateway_with_the_key(self):
        captured = {}
        out = grader.grade(GOOD_REASON, key="vck_test",
                           opener=opener_returning({"answers": jev_answers()}, captured))
        req = captured["req"]
        assert req.full_url == grader.GATEWAY_URL
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer vck_test"
        assert json.loads(req.data)["state"] == GOOD_REASON
        assert captured["timeout"] == grader.TIMEOUT_S
        assert out["label"] == "solid"

    def test_cleans_the_reason_before_sending(self):
        captured = {}
        grader.grade("  " + GOOD_REASON + "  ", key="vck_test",
                     opener=opener_returning({"answers": jev_answers()}, captured))
        assert json.loads(captured["req"].data)["state"] == GOOD_REASON

    def test_no_key_is_unavailable_and_sends_nothing(self):
        def _never(req, timeout=None):
            raise AssertionError("must not call the network without a key")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="", opener=_never)

    def test_invalid_reason_sends_nothing(self):
        def _never(req, timeout=None):
            raise AssertionError("must not call the network for bad input")
        with pytest.raises(InvalidReason):
            grader.grade("", key="vck_test", opener=_never)

    def test_http_error_becomes_unavailable(self):
        def _fail(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b'{"error":"no card"}'))
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="vck_test", opener=_fail)
        assert "403" in str(exc.value)

    def test_network_error_becomes_unavailable(self):
        def _fail(req, timeout=None):
            raise urllib.error.URLError("timed out")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="vck_test", opener=_fail)

    def test_non_json_reply_becomes_unavailable(self):
        def _open(req, timeout=None):
            return FakeResponse(b"<html>gateway error</html>")
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="vck_test", opener=_open)

    def test_reply_without_answers_becomes_unavailable(self):
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="vck_test", opener=opener_returning({"ok": True}))

    def test_key_never_appears_in_an_error(self):
        def _fail(req, timeout=None):
            raise urllib.error.URLError("boom")
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="vck_secret_value", opener=_fail)
        assert "vck_secret_value" not in str(exc.value)


def backup_reply(content):
    return {"choices": [{"message": {"content": content}}]}


def routed_opener(calls, jev=None, backup=None):
    """Fake network: `jev` / `backup` are a payload dict, or an exception to raise."""
    def _open(req, timeout=None):
        which = "jev" if req.full_url == grader.GATEWAY_URL else "backup"
        calls.append((which, req, timeout))
        result = jev if which == "jev" else backup
        if isinstance(result, Exception):
            raise result
        return FakeResponse(json.dumps(result).encode("utf-8"))
    return _open


def rate_limited(url=grader.GATEWAY_URL):
    return urllib.error.HTTPError(url, 429, "Too Many Requests", {},
                                  io.BytesIO(b'{"error":{"message":"high demand"}}'))


THIN_JSON = '{"setup": true, "size": true, "exit": false, "hype": false, "grade": 1}'


class TestBackup:
    def test_jev_answer_never_touches_the_backup(self):
        calls = []
        out = grader.grade(GOOD_REASON, key="vck_test", backup="sk-or-test",
                           opener=routed_opener(calls, jev={"answers": jev_answers()}))
        assert [c[0] for c in calls] == ["jev"]
        assert out["graded_by"] == "jev"

    def test_falls_back_when_jev_is_overloaded(self):
        calls = []
        out = grader.grade(GOOD_REASON, key="vck_test", backup="sk-or-test",
                           opener=routed_opener(calls, jev=rate_limited(),
                                                backup=backup_reply(THIN_JSON)))
        assert [c[0] for c in calls] == ["jev", "backup"]
        assert out["graded_by"] == "backup"
        assert out["label"] == "thin"
        assert out["missing"] == ["exit"]
        assert out["checks"]["setup"] == 1.0 and out["checks"]["exit"] == 0.0

    def test_backup_request_uses_the_paid_lane_with_thinking_off(self):
        calls = []
        grader.grade(GOOD_REASON, key="vck_test", backup="sk-or-test",
                     opener=routed_opener(calls, jev=rate_limited(), backup=backup_reply(THIN_JSON)))
        _, req, timeout = calls[1]
        body = json.loads(req.data)
        assert req.full_url == grader.BACKUP_URL
        assert req.get_header("Authorization") == "Bearer sk-or-test"
        assert body["model"] == grader.BACKUP_MODEL and not body["model"].endswith(":free")
        assert body["reasoning"] == {"enabled": False}
        assert GOOD_REASON in body["messages"][-1]["content"]
        assert timeout == grader.BACKUP_TIMEOUT_S

    def test_backup_alone_works_without_a_jev_key(self):
        calls = []
        out = grader.grade(GOOD_REASON, key="", backup="sk-or-test",
                           opener=routed_opener(calls, backup=backup_reply(THIN_JSON)))
        assert [c[0] for c in calls] == ["backup"]
        assert out["graded_by"] == "backup"

    def test_both_down_is_unavailable_and_names_both(self):
        calls = []
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="vck_secret", backup="sk-or-secret",
                         opener=routed_opener(calls, jev=rate_limited(),
                                              backup=rate_limited(grader.BACKUP_URL)))
        msg = str(exc.value)
        assert "jev" in msg and "backup" in msg
        assert "vck_secret" not in msg and "sk-or-secret" not in msg

    def test_no_backup_key_keeps_the_jev_error(self):
        with pytest.raises(GraderUnavailable) as exc:
            grader.grade(GOOD_REASON, key="vck_test", backup="",
                         opener=routed_opener([], jev=rate_limited()))
        assert "429" in str(exc.value)

    @pytest.mark.parametrize("content", ["", "Sorry, I can't help with that.", '{"setup": true}'])
    def test_unusable_backup_reply_is_unavailable(self, content):
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="", backup="sk-or-test",
                         opener=routed_opener([], backup=backup_reply(content)))

    def test_backup_reply_without_choices_is_unavailable(self):
        with pytest.raises(GraderUnavailable):
            grader.grade(GOOD_REASON, key="", backup="sk-or-test",
                         opener=routed_opener([], backup={"error": "nope"}))


class TestParseBackup:
    def test_reads_json_inside_other_text(self):
        out = grader.parse_backup("Here you go:\n```json\n" + THIN_JSON + "\n```")
        assert out["label"] == "thin" and out["graded_by"] == "backup"

    def test_solid_and_hype_flags(self):
        out = grader.parse_backup('{"setup": true, "size": true, "exit": true, "hype": true, "grade": 2}')
        assert out["label"] == "solid" and out["missing"] == [] and out["hype"] is True

    @pytest.mark.parametrize("text", [
        '{"setup": "yes", "size": true, "exit": true, "hype": false, "grade": 2}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": 3}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": -1}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": true}',
        '{"setup": true, "size": true, "exit": true, "hype": false, "grade": "2"}',
        '{"setup": true, "size": true, "exit": true, "grade": 2}',
        "not json at all",
    ])
    def test_rejects_anything_off_contract(self, text):
        with pytest.raises(GraderUnavailable):
            grader.parse_backup(text)


class TestEnabled:
    def test_on_with_only_the_backup_key(self, monkeypatch):
        monkeypatch.setenv(grader.BACKUP_KEY_ENV, "sk-or-test")
        assert grader.enabled() is True

    def test_off_without_a_key(self, monkeypatch):
        monkeypatch.delenv(grader.KEY_ENV, raising=False)
        assert grader.enabled() is False

    def test_off_with_a_blank_key(self, monkeypatch):
        monkeypatch.setenv(grader.KEY_ENV, "   ")
        assert grader.enabled() is False

    def test_on_with_a_key(self, monkeypatch):
        monkeypatch.setenv(grader.KEY_ENV, "vck_test")
        assert grader.enabled() is True


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
