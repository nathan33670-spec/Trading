# NewsTrader 📈

Bot de trading piloté par l'actualité, auto-hébergé sur votre NAS.
Il lit les news financières en continu, les fait analyser par **Claude** (avec
**Gemini** en contre-expertise), applique un **moteur de risque déterministe**
que vous configurez, exécute les ordres (simulés ou réels), et vous notifie sur
votre téléphone à chaque trade — avec synthèses hebdomadaires et mensuelles.

> ## ⚠️ À lire avant tout
> **Aucun bot ne "gagne de l'argent" garanti.** Le trading comporte un risque
> réel de perte en capital. C'est précisément pour ça que NewsTrader démarre en
> **paper trading** (argent fictif, prix réels) : laissez-le tourner 4 à 8
> semaines, jugez les chiffres dans l'onglet Rapports, et n'activez le mode réel
> que si — et seulement si — la stratégie est rentable sur la durée.
> N'engagez jamais d'argent dont vous avez besoin.

## Architecture

```
   RSS / Finnhub ──► core (FastAPI) ──► Claude + Gemini ──► signaux
                        │                                      │
                        │              moteur de risque ◄──────┘
                        │                     │
   PWA (téléphone) ◄────┤            courtiers : Paper (défaut)
   notifications push   │            Trading212 (actions/ETF, live)
                        │            Kraken (crypto, live)
   synthèses hebdo/     │
   mensuelles + watchdog┘  (intégrés au core)
```

| Service | Rôle |
|---|---|
| `db` | PostgreSQL — news, signaux, trades, P&L, config de risque |
| `core` | FastAPI — ingestion, analyse LLM, risque, exécution, API, Web Push, synthèses planifiées, watchdog |
| `web` | PWA React servie par nginx (proxy `/api` → core) |

## Installation sur le NAS

### 1. Récupérer le projet et configurer

Sans git (une archive suffit) :

```bash
curl -sfL https://api.github.com/repos/nathan33670-spec/Trading/tarball/main | tar xz
mv nathan33670-spec-Trading-* Trading && cd Trading
sh scripts/setup-env.sh
```

`setup-env.sh` crée le `.env` sans éditeur de texte : il génère le mot de
passe Postgres et **affiche votre `API_TOKEN`** — notez-le, c'est le mot de
passe de connexion à la PWA. La `MASTER_KEY` reste vide et sera générée
automatiquement au premier démarrage (la fournir vous-même dans `.env` —
`openssl rand -base64 32 | tr '+/' '-_'` — la sépare des données chiffrées,
un cran plus sûr).

(Avec git si vous l'avez : `git clone https://github.com/nathan33670-spec/Trading.git && cd Trading` —
le self-update utilisera alors `git pull` au lieu de l'archive. Si le dépôt
repasse en privé un jour : jeton lecture seule dans `GITHUB_TOKEN` du `.env`.)

### 2. Lancer

```bash
docker compose up -d --build
```

La PWA est disponible sur `http://<IP-du-NAS>:8480` (port modifiable via
`WEB_PORT`). Connectez-vous avec votre `API_TOKEN`. Les clés Web Push
(notifications) sont générées automatiquement au premier démarrage.

### 3. Saisir les clés API — dans l'app, rien en ligne de commande

**Réglages → Clés API (admin)** : collez chaque clé dans son champ. Elles sont
chiffrées côté serveur (Fernet, volume Docker dédié) et **ne redescendent
jamais dans le navigateur** — seul leur statut et les 4 derniers caractères
s'affichent. La même page montre en direct quel modèle joue l'analyste et
lequel donne le second avis.

<details>
<summary>Alternative en SSH (équivalente)</summary>

```bash
docker compose run --rm core python -m app.secrets set google_api_key
docker compose run --rm core python -m app.secrets set claude_code_oauth_token
docker compose run --rm core python -m app.secrets set finnhub_api_key
```
</details>

> Migration depuis une installation antérieure (dossier `./secrets` monté en
> bind) : les secrets vivent désormais dans le volume Docker `secrets_data` —
> re-saisissez simplement vos clés dans la PWA après la mise à jour.

### 💰 Coût zéro : tout tient dans vos abonnements existants

Le bot n'exige **aucune facturation API supplémentaire** :

