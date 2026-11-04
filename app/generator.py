"""The generation engine (audio-drama oriented).

Responsibilities:
  * Infer a sensible duration when the user doesn't give one.
  * Derive scope (scene count, character count, word budget) from the duration.
  * Build a strong instruction prompt and ask an OpenAI-compatible LLM for a
    structured JSON script shaped for AUDIO DRAMA production.
  * Validate the result against our Pydantic models and build the flat audio
    timeline.
  * Provide a deterministic mock script when no API key is configured.
"""

from __future__ import annotations

import json
import re

import httpx

from .config import settings
from .models import (
    Character,
    DialogueLine,
    Emotion,
    Gender,
    GenerateRequest,
    Narrator,
    Scene,
    SceneElement,
    Script,
    SoundCue,
    VoiceProfile,
)
from .timeline import build_timeline

# Roughly how many spoken words land in a minute of audio. Used to size the
# script when scaling to a target duration.
WORDS_PER_MINUTE = 150


def infer_duration(prompt: str) -> float:
    explicit = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(min|minute|minutes|hour|hours|hr|hrs)", prompt.lower()
    )
    if explicit:
        value = float(explicit.group(1))
        if explicit.group(2).startswith("h"):
            value *= 60
        return max(0.5, min(value, 600))

    words = len(prompt.split())
    base = 3.0
    if words > 40:
        base += 3
    if words > 80:
        base += 4
    if re.search(r"\b(epic|saga|series|feature|movie|film)\b", prompt.lower()):
        base += 5
    return float(min(base, 20))


def derive_scope(duration_minutes: float) -> dict:
    scenes = min(max(2, round(duration_minutes / 1.5)), 30)
    characters = 2 if duration_minutes <= 3 else 3 if duration_minutes <= 8 else 5
    word_budget = int(duration_minutes * WORDS_PER_MINUTE)
    return {"scenes": scenes, "characters": characters, "word_budget": word_budget}


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

def _emotion_list() -> str:
    return ", ".join(e.value for e in Emotion)


