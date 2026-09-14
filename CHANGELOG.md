# Änderungsverlauf

**Deutsch** · [English](CHANGELOG.en.md)

Dieses Changelog dokumentiert die Entwicklung von ZM Wall mit Funktionen, Betriebsabläufen, technischen Entscheidungen und Fehlerbehebungen. Die neuesten Änderungen stehen zuerst. Versionsnummern vor `0.3.0` waren schnelle Beta-Zwischenstände während der Entwicklung und wurden nicht als separate GitHub-Releases markiert.

## Unveröffentlicht

- Noch keine Änderungen.

## 0.3.0-beta.8 – 2026-09-14

### Behoben

- Wenn eine alte GPU ihre praktische Grenze gleichzeitig nutzbarer Decoder erreicht, blieb ein erzwungener VAAPI-Player bislang unbegrenzt ohne stabilen Frame und wurde in der Weboberfläche nur mit `…` angezeigt.
- Ein Hardware-Upgrade wird jetzt nach 30 Sekunden ohne bestätigte GPU-Decodierung kontrolliert beendet. Bei einem vorhandenen sichtbaren CPU-Player bleibt dieser ohne Bildunterbrechung aktiv; nach einem direkten Start mit gespeicherter GPU-Strategie wird gezielt ein Softwaredecoder gestartet.
- Kapazitätsabhängige CPU-Rückfälle werden nicht dauerhaft gespeichert, damit der Stream bei einem kleineren Layout oder auf anderer Hardware erneut die GPU nutzen kann.

### Tests

- Abdeckung für den Timeout eines GPU-Upgrades, den Erhalt des sichtbaren CPU-Players und den direkten Software-Fallback nach einem blockierten gespeicherten Hardwarestart.

## 0.3.0-beta.7 – 2026-09-14

### Verbessert

- Intel-H.264-Baseline-Streams überspringen nach einem eindeutigen CPU-Ergebnis den bereits als ungeeignet bekannten `auto-copy`-Zwischenschritt und wechseln direkt zur bestätigten VAAPI-Kompatibilitätsstrategie.
- Es werden höchstens zwei Decoder-Upgrades gleichzeitig vorgepuffert. Dadurch erzeugt ein großes Grid nicht mehr zeitweise einen Ersatzprozess für jede Position und überlastet alte CPUs und GPUs während der automatischen Erkennung.
- Erfolgreiche Decoderstrategien werden pro Stream und GPU-Modell in der lokalen Datenbank gespeichert. Nach einem ZM-Wall-Update oder Neustart beginnt ein bekannter Stream direkt mit seiner zuletzt bestätigten Hardwarekonfiguration.

### Tests

- Abdeckung für die verkürzte Intel-Baseline-Kette, hardwarebezogene Persistenz und die Begrenzung gleichzeitig laufender Decoder-Upgrades.

## 0.3.0-beta.6 – 2026-09-14

### Behoben

- Ein vorübergehender IPC-Timeout lieferte für `hwdec-current` den Zustand `unknown`. Dieser wurde fälschlich als CPU-Decoding gewertet, wodurch ein bereits bestätigter `vaapi-copy`-Player verworfen und die Decoderkette unnötig fortgesetzt wurde.
- Eine einmal bestätigte GPU-Decodierung bleibt jetzt bei einer vorübergehend unbekannten Statusabfrage erhalten. Nur die eindeutige mpv-Rückmeldung `hwdec=no` darf einen weiteren Decoder-Versuch auslösen.
- Ein unbekannter Decoderzustand wird in der Weboberfläche nicht mehr irreführend als CPU angezeigt.

### Diagnose und Tests

- First-Frame-Ereignisse protokollieren jetzt den effektiv beibehaltenen und den aktuell von mpv gemeldeten Decoderzustand getrennt.
- Regressionstests decken den Erhalt einer bestätigten GPU sowie einen noch unbekannten Decoderstatus ab.

