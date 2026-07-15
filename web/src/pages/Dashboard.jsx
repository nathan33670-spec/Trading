import { fmtEUR, fmtPct } from "../api";
import { Card, Empty, EquityChart, Tile } from "../components";

export default function Dashboard({ data }) {
  if (!data) return <Empty>Chargement…</Empty>;

  const delta = data.total_pnl;
  const deltaPct = (delta / data.start_capital) * 100;

  return (
    <>
      <Card className="hero">
        <div className="label">Valeur du portefeuille</div>
        <div className="value">{fmtEUR(data.equity)}</div>
        <div className={`delta ${delta >= 0 ? "pos" : "neg"}`}>
          {delta >= 0 ? "▲" : "▼"} {fmtEUR(delta, true)} ({fmtPct(deltaPct)}) depuis le départ
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>
          Cash disponible : {fmtEUR(data.cash)}
        </div>
      </Card>

      <div className="tiles">
        <Tile label="Jour" value={fmtEUR(data.daily_pnl, true)} positive={data.daily_pnl >= 0} />
        <Tile label="Semaine" value={fmtEUR(data.weekly_pnl, true)} positive={data.weekly_pnl >= 0} />
        <Tile label="Mois" value={fmtEUR(data.monthly_pnl, true)} positive={data.monthly_pnl >= 0} />
      </div>

      <Card title="Équity — 30 jours">
        <EquityChart data={data.equity_curve} />
      </Card>

      <Card title={`Positions ouvertes (${data.positions.length})`}>
        {data.positions.length === 0 && <Empty>Aucune position ouverte. Le bot attend une opportunité.</Empty>}
        {data.positions.map((p) => (
          <div className="row" key={p.id}>
            <div>
              <div className="sym">
                {p.symbol}{" "}
                <span className={`chip ${p.is_paper ? "paper" : "live"}`}>{p.is_paper ? "paper" : "réel"}</span>
              </div>
              <div className="sub">
                {p.qty.toLocaleString("fr-FR", { maximumFractionDigits: 6 })} × {p.entry_price.toLocaleString("fr-FR")} —
                stop {p.stop_price.toLocaleString("fr-FR", { maximumFractionDigits: 4 })} · objectif{" "}
                {p.target_price.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}
              </div>
            </div>
            <div className="right">
              <div className={`val ${p.unrealized_pnl >= 0 ? "pos" : "neg"}`}>
                {fmtEUR(p.unrealized_pnl, true)}
              </div>
              <div className={`small ${p.unrealized_pnl >= 0 ? "pos" : "neg"}`}>{fmtPct(p.unrealized_pnl_pct)}</div>
            </div>
          </div>
        ))}
      </Card>
    </>
  );
}
