"""The generation engine.

Responsibilities:
  * Infer a sensible duration when the user doesn't give one.
  * Derive scope (scene count, character count, word budget) from the duration.
  * Build a strong instruction prompt and ask an OpenAI-compatible LLM for a
    structured JSON script.
  * Validate the result against our Pydantic models.
  * Provide a deterministic mock script when no API key is configured, so the
    whole app works out of the box.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from .config import settings
from .models import (
    Character,
    DialogueLine,
    GenerateRequest,
    Scene,
    SceneElement,
    Script,
)

# Roughly how many spoken words land in a minute of screen time. Used to size
# the script when scaling to a target duration.
WORDS_PER_MINUTE = 130


def infer_duration(prompt: str) -> float:
    """Pick a target runtime (minutes) when the user didn't specify one.

    Heuristic: start from a short-film baseline and nudge up for prompts that
    describe bigger, multi-beat stories. Also honor an explicit mention like
    "10 minute" / "2 min" in the prompt text.
    """
    explicit = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(min|minute|minutes|hour|hours|hr|hrs)", prompt.lower())
    if explicit:
        value = float(explicit.group(1))
        unit = explicit.group(2)
        if unit.startswith("h"):
            value *= 60
        return max(0.5, min(value, 600))

    words = len(prompt.split())
    base = 3.0
    if words > 40:
        base += 3
    if words > 80:
        base += 4
    # Epics / series hints.
    if re.search(r"\b(epic|saga|series|feature|movie|film)\b", prompt.lower()):
        base += 5
    return float(min(base, 20))


def derive_scope(duration_minutes: float) -> dict:
    """Translate a runtime into concrete structural targets."""
    scenes = max(2, round(duration_minutes / 1.5))
    scenes = min(scenes, 30)
    characters = 2 if duration_minutes <= 3 else 3 if duration_minutes <= 8 else 5
    word_budget = int(duration_minutes * WORDS_PER_MINUTE)
    return {
        "scenes": scenes,
        "characters": characters,
        "word_budget": word_budget,
    }


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

def _build_messages(req: GenerateRequest, duration: float, scope: dict) -> list[dict]:
    genre = req.genre or "let the story dictate the most fitting genre"
    schema_hint = {
        "title": "string",
        "logline": "one sentence",
        "genre": "string",
        "language": req.language,
        "estimated_duration_minutes": duration,
        "synopsis": "one short paragraph",
        "characters": [
            {
                "name": "string",
                "role": "protagonist/antagonist/etc",
                "description": "background, appearance, personality",
                "motivation": "what they want",
                "emotional_arc": "how their emotions change",
                "voice_profile": "pitch, pace, accent, age for TTS",
            }
        ],
        "scenes": [
            {
                "number": 1,
                "heading": "INT./EXT. LOCATION - TIME",
                "summary": "one line",
                "mood": "emotional atmosphere",
                "elements": [
                    {"kind": "action", "action": "scene direction text", "dialogue": None},
                    {
                        "kind": "dialogue",
                        "action": "",
                        "dialogue": {
                            "character": "name",
                            "emotion": "primary emotion",
                            "line": "the spoken words",
                            "parenthetical": "optional delivery note",
                        },
                    },
                ],
            }
        ],
    }

    system = (
        "You are an expert screenwriter and story developer. You turn a short prompt "
        "into a complete, coherent, emotionally rich script. You always respond with a "
        "single valid JSON object and nothing else — no markdown, no commentary."
    )

    user = f"""Write a complete script/story from this prompt.

PROMPT: {req.prompt}

REQUIREMENTS:
- Language: {req.language}
- Genre/tone: {genre}
- Target runtime: about {duration:g} minute(s).
- Structure the story into roughly {scope['scenes']} scenes.
- Include about {scope['characters']} well-developed characters. Give each a clear
  motivation, a personality, an emotional arc, and a voice profile.
- Aim for roughly {scope['word_budget']} words of spoken dialogue total, distributed
  across the scenes so the runtime feels right.
- Every scene must have a slugline heading, a mood, a one-line summary, and an ordered
  list of elements mixing 'action' directions and 'dialogue' lines.
- Every dialogue line MUST carry an 'emotion'. Use parentheticals for delivery notes.
- Make it feel complete: clear beginning, middle, and end; real conflict; a resolution.

Respond with ONLY a JSON object matching exactly this shape (same keys, same nesting):

