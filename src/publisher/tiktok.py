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
            p = prof.get("tiktok_cookies_file")
            if not p:
                if active_target == "official":
                    candidate = DATA_DIR / "tiktok_cookies_official.json"
                    p = "tiktok_cookies_official.json" if candidate.exists() else os.getenv("TIKTOK_COOKIES_PATH")
                else:
                    p = os.getenv("TIKTOK_COOKIES_PATH")

        if p:
            resolved = Path(p)
            if not resolved.is_absolute():
                resolved = DATA_DIR / resolved.name
            self.cookies_path = resolved
        else:
            self.cookies_path = TIKTOK_COOKIES_FILE

    def _dismiss_modals(self, page):
        """Ferme ou neutralise les modales, tutoriels et popups dans TikTok Studio."""
        # 1. Boutons d'action usuels des modales et alertes (Turn on, Got it, etc.)
        dismiss_texts = [
            "Turn on",
            "Got it",
            "J'ai compris",
            "OK",
            "Ok",
            "D'accord",
            "Allow",
            "Autoriser",
            "Activer",
            "Fermer",
            "Close",
            "Continuer",
            "Continue",
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
                    f'button:has-text("{txt}"), '
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

        # 2. Si un dialogue "Are you sure you want to exit" apparait par erreur, cliquer sur Cancel
        try:
            exit_modal = page.locator('*:has-text("Are you sure you want to exit")')
            if exit_modal.count() > 0 and exit_modal.first.is_visible():
                cancel_btn = page.locator('button:has-text("Cancel")').first
                if cancel_btn.count() > 0:
                    cancel_btn.click(timeout=1000, force=True)
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
                    const hasPublish = p.querySelector('button[type="submit"]') || p.innerText.includes('Post') || p.innerText.includes('Publier');
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
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    "ignore_default_args": ["--enable-automation"],
                }
                chrome_path = "/opt/google/chrome/chrome"
                if Path(chrome_path).exists():
                    launch_kwargs["executable_path"] = chrome_path

                browser = p.chromium.launch(**launch_kwargs)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    viewport={"width": 1440, "height": 900},
                    locale="fr-FR",
                )
                context.add_cookies(cookies)
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)

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
                for _ in range(45):
                    time.sleep(2)
                    self._dismiss_modals(page)
                    
                    # Detection et gestion automatique de l'erreur "Une erreur est survenue. Merci de reessayer."
                    retry_btn = page.locator('button:has-text("Réessayer"), button:has-text("Reessayer"), button:has-text("Retry")')
                    if retry_btn.count() > 0 and retry_btn.first.is_visible():
                        print("Bouton Reessayer detecte durant l'upload TikTok, clic de relance...")
                        retry_btn.first.click(force=True)
                        time.sleep(3)
                        continue

                    # Verifier que l'editeur est visible ET que le bouton de publication ou la couverture est monte
                    has_editor = editor.count() > 0 and editor.is_visible()
                    has_cover_or_post = page.locator('button[data-e2e="post_video_button"], *:has-text("Modifier la couverture"), *:has-text("Edit cover")').count() > 0
                    is_uploading = page.locator('*:has-text("Importation..."), *:has-text("Uploading..."), *:has-text("Téléversement...")').count() > 0

                    if has_editor and has_cover_or_post and not is_uploading:
                        video_ready = True
                        break

                if not video_ready:
                    time.sleep(5)
                    self._dismiss_modals(page)

                # 4. Remplissage de la legende avec effacement garanti du nom de fichier
                self._dismiss_modals(page)
                if editor.count() > 0:
                    try:
                        editor.click(force=True, timeout=5000)
                    except Exception:
                        pass
                    time.sleep(0.5)
                    page.evaluate("""(text) => {
                        const el = document.querySelector('div[contenteditable="true"]');
                        if (el) {
                            el.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('delete', false, null);
                            document.execCommand('insertText', false, text);
                        }
                    }""", caption)
                    time.sleep(1)

                time.sleep(1)
                self._dismiss_modals(page)

                # 5. Selection du lieu (BCHEF Bourges)
                if location_query:
                    try:
                        page.evaluate("""() => {
                            document.querySelectorAll("#react-joyride-portal, .react-joyride__overlay").forEach(e => e.remove());
                        }""")
                        loc_input = page.locator('input.Select__searchInput, input[placeholder*="Search locations" i], input[placeholder*="location" i]').first
                        if loc_input.count() > 0:
                            loc_input.click(force=True)
                            time.sleep(0.5)
                            page.keyboard.type(location_query, delay=70)
                            time.sleep(2)

                            # Selection dans la liste deroulante
                            candidates = page.locator('.Select__menu div, div[role="option"], div[class*="option"]').all()
                            matched_target = None
                            for cand in candidates:
                                txt = cand.inner_text().strip().lower()
                                if "bourges" in txt or "bchef" in txt:
                                    matched_target = cand
                                    break

                            if matched_target:
                                matched_target.click(force=True)
                                print(f"Lieu TikTok applique : {matched_target.inner_text().strip().replace(chr(10), ' ')}")
                            elif candidates:
                                candidates[0].click(force=True)
                                print("Premier lieu suggere applique")
                    except Exception as e_loc:
                        print(f"Lieu TikTok non applique : {e_loc}")

                time.sleep(2)
                self._dismiss_modals(page)

                # 6. Defilement vers le bas et detection du bouton Post certifie
                page.evaluate("""() => {
                    window.scrollTo(0, 10000);
                    document.querySelectorAll("div").forEach(d => {
                        if (d.scrollHeight > 1000) d.scrollTop = 10000;
                    });
                }""")
                time.sleep(2)
                self._dismiss_modals(page)

                publish_btn = None
                for _ in range(10):
                    candidate = page.locator(
                        'button[data-e2e="post_video_button"], '
                        'button.Button__root--type-primary:has-text("Post"), '
                        'button.Button__root--type-primary:has-text("Publier")'
                    ).first
                    if candidate.count() > 0 and candidate.is_visible():
                        publish_btn = candidate
                        break
                    time.sleep(1)

                if publish_btn and publish_btn.count() > 0:
                    # Attente que les verifications TikTok se terminent
                    for _ in range(20):
                        self._dismiss_modals(page)
                        if publish_btn.is_enabled():
                            break
                        time.sleep(2)

                    publish_btn.click(force=True, timeout=5000)
                    time.sleep(4)

                    # Gestion des confirmations secondaires
                    for confirm_txt in [
                        "Post now",
                        "Post anyway",
                        "Publier maintenant",
                        "Ignorer et publier",
                        "Continuer la publication",
                        "Continue",
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

                    # Attente de la redirection ou confirmation de succes
                    is_published = False
                    for _ in range(20):
                        time.sleep(2)
                        cur_url = page.url
                        if "content" in cur_url or "manage" in cur_url:
                            is_published = True
                            break
                        if page.locator('*:has-text("Manage your posts"), *:has-text("Your video has been published"), *:has-text("Upload another video")').count() > 0:
                            is_published = True
                            break

                    screenshot_path = DATA_DIR / "tiktok_last_success.png"
                    try:
                        page.screenshot(path=str(screenshot_path))
                    except Exception:
                        pass

                    browser.close()
                    if is_published:
                        return {
                            "platform": "tiktok",
                            "type": "video",
                            "status": "published",
                            "file": str(video_path),
                            "caption": caption,
                            "location": location_query,
                        }
                    else:
                        return {
                            "platform": "tiktok",
                            "type": "video",
                            "status": "error",
                            "error": "La publication TikTok n'a pas confirme la redirection vers la liste des contenus.",
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


if __name__ == "__main__":
    from src.scheduler import get_today_preview, save_today_preview
    from src.config import PROCESSED_VIDEOS_DIR

    preview = get_today_preview()
    if not preview or not preview.get("processed_video"):
        print("Aucun apercu trouve dans today_preview.json")
        exit(1)

    vid_path = PROCESSED_VIDEOS_DIR / preview["processed_video"]
    if not vid_path.exists():
        print(f"Video introuvable : {vid_path}")
        exit(1)

    caption_line = preview.get("description", "Rejoignez-nous chez BCHEF Bourges !")
    hashtags = preview.get("hashtags", ["#bchef", "#bourges", "#burger"])
    full_caption = f"{caption_line}\n\n{' '.join(hashtags)}"

    print(f"Publication TikTok pour : {vid_path.name}")
    print(f"Legende : {full_caption}")

    res = publish_single_tiktok(
        video_path=vid_path,
        caption=full_caption,
        target_profile="official",
        simulation=False,
        location_query="BCHEF Bourges",
    )
    print("Resultat TikTok :", json.dumps(res, indent=2, ensure_ascii=False))

    if res.get("status") == "published":
        pubs = [p for p in preview.get("publications", []) if p.get("platform") != "tiktok"]
        pubs.append(res)
        preview["publications"] = pubs
        save_today_preview(preview)
        print("today_preview.json mis a jour avec succes.")


