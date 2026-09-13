# NewsTrader 📈

Bot de trading auto-hébergé sur votre NAS, piloté par deux moteurs :

- **la stratégie de régime** sur la crypto — investi tant que le prix est
  au-dessus de son niveau d'il y a 12 mois, en cash sinon. Déterministe, sans
  aucune clé API, quelques mouvements par an.
- **l'actualité financière**, analysée par **Gemini** avec **Claude** en
  contre-expertise.

Les deux alimentent un **moteur de risque déterministe** que vous configurez
(enveloppes, frais), qui exécute les ordres (simulés ou réels) et vous notifie.

### Ce que donne la stratégie sur BTC/EUR, frais Revolut inclus

Mise de départ 10 000 €, mesuré sur les bougies réelles depuis 2016 :

| Période | Stratégie | Achat-conservation | Pire baisse |
|---|---|---|---|
| **5 dernières années** | **29 440 €** (23,7 %/an) | 16 372 € (10,2 %/an) | **−47 %** contre −74 % |
| **3 dernières années** | **29 164 €** (41,6 %/an) | 24 452 € (33,7 %/an) | **−32 %** contre −52 % |
| Tout l'historique (9,4 ans) | 367 708 € (46,7 %/an) | 586 295 € (54,2 %/an) | −83 % contre −83 % |

Sur les périodes récentes, la stratégie bat nettement l'achat-conservation avec
une baisse maximale bien moindre. Sur l'historique complet elle reste derrière :
2016-2017 a monté presque sans interruption, et tout filtre y coûte cher.
**Aucune de ces observations ne prédit l'avenir** — le backtest est rejouable à
tout moment depuis l'onglet Marché.

> ## ⚠️ À lire avant tout
> **Aucun bot ne "gagne de l'argent" garanti.** Le trading comporte un risque
> réel de perte en capital. C'est précisément pour ça que NewsTrader démarre en
> **paper trading** (argent fictif, prix réels) : laissez-le tourner 4 à 8
> semaines, jugez les chiffres dans l'onglet Rapports, et n'activez le mode réel
> que si — et seulement si — la stratégie est rentable sur la durée.
> N'engagez jamais d'argent dont vous avez besoin.

## Architecture