## 0.3.0-beta.5 – 2026-09-14

### Behoben

- Die Streamdiagnose konnte betroffene Intel-Streams per `vaapi-copy` wiedergeben, während der normale Player nach einzelnen fehlerhaften Referenzbildern still auf CPU-Decoding zurückfiel. Die bestätigte VAAPI-Kompatibilitätsstrategie deaktiviert diesen automatischen Software-Fallback jetzt ebenfalls.
- Betroffene H.264-Streams mit widersprüchlicher Profilangabe bleiben dadurch auch im regulären Wall-Betrieb auf der GPU. Normale Streams und andere Hardware behalten ihre bisherige sichere Fallbackkette.

### Tests

- Regressionstests stellen sicher, dass die Kompatibilitätsoptionen in der final wirksamen Reihenfolge stehen und in diesem gezielten Modus kein stiller CPU-Fallback mehr erfolgt.

## 0.3.0-beta.4 – 2026-09-14

### Hinzugefügt

- Der Status unter **Anzeige aktiv** zeigt live alle aktiven physischen LAN- und WLAN-Verbindungen einschließlich Interface-Namen an. Sind beide Wege verbunden, werden beide dargestellt.
- Die Streamdiagnose enthält jetzt pro aktiver Verbindung Typ, Interface, IPv4-Adresse, Gateway, Linkgeschwindigkeit und Kennzeichnung der Standardroute. Bei WLAN werden zusätzlich – soweit vom System bereitgestellt – SSID, Signalstärke und TX-Bitrate ausgegeben.
- Virtuelle Netze wie Docker-Bridges werden ohne eigene Standardroute nicht als aktive Geräteverbindung gemeldet.

### Tests

- Abdeckung für gleichzeitiges LAN/WLAN, das Ausblenden virtueller Interfaces und die formatierten Netzwerkdetails im Diagnosebericht.

## 0.3.0-beta.3 – 2026-09-14

### Dokumentation

- Vollständiges, chronologisch rückwärts aufgebautes Changelog für alle versionierten Betastände und die initiale Entwicklungsphase angelegt.
- Funktionen, Betriebsabläufe, Fehlerursachen, Korrekturen, Sicherheitsentscheidungen, Tests und zurückgenommene Versuche werden getrennt dokumentiert.
- Deutsche und englische Fassungen sind gegenseitig verlinkt und aus der jeweiligen README erreichbar.

## 0.3.0-beta.2 – 2026-09-14

### Behoben

- Kameras konnten nach einer gespeicherten Layoutänderung vorübergehend an ihrer alten und neuen Grid-Position erscheinen.
- Ursache war die für normale Rotationen gewünschte Übergabelogik: Das alte Bild blieb sichtbar, bis der Ersatzstream bereit war. Bei einer verschobenen Kamera machte diese Logik die alte Zuordnung jedoch fälschlich weiter sichtbar.
- Layoutänderungen, Rasteränderungen und gelöschte Displays verwerfen jetzt alle Player, Preloads und X11-Flächen des vorherigen Layouts, bevor die neue Belegung gestartet wird.
- Eine zusätzliche Laufzeitprüfung beendet einen veralteten Player, sobald derselbe Stream laut aktueller Konfiguration einer anderen Grid-Position gehört.

### Ablauf

- **Layout speichern:** alter Playerbestand wird vollständig beendet → alte Containerflächen werden entfernt → neue Belegung wird aus der Datenbank gelesen und gestartet.
- **Normale Rotation:** der bisherige Stream bleibt weiterhin sichtbar, bis der vorgepufferte Nachfolger stabile Frames liefert. Der unterbrechungsfreie Wechsel bleibt damit erhalten.

### Tests

- Regressionstest für das Vertauschen zweier bereits belegter Grid-Positionen.
- Regressionstest für die eindeutige Laufzeit-Zuordnung eines Streams zu genau einer Position.

