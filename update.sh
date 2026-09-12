#!/bin/bash
set -euo pipefail

APP_DIR=/opt/zmwall
APP_USER=zmwall
EXPECTED_BRANCH=main
MODE=manual
APP_PID=""
APPROVED_SHA=""

if [ "${ZMWALL_UPDATE_RUNNING_COPY:-0}" != "1" ]; then
  update_copy=$(mktemp /tmp/zmwall-update.XXXXXX)
  cp -- "$0" "$update_copy"
  chmod 0700 "$update_copy"
  export ZMWALL_UPDATE_RUNNING_COPY=1
  exec /bin/bash "$update_copy" "$@"
fi
trap 'unlink "$0"' EXIT

if [ "${1:-}" = "--web" ]; then
  MODE=web
  APP_PID=${2:-}
  APPROVED_SHA=${3:-}
  shift 3 || true
fi

if [ "$#" -ne 0 ]; then
  echo "Verwendung: $APP_DIR/update.sh [--web APP-PID FREIGEGEBENER-COMMIT]"
  exit 1
fi

if [ "$MODE" = "manual" ] && [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausführen: sudo $APP_DIR/update.sh"
  exit 1
fi

if [ "$MODE" = "web" ]; then
  if [ "$(id -un)" != "$APP_USER" ]; then
    echo "Fehler: Web-Updates dürfen nur als Benutzer $APP_USER laufen."
    exit 1
  fi
  if ! [[ "$APP_PID" =~ ^[1-9][0-9]*$ ]] || ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "Fehler: Ungültiger ZMWall-Prozess."
    exit 1
  fi
  if ! [[ "$APPROVED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Fehler: Ungültiger freigegebener Commit."
    exit 1
  fi
  app_process_user=$(ps -o user= -p "$APP_PID" | xargs)
  app_process_command=$(tr '\0' ' ' < "/proc/$APP_PID/cmdline")
  if [ "$app_process_user" != "$APP_USER" ] || [[ "$app_process_command" != *"$APP_DIR/run.py"* ]]; then
    echo "Fehler: PID $APP_PID gehört nicht zum erwarteten ZMWall-Prozess."
    exit 1
  fi
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Fehler: Der Benutzer $APP_USER existiert nicht."
  exit 1
fi

LOCK_FILE=/var/lib/zmwall/update.lock
if [ "$(id -u)" -eq 0 ]; then
  touch "$LOCK_FILE"
  chown "$APP_USER:$APP_USER" "$LOCK_FILE"
  chmod 0660 "$LOCK_FILE"
fi
exec 9>>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Es läuft bereits eine ZMWall-Aktualisierung."
  exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Fehler: $APP_DIR ist kein Git-Checkout."
  exit 1
fi

run_git() {
  if [ "$(id -u)" -eq 0 ]; then
    runuser -u "$APP_USER" -- git -C "$APP_DIR" "$@"
  else
    git -C "$APP_DIR" "$@"
  fi
}

origin_url=$(run_git remote get-url origin)
case "$origin_url" in
  https://github.com/noxare/ZMWall|https://github.com/noxare/ZMWall.git|git@github.com:noxare/ZMWall.git)
    ;;
  *)
    echo "Fehler: Unerwartetes Git-Repository: $origin_url"
    exit 1
    ;;
esac

current_branch=$(run_git branch --show-current)
if [ "$current_branch" != "$EXPECTED_BRANCH" ]; then
  echo "Fehler: Erwartet wird Branch $EXPECTED_BRANCH, aktiv ist ${current_branch:-kein Branch}."
  exit 1
fi

if [ -n "$(run_git status --porcelain --untracked-files=no)" ]; then
  echo "Fehler: Unter $APP_DIR liegen lokale Änderungen an verwalteten Dateien."
  echo "Das Update wurde abgebrochen, damit nichts überschrieben wird."
  exit 1
fi

old_revision=$(run_git rev-parse HEAD)
echo "Suche nach ZMWall-Updates ..."
run_git fetch --prune origin "$EXPECTED_BRANCH"

if ! run_git merge-base --is-ancestor HEAD "origin/$EXPECTED_BRANCH"; then
  echo "Fehler: Das lokale Repository und origin/$EXPECTED_BRANCH sind nicht per Fast-Forward vereinbar."
  exit 1
fi

new_revision=$(run_git rev-parse "origin/$EXPECTED_BRANCH")
if [ "$MODE" = "web" ] && [ "$new_revision" != "$APPROVED_SHA" ]; then
  echo "Fehler: main wurde nach der Freigabe erneut geändert. Bitte das neue Update bestätigen."
  exit 1
fi
if [ "$old_revision" = "$new_revision" ]; then
  echo "ZMWall ist bereits aktuell."
else
  run_git merge --ff-only "origin/$EXPECTED_BRANCH"
fi

if [ ! -x "$APP_DIR/.venv/bin/pip" ]; then
  echo "Fehler: Die Python-Umgebung unter $APP_DIR/.venv fehlt."
  exit 1
fi

echo "Aktualisiere Python-Abhängigkeiten ..."
if [ "$(id -u)" -eq 0 ]; then
  runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/pip" install \
    --disable-pip-version-check \
    -r "$APP_DIR/requirements.txt"
else
  "$APP_DIR/.venv/bin/pip" install \
    --disable-pip-version-check \
    -r "$APP_DIR/requirements.txt"
fi

if [ "$(id -u)" -eq 0 ]; then
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
fi

if [ "$MODE" = "web" ]; then
  echo "Starte nur den ZMWall-Prozess neu ..."
  sleep 2
  kill -TERM "$APP_PID"
else
  echo "Starte die ZMWall-Anzeige neu ..."
  systemctl restart lightdm
fi

if [ "$old_revision" = "$new_revision" ]; then
  echo "Prüfung abgeschlossen; ZMWall wurde neu gestartet."
else
  echo "Update abgeschlossen: ${old_revision:0:8} -> ${new_revision:0:8}"
fi
