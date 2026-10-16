import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from montage_auto.config import FONTS_DIR, MUSIC_DIR, TEMP_DIR


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp h:mm:ss.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def chunk_transcription_items(transcription: list[dict], max_words: int = 3) -> list[dict]:
    """
    Splits sentence cues into short dynamic chunks of 2-3 words
    with proportional timestamps, creating punchy viral TikTok/Reels subtitles.
    """
    chunked = []
    for item in transcription:
        raw_text = str(item.get("text", "")).replace("\\", "").replace("\n", " ").strip()
        if not raw_text:
            continue

        st = float(item.get("start", 0.0))
        et = float(item.get("end", st + 1.2))
        total_dur = max(et - st, 0.4)

        words = raw_text.split()
        if len(words) <= max_words:
            chunked.append({
                "start": st,
                "end": et,
                "text": raw_text.upper()
            })
            continue

        # Split words into groups of max_words
        groups = []
        curr = []
        for w in words:
            curr.append(w)
            if len(curr) >= max_words:
                groups.append(" ".join(curr))
                curr = []
        if curr:
            groups.append(" ".join(curr))

        # Distribute time proportionally according to group character lengths
        total_chars = max(sum(len(g) for g in groups), 1)
        curr_time = st
        for i, g in enumerate(groups):
            dur_g = total_dur * (len(g) / total_chars)
            # Ensure minimum display time of 0.35s
            dur_g = max(dur_g, 0.35)
            end_g = curr_time + dur_g
            if i == len(groups) - 1:
                end_g = max(end_g, et)
            chunked.append({
                "start": round(curr_time, 2),
                "end": round(end_g, 2),
                "text": g.upper()
            })
            curr_time = end_g

    return chunked


def generate_ass_subtitles(
    transcription: list[dict],
    hook: str,
    output_ass_path: Path,
    burn_hook: bool = False,
    hook_duration: float = 4.5,
) -> Path:
    """
    Generates a professional ASS subtitle file:
    - Layer 1: Optional viral hook banner at top (only if burn_hook is True)
    - Layer 0: Dynamic short-chunk subtitles in BCHEF R41 Etoile with smooth pop-in animation
    """
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,R41 Etoile,62,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,5,1.5,2,70,70,330,1
Style: HookTop,Heavitas Neue,54,&H00FFFFFF,&H000000FF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,6,2,8,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Add top hook banner ONLY if burn_hook is explicitly enabled
    if burn_hook and hook:
        hook_clean = hook.replace("\\", "").replace("\n", " ").strip()
        hook_end = format_ass_time(hook_duration)
        ass_content += f"Dialogue: 1,0:00:00.00,{hook_end},HookTop,,0,0,0,,{hook_clean}\n"

    # Chunk long sequences into 2-3 words per cue
    dynamic_cues = chunk_transcription_items(transcription, max_words=3)

    # Add subtitle cues with subtle pop-in animation
    for item in dynamic_cues:
        st = float(item.get("start", 0.0))
        et = float(item.get("end", st + 0.8))
        txt = str(item.get("text", "")).strip()
        if txt:
            st_str = format_ass_time(st)
            et_str = format_ass_time(et)
            # Pop-in scale bounce: expands slightly then settles to normal size in 140ms
            animated_txt = f"{{\\t(0,70,\\fscx108\\fscy108)\\t(70,140,\\fscx100\\fscy100)}}{txt}"
            ass_content += f"Dialogue: 0,{st_str},{et_str},Subtitle,,0,0,0,,{animated_txt}\n"

    output_ass_path.write_text(ass_content, encoding="utf-8")
    return output_ass_path


def select_music_file(style: str) -> Path | None:
    """Finds best matching audio track for requested mood."""
    if not style or style.lower() in ("none", "aucun", "sans"):
        return None

    style = style.lower().strip()
    music_map = {
        "lofi": "friday.mp3",
        "upbeat": "monday.mp3",
        "comedy": "saturday.mp3",
        "tension": "sunday.mp3",
        "modern": "wednesday.mp3",
        "chill": "thursday.mp3",
        "pop": "tuesday.mp3",
    }
    filename = music_map.get(style, "friday.mp3")
    target = MUSIC_DIR / filename
    if target.exists():
        return target

    # Fallback to any mp3
    available = list(MUSIC_DIR.glob("*.mp3"))
    return available[0] if available else None


