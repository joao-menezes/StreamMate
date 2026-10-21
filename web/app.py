"""StreamMate Web — mesma lógica do app desktop, servida por HTTP para uso na rede interna.

Os arquivos ficam no servidor só enquanto o job existe (STREAMMATE_JOB_TTL_MINUTES) e
cada navegador só enxerga os jobs que ele mesmo criou.
"""
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants.app_constants import AppConstants  # noqa: E402
from constants.media_formats import AUDIO_FORMATS, VIDEO_FORMATS, extension_for  # noqa: E402
from services.conversion_service import ConversionCancelled, ConversionService  # noqa: E402
from services.download_service import DownloadService  # noqa: E402
from services.playlist_service import is_playlist, read_playlist  # noqa: E402

DATA_DIR = os.environ.get("STREAMMATE_DATA_DIR", os.path.join(tempfile.gettempdir(),
                                                              "streammate-web"))
MAX_WORKERS = int(os.environ.get("STREAMMATE_MAX_JOBS", "2"))
JOB_TTL = int(os.environ.get("STREAMMATE_JOB_TTL_MINUTES", "60")) * 60
MAX_UPLOAD = int(os.environ.get("STREAMMATE_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
ALLOW_DOWNLOADS = os.environ.get("STREAMMATE_ENABLE_YOUTUBE", "true").lower() != "false"

os.makedirs(DATA_DIR, exist_ok=True)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def safe_name(name: str, fallback: str = "arquivo") -> str:
    name = os.path.basename(name or "")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return name[:150] or fallback


@dataclass
class Job:
    kind: str                       # "convert" | "download"
    title: str
    format: str
    source: str
    workdir: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: str = "queued"           # queued | running | done | error | cancelled
    progress: Optional[float] = None
    message: str = "na fila"
    output: Optional[str] = None
    created: float = field(default_factory=time.time)
    service: ConversionService = field(default_factory=ConversionService)
    cancelled: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "format": self.format,
            "state": self.state, "progress": self.progress, "message": self.message,
            "filename": os.path.basename(self.output) if self.output else None,
            "size": os.path.getsize(self.output) if self.output and os.path.exists(self.output)
            else None,
        }


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
app = FastAPI(title="StreamMate", version=AppConstants.VERSION, docs_url=None, redoc_url=None)


def _run_job(job: Job) -> None:
    if job.cancelled.is_set():
        return
    job.state, job.message, job.progress = "running", "processando", None

    def on_progress(value: float):
        job.progress = value
        job.message = "convertendo"

    try:
        if job.kind == "download":
            def status(message, value):
                job.message = message.lower().rstrip(".…")
                job.progress = value
            downloader = DownloadService(job.service)
            path, _ = downloader.download(job.source, job.workdir, job.format, status)
            job.output = path
        else:
            base = os.path.splitext(job.title)[0] or "convertido"
            output = os.path.join(job.workdir, "out", f"{safe_name(base)}.{extension_for(job.format)}")
            os.makedirs(os.path.dirname(output), exist_ok=True)
            info = job.service.probe(job.source)
            if not info.has_video and job.format in VIDEO_FORMATS:
                # arquivo só de áudio com saída de vídeo escolhida: entrega em MP3
                job.format = "mp3"
                output = os.path.splitext(output)[0] + ".mp3"
            job.service.convert(job.source, output, job.format, on_progress, info=info)
            job.output = output
        job.state, job.message, job.progress = "done", "pronto", 1.0
    except ConversionCancelled:
        job.state, job.message = "cancelled", "cancelado"
    except Exception as error:  # noqa: BLE001
        if job.cancelled.is_set():
            job.state, job.message = "cancelled", "cancelado"
        else:
            job.state = "error"
            lines = [l for l in str(error).strip().splitlines() if l.strip()]
            job.message = lines[0][:160] if lines else "erro"


def _submit(job: Job) -> Job:
    with jobs_lock:
        jobs[job.id] = job
    executor.submit(_run_job, job)
    return job


def _cleanup_loop() -> None:
    while True:
        time.sleep(60)
        now = time.time()
        with jobs_lock:
            expired = [j for j in jobs.values()
                       if now - j.created > JOB_TTL and j.state not in ("queued", "running")]
            for j in expired:
                jobs.pop(j.id, None)
        for j in expired:
            shutil.rmtree(j.workdir, ignore_errors=True)
        # uploads de lotes antigos (os jobs que os usavam já expiraram)
        for name in os.listdir(DATA_DIR):
            path = os.path.join(DATA_DIR, name)
            if name.startswith("batch-") and now - os.path.getmtime(path) > JOB_TTL * 2:
                shutil.rmtree(path, ignore_errors=True)


threading.Thread(target=_cleanup_loop, daemon=True).start()


async def _save_upload(upload: UploadFile, folder: str) -> str:
    path = os.path.join(folder, safe_name(upload.filename))
    written = 0
    with open(path, "wb") as out:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD:
                raise HTTPException(413, f"Arquivo maior que o limite de "
                                         f"{MAX_UPLOAD // (1024 * 1024)} MB.")
            out.write(chunk)
    return path


# ------------------------------------------------------------------- API
@app.get("/api/config")
def config():
    return {
        "version": AppConstants.VERSION,
        "video_formats": {k: v[0] for k, v in VIDEO_FORMATS.items()},
        "audio_formats": {k: v[0] for k, v in AUDIO_FORMATS.items()},
        "youtube": ALLOW_DOWNLOADS,
        "max_upload_mb": MAX_UPLOAD // (1024 * 1024),
        "ttl_minutes": JOB_TTL // 60,
    }


@app.post("/api/convert")
async def convert(files: list[UploadFile] = File(...), format: str = Form("mp4")):
    if format not in VIDEO_FORMATS and format not in AUDIO_FORMATS:
        raise HTTPException(400, "Formato de saída inválido.")
    batch_dir = tempfile.mkdtemp(prefix="batch-", dir=DATA_DIR)
    uploads_dir = os.path.join(batch_dir, "uploads")
    os.makedirs(uploads_dir)

    saved = [await _save_upload(f, uploads_dir) for f in files]
    playlists = [p for p in saved if is_playlist(p)]
    media = [p for p in saved if not is_playlist(p)]
    by_name = {os.path.basename(p).lower(): p for p in media}
    used: set[str] = set()

    created, skipped = [], []

    def add(source: str, title: str):
        workdir = tempfile.mkdtemp(prefix="job-", dir=DATA_DIR)
        created.append(_submit(Job("convert", title, format, source, workdir)).public())

    for playlist in playlists:
        try:
            entries = read_playlist(playlist)
        except Exception as error:  # noqa: BLE001
            skipped.append({"title": os.path.basename(playlist), "reason": str(error)})
            continue
        for entry in entries:
            if entry.is_url:
                add(entry.source, safe_name(entry.title, "stream"))
                continue
            if os.path.abspath(entry.source) == os.path.abspath(playlist):  # HLS local
                add(playlist, os.path.basename(playlist))
                continue
            # playlists criadas no Windows usam "\" mesmo quando o servidor é Linux
            match = by_name.get(re.split(r"[\\/]", entry.source)[-1].lower())
            if match:
                used.add(match)
                add(match, os.path.basename(match))
            else:
                skipped.append({
                    "title": entry.title,
                    "reason": "o arquivo está no computador de quem criou a playlist — "
                              "envie o vídeo junto com o .vlc",
                })

    for path in media:
        if path not in used:
            add(path, os.path.basename(path))

    if not created and not skipped:
        raise HTTPException(400, "Nenhum arquivo recebido.")
    return {"jobs": created, "skipped": skipped}


class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"


@app.post("/api/download")
def download(req: DownloadRequest):
    if not ALLOW_DOWNLOADS:
        raise HTTPException(403, "Downloads do YouTube estão desativados neste servidor.")
    if req.format not in VIDEO_FORMATS and req.format not in AUDIO_FORMATS:
        raise HTTPException(400, "Formato inválido.")
    url = req.url.strip()
    if not re.match(r"^https?://", url):
        raise HTTPException(400, "Cole um link começando com http:// ou https://")
    workdir = tempfile.mkdtemp(prefix="job-", dir=DATA_DIR)
    job = _submit(Job("download", url, req.format, url, workdir))
    return job.public()


@app.get("/api/jobs")
def list_jobs(ids: str = ""):
    wanted = [i for i in ids.split(",") if i]
    with jobs_lock:
        return {"jobs": [jobs[i].public() for i in wanted if i in jobs]}


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str):
    job = jobs.get(job_id)
    if not job or job.state != "done" or not job.output or not os.path.exists(job.output):
        raise HTTPException(404, "Arquivo não disponível (pode ter expirado).")
    return FileResponse(job.output, filename=os.path.basename(job.output))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    with jobs_lock:
        job = jobs.pop(job_id, None)
    if not job:
        return {"ok": True}
    job.cancelled.set()
    job.service.cancel()
    shutil.rmtree(job.workdir, ignore_errors=True)
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok", "jobs": len(jobs)}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
