#!/bin/bash
set -euo pipefail

APP_DIR=/opt/zmwall
APP_USER=zmwall
EXPECTED_BRANCH=main

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausführen: sudo $APP_DIR/update.sh"
  exit 1
fi

exec 9>/run/lock/zmwall-update.lock
if ! flock -n 9; then
  echo "Es läuft bereits eine ZMWall-Aktualisierung."
  exit 1
fi

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Fehler: $APP_DIR ist kein Git-Checkout."
  exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
  echo "Fehler: Der Benutzer $APP_USER existiert nicht."
  exit 1
fi

run_git() {
  runuser -u "$APP_USER" -- git -C "$APP_DIR" "$@"
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
runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/pip" install \
  --disable-pip-version-check \
  -r "$APP_DIR/requirements.txt"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "Starte die ZMWall-Anzeige neu ..."
systemctl restart lightdm

if [ "$old_revision" = "$new_revision" ]; then
  echo "Prüfung abgeschlossen; die ZMWall-Anzeige wurde neu gestartet."
else
  echo "Update abgeschlossen: ${old_revision:0:8} -> ${new_revision:0:8}"
fi
