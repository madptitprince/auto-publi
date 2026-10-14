#!/usr/bin/env bash
set -e

# Se placer dans le répertoire du projet
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

# Vérifier et ajouter les binaires locaux au PATH (ffmpeg, uv)
export PATH="$HOME/.local/bin:$PATH"

# Vérifier l'environnement virtuel
if [ ! -d ".venv" ]; then
    echo "Initialisation de l'environnement virtuel..."
    uv venv .venv
    source .venv/bin/activate
    uv pip install -r requirements.txt
else
    source .venv/bin/activate
fi

echo "=========================================================="
echo "  🍔 BCHEF BOURGES - AUTOMATE RÉSEAUX SOCIAUX (11h30)   "
echo "=========================================================="
echo "  Interface Web disponible sur : http://localhost:8000    "
echo "  Planification active : tous les jours à 11h30          "
echo "=========================================================="

# Lancer le serveur web FastAPI
exec uvicorn src.web.app:app --host 0.0.0.0 --port 8000 --reload
