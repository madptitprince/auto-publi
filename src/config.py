import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Directories
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_STORIES_DIR = UPLOADS_DIR / "stories"
UPLOADS_VIDEOS_DIR = UPLOADS_DIR / "videos"

PROCESSED_DIR = BASE_DIR / "processed"
PROCESSED_STORIES_DIR = PROCESSED_DIR / "stories"
PROCESSED_VIDEOS_DIR = PROCESSED_DIR / "videos"
ARCHIVE_VIDEOS_DIR = PROCESSED_DIR / "archive"

DATA_DIR = BASE_DIR / "data"
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
TODAY_PREVIEW_FILE = DATA_DIR / "today_preview.json"
INSTAGRAM_SESSION_FILE = DATA_DIR / "instagram_session.json"
TIKTOK_COOKIES_FILE = DATA_DIR / "tiktok_cookies.json"

FONTS_DIR = BASE_DIR / "assets" / "fonts"
LOGOS_DIR = BASE_DIR / "assets" / "logos"
BCHEF_LOGO_PATH = LOGOS_DIR / "BCHEF-ORANGE.png"
FOX_LOGO_PATH = LOGOS_DIR / "RENARD-BASELINE-ORANGE 2.png"

HEAVITAS_FONT_PATH = FONTS_DIR / "HeavitasNeue-Black.otf"
ARTELY_FONT_PATH = FONTS_DIR / "ArtelyInks.otf"
ETOILE_FONT_PATH = FONTS_DIR / "R41Etoile-Regular.otf"
MONTSERRAT_BOLD_PATH = FONTS_DIR / "Montserrat-Bold.ttf"
MONTSERRAT_EXTRABOLD_PATH = FONTS_DIR / "Montserrat-ExtraBold.ttf"

# Official BCHEF Brand Color (#d54a15)
BRAND_ORANGE = "#d54a15"
BRAND_ORANGE_RGB = (213, 74, 21)

# Default Headline and Story Font: prioritize official BCHEF Heavitas Neue
if HEAVITAS_FONT_PATH.exists():
    DEFAULT_FONT = str(HEAVITAS_FONT_PATH)
elif MONTSERRAT_EXTRABOLD_PATH.exists():
    DEFAULT_FONT = str(MONTSERRAT_EXTRABOLD_PATH)
else:
    DEFAULT_FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

# Ensure runtime directories exist
for directory in [
    UPLOADS_STORIES_DIR,
    UPLOADS_VIDEOS_DIR,
    PROCESSED_STORIES_DIR,
    PROCESSED_VIDEOS_DIR,
    ARCHIVE_VIDEOS_DIR,
    DATA_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)

# Default Opening Hours
DEFAULT_OPENING_HOURS = {
    "Monday": "11h00 - 22h45",
    "Tuesday": "11h00 - 22h45",
    "Wednesday": "11h00 - 22h45",
    "Thursday": "11h00 - 22h45",
    "Friday": "11h00 - 23h30",
    "Saturday": "11h00 - 23h30",
    "Sunday": "11h00 - 22h00",
}

DAYS_FR = {
    "Monday": "Lundi",
    "Tuesday": "Mardi",
    "Wednesday": "Mercredi",
    "Thursday": "Jeudi",
    "Friday": "Vendredi",
    "Saturday": "Samedi",
    "Sunday": "Dimanche",
}

DAYS_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Brand Colors (BCHEF)
COLOR_ORANGE = (227, 82, 5)       # #e35205
COLOR_DARK = (40, 40, 40)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (80, 80, 80)

# Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def get_opening_hours() -> dict[str, str]:
    """Retrieve opening hours from settings.json or defaults."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("opening_hours", DEFAULT_OPENING_HOURS)
        except Exception:
            pass
    return DEFAULT_OPENING_HOURS.copy()


def save_opening_hours(hours_dict: dict[str, str]):
    """Persist opening hours to settings.json."""
    data = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["opening_hours"] = hours_dict
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


DEFAULT_PROFILES = {
    "test": {
        "name": "Mode Test (Compte bac a sable)",
        "instagram_username": "test_publi00",
        "instagram_password": "",
        "instagram_session_file": "instagram_session.json",
        "tiktok_cookies_file": "tiktok_cookies.json",
    },
    "official": {
        "name": "Mode Officiel (BCHEF Bourges)",
        "instagram_username": "bchef_bourges",
        "instagram_password": "",
        "instagram_session_file": "instagram_session_official.json",
        "tiktok_cookies_file": "tiktok_cookies_official.json",
    },
}


def get_social_settings() -> dict:
    """Retrieves publication profiles and active target (test or official)."""
    data = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    active_profile = data.get("active_profile", "test")
    if active_profile not in ("test", "official"):
        active_profile = "test"

    saved_profiles = data.get("profiles", {})
    profiles = {}
    for key, defaults in DEFAULT_PROFILES.items():
        p = defaults.copy()
        if key in saved_profiles:
            p.update({k: v for k, v in saved_profiles[key].items() if v is not None})
        profiles[key] = p

    if not profiles["test"].get("instagram_password"):
        profiles["test"]["instagram_password"] = os.getenv("INSTAGRAM_PASSWORD", "mad1234")
    if not profiles["test"].get("instagram_username"):
        profiles["test"]["instagram_username"] = os.getenv("INSTAGRAM_USERNAME", "test_publi00")

    if not profiles["official"].get("instagram_password"):
        env_official_pass = os.getenv("OFFICIAL_INSTAGRAM_PASSWORD", "")
        if env_official_pass:
            profiles["official"]["instagram_password"] = env_official_pass
    if not profiles["official"].get("instagram_username"):
        profiles["official"]["instagram_username"] = os.getenv("OFFICIAL_INSTAGRAM_USERNAME", "bchef_bourges")

    return {
        "active_profile": active_profile,
        "profiles": profiles,
    }


def save_social_settings(active_profile: str, profiles_dict: dict | None = None):
    """Saves active target profile and optional credential updates."""
    data = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    if active_profile in ("test", "official"):
        data["active_profile"] = active_profile

    if profiles_dict:
        if "profiles" not in data:
            data["profiles"] = {}
        for p_key, p_vals in profiles_dict.items():
            if p_key not in data["profiles"]:
                data["profiles"][p_key] = {}
            for k, v in p_vals.items():
                if v is not None and v != "":
                    data["profiles"][p_key][k] = v

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_publication_frequency() -> int:
    """Retrieve number of posts per day (1, 2, 3, or 4). Defaults to 1."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                val = int(data.get("posts_per_day", 1))
                if val in (1, 2, 3, 4):
                    return val
        except Exception:
            pass
    return 1


def save_publication_frequency(posts_per_day: int):
    """Save number of posts per day (1, 2, 3, or 4)."""
    if posts_per_day not in (1, 2, 3, 4):
        posts_per_day = 1
    data = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["posts_per_day"] = posts_per_day
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

