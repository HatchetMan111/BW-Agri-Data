"""heimgrund - Grundstueck-Check + Gartenplaner (lokal, Proxmox-LXC).

Datenbasis: daten-bw.de / groups=agri (Geoportal BW, LUBW, InVeKoS LPIS,
Bodenschaetzung, AWGN, Biosphaere). Live-WFS wird versucht, bei
fehlendem Netz/Cache wird ein transparent gekennzeichnetes
Mock-/Cache-Ergebnis geliefert, damit die UI immer funktioniert.
"""
from __future__ import annotations

import json
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
APP_VERSION = "0.1.0"
APP_PORT = int(os.environ.get("APP_PORT", "8000"))

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / ".." / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "heimgrund.db"

STATIC_DIR = BASE_DIR / "static"

# WFS-Quellen (Live-Versuch, Timeout 6s). URLs sind GetCapabilities- bzw.
# GetFeature-faehig; wir fragen nur minimal ab und fallen sonst auf Mock zurueck.
WFS_SOURCES = {
    "bodenschaetzung": "https://via.bund.de/bmf/inspire/so/wfs?service=WFS&version=2.0.0&request=GetCapabilities",
    "lpis_bw": "https://gdk.gdi-de.org/gdi-de/srv/ger/catalog.search#/metadata/778b16fa-faaa-4db3-8445-5dca615fa505",
}

app = FastAPI(title="heimgrund", version=APP_VERSION)


# ---------------- DB ----------------
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


def cache_get(ckey: str, max_age_s: int = 30 * 86400) -> dict | None:
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
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > max_age_s:
            return None
        return json.loads(row["payload"])
    except Exception:
        return None


