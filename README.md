# ZM Wall

ZM Wall macht aus einem schlanken Debian-Rechner eine über das Netzwerk konfigurierbare RTSP-Videowand für ZoneMinder. Jeder physische Monitor kann ein eigenes Raster und eine eigene Kamerabelegung erhalten. Die Streams werden direkt mit `mpv` wiedergegeben; die Weboberfläche dient nur zur Verwaltung.

## Funktionen

- einstellbares Raster von 1×1 bis 8×8 je Display-Ausgang
- beliebig viele angeschlossene Displays
- mehrere unabhängige ZoneMinder-Verbindungen
- ZoneMinder-Multiserver: Zuordnung über `Monitor.ServerId` und `/api/servers.json`
- automatische Übernahme von Kamera-ID, Name, Status und zuständigem Server
- Hostname bevorzugt; automatische Fallback-IP pro ZoneMinder-Server
- erneute API-Synchronisierung alle fünf Minuten und manuell per Schaltfläche
- anpassbare RTSP-Port-, Streamname- und URL-Regeln
- abweichender RTSP-Host oder Streamname pro Kamera möglich
- Erstkonfiguration der Weboberfläche ohne lokales Kennwort
- nach erfolgreicher ZoneMinder-Erkennung Anmeldung direkt gegen ZoneMinder
- direkter RTSP-Abruf mit `mpv`, Hardware-Decoding und TCP-Transport

## Voraussetzungen

- Debian 12 oder 13 auf einem dedizierten Anzeigerechner
- Netzwerkzugriff auf die ZoneMinder-API und alle RTSP-Ports
- ein eigener ZoneMinder-Benutzer mit mindestens Leserechten auf die benötigten Monitore
- für die automatische Multiserver-Zuordnung müssen die in ZoneMinder hinterlegten Server-Hostnamen vom Anzeigerechner aus auflösbar sein

Die ZoneMinder-API muss unter **Options → System → OPT_USE_API** aktiviert sein. Für die aktuelle Token-Anmeldung benötigt ZoneMinder außerdem einen gesetzten `AUTH_HASH_SECRET`.

## Installation

Auf dem frisch installierten Debian:

```bash
tar -xzf zmwall.tar.gz
cd zmwall
sudo bash install.sh
sudo reboot
```

Der Installer richtet Xorg, Openbox, LightDM, `mpv`, Nginx, lokales HTTPS, den Benutzer `zmwall` und die Python-Umgebung ein. Ein separates Kennwort für die ZM-Wall-Weboberfläche wird nicht mehr angelegt. Danach ist die Verwaltung unter folgender Adresse erreichbar:

```text
https://IP-DES-ANZEIGERECHNERS
```

## Lokales HTTPS

Nginx stellt die Weboberfläche auf Port 443 bereit und leitet Port 80 automatisch auf HTTPS um. Der Python-Webdienst ist nur lokal unter `127.0.0.1:8080` erreichbar.

Bei der Installation wird eine lokale ZMWall-CA mit zehn Jahren Laufzeit angelegt. Das davon signierte Serverzertifikat ist 90 Tage gültig. Der systemd-Timer `zmwall-cert-renew.timer` prüft es täglich, erneuert es 30 Tage vor Ablauf und berücksichtigt auch geänderte lokale IPv4-Adressen.

Die öffentliche CA kann nach der Installation hier heruntergeladen und einmalig auf den Verwaltungsgeräten als vertrauenswürdig eingerichtet werden:

```text
https://IP-DES-ANZEIGERECHNERS/zmwall-local-ca.crt
```

Der private CA-Schlüssel liegt ausschließlich unter `/etc/zmwall/tls/zmwall-local-ca.key` und darf den Anzeigerechner nicht verlassen.

## Erste Einrichtung und Anmeldung

Solange noch keine ZoneMinder-Verbindung erfolgreich synchronisiert wurde, ist die Weboberfläche absichtlich ohne Anmeldung erreichbar. Dadurch kann die erste ZoneMinder-Verbindung eingerichtet und bei falscher URL, TLS-Problemen oder fehlerhaften Zugangsdaten korrigiert werden.

1. In der Weboberfläche eine ZoneMinder-Verbindung hinzufügen. Als URL beispielsweise `https://zm.example/zm` eintragen, also den Pfad vor `/api`.
2. ZoneMinder-Benutzername und Kennwort für die API-/RTSP-Verbindung eintragen.
3. RTSP-Port festlegen. Der Vorgabewert ist `20000`.
4. Die Streamname-Regel festlegen. `{id}` ergibt beispielsweise für Monitor 100 den Streamnamen `100`.
5. Nach dem ersten erfolgreichen Sync wird die Weboberfläche automatisch geschützt. Der Browser verlangt dann Benutzername und Kennwort; diese werden direkt gegen `/api/host/login.json` des erfolgreich erkannten ZoneMinder-Servers geprüft.
6. Einen erkannten Display-Ausgang hinzufügen, Zeilen und Spalten wählen und die Kameras auf die Kacheln verteilen.
7. **Layout übernehmen** klicken. Die Anzeige wird ohne Neustart neu aufgebaut.

