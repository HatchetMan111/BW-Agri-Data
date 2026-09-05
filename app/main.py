"""heimgrund - Grundstueck-Check + Gartenplaner (lokal, Proxmox-LXC).

Echte Live-Daten statt Platzhalter:
- Boden: SoilGrids v2 (ISRIC, kostenlos, ohne Key)
- Wetter/Hoehe: Open-Meteo (kostenlos, ohne Key)
- Wasserstaende: PEGELONLINE v2 (WSV, HVD)
- Schutzgebiete/Landnutzung: OpenStreetMap via Overpass
- Adresssuche: Nominatim (mit User-Agent, gecacht)
- Fach-Geodaten BW (InVeKoS LPIS, AWGN, Biosphaere): WMS/WFS-Overlay-Links,
  Punktabfragen folgen (dann ersetzen sie die OSM-Naeherungen).

Alles mit Timeout + Cache + ehrlicher Quellen-Kennzeichnung.
Ohne Netz: gekennzeichnete Cache-/Fallback-Antwort, UI bleibt nutzbar.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import traceback
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_NAME = "heimgrund"
APP_VERSION = "0.4.0"
APP_PORT = int(os.environ.get("APP_PORT", "8000"))
UA = {"User-Agent": "heimgrund/0.2 (personal local use)"}

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / ".." / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "heimgrund.db"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="heimgrund", version=APP_VERSION)


# ---------------- DB + Cache ----------------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    con = db()
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS standorte (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS wfs_cache (
                ckey TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS beete (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kultur TEXT NOT NULL DEFAULT '',
                notiz TEXT NOT NULL DEFAULT '',
                standort_id INTEGER,
                created TEXT NOT NULL
            );
            """
        )
        con.commit()
    finally:
        con.close()


init_db()


def cache_get(ckey: str, max_age_s: int) -> dict | list | None:
    try:
        con = db()
        try:
            row = con.execute(
                "SELECT payload, updated FROM wfs_cache WHERE ckey=?", (ckey,)
            ).fetchone()
        finally:
            con.close()
        if not row:
            return None
        ts = datetime.fromisoformat(row["updated"])
        if (datetime.now(timezone.utc) - ts).total_seconds() > max_age_s:
            return None
        return json.loads(row["payload"])
    except Exception:
        return None


