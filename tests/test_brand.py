"""The MarketPulse emblem and the grown-up app chrome.

The emblem (gold heartbeat that loops into a melanin molecule) is inlined in
more than one page. These tests keep every copy identical and pin the three
traps the design mockups hit: <use> copies render blank (page CSS cannot style
them), an objectBoundingBox gradient paints nothing on a straight line, and
motion must stop for people who ask for reduced motion.
"""

import glob
import os
import re

import pytest

pytestmark = pytest.mark.unit

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
EMBLEM = re.compile(r"<!-- MP-EMBLEM:START -->(.*?)<!-- MP-EMBLEM:END -->", re.S)
PICTOGRAPH = re.compile("[\U0001F300-\U0001FAFF⚠⚪✋⛓✍]")


def _read(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        return fh.read()


def _emblems():
    return {name: EMBLEM.findall(_read(name)) for name in ("landing.html", "index.html")}


def test_landing_and_app_both_carry_the_emblem():
    for name, found in _emblems().items():
        assert len(found) == 1, f"{name} has {len(found)} emblems (one per page keeps the gradient id unique)"


def test_every_emblem_copy_is_identical():
    copies = {found[0].strip() for found in _emblems().values()}
    assert len(copies) == 1, "the landing and app emblems have drifted apart"


def test_emblem_is_inline_not_a_use_reference():
    # A <use> clone cannot be styled by page CSS: the preview rendered a black box.
    emblem = _emblems()["landing.html"][0]
    assert "<use" not in emblem


def test_emblem_gradient_survives_straight_lines():
    # objectBoundingBox (the default) collapses to nothing on a horizontal or
    # vertical line; the benzene double bond and the heartbeat baseline vanished.
    emblem = _emblems()["landing.html"][0]
    assert 'gradientUnits="userSpaceOnUse"' in emblem


def test_emblem_draws_both_the_heartbeat_and_the_molecule():
    emblem = _emblems()["landing.html"][0]
    assert "mp-ecg" in emblem and "mp-mol" in emblem
    assert emblem.count('pathLength="1"') >= 9  # every stroke animates on a 0..1 dash


def test_loop_is_seven_seconds_and_respects_reduced_motion():
    css = _read("brand.css")
    assert re.search(r"--mp-loop:\s*7s", css)
    reduced = css.split("prefers-reduced-motion", 1)
    assert len(reduced) == 2 and "animation: none" in reduced[1]


def test_both_pages_load_the_shared_brand_css():
    for name in ("landing.html", "index.html"):
        assert 'href="/brand.css"' in _read(name), name


def test_app_has_no_pictographic_emoji():
    offenders = []
    for path in [os.path.join(STATIC, "index.html")] + glob.glob(os.path.join(STATIC, "*.js")):
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if PICTOGRAPH.search(line):
                    offenders.append(f"{os.path.basename(path)}:{n}")
    assert not offenders, offenders


def test_no_button_was_left_empty():
    for path in [os.path.join(STATIC, "index.html")] + glob.glob(os.path.join(STATIC, "*.js")):
        with open(path, encoding="utf-8") as fh:
            assert not re.search(r"<button[^>]*>\s*</button>", fh.read()), path


def test_nudge_banners_draw_their_own_icon_not_the_server_emoji():
    # options.py / dca.py still send an emoji "icon"; rendering it raw put a
    # cartoon chart back on the DCA screen (and inserted a server string unescaped).
    for name in ("panels.js", "wizards.js"):
        assert "${n.icon" not in _read(name), name