## 0.3.0-beta.1 – 2026-09-12

### Hinzugefügt

- Vollständige deutsche und englische Weboberfläche.
- Auswahl **Systemsprache**, **Deutsch** oder **English** in der Kopfzeile.
- Ohne manuelle Auswahl wird die vom Browser übermittelte bevorzugte Sprache verwendet; eine explizite Auswahl wird ein Jahr lang im Browser gespeichert.
- Zentrale, abhängigkeitsfreie Übersetzungsschicht für Templates, Flask-Rückmeldungen, Updatezustände sowie dynamische JavaScript-Texte.
- Englische Projektdokumentation in `README.en.md` und gegenseitige Sprachlinks in beiden READMEs.
- Ausdrückliche Dokumentation, dass ZM Wall ZoneMinders integrierte RTSP-Restream-Funktion verwendet und keine zusätzlichen direkten Kameraverbindungen öffnet.

### Geändert

- Update-, Diagnose-, Layout-, ZoneMinder- und Decodertexte werden entsprechend der gewählten Sprache ausgeliefert.
- Die Suchfunktion verwendet für die Kleinschreibung die aktive Dokumentsprache.

### Tests

- Gleiche Schlüsselmenge für den deutschen und englischen Übersetzungskatalog.
- Prüfung der automatischen Sprachwahl, manuellen Überschreibung und formatierten Rückmeldungen.

## 0.3.0-beta – 2026-09-12

### Meilenstein

- Erster zusammenhängender Beta-Meilenstein mit stabiler Grid-Verwaltung, Rotation ohne schwarze Zwischenbilder, Stream-Preloading, automatischer Decoderwahl, CPU-/GPU-Anzeige, Webdiagnose und bestätigten Webupdates.
- Versionslinie von `0.2.0-beta.*` auf `0.3.0-beta` angehoben.

## 0.2.0-beta.24 – 2026-09-12

### Behoben

- Bestimmte H.264-Baseline-Streams der Testkamera wurden von FFmpeg mit `Codec h264 profile 66 not supported for hardware decode` abgelehnt, obwohl der Intel-iHD-Treiber den Stream dekodieren konnte.

### Geändert

- Intel-Systeme erhalten nach den sicheren Strategien `auto` und `auto-copy` den zusätzlichen Fallback `vaapi-copy` mit deaktivierter FFmpeg-Hardwareprofilprüfung.
- Der erzwungene Profil-Fallback wird nur auf erkannter Intel-Hardware und erst nach dem Scheitern normaler Methoden verwendet.
- Der alte `i965`-Treiber bleibt nachgeordnet, weil der Diagnosetest dort reale Slice-/Referenzbildfehler zeigte.
- Der Fallback wird pro Stream ausgewählt; andere Kameras und andere Hardwareplattformen bleiben unbeeinflusst.

## 0.2.0-beta.23 – 2026-09-12

### Hinzugefügt

- Zusätzlicher isolierter Diagnosedurchlauf mit `--vd-lavc-check-hw-profile=no`.
- Vergleich zwischen normaler VAAPI-Profilprüfung und bewusst deaktivierter Profilprüfung für Systemtreiber und `i965`.

### Sicherheit

- Der Test deaktiviert Software-Fallback, verändert keine Kameraeinstellungen und speichert keine Decoderstrategie.
- Zugangsdaten und vollständige RTSP-URL werden weiterhin aus dem Bericht entfernt.

## 0.2.0-beta.22 – 2026-09-12

### Hinzugefügt

- Geschützte Diagnoseseite direkt in der Weboberfläche.
- Kamerawahl, Start der Streamdiagnose, Fortschrittsanzeige, Kopieren der bereinigten Ausgabe und Download als Logdatei.
- Kleiner Link zur Diagnose unmittelbar unter der Versionsnummer.

### Ablauf