def cache_put(ckey: str, payload: dict | list) -> None:
    try:
        con = db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO wfs_cache(ckey, payload, updated) VALUES (?,?,?)",
                (ckey, json.dumps(payload, ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat()),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        print(traceback.format_exc())


def fetch_json(url: str, timeout: int = 12, params: dict | None = None,
               data: bytes | None = None) -> tuple[dict | list | None, str]:
    """GET (oder POST wenn data) -> (objekt, fehlertext). Niemals Exception."""
    try:
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(full, data=data, headers=UA,
                                     method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as e:  # noqa: BLE001 - Offline-Fallback ist Konzept
        return None, f"{type(e).__name__}: {e}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------- Live-Quellen ----------------
def soil_live(lat: float, lon: float) -> dict:
    ckey = f"soil:{round(lat,3)}:{round(lon,3)}"
    hit = cache_get(ckey, 90 * 86400)
    if hit is not None:
        hit["cached"] = True
        return hit
    url = ("https://rest.isric.org/soilgrids/v2.0/properties/query"
           f"?lon={lon}&lat={lat}&property=clay&property=sand&property=silt"
           "&property=phh2o&property=soc&depth=0-5cm&depth=5-15cm&value=mean")
    data, err = fetch_json(url, timeout=15)
    if data is None:
        return {"status": "offline", "error": err, "quelle": "SoilGrids (nicht erreichbar)"}
    try:
        vals: dict[str, float | None] = {}
        for layer in data["properties"]["layers"]:
            ms = [d["values"].get("mean") for d in layer["depths"]
                  if d["values"].get("mean") is not None]
            vals[layer["name"]] = (sum(ms) / len(ms)) if ms else None
        out: dict = {"status": "live", "quelle": "SoilGrids v2 (ISRIC, CC-BY 4.0)", "cached": False}
        if vals.get("clay") is None:
            out["versiegelt"] = True
            out["hinweis"] = ("Keine Bodendaten an diesem Punkt (versiegelte/bebaute "
                              "Flaeche oder Gewaesser). Fuer Gartenboeden 50-200 m "
                              "ausserhalb der Bebauung pruefen.")
            cache_put(ckey, out)
            return out
        clay = vals["clay"] / 10  # g/kg -> %
        sand = vals["sand"] / 10
        silt = vals["silt"] / 10
        ph = (vals["phh2o"] / 10) if vals.get("phh2o") else None
        soc = (vals["soc"] / 10) if vals.get("soc") else None  # dg/kg -> g/kg
        out.update({"ton_pct": round(clay, 1), "sand_pct": round(sand, 1),
                    "schluff_pct": round(silt, 1),
                    "ph": round(ph, 1) if ph else None,
                    "humus_g_kg": round(soc, 1) if soc else None,
                    "tiefe": "0-15 cm (gemittelt)",
                    "bodenart": bodenart_de(clay, sand, silt),
                    "ph_wertung": ph_wertung(ph) if ph else None})
        out["garten_score"] = garten_score(clay, sand, ph)
        cache_put(ckey, out)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "fehler", "error": f"{type(e).__name__}: {e}",
                "quelle": "SoilGrids (Parse-Fehler)"}


def bodenart_de(clay: float, sand: float, silt: float) -> str:
    if sand >= 85:
        return "Sand"
    if clay >= 40:
        return "Ton"
    if silt >= 70:
        return "Schluff"
    if clay >= 25 and sand < 50:
        return "Lehm"
    if sand >= 60:
        return "lehmiger Sand"
    if silt >= 50:
        return "schluffiger Lehm"
    return "sandiger Lehm"


def ph_wertung(ph: float) -> str:
    if ph < 5.5:
        return "sauer – Kalkung pruefen, Kartoffeln/Heidelbeeren ok"
    if ph <= 7.2:
        return "optimal fuer die meisten Gemuese"
    return "alkalisch – eher kalkliebende Kulturen"


def garten_score(clay: float, sand: float, ph: float | None) -> dict:
    s = 70.0
    s += 8 if 10 <= clay <= 27 else (-12 if clay > 35 else -4)
    s += 6 if 30 <= sand <= 65 else -6
    if ph:
        s += 8 if 6.0 <= ph <= 7.2 else -8
    s = max(5, min(98, round(s)))
    label = "sehr gut" if s >= 80 else "gut" if s >= 65 else "mittel" if s >= 50 else "schwierig"
    return {"wert": s, "label": label}


def weather_live(lat: float, lon: float) -> dict:
    ckey = f"wx:{round(lat,2)}:{round(lon,2)}"
    hit = cache_get(ckey, 30 * 60)
    if hit is not None:
        hit["cached"] = True
        return hit
    params = {"latitude": lat, "longitude": lon,
              "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
              "timezone": "Europe/Berlin", "forecast_days": 4}
    data, err = fetch_json("https://api.open-meteo.com/v1/forecast", timeout=15, params=params)
    if data is None:
        return {"status": "offline", "error": err, "quelle": "Open-Meteo (nicht erreichbar)"}
    try:
        cur = data["current"]
        days = [{"datum": d, "wmo": w, "tmax": tmax, "tmin": tmin, "regen": r}
                for d, w, tmax, tmin, r in zip(
                    data["daily"]["time"], data["daily"]["weather_code"],
                    data["daily"]["temperature_2m_max"], data["daily"]["temperature_2m_min"],
                    data["daily"]["precipitation_sum"])]
        for dd in days:
            dd["text"], dd["icon"] = wmo_de(dd["wmo"])
        ctext, cicon = wmo_de(cur["weather_code"])
        out = {"status": "live", "quelle": "Open-Meteo (CC-BY 4.0)", "cached": False,
               "hoehe_m": data.get("elevation"),
               "aktuell": {"temp": cur["temperature_2m"], "feuchte": cur["relative_humidity_2m"],
                           "regen_mm": cur["precipitation"], "text": ctext, "icon": cicon},
               "tage": days}
        cache_put(ckey, out)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "fehler", "error": f"{type(e).__name__}: {e}", "quelle": "Open-Meteo"}


def wmo_de(code: int) -> tuple[str, str]:
    m = {0: ("Klar", "☀️"), 1: ("Meist klar", "🌤️"), 2: ("Wechselhaft", "⛅"),
         3: ("Bedeckt", "☁️"), 45: ("Nebel", "🌫️"), 48: ("Reifnebel", "🌫️"),
         51: ("Niesel", "🌦️"), 53: ("Niesel", "🌦️"), 55: ("Niesel", "🌦️"),
         56: ("Gefr. Niesel", "🌧️"), 57: ("Gefr. Niesel", "🌧️"),
         61: ("Leichter Regen", "🌧️"), 63: ("Regen", "🌧️"), 65: ("Starkregen", "⛈️"),
         66: ("Gefr. Regen", "🌧️"), 67: ("Gefr. Regen", "🌧️"),
         71: ("Leichter Schnee", "🌨️"), 73: ("Schnee", "🌨️"), 75: ("Starker Schnee", "❄️"),
         77: ("Graupel", "🌨️"), 80: ("Schauer", "🌦️"), 81: ("Schauer", "🌦️"),
         82: ("Starkschauer", "⛈️"), 85: ("Schneeschauer", "🌨️"), 86: ("Schneeschauer", "🌨️"),
         95: ("Gewitter", "⛈️"), 96: ("Gewitter m. Hagel", "⛈️"), 99: ("Gewitter m. Hagel", "⛈️")}
    return m.get(code, ("–", "🌡️"))


