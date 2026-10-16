import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

from src.config import TIKTOK_COOKIES_FILE, BASE_DIR, DATA_DIR, get_social_settings

load_dotenv()

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


class TikTokPublisher:
    def __init__(self, cookies_path: str | Path | None = None, target_profile: str | None = None):
        social_cfg = get_social_settings()
        active_target = target_profile or social_cfg.get("active_profile", "test")
        prof = social_cfg["profiles"].get(active_target, social_cfg["profiles"]["test"])

        self.target_profile = active_target
        if cookies_path:
            p = cookies_path
        else:
            p = prof.get("tiktok_cookies_file") or os.getenv("TIKTOK_COOKIES_PATH")

        if p:
            resolved = Path(p)
            if not resolved.is_absolute():
                resolved = DATA_DIR / resolved.name
            self.cookies_path = resolved
        else:
            self.cookies_path = TIKTOK_COOKIES_FILE

    def _dismiss_modals(self, page):
        """Ferme ou neutralise les modales, tutoriels et popups dans TikTok Studio."""
        # 1. Echap au clavier pour fermer les dialogues standards
        try:
            page.keyboard.press("Escape")
            time.sleep(0.3)
        except Exception:
            pass

        # 2. Boutons d'action usuels des modales et alertes
        dismiss_texts = [
            "J'ai compris",
            "Got it",
            "OK",
            "Ok",
            "D'accord",
            "Fermer",
            "Close",
            "Continuer",
            "Continue",
            "Activer",
            "Autoriser",
            "Non merci",
            "Plus tard",
            "Not now",
            "Ignorer",
            "Accepter",
            "Suivant",
            "Next",
            "Compris",
        ]
        for txt in dismiss_texts:
            try:
                btns = page.locator(
                    f'div[role="dialog"] button:has-text("{txt}"), '
                    f'.TUXModal button:has-text("{txt}"), '
                    f'[data-floating-ui-portal] button:has-text("{txt}")'
                )
                cnt = btns.count()
                for i in range(min(cnt, 2)):
                    b = btns.nth(i)
                    if b.is_visible():
                        b.click(timeout=1000, force=True)
                        time.sleep(0.3)
            except Exception:
                pass

        # 3. Icones ou croix de fermeture
        try:
            close_btns = page.locator(
                '[data-floating-ui-portal] button[aria-label*="close" i], '
                '[data-floating-ui-portal] button[aria-label*="fermer" i], '
                '.TUXModal-close, '
                'div[role="dialog"] button[aria-label*="close" i], '
                'div[role="dialog"] button[aria-label*="fermer" i]'
            )
            for i in range(min(close_btns.count(), 2)):
                cb = close_btns.nth(i)
                if cb.is_visible():
                    cb.click(timeout=1000, force=True)
                    time.sleep(0.3)
        except Exception:
            pass

        # 4. Suppression DOM en dernier recours des overlays bloquants
        try:
            page.evaluate('''() => {
                const portals = document.querySelectorAll(
                    '[data-floating-ui-portal], .TUXModal-overlay, .TUXModal'
                );
                portals.forEach(p => {
                    const hasEditor = p.querySelector('div[contenteditable="true"]');
                    const hasFileInput = p.querySelector('input[type="file"]');
                    const hasPublish = p.querySelector('button[type="submit"]') || p.innerText.includes('Publier');
                    if (!hasEditor && !hasFileInput && !hasPublish) {
                        p.remove();
                    }
                });
            }''')
        except Exception:
            pass

    def publish_video(
        self,
        video_path: Path,
        caption: str,
        simulation: bool = True,
        location_query: str = "BCHEF Bourges",
    ) -> dict:
        """Publie une video sur TikTok via session de navigateur automatisee."""
        if not video_path.exists():
            raise FileNotFoundError(f"Video TikTok introuvable : {video_path}")

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
                    "Video TikTok prete et validee (Mode simulation ou session cookies non configuree). "
                    f"Session attendue dans {self.cookies_path}."
                ),
            }

        if sync_playwright is None:
            return {
                "platform": "tiktok",
                "type": "video",
                "status": "error",
                "error": "Playwright n'est pas installe dans l'environnement Python.",
            }

        browser = None
        page = None
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

                # 1. Navigation vers TikTok Studio
                page.goto("https://www.tiktok.com/tiktokstudio/upload", wait_until="domcontentloaded")
                time.sleep(5)
                self._dismiss_modals(page)

                # 2. Selection du fichier video
                file_input = page.locator('input[type="file"]').first
                try:
                    file_input.wait_for(state="attached", timeout=15000)
                except Exception:
                    pass

                self._dismiss_modals(page)
                file_input.set_input_files(resolved_video_path)

                # 3. Attente dynamique de televersement et d'apparition de l'editeur
                editor = page.locator('div[contenteditable="true"]').first
                video_ready = False
                for _ in range(30):
                    time.sleep(2)
                    self._dismiss_modals(page)
                    if editor.count() > 0 and editor.is_visible():
                        video_ready = True
                        break

                if not video_ready:
                    time.sleep(5)
                    self._dismiss_modals(page)

                # 4. Remplissage de la legende avec click force anti-interception
                self._dismiss_modals(page)
                if editor.count() > 0:
                    try:
                        editor.click(force=True, timeout=5000)
                    except Exception:
                        pass
                    time.sleep(0.5)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    time.sleep(0.5)
                    try:
                        page.keyboard.insert_text(caption)
                    except Exception:
                        try:
                            editor.fill(caption)
                        except Exception:
                            page.keyboard.type(caption, delay=15)

                time.sleep(1)
                self._dismiss_modals(page)

                # 5. Selection du lieu (BCHEF Bourges)
                if location_query:
                    try:
                        loc_box = page.locator('*:has-text("Rechercher des lieux")').last
                        if loc_box.count() > 0:
                            loc_box.click(timeout=3000, force=True)
                            time.sleep(1)
                            page.keyboard.type(location_query)
                            time.sleep(2)
                            first_loc_item = page.locator('div[role="listbox"] div, ul li, .location-item').first
                            if first_loc_item.count() > 0:
                                first_loc_item.click(timeout=3000, force=True)
                    except Exception as e_loc:
                        print(f"Lieu TikTok non applique : {e_loc}")

                time.sleep(2)
                self._dismiss_modals(page)

                # 6. Clic sur le bouton Publier
                publish_btn = page.locator('button:has-text("Publier")').first
                if publish_btn.count() == 0:
                    publish_btn = page.locator('button:has-text("Post")').first

                if publish_btn.count() > 0:
                    # Attente que les verifications TikTok se terminent
                    for _ in range(15):
                        self._dismiss_modals(page)
                        if publish_btn.is_enabled():
                            break
                        time.sleep(2)

                    publish_btn.click(force=True, timeout=5000)
                    time.sleep(3)

                    # Gestion des confirmations secondaires
                    for confirm_txt in [
                        "Publier maintenant",
                        "Post now",
                        "Ignorer et publier",
                        "Post anyway",
                        "Continuer la publication",
                        "Confirmer",
                        "J'ai compris",
                    ]:
                        try:
                            confirm_btn = page.locator(f'button:has-text("{confirm_txt}")')
                            if confirm_btn.count() > 0 and confirm_btn.first.is_visible():
                                confirm_btn.first.click(timeout=3000, force=True)
                                time.sleep(2)
                        except Exception:
                            pass

                    # Attente de validation finale
                    time.sleep(8)
                    screenshot_path = DATA_DIR / "tiktok_last_success.png"
                    try:
                        page.screenshot(path=str(screenshot_path))
                    except Exception:
                        pass

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
                    err_screenshot = DATA_DIR / "tiktok_error_no_btn.png"
                    try:
                        page.screenshot(path=str(err_screenshot))
                    except Exception:
                        pass
                    browser.close()
                    return {
                        "platform": "tiktok",
                        "type": "video",
                        "status": "error",
                        "error": "Bouton de publication TikTok non trouve sur la page.",
                    }

        except Exception as e:
            err_screenshot = DATA_DIR / "tiktok_last_error.png"
            try:
                if page:
                    page.screenshot(path=str(err_screenshot))
            except Exception:
                pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            return {
                "platform": "tiktok",
                "type": "video",
                "status": "error",
                "error": str(e),
            }


def publish_single_tiktok(
    video_path: str | Path,
    caption: str,
    target_profile: str = "official",
    simulation: bool = False,
    location_query: str = "BCHEF Bourges",
) -> dict:
    """Helper direct pour publier une video sur TikTok sans passer par le pipeline complet."""
    publisher = TikTokPublisher(target_profile=target_profile)
    return publisher.publish_video(
        video_path=Path(video_path),
        caption=caption,
        simulation=simulation,
        location_query=location_query,
    )

