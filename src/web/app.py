import os
import json
import time
import uuid
import shutil
import datetime
import subprocess
import threading
from pathlib import Path
from PIL import Image
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.auth import (
    get_authenticated_user,
    verify_credentials,
    create_session_token,
    COOKIE_NAME,
    SESSION_DURATION_DAYS,
)

from src.config import (
    BASE_DIR,
    DATA_DIR,
    UPLOADS_STORIES_DIR,
    UPLOADS_VIDEOS_DIR,
    PROCESSED_STORIES_DIR,
    PROCESSED_VIDEOS_DIR,
    DAYS_FR,
    DAYS_ORDER,
    get_opening_hours,
    save_opening_hours,
    get_social_settings,
    save_social_settings,
    get_publication_frequency,
    save_publication_frequency,
)
from src.scheduler import (
    run_daily_publication,
    load_history,
    start_scheduler,
    scheduler,
    configure_scheduler_jobs,
    PUBLICATION_SLOTS,
    list_pending_videos,
    list_archived_videos,
    archive_video_file,
    restore_video_file,
    delete_archived_file,
    get_today_preview,
    save_today_preview,
    generate_daily_preview,
)
from src.video_processor import process_video_with_hook
from src.story_generator import (
    list_story_templates,
    get_today_hours,
    generate_daily_story,
    create_story_video,
    record_used_story_template,
)
from src.ai_analyzer import analyze_video_with_gemini

app = FastAPI(title="BCHEF Bourges - Automatisation")

_PREVIEW_LOCK = threading.Lock()
_PREVIEW_THREAD = None

def trigger_preview_generation():
    global _PREVIEW_THREAD
    with _PREVIEW_LOCK:
        if _PREVIEW_THREAD is None or not _PREVIEW_THREAD.is_alive():
            _PREVIEW_THREAD = threading.Thread(target=generate_daily_preview, daemon=True)
            _PREVIEW_THREAD.start()

STATIC_DIR = BASE_DIR / "src" / "web" / "static"
TEMPLATES_DIR = BASE_DIR / "src" / "web" / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Mount static, assets and media folders
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")
app.mount("/media/uploads", StaticFiles(directory=str(BASE_DIR / "uploads")), name="uploads")
app.mount("/media/processed", StaticFiles(directory=str(BASE_DIR / "processed")), name="processed")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Endpoints publics sans authentification requise
    if (
        path in ("/login", "/logout", "/favicon.ico")
        or path.startswith("/static")
        or path.startswith("/assets")
        or path == "/api/status"
    ):
        return await call_next(request)

    user = get_authenticated_user(request)
    if not user:
        accept = request.headers.get("accept", "")
        # Redirection vers /login pour les requetes de pages Web
        if "text/html" in accept or path == "/":
            next_url = str(request.url.path)
            if request.url.query:
                next_url += f"?{request.url.query}"
            return RedirectResponse(url=f"/login?next={next_url}", status_code=303)
        # 401 JSON pour les requetes API et medias
        return JSONResponse(
            status_code=401,
            content={"status": "unauthorized", "message": "Authentification requise pour acceder a cette ressource."}
        )

    request.state.user = user
    return await call_next(request)


@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    fav = BASE_DIR / "assets" / "logos" / "favicon.png"
    if fav.exists():
        return FileResponse(fav, media_type="image/png")
    return Response(status_code=404)


@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: str | None = None,
    message: str | None = None,
    next: str = "/",
):
    if get_authenticated_user(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error, "message": message, "next": next},
    )


@app.post("/login")
async def login_action(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    if not verify_credentials(username, password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "invalid", "next": next, "username": username},
            status_code=401,
        )

    redirect_target = next if (next and next.startswith("/") and not next.startswith("//")) else "/"
    token = create_session_token(username.strip())
    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_DURATION_DAYS * 86400,
        httponly=True,
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login?message=logged_out", status_code=303)
    response.delete_cookie(key=COOKIE_NAME)
    return response


@app.on_event("startup")
def on_startup():
    start_scheduler()


