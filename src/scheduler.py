import os
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
    TODAY_PREVIEW_FILE,
    PROCESSED_VIDEOS_DIR,
    PROCESSED_STORIES_DIR,
    BASE_DIR,
)
from src.story_generator import generate_daily_story, create_story_video
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


def get_today_preview() -> dict | None:
    """Reads the locked daily preview contract from data/today_preview.json."""
    if TODAY_PREVIEW_FILE.exists():
        try:
            with open(TODAY_PREVIEW_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Erreur lecture today_preview.json : {e}")
    return None


def save_today_preview(data: dict):
    """Saves the locked daily preview contract into data/today_preview.json."""
    try:
        TODAY_PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TODAY_PREVIEW_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erreur ecriture today_preview.json : {e}")


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
    custom_hook: str | None = None,
    custom_description: str | None = None,
    custom_hashtags: list[str] | None = None,
    force_publish: bool = False,
    progress_callback=None,
) -> dict:
    """
    Executes the full automated publication workflow:
    1. Verifie le verrou anti-doublon (empeche de republier si deja effectue aujourd'hui).
    2. Recupere l'apercu verrouille a 00h01 (ou genere si absent).
    3. Utilise la video selectionnee et deja pre-encodee la nuit (gain de temps et 0 bug).
    4. Publie la Story 15s avec musique et le Reel (sans fond noir).
    5. Archive la video brute et met a jour today_preview.json.
    """
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    date_str = now.strftime("%Y-%m-%d")

    # Anti-doublon check:
    today_preview = get_today_preview()
    is_already_published = False
    if today_preview and today_preview.get("date") == date_str and today_preview.get("is_published"):
        is_already_published = True

    if not is_simulation:
        history = load_history()
        for h in history:
            if h.get("date") == date_str and h.get("status") == "success" and not h.get("is_simulation"):
                is_already_published = True
                break

    if is_already_published and not force_publish:
        msg = f"La publication du {date_str} a deja ete effectuee aujourd'hui. Aucune republication pour eviter les doublons."
        print(f"[{timestamp_str}] {msg}")
        if progress_callback:
            progress_callback(msg, 100)
        return {
            "id": f"pub_{timestamp_str}",
            "status": "already_published",
            "message": msg,
            "date": date_str,
        }

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
        # Step 1: Ensure today's preview & story exist
        story_vid_path = PROCESSED_STORIES_DIR / f"story_{date_str}.mp4"
        story_img_path = PROCESSED_STORIES_DIR / f"story_{date_str}.png"
        if not today_preview or today_preview.get("date") != date_str or not story_vid_path.exists():
            if progress_callback:
                progress_callback("Preparation et verrouillage de l'apercu du jour...", 15)
            today_preview = generate_daily_preview(target_date=now.date())

        story_res = {
            "status": "success",
            "output_path": str(story_img_path),
            "video_path": str(story_vid_path) if story_vid_path.exists() else str(story_img_path),
            "date": date_str,
        }
        report["story"] = story_res

        # Step 2: Select the locked Video
        if progress_callback:
            progress_callback("Selection de la video verrouillee...", 30)
        print(f"[{timestamp_str}] Etape 2 : Selection de la video verrouillee...")
        pending_videos = list_pending_videos()
        selected_video = None
        is_recycled = False

        if custom_video_name:
            for v in pending_videos:
                if v.name == custom_video_name:
                    selected_video = v
                    break

        if not selected_video and today_preview and today_preview.get("video_name"):
            target_name = today_preview["video_name"]
            for v in pending_videos:
                if v.name == target_name:
                    selected_video = v
                    break
            if not selected_video:
                for v in list_archived_videos():
                    if v.name == target_name:
                        selected_video = v
                        is_recycled = True
                        break

        if not selected_video:
            if pending_videos:
                selected_video = pending_videos[0]
            else:
                archived = list_archived_videos()
                if archived:
                    selected_video = archived[0]
                    is_recycled = True
                else:
                    raise FileNotFoundError("Aucune video trouvee dans uploads/videos ni dans archive.")

        report["raw_video"] = str(selected_video.name)
        report["recycled_from_archive"] = is_recycled

        # Step 3: Texts (Hook, Description, Hashtags)
        ai_data = None
        need_reencode = False
        if custom_hook and custom_description:
            if progress_callback:
                progress_callback("Utilisation des textes personnalises...", 50)
            hook_text = custom_hook.upper().strip()
            caption_line = custom_description
            hashtags_list = custom_hashtags if custom_hashtags else ["#bchef", "#bourges", "#burger", "#restobourges", "#foodie"]
            ai_data = {
                "hook": hook_text,
                "description": caption_line,
                "hashtags": hashtags_list,
                "source": "custom_override",
            }
            need_reencode = True
        else:
            if progress_callback:
                progress_callback("Reutilisation des textes verrouilles a minuit...", 50)
            hook_text = today_preview.get("hook", "Le rendez-vous des gourmands chez BCHEF Bourges !").upper().strip()
            caption_line = today_preview.get("description", "Rejoignez-nous chez BCHEF Bourges au 13 place Gordaine !")
            hashtags_list = today_preview.get("hashtags", ["#bchef", "#bourges", "#burger", "#restobourges", "#foodie"])
            ai_data = {
                "hook": hook_text,
                "description": caption_line,
                "hashtags": hashtags_list,
                "transcription": today_preview.get("transcription", ""),
                "contexte": today_preview.get("contexte", ""),
                "source": "today_preview_locked",
            }

        report["ai_analysis"] = ai_data
        full_caption = f"{caption_line}\n\n{' '.join(hashtags_list)}"

        # Step 4: Video Processing (Reuse Pre-encoded or Re-encode)
        expected_video_file = f"video_{date_str}_{selected_video.stem}.mp4"
        expected_video_path = PROCESSED_VIDEOS_DIR / expected_video_file
        expected_cover_path = PROCESSED_VIDEOS_DIR / f"{expected_video_path.stem}_cover.jpg"

        if not need_reencode and expected_video_path.exists() and expected_cover_path.exists():
            if progress_callback:
                progress_callback("Reutilisation de la video deja encodee a minuit...", 75)
            print(f"[{timestamp_str}] Etape 4 : Video deja encodee a minuit disponible ({expected_video_file}), saut de l'encodage...")
            video_res = {
                "status": "success",
                "input_video": str(selected_video.name),
                "output_video": str(expected_video_path),
                "cover_image": str(expected_cover_path),
                "hook_text": hook_text,
            }
        else:
            if progress_callback:
                progress_callback("Incrustation du Hook video (FFmpeg)...", 75)
            print(f"[{timestamp_str}] Etape 4 : Incrustation du Hook sur la video...")
            video_res = process_video_with_hook(
                input_video=selected_video,
                hook_text=hook_text,
                output_filename=expected_video_file,
            )
        report["video"] = video_res

        # Step 5: Publications
        insta = InstagramPublisher()
        tiktok = TikTokPublisher()
        report["target_profile"] = insta.target_profile
        if progress_callback:
            progress_callback(f"Publication sur profil {insta.target_profile}...", 90)
        print(f"[{timestamp_str}] Etape 5 : Publications sur profil '{insta.target_profile}' ({insta.username})...")

        # Story Instagram (vidéo 15s avec l'audio du jour)
        story_to_publish = (
            story_vid_path
            if story_vid_path.exists()
            else story_img_path
        )
        insta_story_res = insta.publish_story(
            media_path=story_to_publish,
            simulation=is_simulation,
        )
        report["publications"].append(insta_story_res)

        # Reel Instagram (avec lieu BCHEF Bourges - SANS repartage en story pour eviter le fond noir)
        insta_reel_res = insta.publish_reel(
            video_path=Path(video_res["output_video"]),
            caption=full_caption,
            cover_path=Path(video_res["cover_image"]),
            simulation=is_simulation,
            share_to_story=False,
        )
        report["publications"].append(insta_reel_res)

        # Video TikTok (avec lieu BCHEF Bourges)
        tiktok_res = tiktok.publish_video(
            video_path=Path(video_res["output_video"]),
            caption=full_caption,
            simulation=is_simulation,
            location_query="BCHEF Bourges",
        )
        report["publications"].append(tiktok_res)

        # Step 6: Rotation & Archivage de la video
        any_published_ok = any(p.get("status") == "published" for p in report["publications"])
        if not is_simulation and any_published_ok:
            if progress_callback:
                progress_callback("Rotation et archivage de la video...", 98)
            print(f"[{timestamp_str}] Etape 6 : Rotation et archivage de la video...")
            if not is_recycled:
                ARCHIVE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
                dest_name = f"{date_str}_{selected_video.name}"
                dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                if dest_path.exists():
                    dest_name = f"{timestamp_str}_{selected_video.name}"
                    dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                shutil.move(str(selected_video), str(dest_path))
                report["archived_video"] = dest_name
                print(f"[{timestamp_str}] Video archivee avec succes : {dest_name}")
            else:
                selected_video.touch()
                report["archived_video"] = selected_video.name
                print(f"[{timestamp_str}] Video recyclee decalee en fin de cycle : {selected_video.name}")

            # Marquer l'apercu du jour comme publie
            if today_preview:
                today_preview["is_published"] = True
                today_preview["published_at"] = now.isoformat()
                today_preview["publications"] = report["publications"]
                today_preview["report"] = report
                save_today_preview(today_preview)
        elif not is_simulation and not any_published_ok:
            print(f"[{timestamp_str}] Avertissement : Aucune publication n'a reussi en production. La video n'est pas archivee.")

        report["status"] = "success" if (is_simulation or any_published_ok) else "error"
        if progress_callback:
            progress_callback("Publication terminee avec succes !" if report["status"] == "success" else "Echec de la publication.", 100 if report["status"] == "success" else -1)
        print(f"[{timestamp_str}] Publication terminee (status={report['status']})")

    except Exception as e:
        report["status"] = "error"
        report["error"] = str(e)
        if progress_callback:
            progress_callback(f"Erreur : {e}", -1)
        print(f"[{timestamp_str}] Erreur durant la publication : {e}")

    save_history_entry(report)
    return report


