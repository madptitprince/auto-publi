import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

PORT = int(os.getenv("MONTAGE_PORT", "8001"))
HOST = os.getenv("MONTAGE_HOST", "0.0.0.0")

RUSHS_DIR = BASE_DIR / "rushs"
OUTPUTS_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"
TEMP_DIR = BASE_DIR / "scratch"
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR = ASSETS_DIR / "sfx"
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

UPLOADS_VIDEOS_DIR = PROJECT_ROOT / "uploads" / "videos"

HISTORY_FILE = DATA_DIR / "history.json"

for d in [RUSHS_DIR, OUTPUTS_DIR, DATA_DIR, TEMP_DIR, ASSETS_DIR, MUSIC_DIR, SFX_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not HISTORY_FILE.exists():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        f.write("[]")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
