import re
import json
import shutil
import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import (
    UPLOADS_VIDEOS_DIR,
    ARCHIVE_VIDEOS_DIR,
    HISTORY_FILE,
)
from src.story_generator import generate_daily_story
from src.ai_analyzer import analyze_video_with_gemini
from src.video_processor import process_video_with_hook
from src.publisher.instagram import InstagramPublisher
from src.publisher.tiktok import TikTokPublisher


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history_entry(entry: dict):
    history = load_history()
    history.insert(0, entry)  # Prepend latest
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def list_pending_videos() -> list[Path]:
    """Lists videos waiting in uploads/videos/."""
    valid_exts = {".mov", ".mp4", ".MOV", ".MP4"}
    return sorted([
        p for p in UPLOADS_VIDEOS_DIR.iterdir()
        if p.is_file() and p.suffix in valid_exts and not p.name.startswith(".")
    ], key=lambda x: x.stat().st_mtime)


def list_archived_videos() -> list[Path]:
    """Lists previously published videos in processed/archive/."""
    valid_exts = {".mov", ".mp4", ".MOV", ".MP4"}
    if not ARCHIVE_VIDEOS_DIR.exists():
        return []
    return sorted([
        p for p in ARCHIVE_VIDEOS_DIR.iterdir()
        if p.is_file() and p.suffix in valid_exts and not p.name.startswith(".")
    ], key=lambda x: x.stat().st_mtime)


def archive_video_file(filename: str) -> Path:
    """Manually moves a video from uploads/videos/ to processed/archive/ with date prefix."""
    src = UPLOADS_VIDEOS_DIR / filename
    if not src.exists():
        raise FileNotFoundError(f"Vidéo introuvable dans la file d'attente : {filename}")
    now_prefix = datetime.datetime.now().strftime("%Y-%m-%d")
    ARCHIVE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    target_name = f"{now_prefix}_{src.name}"
    target = ARCHIVE_VIDEOS_DIR / target_name
    if target.exists():
        target_name = f"{datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{src.name}"
        target = ARCHIVE_VIDEOS_DIR / target_name
    shutil.move(str(src), str(target))
    return target


def restore_video_file(archived_filename: str) -> Path:
    """Restores an archived video from processed/archive/ back to uploads/videos/."""
    src = ARCHIVE_VIDEOS_DIR / archived_filename
    if not src.exists():
        raise FileNotFoundError(f"Vidéo archivée introuvable : {archived_filename}")
    original_name = re.sub(r"^\d{4}-\d{2}-\d{2}(?:_\d+)?_", "", archived_filename)
    if not original_name:
        original_name = archived_filename
    target = UPLOADS_VIDEOS_DIR / original_name
    if target.exists():
        target = UPLOADS_VIDEOS_DIR / f"restored_{original_name}"
    shutil.move(str(src), str(target))
    return target


def delete_archived_file(archived_filename: str) -> bool:
    """Permanently deletes a video from the archive."""
    target = ARCHIVE_VIDEOS_DIR / archived_filename
    if target.exists() and target.is_file():
        target.unlink()
        return True
    return False