- Die Diagnose öffnet für 30 Frames eine zusätzliche schreibgeschützte RTSP-Verbindung.
- Gleichzeitig kann nur eine Diagnose laufen; der normale Anzeigebetrieb und die Konfiguration werden nicht verändert.

## 0.2.0-beta.21 – 2026-09-12

### Hinzugefügt

- Kommandozeilenwerkzeug `diagnose-stream.py` zur isolierten Hardwaredecoderprüfung eines konfigurierten Kamerastreams.
- Prüfung des System-VAAPI-Treibers und, falls vorhanden, des Intel-Legacy-Treibers `i965` ohne Software-Fallback.
- Bericht enthält System, ZM-Wall-Version, mpv-Version, CPU, GPU, Kamera, Decoderprofil und Ergebniscode.

### Sicherheit

- Die kennworthaltige URL wird über stdin an mpv übergeben.
- URL, Benutzername und Kennwort werden nochmals aus der Diagnoseausgabe entfernt.

## 0.2.0-beta.20 – 2026-09-12

### Geändert

- Jede Display-Karte zeigt dauerhaft die erkannte CPU und GPU mit lesbarer Modellbezeichnung, unabhängig von der gerade verwendeten Decoderart.
- Die tatsächliche Decoderart wird ausschließlich pro Kamerastream dargestellt, weil ein Monitor gleichzeitig CPU- und GPU-Streams enthalten kann.
- Zustände wurden präzisiert: `wartet`, `puffert`, `CPU · puffert`, `GPU · puffert`, `CPU` und `GPU`.

### Ablauf

- `wartet` bedeutet, dass für die Kamera kein Player läuft und daher keine zusätzliche Decoderlast entsteht.
- Ein Preload läuft nur im fünfsekündigen Vorabfenster und wird ausdrücklich als puffender Stream markiert.

## 0.2.0-beta.19 – 2026-09-12

### Hinzugefügt

- Decoderbadge direkt an jeder zugeordneten Kamera im Grid.
- Aktive Kamera zeigt `CPU` oder `GPU`; nicht laufende Rotationskameras zeigen `wartet`.
- Tooltips nennen bei GPU-Decoding das erkannte Modell und die aktive mpv-Hardwaremethode.

## 0.2.0-beta.18 – 2026-09-12

### Hinzugefügt

- Hardware- und treiberabhängige Decoderstrategie statt statischer Intel-Konfiguration.
- Automatische Erkennung lesbarer CPU-/GPU-Modellnamen.
- Auf Intel-Systemen werden `i965`-Strategien nur ergänzt, wenn die passende Treiberdatei tatsächlich installiert ist.

### Decoderreihenfolge

1. mpv `auto`
2. mpv `auto-copy`
3. installierte, hardwareabhängige Fallbacks
4. CPU-Decoding als zuverlässiger letzter Rückfall

### Behoben

- AMD-, NVIDIA- und andere Systeme erhalten keine Intel-spezifischen VAAPI-Optionen mehr.

## 0.2.0-beta.17 – 2026-09-12

### Geändert

- `auto-copy` wurde zu einem eigenen zweiten Startversuch pro Stream.
- Erkennt ZM Wall beim ersten Frame Software-Decoding, wird nur dieser Stream verdeckt neu aufgebaut.
- Das aktuelle Bild bleibt sichtbar, bis der Copy-Versuch stabile Frames liefert.
- Erfolglose Strategien werden für denselben Lauf nicht endlos wiederholt.

## 0.2.0-beta.16 – 2026-09-12

### Hinzugefügt

- Liveanzeige des Decoderzustands je physischem Monitor: CPU, GPU, gemischt, wird ermittelt oder inaktiv.
- Lesbare CPU- und GPU-Bezeichnungen statt kryptischer PCI-Ausgaben.
- JSON-Laufzeitstatus für die Weboberfläche.

### Geändert

- mpv probiert zunächst direktes Hardware-Decoding und anschließend eine kompatible Copy-Variante.
- Nicht unterstützte Streams fallen weiterhin auf Software-Decoding zurück.

