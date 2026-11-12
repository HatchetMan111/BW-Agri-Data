import { useEffect, useState } from 'react'
import Karte from '../components/Karte.jsx'
import Report from './Report.jsx'
import GartenPanel from '../components/GartenPanel.jsx'
import { j, osmUrl } from '../api.js'

/** Grundstueck-Tab: Suche, Koordinaten, Karte, Report, gespeicherte Standorte. */
export default function Grundstueck({ koord, setKoord, report, setReport, gartenPanel, setGartenPanel }) {
  const [latStr, setLatStr] = useState(String(koord.lat))
  const [lonStr, setLonStr] = useState(String(koord.lon))
  const [q, setQ] = useState('')
  const [suche, setSuche] = useState(null)   // null | {laeuft} | {treffer} | {fehler} | {hinweis}
  const [busy, setBusy] = useState(false)
  const [sites, setSites] = useState(null)
  const [sitesErr, setSitesErr] = useState('')
  const [punktLabel, setPunktLabel] = useState('Punkt: noch nicht bestimmt.')
  const [err, setErr] = useState('')

  // Koordinaten von aussen (Karte, Standort-Liste) uebernehmen
  useEffect(() => {
    setLatStr(String(koord.lat)); setLonStr(String(koord.lon)
    )
  }, [koord])

  // Reverse-Geocode fuer den Punkt-Label
  useEffect(() => {
    let alive = true
    setPunktLabel(`Punkt: ${koord.lat}, ${koord.lon} (Adresse wird geladen …)`)
    j(`/api/reverse_geocode?lat=${encodeURIComponent(koord.lat)}&lon=${encodeURIComponent(koord.lon)}`)
      .then((r) => {
        if (!alive) return
        if (r.status === 'live' && (r.plz || r.ort)) {
          setPunktLabel(`Punkt: ${r.plz} ${r.ort}${r.strasse ? ', ' + r.strasse : ''} (${koord.lat}, ${koord.lon})`)
        } else setPunktLabel(`Punkt: ${koord.lat}, ${koord.lon}`)
      })
      .catch(() => { if (alive) setPunktLabel(`Punkt: ${koord.lat}, ${koord.lon}`) })
    return () => { alive = false }
  }, [koord])

  const setCoords = (lat, lon) => {
    lat = Math.round(lat * 10000) / 10000
    lon = Math.round(lon * 10000) / 10000
    setKoord({ lat, lon })
  }

  const onInput = () => {
    const la = parseFloat(latStr.replace(',', '.')), lo = parseFloat(lonStr.replace(',', '.'))
    if (isFinite(la) && isFinite(lo)) setKoord({ lat: la, lon: lo })
  }

  async function doSearch() {
    const query = q.trim()
    if (query.length < 2) { setSuche({ hinweis: 'Mindestens 2 Zeichen (PLZ oder Ort) eingeben.' }); return }
    setSuche({ laeuft: true })
    try {
      const d = await j('/api/geocode?q=' + encodeURIComponent(query))
      if (d.status !== 'live') setSuche({ hinweis: `Suche offline${d.error ? ' (' + String(d.error).slice(0, 80) + ')' : ''} – Koordinaten direkt eingeben oder Karte klicken.` })
      else if (!d.treffer.length) setSuche({ hinweis: 'Keine Treffer – PLZ oder größeren Ort versuchen.' })
      else setSuche({ treffer: d.treffer })
    } catch (e) {
      setSuche({ fehler: `Suche fehlgeschlagen: ${e.message}` })
    }
  }

  async function check() {
    const la = parseFloat(latStr.replace(',', '.')), lo = parseFloat(lonStr.replace(',', '.'))
    if (!isFinite(la) || !isFinite(lo)) { setErr('Bitte gültige Koordinaten eingeben (oder auf die Karte klicken).'); return }
    setKoord({ lat: la, lon: lo })
    setErr('')
    setBusy(true)
    setReport(null)
    try {
      const d = await j(`/api/standort/reverse?lat=${encodeURIComponent(la)}&lon=${encodeURIComponent(lo)}`)
      setReport(d)
      // Garten-Empfehlung nachziehen und global fuer Tab B + Inline ablegen
      const g = await j(`/api/garten/empfehlung?lat=${encodeURIComponent(la)}&lon=${encodeURIComponent(lo)}`)
      setGartenPanel(<GartenPanel e={g} />)
    } catch (e) {
      setErr(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  const loadSites = async () => {
    try {
      const d = await j('/api/standorte')
      setSites(d); setSitesErr('')
    } catch (e) { setSitesErr(String(e.message || e)) }
  }
  useEffect(() => { loadSites() }, [])

  const save = async () => {
    const la = parseFloat(latStr.replace(',', '.')), lo = parseFloat(lonStr.replace(',', '.'))
    if (!isFinite(la) || !isFinite(lo)) { alert('Bitte gültige Koordinaten (oder erst Suchen + Prüfen).'); return }
    const label = q.trim() || 'Standort'
    try {
      const d = await j('/api/standorte', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label.slice(0, 120), lat: la, lon: lo }),
      })
      alert(`Gespeichert (ID ${d.id}).`)
      loadSites()
    } catch (e) { alert('Speichern fehlgeschlagen: ' + e.message) }
  }

  const delSite = async (id) => {
    if (!confirm('Standort wirklich löschen?')) return
    try { await fetch('/api/standorte/' + id, { method: 'DELETE' }) } catch { /* ignore */ }
    loadSites()
  }

  const useSite = (la, lo) => { setKoord({ lat: la, lon: lo }) }

  return (
    <section>
      <div className="card">
        <h3>📍 Standort suchen oder wählen</h3>
        <label htmlFor="q">Adresse / Ort (z. B. „Freiburg Münsterplatz" oder PLZ)</label>
        <div className="row even">
          <div>
            <input id="q" placeholder="Adresse eingeben …" value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') doSearch() }} />
          </div>
          <div><button className="primary" style={{ marginTop: 0 }} onClick={doSearch}>Suchen</button></div>
        </div>
        {suche && (
          <div className="searchres">
            {suche.laeuft && <div>Suche läuft …</div>}
            {suche.hinweis && <div>{suche.hinweis}</div>}
            {suche.fehler && <div>{suche.fehler} – Backend unter <a href="/api/health" target="_blank" rel="noopener noreferrer">/api/health</a> prüfen.</div>}
            {suche.treffer && suche.treffer.map((t, i) => (
              <div key={i} onClick={() => { setSuche(null); setKoord({ lat: t.lat, lon: t.lon }); check() }}>{t.name}</div>
            ))}
          </div>
        )}
        <label>Oder direkt Koordinaten (Klick auf die Karte übernimmt)</label>
        <div className="row">
          <div><input value={latStr} onChange={(e) => { setLatStr(e.target.value); onInput() }}
            inputMode="decimal" aria-label="Breite" /></div>
          <div><input value={lonStr} onChange={(e) => { setLonStr(e.target.value); onInput() }}
            inputMode="decimal" aria-label="Länge" /></div>
        </div>
        <div>
          <button className="primary" onClick={check} disabled={busy}>Prüfen</button>
          <button className="secondary" onClick={save}>Als Standort speichern</button>
        </div>
        <p className="small" style={{ marginBottom: 0 }}>{punktLabel}</p>
      </div>

      <div className="card">
        <h3>🗺️ Karte <span className="small">(Klick setzt den Punkt · rechts oben: Luftbild &amp; Fachlayer)</span></h3>
        <Karte lat={koord.lat} lon={koord.lon} onPick={setCoords}
          reservate={report?.umfeld?.reservate || []}
          sights={report?.umfeld?.sehenswuerdigkeiten || []}
          laden={report?.laden?.saeulen || []} />
        <p className="small" style={{ marginBottom: 0 }}>
          <a href={osmUrl(koord.lat, koord.lon)} target="_blank" rel="noopener noreferrer">Auf OpenStreetMap zeigen ↗</a>
        </p>
      </div>

      {err && <div className="err">Abfrage fehlgeschlagen: {err}<br />
        <span className="small">Backend-Status: <a href="/api/health" target="_blank" rel="noopener noreferrer">/api/health</a></span></div>}
      {busy && (
        <div className="card">
          <p className="loading">Frage Boden, Wetter, Pegel &amp; Umfeld ab (dauert ein paar Sekunden) …</p>
          <div className="skeleton" style={{ width: '80%' }} />
          <div className="skeleton" style={{ width: '60%' }} />
          <div className="skeleton" style={{ width: '70%' }} />
        </div>
      )}
      {report && <Report d={report} garten={gartenPanel} />}

      <div className="card">
        <h3>💾 Gespeicherte Standorte</h3>
        {sitesErr ? <div className="err">Laden fehlgeschlagen: {sitesErr}</div>
          : sites === null ? <p className="small">Lade …</p>
            : sites.length === 0 ? <p className="small">Noch keine Standorte.</p>
              : <ul className="clean">
                {sites.map((s) => (
                  <li key={s.id}><b>{s.label}</b> – {s.lat}, {s.lon} <span className="small">[ID {s.id}]</span>{' '}
                    <button className="linkbtn" onClick={() => useSite(s.lat, s.lon)}>übernehmen</button> ·{' '}
                    <button className="linkbtn red" onClick={() => delSite(s.id)}>löschen</button></li>
                ))}
              </ul>}
        <button className="secondary" onClick={loadSites}>Neu laden</button>
      </div>
    </section>
  )
}
