"""Procedural ambience beds and sound effects.

No sample library is required: sounds are synthesized from filtered noise and
simple tones, chosen by keywords in the cue description. Everything returns
mono float32 at SR. Swap `ambience()` / `effect()` for real samples later.
"""

from __future__ import annotations

import zlib

import numpy as np

from .common import SR


def _rng(key: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(key.encode()))


def _noise(n: int, rng: np.random.Generator, lo: float | None = None, hi: float | None = None,
           tilt: float = 0.0) -> np.ndarray:
    """Band-limited noise via FFT shaping. tilt=1 -> pink-ish, 2 -> brown-ish."""
    spec = rng.normal(size=n // 2 + 1) + 1j * rng.normal(size=n // 2 + 1)
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = 1.0
    spec = spec / (f ** (tilt / 2))
    if lo is not None:
        spec[f < lo] = 0
    if hi is not None:
        spec[f > hi] = 0
    x = np.fft.irfft(spec, n)
    return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)


def _lfo(n: int, hz: float, depth: float, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n) / SR
    return (1 - depth + depth * (0.5 + 0.5 * np.sin(2 * np.pi * hz * t + phase))).astype(np.float32)


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return (np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-t / decay)).astype(np.float32)


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def ambience(description: str, seconds: float) -> np.ndarray:
    """A sustained bed of the given length (normalised to peak ~0.5)."""
    d = description.lower()
    n = max(int(seconds * SR), SR)
    rng = _rng(d)
    if _has(d, "rain", "storm", "drizzle", "downpour"):
        x = _noise(n, rng, 800, 9000) * 0.8 + _noise(n, rng, 100, 500, 1) * 0.3
        x *= _lfo(n, 0.13, 0.25)
    elif _has(d, "wave", "sea", "ocean", "surf", "shore", "lighthouse", "harbor", "harbour"):
        x = _noise(n, rng, 40, 1800, 1.5) * _lfo(n, 0.11, 0.7) + _noise(n, rng, 2000, 7000) * 0.08 * _lfo(n, 0.11, 0.8, 0.8)
    elif _has(d, "wind", "gale", "breeze", "howl"):
        x = _noise(n, rng, 120, 1400, 1.2) * _lfo(n, 0.2, 0.6)
    elif _has(d, "fire", "campfire", "fireplace", "crackl"):
        x = _noise(n, rng, 50, 700, 1.5) * 0.35
        pops = (rng.random(n) < 14 / SR).astype(np.float32)
        x = x + np.convolve(pops, _env(1200, 0.0005, 0.01) * _noise(1200, rng, 1500, 8000), "same") * 3
    elif _has(d, "forest", "night", "crickets", "jungle", "swamp", "field"):
        x = _noise(n, rng, 60, 600, 1.5) * 0.25
        t = np.arange(n) / SR
        x += 0.12 * np.sin(2 * np.pi * 4300 * t) * (np.sin(2 * np.pi * 7 * t) > 0.3) * _lfo(n, 0.05, 0.5)
    elif _has(d, "city", "street", "traffic", "crowd", "market", "cafe", "café", "bar", "pub", "restaurant"):
        x = _noise(n, rng, 80, 2500, 1.3) * _lfo(n, 0.3, 0.3)
    elif _has(d, "engine", "ship", "spaceship", "station", "hum", "machine", "reactor", "motor"):
        t = np.arange(n) / SR
        x = 0.5 * np.sin(2 * np.pi * 55 * t) + 0.25 * np.sin(2 * np.pi * 110.5 * t) + _noise(n, rng, 30, 400, 1) * 0.3
    else:  # generic room tone
        x = _noise(n, rng, 40, 900, 1.8) * 0.5
    x = x.astype(np.float32)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.5


def _thump(freq: float, dur: float, rng) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * freq * np.exp(-t * 18) * t) * _env(n, 0.001, dur / 4) + 0.3 * _noise(n, rng, 80, 1500) * _env(n, 0.001, 0.03)


