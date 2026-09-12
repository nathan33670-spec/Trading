import { useMemo, useRef, useState } from "react";
import { fmtEUR } from "./api";

export const Card = ({ title, children, className = "" }) => (
  <section className={`card ${className}`}>
    {title && <h3>{title}</h3>}
    {children}
  </section>
);

export const Tile = ({ label, value, positive }) => (
  <div className="tile">
    <div className="label">{label}</div>
    <div className={`value ${positive === undefined ? "" : positive ? "pos" : "neg"}`}>{value}</div>
  </div>
);

export const Empty = ({ children }) => <div className="empty">{children}</div>;

/* Jauge d'enveloppe : part engagée du portefeuille face à son plafond. */
export const Gauge = ({ label, used, max, amount }) => {
  const pct = max > 0 ? Math.min((used / max) * 100, 100) : 0;
  const full = used >= max;
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span>{label}</span>
        <b>
          {used} % <span className="muted">/ {max} %</span>
          {amount != null && <span className="muted"> · {fmtEUR(amount)}</span>}
        </b>
      </div>
      <div className="bar">
        <i style={{ width: `${pct}%`, background: full ? "var(--warn)" : "var(--accent-grad)" }} />
      </div>
    </div>
  );
};

export const ConvictionBar = ({ label, value, color }) => (
  <div className="conviction">
    <span style={{ width: 58 }}>{label}</span>
    <div className="bar" role="img" aria-label={`${label} ${value}/100`}>
      <i style={{ width: `${value}%`, background: color }} />
    </div>
    <b style={{ width: 30, textAlign: "right" }}>{value ?? "—"}</b>
  </div>
);

export const Switch = ({ checked, onChange }) => (
  <label className="switch">
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    <i />
  </label>
);

/* ── Courbe d'equity : SVG, ligne 2px + aire, crosshair & tooltip au survol ── */
export function EquityChart({ data, height = 190 }) {
  const wrapRef = useRef(null);
  const [hover, setHover] = useState(null);
  const width = 640; // viewBox — le SVG est responsive

  const { path, area, points, min, max } = useMemo(() => {
    if (!data || data.length < 2) return { points: [] };
    const values = data.map((d) => d.equity);
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    if (hi - lo < 1) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * 0.12;
    lo -= pad; hi += pad;
    const px = 8, pyTop = 10, pyBottom = 22;
    const X = (i) => px + (i / (data.length - 1)) * (width - 2 * px);
    const Y = (v) => pyTop + (1 - (v - lo) / (hi - lo)) * (height - pyTop - pyBottom);
    const pts = data.map((d, i) => ({ x: X(i), y: Y(d.equity), ...d }));
    const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
    return {
      path: line,
      area: `${line} L${pts[pts.length - 1].x},${height - pyBottom} L${pts[0].x},${height - pyBottom} Z`,
      points: pts,
      min: Math.min(...values),
      max: Math.max(...values),
    };
  }, [data, height]);

  if (!points.length) {
    return <Empty>La courbe se dessinera après les premiers relevés horaires.</Empty>;
  }

  const onMove = (e) => {
    const rect = wrapRef.current.getBoundingClientRect();
    const x = ((e.clientX ?? e.touches?.[0]?.clientX) - rect.left) / rect.width * width;
    let best = points[0];
    for (const p of points) if (Math.abs(p.x - x) < Math.abs(best.x - x)) best = p;
    setHover({ ...best, left: (best.x / width) * rect.width, top: (best.y / height) * rect.height });
  };

  return (
    <div
      className="chart-wrap"
      ref={wrapRef}
      onMouseMove={onMove}
      onTouchMove={onMove}
      onMouseLeave={() => setHover(null)}
      onTouchEnd={() => setHover(null)}
    >
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }} role="img"
           aria-label="Évolution de la valeur du portefeuille sur 30 jours">
        <defs>
          <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#0891b2" stopOpacity="0.35" />
            <stop offset="1" stopColor="#0891b2" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1="8" x2={width - 8} y1={10 + f * (height - 32)} y2={10 + f * (height - 32)}
                stroke="var(--grid)" strokeWidth="1" />
        ))}
        <path d={area} fill="url(#eqfill)" />
        <path d={path} fill="none" stroke="var(--series-1)" strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" />
        {hover && (
          <>
            <line x1={hover.x} x2={hover.x} y1="10" y2={height - 22} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={hover.x} cy={hover.y} r="5" fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2" />
          </>
        )}
        <text x="8" y={height - 6} fontSize="10.5" fill="var(--ink-3)">min {fmtEUR(min)}</text>
        <text x={width - 8} y={height - 6} fontSize="10.5" fill="var(--ink-3)" textAnchor="end">max {fmtEUR(max)}</text>
      </svg>
      {hover && (
        <div className="chart-tooltip" style={{ left: hover.left, top: hover.top }}>
          <div className="muted">{new Date(hover.ts).toLocaleString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</div>
          <div className="v">{fmtEUR(hover.equity)}</div>
        </div>
      )}
    </div>
  );
}
