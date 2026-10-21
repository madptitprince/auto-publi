import os
import re
import time
import json
from pathlib import Path
from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY


def clean_json_response(text: str) -> dict:
    """Extract and parse JSON safely from model response."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start:end+1]
    return json.loads(cleaned)


import subprocess
import tempfile


def create_preview_video(video_path: Path, output_preview_path: Path) -> Path:
    """
    Generates an ultra-lightweight 480p 12fps preview (~300-500 KB)
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
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if output_preview_path.exists() and output_preview_path.stat().st_size > 0:
            return output_preview_path
    except Exception:
        pass
    return video_path


def analyze_video_with_gemini(video_path: Path, api_key: str | None = None) -> dict:
    """
    Uploads the video to Google Gemini File API (with fast 480p preview).
    Gemini vision and audio transcribe exact spoken words, understand the scene context,
    and craft viral, dynamic hooks, descriptions and hashtags tailored for BCHEF Bourges.
    """
    # Check for optional background metadata (used as hint or emergency fallback)
    fallback_meta = None
    sidecar_json = video_path.with_suffix(".json")
    if sidecar_json.exists():
        try:
            with open(sidecar_json, "r", encoding="utf-8") as f:
                fallback_meta = json.load(f)
        except Exception as e_sidecar:
            print(f"Erreur lecture sidecar JSON : {e_sidecar}", flush=True)

    if not fallback_meta:
        for h_path in [
            Path(__file__).resolve().parent.parent / "montage_auto" / "data" / "history.json",
            Path("/app/montage_auto/data/history.json"),
            Path("montage_auto/data/history.json"),
        ]:
            if h_path.exists():
                try:
                    with open(h_path, "r", encoding="utf-8") as f:
                        hist = json.load(f)
                        for entry in hist:
                            if entry.get("filename") == video_path.name:
                                fallback_meta = entry
                                break
                except Exception:
                    pass

    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY

    if not active_key:
        print("Aucune clef GEMINI_API_KEY detectee. Mode fallback.", flush=True)
        if fallback_meta and fallback_meta.get("hook"):
            return {
                "source": "fallback_montage_meta",
                "transcription": fallback_meta.get("transcription", ""),
                "contexte": fallback_meta.get("contexte") or fallback_meta.get("histoire_comprise", ""),
                "hook": fallback_meta.get("hook", "").upper().strip(),
                "description": fallback_meta.get("description", ""),
                "hashtags": fallback_meta.get("hashtags", ["#bchef", "#bourges", "#restauration", "#viedequipe"]),
            }
        return {
            "source": "fallback",
            "transcription": "Transcription non disponible (clef manquante)",
            "contexte": "Coulisses du restaurant BCHEF Bourges",
            "hook": "L'EQUIPE BCHEF BOURGES PLACE GORDAINE",
            "description": "L'ambiance est toujours au rendez-vous chez BCHEF Bourges place Gordaine.",
            "hashtags": ["#bchef", "#bourges", "#burgerlovers", "#restobourges", "#foodiefr"],
        }

    video_file = None
    temp_preview = None
    try:
        client = genai.Client(api_key=active_key)

        # Generate fast preview for upload
        upload_target = video_path
        try:
            tmp_fd, tmp_prev_str = tempfile.mkstemp(suffix="_prev.mp4")
            os.close(tmp_fd)
            temp_preview = Path(tmp_prev_str)
            upload_target = create_preview_video(video_path, temp_preview)
        except Exception:
            upload_target = video_path

        print(f"Envoi de la video {upload_target.name} a l'API Gemini File...", flush=True)
        video_file = client.files.upload(file=str(upload_target))
        print(f"Fichier envoye : {video_file.name}, statut={video_file.state}", flush=True)

        # Wait if video is being processed by Gemini
        max_wait = 45
        waited = 0
        while video_file.state.name == "PROCESSING" and waited < max_wait:
            time.sleep(2)
            waited += 2
            video_file = client.files.get(name=video_file.name)

        extra_ctx = ""
        if fallback_meta:
            hint = fallback_meta.get("contexte") or fallback_meta.get("histoire_comprise") or fallback_meta.get("description")
            if hint:
                extra_ctx = f" (Information indicative sur la scene : {hint})"

        prompt = (
            "Tu es le Community Manager professionnel et Directeur Artistique officiel de BCHEF Bourges (13 place Gordaine, 18000 Bourges). "
            f"Visionne et ecoute attentivement cette video complete (visuel, jeu d'acteur, expressions, actions et bande-son/voix/musique){extra_ctx}.\n\n"
            "ADN EDITORIAL DE LA PAGE BCHEF BOURGES (base sur les posts historiques a plus fort engagement) :\n"
            "- Ton : Sitcom de restaurant, coulisses authentiques, second degre, auto-derision de l'equipe (Aly, Laindy, les equipiers en cuisine et au comptoir) et realite du rush en restauration.\n"
            "- A PROSCRIRE ABSOLUMENT : Le ton institutionnel, publicitaire ou corporate type brochure commerciale ('Venez deguster nos burgers prepares avec passion', 'Nouvelle carte meme plaisir') qui genere 0 engagement.\n"
            "- A PRIVILEGIER : L'humour de travail universel (le coup de feu, les pauses impossibles, les corvées refilees aux collegues, les clients inattendus, les departs surprises).\n\n"
            "CONSIGNES DE REDACTION :\n"
            "1. Transcription : Retranscris precisement les dialogues ou paroles entendues. "
            "Si la video est sans parole (gag visuel, mime, reaction, musique de fond, tendance TikTok), "
            "indique dans 'transcription' : 'Gag visuel sans parole' suivi d'un bref descriptif de l'action ou musique.\n"
            "2. Contexte : Resume le sens reel de la scene en une phrase explicite (comprends le second degre, le comique de situation ou la mise en valeur foodie).\n"
            "3. Hook (haut d'ecran) : 6 a 9 mots max, STRICTEMENT EN MAJUSCULES, percutant, concu pour stopper le scroll sur Reels/TikTok, parfaitement adapte a la scene, SANS AUCUN EMOJI.\n"
            "   Exemples de style : 'QUAND LE RUSH COMMENCE ET QUE TON COLLEGUE DISPARAIT', 'QUAND UNE CLIENTE DEPASSE TOTALEMENT LES BORNES', 'A PEINE ARRIVEE DEJA UN DOSSIER A TRAITER'.\n"
            "4. Description : Strictement 1 seule ligne, directe et naturelle, SANS AUCUN EMOJI. Choisis parmi les 3 formats qui cartonnent sur la page :\n"
            "   - Format Question / Debat : 'Et vous, vous arrivez a tenir combien de temps sans faire de pause en plein coup de feu ?'\n"
            "   - Format Tag collegue : 'Tague la personne de ton equipe a qui tu refiles toujours cette corvee en commentaire.'\n"
            "   - Format Punchline / Auto-derision : 'J'ai absolument rien vu pendant tout le service.' ou 'Chaque equipe a sa superstar qu'elle est toujours contente de voir.'\n"
            "5. Hashtags : Exactement 5 hashtags cibles sans emoji parmi #bchef #bourges #restauration #viedequipe #humour #convivial #burger.\n\n"
            "Reponds STRICTEMENT en format JSON valide :\n"
            "{\n"
            '  "transcription": "dialogue exact ou description du gag sonore/visuel",\n'
            '  "contexte": "explication de la situation et de l\'humour",\n'
            '  "hook": "ACCROCHE ECRAN PERCUTANTE EN MAJUSCULES SANS EMOJI",\n'
            '  "description": "description en 1 ligne sans emoji",\n'
            '  "hashtags": ["#bchef", "#bourges", "#restauration", "#viedequipe", "#humour"]\n'
            "}"
        )

        candidate_models = ["gemini-3-flash-preview", "gemini-3.7-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
        data = None
        last_error = None

        for model_name in candidate_models:
            try:
                print(f"Tentative d'analyse avec {model_name}...", flush=True)
                res = client.models.generate_content(
                    model=model_name,
                    contents=[video_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                data = clean_json_response(res.text)
                data["source"] = f"{model_name}-full-video"
                if "hook" in data and data["hook"]:
                    data["hook"] = data["hook"].upper().strip()
                print(f"Analyse reussie avec {model_name} ! Hook genere: {data.get('hook')}", flush=True)
                break
            except Exception as model_err:
                print(f"Echec avec {model_name} : {model_err}", flush=True)
                last_error = str(model_err)
                continue

        if not data:
            raise RuntimeError(f"Tous les modeles ont echoue. Derniere erreur : {last_error}")

        return data

    except Exception as e:
        print(f"Erreur lors de l'analyse video complete par Gemini: {e}", flush=True)
        if fallback_meta and fallback_meta.get("hook"):
            print(f"Secours sur metadonnees de montage pour {video_path.name}", flush=True)
            return {
                "source": "fallback_montage_meta",
                "transcription": fallback_meta.get("transcription", ""),
                "contexte": fallback_meta.get("contexte") or fallback_meta.get("histoire_comprise", ""),
                "hook": fallback_meta.get("hook", "").upper().strip(),
                "description": fallback_meta.get("description", ""),
                "hashtags": fallback_meta.get("hashtags", ["#bchef", "#bourges", "#restauration", "#viedequipe"]),
            }
        return {
            "source": "fallback_error",
            "error": str(e),
            "transcription": "Moment capture au restaurant BCHEF Bourges",
            "contexte": "Coulisses et quotidien du restaurant BCHEF",
            "hook": "L'EQUIPE DU RESTAURANT BCHEF BOURGES",
            "description": "Retrouvez l'equipe et les burgers gourmands au 13 place Gordaine a Bourges.",
            "hashtags": ["#bchef", "#bourges", "#restauration", "#viedequipe", "#burgerbourges"],
        }
    finally:
        if video_file:
            try:
                client.files.delete(name=video_file.name)
            except Exception:
                pass
        if temp_preview and temp_preview.exists():
            try:
                temp_preview.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    v_path = Path("uploads/videos/v1.MOV")
    if v_path.exists():
        analysis = analyze_video_with_gemini(v_path)
        print("Resultat de l'analyse complete :", json.dumps(analysis, indent=2, ensure_ascii=False))
