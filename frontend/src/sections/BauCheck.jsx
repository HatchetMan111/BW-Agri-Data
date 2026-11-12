import { useEffect, useState } from 'react'
import { ScoreRing, FaktorBar, AussageBox, Rohdaten, PrintButton } from '../components/ui.jsx'
import { useCheck, LoadingBox } from './useCheck.jsx'
import { BAUCHECK } from '../data/baucheck.js'

function KaufCheckliste() {
  const [done, setDone] = useState(() => {
    try { return JSON.parse(localStorage.getItem('baucheck') || '{}') } catch { return {} }
  })
  const toggle = (i, v) => {
    const next = { ...done, [i]: v }
    setDone(next)
    localStorage.setItem('baucheck', JSON.stringify(next))
  }
  return (
    <div className="card">
      <h3>📋 Kauf-Checkliste <span className="small">(wird lokal gespeichert)</span></h3>
      <ul className="clean checklist">
        {BAUCHECK.map((c, i) => (
          <li key={i}>
            <label>
              <input type="checkbox" checked={!!done[i]} onChange={(e) => toggle(i, e.target.checked)} />
              <span><b>{c[0]}</b><br /><span className="small">{c[1]}</span></span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AmpelBadge({ a }) {
  return a === 'gruen' ? <span className="badge ok">🟢 unauffällig</span>
    : a === 'gelb' ? <span className="badge warn">🟡 Auflagen prüfen</span>
      : <span className="badge bad">🔴 K.O. – Bauamt klären</span>
}

export default function BauCheck({ koord }) {
  const chk = useCheck('/api/bau/test', koord.lat, koord.lon)
  const b = chk.data
  const fn = {
    schutz: '🏛️ Schutzgebiete (30 %)', laerm: '🔊 Lärm-Abstände (20 %)',
    starkregen: '⛈️ Starkregen (15 %)', hang: '⛰️ Hang/Baugrund (15 %)', lage: '🚏 Lage (20 %)',
  }
  const koList = (b?.ko_kriterien || []).map((k, i) => <div className="warnbox" key={i}>🛑 <b>K.O.:</b> {k}</div>)
  const aufList = (b?.auflagen || []).map((k, i) => <div className="tip" key={i}>⚠️ {k}</div>)
  const denk = (b?.denkmal || []).filter((o) => o.treffer).map((o, i) => (
    <li key={i}>🏛️ <b>{o.label}</b><br /><span className="small">{o.beschreibung || ''}</span></li>
  ))
  return (
    <section>
      <div className="card no-print">
        <h3>🏗️ Grundstück-Erwerb-Einschätzung</h3>
        <p className="small">K.O.-Check (ÜSG/NSG/FFH) · Denkmalschutz (LAD) · Lärm-Abstände · Starkregen · Hang · Lage (ÖPNV/Einkauf/Schule/Arzt). Übernimmt die Koordinaten aus „Grundstück".</p>
        <button className="primary" onClick={chk.run}>Bau-Check neu starten</button>
      </div>
      {chk.busy && <LoadingBox text="Prüfe Schutzgebiete, Denkmal, Lärm, Starkregen, Lage" sekunden />}
      {chk.err && <div className="err">Bau-Check fehlgeschlagen: {chk.err}</div>}
      {b && (
        <>
          {koList}
          <div className="card">
            <ScoreRing score={b.score}
              label={b.ampel === 'gruen' ? 'Unauffällig' : b.ampel === 'gelb' ? 'Auflagen prüfen' : 'K.O. – klären'}
              sub={<><AmpelBadge a={b.ampel} /> <span className="small">{b.lat}, {b.lon} · {b.dauer_s}s</span></>} />
          </div>
          <PrintButton />
          <AussageBox aussage={b.aussagekraft} gegenwert={b.gegenwert} />
          {aufList}
          <div className="card"><h3>📊 Faktoren</h3>
            {Object.entries(b.faktoren || {}).map(([k, f]) => <FaktorBar key={k} name={fn[k] || k} f={f} />)}
          </div>
          {denk.length ? <div className="card"><h3>🏛️ Denkmalschutz (LAD, ±130 m)</h3><ul className="clean">{denk}</ul></div> : null}
          <Rohdaten data={b} />
        </>
      )}
      <KaufCheckliste />
    </section>
  )
}
