# Guide de Déploiement VPS - BCHEF Bourges Automation

Ce guide détaille la mise en production de la solution d'automatisation des réseaux sociaux pour **BCHEF Bourges** sur un serveur VPS (24h/24, 7j/7).

---

## 1. Pré-requis Serveur

- **Système d'exploitation** : Ubuntu 22.04 / 24.04 LTS ou Debian 12
- **Configuration minimale** : 1 vCPU, 2 Go de RAM, 20 Go de disque SSD
- **Fournisseurs recommandés** :
  - **Oracle Cloud Free Tier** (VM.Standard.A1.Flex ou VM.Standard.E2.1.Micro - Gratuit à vie)
  - **Hetzner Cloud** (CX22 ~ 4€/mois)
  - **OVHcloud** (VPS Starter ~ 3.5€/mois)

---

## 2. Installation de Docker & Docker Compose sur le VPS

Connectez-vous en SSH à votre serveur VPS :

```bash
ssh utilisateur@ip_de_votre_vps
```

Mettez à jour le système et installez Docker avec le script officiel :

```bash
# Mise à jour des paquets
sudo apt-get update && sudo apt-get upgrade -y

# Installation de Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Donner les droits Docker à votre utilisateur (évite d'utiliser sudo à chaque fois)
sudo usermod -aG docker $USER
newgrp docker

# Vérification
docker --version
docker compose version
```

---

## 3. Transfert du Projet sur le VPS

### Option A : Par Git (Recommandé)

```bash
git clone <URL_DU_DEPOT_GIT> auto-publi
cd auto-publi
```

### Option B : Par SCP depuis votre machine locale

Depuis votre machine locale :

```bash
scp -r /home/adiack/Documents/perso/auto-publi utilisateur@ip_de_votre_vps:~/auto-publi
```

---

## 4. Configuration des Fichiers et Sessions

Accédez au dossier sur le VPS :

```bash
cd auto-publi
```

### A. Fichier d'environnement `.env`

Créez le fichier `.env` à partir du template :

```bash
cp .env.example .env
nano .env
```

Vérifiez que votre clé Google Gemini et vos identifiants de test y figurent :

```ini
GEMINI_API_KEY=AIzaSy...
PORT=8000
HOST=0.0.0.0

# Comptes de test actuels
INSTAGRAM_USERNAME=test_publi00
INSTAGRAM_PASSWORD=mad1234
TIKTOK_COOKIES_PATH=data/tiktok_cookies.json
```

### B. Sessions Instagram & TikTok

Assurez-vous que les sessions générées et testées sont bien présentes dans le dossier `data/` :
- `data/instagram_session.json` : session Instagram connectée.
- `data/tiktok_cookies.json` : cookies TikTok déchiffrés pour Playwright Studio.

Si vous avez besoin de copier les sessions depuis votre PC vers le VPS :

```bash
# Sur votre PC :
scp data/instagram_session.json utilisateur@ip_de_votre_vps:~/auto-publi/data/
scp data/tiktok_cookies.json utilisateur@ip_de_votre_vps:~/auto-publi/data/
```

---

## 5. Démarrage avec Docker Compose

Lancez la construction et le démarrage en arrière-plan :

```bash
docker compose up -d --build
```

### Vérifier l'état du conteneur :

```bash
docker compose ps
```

### Suivre les logs en temps réel :

```bash
docker compose logs -f
```

