"""Generate a one-off reference PDF: 'MAPLE58 / MarketPulse — How It Sells on
Gumroad'. Plain-English explanation of git-vs-Gumroad, the buyer download flow,
and how a customer runs the tool on their own machine.

Run:  python tools/build_gumroad_reference_pdf.py
Out:  marketing/MAPLE58_Gumroad_HowItSells.pdf
"""
from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "marketing", "MAPLE58_Gumroad_HowItSells.pdf")

# Brand-ish palette (dark-luxury accent on white for print legibility)
INK = colors.HexColor("#14171c")
GOLD = colors.HexColor("#b8860b")
GREEN = colors.HexColor("#1f7a4d")
RED = colors.HexColor("#a83232")
MUTE = colors.HexColor("#555a63")
RULE = colors.HexColor("#d8dadf")


def _styles():
    ss = getSampleStyleSheet()
    out = {}
    out["title"] = ParagraphStyle("title", parent=ss["Title"], textColor=INK,
                                   fontSize=22, leading=26, spaceAfter=2)
    out["sub"] = ParagraphStyle("sub", parent=ss["Normal"], textColor=MUTE,
                                fontSize=10.5, leading=14, spaceAfter=14)
    out["h2"] = ParagraphStyle("h2", parent=ss["Heading2"], textColor=GOLD,
                               fontSize=14, leading=18, spaceBefore=14, spaceAfter=4)
    out["body"] = ParagraphStyle("body", parent=ss["Normal"], textColor=INK,
                                 fontSize=10.5, leading=15, spaceAfter=7,
                                 alignment=TA_LEFT)
    out["mono"] = ParagraphStyle("mono", parent=ss["Code"], textColor=INK,
                                 fontName="Courier", fontSize=9.5, leading=13,
                                 backColor=colors.HexColor("#f3f4f6"),
                                 borderPadding=8, spaceBefore=4, spaceAfter=8,
                                 leftIndent=4, rightIndent=4)
    out["warn"] = ParagraphStyle("warn", parent=ss["Normal"], textColor=RED,
                                 fontSize=10.5, leading=15, spaceAfter=7,
                                 backColor=colors.HexColor("#fbeaea"),
                                 borderPadding=8)
    out["foot"] = ParagraphStyle("foot", parent=ss["Normal"], textColor=MUTE,
                                 fontSize=8.5, leading=11)
    return out


