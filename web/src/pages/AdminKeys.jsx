import { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components";

const PROVIDER_LABELS = {
  gemini: "Gemini (gratuit)",
  claude_cli: "Claude via abonnement",
  anthropic: "API Anthropic",
};

export default function AdminKeys() {
  const [items, setItems] = useState(null);
  const [status, setStatus] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [msg, setMsg] = useState("");
  const [tests, setTests] = useState({});

  const refresh = () =>
    Promise.all([api("/admin/secrets"), api("/admin/status")])
      .then(([secrets, st]) => {
        setItems(secrets);
        setStatus(st);
      })
      .catch((e) => setMsg(`❌ ${e.message}`));

  useEffect(() => {
    refresh();
  }, []);

  if (!items) return null;

  const save = async (name) => {
    const value = (drafts[name] || "").trim();
    if (!value) return;
    setMsg("");
    try {
      await api(`/admin/secrets/${name}`, { method: "PUT", body: JSON.stringify({ value }) });
      setDrafts((d) => ({ ...d, [name]: "" }));
      setMsg("✅ Clé enregistrée (chiffrée côté serveur)");
      refresh();
      test(name);   // vérification immédiate : une clé mal collée se voit tout de suite
    } catch (e) {
      setMsg(`❌ ${e.message}`);
    }
  };

  const test = async (name) => {
    setTests((t) => ({ ...t, [name]: { busy: true } }));
    try {
      const r = await api(`/admin/secrets/${name}/test`, { method: "POST" });
      setTests((t) => ({ ...t, [name]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [name]: { ok: false, detail: e.message } }));
    }
  };

  const remove = async (name, label) => {
    if (!window.confirm(`Supprimer la clé « ${label} » ?`)) return;
    await api(`/admin/secrets/${name}`, { method: "DELETE" });
    setMsg("Clé supprimée");
    refresh();
  };

  const categories = [...new Set(items.map((i) => i.category))];

  return (
    <Card title="Clés API (admin)">
      <p className="small muted" style={{ marginTop: 0 }}>
        Les clés sont chiffrées sur le serveur et ne redescendent jamais dans le
        navigateur : seul leur statut s'affiche ici.
      </p>
      {status && (
        <p className="small" style={{ marginTop: 0 }}>
          Analyste : <b>{status.analyst ? `${PROVIDER_LABELS[status.analyst]} ✓` : "aucun ✗"}</b>
          {" · "}Second avis :{" "}
          <b>{status.second_opinion ? `${PROVIDER_LABELS[status.second_opinion]} ✓` : "aucun"}</b>
          {" · "}Données marché : <b>{status.market_data ? "✓" : "✗"}</b>
          {" · "}Push : <b>{status.push_ready ? "✓" : "✗"}</b>
        </p>
      )}

      {categories.map((cat) => (
        <div key={cat} style={{ marginTop: 14 }}>
          <div className="small muted" style={{ textTransform: "uppercase", letterSpacing: 1 }}>
            {cat}
          </div>
          {items
            .filter((i) => i.category === cat)
            .map((item) => (
              <div className="field" key={item.name}>
                <label>
                  {item.label}{" "}
                  <b>{item.configured ? `configurée ${item.hint}` : "absente"}</b>
                </label>
                <div className="small muted">{item.help}</div>
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={item.configured ? "Remplacer…" : "Coller la clé…"}
                    value={drafts[item.name] || ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [item.name]: e.target.value }))}
                    style={{ flex: 1 }}
                  />
                  <button
                    className="btn small primary"
                    disabled={!(drafts[item.name] || "").trim()}
                    onClick={() => save(item.name)}
                  >
                    Enregistrer
                  </button>
                  {item.configured && (
                    <>
                      <button
                        className="btn small"
                        disabled={tests[item.name]?.busy}
                        onClick={() => test(item.name)}
                      >
                        {tests[item.name]?.busy ? "…" : "Tester"}
                      </button>
                      <button className="btn small danger" onClick={() => remove(item.name, item.label)}>
                        ✕
                      </button>
                    </>
                  )}
                </div>
                {tests[item.name] && !tests[item.name].busy && (
                  <div className={`small ${tests[item.name].ok ? "pos" : "neg"}`} style={{ marginTop: 6 }}>
                    {tests[item.name].ok ? "✅" : "❌"} {tests[item.name].detail}
                  </div>
                )}
              </div>
            ))}
        </div>
      ))}
      {msg && <div className="small" style={{ marginTop: 10 }}>{msg}</div>}
    </Card>
  );
}
