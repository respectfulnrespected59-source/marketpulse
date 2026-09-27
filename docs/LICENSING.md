# MarketPulse Pro licensing (Gumroad)

Status: **built, not selling.** The four Gumroad products exist and are
**Unpublished**. The hosted app has licensing switched **off** (no
`MP_GUMROAD_PLANS`), so the license card is hidden. Owner decision
2026-09-27: flip this on the day real-money execution ships, not before.

## The four products (created 2026-09-27, all Unpublished)

| Plan | Gumroad link | Price | product_id |
|---|---|---|---|
| Pro, monthly | quantummelaninmedia.gumroad.com/l/ccjgrl | $29 / month | `25QwjcpqEWyRclleMH9ZnA==` |
| Pro+, monthly | quantummelaninmedia.gumroad.com/l/asoiy | $59 / month | `N7ZyxQvf3pmJgs4BkON1ng==` |
| Pro, lifetime | quantummelaninmedia.gumroad.com/l/utstnu | $297 once | `86DyepNN0f845qTmiZReLQ==` |
| Pro+, lifetime | quantummelaninmedia.gumroad.com/l/vemdeg | $597 once | `vpnh2xF3KEN9FC2kMBf30g==` |

Each has a **License key** block in its Content tab (that is what puts a unique
key on the buyer's receipt) plus a line telling the buyer where to paste it.
"Let customers choose the number of seats" is deliberately OFF: seats are
fixed per plan (Pro 2 devices / 1 account, Pro+ 5 devices / 3 accounts).

product_ids are not secret (every buyer's app sends them). They were read from
the license-key block, and a live verify with a made-up key returned Gumroad's
real `404 "That license does not exist for the provided product."`. That proves
the plumbing, **not** the IDs: a made-up ID gets the same answer. Launch step 4
proves them.

## How it works

See `licensing.py` (module docstring). In short: `POST /api/license/activate`
checks the key with Gumroad, judges refunds / chargebacks / disputes / ended or
failed subscriptions itself (Gumroad answers `success: true` for refunds),
consumes one seat via Gumroad's `uses` counter, and returns an HMAC-signed
token bound to that device. Pro-only calls send key + token + device in
`X-MP-License-*` headers; `app.license_entitlement(headers)` is the gate.

## Safety rails (from the 2026-09-27 security + code reviews)

- Activation is rate limited per client (10/hour) AND per key (6/hour). There is
  no shared daily cap on purpose: client identity comes from forwarding headers
  that can be spoofed, and a shared cap would let a spoofer lock every buyer out.
- The downloadable app keeps its own signing secret only because `run.bat` /
  `run.sh` set `MP_LICENSE_LOCAL=1`. Any other host without `MP_LICENSE_SECRET`
  has licensing OFF (it never mints a secret on a filesystem nobody provisioned).
- Gumroad 404 = "not this product" (wording never parsed); any other non-200
  (429, 401, 5xx, network) = unreachable, which only extends an already-verified
  key for up to 72h and never grants a first activation.
- An active status is re-checked hourly; a denial within a minute (fixed card).
- `[warn]` lines in the Render log mean: a seat was NOT released (key fingerprint
  only) or the outage grace was used. Either one repeating is worth a look.
- Buyers: the key is a password. Anyone holding it can use its seats. The
  receipt line says where to paste it; support can free seats from Gumroad.

## Launch day checklist

0. Check the Render origin (`marketpulse-22bi.onrender.com`) cannot be reached
   bypassing Cloudflare with forged `CF-Connecting-IP` headers, or accept that the
   per-key limit is the real guard (it is; the per-client one is best effort).

1. Render dashboard, marketpulse service, Environment:
   - `MP_LICENSE_SECRET` = 64 random hex chars (`python -c "import secrets;print(secrets.token_hex(32))"`).
     Set it ONCE. Changing it voids every activation and buyers would burn seats re-activating.
   - `MP_GUMROAD_PLANS` =
     `{"25QwjcpqEWyRclleMH9ZnA==":{"tier":"pro","billing":"monthly"},"N7ZyxQvf3pmJgs4BkON1ng==":{"tier":"proplus","billing":"monthly"},"86DyepNN0f845qTmiZReLQ==":{"tier":"pro","billing":"lifetime"},"vpnh2xF3KEN9FC2kMBf30g==":{"tier":"proplus","billing":"lifetime"}}`
   - `MP_GUMROAD_TOKEN` = a Gumroad access token with `edit_products` (needed to
     release a seat on "Deactivate this device" and to roll back a seat race).
2. Deploy, then `curl https://marketpulse-22bi.onrender.com/api/license` must say `"enabled": true` with 4 plans.
3. Publish the four Gumroad products.
4. **Prove it with a real purchase**: buy Pro monthly with a 100%-off or $1 offer code,
   paste the key into the app, confirm "Pro active", confirm Gumroad shows 1 use,
   deactivate, confirm 0 uses, then refund it and confirm the app turns Pro off
   within an hour (the status cache).
5. Point the landing page's Pro / Pro+ buttons at the four product links (they
   currently go to the free listing as a founding list).