## 0.2.0-beta.15 – 2026-09-12

### Diagnose

- Das Log des ersten Frames enthält nun Kamera, Codec, Codecprofil, Decoder, Auflösung, Pixelformat, Hardwarepixelformat, `hwdec`, Interop, Startzeit und Prüfzeit.
- Dadurch können Streams mit unerwartetem CPU-Decoding identifiziert werden, ohne Zugangsdaten zu protokollieren.

## 0.2.0-beta.14 – 2026-09-12

### Hinzugefügt

- Dauerhaftes, nicht von Openbox verwaltetes X11-Containerfenster für jede Grid-Position.
- Aktiver und vorgepufferter mpv-Player rendern in getrennten Kindflächen desselben Containers.

### Behoben

- Der eigentliche Kamerawechsel erfolgt innerhalb des X-Servers und benötigt keinen Wechsel zwischen eigenständigen Top-Level-Fenstern mehr.
- Schwarze Zwischenbilder durch langsame Openbox-Aktivierung wurden beseitigt.

### Kompatibilität

- Kann der eingebettete X11-Modus nicht initialisiert werden, bleibt die bisherige Top-Level-Fenstersteuerung als Rückfall verfügbar.

## 0.2.0-beta.13 – 2026-09-12

### Diagnose

- Millisekundengenaue Wechselprotokolle für Playerstart, erstes Frame, Hardwaredecoder, Preload-Bereitschaft, Fensteranhebung und Beenden des Vorgängers.
- Kamera-Zugangsdaten werden nicht ausgegeben.

## 0.2.0-beta.12 – 2026-09-12

### Behoben

- Der Updatebereich wird unabhängig vom aktuellen Updatezustand dauerhaft oben in der Kopfzeile angezeigt.
- Auch bei aktuellem Versionsstand ist eine sofortige manuelle Updateprüfung möglich.

## 0.2.0-beta.11 – 2026-09-12

### Hinzugefügt

- Webbasierte Updateprüfung im Fünf-Minuten-Intervall.
- Sichtbarer Hinweis bei verfügbarem Update und Installation erst nach manueller Bestätigung.
- Fortschritts- und Fehlerzustände sowie automatische Wiederverbindung der Seite nach dem kurzen Dienstneustart.

### Ablauf und Sicherheit

- Update nur aus `noxare/ZMWall`, nur auf Branch `main`, nur ohne lokale Änderungen und ausschließlich als Fast-Forward.
- Nur der ZM-Wall-Web-/Player-Prozess wird neu gestartet; Rechner, Xorg und LightDM laufen weiter.
- Ausgabe wird nach `/var/lib/zmwall/update.log` geschrieben.

## 0.2.0-beta.10 – 2026-09-12

### Hinzugefügt

- Sicheres `update.sh` für vorhandene Installationen.
- Prüfung von Rootrechten, Repository-Ursprung, Branch, lokalem Änderungsstand und Fast-Forward-Möglichkeit.
- Aktualisierung der Python-Abhängigkeiten und sauberer Neustart der grafischen ZM-Wall-Sitzung.

### Behoben

- Bootstrap-Ablauf für Installationen, die `update.sh` noch nicht enthalten.
- Übergabe und Prüfung eines erwarteten Ziel-Commits für webgestützte Updates.
- Konfiguration, Zertifikate und Datenbank bleiben beim Update erhalten.

## 0.2.0-beta.9 – 2026-09-12

### Behoben

- Zwei aufeinanderfolgende einsekündige X11-Aktivierungs-Timeouts verursachten ungefähr zwei Sekunden Schwarzbild.
- Der blockierende Aktivierungsaufruf wurde entfernt; X11-Kommandos sind auf 200 ms begrenzt.
- Altes und neues Fenster überlappen 50 ms, bevor der Vorgänger beendet wird.
- Preloads laufen nur noch in den letzten fünf Sekunden vor einem Wechsel und nicht während des gesamten Intervalls.

