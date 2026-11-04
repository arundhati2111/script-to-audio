"""Render a Script's timeline into a finished stereo audio drama, as background jobs."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ..config import settings
from ..models import AudioJob, CastEntry, Emotion, Script, Segment
from . import sfx
from .common import SR, encode_mp3
from .tts import TTSProvider, get_provider, speakers_of, synthesize_with_retry

# Relative loudness per emotion, applied after per-clip loudness normalisation.
_EMOTION_GAIN = {"whispering": 0.55, "shouting": 1.25, "sad": 0.85, "angry": 1.1, "excited": 1.1}
_TARGET_RMS = 0.11
_AMBIENCE_GAIN = 0.16
_SFX_GAIN = 0.55

_jobs: dict[str, AudioJob] = {}
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Signal helpers
# --------------------------------------------------------------------------- #

def _trim(x: np.ndarray, thresh: float = 0.01, pad: float = 0.04) -> np.ndarray:
    idx = np.flatnonzero(np.abs(x) > thresh)
    if len(idx) == 0:
        return x
    p = int(pad * SR)
    return x[max(idx[0] - p, 0): idx[-1] + p]


def _normalise(x: np.ndarray, emotion: Emotion) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
    gain = min(_TARGET_RMS / rms, 8.0) * _EMOTION_GAIN.get(emotion.value, 1.0)
    y = x * gain
    # Fade edges to avoid clicks.
    f = min(int(0.01 * SR), len(y) // 2)
    if f:
        ramp = np.linspace(0, 1, f, dtype=np.float32)
        y[:f] *= ramp
        y[-f:] *= ramp[::-1]
    return y


def _pan(mono: np.ndarray, pan: float) -> np.ndarray:
    """Constant-power pan; returns (n, 2)."""
    ang = (pan + 1) * np.pi / 4
    return np.stack([mono * np.cos(ang), mono * np.sin(ang)], axis=1)


def _fade(x: np.ndarray, seconds: float) -> np.ndarray:
    n = min(int(seconds * SR), len(x) // 2)
    if n:
        r = np.linspace(0, 1, n, dtype=np.float32)
        x[:n] *= r
        x[-n:] *= r[::-1]
    return x


def _add(buf: np.ndarray, stereo: np.ndarray, start: int) -> np.ndarray:
    end = start + len(stereo)
    if end > len(buf):
        buf = np.pad(buf, ((0, end - len(buf)), (0, 0)))
    buf[start:end] += stereo
    return buf


def _gap_after(u, nxt) -> float:
    """Silence after an utterance, in seconds."""
    if nxt is None:
        return 0.8
    if nxt.scene_number != u.scene_number:
        return 1.3
    gap = 0.22 if u.speaker_id == nxt.speaker_id else 0.38
    if u.kind == "narration" or nxt.kind == "narration":
        gap += 0.12
    if u.text.rstrip().endswith(("...", "…", "—", "-")):
        gap += 0.25
    if "pause" in u.direction.lower() or "beat" in u.direction.lower():
        gap += 0.5
    if u.emotion in (Emotion.tense, Emotion.sad):
        gap += 0.15
    return gap


def _pans(script: Script) -> dict[str, float]:
    chars = [c.id for c in script.characters]
    pans = {script.narrator.id: 0.0}
    n = len(chars)
    for i, cid in enumerate(chars):
        pans[cid] = 0.0 if n == 1 else -0.55 + 1.1 * i / (n - 1)
    return pans


# --------------------------------------------------------------------------- #
# Job lifecycle
# --------------------------------------------------------------------------- #

def get_job(job_id: str) -> AudioJob | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.model_copy(deep=True) if job else None


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs[job_id]
        for k, v in fields.items():
            setattr(job, k, v)


def output_path(job_id: str) -> Path:
    return Path(settings.audio_output_dir) / f"{job_id}.mp3"


def start_job(script: Script, provider_name: str | None, with_ambience: bool) -> AudioJob:
    provider = get_provider(provider_name)  # validates config before queueing
    job_id = uuid.uuid4().hex[:12]
    job = AudioJob(id=job_id, status="queued", provider=provider.name, message="Queued")
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job_id, script, provider, with_ambience), daemon=True).start()
    return job.model_copy(deep=True)


def _run(job_id: str, script: Script, provider: TTSProvider, with_ambience: bool) -> None:
    try:
        _update(job_id, status="running", message="Casting voices")
        audio, cast, segments = render(script, provider, with_ambience,
                                       lambda p, m: _update(job_id, progress=p, message=m))
        path = output_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _update(job_id, message="Encoding MP3", progress=0.98)
        encode_mp3(audio, path)
        _update(job_id, status="done", progress=1.0, message="Done", cast=cast, segments=segments,
                duration_seconds=round(len(audio) / SR, 2), audio_url=f"/audio/{job_id}/file")
    except Exception as exc:  # noqa: BLE001
        _update(job_id, status="error", message=str(exc))


# --------------------------------------------------------------------------- #
# The render pipeline
# --------------------------------------------------------------------------- #

def render(script: Script, provider: TTSProvider, with_ambience: bool = True, progress=lambda p, m: None):
    voices = provider.cast(script)
    pans = _pans(script)
    profiles = {sp.id: sp.profile for sp in speakers_of(script)}
    names = {sp.id: sp.name for sp in speakers_of(script)}
    default_voice = voices[script.narrator.id]
    cast = [CastEntry(speaker_id=sid, speaker_name=names[sid], voice=v, pan=round(pans.get(sid, 0.0), 2))
            for sid, v in voices.items()]

    timeline = script.timeline
    spoken = [u for u in timeline if u.kind in ("narration", "dialogue") and u.text.strip()]
    clips: dict[int, np.ndarray] = {}
    total = max(len(spoken), 1)

    # 1. Synthesize every spoken line (concurrently), keeping script order.
    def synth(u):
        profile = profiles.get(u.speaker_id, script.narrator.voice)
        voice = voices.get(u.speaker_id, default_voice)
        raw = synthesize_with_retry(provider, u.text, voice, profile, u.emotion, u.intensity, u.direction)
        return u.index, _normalise(_trim(raw), u.emotion)

    with ThreadPoolExecutor(max_workers=max(settings.tts_concurrency, 1)) as pool:
        for done, (idx, clip) in enumerate(pool.map(synth, spoken), 1):
            clips[idx] = clip
            progress(0.9 * done / total, f"Voicing line {done}/{len(spoken)}")

    # 2. Lay everything on the timeline.
    progress(0.92, "Mixing")
    buf = np.zeros((SR, 2), np.float32)
    cursor = int(0.4 * SR)
    segments: list[Segment] = []
    scene_start: dict[int, int] = {}
    scene_end: dict[int, int] = {}
    scene_ambience: dict[int, str] = {}
    sfx_events: list[tuple[int, str]] = []

    for i, u in enumerate(timeline):
        nxt = timeline[i + 1] if i + 1 < len(timeline) else None
        scene_start.setdefault(u.scene_number, cursor)

        if u.kind == "sound" and u.sound_cue:
            if u.sound_cue.cue_type == "ambience":
                scene_ambience[u.scene_number] = u.sound_cue.description
            elif with_ambience:
                sfx_events.append((cursor, u.sound_cue.description))
                cursor += int(0.5 * SR)  # leave room so the effect lands before the next line
            continue

        clip = clips.get(u.index)
        if clip is None:
            continue
        buf = _add(buf, _pan(clip, pans.get(u.speaker_id, 0.0)), cursor)
        segments.append(Segment(index=u.index, start=round(cursor / SR, 2), end=round((cursor + len(clip)) / SR, 2)))
        cursor += len(clip) + int(_gap_after(u, nxt) * SR)
        scene_end[u.scene_number] = cursor

    # 3. Sound design under and between the speech.
    if with_ambience:
        for number, desc in scene_ambience.items():
            start = scene_start.get(number, 0)
            end = scene_end.get(number, cursor) + int(0.8 * SR)
            bed = _fade(sfx.ambience(desc, (end - start) / SR)[: end - start], 1.5)
            buf = _add(buf, _pan(bed * _AMBIENCE_GAIN, 0.0), start)
        for start, desc in sfx_events:
            fx = sfx.effect(desc) * _SFX_GAIN
            buf = _add(buf, _pan(fx, 0.0), start)

    # 4. Master: tail, peak-normalise to about -1 dBFS.
    buf = np.pad(buf, ((0, int(0.6 * SR)), (0, 0)))
    peak = float(np.max(np.abs(buf))) or 1.0
    buf = buf * (0.89 / peak)
    progress(0.95, "Mastering")
    return buf, cast, segments
