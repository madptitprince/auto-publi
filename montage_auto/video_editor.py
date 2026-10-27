import os
import json
import re
import time
import subprocess
import tempfile
import uuid
from pathlib import Path
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from montage_auto.config import GEMINI_API_KEY, FONTS_DIR, MUSIC_DIR, SFX_DIR, TEMP_DIR


class WordTiming(BaseModel):
    word: str = Field(description="Mot individuel prononce en majuscules sans emoji")
    start: float = Field(description="Horodatage exact de debut du mot en secondes")
    end: float = Field(description="Horodatage exact de fin du mot en secondes")


class PhraseBlock(BaseModel):
    phrase: str = Field(description="Phrase courte ou groupe de 2 a 4 mots en majuscules")
    start: float = Field(description="Horodatage exact de debut de la phrase en secondes")
    end: float = Field(description="Horodatage exact de fin de la phrase en secondes")
    words: list[WordTiming] = Field(description="Liste temporelle precise de chaque mot du groupe")


class AudioTranscriptionWords(BaseModel):
    has_speech: bool = Field(description="True si des voix humaines sont audibles, False sinon")
    cues: list[PhraseBlock] = Field(description="Groupes de mots chronologiques synchronises")


# Backward compatibility aliases
SubtitleCueItem = PhraseBlock
AlignedAudioTranscription = AudioTranscriptionWords