def run_daily_publication(
    is_simulation: bool = True,
    custom_video_name: str | None = None,
    progress_callback=None,
) -> dict:
    """
    Executes the full automated workflow:
    1. Generates the daily story with opening hours
    2. Picks a video from queue (or recycled archive) and analyzes it with Gemini
    3. Burns the hook onto the video
    4. Posts to Instagram & TikTok (or simulates)
    5. Archives the used video (rotation)
    6. Saves history
    """
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    date_str = now.strftime("%Y-%m-%d")

    report = {
        "id": f"pub_{timestamp_str}",
        "timestamp": now.isoformat(),
        "date": date_str,
        "is_simulation": is_simulation,
        "story": None,
        "video": None,
        "ai_analysis": None,
        "publications": [],
        "status": "in_progress",
    }

    try:
        # Step 1: Generate Story
        if progress_callback:
            progress_callback("Génération de la story Instagram...", 15)
        print(f"[{timestamp_str}] Étape 1 : Génération de la story quotidienne...")
        story_res = generate_daily_story(
            output_filename=f"story_{date_str}.png"
        )
        report["story"] = story_res

        # Step 2: Pick Video with Rotation & Archive fallback
        if progress_callback:
            progress_callback("Sélection de la vidéo...", 30)
        print(f"[{timestamp_str}] Étape 2 : Sélection de la vidéo...")
        pending_videos = list_pending_videos()
        selected_video = None
        is_recycled = False

        if custom_video_name:
            for v in pending_videos:
                if v.name == custom_video_name:
                    selected_video = v
                    break

        if not selected_video:
            if pending_videos:
                # FIFO: take the oldest uploaded video
                selected_video = pending_videos[0]
            else:
                # Fallback: Recycle the oldest archived video so publication never fails silently
                archived = list_archived_videos()
                if archived:
                    selected_video = archived[0]
                    is_recycled = True
                    print(f"File d'attente vide : recyclage de la vidéo archivée {selected_video.name}")
                else:
                    raise FileNotFoundError(
                        f"Aucune vidéo trouvée dans {UPLOADS_VIDEOS_DIR} ni dans {ARCHIVE_VIDEOS_DIR}. "
                        "Veuillez déposer au moins une vidéo."
                    )

        report["raw_video"] = str(selected_video.name)
        report["recycled_from_archive"] = is_recycled

        # Step 3: AI Analysis (Hook, Description, Hashtags)
        if progress_callback:
            progress_callback("Analyse IA multimodale (Gemini)...", 50)
        print(f"[{timestamp_str}] Étape 3 : Analyse IA de la vidéo...")
        ai_data = analyze_video_with_gemini(selected_video)
        report["ai_analysis"] = ai_data

        hook_text = ai_data.get("hook", "Le rendez-vous des gourmands chez BCHEF Bourges !")
        caption_line = ai_data.get("description", "Rejoignez-nous chez BCHEF Bourges au 13 place Gordaine !")
        hashtags_list = ai_data.get("hashtags", ["#bchef", "#bourges", "#burger", "#restobourges", "#foodie"])
        full_caption = f"{caption_line}\n\n{' '.join(hashtags_list)}"

        # Step 4: Video Processing (Burn hook)
        if progress_callback:
            progress_callback("Incrustation du Hook vidéo (FFmpeg)...", 75)
        print(f"[{timestamp_str}] Étape 4 : Incrustation du Hook sur la vidéo...")
        video_res = process_video_with_hook(
            input_video=selected_video,
            hook_text=hook_text,
            output_filename=f"video_{date_str}_{selected_video.stem}.mp4",
        )
        report["video"] = video_res

        # Step 5: Publications
        if progress_callback:
            progress_callback("Publication Instagram & TikTok...", 90)
        print(f"[{timestamp_str}] Étape 5 : Publications...")
        insta = InstagramPublisher()
        tiktok = TikTokPublisher()

        # Story Instagram
        insta_story_res = insta.publish_story(
            image_path=Path(story_res["output_path"]),
            simulation=is_simulation,
        )
        report["publications"].append(insta_story_res)

        # Reel Instagram (avec lieu BCHEF Bourges et partage direct en Story)
        insta_reel_res = insta.publish_reel(
            video_path=Path(video_res["output_video"]),
            caption=full_caption,
            cover_path=Path(video_res["cover_image"]),
            simulation=is_simulation,
            share_to_story=True,
        )
        report["publications"].append(insta_reel_res)

        # Video TikTok (avec lieu BCHEF Bourges)
        tiktok_res = tiktok.publish_video(
            video_path=Path(video_res["output_video"]),
            caption=full_caption,
            simulation=is_simulation,
            location_query="BCHEF Bourges",
        )
        # Step 6: Rotation & Archivage de la video
        if not is_simulation:
            if progress_callback:
                progress_callback("Rotation et archivage de la vidéo...", 98)
            print(f"[{timestamp_str}] Étape 6 : Rotation et archivage de la vidéo...")
            if not is_recycled:
                ARCHIVE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
                dest_name = f"{date_str}_{selected_video.name}"
                dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                if dest_path.exists():
                    dest_name = f"{timestamp_str}_{selected_video.name}"
                    dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                shutil.move(str(selected_video), str(dest_path))
                report["archived_video"] = dest_name
                print(f"[{timestamp_str}] Vidéo archivée avec succès : {dest_name}")
            else:
                selected_video.touch()
                report["archived_video"] = selected_video.name
                print(f"[{timestamp_str}] Vidéo recyclée décalée en fin de cycle de rotation : {selected_video.name}")

        report["status"] = "success"
        if progress_callback:
            progress_callback("Publication terminée avec succès !", 100)
        print(f"[{timestamp_str}] Publication terminée avec succès !")

    except Exception as e:
        report["status"] = "error"
        report["error"] = str(e)
        if progress_callback:
            progress_callback(f"Erreur : {e}", -1)
        print(f"[{timestamp_str}] Erreur durant la publication : {e}")

    save_history_entry(report)
    return report


scheduler = BackgroundScheduler()


def start_scheduler():
    """Starts the daily 11:30 AM publication schedule."""
    if not scheduler.running:
        # Schedule every day at 11:30:00
        scheduler.add_job(
            func=run_daily_publication,
            trigger=CronTrigger(hour=11, minute=30),
            id="daily_bchef_publication",
            name="Publication quotidienne BCHEF Bourges",
            replace_existing=True,
            kwargs={"is_simulation": False},
        )
        scheduler.start()
        print("Planificateur activé : publication programmée chaque jour à 11h30.")


if __name__ == "__main__":
    print("Test du pipeline complet...")
    res = run_daily_publication(is_simulation=True)
    print("\n--- RAPPORT DU PIPELINE ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
