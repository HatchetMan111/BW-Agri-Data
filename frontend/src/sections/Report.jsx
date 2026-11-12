import { useState } from 'react'
import { LiveBadge, TexBar, Sparkline } from '../components/ui.jsx'
import { osmUrl } from '../api.js'

function BodenCard({ b }) {
  if (b.status === 'live' && !b.versiegelt) {
    const sc = b.garten_score || { wert: '?', label: '' }
    return (
      <div className="card">
        <h3>🌍 Boden <LiveBadge mod={b} /></h3>
        <div className="bignum" style={{ color: sc.wert >= 65 ? '#2f7d4f' : sc.wert >= 50 ? '#a97b1f' : '#b53a3a' }}>
          {sc.wert}<span className="small">/100 · {sc.label} für Garten</span>
        </div>
        <p style={{ margin: '4px 0' }}><b>Bodenart: {b.bodenart || '–'}</b> <span className="small">({b.tiefe || ''})</span></p>
        <TexBar label="Sand" pct={b.sand_pct || 0} color="#d9b45b" />
        <TexBar label="Schluff" pct={b.schluff_pct || 0} color="#9db87a" />
        <TexBar label="Ton" pct={b.ton_pct || 0} color="#7a5b3a" />
        <p className="small">
          pH-Wert: <b>{b.ph == null ? '–' : b.ph}</b>{b.ph_wertung ? ' – ' + b.ph_wertung : ''}
          {b.humus_g_kg != null ? <> · Humus: <b>{b.humus_g_kg} g/kg</b></> : null}
        </p>
        {b.lgrb && b.lgrb.gesamtbewertung ? (
          <div className="tip">🏛️ <b>Behörde (LGRB BK50):</b> {b.lgrb.gesamtbewertung.einheit} – {b.lgrb.gesamtbewertung.legende}
            {b.lgrb.nfk?.extra?.['nfk-Wert'] ? <> · <b>nfk-Wert {b.lgrb.nfk.extra['nfk-Wert']}</b> (nutzbare Feldkapazität)</> : null}
          </div>
        ) : b.lgrb ? <p className="small">LGRB: keine Kartierung an diesem Punkt (z. B. Siedlung).</p> : null}
        <details className="raw"><summary>Was bedeuten Sand, Schluff, Ton?</summary><p className="small">
          Das sind die <b>Korngrößen</b> des Bodens: <b>Sand</b> (2–0,063 mm, grob – lässt Wasser durch, hält kaum Nährstoffe),
          {' '}<b>Schluff</b> (0,063–0,002 mm, mittel – <b>speichert Wasser und Nährstoffe sehr gut</b>, verschlämmt aber bei Regen und bildet Krusten),
          {' '}<b>Ton</b> (&lt;0,002 mm, fein – hält am meisten Wasser/Nährstoffe, ist aber schwer zu bearbeiten und neigt zu Staunässe).<br />
          Die Mischung bestimmt die <b>Bodenart</b>: viel Sand = leicht/durchlässig (Kartoffeln lieben das), viel Schluff = fruchtbar aber verschlämmungsanfällig (mulchen!), viel Ton = schwer (nur trocken bearbeiten).
          Ideal für Gemüse: lehmige Mitte mit Humus.
        </p></details>
      </div>
    )
  }
  if (b.versiegelt) return <div className="card"><h3>🌍 Boden <LiveBadge mod={b} /></h3><div className="warnbox">🏗️ {b.hinweis || 'Versiegelte Fläche.'}</div></div>
  return <div className="card"><h3>🌍 Boden <LiveBadge mod={b} /></h3>
    <div className="warnbox">Bodendaten offline{b.error ? ' (' + String(b.error).slice(0, 80) + ')' : ''}. Später erneut versuchen.</div></div>
}