def get_video_duration(path: Path) -> float:
    """Uses ffprobe to obtain video duration in seconds."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return round(float(res.stdout.strip()), 2)
    except Exception:
        pass
    return 25.0


def align_subtitles_to_audio(
    audio_path: Path,
    api_key: str | None = None,
    target_duration: float = 25.0,
) -> list[dict]:
    """
    Direct multimodal audio speech-to-text alignment with word-level surgical precision.
    Transcribes the exact assembled audio track with word-by-word timestamps
    perfectly synced to the tempo of spoken dialogue for viral dynamic highlighting.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        print("[Subtitles] Aucune clef Gemini configuree pour l'alignement audio.")
        return []

    try:
        client = genai.Client(api_key=active_key)
        f_ref = client.files.upload(file=str(audio_path))

        waited = 0
        while f_ref.state.name == "PROCESSING" and waited < 30:
            time.sleep(1)
            waited += 1
            f_ref = client.files.get(name=f_ref.name)

        prompt = (
            "Tu es un monteur professionnel expert en synchronisation audio pour sous-titres viraux (TikTok / Reels).\n"
            f"Cet extrait audio final dure {round(target_duration, 1)} secondes.\n"
            "Consignes de synchronisation millimetrique :\n"
            "1. Reperes toutes les paroles et dialogues humains prononces.\n"
            "2. Decoupe la parole en phrases tres courtes de 2 a 4 mots maximum par bloc visuel.\n"
            "3. Pour CHAQUE phrase, donne son horodatage start et end exacts en secondes.\n"
            "4. Pour CHAQUE MOT de la phrase, donne son horodatage start et end ultra-precis en secondes au moment exact ou la voix le prononce.\n"
            "5. Ne genere aucun sous-titre pendant les silences, bruits de fond ou moments sans parole.\n"
            "6. Format strict en francais, majuscules, sans emoji."
        )

        candidate_models = [
            "gemini-3-flash-preview",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
        ]

        for model_name in candidate_models:
            raw_cues = None
            for attempt in range(2):
                try:
                    print(f"[Subtitles] Alignement audio mot-a-mot avec {model_name} (tentative {attempt+1})...")
                    res = client.models.generate_content(
                        model=model_name,
                        contents=[f_ref, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=AudioTranscriptionWords,
                        ),
                    )
                    data = json.loads(res.text)
                    if not data.get("has_speech", True) or not data.get("cues"):
                        print("[Subtitles] Aucune voix humaine detectee dans le montage.")
                        return []

                    raw_cues = data.get("cues", [])
                    print(f"[Subtitles] {len(raw_cues)} phrases synchronisees avec succes via {model_name} !")
                    break
                except Exception as e:
                    print(f"[Subtitles] Echec avec {model_name} (tentative {attempt+1}) : {e}")
                    if attempt == 0:
                        time.sleep(1.5)

            if not raw_cues:
                continue

            # Process phrases and words
            processed_phrases = []
            for c in raw_cues:
                raw_phrase = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", str(c.get("phrase", ""))).strip().upper()
                raw_words = c.get("words", [])

                clean_words = []
                for w in raw_words:
                    w_txt = re.sub(r"[^\w\s\-\']", "", str(w.get("word", ""))).strip().upper()
                    if not w_txt:
                        continue
                    w_st = round(float(w.get("start", 0.0)), 2)
                    w_et = round(float(w.get("end", w_st + 0.2)), 2)
                    w_et = max(w_et, w_st + 0.10)
                    w_st = min(w_st, target_duration)
                    w_et = min(w_et, target_duration)
                    clean_words.append({
                        "word": w_txt,
                        "start": w_st,
                        "end": w_et,
                    })

                # Fallback if phrase text exists but words list was omitted by model
                if not clean_words and raw_phrase:
                    tokens = raw_phrase.split()
                    p_st = round(float(c.get("start", 0.0)), 2)
                    p_et = round(float(c.get("end", p_st + 1.2)), 2)
                    p_dur = max(p_et - p_st, 0.4)
                    step = p_dur / max(len(tokens), 1)
                    for idx, tok in enumerate(tokens):
                        w_st = round(p_st + idx * step, 2)
                        w_et = round(w_st + step, 2)
                        clean_words.append({
                            "word": tok,
                            "start": w_st,
                            "end": w_et,
                        })

                if not clean_words:
                    continue

                # Sort words
                clean_words.sort(key=lambda x: x["start"])

                # Split long phrases (> 4 words) into chunks of 2 to 3 words
                if len(clean_words) <= 4:
                    chunks = [clean_words]
                else:
                    chunks = []
                    for i in range(0, len(clean_words), 3):
                        chunk_slice = clean_words[i:i + 3]
                        if chunk_slice:
                            chunks.append(chunk_slice)

                for chunk in chunks:
                    p_start = chunk[0]["start"]
                    p_end = chunk[-1]["end"]
                    if p_end > p_start and p_start < target_duration:
                        p_end = max(p_end, p_start + 0.35)
                        p_end = min(p_end, target_duration)
                        phrase_text = " ".join(w["word"] for w in chunk)
                        processed_phrases.append({
                            "phrase": phrase_text,
                            "start": p_start,
                            "end": p_end,
                            "words": chunk,
                        })

            # Sort phrases chronologically
            processed_phrases.sort(key=lambda x: x["start"])

            # Prevent phrase overlaps
            for i in range(len(processed_phrases) - 1):
                if processed_phrases[i]["end"] > processed_phrases[i + 1]["start"]:
                    processed_phrases[i]["end"] = max(
                        processed_phrases[i]["start"] + 0.25,
                        processed_phrases[i + 1]["start"] - 0.02
                    )
                    if processed_phrases[i]["words"]:
                        processed_phrases[i]["words"][-1]["end"] = min(
                            processed_phrases[i]["words"][-1]["end"],
                            processed_phrases[i]["end"]
                        )

            return processed_phrases

    except Exception as err:
        print(f"[Subtitles] Erreur globale alignement audio : {err}")

    return []


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp h:mm:ss.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_subtitles(
    transcription: list[dict],
    hook: str,
    output_ass_path: Path,
    burn_hook: bool = False,
    hook_duration: float = 4.5,
    font_name: str = "R41 Etoile",
    highlight_color: str = "&H0000E6FF&",
) -> Path:
    """
    Generates a professional ASS subtitle file:
    - Layer 1: Optional viral hook banner at top (only if burn_hook is True)
    - Layer 0: High-fluidity word-by-word active tracking subtitles in BCHEF branding.
      The full phrase stays 100% stable on screen while the currently spoken word
      lights up in vibrant BCHEF yellow without any jitter or pixel displacement.
    """
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Subtitle,{font_name},66,&H00FFFFFF,{highlight_color},&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,330,1
Style: HookTop,Heavitas Neue,54,&H00FFFFFF,&H000000FF,&H00000000,&HB0000000,-1,0,0,0,100,100,0,0,1,6,2,8,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Add top hook banner ONLY if burn_hook is explicitly enabled
    if burn_hook and hook:
        hook_clean = hook.replace("\\", "").replace("\n", " ").strip()
        hook_end = format_ass_time(hook_duration)
        ass_content += f"Dialogue: 1,0:00:00.00,{hook_end},HookTop,,0,0,0,,{hook_clean}\n"

    for item in transcription:
        # Check if item contains word-level timings
        p_words = item.get("words", [])
        p_start = float(item.get("start", 0.0))
        p_end = float(item.get("end", p_start + 1.2))

        if not p_words:
            # Fallback for legacy cues or cues without word-level breakdowns
            raw_text = str(item.get("phrase", item.get("text", ""))).strip().upper()
            if not raw_text:
                continue
            words_list = raw_text.split()
            # If 1-3 words, show static line
            if len(words_list) <= 3:
                st_str = format_ass_time(p_start)
                et_str = format_ass_time(p_end)
                ass_content += f"Dialogue: 0,{st_str},{et_str},Subtitle,,0,0,0,,{raw_text}\n"
                continue
            # If multiple words, synthesize word timings
            dur = max(p_end - p_start, 0.4)
            w_step = dur / len(words_list)
            p_words = []
            for i, w in enumerate(words_list):
                p_words.append({
                    "word": w,
                    "start": p_start + i * w_step,
                    "end": p_start + (i + 1) * w_step,
                })

        # Ensure chunks are <= 4 words
        if len(p_words) <= 4:
            chunks = [p_words]
        else:
            chunks = [p_words[i:i + 3] for i in range(0, len(p_words), 3)]

        for chunk_words in chunks:
            if not chunk_words:
                continue
            c_start = chunk_words[0]["start"]
            c_end = chunk_words[-1]["end"]
            n_words = len(chunk_words)

            for idx, active_w in enumerate(chunk_words):
                w_st = active_w["start"]
                # Active highlight extends until the start of the next word to prevent black flashes
                if idx < n_words - 1:
                    w_et = chunk_words[idx + 1]["start"]
                else:
                    w_et = c_end

                if w_et <= w_st:
                    w_et = w_st + 0.15

                st_str = format_ass_time(w_st)
                et_str = format_ass_time(w_et)

                # Build line text: active word has highlight color tag, others stay crisp white
                line_parts = []
                for i, w in enumerate(chunk_words):
                    w_txt = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", str(w.get("word", ""))).strip().upper()
                    if not w_txt:
                        continue
                    if i == idx:
                        line_parts.append(f"{{\\c{highlight_color}}}{w_txt}{{\\r\\c&H00FFFFFF&}}")
                    else:
                        line_parts.append(w_txt)

                if line_parts:
                    full_line = " ".join(line_parts)
                    ass_content += f"Dialogue: 0,{st_str},{et_str},Subtitle,,0,0,0,,{full_line}\n"

    output_ass_path.write_text(ass_content, encoding="utf-8")
    return output_ass_path


