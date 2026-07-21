"""MAPLE58 "The Robot That Refuses" VO baker — discipline-layer explainer.

Cast: Quantus = am_liam, Tess = af_heart (same locked voices as the ad pack).
Two-hander rule: Tess names the wound, Quantus shows the control. IDs are
ordered as spoken, so the LINES table reads as the running order.

GOLDEN method (matches ads_quantus_tess/bake_ad_vo.py): ONE continuous Kokoro
read per line, no splicing/effects, so delivery breathes on its own punctuation.

Kokoro gotchas applied throughout:
  - digits as words ...... "one hundred dollars", "twenty four hours"
  - abbreviations spaced .. "A I", "A P I"
  - ase ................... "ah-shay"

Usage:
  python bake_discipline_vo.py             # bake every line to vo_discipline/<id>.wav
  python bake_discipline_vo.py q_g8        # bake one line
  python bake_discipline_vo.py --dry       # no TTS; word counts + runtime estimate
Outputs 24k WAV into ./vo_discipline/.
"""
import os
import sys

SR = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, "vo_discipline")

# (id, voice, text) — am_liam = Quantus, af_heart = Tess
LINES: list[tuple[str, str, str]] = [
    # ================= ACT I — THE SETUP  (bed: nine_witches_of_mali) =========
    ("q_open",     "am_liam",  "This is my trading robot finding a setup it likes. Watch what it does next."),
    ("q_open2",    "am_liam",  "It said no. To itself. That's not a bug. That's the part I paid the most attention to."),
    ("t_wound",    "af_heart", "Here's how people actually lose money. It's never one bad call. It's a chain."),
    ("t_wound2",   "af_heart", "You take a loss, so you size up to make it back. That one loses too. Now you're mad. And mad is expensive. By Friday, the account that was supposed to teach you something is just gone."),
    ("t_wound3",   "af_heart", "Nobody blows up from being wrong once. They blow up from being wrong, then reaching."),
    ("q_turn",     "am_liam",  "So when I built the agent layer, I didn't spend the time on the part that picks. I spent it on the part that refuses."),
    ("q_turn2",    "am_liam",  "Nine separate controls. Any one of them kills an order on its own."),

    # ---- thesis (transition into Act II) ----
    ("q_thesis1",  "am_liam",  "Everybody out here selling you signals. Nobody's selling you brakes."),
    ("t_thesis",   "af_heart", "This robot's main job ain't finding trades. It's refusing them."),
    ("q_thesis2",  "am_liam",  "And the code that says no? It doesn't ask the A I for permission."),

    # ================= ACT II — THE NINE  (bed: buffalo_woman_rising) ========
    # 1 - propose, don't execute
    ("t_g1",       "af_heart", "Most bots start trading the second you turn them on."),
    ("q_g1",       "am_liam",  "Not this one. Out the box it proposes. You approve. Default mode is propose. Default account is paper. Fake money. You have to go out of your way to point it at real cash. And most bots ship the other way around. That's a choice they made about you."),
    # 2 - per-trade ceiling
    ("t_g2",       "af_heart", "Everybody's got a size they swear they'd never go past. Until the day they do."),
    ("q_g2",       "am_liam",  "So it's not a promise. It's a ceiling. No single order past one hundred dollars. Not because one hundred is magic. Because a cap you set on a calm Tuesday protects you from the version of you that shows up on a red Thursday."),
    # 3 - daily ceiling
    ("t_g3",       "af_heart", "And the day you're down? That's the day you want to keep going."),
    ("q_g3",       "am_liam",  "Four hundred dollars a day. Rolling twenty four hours. It counts what you already spent before it lets you spend more. This is the one that kills the death spiral. You cannot revenge trade past it, because the ledger says no."),
    # 4 - kill switch
    ("q_g4",       "am_liam",  "One flag. Everything stops. Manual, or automatic when something else trips. There is always a way to make it all stop."),
    # 5 - staleness
    ("t_g5",       "af_heart", "A signal fires. You step away, make a sandwich, come back."),
    ("q_g5",       "am_liam",  "Thirty minutes later that read is old news. The market moved without you. So it expires. Thirty minutes, then it's dead, and it will not send. A stale plan is a different plan."),
    # 6 - allow-list re-check
    ("t_g6",       "af_heart", "This next one sounds paranoid."),
    ("q_g6",       "am_liam",  "It is. On purpose. Right before sending, it checks the ticker against the allowed list again. Even though it already checked. Because the queue could be corrupted, tampered with, or just wrong. And the last thing you want is a bot confidently buying something nobody approved."),
    # 7 - slippage
    ("t_g7",       "af_heart", "Your edge was at that price. What about this one?"),
    ("q_g7",       "am_liam",  "It saves the price from when the signal fired, pulls the live price, and compares. Stocks. Moved more than half a percent against you? Cancel. Crypto, one and a half percent, because crypto's wilder. At a worse price, it might not be an edge at all."),
    # 8 - consecutive losses
    ("t_g8",       "af_heart", "After three losses in a row, you are not analyzing anymore. You're chasing."),
    ("q_g8",       "am_liam",  "Three losses, and it halts itself. Not a suggestion. It stops. The robot doesn't get tilted, so it can notice that you are."),
    # 9 - daily drawdown
    ("t_g9",       "af_heart", "And the whole day?"),
    ("q_g9",       "am_liam",  "It snapshots your equity when the day starts. Down five percent, everything halts. Five percent is a bad day. Five percent is survivable. It's the tenth bad day in a row that ends you. This makes sure today ends at bad, not fatal."),

    # ================= ACT III — REAL  (bed: the_lion_rises) =================
    ("q_asym",     "am_liam",  "Now sit with this one. The spend caps only apply to buys."),
    ("t_asym",     "af_heart", "Selling is never blocked. Never. You can always get out."),
    ("q_asym2",    "am_liam",  "A cap that trapped you in a position would be a cap that hurt you."),
    ("t_asym2",    "af_heart", "Same idea in what it acts on. To enter, it needs a strong buy. Highest conviction. To exit? Any sell signal at all will do."),
    ("q_asym3",    "am_liam",  "High bar to get in. Low bar to get out. That's not a setting. That's a whole philosophy about being wrong."),
    ("q_fail",     "am_liam",  "One more. If the live price is missing when it goes to send. A P I down, network hiccup, whatever. It doesn't guess, and it doesn't send anyway. It refuses."),
    ("t_fail",     "af_heart", "When it doesn't know, it does nothing. You know how rare that is?"),
    ("q_receipt",  "am_liam",  "None of this is a claim. Every number we said is in the file. Open it yourself."),
    ("t_receipt",  "af_heart", "One hundred. Four hundred. Three. Five percent. Thirty minutes. Half a percent. One and a half percent. All of it, right there."),

    # ---- the honest close (MUSIC FULLY OUT under these) ----
    ("t_close1",   "af_heart", "So let's be straight about what this is not. It is not advice. We're not your advisors, and this isn't a recommendation."),
    ("q_close1",   "am_liam",  "It will not make you money. Most options trades lose. That's not pessimism, that's the math. And any tool telling you different is selling you something."),
    ("t_close2",   "af_heart", "Guardrails aren't a guarantee. They're seatbelts. Seatbelts don't make you a good driver. They make crashing survivable."),
    ("q_close2",   "am_liam",  "What this is: the discipline you already know you need, written down in code. So it works on the days you don't feel like it."),

    # ---- bumper over the ase + wordmark end card ----
    ("q_bumper",   "am_liam",  "Quantum Melanin Media."),
    ("t_bumper",   "af_heart", "Voice and receipts for the unparented diaspora."),
    ("q_ase",      "am_liam",  "ah-shay."),
]