| Clé | Où l'obtenir | Coût |
|---|---|---|
| `google_api_key` | [aistudio.google.com](https://aistudio.google.com) → *Get API key* | **0 €** — quota gratuit officiel de l'API Gemini (le bot utilise `gemini-2.5-flash`, dont le plafond gratuit journalier est large pour ce volume) |
| `claude_code_oauth_token` | `claude setup-token` sur n'importe quel ordinateur où la CLI [Claude Code](https://claude.com/claude-code) est connectée à votre compte | **0 €** — inclus dans votre abonnement **Claude Pro** (consomme votre quota d'abonnement, usage personnel) |
| `finnhub_api_key` | [finnhub.io](https://finnhub.io) | **0 €** (prix actions + news) |
| `trading212_api_key` | app Trading212 → Réglages → API | **0 €** (commencez par un compte **Practice**) |
| `kraken_api_key/secret` | [kraken.com](https://www.kraken.com) → Settings → API | **0 €** |
| `anthropic_api_key` | console.anthropic.com | *optionnelle* — uniquement si vous préférez l'API payante |

Comment le bot choisit ses modèles (`core/app/analysis/llm.py`) :
- **Analyste** : premier fournisseur disponible dans l'ordre
  Gemini (gratuit) → CLI Claude Code (abonnement) → API Anthropic (payante).
- **Second avis** : un fournisseur *différent* de l'analyste. Avec les deux
  clés gratuites ci-dessus, chaque signal est donc contre-expertisé
  Gemini × Claude, pour 0 €.
- Avec une seule clé, le bot fonctionne quand même : les signaux exigent alors
  une conviction ≥ 80 (seuil `solo_conviction`) faute de contre-expertise.

Deux limites honnêtes : le quota gratuit Gemini a un plafond journalier
(largement suffisant ici grâce au pré-filtre par mots-clés) et les appels via la
CLI Claude Code puisent dans le quota de votre abonnement Pro, partagé avec
votre propre usage — le bot ne l'appelle que pour les rares signaux, donc
l'impact est minime.

> ℹ️ Un abonnement Gemini (Google AI Pro/Advanced) ne change rien ici : c'est
> une offre grand public, séparée de l'API. La clé AI Studio est gratuite de
> toute façon.

### 4. Installer l'app sur le téléphone

1. Ouvrez l'URL de la PWA dans le navigateur du téléphone.
2. « Ajouter à l'écran d'accueil » (Android/Chrome : bannière automatique ;
   iOS/Safari : bouton Partager → Sur l'écran d'accueil).
3. Dans **Réglages → Notifications → Activer sur cet appareil**, puis « Tester ».

> 📱 **iOS** : les notifications push web exigent iOS 16.4+ **et** que l'app
> soit installée sur l'écran d'accueil, servie en **HTTPS**.
>
> 🌐 **Accès hors domicile + HTTPS** : le plus simple et le plus sûr est
> [Tailscale](https://tailscale.com) sur le NAS et le téléphone (VPN privé,
> certificats HTTPS via `tailscale cert`). Alternative : reverse proxy du NAS
> (Synology : Portail d'applications ; sinon Caddy/Traefik) avec certificat
> Let's Encrypt. N'exposez jamais le port en HTTP nu sur internet.

### 5. C'est tout — synthèses et watchdog sont intégrés

Aucun outil externe à brancher, le core fait tout lui-même :

- **Synthèses** : dimanche 19h (hebdo) et le 1er du mois à 9h (mensuelle) — le
  core calcule P&L, taux de réussite, meilleur/pire trade, fait rédiger un
  commentaire par le LLM et **pousse le tout sur votre téléphone**. Horaires
  réglables via `REPORT_WEEKLY_DAY/HOUR` et `REPORT_MONTHLY_DAY/HOUR`.
- **Watchdog** : toutes les 15 min, le core vérifie que l'ingestion de news
  n'est pas muette depuis plus de 2h (flux RSS morts, panne réseau…) et vous
  alerte par notification push — une seule alerte par incident. Réglable via
  `WATCHDOG_INTERVAL_MIN` et `WATCHDOG_NEWS_SILENCE_MIN`.
- **Crash du core** : couvert par Docker — `restart: unless-stopped` relance le
  conteneur, et le healthcheck rend l'état visible dans `docker compose ps`.

## Durcissement

L'app est pensée pour un réseau local ou un VPN, mais elle est durcie comme si
elle était exposée :

- **Authentification** : comparaison du jeton à temps constant ; verrouillage
  d'IP après 5 échecs (15 min), doublé d'un `limit_req` nginx sur le login.
- **Clés API write-only** : saisies dans la PWA, chiffrées (Fernet) dans un
  volume Docker dédié (`secrets_data`, fichier en `chmod 600`), jamais
  renvoyées au navigateur — statut et 4 derniers caractères seulement.
- **HTTP** : en-têtes de sécurité (CSP, `nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`), `server_tokens off`, corps de requête limité à 64 ko,
  documentation OpenAPI désactivée, réponses API en `no-store`.
- **Conteneurs** : le core tourne **non-root** avec `cap_drop: ALL` ;
  `no-new-privileges` sur les trois services ; healthchecks + `restart:
  unless-stopped`.
- Sauvegarde des secrets :
  `docker run --rm -v trading_secrets_data:/s alpine tar cz -C /s . > secrets-backup.tgz`
  (à conserver hors du NAS, comme la base).

Cela reste une défense en profondeur, pas une invitation : **n'exposez jamais
le port en HTTP nu sur internet** — Tailscale ou reverse proxy HTTPS.

## Fonctionnement

1. **Ingestion** (toutes les 5 min) : flux RSS (CoinDesk, Cointelegraph, Yahoo
   Finance, MarketWatch, Investing) + Finnhub. Dédoublonnage par empreinte de titre.
2. **Pré-filtre** : seules les news contenant des termes à fort impact
   (résultats, M&A, banques centrales, régulation crypto…) partent au LLM —
   c'est ce qui maintient le coût API très bas.
3. **Analyse** : l'analyste (Gemini par défaut, gratuit) reçoit le lot et
   n'émet un signal que si une actualité le justifie (actif, sens, conviction
   0-100, stop, objectif, raisonnement). Un **second modèle différent** (Claude
   via la CLI Claude Code par défaut) contre-expertise chaque signal : il faut
   **l'accord des deux** (ou une conviction ≥ 80 si un seul modèle est configuré).
4. **Moteur de risque** (jamais le LLM — 100 % déterministe) :
   - taille de position = `capital × risque% ÷ distance au stop`
   - plafonds : perte max/jour, perte max/semaine (kill-switch), nb de
     positions, exposition par actif, cash disponible
   - stop-loss et objectif **obligatoires** sur chaque trade
5. **Exécution** : Paper par défaut. Les bascules « réel » (Trading212 /
   Kraken) sont des interrupteurs distincts dans Réglages, avec confirmation.
6. **Suivi** : toutes les minutes, stops et objectifs sont contrôlés ; chaque
   ouverture/clôture déclenche une notification push avec le résultat.

## L'application

- **Dashboard** : valeur du portefeuille, P&L jour/semaine/mois, courbe
  d'équity 30 jours, positions ouvertes en temps réel, badge PAPER/LIVE.
- **Signaux** : le raisonnement de chaque analyse (Claude + avis Gemini), et
  pourquoi un signal a été exécuté ou rejeté (traçabilité complète).
- **Historique** : tous les trades, filtres, clôture manuelle, export CSV.
- **Rapports** : synthèses hebdo/mensuelles archivées.
- **Réglages** : curseurs de risque, kill-switch, bascules paper/réel,
  activation des notifications.

## Mise à jour automatique (self-update)

Deux mécanismes complémentaires :

1. **Maintenance du code par Claude (Routine hebdomadaire)** — une Routine
   Claude Code planifiée se réveille chaque lundi matin : elle vérifie que les
   flux RSS répondent encore, met à jour prudemment les dépendances, relance
   les tests et le build, corrige ce qui casse, puis pousse sur cette branche.
   Vous recevez une notification à chaque exécution. (Gérable depuis
   claude.ai/code → Routines ; couverte par votre abonnement Claude.)

2. **Redéploiement automatique sur le NAS** — `scripts/self-update.sh`
   détecte les nouveaux commits et fait `docker compose up -d --build`, puis
   envoie une notification push. **git n'est pas requis** : si le NAS n'en a
   pas, le script compare le dernier commit via l'API GitHub et télécharge
   l'archive de la branche (`.env` n'est jamais touché). À planifier sur le
   NAS (Synology : Planificateur de tâches ; sinon cron) :

   ```
   30 6 * * * /chemin/vers/Trading/scripts/self-update.sh >> /var/log/newstrader-update.log 2>&1
   ```

Le duo forme la boucle complète : Claude améliore le code chaque semaine → le
NAS se met à jour tout seul le lendemain matin → vous êtes notifié.

## Passage en réel — checklist

1. ≥ 4-8 semaines de paper trading.
2. Rapports : P&L net positif, drawdown supportable, assez de trades pour juger.
3. Commencez petit : `START_CAPITAL` réel modeste, risque à 0,5 %/trade.
4. Trading212 : testez d'abord avec une clé **Practice** (`T212_ENV=demo`,
   ordres réels sur compte fictif), puis passez `T212_ENV=live` dans
   l'environnement du service `core`.
5. Activez UNE plateforme à la fois et surveillez la première semaine.

## Développement

```bash
# API (SQLite local, sans Docker)
cd core && pip install -r requirements.txt
uvicorn app.main:app --reload

# Tests
python -m pytest tests/

# PWA
cd web && npm install && npm run dev   # proxy /api → localhost:8000
```

Pour tester la chaîne complète sans attendre une vraie actualité :

```bash
curl -X POST http://localhost:8000/api/test/inject-news \
  -H "X-API-Token: $API_TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "La SEC approuve un ETF Bitcoin spot, afflux record attendu"}'
```

## Limites connues (assumées)

- **Prix des actions** via Finnhub gratuit : tickers US principalement. Les
  ETF/actions EU passent par Trading212 en réel, mais le paper trading actions
  est le plus fiable sur les tickers US.
- **Positions longues uniquement** : un signal « sell » clôture une position,
  il n'ouvre pas de vente à découvert.
- **Matières premières** : pas d'API Revolut pour l'or/argent ; l'équivalent
  se trade via ETF/ETC (ex. or physique) côté Trading212.
- Les limites de perte jour/semaine comptent le P&L **réalisé**.