def generate_daily_preview(target_date: datetime.date | None = None, force: bool = False) -> dict:
    """
    S'execute automatiquement chaque nuit a 00:01 pour preparer et verrouiller l'apercu du jour :
    1. Pre-genere l'image de la story + video 15s avec l'audio du jour.
    2. Selectionne la video du jour dans la file d'attente (ou recycle une archive).
    3. Lance l'analyse multimodale Gemini (transcription, contexte, hook, description, hashtags).
    4. PRE-INCRUSTE LE HOOK SUR LA VIDEO DES 00h01 (FFmpeg).
    5. Sauvegarde le contrat journalier dans data/today_preview.json.
    Assure qu'au reveil du gerant, la video est DEJA montee et prete a diffuser.
    """
    now = datetime.datetime.now()
    target = target_date or now.date()
    date_str = target.strftime("%Y-%m-%d")
    print(f"[{date_str} 00:01] Pre-generation automatique de l'apercu du jour...")

    cached_preview = get_today_preview()
    if cached_preview and cached_preview.get("date") == date_str and not force:
        proc_v = PROCESSED_VIDEOS_DIR / cached_preview.get("processed_video", "")
        if proc_v.exists():
            print(f"[{date_str}] Apercu du jour deja existant et valide dans today_preview.json.")
            return cached_preview

    # 1. Pre-generate today's story image + 15s MP4 video with daily audio
    story_img_name = f"story_{date_str}.png"
    story_vid_name = f"story_{date_str}.mp4"
    try:
        story_res = generate_daily_story(target_date=target, output_filename=story_img_name)
        create_story_video(
            image_path=Path(story_res["output_path"]),
            target_date=target,
            duration=15,
            output_filename=story_vid_name,
        )
        print(f"[{date_str}] Story video 15s pre-generee pour la journee.")
    except Exception as e_story:
        print(f"Erreur pre-generation story : {e_story}")

    # 2. Select the video of the day
    pending = list_pending_videos()
    video_to_process = None
    is_recycled = False
    if pending:
        video_to_process = pending[0]
    else:
        archived = list_archived_videos()
        if archived:
            video_to_process = archived[0]
            is_recycled = True
            print(f"File d'attente vide : recyclage de la video archivee {video_to_process.name}")
        else:
            print("Aucune video disponible pour la pre-generation.")
            return {}

    # 3. Gemini AI Analysis
    ai_data = None
    cache_file = BASE_DIR / "data" / "last_ai_analysis.json"
    if not force and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if cdata.get("video_name") == video_to_process.name and "analysis" in cdata:
                    ai_data = cdata["analysis"]
        except Exception:
            pass

    if not ai_data:
        print(f"[{date_str}] Analyse IA Gemini de la video {video_to_process.name}...")
        ai_data = analyze_video_with_gemini(video_to_process)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"video_name": video_to_process.name, "analysis": ai_data}, f, ensure_ascii=False, indent=2)
        except Exception as e_cache:
            print(f"Erreur sauvegarde cache IA : {e_cache}")

    hook_text = ai_data.get("hook", "Le rendez-vous des gourmands chez BCHEF Bourges !").upper().strip()
    caption_line = ai_data.get("description", "Rejoignez-nous chez BCHEF Bourges au 13 place Gordaine !")
    hashtags_list = ai_data.get("hashtags", ["#bchef", "#bourges", "#burger", "#restobourges", "#foodie"])

    # 4. Burn the hook overlay onto the video NOW at 00h01
    output_video_name = f"video_{date_str}_{video_to_process.stem}.mp4"
    print(f"[{date_str}] Pre-incrustation de l'accroche sur {video_to_process.name} -> {output_video_name}...")
    video_res = process_video_with_hook(
        input_video=video_to_process,
        hook_text=hook_text,
        output_filename=output_video_name,
    )
    cover_image_name = Path(video_res["cover_image"]).name

    # Verifier si aujourd'hui a deja ete publie dans l'historique
    history = load_history()
    is_already_published = False
    for h in history:
        if h.get("date") == date_str and h.get("status") == "success" and not h.get("is_simulation"):
            is_already_published = True
            break

    # 5. Save into data/today_preview.json
    preview_data = {
        "date": date_str,
        "video_name": video_to_process.name,
        "is_recycled": is_recycled,
        "hook": hook_text,
        "description": caption_line,
        "hashtags": hashtags_list,
        "transcription": ai_data.get("transcription", ""),
        "contexte": ai_data.get("contexte", ""),
        "story_image": story_img_name,
        "story_video": story_vid_name,
        "processed_video": output_video_name,
        "cover_image": cover_image_name,
        "is_published": is_already_published,
        "published_at": now.isoformat() if is_already_published else None,
        "publications": [],
    }
    save_today_preview(preview_data)
    print(f"[{date_str}] Apercu et video du jour verrouilles avec succes dans today_preview.json.")
    return preview_data