Bei mehreren erfolgreich synchronisierten ZoneMinder-Verbindungen genügt ein gültiger Benutzer auf einer dieser Installationen für den Zugriff auf ZM Wall.

Die mitgelieferte RTSP-Vorlage entspricht:

```text
rtsp://{host}:{port}/{stream}?username={username}&password={password}
```

Verfügbare Werte sind `{host}`, `{port}`, `{stream}`, `{username}`, `{password}`, `{id}` und `{name}`. Die Streamname-Regel versteht `{id}`, `{name}` und `{server_id}`.

## Multiserver-Verhalten

ZM Wall fragt am eingetragenen ZoneMinder-Controller `/api/monitors.json` und `/api/servers.json` ab. Bei jeder Kamera wird `Monitor.ServerId` mit dem passenden `Server.Id` verknüpft und `Server.Hostname` als RTSP-Host verwendet. Bei einer Einzelserver-Installation wird der Hostname der eingetragenen ZoneMinder-URL benutzt.

ZM Wall speichert bei jeder erfolgreichen Namensauflösung zusätzlich die ermittelte IPv4-Adresse des ZoneMinder-Servers. Ist der Hostname später nicht mehr auflösbar, wird automatisch diese zuletzt bekannte IP verwendet. Ist der Name bereits bei der ersten Einrichtung nicht auflösbar, kann unter der ZoneMinder-Verbindung einmalig eine **Fallback-IP** für den betreffenden Server eingetragen werden. Sie gilt automatisch für alle Kameras mit dieser `ServerId`.

Zusätzlich kann für Sonderfälle weiterhin in der Kameraliste ein individueller **RTSP-Host (optional)** eingetragen werden. Diese Kamera-Überschreibung hat die höchste Priorität und bleibt bei späteren Synchronisierungen erhalten.

## Betrieb und Diagnose

Die wichtigsten Dateien:

```text
/opt/zmwall/                       Programm
/etc/zmwall.env                    Laufzeitkonfiguration
/var/lib/zmwall/zmwall.db          ZoneMinder-, Kamera- und Grid-Konfiguration
/var/lib/zmwall/zmwall.log         Programm- und Player-Log
/etc/lightdm/lightdm.conf.d/50-zmwall.conf
```

Prüfen, ob Displays erkannt werden:

```bash
sudo -u zmwall DISPLAY=:0 xrandr --query
```

Log beobachten:

```bash
sudo tail -f /var/lib/zmwall/zmwall.log
```

Einen erzeugten Stream unabhängig testen (Kennwort nicht in gemeinsam genutzte Shell-History übernehmen):

```bash
mpv 'rtsp://SERVER:20000/100?username=BENUTZER&password=PASSWORT'
```

Bei selbst signierten HTTPS-Zertifikaten kann die TLS-Prüfung je ZoneMinder-Verbindung deaktiviert werden. Im normalen Betrieb sollte sie aktiviert bleiben.

## Sicherheit

- Die Erstkonfiguration ist nur solange offen, bis mindestens eine ZoneMinder-Verbindung erfolgreich synchronisiert wurde. Deshalb sollte ZM Wall trotzdem nur im vertrauenswürdigen LAN oder Verwaltungs-VLAN betrieben werden.
- Danach wird jeder Zugriff per HTTP-Basisauthentifizierung abgefragt und das eingegebene Benutzername/Kennwort-Paar direkt gegen ZoneMinder geprüft. Es existiert kein separates lokales Web-Kennwort.
- Die HTTP-Basisauthentifizierung wird ausschließlich innerhalb der lokalen HTTPS-Verbindung übertragen.
- ZoneMinder-Zugangsdaten für API und RTSP werden lokal in `/var/lib/zmwall/zmwall.db` gespeichert. Verzeichnis und Datei sind ausschließlich für den Dienstbenutzer zugänglich.
- Die kennworthaltige RTSP-URL wird `mpv` über die Standardeingabe übergeben und steht daher nicht in dessen Prozessargumenten.
- Empfohlen ist ein eigener ZoneMinder-Benutzer, der nur die anzuzeigenden Kameras lesen darf.

## Deinstallation

```bash
sudo bash /opt/zmwall/uninstall.sh
```

Die Deinstallation entfernt das Programm und den Autostart, lässt `/var/lib/zmwall` als Sicherung aber bestehen.
