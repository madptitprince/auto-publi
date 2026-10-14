# Cahier des Charges - Automatisation CM BCHEF Bourges

## 1. Contexte & Objectif
Automatiser la présence quotidienne sur les réseaux sociaux pour le restaurant **BCHEF Bourges** :
- Publication quotidienne programmée à **11h30** sur **Instagram** et **TikTok**.
- Phase 1 : Tests sur des comptes Instagram et TikTok dédiés aux tests.
- Phase 2 : Bascule sur les comptes officiels.

---

## 2. Horaires d'Ouverture du Restaurant
Les horaires configurés dans le système pour les stories :
- **Lundi à Jeudi** : 11h00 - 22h45
- **Vendredi et Samedi** : 11h00 - 23h30
- **Dimanche** : 11h00 - 22h00

---

## 3. Les Formats de Publication Quotidienne (11h30)

### A. Story Instagram ("Le restaurant est ouvert")
- **Fréquence** : 1 story chaque jour à 11h30.
- **Ressource** : Sélection d'une photo parmi le stock du dossier `photos_stories/` (sélection aléatoire sans répétition immédiate).
- **Visuel généré** :
  - Photo de fond adaptée au format 9:16.
  - Badge graphique *"BCHEF Bourges est Ouvert !"*.
  - Horaires dynamiques du jour incrustés élégamment.

### B. Vidéo Reel (Instagram) & Vidéo (TikTok)
- **Fréquence** : 1 vidéo chaque jour à 11h30.
- **Ressource** : Sélection parmi les vidéos montées déposées dans la file d'attente.
- **Traitement IA (Gemini + Whisper)** :
  - Analyse audio (transcription des paroles/voix off si existante).
  - Analyse visuelle des scènes de la vidéo (produits phares : burgers, bagels, frites, cookies, etc.).
  - Génération d'un **Hook** (accroche percutante).
  - Génération d'une **description en 1 ligne**.
  - Génération de **5 hashtags optimisés** (ex: `#bchef #bourges #burgerlovers #restobourges #foodie`).
- **Post-traitement vidéo (FFmpeg)** :
  - Incrustation du texte d'accroche (Hook) à l'écran sur les 3 à 5 premières secondes (style moderne, typographie lisible, couleurs de la marque).
- **Publication** :
  - Publication simultanée sur Instagram (Reel) et TikTok.

---

## 4. Architecture Technique

### Stack Logicielle
- **Backend & Moteur** : Python 3 (FastAPI ou Flask)
- **Traitement Vidéo & Image** :
  - `ffmpeg` pour le découpage et l'incrustation du Hook sur la vidéo.
  - `Pillow` pour la création dynamique des visuels de Story.
- **Intelligence Artificielle** :
  - `google-genai` (Gemini Flash) pour l'analyse visuelle multimodale et la rédaction publicitaire.
  - `whisper` (ou API) pour la transcription audio.
- **Publication Réseaux Sociaux** :
  - Instagram : `instagrapi` / Playwright.
  - TikTok : Automatisation navigateur avec sessions persistantes (Playwright).
- **Planificateur** : `APScheduler` / Cron réglé sur 11h30 chaque jour.
- **Interface Utilisateur** : Web UI épurée pour :
  - Glisser-déposer les vidéos montées.
  - Consulter la file d'attente des vidéos.
  - Ajouter/gérer les photos pour les stories.
  - Prévisualiser le visuel de la story et la vidéo avec son hook avant publication.
  - Déclencher une publication de test manuelle en 1 clic.

---

## 5. Environnement & Hébergement
1. **Étape 1 (Actuelle)** : Exécution locale sur machine Linux.
2. **Étape 2** : Déploiement facile sur un VPS gratuit (ex. Oracle Cloud Compute ARM / Ubuntu) via Docker pour tourner 24h/24 sans dépendre du PC local.
