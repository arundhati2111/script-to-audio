"""Render a structured Script into a human-readable screenplay string."""

from __future__ import annotations

from .models import Script


def _wrap(text: str, width: int = 60, indent: str = "") -> str:
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


def to_screenplay(script: Script) -> str:
    out: list[str] = []
    out.append(script.title.upper())
    out.append("")
    out.append(f'"{script.logline}"')
    out.append("")
    out.append(f"Genre: {script.genre}    |    Language: {script.language}    |    "
               f"Est. runtime: {script.estimated_duration_minutes:g} min")
    out.append("")
    out.append("SYNOPSIS")
    out.append(_wrap(script.synopsis))
    out.append("")
    out.append("CHARACTERS")
    for c in script.characters:
        out.append(f"  {c.name} — {c.role}")
        out.append(_wrap(c.description, indent="    "))
        out.append(_wrap(f"Wants: {c.motivation}", indent="    "))
        out.append(_wrap(f"Arc: {c.emotional_arc}", indent="    "))
        if c.voice_profile:
            out.append(_wrap(f"Voice: {c.voice_profile}", indent="    "))
        out.append("")

    out.append("=" * 60)
    out.append("")

    for scene in script.scenes:
        out.append(f"{scene.number}. {scene.heading}")
        out.append(f"   [{scene.mood}] {scene.summary}")
        out.append("")
        for el in scene.elements:
            if el.kind == "action" and el.action:
                out.append(_wrap(el.action))
                out.append("")
            elif el.kind == "dialogue" and el.dialogue:
                d = el.dialogue
                speaker = f"{'':>20}{d.character.upper()}"
                out.append(speaker)
                note = f"({d.parenthetical})" if d.parenthetical else f"({d.emotion})"
                out.append(f"{'':>18}{note}")
                out.append(_wrap(d.line, width=40, indent=" " * 10))
                out.append("")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
