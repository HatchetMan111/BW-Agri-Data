import { useState } from 'react'
import { GLOSSAR } from '../data/glossar.js'

/** Glossar-Tab: Fachbegriffe mit Live-Suche. */
export default function Glossar() {
  const [f, setF] = useState('')
  const needle = f.toLowerCase().trim()
  const gruppen = GLOSSAR.map(([gruppe, begriffe]) => ({
    gruppe,
    treffer: begriffe.filter(([t, e]) =>
      !needle || t.toLowerCase().includes(needle) || e.toLowerCase().includes(needle)),
  })).filter((g) => g.treffer.length)
  return (
    <section>
      <div className="card">
        <h3>❓ Fachbegriffe einfach erklärt</h3>
        <p className="small">Alle Begriffe, die in den Ergebnissen vorkommen — in normalem Deutsch, mit Tipp was zu tun ist.</p>
        <input value={f} onChange={(e) => setF(e.target.value)} placeholder="Suchen, z. B. Schluff …" aria-label="Glossar durchsuchen" />
      </div>
      {gruppen.length === 0
        ? <div className="card"><p className="small">Nichts gefunden – anderen Suchbegriff versuchen.</p></div>
        : gruppen.map((g) => (
          <div className="card" key={g.gruppe}>
            <h3>{g.gruppe}</h3>
            <ul className="clean">
              {g.treffer.map(([t, e]) => <li key={t}><b>{t}</b><br /><span className="small">{e}</span></li>)}
            </ul>
          </div>
        ))}
    </section>
  )
}
