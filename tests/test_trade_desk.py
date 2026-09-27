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
    """FakeAlpaca plus GET /v2/orders/<id> answering with a fill."""

    def __call__(self, method, url, headers, body):
        path = url.split(".markets", 1)[1]
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
