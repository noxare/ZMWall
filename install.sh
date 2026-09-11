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
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv mpv xorg openbox lightdm x11-xserver-utils unclutter openssl nginx

id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"
install -d -m 0755 "$APP_DIR"
cp -a "$SOURCE_DIR"/. "$APP_DIR"/
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -r "$APP_DIR/requirements.txt"

SECRET_KEY=$(openssl rand -hex 32)

install -d -o "$APP_USER" -g "$APP_USER" -m 0700 /var/lib/zmwall
install -o "$APP_USER" -g "$APP_USER" -m 0600 /dev/null "$ENV_FILE"
{
  printf 'ZMWALL_BIND=%q\n' "127.0.0.1"
  printf 'ZMWALL_PORT=%q\n' "8080"
  printf 'ZMWALL_SECRET_KEY=%q\n' "$SECRET_KEY"
  printf 'ZMWALL_DB=%q\n' "/var/lib/zmwall/zmwall.db"
  printf 'ZMWALL_DISPLAY=%q\n' ":0"
} > "$ENV_FILE"

install -m 0755 "$APP_DIR/renew-cert.sh" /usr/local/sbin/zmwall-renew-cert
install -m 0644 "$APP_DIR/deploy/zmwall-cert-renew.service" /etc/systemd/system/zmwall-cert-renew.service
install -m 0644 "$APP_DIR/deploy/zmwall-cert-renew.timer" /etc/systemd/system/zmwall-cert-renew.timer
install -m 0644 "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/zmwall
if [ -e /etc/nginx/sites-enabled/default ] || [ -L /etc/nginx/sites-enabled/default ]; then
  mv /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.disabled-by-zmwall
fi
ln -sfn /etc/nginx/sites-available/zmwall /etc/nginx/sites-enabled/zmwall
/usr/local/sbin/zmwall-renew-cert
nginx -t
systemctl daemon-reload
systemctl enable nginx
systemctl restart nginx
systemctl enable --now zmwall-cert-renew.timer

install -d -m 0755 /etc/lightdm/lightdm.conf.d
{
  echo "[Seat:*]"
  echo "autologin-user=$APP_USER"
  echo "autologin-user-timeout=0"
  echo "user-session=openbox"
} > /etc/lightdm/lightdm.conf.d/50-zmwall.conf

install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "/home/$APP_USER/.config/openbox"
{
  echo '<?xml version="1.0" encoding="UTF-8"?>'
  echo '<openbox_config xmlns="http://openbox.org/3.4/rc">'
  echo '  <keyboard>'
  echo '    <keybind key="C-A-End">'
  echo '      <action name="Exit"><prompt>no</prompt></action>'
  echo '    </keybind>'
  echo '  </keyboard>'
  echo '</openbox_config>'
} > "/home/$APP_USER/.config/openbox/rc.xml"
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

echo "Installation abgeschlossen. Nach dem Neustart: https://DIE-IP-DIESES-RECHNERS"
echo "Die Erstkonfiguration ist ohne Web-Login möglich. Nach dem ersten erfolgreichen ZoneMinder-Sync werden gültige ZoneMinder-Zugangsdaten für die Weboberfläche verlangt."
echo "Die lokale CA kann unter https://DIE-IP-DIESES-RECHNERS/zmwall-local-ca.crt heruntergeladen werden."\necho "Die Datei $ENV_FILE und die privaten TLS-Schlüssel sind lokal geschützt."
