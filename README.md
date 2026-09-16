# ZM Wall

**Deutsch** · [English](README.en.md)

[Detaillierter Änderungsverlauf](CHANGELOG.md)

Aktueller Entwicklungsstand: **0.3.0-beta.24**

ZM Wall macht aus einem Debian-Rechner eine über das Netzwerk konfigurierbare RTSP-Videowand für ZoneMinder. Jeder physische Monitor erhält ein eigenes Raster und eine eigene Kamerabelegung. Die Anzeige verwendet ZoneMinders integrierte RTSP-Restreams und erzeugt keine zusätzlichen direkten Verbindungen zu den Kameras.

## Aktueller Funktionsumfang

- mehrere Displays und unabhängige ZoneMinder-Verbindungen
- visuelle Grid-Vorgaben sowie benutzerdefinierte Raster von 1×1 bis 8×8
- Drag-and-drop-Belegung aus einem Vorrat verfügbarer RTSP-Kameras
- mehrere Kameras je Grid-Position mit einstellbarem Wechselintervall
- vorgepufferter Kamerawechsel ohne absichtlich erzeugte Schwarzphase
- automatische Wiederherstellung ausgefallener Streams
- automatische ZoneMinder-Multiserver-Zuordnung über `Monitor.ServerId`
- frei konfigurierbare RTSP-Ports, Streamnamen und URL-Vorlagen
- automatische Hardwaredecoderwahl mit Rockchip-MPP- und Intel-VAAPI-Unterstützung sowie CPU-Fallback
- Live-Anzeige des verwendeten CPU-/GPU-Decoders pro Stream
- Vollbild einer Grid-Position per Doppelklick oder Tastenkombination
- deutsch- und englischsprachige Weboberfläche und Wall-Hinweise
- Stream-, Auflösungs-, Hardwaredecoder- und Netzwerkdiagnose
- geschützte Aktualisierung direkt aus der Weboberfläche

## Voraussetzungen

- Debian 12 oder 13 auf einem dedizierten Anzeigerechner
- Netzwerkzugriff auf ZoneMinder-API und RTSP-Restreams
- ZoneMinder-Benutzer mit Leserechten auf die benötigten Monitore
- aktivierte API unter **Options → System → OPT_USE_API**
- gesetztes `AUTH_HASH_SECRET` für die Token-Anmeldung
- erreichbarer RTSP-Restream; Standardport ist `20000`

Für die automatische Multiserver-Zuordnung sollten die in ZoneMinder hinterlegten Server-Hostnamen vom Anzeigerechner auflösbar sein. Alternativ kann je Server eine Fallback-IP hinterlegt werden.

## Installation

Auf einem frisch installierten Debian:

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/noxare/ZMWall.git
cd ZMWall
sudo bash install.sh
sudo reboot
```

Der Installer richtet Xorg, Openbox, LightDM, `mpv`, Nginx, lokales HTTPS, den Benutzer `zmwall` und die Python-Umgebung ein. Danach ist die Verwaltung erreichbar unter:

```text
https://IP-DES-ANZEIGERECHNERS
```

## Erste Einrichtung

Die Weboberfläche bleibt bis zur ersten erfolgreich synchronisierten ZoneMinder-Verbindung ohne Anmeldung erreichbar.

1. ZoneMinder-Verbindung hinzufügen, beispielsweise `https://zm.example/zm` ohne `/api`.
2. ZoneMinder-Benutzername, Kennwort und RTSP-Port eintragen.
3. Streamname-Regel festlegen; `{id}` verwendet die Monitor-ID.
4. Verbindung synchronisieren. Danach wird die Weboberfläche automatisch durch die Anmeldung gegen ZoneMinder geschützt.
5. Erkannten Display-Ausgang hinzufügen und Grid sowie Wechselintervall wählen.
6. Kameras aus **Verfügbare Kameras** auf die Grid-Positionen ziehen.
7. **Alle Layouts übernehmen** wählen.

Mehrere Kameras in einer Position wechseln in ihrer angezeigten Reihenfolge. Auf Touch-Geräten kann zuerst die Kamera und anschließend die Zielposition angetippt werden. Bereits konfigurierte Display-Ausgänge stehen erst nach dem Löschen ihrer Konfiguration wieder zur Auswahl.

Die Standardvorlage für RTSP lautet:

```text
rtsp://{host}:{port}/{stream}?username={username}&password={password}
```

Verfügbare Werte sind `{host}`, `{port}`, `{stream}`, `{username}`, `{password}`, `{id}` und `{name}`. Die Streamname-Regel unterstützt `{id}`, `{name}` und `{server_id}`.

## Bedienung der Wall