def get_sfx_path(sfx_name: str) -> Path | None:
    """Returns absolute path to matching SFX audio file."""
    if not sfx_name:
        return None
    clean = sfx_name.lower().strip().replace(" ", "_").replace("-", "_")
    direct = SFX_DIR / f"{clean}.mp3"
    if direct.exists():
        return direct
    if "scratch" in clean:
        return SFX_DIR / "record_scratch.mp3"
    elif any(k in clean for k in ("boom", "punch", "chute", "impact", "bass")):
        return SFX_DIR / "comedy_punch.mp3"
    elif any(k in clean for k in ("whoosh", "trans", "sweep", "cut")):
        return SFX_DIR / "whoosh.mp3"
    elif any(k in clean for k in ("ding", "bell", "chime")):
        return SFX_DIR / "ding.mp3"
    elif any(k in clean for k in ("pop", "bubble", "click")):
        return SFX_DIR / "pop.mp3"
    # Fallback to whoosh
    default_sfx = SFX_DIR / "whoosh.mp3"
    return default_sfx if default_sfx.exists() else None


def select_music_file(style: str) -> Path | None:
    """Finds best matching audio track for requested mood."""
    if not style or style.lower() in ("none", "aucun", "sans"):
        return None

    style = style.lower().strip()
    music_map = {
        "lofi": "lofi.mp3",
        "chill": "lofi.mp3",
        "culinaire": "lofi.mp3",
        "food": "lofi.mp3",
        "comedy": "comedy.mp3",
        "humour": "comedy.mp3",
        "humor": "comedy.mp3",
        "tension": "tension.mp3",
        "drama": "tension.mp3",
        "upbeat": "upbeat.mp3",
        "pop": "upbeat.mp3",
        "trend": "upbeat.mp3",
        "modern": "upbeat.mp3",
    }
    filename = music_map.get(style, "lofi.mp3")
    target = MUSIC_DIR / filename
    if target.exists():
        return target

    # Fallback to comedy or any available mp3
    if (MUSIC_DIR / "comedy.mp3").exists():
        return MUSIC_DIR / "comedy.mp3"
    available = list(MUSIC_DIR.glob("*.mp3"))
    return available[0] if available else None


