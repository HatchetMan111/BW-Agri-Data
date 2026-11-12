import { useEffect, useState } from 'react'
import { j } from '../api.js'

/** Beete-Tab: CRUD + Export-Links. */
export default function Beete({ standorte }) {
  const [name, setName] = useState('')
  const [kultur, setKultur] = useState('')
  const [notiz, setNotiz] = useState('')
  const [siteId, setSiteId] = useState('')
  const [beete, setBeete] = useState(null)
  const [err, setErr] = useState('')

  const load = async () => {
    try {
      const d = await j('/api/beete')
      setBeete(d); setErr('')
    } catch (e) { setErr(String(e.message || e)) }
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!name.trim()) { alert('Bitte einen Beet-Namen eingeben.'); return }
    const body = { name: name.trim(), kultur: kultur.trim(), notiz: notiz.trim() }
    const sid = parseInt(siteId, 10)
    if (isFinite(sid)) body.standort_id = sid
    try {
      await j('/api/beete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setName(''); setKultur(''); setNotiz(''); setSiteId('')
      load()
    } catch (e) { alert('Speichern fehlgeschlagen: ' + e.message) }
  }

  const del = async (id) => {
    if (!confirm('Beet wirklich löschen?')) return
    try { await fetch('/api/beete/' + id, { method: 'DELETE' }) } catch { /* ignore */ }
    load()
  }

  return (
    <section>
      <div className="card">
        <h3>➕ Beet anlegen</h3>
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="z. B. Hochbeet Nord" />
        <div className="row">
          <div>
            <label>Kultur</label>
            <input value={kultur} onChange={(e) => setKultur(e.target.value)} placeholder="z. B. Kartoffeln" />
          </div>
          <div>
            <label>Standort</label>
            <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
              <option value="">– keiner –</option>
              {(standorte || []).map((s) => <option value={s.id} key={s.id}>{s.label} [ID {s.id}]</option>)}
            </select>
          </div>
        </div>
        <label>Notiz</label>
        <textarea value={notiz} onChange={(e) => setNotiz(e.target.value)} rows={2} placeholder="z. B. Kompost eingearbeitet" />
        <button className="primary" onClick={add}>Speichern</button>
      </div>

      <div className="card">
        <h3>🥬 Meine Beete</h3>
        {err ? <div className="err">Laden fehlgeschlagen: {err}</div>
          : beete === null ? <p className="small">Lade …</p>
            : beete.length === 0 ? <p className="small">Noch keine Beete. Lege oben dein erstes an.</p>
              : <ul className="clean">
                {beete.map((b) => (
                  <li key={b.id}><b>{b.name}</b>{b.kultur ? <> – {b.kultur}</> : null}{' '}
                    <button className="danger" onClick={() => del(b.id)}>löschen</button>
                    {b.standort_id ? <><br /><span className="small">Standort-ID {b.standort_id}</span></> : null}
                    {b.notiz ? <><br /><span className="small">{b.notiz}</span></> : null}
                  </li>
                ))}
              </ul>}
        <button className="secondary" onClick={load}>Neu laden</button>
      </div>

      <div className="card">
        <h3>📤 Export</h3>
        <p className="small">
          <a href="/api/export" target="_blank" rel="noopener noreferrer">Alle Daten als JSON</a> ·{' '}
          <a href="/docs" target="_blank" rel="noopener noreferrer">API-Doku</a>
        </p>
      </div>
    </section>
  )
}
