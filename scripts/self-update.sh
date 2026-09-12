#!/bin/sh
# NewsTrader — self-update sur le NAS, avec ou sans git.
#
# - Dossier cloné avec git  : fetch + pull --ff-only + rebuild.
# - Installé par archive (pas de git sur le NAS) : compare le dernier commit
#   GitHub avec .deployed-commit, télécharge l'archive et redéploie.
#   Le fichier .env n'est jamais touché (absent de l'archive).
#
# Dépôt privé : mettre GITHUB_TOKEN=<token lecture seule> dans .env.
#
# À planifier sur le NAS (Synology : Planificateur de tâches ; sinon cron) :
#   30 6 * * * /chemin/vers/Trading/scripts/self-update.sh >> /var/log/newstrader-update.log 2>&1
set -eu

REPO="${NEWSTRADER_REPO:-nathan33670-spec/Trading}"
BRANCH="${NEWSTRADER_BRANCH:-main}"
now() { date '+%F %T'; }

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  # shellcheck disable=SC1091
  . ./.env
fi

gh_curl() {
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    curl -sfL -H "Authorization: Bearer $GITHUB_TOKEN" "$@"
  else
    curl -sfL "$@"
  fi
}

notify() {
  sleep 15
  curl -sf -X POST "http://localhost:${WEB_PORT:-8480}/api/push/test" \
    -H "X-API-Token: ${API_TOKEN:-}" >/dev/null \
    && echo "$(now) notification de mise à jour envoyée" \
    || echo "$(now) notification non envoyée (service pas encore prêt ?)"
}

update_git() {
  BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git fetch origin "$BRANCH" --quiet
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse "origin/$BRANCH")
  if [ "$LOCAL" = "$REMOTE" ]; then
    echo "$(now) déjà à jour ($BRANCH @ $(echo "$LOCAL" | cut -c1-8))"
    return 0
  fi
  echo "$(now) mise à jour: $(echo "$LOCAL" | cut -c1-8) → $(echo "$REMOTE" | cut -c1-8)"
  git pull --ff-only origin "$BRANCH"
  docker compose up -d --build
  notify
  echo "$(now) redéployé ($BRANCH @ $(echo "$REMOTE" | cut -c1-8))"
}

update_archive() {
  LATEST=$(gh_curl "https://api.github.com/repos/$REPO/commits/$BRANCH" \
    | grep -m1 '"sha"' | cut -d '"' -f4) || LATEST=""
  if [ -z "$LATEST" ]; then
    echo "$(now) API GitHub injoignable (dépôt privé sans GITHUB_TOKEN dans .env ?) — nouvel essai au prochain passage"
    return 1
  fi

  CURRENT=$(cat .deployed-commit 2>/dev/null || echo "aucun")
  if [ "$LATEST" = "$CURRENT" ]; then
    echo "$(now) déjà à jour ($BRANCH @ $(echo "$LATEST" | cut -c1-8))"
    return 0
  fi

  echo "$(now) mise à jour: $(echo "$CURRENT" | cut -c1-8) → $(echo "$LATEST" | cut -c1-8)"
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  gh_curl "https://api.github.com/repos/$REPO/tarball/$BRANCH" | tar xz -C "$TMP"
  cp -a "$TMP"/*/. .

  docker compose up -d --build
  echo "$LATEST" > .deployed-commit
  notify
  echo "$(now) redéployé ($BRANCH @ $(echo "$LATEST" | cut -c1-8))"
}

main() {
  if [ -d .git ] && command -v git >/dev/null 2>&1; then
    update_git
  else
    update_archive
  fi
}

# Tout passe par main : le shell a fini de lire le fichier avant d'exécuter,
# le script peut donc se remplacer lui-même sans risque pendant la mise à jour.
main "$@"; exit $?
