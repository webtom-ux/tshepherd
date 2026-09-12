# TShepherd

Live-Terminalübersicht der eigenen Firstmate-Worker – in einem normalen Herdr-Tab.
Kompakte farbige Zählerblöcke, eingerückte Projektgruppen und bündige Worker-Zeilen
mit letzter bekannter Aktivität und bewusstem Wechsel zum ausgewählten Worker.
**Firstmate selbst steht fest darüber und ist ebenfalls per Enter erreichbar.**
Keine zweite Aufgabenverwaltung.

## Vorschau

![TShepherd mit fünf Beispiel-Workern in Atlas und Harbor](docs/images/tshepherd-preview.png)

Illustrative, vollständig synthetische Beispieldaten — keine echten Worker oder
privaten Flottendaten. Die Ansicht wurde aus dem tatsächlichen curses-Fenster
aufgenommen; Schrift und Palette können je nach Terminal abweichen.

## Start

Benötigt: **Python 3.9+ mit curses**, Firstmate mit `fm-fleet-snapshot.v1`, dessen
Abhängigkeiten (insbesondere Bash und jq) sowie einen zum Server passenden Herdr-CLI.
Die Herdr-Abfragen wurden mit **0.9.0 / Protokoll 22** geprüft. Ältere oder abweichende
Antwortformen können `unknown` ergeben. Keine zusätzlichen Python-Pakete nötig.

Im ausgecheckten Projekt, innerhalb eines Herdr-Terminaltabs:

```sh
python3 tshepherd.py --fm-home /pfad/zum/firstmate-home \
  --firstmate-root /pfad/zum/firstmate-code
```

`FM_HOME` (operative Daten) und Firstmate-Code können getrennt liegen. Beide müssen
explizit über die Optionen oder `TSHEPHERD_FM_HOME` und
`TSHEPHERD_FIRSTMATE_ROOT` gesetzt werden. Geerbte `FM_*`-Overrides werden beim
Snapshot-Aufruf entfernt, damit sie nicht unbemerkt ein anderes Home auswählen.
`--herdr /pfad/zu/herdr` wählt bei mehreren installierten Clients den passenden aus.
Es wird nichts global installiert; Herdr wird weder gestartet noch gestoppt.

## Bedienung und Zustände

- **↑/↓ oder j/k**: Firstmate oder Worker wählen; die Auswahl bleibt an Identität
  und Generation gebunden. Der feste Eintrag **◆ Firstmate** bleibt über den
  Worker-Gruppen sichtbar, zählt aber weder als Worker noch als Aufgabe.
  Verschwindet der gewählte Worker, muss ein anderer ausdrücklich gewählt werden,
  auch wenn der Snapshot zwischenzeitlich leer war.
- **Enter**: Auswahl erneut prüfen, genau diesen Herdr-Agent fokussieren und
  zum zugehörigen Tab wechseln.
  Auch während einer Hintergrundmessung wird Enter für eine gültige Auswahl
  sofort angenommen; eine bereits laufende Fokusprüfung verhindert einen zweiten
  Auftrag. Kein automatischer Fokus.
- **R**: Firstmate-/Herdr-Zuordnung jetzt erneut lesen, ohne Worker oder Dashboard
  neu zu starten. Ein bereits laufender Abruf übernimmt die Neuerkennung;
  wiederholtes Drücken stellt keine zusätzlichen Abfragen in eine Warteschlange.
- **q oder Ctrl+C**: beenden, Terminal wiederherstellen.
- Resize wird automatisch berücksichtigt. Ab 78 Spalten steht jeder Worker auf einer
  kompakten Zeile; darunter wird gestapelt. Unter 28 Spalten oder 16 Zeilen erscheint
  ein Hinweis statt einer unlesbaren Tabelle.

| Anzeige | Bedeutung |
| --- | --- |
| `working` | Bestätigte native Herdr-Registrierung meldet `working`. |
| `waiting` | Native Registrierung meldet `blocked` (z. B. Interaktion nötig). |
| `idle` | Native Registrierung meldet `idle`; **kein Beweis**, dass die Aufgabe ruht. |
| `completed` | Separater Zähler für frisch gelieferten Aufgabenstatus `done`. |
| `unknown` | Keine aktuelle, bestätigte Zuordnung zu `working`, `waiting` oder `idle`; auch bei nativem `done`. |