def pegel_live(lat: float, lon: float) -> dict:
    stations = cache_get("pegel:stations:v1", 7 * 86400)
    if stations is None:
        data, err = fetch_json(
            "https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations.json", timeout=25)
        if data is None:
            return {"status": "offline", "error": err, "quelle": "PEGELONLINE (nicht erreichbar)"}
        stations = [s for s in data if s.get("latitude") and s.get("longitude")]
        cache_put("pegel:stations:v1", stations)
    near = sorted(stations,
                  key=lambda s: haversine_km(lat, lon, s["latitude"], s["longitude"]))[:3]
    out_stations = []
    for s in near:
        dist = haversine_km(lat, lon, s["latitude"], s["longitude"])
        mkey = f"pegel:mess:{s['uuid']}"
        mess = cache_get(mkey, 15 * 60)
        m_cached = True
        if mess is None:
            m_cached = False
            mess, merr = fetch_json(
                f"https://www.pegelonline.wsv.de/webservices/rest-api/v2/stations/"
                f"{s['uuid']}/W/measurements.json?start=P2D", timeout=20)
            if mess:
                cache_put(mkey, mess)
            else:
                mess, merr = [], merr
        entry: dict = {"name": s["longname"], "gewaesser": s["water"]["longname"],
                       "dist_km": round(dist, 1), "lat": s["latitude"], "lon": s["longitude"],
                       "mess_cached": m_cached}
        if mess:
            vals = [m["value"] for m in mess if m.get("value") is not None]
            entry.update({"aktuell_cm": vals[-1], "zeit": mess[-1]["timestamp"],
                          "trend_cm_24h": round(vals[-1] - vals[0], 1) if len(vals) > 1 else 0.0,
                          "verlauf": vals[-48:]})
        else:
            entry["fehler"] = merr if isinstance(mess, list) else "keine Messwerte"
        out_stations.append(entry)
    return {"status": "live", "quelle": "PEGELONLINE (Wasserstraßen des Bundes, HVD)",
            "stationen": out_stations}


def osm_live(lat: float, lon: float) -> dict:
    ckey = f"osm:{round(lat,2)}:{round(lon,2)}"
    hit = cache_get(ckey, 30 * 86400)
    if hit is not None:
        hit["cached"] = True
        return hit
    q = (f"[out:json][timeout:25];"
         f"(relation[\"boundary\"~\"^(national_park|nature_reserve|protected_area)$\"]"
         f"(around:15000,{lat},{lon});"
         f"way[\"leisure\"=\"nature_reserve\"](around:15000,{lat},{lon});"
         f"way[\"landuse\"~\"^(farmland|meadow|orchard|forest|vineyard|allotments)$\"]"
         f"(around:3000,{lat},{lon}););out tags center 40;")
    data, err = fetch_json("https://overpass-api.de/api/interpreter", timeout=35,
                           data=q.encode("utf-8"))
    if data is None:
        return {"status": "offline", "error": err, "quelle": "OpenStreetMap (nicht erreichbar)"}
    try:
        reservate, nutzung = [], {}
        for e in data.get("elements", []):
            tags = e.get("tags", {})
            c = e.get("center", {})
            if not c:
                continue
            d = haversine_km(lat, lon, c["lat"], c["lon"])
            if tags.get("boundary") in ("national_park", "nature_reserve", "protected_area") \
                    or tags.get("leisure") == "nature_reserve":
                name = tags.get("name") or "Naturschutzflaeche"
                reservate.append({"name": name, "dist_km": round(d, 1),
                                  "lat": c["lat"], "lon": c["lon"]})
            elif tags.get("landuse"):
                nutzung[tags["landuse"]] = nutzung.get(tags["landuse"], 0) + 1
        reservate.sort(key=lambda r: r["dist_km"])
        out = {"status": "live", "quelle": "OpenStreetMap (ODbL)", "cached": False,
               "reservate": reservate[:8],
               "landnutzung": [{"typ": landuse_de(k), "treffer": v}
                               for k, v in sorted(nutzung.items(), key=lambda i: -i[1])][:5]}
        cache_put(ckey, out)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "fehler", "error": f"{type(e).__name__}: {e}", "quelle": "Overpass"}


def landuse_de(k: str) -> str:
    return {"farmland": "Acker", "meadow": "Grünland/Wiese", "orchard": "Streuobst/Plantage",
            "forest": "Wald", "vineyard": "Weinberg",
            "allotments": "Kleingärten"}.get(k, k)


# LUBW-Fachdienste (RIPS/GDI-BW, alle WFS 2.0, Punktabfrage via Mini-BBox).
LUBW_BASE = ("https://rips-gdi.lubw.baden-wuerttemberg.de/arcgis/services/"
             "wfs/{svc}/MapServer/WFSServer")
LUBW_LAYER = [
    {"svc": "Naturschutzgebiet", "tn": "Naturschutzgebiet:Naturschutzgebiet",
     "label": "Naturschutzgebiet", "stufe": "rot"},
    {"svc": "FFH_Gebiet", "tn": "FFH_Gebiet:FFH_Gebiet",
     "label": "FFH-Gebiet (Natura 2000)", "stufe": "rot"},
    {"svc": "Landschaftsschutzgebiet", "tn": "Landschaftsschutzgebiet:Landschaftsschutzgebiet",
     "label": "Landschaftsschutzgebiet", "stufe": "gelb"},
    {"svc": "Wasserschutzgebiet", "tn": "Wasserschutzgebiet:Wasserschutzgebiet",
     "label": "Wasserschutzgebiet", "stufe": "gelb"},
    {"svc": "FFH_Maehwiese", "tn": "FFH_Maehwiese:FFH_Maehwiese",
     "label": "FFH-Mähwiese", "stufe": "gelb"},
    {"svc": "Ueberschwemmungsgebiet", "tn": "Ueberschwemmungsgebiet:UESG",
     "label": "Überschwemmungsgebiet", "stufe": "rot"},
]


