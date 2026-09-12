#!/bin/sh
# Crée le fichier .env sans éditeur de texte : mots de passe générés,
# valeurs par défaut saines. À lancer une seule fois après le téléchargement.
#
#   sh scripts/setup-env.sh
#
# Ne touche jamais à un .env existant.
set -eu
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env existe déjà — rien n'a été modifié."
  exit 0
fi

rand_hex() { openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

API_TOKEN=$(rand_hex 32)
PG_PASS=$(rand_hex 16)

sed -e "s/^API_TOKEN=.*/API_TOKEN=$API_TOKEN/" \
    -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$PG_PASS/" \
    .env.example > .env
chmod 600 .env

echo "Fichier .env créé (mot de passe Postgres généré aussi)."
echo
echo "  Mot de passe de l'app (API_TOKEN) :"
echo
echo "  $API_TOKEN"
echo
echo "NOTEZ-LE : c'est lui qui ouvre la PWA. Il reste lisible dans ./.env."
