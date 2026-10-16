#!/usr/bin/env bash
set -e

# Script de déploiement automatique 1-clic pour VPS (Oracle Cloud / Ubuntu)
# Usage : ./deploy_to_vps.sh <IP_PUBLIQUE_DU_VPS> [UTILISATEUR]

VPS_IP="$1"
VPS_USER="${2:-ubuntu}"
SSH_KEY="$HOME/.ssh/id_ed25519"

if [ -z "$VPS_IP" ]; then
  echo "Usage: ./deploy_to_vps.sh <IP_DU_VPS> [USER (défaut: ubuntu)]"
  echo "Exemple: ./deploy_to_vps.sh 140.238.12.34"
  exit 1
fi

echo "============================================================"
echo "  Déploiement BCHEF Bourges Automation vers $VPS_USER@$VPS_IP"
echo "============================================================"

# 1. Vérification et attente de la connexion SSH
echo "[1/4] Attente de la disponibilité du serveur SSH..."
CONNECTED=0
for i in $(seq 1 30); do
  if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i "$SSH_KEY" "$VPS_USER@$VPS_IP" "echo 'Connexion SSH établie avec succès sur \$(uname -n).'" 2>/dev/null; then
    CONNECTED=1
    break
  fi
  echo "Attente du démarrage du serveur SSH (tentative $i/30)..."
  sleep 6
done

if [ "$CONNECTED" -eq 0 ]; then
  echo "Erreur : Impossible de joindre le serveur SSH après 30 tentatives."
  exit 1
fi

# 2. Installation de Docker et rsync sur le VPS si absent
echo "[2/4] Vérification et installation de Docker et rsync sur le VPS..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$VPS_USER@$VPS_IP" "bash -s" << 'EOF'
  sudo apt-get update -qq && sudo apt-get install -y -qq curl ca-certificates rsync
  if ! command -v docker &> /dev/null; then
    echo "Installation de Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo "Docker installé avec succès."
  else
    echo "Docker est déjà installé."
  fi
  # Démarrage du service Docker si nécessaire
  sudo systemctl enable --now docker
EOF

# 3. Transfert des fichiers du projet vers le VPS
echo "[3/4] Synchronisation des fichiers de l'application..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$VPS_USER@$VPS_IP" "mkdir -p ~/auto-publi"

tar --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='.tempmediaStorage' \
    --exclude='processed/videos/*' \
    --exclude='processed/stories/*' \
    --exclude='processed/archive/*' \
    --exclude='data/history.json' \
    --exclude='data/instagram_session.json' \
    --exclude='data/tiktok_cookies.json' \
    --exclude='montage_auto/outputs/*' \
    --exclude='montage_auto/scratch/*' \
    --exclude='montage_auto/rushs/**/*.MOV' \
    --exclude='montage_auto/rushs/**/*.mov' \
    --exclude='montage_auto/rushs/**/*.mp4' \
    --exclude='montage_auto/data/history.json' \
    --exclude='.env' \
    --exclude='*.log' \
    -czf - . | ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$VPS_USER@$VPS_IP" "tar -xzf - -C ~/auto-publi"

# 4. Lancement des conteneurs Docker avec docker compose et configuration Nginx
echo "[4/4] Configuration Nginx et démarrage des conteneurs en arrière-plan..."
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "$VPS_USER@$VPS_IP" "bash -s" << 'EOF'
  cd ~/auto-publi
  if [ ! -f .env ]; then
    cp .env.example .env 2>/dev/null || touch .env
  fi

  # Configuration du port de binding interne pour le Studio (proxy Nginx sur 8001)
  if ! grep -q "MONTAGE_PORT_BIND" .env; then
    echo "MONTAGE_PORT_BIND=127.0.0.1:8002" >> .env
  else
    sed -i 's/^MONTAGE_PORT_BIND=.*/MONTAGE_PORT_BIND=127.0.0.1:8002/' .env
  fi

  # Configuration pare-feu Ubuntu
  if command -v ufw &> /dev/null; then
    sudo ufw allow 80/tcp || true
    sudo ufw allow 443/tcp || true
    sudo ufw allow 8000/tcp || true
    sudo ufw allow 8001/tcp || true
    sudo ufw allow 22/tcp || true
  fi

  # Configuration Nginx avec SSL pour Auto-Publi (443) et Montage Studio (8001)
  if sudo test -f /etc/letsencrypt/live/bchef.duckdns.org/fullchain.pem; then
    sudo tee /etc/nginx/sites-available/default > /dev/null << 'NGINX_CONF'
server {
    listen [::]:443 ssl;
    listen 443 ssl;
    server_name bchef.duckdns.org;
    client_max_body_size 500M;

    location /studio/ {
        proxy_pass http://127.0.0.1:8002/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }

    location = /studio {
        return 301 https://$host/studio/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }

    ssl_certificate /etc/letsencrypt/live/bchef.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bchef.duckdns.org/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    listen [::]:8001 ssl;
    listen 8001 ssl;
    server_name bchef.duckdns.org;
    client_max_body_size 500M;

    error_page 497 https://$host:8001$request_uri;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 600s;
        proxy_send_timeout 600s;
        proxy_read_timeout 600s;
    }

    ssl_certificate /etc/letsencrypt/live/bchef.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bchef.duckdns.org/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = bchef.duckdns.org) {
        return 301 https://$host$request_uri;
    }

    listen 80 default_server;
    listen [::]:80 default_server;
    server_name bchef.duckdns.org;
    return 404;
}
NGINX_CONF
    sudo nginx -t && sudo systemctl restart nginx
  fi

  # Lancement Docker Compose (Auto-Publi + Montage Studio)
  sudo docker compose down || true
  sudo docker compose up -d --build
  echo "Attente de l'initialisation des serveurs..."
  sleep 6
  sudo docker compose ps
EOF

echo ""
echo "============================================================"
echo "  DÉPLOIEMENT TERMINÉ AVEC SUCCÈS !"
echo "  Tableau de bord Publication : https://bchef.duckdns.org"
echo "  Studio de Montage Vidéo      : https://bchef.duckdns.org/studio/ (ou :8001)"
echo "  Publication quotidienne active : 11h30 (Europe/Paris)"
echo "============================================================"
