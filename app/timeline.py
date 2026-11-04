"""Flatten a Script's scenes into an ordered audio timeline.

The timeline is the production-facing view: a single ordered list of Utterances
that the downstream TTS + mixing stage can iterate without walking nested
scenes. This module also resolves/normalizes speaker references so every
dialogue utterance points at a real character id.
"""

from __future__ import annotations

from .models import Emotion, Script, Utterance


def _norm_id(value: str) -> str:
    return "".join(ch for ch in value.lower().strip() if ch.isalnum() or ch == "_")


def build_timeline(script: Script) -> list[Utterance]:
    # Map both ids and names to a canonical character for robust resolution,
    # since LLM output sometimes references a speaker by name instead of id.
    by_id: dict[str, tuple[str, str]] = {}  # key -> (id, display_name)
    for c in script.characters:
        by_id[_norm_id(c.id)] = (c.id, c.name)
        by_id[_norm_id(c.name)] = (c.id, c.name)

    timeline: list[Utterance] = []
    index = 0

    for scene in script.scenes:
        # A scene-level ambience bed, emitted once at the top of the scene.
        if scene.ambience:
            timeline.append(
                Utterance(
                    index=index,
                    scene_number=scene.number,
                    kind="sound",
                    speaker_id="sfx",
                    speaker_name="Ambience",
                    text="",
                    sound_cue={"cue_type": "ambience", "description": scene.ambience},
                )
            )
            index += 1

        for el in scene.elements:
            if el.kind == "narration" and el.narration:
                timeline.append(
                    Utterance(
                        index=index,
                        scene_number=scene.number,
                        kind="narration",
                        speaker_id=script.narrator.id,
                        speaker_name=script.narrator.name,
                        emotion=script.narrator.voice.base_emotion,
                        intensity=0.5,
                        text=el.narration,
                    )
                )
                index += 1

            elif el.kind == "dialogue" and el.dialogue:
                d = el.dialogue
                resolved = by_id.get(_norm_id(d.character_id)) or by_id.get(_norm_id(d.character))
                speaker_id, speaker_name = resolved if resolved else (d.character_id or "unknown", d.character)
                timeline.append(
                    Utterance(
                        index=index,
                        scene_number=scene.number,
                        kind="dialogue",
                        speaker_id=speaker_id,
                        speaker_name=speaker_name,
                        emotion=d.emotion,
                        intensity=d.intensity,
                        text=d.line,
                        direction=d.direction,
                    )
                )
                index += 1

            elif el.kind == "sound" and el.sound:
                timeline.append(
                    Utterance(
                        index=index,
                        scene_number=scene.number,
                        kind="sound",
                        speaker_id="sfx",
                        speaker_name="SFX",
                        emotion=Emotion.neutral,
                        text="",
                        sound_cue=el.sound,
                    )
                )
                index += 1

    return timeline
