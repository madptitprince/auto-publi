import os
import re
import json
import time
import subprocess
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


def create_preview_video(video_path: Path, output_preview_path: Path) -> Path:
    """
    Generates an ultra-lightweight 540p compressed preview (1-2 MB)
    for fast upload and optimal visual processing by Gemini.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", "scale=-2:540",
        "-c:v", "libx264",
        "-crf", "28",
        "-preset", "ultrafast",
        "-c:a", "aac",
        "-ar", "24000",
        "-b:a", "64k",
        "-ac", "1",
        str(output_preview_path),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_preview_path if output_preview_path.exists() else video_path


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


def analyze_single_rush(client: genai.Client, video_path: Path, scratch_dir: Path, rush_idx: int) -> dict:
    """
    Performs fast multimodal visual + auditory analysis on a single rush.
    Returns visual description, spoken dialogue, tone, and character actions.
    """
    dur = get_video_duration(video_path)
    preview_file = scratch_dir / f"prev_rush_{rush_idx}.mp4"
    create_preview_video(video_path, preview_file)

    try:
        f_ref = client.files.upload(file=str(preview_file))
        waited = 0
        while f_ref.state.name == "PROCESSING" and waited < 30:
            time.sleep(1)
            waited += 1
            f_ref = client.files.get(name=f_ref.name)

        prompt = (
            "Analyse cette sequence video pour le restaurant BCHEF Bourges (13 place Gordaine) :\n"
            "1. Visuel : Qui sont les personnes, que font-elles precisement (actions, regards, mimiques, objets/plats manipules) ?\n"
            "2. Paroles : Y a-t-il des dialogues ou est-ce muet / bruit ambiant ? Transcris tout mot prononce.\n"
            "3. Rôle narratif : Est-ce une mise en place de vanne (feinte), une chute comique, une commande en cuisine, ou un moment produit/service burger gourmand ?\n\n"
            "Reponds en JSON strict :\n"
            "{\n"
            '  "visuel": "description detaillee des actions et expressions",\n'
            '  "dialogues": "mots prononces mot a mot ou AUCUN",\n'
            '  "role": "feinte / chute / service / cuisine",\n'
            '  "ton": "humour / culinaire / rush"\n'
            "}"
        )

        for model_name in ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.8-flash"]:
            try:
                res = client.models.generate_content(
                    model=model_name,
                    contents=[f_ref, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        http_options={"timeout": 30000},
                    )
                )
                data = clean_json_text(res.text)
                data["duration"] = dur
                data["name"] = video_path.name
                return data
            except Exception:
                continue

    except Exception as e:
        print(f"[AI Director] Erreur analyse rush {video_path.name}: {e}")

    # Fallback to audio transcription if multimodal fails
    audio_path = scratch_dir / f"audio_{rush_idx}.mp3"
    extract_audio_track(video_path, audio_path)
    return {
        "name": video_path.name,
        "duration": dur,
        "visuel": "Sequence en restaurant ou cuisine BCHEF",
        "dialogues": "Paroles non analysees",
        "role": "sequence",
        "ton": "humour",
    }


def synthesize_master_montage_plan(
    client: genai.Client,
    rush_analyses: list[dict],
    video_paths: list[Path],
    target_duration: int = 25,
    music_mode: str = "auto",
    custom_hook: str = "",
) -> dict:
    """
    Directorial synthesis:
    Understands the narrative arc across all rushs, sequences the clips logically (setup -> punchline),
    chooses the appropriate music and places sound effects (SFX) at key moments.
    """
    rush_summary = ""
    for i, a in enumerate(rush_analyses):
        rush_summary += (
            f"\n--- RUSH {i} (Fichier: {a.get('name')}, Duree: {a.get('duration')}s) ---\n"
            f"Actions visuelles : {a.get('visuel')}\n"
            f"Paroles : {a.get('dialogues')}\n"
            f"Rôle : {a.get('role')} | Ton : {a.get('ton')}\n"
        )

    prompt = f"""Tu es le Chef Monteur et Directeur Artistique expert en Reels et TikTok viraux pour BCHEF Bourges (13 place Gordaine).
Voici l'analyse visuelle et audio de chaque rush brut disponible ({len(rush_analyses)} video(s)) :
{rush_summary}

