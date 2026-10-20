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


def transcribe_audio_with_gemini(client: genai.Client, audio_path: Path) -> str:
    """Transcribes audio with gemini-3.5-transcribe or fallback models."""
    try:
        f_ref = client.files.upload(file=str(audio_path))
        waited = 0
        while f_ref.state.name == "PROCESSING" and waited < 30:
            time.sleep(1)
            waited += 1
            f_ref = client.files.get(name=f_ref.name)

        res = client.models.generate_content(
            model="gemini-3.5-transcribe",
            contents=[f_ref, "Transcris mot a mot cet audio en francais."]
        )
        if res.candidates and res.candidates[0].content.parts:
            part = res.candidates[0].content.parts[0]
            txt_obj = getattr(part, "audio_transcription", None)
            val = getattr(txt_obj, "text", None) or part.text
            if val:
                return val.strip()
    except Exception as e:
        print(f"gemini-3.5-transcribe echec ({e}), tentative via flash models...")

    for m in ["gemini-3.1-flash-lite", "gemini-flash-latest", "gemini-3.6-flash"]:
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


def analyze_multimodal_rushs(
    client: genai.Client,
    video_paths: list[Path],
    scratch_dir: Path,
    target_duration: int = 25,
    music_mode: str = "auto",
    custom_hook: str = "",
) -> dict | None:
    """
    Comprehensive multimodal video understanding:
    1. Uploads compressed video previews (visual frames + temporal actions + audio).
    2. Deeply understands the scene: actors, expressions, sneaking actions, foodie service, gags.
    3. Handles multi-rush narrative sequencing (setup -> punchline) and silent video lifestyle editing.
    4. Proposes adapted music and comedic/dynamic sound effects (SFX).
    """
    uploaded_files = []
    durations = [get_video_duration(p) for p in video_paths]

    try:
        print(f"[AI Director] Creation des previsualisations et envoi multimodal de {len(video_paths)} rushs...")
        for i, vp in enumerate(video_paths):
            prev_path = scratch_dir / f"prev_rush_{i}.mp4"
            create_preview_video(vp, prev_path)
            f_ref = client.files.upload(file=str(prev_path))
            waited = 0
            while f_ref.state.name == "PROCESSING" and waited < 30:
                time.sleep(1)
                waited += 1
                f_ref = client.files.get(name=f_ref.name)
            uploaded_files.append(f_ref)

        rush_descriptions = "\n".join([
            f"- Rush {i} : nom='{video_paths[i].name}', duree={durations[i]}s"
            for i in range(len(video_paths))
        ])

        prompt = f"""Tu es le Realisateur et Chef Monteur expert en contenus viraux (TikTok / Instagram Reels) pour le restaurant BCHEF Bourges (13 place Gordaine, 18000 Bourges).
Tu disposes de {len(video_paths)} rush(s) video de cuisine et de service :
{rush_descriptions}

Duree cible du montage final : {target_duration} secondes (entre 15s et 30s).

MISSION CRUCIALE D'ANALYSE ET DE MONTAGE :
1. COMPREHENSION NARRATIVE ET VISUELLE :
   - Visionne attentivement chaque rush : que font les personnes a l'ecran ? Leurs expressions, leurs regards complices, leurs mimiques, leurs gestes ?
   - Si plusieurs rushs sont fournis, ils racontent souvent une histoire en plusieurs temps :
     * Une mise en place / pretexte dans un rush (ex: un equipier qui fait croire qu'une cliente attend d'urgence une boisson/chiller depuis 10 minutes).
     * Une chute comique dans un autre rush (ex: des qu'Alexandre prepare le chiller, l'equipier s'en empare et va le boire en douce tout seul au calme !).
     * Dans ce cas, RE-ORDONNE les rushs de facon logique : la mise en place d'abord, puis la chute !
   - Si la video est sans dialogue ou muette (ex: une serveuse qui apporte un plateau burger et frites a table, une cliente qui filme son plat avec son smartphone pour les reseaux sociaux) :
     * Comprends qu'il s'agit d'une sequence produit / foodie / lifestyle BCHEF.
     * Oriente le Hook et le montage sur la gourmandise du burger, le rituel photo avant de manger ("Quand ton plat est trop beau pour ne pas etre filme").

2. HABILLAGE SONORE ET SOUND EFFECTS (SFX) :
   - Style musical ('comedy', 'lofi', 'tension', 'upbeat') :
     * 'comedy' : pour les gags, sketchs, vannes entre collegues, feintes de boissons.
     * 'lofi' : pour les videos calmes, culinaires, service en salle, ambiance cosy.
     * 'tension' : pour le faux suspense, incidents clients simules, secrets de cuisine.
     * 'upbeat' : pour le gros rush de midi, preparations rapides, service dynamique.
   - Effets sonores (SFX) a placer a des moments cles du montage :
     * 'whoosh' : transition dynamique ou changement de plan.
     * 'record_scratch' : rupture comique, arret soudain quand la ruse est demasquee.
     * 'comedy_punch' : gros impact sonore sur la chute humoristique.
     * 'ding' ou 'pop' : accentuation de l'accroche ou revelation gourmande.

3. HOOK, DESCRIPTION ET HASHTAGS (SANS AUCUN EMOJI) :
   - Hook : majuscules, max 8 mots, percutant, resument exactement l'humour ou la gourmandise de la scene (SANS AUCUN EMOJI).
   - Description : 1 seule phrase engageante incitant a reagir en commentaire (SANS EMOJI).
   - Hashtags : 5 hashtags pertinents (SANS EMOJI).

Reponds STRICTEMENT en format JSON valide :
{{
  "type_contenu": "humour" ou "culinaire" ou "coulisses",
  "histoire_comprise": "Explication claire de ce qu'il se passe reellement dans la scene et du gag/sens",
  "hook": "ACCROCHE PERCUTANTE EN MAJUSCULES SANS EMOJI",
  "description": "Courte description engageante sans emoji.",
  "hashtags": ["#bchef", "#bourges", "#restohumour", "#viedequipe", "#chiller"],
  "musique_style": "{music_mode if music_mode != 'auto' else 'comedy'}",
  "mix_voix": true,
  "segments": [
    {{"file_index": 1, "start": 0.0, "end": 8.0, "label": "Mise en place de la feinte"}},
    {{"file_index": 0, "start": 0.0, "end": 8.5, "label": "Chute comique et degustation en douce"}}
  ],
  "sfx": [
    {{"time": 7.8, "type": "whoosh"}},
    {{"time": 13.0, "type": "record_scratch"}}
  ]
}}
"""
        candidate_models = [
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
            "gemini-flash-latest",
            "gemini-3.6-flash",
        ]
        for model_name in candidate_models:
            try:
                print(f"[AI Director] Analyse multimodale de la scene avec {model_name}...")
                config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    http_options={"timeout": 45000},
                )
                res = client.models.generate_content(
                    model=model_name,
                    contents=[*uploaded_files, prompt],
                    config=config,
                )
                data = clean_json_text(res.text)
                data["model_used"] = f"{model_name}-multimodal"
                print(f"[AI Director] Succes multimodal avec {model_name} ! Histoire comprise : {data.get('histoire_comprise', '')}")
                return data
            except Exception as e_mod:
                print(f"[AI Director] Modele {model_name} indisponible ({e_mod}), tentative suivante...")
                continue

    except Exception as e_multi:
        print(f"[AI Director] Echec global de l'analyse multimodale : {e_multi}")

    return None


