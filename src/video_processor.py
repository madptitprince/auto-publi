import os
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from src.config import (
    PROCESSED_VIDEOS_DIR,
    DEFAULT_FONT,
    BASE_DIR,
)


def get_hook_font(font_size: int) -> ImageFont.FreeTypeFont:
    """
    Selects the best available font for the hook badge:
    1. HeavitasNeue-Black.otf (Official BCHEF Headline font - ultra punchy bold)
    2. Montserrat-ExtraBold.ttf (modern, bold geometric sans-serif)
    3. Montserrat-Bold.ttf
    4. DEFAULT_FONT fallback
    """
    fonts_dir = BASE_DIR / "assets" / "fonts"
    if fonts_dir.exists():
        # 1. Official BCHEF Headline Font: Heavitas Neue Black
        for target in ["HeavitasNeue-Black.otf", "HeavitasNeue-Black.ttf", "HeavitasNeue.otf"]:
            fp = fonts_dir / target
            if fp.exists():
                try:
                    return ImageFont.truetype(str(fp), font_size)
                except Exception:
                    pass

        # 2. Case-insensitive search for heavitas
        for f in sorted(fonts_dir.iterdir()):
            if "heavitas" in f.name.lower() and f.suffix.lower() in {".ttf", ".otf"}:
                try:
                    return ImageFont.truetype(str(f), font_size)
                except Exception:
                    pass

        # 3. High-impact geometric sans-serif fallback
        for fallback in ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf"]:
            fp = fonts_dir / fallback
            if fp.exists():
                try:
                    return ImageFont.truetype(str(fp), font_size)
                except Exception:
                    pass
    return ImageFont.truetype(DEFAULT_FONT, font_size)


def create_hook_badge(
    text: str,
    output_path: Path,
    video_width: int = 1440,
    video_height: int = 2560,
    font_size: int = 46,
) -> Path:
    """
    Creates a clean, high-contrast white card hook badge.
    Modern TikTok / Reels aesthetic: white card, dark bold typography, clean drop shadow.
    """
    text = text.upper().strip()
    scale = video_width / 1080.0
    actual_font_size = int(font_size * scale)
    font = get_hook_font(actual_font_size)

    # Word wrap
    max_text_width = int(video_width * 0.78)
    words = text.split()
    lines = []
    current_line = []

    dummy_img = Image.new("RGBA", (10, 10))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = dummy_draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_text_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]
    if current_line:
        lines.append(" ".join(current_line))

    line_height = int(actual_font_size * 1.38)
    padding_x = int(48 * scale)
    padding_y = int(30 * scale)

    max_line_w = 0
    for line in lines:
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        max_line_w = max(max_line_w, bbox[2] - bbox[0])

    badge_w = max_line_w + (padding_x * 2)
    badge_h = (len(lines) * line_height) + (padding_y * 2)

    badge = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)

    # Soft subtle drop shadow
    shadow_offset = int(4 * scale)
    draw.rounded_rectangle(
        [shadow_offset, shadow_offset, badge_w - 2, badge_h - 2],
        radius=int(20 * scale),
        fill=(0, 0, 0, 75),
    )

    # Clean white background card with refined border
    draw.rounded_rectangle(
        [0, 0, badge_w - shadow_offset - 2, badge_h - shadow_offset - 2],
        radius=int(20 * scale),
        fill=(255, 255, 255, 252),
        outline=(230, 232, 240),
        width=int(2 * scale),
    )

    # Crisp dark text (almost black for maximum contrast and readability)
    for i, line in enumerate(lines):
        bbox = dummy_draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        lx = (badge_w - shadow_offset - 2 - lw) // 2
        ly = padding_y - int(3 * scale) + (i * line_height)
        draw.text((lx, ly), line, font=font, fill=(15, 17, 23, 255))

    badge.save(output_path, "PNG")
    return output_path


def get_video_dimensions(video_path: Path) -> tuple[int, int]:
    """Retrieve video resolution (width, height) using ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams and "width" in streams[0] and "height" in streams[0]:
            return int(streams[0]["width"]), int(streams[0]["height"])
    except Exception as e:
        print(f"Erreur lecture dimensions video {video_path}: {e}")
    return 1080, 1920


def process_video_with_hook(
    input_video: Path,
    hook_text: str,
    output_filename: str | None = None,
    hook_duration: int | None = None,
    y_ratio: float = 0.13,
) -> dict:
    """
    Overlays a clean white hook badge on top of the video (until the end by default).
    Outputs an Instagram Reel & TikTok compliant MP4.
    """
    if not input_video.exists():
        raise FileNotFoundError(f"Video introuvable: {input_video}")

    hook_text = hook_text.upper().strip()
    width, height = get_video_dimensions(input_video)

    badge_path = Path("/tmp") / f"badge_{input_video.stem}.png"
    create_hook_badge(hook_text, badge_path, width, height)

    if not output_filename:
        output_filename = f"processed_{input_video.stem}.mp4"

    output_path = PROCESSED_VIDEOS_DIR / output_filename

    # FFmpeg command: overlay badge at y = height * y_ratio
    # If hook_duration is specified, show for that duration; otherwise stay until the end of video
    if hook_duration is not None and hook_duration > 0:
        filter_expr = (
            f"[0:v][1:v]overlay=(W-w)/2:H*{y_ratio}:enable='between(t,0,{hook_duration})'[outv]"
        )
    else:
        filter_expr = (
            f"[0:v][1:v]overlay=(W-w)/2:H*{y_ratio}[outv]"
        )

    cmd = [
        "ffmpeg", "-loglevel", "error", "-y",
        "-i", str(input_video),
        "-i", str(badge_path),
        "-filter_complex", filter_expr,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "faster",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    subprocess.run(cmd, check=True)

    if badge_path.exists():
        badge_path.unlink()

    # Generate a cover thumbnail at 1 second
    cover_path = PROCESSED_VIDEOS_DIR / f"{output_path.stem}_cover.jpg"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y",
        "-ss", "00:00:01",
        "-i", str(output_path),
        "-vframes", "1",
        "-q:v", "2",
        str(cover_path)
    ], check=True)

    return {
        "status": "success",
        "input_video": str(input_video.name),
        "output_video": str(output_path),
        "cover_image": str(cover_path),
        "hook_text": hook_text,
        "duration": hook_duration,
        "width": width,
        "height": height,
    }
