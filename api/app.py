"""
Local API for the Adaptive CSV Analytics engine. The website talks only to this.

Run (from the project folder; keep it running in its own terminal):
  python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
Interactive docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.jobs import Busy, FilterIn, Job, JobStore, apply_filters
from engine.discover.loader import MAX_FILE_MB
from engine.sql import QueryError

store = JobStore()

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    store.close_all()

app = FastAPI(title="Adaptive CSV Analytics API", version="0.1.0", lifespan=lifespan)
ORIGINS = [o.strip() for o in os.getenv("API_CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type"])

class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)

class FiltersIn(BaseModel):
    filters: list[FilterIn] = Field(default_factory=list, max_length=10)

def _job(job_id: str) -> Job:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "No analysis with this id.")
    return job

@app.get("/health")
def health() -> dict:
    return {"ok": True}

@app.post("/analyses", status_code=202)
async def create_analysis(file: UploadFile = File(...)) -> dict:
    limit = int(MAX_FILE_MB * 1_048_576)
    data = await file.read(limit + 1)
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > limit:
        raise HTTPException(413, f"The file is larger than {MAX_FILE_MB:g} MB.")
    name = os.path.basename(file.filename or "")[:200] or "upload.csv"
    try:
        job = store.start(name, data)
    except Busy as exc:
        raise HTTPException(429, str(exc)) from None
    except (RuntimeError, ValueError) as exc:          # e.g. no API key in .env
        raise HTTPException(503, f"Settings problem: {exc}") from None
    return job.view()

@app.get("/analyses/{job_id}")
def get_analysis(job_id: str) -> dict:
    return _job(job_id).view()

@app.post("/analyses/{job_id}/answer", status_code=202)
def answer_question(job_id: str, body: AnswerIn) -> dict:
    job = _job(job_id)
    try:
        job.answer(body.answer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return job.view()

@app.get("/analyses/{job_id}/dashboard")
def get_dashboard(job_id: str) -> dict:
    job = _job(job_id)
    if job.status != "done" or job.dashboard is None:
        raise HTTPException(409, f"The dashboard is not ready (status: {job.status}).")
    return job.dashboard

@app.post("/analyses/{job_id}/filters")
def filter_dashboard(job_id: str, body: FiltersIn) -> dict:
    job = _job(job_id)
    try:
        return apply_filters(job, body.filters)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except QueryError as exc:
        raise HTTPException(400, exc.message) from None

@app.delete("/analyses/{job_id}")
def delete_analysis(job_id: str) -> dict:
    try:
        removed = store.delete(job_id)
    except Busy as exc:
        raise HTTPException(409, str(exc)) from None
    if not removed:
        raise HTTPException(404, "No analysis with this id.")
    return {"deleted": job_id}
