"""The lesson voices: Tess (af_heart) teaches, Quantus (am_liam) asks.

Kokoro renders locally (free); ffmpeg turns each line into a small mono MP3.
Used by build.py; the compiler only ever sees bake(text, who) -> (mp3, ms).
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf

VOICES = {"T": "af_heart", "Q": "am_liam"}
SPEED = 1.0              # a lesson, not a promo: unhurried
SAMPLE_RATE = 24_000     # Kokoro's output rate
MP3_BITRATE = "64k"
TAIL_S = 0.25            # a breath after each line so steps don't butt together
# Part of every audio file name: change a voice, the speed or the tail and every
# line re-bakes, instead of the build reusing takes made with the old settings.
VOICE_KEY = f"kokoro|{sorted(VOICES.items())}|{SPEED}|{TAIL_S}|{MP3_BITRATE}"

_pipe = None


def _pipeline():
    global _pipe
    if _pipe is None:
        from kokoro import KPipeline
        _pipe = KPipeline(lang_code="a")
    return _pipe


def bake(text: str, who: str) -> tuple[bytes, int]:
    wav = np.concatenate([a for _, _, a in _pipeline()(text, voice=VOICES[who], speed=SPEED)])
    wav = np.concatenate([wav, np.zeros(int(SAMPLE_RATE * TAIL_S), dtype=wav.dtype)])
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "line.wav"), os.path.join(tmp, "line.mp3")
        sf.write(src, wav, SAMPLE_RATE)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1", "-b:a", MP3_BITRATE, dst],
                       check=True)
        with open(dst, "rb") as fh:
            data = fh.read()
    return data, round(len(wav) / SAMPLE_RATE * 1000)