```
   Historique Bitstamp ──► stratégie de régime ──┐
   (10 ans, sans clé)      (momentum 12 mois)    │
                                                 ├──► moteur de risque
   RSS / Finnhub ──────► Gemini + Claude ────────┘    enveloppes, frais
                        │                                    │
   PWA (téléphone) ◄────┤              courtiers : Paper (défaut)
   notifications push   │              Trading212 (actions/ETF, live)
                        │              Kraken (crypto, live)
   synthèses + watchdog ┘  (intégrés au core)
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

### Moteur 1 — stratégie de régime (crypto, sans clé API)

**Investir si le prix est au-dessus de son niveau d'il y a 12 mois, rester en
cash sinon.** Signal vérifié une fois par semaine, quelques mouvements par an.

C'est le signal le plus documenté de la finance quantitative (momentum 12 mois :
Jegadeesh & Titman, Faber, Antonacci) — pas une trouvaille maison. Il a été
retenu après avoir mesuré une dizaine de familles de stratégies sur 10 ans de
BTC/EUR et quatre sous-périodes. Les résultats sont en tête de ce README.

Trois enseignements du banc d'essai, qui expliquent chaque choix :

1. **Une stratégie jugée sur une seule période ne vaut rien.** Une première
   version de ce bot faisait du swing trading et perdait −1 042 € au backtest —
   testée uniquement sur 2024-2026, un marché baissier. Sur 10 ans, *toutes* les
   stratégies longues gagnent : la fenêtre de test décidait du verdict, pas la
   stratégie.
2. **Les frais dictent la fréquence.** À ~3 % l'aller-retour, une stratégie qui
   trade souvent est condamnée d'avance : le filtre SMA50 a payé 567 000 € de
   frais sur 10 ans, contre 21 000 € pour le momentum 12 mois.
3. **Il faut laisser courir les gagnants.** Les objectifs fixes à 2R plafonnent
   les gains alors que les tendances crypto courent sur 5 à 20R. D'où l'absence
   d'objectif de prix ici : la sortie vient du signal.

Ce que la calibration a aussi montré, et qui est appliqué :

- **Uniquement BTC** (et, moins nettement, ETH). Le même filtre testé sur XRP,
  LTC, LINK et ADA détruit le capital : leurs hausses sont trop brèves pour un
  signal à 12 mois.
- **Contrôle hebdomadaire**, pas quotidien : 32 mouvements en 10 ans si on
  vérifie chaque jour, 15 en vérifiant chaque semaine — pour un rendement moyen
  supérieur (mesuré sur tous les décalages de jour possibles, pour ne pas
  confondre un bon réglage avec un coup de chance).
- **Pas de stop serré**, seulement un garde-fou catastrophe à −50 %.

> Une validation « hors échantillon » a été faite : les paramètres choisis sur
> 2016-2021 puis appliqués tels quels à 2021-2026 se sont effondrés (5,4 %/an
> contre 19,2 % pour l'achat-conservation). C'est la démonstration du
> sur-ajustement — et la raison pour laquelle le réglage retenu est le signal
> standard, pas celui qui brillait le plus sur l'historique.

### Sur quels actifs cette stratégie a été validée — et sur lesquels elle échoue

Le filtre a été testé sur 11 actifs hors crypto (20 ans de données Yahoo,
2006-2026, krachs de 2008, 2020 et 2022 inclus), avec les frais correspondants.
Verdict : **il ne bat l'achat-conservation sur aucun d'entre eux**, mais réduit
le drawdown sur 10 sur 11.

| Actif | Stratégie | Achat-conservation | Pire baisse | Verdict |
|---|---|---|---|---|
| **BTC/EUR** (5 ans) | **23,7 %/an** | 10,2 %/an | −47 % vs −74 % | ✅ utilisé |
| **ETH/EUR** (3 ans) | **11,6 %/an** | 8,0 %/an | −46 % vs −67 % | ⚠️ possible |
| S&P 500 (20 ans) | 6,7 %/an | 8,9 %/an | **−22 % vs −57 %** | ❌ non retenu |
| Nasdaq 100 (20 ans) | 13,2 %/an | 14,9 %/an | **−30 % vs −54 %** | ❌ non retenu |
| Apple, Microsoft | nettement en dessous | — | à peine mieux | ❌ non retenu |
| Or, Argent | 5,7 / 9,9 %/an | 10,0 / 13,1 %/an | un peu mieux | ❌ non retenu |
| Pétrole, Cuivre, Gaz, Maïs | ≤ 2,3 %/an | mieux | mieux | ❌ non retenu |

Pourquoi cette différence, actif par actif :

* **La crypto a des marchés baissiers de plusieurs années** (−70 à −80 %).
  Sortir pendant ces phases fait gagner plus que rater quelques rebonds ne fait
  perdre. C'est là que le filtre paie.
* **Les actions montent presque tout le temps.** Être hors marché pendant les
  reprises coûte davantage que d'éviter les krachs ne rapporte. Le filtre reste
  un bon outil de *réduction du risque* (drawdown divisé par deux sur le
  S&P 500), mais il fait perdre 1,4 à 2,2 points de rendement annuel — y compris
  en tenant compte d'un cash rémunéré à 3 % et de frais à 0,15 %.
* **Les matières premières oscillent sans tendance durable.** Le signal se
  retourne sans arrêt : 91 allers-retours sur le maïs, 76 sur le gaz. Chaque
  retournement coûte des frais et arrive trop tard.

Conséquence assumée : **la stratégie de régime ne s'applique qu'à BTC**
(ETH en option). Les matières premières ne sont pas gérées du tout —
l'application ne connaît que les classes action, ETF et crypto. Pour les
actions, seul le moteur d'actualité reste actif.

### Moteur 1 bis — swing court terme (désactivé par défaut)

L'ancien moteur (cassures, replis, croisements MACD, objectifs à 2R) reste
disponible dans Réglages → Stratégie. Il est **mesuré perdant** : conservé pour
expérimenter, déconseillé.

### Moteur 2 — actualité

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
### Moteur de risque — commun aux deux, jamais un LLM

Tout signal, technique ou issu d'une actualité, passe par les mêmes contrôles :

- taille de position = `capital × risque% ÷ distance au stop` ;
- **enveloppes** : part maximale du portefeuille engageable, au total et par
  classe d'actif — elles *réduisent* la position au lieu de la refuser, et le
  capital hors enveloppe n'est jamais touché ;
- plafonds : perte max/jour, perte max/semaine (kill-switch), nombre de
  positions, exposition par actif, cash disponible ;
- **rentabilité nette de frais** : un trade dont le gain visé ne couvre pas
  plusieurs fois l'aller-retour de commissions est refusé ;
- stop-loss et objectif **obligatoires** sur chaque trade.

### Exécution et suivi

- **Paper par défaut**, aux prix réels, **frais réels inclus**. Les bascules
  « réel » (Trading212 / Kraken) sont des interrupteurs distincts, avec
  confirmation.
- **Stop suiveur** : dès que le gain atteint 2× le risque initial, le stop
  remonte au point mort *frais compris* (le trade ne peut plus perdre), puis
  suit le plus haut atteint à 1,5× le risque.
- Toutes les minutes : stops, objectifs et stops suiveurs sont contrôlés ;
  chaque ouverture/clôture déclenche une notification push.

## 💸 Frais : la contrainte qui décide de tout

Barème par défaut : **Revolut, compte Standard — 1,49 % par transaction,
minimum 0,99 €** (modifiable dans Réglages → Frais, vérifiez-le chez votre
courtier, les barèmes changent).

Conséquence à avoir en tête : **un aller-retour coûte ~3 %**. Viser +2 % est
donc une perte garantie, et sur une petite position le plancher de 0,99 €
devient énorme (aller-retour de 6,6 % sur 30 €). C'est pourquoi :

- les frais sont appliqués **aussi en paper trading** — sinon les résultats
  simulés sont une illusion, et le P&L affiché est net ;
- le moteur de risque refuse tout trade dont l'objectif ne vaut pas au moins
  3× l'aller-retour (réglable) ;
- l'unité de temps par défaut est **le jour**, pas l'heure : moins de trades,
  des mouvements plus amples, moins de frottement.

## 📊 Le backtest — mesurer plutôt que croire

L'onglet **Marché** rejoue la stratégie sur l'historique réel depuis 2016
(Bitstamp, public et sans clé), frais compris, décision à la clôture et
exécution à l'ouverture suivante. Il affiche la période complète **et** les
sous-périodes récentes, comparées à « acheter et ne rien faire ».

Relancez-le régulièrement : il tourne sur les données du jour. La règle de
décision reste la même — **ne passez en réel que si le backtest est positif
ET que plusieurs semaines de paper trading le confirment.**

### Exécution et suivi des positions d'allocation

Les positions ouvertes par la stratégie de régime sont marquées « pilotées par
le signal » : ni objectif de prix, ni stop suiveur. Elles restent ouvertes tant
que la tendance de fond tient, et se ferment quand le signal se retourne. Seul
un stop catastrophe à −50 % peut intervenir entre deux vérifications.

## L'application

- **Dashboard** : valeur du portefeuille, P&L jour/semaine/mois, courbe
  d'équity 30 jours, **jauges d'enveloppes**, positions ouvertes, badge PAPER/LIVE.
- **Marché** : l'état du signal sur chaque actif suivi et la raison de
  l'inaction, un bouton « Évaluer maintenant », et le **backtest** sur 10 ans
  comparé à l'achat-conservation.
- **Signaux** : le raisonnement de chaque analyse — marqueurs techniques ou
  actualité + avis du second modèle — et pourquoi un signal a été exécuté ou
  rejeté (traçabilité complète).
- **Historique** : tous les trades, filtres, clôture manuelle, export CSV.
- **Rapports** : synthèses hebdo/mensuelles archivées.
- **Réglages** : choix de la **stratégie**, risque, **enveloppes**, **frais**,
  kill-switch, bascules paper/réel, **clés API avec bouton « Tester »**
  (vérification réelle auprès de Google, Anthropic, Finnhub, Kraken ou
  Trading212 — une clé mal collée se voit immédiatement), notifications.

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
2. **Backtest positif** (onglet Marché) — pas seulement l'intuition.
3. Rapports : P&L net positif, drawdown supportable, assez de trades pour juger.
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

- **L'analyse technique ne couvre que la crypto** : les bougies viennent de
  l'API publique Kraken, gratuite et sans clé. Finnhub ne donne pas
  d'historique de bougies en gratuit, donc les actions restent pilotées par
  l'actualité seule.
- **La stratégie est une exposition longue filtrée, pas une martingale.** Si la
  crypto baisse durablement, le filtre limite la casse mais ne crée pas de
  profit. Les drawdowns restent importants (−32 % à −47 % sur les périodes
  récentes, −83 % sur 10 ans).
- **Résultats passés ≠ résultats futurs.** Le signal est robuste sur les données
  disponibles ; cela ne garantit rien.
- **Prix des actions** via Finnhub gratuit : tickers US principalement. Les
  ETF/actions EU passent par Trading212 en réel, mais le paper trading actions
  est le plus fiable sur les tickers US.
- **Positions longues uniquement** : un signal « sell » clôture une position,
  il n'ouvre pas de vente à découvert.
- **Matières premières** : pas d'API Revolut pour l'or/argent ; l'équivalent
  se trade via ETF/ETC (ex. or physique) côté Trading212.
- Les limites de perte jour/semaine comptent le P&L **réalisé**.
