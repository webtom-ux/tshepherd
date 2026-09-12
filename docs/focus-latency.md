# Enter: Latenz und zielbezogener Eigentumsbeleg

## Ursache und Messpunkt

Ausgangspunkt ist der frühere Fokuspfad: Agent-Fokus plus expliziter Tab-Fokus funktionieren.
Die bereits geklärte Client-Projektion wurde nicht erneut als Ursache behandelt.

**Trigger:** Enter auf der ausgewählten Generation.
**Sichtbares Symptom:** späte Zielansicht; während eines Abrufs wird Enter sogar
verworfen und muss wiederholt werden. **Maskierung:** schnelle Snapshot-Fixtures
verbergen den Preis echter Flottenabrufe; API-Fokusflags verbergen die Zeit bis
zur tatsächlichen Client-Projektion.

Der alte Fokuspfad führte vor sichtbarem Tab-Fokus vier vollständige Snapshots
aus, danach zwei weitere. Beim gemessenen echten 32-Zeilen-Snapshot verbrauchten
die ersten vier **23,027 s** von **24,080 s** Eingabe-bis-Zielbild. Jede vollständige
Fokusprüfung las außerdem fünfmal den nativen Zielendpunkt. Der Subprozessrunner
wartete unabhängig vom tatsächlichen Prozessende jeweils in 40-ms-Schritten.
Ein serialisierter Collector lehnte Enter während seiner Arbeit ausdrücklich ab.
Das sind drei getrennte, beobachtete Beiträge; die Snapshot-Arbeit dominiert.

### Echte Client-Messungen

Herdr-Lab auf macOS 26.6.2 arm64; nur benannte, nicht-default Sessions. Derselbe
Beobachter misst mit `time.monotonic()` direkt vor Eingabe in die Client-FIFO und
beim ersten Zielmarker im tatsächlichen Client-PTY-Capture. Keine Differenzbildung
zwischen Prozessuhren. Vor Eingabe wird eine **frische Zielprojektion im Capture**
abgewartet; Marker sind im gestarteten Shell-Kommando nicht zusammenhängend
enthalten. Eine bekannte Eingabe/Antwort kontrolliert denselben Capturepfad.

| Szenario | Main vorher | Korrektur |
| --- | ---: | ---: |
| Kontroll-Echo nach beobachteter Zielbereitschaft | 13 ms | 19 ms |
| Enter → sichtbares Ziel, echter 32-Zeilen-Snapshot | **24,080 s** | **0,696 s** |
| Enter bei ausdrücklich blockiertem Hintergrundabruf | verworfen, kein Auftrag | **0,727 s**, Abruf weiterhin blockiert |
| Anschließende Tastatureingabe vom Ziel quittiert | 26 ms | 19 ms |

Ein eigener Start-/Freigabe-Dateibeleg hält den Testabruf begrenzt an; keine
Schlafdauer dient als angenommener Busy-Zustand. Entfernte, ersetzte, fremde und
unverständliche Zielmetadaten wurden im korrigierten UI per echtem Enter während
dieser Blockade abgelehnt, ohne Zielmarker im Client. Generation/Provider/Session,
physische Ersetzung, Veränderungen zwischen den Mutationen und Stale werden
zusätzlich in den Standardtests und der separaten Client-Regressionssuite geprüft.

Das Inventar besteht aus **32 echten Metadatensätzen im eigenen Lab-Home**, die
bewusst zwei eigene physische Herdr-Endpunkte teilen. Die unveränderte echte
Firstmate-Snapshotimplementierung verarbeitet sie. Es sind nicht 32 unabhängige
KI-Prozesse. Ein testlokaler PATH-Adapter leitet auch deren interne Herdr-Leseaufrufe
an den benannten Helper; keine geteilten Dateien werden geändert. Diese zusätzliche
Adapter-/Helper-Latenz steckt in den Werten; es ist keine Messung der produktiven
Default-Session, der physischen Mac-Tastatur oder eines OS-Fensterwechsels.

