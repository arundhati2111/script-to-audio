"""TTS providers and voice casting.

A provider knows its voice catalogue (``cast``) and how to turn one line plus an
emotion into audio (``synthesize``). All providers return mono float32 at SR.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

import httpx
import numpy as np

from ..config import settings
from ..models import Emotion, Script, VoiceProfile
from .common import SR, age_group, decode_audio, pace_level, pitch_level


@dataclass
class Speaker:
    id: str
    name: str
    profile: VoiceProfile


def speakers_of(script: Script) -> list[Speaker]:
    """Narrator first, then characters in script order."""
    out = [Speaker(script.narrator.id, script.narrator.name, script.narrator.voice)]
    out += [Speaker(c.id, c.name, c.voice) for c in script.characters]
    return out


@dataclass
class Voice:
    id: str
    gender: str  # male / female / neutral
    locale: str = ""  # e.g. en-GB
    child_ok: bool = False


def _accent_locale(accent: str) -> str:
    a = accent.lower()
    table = [
        ("british", "en-GB"), ("english", "en-GB"), ("scottish", "en-GB"),
        ("welsh", "en-GB"), ("cockney", "en-GB"), ("irish", "en-IE"), ("australian", "en-AU"),
        ("indian", "en-IN"), ("canadian", "en-CA"), ("south african", "en-ZA"),
        ("american", "en-US"), ("southern", "en-US"), ("new york", "en-US"),
    ]
    for key, loc in table:
        if key in a:
            return loc
    return ""


def cast_voices(speakers: list[Speaker], catalogue: list[Voice]) -> dict[str, str]:
    """Give every speaker the best-matching voice, preferring unused voices so
    that different characters sound different. Reuses voices only when the
    catalogue is exhausted (prosody differences still separate them)."""
    used: dict[str, int] = {}
    result: dict[str, str] = {}
    for sp in speakers:
        g = sp.profile.gender.value
        locale = _accent_locale(sp.profile.accent)
        child = age_group(sp.profile) == "child"
        best, best_score = None, -1e9
        for v in catalogue:
            score = 0.0
            if v.gender == g:
                score += 10
            elif v.gender == "neutral" or g == "neutral":
                score += 4
            if not locale and v.locale in ("en-US", "en-GB"):
                score += 3  # sensible default when no accent is specified
            if locale and v.locale == locale:
                score += 5
            elif locale and v.locale[:2] == locale[:2]:
                score += 1
            if child and v.child_ok:
                score += 6
            score -= 20 * used.get(v.id, 0)
            if score > best_score:
                best, best_score = v, score
        assert best is not None
        used[best.id] = used.get(best.id, 0) + 1
        result[sp.id] = best.id
    return result


class TTSProvider:
    name = "base"

    def cast(self, script: Script) -> dict[str, str]:
        raise NotImplementedError

    def synthesize(self, text: str, voice: str, profile: VoiceProfile,
                   emotion: Emotion, intensity: float, direction: str) -> np.ndarray:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# OpenAI-compatible (real emotional acting via `instructions`)
# --------------------------------------------------------------------------- #

_OPENAI_VOICES = [
    Voice("onyx", "male"), Voice("coral", "female"), Voice("ash", "male"), Voice("nova", "female"),
    Voice("echo", "male"), Voice("sage", "female"), Voice("ballad", "male", "en-GB"),
    Voice("shimmer", "female"), Voice("verse", "male"), Voice("fable", "neutral", "en-GB"),
    Voice("alloy", "neutral"),
]

_EMOTION_ACTING = {
    "neutral": "natural and conversational",
    "happy": "warm, smiling, bright",
    "excited": "energetic, breathless with excitement",
    "affectionate": "tender, soft and loving",
    "calm": "calm, steady and soothing",
    "hopeful": "gently hopeful, lifting at phrase ends",
    "sad": "sorrowful, heavy, voice close to breaking",
    "fearful": "frightened, trembling, short shaky breaths",
    "anxious": "nervous, hurried, uneasy",
    "angry": "furious, sharp and clipped, barely restrained",
    "disgusted": "disgusted, repulsed, with a curled-lip tone",
    "surprised": "startled and astonished, sudden pitch jumps",
    "determined": "resolute, firm and controlled",
    "sarcastic": "dry, mocking, with ironic emphasis",
    "whispering": "hushed whisper, intimate and secretive",
    "shouting": "loud, projected shouting",
    "tense": "tight, restrained, strained with suspense",
}


def _intensity_word(x: float) -> str:
    return "subtle" if x < 0.35 else "moderate" if x < 0.7 else "strong" if x < 0.9 else "extreme"


class OpenAITTS(TTSProvider):
    name = "openai"

    def cast(self, script: Script) -> dict[str, str]:
        return cast_voices(speakers_of(script), _OPENAI_VOICES)

    def synthesize(self, text, voice, profile, emotion, intensity, direction):
        payload: dict = {
            "model": settings.tts_model,
            "voice": voice,
            "input": text,
            "response_format": "mp3",
        }
        pace = pace_level(profile)
        if pace:
            payload["speed"] = 1.0 + 0.1 * pace
        if "gpt-4o" in settings.tts_model:
            parts = [
                "You are a voice actor in a radio audio drama. Perform the line, do not read stage directions.",
                f"Character voice: {profile.gender.value}, {profile.age_range}, {profile.pitch} pitch, "
                f"{profile.accent} accent" + (f", {profile.timbre} timbre" if profile.timbre else "") + ".",
                f"Emotion: {_EMOTION_ACTING.get(emotion.value, emotion.value)} "
                f"({_intensity_word(intensity)} intensity).",
            ]
            if direction:
                parts.append(f"Delivery: {direction}.")
            payload["instructions"] = " ".join(parts)
        headers = {"Authorization": f"Bearer {settings.tts_api_key}"}
        resp = httpx.post(f"{settings.tts_base_url}/audio/speech", json=payload, headers=headers,
                          timeout=settings.tts_timeout)
        resp.raise_for_status()
        return decode_audio(resp.content)


# --------------------------------------------------------------------------- #
# Edge (free, no key): emotion is expressed through rate / pitch / volume
# --------------------------------------------------------------------------- #

# (rate %, pitch Hz, volume %) at full intensity
_EDGE_PROSODY = {
    "neutral": (0, 0, 0), "happy": (8, 8, 5), "excited": (16, 14, 10), "affectionate": (-8, 2, -5),
    "calm": (-10, -4, -5), "hopeful": (2, 5, 0), "sad": (-16, -9, -12), "fearful": (10, 12, -5),
    "anxious": (12, 8, -3), "angry": (8, 4, 18), "disgusted": (-6, -4, 0), "surprised": (6, 16, 8),
    "determined": (-4, -3, 8), "sarcastic": (-6, 3, 0), "whispering": (-12, -2, -40),
    "shouting": (8, 8, 40), "tense": (-2, 3, -3),
}

_LANG_CODES = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "hindi": "hi", "japanese": "ja", "korean": "ko", "chinese": "zh",
    "mandarin": "zh", "arabic": "ar", "russian": "ru", "dutch": "nl", "turkish": "tr",
    "polish": "pl", "swedish": "sv", "tamil": "ta", "bengali": "bn", "urdu": "ur",
    "telugu": "te", "marathi": "mr", "gujarati": "gu", "indonesian": "id", "thai": "th",
    "vietnamese": "vi", "greek": "el", "ukrainian": "uk",
}

_edge_voice_cache: list[dict] | None = None


def _edge_catalogue() -> list[dict]:
    global _edge_voice_cache
    if _edge_voice_cache is None:
        import edge_tts
        _edge_voice_cache = asyncio.run(edge_tts.list_voices())
    return _edge_voice_cache


class EdgeTTS(TTSProvider):
    name = "edge"

    def cast(self, script: Script) -> dict[str, str]:
        lang = script.language.strip().lower()
        code = _LANG_CODES.get(lang, lang[:2] if len(lang) in (2, 5) else "en")
        voices = [v for v in _edge_catalogue() if v["Locale"].lower().startswith(code)]
        if not voices:
            voices = [v for v in _edge_catalogue() if v["Locale"].startswith("en")]
        catalogue = [Voice(v["ShortName"], v["Gender"].lower(), v["Locale"],
                           child_ok=v["ShortName"] in ("en-US-AnaNeural",)) for v in voices]
        # English: keep the pool to well-known broadcast-quality locales first.
        return cast_voices(speakers_of(script), catalogue)

    def synthesize(self, text, voice, profile, emotion, intensity, direction):
        import edge_tts

        rate, pitch, vol = _EDGE_PROSODY.get(emotion.value, (0, 0, 0))
        k = max(0.3, min(1.0, intensity)) if emotion != Emotion.neutral else 0.0
        rate, pitch, vol = rate * k, pitch * k, vol * k
        # Character baseline so speakers differ even when sharing a voice.
        pitch += 7 * pitch_level(profile)
        rate += 8 * pace_level(profile)
        age = age_group(profile)
        if age == "child":
            pitch += 25
        elif age == "older":
            rate -= 6
            pitch -= 3
        rate = int(max(-50, min(60, rate)))
        pitch = int(max(-60, min(60, pitch)))
        vol = int(max(-60, min(50, vol)))

        async def run() -> bytes:
            comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz",
                                        volume=f"{vol:+d}%")
            buf = bytearray()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            if not buf:
                raise RuntimeError("edge-tts returned no audio")
            return bytes(buf)

        return decode_audio(asyncio.run(run()))


# --------------------------------------------------------------------------- #
# Mock (offline): one synthetic tone "voice" per speaker, for pipeline tests
# --------------------------------------------------------------------------- #

class MockTTS(TTSProvider):
    name = "mock"

    def cast(self, script: Script) -> dict[str, str]:
        return {sp.id: f"tone-{i}" for i, sp in enumerate(speakers_of(script))}

    def synthesize(self, text, voice, profile, emotion, intensity, direction):
        seed = int(hashlib.md5(voice.encode()).hexdigest()[:6], 16)
        base = 110 + (seed % 200) + 12 * (1 + intensity)
        dur = max(0.4, len(text.split()) * 0.32)
        t = np.arange(int(dur * SR)) / SR
        syl = 0.5 + 0.5 * np.sin(2 * np.pi * 3.2 * t)  # syllable-like pulsing
        sig = 0.25 * syl * (np.sin(2 * np.pi * base * t) + 0.4 * np.sin(2 * np.pi * 2 * base * t))
        return sig.astype(np.float32)


def get_provider(name: str | None = None) -> TTSProvider:
    name = (name or settings.resolved_tts_provider).lower()
    if name == "openai":
        if not settings.tts_api_key:
            raise ValueError("TTS provider 'openai' needs TTS_API_KEY in .env")
        return OpenAITTS()
    if name == "edge":
        return EdgeTTS()
    if name == "mock":
        return MockTTS()
    raise ValueError(f"Unknown TTS provider '{name}'. Use openai, edge or mock.")


def synthesize_with_retry(provider: TTSProvider, *args, attempts: int = 3) -> np.ndarray:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return provider.synthesize(*args)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"TTS failed after {attempts} attempts: {last}") from last