scheduler = BackgroundScheduler()


def start_scheduler():
    """Demarre la pre-generation quotidienne a 00:01 et la publication a 11:30."""
    if os.getenv("DISABLE_AUTO_SCHEDULER", "false").lower() in ("true", "1", "yes"):
        print("Planificateur automatique desactive via DISABLE_AUTO_SCHEDULER.")
        return

    if not scheduler.running:
        default_simulation = os.getenv("SIMULATION_MODE", "false").lower() in ("true", "1", "yes")

        # 1. Preparation de l'apercu chaque nuit a 00:01 heure de Paris
        scheduler.add_job(
            func=generate_daily_preview,
            trigger=CronTrigger(hour=0, minute=1, timezone="Europe/Paris"),
            id="daily_bchef_preview",
            name="Pre-generation quotidienne de l'apercu BCHEF",
            replace_existing=True,
        )

        # 2. Publication quotidienne a 11:30 heure de Paris
        scheduler.add_job(
            func=run_daily_publication,
            trigger=CronTrigger(hour=11, minute=30, timezone="Europe/Paris"),
            id="daily_bchef_publication",
            name="Publication quotidienne BCHEF Bourges",
            replace_existing=True,
            kwargs={"is_simulation": default_simulation},
        )
        scheduler.start()
        print("Planificateur active :")
        print(" - Pre-generation de l'apercu du jour chaque nuit a 00h01 (Paris).")
        print(f" - Publication automatique chaque jour a 11h30 (Paris, simulation={default_simulation}).")


if __name__ == "__main__":
    print("Test du pipeline complet...")
    res = run_daily_publication(is_simulation=True)
    print("\n--- RAPPORT DU PIPELINE ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
