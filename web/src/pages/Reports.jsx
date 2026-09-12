import { useEffect, useState } from "react";
import { api, fmtEUR } from "../api";
import { Card, Empty } from "../components";

export default function Reports() {
  const [reports, setReports] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () => api("/reports").then(setReports).catch(() => setReports([]));
  useEffect(() => { load(); }, []);

  const generate = async (kind) => {
    setBusy(true);
    try {
      await api(`/reports/generate?kind=${kind}`, { method: "POST" });
      await load();
    } catch (e) {
      window.alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!reports) return <Empty>Chargement…</Empty>;

  return (
    <>
      <div className="filters">
        <button className="btn small" disabled={busy} onClick={() => generate("weekly")}>
          Générer la synthèse hebdo
        </button>
        <button className="btn small" disabled={busy} onClick={() => generate("monthly")}>
          Générer la synthèse mensuelle
        </button>
      </div>

      {reports.length === 0 && (
        <Empty>
          Pas encore de synthèse. Le bot en génère une chaque dimanche soir
          et le 1er de chaque mois.
        </Empty>
      )}

      {reports.map((r) => (
        <Card
          key={r.id}
          title={`${r.kind === "weekly" ? "Synthèse hebdomadaire" : "Synthèse mensuelle"} — ${new Date(
            r.period_start
          ).toLocaleDateString("fr-FR")} → ${new Date(r.period_end).toLocaleDateString("fr-FR")}`}
        >
          <div className="tiles" style={{ marginBottom: 12 }}>
            <div className="tile">
              <div className="label">Trades</div>
              <div className="value">{r.stats.trades}</div>
            </div>
            <div className="tile">
              <div className="label">Réussite</div>
              <div className="value">{r.stats.win_rate}%</div>
            </div>
            <div className="tile">
              <div className="label">P&L</div>
              <div className={`value ${r.stats.pnl >= 0 ? "pos" : "neg"}`}>{fmtEUR(r.stats.pnl, true)}</div>
            </div>
          </div>
          {r.stats.best_trade && (
            <div className="small muted" style={{ marginBottom: 10 }}>
              Meilleur : {r.stats.best_trade.symbol} ({fmtEUR(r.stats.best_trade.pnl, true)}) · Pire :{" "}
              {r.stats.worst_trade.symbol} ({fmtEUR(r.stats.worst_trade.pnl, true)})
            </div>
          )}
          <div style={{ lineHeight: 1.6, color: "var(--ink-2)", fontSize: 14.5 }}>{r.commentary}</div>
        </Card>
      ))}
    </>
  );
}