def build():
    S = _styles()
    doc = SimpleDocTemplate(OUT, pagesize=LETTER,
                            leftMargin=0.85 * inch, rightMargin=0.85 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.6 * inch,
                            title="MAPLE58 — How It Sells on Gumroad")
    e = []

    def p(text, style="body"):
        e.append(Paragraph(text, S[style]))

    def bullets(items, color=INK):
        flow = [ListItem(Paragraph(t, S["body"])) for t in items]
        e.append(ListFlowable(flow, bulletType="bullet", bulletChar="•",
                              leftIndent=14, bulletColor=color))
        e.append(Spacer(1, 4))

    def rule():
        e.append(Spacer(1, 4))
        e.append(HRFlowable(width="100%", thickness=0.7, color=RULE))
        e.append(Spacer(1, 2))

    # ---- Header
    p("MAPLE58 / MarketPulse", "title")
    p("How it sells on Gumroad &amp; how a buyer runs it — plain-English reference.",
      "sub")
    rule()

    # ---- 1
    p("1 · Git and Gumroad are two separate worlds", "h2")
    p("They do not talk to each other. A code commit changes <b>nothing</b> a "
      "customer sees.")
    bullets([
        "<b>Git</b> = a private logbook of your source code (on your machine and "
        "GitHub). A <i>commit</i> is a saved snapshot with a note. A <i>branch</i> "
        "is a side-copy where new work waits until you approve it.",
        "<b>Gumroad</b> serves exactly one thing: <b>the file you manually "
        "uploaded</b> to the product. It never watches your git repo.",
    ])
    p("So the recent test-suite commit has <b>no effect on the listing</b>. It "
      "only recorded test files into your code history.")

    # ---- 2 warning
    p("2 · The thing that actually matters", "h2")
    e.append(Paragraph(
        "&#9888; The file currently selling is <b>MarketPulse_v1.zip, dated "
        "June&nbsp;14</b>. It contains the <i>original</i> dashboard only — "
        "no options engine (chains / IV / Greeks), no nudge&rarr;strategy&rarr;"
        "probe&rarr;\"The Read\" funnel, no Pot Tracker, no Scanner, no agent, "
        "no tests. <b>Buyers today get the old tool, not MAPLE58.</b> The "
        "listing is a whole product behind.", S["warn"]))
    e.append(Spacer(1, 6))

    # ---- 3
    p("3 · How selling on Gumroad actually works", "h2")
    p("It is just a <b>file download</b>. No app store, no installer, no cloud "
      "account.")
    e.append(Paragraph(
        "You upload   &rarr;   MarketPulse_v1.zip   &rarr;   sits on Gumroad<br/>"
        "Buyer pays $19   &rarr;   Gumroad emails a download link   &rarr;   they "
        "get the .zip", S["mono"]))
    p("The product is a <b>downloadable code pack</b> (a ZIP). On purchase, the "
      "buyer gets a Download button for the same zip you uploaded.")

    # ---- 4
    p("4 · What the buyer does on their computer", "h2")
    e.append(ListFlowable([
        ListItem(Paragraph("Buys &rarr; downloads <font face='Courier'>"
                           "MarketPulse_v1.zip</font>", S["body"])),
        ListItem(Paragraph("<b>Unzips it</b> &rarr; gets a "
                           "<font face='Courier'>MarketPulse/</font> folder", S["body"])),
        ListItem(Paragraph("<b>Windows:</b> double-clicks "
                           "<font face='Courier'>run.bat</font> &nbsp;·&nbsp; "
                           "<b>Mac/Linux:</b> runs "
                           "<font face='Courier'>bash run.sh</font>", S["body"])),
        ListItem(Paragraph("The script starts a tiny local web server "
                           "(<font face='Courier'>python app.py</font>) and "
                           "auto-opens <font face='Courier'>http://127.0.0.1:8000"
                           "</font>", S["body"])),
        ListItem(Paragraph("The tool runs <b>locally on their own machine</b> — "
                           "the \"app\" is a web page served from their computer. "
                           "Close the terminal to stop it.", S["body"])),
    ], bulletType="1", leftIndent=16))
    e.append(Spacer(1, 4))
    p("That is why it is written in pure-Python standard library with no pip "
      "installs — a buyer needs nothing except Python itself.")

    # ---- 5
    p("5 · The one real friction point", "h2")
    p("\"You only need Python 3\" is true on Mac/Linux but <b>often false on "
      "Windows</b> — many buyers will not have Python, and "
      "<font face='Courier'>run.bat</font> just flashes an error. This is the "
      "biggest \"it doesn't work on my computer\" risk.")
    e.append(Paragraph(
        "Fix: add a README line telling Windows users to install Python from "
        "python.org and check <b>\"Add Python to PATH\"</b> during setup.",
        S["body"]))

    # ---- 6
    p("6 · Where the tests fit", "h2")
    p("The test suite is for <b>you</b> (and any developer who forks the "
      "open-source GitHub copy) — proof the math and the money-safety gates "
      "work. Buyers do not run tests. Including them in the pack is a nice trust "
      "signal but does not change how the tool runs.")

    # ---- Action
    rule()
    p("Action item", "h2")
    e.append(Paragraph(
        "Rebuild the Gumroad zip (bump to <b>_v2</b>) from the current source — "
        "options engine, probe/pot/scanner, tests, and an updated README with "
        "the Windows-Python note — so buyers actually receive MAPLE58.",
        S["body"]))

    e.append(Spacer(1, 14))
    e.append(HRFlowable(width="100%", thickness=0.7, color=RULE))
    e.append(Spacer(1, 4))
    p("Quantum Melanin Media · MAPLE58 = MArket PuLsE · educational tool, not "
      "financial advice. Generated reference doc.", "foot")

    doc.build(e)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({os.path.getsize(path)} bytes)")
