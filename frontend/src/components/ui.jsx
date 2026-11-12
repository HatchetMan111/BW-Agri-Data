export function LiveBadge({ mod }) {
  if (!mod) return null
  if (mod.status === 'live') {
    return (mod.cached || mod.mess_cached)
      ? <span className="badge info">Live (Cache)</span>
      : <span className="badge ok">Live</span>
  }
  if (mod.status === 'offline') {
    return <span className="badge warn">Offline{mod.error ? ' – ' + String(mod.error).slice(0, 60) : ''}</span>
  }
  return <span className="badge warn">Eingeschränkt</span>
}

export function VertrauenDot({ v }) {
  if (v === 'hoch') return <span className="badge ok" title="Amtliche Messung / Fachdaten">● belastbar</span>
  if (v === 'mittel') return <span className="badge info" title="Modell oder Rasterdaten">● Modell</span>
  if (!v) return null
  return <span className="badge warn" title="Näherung / Community-Daten">● Schätzung</span>
}

export function scoreColor(s) {
  if (s == null) return '#888'
  return s >= 80 ? '#2f7d4f' : s >= 65 ? '#7ab54a' : s >= 50 ? '#a97b1f' : '#b53a3a'
}

export function ScoreRing({ score, label, sub }) {
  if (score == null) {
    return <div className="bignum">?<div className="small">{label || ''}</div></div>
  }
  const col = scoreColor(score)
  const r = 54
  const c = 2 * Math.PI * r
  const off = c * (1 - Math.max(0, Math.min(100, score)) / 100)
  return (
    <div className="ringwrap">
      <svg className="ring" viewBox="0 0 132 132" role="img" aria-label={`Score ${score} von 100`}>
        <circle cx="66" cy="66" r={r} fill="none" stroke="currentColor" opacity=".15" strokeWidth="12" />
        <circle cx="66" cy="66" r={r} fill="none" stroke={col} strokeWidth="12" strokeLinecap="round"
          strokeDasharray={c.toFixed(1)} strokeDashoffset={off.toFixed(1)} transform="rotate(-90 66 66)" />
        <text x="66" y="62" textAnchor="middle" fontSize="30" fontWeight="700" fill="currentColor">{score}</text>
        <text x="66" y="82" textAnchor="middle" fontSize="11" fill="currentColor" opacity=".6">/ 100</text>
      </svg>
      <div className="ringmeta">
        <div style={{ fontSize: 17, fontWeight: 700 }}>{label || ''}</div>
        <div className="small">{sub || ''}</div>
      </div>
    </div>
  )
}

export function TexBar({ label, pct, color }) {
  const p = Math.max(0, Math.min(100, pct || 0))
  return (
    <div>
      <span className="small">{label}: <b>{p.toFixed(0)} %</b></span>
      <div className="bar"><i style={{ width: `${p}%`, background: color }} /></div>
    </div>
  )
}

export function FaktorBar({ name, f }) {
  return (
    <div>
      <span className="small"><b>{name}</b>: {f.wert == null ? 'offline' : f.wert + ' / 100'} <VertrauenDot v={f.vertrauen} /></span>
      <div className="bar"><i style={{ width: `${f.wert || 0}%`, background: scoreColor(f.wert) }} /></div>
      <p className="small" style={{ margin: 0 }}>{f.text}</p>
      {f.vertrauen_grund
        ? <p className="small" style={{ margin: '0 0 6px', opacity: .55 }}>Datenbasis: {f.vertrauen_grund}</p>
        : <p style={{ margin: '0 0 6px' }} />}
    </div>
  )
}

export function Sparkline({ vals, caption = 'Wasserstand letzte ~12 h in cm' }) {
  if (!vals || vals.length < 2) return null
  const w = 300, h = 56
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = (max - min) || 1
  const pts = vals.map((v, i) =>
    `${(i / (vals.length - 1) * w).toFixed(1)},${(h - 4 - ((v - min) / span) * (h - 10)).toFixed(1)}`).join(' ')
  return (
    <>
      <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <polyline points={pts} fill="none" stroke="#5aa2e0" strokeWidth="2" />
        <text x="4" y="12" fontSize="10" fill="currentColor" opacity=".6">{max}</text>
        <text x="4" y={h - 4} fontSize="10" fill="currentColor" opacity=".6">{min}</text>
      </svg>
      <p className="small">{caption}</p>
    </>
  )
}

export function AussageBox({ aussage, gegenwert }) {
  if (!aussage || aussage.prozent == null) return null
  const col = aussage.prozent >= 80 ? '#2f7d4f' : aussage.prozent >= 55 ? '#a97b1f' : '#b53a3a'
  return (
    <div className="card">
      <h3>🔍 So belastbar ist der Wert: {aussage.prozent} %</h3>
      <div className="bar"><i style={{ width: `${aussage.prozent}%`, background: col }} /></div>
      <p className="small">{aussage.text}</p>
      {gegenwert ? <div className="tip">⚖️ <b>Gegenwert:</b> {gegenwert}</div> : null}
    </div>
  )
}

export function Rohdaten({ data }) {
  return (
    <details className="raw card">
      <summary>Rohdaten (für Fehlersuche)</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  )
}

export function PrintButton() {
  return (
    <div className="no-print">
      <button className="secondary" onClick={() => window.print()}>🖨️ Exposé drucken / als PDF</button>
    </div>
  )
}
