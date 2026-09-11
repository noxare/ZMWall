#!/bin/bash
set -euo pipefail

APP_DIR=/opt/zmwall
ENV_FILE=/etc/zmwall.env
APP_USER=zmwall

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root oder mit sudo ausführen: sudo ./pwreset.sh"
  exit 1
fi

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "Fehler: Python-Umgebung von ZMWall wurde nicht gefunden: $APP_DIR/.venv/bin/python"
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Fehler: Konfigurationsdatei wurde nicht gefunden: $ENV_FILE"
  exit 1
fi

while true; do
  read -r -s -p "Neues Passwort für die Weboberfläche: " ADMIN_PASSWORD
  echo

  if [ -z "$ADMIN_PASSWORD" ]; then
    echo "Das Passwort darf nicht leer sein. Bitte erneut eingeben."
    continue
  fi

  read -r -s -p "Passwort wiederholen: " ADMIN_PASSWORD_CONFIRM
  echo

  if [ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]; then
    echo "Die Passwörter stimmen nicht überein. Bitte erneut eingeben."
    continue
  fi

  break
done

PASSWORD_HASH=$("$APP_DIR/.venv/bin/python" -c 'import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.argv[1]))' "$ADMIN_PASSWORD")
unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM

"$APP_DIR/.venv/bin/python" - "$ENV_FILE" "$PASSWORD_HASH" <<'PY'
import shlex
import sys
from pathlib import Path

env_file = Path(sys.argv[1])
password_hash = sys.argv[2]
lines = env_file.read_text().splitlines()
key = "ZMWALL_ADMIN_PASSWORD_HASH="

updated = False
out = []
for line in lines:
    if line.startswith(key):
        out.append(key + shlex.quote(password_hash))
        updated = True
    else:
        out.append(line)

if not updated:
    out.append(key + shlex.quote(password_hash))

env_file.write_text("\n".join(out) + "\n")
PY

chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 0600 "$ENV_FILE"

# ZMWall wird von der Openbox-Autostart-Schleife automatisch neu gestartet.
# Den laufenden Prozess beenden, damit das neue Passwort sofort aktiv wird.
pkill -f "$APP_DIR/run.py" 2>/dev/null || true

echo "Passwort wurde erfolgreich geändert."
echo "ZMWall wird automatisch neu gestartet; bitte die Weboberfläche in ein paar Sekunden neu laden."
