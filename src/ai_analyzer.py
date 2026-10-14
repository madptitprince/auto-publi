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


def analyze_video_with_gemini(video_path: Path, api_key: str | None = None) -> dict:
    """
    Uploads the entire video (audio + visual) to Google Gemini File API.
    Gemini 3.8 Flash transcribes the exact spoken words, understands the scene context,
    and crafts viral hooks, descriptions and hashtags tailored for BCHEF Bourges.
    """
    active_key = api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY

    if not active_key:
        print("Aucune clef GEMINI_API_KEY detectee. Mode fallback.")
        return {
            "source": "fallback",
            "transcription": "Transcription non disponible (clef manquante)",
            "contexte": "Coulisses de la cuisine du restaurant BCHEF Bourges",
            "hook": "L'equipe BCHEF Bourges avant le grand rush du midi",
            "description": "L'ambiance est toujours au rendez-vous chez BCHEF Bourges place Gordaine.",
            "hashtags": ["#bchef", "#bourges", "#burgerlovers", "#restobourges", "#foodiefr"],
        }

    video_file = None
    try:
        client = genai.Client(api_key=active_key)
        print(f"Envoi de la video {video_path.name} a l'API Gemini File...")

        video_file = client.files.upload(file=str(video_path))
        print(f"Fichier envoye : {video_file.name}, statut={video_file.state}")

        # Wait if video is being processed by Gemini
        max_wait = 45
        waited = 0
        while video_file.state.name == "PROCESSING" and waited < max_wait:
            time.sleep(3)
            waited += 3
            video_file = client.files.get(name=video_file.name)

        prompt = (
            "Tu es le Community Manager professionnel de BCHEF Bourges (13 place Gordaine, 18000 Bourges). "
            "Visionne et ecoute attentivement cette video complete (visuel, jeu d'acteur, expressions, actions et bande-son/voix/musique). "
            "Consignes strictes : "
            "1. Retranscris precisement les dialogues ou paroles entendues. "
            "Si la video est sans parole (gag visuel, mime, reaction, musique de fond, tendance TikTok), "
            "indique dans 'transcription' : 'Gag visuel sans parole' suivi d'un bref descriptif de l'action ou musique. "
            "2. Resume le contexte de la scene en une phrase explicite (comprends le second degre, l'humour en cuisine, les reactions de l'equipe ou la mise en valeur des produits BCHEF). "
            "3. Concois un texte d'accroche (Hook) pour le haut de l'ecran : court (8 a 10 mots max), "
            "dynamique, percutant pour TikTok / Reels, parfaitement adapte a la situation comique ou au sujet, et SANS AUCUN EMOJI. "
            "4. Rédige une description de post en 1 seule ligne engageante, invitant a reagir en commentaire, SANS AUCUN EMOJI. "
            "5. Fournis exactement 5 hashtags pertinents, sans emoji. "
            "Reponds STRICTEMENT en format JSON valide :\n"
            "{\n"
            '  "transcription": "dialogue exact ou description du gag sonore/visuel",\n'
            '  "contexte": "explication de la situation et de l\'humour",\n'
            '  "hook": "accroche ecran percutante sans emoji",\n'
            '  "description": "description en 1 ligne sans emoji",\n'
            '  "hashtags": ["#bchef", "#bourges", "#tag3", "#tag4", "#tag5"]\n'
            "}"
        )

        candidate_models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]
        data = None
        last_error = None

        for model_name in candidate_models:
            try:
                print(f"Tentative d'analyse avec {model_name}...")
                res = client.models.generate_content(
                    model=model_name,
                    contents=[video_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        http_options={"timeout": 30000},
                    ),
                )
                data = clean_json_response(res.text)
                data["source"] = f"{model_name}-full-video"
                print(f"Analyse reussie avec {model_name} !")
                break
            except Exception as model_err:
                print(f"Echec avec {model_name} : {model_err}")
                last_error = str(model_err)
                continue

        if not data:
            raise RuntimeError(f"Tous les modeles ont echoue. Derniere erreur : {last_error}")

        return data

    except Exception as e:
        print(f"Erreur lors de l'analyse video complete par Gemini: {e}")
        return {
            "source": "fallback_error",
            "error": str(e),
            "transcription": "Erreur lors de la recuperation audio",
            "contexte": "Coulisses du restaurant BCHEF",
            "hook": "Quand la responsable n'est pas la pendant le rush",
            "description": "Decouvrez l'envers du decor et l'ambiance chez BCHEF Bourges place Gordaine.",
            "hashtags": ["#bchef", "#bourges", "#restauration", "#viedequipe", "#burgerbourges"],
        }
    finally:
        if video_file:
            try:
                client.files.delete(name=video_file.name)
            except Exception:
                pass


if __name__ == "__main__":
    v_path = Path("uploads/videos/v1.MOV")
    if v_path.exists():
        analysis = analyze_video_with_gemini(v_path)
        print("Resultat de l'analyse complete :", json.dumps(analysis, indent=2, ensure_ascii=False))