def _lubw_point(layer: dict, lat: float, lon: float) -> dict:
    import re as _re
    d = 0.00045  # ~50 m Box
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
              "typeNames": layer["tn"], "srsName": "urn:ogc:def:crs:EPSG::4326",
              "bbox": f"{lat-d},{lon-d},{lat+d},{lon+d},urn:ogc:def:crs:EPSG::4326",
              "count": 3}
    try:
        full = LUBW_BASE.format(svc=layer["svc"]) + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as resp:
            xml = resp.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return {"label": layer["label"], "stufe": layer["stufe"], "status": "offline",
                "error": f"{type(e).__name__}: {e}"}
    m = _re.search(r'numberMatched="(\d+)"', xml)
    anzahl = int(m.group(1)) if m else 0
    namen: list[str] = []
    if anzahl:
        for pat in (r"<[\w:]*OBJEKT[\w:]*>([^<]{1,120})</",
                    r"<[\w:]*NAME[\w:]*>([^<]{1,120})</",
                    r"<[\w:]*GEBIET[\w:]*>([^<]{1,120})</"):
            namen = [n.strip() for n in _re.findall(pat, xml)
                     if n.strip() and not n.strip().replace(".", "").replace("-", "").isdigit()]
            if namen:
                break
    return {"label": layer["label"], "stufe": layer["stufe"], "status": "live",
            "treffer": anzahl > 0, "anzahl": anzahl, "namen": namen[:3]}


def schutz_amtlich(lat: float, lon: float) -> dict:
    ckey = f"amt:{round(lat,3)}:{round(lon,3)}"
    hit = cache_get(ckey, 30 * 86400)
    if hit is not None:
        hit["cached"] = True
        return hit
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [(layer, ex.submit(_lubw_point, layer, lat, lon)) for layer in LUBW_LAYER]
        layers = [{**layer, **f.result()} for layer, f in futs]
    out = {"status": "live" if any(x["status"] == "live" for x in layers) else "offline",
           "quelle": "LUBW RIPS/GDI-BW (WFS, DL-BY-2.0)", "cached": False, "layer": layers}
    cache_put(ckey, out)
    return out


def geocode_live(q: str) -> dict:
    ckey = f"geo:{q.strip().lower()}"
    hit = cache_get(ckey, 90 * 86400)
    if hit is not None:
        return hit
    params = {"q": q, "format": "json", "limit": 5, "countrycodes": "de",
              "viewbox": "7.4,49.9,10.6,47.0", "bounded": 0, "addressdetails": 1}
    data, err = fetch_json("https://nominatim.openstreetmap.org/search", timeout=15, params=params)
    if data is None:
        return {"status": "offline", "error": err, "treffer": []}
    out = {"status": "live",
           "treffer": [{"name": t["display_name"], "lat": float(t["lat"]), "lon": float(t["lon"]),
                        "typ": t.get("type", "")} for t in data]}
    cache_put(ckey, out)
    return out


def slope_live(lat: float, lon: float) -> dict:
    """Hangneigung aus Hoehenkreuz (1 Call, 5 Punkte, ~110 m Basis)."""
    ckey = f"slope:{round(lat,3)}:{round(lon,3)}"
    hit = cache_get(ckey, 90 * 86400)
    if hit is not None:
        hit["cached"] = True
        return hit
    d = 0.001
    lats = [lat, lat + d, lat - d, lat, lat]
    lons = [lon, lon, lon, lon + d, lon - d]
    params = {"latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons))}
    data, err = fetch_json("https://api.open-meteo.com/v1/elevation", timeout=20, params=params)
    if data is None or not data.get("elevation"):
        return {"status": "offline", "error": err, "quelle": "Open-Meteo Elevation"}
    try:
        z0, zn, zs, ze, zw = data["elevation"]
        my = 111320 * d
        mx = 111320 * math.cos(math.radians(lat)) * d
        gx = (ze - zw) / (2 * mx)   # Ost-Gradient
        gy = (zn - zs) / (2 * my)   # Nord-Gradient
        hang = math.hypot(gx, gy) * 100
        # Exposition = Richtung des steilsten Abstiegs
        dx, dy = -gx, -gy
        winkel = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        expo = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][round(winkel / 45) % 8]
        out = {"status": "live", "quelle": "Open-Meteo Elevation (CC-BY 4.0)", "cached": False,
               "hoehe_m": z0, "hang_pct": round(hang, 1),
               "hang_klasse": ("eben" if hang < 2 else "schwach geneigt" if hang < 4
                               else "geneigt" if hang < 7 else "stark geneigt" if hang < 12
                               else "steil"),
               "exposition": expo}
        cache_put(ckey, out)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "fehler", "error": f"{type(e).__name__}: {e}", "quelle": "Elevation"}


