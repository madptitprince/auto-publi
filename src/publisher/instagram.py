import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class InstagramPublisher:
    def __init__(self, username: str | None = None, password: str | None = None):
        self.username = username or os.getenv("INSTAGRAM_USERNAME")
        self.password = password or os.getenv("INSTAGRAM_PASSWORD")
        self.session_file = Path("data/instagram_session.json")

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

    def publish_story(self, image_path: Path, simulation: bool = True) -> dict:
        """Publishes a photo story with location and suggested background music to Instagram."""
        if not image_path.exists():
            raise FileNotFoundError(f"Image story introuvable : {image_path}")

        if simulation or not self.username or not self.password:
            return {
                "platform": "instagram",
                "type": "story",
                "status": "simulated",
                "file": str(image_path),
                "location": "BCHEF - 13 Place Gordaine, Bourges",
                "music": "Musique suggérée n°1 par Instagram",
                "message": (
                    "Story prête et validée (Mode simulation ou identifiants manquants). "
                    "Renseignez INSTAGRAM_USERNAME et INSTAGRAM_PASSWORD pour poster en direct."
                ),
            }

        try:
            from instagrapi.types import StoryLocation

            cl = self._get_client()

            # 1. Location tagging
            bchef_loc = self.get_bchef_location(cl)
            story_locations = []
            if bchef_loc:
                story_locations.append(
                    StoryLocation(location=bchef_loc, x=0.5, y=0.85, width=0.4, height=0.08)
                )

            # 2. Suggested music
            suggested_track = self.get_suggested_music_track(cl)
            media = None
            used_music = None

            if suggested_track:
                try:
                    if hasattr(suggested_track, "title"):
                        used_music = f"{suggested_track.title} - {getattr(suggested_track, 'display_artist', '')}"
                    else:
                        used_music = f"{suggested_track.get('title')} - {suggested_track.get('display_artist')}"
                    print(f"Publication de la story avec la musique suggérée : {used_music}")
                    media = cl.photo_upload_to_story_with_music(
                        path=image_path,
                        caption="",
                        track=suggested_track,
                        locations=story_locations,
                    )
                except Exception as e_music:
                    print(f"Upload avec musique échoué ({e_music}), repli sur upload standard avec lieu.")
                    media = None

            # Fallback without music if music upload fails or unavailable
            if media is None:
                media = cl.photo_upload_to_story(str(image_path), locations=story_locations)

            return {
                "platform": "instagram",
                "type": "story",
                "status": "published",
                "media_id": str(media.pk),
                "location": bchef_loc.name if bchef_loc else "Bourges",
                "music": used_music or "Standard",
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
        share_to_story: bool = True,
    ) -> dict:
        """Publishes a video reel with location, then immediately shares the reel to Story."""
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
                "shared_to_story": share_to_story,
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

            # 2. Upload Reel with location
            print(f"Publication du Reel avec le lieu : {bchef_loc.name if bchef_loc else 'Non trouvé'}")
            media = cl.clip_upload(
                str(video_path),
                caption=caption,
                thumbnail=thumbnail,
                location=bchef_loc,
            )

            # 3. Direct share Reel to Story
            shared_story_id = None
            if share_to_story:
                try:
                    print(f"Partage immédiat du Reel {media.pk} en Story Instagram...")
                    shared_story = cl.media_share_to_story(str(media.pk))
                    shared_story_id = str(shared_story.pk)
                    print(f"Reel partagé en Story avec succès (ID: {shared_story_id})")
                except Exception as e_share:
                    print(f"Partage du Reel en story non effectué : {e_share}")

            return {
                "platform": "instagram",
                "type": "reel",
                "status": "published",
                "media_id": str(media.pk),
                "location": bchef_loc.name if bchef_loc else "Bourges",
                "shared_to_story": bool(shared_story_id),
                "story_media_id": shared_story_id,
            }
        except Exception as e:
            return {
                "platform": "instagram",
                "type": "reel",
                "status": "error",
                "error": str(e),
            }
