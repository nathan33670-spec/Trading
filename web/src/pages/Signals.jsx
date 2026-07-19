import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Card, ConvictionBar, Empty } from "../components";

const STATUS_LABELS = {
  executed: "exécuté",
  rejected: "rejeté",
  proposed: "en attente",
  expired: "expiré",
};

export default function Signals() {
  const [signals, setSignals] = useState(null);

  useEffect(() => {
    api("/signals").then(setSignals).catch(() => setSignals([]));
  }, []);

  if (!signals) return <Empty>Chargement…</Empty>;
  if (!signals.length)
    return (
      <Empty>
        Aucun signal pour l'instant.
        <br />
        Le bot n'émet un signal que quand une actualité le justifie vraiment.
      </Empty>
    );

  return signals.map((s) => (
    <Card key={s.id} className="signal-card">
      <div className="head">
        <span className="sym" style={{ fontWeight: 700 }}>{s.asset}</span>
        <span className={`chip ${s.direction}`}>{s.direction === "buy" ? "achat" : "vente"}</span>
        <span className={`chip status-${s.status}`}>{STATUS_LABELS[s.status] || s.status}</span>
        <span className="chip">{s.asset_class}</span>
      </div>

      <ConvictionBar label="Analyste" value={s.conviction} color="var(--series-1)" />
      <ConvictionBar
        label="2ᵉ avis"
        value={s.gemini_agrees === null ? null : s.gemini_conviction ?? 0}
        color="var(--series-2)"
      />

      <div className="rationale">{s.rationale}</div>

      {s.status_reason && (
        <div className="small muted">Motif : {s.status_reason}</div>
      )}

      {s.news.length > 0 && (
        <div className="news">
          {s.news.map((n, i) => (
            <a key={i} href={n.url || "#"} target="_blank" rel="noreferrer">
              📰 {n.title} <span className="muted">({n.source})</span>
            </a>
          ))}
        </div>
      )}

      <div className="meta">{fmtDate(s.created_at)}</div>
    </Card>
  ));
}