function WetterCard({ wx }) {
  if (wx.status !== 'live') {
    return <div className="card"><h3>🌤️ Wetter &amp; Höhe <LiveBadge mod={wx} /></h3>
      <div className="warnbox">Wetter offline{wx.error ? ' (' + String(wx.error).slice(0, 80) + ')' : ''}.</div></div>
  }
  const a = wx.aktuell
  const heute = (wx.tage || [])[0]
  return (
    <div className="card">
      <h3>🌤️ Wetter &amp; Höhe <LiveBadge mod={wx} /></h3>
      <div style={{ fontSize: 15 }}>
        <span style={{ fontSize: 28 }}>{a.icon}</span> <b>{a.temp} °C</b> · {a.text}{' '}
        <span className="small">· 💧 {a.feuchte} % · 🌧️ {a.regen_mm} mm
          {wx.hoehe_m != null ? <> · ⛰️ {wx.hoehe_m} m</> : null}</span>
      </div>
      <div className="fcast">
        {(wx.tage || []).map((t, i) => (
          <div className={'fday' + (i === 0 ? ' today' : '')} key={t.datum}>
            <div><b>{i === 0 ? 'Heute' : t.datum.slice(5)}</b></div>
            <div className="ic">{t.icon}</div>
            <div>{t.text}</div>
            <div>{t.tmin}–{t.tmax} °C</div>
            <div className="small">🌧️ {t.regen} mm</div>
          </div>
        ))}
      </div>
      {heute && <p className="small" style={{ margin: '8px 0 0' }}>Heute markiert · Quelle: {wx.quelle}</p>}
    </div>
  )
}

function PegelCard({ p }) {
  const [idx, setIdx] = useState(0)
  if (p.status !== 'live' || !(p.stationen || []).length) {
    return <div className="card"><h3>💧 Pegel in der Nähe <LiveBadge mod={p} /></h3>
      <div className="warnbox">Pegeldaten offline{p.error ? ' (' + String(p.error).slice(0, 80) + ')' : ''}.</div></div>
  }
  const stationen = p.stationen
  const s = stationen[Math.min(idx, stationen.length - 1)]
  const tr = s.trend_cm_24h == null ? null
    : s.trend_cm_24h > 1 ? <span className="badge warn">↗ +{s.trend_cm_24h} cm/24h</span>
      : s.trend_cm_24h < -1 ? <span className="badge ok">↘ {s.trend_cm_24h} cm/24h</span>
        : <span className="badge info">→ stabil</span>
  return (
    <div className="card">
      <h3>💧 Pegel in der Nähe <LiveBadge mod={p} /></h3>
      {stationen.length > 1 && (
        <>
          <label>Pegel wählen</label>
          <select value={idx} onChange={(e) => setIdx(+e.target.value)}>
            {stationen.map((st, i) => <option value={i} key={st.name + i}>{st.gewaesser} · {st.name} ({st.dist_km} km)</option>)}
          </select>
        </>
      )}
      <p style={{ margin: '4px 0' }}><b>{s.gewaesser} · {s.name}</b> <span className="small">({s.dist_km} km entfernt)</span> {tr}</p>
      {s.aktuell_cm != null ? (
        <>
          <div className="bignum">{s.aktuell_cm} <span className="small">cm · {(s.zeit || '').slice(0, 16).replace('T', ' ')}</span></div>
          <Sparkline vals={s.verlauf} />
        </>
      ) : <p className="small">Keine Messwerte.{s.fehler ? ` (${String(s.fehler).slice(0, 80)})` : ''}</p>}
    </div>
  )
}

