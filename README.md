# heimgrund – Grundstück-Check + Gartenplaner (Proxmox LXC)

Lokale App auf Basis `daten-bw.de / groups=agri` (Geoportal BW, LUBW, InVeKoS LPIS,
Bodenschätzung, AWGN, Biosphäre). 1 LXC, 1 App, 2 Module. Kein Cloud-Zwang:
ohne Netz antwortet die API mit gekennzeichnetem Cache/Mock.

- **Stack:** Python 3.11+ / FastAPI / Uvicorn / SQLite (Stdlib), Vanilla-JS + Leaflet-Karte (CDN, mit Offline-Fallback)
- **Port:** `8000` (via `APP_PORT` änderbar)
- **LXC-Default:** Debian 13 unprivileged, 2 vCPU, 2 GB RAM, 12 GB Disk, `onboot: 1`

## Was die App zeigt (alles live, alles gecacht)

| Modul | Echte Datenquelle |
|---|---|
| 🌍 Boden | SoilGrids (ISRIC): Bodenart, Sand/Schluff/Ton-Balken, pH, Humus, Garten-Score |
| 🌤️ Wetter | Open-Meteo: aktuell + 4-Tage-Vorhersage, Höhenmeter |
| 💧 Pegel | PEGELONLINE: 3 nächste Pegel mit aktuellem Stand, 24h-Trend, Verlaufskurve |
| 🦋 Umfeld | OpenStreetMap: Schutzgebiete im Umkreis (mit Karte), Landnutzung (Acker/Wald/…) |
| 🔎 Suche | Nominatim-Adresssuche + Klick auf Karte statt Koordinaten-Tippen |
| 🌱 Garten | Gieß-Empfehlung aus echtem Regen + Boden + Saison |
| 🚜 Acker-Test | Eignungs-Score (Boden 35 / Klima 20 / Hang 20 / Umfeld 15 / Schutz 10) + Kulturmatrix für Weizen, Mais, Kartoffel, Grünland, Streuobst, Wein — Klima aus ERA5 2020–24, Hang aus Höhenmodell |
| 🏛️ Behörden-Check | Punktabfrage (±50 m) in LUBW-Fachdaten: NSG, FFH, LSG, WSG, FFH-Mähwiesen, Überschwemmungsgebiete — mit Gebietsnamen |
| 🏗️ Bau-Check | Erwerbs-Einschätzung: K.O. (ÜSG/NSG/FFH), Denkmalschutz (LAD live), Lärm-Abstände, Starkregentage (ERA5), Hang, Lage-Score (Bus/Bahn/Einkauf/Schule/Arzt) + Kauf-Checkliste |
| 🌲 Wald | Waldanteil + Laub/Nadel (OSM), Klimafitness, Sturmsicherheit, Boden-Hinweis |
| 🗺️ Karten-Overlays | Luftbild DOP 20cm (LGL) + FVA-Layer (Bestockung, Sturmrisiko, Buchdrucker) direkt in der Karte |

## Einzeiler (Proxmox-Host als root)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BW-Agri-Data/main/install/heimgrund.sh)"
```

Mit eigenem Repo / CT-ID / statischer IP / Storage:

```bash
REPO=https://github.com/HatchetMan111/BW-Agri-Data CTID=150 IPV4=192.168.1.150/24 GW=192.168.1.1 \
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BW-Agri-Data/main/install/heimgrund.sh)"
```

Der Installer wählt automatisch (nur falls nötig):
- **nächsten freien CTID**, wenn `$CTID` von einem fremden Container belegt ist
  (eigener `heimgrund`-CT → Update-Pfad, idempotent)
- **erstes aktives rootdir-Storage** + vorhandenes Debian-13-Template
- Per Env erzwingbar: `CTID=160 STORAGE=local CT_HOSTNAME=heimgrund ...`

Debug mit vollem Trace:

```bash
DEBUG=1 bash -x install/heimgrund.sh
```

## Was das Install-Script tut

1. Erstellt (idempotent) CT `$CTID` – existiert er schon, läuft der Update-Pfad.
2. Installiert im CT: Python-venv, User `heimgrund`, App nach `/opt/heimgrund`, Daten nach `/var/lib/heimgrund`.
3. Installiert `systemd/heimgrund.service` (`enable`, `Restart=always`, `After=network-online.target`), CT mit `onboot: 1`.
4. Verifiziert selbst: `systemctl is-active heimgrund` + `curl localhost:8000/api/health`, gibt finale URL + CT-IP aus.
5. Bei Fehlern: komplette Fehlerkette (Exit-Code, Befehl, Stack, `systemctl status`, `journalctl -n 50`). Log: `/tmp/heimgrund-install.log`.

Aus lokalem Checkout (ohne GitHub): `install/heimgrund.sh` pusht `app/` automatisch per `pct push`, wenn `app/main.py` nebenan liegt.

## Web UI

Nach Installation: `http://<LXC-IP>:8000`

- `/` – Tabs Grundstück / Garten / Beete
- `GET /api/health`, `GET /api/meta`, `GET /docs`
- `GET /api/standort/reverse?lat=48.7758&lon=9.1829`
- `GET /api/garten/empfehlung?lat=..&lon=..`
- `GET/POST /api/standorte`, `GET/POST/DELETE /api/beete`, `GET /api/export`

## Update / Deinstall

```bash
# Update im CT:
pct exec 150 -- bash -c 'git -C /opt/heimgrund pull --ff-only; /opt/heimgrund-venv/bin/pip install -r /opt/heimgrund/app/requirements.txt; systemctl restart heimgrund'
# Deinstall:
pct stop 150 && pct destroy 150
```

## Problemlösung: Version bleibt nach Update alt

Kopfzeile zeigt alte Version (statt aktuell)? Dann hat das Update den Code nicht übernommen
(typisch: lokale Dateiänderungen im CT blockierten früher das `git pull`).
Diagnose + Reparatur auf dem Proxmox-Host:

```bash
pct exec 150 -- git -C /opt/heimgrund log --oneline -3
pct exec 150 -- git -C /opt/heimgrund status --short
# Reparatur: hart auf GitHub-Stand setzen + Dienst neu starten
pct exec 150 -- bash -c 'git -C /opt/heimgrund fetch --all && git -C /opt/heimgrund reset --hard origin/main && grep ^APP_VERSION /opt/heimgrund/app/main.py && systemctl restart heimgrund'
curl http://<CT-IP>:8000/api/health   # "version" muss jetzt aktuell sein
```

## Manueller Test (ohne Proxmox)

```bash
python3 -m venv /tmp/hg-venv && /tmp/hg-venv/bin/pip install -r app/requirements.txt
DATA_DIR=/tmp/hg-data APP_PORT=8000 /tmp/hg-venv/bin/uvicorn main:app --app-dir app --host 127.0.0.1 --port 8000
curl localhost:8000/api/health
```

## Projekt-Layout

```
heimgrund-lxc/
  install/heimgrund.sh
  app/main.py
  app/requirements.txt
  app/static/index.html
  systemd/heimgrund.service
  README.md
```
