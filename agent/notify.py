"""A quiet desktop notification when a trade is waiting for approval.

Proposals expire after 30 minutes, so a buy nobody sees is a buy nobody
approves. This is a toast in the corner, never a window that grabs the
screen: Windows toast via Windows PowerShell (hidden), macOS Notification
Center via osascript, nothing elsewhere. MP_NOTIFY=0 turns it off.

The text names only side and symbol: no amounts, ids, or keys.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

_SAFE = re.compile(r"[^A-Za-z0-9 /,.:()+-]")
# Windows only shows toasts from a registered app id; PowerShell's own is always there.
_PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _clean(text: str) -> str:
    return _SAFE.sub("", text)[:180]


def message(proposals: list[dict]) -> str | None:
    buys = [p for p in proposals if p.get("side") == "buy"]
    if not buys:
        return None
    names = ", ".join(f"BUY {p.get('symbol', '?')}" for p in buys[:4])
    more = f" +{len(buys) - 4} more" if len(buys) > 4 else ""
    n = len(buys)
    return _clean(f"{n} trade{'s' if n != 1 else ''} waiting for your approval: {names}{more}. "
                  "Open the Trade desk within 30 min.")


def _windows_script(text: str) -> str:
    """PowerShell that shows one toast. `text` must already be _clean()ed: no
    quotes survive, so it cannot break out of the single-quoted string."""
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$x = $t.GetElementsByTagName('text');"
        "$x.Item(0).AppendChild($t.CreateTextNode('MarketPulse')) | Out-Null;"
        f"$x.Item(1).AppendChild($t.CreateTextNode('{text}')) | Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{_PS_APP_ID}').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )


def send(text: str) -> bool:
    """Fire and forget. Never raises: a missing toast must not stop a scan."""
    if os.environ.get("MP_NOTIFY", "1") == "0" or not text:
        return False
    text = _clean(text)
    try:
        if os.name == "nt":
            script = _windows_script(text)
            subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                              "-Command", script],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e", f'display notification "{text}" with title "MarketPulse"'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except OSError as exc:
        print(f"[notify] {type(exc).__name__}: {exc}", file=sys.stderr)
    return False
