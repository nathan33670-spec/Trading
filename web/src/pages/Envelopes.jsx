import { Card } from "../components";

/* Enveloppes, frais et moteur technique. Reçoit la config de risque complète
   et la fonction de sauvegarde de la page Réglages. */

const ENVELOPES = [
  ["max_invested_pct", "Enveloppe globale", 5, 100, 5, "%",
   "Part maximale du portefeuille engagée, toutes classes confondues. Le reste ne sera jamais touché."],
  ["envelope_crypto_pct", "Enveloppe crypto", 0, 100, 5, "%",
   "Plafond de la poche crypto."],
  ["envelope_stock_pct", "Enveloppe actions / ETF", 0, 100, 5, "%",
   "Plafond de la poche actions et ETF."],
];

const TIMEFRAMES = [
  [60, "1 heure"],
  [240, "4 heures"],
  [1440, "1 jour"],
];

export default function Envelopes({ cfg, save, setCfg }) {
  const engaged = cfg.envelope_crypto_pct + cfg.envelope_stock_pct;
  const roundTrip = (cfg.fee_crypto_pct * 2).toFixed(2);

  const slider = ([key, label, min, max, step, unit, help]) => (
    <div className="field" key={key}>
      <label>
        {label}
        <b>{cfg[key]}{unit}</b>
      </label>
      <div className="small muted">{help}</div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={cfg[key]}
        onChange={(e) => setCfg({ ...cfg, [key]: Number(e.target.value) })}
        onMouseUp={() => save(cfg)}
        onTouchEnd={() => save(cfg)}
      />
    </div>
  );

  const number = (key, label, help, props = {}) => (
    <div className="field">
      <label>{label}</label>
      <div className="small muted">{help}</div>
      <input
        type="number"
        value={cfg[key]}
        onChange={(e) => setCfg({ ...cfg, [key]: Number(e.target.value) })}
        onBlur={() => save(cfg)}
        {...props}
      />
    </div>
  );

  return (
    <>
      <Card title="Enveloppes de jeu">
        <p className="small muted" style={{ marginTop: 0 }}>
          Combien du portefeuille le bot a le droit d'engager. Ces plafonds
          réduisent la taille des positions au lieu de les refuser, et le capital
          hors enveloppe reste intouchable.
        </p>
        {ENVELOPES.map(slider)}
        {engaged > cfg.max_invested_pct && (
          <p className="small warn">
            ⚠️ Crypto + actions ({engaged} %) dépasse l'enveloppe globale
            ({cfg.max_invested_pct} %) : c'est cette dernière qui s'appliquera en premier.
          </p>
        )}
      </Card>

      <Card title="Frais de transaction">
        <p className="small muted" style={{ marginTop: 0 }}>
          Appliqués aussi en paper trading, sinon les résultats simulés sont
          trompeurs. Valeurs par défaut : <b>Revolut compte Standard</b>
          (1,49 % par transaction, minimum 0,99 €). Vérifiez-les chez votre
          courtier, les barèmes changent.
        </p>
        {number("fee_crypto_pct", "Commission crypto (%)",
          "Prélevée à l'achat ET à la vente.", { step: 0.01, min: 0, max: 5 })}
        {number("fee_crypto_min", "Commission minimum crypto (€)",
          "Plancher qui rend les petites positions prohibitives.", { step: 0.01, min: 0, max: 50 })}
        {number("fee_stock_pct", "Commission actions / ETF (%)",
          "Trading212 : 0 % de commission, ~0,15 % de change.", { step: 0.01, min: 0, max: 5 })}
        {number("min_target_fee_ratio", "L'objectif doit valoir N fois les frais",
          "Garde-fou : un trade dont le gain visé ne couvre pas plusieurs fois l'aller-retour est refusé.",
          { step: 0.5, min: 0, max: 10 })}
        <p className="small">
          Aller-retour actuel : <b>~{roundTrip} %</b> du montant investi. Un
          objectif inférieur à ce seuil est une perte assurée.
        </p>
      </Card>

      <Card title="Stratégie crypto">
        <p className="small muted" style={{ marginTop: 0 }}>
          Fonctionne sans aucune clé API : les prix viennent d'API publiques.
        </p>
        <div className="field">
          <label>Stratégie active</label>
          <select
            value={cfg.strategy}
            onChange={(e) => save({ ...cfg, strategy: e.target.value })}
          >
            <option value="regime">Régime — momentum 12 mois (recommandé)</option>
            <option value="swing">Swing court terme (perdant au backtest)</option>
            <option value="off">Aucune</option>
          </select>
          <div className="small muted" style={{ marginTop: 8 }}>
            {cfg.strategy === "regime" && (
              <>
                Investi tant que le prix est au-dessus de son niveau d'il y a 12 mois,
                en cash sinon. Quelques mouvements par an, donc très peu de frais.
                Sortie sur retournement du signal, pas sur objectif de prix.
              </>
            )}
            {cfg.strategy === "swing" && (
              <>
                ⚠️ Détection de configurations court terme. Mesurée <b>perdante</b> au
                backtest : les allers-retours fréquents ne survivent pas à 3 % de frais.
                Conservée pour expérimenter, pas recommandée.
              </>
            )}
            {cfg.strategy === "off" && "Aucune prise de position automatique sur la crypto."}
          </div>
        </div>

        {cfg.strategy === "regime" && (
          <>
            <div className="field">
              <label>Actifs suivis</label>
              <div className="small muted">
                Validé uniquement sur <b>BTC/EUR</b> (ETH en option, plus faible).
                Testé sur 11 autres actifs — S&P 500, Nasdaq, Apple, Microsoft, or,
                argent, pétrole, cuivre, gaz, maïs, altcoins — le filtre n'améliore
                le rendement sur <b>aucun</b> d'entre eux.
              </div>
              <input
                type="text"
                value={(cfg.regime_assets || []).join(", ")}
                placeholder="BTC/EUR"
                onChange={(e) =>
                  setCfg({ ...cfg, regime_assets: e.target.value.split(",").map((s) => s.trim()) })
                }
                onBlur={() => save(cfg)}
              />
            </div>
            {number("momentum_days", "Horizon du momentum (jours)",
              "365 = 12 mois, le réglage le plus documenté et le plus robuste.",
              { step: 30, min: 90, max: 720 })}
            {number("regime_check_days", "Vérification du signal (jours)",
              "7 = hebdomadaire. Vérifier tous les jours double les allers-retours sans gain.",
              { step: 1, min: 1, max: 30 })}
          </>
        )}
      </Card>

      {cfg.strategy === "swing" && (
      <Card title="Réglages du swing court terme">
        <div className="field">
          <label>Unité de temps analysée</label>
          <div className="small muted">
            Plus l'unité est courte, plus le bot trade — et plus les frais pèsent.
          </div>
          <select
            value={cfg.tech_timeframe_min}
            onChange={(e) => save({ ...cfg, tech_timeframe_min: Number(e.target.value) })}
          >
            {TIMEFRAMES.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </div>

        {slider(["tech_min_conviction", "Conviction technique minimale", 0, 100, 1, "/100",
          "Plus haut = moins de trades, mais mieux confirmés."])}

        <div className="field">
          <label>Watchlist crypto</label>
          <div className="small muted">
            Paires séparées par des virgules. Vide = liste par défaut (10 paires
            EUR les plus liquides de Kraken).
          </div>
          <input
            type="text"
            value={(cfg.crypto_watchlist || []).join(", ")}
            placeholder="BTC/EUR, ETH/EUR, SOL/EUR…"
            onChange={(e) =>
              setCfg({ ...cfg, crypto_watchlist: e.target.value.split(",").map((s) => s.trim()) })
            }
            onBlur={() => save(cfg)}
          />
        </div>

        <div className="switch-row">
          <div className="lbl">
            <div className="t">Second avis du LLM sur les signaux techniques</div>
            <div className="d">Optionnel : consomme votre quota Gemini/Claude.</div>
          </div>
          <input
            type="checkbox"
            checked={cfg.tech_llm_review}
            onChange={(e) => save({ ...cfg, tech_llm_review: e.target.checked })}
          />
        </div>
      </Card>
      )}

      <Card title="Stop suiveur">
        <p className="small muted" style={{ marginTop: 0 }}>
          Remonte le stop quand la position gagne : d'abord au point mort (frais
          compris), puis en suivant le plus haut atteint.
        </p>
        <div className="switch-row">
          <div className="lbl">
            <div className="t">Activer le stop suiveur</div>
            <div className="d">Verrouille les gains au lieu de les rendre.</div>
          </div>
          <input
            type="checkbox"
            checked={cfg.trailing_enabled}
            onChange={(e) => save({ ...cfg, trailing_enabled: e.target.checked })}
          />
        </div>
        {number("trail_activate_r", "Déclenchement (en multiples du risque)",
          "2 = le stop bouge quand le gain atteint 2× le risque initial.", { step: 0.5, min: 0.5, max: 10 })}
        {number("trail_distance_r", "Distance de suivi (en multiples du risque)",
          "1,5 = le stop reste à 1,5× le risque sous le plus haut atteint.", { step: 0.5, min: 0.3, max: 10 })}
      </Card>
    </>
  );
}
