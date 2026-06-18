"""MarketPulse Agent — human control surface.

Propose-and-approve trading on Alpaca PAPER by default. The agent can never
send an order on its own: it writes proposals; you approve them here. Every
order passes the guardrails chokepoint before it reaches the broker.

Usage (from the agent/ directory):
  python cli.py status              account, mode, halt state, 24h spend
  python cli.py scan                compute signals -> new proposals
  python cli.py list                show pending proposals
  python cli.py approve <id>        authorize + send ONE proposal
  python cli.py reject  <id>        discard a proposal
  python cli.py panic  [reason]     engage kill switch (blocks all sends)
  python cli.py resume              release kill switch
  python cli.py audit  [n]          tail the decision log
"""
from __future__ import annotations

import sys
from decimal import Decimal

import broker
import config
import guardrails
import proposer
import store


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def cmd_status() -> None:
    print("\n  MarketPulse Agent")
    print(f"  mode      : {config.MODE}   ({'PAPER' if config.PAPER else 'LIVE'})")
    print(f"  endpoint  : {config.ALPACA_BASE}")
    print(f"  per-trade : {_fmt_money(config.PER_TRADE_USD)}   "
          f"single-cap {_fmt_money(config.MAX_SINGLE_TX_USD)}   "
          f"daily-cap {_fmt_money(config.MAX_DAILY_SPEND_USD)}")
    print(f"  24h spend : {_fmt_money(store.spend_last_24h())}")
    halted = store.is_halted()
    print(f"  halted    : {'YES - ' + (store.load_circuit().get('reason') or '') if halted else 'no'}")

    if not config.keys_present():
        print("\n  ! Alpaca keys not set - read-only. See agent/.env.example.\n")
        return
    try:
        acct = broker.account()
        print(f"\n  account   : {acct.get('status')}")
        print(f"  equity    : {_fmt_money(acct.get('equity'))}")
        print(f"  buying pwr: {_fmt_money(acct.get('buying_power'))}")
        pos = broker.positions()
        if pos:
            print("  positions :")
            for p in pos:
                print(f"     {p['symbol']:<10} {p['qty']:>12}  "
                      f"mv {_fmt_money(p.get('market_value'))}  "
                      f"pl {_fmt_money(p.get('unrealized_pl'))}")
        else:
            print("  positions : none")
    except guardrails.GuardrailError as exc:
        print(f"\n  ! {exc}")
    except broker.BrokerError as exc:
        print(f"\n  ! Broker error: {exc}")
    print()


def cmd_scan() -> None:
    new = proposer.scan()
    if not new:
        print("  No new proposals (no STRONG entries / exits, or all pending).")
        return
    print(f"  {len(new)} new proposal(s):")
    for p in new:
        _print_proposal(p)
    print("\n  Review, then:  python cli.py approve <id>")


def _print_proposal(p: dict) -> None:
    notional = _fmt_money(p["notional"]) if p["notional"] else "(close position)"
    print(f"   [{p['id']}]  {p['side'].upper():<4} {p['symbol']:<9} "
          f"{notional:<14} {p['label']}  score {p['score']}")
    if p.get("reasons"):
        print(f"        why: {', '.join(p['reasons'][:5])}")


def cmd_list() -> None:
    pending = [p for p in store.load_proposals() if p["status"] == "pending"]
    if not pending:
        print("  No pending proposals. Run:  python cli.py scan")
        return
    print(f"  {len(pending)} pending:")
    for p in pending:
        _print_proposal(p)