Belege unter `.local/` (ignoriert):

- `fm-lab-tshepherd-fast-e-38888-7627`: Main, `latency-before-ready.log/.exit`.
- `fm-lab-tshepherd-fast-e-23342-3672`: Korrektur, `latency-after-ready.log/.exit`.
- Wiederholung `fm-lab-tshepherd-fast-e-88527-8302`,
  `latency-after-final.log/.exit`: **0,695 s** bereit, **0,764 s** bei gehaltenem
  Abruf und **0,716 s während des tatsächlich laufenden Firstmate-Snapshots**.
  Letzterer war beim sichtbaren Wechsel nachweislich noch nicht abgeschlossen.
- Alle drei äußeren Lab-Läufe: Exit **0**, einschließlich Helper-Teardown/Default-Tripwire.
- `measurements.json`, `observer-clock.json`, `observer-events.jsonl`,
  `timings.jsonl`, `client-events.jsonl`, Client-ANSI und Kommandojournal.

### Gegenprobe und widerlegende Befunde

Ein früherer gültiger gemeinsamer Beobachter-Kontrolllauf mit schnellen Fixtures
(`fm-lab-tshepherd-fast-e-85437-15897`) maß 18 ms Echo, 524/529 ms vollständigen
Enter-Wechsel für 2/32 Zeilen und 270 ms für den diagnostischen direkten Pfad:
volle erste Zielprüfung, physisch bestätigter Agent-Fokus, dann direkt Tab-Fokus.
Dieser Gegenversuch lässt nur die zweite komplette Vorprüfung weg; er ist **keine
übernommene Lockerung**. Die Korrektur behält beide Vorprüfungen und die Nachprüfung,
ersetzt aber deren unbeteiligte Flottenarbeit durch aktuellen Zielbeleg.

Dass 32 schnelle Fixture-Zeilen den angenommenen Fokus nicht langsamer machten,
widerspricht einer reinen Sortier-/Rendering- oder Inventarlängenursache im UI.
Der reale Snapshotpfad und die instrumentierten Einzelzeiten erklären dagegen
die mehrsekündige Verzögerung. Eine gehaltene Refresh-Barriere widerlegt außerdem
die Annahme, früheres Busy-Enter sei lediglich langsam angenommen worden: der
Dispatch gab `False` zurück. Jetzt beendet Fokus denselben Versuch **vor** Freigabe.

Fehlläufe bleiben erhalten: `37739-19476` und `71883-13335` mischten
prozesslokale monotone Ursprünge bei der Busy-Korrelation. Plattform-, Prozess-,
Clock-API- und Einheitenbelege des korrigierten Laufs stehen im Evidence-Verzeichnis.
`39042-24156` injizierte sein Kontroll-Echo unmittelbar nach CLI-Tab-Fokus, ohne
sichtbare Client-Bereitschaft. Die Eingabe erschien nicht am Ziel. Mit frischem
Render-Handshake bestanden dieselben Kontrollen vor und nach der Korrektur.
Die damalige Erfassung belegt nicht die genaue innere Reihenfolge von
Client-Projektion und Input; ein Readiness-Rennen ist dafür plausibel, nicht
rückwirkend bewiesen. Keine dieser fehlgeschlagenen Kontrollen begründet eine
akzeptierte Latenzzahl.

### Nachprüfung und akzeptierte Restlatenz

