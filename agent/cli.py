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
  python cli.py tick                one background pass: expire, scan, auto-exits (if on)
  python cli.py report [days]       what the agent did (paper vs live), default 7 days
  python cli.py pilot start|stop|status   the owner's one-week live pilot window
  python cli.py strategy init       write a starter rules file you then edit
  python cli.py strategy validate   check your rules before they trade
  python cli.py strategy show       print the rules currently in force
  python cli.py strategy fields     list every field a condition can use
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import broker
import agent_config as config
import credentials
import desk
import guardrails
import pilot
import proposer
import store


def _owner_pilot() -> bool:
    """The CLI's live permission: the owner's pilot, which needs MP_OWNER_PILOT=1
    on the owner's own machine AND a started, unexpired one-week window
    (pilot.py). The app also accepts a Pro license."""
    return pilot.active()


def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def cmd_status() -> None:
    creds = credentials.load()
    mode = creds.mode if creds else "paper"
    single, daily = config.caps(mode)
    print("\n  MarketPulse Agent")
    print(f"  mode      : {config.MODE}   ({mode.upper()})"
          + ("   live allowed: " + ("yes (owner pilot)" if _owner_pilot() else "NO") if mode == "live" else ""))
    print(f"  endpoint  : {broker.trading_base(creds) if creds else '(not connected)'}")
    if creds:
        shown = credentials.masked(creds)
        print(f"  keys from : {shown['source']}" + ("   ! these ENV keys override the keys saved in the app"
                                                  if shown["overrides_saved_file"] else ""))
    print(f"  per-trade : {_fmt_money(config.PER_TRADE_USD)}   "
          f"single-cap {_fmt_money(single)}   daily-cap {_fmt_money(daily)}")
    print(f"  24h spend : {_fmt_money(store.spend_last_24h(mode))} ({mode})")
    halted = store.is_halted()
    print(f"  halted    : {'YES - ' + (store.load_circuit().get('reason') or '') if halted else 'no'}")

    if creds is None:
        why = credentials.problem()
        print("\n  ! Alpaca not connected - read-only. "
              + (why if why else "Add keys in the app's Trade desk or see agent/.env.example.") + "\n")
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
    """Same single path the app uses: desk.approve (lock, live permission,
    fresh price, market hours, chokepoint, idempotent send)."""
    r = desk.approve(pid, live_permitted=_owner_pilot())
    # Key off the STATUS: an order Alpaca accepted is "submitted" even if our
    # own bookkeeping hiccuped afterwards, and must never read as "not sent".
    sent = r.get("status") == "submitted"
    print("  " + ("SUBMITTED " if sent else "NOT SENT: ") + r["message"]
          + (f"  order={r['order_id']}" if r.get("order_id") else ""))


def cmd_reject(pid: str) -> None:
    # desk.reject, not a raw store write: only a PENDING proposal can be
    # rejected, under the approval lock, so a sent order is never relabelled.
    print("  " + desk.reject(pid)["message"])


def cmd_tick() -> None:
    print("  ", desk.tick(live_permitted=_owner_pilot()))


def cmd_report(days: float) -> None:
    r = desk.report(days)
    print(f"\n  Last {r['days']:g} days: {r['proposed']} proposals  {r['by_status']}")
    for mode, m in sorted(r["modes"].items()):
        print(f"  {mode.upper():<6} buys {m['buys']}  sells {m['sells']} (auto {m['auto_sells']})  "
              f"filled {m['filled']}  bought {_fmt_money(m['bought_usd'])}")
    for mode, pl in sorted(r["exit_pl_usd"].items()):
        print(f"  {mode.upper():<6} P/L at exit over {r['exits']} closes: {_fmt_money(pl)}")
    print()


def cmd_pilot(args: list[str]) -> int:
    sub = (args[0] if args else "status").lower()
    try:
        if sub == "start":
            w = pilot.start()
            print(f"  Live pilot started. It ends by itself on {pilot.status()['ends']} (UTC).")
            print(f"  Caps: {_fmt_money(config.LIVE_MAX_SINGLE_TX_USD)} a trade, "
                  f"{_fmt_money(config.LIVE_MAX_DAILY_SPEND_USD)} a day.")
            return 0 if w else 1
        if sub == "stop":
            pilot.stop()
            print("  Live pilot stopped. Live orders are refused again.")
            return 0
    except pilot.PilotError as exc:
        print(f"  {exc}")
        return 1
    print("  ", pilot.status())
    return 0


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


def cmd_strategy(args: list[str]) -> int:
    """init / validate / show / fields — the trader's own rules."""
    import json
    import strategy

    path = os.path.join(config.HERE, strategy.STRATEGY_FILENAME)
    sub = (args[0] if args else "show").lower()

    if sub == "fields":
        print("\nFields you can use in a condition:\n")
        for name, why in strategy.FIELDS.items():
            print(f"  {name:<16} {why}")
        print("\nOperators: " + ", ".join(strategy.OPERATORS))
        print("Group conditions under 'all' (every one) or 'any' (one is enough).\n")
        return 0

    if sub == "init":
        if os.path.exists(path) and "--force" not in args:
            print(f"{path} already exists. Re-run with --force to overwrite it.")
            return 2
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(strategy.TEMPLATE, fh, indent=2)
            fh.write("\n")
        print(f"Wrote {path}")
        print("Edit it, then run:  python cli.py strategy validate")
        print("It is an EXAMPLE, not advice. Backtest it, then paper it.")
        return 0

    if sub in ("validate", "show"):
        if not os.path.isfile(path):
            print(f"No strategy at {path}")
            print("Run:  python cli.py strategy init")
            return 2
        try:
            doc = strategy.load(path)
        except strategy.StrategyError as exc:
            print(str(exc))
            return 1
        entry = doc.get("entry") or {}
        exit_rules = doc.get("exit") or {}
        sizing = doc.get("sizing") or {}
        print(f"\n  {doc['name']}  ({doc.get('kind', 'stock')})")
        print(f"  universe   {', '.join(doc.get('universe', []))}")
        print(f"  entry      {'all of' if 'all' in entry else 'any of'}:")
        for cond in entry.get("all") or entry.get("any") or []:
            print(f"               {cond[0]} {cond[1]} {cond[2]}")
        if exit_rules:
            bits = []
            if exit_rules.get("stop_loss_pct"):
                bits.append(f"stop -{exit_rules['stop_loss_pct']}%")
            if exit_rules.get("take_profit_pct"):
                bits.append(f"target +{exit_rules['take_profit_pct']}%")
            for cond in exit_rules.get("all") or exit_rules.get("any") or []:
                bits.append(f"{cond[0]} {cond[1]} {cond[2]}")
            print("  exit       " + (" · ".join(bits) if bits else "(none)"))
        print(f"  size       ${sizing.get('notional', config.PER_TRADE_USD)} "
              f"per trade, max {sizing.get('max_open', '—')} open")
        print("\n  Valid. Backtest it, then run it on paper before anything else.\n")
        return 0

    print("usage: cli.py strategy [init|validate|show|fields]")
    return 2


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
    elif cmd == "tick":
        cmd_tick()
    elif cmd == "report":
        cmd_report(float(rest[0]) if rest else 7)
    elif cmd == "pilot":
        return cmd_pilot(rest)
    elif cmd == "strategy":
        return cmd_strategy(rest)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
