#!/bin/bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Bitte mit sudo ausführen."; exit 1; fi
echo "Die Kamerakonfiguration in /var/lib/zmwall bleibt absichtlich erhalten."
rm -f /etc/lightdm/lightdm.conf.d/50-zmwall.conf
rm -rf /opt/zmwall
echo "Programm entfernt. Benutzer und Daten können nach Prüfung manuell entfernt werden."

