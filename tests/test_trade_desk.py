"""The desk's supporting parts: the one-week pilot window, the locked store,
stale-proposal expiry, live-sized proposals, the background tick (auto-exits
only), fill receipts and the paper-week report."""
from __future__ import annotations

import json
import os
import threading
import time
from decimal import Decimal

import pytest

import agent_config as config
import broker
import credentials
import desk
import pilot
import proposer
import store
from test_money_core import FakeAlpaca, LIVE_KEY, PAPER_KEY, SECRET

pytestmark = pytest.mark.unit


class FillingAlpaca(FakeAlpaca):
    """FakeAlpaca plus GET /v2/orders/<id> answering with a fill, lookup by our
    client_order_id, and two ways for an order's reply to go missing."""

    lose_order_reply = False      # Alpaca takes the order, the reply never arrives
    garble_order_reply = False    # Alpaca takes the order, the reply is not JSON

    def __call__(self, method, url, headers, body):
        path = url.split(".markets", 1)[1]
        if method == "GET" and path.startswith("/v2/orders:by_client_order_id"):
            self.calls.append((method, url))
            cid = path.split("client_order_id=", 1)[1]
            if cid not in self.seen_client_ids:
                return 404, json.dumps({"message": "order not found"})
            return 200, json.dumps({"id": "ord-found", "client_order_id": cid, "status": "filled",
                                    "filled_qty": "0.2", "filled_avg_price": "100.0"})
        if method == "POST" and path == "/v2/orders" and (self.lose_order_reply or self.garble_order_reply):
            status, raw = super().__call__(method, url, headers, body)
            if self.lose_order_reply:
                raise broker.TransportError("Alpaca didn't answer (TimeoutError)")
            return status, "<html>502 bad gateway</html>"
        if method == "GET" and path.startswith("/v2/orders/"):
            self.calls.append((method, url))
            oid = path.rsplit("/", 1)[1]
            return 200, json.dumps({"id": oid, "status": "filled", "filled_qty": "0.2",
                                    "filled_avg_price": "100.0", "filled_at": "2026-09-27T15:00:00Z"})
        return super().__call__(method, url, headers, body)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    for var in ("MP_ALPACA_KEY_ID", "MP_ALPACA_SECRET", "MP_ALPACA_PAPER", "MP_OWNER_PILOT"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def alpaca(monkeypatch):
    fake = FillingAlpaca()
    monkeypatch.setattr(broker, "_TRANSPORT", fake)
    return fake


def connect(mode="paper"):
    credentials.save(credentials.Credentials(PAPER_KEY if mode == "paper" else LIVE_KEY, SECRET, mode))


def add(pid, side="buy", symbol="BTC/USD", kind="crypto", age=0, status="pending", **extra):
    p = {"id": pid, "ts": time.time() - age, "kind": kind, "symbol": symbol, "side": side,
         "notional": "20" if side == "buy" else None, "ref_price": 100.0, "status": status, **extra}
    store.add_proposal(p)
    return p


# ------------------------------------------------------------------ pilot
NOW = 1_800_000_000.0


def test_pilot_is_off_without_the_owner_flag_even_with_a_window(monkeypatch):
    monkeypatch.setenv("MP_OWNER_PILOT", "1")
    pilot.start(now=NOW)
    monkeypatch.delenv("MP_OWNER_PILOT")
    assert pilot.active(now=NOW + 60) is False


def test_pilot_cannot_start_without_the_owner_flag():
    with pytest.raises(pilot.PilotError):
        pilot.start(now=NOW)
    assert pilot.window() is None


def test_pilot_runs_exactly_one_week_then_switches_itself_off(monkeypatch):
    monkeypatch.setenv("MP_OWNER_PILOT", "1")
    pilot.start(now=NOW)
    assert pilot.active(now=NOW) is True
    assert pilot.active(now=NOW + 7 * 86400 - 1) is True
    assert pilot.active(now=NOW + 7 * 86400) is False


def test_pilot_cannot_be_restarted_while_running_but_can_be_stopped(monkeypatch):
    monkeypatch.setenv("MP_OWNER_PILOT", "1")
    pilot.start(now=NOW)
    with pytest.raises(pilot.PilotError):
        pilot.start(now=NOW + 3600)
    pilot.stop(now=NOW + 3600)
    assert pilot.active(now=NOW + 3601) is False


def test_a_damaged_pilot_file_means_no_pilot(monkeypatch):
    monkeypatch.setenv("MP_OWNER_PILOT", "1")
    with open(os.path.join(config.DATA_DIR, pilot.FILE), "w") as fh:
        fh.write("{not json")
    assert pilot.active() is False
    store.write_json(pilot.FILE, {"started": NOW, "ends": "forever"})
    assert pilot.active(now=NOW + 1) is False


# ------------------------------------------------------------------ store
def test_expire_stale_only_touches_old_pending_proposals():
    add("old", age=config.PROPOSAL_TTL + 5)
    add("fresh")
    add("old-sent", age=config.PROPOSAL_TTL + 5, status="submitted")
    assert store.expire_stale(config.PROPOSAL_TTL) == ["old"]
    status = {p["id"]: p["status"] for p in store.load_proposals()}
    assert status == {"old": "expired", "fresh": "pending", "old-sent": "submitted"}


def test_concurrent_writers_never_lose_an_update():
    add("base")

    def writer(i):
        add(f"p{i}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    threads.append(threading.Thread(target=lambda: store.update_proposal("base", status="submitted")))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = {p["id"]: p for p in store.load_proposals()}
    assert len(rows) == 21
    assert rows["base"]["status"] == "submitted"


def test_a_damaged_ledger_fails_closed_instead_of_reading_as_zero_spent(alpaca):
    connect()
    with open(os.path.join(config.DATA_DIR, "ledger.json"), "w") as fh:
        fh.write("[{broken")
    with pytest.raises(store.LedgerError):
        store.spend_last_24h("paper")
    add("p1")
    r = desk.approve("p1", live_permitted=False)
    assert r["status"] == "blocked" and "ledger" in r["message"].lower()
    assert alpaca.orders == []


# ------------------------------------------------------------------ proposer sizing
def test_live_proposals_are_sized_to_the_25_dollar_live_cap(alpaca, monkeypatch):
    monkeypatch.setattr(config, "PER_TRADE_USD", Decimal("50"))
    connect("live")
    assert proposer.single_trade_cap() == Decimal("25")
    p = proposer._make_proposal("crypto", "BTC/USD", "buy", {"label": "STRONG BUY"}, 100.0)
    assert Decimal(p["notional"]) == Decimal("25")


def test_paper_proposals_keep_the_paper_size(alpaca, monkeypatch):
    monkeypatch.setattr(config, "PER_TRADE_USD", Decimal("50"))
    connect("paper")
    p = proposer._make_proposal("crypto", "BTC/USD", "buy", {"label": "STRONG BUY"}, 100.0)
    assert Decimal(p["notional"]) == Decimal("50")


def test_no_stock_proposals_while_the_market_is_closed(alpaca, monkeypatch):
    connect()
    alpaca.market_open = False
    fetched = []
    monkeypatch.setattr(proposer.app, "fetch_stocks", lambda syms: fetched.append(syms) or [])
    monkeypatch.setattr(proposer.app, "fetch_crypto", lambda ids: [])
    proposer.scan()
    assert fetched == []
    alpaca.market_open = True
    proposer.scan()
    assert fetched and fetched[0] == config.STOCK_UNIVERSE


def test_a_scan_expires_stale_proposals_so_the_symbol_can_be_proposed_again(alpaca, monkeypatch):
    connect()
    add("old", age=config.PROPOSAL_TTL + 5)
    monkeypatch.setattr(proposer.app, "fetch_stocks", lambda syms: [])
    monkeypatch.setattr(proposer.app, "fetch_crypto",
                        lambda ids: [{"signal": {"label": "STRONG BUY", "score": 9}, "price": 100.0}])
    new = proposer.scan()
    assert store.get_proposal("old")["status"] == "expired"
    assert "BTC/USD" in {p["symbol"] for p in new}


def test_a_scan_skips_while_another_scan_holds_the_lock(alpaca, monkeypatch):
    import oslock
    called = []
    monkeypatch.setattr(proposer, "_scan_locked", lambda: called.append(1) or [])
    with oslock.FileLock(proposer.SCAN_LOCK_FILE, timeout=1):
        assert proposer.scan() == []
    assert called == []
    proposer.scan()
    assert called == [1]


# ------------------------------------------------------------------ tick / auto-exits
def test_tick_does_nothing_until_connected(alpaca):
    assert desk.tick(live_permitted=False, scan=lambda: [])["ran"] is False


def test_tick_never_sends_a_buy_even_with_auto_exits_on(alpaca):
    connect()
    desk.set_auto_exits(True)
    add("b1", side="buy")
    desk.tick(live_permitted=False, scan=lambda: [])
    assert store.get_proposal("b1")["status"] == "pending"
    assert alpaca.orders == []


def test_tick_closes_positions_only_when_auto_exits_are_on(alpaca):
    connect()
    alpaca.held = {"BTCUSD": "0.5"}
    add("s1", side="sell")
    desk.tick(live_permitted=False, scan=lambda: [])
    assert store.get_proposal("s1")["status"] == "pending"      # auto-exits default OFF
    desk.set_auto_exits(True)
    desk.tick(live_permitted=False, scan=lambda: [])
    assert store.get_proposal("s1")["status"] == "submitted"
    assert alpaca.orders[-1]["side"] == "sell" and store.get_proposal("s1")["auto"] is True


def test_live_auto_exit_without_permission_leaves_the_exit_pending_not_blocked(alpaca):
    connect("live")
    alpaca.held = {"BTCUSD": "0.1"}
    desk.set_auto_exits(True)
    add("s1", side="sell")
    desk.tick(live_permitted=False, scan=lambda: [])
    assert store.get_proposal("s1")["status"] == "pending"
    assert alpaca.orders == []


def test_settings_file_with_junk_reads_as_auto_exits_off():
    store.write_json(desk.SETTINGS_FILE, {"auto_exits": "yes"})
    assert desk.settings() == {"auto_exits": False}


# ------------------------------------------------------------------ receipts + report
def test_fill_receipts_are_read_back_from_alpaca(alpaca):
    connect()
    add("b1")
    desk.approve("b1", live_permitted=False)
    assert desk.refresh_fills() == 1
    fill = store.get_proposal("b1")["fill"]
    assert fill["status"] == "filled" and fill["qty"] == "0.2" and fill["avg_price"] == "100.0"
    assert desk.refresh_fills() == 0            # final: never asked again


def test_report_splits_paper_and_live_and_counts_auto_exits(alpaca):
    connect()
    alpaca.held = {"BTCUSD": "0.5"}
    add("b1")
    desk.approve("b1", live_permitted=False)
    add("s1", side="sell")
    desk.approve("s1", live_permitted=False, auto=True)
    add("x1", age=config.PROPOSAL_TTL + 5)
    store.expire_stale(config.PROPOSAL_TTL)
    desk.refresh_fills()
    r = desk.report(7)
    assert r["by_status"] == {"submitted": 2, "expired": 1}
    paper = r["modes"]["paper"]
    assert (paper["buys"], paper["sells"], paper["auto_sells"], paper["filled"]) == (1, 1, 1, 2)
    assert paper["bought_usd"] == pytest.approx(20.0)
    assert r["exits"] == 1 and r["exit_pl_usd"] == {"paper": 1.25}
    assert "live" not in r["modes"]


def test_cli_reject_cannot_relabel_a_sent_order(alpaca, capsys):
    import cli
    connect()
    add("b1")
    desk.approve("b1", live_permitted=False)
    cli.cmd_reject("b1")
    assert store.get_proposal("b1")["status"] == "submitted"


# ------------------------------------------------------------------ an order's reply goes missing
def test_a_lost_order_reply_is_unconfirmed_never_refused_and_counts_the_spend(alpaca):
    connect()
    alpaca.lose_order_reply = True
    add("b1")
    r = desk.approve("b1", live_permitted=False)
    assert r["status"] == "unconfirmed" and "refused" not in r["message"].lower()
    assert store.get_proposal("b1")["status"] == "unconfirmed"
    assert store.spend_last_24h("paper") == 20.0          # counted until proven unsent


def test_a_garbled_success_reply_is_unconfirmed_not_refused(alpaca):
    connect()
    alpaca.garble_order_reply = True
    add("b1")
    assert desk.approve("b1", live_permitted=False)["status"] == "unconfirmed"


def test_reconcile_finds_an_unconfirmed_order_alpaca_actually_has(alpaca):
    connect()
    alpaca.lose_order_reply = True
    add("b1")
    desk.approve("b1", live_permitted=False)
    alpaca.lose_order_reply = False
    assert desk.reconcile() == 1
    p = store.get_proposal("b1")
    assert p["status"] == "submitted" and p["broker_order_id"] == "ord-found"
    assert p["fill"]["status"] == "filled"
    assert len(alpaca.orders) == 1                         # settled by asking, never by resending


def test_reconcile_blocks_an_unconfirmed_order_alpaca_never_got():
    store.add_proposal({"id": "ghost", "ts": time.time(), "kind": "crypto", "symbol": "BTC/USD",
                        "side": "buy", "notional": "20", "ref_price": 100.0, "status": "unconfirmed"})
    fake = FillingAlpaca()
    import broker as b
    old = b._TRANSPORT
    b._TRANSPORT = fake
    try:
        connect()
        assert desk.reconcile() == 1
    finally:
        b._TRANSPORT = old
    p = store.get_proposal("ghost")
    assert p["status"] == "blocked" and "never placed" in p["note"]


def test_an_interrupted_send_is_settled_only_after_it_has_been_stuck_a_while(alpaca):
    connect()
    store.add_proposal({"id": "mid", "ts": time.time(), "kind": "crypto", "symbol": "BTC/USD",
                        "side": "buy", "notional": "20", "ref_price": 100.0, "status": "sending",
                        "sending_since": time.time()})
    assert desk.reconcile() == 0                            # a send may be in flight right now
    assert desk.reconcile(now=time.time() + desk.SEND_STUCK_S + 1) == 1
    assert store.get_proposal("mid")["status"] == "blocked"


def test_a_failed_submitted_write_still_reports_sent_never_blocked(alpaca, monkeypatch):
    connect()
    add("b1")
    real = store.update_proposal

    def flaky(pid, **changes):
        if changes.get("status") == "submitted":
            raise OSError("disk full")
        return real(pid, **changes)

    monkeypatch.setattr(store, "update_proposal", flaky)
    monkeypatch.setattr(desk.time, "sleep", lambda s: None)
    r = desk.approve("b1", live_permitted=False)
    assert r["ok"] is True and r["status"] == "submitted" and "Do NOT approve it again" in r["message"]
    assert len(alpaca.orders) == 1
    assert real("b1")["status"] == "sending"                # can't be approved again
    monkeypatch.setattr(store, "update_proposal", real)
    assert desk.approve("b1", live_permitted=False)["ok"] is False
    assert len(alpaca.orders) == 1


def test_unreadable_positions_stop_the_scan_instead_of_proposing_a_second_buy(alpaca, monkeypatch):
    connect()
    monkeypatch.setattr(broker, "positions", lambda: (_ for _ in ()).throw(broker.BrokerError("503")))
    monkeypatch.setattr(proposer.app, "fetch_stocks", lambda syms: [])
    monkeypatch.setattr(proposer.app, "fetch_crypto",
                        lambda ids: [{"signal": {"label": "STRONG BUY", "score": 9}, "price": 100.0}])
    assert proposer.scan() == []
    assert store.load_proposals() == []


def test_concurrent_audit_lines_never_interleave():
    def burst(i):
        for j in range(25):
            store.audit("probe", {"i": i, "j": j, "pad": "x" * 200})

    threads = [threading.Thread(target=burst, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(os.path.join(config.DATA_DIR, "audit.log.jsonl"), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 200 and all(json.loads(ln)["event"] == "probe" for ln in lines)


def test_fill_receipts_read_the_oldest_unresolved_orders_first(alpaca, monkeypatch):
    for i in range(12):
        store.add_proposal({"id": f"o{i:02d}", "ts": time.time() + i, "kind": "crypto", "symbol": "BTC/USD",
                            "side": "buy", "notional": "20", "status": "submitted",
                            "broker_order_id": f"ord-{i}"})
    connect()
    asked = []
    monkeypatch.setattr(broker, "get_order", lambda oid: asked.append(oid) or {"status": "filled"})
    desk.refresh_fills(limit=10)
    assert asked[:2] == ["ord-0", "ord-1"] and len(asked) == 10
    desk.refresh_fills(limit=10)
    assert asked[-2:] == ["ord-10", "ord-11"]


def test_exit_pl_lives_on_the_proposal_not_the_audit_tail(alpaca, monkeypatch):
    connect()
    alpaca.held = {"BTCUSD": "0.5"}
    add("s1", side="sell")
    desk.approve("s1", live_permitted=False)
    assert store.get_proposal("s1")["exit_pl"] == 1.25
    monkeypatch.setattr(store, "read_audit", lambda limit=50: [])
    assert desk.report(7)["exit_pl_usd"] == {"paper": 1.25}