def cache_put(ckey: str, payload: dict) -> None:
    try:
        con = db()
        try:
            con.execute(
                "INSERT OR REPLACE INTO wfs_cache(ckey, payload, updated) VALUES (?,?,?)",
                (
                    ckey,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        # Cache darf nie den Request killen
        print(traceback.format_exc())


def wfs_probe(url: str, timeout: int = 6) -> dict:
    """Minimaler Live-Check: HEAD/GET mit Timeout. Gibt status dict zurueck."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "heimgrund/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            head = resp.read(4000)
            return {"reachable": True, "http": resp.status, "hint": head[:200].decode("utf-8", "ignore")}
    except Exception as e:  # noqa: BLE001 - bewusst breit, Offline-Fallback
        return {"reachable": False, "error": f"{type(e).__name__}: {e}"}


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
        "app": APP_NAME,
        "version": APP_VERSION,
        "zweck": "Grundstueck-Check + Gartenplaner auf Basis daten-bw.de (agri)",
        "datenquellen": [
            "Geoportal Baden-Wuerttemberg (WMS/WFS, DL-BY-2.0)",
            "LUBW: AWGN Fliessgewaesser + Einzugsgebiete, Biosphaerengebiet/Zonen",
            "BMF Bodenschaetzung Musterstuecke (INSPIRE Soil, WFS)",
            "GDI-BMLEH InVeKoS LPIS BW ab 2023 (HVD Georaum)",
            "PEGELONLINE (HVD) - optional erweiterbar",
        ],
        "hinweis": "Live-WFS wird best-effort abgefragt; ohne Netz antwortet die API mit gekennzeichnetem Mock/Cache.",
    }


@app.get("/api/standort/reverse")
def standort_reverse(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
) -> dict:
    """Kombinierter Grundstücks-Report für einen Punkt. Immer 200, Quelle pro Layer ausgewiesen."""
    try:
        # BW-Bounding-Box grob (47.0-49.9 N, 7.4-10.6 E) als Plausibilitaet
        in_bw = 47.0 <= lat <= 49.9 and 7.4 <= lon <= 10.6
        ckey = f"reverse:{round(lat,4)}:{round(lon,4)}"
        cached = cache_get(ckey)
        live: dict = {}
        # Best-effort Live-Probe (nur Bodenschaetzung-Capabilities, Rest waere zu schwer im MVP)
        probe = wfs_probe(WFS_SOURCES["bodenschaetzung"])
        live["bodenschaetzung_service"] = probe

        # Regelbasierte Einschaetzung (Mock, aber ehrlich gelabelt).
        # Sobald echte WFS-Layer per GetFeature angebunden sind, hier ersetzen.
        if in_bw:
            boden = {
                "quelle": "mock-regel (LGRB/Bodenschaetzung noch nicht per GetFeature verdrahtet)",
                "bodenfunktion": "mittel bis hoch (Platzhalter) - GetFeature folgt",
                "ackerzahl": "40-60 (Platzhalter, lageabhaengig)",
                "empfehlung": "Kompost einarbeiten, Staunaesse nach Regen beobachten",
            }
            wasser = {
                "quelle": "mock-regel (AWGN + PEGELONLINE folgen)",
                "einzugsgebiet": "AWGN-Basiseinzugsgebiet (Platzhalter)",
                "naechstes_fliessgewaesser": "ca. 300-800 m (Platzhalter - AWGN-Layer folgt)",
                "hochwasser_hinweis": "Pegel in der Naehe in PEGELONLINE pruefen; Keller + Versickerung beachten",
            }
            schutz = {
                "quelle": "mock-regel (Biosphaere-Zone WFS folgt)",
                "biosphaere_zone": "ausserhalb Kernzone (Platzhalter - Lage pruefen)",
                "biotop_naehe": "moeglich (Biotoptypkartierung folgt)",
            }
            lpis = {
                "quelle": "mock-regel (InVeKoS LPIS BW WMS folgt)",
                "umgebung": "Acker/Gruenland gemischt (Platzhalter)",
            }
        else:
            boden = {"quelle": "mock", "hinweis": "Punkt ausserhalb BW - BW-Daten nicht anwendbar"}
            wasser = {"quelle": "mock", "hinweis": "Punkt ausserhalb BW"}
            schutz = {"quelle": "mock", "hinweis": "Punkt ausserhalb BW"}
            lpis = {"quelle": "mock", "hinweis": "Punkt ausserhalb BW"}

        result = {
            "lat": lat,
            "lon": lon,
            "in_bw": in_bw,
            "boden": boden,
            "wasser": wasser,
            "schutzgebiete": schutz,
            "landnutzung_umgebung": lpis,
            "live": live,
            "cached": cached is not None,
            "attribution": "© Geoportal BW, LUBW, LGRB, WSV, BMF - DL-BY-2.0 / CC-BY-4.0 (je Layer, bei Anzeige nennen)",
        }
        cache_put(ckey, result)
        return result
    except Exception as e:  # noqa: BLE001
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")


@app.get("/api/standorte")
def list_standorte() -> list[dict]:
    con = db()
    try:
        rows = con.execute("SELECT * FROM standorte ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.post("/api/standorte", status_code=201)
def add_standort(payload: StandortIn) -> dict:
    con = db()
    try:
        cur = con.execute(
            "INSERT INTO standorte(label, lat, lon, created) VALUES (?,?,?,?)",
            (payload.label, payload.lat, payload.lon, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        return {"id": cur.lastrowid, **payload.model_dump()}
    except Exception:
        print(traceback.format_exc())
        raise
    finally:
        con.close()


@app.get("/api/beete")
def list_beete() -> list[dict]:
    con = db()
    try:
        rows = con.execute("SELECT * FROM beete ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@app.post("/api/beete", status_code=201)
def add_beet(payload: BeetIn) -> dict:
    con = db()
    try:
        cur = con.execute(
            "INSERT INTO beete(name, kultur, notiz, standort_id, created) VALUES (?,?,?,?,?)",
            (
                payload.name,
                payload.kultur,
                payload.notiz,
                payload.standort_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
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
def garten_empfehlung(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
) -> dict:
    """Einfache regelbasierte Empfehlung aus Standort + Monat (DWD-Anbindung folgt via wetterdienst-lxc)."""
    month = datetime.now().month
    saison = "Fruehjahr" if 3 <= month <= 5 else "Sommer" if 6 <= month <= 8 else "Herbst" if 9 <= month <= 10 else "Winter"
    in_bw = 47.0 <= lat <= 49.9 and 7.4 <= lon <= 10.6
    if saison == "Fruehjahr":
        kulturen = ["Kartoffeln (früh)", "Spinat", "Radieschen", "Erbsen", "Streuobst: Apfel Topaz/Bohnapfel"]
        giessen = "maessig, Mulchen gegen Spaetfrost"
    elif saison == "Sommer":
        kulturen = ["Tomaten (geschuetzt)", "Zucchini", "Bohnen", "Streuobst: Sommerschnitt"]
        giessen = "morgens tief waessern, Bodenbedeckung halten"
    elif saison == "Herbst":
        kulturen = ["Feldsalat", "Knoblauch stecken", "Streuobst: Neupflanzung"]
        giessen = "wenig, Staunaesse vermeiden"
    else:
        kulturen = ["Planung", "Kompost ausbringen", "Streuobst: Winterschnitt"]
        giessen = "kein aktives Giessen"
    return {
        "lat": lat,
        "lon": lon,
        "in_bw": in_bw,
        "saison": saison,
        "empfohlene_kulturen": kulturen,
        "giess_hinweis": giessen,
        "boden_hinweis": "Platzhalter: sobald LGRB-Bodenfunktion per GetFeature angebunden ist, wird hier nach Bodenart differenziert.",
    }


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
        return {
            "standorte": [dict(r) for r in con.execute("SELECT * FROM standorte").fetchall()],
            "beete": [dict(r) for r in con.execute("SELECT * FROM beete").fetchall()],
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        con.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=APP_PORT)