**Live-Aktivität und Aufgabe sind getrennte Spalten.** Ein idle Worker kann eine
abgeschlossene, pausierte oder unbekannte Aufgabe haben. `completed` überlappt daher
mit den Live-Zählern; nicht alle fünf Zähler addieren. Aufgaben behalten die
Firstmate-Unterscheidungen `working`, `parked`, `blocked`, `paused`, `done`, `failed`
und `unknown`. `done` bedeutet nicht zwingend gemergt. Ein natives `done` ohne klare
Idle-Aussage wird nicht als idle umgedeutet. Trotzdem kann Enter einen erneut
bestätigten Worker mit nativem `done` fokussieren: `unknown` beschreibt die
Live-Aktivität, nicht allein die Erreichbarkeit des Workers.

Die Zähler zählen bestätigte Beobachtungen, nicht vermutete Abwesenheit. Vor der ersten
Messung steht `?`; ausgefallene oder veraltete Messungen werden `unknown`. Ein
frisch bekannter Aufgabenabschluss kann neben unbekannter nativer Aktivität stehen.
Bei Snapshot-Ausfall bleiben alte Zeilen zur Orientierung sichtbar, aber ihre
aktuellen Live-/Aufgabenwerte werden unbekannt. Alter des letzten erfolgreichen
Abrufs und Fehler stehen in der Ansicht.

Firstmates Live-Zustand nutzt dieselben Farben wie Worker, weiterhin mit lesbarem
Zustandswort und Auswahlmarker. Nach 30 s durchgehendem `unknown` wird derselbe
read-only Abruf wie bei **R** angefordert, höchstens einmal je 60 s insgesamt.
Das normale Polling liest bereits bei jedem Durchlauf den Snapshot, den aktuellen
Firstmate-Owner und die exakt dort gebundenen nativen Endpunkte neu; es gibt keinen
zusätzlichen Zuordnungscache zum Löschen. **R** verkürzt nur die Wartezeit bis zum
nächsten Abruf. Ändert sich ein zuvor bestätigtes physisches Auswahlziel, ist eine
bewusste Neuauswahl nötig, auch nach zwischenzeitlich fehlendem Prozessbeleg.

`unknown` bleibt mit Grund bestehen, wenn etwa nur eine Shell sichtbar ist,
Provider/Pane nicht zusammenpassen oder Quellen unlesbar sind. Zugriff bzw.
Firstmate-Metadaten und Herdr-Registrierung prüfen; automatische Wiederherstellung
unzugänglicher Quellen wird nicht versprochen. Natives `done` wird ausdrücklich als
beendet ohne Live-Aussage erklärt, nicht als arbeitend/idle erfunden. Kein Neustart,
keine Nachricht an Agenten und kein Eingriff in Firstmates autoritativen Zustand.

## Quelle und Grenzen

