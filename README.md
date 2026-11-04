# Prompt → Audio Drama Script Generator

Give a short prompt, get back a complete script written **for an audio drama**: a
narrator, a cast of characters each with a distinct machine-usable voice, emotion-tagged
dialogue (with intensity), and sound cues. The output also includes a flat, ordered
**audio timeline** — the exact sequence of narration, dialogue, and sound events — so a
downstream text-to-speech + mixing stage can render it into audio with different speakers
and emotions.

This is **step one** of a larger pipeline: prompt → script → audio drama.

## Features

- **Prompt-driven generation** — one idea in, a full audio-drama script out.
- **Audio-first structure** — a narrator voices action/setting (nothing is "shown"),
  every character has a structured voice, and sound design (ambience + SFX) is first-class.
- **Voice casting data** — each speaker carries gender, age range, pitch, pace, accent,
  timbre, and a base emotion, so each maps cleanly onto a distinct TTS voice.
- **Controlled emotions** — dialogue uses a fixed emotion vocabulary plus a 0.0–1.0
  intensity, which maps reliably onto TTS/SSML speaking styles.
- **Audio timeline** — a flat, ordered list of utterances (narration/dialogue/sound) with
  resolved speaker + emotion, ready for rendering.
- **Duration control** — pass `duration_minutes`, or the engine infers and scales the script.
- **Pluggable LLM** — any OpenAI-compatible API (OpenAI, OpenRouter, Groq, local Ollama).
- **Mock mode** — runs with no API key for instant local testing.

## Requirements

- Python 3.10+
- An OpenAI-compatible API key (optional — omit it to run in mock mode)

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env and add your LLM_API_KEY (optional)
```

If you leave `LLM_API_KEY` empty, the app runs in **mock mode** and returns a
deterministic sample script — handy for trying the UI and API without any external calls.

## Run

```bash
uvicorn app.main:app --reload
```

Then open http://localhost:8000 in your browser.

## API

### `POST /generate`

Request body:

```json
{
  "prompt": "A lighthouse keeper discovers a message in a bottle from the future.",
  "duration_minutes": 5,
  "genre": "drama",
  "language": "English"
}
```

- `prompt` (required) — your story idea.
- `duration_minutes` (optional) — target runtime; inferred if omitted.
- `genre` (optional) — tone hint (free text or a known genre).
- `language` (optional, default `English`).

Response:
- `script` — the structured audio drama. Key fields:
  - `narrator` — `{ id, name, style, voice }`
  - `characters[]` — each with `id`, `name`, `role`, `description`, `motivation`,
    `emotional_arc`, and a structured `voice`
  - `scenes[]` — each with `heading`, `mood`, `ambience`, and ordered `elements`
    (`narration` / `dialogue` / `sound`)
  - `timeline[]` — the flat, ordered list of `Utterance`s for the audio renderer
- `screenplay_text` — a human-readable rendering of the script.
- `mode` — `"llm"` or `"mock"`.

Each dialogue `Utterance` in `timeline` carries `speaker_id`, `speaker_name`, `emotion`,
`intensity`, and `text` — everything the TTS stage needs, with no scene-walking required.

Interactive API docs are available at http://localhost:8000/docs.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable       | Default                      | Purpose                                              |
| -------------- | ---------------------------- | ---------------------------------------------------- |
| `LLM_API_KEY`  | _(empty)_                    | API key. Empty → mock mode.                          |
| `LLM_BASE_URL` | `https://api.openai.com/v1`  | OpenAI-compatible endpoint base URL.                 |
| `LLM_MODEL`    | `gpt-4o-mini`                | Model name.                                          |
| `LLM_TIMEOUT`  | `120`                        | LLM request timeout in seconds.                      |

## Project structure

```
app/
  __init__.py
  config.py       # env-based settings
  models.py       # Pydantic models (the audio-drama data contract)
  generator.py    # duration inference, prompt building, LLM call, mock fallback
  timeline.py     # flatten scenes -> ordered audio timeline (resolves speakers)
  formatter.py    # structured script -> readable audio-drama script
  main.py         # FastAPI app + routes
  static/         # web UI (Script / Cast & Scenes / Audio Timeline views)
```

## Audio drama rendering

After generating a script, click **Generate audio** in the UI (or call the API). The
renderer consumes `script.timeline`:

1. **Casting** - every speaker gets a different voice, matched on gender, accent and age.
2. **Acting** - each line is voiced with its `emotion` and `intensity`.
   - `openai` engine: emotion, voice traits and delivery notes are sent as acting
     instructions to `gpt-4o-mini-tts` (real emotional performance).
   - `edge` engine (free, no key): emotion is expressed through rate, pitch and volume,
     so it is more subtle.
3. **Mixing** - characters are panned across the stereo field, loudness is balanced per
   line, pauses are timed from punctuation and directions, scene ambience beds and sound
   effects are synthesized locally and layered in, and the result is exported as MP3.

Requires `ffmpeg` on the PATH.

### API

- `POST /audio` - body `{ "script": <Script>, "provider": "edge|openai|mock" (optional), "ambience": true }`.
  Returns `202` with a job (`id`, `status`, `progress`).
- `GET /audio/{id}` - job status. When `done` it includes `audio_url`, `duration_seconds`,
  the voice `cast`, and per-line `segments` (start/end seconds).
- `GET /audio/{id}/file` - the MP3.

Jobs are kept in memory and files are written to `AUDIO_OUTPUT_DIR`.

Audio settings: `TTS_PROVIDER`, `TTS_API_KEY`, `TTS_BASE_URL`, `TTS_MODEL`, `TTS_TIMEOUT`,
`TTS_CONCURRENCY`, `AUDIO_OUTPUT_DIR` (see `.env.example`).

## Roadmap

- Swap the synthesized ambience/SFX for a real sound-effect library.
- Music beds and stingers between scenes.
- Persist jobs across restarts.
