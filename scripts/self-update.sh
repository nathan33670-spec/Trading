#!/usr/bin/env bash
# NewsTrader — self-update sur le NAS.
#
# Vérifie si la branche suivie a reçu de nouveaux commits ; si oui :
# git pull + rebuild + redéploiement docker compose, puis notification push.
#
# À planifier sur le NAS (Synology : Panneau de configuration → Planificateur
# de tâches ; sinon cron), par exemple tous les jours à 6h30 :
#   30 6 * * * /chemin/vers/Trading/scripts/self-update.sh >> /var/log/newstrader-update.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "$(date -Is) déjà à jour ($BRANCH @ ${LOCAL:0:8})"
  exit 0
fi

echo "$(date -Is) mise à jour: ${LOCAL:0:8} → ${REMOTE:0:8}"
git pull --ff-only origin "$BRANCH"
docker compose up -d --build

# Notification push (best effort) — nécessite API_TOKEN dans .env
if [ -f .env ]; then
  # shellcheck disable=SC1091
  . ./.env
  sleep 15
  curl -sf -X POST "http://localhost:${WEB_PORT:-8480}/api/push/test" \
    -H "X-API-Token: ${API_TOKEN:-}" >/dev/null \
    && echo "$(date -Is) notification de mise à jour envoyée" \
    || echo "$(date -Is) notification non envoyée (service pas encore prêt ?)"
fi

echo "$(date -Is) redéployé ($BRANCH @ ${REMOTE:0:8})"