function UmfeldCard({ u, lad }) {
  const res = (u.reservate || []).map((r, i) => (
    <li key={i}>🦋 <b>{r.name}</b> <span className="badge gray">{r.dist_km} km</span>{' '}
      <span className="small"><a href={osmUrl(r.lat, r.lon)} target="_blank" rel="noopener noreferrer">Karte ↗</a></span></li>
  ))
  const nutz = (u.landnutzung || []).map((n, i) => <span className="chip gray" key={i}>{n.typ} ×{n.treffer}</span>)
  const sights = (u.sehenswuerdigkeiten || []).slice(0, 8).map((s, i) => (
    <li key={i}>{s.icon || '⭐'} <b>{s.name}</b> <span className="small">{s.art || ''} · {s.dist_km} km</span></li>
  ))
  const ladList = (lad.saeulen || []).slice(0, 5).map((s, i) => (
    <li key={i}>🔌 <b>{s.kw} kW{s.schnell ? ' ⚡' : ''}</b> <span className="small">{s.betreiber} · {s.adresse} · {s.dist_km} km</span></li>
  ))
  return (
    <div className="card">
      <h3>🦋 Natur &amp; Nutzung <LiveBadge mod={u} /></h3>
      {res.length ? <ul className="clean">{res}</ul> : <p className="small">Keine Schutzgebiete im Umkreis 15 km gefunden (OSM).</p>}
      <p style={{ margin: '8px 0 4px' }}><b>Nutzung im Umfeld (3 km):</b></p>
      <div>{nutz.length ? nutz : <span className="small">–</span>}</div>
      {sights.length ? (
        <>
          <p style={{ margin: '8px 0 4px' }}><b>⭐ Sehenswert im Umkreis (10 km, auch auf der Karte):</b></p>
          <ul className="clean">{sights}</ul>
        </>
      ) : <p className="small">Keine Sehenswürdigkeiten im Umkreis gefunden.</p>}
      {ladList.length ? (
        <>
          <p style={{ margin: '8px 0 4px' }}><b>🔌 Nächste Ladesäulen <LiveBadge mod={lad} />:</b></p>
          <ul className="clean">{ladList}</ul>
        </>
      ) : null}
    </div>
  )
}

function BehoerdenCard({ bh }) {
  const rows = (bh.layer || []).map((l, i) => {
    const ic = l.status !== 'live' ? '❔' : l.treffer ? (l.stufe === 'rot' ? '🛑' : '⚠️') : '✅'
    const det = l.status !== 'live' ? <span className="small">offline</span>
      : l.treffer ? <><br /><span className="small">Treffer: <b>{(l.namen || []).join('; ') || (l.anzahl + ' Fläche(n)')}</b></span></>
        : <span className="small">frei</span>
    return <li key={i}>{ic} <b>{l.label}</b> {det}</li>
  })
  return (
    <div className="card">
      <h3>🏛️ Behörden-Check (LUBW-Fachdaten) <LiveBadge mod={bh} /></h3>
      {rows.length ? <ul className="clean">{rows}</ul> : <p className="small">Behördendaten offline – später erneut versuchen.</p>}
      <p className="small">Punktabfrage (±50 m) in NSG, FFH, LSG, WSG, FFH-Mähwiesen, Überschwemmungsgebieten. 🛑 = Bauen/Nutzung stark eingeschränkt · ⚠️ = Auflagen prüfen · ✅ = frei. Quelle: LUBW RIPS (DL-BY-2.0).</p>
    </div>
  )
}

export default function Report({ d, garten }) {
  if (!d) return null
  const bw = d.in_bw
    ? <span className="badge ok">📍 Baden-Württemberg</span>
    : <span className="badge bad">Außerhalb BW – Fachdaten nur für BW</span>
  const b = d.boden || {}, wx = d.wetter || {}, p = d.pegel || {}, u = d.umfeld || {}, lad = d.laden || {}
  return (
    <>
      <div className="card">
        <h3>🧾 {d.lat}, {d.lon} <span className="small">
          <a href={osmUrl(d.lat, d.lon)} target="_blank" rel="noopener noreferrer">OSM ↗</a> · {d.dauer_s}s</span></h3>
        <div>{bw}</div>
      </div>
      <div className="grid">
        <BodenCard b={b} />
        <WetterCard wx={wx} />
        <PegelCard p={p} />
        <UmfeldCard u={u} lad={lad} />
        <div className="card no-print">
          <h3>🖨️ Exposé <span className="small">(druckt nur diesen Bericht)</span></h3>
          <button className="secondary" onClick={() => window.print()}>Drucken / PDF</button>
        </div>
      </div>
      <BehoerdenCard bh={d.behoerden || {}} />
      <div className="card">
        <h3>🌱 Garten-Empfehlung</h3>
        {garten || <p className="small">Wird geladen …</p>}
      </div>
    </>
  )
}