Duree cible du montage final : {target_duration} secondes (entre 15s et 30s).

MISSION DE SCENARISATION ET MONTAGE :
1. COMPREHENSION NARRATIVE REELLE :
   - Explique ce qu'il se passe reellement :
     * Si c'est un sketch a plusieurs rushs (ex: l'equipier qui fait croire qu'une cliente attend d'urgence un chiller pour qu'Alexandre le prepare vite, puis s'en empare pour aller le boire en douce tout seul), comprends l'arnaque amicale !
     * Ordonne chronologiquement les segments : la mise en place d'abord (la fausse urgence), puis la chute (la recuperation du chiller et la degustation en douce). N'hesite pas a inverser l'ordre des rushs si necessaire pour respecter la logique (Setup -> Punchline) !
     * Si c'est une sequence sans parole (ex: serveuse qui apporte un burger gourmand et frites a table, cliente qui filme le plat), oriente le Hook et le ton sur la gourmandise du burger et le rituel foodie !
2. HABILLAGE SONORE ET SOUND EFFECTS (SFX) :
   - Style musical ('comedy', 'lofi', 'tension', 'upbeat') :
     * 'comedy' : pour les vannes entre collegues, sketchs, chiller en douce.
     * 'lofi' : pour les moments gourmands, service en salle, ambiance cosy.
     * 'tension' : pour le faux suspense ou secrets de cuisine.
     * 'upbeat' : pour le gros rush et energie de service.
   - Points d'effets sonores (SFX) a placer a des horodatages precis :
     * 'whoosh' : transition dynamique lors d'un changement de rush.
     * 'record_scratch' : rupture comique, arret net quand la verite eclate ou temps d'arret comique.
     * 'comedy_punch' : gros impact comique sur la chute humoristique.
     * 'ding' ou 'pop' : mise en valeur gourmande ou revelation.
3. HOOK, DESCRIPTION ET HASHTAGS (SANS AUCUN EMOJI) :
   - Hook : MAJUSCULES, max 8 mots, percutant, parfaitement adapte a la situation (SANS AUCUN EMOJI).
   - Description : 1 seule phrase engageante incitant a reagir (SANS EMOJI).
   - Hashtags : 5 hashtags pertinents (SANS EMOJI).

Reponds STRICTEMENT en format JSON valide :
{{
  "type_contenu": "humour" ou "culinaire" ou "coulisses",
  "histoire_comprise": "Explication claire du sens reel de la scene et de la chute",
  "hook": "TITRE PERCUTANT EN MAJUSCULES SANS EMOJI",
  "description": "Courte description engageante sans emoji.",
  "hashtags": ["#bchef", "#bourges", "#restohumour", "#viedequipe", "#chiller"],
  "musique_style": "{music_mode if music_mode != 'auto' else 'comedy'}",
  "mix_voix": true,
  "segments": [
    {{"file_index": 1, "start": 0.0, "end": 8.1, "label": "Mise en place de la feinte"}},
    {{"file_index": 0, "start": 0.0, "end": 8.5, "label": "Chute : depart avec la boisson"}}
  ],
  "sfx": [
    {{"time": 7.8, "type": "whoosh", "volume": 0.85}},
    {{"time": 12.5, "type": "record_scratch", "volume": 0.85}}
  ]
}}
"""
    for model_name in ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.8-flash"]:
        try:
            print(f"[AI Director] Synthese directoriale du montage avec {model_name}...")
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = clean_json_text(res.text)
            data["model_used"] = f"{model_name}-master-director"
            return data
        except Exception as e:
            print(f"[AI Director] Echec synthese {model_name}: {e}")
            continue

    return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)


def analyze_and_plan_montage(
    video_paths: list[Path],
    target_duration: int = 25,
    music_mode: str = "auto",
    custom_hook: str = "",
    api_key: str | None = None,
) -> dict:
    """
    Main entrypoint:
    Analyzes all rushs with multimodal visual + auditory understanding,
    then synthesizes a high-impact narrative montage plan with adapted SFX and music.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        print("Aucune clef GEMINI_API_KEY configuree.")
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    client = genai.Client(api_key=active_key)
    scratch_dir = TEMP_DIR / f"ai_analysis_{int(time.time())}"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[AI Director] Analyse multimodale de {len(video_paths)} rushs...")
        rush_analyses = []
        for i, vp in enumerate(video_paths):
            print(f"[AI Director] Analyse du rush {i+1}/{len(video_paths)} ({vp.name})...")
            ra = analyze_single_rush(client, vp, scratch_dir, i)
            rush_analyses.append(ra)

        plan = synthesize_master_montage_plan(
            client=client,
            rush_analyses=rush_analyses,
            video_paths=video_paths,
            target_duration=target_duration,
            music_mode=music_mode,
            custom_hook=custom_hook,
        )

        plan["api_key"] = active_key
        return validate_and_sanitize_plan(plan, video_paths, target_duration, custom_hook, music_mode)

    except Exception as err:
        print(f"Erreur globale analyse IA : {err}")
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    finally:
        try:
            for item in scratch_dir.iterdir():
                item.unlink(missing_ok=True)
            scratch_dir.rmdir()
        except Exception:
            pass