Die gezielte Nachprüfung reproduzierte **1,307 s** während eines echten Refreshs
(0,590 s bereit, 0,859 s bei gehaltenem Refresh). Der bisherige Treiber meldete
auch solche Werte erfolgreich, weil er nur das Erscheinen des Zielmarkers prüfte.
Die vier voneinander unabhängigen nativen Reads jeder Fokusprüfung laufen nun
parallel. Der zwischenzeitlich entfernte abschließende `pane get` in `focus_target`
ist wiederhergestellt: Nach dem Eigentums-Recheck muss die aktuelle physische
Bindung noch mit den Pane-/Agent-Antworten der nativen Prüfung übereinstimmen.
Eine Ersetzung in diesem Zwischenraum verhindert die folgende Mutation; dafür
gibt es eine gezielte Regression vor Agent- und vor Tab-Fokus.
`focus` vergleicht die Bindung außerdem mit der angezeigten Bindung (sofern vorhanden),
der Agent-Fokusantwort sowie den erneuten Prüfungen vor und nach Tab-Fokus.
Die abschließende Agent-Abfrage bestätigt zusätzlich den exakten Fokus.
Collector-Probes behalten ihren bestehenden Pool mit höchstens vier Lesern;
Fokus nutzt separat höchstens vier.

Der erste Nachlauf maß **0,269 s** bereit, **0,331 s** gehalten und **0,418 s**
während des echten Refreshs. Der zunächst eingeführte 100-ms-Grenzwert war nicht
abgestimmt. Für die beobachteten **305–345 ms** wurde als projektspezifische
Abnahmegrenze **345 ms** für jede sichtbare Wechselmessung festgelegt.
Der Live-Treiber verwendet diese Grenze, keine universelle Wahrnehmungs-SLA.
Er sammelt weiterhin auch die Ablehnungsbelege und schlägt bei Überschreitung fehl.
Die finale physische Prüfung wird nicht für eine schnellere Zahl geopfert;
weitere Optimierung in Richtung null oder unter 300 ms ist nicht beauftragt.
Erfolgreiche CLI-Antworten allein bleiben unzureichend als sichtbarer Nachweis.

Finaler gezielter Lauf mit wiederhergestelltem Recheck:
`fm-lab-tshepherd-fast-e-83888-5903`, `.local/final-restored-latency.log/.exit`:
**130 ms** bereit, **167 ms** während gehaltenem Abruf und **324 ms** während
des echten Snapshots. Alle vier UI-Eigentumsablehnungen bestanden; der äußere
Lab-Lauf einschließlich Teardown/Default-Tripwire endete mit Exit **0**.
Zusätzlich bestanden die **24** gezielten Source-/Ownership-/Polling-Tests.
Das ist die finale sichtbare Messung, kein Null-Latenz-Versprechen.

## Zielbezogener Eigentumsbeleg

Das Inventar stammt weiterhin **nur** aus dem validierten strukturierten Snapshot
des expliziten Homes. Die Korrektur fügt keinen Inventar-, Status- oder Logparser
hinzu. Sie ersetzt auf dem bereits geladenen UI-Pfad erneute vollständige
Flottenabrufe durch aktuelle, begrenzte Reads der **einen bereits darin gebundenen
lokalen Metadatendatei**. Ein noch nicht initialisierter direkter `Source.focus`-
Aufrufer behält den bisherigen Snapshotpfad; die explizite Lab-Fixture bleibt ihre
synthetische Eigentumsquelle.

### Autorität, kein geratenes Format

Geprüfte Firstmate-Quellen für den beschriebenen Schnittstellenvertrag:

- `bin/fm-spawn.sh`: schreibt lokale Metadaten mit `window`, `harness`,
  `spawn_gen`; ein nicht-tmux Backend schreibt zusätzlich `backend`.
- `bin/fm-backend.sh`, `fm_meta_get`: **letzter** vollständiger `key=value`-Wert,
  kein Shell-Evaluieren, kein Trimmen; auch die letzte Zeile ohne Newline zählt.
  `fm_backend_of_meta` behandelt fehlendes/leeres Backend als tmux.
  `fm_backend_target_of_meta` verwendet für Herdr `window` (nicht Orcas `terminal`).
- `bin/fm-fleet-snapshot.sh`: verwendet genau diese Getter für Task-Identität und
  `paths.meta`. Nichtleeres `remote_host` kennzeichnet fremde/remote Zuordnung.
  Es bietet `--json` und `--secondmate-home-summary`, **keine** begrenzte
  Zielidentitätsabfrage. Crew-State ist keine Eigentums-/Generationsschnittstelle;
  die internen Selector-Metadatenhelfer suchen im Namespace und werden nicht benutzt.

