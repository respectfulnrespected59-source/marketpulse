# Para-Sail options — pre-registered forward test

**Registered:** 2026-09-30, before any trade under these rules. Nothing below changes after the first trade;
a change starts a new test with a new date.

## Why a forward test
There is no free historical options data, so the stock/crypto Para-Sail backtest (`parasail.py`, 5 years,
8 assets) cannot be repeated for options. The only honest test is forward, on paper, with every trade kept —
winners and losers — and the pass/fail line decided now, not after the results are in.

The trade that started it: TSLA put debit spread +355P/−350P, exp 2026-09-30, opened from the app's own
signal ("Load the signal's spread") with TSLA at its 30-day low, closed near max the next morning for
+$714.20 on three contracts. At the 4 PM close the same spread was worth $0.19. That is one trade, and it is
**not** part of this test (it was opened before the rules existed).

## The rules (code: `static/options-parasail.js`, pinned by `tests/test_options_parasail.py`)
| Rule | Exact setting |
|---|---|
| Entry | The app's signal spread ("Load the signal's spread") — the signal picks direction, strikes and expiry |
| On plan: **bounce** | a CALL spread with the stock inside its 8 % low zone (close within 8 % of the lowest close of the last 30 calendar days) |
| On plan: **breakdown** | a PUT spread with the stock within 2 % of that 30-day low |
| Off plan | anything else — it may be opened, and it is scored separately |
| Cap | a spread costing more than **10 % of equity** is off plan |
| Para-sail | once the position is up **+40 %** on what it cost, after the commission to open and the one to close: close half (one contract = the whole position). Once per trade. |
| Time parachute | from **12:00 New York time on expiry day**: take it or cut it |
| News cord | withdrawals halted, bankruptcy, delisting, fraud charges, the team gone → close |
| Fills | the book's existing rules: buy at the ask, sell at the bid, $0.65 per leg per contract each way, marks never at the mid, chain ~15 min delayed |

## What counts
- A **trade** = one opened position. A para-sail half and the rest closed later are the same trade.
- Only positions opened after this date through the app, carrying a `setup`, are scored.
- Every closed trade counts — expired worthless, cut at the parachute, closed at a loss. Nothing is deleted.

## The verdict — decided now
- **At 25 trades**, one number decides it: **expectancy after every cost > $0 per trade** → *pass*.
  Anything else → *fail*.
- Reported next to it, whatever the verdict: win rate, average win, average loss, on-plan vs off-plan totals,
  the worst trade.
- A pass means the rules had an edge over those 25 trades on paper. It is not a guarantee, and it is not
  advice. A fail is reported the same way, in the app and in the class.
