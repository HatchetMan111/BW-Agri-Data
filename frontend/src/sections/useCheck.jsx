import { useEffect, useState } from 'react'
import { j } from '../api.js'

/**
 * Ruft einen Test-Endpoint beim ersten Mount automatisch ab (wie die alte
 * Tab-Logik "beim ersten Oeffnen starten") und erlaubt Neustart per run().
 */
export function useCheck(url, lat, lon, auto = true) {
  const [state, setState] = useState({ busy: false, data: null, err: '' })
  const [lauf, setLauf] = useState(0)

  useEffect(() => {
    if (!auto && lauf === 0) return
    let alive = true
    setState({ busy: true, data: null, err: '' })
    j(`${url}?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`)
      .then((d) => { if (alive) setState({ busy: false, data: d, err: '' }) })
      .catch((e) => { if (alive) setState({ busy: false, data: null, err: String(e.message || e) }) })
    return () => { alive = false }
  }, [url, lat, lon, lauf, auto])

  return { ...state, run: () => setLauf((n) => n + 1) }
}

export function LoadingBox({ text, sekunden }) {
  return (
    <div className="card">
      <p className="loading">{text}{sekunden ? ' (erster Abruf dauert etwas, danach Cache)' : ' …'}</p>
      <div className="skeleton" style={{ width: '85%' }} />
      <div className="skeleton" style={{ width: '65%' }} />
      <div className="skeleton" style={{ width: '75%' }} />
    </div>
  )
}