def cmd_approve(pid: str) -> None:
    p = store.get_proposal(pid)
    if not p:
        print(f"  No proposal {pid}.")
        return
    if p["status"] != "pending":
        print(f"  Proposal {pid} is '{p['status']}', not pending.")
        return

    # 1) Pull a fresh LIVE price (fail-closed). Without it we cannot bound
    #    slippage, so we refuse rather than fill blind (skill: simulate before
    #    send / mandatory min_amount_out).
    try:
        live = broker.latest_price(p["symbol"])
    except broker.BrokerError as exc:
        store.update_proposal(pid, status="blocked", note=f"no live price: {exc}")
        store.audit("blocked", {"id": pid, "reason": f"no live price: {exc}"})
        print(f"  BLOCKED: could not get a live price to bound slippage — {exc}")
        return

    # 2) Independent safety chokepoint — may raise and block the send.
    try:
        guardrails.authorize_send(p, current_price=live)
    except guardrails.GuardrailError as exc:
        store.update_proposal(pid, status="blocked", note=str(exc))
        store.audit("blocked", {"id": pid, "reason": str(exc)})
        print(f"  BLOCKED: {exc}")
        return

    # 3) Send through the broker.
    exit_pl: float | None = None  # set on exits, feeds the loss circuit breaker
    try:
        if p["side"] == "buy":
            order = broker.submit_order(p["symbol"], "buy", notional=p["notional"])
        else:
            held = broker.position(p["symbol"])
            if not held:
                store.update_proposal(pid, status="blocked", note="no position to sell")
                print("  BLOCKED: no open position to close.")
                return
            exit_pl = float(held.get("unrealized_pl", 0) or 0)
            order = broker.submit_order(p["symbol"], "sell", qty=held["qty"])
    except broker.BrokerError as exc:
        store.update_proposal(pid, status="blocked", note=str(exc))
        store.audit("send_failed", {"id": pid, "reason": str(exc)})
        print(f"  Send failed: {exc}")
        return

    oid = order.get("id")
    store.update_proposal(pid, status="submitted", broker_order_id=oid)
    if p["side"] == "buy":
        guardrails.record_spend(Decimal(str(p["notional"])), p["symbol"], oid)
    else:
        # An exit realizes a win/loss — feed the consecutive-loss breaker so a
        # losing streak can halt the agent (skill: circuit breakers).
        guardrails.record_trade_result(is_win=(exit_pl is None or exit_pl >= 0))
        store.audit("exit_result", {"id": pid, "symbol": p["symbol"],
                                    "unrealized_pl": exit_pl})
    store.audit("submitted", {"id": pid, "symbol": p["symbol"],
                              "side": p["side"], "order_id": oid})
    print(f"  SUBMITTED {p['side'].upper()} {p['symbol']}  order={oid}")


def cmd_reject(pid: str) -> None:
    updated = store.update_proposal(pid, status="rejected")
    if updated:
        store.audit("rejected", {"id": pid})
        print(f"  Rejected {pid}.")
    else:
        print(f"  No proposal {pid}.")


def cmd_panic(reason: str) -> None:
    store.engage_halt(reason or "manual kill switch")
    print(f"  KILL SWITCH ENGAGED. All sends blocked. Reason: {reason or 'manual'}")
    print("  Release with:  python cli.py resume")


def cmd_resume() -> None:
    store.release_halt()
    print("  Kill switch released. Circuit reset.")


def cmd_audit(n: int) -> None:
    rows = store.read_audit(n)
    if not rows:
        print("  Audit log empty.")
        return
    for r in rows:
        print(f"  {r['ts']}  {r['event']:<14} {r.get('detail', {})}")


def main(argv: list[str]) -> int:
    if not argv:
        cmd_status()
        return 0
    cmd, *rest = argv
    if cmd == "status":
        cmd_status()
    elif cmd == "scan":
        cmd_scan()
    elif cmd == "list":
        cmd_list()
    elif cmd == "approve" and rest:
        cmd_approve(rest[0])
    elif cmd == "reject" and rest:
        cmd_reject(rest[0])
    elif cmd == "panic":
        cmd_panic(" ".join(rest))
    elif cmd == "resume":
        cmd_resume()
    elif cmd == "audit":
        cmd_audit(int(rest[0]) if rest else 30)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
