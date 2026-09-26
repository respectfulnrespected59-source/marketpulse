"""POST /api/grade-reason through the real request handler.

Runs app.Handler on a loopback port. The model call itself is faked, so these
tests pin the route's contract: what it refuses, what it spends a call on,
and what it tells the browser when the grader fails.
"""

import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import app
import grader

pytestmark = pytest.mark.unit

REASON = "RSI came off 30. $60 probe out of a $300 pot. Stop at -50%, take profit at +32%."
SOLID = {"grade": 2.0, "label": "solid", "missing": [], "hype": False,
         "checks": {"setup": 0.99, "size": 0.99, "exit": 0.99, "hype": 0.01}}


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def calls(monkeypatch):
    """Fake grader.grade and record every reason it was asked to send."""
    sent = []

    def _fake(reason, **_kw):
        sent.append(reason)
        return SOLID

    monkeypatch.setattr(grader, "grade", _fake)
    monkeypatch.setenv(grader.KEY_ENV, "sk-or-route-test-key")
    monkeypatch.setattr(app, "_GRADE_LIMITER", grader.GradeLimiter())
    return sent


def post(base, body, raw=None):
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/grade-reason", data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_grades_a_reason(server, calls):
    status, out = post(server, {"reason": REASON})
    assert status == 200
    assert out["label"] == "solid"
    assert calls == [REASON]


def test_off_without_a_key(server, calls, monkeypatch):
    monkeypatch.delenv(grader.KEY_ENV)
    status, out = post(server, {"reason": REASON})
    assert status == 503
    assert calls == []


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "moon"},
                                  {"reason": 42}, {"reason": "x" * 5000}])
def test_bad_input_is_400_and_spends_nothing(server, calls, body):
    status, out = post(server, body)
    assert status == 400
    assert out["error"]
    assert calls == []


def test_non_json_body_is_400(server, calls):
    status, _ = post(server, None, raw=b"not json")
    assert status == 400
    assert calls == []


def test_rate_limited_is_429(server, calls, monkeypatch):
    monkeypatch.setattr(app, "_GRADE_LIMITER", grader.GradeLimiter(per_client=1))
    assert post(server, {"reason": REASON})[0] == 200
    status, out = post(server, {"reason": REASON})
    assert status == 429
    assert out["error"]
    assert len(calls) == 1


def test_grader_failure_is_502_without_the_detail(server, calls, monkeypatch):
    def _down(reason, **_kw):
        raise grader.GraderUnavailable("grader HTTP 403: sk-or-route-test-key rejected")

    monkeypatch.setattr(grader, "grade", _down)
    status, out = post(server, {"reason": REASON})
    assert status == 502
    assert "sk-or-route-test-key" not in json.dumps(out)
    assert "403" not in out["error"]


def _dashboard_config():
    # Under pytest, `import config` resolves to agent/config.py (see conftest),
    # so app.config is the agent's. /api/universe needs the dashboard's.
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config.py")
    spec = importlib.util.spec_from_file_location("dashboard_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_universe_reports_the_grader_switch(server, calls, monkeypatch):
    monkeypatch.setattr(app, "config", _dashboard_config())
    with urllib.request.urlopen(f"{server}/api/universe", timeout=5) as resp:
        assert json.loads(resp.read())["grader"] is True
    monkeypatch.delenv(grader.KEY_ENV)
    with urllib.request.urlopen(f"{server}/api/universe", timeout=5) as resp:
        assert json.loads(resp.read())["grader"] is False