def cut_and_normalize_segment(
    source_file: Path,
    start_sec: float,
    duration_sec: float,
    output_segment_path: Path,
) -> None:
    """
    Cuts a segment from source video, applies audio micro-fades to eliminate cut clicks/pops,
    and normalizes video dimensions to 1080x1920 @ 30fps with frame-accurate seeking.
    """
    vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"

    # Acoustic micro-fades (15ms) on cut boundaries to ensure seamless transition without pops
    fade_d = min(0.015, max(0.005, duration_sec / 20.0))
    fade_out_st = max(0.0, duration_sec - fade_d)
    af = f"afade=t=in:st=0:d={fade_d},afade=t=out:st={fade_out_st}:d={fade_d}"

    cmd = [
        "ffmpeg", "-y",
        "-accurate_seek",
        "-ss", str(start_sec),
        "-i", str(source_file),
        "-t", str(duration_sec),
        "-vf", vf,
        "-af", af,
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
            dur = max(0.5, float(seg.get("end", st + 5.0)) - st)

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
            progress_callback(50, "Synchronisation chirurgicale des sous-titres au tempo audio...")

        # Extract audio directly from assembled montage to guarantee perfect sync
        assembled_audio = scratch_dir / "assembled_audio.mp3"
        cmd_extract_audio = [
            "ffmpeg", "-y",
            "-i", str(concat_out),
            "-vn", "-ac", "1", "-ar", "24000", "-b:a", "64k",
            str(assembled_audio),
        ]
        subprocess.run(cmd_extract_audio, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        total_montage_dur = get_video_duration(concat_out)
        aligned_cues = align_subtitles_to_audio(
            audio_path=assembled_audio,
            api_key=plan.get("api_key"),
            target_duration=total_montage_dur,
        )

        # Use audio-aligned cues if speech found, else fallback to sanitized plan cues
        final_transcription = aligned_cues if aligned_cues else plan.get("transcription", [])
        plan["transcription"] = final_transcription

        # Step 3: Subtitles & Hook
        ass_path = scratch_dir / "subtitles.ass"
        hook_text = plan.get("hook", "")
        burn_hook = bool(plan.get("burn_hook", False))
        font_name = plan.get("font_name", "R41 Etoile")
        generate_ass_subtitles(
            transcription=final_transcription,
            hook=hook_text,
            output_ass_path=ass_path,
            burn_hook=burn_hook,
            hook_duration=4.5,
            font_name=font_name,
        )

        # Step 4: Color Grading filter graph
        # eq: contrast, brightness, saturation + unsharp
        color_filter = "eq=contrast=1.06:brightness=0.02:saturation=1.18,unsharp=5:5:0.7:5:5:0.3"
        subtitles_filter = f"ass={ass_path.resolve()}:fontsdir={FONTS_DIR.resolve()}"
        video_filters = f"{color_filter},{subtitles_filter}"

        if progress_callback:
            progress_callback(70, "Traitement sonore et habillage musical...")

        # Step 5: Audio configuration with SFX
        mix_voix = plan.get("mix_voix", True)
        music_style = plan.get("musique_style", "lofi")
        music_path = select_music_file(music_style)
        sfx_events = plan.get("sfx", [])

        # Filter valid SFX events
        valid_sfx = []
        for ev in sfx_events:
            s_type = ev.get("type") or ev.get("sound", "whoosh")
            s_file = get_sfx_path(s_type)
            s_time = float(ev.get("time", 0.0))
            if s_file and s_file.exists() and s_time >= 0:
                valid_sfx.append({
                    "file": s_file,
                    "time": s_time,
                    "volume": float(ev.get("volume", 0.85)),
                })

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd_render = ["ffmpeg", "-y", "-i", str(concat_out)]
        fc_audio_parts = []
        mix_inputs = []

        if music_path and music_path.exists():
            cmd_render.extend(["-stream_loop", "-1", "-i", str(music_path)])
            if mix_voix:
                fc_audio_parts.append("[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a_speech]")
                fc_audio_parts.append("[1:a]volume=0.18[a_music]")
                fc_audio_parts.append("[a_speech][a_music]amix=inputs=2:duration=first:dropout_transition=2[a_base]")
            else:
                fc_audio_parts.append("[1:a]volume=0.85[a_base]")
            mix_inputs.append("[a_base]")
            next_input_idx = 2
        else:
            if mix_voix:
                fc_audio_parts.append("[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[a_base]")
                mix_inputs.append("[a_base]")
            next_input_idx = 1

        # Add SFX inputs and filters
        for i, sfx_item in enumerate(valid_sfx):
            cmd_render.extend(["-i", str(sfx_item["file"])])
            delay_ms = int(sfx_item["time"] * 1000)
            vol = sfx_item["volume"]
            fc_audio_parts.append(f"[{next_input_idx + i}:a]adelay={delay_ms}|{delay_ms},volume={vol}[sfx_{i}]")
            mix_inputs.append(f"[sfx_{i}]")

        if len(mix_inputs) > 1:
            fc_audio_parts.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0[outa]")
        elif len(mix_inputs) == 1:
            fc_audio_parts.append(f"{mix_inputs[0]}anull[outa]")
        else:
            fc_audio_parts.append("aevalsrc=0:d=1[outa]")

        filter_complex = f"[0:v]{video_filters}[outv];" + ";".join(fc_audio_parts)

        cmd_render.extend([
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
        ])

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