# Lines that must play with NO music bed under them (the honest close).
NO_BED = {"t_close1", "q_close1", "t_close2", "q_close2"}

WPM = 155  # Kokoro conversational pace


def _estimate() -> None:
    """Dry run: word counts + runtime estimate, no TTS required."""
    total_words = 0
    per_speaker: dict[str, int] = {}
    print(f"{'id':<12} {'voice':<9} {'words':>5}  {'est':>6}")
    for bid, voice, text in LINES:
        w = len(text.split())
        total_words += w
        per_speaker[voice] = per_speaker.get(voice, 0) + w
        print(f"{bid:<12} {voice:<9} {w:>5}  {w / WPM * 60:>5.1f}s")
    vo_s = total_words / WPM * 60
    print(f"\nlines={len(LINES)}  words={total_words}")
    for v, w in sorted(per_speaker.items()):
        who = "Quantus" if v == "am_liam" else "Tess"
        print(f"  {who:<8} {v:<9} {w:>4} words  ({w / total_words:.0%})")
    print(f"\nVO only            : {vo_s / 60:>5.2f} min ({vo_s:.0f}s)")
    for pad, label in ((1.30, "tight cut"), (1.40, "with B-roll holds"), (1.50, "loose")):
        print(f"  x{pad:<5}{label:<18}: {vo_s * pad / 60:>5.2f} min")
    print("\ntarget window 5:00-10:00  |  brief target 7:30-8:30")


def main() -> None:
    if "--dry" in sys.argv:
        _estimate()
        return

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    def say(pipe, text: str, voice: str):
        return np.concatenate([a for _, _, a in pipe(text.strip(), voice=voice)]).astype(np.float32)

    os.makedirs(OUTDIR, exist_ok=True)
    only = sys.argv[1] if len(sys.argv) > 1 else None
    pipe = KPipeline(lang_code="a")
    total = 0.0
    for bid, voice, text in LINES:
        if only and bid != only:
            continue
        wav = say(pipe, text, voice)
        sf.write(os.path.join(OUTDIR, f"{bid}.wav"), wav, SR)
        secs = len(wav) / SR
        total += secs
        print(f"{bid:<12} {voice:<9} {secs:>5.1f}s")
    print(f"\ntotal VO {total:.1f}s ({total / 60:.2f} min)")


if __name__ == "__main__":
    main()