- Firstmate-Identität wird in dieser Version **nur auf macOS** geprüft:
  aus `<FM_HOME>/state/.lock`, der aktuellen Owner-Prozessgeneration und dessen
  injizierter Herdr-Identität. Der ausgewählte Owner muss zur exakt nativ
  bestätigten Pane-Shell gehören. Firstmates bestehende read-only Harnessprüfung
  (`bin/fm-session-lock-lib.sh`) bleibt maßgeblich. Keine Titel-/Namenssuche und
  keine Ableitung aus dem eigenen TShepherd-Tab. Fehlende, mehrdeutige, veraltete
  oder unlesbare Bindung sowie andere Betriebssysteme zeigen **nicht verfügbar**;
  Enter wählt dafür keinen Ersatz. Details und nicht-atomare Grenzen:
  [Primärer Chat](docs/design.md#primärer-chat).
- Worker-Inventar ausschließlich aus `bin/fm-fleet-snapshot.sh --json` im gewählten
  Firstmate-Code-Root, mit explizitem `FM_HOME`. Enter liest zur aktuellen
  Eigentumsprüfung nur die exakt im frischen Snapshot gebundene lokale `.meta`-Datei;
  daraus werden weder Inventar noch Aufgabenstatus abgeleitet. Vertrag und Grenzen:
  [Fokuslatenz](docs/focus-latency.md). Keine eigenen Statuslog-Parser,
  Transkripte, Modelle, Aufgabenpersistenz oder Hintergrund-Scheduler.
- Nur Metadaten-Worker **dieses Homes**. Secondmate-Kinder werden nicht rekursiv
  eingesammelt; entfernte und andere Backend-Endpunkte bleiben nativ unbekannt.
  Queued-/Done-Backlog ohne Worker-Metadaten wird nicht als Worker erfunden.
- Projekt bevorzugt `task.backlog.repo`, sonst `task.project`. Titel aus
  `task.backlog.title`, sonst ID. Aktivität aus `current_state.detail`, ersatzweise
  ausdrücklich historische `paths.status_log.last_event.note`. Das ist die letzte
  gelieferte Information, keine behauptete Echtzeit-Zusammenfassung.
- Zusätzliche begrenzte Herdr-Leseabfragen nur für exakt diese lokalen Endpunkte:
  `status`, `pane get`, `agent get`, `pane process-info`. Keine Session-/Pane-Suche.
  Session, Pane, Provider und physische IDs müssen zusammenpassen. Herdrs reservierte
  `default`-Session wird nur beim expliziten Ziel `default` als **vorhandenes** JSON-
  `null` in Client und Server erkannt; fehlende Felder oder ein widersprüchlicher
  Socket-Namespace reichen nicht. Großbuchstaben-IDs wie `wA:p2` sind gültige
  Herdr-Base32-Handles, keine dezimalen Zeilennummern. Shell-only oder
  unlesbare Prozessinformation macht eine möglicherweise alte Registrierung unbekannt.
  Nicht-Shell-Vordergrund ist nur ein Plausibilitätsbeleg, keine semantische
  Busy-Erkennung: Herdr kann während eines langen Tools weiterhin native idle melden.
- Fokus nutzt `agent focus <pane-id> --session <session>` und danach
  `tab focus <tab-id> --session <session>` aus derselben erneut geprüften physischen
  Zielidentität, keine Labels oder Shell-Interpolation. Herdr projiziert den
  Tab-Fokus auf die angeschlossenen Clients dieser Session, nicht gezielt auf ein
  einzelnes OS-Fenster. Der Footer bestätigt nur den abschließend geprüften
  Server-Zustand, keine beobachtete Client-Darstellung oder OS-Aktivierung.
  Scheitert die zweite Stufe, wird der bereits erfolgte Agent-Fokus als Teilerfolg
  benannt; es gibt keinen automatischen Rücksprung. Ein verschwundener, ersetzter, fremder oder unbestätigter Worker
  wird abgelehnt. Zwischen letzter Prüfung und CLI-Aktion bleibt ein unvermeidbares
  Rennen; Herdr bietet dafür keine atomare Generation-Prüfung.
- Standard: 5 s Pause **nach** einem Abruf; Snapshot-Timeout 20 s; native Messungen
  insgesamt 12 s mit höchstens vier parallelen Lesern und 3 s je CLI-Aufruf.
  Messungen gelten höchstens 45 s als frisch. Aufbau des Hintergrundabrufs:
  [Design](docs/design.md#umsetzung). Herdr-CLI, Identitätsprüfungen und
  Client-Rendering benötigen weiterhin Zeit; ein buchstäblich latenzfreier Wechsel
  wird nicht versprochen. Messungen und offene Abnahme:
  [Fokuslatenz](docs/focus-latency.md#nachprüfung-und-akzeptierte-restlatenz).
- Keine Telemetrie, Webdienste oder Steueraktionen über den expliziten Fokus hinaus.
  Firstmates eigener Snapshot kann seinen dokumentierten Beobachtungscache
  aktualisieren; TShepherd schreibt keine Aufgaben- oder Flottendaten.

## Prüfen

```sh
make check
```

Das führt Standardbibliothekstests einschließlich echter POSIX-PTYs aus, ohne
Herdr oder die echte Flotte anzufassen. Mocktests beweisen **keinen** echten Fokus.
Der separate, opt-in Live-Test verwendet ausschließlich Firstmates isolierten Lab-Helper:

```sh
HERDR_LAB_HELPER=/pfad/zum/firstmate-code/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh
HERDR_LAB_HELPER=/pfad/zum/firstmate-code/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --client
# macOS: echte Client-Navigation zum synthetischen Firstmate-Owner
HERDR_LAB_HELPER=/pfad/zum/firstmate-code/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --primary-client
```

Alle Lifecycle-Aktionen liegen beim Helper; er prüft die unveränderte Default-Session
beim Teardown. Die synthetischen Registrierungen im Lab sind keine echten KI-Agenten.
Details: [Anforderungen/Design](docs/design.md), [Verifikation](docs/verification.md).
