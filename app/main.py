"""FastAPI application: serves the UI and the /generate endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audio.render import get_job, output_path, start_job
from .config import settings
from .formatter import to_screenplay
from .generator import generate_script
from .models import AudioJob, AudioRequest, GenerateRequest, GenerateResponse
from .timeline import build_timeline

app = FastAPI(
    title="Prompt → Script Generator",
    description="Turn a short prompt into a complete, structured script/story.",
    version="1.0.0",
)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "mock" if settings.use_mock else "llm",
        "model": settings.llm_model,
        "tts_provider": settings.resolved_tts_provider,
    }


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


@app.post("/audio", response_model=AudioJob, status_code=202)
def create_audio(req: AudioRequest) -> AudioJob:
    """Start rendering the script's timeline into audio. Poll GET /audio/{id}."""
    if not req.script.timeline:
        req.script.timeline = build_timeline(req.script)
    try:
        return start_job(req.script, req.provider, req.ambience)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/audio/{job_id}", response_model=AudioJob)
def audio_status(job_id: str) -> AudioJob:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown audio job")
    return job


@app.get("/audio/{job_id}/file")
def audio_file(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if job is None or job.status != "done":
        raise HTTPException(status_code=404, detail="Audio not ready")
    return FileResponse(output_path(job_id), media_type="audio/mpeg", filename=f"audio-drama-{job_id}.mp3")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Serve the rest of the static assets.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
