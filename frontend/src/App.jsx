import { useEffect, useState } from 'react'
import { j } from './api.js'
import Grundstueck from './sections/Grundstueck.jsx'
import BauCheck from './sections/BauCheck.jsx'
import AgriTest from './sections/AgriTest.jsx'
import Wald from './sections/Wald.jsx'
import Garten from './sections/Garten.jsx'
import Beete from './sections/Beete.jsx'
import Glossar from './sections/Glossar.jsx'

const TABS = [
  { id: 'grundstueck', label: 'Grundstück' },
  { id: 'bau', label: '🏗️ Bau-Check' },
  { id: 'acker', label: '🚜 Acker-Test' },
  { id: 'wald', label: '🌲 Wald' },
  { id: 'garten', label: 'Garten' },
  { id: 'beete', label: 'Beete' },
  { id: 'glossar', label: '❓ Begriffe' },
]

function tabFromHash() {
  const h = window.location.hash.replace('#', '')
  return TABS.some((t) => t.id === h) ? h : 'grundstueck'
}

export default function App() {
  const [tab, setTab] = useState(tabFromHash)
  const [koord, setKoord] = useState({ lat: 48.7758, lon: 9.1829 })
  const [report, setReport] = useState(null)
  const [gartenPanel, setGartenPanel] = useState(null)
  const [standorte, setStandorte] = useState([])
  const [health, setHealth] = useState(null)
  // Sektionen erst beim ersten Besuch mounten (sonst feuern alle Tests beim
  // Seitenaufruf gleichzeitig) und danach gemountet lassen (Ergebnisse bleiben).
  const [besucht, setBesucht] = useState(() => new Set([tabFromHash()]))

  // Hash <-> Tab (Deep-Link + Zurueck-Button)
  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    if (window.location.hash.replace('#', '') !== tab) window.location.hash = tab
    document.title = `heimgrund – ${TABS.find((t) => t.id === tab)?.label || ''}`
    setBesucht((prev) => (prev.has(tab) ? prev : new Set(prev).add(tab)))
  }, [tab])

  useEffect(() => {
    j('/api/health')
      .then((h) => setHealth(h))
      .catch(() => setHealth({ status: 'offline', version: '' }))
    j('/api/standorte').then(setStandorte).catch(() => {})
  }, [])

  return (
    <>
      <header className="apphead">
        <h1>🏡 heimgrund</h1>
        <p className="sub">Grundstück-Check + Gartenplaner · lokal · echte Daten</p>
        {health && (
          <span className={'verchip ' + (health.status === 'ok' ? 'ok' : 'bad')}
            title={`Backend: ${health.status} · DB: ${health.db_ok ? 'ok' : 'fehler'}`}>
            {health.version ? 'v' + health.version : ''} {health.status === 'ok' ? '· Backend ok' : '· Backend offline?'}
          </span>
        )}
      </header>

      <nav className="tabs" aria-label="Bereiche">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? 'active' : ''}
            aria-current={tab === t.id ? 'page' : undefined}
            onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </nav>

      <main>
        {besucht.has('grundstueck') && (
          <div hidden={tab !== 'grundstueck'}>
            <Grundstueck koord={koord} setKoord={setKoord}
              report={report} setReport={setReport}
              gartenPanel={gartenPanel} setGartenPanel={setGartenPanel} />
          </div>
        )}
        {besucht.has('bau') && <div hidden={tab !== 'bau'}><BauCheck koord={koord} /></div>}
        {besucht.has('acker') && <div hidden={tab !== 'acker'}><AgriTest koord={koord} /></div>}
        {besucht.has('wald') && <div hidden={tab !== 'wald'}><Wald koord={koord} /></div>}
        {besucht.has('garten') && (
          <div hidden={tab !== 'garten'}>
            <Garten koord={koord} gartenPanel={gartenPanel} setGartenPanel={setGartenPanel} />
          </div>
        )}
        {besucht.has('beete') && <div hidden={tab !== 'beete'}><Beete standorte={standorte} /></div>}
        {besucht.has('glossar') && <div hidden={tab !== 'glossar'}><Glossar /></div>}
      </main>

      <footer>
        Boden: SoilGrids/ISRIC (CC-BY 4.0) · Wetter/Klima: Open-Meteo (CC-BY 4.0) · Pegel: WSV PEGELONLINE ·
        Karte: © OpenStreetMap (ODbL) · Ladesäulen: MobiData-BW · Fach-Geodaten BW: Geoportal BW/LUBW/LGRB/LGL (DL-BY-2.0)
      </footer>
    </>
  )
}
