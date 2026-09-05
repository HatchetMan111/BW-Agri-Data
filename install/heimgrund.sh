#!/usr/bin/env bash
# heimgrund - Proxmox VE Community-Scripts-konformer Installer (Einzeiler).
#
# Auf dem PROXMOX-HOST als root ausfuehren:
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/BW-Agri-Data/main/install/heimgrund.sh)"
#
# Was das Script tut:
#  1) erstellt (idempotent) einen unprivileged LXC (Debian 13)
#  2) installiert per pct exec: Systempakete, User, venv, App aus GitHub, systemd-Service
#  3) verifiziert: systemctl is-active + HTTP-Check auf localhost:$APP_PORT
#
# Debugging: DEBUG=1 bash -x install/heimgrund.sh   (voller Trace)
set -euo pipefail

# ---------------- Variablen (oben, anpassbar) ----------------
CTID="${CTID:-150}"
HOSTNAME="${HOSTNAME:-heimgrund}"
TEMPLATE="${TEMPLATE:-local:vztmpl/debian-13-standard_13.0-1_amd64.tar.zst}"
TEMPLATE_FALLBACK="${TEMPLATE_FALLBACK:-local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst}"
STORAGE="${STORAGE:-local-lvm}"
DISK_SIZE="${DISK_SIZE:-12G}"
CORES="${CORES:-2}"
MEMORY="${MEMORY:-2048}"
SWAP="${SWAP:-512}"
BRIDGE="${BRIDGE:-vmbr0}"
IPV4="${IPV4:-dhcp}"            # z.B. "192.168.1.150/24" oder "dhcp"
GW="${GW:-}"                    # bei dhcp leer lassen
DNS="${DNS:-1.1.1.1 8.8.8.8}"
APP_PORT="${APP_PORT:-8000}"
REPO="${REPO:-https://github.com/HatchetMan111/BW-Agri-Data}"
BRANCH="${BRANCH:-main}"
APP_USER="heimgrund"
APP_DIR="/opt/heimgrund"
VENV_DIR="/opt/heimgrund-venv"
DATA_DIR="/var/lib/heimgrund"
LOG_FILE="/tmp/heimgrund-install.log"
# -------------------------------------------------------------

exec > >(tee -a "$LOG_FILE") 2>&1
DEBUG="${DEBUG:-0}"
if [[ "$DEBUG" == "1" ]]; then set -x; fi

