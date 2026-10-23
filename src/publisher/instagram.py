import os
import subprocess
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from src.config import INSTAGRAM_SESSION_FILE, BASE_DIR, DATA_DIR, get_social_settings

load_dotenv()


class InstagramPublisher:
    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        session_file: Path | str | None = None,
        target_profile: str | None = None,
    ):
        social_cfg = get_social_settings()
        active_target = target_profile or social_cfg.get("active_profile", "test")
        prof = social_cfg["profiles"].get(active_target, social_cfg["profiles"]["test"])

        self.target_profile = active_target
        self.username = username or prof.get("instagram_username") or os.getenv("INSTAGRAM_USERNAME")
        self.password = password or prof.get("instagram_password") or os.getenv("INSTAGRAM_PASSWORD")

        if session_file:
            resolved = Path(session_file)
            if not resolved.is_absolute():
                resolved = BASE_DIR / resolved
            self.session_file = resolved
        else:
            sess_name = prof.get("instagram_session_file", f"instagram_session_{active_target}.json")
            self.session_file = DATA_DIR / sess_name

    @staticmethod
    def _patch_instagrapi_ffmpeg():
        from instagrapi import Client
        import subprocess

        def custom_render_story_video_with_music(
            self,
            path: Path,
            track,
            output_path: Path,
            audio_asset_start_time: int,
            is_photo: bool = False,
            duration: Optional[float] = None,
            music_volume: float = 1.0,
        ) -> float:
            tmpaudio = self.track_download_by_url(
                self._story_music_track_url(track),
                "track",
                output_path.parent,
            )
            duration_sec = float(duration or 15.0)
            start_sec = float(audio_asset_start_time or 0) / 1000.0

            if is_photo:
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(path),
                    "-ss", str(start_sec),
                    "-t", str(duration_sec),
                    "-i", str(tmpaudio),
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(output_path),
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(path),
                    "-ss", str(start_sec),
                    "-t", str(duration_sec),
                    "-i", str(tmpaudio),
                    "-filter_complex", f"[1:a]volume={music_volume}[ma];[0:a][ma]amix=inputs=2[outa]",
                    "-map", "0:v",
                    "-map", "[outa]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    str(output_path),
                ]
            subprocess.run(cmd, check=True)
            return duration_sec

        Client._render_story_video_with_music = custom_render_story_video_with_music

    def _get_client(self):
        self._patch_instagrapi_ffmpeg()
        from instagrapi import Client
        cl = Client()
        if self.session_file.exists():
            try:
                cl.load_settings(self.session_file)
            except Exception:
                pass
        cl.login(self.username, self.password)
        cl.dump_settings(self.session_file)
        return cl

    def get_bchef_location(self, cl):
        """Finds the official BCHEF Bourges (13 Place Gordaine) location on Instagram."""
        try:
            # 13 Place Gordaine, 18000 Bourges coordinates
            locs = cl.location_search(47.08579, 2.39875)
            for loc in locs:
                if "bchef" in loc.name.lower():
                    return loc
            if locs:
                return locs[0]
        except Exception as e:
            print(f"Erreur recherche lieu BCHEF Instagram : {e}")
        return None

    def get_facebook_page_destination(self, cl) -> tuple[str | None, str | None]:
        """
        Retrieves the linked Facebook Page ID and name for cross-posting.
        Returns (page_id, page_name) if a Page is linked, else (None, None).
        Strictly guarantees that personal FB profiles are NEVER used for cross-posting.
        """
        if self.target_profile != "official":
            return None, None

        # 1. Try to extract directly from current Instagram profile metadata
        try:
            raw = cl.private_request(f"users/{cl.user_id}/info/")
            user = raw.get("user", {})
            page_id = user.get("page_id") or user.get("linked_fb_info", {}).get("linked_fb_page", {}).get("id")
            page_name = user.get("page_name") or user.get("linked_fb_info", {}).get("linked_fb_page", {}).get("name")
            if page_id:
                return str(page_id), str(page_name or "BCHEF (Bourges)")
        except Exception as e:
            print(f"Avertissement detection dynamique page Facebook : {e}", flush=True)

        # 2. Fallback to configured FACEBOOK_PAGE_ID
        from src.config import FACEBOOK_PAGE_ID
        if FACEBOOK_PAGE_ID:
            return str(FACEBOOK_PAGE_ID).strip(), "BCHEF (Bourges)"

        return None, None

    def get_suggested_music_track(self, cl) -> Optional[object]:
        """Fetches the #1 trending/suggested music track by Instagram, with search fallback."""
        try:
            trending = cl.music_trending()
            if trending and "items" in trending and len(trending["items"]) > 0:
                track = trending["items"][0].get("track")
                if track:
                    return track
        except Exception as e:
            print(f"Erreur récupération musique tendance Instagram : {e}")

        # Fallback to search if trending is unavailable
        try:
            tracks = cl.search_music("chill")
            if tracks and len(tracks) > 0:
                return tracks[0]
        except Exception as e_search:
            print(f"Erreur recherche musique de secours : {e_search}")

        return None

    def publish_story(self, media_path: Path, simulation: bool = True) -> dict:
        """
        Publishes a story to Instagram.
        Supports both 15s MP4 video stories (with native audio) and static PNG/JPG photos.
        """
        if not media_path.exists():
            raise FileNotFoundError(f"Fichier story introuvable : {media_path}")

        is_video = media_path.suffix.lower() in {".mp4", ".mov"}

        if simulation or not self.username or not self.password:
            return {
                "platform": "instagram",
                "type": "story",
                "status": "simulated",
                "file": str(media_path),
                "is_video": is_video,
                "message": (
                    "Story prête et validée (Mode simulation ou identifiants manquants). "
                    "Renseignez INSTAGRAM_USERNAME et INSTAGRAM_PASSWORD pour poster en direct."
                ),
            }

        try:
            cl = self._get_client()

            if is_video:
                print(f"Publication de la story vidéo Instagram avec son : {media_path.name}...")
                thumb_path = media_path.with_suffix(".jpg")
                if not thumb_path.exists():
                    try:
                        subprocess.run([
                            "ffmpeg", "-y",
                            "-ss", "00:00:01",
                            "-i", str(media_path),
                            "-vframes", "1",
                            "-q:v", "2",
                            str(thumb_path),
                        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    except Exception as e_thumb:
                        print(f"Avertissement création miniature story FFmpeg : {e_thumb}")
                        thumb_path = None
                media = cl.video_upload_to_story(str(media_path), thumbnail=thumb_path if thumb_path and thumb_path.exists() else None)
            else:
                print(f"Publication directe de la story photo Instagram : {media_path.name}...")
                media = cl.photo_upload_to_story(str(media_path))

            return {
                "platform": "instagram",
                "type": "story",
                "status": "published",
                "media_id": str(media.pk),
                "is_video": is_video,
            }
        except Exception as e:
            return {
                "platform": "instagram",
                "type": "story",
                "status": "error",
                "error": str(e),
            }

    def publish_reel(
        self,
        video_path: Path,
        caption: str,
        cover_path: Path | None = None,
        simulation: bool = True,
    ) -> dict:
        """Publishes a video reel with location BCHEF Bourges."""
        if not video_path.exists():
            raise FileNotFoundError(f"Vidéo reel introuvable : {video_path}")

        if simulation or not self.username or not self.password:
            return {
                "platform": "instagram",
                "type": "reel",
                "status": "simulated",
                "file": str(video_path),
                "caption": caption,
                "location": "BCHEF - 13 Place Gordaine, Bourges",
                "message": (
                    "Reel prêt et validé (Mode simulation ou identifiants manquants). "
                    "Renseignez INSTAGRAM_USERNAME et INSTAGRAM_PASSWORD pour poster en direct."
                ),
            }

        try:
            cl = self._get_client()
            thumbnail = str(cover_path) if cover_path and cover_path.exists() else None

            # 1. Location tagging
            bchef_loc = self.get_bchef_location(cl)

            # 2. Check Facebook Page cross-posting destination
            share_fb = False
            fb_page_id, fb_page_name = self.get_facebook_page_destination(cl)
            if fb_page_id:
                share_fb = True
                print(f"Destination Facebook validee : Page '{fb_page_name}' (ID: {fb_page_id})", flush=True)
            else:
                print(
                    "Partage Facebook desactive : aucune Page Facebook liee detectee. "
                    "Le partage sur profil personnel est strictement bloque par securite.",
                    flush=True,
                )

            # 3. Upload Reel with location and Facebook crossposting
            print(
                f"Publication du Reel avec le lieu : {bchef_loc.name if bchef_loc else 'Non trouve'} "
                f"(Partage Facebook Page : {share_fb}{f' -> {fb_page_name}' if share_fb else ''})",
                flush=True,
            )
            try:
                if share_fb and fb_page_id:
                    media = cl.clip_upload(
                        str(video_path),
                        caption=caption,
                        thumbnail=thumbnail,
                        location=bchef_loc,
                        share_to_facebook=True,
                        fb_destination_id=fb_page_id,
                        fb_destination_type="PAGE",
                    )
                else:
                    media = cl.clip_upload(
                        str(video_path),
                        caption=caption,
                        thumbnail=thumbnail,
                        location=bchef_loc,
                        share_to_facebook=False,
                    )
            except Exception as fb_err:
                print(f"Avertissement lors de l'envoi du Reel ({fb_err}), repli sans cross-posting Facebook...", flush=True)
                media = cl.clip_upload(
                    str(video_path),
                    caption=caption,
                    thumbnail=thumbnail,
                    location=bchef_loc,
                    share_to_facebook=False,
                )

            return {
                "platform": "instagram",
                "type": "reel",
                "status": "published",
                "media_id": str(media.pk),
                "location": bchef_loc.name if bchef_loc else "Bourges",
                "facebook_shared": share_fb,
                "facebook_destination": f"{fb_page_name} ({fb_page_id})" if share_fb and fb_page_id else None,
            }
        except Exception as e:
            return {
                "platform": "instagram",
                "type": "reel",
                "status": "error",
                "error": str(e),
            }
