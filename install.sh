#!/bin/bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo ausführen: sudo ./install.sh"
  exit 1
fi

APP_DIR=/opt/zmwall
APP_USER=zmwall
ENV_FILE=/etc/zmwall.env
SOURCE_DIR=$(cd "$(dirname "$0")" && pwd)

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv mpv xorg openbox lightdm x11-xserver-utils unclutter openssl

id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"
install -d -m 0755 "$APP_DIR"
cp -a "$SOURCE_DIR"/. "$APP_DIR"/
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$APP_DIR/requirements.txt"

read -r -p "Benutzer für die Weboberfläche [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}
read -r -s -p "Passwort für die Weboberfläche: " ADMIN_PASSWORD
echo
if [ -z "$ADMIN_PASSWORD" ]; then
  echo "Das Passwort darf nicht leer sein."
  exit 1
fi
PASSWORD_HASH=$("$APP_DIR/.venv/bin/python" -c 'import sys; from werkzeug.security import generate_password_hash; print(generate_password_hash(sys.argv[1]))' "$ADMIN_PASSWORD")
SECRET_KEY=$(openssl rand -hex 32)

install -d -o "$APP_USER" -g "$APP_USER" -m 0700 /var/lib/zmwall
install -o "$APP_USER" -g "$APP_USER" -m 0600 /dev/null "$ENV_FILE"
{
  printf 'ZMWALL_BIND=%q\n' "0.0.0.0"
  printf 'ZMWALL_PORT=%q\n' "8080"
  printf 'ZMWALL_ADMIN_USER=%q\n' "$ADMIN_USER"
  printf 'ZMWALL_ADMIN_PASSWORD_HASH=%q\n' "$PASSWORD_HASH"
  printf 'ZMWALL_SECRET_KEY=%q\n' "$SECRET_KEY"
  printf 'ZMWALL_DB=%q\n' "/var/lib/zmwall/zmwall.db"
  printf 'ZMWALL_DISPLAY=%q\n' ":0"
} > "$ENV_FILE"

install -d -m 0755 /etc/lightdm/lightdm.conf.d
{
  echo "[Seat:*]"
  echo "autologin-user=$APP_USER"
  echo "autologin-user-timeout=0"
  echo "user-session=openbox"
} > /etc/lightdm/lightdm.conf.d/50-zmwall.conf

install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "/home/$APP_USER/.config/openbox"
{
  echo "xset -dpms"
  echo "xset s off"
  echo "xset s noblank"
  echo "unclutter -idle 1 -root &"
  echo "while true; do set -a; . $ENV_FILE; set +a; $APP_DIR/.venv/bin/python $APP_DIR/run.py >> /var/lib/zmwall/zmwall.log 2>&1; sleep 2; done &"
} > "/home/$APP_USER/.config/openbox/autostart"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" "/home/$APP_USER/.config" /var/lib/zmwall
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 0600 "$ENV_FILE"
systemctl enable lightdm

echo "Installation abgeschlossen. Nach dem Neustart: http://DIE-IP-DIESES-RECHNERS:8080"
echo "Die Datei $ENV_FILE enthält Geheimnisse und ist nur für den Dienstbenutzer lesbar."
