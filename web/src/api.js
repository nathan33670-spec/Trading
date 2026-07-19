// Client API : jeton stocké localement, erreurs 401 → retour au login.

const KEY = "nt_token";

export const getToken = () => localStorage.getItem(KEY) || "";
export const setToken = (t) => localStorage.setItem(KEY, t);
export const clearToken = () => localStorage.removeItem(KEY);

export async function api(path, options = {}) {
  const resp = await fetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Token": getToken(),
      ...(options.headers || {}),
    },
  });
  if (resp.status === 401) {
    clearToken();
    window.location.reload();
    throw new Error("session expirée");
  }
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || `erreur ${resp.status}`);
  }
  return resp.json();
}

export function connectWS(onMessage) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/api/ws?token=${encodeURIComponent(getToken())}`);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch { /* ignore */ }
  };
  const ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
  ws.onclose = () => clearInterval(ping);
  return ws;
}

// ── Web Push ────────────────────────────────────────────────────────────────

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

export async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("notifications non supportées par ce navigateur");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("permission refusée");

  const reg = await navigator.serviceWorker.ready;
  const { key } = await api("/push/vapid-public-key");
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key),
  });
  const json = sub.toJSON();
  await api("/push/subscribe", {
    method: "POST",
    body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }),
  });
}

// ── Formatage ───────────────────────────────────────────────────────────────

export const fmtEUR = (v, sign = false) =>
  `${sign && v > 0 ? "+" : ""}${new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2,
  }).format(v)}`;

export const fmtPct = (v) => `${v > 0 ? "+" : ""}${(v ?? 0).toFixed(2)} %`;

export const fmtDate = (iso) =>
  new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