def climate_live(lat: float, lon: float) -> dict:
    """5-Jahres-Klima (ERA5): Jahresniederschlag, Mitteltemperatur, Frost-/Hitzetage."""
    ckey = f"klima:{round(lat,2)}:{round(lon,2)}"
    hit = cache_get(ckey, 90 * 86400)
    if hit is not None:
        hit["cached"] = True
        return hit
    params = {"latitude": lat, "longitude": lon, "start_date": "2020-01-01",
              "end_date": "2024-12-31",
              "daily": "temperature_2m_mean,temperature_2m_max,temperature_2m_min,precipitation_sum",
              "timezone": "Europe/Berlin"}
    data, err = fetch_json("https://archive-api.open-meteo.com/v1/era5", timeout=90, params=params)
    if data is None:
        return {"status": "offline", "error": err, "quelle": "Open-Meteo ERA5"}
    try:
        years: dict[str, list] = {}
        for dt, tm, tx, tn, pp in zip(data["daily"]["time"], data["daily"]["temperature_2m_mean"],
                                      data["daily"]["temperature_2m_max"],
                                      data["daily"]["temperature_2m_min"],
                                      data["daily"]["precipitation_sum"]):
            y = years.setdefault(dt[:4], [[], [], 0, 0])
            if tm is not None:
                y[0].append(tm)
            y[1].append(pp or 0)
            y[2] += 1 if (tn is not None and tn < 0) else 0
            y[3] += 1 if (tx is not None and tx >= 30) else 0
        nj = len(years)
        nied = sum(sum(v[1]) for v in years.values()) / nj
        temp = sum(sum(v[0]) / len(v[0]) for v in years.values()) / nj
        frost = sum(v[2] for v in years.values()) / nj
        hitze = sum(v[3] for v in years.values()) / nj
        out = {"status": "live", "quelle": "Open-Meteo ERA5 (CC-BY 4.0, 2020-2024)", "cached": False,
               "niederschlag_mm_jahr": round(nied), "temp_mittel_c": round(temp, 1),
               "frosttage_jahr": round(frost), "hitzetage_jahr": round(hitze)}
        cache_put(ckey, out)
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "fehler", "error": f"{type(e).__name__}: {e}", "quelle": "ERA5"}


def _score_band(wert: float, ideal_lo: float, ideal_hi: float,
                tol: float, minimum: float = 5.0) -> float:
    if ideal_lo <= wert <= ideal_hi:
        return 100.0
    abstand = ideal_lo - wert if wert < ideal_lo else wert - ideal_hi
    return max(minimum, 100.0 - (abstand / tol) * 90.0)


