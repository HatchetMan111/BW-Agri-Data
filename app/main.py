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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

APP_NAME = "heimgrund"
APP_VERSION = "0.2.0"
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
    """Kombinierter Report. Jedes Modul meldet status live|offline|fehler + Quelle."""
    try:
        in_bw = 47.0 <= lat <= 49.9 and 7.4 <= lon <= 10.6
        t0 = time.time()
        boden = soil_live(lat, lon)
        wetter = weather_live(lat, lon)
        pegel = pegel_live(lat, lon)
        osm = osm_live(lat, lon)
        return {"lat": lat, "lon": lon, "in_bw": in_bw,
                "boden": boden, "wetter": wetter, "pegel": pegel, "umfeld": osm,
                "dauer_s": round(time.time() - t0, 1),
                "attribution": ("Boden: SoilGrids/ISRIC CC-BY 4.0 · Wetter: Open-Meteo CC-BY 4.0 · "
                                "Pegel: WSV PEGELONLINE · Karte/Daten: © OpenStreetMap ODbL · "
                                "Fach-Geodaten BW: Geoportal BW/LUBW (DL-BY-2.0)")}
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
