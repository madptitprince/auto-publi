flowchart TD
    subgraph Sourcing ["1. Gestion des Médias & Interface"]
        UI["Interface Web d'Upload & Dashboard"] --> StockV["Dossier Vidéos en attente"]
        UI --> StockP["Dossier Photos Stories (banque d'images)"]
    end

    subgraph Intelligence ["2. Traitement & IA (Gemini / Whisper)"]
        StockV --> Transc["Transcription Audio (Whisper)"]
        StockV --> Vision["Analyse Visuelle de la vidéo (Gemini)"]
        Transc & Vision --> Gen["Génération automatique :\n- Hook écran\n- Description 1 ligne\n- 5 Hashtags pertinents"]
        Gen --> FFMPEG["FFmpeg : Incrustation texte 'Hook' sur la vidéo"]
        StockP --> ImgProc["Génération Story du jour :\nPhoto aléatoire + Incrustation Horaires du jour"]
    end

    subgraph Publishing ["3. Publication Quotidienne (11h30)"]
        Scheduler["Planificateur automatique (Cron / 11h30)"]
        FFMPEG --> Scheduler
        ImgProc --> Scheduler
        Scheduler --> Insta["Instagram (Story + Reel)"]
        Scheduler --> TikTok["TikTok (Vidéo)"]
    end