def _build_messages(req: GenerateRequest, duration: float, scope: dict) -> list[dict]:
    genre = req.genre or "let the story dictate the most fitting genre"

    schema_hint = {
        "title": "string",
        "logline": "one sentence",
        "genre": "string",
        "language": req.language,
        "estimated_duration_minutes": duration,
        "synopsis": "one short paragraph",
        "narrator": {
            "id": "narrator",
            "name": "Narrator",
            "style": "omniscient | first-person | noir | documentary",
            "voice": {
                "gender": "male | female | neutral",
                "age_range": "e.g. 40s",
                "pitch": "low | medium-low | medium | medium-high | high",
                "pace": "slow | medium | fast",
                "accent": "e.g. neutral, British RP",
                "timbre": "warm | raspy | breathy | booming | ...",
                "base_emotion": "one of the allowed emotions",
            },
        },
        "characters": [
            {
                "id": "lowercase_stable_id",
                "name": "string",
                "role": "protagonist/antagonist/etc",
                "description": "background and personality",
                "motivation": "what they want",
                "emotional_arc": "how their emotions change",
                "voice": {
                    "gender": "male | female | neutral",
                    "age_range": "e.g. 20s",
                    "pitch": "low | medium-low | medium | medium-high | high",
                    "pace": "slow | medium | fast",
                    "accent": "e.g. US Southern",
                    "timbre": "warm | raspy | breathy | ...",
                    "base_emotion": "one of the allowed emotions",
                },
            }
        ],
        "scenes": [
            {
                "number": 1,
                "heading": "INT./EXT. LOCATION - TIME",
                "summary": "one line",
                "mood": "emotional atmosphere",
                "ambience": "sustained background sound bed for the scene",
                "elements": [
                    {
                        "kind": "narration",
                        "narration": "narrator text describing action/setting (spoken aloud)",
                        "dialogue": None,
                        "sound": None,
                    },
                    {
                        "kind": "sound",
                        "narration": "",
                        "dialogue": None,
                        "sound": {"cue_type": "sfx", "description": "a door creaks open"},
                    },
                    {
                        "kind": "dialogue",
                        "narration": "",
                        "dialogue": {
                            "character_id": "must match a character id above",
                            "character": "display name",
                            "emotion": "one of the allowed emotions",
                            "intensity": 0.7,
                            "line": "the spoken words, clean and TTS-friendly",
                            "direction": "optional delivery note",
                        },
                        "sound": None,
                    },
                ],
            }
        ],
    }

    system = (
        "You are an expert audio-drama writer and voice director. You turn a short prompt "
        "into a complete radio/audio drama that will be performed by text-to-speech voices. "
        "Because the audience only LISTENS, there is no visual channel: convey all action, "
        "setting, and description through the NARRATOR and through SOUND cues, never as silent "
        "stage directions. You always respond with a single valid JSON object and nothing else."
    )

    user = f"""Write a complete AUDIO DRAMA from this prompt.

PROMPT: {req.prompt}

REQUIREMENTS:
- Language: {req.language}
- Genre/tone: {genre}
- Target runtime: about {duration:g} minute(s) of audio.
- Roughly {scope['scenes']} scenes; about {scope['characters']} distinct speaking characters.
- Aim for about {scope['word_budget']} spoken words total (narration + dialogue), so the
  runtime feels right.

AUDIO-DRAMA RULES (important):
- Provide a NARRATOR with its own voice. Use narration to establish place, time, and action
  that cannot be heard.
- Give EVERY character a distinct, structured 'voice' so each maps to a different TTS speaker.
  Vary gender, age_range, pitch, pace, accent, and timbre so voices are clearly distinguishable.
- Each character needs a stable lowercase 'id'. Every dialogue line must reference a valid
  character_id.
- 'emotion' MUST be exactly one of: {_emotion_list()}.
- Give each dialogue line an 'intensity' from 0.0 to 1.0.
- Use 'sound' elements for discrete SFX and set each scene's 'ambience' for the background bed.
- Keep spoken 'line' and 'narration' text clean and natural to read aloud: no bracketed stage
  directions inside the spoken text, spell out things that should be pronounced.
- Tell a complete story: clear beginning, middle, end; real conflict; a resolution.

Respond with ONLY a JSON object matching exactly this shape (same keys, same nesting):

{json.dumps(schema_hint, indent=2)}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _call_llm(messages: list[dict]) -> dict:
    url = f"{settings.llm_base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.9,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client(timeout=settings.llm_timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400 and ("response_format" in resp.text or resp.status_code in (400, 422)):
            payload.pop("response_format", None)
            resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return _extract_json(data["choices"][0]["message"]["content"])


def _coerce_emotions(raw: dict) -> None:
    """Map any unknown emotion strings onto the controlled vocabulary.

    LLMs occasionally emit a synonym; snap it to the nearest allowed value so
    validation doesn't fail and the TTS stage gets a known style.
    """
    allowed = {e.value for e in Emotion}
    synonyms = {
        "joyful": "happy", "joy": "happy", "glad": "happy", "cheerful": "happy",
        "scared": "fearful", "afraid": "fearful", "terrified": "fearful",
        "worried": "anxious", "nervous": "anxious", "uneasy": "anxious",
        "furious": "angry", "mad": "angry", "irritated": "angry",
        "awestruck": "surprised", "amazed": "surprised", "shocked": "surprised", "stunned": "surprised",
        "skeptical": "sarcastic", "wry": "sarcastic", "ironic": "sarcastic",
        "melancholy": "sad", "grief": "sad", "sorrowful": "sad",
        "loving": "affectionate", "tender": "affectionate", "warm": "affectionate",
        "resolute": "determined", "resolved": "determined",
        "soft": "calm", "serene": "calm", "relaxed": "calm",
    }

    def fix(value):
        if not isinstance(value, str):
            return "neutral"
        v = value.strip().lower()
        if v in allowed:
            return v
        return synonyms.get(v, "neutral")

    for scene in raw.get("scenes", []):
        for el in scene.get("elements", []):
            d = el.get("dialogue")
            if d and "emotion" in d:
                d["emotion"] = fix(d["emotion"])
    nar = raw.get("narrator", {}).get("voice", {})
    if "base_emotion" in nar:
        nar["base_emotion"] = fix(nar["base_emotion"])
    for c in raw.get("characters", []):
        v = c.get("voice", {})
        if "base_emotion" in v:
            v["base_emotion"] = fix(v["base_emotion"])


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def generate_script(req: GenerateRequest) -> tuple[Script, str]:
    duration = req.duration_minutes or infer_duration(req.prompt)
    scope = derive_scope(duration)

    if settings.use_mock:
        script = _mock_script(req, duration)
        script.timeline = build_timeline(script)
        return script, "mock"

    messages = _build_messages(req, duration, scope)
    raw = _call_llm(messages)
    raw.setdefault("language", req.language)
    raw.setdefault("genre", req.genre or "drama")
    raw.setdefault("estimated_duration_minutes", duration)
    _coerce_emotions(raw)
    script = Script.model_validate(raw)
    script.timeline = build_timeline(script)
    return script, "llm"


# --------------------------------------------------------------------------- #
# Mock fallback (no API key needed)
# --------------------------------------------------------------------------- #

def _mock_script(req: GenerateRequest, duration: float) -> Script:
    genre = req.genre or "drama"
    topic = req.prompt.strip().rstrip(".")
    short = (topic[:60] + "…") if len(topic) > 60 else topic

    narrator = Narrator(
        style="omniscient",
        voice=VoiceProfile(
            gender=Gender.neutral, age_range="timeless", pitch="medium-low", pace="slow",
            accent="neutral", timbre="warm, resonant", base_emotion=Emotion.calm,
        ),
    )

    characters = [
        Character(
            id="maya", name="Maya", role="protagonist",
            description="A curious, determined woman in her early 30s who refuses easy answers.",
            motivation=f"To understand the truth behind: {short}.",
            emotional_arc="Moves from guarded skepticism to open-hearted resolve.",
            voice=VoiceProfile(
                gender=Gender.female, age_range="30s", pitch="medium", pace="medium",
                accent="neutral", timbre="warm", base_emotion=Emotion.determined,
            ),
        ),
        Character(
            id="eli", name="Eli", role="foil",
            description="Maya's pragmatic friend who grounds her wild theories in reality.",
            motivation="To keep Maya safe while secretly sharing her curiosity.",
            emotional_arc="Starts dismissive, ends a believer and ally.",
            voice=VoiceProfile(
                gender=Gender.male, age_range="30s", pitch="low", pace="fast",
                accent="US", timbre="dry, gravelly", base_emotion=Emotion.neutral,
            ),
        ),
    ]

    scenes = [
        Scene(
            number=1, heading="INT. SMALL APARTMENT - NIGHT",
            summary=f"Maya becomes obsessed with {short}.",
            mood="tense, curious", ambience="rain against windows, a ticking clock",
            elements=[
                SceneElement(kind="narration",
                    narration=f"Rain streaks the window of a cramped apartment. Maya stands before "
                    f"a wall of notes about {short}, while Eli lingers in the doorway."),
                SceneElement(kind="sound", sound=SoundCue(cue_type="sfx", description="a chair scrapes the floor")),
                SceneElement(kind="dialogue", dialogue=DialogueLine(
                    character_id="eli", character="Eli", emotion=Emotion.sarcastic, intensity=0.5,
                    line="You've been at this for three days. It's just a story.", direction="sighing")),
                SceneElement(kind="dialogue", dialogue=DialogueLine(
                    character_id="maya", character="Maya", emotion=Emotion.determined, intensity=0.8,
                    line="Stories start somewhere. I'm going to find out where this one did.")),
            ],
        ),
        Scene(
            number=2, heading="EXT. OLD PIER - DAWN",
            summary="A discovery changes everything.",
            mood="hopeful, uneasy", ambience="gentle surf, distant gulls, a low wind",
            elements=[
                SceneElement(kind="narration",
                    narration="Fog hangs over the water at dawn. Maya kneels on the wet sand and "
                    "uncovers something half-buried. Eli arrives, breathless."),
                SceneElement(kind="sound", sound=SoundCue(cue_type="sfx", description="wet sand shifting, a muffled clink")),
                SceneElement(kind="dialogue", dialogue=DialogueLine(
                    character_id="maya", character="Maya", emotion=Emotion.surprised, intensity=0.9,
                    line="I was right. It was real the whole time.", direction="whispering")),
                SceneElement(kind="dialogue", dialogue=DialogueLine(
                    character_id="eli", character="Eli", emotion=Emotion.fearful, intensity=0.7,
                    line="Okay. Okay. So what do we do now?")),
                SceneElement(kind="narration",
                    narration="They look at each other, then back at the discovery as the tide begins to turn."),
            ],
        ),
    ]

    return Script(
        title=f"The Matter of {short.title()}"[:80],
        logline=f"A relentless seeker and her reluctant friend chase the truth behind {short}.",
        genre=genre, language=req.language, estimated_duration_minutes=duration,
        synopsis=(
            f"Driven by an idea she can't shake — {short} — Maya pulls her skeptical friend Eli "
            "into an investigation that tests their friendship and rewrites what they believe is "
            "possible. (Sample output from MOCK mode; set LLM_API_KEY in .env for real AI generation.)"
        ),
        narrator=narrator, characters=characters, scenes=scenes,
    )
