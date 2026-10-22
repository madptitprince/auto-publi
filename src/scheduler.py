import os
import re
import json
import time
import shutil
import datetime
from pathlib import Path
import threading
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
    get_publication_frequency,
)
from src.story_generator import generate_daily_story, create_story_video
from src.ai_analyzer import analyze_video_with_gemini
from src.video_processor import process_video_with_hook
from src.publisher.instagram import InstagramPublisher
from src.publisher.tiktok import TikTokPublisher

PUBLICATION_SLOTS = [
    {
        "slot": 1,
        "prepare_hour": 0,
        "prepare_minute": 1,
        "publish_hour": 11,
        "publish_minute": 30,
        "publish_time_str": "11:30",
        "has_story": True,
    },
    {
        "slot": 2,
        "prepare_hour": 11,
        "prepare_minute": 31,
        "publish_hour": 13,
        "publish_minute": 30,
        "publish_time_str": "13:30",
        "has_story": False,
    },
    {
        "slot": 3,
        "prepare_hour": 13,
        "prepare_minute": 31,
        "publish_hour": 15,
        "publish_minute": 30,
        "publish_time_str": "15:30",
        "has_story": False,
    },
    {
        "slot": 4,
        "prepare_hour": 15,
        "prepare_minute": 31,
        "publish_hour": 17,
        "publish_minute": 30,
        "publish_time_str": "17:30",
        "has_story": False,
    },
]


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_history(history: list[dict]):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def save_history_entry(entry: dict):
    history = load_history()
    history.insert(0, entry)  # Prepend latest
    save_history(history)


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
    slot_index: int = 1,
    publish_story: bool = True,
) -> dict:
    """
    Executes the full automated publication workflow:
    1. Verifie le verrou anti-doublon pour le creneau du jour (empeche de republier le meme creneau).
    2. Recupere l'apercu verrouille a 00h01 (ou genere si absent).
    3. Utilise la video selectionnee et deja pre-encodee (gain de temps et 0 bug).
    4. Publie la Story 15s (uniquement sur le creneau 1 de 11h30) et le Reel / TikTok.
    5. Archive la video brute et met a jour today_preview.json.
    """
    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d_%H-%M-%S")
    date_str = now.strftime("%Y-%m-%d")

    today_preview = get_today_preview()
    # Si le slot_index n'est pas force et qu'un apercu existe pour aujourd'hui, heriter de son slot
    if today_preview and today_preview.get("date") == date_str and "slot" in today_preview and slot_index == 1:
        slot_index = today_preview.get("slot", 1)
        publish_story = today_preview.get("has_story", slot_index == 1)

    # Anti-doublon check pour ce créneau précis
    is_already_published = False
    if today_preview and today_preview.get("date") == date_str and today_preview.get("slot", 1) == slot_index and today_preview.get("is_published"):
        is_already_published = True

    if not is_simulation:
        history = load_history()
        for h in history:
            if h.get("date") == date_str and h.get("slot", 1) == slot_index and h.get("status") == "success" and not h.get("is_simulation"):
                is_already_published = True
                break

    if is_already_published and not force_publish:
        msg = f"La publication du {date_str} (creneau {slot_index}) a deja ete effectuee aujourd'hui. Aucune republication pour eviter les doublons."
        print(f"[{timestamp_str}] {msg}")
        if progress_callback:
            progress_callback(msg, 100)
        return {
            "id": f"pub_{timestamp_str}",
            "status": "already_published",
            "message": msg,
            "date": date_str,
            "slot": slot_index,
        }

    report = {
        "id": f"pub_{timestamp_str}",
        "timestamp": now.isoformat(),
        "date": date_str,
        "slot": slot_index,
        "is_simulation": is_simulation,
        "story": None,
        "video": None,
        "ai_analysis": None,
        "publications": [],
        "status": "in_progress",
    }

    try:
        # Step 1: Ensure today's preview & story exist (story only if publish_story is True)
        story_vid_path = PROCESSED_STORIES_DIR / f"story_{date_str}.mp4"
        story_img_path = PROCESSED_STORIES_DIR / f"story_{date_str}.png"
        if not today_preview or today_preview.get("date") != date_str or (publish_story and not story_vid_path.exists()):
            if progress_callback:
                progress_callback("Preparation et verrouillage de l'apercu du jour...", 15)
            today_preview = generate_daily_preview(
                target_date=now.date(),
                slot_index=slot_index,
                generate_story=publish_story,
            )

        if publish_story:
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
        print(f"[{timestamp_str} slot {slot_index}] Etape 2 : Selection de la video verrouillee...")
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
                    msg = f"[{timestamp_str} slot {slot_index}] Aucune video disponible (file d'attente et archives vides). Creneau ignore sans erreur."
                    print(msg)
                    if progress_callback:
                        progress_callback(msg, -1)
                    return {
                        "id": f"pub_{timestamp_str}",
                        "status": "skipped_no_media",
                        "message": msg,
                        "date": date_str,
                        "slot": slot_index,
                    }

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
        expected_video_file = (
            f"video_{date_str}_{selected_video.stem}.mp4"
            if slot_index == 1
            else f"video_{date_str}_slot{slot_index}_{selected_video.stem}.mp4"
        )
        expected_video_path = PROCESSED_VIDEOS_DIR / expected_video_file
        expected_cover_path = PROCESSED_VIDEOS_DIR / f"{expected_video_path.stem}_cover.jpg"

        if not need_reencode and expected_video_path.exists() and expected_cover_path.exists():
            if progress_callback:
                progress_callback("Reutilisation de la video deja encodee...", 75)
            print(f"[{timestamp_str} slot {slot_index}] Etape 4 : Video deja encodee disponible ({expected_video_file}), saut de l'encodage...")
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
            print(f"[{timestamp_str} slot {slot_index}] Etape 4 : Incrustation du Hook sur la video...")
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
        print(f"[{timestamp_str} slot {slot_index}] Etape 5 : Publications sur profil '{insta.target_profile}' ({insta.username})...")

        # Story Instagram (publiée 1 seule fois à 11h30 pour le créneau 1)
        if publish_story:
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
        else:
            print(f"[{timestamp_str} slot {slot_index}] Publication video seule (Reel + TikTok), saut de la story.")

        # Reel Instagram (avec lieu BCHEF Bourges et partage Facebook auto)
        insta_reel_res = insta.publish_reel(
            video_path=Path(video_res["output_video"]),
            caption=full_caption,
            cover_path=Path(video_res["cover_image"]),
            simulation=is_simulation,
        )
        report["publications"].append(insta_reel_res)

        # Video TikTok (avec lieu BCHEF Bourges) - Avec 2 tentatives automatiques
        tiktok_res = None
        for attempt in range(1, 3):
            if attempt > 1:
                print(f"[{timestamp_str} slot {slot_index}] Tentative TikTok {attempt}/2 apres un premier echec. Pause de 15s...")
                time.sleep(15)
            tiktok_res = tiktok.publish_video(
                video_path=Path(video_res["output_video"]),
                caption=full_caption,
                simulation=is_simulation,
                location_query="BCHEF Bourges",
            )
            if tiktok_res.get("status") in ("published", "simulated"):
                break
        report["publications"].append(tiktok_res)

        # Step 6: Rotation & Archivage de la video
        any_published_ok = any(p.get("status") == "published" for p in report["publications"])
        if not is_simulation and any_published_ok:
            if progress_callback:
                progress_callback("Rotation et archivage de la video...", 98)
            print(f"[{timestamp_str} slot {slot_index}] Etape 6 : Rotation et archivage de la video...")
            if not is_recycled:
                ARCHIVE_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
                dest_name = f"{date_str}_{selected_video.name}"
                dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                if dest_path.exists():
                    dest_name = f"{timestamp_str}_{selected_video.name}"
                    dest_path = ARCHIVE_VIDEOS_DIR / dest_name
                shutil.move(str(selected_video), str(dest_path))
                report["archived_video"] = dest_name
                print(f"[{timestamp_str} slot {slot_index}] Video archivee avec succes : {dest_name}")
            else:
                selected_video.touch()
                report["archived_video"] = selected_video.name
                print(f"[{timestamp_str} slot {slot_index}] Video recyclee decalee en fin de cycle : {selected_video.name}")

            # Marquer l'apercu du jour comme publie pour ce creneau
            if today_preview:
                today_preview["is_published"] = True
                today_preview["published_at"] = now.isoformat()
                today_preview["slot"] = slot_index
                today_preview["publications"] = report["publications"]
                today_preview["report"] = report
                save_today_preview(today_preview)
        elif not is_simulation and not any_published_ok:
            print(f"[{timestamp_str} slot {slot_index}] Avertissement : Aucune publication n'a reussi en production. La video n'est pas archivee.")

        report["status"] = "success" if (is_simulation or any_published_ok) else "error"
        if progress_callback:
            progress_callback("Publication terminee avec succes !" if report["status"] == "success" else "Echec de la publication.", 100 if report["status"] == "success" else -1)
        print(f"[{timestamp_str} slot {slot_index}] Publication terminee (status={report['status']})")

    except Exception as e:
        report["status"] = "error"
        report["error"] = str(e)
        if progress_callback:
            progress_callback(f"Erreur : {e}", -1)
        print(f"[{timestamp_str} slot {slot_index}] Erreur durant la publication : {e}")

    save_history_entry(report)
    return report