def validate_and_sanitize_plan(
    plan: dict,
    video_paths: list[Path],
    target_duration: int,
    custom_hook: str,
    music_mode: str,
) -> dict:
    """Ensures plan has valid cuts, duration, sfx, and clean text without emojis."""
    if custom_hook:
        plan["hook"] = custom_hook.upper()

    if music_mode != "auto":
        plan["musique_style"] = music_mode

    # Clean emojis from hook and description
    plan["hook"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("hook", "MOMENT EN CUISINE")).strip().upper()
    plan["description"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("description", "")).strip()

    segments = plan.get("segments", [])
    if not segments:
        dur_clip = min(float(target_duration), 25.0) / max(1, len(video_paths))
        segments = [
            {"file_index": i, "start": 0.0, "end": round(dur_clip, 2), "label": f"Plan {i+1}"}
            for i in range(len(video_paths))
        ]

    sanitized_segments = []
    total_dur = 0.0
    for seg in segments:
        f_idx = int(seg.get("file_index", 0))
        if f_idx < 0 or f_idx >= len(video_paths):
            f_idx = 0
        v_dur = get_video_duration(video_paths[f_idx])
        s = max(0.0, float(seg.get("start", 0.0)))
        e = min(v_dur, max(s + 1.0, float(seg.get("end", s + 5.0))))
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

    # Sanitize SFX events
    raw_sfx = plan.get("sfx", [])
    clean_sfx = []
    for ev in raw_sfx:
        s_time = round(float(ev.get("time", 0.0)), 2)
        s_type = re.sub(r"[^\w\-]", "", str(ev.get("type") or ev.get("sound", "whoosh"))).lower().strip()
        if 0.0 <= s_time <= total_dur:
            clean_sfx.append({
                "time": s_time,
                "type": s_type,
                "volume": float(ev.get("volume", 0.85)),
            })
    plan["sfx"] = clean_sfx

    return plan


def create_fallback_plan(
    video_paths: list[Path],
    target_duration: int = 25,
    custom_hook: str = "",
    music_mode: str = "auto",
) -> dict:
    """Safe offline emergency plan."""
    hook = (custom_hook or "LES COULISSES DU RESTAURANT").upper()
    dur_per_clip = max(4.0, target_duration / max(1, len(video_paths)))
    segments = []
    for i, vp in enumerate(video_paths):
        v_dur = get_video_duration(vp)
        segments.append({
            "file_index": i,
            "start": 0.0,
            "end": round(min(dur_per_clip, v_dur), 2),
            "label": f"Rush {i+1}",
        })

    return {
        "type_contenu": "coulisses",
        "histoire_comprise": "Coulisses du restaurant BCHEF Bourges",
        "hook": hook,
        "description": "Retrouvez l'equipe BCHEF Bourges au quotidien.",
        "hashtags": ["#bchef", "#bourges", "#foodie", "#restaurant", "#viedequipe"],
        "mix_voix": True,
        "musique_style": music_mode if music_mode != "auto" else "comedy",
        "segments": segments,
        "sfx": [{"time": 5.0, "type": "whoosh", "volume": 0.85}],
        "transcription": [],
        "total_duration": round(dur_per_clip * len(video_paths), 2),
        "model_used": "fallback-local",
    }