def analyze_and_plan_montage(
    video_paths: list[Path],
    target_duration: int = 25,
    music_mode: str = "auto",
    custom_hook: str = "",
    api_key: str | None = None,
) -> dict:
    """
    Intelligent two-tier video director:
    Tier 1: Full multimodal visual + audio scene understanding (actors, expressions, narrative, SFX).
    Tier 2: Robust audio transcript + LLM fallback if video files upload fails.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        print("Aucune clef GEMINI_API_KEY configuree.")
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    client = genai.Client(api_key=active_key)
    scratch_dir = TEMP_DIR / f"ai_analysis_{int(time.time())}"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Tier 1 : Try full multimodal video understanding first
        plan = analyze_multimodal_rushs(
            client=client,
            video_paths=video_paths,
            scratch_dir=scratch_dir,
            target_duration=target_duration,
            music_mode=music_mode,
            custom_hook=custom_hook,
        )

        # Tier 2 : Audio transcription fallback if multimodal was unavailable
        if not plan:
            print("[AI Director] Bascule sur l'analyse audio de secours...")
            all_transcripts = []
            rush_durations = []
            for i, vpath in enumerate(video_paths):
                dur = get_video_duration(vpath)
                rush_durations.append(dur)
                audio_path = scratch_dir / f"rush_{i}_audio.mp3"
                extract_audio_track(vpath, audio_path)
                tr = transcribe_audio_with_gemini(client, audio_path)
                all_transcripts.append(tr)

            combined_transcript = "\n".join([f"Rush {i} ({rush_durations[i]}s) : {t}" for i, t in enumerate(all_transcripts)])
            has_dialogue = any(len(t.strip()) > 5 for t in all_transcripts)

            prompt_audio = f"""Tu es le monteur video de BCHEF Bourges.
Voici la transcription des rushs ({len(video_paths)} videos) :
{combined_transcript}

Concois un montage percutant de {target_duration} secondes.
- Si c'est un gag d'urgence chiller ou feinte entre collegues, ordonne la feinte d'abord puis la recuperation.
- Style musical : {'comedy' if 'chiller' in combined_transcript.lower() or 'urgence' in combined_transcript.lower() else 'lofi'}.
- Hook : MAJUSCULES, max 8 mots, sans emoji.
- Description et 5 hashtags sans emoji.
- SFX : transitions 'whoosh' ou 'record_scratch'.

Reponds en JSON :
{{
  "type_contenu": "dialogue" if has_dialogue else "culinaire",
  "histoire_comprise": "Montage base sur les echanges entendus en cuisine",
  "hook": "ACCROCHE MAJUSCULES SANS EMOJI",
  "description": "Description en 1 phrase sans emoji.",
  "hashtags": ["#bchef", "#bourges", "#restohumour", "#viedequipe"],
  "musique_style": "comedy",
  "mix_voix": {str(has_dialogue).lower()},
  "segments": [
    {{"file_index": 0, "start": 0.0, "end": min(target_duration, rush_durations[0]), "label": "Sequence principale"}}
  ],
  "sfx": [
    {{"time": 7.0, "type": "whoosh"}}
  ]
}}
"""
            for m in ["gemini-3.1-flash-lite", "gemini-flash-latest"]:
                try:
                    res = client.models.generate_content(
                        model=m,
                        contents=prompt_audio,
                        config=types.GenerateContentConfig(response_mime_type="application/json")
                    )
                    plan = clean_json_text(res.text)
                    plan["model_used"] = f"{m}-audio-fallback"
                    break
                except Exception:
                    continue

        if not plan:
            plan = create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

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
        "sfx": [{"time": 5.0, "type": "whoosh"}],
        "transcription": [],
        "total_duration": round(dur_per_clip * len(video_paths), 2),
        "model_used": "fallback-local",
    }