Vous devriez voir :
```text
Planificateur activé : publication programmée chaque jour à 11h30.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

---

## 6. Accès au Tableau de Bord Web

Ouvrez votre navigateur sur :
```
http://<IP_DE_VOTRE_VPS>:8000
```

> **Note Pare-feu** : Si la page ne s'ouvre pas, ouvrez le port 8000 sur le pare-feu du VPS :
> ```bash
> sudo ufw allow 8000/tcp
> sudo ufw reload
> ```
> *(Et sur la console cloud de votre hébergeur, ex: Oracle Cloud Security List / AWS Security Groups).*

---

## 7. Instance en Production (Oracle Cloud Always Free)

L'application est déployée et active sur le cloud Oracle en respectant strictement le palier **Always Free (100% gratuit à vie)** :

- **Adresse IP Publique** : `158.178.198.34`
- **Dashboard Web** : [http://158.178.198.34/](http://158.178.198.34/)
- **Statut API** : [http://158.178.198.34/api/status](http://158.178.198.34/api/status)
- **Forme Compute** : `VM.Standard.A1.Flex` (Ampere Arm, 1 OCPU, 2 Go RAM) — Quota Always Free : jusqu'à 4 OCPUs et 24 Go RAM.
- **Stockage Boot** : 47 Go SSD (Quota Always Free : jusqu'à 200 Go).
- **Reverse Proxy** : Nginx (port 80 -> port interne 8000).

### Sécurité Anti-Facturation Active (0 € garanti)

1. **Quotas de gouvernance OCI (`quota-securite-zero-euro`)** :
   - Plafond Ampere A1 : 4 OCPUs et 24 Go RAM maximum dans la tenancy.
   - Plafond Stockage : 200 Go maximum dans la tenancy.
   - Blocage dur (`zero quota`) de toutes les formes payantes : AMD E4, AMD E5, Intel Standard3, GPU A10.
   - Blocage dur (`zero quota`) des répartiteurs de charge payants (100 Mbps, 400 Mbps, 8 Gbps).
2. **Budget et Alertes Emails automatiques (`budget-securite-zero-euro`)** :
   - Plafond mensuel configuré : 1,00 €.
   - Règle 1 : Alerte dès 0,50 € de dépense réelle (`amadou.bchef@gmail.com`).
   - Règle 2 : Alerte dès 1,00 € de dépense réelle (`amadou.bchef@gmail.com`).
   - Règle 3 : Alerte dès prévision de dépassement de 1,00 € (`amadou.bchef@gmail.com`).


---

## 8. Fonctionnement Autonome & Rotation

1. **Cycle quotidien automatique** :
   - Chaque jour à **11h30 précises (Heure de Paris)**, le planificateur :
     1. Génère la Story Instagram avec la musique suggérée n°1 et les horaires d'ouverture du jour.
     2. Prend la vidéo en tête de file (`uploads/videos/`).
     3. Fait analyser l'audio et l'image par **Gemini 3.8 Flash** pour générer l'accroche, la description et les 5 hashtags.
     4. Incruste l'accroche sur fond blanc au centre de la vidéo.
     5. Publie le Reel Instagram géolocalisé `BCHEF Bourges (13 place Gordaine)` et le partage instantanément en Story.
     6. Publie la vidéo TikTok géolocalisée `BCHEF Bourges` via TikTok Studio.
     7. **Rotation / Archivage** : Déplace la vidéo originale publiée vers `processed/archive/AAAA-MM-JJ_nom.mp4`.
2. **Recyclage de secours** :
   - Si la file `uploads/videos/` est vide un jour donné, le robot pioche automatiquement la plus ancienne vidéo archivée et la recycle pour ne jamais rater une publication.
3. **Persistance des données** :
   - Les dossiers `uploads/`, `processed/`, et `data/` sont montés en volumes Docker et restent préservés même en cas de redémarrage ou de mise à jour du conteneur.

---

## 9. Commandes Utiles d'Exploitation

| Action | Commande |
| :--- | :--- |
| **Voir les logs en direct** | `docker compose logs -f --tail=100` |
| **Redémarrer le service** | `docker compose restart` |
| **Arrêter le service** | `docker compose down` |
| **Mettre à jour le code** | `git pull && docker compose up -d --build` |
| **Vérifier l'état de l'API** | `curl http://localhost:8000/api/status` |

---

## 10. Passage aux Comptes Officiels (Étape Ultérieure)

Lorsque le client validera la bascule sur les comptes officiels :
1. Modifiez les identifiants dans `.env` ou directement via l'onglet **Identifiants & IA** de l'interface Web.
2. Pour TikTok officiel, déposez les nouveaux cookies de session dans `data/tiktok_cookies.json`.
3. Redémarrez le conteneur (`docker compose restart`).

---

## 11. Pipeline CI/CD GitHub Actions (Déploiement Automatique)

Le dépôt dispose d'un pipeline d'intégration et de déploiement continu dans `.github/workflows/deploy.yml`.

À chaque `git push origin main` :
1. **Tests & Qualité** : Validation automatique de la syntaxe Python et des dépendances.
2. **Déploiement Continu** : Connexion SSH sécurisée au serveur VPS Oracle Cloud, mise à jour du code via `git pull` et reconstruction du conteneur Docker.

### Configuration des Secrets GitHub (À faire une seule fois)

Sur votre dépôt GitHub (`https://github.com/madptitprince/auto-publi`) :
1. Rendez-vous dans **Settings** > **Secrets and variables** > **Actions**
2. Cliquez sur **New repository secret** et ajoutez les secrets suivants :

| Nom du Secret | Valeur recommandée | Description |
| :--- | :--- | :--- |
| `VPS_HOST` | `158.178.198.34` | Adresse IP publique du VPS Oracle Cloud |
| `VPS_USER` | `ubuntu` | Utilisateur SSH par défaut |
| `VPS_SSH_KEY` | *(Contenu de `~/.ssh/id_ed25519`)* | Clé privée SSH permettant l'accès sans mot de passe |

Pour afficher votre clé privée à copier dans GitHub :
```bash
cat ~/.ssh/id_ed25519
```
