import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, Empty } from "../components";

const fmtPrice = (v) =>
  v == null ? "—" : v >= 100 ? v.toFixed(2) : v >= 1 ? v.toFixed(4) : v.toFixed(6);

function Markers({ markers }) {
  if (!markers?.length) return null;
  return (
    <div className="markers">
      {markers.map((m) => (
        <span key={m.code} className={`marker ${m.score > 0 ? "pos" : "neg"} ${m.primary ? "primary" : ""}`}>
          {m.label} {m.score > 0 ? `+${m.score}` : m.score}
        </span>
      ))}
    </div>
  );
}

function Backtest({ result, busy, onRun }) {
  return (
    <Card title="Backtest — la stratégie sur l'historique réel">
      <p className="small muted" style={{ marginTop: 0 }}>
        Rejoue les mêmes règles sur les vraies bougies, <b>frais compris</b>, avec
        des hypothèses pessimistes (entrée à l'ouverture suivante, stop prioritaire
        sur l'objectif). C'est une mesure du passé, pas une prévision.
      </p>
      <button className="btn primary small" disabled={busy} onClick={onRun}>
        {busy ? "Calcul en cours…" : "Lancer le backtest"}
      </button>

      {result && (
        <>
          <div className="tiles" style={{ marginTop: 14 }}>
            <div className="tile">
              <div className="label">Trades</div>
              <div className="value">{result.trades}</div>
            </div>
            <div className="tile">
              <div className="label">Taux de réussite</div>
              <div className="value">{result.win_rate} %</div>
            </div>
            <div className="tile">
              <div className="label">Frais payés</div>
              <div className="value neg">−{result.fees} €</div>
            </div>
            <div className="tile">
              <div className="label">Résultat net</div>
              <div className={`value ${result.net >= 0 ? "pos" : "neg"}`}>
                {result.net >= 0 ? "+" : ""}{result.net} €
              </div>
            </div>
          </div>
          <p className="small muted">
            Mise de {result.stake} € par trade, sur {result.days} jours et {result.symbols} paires.
            Brut {result.gross} € avant frais → net {result.net} € après.
            Sorties : {result.by_reason?.target ?? 0} objectifs, {result.by_reason?.trailing ?? 0} stops
            suiveurs, {result.by_reason?.stop ?? 0} stops.
          </p>
          {result.net < 0 && (
            <p className="small warn">
              ⚠️ Résultat négatif sur cette période. C'est exactement pourquoi le bot
              reste en paper trading : ne passez jamais en réel sans un backtest ET
              plusieurs semaines de simulation positives.
            </p>
          )}
        </>
      )}
    </Card>
  );
}

export default function Market() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [bt, setBt] = useState(null);
  const [btBusy, setBtBusy] = useState(false);
  const [err, setErr] = useState("");

  const refresh = () => api("/market").then(setData).catch((e) => setErr(e.message));
  useEffect(() => { refresh(); }, []);

  const scanNow = async () => {
    setBusy(true);
    setErr("");
    try {
      await api("/market/scan", { method: "POST" });
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runBacktest = async () => {
    setBtBusy(true);
    setErr("");
    try {
      setBt(await api("/market/backtest?days=365", { method: "POST" }));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBtBusy(false);
    }
  };

  if (!data) return <Empty>Chargement…</Empty>;

  return (
    <>
      <Card title="Ce que le moteur technique voit">
        <p className="small muted" style={{ marginTop: 0 }}>
          Analyse en {data.timeframe_min >= 1440 ? `${data.timeframe_min / 1440} jour(s)` : `${data.timeframe_min / 60} h`},
          seuil de conviction {data.min_conviction}/100.
          {!data.enabled && " — moteur désactivé dans les Réglages."}
        </p>
        <button className="btn small" disabled={busy} onClick={scanNow}>
          {busy ? "Analyse…" : "Analyser maintenant"}
        </button>
        {err && <div className="small neg" style={{ marginTop: 8 }}>❌ {err}</div>}

        <div style={{ marginTop: 12 }}>
          {data.rows.map((r) => (
            <div className="market-row" key={r.symbol}>
              <div className="market-head">
                <b>{r.symbol}</b>
                <span className="small muted">{fmtPrice(r.price)} €</span>
                {r.trend && (
                  <span className={`chip small ${r.trend === "haussière" ? "paper" : "kill"}`}>
                    {r.trend}
                  </span>
                )}
                {r.rsi != null && <span className="small muted">RSI {r.rsi}</span>}
                {r.conviction > 0 && (
                  <span className="small">
                    conviction <b>{r.conviction}</b>/100
                  </span>
                )}
              </div>
              <div className="small muted">{r.decision}</div>
              <Markers markers={r.markers} />
            </div>
          ))}
        </div>
      </Card>

      <Backtest result={bt} busy={btBusy} onRun={runBacktest} />
    </>
  );
}