def agri_test(lat: float, lon: float) -> dict:
    """Landwirtschafts-Eignung: Boden 35 / Klima 20 / Hang 20 / Umfeld 15 / Schutz 10."""
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_boden = ex.submit(soil_live, lat, lon)
        f_klima = ex.submit(climate_live, lat, lon)
        f_hang = ex.submit(slope_live, lat, lon)
        f_osm = ex.submit(osm_live, lat, lon)
        f_amt = ex.submit(schutz_amtlich, lat, lon)
        boden, klima, hang, osm = f_boden.result(), f_klima.result(), f_hang.result(), f_osm.result()
        amt = f_amt.result()

    faktoren: dict[str, dict] = {}
    ko = None
    if boden.get("status") == "live" and boden.get("versiegelt"):
        ko = "Versiegelte/bebaute Flaeche – kein Ackerbau moeglich."
    # Boden 35 %
    if boden.get("status") == "live" and not boden.get("versiegelt"):
        clay, sand = boden["ton_pct"], boden["sand_pct"]
        ph = boden.get("ph") or 6.5
        s = 0.4 * _score_band(clay, 12, 28, 20) + 0.3 * _score_band(sand, 25, 60, 30) \
            + 0.3 * _score_band(ph, 6.0, 7.0, 1.5)
        if (boden.get("humus_g_kg") or 0) >= 20:
            s = min(100, s + 5)
        faktoren["boden"] = {"gewicht": 35, "wert": round(s),
                             "text": f"{boden.get('bodenart')} · pH {boden.get('ph')} · Humus {boden.get('humus_g_kg')} g/kg"}
    else:
        faktoren["boden"] = {"gewicht": 35, "wert": None,
                             "text": "Keine Bodendaten (versiegelt/offline)"}
    # Klima 20 %
    if klima.get("status") == "live":
        s = (0.45 * _score_band(klima["niederschlag_mm_jahr"], 650, 900, 350)
             + 0.35 * _score_band(klima["temp_mittel_c"], 8.5, 10.5, 3)
             + 0.2 * _score_band(klima["frosttage_jahr"], 0, 90, 60))
        if klima["hitzetage_jahr"] > 20:
            s -= min(15, (klima["hitzetage_jahr"] - 20) * 0.8)
        faktoren["klima"] = {"gewicht": 20, "wert": round(max(5, s)),
                             "text": (f"{klima['niederschlag_mm_jahr']} mm/Jahr · "
                                      f"{klima['temp_mittel_c']} °C · {klima['frosttage_jahr']} Frosttage")}
    else:
        faktoren["klima"] = {"gewicht": 20, "wert": None, "text": "Klimadaten offline"}
    # Hang 20 %
    if hang.get("status") == "live":
        hp = hang["hang_pct"]
        s = 100 if hp < 2 else 85 if hp < 4 else 65 if hp < 7 else 40 if hp < 12 else 15
        if hang.get("exposition") in ("S", "SW", "SO"):
            s = min(100, s + 5)
        faktoren["hang"] = {"gewicht": 20, "wert": round(s),
                            "text": f"{hp} % ({hang.get('hang_klasse')}) · Exposition {hang.get('exposition')}"}
    else:
        faktoren["hang"] = {"gewicht": 20, "wert": None, "text": "Hangdaten offline"}
    # Umfeld 15 %
    if osm.get("status") == "live":
        nutz = {n["typ"]: n["treffer"] for n in osm.get("landnutzung", [])}
        agri_hits = nutz.get("Acker", 0) + nutz.get("Grünland/Wiese", 0)
        total = sum(nutz.values())
        anteil = (agri_hits / total) if total else 0
        s = 90 if anteil >= 0.6 else 70 if anteil >= 0.3 else (50 if agri_hits else 40)
        faktoren["umfeld"] = {"gewicht": 15, "wert": s,
                              "text": f"Agrar-Anteil im Umfeld: {round(anteil*100)} % (OSM, 3 km)"}
    else:
        faktoren["umfeld"] = {"gewicht": 15, "wert": None, "text": "Umfeld offline"}
    # Schutz 10 % – amtliche LUBW-Layer haben Vorrang vor OSM-Naeherung
    amt_layer = {x["label"]: x for x in amt.get("layer", [])} if amt.get("status") == "live" else {}
    if amt_layer:
        treffer_rot = [k for k in ("Naturschutzgebiet", "FFH-Gebiet (Natura 2000)",
                                   "Überschwemmungsgebiet") if amt_layer.get(k, {}).get("treffer")]
        treffer_gelb = [k for k in ("Landschaftsschutzgebiet", "Wasserschutzgebiet",
                                    "FFH-Mähwiese") if amt_layer.get(k, {}).get("treffer")]
        if treffer_rot:
            s, txt = 30, "Direkt in " + ", ".join(treffer_rot) + " – Nutzung stark eingeschraenkt!"
        elif treffer_gelb:
            s, txt = 65, "In " + ", ".join(treffer_gelb) + " – Auflagen beachten"
        else:
            s, txt = 100, "Keine Schutzgebiets-Treffer (LUBW-Fachdaten, Punktabfrage)"
        faktoren["schutz"] = {"gewicht": 10, "wert": s, "text": txt}
    elif osm.get("status") == "live":
        res = osm.get("reservate", [])
        nearest = min([r["dist_km"] for r in res], default=99)
        if nearest < 0.5:
            s, txt = 30, f"Schutzgebiet {nearest} km entfernt – Nutzung stark eingeschraenkt, NSG/FFH-WFS pruefen!"
        elif nearest < 2:
            s, txt = 70, f"Naechstes Schutzgebiet {nearest} km – Auflagen moeglich"
        else:
            s, txt = 100, "Kein Schutzgebiet im nahen Umfeld (OSM, 15 km)"
        faktoren["schutz"] = {"gewicht": 10, "wert": s, "text": txt}
    else:
        faktoren["schutz"] = {"gewicht": 10, "wert": None, "text": "Schutzdaten offline"}

    aktiv = {k: v for k, v in faktoren.items() if v["wert"] is not None}
    score = round(sum(v["wert"] * v["gewicht"] for v in aktiv.values())
                  / sum(v["gewicht"] for v in aktiv.values())) if aktiv else None
    label = ("hervorragend" if score is not None and score >= 80 else "gut" if score is not None and score >= 65
             else "mittel" if score is not None and score >= 50 else "schwierig"
             if score is not None else "unbestimmt")
    return {"lat": lat, "lon": lon, "score": score, "label": label, "ko_kriterium": ko,
            "faktoren": faktoren, "kulturen": kulturmatrix(boden, klima, hang),
            "behoerden": amt.get("layer", []) if amt.get("status") == "live" else [],
            "quellen": {"boden": boden.get("quelle"), "klima": klima.get("quelle"),
                        "hang": hang.get("quelle"), "umfeld": osm.get("quelle"),
                        "behoerden": amt.get("quelle")}}


