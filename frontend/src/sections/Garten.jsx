import { useEffect, useState } from 'react'
import GartenPanel from '../components/GartenPanel.jsx'
import { j } from '../api.js'

/** Garten-Tab: zeigt die Empfehlung aus dem Standort-Check oder holt sie selbst. */
export default function Garten({ koord, gartenPanel, setGartenPanel }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (gartenPanel) return
    let alive = true
    setBusy(true); setErr('')
    j(`/api/garten/empfehlung?lat=${encodeURIComponent(koord.lat)}&lon=${encodeURIComponent(koord.lon)}`)
      .then((g) => { if (alive) setGartenPanel(<GartenPanel e={g} />) })
      .catch((e) => { if (alive) setErr(String(e.message || e)) })
      .finally(() => { if (alive) setBusy(false) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const neu = async () => {
    setBusy(true); setErr('')
    try {
      const g = await j(`/api/garten/empfehlung?lat=${encodeURIComponent(koord.lat)}&lon=${encodeURIComponent(koord.lon)}`)
      setGartenPanel(<GartenPanel e={g} />)
    } catch (e) { setErr(String(e.message || e)) } finally { setBusy(false) }
  }

  return (
    <section>
      <div className="card">
        <h3>🌱 Was passt zu Boden, Wetter &amp; Saison?</h3>
        <p className="small">Gieß-Empfehlung aus echtem Regen + Boden + Saison. Koordinaten: {koord.lat}, {koord.lon}</p>
        <button className="primary" onClick={neu} disabled={busy}>Empfehlung neu berechnen</button>
        {err && <div className="err">Abruf fehlgeschlagen: {err}</div>}
        {busy && !gartenPanel ? <p className="loading">Berechne …</p> : null}
      </div>
      <div className="card">{gartenPanel || <p className="small">Wird berechnet …</p>}</div>
    </section>
  )
}
