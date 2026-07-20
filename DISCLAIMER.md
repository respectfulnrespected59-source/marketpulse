# MarketPulse — Important Risk Disclosures

**Last updated: 2026-07-20**

Read this before using MarketPulse. By using this software you acknowledge that you have read and understood it.

---

## 1. Not financial advice

MarketPulse is an **educational and informational tool**. It is not financial, investment, tax, accounting, or legal advice, and nothing it displays is a recommendation to buy, sell, or hold any security, option, cryptocurrency, or other instrument.

Quantum Melanin Media is **not** a registered investment adviser, broker-dealer, futures commission merchant, or commodity trading advisor, and is not registered with the SEC, FINRA, CFTC, NFA, or any equivalent authority in any jurisdiction. Using this software creates **no advisory, fiduciary, or brokerage relationship** of any kind.

The software's output — including any signal, score, label, "lean," "nudge," suggested spread, suggested strangle, probe plan, or scan result — is the mechanical output of published technical formulas applied to third-party data. **It is a description, not a prediction, and not an instruction.**

Every decision you make with your money is yours alone.

---

## 2. Options carry substantial risk

Options trading is **not suitable for all investors** and carries a high level of risk.

- You can lose **your entire investment**, and you can lose it quickly.
- Certain strategies — including uncovered/naked positions and multi-leg spreads — can produce losses **exceeding your initial investment**.
- Options lose value as they approach expiration. A correct directional view can still lose money on timing alone.
- Assignment, early exercise, liquidity gaps, and wide bid/ask spreads can all produce outcomes materially worse than any modeled result.

Before trading options, read the Options Clearing Corporation's *Characteristics and Risks of Standardized Options* ("the ODD"), which your broker is required to provide, and which is available from the OCC. If any part of it is unclear, do not trade options until it is.

Cryptocurrency markets carry their own risks, including extreme volatility, 24/7 trading, thin liquidity, exchange failure, and — in many jurisdictions — limited or no regulatory protection.

**Never trade with money you cannot afford to lose entirely.**

---

## 3. Proof Mode, backtests, and simulated results

Proof Mode produces **hypothetical, simulated results based on historical data**. Simulated performance has inherent and severe limitations. In particular:

- It is prepared **with the benefit of hindsight**. The strategy parameters are known after the fact.
- It involves **no financial risk** and no emotional pressure. No simulated record can account for how a person actually behaves during a drawdown.
- It may not fully account for **slippage, spread, commissions, fees, taxes, partial fills, liquidity constraints, halts, gaps, or the market impact** of the order itself.
- It cannot account for **future market conditions**, regime changes, or events that have never occurred before.

**Past performance is not indicative of future results. Simulated past performance is weaker evidence still.**

No representation is made that any account will or is likely to achieve profits or losses resembling any result shown. A backtest curve is a description of what already happened under a set of assumptions. It is **not a projection, not an expected return, and not a promise**.

---

## 4. Data accuracy

MarketPulse retrieves data from free third-party sources, which at time of writing include CoinGecko, Yahoo Finance, and Coinbase. That data may be **delayed, incomplete, adjusted, mis-split, cached, rate-limited, or simply wrong**. Sources may change, break, or disappear without notice.

No warranty is made as to the accuracy, timeliness, completeness, or availability of any data displayed. Do not rely on MarketPulse as a source of record for prices, quotes, chains, or fills. **Verify against your broker before acting.**

---

## 5. The automated agent layer (Pro)

The optional agent is **paper-first by design**: it defaults to `propose` mode and to paper trading, and it will not transmit an order without passing its guardrail checks.

Those guardrails — spend caps, staleness checks, symbol allowlists, slippage bands, drawdown limits, and a consecutive-loss circuit breaker — are **risk-management tooling, not guarantees**. They can be misconfigured, bypassed, or defeated by market conditions such as gaps, halts, or outages. They reduce certain categories of error. They do not make trading safe, and they do not make losses unlikely.

If you configure the agent for live trading with real credentials, **you are solely responsible** for every order it transmits, for the correctness of your configuration, and for compliance with your broker's terms and with all laws applicable to you. Test in paper mode first, and for long enough to see it behave badly.

---

## 6. No warranty; limitation of liability

This software is provided **"as is," without warranty of any kind**, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, accuracy, and non-infringement.

To the maximum extent permitted by applicable law, Quantum Melanin Media and its author shall not be liable for any direct, indirect, incidental, special, consequential, exemplary, or punitive damages — including **trading losses, lost profits, lost data, or business interruption** — arising from or relating to your use of, or inability to use, this software, regardless of the theory of liability and even if advised of the possibility of such damages.

---

## 7. Your jurisdiction

Financial regulation differs by country, state, and province. You are responsible for determining whether your use of this software, and any activity you undertake with it, is lawful where you live. Nothing here is an offer or solicitation in any jurisdiction where such an offer would be unlawful.

---

## 8. Purchases

Any purchase grants a license to **use the software**. It does not purchase advice, a service, a managed account, a signal subscription, or any promise of performance. Refund terms are those stated on the storefront at the time of purchase.

---

> **The brand rule, stated plainly:** this tool will not lie to you about getting rich.
> Most options trades lose. Survival is the real skill, and that is what the
> software is built to teach.

---

*This document is a good-faith risk disclosure written to industry-standard patterns. It is not legal advice and it is not a substitute for review by a qualified attorney in your jurisdiction. Software that analyzes markets and can transmit orders sits in a regulated area; obtain professional review before selling it.*
