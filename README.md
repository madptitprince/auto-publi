# BCHEF Bourges - Automatisation Quotidienne (11h30)

Automatisation complète de la présence sur **Instagram (Story avec Musique + Reels + Partage Story)** et **TikTok (Studio + Géolocalisation)** pour le restaurant **BCHEF Bourges** (13 place Gordaine, 18000 Bourges).

---

## Démarrage Rapide

### En local :
```bash
./start.sh
```
Puis accédez au tableau de bord sur **[http://localhost:8000](http://localhost:8000)**.

### Sur serveur VPS (Docker 24h/24) :
```bash
docker compose up -d --build
```
Consultez le guide complet de déploiement dans [DEPLOY.md](file:///home/adiack/Documents/perso/auto-publi/DEPLOY.md).

---

## Fonctionnalités Validées & En Production

1. **Générateur de Story Quotidienne avec Musique Tendances** ([src/story_generator.py](file:///home/adiack/Documents/perso/auto-publi/src/story_generator.py)) :
   * Sélectionne aléatoirement une photo parmi les 22 templates de story dans `uploads/stories/`.
   * Calcule le jour actuel et injecte automatiquement les horaires exacts :
     * **Lundi à Jeudi** : 11h00 - 22h45
     * **Vendredi et Samedi** : 11h00 - 23h30
     * **Dimanche** : 11h00 - 22h00
   * Typographie blanche en gras (`LiberationSans-Bold`) sans parenthèses, positionnée sous *ouvert !*.
   * **Musique suggérée n°1** récupérée directement via l'API Instagram Trends et fusionnée avec la story.

2. **Incrustation Vidéo Hook avec FFmpeg** ([src/video_processor.py](file:///home/adiack/Documents/perso/auto-publi/src/video_processor.py)) :
   * Carte blanche épurée avec texte sombre haute lisibilité et ombre douce.
   * Reste affichée jusqu'à la fin de la vidéo, positionnée dans le tiers supérieur (19%).
   * Fichier MP4 H.264/AAC optimisé mobile + photo miniature de couverture.

3. **Analyse IA Multimodale (Gemini 3.8 Flash)** ([src/ai_analyzer.py](file:///home/adiack/Documents/perso/auto-publi/src/ai_analyzer.py)) :
   * Analyse native audio + flux vidéo complet.
   * Retranscription fidèle des dialogues ou compréhension des gags visuels sans parole (mimes, réactions, musique).
   * Génération :
     * 1 **Hook** percutant pour l'écran (sans emoji)
     * 1 **Description** dynamique d'une seule ligne (sans emoji)
     * Exactement **5 hashtags** ciblés (sans emoji)

4. **Publication Instagram Live** ([src/publisher/instagram.py](file:///home/adiack/Documents/perso/auto-publi/src/publisher/instagram.py)) :
   * Publication de Story avec musique tendance.
   * Publication de Reel avec géolocalisation officielle `BCHEF (13 Place Gordaine)`.
   * **Partage automatique immédiat du Reel en Story**.

5. **Publication TikTok Live** ([src/publisher/tiktok.py](file:///home/adiack/Documents/perso/auto-publi/src/publisher/tiktok.py)) :
   * Automatisation Playwright sur TikTok Studio Upload avec session cookies persistée.
   * Géolocalisation automatique `BCHEF Bourges`.

6. **Rotation & Archivage Automatique** ([src/scheduler.py](file:///home/adiack/Documents/perso/auto-publi/src/scheduler.py)) :
   * Chaque vidéo publiée est automatiquement déplacée dans `processed/archive/AAAA-MM-JJ_nom.mp4`.
   * **Recyclage de secours** : si la file d'attente est vide, le planificateur recycle automatiquement la plus ancienne vidéo archivée pour garantir la continuité des publications sans rupture.
   * Restauration, archivage manuel et prévisualisation depuis l'interface Web.

7. **Interface Web de Gestion CM** ([http://localhost:8000](http://localhost:8000)) :
   * Tableau de bord sans emoji avec icônes SVG et design sombre moderne.
   * Gestion de la file d'attente et des archives avec compteurs en temps réel.
   * Galerie des templates de stories avec aperçu direct.
   * Visualisation de la transcription audio et du contexte IA.
   * Déclencheur manuel en 1 clic pour tester la publication.

8. **Packaging Docker & VPS** ([Dockerfile](file:///home/adiack/Documents/perso/auto-publi/Dockerfile), [docker-compose.yml](file:///home/adiack/Documents/perso/auto-publi/docker-compose.yml)) :
   * Image Docker Python 3.11 avec FFmpeg, Playwright Chromium et fuseau horaire `Europe/Paris`.
   * Volumes persistants pour les vidéos, templates et sessions.
   * Prêt pour hébergement 24/7 sur VPS (Oracle Cloud Free Tier, Hetzner, etc.).

---

## Comptes de Test Utilisés

- **Instagram** : `test_publi00` (Session persistée dans `data/instagram_session.json`)
- **TikTok** : `testpubli00` (Cookies de session dans `data/tiktok_cookies.json`)

*(La bascule sur les comptes officiels sera effectuée ultérieurement lors de la validation client).*
