"""Render a structured audio-drama Script into a readable script string."""

from __future__ import annotations

from .models import Script, VoiceProfile


def _wrap(text: str, width: int = 66, indent: str = "") -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(indent + current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(indent + current)
    return "\n".join(lines) if lines else indent


def _voice_str(v: VoiceProfile) -> str:
    parts = [v.gender.value, v.age_range, f"{v.pitch} pitch", f"{v.pace} pace"]
    if v.accent and v.accent != "neutral":
        parts.append(v.accent)
    if v.timbre:
        parts.append(v.timbre)
    return ", ".join(p for p in parts if p)


def to_screenplay(script: Script) -> str:
    out: list[str] = []
    out.append(script.title.upper())
    out.append("")
    out.append(f'"{script.logline}"')
    out.append("")
    out.append(f"Genre: {script.genre}  |  Language: {script.language}  |  "
               f"Est. runtime: {script.estimated_duration_minutes:g} min  |  AUDIO DRAMA")
    out.append("")
    out.append("SYNOPSIS")
    out.append(_wrap(script.synopsis))
    out.append("")

    out.append("CAST & VOICES")
    out.append(f"  NARRATOR ({script.narrator.style})")
    out.append(_wrap(f"Voice: {_voice_str(script.narrator.voice)}", indent="    "))
    out.append("")
    for c in script.characters:
        out.append(f"  {c.name} [{c.id}] — {c.role}")
        out.append(_wrap(c.description, indent="    "))
        out.append(_wrap(f"Wants: {c.motivation}", indent="    "))
        out.append(_wrap(f"Arc: {c.emotional_arc}", indent="    "))
        out.append(_wrap(f"Voice: {_voice_str(c.voice)}", indent="    "))
        out.append("")

    out.append("=" * 68)
    out.append("")

    for scene in script.scenes:
        out.append(f"SCENE {scene.number} — {scene.heading}")
        out.append(f"   [{scene.mood}] {scene.summary}")
        if scene.ambience:
            out.append(f"   AMBIENCE: {scene.ambience}")
        out.append("")
        for el in scene.elements:
            if el.kind == "narration" and el.narration:
                out.append(_wrap(f"NARRATOR: {el.narration}"))
                out.append("")
            elif el.kind == "sound" and el.sound:
                out.append(f"   >> SOUND [{el.sound.cue_type}]: {el.sound.description}")
                out.append("")
            elif el.kind == "dialogue" and el.dialogue:
                d = el.dialogue
                out.append(f"{'':>18}{d.character.upper()}")
                note = d.direction if d.direction else d.emotion.value
                out.append(f"{'':>16}({note}, {d.emotion.value} {d.intensity:.1f})")
                out.append(_wrap(d.line, width=42, indent=" " * 10))
                out.append("")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
