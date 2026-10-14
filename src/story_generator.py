import random
import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from src.config import (
    UPLOADS_STORIES_DIR,
    PROCESSED_STORIES_DIR,
    DEFAULT_FONT,
    DAYS_FR,
    get_opening_hours,
)


def get_today_hours(target_date: datetime.date | None = None) -> tuple[str, str]:
    """Returns (day_name_fr, hours_str) for given date (defaults to today)."""
    if target_date is None:
        target_date = datetime.date.today()
    day_en = target_date.strftime("%A")
    day_fr = DAYS_FR.get(day_en, day_en)
    hours_map = get_opening_hours()
    hours = hours_map.get(day_en, "11h00 - 22h45")
    return day_fr, hours


def list_story_templates() -> list[Path]:
    """List all available story template photos in uploads/stories."""
    valid_exts = {".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"}
    return [
        p for p in UPLOADS_STORIES_DIR.iterdir()
        if p.is_file() and p.suffix in valid_exts and not p.name.startswith(".")
    ]


def generate_daily_story(
    source_image: Path | None = None,
    target_date: datetime.date | None = None,
    custom_hours: str | None = None,
    output_filename: str | None = None,
) -> dict:
    """
    Selects a story photo and overlays today's opening hours simply in bold white
    directly under the word 'ouvert !', without a box, formatted e.g. (11H00 - 22H30).
    """
    templates = list_story_templates()
    if not templates:
        raise FileNotFoundError(
            f"Aucune photo trouvée dans le dossier {UPLOADS_STORIES_DIR}."
        )

    if source_image is None or not source_image.exists():
        source_image = random.choice(templates)

    day_fr, hours = get_today_hours(target_date)
    if custom_hours:
        hours = custom_hours

    # Format uppercase with H, without parentheses e.g. 11H00 - 22H45
    formatted_hours = hours.upper().replace("(", "").replace(")", "").strip()
    hours_text = formatted_hours

    base_img = Image.open(source_image).convert("RGBA")
    width, height = base_img.size

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Scale according to reference width 1080 - punchy bold font
    scale = width / 1080.0
    font_size = int(54 * scale)
    font_hours = ImageFont.truetype(DEFAULT_FONT, font_size)

    bbox = draw.textbbox((0, 0), hours_text, font=font_hours)
    tw = bbox[2] - bbox[0]

    # Center horizontally, position directly under "ouvert !" (descended slightly to y=1115 on 1080x1920)
    x = (width - tw) // 2
    y = int(1115 * (height / 1920.0))

    # Text shadow outline for 100% legibility on any burger photo
    shadow_color = (0, 0, 0, 200)
    offsets = [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4), (4, 0), (0, -4), (-4, 0)]
    for ox, oy in offsets:
        draw.text(
            (x + int(ox * scale), y + int(oy * scale)),
            hours_text,
            font=font_hours,
            fill=shadow_color,
            stroke_width=int(2 * scale),
            stroke_fill=shadow_color,
        )

    # Pure extra bold white text
    draw.text(
        (x, y),
        hours_text,
        font=font_hours,
        fill=(255, 255, 255, 255),
        stroke_width=int(2 * scale),
        stroke_fill=(255, 255, 255, 255),
    )

    final_img = Image.alpha_composite(base_img, overlay).convert("RGB")

    if not output_filename:
        date_str = (target_date or datetime.date.today()).strftime("%Y-%m-%d")
        output_filename = f"story_{date_str}.png"

    output_path = PROCESSED_STORIES_DIR / output_filename
    final_img.save(output_path, "PNG", quality=95)

    return {
        "status": "success",
        "output_path": str(output_path),
        "source_image": str(source_image.name),
        "day": day_fr,
        "hours": hours_text,
        "date": (target_date or datetime.date.today()).isoformat(),
    }


if __name__ == "__main__":
    result = generate_daily_story()
    print("Story generee avec succes :", result)
