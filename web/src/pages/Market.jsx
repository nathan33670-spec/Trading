import { useEffect, useState } from "react";
import { api, fmtEUR } from "../api";
import { Card, Empty } from "../components";

const fmtPrice = (v) =>
  v == null ? "—" : v >= 100 ? v.toFixed(2) : v >= 1 ? v.toFixed(4) : v.toFixed(6);

function Markers({ markers }) {
  if (!markers?.length) return null;
  return (
    <div className="markers">
      {markers.map((m) => (
        <span key={m.code} className={`marker ${m.score > 0 ? "pos" : "neg"} ${m.primary ? "primary" : ""}`}>
          {m.label}
        </span>
      ))}
    </div>
  );
}

/* Comparaison stratégie vs achat-conservation sur une période. */
function PeriodRow({ label, r }) {
  const better = r.equity > r.buy_hold_equity;
  return (
    <tr>
      <td>{label}</td>
      <td className={better ? "pos" : ""}>
        <b>{fmtEUR(r.equity)}</b>
        <span className="muted"> ({r.cagr} %/an)</span>
      </td>
      <td className="muted">
        {fmtEUR(r.buy_hold_equity)} <span className="muted">({r.buy_hold_cagr} %/an)</span>
      </td>
      <td className={r.max_drawdown < r.buy_hold_drawdown ? "pos" : "neg"}>
        −{r.max_drawdown} %
        <span className="muted"> vs −{r.buy_hold_drawdown} %</span>
      </td>
      <td className="muted">{r.trades}</td>
    </tr>
  );
}

function RegimeBacktest({ result, busy, onRun }) {
  return (
    <Card title="Backtest — la stratégie sur l'historique réel">
      <p className="small muted" style={{ marginTop: 0 }}>
        Rejoue la stratégie sur les vraies bougies depuis 2016, <b>frais compris</b>,
        décision à la clôture et exécution à l'ouverture suivante. Comparée à
        « acheter et ne rien faire ». Une mesure du passé, pas une prévision.
      </p>
      <button className="btn primary small" disabled={busy} onClick={onRun}>
        {busy ? "Calcul en cours…" : "Lancer le backtest"}
      </button>

      {result?.per_symbol?.map((r) => (
        <div key={r.symbol} style={{ marginTop: 16 }}>
          <div className="small muted" style={{ textTransform: "uppercase", letterSpacing: 1 }}>
            {r.symbol} — mise de départ {fmtEUR(result.stake)}
          </div>
          <div className="table-scroll">
            <table className="bt">
              <thead>
                <tr>
                  <th>Période</th>
                  <th>Stratégie</th>
                  <th>Achat-conservation</th>
                  <th>Pire baisse</th>
                  <th>Mvts</th>
                </tr>
              </thead>
              <tbody>
                {r.periods?.map((p) => <PeriodRow key={p.label} label={p.label} r={p} />)}
                <PeriodRow label={`Tout l'historique (${r.years} ans)`} r={r} />
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Investie {r.exposure} % du temps, {fmtEUR(r.fees)} de frais sur toute la période.
          </p>
        </div>
      ))}

      {result && (
        <p className="small warn">
          Sur les périodes récentes la stratégie bat l'achat-conservation avec une
          baisse maximale bien moindre. Sur l'historique complet elle reste
          derrière : 2016-2017 a monté quasiment sans interruption, et tout filtre
          y coûte cher. Aucune de ces deux observations ne prédit l'avenir —
          restez en paper trading le temps de juger sur pièces.
        </p>
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
  const [msg, setMsg] = useState("");

  const refresh = () => api("/market").then(setData).catch((e) => setErr(e.message));
  useEffect(() => { refresh(); }, []);

  const scanNow = async () => {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api("/market/scan", { method: "POST" });
      const actions = r.actions ?? [];
      setMsg(actions.length ? actions.join(" · ") : "Aucun changement : le signal est inchangé.");
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const runBacktest = async () => {
    setBtBusy(true); setErr("");
    try {
      setBt(await api("/market/backtest", { method: "POST" }));
    } catch (e) {
      setErr(e.message);
    } finally {
      setBtBusy(false);
    }
  };

  if (!data) return <Empty>Chargement…</Empty>;

  const isRegime = data.strategy === "regime";

  return (
    <>
      <Card title={isRegime ? "Stratégie de régime — momentum 12 mois" : "Analyse technique court terme"}>
        <p className="small muted" style={{ marginTop: 0 }}>
          {isRegime ? (
            <>
              Investi tant que le prix reste au-dessus de son niveau d'il y a{" "}
              {Math.round(data.momentum_days / 30)} mois, en cash sinon. Signal vérifié
              tous les {data.check_days} jours — quelques mouvements par an, donc très
              peu de frais.
            </>
          ) : (
            <>
              Analyse en {data.timeframe_min >= 1440 ? `${data.timeframe_min / 1440} jour(s)` : `${data.timeframe_min / 60} h`},
              seuil de conviction {data.min_conviction}/100.
            </>
          )}
          {!data.enabled && " — stratégie désactivée dans les Réglages."}
        </p>
        <button className="btn small" disabled={busy} onClick={scanNow}>
          {busy ? "Évaluation…" : "Évaluer maintenant"}
        </button>
        {msg && <div className="small" style={{ marginTop: 8 }}>{msg}</div>}
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
                {!isRegime && r.rsi != null && <span className="small muted">RSI {r.rsi}</span>}
              </div>
              <div className="small muted">{r.decision}</div>
              <Markers markers={r.markers} />
            </div>
          ))}
        </div>
      </Card>

      <RegimeBacktest result={bt} busy={btBusy} onRun={runBacktest} />
    </>
  );
}