def get_video_info(video_path: Path) -> dict:
    """Extract duration, resolution and size using ffprobe."""
    stat = video_path.stat()
    size_mb = round(stat.st_size / (1024 * 1024), 1)
    modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
    duration = 0.0
    resolution = "Inconnue"

    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            str(video_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        dur_str = data.get("format", {}).get("duration") or (
            data.get("streams", [{}])[0].get("duration")
        )
        if dur_str:
            duration = round(float(dur_str), 1)
        streams = data.get("streams", [])
        if streams:
            w = streams[0].get("width")
            h = streams[0].get("height")
            if w and h:
                resolution = f"{w}x{h}"
    except Exception:
        pass

    return {
        "name": video_path.name,
        "size_mb": size_mb,
        "duration_sec": duration,
        "resolution": resolution,
        "modified": modified,
    }


def get_tiktok_session_status(cookies_file_name: str) -> dict:
    c_path = DATA_DIR / cookies_file_name
    if not c_path.exists():
        return {"exists": False, "status": "missing", "badge_class": "badge-rose", "label": "Session absente"}
    try:
        with open(c_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        session_c = next((c for c in cookies if c.get("name") in ("sessionid", "sessionid_ss")), None)
        if not session_c:
            return {"exists": True, "status": "invalid", "badge_class": "badge-amber", "label": "Session invalide"}
        exp = session_c.get("expires")
        if exp and exp > 0 and time.time() > exp:
            exp_date = datetime.datetime.fromtimestamp(exp).strftime("%d/%m")
            return {"exists": True, "status": "expired", "badge_class": "badge-rose", "label": f"Expiree ({exp_date})"}
        return {"exists": True, "status": "active", "badge_class": "badge-emerald", "label": "Session active"}
    except Exception:
        return {"exists": True, "status": "error", "badge_class": "badge-amber", "label": "Erreur cookies"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    day_fr, hours = get_today_hours()
    history = load_history()
    videos = [get_video_info(v) for v in list_pending_videos()]
    archived_videos = [get_video_info(v) for v in list_archived_videos()]
    stories = [s.name for s in list_story_templates()]
    hours_map = get_opening_hours()

    # Ordered days list with their French names and hours
    schedule_days = [
        {"day_en": d, "day_fr": DAYS_FR.get(d, d), "hours": hours_map.get(d, "11h00 - 22h45")}
        for d in DAYS_ORDER
    ]

    # Chargement du contrat de prévisualisation du jour
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    today_preview = get_today_preview()

    # Si l'aperçu du jour n'a pas encore été généré pour aujourd'hui, le déclencher en tâche de fond
    if not today_preview or today_preview.get("date") != today_str:
        trigger_preview_generation()

    latest_story = None
    latest_story_video = None
    latest_video = None
    latest_report = history[0] if history else None
    is_today_published = False

    if today_preview and today_preview.get("date") == today_str:
        latest_story = today_preview.get("story_image")
        latest_story_video = today_preview.get("story_video")
        latest_video = today_preview.get("processed_video")
        latest_report = {"ai_analysis": today_preview}
        is_today_published = today_preview.get("is_published", False)

    if not is_today_published:
        for h in history:
            if h.get("date") == today_str and h.get("status") == "success" and not h.get("is_simulation"):
                is_today_published = True
                if today_preview:
                    today_preview["is_published"] = True
                    save_today_preview(today_preview)
                break
    else:
        # Repli fichiers
        story_files = sorted(PROCESSED_STORIES_DIR.glob("*.png"), key=os.path.getmtime, reverse=True)
        if story_files:
            latest_story = story_files[0].name

        story_video_files = sorted(PROCESSED_STORIES_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True)
        if story_video_files:
            latest_story_video = story_video_files[0].name

        video_files = sorted(PROCESSED_VIDEOS_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True)
        if video_files:
            latest_video = video_files[0].name

        latest_report = history[0] if history else None

    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

    posts_per_day = get_publication_frequency()
    current_slot = today_preview.get("slot", 1) if today_preview else 1
    current_slot_time = today_preview.get("scheduled_time", "11:30") if today_preview else "11:30"
    current_has_story = today_preview.get("has_story", current_slot == 1) if today_preview else True

    # Calcul dynamique du prochain créneau de publication parmi les créneaux actifs
    next_run = "Demain à 11h30"
    try:
        upcoming_runs = []
        for s_idx in range(1, posts_per_day + 1):
            job = scheduler.get_job(f"bchef_pub_slot_{s_idx}")
            if job and job.next_run_time:
                upcoming_runs.append((job.next_run_time, s_idx))
        if upcoming_runs:
            upcoming_runs.sort(key=lambda x: x[0])
            next_dt, s_num = upcoming_runs[0]
            today_date = datetime.datetime.now(next_dt.tzinfo).date() if next_dt.tzinfo else datetime.date.today()
            slot_info = next((s for s in PUBLICATION_SLOTS if s["slot"] == s_num), None)
            time_display = slot_info["publish_time_str"] if slot_info else next_dt.strftime("%Hh%M")
            if next_dt.date() == today_date and not is_today_published:
                next_run = f"Aujourd'hui à {time_display} (créneau {s_num}/{posts_per_day})"
            else:
                next_run = f"Demain à {time_display} (créneau {s_num}/{posts_per_day})"
    except Exception:
        next_run = "Aujourd'hui à 11h30"

    social_cfg = get_social_settings()
    active_profile = social_cfg["active_profile"]
    profiles = social_cfg["profiles"]
    has_tiktok_test = (DATA_DIR / profiles["test"].get("tiktok_cookies_file", "tiktok_cookies.json")).exists()
    has_tiktok_official = (DATA_DIR / profiles["official"].get("tiktok_cookies_file", "tiktok_cookies_official.json")).exists()
    tiktok_test_status = get_tiktok_session_status(profiles["test"].get("tiktok_cookies_file", "tiktok_cookies.json"))
    tiktok_official_status = get_tiktok_session_status(profiles["official"].get("tiktok_cookies_file", "tiktok_cookies_official.json"))

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "day_fr": day_fr,
            "hours": hours,
            "videos": videos,
            "archived_videos": archived_videos,
            "stories": stories,
            "today_story_source": (today_preview or {}).get("source_story_template", ""),
            "history": history,
            "latest_story": latest_story,
            "latest_story_video": latest_story_video,
            "latest_video": latest_video,
            "latest_report": latest_report,
            "schedule_days": schedule_days,
            "has_gemini_key": has_gemini_key,
            "next_run": next_run,
            "posts_per_day": posts_per_day,
            "current_slot": current_slot,
            "current_slot_time": current_slot_time,
            "current_has_story": current_has_story,
            "publication_slots": PUBLICATION_SLOTS,
            "active_profile": active_profile,
            "profiles": profiles,
            "instagram_user": profiles.get(active_profile, {}).get("instagram_username", ""),
            "has_tiktok": has_tiktok_official if active_profile == "official" else has_tiktok_test,
            "has_tiktok_test": has_tiktok_test,
            "has_tiktok_official": has_tiktok_official,
            "tiktok_test_status": tiktok_test_status,
            "tiktok_official_status": tiktok_official_status,
            "auth_user": getattr(request.state, "user", "admin"),
            "is_today_published": is_today_published,
        },
    )


@app.post("/api/upload/video")
async def upload_video(file: UploadFile = File(...)):
    filename = file.filename or "video.mp4"
    target_path = UPLOADS_VIDEOS_DIR / filename
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "filename": filename}


