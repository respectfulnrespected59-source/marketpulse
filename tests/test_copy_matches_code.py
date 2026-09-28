"""What the site SAYS must match what the code DOES.

2026-09-28, found while writing the class explainer: the landing promised
"full auto is an opt-in switch" (auto only ever closes positions), the app
said "four factors have to agree" and "RSI + MACD + trend" (it is a net vote
of seven checks), the FAQ said every reading is at most a minute old
(options quotes run about 15 minutes behind), and the landing's
"Paper trade" link opened Home because the deep-link list skipped the tab.
Each pin below reads the claim next to the code it describes.
"""

import os
import re

import pytest

from indicators import _LABELS

pytestmark = pytest.mark.unit

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def _deep_link_views():
    block = re.search(r"const VIEWS = \[(.*?)\];", _read("app.js")).group(1)
    return set(re.findall(r'"([a-z]+)"', block))


def test_the_site_never_promises_auto_buying():
    for name in ("landing.html", os.path.join("landing", "landing.js")):
        text = _read(name).lower()
        assert "full auto" not in text, name
        assert "switch on auto" not in text, name
    assert "only closes positions" in _read(os.path.join("landing", "landing.js"))


def test_the_engine_is_described_as_the_seven_check_vote_it_is():
    strong_buy_at = next(t for t, label, _ in _LABELS if label == "STRONG BUY")
    blurb = _read("home.js")
    assert "Four factors" not in blurb
    assert f"net score of {strong_buy_at} or more" in blurb, "the onboarding threshold is the engine's"
    index = _read("index.html")
    assert "RSI + MACD + trend" not in index
    assert "seven checks" in index and "seven-check" in index


def test_the_faq_says_how_old_options_quotes_are():
    assert "Options quotes are delayed about 15 minutes" in _read("landing.html")


def test_every_public_tab_can_be_opened_from_a_link():
    tabs = set(re.findall(r'class="tab[^"]*" data-view="([a-z]+)"', _read("index.html")))
    views = _deep_link_views()
    missing = tabs - {"trade"} - views
    assert not missing, f"tabs a link cannot open: {sorted(missing)}"
    assert "trade" not in views, "the desk shows itself only when it answers, never from a URL"


def test_the_landings_deep_links_all_land_on_a_real_tab():
    views = _deep_link_views()
    for view in re.findall(r"/app\?view=([a-z]+)", _read("landing.html")):
        assert view in views, f"/app?view={view} would open Home instead"
