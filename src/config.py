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
