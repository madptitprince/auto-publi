import os
import re
import json
import time
import subprocess
import unicodedata
from pathlib import Path
from google import genai
from google.genai import types

from montage_auto.config import GEMINI_API_KEY, TEMP_DIR


def clean_json_text(text: str) -> dict:
    """Extract and parse clean JSON from model response."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end+1]
    return json.loads(cleaned)


def extract_audio_track(video_path: Path, output_audio_path: Path) -> Path:
    """Extracts a lightweight mono MP3 audio track from a video file."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "24000",
        "-b:a", "64k",
        str(output_audio_path),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_audio_path


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
            return round(float(res.stdout.strip()), 1)
    except Exception:
        pass
    return 25.0


def transcribe_audio_with_gemini(client: genai.Client, audio_path: Path) -> str:
    """
    Transcribes audio with gemini-3.5-transcribe or fallback models.
    Returns plain text transcript.
    """
    f_ref = client.files.upload(file=str(audio_path))
    
    # Wait until ACTIVE
    waited = 0
    while f_ref.state.name == "PROCESSING" and waited < 30:
        time.sleep(1)
        waited += 1
        f_ref = client.files.get(name=f_ref.name)

    # 1. Try gemini-3.5-transcribe first (dedicated audio transcription, no 503 quota issues)
    try:
        res = client.models.generate_content(
            model="gemini-3.5-transcribe",
            contents=[f_ref, "Transcris mot a mot cet audio en francais."]
        )
        if res.candidates and res.candidates[0].content.parts:
            part = res.candidates[0].content.parts[0]
            if hasattr(part, "audio_transcription") and part.audio_transcription:
                return part.audio_transcription.text or ""
            elif part.text:
                return part.text
    except Exception as e:
        print(f"gemini-3.5-transcribe echec ({e}), tentative avec gemini-3.6-flash...")

    # 2. Try flash models for transcription
    for m in ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-flash-latest"]:
        try:
            res = client.models.generate_content(
                model=m,
                contents=[f_ref, "Transcris mot a mot tous les dialogues ou paroles entendus."]
            )
            if res.text:
                return res.text.strip()
        except Exception:
            continue

    return ""


def analyze_and_plan_montage(
    video_paths: list[Path],
    target_duration: int = 25,
    music_mode: str = "auto",
    custom_hook: str = "",
    api_key: str | None = None,
) -> dict:
    """
    Two-stage high-reliability editing planner:
    1. Transcribes audio reliably using gemini-3.5-transcribe
    2. Plans smart cuts, hook and subtitles using LLM with zero emoji constraints
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        print("Aucune clef GEMINI_API_KEY configuree.")
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    client = genai.Client(api_key=active_key)
    scratch_dir = TEMP_DIR / "ai_analysis"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Collect durations and transcribe audio from each rush
        all_transcripts = []
        rush_durations = []

        for i, vpath in enumerate(video_paths):
            dur = get_video_duration(vpath)
            rush_durations.append(dur)
            audio_path = scratch_dir / f"rush_{i}_audio.mp3"
            extract_audio_track(vpath, audio_path)

            print(f"Transcription audio du rush {i+1}/{len(video_paths)} ({vpath.name})...")
            tr = transcribe_audio_with_gemini(client, audio_path)
            all_transcripts.append(tr)

        combined_transcript = "\n".join([f"Rush {i} ({rush_durations[i]}s) : {t}" for i, t in enumerate(all_transcripts)])
        has_dialogue = any(len(t.strip()) > 10 for t in all_transcripts)
        print(f"Transcription terminee (Paroles detectees : {has_dialogue}).")

        # LLM Planning Prompt
        prompt = f"""Tu es un monteur video expert en contenu viral TikTok et Instagram Reels pour des restaurants (BCHEF Bourges).
Voici la transcription des rushs ({len(video_paths)} video(s)) :
{combined_transcript}

Durees sources : {', '.join([f'Rush {i}: {d}s' for i, d in enumerate(rush_durations)])}
Duree cible du montage : {target_duration} secondes (entre 20s et 30s).

