import { useCallback, useEffect, useRef, useState } from "react";
import { api, connectWS, getToken, setToken } from "./api";
import Dashboard from "./pages/Dashboard";
import History from "./pages/History";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Signals from "./pages/Signals";

const NAV = [
  ["dashboard", "Dashboard", "M3 13h4l3-8 4 14 3-8h4"],
  ["signals", "Signaux", "M12 3v3m0 12v3m9-9h-3M6 12H3m14.5-5.5l-2 2m-9 9l-2 2m13 0l-2-2m-9-9l-2-2M12 8a4 4 0 100 8 4 4 0 000-8z"],
  ["history", "Historique", "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"],
  ["reports", "Rapports", "M9 17v-6m4 6V7m4 10v-3M5 21h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z"],
  ["settings", "Réglages", "M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7.5 7.5 0 00-2-1.2L14.5 3h-5l-.4 2.6a7.5 7.5 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.4l-2 1.6 2 3.4 2.4-1a7.5 7.5 0 002 1.2l.4 2.6h5l.4-2.6a7.5 7.5 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z"],
];

function Login() {
  const [token, setTok] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    try {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      if (!resp.ok) throw new Error("jeton invalide");
      setToken(token);
      window.location.reload();
    } catch (e2) {
      setErr(e2.message);
    }
  };

  return (
    <div className="login">
      <img src="/icon.svg" alt="" className="big-logo" />
      <h1>
        News<span style={{ background: "var(--accent-grad)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>Trader</span>
      </h1>
      <p>Trading piloté par l'actualité</p>
      <form onSubmit={submit}>
        <input
          type="password"
          placeholder="Jeton d'accès (API_TOKEN)"
          value={token}
          onChange={(e) => setTok(e.target.value)}
          autoFocus
        />
        {err && <div className="err">{err}</div>}
        <button className="btn primary" type="submit">Entrer</button>
      </form>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [dash, setDash] = useState(null);
  const wsRef = useRef(null);

  const refresh = useCallback(() => {
    api("/dashboard").then(setDash).catch(() => {});
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    refresh();
    const poll = setInterval(refresh, 30_000);
    wsRef.current = connectWS(() => refresh());
    return () => {
      clearInterval(poll);
      wsRef.current?.close();
    };
  }, [refresh]);

  if (!getToken()) return <Login />;

  const mode = dash?.mode;
  const isLive = mode && (mode.live_trading212 || mode.live_kraken);

  return (
    <>
      <header className="topbar">
        <div className="logo">
          <img src="/icon.svg" alt="" />
          <span>
            News<span className="grad">Trader</span>
          </span>
        </div>
        <div className="spacer" />
        {mode?.kill_switch && <span className="chip kill">⛔ kill-switch</span>}
        {mode && <span className={`chip ${isLive ? "live" : "paper"}`}>{isLive ? "● LIVE" : "◌ PAPER"}</span>}
      </header>

      <main>
        {tab === "dashboard" && <Dashboard data={dash} />}
        {tab === "signals" && <Signals />}
        {tab === "history" && <History />}
        {tab === "reports" && <Reports />}
        {tab === "settings" && <Settings onSaved={refresh} />}
      </main>

      <nav className="nav">
        <svg width="0" height="0" style={{ position: "absolute" }}>
          <defs>
            <linearGradient id="navgrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#22d3ee" />
              <stop offset="1" stopColor="#a78bfa" />
            </linearGradient>
          </defs>
        </svg>
        {NAV.map(([key, label, d]) => (
          <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d={d} />
            </svg>
            {label}
          </button>
        ))}
      </nav>
    </>
  );
}