@app.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    target = UPLOADS_VIDEOS_DIR / filename
    if target.exists() and target.is_file():
        target.unlink()
        return {"status": "success", "message": f"{filename} supprimé."}
    raise HTTPException(status_code=404, detail="Vidéo introuvable")


@app.post("/api/videos/archive/{filename}")
async def archive_video_endpoint(filename: str):
    try:
        target = archive_video_file(filename)
        return {"status": "success", "message": f"{filename} déplacé dans les archives ({target.name})."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/videos/restore/{filename}")
async def restore_video_endpoint(filename: str):
    try:
        target = restore_video_file(filename)
        return {"status": "success", "message": f"{filename} restauré dans la file d'attente ({target.name})."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/archive/{filename}")
async def delete_archive_endpoint(filename: str):
    success = delete_archived_file(filename)
    if success:
        return {"status": "success", "message": f"{filename} supprimé des archives."}
    raise HTTPException(status_code=404, detail="Vidéo archivée introuvable")


@app.post("/api/upload/story")
async def upload_story(file: UploadFile = File(...)):
    raw_name = file.filename or "story.png"
    raw_path = Path(raw_name)
    stem = raw_path.stem.strip().replace(" ", "_")
    ext = raw_path.suffix.lower()

    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".heic"):
        ext = ".png"

    # Nom unique pour eviter les collisions sur les noms generiques smartphones (image.jpg, photo.png...)
    generic_stems = {"image", "photo", "fullsizerender", "story", "img", "capture"}
    target_name = f"{stem}{ext}"
    target_path = UPLOADS_STORIES_DIR / target_name
    if target_path.exists() or stem.lower() in generic_stems:
        uid = uuid.uuid4().hex[:6]
        target_name = f"{stem}_{uid}{ext}"
        target_path = UPLOADS_STORIES_DIR / target_name

    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Conversion automatique si WebP ou HEIC
    if ext in (".webp", ".heic"):
        converted_name = f"{stem}_{uuid.uuid4().hex[:6]}.png"
        converted_path = UPLOADS_STORIES_DIR / converted_name
        converted_ok = False
        try:
            with Image.open(target_path) as img:
                img.convert("RGB").save(converted_path, "PNG")
                converted_ok = True
        except Exception:
            res = subprocess.run(["convert", str(target_path), str(converted_path)], capture_output=True)
            if res.returncode == 0 and converted_path.exists():
                converted_ok = True

        if converted_ok:
            target_path.unlink(missing_ok=True)
            target_name = converted_name

    return {"status": "success", "filename": target_name}


@app.delete("/api/stories/{filename}")
async def delete_story(filename: str):
    target = UPLOADS_STORIES_DIR / filename
    if target.exists() and target.is_file():
        target.unlink()
        return {"status": "success", "message": f"{filename} supprimé."}
    raise HTTPException(status_code=404, detail="Image introuvable")


@app.post("/api/story/preview-custom")
async def preview_custom_story(story_name: str = Form(...)):
    source = UPLOADS_STORIES_DIR / story_name
    if not source.exists():
        raise HTTPException(status_code=404, detail="Image introuvable")
    out_name = f"preview_{story_name}"
    res = generate_daily_story(source_image=source, output_filename=out_name)
    return {"status": "success", "preview_url": f"/media/processed/stories/{out_name}"}


@app.post("/api/story/select-for-today")
async def select_story_for_today(source_image: str = Form(...)):
    source = UPLOADS_STORIES_DIR / source_image
    if not source.exists():
        raise HTTPException(status_code=404, detail="Template introuvable")

    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    story_img_name = f"story_{date_str}.png"
    story_vid_name = f"story_{date_str}.mp4"

    # Regénération immédiate de l'image story du jour
    res = generate_daily_story(
        source_image=source,
        target_date=today,
        output_filename=story_img_name,
    )

    # Regénération immédiate de la vidéo story MP4 15s avec l'audio du jour
    create_story_video(
        image_path=Path(res["output_path"]),
        target_date=today,
        duration=15,
        output_filename=story_vid_name,
    )

    # Mise à jour de l'aperçu du jour dans today_preview.json
    today_preview = get_today_preview() or {}
    today_preview["date"] = date_str
    today_preview["story_image"] = story_img_name
    today_preview["story_video"] = story_vid_name
    today_preview["source_story_template"] = source_image
    save_today_preview(today_preview)

    # Enregistrement dans l'historique anti-répétition
    record_used_story_template(source_image, date_str)

    return {
        "status": "success",
        "message": f"Story du jour mise à jour avec succès avec {source_image} !",
        "story_image": f"/media/processed/stories/{story_img_name}",
        "story_video": f"/media/processed/stories/{story_vid_name}",
    }


publication_status = {
    "is_running": False,
    "status": "idle",
    "step": "",
    "percent": 0,
    "error": None,
    "report": None,
}


@app.post("/api/trigger/publish")
async def trigger_publish(
    simulation: bool = Form(False),
    video_name: str = Form(None),
    hook: str = Form(None),
    description: str = Form(None),
    hashtags: str = Form(None),
    force: bool = Form(False),
):
    global publication_status
    if publication_status["is_running"]:
        return JSONResponse(
            status_code=409,
            content={
                "status": "already_running",
                "message": "Une publication est deja en cours d'execution.",
                "progress": publication_status,
            }
        )

    publication_status = {
        "is_running": True,
        "status": "running",
        "step": "Demarrage du pipeline...",
        "percent": 5,
        "error": None,
        "report": None,
    }

    parsed_tags = None
    if hashtags:
        try:
            parsed = json.loads(hashtags)
            if isinstance(parsed, list):
                parsed_tags = [str(t).strip() for t in parsed if str(t).strip()]
        except Exception:
            parsed_tags = [t.strip() for t in hashtags.split() if t.strip()]

    def background_worker(
        is_sim: bool,
        v_name: str | None,
        c_hook: str | None,
        c_desc: str | None,
        c_tags: list[str] | None,
        is_force: bool,
    ):
        global publication_status

        def progress_cb(step_name: str, pct: int):
            global publication_status
            if pct < 0:
                publication_status["status"] = "error"
                publication_status["is_running"] = False
                publication_status["error"] = step_name
            elif pct >= 100:
                publication_status["status"] = "success"
                publication_status["is_running"] = False
                publication_status["percent"] = 100
                publication_status["step"] = step_name
            else:
                publication_status["step"] = step_name
                publication_status["percent"] = pct

        try:
            res = run_daily_publication(
                is_simulation=is_sim,
                custom_video_name=v_name if v_name else None,
                custom_hook=c_hook.upper().strip() if c_hook and c_hook.strip() else None,
                custom_description=c_desc.strip() if c_desc and c_desc.strip() else None,
                custom_hashtags=c_tags,
                force_publish=is_force,
                progress_callback=progress_cb,
            )
            publication_status["report"] = res
            if res.get("status") == "success":
                publication_status["status"] = "success"
                publication_status["percent"] = 100
                publication_status["step"] = "Publication terminee avec succes !"

                # Si d'autres creneaux sont prevus aujourd'hui, preparer le suivant
                done_slot = res.get("slot", 1)
                total_freq = get_publication_frequency()
                if not is_sim and done_slot < total_freq:
                    next_s = done_slot + 1
                    next_info = next((s for s in PUBLICATION_SLOTS if s["slot"] == next_s), None)
                    if next_info:
                        print(f"Preparation automatique du creneau suivant {next_s}/{total_freq} (prevu a {next_info['publish_time_str']})...", flush=True)
                        threading.Thread(
                            target=generate_daily_preview,
                            kwargs={
                                "slot_index": next_s,
                                "publish_time_str": next_info["publish_time_str"],
                                "generate_story": False,
                                "force": True,
                            },
                            daemon=True,
                        ).start()
            elif res.get("status") == "already_published":
                publication_status["status"] = "already_published"
                publication_status["percent"] = 100
                publication_status["step"] = res.get("message", "Publication deja effectuee aujourd'hui.")
            else:
                publication_status["status"] = "error"
                publication_status["error"] = res.get("error", "Erreur inconnue")
        except Exception as e:
            publication_status["status"] = "error"
            publication_status["error"] = str(e)
        finally:
            publication_status["is_running"] = False

    thread = threading.Thread(
        target=background_worker,
        args=(simulation, video_name, hook, description, parsed_tags, force),
        daemon=True,
    )
    thread.start()

    return {"status": "started", "message": "Pipeline de publication lance en arriere-plan."}



@app.get("/api/trigger/status")
async def get_trigger_status():
    global publication_status
    return publication_status


@app.post("/api/trigger/tiktok-retry")
async def trigger_tiktok_retry(simulation: bool = Form(False)):
    from src.publisher.tiktok import publish_single_tiktok
    from src.config import PROCESSED_VIDEOS_DIR, get_social_settings
    from src.scheduler import get_today_preview, save_today_preview

    today_preview = get_today_preview()
    if not today_preview or not today_preview.get("processed_video"):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "Aucune video traitee du jour disponible dans today_preview.json."}
        )

    vid_path = PROCESSED_VIDEOS_DIR / today_preview["processed_video"]
    if not vid_path.exists():
        return JSONResponse(
            status_code=404,
            content={"status": "error", "error": f"Fichier video introuvable : {vid_path}"}
        )

    caption_line = today_preview.get("description", "Rejoignez-nous chez BCHEF Bourges !")
    hashtags = today_preview.get("hashtags", ["#bchef", "#bourges", "#burger"])
    full_caption = f"{caption_line}\n\n{' '.join(hashtags)}"

    social_cfg = get_social_settings()
    target_prof = social_cfg.get("active_profile", "official")

    res = publish_single_tiktok(
        video_path=vid_path,
        caption=full_caption,
        target_profile=target_prof,
        simulation=simulation,
        location_query="BCHEF Bourges",
    )

    if res.get("status") == "published":
        pubs = today_preview.get("publications", [])
        pubs = [p for p in pubs if p.get("platform") != "tiktok"]
        pubs.append(res)
        today_preview["publications"] = pubs
        save_today_preview(today_preview)

    return res