def effect(description: str) -> np.ndarray:
    """A short discrete sound effect (peak ~0.7)."""
    d = description.lower()
    rng = _rng(d)

    def seq(parts: list[tuple[float, np.ndarray]]) -> np.ndarray:
        total = max(int(off * SR) + len(p) for off, p in parts)
        out = np.zeros(total, np.float32)
        for off, p in parts:
            i = int(off * SR)
            out[i:i + len(p)] += p
        return out

    if _has(d, "knock", "tap"):
        x = seq([(i * 0.22, _thump(180, 0.12, rng)) for i in range(3)])
    elif _has(d, "door") and _has(d, "slam", "bang", "shut", "close"):
        x = _thump(90, 0.5, rng) * 1.2
    elif _has(d, "door", "creak", "hinge"):
        n = int(1.1 * SR)
        t = np.arange(n) / SR
        f = 300 + 250 * np.sin(2 * np.pi * 1.3 * t) + 120 * t
        x = (np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.4 + _noise(n, rng, 500, 3000) * 0.2) * _env(n, 0.05, 0.6)
    elif _has(d, "footstep", "footsteps", "steps", "walking", "walks", "boots"):
        x = seq([(i * 0.45, _thump(120 + 15 * (i % 2), 0.15, rng) * 0.8) for i in range(5)])
    elif _has(d, "thunder", "boom", "explosion", "blast", "crash"):
        n = int(2.8 * SR)
        x = _noise(n, rng, 30, 500, 1.5) * _env(n, 0.03, 0.9) * 1.4
    elif _has(d, "glass", "shatter", "break", "smash"):
        n = int(1.0 * SR)
        x = _noise(n, rng, 2500, 11000) * _env(n, 0.001, 0.12)
        shard_n = int(0.12 * SR)
        for _ in range(8):  # tinkling shards after the initial crash
            i = int((0.1 + rng.random() * 0.6) * SR)
            x[i:i + shard_n] += 0.5 * _noise(shard_n, rng, 3000, 10000)[: n - i] * _env(shard_n, 0.001, 0.03)[: n - i]
    elif _has(d, "bell", "chime", "ding", "toll", "clock"):
        n = int(2.5 * SR)
        t = np.arange(n) / SR
        x = sum(a * np.sin(2 * np.pi * f * t) for f, a in [(523, 1), (1047, 0.5), (1570, 0.3), (2093, 0.15)]) * _env(n, 0.002, 0.9) * 0.35
    elif _has(d, "phone", "ring", "alarm", "beep", "buzz"):
        n = int(0.25 * SR)
        t = np.arange(n) / SR
        beep = (np.sin(2 * np.pi * 880 * t) + np.sin(2 * np.pi * 1320 * t)) * 0.3
        x = seq([(i * 0.4, beep.astype(np.float32)) for i in range(3)])
    elif _has(d, "gun", "shot", "bang"):
        n = int(0.9 * SR)
        x = _noise(n, rng, 100, 6000) * _env(n, 0.0005, 0.12) * 1.3
    elif _has(d, "splash", "water", "drip"):
        n = int(0.9 * SR)
        x = _noise(n, rng, 300, 5000) * _env(n, 0.005, 0.15)
    elif _has(d, "bottle", "cork", "clink"):
        n = int(0.8 * SR)
        t = np.arange(n) / SR
        x = (np.sin(2 * np.pi * 1900 * t) + 0.5 * np.sin(2 * np.pi * 3100 * t)) * _env(n, 0.001, 0.15) * 0.4
    elif _has(d, "scream", "cry"):
        n = int(1.2 * SR)
        t = np.arange(n) / SR
        x = np.sin(2 * np.pi * np.cumsum(900 + 500 * np.sin(2 * np.pi * 6 * t)) / SR) * _env(n, 0.05, 0.6) * 0.4
    else:  # soft whoosh / generic
        n = int(1.0 * SR)
        x = _noise(n, rng, 300, 4000) * np.sin(np.linspace(0, np.pi, n)).astype(np.float32) ** 2
    x = np.asarray(x, np.float32)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.7