## 0.2.0-beta.8 – 2026-09-12

### Zurückgenommen

- Der in Beta 7 erzwungene OpenGL-/VAAPI-Copy-Renderer war auf der Testhardware nicht zuverlässig und führte dazu, dass keine Videos mehr sichtbar waren.
- Die erzwungenen Rendereroptionen wurden entfernt; Hardware-Decoding wird wieder kompatibilitätsorientiert ausgewählt.

## 0.2.0-beta.7 – 2026-09-12

### Versuch

- Intel-X11-Wiedergabe wurde versuchsweise auf einen OpenGL-/VAAPI-Copy-Pfad festgelegt, um GPU-Decoding zu erzwingen.
- Dieser Ansatz wurde in Beta 8 wegen fehlender Bildausgabe zurückgenommen.

## 0.2.0-beta.6 – 2026-09-12

### Geändert

- Das vorgepufferte Fenster wird vor der endgültigen Übergabe aktiviert und angehoben.
- Wenn Openbox die Aktivierung verweigert, wird der Vorgänger aus der obersten Ebene genommen und der neue Player erneut angehoben.
- Der alte Player wird nach einer kurzen Präsentationsphase zuverlässig entfernt, damit eine fehlgeschlagene Stapeloperation die Rotation nicht einfriert.

## 0.2.0-beta.5 – 2026-09-12

### Behoben

- Fensteranhebung darf die Rotation nicht unbegrenzt blockieren.
- `xdotool`-Aufrufe erhielten kurze Timeouts und Fehlerpfade; der Wechsel kann auch nach einem Werkzeugfehler weiterlaufen.

## 0.2.0-beta.4 – 2026-09-12

### Versuch

- Einführung dauerhaft laufender, doppelt gepufferter mpv-Fenster für aktive und nächste Kamera.
- Ziel war ein sofortiger Wechsel durch Umschalten der Fensterreihenfolge.

### Erkenntnis

- Dauerhaftes Double-Buffering erhöhte Ressourcenverbrauch und Komplexität. Der Ansatz wurde anschließend schrittweise durch zeitlich begrenztes Preloading und eingebettete X11-Flächen ersetzt.

## 0.2.0-beta.3 – 2026-09-11

### Geändert

- Ein Preload gilt erst als bereit, wenn mpv echte Videoparameter und ein decodiertes Frame meldet.
- Der Stream muss mindestens 0,75 Sekunden stabil Frames liefern.
- Verliert der Preload das Bild, beginnt die Stabilitätsmessung erneut.
- Das bisherige Bild bleibt sichtbar, solange der Nachfolger nicht nachweislich bereit ist.

## 0.2.0-beta.2 – 2026-09-11

### Hinzugefügt

- Verdeckter Parallelstart der nächsten Kamera vor dem Rotationszeitpunkt.
- Eindeutige Player- und Preloadverwaltung je Grid-Position.

### Behoben

- Kamerasuche filtert den Vorrat tatsächlich nach Name, Server und ID.
- Suchzustand bleibt beim Verschieben von Kameras korrekt.
- Installer installiert `xdotool` für den damaligen Fensterübergabeweg.

## 0.2.0-beta.1 – 2026-09-11

### Hinzugefügt

- Mehrere Kameras pro Grid-Position mit konfigurierbarem Wechselintervall.
- Drag-and-drop-Kameravorrat; zugeordnete Kameras verschwinden aus der verfügbaren Liste.
- Verschieben zwischen Grid-Positionen, Sortierung innerhalb einer Position und Touch-Bedienung durch Antippen.
- Automatische Wiederherstellung abgebrochener oder vorübergehend nicht erreichbarer RTSP-Streams.
- Datenbankmigration von einer Kamera pro Position auf geordnete Mehrfachzuordnungen.
- Serverseitige Validierung verhindert die Zuordnung derselben Kamera zu mehreren Positionen.

