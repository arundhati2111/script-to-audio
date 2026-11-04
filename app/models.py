"""Pydantic models describing the structured script output.

This output is designed to feed an AUDIO DRAMA pipeline: the script is turned
into audio with distinct speakers and emotions via text-to-speech. Everything
a TTS/voice-casting stage needs is captured as structured data:

  * Each character has a machine-usable VoiceProfile (gender, age, pitch, pace,
    accent, timbre) plus a stable character_id for referencing.
  * A dedicated Narrator voices scene-setting and action (you can't *show*
    action in audio, so it's narrated).
  * Dialogue carries a controlled Emotion plus an intensity, so TTS/SSML can
    map it reliably.
  * Sound design (ambience + SFX) is first-class.
  * A flat, ordered AudioTimeline of Utterances is provided so the audio
    renderer can iterate a single list instead of walking nested scenes.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class GenreHint(str, Enum):
    drama = "drama"
    comedy = "comedy"
    thriller = "thriller"
    scifi = "sci-fi"
    fantasy = "fantasy"
    horror = "horror"
    romance = "romance"
    documentary = "documentary"
    adventure = "adventure"


class Emotion(str, Enum):
    """Controlled emotion vocabulary.

    A fixed set maps far more reliably onto TTS engines / SSML styles than
    free-form text. Keep this list aligned with whatever your TTS backend
    supports (e.g. Azure speaking styles, ElevenLabs, etc.).
    """

    neutral = "neutral"
    happy = "happy"
    excited = "excited"
    affectionate = "affectionate"
    calm = "calm"
    hopeful = "hopeful"
    sad = "sad"
    fearful = "fearful"
    anxious = "anxious"
    angry = "angry"
    disgusted = "disgusted"
    surprised = "surprised"
    determined = "determined"
    sarcastic = "sarcastic"
    whispering = "whispering"
    shouting = "shouting"
    tense = "tense"


class Gender(str, Enum):
    male = "male"
    female = "female"
    neutral = "neutral"


# ---------- Request ----------

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, description="The user's story idea / prompt.")
    duration_minutes: Optional[float] = Field(
        default=None, gt=0, le=600,
        description="Target runtime in minutes. If omitted, the engine infers a sensible length.",
    )
    genre: Optional[str] = Field(default=None, description="Optional genre or tone hint.")
    language: str = Field(default="English", description="Language the audio drama should be in.")


# ---------- Voice casting ----------

class VoiceProfile(BaseModel):
    """Structured, TTS-ready voice description for casting a speaker."""

    gender: Gender = Field(..., description="Perceived vocal gender.")
    age_range: str = Field(..., description="Approximate age band, e.g. 'child', '20s', '60s-elderly'.")
    pitch: str = Field(default="medium", description="low / medium-low / medium / medium-high / high.")
    pace: str = Field(default="medium", description="slow / medium / fast.")
    accent: str = Field(default="neutral", description="Accent or region, e.g. 'British RP', 'US Southern'.")
    timbre: str = Field(default="", description="Texture: warm, raspy, breathy, booming, nasal, etc.")
    base_emotion: Emotion = Field(
        default=Emotion.neutral, description="Default emotional color when no line emotion overrides it."
    )


# ---------- Characters & narrator ----------

class Character(BaseModel):
    id: str = Field(..., description="Stable identifier used to reference this speaker (e.g. 'maya').")
    name: str = Field(..., description="Character name as spoken/credited.")
    role: str = Field(..., description="Role in the story, e.g. protagonist, antagonist, mentor.")
    description: str = Field(..., description="Background and personality.")
    motivation: str = Field(..., description="What this character wants.")
    emotional_arc: str = Field(..., description="How their emotional state changes across the story.")
    voice: VoiceProfile = Field(..., description="How this character should sound.")


class Narrator(BaseModel):
    """The narrator voices scene-setting and action beats in the audio drama."""

    id: str = Field(default="narrator")
    name: str = Field(default="Narrator")
    style: str = Field(default="omniscient", description="Narration style, e.g. omniscient, first-person, noir.")
    voice: VoiceProfile


# ---------- Scene structure (authoring view) ----------

class DialogueLine(BaseModel):
    character_id: str = Field(..., description="id of the speaking character.")
    character: str = Field(..., description="Display name of the speaker.")
    emotion: Emotion = Field(default=Emotion.neutral, description="Controlled emotion driving the line.")
    intensity: float = Field(
        default=0.6, ge=0.0, le=1.0, description="How strong the emotion is, 0.0-1.0 (for TTS style degree)."
    )
    line: str = Field(..., description="TTS-friendly spoken dialogue (no stage formatting).")
    direction: str = Field(default="", description="Optional delivery note, e.g. 'trailing off'.")


class SoundCue(BaseModel):
    """Ambience or a discrete sound effect to mix into the audio."""

    cue_type: str = Field(..., description="'ambience' (sustained bed) or 'sfx' (discrete effect).")
    description: str = Field(..., description="What the sound is, e.g. 'rain on windows', 'door slams'.")


class SceneElement(BaseModel):
    """An ordered beat within a scene."""

    kind: str = Field(..., description="'narration', 'dialogue', or 'sound'.")
    narration: str = Field(default="", description="Narrator text (when kind == 'narration').")
    dialogue: Optional[DialogueLine] = Field(default=None, description="Dialogue (when kind == 'dialogue').")
    sound: Optional[SoundCue] = Field(default=None, description="Sound cue (when kind == 'sound').")


class Scene(BaseModel):
    number: int = Field(..., description="Scene order, starting at 1.")
    heading: str = Field(..., description="Location/time slug, e.g. 'INT. LIGHTHOUSE - NIGHT'.")
    summary: str = Field(..., description="One-line summary of the scene.")
    mood: str = Field(..., description="Overall emotional atmosphere.")
    ambience: str = Field(default="", description="Default background sound bed for the whole scene.")
    elements: List[SceneElement] = Field(default_factory=list)


# ---------- Flat audio timeline (production view) ----------

class Utterance(BaseModel):
    """One atomic, renderable audio event, in play order.

    This is what the downstream TTS/mixing stage iterates over. Every utterance
    already knows who speaks it and with what emotion, so no scene-walking is
    needed at render time.
    """

    index: int = Field(..., description="Global 0-based order across the whole drama.")
    scene_number: int
    kind: str = Field(..., description="'narration', 'dialogue', or 'sound'.")
    speaker_id: str = Field(..., description="Character id, or 'narrator', or 'sfx' for sound cues.")
    speaker_name: str
    emotion: Emotion = Field(default=Emotion.neutral)
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    text: str = Field(default="", description="Words to synthesize (empty for pure sound cues).")
    direction: str = Field(default="")
    sound_cue: Optional[SoundCue] = Field(default=None, description="Present when kind == 'sound'.")


class Script(BaseModel):
    title: str
    logline: str
    genre: str
    language: str
    estimated_duration_minutes: float
    synopsis: str
    narrator: Narrator
    characters: List[Character]
    scenes: List[Scene]
    timeline: List[Utterance] = Field(
        default_factory=list, description="Flat, ordered audio timeline built from the scenes."
    )


# ---------- Audio rendering ----------

class AudioRequest(BaseModel):
    script: Script
    provider: Optional[str] = Field(
        default=None, description="'openai', 'edge' or 'mock'. Defaults to the server configuration."
    )
    ambience: bool = Field(default=True, description="Mix in scene ambience beds and sound effects.")


class CastEntry(BaseModel):
    speaker_id: str
    speaker_name: str
    voice: str
    pan: float = Field(description="Stereo position, -1.0 (left) to 1.0 (right).")


class Segment(BaseModel):
    index: int
    start: float
    end: float


class AudioJob(BaseModel):
    id: str
    status: str = Field(description="'queued', 'running', 'done' or 'error'.")
    provider: str
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    duration_seconds: Optional[float] = None
    audio_url: Optional[str] = None
    cast: List[CastEntry] = Field(default_factory=list)
    segments: List[Segment] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    script: Script
    screenplay_text: str = Field(..., description="Human-readable audio-drama script.")
    mode: str = Field(..., description="'llm' or 'mock'.")