OBJECTIF :
Concevoir un montage video court, percutant et dynamique.
- Si des paroles sont presentes, selectionne le segment le plus interessant, comique ou dramatique d'environ {target_duration} secondes.
- Fournis un Hook percutant en majuscules (max 8 mots, SANS EMOJI).
- Rédige une description en 1 phrase (SANS EMOJI) et 5 hashtags pertinents (SANS EMOJI).
- Découpe les sous-titres en séquences TRÈS COURTES de 2 à 4 mots maximum par cue (durée 0.5s à 1.2s par cue) pour un rythme dynamique style TikTok/Reels.
- Style musical : {music_mode if music_mode != 'auto' else ('tension' if 'privil' in combined_transcript.lower() or 'racis' in combined_transcript.lower() else 'lofi')}.

Reponds STRICTEMENT en format JSON valide :
{{
  "type_contenu": "dialogue" if has_dialogue else "culinaire",
  "hook": "TITRE ACCROCHE EN MAJUSCULES (max 8 mots, sans emoji)",
  "description": "Courte description engageante sans emoji.",
  "hashtags": ["#bchef", "#bourges", "#restohumour", "#viedequipe", "#burgerlovers"],
  "musique_style": "tension",
  "mix_voix": {str(has_dialogue).lower()},
  "segments": [
    {{"file_index": 0, "start": 18.0, "end": 41.0, "label": "Moment fort"}}
  ],
  "transcription": [
    {{"start": 0.0, "end": 0.9, "text": "2 OU 3 MOTS"}},
    {{"start": 0.9, "end": 1.8, "text": "MOTS SUIVANTS"}}
  ]
}}
"""
        plan = None
        last_err = None

        candidate_llms = [
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.8-flash",
        ]
        for model_name in candidate_llms:
            try:
                print(f"Generation du plan de montage avec {model_name}...")
                config_kwargs = {}
                if "gemini" in model_name:
                    config_kwargs["response_mime_type"] = "application/json"
                
                res = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None
                )
                plan = clean_json_text(res.text)
                plan["model_used"] = model_name
                print(f"Planification reussie avec {model_name} !")
                break
            except Exception as e:
                print(f"Echec avec {model_name} : {e}")
                last_err = str(e)
                continue

        if not plan:
            # Emergency synthesis from transcript directly
            plan = build_plan_from_transcript(all_transcripts, rush_durations, target_duration, custom_hook, music_mode)

        plan["api_key"] = active_key
        return validate_and_sanitize_plan(plan, video_paths, target_duration, custom_hook, music_mode)

    except Exception as err:
        print(f"Erreur globale analyse IA : {err}")
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    finally:
        try:
            for item in scratch_dir.glob("rush_*_audio.mp3"):
                item.unlink(missing_ok=True)
        except Exception:
            pass


def build_plan_from_transcript(
    transcripts: list[str],
    durations: list[float],
    target_duration: int,
    custom_hook: str,
    music_mode: str,
) -> dict:
    """Builds a structured plan directly from audio transcript if LLM generation was unavailable."""
    main_text = transcripts[0] if transcripts else ""
    dur = durations[0] if durations else 25.0

    # Auto Hook detection based on keywords
    hook = custom_hook.upper() if custom_hook else ""
    if not hook:
        if "privilège" in main_text.lower() or "privilege" in main_text.lower():
            hook = "PRIVILEGES AU TRAVAIL VRAI OU FAUX"
        elif "raciste" in main_text.lower() or "servie" in main_text.lower():
            hook = "QUAND UNE CLIENTE REFUSE DE SE FAIRE SERVIR"
        elif "alexa" in main_text.lower():
            hook = "LES COULISSES D ALEXA EN SERVICE"
        else:
            hook = "MOMENT EN DIRECT DE LA CUISINE"

    # Select best segment
    st = 0.0
    if dur > 30.0:
        st = max(0.0, round(dur - target_duration - 2.0, 1))
    et = min(dur, st + target_duration)

    # Segment sentences
    sentences = [s.strip().upper() for s in re.split(r"[\.\?\!]", main_text) if len(s.strip()) > 3]
    trans_cues = []
    if sentences:
        cue_dur = (et - st) / len(sentences)
        for idx, sentence in enumerate(sentences):
            c_start = round(idx * cue_dur, 2)
            c_end = round(min(et - st, (idx + 1) * cue_dur), 2)
            trans_cues.append({
                "start": c_start,
                "end": c_end,
                "text": re.sub(r"[^\w\s\-\'\,\.]", "", sentence),
            })

    return {
        "type_contenu": "dialogue" if len(main_text) > 10 else "culinaire",
        "hook": hook,
        "description": "Retrouvez l'equipe BCHEF Bourges au quotidien.",
        "hashtags": ["#bchef", "#bourges", "#viedequipe", "#restohumour", "#travail"],
        "musique_style": music_mode if music_mode != "auto" else "tension",
        "mix_voix": True,
        "segments": [{"file_index": 0, "start": st, "end": et, "label": "Moment fort"}],
        "transcription": trans_cues,
        "model_used": "transcript-synthesizer",
    }


def validate_and_sanitize_plan(
    plan: dict,
    video_paths: list[Path],
    target_duration: int,
    custom_hook: str,
    music_mode: str,
) -> dict:
    """Ensures plan has valid cuts, duration, and clean text without emojis."""
    if custom_hook:
        plan["hook"] = custom_hook.upper()

    if music_mode != "auto":
        plan["musique_style"] = music_mode

    # Clean emojis from hook and description
    plan["hook"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("hook", "MOMENT EN CUISINE")).strip().upper()
    plan["description"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("description", "")).strip()

    segments = plan.get("segments", [])
    if not segments:
        segments = [{"file_index": 0, "start": 0.0, "end": min(float(target_duration), 25.0), "label": "Segment principal"}]

    sanitized_segments = []
    total_dur = 0.0
    for seg in segments:
        f_idx = int(seg.get("file_index", 0))
        if f_idx < 0 or f_idx >= len(video_paths):
            f_idx = 0
        s = max(0.0, float(seg.get("start", 0.0)))
        e = max(s + 1.0, float(seg.get("end", s + 5.0)))
        dur = e - s
        if total_dur + dur > 32.0 and sanitized_segments:
            e = s + max(2.0, 30.0 - total_dur)
            dur = e - s
        total_dur += dur
        sanitized_segments.append({
            "file_index": f_idx,
            "start": round(s, 2),
            "end": round(e, 2),
            "label": seg.get("label", f"Plan {len(sanitized_segments)+1}"),
        })
        if total_dur >= 28.0:
            break

    plan["segments"] = sanitized_segments
    plan["total_duration"] = round(total_dur, 2)

    # Sanitize transcription
    trans = plan.get("transcription", [])
    cleaned_trans = []
    for item in trans:
        text = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", item.get("text", "")).strip().upper()
        if text:
            cleaned_trans.append({
                "start": max(0.0, round(float(item.get("start", 0.0)), 2)),
                "end": max(0.5, round(float(item.get("end", 1.0)), 2)),
                "text": text,
            })
    plan["transcription"] = cleaned_trans
    return plan


def create_fallback_plan(
    video_paths: list[Path],
    target_duration: int = 25,
    custom_hook: str = "",
    music_mode: str = "auto",
) -> dict:
    """Safe offline emergency plan."""
    hook = (custom_hook or "LES COULISSES DU SERVICE").upper()
    dur_per_clip = max(5.0, target_duration / max(1, len(video_paths)))
    segments = []
    for i, _ in enumerate(video_paths):
        segments.append({
            "file_index": i,
            "start": 0.0,
            "end": round(dur_per_clip, 2),
            "label": f"Rush {i+1}",
        })

    return {
        "type_contenu": "dialogue",
        "hook": hook,
        "description": "Retrouvez l'equipe BCHEF Bourges au quotidien.",
        "hashtags": ["#bchef", "#bourges", "#foodie", "#restaurant", "#viedequipe"],
        "mix_voix": True,
        "musique_style": music_mode if music_mode != "auto" else "tension",
        "segments": segments,
        "transcription": [],
        "total_duration": round(dur_per_clip * len(video_paths), 2),
        "model_used": "fallback-local",
    }
