#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Bitte mit sudo ausführen."; exit 1; fi
echo "Die Kamerakonfiguration in /var/lib/zmwall bleibt absichtlich erhalten."
systemctl disable --now zmwall-cert-renew.timer 2>/dev/null || true
rm -f /etc/systemd/system/zmwall-cert-renew.service /etc/systemd/system/zmwall-cert-renew.timer
rm -f /usr/local/sbin/zmwall-renew-cert
rm -f /etc/nginx/sites-enabled/zmwall /etc/nginx/sites-available/zmwall
if [ ! -e /etc/nginx/sites-enabled/default ] && [ -e /etc/nginx/sites-enabled/default.disabled-by-zmwall ]; then
  mv /etc/nginx/sites-enabled/default.disabled-by-zmwall /etc/nginx/sites-enabled/default
fi
rm -rf /etc/zmwall/tls
systemctl daemon-reload
if systemctl is-active --quiet nginx; then
  nginx -t && systemctl reload nginx
fi
rm -f /etc/lightdm/lightdm.conf.d/50-zmwall.conf
rm -rf /opt/zmwall
echo "Programm entfernt. Benutzer und Daten können nach Prüfung manuell entfernt werden."