- **Doppelklick auf ein Kamerabild:** Grid-Position auf dem zugehörigen Monitor als Vollbild anzeigen oder wieder schließen
- **Esc:** Vollbild schließen
- **Alt halten, Feldnummer eingeben, Alt loslassen:** nummerierte Grid-Position als Vollbild öffnen oder schließen
- **Strg+Alt+Ende:** lokale Openbox-Sitzung beenden

Die Feldnummer steht dezent oben links im Kamerabild. Während des Vollbilds pausiert der Kamerawechsel dieser Position; die laufenden Streams bleiben für eine schnelle Rückkehr zum Grid erhalten.

## Multiserver und Stream-Wiederherstellung

ZM Wall verknüpft `Monitor.ServerId` mit `/api/servers.json` und verwendet den jeweiligen Server-Hostnamen als RTSP-Ziel. Die zuletzt erfolgreich aufgelöste IPv4-Adresse wird als automatischer Fallback gespeichert. Zusätzlich sind eine Fallback-IP je Server sowie ein individueller RTSP-Host oder Streamname je Kamera möglich.

Abgebrochene oder vorübergehend nicht erreichbare Streams werden automatisch neu gestartet. Meldet ein erreichbarer ZoneMinder-Restream ausdrücklich `404 Stream Not Found`, kann ZM Wall die RTSP-Registrierung des betroffenen Monitors über die ZoneMinder-API reparieren. Netzwerk-, Anmelde- und Decoderfehler verändern keine ZoneMinder-Einstellung.

## Diagnose und Betrieb

Die Diagnoseseite bietet:

- Einzelprüfung eines Streams und seines Hardwaredecoders
- sequenzielle Prüfung aller aktivierten Kameras
- Vergleich der tatsächlichen Streamauflösung mit der ZoneMinder-Konfiguration
- kontrollierte Übernahme einer bestätigten Auflösung nach ZoneMinder
- erneute RTSP-Registrierung mit temporären berechtigten Zugangsdaten
- LAN-/WLAN-Status, IPv4-Adresse, Gateway, Linkgeschwindigkeit und WLAN-Details
- bereinigte Berichte ohne RTSP-Adressen oder Zugangsdaten

Wichtige Pfade:

```text
/opt/zmwall/                       Programm
/etc/zmwall.env                    Laufzeitkonfiguration
/var/lib/zmwall/zmwall.db          Konfiguration und Layouts
/var/lib/zmwall/zmwall.log         Programm- und Player-Log
/var/lib/zmwall/update.log         Update-Protokoll
```

Displays prüfen:

```bash
sudo -u zmwall DISPLAY=:0 xrandr --query
```

Log beobachten:

```bash
sudo tail -f /var/lib/zmwall/zmwall.log
```

## Lokales HTTPS

Nginx stellt die Weboberfläche auf Port 443 bereit; der Python-Webdienst bleibt auf `127.0.0.1:8080` beschränkt. Der Installer erzeugt eine lokale CA und ein automatisch erneuertes Serverzertifikat. Die öffentliche CA kann auf Verwaltungsgeräten einmalig als vertrauenswürdig eingerichtet werden:

```text
https://IP-DES-ANZEIGERECHNERS/zmwall-local-ca.crt
```

Der private CA-Schlüssel unter `/etc/zmwall/tls/zmwall-local-ca.key` darf den Anzeigerechner nicht verlassen.

## Aktualisierung

Über die Schaltfläche in der Kopfzeile kann jederzeit nach Aktualisierungen gesucht und ein verfügbares Fast-Forward-Update installiert werden. Alternativ:

```bash
sudo /opt/zmwall/update.sh
```

Konfiguration, Datenbank und Zertifikate bleiben erhalten. Lokale Änderungen an verwalteten Programmdateien führen zum Abbruch, statt überschrieben zu werden.

## Sicherheit

- ZM Wall sollte nur in einem vertrauenswürdigen LAN oder Verwaltungs-VLAN betrieben werden.
- Nach der ersten Synchronisierung werden Anmeldedaten direkt gegen ZoneMinder geprüft; es existiert kein separates Webkennwort.
- API- und RTSP-Zugangsdaten liegen geschützt in `/var/lib/zmwall/zmwall.db`.
- Kennworthaltige RTSP-URLs erscheinen weder in Prozessargumenten noch in Diagnoseberichten.
- Empfohlen ist ein eigener ZoneMinder-Benutzer mit den minimal erforderlichen Rechten.

## Deinstallation

```bash
sudo bash /opt/zmwall/uninstall.sh
```

Die Deinstallation entfernt Programm und Autostart, lässt `/var/lib/zmwall` als Sicherung bestehen.