@app.post("/api/ai/regenerate")
async def regenerate_ai(video_name: str = Form(None)):
    try:
        updated_preview = generate_daily_preview(force=True)
        return {
            "status": "success",
            "analysis": updated_preview,
            "preview_video": updated_preview.get("processed_video"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur regeneration apercu IA : {e}")


@app.post("/api/settings/hours")
async def update_hours(request: Request):
    data = await request.json()
    save_opening_hours(data)
    return {"status": "success", "message": "Horaires d'ouverture mis à jour."}


@app.post("/api/settings/credentials")
async def update_credentials(
    gemini_api_key: str = Form(None),
    instagram_username: str = Form(None),
    instagram_password: str = Form(None),
    dashboard_password: str = Form(None),
):
    env_path = BASE_DIR / ".env"
    env_content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    updates = {}
    if gemini_api_key is not None and gemini_api_key.strip():
        updates["GEMINI_API_KEY"] = gemini_api_key.strip()
        os.environ["GEMINI_API_KEY"] = gemini_api_key.strip()
    if instagram_username is not None:
        updates["INSTAGRAM_USERNAME"] = instagram_username.strip()
        os.environ["INSTAGRAM_USERNAME"] = instagram_username.strip()
    if instagram_password is not None and instagram_password.strip():
        updates["INSTAGRAM_PASSWORD"] = instagram_password.strip()
        os.environ["INSTAGRAM_PASSWORD"] = instagram_password.strip()
    if dashboard_password is not None and dashboard_password.strip():
        updates["DASHBOARD_PASSWORD"] = dashboard_password.strip()
        os.environ["DASHBOARD_PASSWORD"] = dashboard_password.strip()

    lines = env_content.splitlines()
    for key, val in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                found = True
                break
        if not found:
            lines.append(f"{key}={val}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "success", "message": "Identifiants enregistrés avec succès."}


@app.post("/api/settings/profile")
async def update_social_profile(
    active_profile: str = Form(...),
    test_insta_user: str = Form(None),
    test_insta_pass: str = Form(None),
    official_insta_user: str = Form(None),
    official_insta_pass: str = Form(None),
):
    profiles_dict = {
        "test": {},
        "official": {},
    }
    if test_insta_user is not None and test_insta_user.strip():
        profiles_dict["test"]["instagram_username"] = test_insta_user.strip()
    if test_insta_pass is not None and test_insta_pass.strip():
        profiles_dict["test"]["instagram_password"] = test_insta_pass.strip()
    if official_insta_user is not None and official_insta_user.strip():
        profiles_dict["official"]["instagram_username"] = official_insta_user.strip()
    if official_insta_pass is not None and official_insta_pass.strip():
        profiles_dict["official"]["instagram_password"] = official_insta_pass.strip()

    save_social_settings(active_profile=active_profile, profiles_dict=profiles_dict)
    label = "Mode Officiel (BCHEF Bourges)" if active_profile == "official" else "Mode Test (Compte bac a sable)"
    return {"status": "success", "message": f"Profil actif basculé sur : {label}", "active_profile": active_profile}


@app.post("/api/settings/frequency")
async def update_publication_frequency(posts_per_day: int = Form(...)):
    if posts_per_day not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="La frequence doit etre comprise entre 1 et 4 publications par jour.")
    save_publication_frequency(posts_per_day)
    try:
        configure_scheduler_jobs()
    except Exception as e:
        print(f"Erreur re-configuration scheduler: {e}", flush=True)
    return {
        "status": "success",
        "posts_per_day": posts_per_day,
        "message": f"Frequence mise a jour avec succes : {posts_per_day} publication(s) par jour.",
    }


@app.get("/api/status")
async def get_status():
    day_fr, hours = get_today_hours()
    return {
        "status": "online",
        "scheduler_running": scheduler.running,
        "day": day_fr,
        "hours": hours,
        "pending_videos": len(list_pending_videos()),
        "archived_videos": len(list_archived_videos()),
        "story_templates": len(list_story_templates()),
    }
