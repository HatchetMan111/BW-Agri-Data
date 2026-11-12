const MEMO = {}

export async function j(url, opt) {
  const r = await fetch(url, opt)
  if (!r.ok) {
    const t = await r.text()
    throw new Error('HTTP ' + r.status + ': ' + t.slice(0, 200))
  }
  return r.json()
}

/** Standort-Toggle:Report-Cache pro Koordinate (verhindert Doppel-Abfragen). */
export function memoKey(lat, lon) {
  return `${lat},${lon}`
}

export function setMemo(key, val) { MEMO[key] = val }
export function getMemo(key) { return MEMO[key] }

export function osmUrl(lat, lon) {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=15/${lat}/${lon}`
}

/** GET mit Fehler-Objekt statt Exception (fuer Live/Offline-Badges). */
export async function tryJson(url) {
  try { return { ok: true, data: await j(url) } }
  catch (e) { return { ok: false, error: String(e.message || e) } }
}