def kulturmatrix(boden: dict, klima: dict, hang: dict) -> list[dict]:
    clay = boden.get("ton_pct", 20) if boden.get("status") == "live" else 20
    sand = boden.get("sand_pct", 40) if boden.get("status") == "live" else 40
    ph = boden.get("ph") or 6.5
    nied = klima.get("niederschlag_mm_jahr", 750) if klima.get("status") == "live" else 750
    temp = klima.get("temp_mittel_c", 9.5) if klima.get("status") == "live" else 9.5
    hp = hang.get("hang_pct", 3) if hang.get("status") == "live" else 3

    def st(ok: bool, bedingt: bool, txt: str) -> dict:
        return {"status": "geeignet" if ok else "bedingt" if bedingt else "kritisch", "grund": txt}

    return [
        {"kultur": "🌾 Weizen", **st(clay <= 32 and 6.0 <= ph <= 7.5 and hp < 9, hp < 12,
            "Anspruchslos, mag Lehm und Kalk – meidet Staunaesse und Steilhaenge.")},
        {"kultur": "🌽 Mais", **st(temp >= 9 and nied >= 650 and hp < 7, temp >= 8.5,
            "Braucht Waerme und Wasser; Erosionsschutz am Hang beachten.")},
        {"kultur": "🥔 Kartoffeln", **st(sand >= 30 and ph <= 6.8, ph <= 7.2,
            "Liebt lockere, leicht saure Boeden – schwerer Ton bremst.")},
        {"kultur": "🐄 Grünland", **st(True, True,
            "Fast immer moeglich; an Haengen >12 % und in Auen die erste Wahl.")},
        {"kultur": "🍎 Streuobst", **st(hp < 12 and 6.0 <= ph <= 7.5, True,
            "Robust auf den meisten Boeden; Spätfrostlagen in Senken meiden.")},
        {"kultur": "🍇 Wein", **st(hp >= 3 and temp >= 9.3 and ph >= 6.2, temp >= 9.0,
            "Will Hang, Waerme und Kalk – klassische Suedhang-Kultur.")},
    ]


# ---------------- Modelle ----------------
class StandortIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class BeetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kultur: str = Field(default="", max_length=120)
    notiz: str = Field(default="", max_length=1000)
    standort_id: int | None = None


# ---------------- API ----------------
@app.get("/api/health")
def health() -> dict:
    try:
        con = db()
        try:
            con.execute("SELECT 1").fetchone()
            db_ok = True
        finally:
            con.close()
    except Exception:
        db_ok = False
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION, "db_ok": db_ok}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "app": APP_NAME, "version": APP_VERSION,
        "zweck": "Grundstueck-Check + Gartenplaner (Baden-Wuerttemberg)",
        "live_quellen": [
            "SoilGrids v2 (ISRIC, CC-BY 4.0) – Boden 0-15 cm",
            "Open-Meteo (CC-BY 4.0) – Wetter + Hoehe",
            "PEGELONLINE (WSV, HVD) – Wasserstaende",
            "OpenStreetMap/Overpass/Nominatim (ODbL) – Schutzgebiete, Landnutzung, Suche",
        ],
        "fach_geodaten_bw": [
            "InVeKoS LPIS BW ab 2023, AWGN Fliessgewaesser/Einzugsgebiete, "
            "Biosphaere-Zonen, Bodenschaetzung (WMS/WFS via daten-bw.de – Overlay/Links)",
        ],
    }


@app.get("/api/geocode")
def geocode(q: str = Query(min_length=2, max_length=200)) -> dict:
    return geocode_live(q)