fail_chain() {
  local ec=$?
  echo ""
  echo "================ FEHLERKETTE ================" >&2
  echo "Exit-Code: $ec | Befehl: [$BASH_COMMAND]" >&2
  echo "--- Stacktrace (neueste zuerst) ---" >&2
  local i
  for (( i=${#FUNCNAME[@]}-1; i>=0; i-- )); do
    echo "  in ${FUNCNAME[$i]:-main} (${BASH_SOURCE[$i]:-script}:${BASH_LINENO[$i]:-?})" >&2
  done
  echo "--- PCT/letzte Logs ---" >&2
  pct status "$CTID" 2>&1 || true
  pct exec "$CTID" -- systemctl status heimgrund --no-pager -l 2>&1 | tail -40 || true
  pct exec "$CTID" -- journalctl -u heimgrund -n 50 --no-pager 2>&1 | tail -60 || true
  echo "Tipp: Re-run mit DEBUG=1 bash -x, Log: $LOG_FILE" >&2
  echo "=============================================" >&2
  exit $ec
}
trap fail_chain ERR

msg(){ echo -e "\n### $*"; }

require_root(){
  if [[ $EUID -ne 0 ]]; then echo "Bitte als root auf dem Proxmox-Host ausfuehren." >&2; exit 1; fi
  command -v pct >/dev/null || { echo "pct nicht gefunden - kein Proxmox-Host?" >&2; exit 1; }
}

pick_template(){
  if pveam list "$STORAGE" 2>/dev/null | grep -q "debian-13-standard"; then return 0; fi
  if pveam list local 2>/dev/null | grep -q "debian-13-standard"; then
    TEMPLATE="local:vztmpl/$(pveam list local 2>/dev/null | grep -o 'debian-13-standard[^ ]*amd64.tar.zst' | head -1)"
    return 0
  fi
  msg "Lade Debian-13-Template ..."
  pveam update || true
  pveam download local "$(basename "$TEMPLATE")" || pveam download local "$(basename "$TEMPLATE_FALLBACK")"
  TEMPLATE="local:vztmpl/$(basename "$TEMPLATE")"
}

ct_exists(){ pct status "$CTID" &>/dev/null; }

create_ct(){
  if ct_exists; then msg "CT $CTID existiert bereits -> Update-Pfad (idempotent)."; return 0; fi
  pick_template
  msg "Erstelle CT $CTID ($HOSTNAME) ..."
  local net0
  if [[ "$IPV4" == "dhcp" ]]; then
    net0="name=eth0,bridge=${BRIDGE},ip=dhcp,ip6=auto"
  else
    net0="name=eth0,bridge=${BRIDGE},ip=${IPV4},gw=${GW},ip6=auto"
  fi
  pct create "$CTID" "$TEMPLATE" \
    --hostname "$HOSTNAME" \
    --cores "$CORES" --memory "$MEMORY" --swap "$SWAP" \
    --rootfs "${STORAGE}:${DISK_SIZE}" \
    --net0 "$net0" \
    --nameserver "$DNS" --searchdomain "lan" \
    --unprivileged 1 --onboot 1 --start 1 \
    --features nesting=1
  msg "Warte auf Netzwerk ..."
  sleep 8
  pct exec "$CTID" -- ping -c1 -W3 1.1.1.1 || pct exec "$CTID" -- ip a
}

setup_in_ct(){
  msg "Installiere App in CT $CTID ..."
  pct exec "$CTID" -- bash -c "set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl ca-certificates git sqlite3
    rm -rf /var/lib/apt/lists/*
    id $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER
    mkdir -p $APP_DIR $DATA_DIR
    if [[ -d $APP_DIR/.git ]]; then
      echo \"--- Update: Stand vorher ---\"
      git -C $APP_DIR log --oneline -3 || true
      git -C $APP_DIR status --short | head -10 || true
      echo \"--- Update: hole $BRANCH von origin (lokale Aenderungen im CT werden verworfen) ---\"
      git -C $APP_DIR fetch --all
      git -C $APP_DIR checkout $BRANCH
      git -C $APP_DIR reset --hard origin/$BRANCH
      echo \"--- Update: Stand nachher ---\"
      git -C $APP_DIR log --oneline -3
    elif [[ -n \"$REPO\" ]]; then
      rm -rf ${APP_DIR}.tmp && git clone --depth 1 --branch $BRANCH \"$REPO\" ${APP_DIR}.tmp || echo \"WARN: git clone fehlgeschlagen ($REPO) - erwarte pct push der App-Dateien\"
      if [[ -d ${APP_DIR}.tmp/heimgrund-lxc/app ]]; then rm -rf $APP_DIR; mv ${APP_DIR}.tmp/heimgrund-lxc $APP_DIR/.. 2>/dev/null || true; fi
      if [[ -d ${APP_DIR}.tmp/app ]]; then rm -rf $APP_DIR; mv ${APP_DIR}.tmp $APP_DIR; fi
    fi
    ls -la $APP_DIR/app 2>&1 | head -20
    test -f $APP_DIR/app/main.py || { echo 'FEHLER: app/main.py fehlt. Entweder REPO korrigieren oder Dateien per pct push kopieren:'; echo '  pct push <CTID> app/main.py /opt/heimgrund/app/main.py'; exit 1; }
    python3 -m venv $VENV_DIR || true
    $VENV_DIR/bin/pip install --upgrade pip wheel
    if [[ -f $APP_DIR/app/requirements.txt ]]; then
      $VENV_DIR/bin/pip install -r $APP_DIR/app/requirements.txt
    else
      echo \"WARN: requirements.txt fehlt (altes Checkout) - installiere Minimaldeps\"
      $VENV_DIR/bin/pip install \"fastapi>=0.110,<1\" \"uvicorn[standard]>=0.29,<1\"
    fi
    mkdir -p $DATA_DIR
    chown -R $APP_USER:$APP_USER $APP_DIR $DATA_DIR
    cp -f $APP_DIR/systemd/heimgrund.service /etc/systemd/system/heimgrund.service
    sed -i 's/^Environment=APP_PORT=.*/Environment=APP_PORT=$APP_PORT/' /etc/systemd/system/heimgrund.service
    systemctl daemon-reload
    systemctl enable heimgrund.service
    systemctl restart heimgrund.service
    echo \"--- Deployed: \$(git -C $APP_DIR rev-parse --short HEAD 2>/dev/null || echo '?') / \$(grep '^APP_VERSION' $APP_DIR/app/main.py 2>/dev/null || echo 'VERSION?') ---\"
  "
}

verify(){
  msg "Verifiziere ..."
  pct exec "$CTID" -- systemctl is-active heimgrund
  sleep 4
  pct exec "$CTID" -- curl -fsS "http://127.0.0.1:${APP_PORT}/api/health"
  echo ""
  local ip
  ip=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
  echo ""
  echo "=================================================="
  echo " OK: heimgrund laeuft"
  echo " URL (LXC):  http://${ip:-<CT-IP>}:${APP_PORT}"
  echo " Health:     http://${ip:-<CT-IP>}:${APP_PORT}/api/health"
  echo " CT-ID: $CTID | Service: systemctl status heimgrund"
  echo " Update: REPO=$REPO -> im CT: git -C $APP_DIR pull && systemctl restart heimgrund"
  echo " Deinstallieren: pct stop $CTID && pct destroy $CTID"
  echo "=================================================="
}

main(){
  require_root
  create_ct
  # Falls REPO leer/Platzhalter ist, Hinweis (trotzdem per pct push nutzbar)
  if [[ -z "$REPO" || "$REPO" == *"USER/"* ]]; then
    echo "HINWEIS: REPO ist Platzhalter/leer ($REPO)."
    echo "Entweder REPO=... CTID=... $0 setzen oder App-Dateien manuell pushen:"
    echo "  pct push $CTID app/main.py /opt/heimgrund/app/main.py"
  fi
  # Lokale Dateien bevorzugen, wenn Script aus Repo-Checkout laeuft:
  if [[ -f "app/main.py" ]]; then
    msg "Pushe lokale App-Dateien in CT ..."
    pct exec "$CTID" -- mkdir -p /opt/heimgrund/app/static /opt/heimgrund/systemd
    pct push "$CTID" app/main.py /opt/heimgrund/app/main.py
    pct push "$CTID" app/requirements.txt /opt/heimgrund/app/requirements.txt
    pct push "$CTID" app/static/index.html /opt/heimgrund/app/static/index.html
    pct push "$CTID" systemd/heimgrund.service /opt/heimgrund/systemd/heimgrund.service
    # Repo-Klon im CT ueberspringen -> leeres REPO signalisieren
    REPO="" setup_in_ct
  else
    setup_in_ct
  fi
  verify
}
main "$@"
