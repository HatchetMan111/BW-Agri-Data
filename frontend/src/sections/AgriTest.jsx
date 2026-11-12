import { ScoreRing, FaktorBar, AussageBox, Rohdaten, PrintButton } from '../components/ui.jsx'
import { useCheck, LoadingBox } from './useCheck.jsx'

export default function AgriTest({ koord }) {
  const chk = useCheck('/api/agri/test', koord.lat, koord.lon)
  const a = chk.data
  const fn = {
    boden: '🌍 Boden (35 %)', klima: '🌤️ Klima (20 %)', hang: '⛰️ Hang (20 %)',
    umfeld: '🚜 Umfeld (15 %)', schutz: '🦋 Schutz (10 %)',
  }
  const kult = (a?.kulturen || []).map((k, i) => {
    const b = k.status === 'geeignet' ? 'ok' : k.status === 'bedingt' ? 'warn' : 'bad'
    const ic = k.status === 'geeignet' ? '✅' : k.status === 'bedingt' ? '⚠️' : '🛑'
    return <li key={i}>{ic} <b>{k.kultur}</b> <span className={'badge ' + b}>{k.status}</span><br />
      <span className="small">{k.grund}</span></li>
  })
  return (
    <section>
      <div className="card no-print">
        <h3>🚜 Landwirtschafts-Eignungstest</h3>
        <p className="small">Boden 35 % · Klima 20 % · Hang 20 % · Umfeld 15 % · Schutz 10 % — aus echten Daten (SoilGrids, ERA5-Klima 2020–24, Höhenmodell, OSM). Übernimmt die Koordinaten aus „Grundstück".</p>
        <button className="primary" onClick={chk.run}>Acker-Test neu starten</button>
      </div>
      {chk.busy && <LoadingBox text="Berechne Boden, Klima (5 Jahre), Hang" sekunden />}
      {chk.err && <div className="err">Acker-Test fehlgeschlagen: {chk.err}</div>}
      {a && (
        <>
          {a.ko_kriterium ? <div className="card"><div className="warnbox">🛑 <b>K.O.:</b> {a.ko_kriterium}</div></div> : null}
          <div className="card">
            <ScoreRing score={a.score} label={a.label}
              sub={<><span className={'badge ' + (a.score >= 65 ? 'ok' : a.score >= 50 ? 'warn' : 'bad')}>{a.label}</span>{' '}
                <span className="small">{a.lat}, {a.lon} · {a.dauer_s}s</span></>} />
          </div>
          <AussageBox aussage={a.aussagekraft} gegenwert={a.gegenwert} />
          <div className="card"><h3>📊 Faktoren</h3>
            {Object.entries(a.faktoren || {}).map(([k, f]) => <FaktorBar key={k} name={fn[k] || k} f={f} />)}
          </div>
          {(a.behoerden || []).length ? (
            <div className="card"><h3>🏛️ Behörden-Layer</h3>
              <ul className="clean">
                {a.behoerden.map((l, i) => {
                  const ic = l.treffer ? (l.stufe === 'rot' ? '🛑' : '⚠️') : '✅'
                  return <li key={i}>{ic} <b>{l.label}</b>{l.treffer ? <> – <span className="small">{(l.namen || []).join('; ')}</span></> : <> <span className="small">frei</span></>}</li>
                })}
              </ul>
            </div>
          ) : null}
          <PrintButton />
          <div className="card"><h3>🌾 Kultur-Eignung</h3>
            <ul className="clean">{kult}</ul>
            <p className="small">Regelwerk transparent im Code (kulturmatrix). LPIS-Feldblock-Prüfung folgt als WFS-Punktabfrage.</p>
          </div>
          <Rohdaten data={a} />
        </>
      )}
    </section>
  )
}
