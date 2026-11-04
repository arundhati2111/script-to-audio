"""Shared audio helpers: sample rate, ffmpeg decode/encode, voice-profile parsing."""

from __future__ import annotations

import subprocess

import numpy as np

from ..models import VoiceProfile

SR = 24000  # internal sample rate for all clips


def decode_audio(data: bytes) -> np.ndarray:
    """Decode any ffmpeg-readable audio (mp3/wav/...) to mono float32 at SR."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-f", "f32le", "-ar", str(SR), "-ac", "1", "pipe:1"],
        input=data, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed: {proc.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def encode_mp3(stereo: np.ndarray, path) -> None:
    """Encode a (n, 2) float32 array in [-1, 1] to an MP3 file.

    Writes to a real file (not a pipe) so ffmpeg can seek back and add a
    correct duration header, which browsers need for seeking.
    """
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-q:a", "3", str(path)],
        input=pcm, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {proc.stderr.decode(errors='replace')[:300]}")


# ---------- Voice profile parsing (profile fields are free text from the LLM) ----------

def pitch_level(profile: VoiceProfile) -> int:
    """-2 (very low) .. +2 (very high)."""
    p = profile.pitch.lower().replace("_", "-").replace(" ", "-")
    if "medium-low" in p:
        return -1
    if "medium-high" in p:
        return 1
    if "low" in p or "deep" in p:
        return -2
    if "high" in p:
        return 2
    return 0


def pace_level(profile: VoiceProfile) -> int:
    """-1 slow, 0 medium, +1 fast."""
    p = profile.pace.lower()
    if "slow" in p:
        return -1
    if "fast" in p or "quick" in p:
        return 1
    return 0


def age_group(profile: VoiceProfile) -> str:
    """'child', 'young', 'adult' or 'older'."""
    a = profile.age_range.lower()
    if any(w in a for w in ("child", "kid", "boy", "girl", "toddler")):
        return "child"
    if any(w in a for w in ("elder", "old", "senior", "aged")):
        return "older"
    digits = "".join(ch if ch.isdigit() else " " for ch in a).split()
    if digits:
        n = int(digits[0])
        if n < 13:
            return "child"
        if n < 30:
            return "young"
        if n >= 60:
            return "older"
        return "adult"
    if any(w in a for w in ("teen", "young")):
        return "young"
    return "adult"
