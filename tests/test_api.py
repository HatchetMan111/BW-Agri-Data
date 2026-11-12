"""API-Tests fuer heimgrund (ohne externe Live-Dienste).

Lauf im Sandbox/dev-venv:
    python -m pytest tests/ -q
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))

# DATA_DIR weg vom Repo (wird beim Import von main gelesen)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="heimgrund-test-")

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


# ---------------- Basis ----------------
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["app"] == "heimgrund"
    assert d["db_ok"] is True
    assert d["version"] == main.APP_VERSION


def test_meta(client):
    d = client.get("/api/meta").json()
    assert d["app"] == "heimgrund"
    assert len(d["live_quellen"]) >= 4


# ---------------- Standorte-CRUD ----------------
def test_standorte_crud(client):
    r = client.post("/api/standorte", json={"label": "Testacker", "lat": 48.77, "lon": 9.18})
    assert r.status_code == 201
    sid = r.json()["id"]
    lst = client.get("/api/standorte").json()
    assert any(s["id"] == sid and s["label"] == "Testacker" for s in lst)
    assert client.delete(f"/api/standorte/{sid}").json() == {"deleted": sid}
    assert client.delete(f"/api/standorte/{sid}").status_code == 404


def test_standorte_validierung(client):
    assert client.post("/api/standorte", json={"label": "x", "lat": 99.0, "lon": 0}).status_code == 422
    assert client.post("/api/standorte", json={"label": "", "lat": 0, "lon": 0}).status_code == 422


# ---------------- Beete-CRUD ----------------
def test_beete_crud(client):
    r = client.post("/api/beete", json={"name": "Hochbeet Nord", "kultur": "Kartoffeln", "notiz": "Kompost"})
    assert r.status_code == 201
    bid = r.json()["id"]
    lst = client.get("/api/beete").json()
    assert any(b["id"] == bid and b["name"] == "Hochbeet Nord" for b in lst)
    assert client.delete(f"/api/beete/{bid}").status_code == 200


# ---------------- Export ----------------
def test_export(client):
    d = client.get("/api/export").json()
    assert "standorte" in d and "beete" in d and "exported_at" in d


# ---------------- SPA-Serving ----------------
def test_index_spa(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert 'id="root"' in r.text
    assert "/assets/" in r.text  # Vite-Build verlinkt


def test_spa_fallback(client):
    r = client.get("/irgendein/deep/link")
    assert r.status_code == 200
    assert 'id="root"' in r.text


def test_assets_werden_ausgeliefert(client):
    idx = (main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    import re
    m = re.search(r'href="/assets/(index-[\w-]+\.css)"', idx)
    assert m, "CSS-Asset fehlt im index.html"
    r = client.get(f"/assets/{m.group(1)}")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_unbekannte_api_route_404(client):
    r = client.get("/api/gibtsnicht")
    assert r.status_code == 404


# ---------------- Sicherheit ----------------
def test_spa_kein_path_traversal():
    # direkt: spa() darf nie Dateien ausserhalb STATIC_DIR ausliefern
    from fastapi import HTTPException
    try:
        resp = main.spa("../../.git/config")
        content = resp.body if hasattr(resp, "body") else b""
        assert b"[core]" not in content
    except HTTPException:
        pass  # 500 (kein Frontend) ist auch ok


def test_input_validierung_query(client):
    r = client.get("/api/reverse_geocode", params={"lat": 91, "lon": 0})
    assert r.status_code == 422
    r = client.get("/api/reverse_geocode", params={"lat": 48.7, "lon": 200})
    assert r.status_code == 422


# ---------------- Logik-Einheiten ----------------
def test_garten_score_rahmen():
    for clay in (5, 25, 45):
        for sand in (10, 45, 90):
            for ph in (5.0, 6.5, 8.0):
                sc = main.garten_score(clay, sand, ph)
                assert 5 <= sc["wert"] <= 98


def test_bodenart_de():
    assert main.bodenart_de(90, 5, 5) == "Ton"
    assert main.bodenart_de(5, 90, 5) == "Sand"
    assert main.bodenart_de(30, 40, 30) == "Lehm"


def test_haversine():
    # Stuttgart <-> Ludwigsburg ~ 12 km
    d = main.haversine_km(48.7758, 9.1829, 48.8956, 9.1904)
    assert 10 < d < 15


def test_wmo_de():
    assert main.wmo_de(0)[0] == "Klar"
    assert main.wmo_de(65)[0] == "Starkregen"
    assert main.wmo_de(999) == ("–", "🌡️")


def test_score_band():
    assert main._score_band(10, 10, 20, 5) == 100.0
    assert main._score_band(9, 10, 20, 5) == 100.0 - (1 / 5) * 90.0
    assert main._score_band(0, 10, 20, 5) == 5.0  # minimum


def test_mit_aussagekraft():
    out = main.mit_aussagekraft({
        "a": {"wert": 50, "gewicht": 50, "vertrauen": "hoch"},
        "b": {"wert": 50, "gewicht": 50, "vertrauen": "niedrig"},
    })
    assert out["prozent"] == round((100 * 50 + 25 * 50) / 100)
    leer = main.mit_aussagekraft({})
    assert leer["prozent"] is None