### Ablauf

- Der Player-Manager berechnet anhand von monotoner Zeit, Kamerareihenfolge und Wechselintervall die aktive Kamera.
- Änderungen werden atomar gespeichert und ohne vollständigen Systemneustart übernommen.

## Initiale Entwicklungsphase – 2026-09-11

### Grundsystem

- Projektstruktur, MIT-Lizenz, Beispielkonfiguration, Installer, Deinstaller, Python-Anwendung und Tests angelegt.
- Debian-Anzeigegerät mit Xorg, Openbox, LightDM, mpv und automatisch angemeldetem Dienstbenutzer `zmwall`.
- Weboberfläche zur Verwaltung von ZoneMinder-Verbindungen, erkannten Displays, Rastergrößen und Kamerazuordnungen.
- SQLite-Datenbank für Standorte, ZoneMinder-Server, Kameras, Displays und Grids.

### ZoneMinder und RTSP

- Synchronisierung über `/api/monitors.json` und `/api/servers.json`.
- Multiserver-Zuordnung über `Monitor.ServerId`, Serverhostname und gespeicherte Fallback-IP.
- Flexible RTSP-Port-, Streamname- und URL-Regeln sowie Overrides je Kamera.
- Anzeigeauswahl auf Kameras mit aktivierter ZoneMinder-RTSP-Restream-Funktion begrenzt.
- RTSP-Zugangsdaten werden URL-kodiert und die vollständige URL wird über stdin statt über Prozessargumente an mpv übergeben.

### Authentifizierung

- Der erste Ansatz mit lokalem Admin-Kennwort, Bestätigungsprüfung und `pwreset.sh` wurde implementiert und anschließend vollständig entfernt.
- Aktueller Ablauf seit dieser Phase: Erstkonfiguration bleibt bis zum ersten erfolgreichen ZoneMinder-Sync offen; danach prüft die Weboberfläche HTTP-Basic-Zugangsdaten direkt gegen `/api/host/login.json`.
- Bei mehreren ZoneMinder-Verbindungen genügt ein gültiger Benutzer einer erfolgreich synchronisierten Installation.

### Anzeige und Fensterplatzierung

- Korrekte Aufteilung jedes XRandR-Ausgangs in lückenlose Gridzellen, einschließlich Restpixeln und negativer Monitorpositionen.
- mpv wird an den konfigurierten physischen Ausgang gebunden; Seitenverhältnis kann vollständig auf die Gridzelle gestreckt werden.
- Mehrere frühe Platzierungswege wurden vereinheitlicht, nachdem parallele Methoden Fenster außerhalb ihrer vorgesehenen Zellen erzeugen konnten.
- `Strg+Alt+Ende` beendet die Openbox-Sitzung; die letzte Gridposition zeigt dazu einen dezenten Hinweis.

### HTTPS

- Nginx-Frontend auf Port 443 mit Weiterleitung von HTTP auf HTTPS.
- Lokale ZM-Wall-CA mit zehn Jahren Laufzeit und automatisch erneuertem 90-Tage-Serverzertifikat.
- systemd-Timer prüft täglich und erneuert 30 Tage vor Ablauf sowie bei geänderten lokalen IPv4-Adressen.
- Konflikt mit der Nginx-Standardseite im Installer und Deinstaller behoben.

## Pflege dieses Changelogs

- Neue Einträge werden mit der nächsten Versionsnummer oberhalb der älteren Versionen ergänzt.
- Relevante Punkte werden als **Hinzugefügt**, **Geändert**, **Behoben**, **Ablauf**, **Sicherheit**, **Diagnose**, **Tests** oder **Zurückgenommen** gekennzeichnet.
- Verworfene technische Ansätze bleiben dokumentiert, wenn sie spätere Architekturentscheidungen erklären.
