export default function GartenPanel({ e }) {
  if (!e) return <p className="small">Erst unter „Grundstück" prüfen – die Empfehlung erscheint dann automatisch hier.</p>
  const chips = (e.empfohlene_kulturen || []).map((k, i) => <span className="chip" key={i}>🌱 {k}</span>)
  return (
    <div>
      <div>
        <span className="badge ok">📅 {e.saison}</span>
        {e.regen_naechste_2_tage_mm != null &&
          <span className="badge info">🌧️ {e.regen_naechste_2_tage_mm.toFixed(0)} mm / 2 Tage</span>}
      </div>
      <p style={{ margin: '10px 0 4px' }}><b>Jetzt passend:</b> {e.saison_notiz && <span className="small">({e.saison_notiz})</span>}</p>
      <div>{chips}</div>
      <div className="tip">💧 {e.giess_empfehlung || '–'}</div>
      {e.boden_einschaetzung ? <p className="small">🌍 {e.boden_einschaetzung}</p> : null}
      {e.wetter ? <p className="small">Aktuell: {e.wetter.icon} {e.wetter.temp} °C, 💧 {e.wetter.feuchte} %</p> : null}
    </div>
  )
}
