# MarketPulse Classes — build plan

Curriculum: [CLASSES_CURRICULUM.md](CLASSES_CURRICULUM.md).

## Owner decisions (2026-09-29)
- Ladder: free 30s shorts → **Classes pass $19/mo** → the app. **Pro+ includes classes**; plain Pro does not.
  A Pro customer who wants classes adds the pass as a second key.
- Pass seats: **2 devices, 1 account, monthly only.**
- **Lesson 1 of every class is free**; lessons 2–5 need the pass.
- Format: **interactive on the chart with full narration** (Tess teaches, Quantus asks), then a practice
  Call on the live chart.
- **Web app only in v1**: lesson content never ships in the downloadable zip.

## Architecture
- Lessons compile to `classes/build/` (outside `static/`, which is public) and are served only by
  `/api/classes`, `/api/classes/lesson?id=`, `/api/classes/audio?id=&step=` after the license gate
  (`licensing.grants_classes`: active `classes` or `proplus`). Failures are closed: 404 unknown, 402
  locked, 429 limited. Licensing unconfigured ⇒ every paid lesson locked.
- Each lesson plays against a **frozen OHLC tape** captured once and committed, so narration and chart
  can never disagree; narration numbers are resolved from the tape at build time. Practice hands off
  to the live chart.
- Step state is derived (`lessonStateAt(lesson, i)`), so skip / back / replay-step are exact.
- Lessons draw on their own layer: the user's marks and lines are hidden during a lesson, never
  touched, and Calls are not scored on frozen data.

## Phases
0. **Tier + gate** (backend): `classes` tier, `classes.py` manifest reader, gated routes, buyer pack
   excludes `classes/`. ✅ built on `feat/classes-gate`.
1. **Content format + compiler**: `classes/src/<class>/<nn>.json`, tape capture, `tools/classes/build.py`
   (validate every step against its tape, honesty lint, Kokoro bake → MP3), DCA-01.
2. **Chart seams + pure engine**: `lessonView` guards in chart.js / chart-tools.js / learn.js,
   `static/lesson-engine.js`.
3. **Player + Classes tab**: `static/lesson-player.js`, `static/classes-ui.js`, license.js second slot,
   sw.js bump, deploy audit asserts a paid lesson is 402 without a key.
4. **Practice handoff** to the live chart.
5. **Content rollout**, one PR per class; count 402s vs Classes activations to see if the shorts convert.

## Owner steps in Gumroad
1. Create a **membership** product "MarketPulse Classes", $19/month, **license keys on**
   (confirm Gumroad offers license keys on memberships before launch).
2. Add its product id to `MP_GUMROAD_PLANS` on the host: `{"<id>": {"tier": "classes", "billing": "monthly"}}`.
3. Set `MP_CLASSES_URL` to the product page. Confirm `MP_LICENSE_SECRET` is set.