Der neue Reader liest ausschließlich `spawn_gen`, `backend`, `window`, `harness`
und `remote_host` als Identitätsbeleg. Das Format wird nicht auf Aufgabenstatus,
Titel, Backlog oder Aktivität ausgeweitet. Explizites `backend=herdr` ist erforderlich;
fehlend/leer bleibt unbekannt und wird abgelehnt. Nicht lesbares, nicht UTF-8-
dekodierbares, binäres (NUL) oder widersprüchliches Material kann keinen Fokus
autorisieren. Ein direkter read-only Getter-Kontrolllauf bestätigte letzte Werte
und die letzte Zeile ohne Newline (`.local/meta-parser-control.json`); binäres
Material bleibt unabhängig von Bash-Versionseigenheiten ausdrücklich unbekannt.

### Sicherheitsgrenze

- Der ausgewählte Schlüssel muss im weiterhin frischen letzten vollständigen
  Snapshot vorkommen. Generation, Backend, Endpunkt und Provider bleiben exakt.
- Nur `FM_HOME/state/<snapshot-id>.meta`, mit passendem `paths.meta.path/present`,
  sicherer ID, ohne Symlink-Auflösung aus diesem Pfad. Keine Verzeichnissuche.
- Nur reguläre Dateien, höchstens 64 KiB; nichtblockierendes Öffnen schützt vor
  FIFO-Geräten. Dateistempel/Inode werden vor/nach Lesen und gegen den aktuellen
  Pfad verglichen. Fehlend, ersetzt, fremd oder unverständlich heißt Ablehnung.
- Diese Eigentumsprüfung läuft vor **und nach** den nativen Reads sowie zwischen
  Agent- und Tab-Mutation und nach Tab-Fokus. Keine bloße Cache-Frische autorisiert
  eine Mutation. Unbekannte Layouts werden abgelehnt, nicht still aufgelöst.
- Session/Protokoll, Pane/Provider, Workspace/Tab/Terminal und nicht-Shell-
  Prozessbeleg werden weiterhin frisch geprüft. Auch natives `done` kann eine
  bestätigte physische Bindung haben, ohne als idle zu gelten.
- Die beim Enter-Dispatch angezeigte physische Bindung wird mitgegeben, sofern
  vorhanden; eine inzwischen andere Terminalgeneration wird vor Mutation abgelehnt.
  Ein zweiter Fokusauftrag während laufender Prüfung wird nicht nachträglich oder
  auf eine inzwischen andere Auswahl umgebogen.

Es wird keine bekannte Generation gegen eine lediglich plausibel erreichbare
ersetzt. Der Schutz wird nicht zugunsten optimistischen falschen Fokus entfernt.
Zwischen letzter Prüfung und CLI-Mutation bleibt das bereits dokumentierte
nichtatomare Rennen: Herdr hat hier keinen Compare-and-Focus-Generationsparameter.
Ein langsames/unlesbares lokales Dateisystem oder Herdr kann weiterhin verzögern
oder ablehnen. Die gemessenen Restzeiten sind **nicht null** und keine universelle
SLA. Es gibt keinen neuen Transport, Dienst, globalen Schalter oder Abhängigkeit.

## Wiederholen

```sh
HERDR_LAB_HELPER=/pfad/zu/firstmate/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --latency
```

Der Test benötigt die echte Firstmate-Implementierung neben dem Helper. Nur für
die historische Gegenmessung kann `LATENCY_SOURCE` auf eine separate alte
`tshepherd.py` zeigen, mit `LATENCY_EXPECT_REJECTION=1`. Beide sind ausschließlich
Testoptionen, keine App-Konfiguration. Ein nicht bestätigter Zielmarker beendet
den Test fehlerhaft; API-Erfolg allein genügt nie.
