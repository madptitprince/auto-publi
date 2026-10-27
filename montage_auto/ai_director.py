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
    Generates an ultra-lightweight 480p 12fps compressed preview (~300-500 KB)
    for lightning-fast encoding and upload to Gemini.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", "fps=12,scale=-2:480",
        "-c:v", "libx264",
        "-crf", "30",
        "-preset", "ultrafast",
        "-threads", "4",
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
    Extracts visual description, spoken dialogue, narrative role, and exact
    speech/silence boundaries to eliminate dead air at rush start and end.
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
            "Tu es un chef monteur expert en Reels et TikTok viraux pour BCHEF Bourges (13 place Gordaine).\n"
            "Analyse ultra-precisement les paroles, silences et temps morts de ce rush video brut :\n"
            "1. Visuel : Qui sont les personnes, que font-elles precisement (actions, regards, mimiques, objets/plats manipules) ?\n"
            "2. Paroles : Y a-t-il des dialogues ou est-ce muet / bruit ambiant ? Transcris fidelement les propos prononces.\n"
            "3. Rôle narratif : Est-ce une mise en place de vanne (feinte), une chute comique, une commande en cuisine, ou un moment produit/service burger gourmand ?\n"
            "4. Horodatages chirurgicaux de parole & silences :\n"
            "   - debut_parole : seconde exacte ou la personne commence a parler (ou debut de l'action narrative clef).\n"
            "   - fin_parole : seconde exacte ou la personne termine sa derniere replique / punchline / mot prononce.\n"
            "   - pause_debut_secondes : secondes de flottement ou d'attente au tout debut avant que la parole/action commence.\n"
            "   - pause_fin_secondes : secondes de silence, hesitation, regard camera fixe ou attente a la fin apres la derniere parole.\n"
            "   - cut_in_recommande : horodatage ideal de debut pour couper l'attente initiale et demarrer direct sur l'action.\n"
            "   - cut_out_recommande : horodatage ideal de fin pour couper NET des la fin de la parole sans aucun temps mort.\n"
            "   - action_fin : description de ce qui se passe a la fin du rush (ex: silence, sourit, regarde la camera, attend, coupe le tel).\n\n"
            "Reponds STRICTEMENT en JSON valide :\n"
            "{\n"
            '  "visuel": "description detaillee des actions et expressions",\n'
            '  "dialogues": "mots prononces mot a mot ou AUCUN",\n'
            '  "role": "feinte / chute / service / cuisine / echange",\n'
            '  "ton": "humour / culinaire / rush",\n'
            '  "debut_parole": 0.0,\n'
            '  "fin_parole": 15.2,\n'
            '  "pause_debut_secondes": 0.5,\n'
            '  "pause_fin_secondes": 2.1,\n'
            '  "cut_in_recommande": 0.4,\n'
            '  "cut_out_recommande": 15.3,\n'
            '  "action_fin": "regarde fixement la camera en silence"\n'
            "}"
        )

        for model_name in ["gemini-3-flash-preview", "gemini-3.1-flash-lite"]:
            try:
                res = client.models.generate_content(
                    model=model_name,
                    contents=[f_ref, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    )
                )
                data = clean_json_text(res.text)
                data["duration"] = dur
                data["name"] = video_path.name

                # Parse timing boundaries
                data["debut_parole"] = round(float(data.get("debut_parole", 0.0)), 2)
                data["fin_parole"] = round(float(data.get("fin_parole", dur)), 2)
                data["cut_in_recommande"] = round(max(0.0, float(data.get("cut_in_recommande", 0.0))), 2)
                data["cut_out_recommande"] = round(min(dur, max(data["cut_in_recommande"] + 0.8, float(data.get("cut_out_recommande", dur)))), 2)
                data["pause_fin_secondes"] = round(max(0.0, float(data.get("pause_fin_secondes", dur - data["fin_parole"]))), 2)
                data["action_fin"] = str(data.get("action_fin", "fin du clip"))
                return data
            except Exception as e:
                print(f"[AI Director] Echec modele {model_name} sur rush {video_path.name}: {e}")
                continue

    except Exception as e:
        print(f"[AI Director] Erreur analyse rush {video_path.name}: {e}")

    # Fallback to basic audio transcription if multimodal fails
    audio_path = scratch_dir / f"audio_{rush_idx}.mp3"
    extract_audio_track(video_path, audio_path)
    return {
        "name": video_path.name,
        "duration": dur,
        "visuel": "Sequence en restaurant ou cuisine BCHEF",
        "dialogues": "Paroles non analysees",
        "role": "sequence",
        "ton": "humour",
        "debut_parole": 0.0,
        "fin_parole": dur,
        "cut_in_recommande": 0.0,
        "cut_out_recommande": dur,
        "pause_fin_secondes": 0.0,
        "action_fin": "fin du rush",
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
    strictly cuts unneeded pauses at clip ends, ensures fluid sequencing, and adapts length up to 40s.
    """
    rush_summary = ""
    for i, a in enumerate(rush_analyses):
        rush_summary += (
            f"\n--- RUSH {i} (Fichier: {a.get('name')}, Duree totale: {a.get('duration')}s) ---\n"
            f"Actions visuelles : {a.get('visuel')}\n"
            f"Paroles : {a.get('dialogues')}\n"
            f"Rôle : {a.get('role')} | Ton : {a.get('ton')}\n"
            f"Parole detectee : de {a.get('debut_parole', 0.0)}s a {a.get('fin_parole', a.get('duration'))}s\n"
            f"Temps mort / Pause fin de rush : {a.get('pause_fin_secondes', 0.0)}s ({a.get('action_fin', 'pause')})\n"
            f"Cuts recommandes : cut_in={a.get('cut_in_recommande', 0.0)}s, cut_out={a.get('cut_out_recommande', a.get('duration'))}s (COUPE OBLIGATOIREMENT AVANT LA PAUSE)\n"
        )

    prompt = f"""Tu es le Chef Monteur et Directeur Artistique expert en Reels et TikTok viraux pour BCHEF Bourges (13 place Gordaine).
Voici l'analyse visuelle et audio detaillee de chaque rush brut disponible ({len(rush_analyses)} video(s)) :
{rush_summary}

Duree indicative cible : {target_duration} secondes (format reseaux sociaux flexible : entre 12s et 40s max).

EXIGENCES CAPITALES DE RYTHME ET COUPE (PACING VIRAL TIKTOK / REELS) :
1. SUPPRESSION IMPERATIVE DES PAUSES ET TEMPS MORTS EN FIN DE RUSH :
   - A la fin des rushs, la personne a souvent fini sa replique et reste fittee, sourit timidement, attend ou regarde la camera avant de couper l'enregistrement.
   - Tu DOIS couper NET immediatement des que la derniere replique ou la reaction comique est terminee (au niveau de 'cut_out_recommande' ou 'fin_parole' + 0.15s max).
   - NE LAISSE JAMAIS TRAINER une pause, un silence ou un temps mort a la fin d'un segment !
2. RACCORDEMENT FLUIDE ET DYNAMIQUE ENTRE LES RUSHS :
   - Demarre chaque rush directement a 'cut_in_recommande' (ou debut_parole) pour supprimer l'hesitation initiale.
   - L'enchainement entre la fin du rush precedent et le debut du rush suivant doit etre ultra-fluide, dynamique et sans trou sonore (jump-cut / match-cut viral).
3. DUREE ADAPTABLE SANS TRONQUER LA FIN (MAX 40s) :
   - La duree cible ({target_duration}s) est une orientation, pas une cage rigide :
     * Si la scene ou le sketch est punchy et se conclut parfaitement en 15s ou 18s, ne le rallonge pas artificiellement avec du vide !
     * Si le dialogue ou l'histoire a besoin de 30s a 38s pour que la punchline finale et la chute soient entieres sans etre coupees, utilise le temps necessaire jusqu'a 40s maximum.
     * PLAFOND STRICT RESEAUX SOCIAUX : MAXIMUM ABSOLU DE 40.0 SECONDES. Ne depasse jamais 40.0s.
     * NE COUPE JAMAIS LA PAROLE OU LA PUNCHLINE EN PLEIN MILIEU pour respecter un quota arbitraire.
4. COMPREHENSION NARRATIVE REELLE :
   - Explique ce qu'il se passe reellement :
     * Si c'est un sketch a plusieurs rushs (ex: vanne entre equipiers, faux pretexte, arnaque amicale pour un chiller, planning ou conges refuses, Moses qui a des privileges), comprends l'intrigue complete !
     * Ordonne chronologiquement les segments : la mise en place d'abord (Setup), puis la chute (Punchline).
     * Si c'est une sequence foodie (burger, frites, service), cadence le rythme sur la gourmandise.
5. HABILLAGE SONORE ET SOUND EFFECTS (SFX) :
   - Style musical ('comedy', 'lofi', 'tension', 'upbeat') :
     * 'comedy' : vannes, sketchs, complicite entre collegues.
     * 'lofi' : moments gourmands, service en salle, ambiance cosy.
     * 'tension' : faux drame, secrets de cuisine, privileges.
     * 'upbeat' : rush du midi, dynamique de service.
   - Points d'effets sonores (SFX) a placer a des horodatages precis :
     * 'whoosh' : transition dynamique lors d'un changement de plan.
     * 'record_scratch' : rupture comique, arret net quand la verite eclate.
     * 'comedy_punch' : gros impact comique sur la chute humoristique.
     * 'ding' ou 'pop' : mise en valeur gourmande ou revelation.
6. HOOK, DESCRIPTION ET HASHTAGS (STYLE OFFICIEL BOURGES, SANS AUCUN EMOJI) :
   - Hook : MAJUSCULES, 6 a 9 mots max, percutant, stoppant le scroll (SANS AUCUN EMOJI).
     Exemples reels : 'QUAND LE RUSH COMMENCE ET QUE TON COLLEGUE DISPARAIT', 'QUAND UNE CLIENTE DEPASSE TOTALEMENT LES BORNES', 'LE PETIT PREFERE DE LA CUISINE'.
   - Description : 1 seule phrase courte et naturelle incitant a l'interaction (SANS EMOJI et JAMAIS de blabla corporate type brochure).
     Exemples reels : 'Et vous, vous arrivez a tenir combien de temps sans faire de pause en plein coup de feu ?' ou 'Tague la personne de ton equipe a qui tu refiles toujours cette corvee en commentaire.'
   - Hashtags : 5 hashtags cibles parmi #bchef #bourges #restauration #viedequipe #humour #convivial #burger (SANS EMOJI).

Reponds STRICTEMENT en format JSON valide :
{{
  "type_contenu": "humour" ou "culinaire" ou "coulisses",
  "histoire_comprise": "Explication claire du sens reel de la scene et de la chute",
  "hook": "TITRE PERCUTANT EN MAJUSCULES SANS EMOJI",
  "description": "Courte description engageante sans emoji.",
  "hashtags": ["#bchef", "#bourges", "#restauration", "#viedequipe", "#humour"],
  "musique_style": "{music_mode if music_mode != 'auto' else 'comedy'}",
  "mix_voix": true,
  "segments": [
    {{"file_index": 1, "start": 0.2, "end": 7.4, "label": "Mise en place sans temps mort"}},
    {{"file_index": 0, "start": 0.1, "end": 8.2, "label": "Chute coupe des la fin de parole"}}
  ],
  "sfx": [
    {{"time": 7.2, "type": "whoosh", "volume": 0.85}},
    {{"time": 12.0, "type": "comedy_punch", "volume": 0.85}}
  ]
}}
"""
    for model_name in ["gemini-3-flash-preview", "gemini-3.1-flash-lite"]:
        try:
            print(f"[AI Director] Synthese directoriale du montage avec {model_name}...", flush=True)
            res = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = clean_json_text(res.text)
            data["model_used"] = f"{model_name}-master-director"
            return data
        except Exception as e:
            print(f"[AI Director] Echec synthese {model_name}: {e}", flush=True)
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
        print("Aucune clef GEMINI_API_KEY configuree.", flush=True)
        return create_fallback_plan(video_paths, target_duration, custom_hook, music_mode)

    client = genai.Client(api_key=active_key)
    scratch_dir = TEMP_DIR / f"ai_analysis_{int(time.time())}"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[AI Director] Analyse multimodale de {len(video_paths)} rushs...", flush=True)
        rush_analyses = []
        for i, vp in enumerate(video_paths):
            print(f"[AI Director] Analyse du rush {i+1}/{len(video_paths)} ({vp.name})...", flush=True)
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
        return validate_and_sanitize_plan(
            plan=plan,
            video_paths=video_paths,
            target_duration=target_duration,
            custom_hook=custom_hook,
            music_mode=music_mode,
            rush_analyses=rush_analyses,
        )

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
    rush_analyses: list[dict] | None = None,
) -> dict:
    """
    Ensures plan has valid cuts, cleans dead pauses at rush ends,
    guarantees fluid transitions, respects social format cap (max 40s),
    and removes any emojis from hook and description.
    """
    MAX_MONTAGE_DURATION = 40.0

    if custom_hook:
        plan["hook"] = custom_hook.upper()

    if music_mode != "auto":
        plan["musique_style"] = music_mode

    # Clean emojis from hook and description
    plan["hook"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("hook", "MOMENT EN CUISINE")).strip().upper()
    plan["description"] = re.sub(r"[^\w\s\-\'\,\.\!\?]", "", plan.get("description", "")).strip()

    segments = plan.get("segments", [])
    if not segments:
        dur_target = max(12.0, min(float(target_duration), MAX_MONTAGE_DURATION))
        dur_clip = dur_target / max(1, len(video_paths))
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
        e = min(v_dur, max(s + 0.8, float(seg.get("end", s + 4.0))))

        # Precise dead pause trimming using rush analysis if available
        if rush_analyses and f_idx < len(rush_analyses):
            ra = rush_analyses[f_idx]
            rec_in = ra.get("cut_in_recommande")
            rec_out = ra.get("cut_out_recommande")
            fin_p = ra.get("fin_parole")
            pause_fin = ra.get("pause_fin_secondes", 0.0)

            # Prune initial dead hesitation if cut started at 0
            if s < 0.2 and rec_in is not None and rec_in > 0.4:
                s = rec_in

            # If segment end trails into dead air or lingering pause, clamp it right after speech
            if pause_fin >= 0.5 and fin_p and e > (fin_p + 0.25):
                e = min(v_dur, max(s + 0.8, fin_p + 0.15))
            elif rec_out and e > (rec_out + 0.3):
                e = min(v_dur, max(s + 0.8, rec_out))

        dur = e - s
        if dur <= 0.3:
            continue

        # Check total montage length ceiling (max 40.0s)
        if total_dur + dur > MAX_MONTAGE_DURATION:
            remaining = MAX_MONTAGE_DURATION - total_dur
            if remaining >= 1.5:
                e = s + remaining
                dur = e - s
            else:
                # Video has reached max capacity
                break

        total_dur += dur
        sanitized_segments.append({
            "file_index": f_idx,
            "start": round(s, 2),
            "end": round(e, 2),
            "label": seg.get("label", f"Plan {len(sanitized_segments)+1}"),
        })

        if total_dur >= MAX_MONTAGE_DURATION:
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
    """Safe offline emergency plan with flexible duration up to 40s."""
    hook = (custom_hook or "LES COULISSES DU RESTAURANT").upper()
    dur_target = max(12.0, min(float(target_duration), 40.0))
    dur_per_clip = max(3.0, dur_target / max(1, len(video_paths)))
    segments = []
    total_len = 0.0
    for i, vp in enumerate(video_paths):
        v_dur = get_video_duration(vp)
        clip_len = round(min(dur_per_clip, v_dur), 2)
        segments.append({
            "file_index": i,
            "start": 0.0,
            "end": clip_len,
            "label": f"Rush {i+1}",
        })
        total_len += clip_len

    return {
        "type_contenu": "coulisses",
        "histoire_comprise": "Coulisses du restaurant BCHEF Bourges",
        "hook": hook,
        "description": "Retrouvez l'equipe BCHEF Bourges au quotidien.",
        "hashtags": ["#bchef", "#bourges", "#foodie", "#restaurant", "#viedequipe"],
        "mix_voix": True,
        "musique_style": music_mode if music_mode != "auto" else "comedy",
        "segments": segments,
        "sfx": [{"time": 4.0, "type": "whoosh", "volume": 0.85}],
        "transcription": [],
        "total_duration": round(total_len, 2),
        "model_used": "fallback-local",
    }
