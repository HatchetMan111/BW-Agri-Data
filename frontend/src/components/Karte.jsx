import { useEffect, useRef } from 'react'
import L from 'leaflet'

const pointIcon = L.divIcon({
  className: '', html: '<div style="font-size:26px;line-height:26px;filter:drop-shadow(0 1px 3px rgba(0,0,0,.5))">📍</div>',
  iconSize: [26, 26], iconAnchor: [13, 24],
})
const sightIcon = (ic) => L.divIcon({
  className: '', html: `<div style="font-size:19px;line-height:19px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.5))">${ic}</div>`,
  iconSize: [19, 19], iconAnchor: [10, 10],
})

/**
 * Leaflet-Karte mit OSM/Luftbild-Basemaps, FVA-Overlays, Sehenswürdigkeits-,
 * Ladesäulen- und Schutzgebiets-Markern. Klick/ziehen setzt den Standort-Punkt.
 */
export default function Karte({ lat, lon, onPick, reservate = [], sights = [], laden = [] }) {
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const layersRef = useRef(null)
  const onPickRef = useRef(onPick)
  onPickRef.current = onPick

  useEffect(() => {
    const map = L.map('map').setView([lat, lon], 12)
    mapRef.current = map
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
      { maxZoom: 19, attribution: '© OpenStreetMap' }).addTo(map)
    const luft = L.tileLayer.wms('https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_LGL-BW_ATKIS_DOP_20_C',
      { layers: 'IMAGES_DOP_20_RGB', version: '1.3.0', format: 'image/png', transparent: false,
        attribution: 'DOP 20cm © LGL-BW (DL-BY-2.0)' })
    const wmsOpt = { version: '1.3.0', format: 'image/png', transparent: true, opacity: .55 }
    const bestock = L.tileLayer.wms('https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_FVA_Fernerkundung_Waldbestockung',
      { ...wmsOpt, layers: 'fern_bestockungslayer', attribution: 'Waldbestockung © FVA-BW' })
    const sturm = L.tileLayer.wms('https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_FVA_Klima_Sturm',
      { ...wmsOpt, layers: 'sturmschadensrisiko_real_fichte', attribution: 'Sturmrisiko © FVA-BW' })
    const kaefer = L.tileLayer.wms('https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_FVA_Klima_Buchdruckergefaehrdung',
      { ...wmsOpt, layers: 'buchdruckerrisiko_rcp85_2021_2050', attribution: 'Buchdrucker © FVA-BW' })
    const sightLayer = L.layerGroup().addTo(map)
    const ladeLayer = L.layerGroup().addTo(map)
    const resLayer = L.layerGroup().addTo(map)
    layersRef.current = { sightLayer, ladeLayer, resLayer }
    L.control.layers(
      { 'Karte (OSM)': osm, 'Luftbild (DOP 20cm)': luft },
      { '🌲 Waldbestockung (FVA)': bestock, '🌪️ Sturmrisiko Fichte': sturm,
        '🪲 Buchdrucker 2021–50': kaefer, '⭐ Sehenswürdigkeiten': sightLayer,
        '🔌 Ladesäulen': ladeLayer, '🦋 Schutzgebiete': resLayer },
      { collapsed: false }).addTo(map)
    const marker = L.marker([lat, lon], { draggable: true, icon: pointIcon }).addTo(map)
    markerRef.current = marker
    marker.on('dragend', () => { const p = marker.getLatLng(); onPickRef.current(p.lat, p.lng) })
    map.on('click', (e) => onPickRef.current(e.latlng.lat, e.latlng.lng))
    return () => { map.remove(); mapRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Punkt setzen (auch bei Aenderungen von aussen)
  useEffect(() => {
    const map = mapRef.current, marker = markerRef.current
    if (!map || !marker) return
    marker.setLatLng([lat, lon])
    map.panTo([lat, lon])
  }, [lat, lon])

  // Popup-Marker bei neuen Daten neu zeichnen
  useEffect(() => {
    const ly = layersRef.current
    if (!ly) return
    ly.sightLayer.clearLayers()
    ;(sights || []).slice(0, 20).forEach((s) => {
      if (s.lat == null) return
      L.marker([s.lat, s.lon], { icon: sightIcon(s.icon || '⭐') }).addTo(ly.sightLayer)
        .bindPopup(`<b>${s.icon || '⭐'} ${s.name}</b><br>${s.art || ''} · ${s.dist_km} km`)
    })
    ly.ladeLayer.clearLayers()
    ;(laden || []).slice(0, 10).forEach((s) => {
      if (s.lat == null) return
      L.circleMarker([s.lat, s.lon], { radius: 6, color: s.schnell ? '#e6a817' : '#3a7ab5', fillOpacity: .7 })
        .addTo(ly.ladeLayer)
        .bindPopup(`<b>🔌 ${s.kw} kW${s.schnell ? ' (schnell)' : ''}</b><br>${s.betreiber}<br>${s.adresse} · ${s.dist_km} km`)
    })
    ly.resLayer.clearLayers()
    ;(reservate || []).slice(0, 8).forEach((r) => {
      if (r.lat == null) return
      L.circleMarker([r.lat, r.lon], { radius: 7, color: '#2f7d4f', fillOpacity: .6 })
        .addTo(ly.resLayer)
        .bindPopup(`<b>${r.name}</b><br>${r.dist_km} km`)
    })
  }, [sights, laden, reservate])

  // Groesse nach Tab-Wechsel korrigieren
  useEffect(() => {
    const t = setTimeout(() => mapRef.current?.invalidateSize(), 60)
    return () => clearTimeout(t)
  })

  return <div id="map" aria-label="Karte: Klick setzt den Standort-Punkt" />
}
