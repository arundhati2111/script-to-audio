# Prompt → Script Generator

Give a short prompt, get back a complete, structured script/story: title, logline,
characters (with motivations, emotional arcs, and voice profiles), and scenes broken
into actions and emotion-tagged dialogue. You can set a target duration, or let the
engine pick a sensible length for you.

This is **step one** of a larger pipeline — the structured output is designed to be
consumed by later stages (for example, turning the script into audio).

## Features

- **Prompt-driven generation** — one idea in, a full script out.
- **Structured output** — strongly-typed JSON (characters, scenes, dialogue, emotions)
  plus a human-readable screenplay view.
- **Duration control** — pass `duration_minutes`, or the engine infers it from the prompt
  and scales the number of scenes and dialogue accordingly.
- **Pluggable LLM** — works with any OpenAI-compatible API (OpenAI, OpenRouter, Groq,
  local Ollama, etc.).
- **Mock mode** — runs with no API key for instant local testing with a deterministic
  sample script.

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

Response: a `script` object (structured), a `screenplay_text` string (formatted), and
`mode` (`"llm"` or `"mock"`).

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
  models.py       # Pydantic models (the script data contract)
  generator.py    # duration inference, prompt building, LLM call, mock fallback
  formatter.py    # structured script -> readable screenplay
  main.py         # FastAPI app + routes
  static/         # web UI
```

## Roadmap

This generator is the foundation. Planned next steps for the larger project include
voice casting per character and text-to-speech rendering of the dialogue.