def cut_and_normalize_segment(
    source_file: Path,
    start_sec: float,
    duration_sec: float,
    output_segment_path: Path,
) -> None:
    """
    Cuts a segment from source video and normalizes video dimensions to 1080x1920 @ 30fps.
    """
    vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", str(source_file),
        "-t", str(duration_sec),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "21",
        "-c:a", "aac",
        "-ar", "48000",
        "-ac", "2",
        "-b:a", "192k",
        str(output_segment_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Erreur découpage segment {source_file.name}: {res.stderr}")


def render_montage(
    plan: dict,
    source_video_paths: list[Path],
    output_path: Path,
    progress_callback=None,
) -> dict:
    """
    Executes the full editing rendering pipeline:
    1. Cut & normalize segments
    2. Concat segments
    3. Generate styled ASS subtitles + hook banner
    4. Apply color grading (étalonnage)
    5. Mix audio (speech loudnorm + ducked music or full music)
    6. Mux final 1080x1920 video
    """
    job_id = uuid.uuid4().hex[:8]
    scratch_dir = TEMP_DIR / f"job_{job_id}"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        segments = plan.get("segments", [])
        if not segments:
            raise ValueError("Aucun segment spécifié dans le plan de montage.")

        if progress_callback:
            progress_callback(10, "Découpage précis des séquences sélectionnées...")

        # Step 1: Cut all segments
        segment_files = []
        for i, seg in enumerate(segments):
            f_idx = seg.get("file_index", 0)
            if f_idx >= len(source_video_paths):
                f_idx = 0
            src = source_video_paths[f_idx]
            st = float(seg.get("start", 0.0))
            dur = max(1.0, float(seg.get("end", st + 5.0)) - st)

            seg_out = scratch_dir / f"seg_{i:02d}.mp4"
            print(f"Découpe segment {i+1}/{len(segments)} : {src.name} [{st}s -> +{dur}s]")
            cut_and_normalize_segment(src, st, dur, seg_out)
            segment_files.append(seg_out)

        if progress_callback:
            progress_callback(35, "Assemblage des séquences...")

        # Step 2: Concat segments
        concat_out = scratch_dir / "assembled.mp4"
        if len(segment_files) == 1:
            concat_out = segment_files[0]
        else:
            list_txt = scratch_dir / "concat_list.txt"
            with open(list_txt, "w", encoding="utf-8") as f:
                for sf in segment_files:
                    f.write(f"file '{sf.resolve()}'\n")

            cmd_concat = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_txt),
                "-c", "copy",
                str(concat_out),
            ]
            res_c = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res_c.returncode != 0:
                raise RuntimeError(f"Erreur assemblage vidéo : {res_c.stderr}")

        if progress_callback:
            progress_callback(50, "Génération des sous-titres et étalonnage des couleurs...")

        # Step 3: Subtitles & Hook
        ass_path = scratch_dir / "subtitles.ass"
        hook_text = plan.get("hook", "")
        burn_hook = bool(plan.get("burn_hook", False))
        generate_ass_subtitles(
            transcription=plan.get("transcription", []),
            hook=hook_text,
            output_ass_path=ass_path,
            burn_hook=burn_hook,
            hook_duration=4.5,
        )

        # Step 4: Color Grading filter graph
        # eq: contrast, brightness, saturation + unsharp
        color_filter = "eq=contrast=1.06:brightness=0.02:saturation=1.18,unsharp=5:5:0.7:5:5:0.3"
        subtitles_filter = f"ass={ass_path.resolve()}:fontsdir={FONTS_DIR.resolve()}"
        video_filters = f"{color_filter},{subtitles_filter}"

        if progress_callback:
            progress_callback(70, "Traitement sonore et habillage musical...")

        # Step 5: Audio configuration
        mix_voix = plan.get("mix_voix", True)
        music_style = plan.get("musique_style", "lofi")
        music_path = select_music_file(music_style)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if music_path and music_path.exists():
            if mix_voix:
                # Keep speech with loudnorm and add soft ducked background music
                filter_complex = (
                    f"[0:v]{video_filters}[outv];"
                    f"[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a_norm];"
                    f"[1:a]volume=0.18[a_bg];"
                    f"[a_norm][a_bg]amix=inputs=2:duration=first:dropout_transition=2[outa]"
                )
                cmd_render = [
                    "ffmpeg", "-y",
                    "-i", str(concat_out),
                    "-stream_loop", "-1",
                    "-i", str(music_path),
                    "-filter_complex", filter_complex,
                    "-map", "[outv]",
                    "-map", "[outa]",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(output_path),
                ]
            else:
                # Replace kitchen noise with full background music
                filter_complex = f"[0:v]{video_filters}[outv];[1:a]volume=0.85[outa]"
                cmd_render = [
                    "ffmpeg", "-y",
                    "-i", str(concat_out),
                    "-stream_loop", "-1",
                    "-i", str(music_path),
                    "-filter_complex", filter_complex,
                    "-map", "[outv]",
                    "-map", "[outa]",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(output_path),
                ]
        else:
            # Voice only / no background track
            cmd_render = [
                "ffmpeg", "-y",
                "-i", str(concat_out),
                "-vf", video_filters,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path),
            ]

        print(f"Rendu final en cours vers {output_path.name}...")
        res_render = subprocess.run(cmd_render, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res_render.returncode != 0:
            raise RuntimeError(f"Erreur rendu final FFmpeg : {res_render.stderr}")

        if progress_callback:
            progress_callback(100, "Montage termine avec succes !")

        return {
            "success": True,
            "output_path": str(output_path),
            "filename": output_path.name,
            "hook": plan.get("hook", ""),
            "description": plan.get("description", ""),
            "hashtags": plan.get("hashtags", []),
            "total_duration": plan.get("total_duration", 0.0),
        }

    finally:
        # Clean temporary segment files
        try:
            for f in scratch_dir.iterdir():
                f.unlink(missing_ok=True)
            scratch_dir.rmdir()
        except Exception:
            pass