@app.get("/api/standort/reverse")
def standort_reverse(lat: float = Query(ge=-90, le=90),
                     lon: float = Query(ge=-180, le=180)) -> dict:
    """Kombinierter Report. Module laufen parallel; jedes meldet status + Quelle."""
    try:
        in_bw = 47.0 <= lat <= 49.9 and 7.4 <= lon <= 10.6
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=5) as ex:
            f_boden = ex.submit(soil_live, lat, lon)
            f_wetter = ex.submit(weather_live, lat, lon)
            f_pegel = ex.submit(pegel_live, lat, lon)
            f_osm = ex.submit(osm_live, lat, lon)
            f_amt = ex.submit(schutz_amtlich, lat, lon)
            boden, wetter, pegel, osm, amt = (f_boden.result(), f_wetter.result(),
                                              f_pegel.result(), f_osm.result(), f_amt.result())
        return {"lat": lat, "lon": lon, "in_bw": in_bw,
                "boden": boden, "wetter": wetter, "pegel": pegel, "umfeld": osm,
                "behoerden": amt,
                "dauer_s": round(time.time() - t0, 1),
                "attribution": ("Boden: SoilGrids/ISRIC CC-BY 4.0 · Wetter: Open-Meteo CC-BY 4.0 · "
                                "Pegel: WSV PEGELONLINE · Karte/Daten: © OpenStreetMap ODbL · "
                                "Fach-Geodaten BW: Geoportal BW/LUBW (DL-BY-2.0)")}
    except Exception as e:  # noqa: BLE001
        print(traceback.format_exc())
        raise HTTPException(status_code=500,
                            detail=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")


@app.get("/api/agri/test")
def api_agri_test(lat: float = Query(ge=-90, le=90),
                  lon: float = Query(ge=-180, le=180)) -> dict:
    """Landwirtschafts-Eignungstest (Boden 35 / Klima 20 / Hang 20 / Umfeld 15 / Schutz 10)."""
    try:
        t0 = time.time()
        out = agri_test(lat, lon)
        out["in_bw"] = 47.0 <= lat <= 49.9 and 7.4 <= lon <= 10.6
        out["dauer_s"] = round(time.time() - t0, 1)
        return out
    except Exception as e:  # noqa: BLE001
        print(traceback.format_exc())
        raise HTTPException(status_code=500,
                            detail=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")


@app.get("/api/standorte")
def list_standorte() -> list[dict]:
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM standorte ORDER BY id DESC").fetchall()]
    finally:
        con.close()


@app.post("/api/standorte", status_code=201)
def add_standort(payload: StandortIn) -> dict:
    con = db()
    try:
        cur = con.execute(
            "INSERT INTO standorte(label, lat, lon, created) VALUES (?,?,?,?)",
            (payload.label, payload.lat, payload.lon, datetime.now(timezone.utc).isoformat()))
        con.commit()
        return {"id": cur.lastrowid, **payload.model_dump()}
    finally:
        con.close()


@app.get("/api/beete")
def list_beete() -> list[dict]:
    con = db()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM beete ORDER BY id DESC").fetchall()]
    finally:
        con.close()


@app.post("/api/beete", status_code=201)
def add_beet(payload: BeetIn) -> dict:
    con = db()
    try:
        cur = con.execute(
            "INSERT INTO beete(name, kultur, notiz, standort_id, created) VALUES (?,?,?,?,?)",
            (payload.name, payload.kultur, payload.notiz, payload.standort_id,
             datetime.now(timezone.utc).isoformat()))
        con.commit()
        return {"id": cur.lastrowid, **payload.model_dump()}
    finally:
        con.close()


@app.delete("/api/beete/{beet_id}")
def delete_beet(beet_id: int) -> dict:
    con = db()
    try:
        cur = con.execute("DELETE FROM beete WHERE id=?", (beet_id,))
        con.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Beet nicht gefunden")
        return {"deleted": beet_id}
    finally:
        con.close()


@app.get("/api/garten/empfehlung")
def garten_empfehlung(lat: float = Query(ge=-90, le=90),
                      lon: float = Query(ge=-180, le=180)) -> dict:
    """Empfehlung aus echtem Wetter (Regen/Temperatur) + Boden + Saison."""
    month = datetime.now().month
    saison = ("Fruehjahr" if 3 <= month <= 5 else "Sommer" if 6 <= month <= 8
              else "Herbst" if 9 <= month <= 10 else "Winter")
    basis = {"Fruehjahr": (["Kartoffeln (früh)", "Spinat", "Radieschen", "Erbsen",
                            "Streuobst: Apfel Topaz/Bohnapfel"], "Boden ab 8 °C bestellbar"),
             "Sommer": (["Tomaten (geschützt)", "Zucchini", "Bohnen", "Streuobst: Sommerschnitt"],
                        "Mulchen gegen Hitze"),
             "Herbst": (["Feldsalat", "Knoblauch stecken", "Streuobst: Neupflanzung"],
                        "Bodenbedeckung über Winter"),
             "Winter": (["Planung", "Kompost ausbringen", "Streuobst: Winterschnitt"],
                        "Boden ruhen lassen")}[saison]
    wx = weather_live(lat, lon)
    giessen = "Wetter offline – nach Gefühl: Boden 5 cm tief prüfen."
    regen48 = None
    if wx.get("status") == "live":
        tage = wx["tage"]
        regen48 = sum(t["regen"] or 0 for t in tage[1:3])
        tmax = tage[0]["tmax"]
        if regen48 >= 8:
            giessen = (f"Kein Gießen nötig – {regen48:.0f} mm Regen in den nächsten 2 Tagen gemeldet.")
        elif regen48 >= 2:
            giessen = (f"Sparsam gießen – nur {regen48:.0f} mm Regen erwartet, morgens wässern.")
        elif tmax is not None and tmax >= 28:
            giessen = (f"Hitzetag ({tmax:.0f} °C): früh morgens tief wässern + mulchen, "
                       "kein Wasser auf heiße Blätter.")
        else:
            giessen = "Morgens wässern – die nächsten 2 Tage bleibt es trocken."
    boden = soil_live(lat, lon)
    boden_tip = None
    if boden.get("status") == "live" and not boden.get("versiegelt"):
        sc = boden.get("garten_score", {})
        boden_tip = (f"Boden: {boden.get('bodenart')} (Score {sc.get('wert')}/100 – {sc.get('label')}). "
                     + (boden.get("ph_wertung") or ""))
    return {"lat": lat, "lon": lon, "saison": saison,
            "empfohlene_kulturen": basis[0], "saison_notiz": basis[1],
            "giess_empfehlung": giessen, "regen_naechste_2_tage_mm": regen48,
            "boden_einschaetzung": boden_tip,
            "wetter": wx.get("aktuell") if wx.get("status") == "live" else None}


# ---------------- Frontend ----------------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        raise HTTPException(status_code=500, detail="Frontend fehlt: app/static/index.html")
    return FileResponse(str(idx))


@app.get("/api/export")
def export_all() -> dict:
    con = db()
    try:
        return {"standorte": [dict(r) for r in con.execute("SELECT * FROM standorte").fetchall()],
                "beete": [dict(r) for r in con.execute("SELECT * FROM beete").fetchall()],
                "exported_at": datetime.now(timezone.utc).isoformat()}
    finally:
        con.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=APP_PORT)
