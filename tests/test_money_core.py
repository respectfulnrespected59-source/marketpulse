"""The money-safety core: credentials, paper vs live, market hours, order ids,
live ceilings, and the one approve() both the CLI and the app use.

Alpaca is replaced by FakeAlpaca, a transport that behaves like the parts of
the real API this agent touches (facts read from alpacahq/alpaca-py):
  - paper and live are different base URLs; keys only work on their own one
  - notional orders are market orders; exactly one of qty / notional
  - client_order_id must be unique: a repeat is rejected with 422
  - a stock DAY order sent while the market is closed is QUEUED for the open,
    which is why the guardrails refuse stock orders while closed
  - /v2/positions/{sym} answers 404 when nothing is held
"""
from __future__ import annotations

import json
import os
import stat
import time
from decimal import Decimal

import pytest

import agent_config as config
import broker
import credentials
import desk
import guardrails
import store

pytestmark = pytest.mark.unit

PAPER_KEY, LIVE_KEY = "PKTESTKEY0000000001", "AKTESTKEY0000000001"
SECRET = "s3cretS3cretS3cretS3cretS3cretS3cret0001"


class FakeAlpaca:
    def __init__(self, *, market_open=True, price=100.0, held=None):
        self.market_open = market_open
        self.price = price
        self.held = dict(held or {})           # {"AAPL": "0.5"}
        self.orders = []                       # every accepted order body
        self.seen_client_ids = set()
        self.calls = []                        # (method, url)

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        key = headers.get("APCA-API-KEY-ID", "")
        live_base = url.startswith("https://api.alpaca.markets")
        paper_base = url.startswith("https://paper-api.alpaca.markets")
        if (live_base and not key.startswith("AK")) or (paper_base and not key.startswith("PK")):
            return 401, json.dumps({"message": "unauthorized."})
        path = url.split(".markets", 1)[1]
        if path == "/v2/account":
            return 200, json.dumps({"status": "ACTIVE", "equity": "1000", "buying_power": "1000",
                                    "trading_blocked": False, "account_blocked": False})
        if path == "/v2/clock":
            return 200, json.dumps({"is_open": self.market_open})
        if path.startswith("/v2/stocks/") and path.endswith("/trades/latest"):
            return 200, json.dumps({"trade": {"p": self.price}})
        if path.startswith("/v1beta3/crypto/us/latest/trades"):
            sym = path.split("symbols=", 1)[1]
            return 200, json.dumps({"trades": {sym: {"p": self.price}}})
        if path == "/v2/positions":
            return 200, json.dumps([{"symbol": s, "qty": q, "unrealized_pl": "0"} for s, q in self.held.items()])
        if path.startswith("/v2/positions/"):
            sym = path.rsplit("/", 1)[1]
            if sym not in self.held:
                return 404, json.dumps({"message": "position does not exist"})
            return 200, json.dumps({"symbol": sym, "qty": self.held[sym], "unrealized_pl": "1.25"})
        if path == "/v2/orders" and method == "POST":
            order = json.loads(body)
            cid = order.get("client_order_id")
            if cid in self.seen_client_ids:
                return 422, json.dumps({"code": 40010001, "message": "client_order_id must be unique"})
            self.seen_client_ids.add(cid)
            self.orders.append(order)
            return 200, json.dumps({"id": f"ord-{len(self.orders)}", "status": "accepted",
                                    "client_order_id": cid})
        return 404, json.dumps({"message": f"unhandled {method} {path}"})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    for var in ("MP_ALPACA_KEY_ID", "MP_ALPACA_SECRET", "MP_ALPACA_PAPER"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def alpaca(monkeypatch):
    fake = FakeAlpaca()
    monkeypatch.setattr(broker, "_TRANSPORT", fake)
    return fake


def connect(mode="paper"):
    credentials.save(credentials.Credentials(PAPER_KEY if mode == "paper" else LIVE_KEY, SECRET, mode))


def proposal(pid="p1", symbol="AAPL", side="buy", notional="20", kind="stock", ref=100.0, age=0):
    p = {"id": pid, "ts": time.time() - age, "kind": kind, "symbol": symbol, "side": side,
         "notional": notional if side == "buy" else None, "ref_price": ref, "status": "pending"}
    store.add_proposal(p)
    return p


# ------------------------------------------------------------------ credentials
def test_credentials_round_trip_and_never_expose_the_secret():
    connect("paper")
    c = credentials.load()
    assert c.key_id == PAPER_KEY and c.mode == "paper"
    shown = credentials.masked(c)
    assert SECRET not in json.dumps(shown) and PAPER_KEY not in json.dumps(shown)
    assert shown["key_id_last4"] == PAPER_KEY[-4:]


def test_credentials_file_is_owner_only():
    connect("paper")
    path = os.path.join(config.DATA_DIR, credentials.FILE)
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


def test_bad_mode_or_malformed_keys_are_refused():
    with pytest.raises(ValueError):
        credentials.Credentials(PAPER_KEY, SECRET, "yolo")
    with pytest.raises(ValueError):
        credentials.Credentials("not a key!", SECRET, "paper")


def test_disconnect_forgets_the_keys():
    connect("paper")
    credentials.clear()
    assert credentials.load() is None


def test_env_keys_still_work_for_the_cli(monkeypatch):
    monkeypatch.setenv("MP_ALPACA_KEY_ID", PAPER_KEY)
    monkeypatch.setenv("MP_ALPACA_SECRET", SECRET)
    assert credentials.load().mode == "paper"


# ------------------------------------------------------------------ broker
def test_paper_keys_talk_to_the_paper_url_and_live_keys_to_live(alpaca):
    connect("paper")
    broker.account()
    connect("live")
    broker.account()
    bases = [u.split("/v2")[0] for m, u in alpaca.calls]
    assert bases == ["https://paper-api.alpaca.markets", "https://api.alpaca.markets"]


def test_verify_checks_keys_against_their_own_mode_before_saving(alpaca):
    assert broker.verify(credentials.Credentials(PAPER_KEY, SECRET, "paper"))["status"] == "ACTIVE"
    with pytest.raises(broker.AuthError):  # paper keys declared as live
        broker.verify(credentials.Credentials(PAPER_KEY, SECRET, "live"))


def test_every_order_carries_its_client_order_id(alpaca):
    connect("paper")
    broker.submit_order("AAPL", "buy", notional="20", client_order_id="p1")
    assert alpaca.orders[0]["client_order_id"] == "p1"
    assert alpaca.orders[0]["type"] == "market" and alpaca.orders[0]["time_in_force"] == "day"


def test_order_status_can_be_read_but_money_cannot_move():
    broker._assert_allowed("GET", "/v2/orders/ord-1")
    for method, path in (("POST", "/v2/account/configurations"), ("DELETE", "/v2/positions"),
                         ("POST", "/v2/transfers"), ("DELETE", "/v2/orders")):
        with pytest.raises(broker.DisallowedEndpointError):
            broker._assert_allowed(method, path)


# ------------------------------------------------------------------ live ceilings
def test_live_caps_can_never_exceed_25_per_trade_and_100_per_day(monkeypatch):
    monkeypatch.setattr(config, "MAX_SINGLE_TX_USD", Decimal("5000"))
    monkeypatch.setattr(config, "MAX_DAILY_SPEND_USD", Decimal("50000"))
    assert config.caps("live") == (Decimal("25"), Decimal("100"))
    assert config.caps("paper") == (Decimal("5000"), Decimal("50000"))


def test_a_lower_configured_cap_still_wins_in_live(monkeypatch):
    monkeypatch.setattr(config, "MAX_SINGLE_TX_USD", Decimal("10"))
    assert config.caps("live")[0] == Decimal("10")


def test_paper_spend_does_not_use_up_the_live_daily_budget():
    store.record_spend("90", "AAPL", "o1", mode="paper")
    guardrails.check_spend(Decimal("25"), mode="live")        # live budget untouched
    store.record_spend("90", "AAPL", "o2", mode="live")
    with pytest.raises(guardrails.SpendLimitError):
        guardrails.check_spend(Decimal("25"), mode="live")    # 90 + 25 > 100


def test_live_single_trade_over_25_is_refused():
    with pytest.raises(guardrails.SpendLimitError):
        guardrails.check_spend(Decimal("25.01"), mode="live")


# ------------------------------------------------------------------ market hours + live permission
def test_stock_orders_are_refused_while_the_market_is_closed():
    with pytest.raises(guardrails.MarketClosedError):
        guardrails.check_market_open({"kind": "stock"}, {"is_open": False})
    with pytest.raises(guardrails.MarketClosedError):
        guardrails.check_market_open({"kind": "stock"}, None)   # unknown = closed
    guardrails.check_market_open({"kind": "crypto"}, None)       # crypto trades 24/7


def test_live_is_refused_unless_permitted():
    with pytest.raises(guardrails.LiveNotPermittedError):
        guardrails.check_live_permitted("live", False)
    guardrails.check_live_permitted("live", True)
    guardrails.check_live_permitted("paper", False)


# ------------------------------------------------------------------ desk.approve
def test_approve_happy_path_paper(alpaca):
    connect("paper")
    proposal()
    r = desk.approve("p1", live_permitted=False)
    assert r["ok"] and r["status"] == "submitted" and r["mode"] == "paper"
    assert store.get_proposal("p1")["status"] == "submitted"
    assert alpaca.orders[0]["notional"] == "20" and alpaca.orders[0]["client_order_id"] == "p1"
    assert store.spend_last_24h("paper") == 20.0 and store.spend_last_24h("live") == 0.0


def test_approving_twice_sends_one_order(alpaca):
    connect("paper")
    proposal()
    desk.approve("p1", live_permitted=False)
    second = desk.approve("p1", live_permitted=False)
    assert not second["ok"] and len(alpaca.orders) == 1


def test_live_without_permission_never_reaches_alpaca(alpaca):
    connect("live")
    proposal()
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and store.get_proposal("p1")["status"] == "blocked"
    assert alpaca.orders == []


def test_live_with_permission_respects_the_25_dollar_ceiling(alpaca):
    connect("live")
    proposal(notional="40")
    r = desk.approve("p1", live_permitted=True)
    assert not r["ok"] and "25" in r["message"] and alpaca.orders == []


def test_live_with_permission_sends_a_small_order(alpaca):
    connect("live")
    proposal(notional="20")
    r = desk.approve("p1", live_permitted=True)
    assert r["ok"] and r["mode"] == "live" and store.spend_last_24h("live") == 20.0


def test_market_closed_blocks_a_stock_order(alpaca):
    alpaca.market_open = False
    connect("paper")
    proposal()
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and "closed" in r["message"].lower() and alpaca.orders == []


def test_crypto_trades_while_the_stock_market_is_closed(alpaca):
    alpaca.market_open = False
    connect("paper")
    proposal(symbol="BTC/USD", kind="crypto")
    assert desk.approve("p1", live_permitted=False)["ok"]


def test_price_moved_too_far_blocks_the_order(alpaca):
    alpaca.price = 110.0          # 10% above the signal's reference price
    connect("paper")
    proposal()
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.orders == []


def test_no_keys_means_nothing_is_sent(alpaca):
    proposal()
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.calls == []


def test_a_duplicate_order_id_is_never_resent(alpaca):
    connect("paper")
    proposal()
    alpaca.seen_client_ids.add("p1")    # an earlier attempt already reached Alpaca
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and store.get_proposal("p1")["status"] == "duplicate" and alpaca.orders == []


def test_a_failed_send_never_leaves_a_proposal_stuck_in_sending(alpaca, monkeypatch):
    connect("paper")
    proposal()

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(broker, "submit_order", boom)
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and store.get_proposal("p1")["status"] == "blocked"


def test_selling_closes_the_whole_position_by_quantity(alpaca):
    alpaca.held["AAPL"] = "0.2"
    connect("paper")
    proposal(side="sell")
    r = desk.approve("p1", live_permitted=False)
    assert r["ok"] and alpaca.orders[0]["qty"] == "0.2" and "notional" not in alpaca.orders[0]


# ------------------------------------------------------------------ auto-exits only
def test_auto_pass_closes_positions_but_never_buys(alpaca):
    alpaca.held["MSFT"] = "0.1"
    connect("paper")
    proposal(pid="buy1", symbol="AAPL", side="buy")
    proposal(pid="sell1", symbol="MSFT", side="sell")
    results = desk.auto_exit_pass(live_permitted=False)
    assert [r["id"] for r in results] == ["sell1"]
    assert store.get_proposal("buy1")["status"] == "pending"
    assert store.get_proposal("sell1")["status"] == "submitted"
    assert all(o["side"] == "sell" for o in alpaca.orders)


def test_the_chokepoint_itself_refuses_live_without_permission():
    # desk.approve checks early too; this pins the layer every order must pass.
    p = {"id": "x", "symbol": "AAPL", "side": "buy", "kind": "stock", "notional": "10",
         "ref_price": 100.0, "ts": time.time()}
    with pytest.raises(guardrails.LiveNotPermittedError):
        guardrails.authorize_send(p, current_price=100.0, mode="live", clock={"is_open": True},
                                  live_permitted=False)


def test_a_rejected_proposal_can_never_be_sent_later(alpaca):
    # client_order_id stops a second send of the SAME approval; this pins the
    # other layer: only a pending proposal may ever reach Alpaca.
    connect("paper")
    proposal()
    desk.reject("p1")
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.orders == [] and store.get_proposal("p1")["status"] == "rejected"


# ------------------------------------------------------------------ review round 1 (code)
def test_an_order_alpaca_accepted_is_never_reported_as_not_sent(alpaca, monkeypatch):
    connect("paper")
    proposal()

    def disk_full(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(guardrails, "record_spend", disk_full)
    r = desk.approve("p1", live_permitted=False)
    assert r["status"] == "submitted" and r.get("order_id") == "ord-1"
    assert "SENT" in r["message"] and "record" in r["message"].lower()
    assert len(alpaca.orders) == 1


def test_a_failed_claim_is_audited_not_raised(alpaca, monkeypatch):
    connect("paper")
    proposal()
    real = store.update_proposal

    def fail_first(pid, **changes):
        if changes.get("status") == "sending":
            raise OSError("locked by another program")
        return real(pid, **changes)

    monkeypatch.setattr(store, "update_proposal", fail_first)
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.orders == []
    assert any(e["event"] == "claim_failed" for e in store.read_audit())


def test_duplicate_is_recognised_by_alpacas_error_not_a_loose_word(alpaca, monkeypatch):
    connect("paper")
    real = alpaca.__call__

    def other_422(method, url, headers, body):
        if method == "POST":  # a DIFFERENT validation error that merely mentions the field
            return 422, json.dumps({"code": 42210000, "message": "client_order_id too long"})
        return real(method, url, headers, body)

    monkeypatch.setattr(broker, "_TRANSPORT", other_422)
    with pytest.raises(broker.BrokerError) as exc:
        broker.submit_order("AAPL", "buy", notional="5", client_order_id="p1")
    assert not isinstance(exc.value, broker.DuplicateOrderError)


def test_no_position_is_a_real_404_not_a_404_somewhere_in_the_text(alpaca, monkeypatch):
    connect("paper")
    assert broker.position("AAPL") is None                     # real 404
    real = alpaca.__call__

    def server_error(method, url, headers, body):
        if "/v2/positions/" in url:
            return 500, json.dumps({"message": "upstream 404 cache miss"})
        return real(method, url, headers, body)

    monkeypatch.setattr(broker, "_TRANSPORT", server_error)
    with pytest.raises(broker.BrokerError):
        broker.position("AAPL")                                # not silently "no position"


def test_a_garbled_success_body_is_a_broker_error(monkeypatch):
    connect("paper")
    monkeypatch.setattr(broker, "_TRANSPORT", lambda *a: (200, "<html>maintenance</html>"))
    with pytest.raises(broker.BrokerError):
        broker.account()


def test_malformed_env_keys_say_why_instead_of_just_not_connected(monkeypatch):
    connect("paper")                                           # a valid file exists too
    monkeypatch.setenv("MP_ALPACA_KEY_ID", "truncated")
    monkeypatch.setenv("MP_ALPACA_SECRET", SECRET)
    assert credentials.load() is None                          # still refuses to trade
    assert "MP_ALPACA_KEY_ID" in credentials.problem()


def test_get_order_and_verify_blocked_account(alpaca, monkeypatch):
    connect("paper")
    real = alpaca.__call__

    def blocked(method, url, headers, body):
        if url.endswith("/v2/account"):
            return 200, json.dumps({"status": "ACTIVE", "trading_blocked": True})
        if "/v2/orders/ord-9" in url:
            return 200, json.dumps({"id": "ord-9", "status": "filled", "filled_avg_price": "100.02"})
        return real(method, url, headers, body)

    monkeypatch.setattr(broker, "_TRANSPORT", blocked)
    assert broker.get_order("ord-9")["status"] == "filled"
    with pytest.raises(broker.AuthError):
        broker.verify(credentials.Credentials(PAPER_KEY, SECRET, "paper"))


# ------------------------------------------------------------------ review round 1 (security)
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402


def test_concurrent_approvals_can_never_beat_the_live_daily_cap(alpaca, monkeypatch):
    # Five $25 buys approved at once: without one lock around check -> send ->
    # record they all read "$0 spent" and $125 goes out. The cap is $100.
    connect("live")
    real = alpaca.__call__

    def slow(method, url, headers, body):
        if method == "POST":
            time.sleep(0.05)          # widen the race window
        return real(method, url, headers, body)

    monkeypatch.setattr(broker, "_TRANSPORT", slow)
    for i in range(5):
        proposal(pid=f"b{i}", symbol="AAPL", notional="25")
    threads = [threading.Thread(target=desk.approve, args=(f"b{i}",), kwargs={"live_permitted": True})
               for i in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(alpaca.orders) == 4 and store.spend_last_24h("live") == 100.0


def test_the_desk_lock_holds_across_separate_processes(tmp_path):
    # The CLI and the app are different processes: an in-memory lock is not enough.
    agent_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent")
    code = (f"import sys,time; sys.path.insert(0,{agent_dir!r}); import agent_config as c; "
            f"c.DATA_DIR={str(tmp_path)!r}; import desk; "
            "l=desk.FileLock(timeout=0.2); l.acquire(); print('held', flush=True); time.sleep(1.5); l.release()")
    holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == "held"
    with pytest.raises(desk.DeskBusyError):
        with desk.FileLock(timeout=0.3):
            pass
    holder.wait(timeout=10)
    with desk.FileLock(timeout=2):   # free again once the other process let go
        pass


def test_off_universe_symbol_never_reaches_alpaca(alpaca):
    connect("paper")
    proposal(symbol="FAKE")
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.calls == []


def test_halted_desk_never_calls_alpaca(alpaca):
    connect("paper")
    proposal()
    store.engage_halt("test")
    r = desk.approve("p1", live_permitted=False)
    assert not r["ok"] and alpaca.calls == []


def test_path_traversal_cannot_slip_past_the_endpoint_allowlist():
    for path in ("/v2/orders/../account/configurations", "/v2/positions/..%2Faccount",
                 "/v2/orders/ord 1", "/v2/positions/AAPL/../../transfers",
                 "/v2/stocks/../../v2/account/configurations"):   # multi-segment prefix: only ".." stops it
        with pytest.raises(broker.DisallowedEndpointError):
            broker._assert_allowed("GET", path)


def test_duplicate_is_recognised_by_alpacas_code_too(alpaca, monkeypatch):
    connect("paper")
    monkeypatch.setattr(broker, "_TRANSPORT",
                        lambda *a: (422, json.dumps({"code": 40010001, "message": "duplicate"})))
    with pytest.raises(broker.DuplicateOrderError):
        broker.submit_order("AAPL", "buy", notional="5", client_order_id="p1")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-5", "1e999", "abc"])
def test_nonsense_order_sizes_are_refused_by_the_spend_guard(bad):
    with pytest.raises(guardrails.SpendLimitError):
        guardrails.check_spend_value(bad, mode="live")


def test_a_live_sale_far_bigger_than_the_pilot_could_build_is_stopped(alpaca):
    # Exits are uncapped by design, but a mis-read quantity must not dump a fortune.
    alpaca.held["AAPL"] = "500"            # $50,000 at $100: impossible at $100/day
    connect("live")
    proposal(side="sell")
    r = desk.approve("p1", live_permitted=True)
    assert not r["ok"] and alpaca.orders == [] and "sanity" in r["message"].lower()


def test_status_says_where_the_keys_came_from(monkeypatch):
    connect("paper")
    assert credentials.masked(credentials.load())["source"] == "file"
    monkeypatch.setenv("MP_ALPACA_KEY_ID", LIVE_KEY)
    monkeypatch.setenv("MP_ALPACA_SECRET", SECRET)
    monkeypatch.setenv("MP_ALPACA_PAPER", "false")
    shown = credentials.masked(credentials.load())
    assert shown["source"] == "env" and shown["mode"] == "live" and shown["overrides_saved_file"]


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL check")
def test_windows_keys_file_is_locked_to_this_user():
    # Make the folder readable by all local users FIRST (as a C:\\MarketPulse
    # install would be), so the test can fail if the lock does not strip it.
    subprocess.run(["icacls", config.DATA_DIR, "/grant", "*S-1-5-32-545:(OI)(CI)R"],
                   capture_output=True, check=True)
    connect("paper")
    path = os.path.join(config.DATA_DIR, credentials.FILE)
    acl = subprocess.run(["icacls", path], capture_output=True, text=True).stdout
    assert r"BUILTIN\Users" not in acl and "Everyone" not in acl and "(F)" in acl


def test_the_pro_download_ships_every_agent_module_the_cli_imports():
    import ast
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "tools"))
    import build_buyer_pack as bp
    shipped = set(bp.BASE) | set(bp.PRO_ONLY)
    seen, todo = set(), ["cli"]
    while todo:
        mod = todo.pop()
        if mod in seen or not os.path.isfile(os.path.join(root, "agent", mod + ".py")):
            continue
        seen.add(mod)
        tree = ast.parse(open(os.path.join(root, "agent", mod + ".py"), encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                todo += [a.name.split(".")[0] for a in node.names]
    missing = sorted(f"agent/{m}.py" for m in seen if f"agent/{m}.py" not in shipped)
    assert not missing, missing
