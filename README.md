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
   n8n ── synthèses ────┘
        ── watchdog
```

| Service | Rôle |
|---|---|
| `db` | PostgreSQL — news, signaux, trades, P&L, config de risque |
| `core` | FastAPI — ingestion, analyse LLM, risque, exécution, API, Web Push |
| `web` | PWA React servie par nginx (proxy `/api` → core) |
| n8n (le vôtre) | synthèses hebdo/mensuelles + watchdog |

## Installation sur le NAS

### 1. Cloner et configurer

```bash
git clone <ce-dépôt> && cd Trading
cp .env.example .env
```

Dans `.env`, renseignez :
- `MASTER_KEY` : générez-la avec `openssl rand -base64 32 | tr '+/' '-_'`
  (ou, après `docker compose build core` :
  `docker compose run --rm core python -m app.secrets gen-key`)
- `API_TOKEN` : `openssl rand -hex 32` — c'est le mot de passe de la PWA et de n8n
- changez `POSTGRES_PASSWORD`

### 2. Stocker les clés API (chiffrées)

Les credentials vivent dans `secrets/credentials.enc.json`, **chiffré**
(Fernet) avec votre `MASTER_KEY`, fichier en `chmod 600`, jamais commité.

```bash
docker compose build core
docker compose run --rm core python -m app.secrets set google_api_key
docker compose run --rm core python -m app.secrets set claude_code_oauth_token
docker compose run --rm core python -m app.secrets set finnhub_api_key
docker compose run --rm core python -m app.secrets gen-vapid   # clés Web Push
# plus tard, pour le mode réel :
docker compose run --rm core python -m app.secrets set trading212_api_key
docker compose run --rm core python -m app.secrets set kraken_api_key
docker compose run --rm core python -m app.secrets set kraken_api_secret
```

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

### 3. Lancer

```bash
docker compose up -d --build
```

La PWA est disponible sur `http://<IP-du-NAS>:8480` (port modifiable via
`WEB_PORT`). Connectez-vous avec votre `API_TOKEN`.

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

### 5. Brancher n8n

1. Importez les deux workflows du dossier `n8n/` dans votre n8n.
2. Ajoutez la variable d'environnement `NEWSTRADER_API_TOKEN` (= `API_TOKEN`) à n8n.
3. Si n8n tourne dans un autre réseau Docker que la stack, remplacez
   `http://core:8000` par `http://<IP-du-NAS>:8480` dans les nœuds HTTP
   (nginx proxyfie `/api` vers le core).
4. Dans le watchdog, remplacez le nœud « Alerte » par votre canal préféré.

Ce que font les workflows :
- **Synthèses** : dimanche 19h (hebdo) et le 1er du mois (mensuelle) — le core
  calcule P&L, taux de réussite, meilleur/pire trade, fait rédiger un
  commentaire par Claude et **pousse le tout sur votre téléphone**.
- **Watchdog** : toutes les 15 min, vérifie que le core répond et que
  l'ingestion de news n'est pas muette depuis plus de 2h.

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
   détecte les nouveaux commits, fait `git pull` + `docker compose up -d
   --build`, et envoie une notification push une fois redéployé. À planifier
   sur le NAS (Synology : Planificateur de tâches ; sinon cron) :

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
