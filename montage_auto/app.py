import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from montage_auto.ai_director import analyze_and_plan_montage
from montage_auto.config import (
    BASE_DIR,
    FONTS_DIR,
    HOST,
    OUTPUTS_DIR,
    PORT,
    PROJECT_ROOT,
    RUSHS_DIR,
    UPLOADS_VIDEOS_DIR,
)
from montage_auto.history_manager import (
    add_history_entry,
    delete_history_entry,
    get_all_history,
)
from montage_auto.video_editor import render_montage

app = FastAPI(title="BCHEF Montage Studio", version="1.0.0")

# Mount static and media directories
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
ROOT_ASSETS_DIR = PROJECT_ROOT / "assets"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/rushs-media", StaticFiles(directory=str(RUSHS_DIR)), name="rushs_media")
if ROOT_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ROOT_ASSETS_DIR)), name="assets")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# In-memory jobs tracking
ACTIVE_JOBS = {}


class MontageRequest(BaseModel):
    rush_paths: List[str]
    target_duration: int = 25
    music_choice: str = "auto"
    custom_hook: Optional[str] = ""
    burn_hook: bool = False


def get_video_duration(path: Path) -> float:
    """Uses ffprobe to obtain video duration in seconds."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return round(float(res.stdout.strip()), 1)
    except Exception:
        pass
    return 0.0


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Main dashboard interface."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/rushs")
async def list_rushs():
    """Returns all available rush videos stored in rushs/ directory."""
    rushs = []
    supported_exts = {".mov", ".mp4", ".m4v"}
    
    for p in sorted(RUSHS_DIR.rglob("*")):
        if p.is_file() and p.suffix.lower() in supported_exts:
            rel = str(p.relative_to(RUSHS_DIR))
            dur = get_video_duration(p)
            size_mb = round(p.stat().st_size / (1024 * 1024), 1)
            rushs.append({
                "name": p.name,
                "relative_path": rel,
                "folder": p.parent.name if p.parent != RUSHS_DIR else "",
                "duration": dur,
                "size_mb": size_mb,
            })
    return {"rushs": rushs}


@app.post("/api/rushs/upload")
async def upload_rushs(files: List[UploadFile] = File(...)):
    """Uploads 1 or more video rushs."""
    upload_dir = RUSHS_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []

    for file in files:
        safe_name = f"{int(datetime.now().timestamp())}_{file.filename.replace(' ', '_')}"
        dest = upload_dir / safe_name
        with open(dest, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        dur = get_video_duration(dest)
        size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
        rel = str(dest.relative_to(RUSHS_DIR))
        uploaded.append({
            "name": safe_name,
            "relative_path": rel,
            "duration": dur,
            "size_mb": size_mb,
        })

    return {"uploaded": uploaded}


@app.delete("/api/rushs/{rush_path:path}")
async def delete_rush(rush_path: str):
    """Deletes a raw rush file from rushs directory to free disk space."""
    try:
        clean_path = Path(rush_path).as_posix().lstrip("/")
        target = (RUSHS_DIR / clean_path).resolve()
        rushs_root = RUSHS_DIR.resolve()

        if not str(target).startswith(str(rushs_root)):
            raise HTTPException(status_code=400, detail="Chemin non autorisé.")

        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="Fichier rush introuvable.")

        filename = target.name
        target.unlink()
        return {"success": True, "message": f"Rush '{filename}' supprimé avec succès."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def run_montage_background_job(job_id: str, request_data: MontageRequest):
    """Worker running in a background thread."""
    try:
        ACTIVE_JOBS[job_id]["progress"] = 5
        ACTIVE_JOBS[job_id]["message"] = "Vérification des rushs sélectionnés..."

        # Resolve paths
        video_paths = []
        for rp in request_data.rush_paths:
            p = RUSHS_DIR / rp
            if not p.exists():
                # Try relative to base or absolute
                p = Path(rp)
            if p.exists() and p.is_file():
                video_paths.append(p)

        if not video_paths:
            raise ValueError("Aucun fichier rush valide trouvé.")

        ACTIVE_JOBS[job_id]["progress"] = 15
        ACTIVE_JOBS[job_id]["message"] = "Analyse multimodale des rushs avec Gemini 3.8 Flash..."

        plan = analyze_and_plan_montage(
            video_paths=video_paths,
            target_duration=request_data.target_duration,
            music_mode=request_data.music_choice,
            custom_hook=request_data.custom_hook or "",
        )
        plan["burn_hook"] = bool(request_data.burn_hook)

        ACTIVE_JOBS[job_id]["progress"] = 40
        ACTIVE_JOBS[job_id]["message"] = "Plan de montage et transcription générés. Démarrage de la découpe et du rendu..."

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"montage_{timestamp_str}_{job_id}.mp4"
        output_path = OUTPUTS_DIR / output_filename

        def on_progress(pct: int, msg: str):
            # Scale 40 to 95%
            mapped = int(40 + (pct / 100.0) * 55)
            ACTIVE_JOBS[job_id]["progress"] = mapped
            ACTIVE_JOBS[job_id]["message"] = msg

        render_res = render_montage(
            plan=plan,
            source_video_paths=video_paths,
            output_path=output_path,
            progress_callback=on_progress,
        )

        final_dur = get_video_duration(output_path)

        # Record history
        entry = {
            "id": job_id,
            "filename": output_filename,
            "video_url": f"/outputs/{output_filename}",
            "created_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "hook": plan.get("hook", ""),
            "description": plan.get("description", ""),
            "hashtags": plan.get("hashtags", []),
            "duration": final_dur,
            "music_style": plan.get("musique_style", "lofi"),
            "rush_count": len(video_paths),
            "sources": [p.name for p in video_paths],
            "transcription_count": len(plan.get("transcription", [])),
            "burn_hook": bool(request_data.burn_hook),
        }
        add_history_entry(entry)

        ACTIVE_JOBS[job_id]["progress"] = 100
        ACTIVE_JOBS[job_id]["status"] = "done"
        ACTIVE_JOBS[job_id]["message"] = "Montage terminé avec succès !"
        ACTIVE_JOBS[job_id]["result"] = entry

    except Exception as e:
        print(f"Erreur job {job_id} : {e}")
        ACTIVE_JOBS[job_id]["status"] = "error"
        ACTIVE_JOBS[job_id]["error"] = str(e)
        ACTIVE_JOBS[job_id]["message"] = f"Erreur : {e}"


@app.post("/api/montages/start")
async def start_montage(payload: MontageRequest):
    """Starts montage creation job."""
    if not payload.rush_paths:
        raise HTTPException(status_code=400, detail="Veuillez sélectionner au moins un rush.")

    job_id = uuid.uuid4().hex[:8]
    ACTIVE_JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "progress": 0,
        "message": "Démarrage du processus...",
        "result": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=run_montage_background_job,
        args=(job_id, payload),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "processing"}


@app.get("/api/montages/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Returns live status of montage job."""
    job = ACTIVE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé.")
    return job