def generate_daily_preview(
    target_date: datetime.date | None = None,
    force: bool = False,
    slot_index: int = 1,
    publish_time_str: str = "11:30",
    generate_story: bool = True,
) -> dict:
    """
    S'execute automatiquement pour preparer et verrouiller l'apercu d'un creneau de publication :
    - Creneau 1 (a 00h01) : genere la story 15s + selectionne la video 1 + analyse Gemini + incruste le hook.
    - Creneaux 2, 3, 4 : selectionne la video suivante (sans refaire de story) + analyse Gemini + incruste le hook.
    """
    now = datetime.datetime.now()
    target = target_date or now.date()
    date_str = target.strftime("%Y-%m-%d")
    print(f"[{date_str} slot {slot_index}] Pre-generation automatique de l'apercu pour diffusion a {publish_time_str}...")

    cached_preview = get_today_preview()
    if cached_preview and cached_preview.get("date") == date_str and cached_preview.get("slot", 1) == slot_index and not force:
        proc_v = PROCESSED_VIDEOS_DIR / cached_preview.get("processed_video", "")
        if proc_v.exists():
            print(f"[{date_str} slot {slot_index}] Apercu deja existant et valide dans today_preview.json.")
            return cached_preview

    # 1. Pre-generate today's story image + 15s MP4 video with daily audio (uniquement si generate_story est True, donc creneau 1 a 11h30)
    story_img_name = f"story_{date_str}.png"
    story_vid_name = f"story_{date_str}.mp4"
    if generate_story:
        try:
            story_res = generate_daily_story(target_date=target, output_filename=story_img_name)
            create_story_video(
                image_path=Path(story_res["output_path"]),
                target_date=target,
                duration=15,
                output_filename=story_vid_name,
            )
            print(f"[{date_str}] Story video 15s pre-generee pour le creneau {slot_index} (11h30).")
        except Exception as e_story:
            print(f"Erreur pre-generation story : {e_story}")
    else:
        # Creneau sans nouvelle story : on conserve la reference vers la story du jour si elle existe
        if not (PROCESSED_STORIES_DIR / story_img_name).exists():
            story_img_name = None
            story_vid_name = None

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
            print(f"[{date_str} slot {slot_index}] Aucune video disponible (file d'attente et archives vides). Creneau ignore.")
            return {}

    # 3. Gemini AI Analysis
    ai_data = None
    cache_file = BASE_DIR / "data" / "last_ai_analysis.json"
    if not force and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if cdata.get("video_name") == video_to_process.name and "analysis" in cdata:
                    cached_analysis = cdata["analysis"]
                    # Do not reuse fallback_error from cache
                    if cached_analysis.get("source") != "fallback_error":
                        ai_data = cached_analysis
        except Exception:
            pass

    if not ai_data:
        print(f"[{date_str} slot {slot_index}] Analyse IA Gemini de la video {video_to_process.name}...", flush=True)
        ai_data = analyze_video_with_gemini(video_to_process)
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"video_name": video_to_process.name, "analysis": ai_data}, f, ensure_ascii=False, indent=2)
        except Exception as e_cache:
            print(f"Erreur sauvegarde cache IA : {e_cache}", flush=True)

    hook_text = ai_data.get("hook", "Le rendez-vous des gourmands chez BCHEF Bourges !").upper().strip()
    caption_line = ai_data.get("description", "Rejoignez-nous chez BCHEF Bourges au 13 place Gordaine !")
    hashtags_list = ai_data.get("hashtags", ["#bchef", "#bourges", "#burger", "#restobourges", "#foodie"])

    # 4. Burn the hook overlay onto the video NOW
    output_video_name = (
        f"video_{date_str}_{video_to_process.stem}.mp4"
        if slot_index == 1
        else f"video_{date_str}_slot{slot_index}_{video_to_process.stem}.mp4"
    )
    print(f"[{date_str} slot {slot_index}] Pre-incrustation de l'accroche sur {video_to_process.name} -> {output_video_name}...")
    video_res = process_video_with_hook(
        input_video=video_to_process,
        hook_text=hook_text,
        output_filename=output_video_name,
    )
    cover_image_name = Path(video_res["cover_image"]).name

    # Verifier si ce créneau a deja ete publie dans l'historique
    history = load_history()
    is_already_published = False
    for h in history:
        if h.get("date") == date_str and h.get("slot", 1) == slot_index and h.get("status") == "success" and not h.get("is_simulation"):
            is_already_published = True
            break

    # 5. Save into data/today_preview.json
    preview_data = {
        "date": date_str,
        "slot": slot_index,
        "scheduled_time": publish_time_str,
        "has_story": generate_story,
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
    print(f"[{date_str} slot {slot_index}] Apercu et video verrouilles avec succes pour diffusion a {publish_time_str}.")
    return preview_data



scheduler = BackgroundScheduler()


def catchup_tiktok_publication(simulation: bool = False):
    """Verifie si Instagram a ete publie aujourd'hui mais que TikTok est manquant ou en erreur, et le publie de maniere autonome."""
    try:
        import zoneinfo
        paris_tz = zoneinfo.ZoneInfo("Europe/Paris")
        now_paris = datetime.datetime.now(paris_tz)
        today_str = now_paris.strftime("%Y-%m-%d")

        if (now_paris.hour > 11 or (now_paris.hour == 11 and now_paris.minute >= 35)) and now_paris.hour < 23:
            prev = get_today_preview()
            if not prev or prev.get("date") != today_str:
                return

            pubs = prev.get("publications", [])
            has_insta_success = any(p.get("platform") == "instagram" and p.get("status") == "published" for p in pubs)
            has_tiktok_success = any(p.get("platform") == "tiktok" and p.get("status") == "published" for p in pubs)

            if has_insta_success and not has_tiktok_success:
                print(f"[{today_str}] Watchdog TikTok : Instagram est publie mais TikTok est manquant ou en erreur. Lancement du rattrapage...")
                processed_video_name = prev.get("processed_video")
                if not processed_video_name:
                    return
                video_file = PROCESSED_VIDEOS_DIR / processed_video_name
                if not video_file.exists():
                    return

                caption_line = prev.get("description", "")
                hashtags_list = prev.get("hashtags", ["#bchef", "#bourges", "#burger"])
                full_caption = f"{caption_line}\n\n{' '.join(hashtags_list)}"

                tiktok = TikTokPublisher()
                tiktok_res = tiktok.publish_video(
                    video_path=video_file,
                    caption=full_caption,
                    simulation=simulation,
                    location_query="BCHEF Bourges",
                )
                print(f"[{today_str}] Resultat du rattrapage automatique TikTok : {tiktok_res.get('status')}")

                new_pubs = [p for p in pubs if p.get("platform") != "tiktok"]
                new_pubs.append(tiktok_res)
                prev["publications"] = new_pubs
                if tiktok_res.get("status") == "published":
                    prev["is_published"] = True
                save_today_preview(prev)

                history = load_history()
                for h in history:
                    if h.get("date") == today_str:
                        h_pubs = [p for p in h.get("publications", []) if p.get("platform") != "tiktok"]
                        h_pubs.append(tiktok_res)
                        h["publications"] = h_pubs
                        save_history(history)
                        break
    except Exception as e_tt_catchup:
        print(f"Erreur rattrapage TikTok : {e_tt_catchup}")


def configure_scheduler_jobs(simulation: bool | None = None):
    """Configure dynamiquement les taches APScheduler selon la frequence choisie (1 a 4 publications par jour)."""
    default_simulation = simulation if simulation is not None else (
        os.getenv("SIMULATION_MODE", "false").lower() in ("true", "1", "yes")
    )
    freq = get_publication_frequency()

    # Nettoyage des anciennes taches de publication et preparation
    for legacy_id in ("daily_bchef_preview", "daily_bchef_publication"):
        if scheduler.get_job(legacy_id):
            scheduler.remove_job(legacy_id)

    for s_idx in range(1, 5):
        j_prep = f"bchef_preview_slot_{s_idx}"
        j_pub = f"bchef_pub_slot_{s_idx}"
        if scheduler.get_job(j_prep):
            scheduler.remove_job(j_prep)
        if scheduler.get_job(j_pub):
            scheduler.remove_job(j_pub)

    active_slots = PUBLICATION_SLOTS[:freq]
    for s_info in active_slots:
        s_num = s_info["slot"]
        prep_h = s_info["prepare_hour"]
        prep_m = s_info["prepare_minute"]
        pub_h = s_info["publish_hour"]
        pub_m = s_info["publish_minute"]
        pub_time = s_info["publish_time_str"]
        has_story = s_info["has_story"]

        # Preparation job
        scheduler.add_job(
            func=generate_daily_preview,
            trigger=CronTrigger(hour=prep_h, minute=prep_m, timezone="Europe/Paris"),
            id=f"bchef_preview_slot_{s_num}",
            name=f"Preparation preview slot {s_num} a {prep_h:02d}h{prep_m:02d}",
            replace_existing=True,
            kwargs={
                "slot_index": s_num,
                "publish_time_str": pub_time,
                "generate_story": has_story,
                "force": s_num > 1,
            },
            misfire_grace_time=7200,
        )

        # Publication job
        scheduler.add_job(
            func=run_daily_publication,
            trigger=CronTrigger(hour=pub_h, minute=pub_m, timezone="Europe/Paris"),
            id=f"bchef_pub_slot_{s_num}",
            name=f"Publication slot {s_num} a {pub_time}",
            replace_existing=True,
            kwargs={
                "is_simulation": default_simulation,
                "slot_index": s_num,
                "publish_story": has_story,
            },
            misfire_grace_time=7200,
        )

    # Watchdog autonome TikTok actif de 11h a 19h
    if not scheduler.get_job("watchdog_tiktok_catchup"):
        scheduler.add_job(
            func=catchup_tiktok_publication,
            trigger=CronTrigger(minute="*/15", hour="11-19", timezone="Europe/Paris"),
            id="watchdog_tiktok_catchup",
            name="Watchdog rattrapage autonome TikTok",
            replace_existing=True,
            kwargs={"simulation": default_simulation},
        )

    print(f"Planificateur configure avec {freq} publication(s) par jour :", flush=True)
    for s_info in active_slots:
        st_txt = " (avec Story Instagram)" if s_info["has_story"] else " (Video seule Reel + TikTok)"
        print(f" - Creneau {s_info['slot']} : Preparation {s_info['prepare_hour']:02d}h{s_info['prepare_minute']:02d} -> Publication {s_info['publish_time_str']}{st_txt}", flush=True)


def check_and_catchup_publication(simulation: bool = False):
    """Verifie si une publication planifiee a ete manquee et lance un rattrapage automatique."""
    try:
        import zoneinfo
        paris_tz = zoneinfo.ZoneInfo("Europe/Paris")
        now_paris = datetime.datetime.now(paris_tz)
        today_str = now_paris.strftime("%Y-%m-%d")

        prev = get_today_preview()
        if prev and prev.get("date") == today_str and not prev.get("is_published"):
            slot_idx = prev.get("slot", 1)
            sched_time = prev.get("scheduled_time", "11:30")
            has_story = prev.get("has_story", slot_idx == 1)
            try:
                sh, sm = map(int, sched_time.split(":"))
            except Exception:
                sh, sm = 11, 30

            # Si l'heure de publication du créneau est passée
            if (now_paris.hour > sh or (now_paris.hour == sh and now_paris.minute >= sm)) and now_paris.hour < 23:
                print(f"[{today_str}] Rattrapage automatique : creneau {slot_idx} ({sched_time}) en attente a {now_paris.strftime('%H:%M')}, declenchement...")
                threading.Thread(
                    target=run_daily_publication,
                    kwargs={
                        "is_simulation": simulation,
                        "slot_index": slot_idx,
                        "publish_story": has_story,
                    },
                    daemon=True,
                ).start()
                return

        catchup_tiktok_publication(simulation=simulation)
    except Exception as e_catchup:
        print(f"Erreur verification rattrapage : {e_catchup}")


def start_scheduler():
    """Demarre le planificateur automatique selon la frequence configuree."""
    if os.getenv("DISABLE_AUTO_SCHEDULER", "false").lower() in ("true", "1", "yes"):
        print("Planificateur automatique desactive via DISABLE_AUTO_SCHEDULER.")
        return

    if not scheduler.running:
        default_simulation = os.getenv("SIMULATION_MODE", "false").lower() in ("true", "1", "yes")
        configure_scheduler_jobs(simulation=default_simulation)
        scheduler.start()
        check_and_catchup_publication(simulation=default_simulation)


if __name__ == "__main__":
    print("Test du pipeline complet...")
    res = run_daily_publication(is_simulation=True)
    print("\n--- RAPPORT DU PIPELINE ---")
    print(json.dumps(res, indent=2, ensure_ascii=False))
