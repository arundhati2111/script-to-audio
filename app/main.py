"""FastAPI application: serves the UI and the /generate endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .formatter import to_screenplay
from .generator import generate_script
from .models import GenerateRequest, GenerateResponse

app = FastAPI(
    title="Prompt → Script Generator",
    description="Turn a short prompt into a complete, structured script/story.",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "mock" if settings.use_mock else "llm", "model": settings.llm_model}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    try:
        script, mode = generate_script(req)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc

    return GenerateResponse(
        script=script,
        screenplay_text=to_screenplay(script),
        mode=mode,
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Serve the rest of the static assets.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