@app.get("/api/history")
async def get_history():
    """Returns list of past montages."""
    return {"history": get_all_history()}


@app.delete("/api/history/{entry_id}")
async def delete_history(entry_id: str):
    """Deletes a montage from history."""
    ok = delete_history_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Montage introuvable.")
    return {"success": True}


@app.post("/api/montages/{entry_id}/send-to-queue")
async def send_to_publishing_queue(entry_id: str):
    """
    Copies the rendered montage video directly into uploads/videos/ of the main
    automation platform (port 8000) for instant scheduling and publishing.
    """
    history = get_all_history()
    target_entry = next((item for item in history if item.get("id") == entry_id), None)
    if not target_entry:
        raise HTTPException(status_code=404, detail="Montage introuvable dans l'historique.")

    fname = target_entry.get("filename")
    source_file = OUTPUTS_DIR / fname
    if not source_file.exists():
        raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque.")

    UPLOADS_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    destination_file = UPLOADS_VIDEOS_DIR / fname
    shutil.copy2(source_file, destination_file)

    return {
        "success": True,
        "message": f"Vidéo {fname} transmise avec succès à la file d'attente de publication (Port 8000).",
        "destination": str(destination_file),
    }


def run():
    import uvicorn
    uvicorn.run("montage_auto.app:app", host=HOST, port=PORT, reload=True)


if __name__ == "__main__":
    run()
