import { ScoreRing, FaktorBar, AussageBox, Rohdaten, PrintButton } from '../components/ui.jsx'
import { useCheck, LoadingBox } from './useCheck.jsx'

export default function Wald({ koord }) {
  const chk = useCheck('/api/wald/test', koord.lat, koord.lon)
  const w = chk.data
  const fn = {
    waldanteil: '🌲 Waldanteil (40 %)', klimafitness: '🌤️ Klimafitness (30 %)',
    sturmsicherheit: '🌪️ Sturmsicherheit (30 %)',
  }
  const hin = (w?.hinweise || []).map((h, i) => <div className="tip" key={i}>💡 {h}</div>)
  return (
    <section>
      <div className="card no-print">
        <h3>🌲 Wald-Potenzial</h3>
        <p className="small">Waldanteil + Laub/Nadel (OSM), Klimafitness (ERA5), Sturmsicherheit (Hang/Exposition), Boden-Hinweis. FVA-Karten als Overlay in der Grundstück-Karte.</p>
        <button className="primary" onClick={chk.run}>Wald-Check neu starten</button>
      </div>
      {chk.busy && <LoadingBox text="Analysiere Waldanteil, Klima, Sturm" />}
      {chk.err && <div className="err">Wald-Check fehlgeschlagen: {chk.err}</div>}
      {w && (
        <>
          <div className="card">
            <ScoreRing score={w.score} label={w.label}
              sub={<span className="small">{w.lat}, {w.lon} · {w.dauer_s}s</span>} />
          </div>
          <AussageBox aussage={w.aussagekraft} gegenwert={w.gegenwert} />
          <div className="card"><h3>📊 Faktoren</h3>
            {Object.entries(w.faktoren || {}).map(([k, f]) => <FaktorBar key={k} name={fn[k] || k} f={f} />)}
          </div>
          {hin}
          <p className="small">{w.fva_hinweis || ''}</p>
          <PrintButton />
          <Rohdaten data={w} />
        </>
      )}
    </section>
  )
}
