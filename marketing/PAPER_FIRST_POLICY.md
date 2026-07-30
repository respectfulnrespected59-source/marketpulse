::: cover

**QUANTUM MELANIN MEDIA**
*presents*

# Paper First
## The MarketPulse Launch Policy

*Why the agent ships unable to spend your money*

A Quantum Melanin Media Production
*MarketPulse Agent — v1.0*

*"The tool doesn't earn your money until it's earned your trust."*

:::

# The Policy

> *Nobody's real money is exposed on day one.
> Not yours. Not a buyer's. Not by accident.*

## One line

**`MODE=auto` ships locked.** Version one of the MarketPulse agent does exactly
two things: it proposes trades, and it waits for a human to approve them. It
cannot place an order on its own, and it cannot touch a live account, because
both are switched off in the code you receive.

That is not a missing feature. It is the feature.

---

## Why a launch needs this

A trading agent is the one kind of software where a bug doesn't cost the buyer
time — it costs them money. Every other product gets to iterate in public.
This one doesn't.

So the launch question isn't *"is it ready?"* It's *"what is the worst thing a
bug can do on day one?"* With `auto` locked and paper as the default, the honest
answer is: **nothing you can't undo.**

---

# What Ships Locked

## The three defaults

| Setting | Ships as | What it means |
|---------|----------|---------------|
| `MP_AGENT_MODE` | `propose` | The agent writes proposals. A human runs `approve` before anything is sent. |
| `MP_ALPACA_PAPER` | `true` | Orders go to Alpaca's paper endpoint. No real position, no real money. |
| Broker keys | *unset* | You generate your own. They live in your environment, never in the product. |

Flipping any of these is a deliberate act by the person who owns the account.
There is no setting we ship that quietly graduates you.

## Bring your own key

The agent never logs into a broker for you and never asks for a brokerage
password. You create your own API key, on your own account, and the software
executes **your** rules against it.

That distinction matters legally as much as practically: this is a tool you
operate, not a service that trades on your behalf.

---

# What Week One Produces

> *A month of "trust me" is worth less than a week of receipts.*

## The paper record

Week one isn't a waiting period. It's the product generating the only evidence
that should ever convince someone to go live:

::: hero
### What you get
*Written to the audit log, every run.*

**Every proposal** — symbol, side, price, and the rule that fired it
**Every approval and rejection** — with a human's timestamp on it
**Every guardrail refusal** — what tripped, and why
**Every outcome** — what the position actually did afterward
:::

## What it's for

At the end of a week you can answer the question that matters, with data
instead of hope: *did my rules do what I thought they'd do?*

Most people discover the answer is no. That's the week doing its job. Finding
that out on paper costs a week. Finding it out live costs a pot.

---

# What Unlocks Live

## Per user. On their own record.

There is no date on which the product "goes live" for everybody. Live mode is
unlocked one trader at a time, by that trader, once **their** strategy has a
paper record **they** are willing to stand behind.

::: row
::: hero
### The honest sequence
*What we ask of every user.*

**1.** Write your rules
**2.** Backtest them — watch them lose
**3.** Paper them for a week minimum
**4.** Read your own audit log
**5.** Then decide
:::
::: villain
### What we won't do
*No matter who asks.*

**Ship `auto` unlocked** — not as a default, not as a toggle in v1
**Promise a return** — the backtest shows losses on purpose
**Trade for you** — your key, your account, your rules
**Rush step 3** — a week is the floor, not the target
:::
:::

---

# The Guardrails Hold Regardless

Independent of mode, every order must clear a single chokepoint before it can
be sent. Not one of these is bypassed by flipping to live.

| Control | What it refuses |
|---------|-----------------|
| Spend cap | Any order past the per-trade or daily limit |
| Kill switch | Everything, the moment a halt is set |
| Staleness | A proposal older than its time-to-live |
| Symbol allow-list | Anything outside your declared universe |
| Slippage | A fill when the market has moved against you |
| **No live price** | **Sending blind — it refuses rather than guess** |
| Circuit breaker | Trading after a drawdown or a losing streak |

That last one is worth saying plainly: if the agent cannot get a fresh price,
it does not send the order. It fails closed. Every control here fails closed.

---

# Why This Is Also The Better Pitch

> *"We ran it on paper for a month, and here's the log"
> outsells any feature list ever written.*

The honest launch and the good launch are the same launch.

A trading product that ships unable to lose your money is making a claim its
competitors can't copy without changing their product. And the paper record it
generates in week one becomes the marketing asset — real proposals, real
refusals, real outcomes, published win or lose.

That is the whole MarketPulse brand in one policy: **the truth is the product.**

---

## The line we hold

Most people don't lose because they were wrong. They lose because they were
too big when they were wrong.

You can't compound from zero. This won't pick winners for you — it's built to
keep you sized like someone who intends to still be trading next year.

::: end-credits
**— PAPER FIRST · v1.0 —**

*Quantum Melanin Media · MarketPulse Agent*

*Educational tool. Not financial advice. Most probes lose — that's the design.*

*The flame is not yours alone. Pass it on.*
:::