{json.dumps(schema_hint, indent=2)}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _extract_json(text: str) -> dict:
    """Parse JSON from a model response, tolerating stray markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to grabbing the outermost {...} block.
        start = text.find("{")
        end = text.rfind("}")
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
        if resp.status_code >= 400:
            # Retry once without response_format for providers that don't support it.
            if "response_format" in resp.text or resp.status_code in (400, 422):
                payload.pop("response_format", None)
                resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _extract_json(content)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def generate_script(req: GenerateRequest) -> tuple[Script, str]:
    """Return (script, mode) where mode is 'llm' or 'mock'."""
    duration = req.duration_minutes or infer_duration(req.prompt)
    scope = derive_scope(duration)

    if settings.use_mock:
        return _mock_script(req, duration), "mock"

    messages = _build_messages(req, duration, scope)
    raw = _call_llm(messages)
    # Ensure required scalar fields have sane fallbacks before validation.
    raw.setdefault("language", req.language)
    raw.setdefault("genre", req.genre or "drama")
    raw.setdefault("estimated_duration_minutes", duration)
    script = Script.model_validate(raw)
    return script, "llm"


# --------------------------------------------------------------------------- #
# Mock fallback (no API key needed)
# --------------------------------------------------------------------------- #

def _mock_script(req: GenerateRequest, duration: float) -> Script:
    genre = req.genre or "drama"
    topic = req.prompt.strip().rstrip(".")
    short = (topic[:60] + "…") if len(topic) > 60 else topic

    characters = [
        Character(
            name="Maya",
            role="protagonist",
            description="A curious, determined woman in her early 30s who refuses to accept easy answers.",
            motivation=f"To understand the truth behind: {short}.",
            emotional_arc="Moves from guarded skepticism to open-hearted resolve.",
            voice_profile="Warm mid-range alto, measured pace, faint regional accent.",
        ),
        Character(
            name="Eli",
            role="foil",
            description="Maya's pragmatic friend who grounds her wild theories in reality.",
            motivation="To keep Maya safe while secretly sharing her curiosity.",
            emotional_arc="Starts dismissive, ends as a believer and ally.",
            voice_profile="Low, dry, slightly gravelly; quick witted delivery.",
        ),
    ]

    scenes = [
        Scene(
            number=1,
            heading="INT. SMALL APARTMENT - NIGHT",
            summary=f"Maya becomes obsessed with {short}.",
            mood="tense, curious",
            elements=[
                SceneElement(
                    kind="action",
                    action=f"Rain streaks the window. MAYA stares at a wall of notes about "
                    f"{short}. ELI leans in the doorway, arms crossed.",
                ),
                SceneElement(
                    kind="dialogue",
                    dialogue=DialogueLine(
                        character="Eli",
                        emotion="skeptical",
                        line="You've been at this for three days. It's just a story.",
                        parenthetical="sighing",
                    ),
                ),
                SceneElement(
                    kind="dialogue",
                    dialogue=DialogueLine(
                        character="Maya",
                        emotion="determined",
                        line="Stories start somewhere. I'm going to find out where this one did.",
                    ),
                ),
            ],
        ),
        Scene(
            number=2,
            heading="EXT. OLD PIER - DAWN",
            summary="A discovery changes everything.",
            mood="hopeful, uneasy",
            elements=[
                SceneElement(
                    kind="action",
                    action="Fog hangs over the water. Maya kneels, uncovering something half-buried "
                    "in the sand. Eli arrives, breathless.",
                ),
                SceneElement(
                    kind="dialogue",
                    dialogue=DialogueLine(
                        character="Maya",
                        emotion="awestruck",
                        line="I was right. It was real the whole time.",
                        parenthetical="whispering",
                    ),
                ),
                SceneElement(
                    kind="dialogue",
                    dialogue=DialogueLine(
                        character="Eli",
                        emotion="stunned",
                        line="Okay. Okay. So what do we do now?",
                    ),
                ),
                SceneElement(
                    kind="action",
                    action="They look at each other, then back at the discovery. The tide begins to turn.",
                ),
            ],
        ),
    ]

    return Script(
        title=f"The Matter of {short.title()}"[:80],
        logline=f"A relentless seeker and her reluctant friend chase the truth behind {short}.",
        genre=genre,
        language=req.language,
        estimated_duration_minutes=duration,
        synopsis=(
            f"Driven by an idea she can't shake — {short} — Maya pulls her skeptical friend Eli "
            "into an investigation that tests their friendship and rewrites what they believe is "
            "possible. (This is sample output from MOCK mode; set LLM_API_KEY in .env for real "
            "AI-generated scripts.)"
        ),
        characters=characters,
        scenes=scenes,
    )
