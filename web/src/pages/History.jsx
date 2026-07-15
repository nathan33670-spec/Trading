import { useEffect, useState } from "react";
import { api, fmtDate, fmtEUR, fmtPct } from "../api";
import { Card, Empty } from "../components";

export default function History() {
  const [trades, setTrades] = useState(null);
  const [filter, setFilter] = useState("all");

  const load = () => api("/trades").then(setTrades).catch(() => setTrades([]));
  useEffect(() => { load(); }, []);

  if (!trades) return <Empty>Chargement…</Empty>;

  const shown = trades.filter((t) => filter === "all" || t.status === filter);

  const exportCSV = () => {
    const header = "symbole;classe;courtier;mode;quantite;entree;sortie;pnl;pnl_pct;raison;ouvert;clos";
    const rows = trades.map((t) =>
      [t.symbol, t.asset_class, t.broker, t.is_paper ? "paper" : "reel", t.qty, t.entry_price,
       t.exit_price ?? "", t.pnl ?? "", t.pnl_pct ?? "", t.close_reason, t.opened_at, t.closed_at ?? ""].join(";")
    );
    const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
    const a = Object.assign(document.createElement("a"), {
      href: URL.createObjectURL(blob),
      download: "newstrader-trades.csv",
    });
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const closeManual = async (id) => {
    if (!window.confirm("Clôturer cette position au prix du marché ?")) return;
    try {
      await api(`/trades/${id}/close`, { method: "POST" });
      load();
    } catch (e) {
      window.alert(e.message);
    }
  };

  return (
    <>
      <div className="filters">
        {[["all", "Tous"], ["open", "Ouverts"], ["closed", "Clôturés"]].map(([k, label]) => (
          <span key={k} className={`chip ${filter === k ? "active" : ""}`} onClick={() => setFilter(k)}>
            {label}
          </span>
        ))}
        <span className="chip" style={{ marginLeft: "auto" }} onClick={exportCSV}>⬇ CSV</span>
      </div>

      <Card>
        {shown.length === 0 && <Empty>Aucun trade dans cette vue.</Empty>}
        {shown.map((t) => (
          <div className="row" key={t.id}>
            <div>
              <div className="sym">
                {t.symbol}{" "}
                <span className={`chip ${t.is_paper ? "paper" : "live"}`}>{t.is_paper ? "paper" : "réel"}</span>
              </div>
              <div className="sub">
                {fmtDate(t.opened_at)}
                {t.closed_at ? ` → ${fmtDate(t.closed_at)} · ${t.close_reason}` : " · en cours"}
              </div>
            </div>
            <div className="right">
              {t.status === "closed" ? (
                <>
                  <div className={`val ${t.pnl >= 0 ? "pos" : "neg"}`}>{fmtEUR(t.pnl, true)}</div>
                  <div className={`small ${t.pnl >= 0 ? "pos" : "neg"}`}>{fmtPct(t.pnl_pct)}</div>
                </>
              ) : (
                <button className="btn small danger" onClick={() => closeManual(t.id)}>Clôturer</button>
              )}
            </div>
          </div>
        ))}
      </Card>
    </>
  );
}
