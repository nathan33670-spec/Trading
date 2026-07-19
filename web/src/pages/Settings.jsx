import { useEffect, useState } from "react";
import { api, clearToken, enablePush } from "../api";
import { Card, Empty, Switch } from "../components";

const SLIDERS = [
  ["risk_per_trade_pct", "Risque par trade", 0.1, 5, 0.1, "%"],
  ["max_daily_loss_pct", "Perte max / jour", 0.5, 20, 0.5, "%"],
  ["max_weekly_loss_pct", "Perte max / semaine", 1, 40, 1, "%"],
  ["max_positions", "Positions simultanées max", 1, 20, 1, ""],
  ["max_exposure_per_asset_pct", "Exposition max / actif", 1, 100, 1, "%"],
  ["min_conviction", "Conviction minimale du LLM", 0, 100, 5, "/100"],
];

export default function Settings({ onSaved }) {
  const [cfg, setCfg] = useState(null);
  const [saved, setSaved] = useState(false);
  const [pushState, setPushState] = useState("");

  useEffect(() => {
    api("/settings/risk").then(setCfg).catch(() => setCfg(null));
  }, []);

  if (!cfg) return <Empty>Chargement…</Empty>;

  const save = async (next) => {
    setCfg(next);
    await api("/settings/risk", { method: "PUT", body: JSON.stringify(next) });
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
    onSaved?.();
  };

  const toggleLive = (key, label) => (checked) => {
    if (
      checked &&
      !window.confirm(
        `⚠️ Activer le trading RÉEL via ${label} ?\n\nDe l'argent réel sera engagé selon vos réglages de risque. ` +
          "Recommandé uniquement après une phase de paper trading rentable."
      )
    )
      return;
    save({ ...cfg, [key]: checked });
  };

  const activatePush = async () => {
    setPushState("…");
    try {
      await enablePush();
      setPushState("✅ Notifications activées sur cet appareil");
    } catch (e) {
      setPushState(`❌ ${e.message}`);
    }
  };

  return (
    <>
      <Card title="Taux de risque">
        {SLIDERS.map(([key, label, min, max, step, unit]) => (
          <div className="field" key={key}>
            <label>
              {label}
              <b>
                {cfg[key]}
                {unit}
              </b>
            </label>
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
        ))}
        {saved && <div className="small pos">Réglages enregistrés ✓</div>}
      </Card>

      <Card title="Mode d'exécution">
        <div className="switch-row">
          <div className="lbl">
            <div className="t">🛑 Kill-switch global</div>
            <div className="d">Bloque immédiatement toute nouvelle prise de position.</div>
          </div>
          <Switch checked={cfg.kill_switch} onChange={(v) => save({ ...cfg, kill_switch: v })} />
        </div>
        <div className="switch-row">
          <div className="lbl">
            <div className="t">Trading212 en réel (actions / ETF)</div>
            <div className="d">Désactivé = ordres simulés (paper) aux prix réels.</div>
          </div>
          <Switch checked={cfg.live_trading212} onChange={toggleLive("live_trading212", "Trading212")} />
        </div>
        <div className="switch-row">
          <div className="lbl">
            <div className="t">Kraken en réel (crypto)</div>
            <div className="d">Désactivé = ordres simulés (paper) aux prix réels.</div>
          </div>
          <Switch checked={cfg.live_kraken} onChange={toggleLive("live_kraken", "Kraken")} />
        </div>
      </Card>

      <Card title="Notifications">
        <p className="small muted" style={{ marginTop: 0 }}>
          Recevez une notification à chaque ouverture/clôture de trade et pour les synthèses.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn primary" onClick={activatePush}>Activer sur cet appareil</button>
          <button className="btn" onClick={() => api("/push/test", { method: "POST" })}>Tester</button>
        </div>
        {pushState && <div className="small" style={{ marginTop: 10 }}>{pushState}</div>}
      </Card>

      <Card title="Session">
        <button
          className="btn danger"
          onClick={() => {
            clearToken();
            window.location.reload();
          }}
        >
          Se déconnecter
        </button>
      </Card>
    </>
  );
}
