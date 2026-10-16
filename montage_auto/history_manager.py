import json
import uuid
from datetime import datetime
from pathlib import Path
from montage_auto.config import HISTORY_FILE, OUTPUTS_DIR


def get_all_history() -> list[dict]:
    """Retrieve all montages from history file."""
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def add_history_entry(entry: dict) -> dict:
    """Adds a new montage record to the history file."""
    history = get_all_history()
    if "id" not in entry:
        entry["id"] = uuid.uuid4().hex[:10]
    if "created_at" not in entry:
        entry["created_at"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # Prepend to display newest first
    history.insert(0, entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    return entry


def delete_history_entry(entry_id: str) -> bool:
    """Deletes a montage record and its video file."""
    history = get_all_history()
    new_history = []
    found = False
    for item in history:
        if item.get("id") == entry_id:
            found = True
            # delete file if present
            fname = item.get("filename")
            if fname:
                target_file = OUTPUTS_DIR / fname
                target_file.unlink(missing_ok=True)
        else:
            new_history.append(item)
    if found:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(new_history, f, indent=2, ensure_ascii=False)
    return found
