import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

from src.config import TIKTOK_COOKIES_FILE, BASE_DIR

load_dotenv()

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class TikTokPublisher:
    def __init__(self, cookies_path: str | Path | None = None):
        p = cookies_path or os.getenv("TIKTOK_COOKIES_PATH")
        if p:
            resolved = Path(p)
            if not resolved.is_absolute():
                resolved = BASE_DIR / resolved
            self.cookies_path = resolved
        else:
            self.cookies_path = TIKTOK_COOKIES_FILE

    def publish_video(
        self,
        video_path: Path,
        caption: str,
        simulation: bool = True,
        location_query: str = "BCHEF Bourges",
    ) -> dict:
        """Publishes a video to TikTok via automated browser session."""
        if not video_path.exists():
            raise FileNotFoundError(f"Vidéo TikTok introuvable : {video_path}")

        cookies_file = Path(self.cookies_path)
        has_cookies = cookies_file.exists()

        if simulation or not has_cookies:
            return {
                "platform": "tiktok",
                "type": "video",
                "status": "simulated",
                "file": str(video_path),
                "caption": caption,
                "location": location_query,
                "message": (
                    "Vidéo TikTok prête et validée (Mode simulation ou session cookies non configurée). "
                    f"Session attendue dans {self.cookies_path}."
                ),
            }

        if sync_playwright is None:
            return {
                "platform": "tiktok",
                "type": "video",
                "status": "error",
                "error": "Playwright n'est pas installé dans l'environnement Python.",
            }

        try:
            with open(cookies_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            resolved_video_path = str(video_path.resolve())

            with sync_playwright() as p:
                launch_kwargs = {
                    "headless": True,
                    "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                }
                chrome_path = "/opt/google/chrome/chrome"
                if Path(chrome_path).exists():
                    launch_kwargs["executable_path"] = chrome_path

                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 900},
                )
                context.add_cookies(cookies)
                page = context.new_page()
                page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded")
                time.sleep(4)

                # Set video file
                file_input = page.locator('input[type="file"]')
                file_input.set_input_files(resolved_video_path)

                # Wait for upload processing
                time.sleep(8)

                # Dismiss modals if present
                for btn_text in ["Activer", "J'ai compris", "Autoriser"]:
                    try:
                        modal_btn = page.locator(f'button:has-text("{btn_text}")')
                        if modal_btn.count() > 0:
                            modal_btn.first.click(timeout=2000)
                            time.sleep(1)
                    except Exception:
                        pass

                # Fill caption
                editor = page.locator('div[contenteditable="true"]').first
                if editor.count() > 0:
                    editor.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    editor.fill(caption)

                time.sleep(1)

                # Location selection (BCHEF Bourges)
                try:
                    loc_box = page.locator('*:has-text("Rechercher des lieux")').last
                    if loc_box.count() > 0:
                        loc_box.click(timeout=2000)
                        time.sleep(1)
                        page.keyboard.type(location_query)
                        time.sleep(2)
                        first_loc_item = page.locator('div[role="listbox"] div, ul li, .location-item').first
                        if first_loc_item.count() > 0:
                            first_loc_item.click(timeout=2000)
                except Exception as e_loc:
                    print(f"Lieu TikTok non appliqué : {e_loc}")

                time.sleep(2)

                # Click Publish button
                publish_btn = page.locator('button:has-text("Publier")').first
                if publish_btn.count() > 0:
                    publish_btn.click()
                    time.sleep(2)

                    # Handle secondary 'Publier maintenant' confirmation if present
                    try:
                        pub_now = page.locator('button:has-text("Publier maintenant")')
                        if pub_now.count() > 0:
                            pub_now.first.click(timeout=3000)
                    except Exception:
                        pass

                    # Wait for redirect to content list
                    time.sleep(6)
                    browser.close()
                    return {
                        "platform": "tiktok",
                        "type": "video",
                        "status": "published",
                        "file": str(video_path),
                        "caption": caption,
                        "location": location_query,
                    }
                else:
                    browser.close()
                    return {
                        "platform": "tiktok",
                        "type": "video",
                        "status": "error",
                        "error": "Bouton de publication TikTok non trouvé sur la page.",
                    }

        except Exception as e:
            return {
                "platform": "tiktok",
                "type": "video",
                "status": "error",
                "error": str(e),
            }
