# Verifikation

## Automatisiert

`make check` führt die Unit-/Integrationssuite und Python-Kompilierung aus. Die
CI wiederholt dies auf macOS und Linux. Kein Test der Standardsuite greift auf
reale Firstmate-Daten oder Herdr-Sessions zu.

Echte PTYs prüfen Resize, Navigation und Beenden während eines langsamen Fetchs.
Nach q und SIGINT werden Echo, kanonische Zeileneingabe, Cursor-Normalisierung und
Alternate-Screen-Austritt überprüft. Ein echtes interaktives `/bin/sh` startet die
TUI mit synthetischen Testdaten, beendet sie per q bzw. terminalgeneriertem Ctrl+C, führt danach ein Kommando
aus und unterbricht anschließend einen neuen `sleep` per Ctrl+C.

Der opt-in Treiber [`tests/status_ui.py`](../tests/status_ui.py) ergänzt Aufnahmen
der echten curses-UI im isolierten PTY für natives `done`, `idle`, ungültige
Provider-Evidenz und veraltete Aufgabendaten bei `done`. Aufruf und Quellengrenze
stehen im Modul-Docstring: Die Antworten sind synthetisch, kein Nachweis realer
Herdr-Zustandswechsel. Der Treiber gehört nicht zu `make check`.

## macOS-Terminaldiagnose

Der erste Restorationstest verglich alle Termios-Bits unmittelbar nach Ende der
Anwendung. Das war für `PENDIN` auf dem geprüften macOS nicht der richtige Zeitpunkt.
`termios(4)` und `sys/termios.h` dokumentieren es als „retype pending input (state)“.

Die minimale Kontrolle ohne Anwendung, curses, Subprozess oder Resize zeigt:

1. Frisches PTY: lokale Flags `0x5cb`.
2. `ICANON`/`ECHO` ausschalten und die ursprünglichen Attribute wieder setzen:
   Flags `0x200005cb`, auch ohne wartenden Text.
3. Ein weiteres `tcsetattr` ändert das nicht.
4. Nach Lesen einer kanonischen Zeile stimmen **alle** Attribute wieder exakt überein.
5. Nur `tcsetattr` ohne Canonical-Übergang erzeugt diesen Unterschied nicht.

Der Trigger ist der Übergang zur kanonischen Eingabe; der Vergleichszeitpunkt
verdeckt oder zeigt den transienten Kernelzustand. Es gab keinen reproduzierten
benutzersichtbaren Eingabedefekt. Die Regression maskiert keine Bits: Sie prüft
zuerst Echo/Canonical/Signals, tatsächliches Blockieren bis zum Zeilenende und den
empfangenen Text; anschließend fordert sie vollständige Attributgleichheit.
Der wirkungslose zusätzliche Restore-Versuch im Anwendungscode wurde entfernt.

Eine unabhängige Shell-Testhängeursache lag im Cleanup, nicht in TShepherd:
Nach erfolgreichem Shell-Test wartete `waitpid` auf die getötete eigene Shell,
bevor deren PTY-Master geschlossen wurde. Die Shell blieb in macOS-Prozessstatus
`?Es` (Exit-Pfad). In der fokussierten Kontrolle ließ **nur das Schließen desselben
noch offenen Master-FDs** denselben PID unmittelbar reapen. Der minimalere Shell-
Test ohne vorangegangene App-/Job-Control-Interaktion zeigte den Hänger nicht;
Capture oder Testreihenfolge allein waren keine hinreichende Erklärung.

Cleanup schließt jetzt den eigenen Master vor dem begrenzten `WNOHANG`-Reap.
Die vollständige Suite und fünf Wiederholungen des echten Shell-Szenarios im
Capture-Modus liefen danach erfolgreich. Alle Signale und Waits betreffen nur
von diesem Test gestartete Prozesse, keine fremden Gruppen.

## Isolierter Herdr-Live-Test

Geprüft auf macOS mit Herdr **0.9.0, Protokoll 22**, über
`tests/herdr-lab.sh` und Firstmates offiziellen Lab-Helper:

- Generierte nicht-default Session, angehängter realer Vordergrund-Viewer.
- Synthetische Pi-Registrierung über einem schlafenden Python-Prozess; native
  `idle`, `working` und `blocked` wurden tatsächlich über Herdr gemessen.
- Aufgabe `done` gleichzeitig mit nativem `idle`.
- `Source.focus` und anschließend Enter in der **wirklich im Herdr-Pane laufenden
  curses-Anwendung** bestätigten serverseitig das erwartete Worker-Pane.
  Dieser ursprüngliche Test allein bewies keinen sichtbaren Client-Wechsel.
- Öffnen/Refresh allein änderte den Fokus nicht.
- Ctrl+C beendete die TUI; der Pane-Vordergrund kehrte zur Shell zurück.
- Guarded Teardown erfolgreich, unveränderte Default-Session laut Helper-Tripwire.

Die echte Antwort auf `agent focus` hat `result.type = agent_info`, nicht einen
eigenen `agent_focused`-Typ. Die Anwendung prüft die zurückgelieferten physischen
IDs, Provider und `focused = true`.

**Grenzen:** Diese Registrierungen sind keine echten KI-Agenten und beweisen keine
semantische Busy-Erkennung eines Modells. Andere Herdr-Versionen wurden für diese
Anwendung nicht live geprüft. Das Lab belegt die echte Fokus-/Terminalintegration,
nicht lediglich Mock-Dispatch. Es wurde keine produktive Session fokussiert,
angehalten, neu gestartet oder umkonfiguriert. Ausführliche lokale Lab-Ausgaben
liegen beim erneuten Test standardmäßig unter `.local/<Lab-Session>/` (ignoriert).
`HERDR_LAB_EVIDENCE_DIR` ersetzt das Basisverzeichnis `.local`; darunter legt der
Test sein Session-Verzeichnis mit Snapshot-Fixture, Fokusantwort und TUI-Mitschnitten
an, einschließlich ANSI-Mitschnitten der befüllten und veralteten Ansicht.

Die Fokusregression in `tests/herdr_lab.py` lässt einen unfokussierten Worker
von `working` nach nativem `done` wechseln und bestätigt den exakten Fokus erst
durch Enter in der TUI, ohne vorherige Fokusquittierung außerhalb der Anwendung.
`native-done-before-enter.json` und `native-done-after-enter.json` halten die
Antworten vor und nach Enter fest. Die unabhängige Aufgabenachse prüft zusätzlich
`test_focus_verified_native_done_without_semantic_completion` in der Standardsuite.

Die separate Slow-Fetch-Variante wird mit demselben isolierten Helper gestartet:

```sh
HERDR_LAB_HELPER=/pfad/zum/firstmate-code/bin/fm-herdr-lab.sh bash tests/herdr-lab.sh --slow-fetch
```

Sie führt `tests/herdr_slow.py` anstelle des Fokus-/Zustandsszenarios aus: Navigation,
echtes Resize durch Split/Zoom und Beenden per q bzw. Ctrl+C während eines blockierten
Abrufs, danach kanonische Shell-Eingabe, Echo, exakte Terminalattribute und SIGINT
für einen neuen Shell-Befehl. Ihre Dateien liegen unter `q/` und `ctrl-c/` im
Session-Evidenzverzeichnis. Das Vorhandensein dieses Tests ersetzt keinen
erfolgreichen Live-Lauf.


## Sichtbarer Enter-Wechsel im echten Client

`tests/herdr-lab.sh --client` prüft zusätzlich den zuvor fehlenden Messpunkt:
Dashboard und zwei synthetische Worker liegen in getrennten Workspaces/Tabs.
Pfeil unten und Enter werden in den PTY des echten Herdr-Clients geschrieben,
nicht über `pane send-keys`. Der Zielprozess muss seinen eindeutigen Screen-Marker
im tatsächlichen Client-Output zeigen und anschließende Client-Tastatureingabe
mit einem zweiten Marker quittieren. Das gewählte Ziel wechselt vorher nativ von
working nach done; die Regression bleibt damit erhalten.

Ein testlokaler PATH-Adapter ergänzt ausschließlich für den Helper-Viewer dessen
verwerfenden PTY-Drain um Capture und eine Eingabe-FIFO. Die originale
Viewer-Implementierung besitzt weiterhin PTY, Prozessidentität und Cleanup;
keine geteilte Helper-Datei wird verändert. Alle Herdr- und Lifecycle-Aufrufe
laufen durch den generierten benannten Lab-Helper, mit EXIT-Teardown und
Default-Tripwire. FIFO-Zugriffe sind nicht blockierend, Prozesse zeitlich begrenzt.

Entfernte, ersetzte, fremde und stale Selektionen werden über `Source.focus`
abgelehnt, während derselbe reale Client das Dashboard zeigt. Nach jeder Ablehnung
beweisen echte Pfeileingaben die Bewegung des gerenderten Auswahlzeichens in der
Dashboard-Ansicht; kein Worker-Marker darf erscheinen. Diese Negativfälle injizieren
die ungültige Auswahl direkt am Fokusinterface (nicht durch UI-Enter), um die
ursprüngliche Generation auch nach Entfernung exakt zu prüfen. Unit-Tests decken
zusätzlich Änderungen zwischen Agent- und Tab-Mutation sowie Teilfehler ab.

Der erfolgreiche Lauf auf Herdr 0.9.0 zeigte Zielinhalt und anschließenden Input
im Client-PTY sowie alle vier unveränderten Negativansichten; beide Live-Varianten
beendeten den Helper-Teardown ohne Tripwire-Fehler. `positive-client.ansi`,
`*-client.ansi`, `native-done-before.json` und `commands.jsonl` liegen im lokalen
Session-Evidenzverzeichnis. Das ist keine Aufnahme einer physischen Mac-Tastatur
oder OS-Fensteraktivierung. Mehrere angeschlossene Clients wurden nicht getestet;
Herdrs öffentlicher Tab-Fokus projiziert sessionweit, nicht garantiert in genau
ein OS-Fenster. Ein API-Fokusflag oder direkt gelesener Pane-Puffer allein genügt
weiterhin ausdrücklich nicht als Nachweis des sichtbaren Wechsels.

## Enter-Latenz und laufender Hintergrundabruf

Die Variante `tests/herdr-lab.sh --latency`, ihr Messvertrag, die bisherigen
Ergebnisse und die noch offene Latenzabnahme sind in
[Fokuslatenz](focus-latency.md) dokumentiert.

## Reale Sessionform und vorlagennahe Ansicht

Die erste benannte Lab-Session verdeckte zwei Integrationsfehler: frühe Lab-IDs
enthielten nur Ziffern, während die reale Flotte bereits `wA:p2` verwendete; und
benannte Sessions geben ihren Namen zurück, die reservierte Default-Session aber
`null`. Die reale Vorschau zeigte deshalb sieben unbekannte Live-Zustände.

Herdr **v0.9.0** ist hierfür die überprüfte Autorität:

- [`src/session.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/session.rs):
  `normalize_name("default")` ergibt `None`; explizites `--session` hat Vorrang vor
  geerbtem Socket-/Sessionkontext.
- [`src/cli/status.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/cli/status.rs):
  Client und Server serialisieren diesen optionalen Sessionnamen. Das Default-
  `null` ist ein vorhandener Wert, kein fehlendes Feld.
- [`src/workspace.rs`](https://github.com/herdrdev/herdr/blob/v0.9.0/src/workspace.rs):
  öffentliche IDs verwenden das lesbare Base32-Alphabet, dessen zehnter Wert `A`
  ist. Großbuchstaben sind regulär; Handles werden nicht aus Reihenfolgen erraten.
- [Socket-Dokumentation](https://herdr.dev/docs/socket-api/): Default-Socket im
  Konfigurationsverzeichnis, benannte Sockets unter `sessions/<name>/herdr.sock`.

Die Korrektur akzeptiert nicht beliebiges `null`: explizites Default-Ziel,
vorhandene übereinstimmende Client-/Serverfelder, laufender kompatibler Server
und konsistenter Socket-Namespace sind erforderlich. Provider-/Pane-/physische
ID-Prüfungen vor Fokus bleiben bestehen. Fehlende, fremde, widersprüchliche und
veraltete Evidenz wird weiterhin unbekannt.

Die read-only Gegenprobe an genau den Snapshot-eigenen echten Endpunkten ergab
**sechs idle und einen working** statt sieben unknown. Kein echter Worker wurde
für diesen Nachweis fokussiert oder gesteuert. Das isolierte Lab überschreitet nun
bewusst die frühen Ziffern-IDs und prüfte den echten Fokus auf **`wA:p1`**, samt
Entfernungs-/Ersetzungs-/Fremd-/Stale-Ablehnung und leerem Inventar. Der Default-
Tripwire wurde nach Teardown erneut bestanden.

Auch die frühere Formatierung hatte einen konkreten Defekt: das abschließende
Kürzen normalisierte sämtliche Abstände und zerstörte Spaltenausrichtung. Jetzt
bleiben Layoutabstände erhalten. Gestapelte farbige Zahlenblöcke, farbige
Projektüberschriften mit Anzahl, eingerückte nummerierte Einzeiler und feste
Spalten folgen der Referenz. Live und Aufgabe bleiben aus Wahrheitsgründen zwei
Spalten; die Host-Sidebar, andere Markengrafiken und nicht vorhandene Worker werden
nicht kopiert.

Für den visuellen Vergleich wurde die echte curses-Anwendung auf einem **120×40**-
PTY mit echten read-only Quelldaten ausgeführt. `tests/capture_view.py` liest nach
einem erfolgreichen Abruf Text **und Attribute aus dem tatsächlich gezeichneten
curses-Fenster**, nicht aus der Layoutfunktion oder einem Mock. Der entsprechende
lokale PNG-Nachweis rendert diese Zellen im Browser bei ungefähr vergleichbarer
Inhaltsfläche zur Referenz (1590×1120 Pixel). Er ist kein Desktopfoto: Font und
Palette des Browsertestbilds können vom Host-Terminal abweichen. Die tatsächliche
Herdr-Vorschau wurde zusätzlich als sichtbarer Text und ANSI erfasst; ausschließlich
der bereits freigegebene Preview-Tab wurde aktualisiert.

Opt-in Zellaufnahme (keine Fokusaktionen):

```sh
python3 tests/capture_view.py --fm-home /pfad/zum/home \
  --firstmate-root /pfad/zum/code --output .local/view-120x40.json
```

Verglichen wurden Kopfproportionen, vertikale Farbblöcke, einheitliche Spalten,
Gruppeneinrückung, Leerzeilen zwischen Projekten und die Dichte der Worker-Zeilen.
Die sieben real vorhandenen Worker lassen naturgemäß mehr Freiraum als die
32-Worker-Referenz. Narrow-/Resize-/Restorationstests bleiben Bestandteil der Suite.

## Firstmate-Owner und feste erste Zeile

Auf macOS mit Herdr **0.9.0 / Protokoll 22** wurde zuerst der tatsächliche
Home-Lock-Owner ausschließlich read-only geprüft: Kernel-Startgeneration vor
Lock-mtime, eigene injizierte Herdr-IDs und Socket, übereinstimmende native
Pane-/Agent-Physik und direkte Abstammung von der gemeldeten Pane-Shell. Der
reale Default-Owner lieferte **kein `HERDR_SESSION`**, aber den kanonischen
Default-Socket. Der Kandidat kam aus dem Lock, nicht aus einer aufgezeichneten
Pane-ID, einem Titel oder dem Dashboard-Prozess. Kein Fokus/Lifecycle am realen
Owner, Preview oder Worker war Teil dieser Prüfung.

Der reproduzierbare opt-in Test ist:

```sh
HERDR_LAB_HELPER=/pfad/zum/firstmate-code/bin/fm-herdr-lab.sh \
  bash tests/herdr-lab.sh --primary-client
```

`tests/herdr_primary.py` verwendet ein synthetisches Home, eine ausdrücklich
synthetische Harness-argv0/Registrierung und einen Python-Chat-Echo-Prozess. Die
bestehende Firstmate-Klassifikation wird dabei wirklich aufgerufen. Apples
`/usr/bin/python3`-Launcher überschreibt argv0 beim Framework-exec; die Fixture
verwendet deshalb für ihre synthetische Identität direkt das Framework-Binary.
Es wird kein echter KI-Harness gestartet und keine Modellaktivität behauptet.

Der erfolgreiche Lauf beweist:

- Feste, eigenständige Firstmate-Zeile über genau einem gezählten Worker; das
  Dashboard läuft in einem **anderen** Tab/Workspace als der primäre Chat.
- Pfeil runter/hoch und Enter laufen durch den echten Herdr-Client-PTY, nicht
  per Pane-Injektion. Anschließend erscheint der eindeutige primäre Screenmarker
  **im tatsächlichen Client-Output**; weitere Client-Eingabe beantwortet der
  Zielprozess. Ein API-Fokuswert allein zählt nicht als dieser Nachweis.
- Eine andere synthetische Home-Lock-PID mit absichtlich kopierter injizierter
  Zielidentität scheitert an der nativen Shell-Abstammung.
- Fehlender, mehrdeutiger/malformed und generationell veralteter Lock wird
  sichtbar nicht verfügbar. Erneutes Enter lässt die Client-Ansicht unverändert;
  die alte Auswahl wird auch durch den direkten Fokus-Einstieg abgelehnt.
- Nach echtem guarded Stop/Re-provision bleiben öffentliche Pane-IDs erhalten,
  aber Terminal-ID und Owner-Lebenszeit nicht: der alte Lock wird abgelehnt.
- Teardown und Default-Session-Tripwire bestanden. Worker-Client-, klassisches
  Herdr- und Slow-Fetch-Lab wurden mit der zusätzlichen Zeile ebenfalls geprüft.

`tests/test_primary.py` ergänzt fleet-unabhängige Tests für stabile Reihenfolge,
Scroll-/Narrow-Darstellung, Tastaturerreichbarkeit, Worker-Zähler, nicht still
ersetzte Auswahl, native-done, Zeit-/Generations-/Ancestry-Rennen, fehlende und
doppelte Identität, Default-Socket-Abgrenzung und fehlende Prozesssicht. Mock-
Mutationsassertionen darin ersetzen niemals den separaten Client-Nachweis.

`--primary-client` ruft außerdem `tests/herdr_narrow.py` auf: Die echte TUI läuft
mit der Live-Quelle des benannten Labs in einem eigenen **28×16**-PTY. Drei
j/k-Navigationszyklen prüfen jeweils acht aufeinanderfolgende curses-Frames mit
stabilem ausgewähltem Worker-Titel und Auswahlzeichen, dessen zweiter Zustandszeile,
sichtbarer fester Firstmate-Zeile und unveränderten Worker-Zählern. Die schmale
Zeile wird weiterhin an der Fensterbreite gekürzt. `narrow-frames.jsonl` erfasst
das tatsächlich gezeichnete curses-Fenster; `narrow-client.ansi` enthält den
PTY-Mitschnitt. Diese separate Terminalaufnahme ist kein Herdr-Client-Wechsel;
diesen prüft das oben beschriebene Enter-Szenario.

Nicht behauptet werden atomare Fokus-/Generationsgarantien, tatsächlich erzwungenes
PID-Recycling, fremde OS-Fensteraktivierung oder Linux-Unterstützung des primären
Readers. Die Stale-PID-Tests stellen die relevante Zeit-/Generationsbedingung
kontrolliert her; die Restart-Prüfung verwendet dagegen einen echten benannten
Server-Neustart. Raw-Client-Evidenz und ausgewählte Owner-Beobachtungen liegen
im [Session-Evidenzverzeichnis](#isolierter-herdr-live-test).

## Modelllabels: echte PTY-UI mit synthetischer Quelle

Am 2026-09-13 wurde der zuvor gemeldete fehlende Lab-Helper reproduziert:
`env -u HERDR_LAB_HELPER bash tests/herdr-lab.sh` endet vor Provisioning mit
`Set HERDR_LAB_HELPER to Firstmate bin/fm-herdr-lab.sh`. Das ist eine fehlende
Live-Testvoraussetzung, kein reproduzierter Produktfehler. Für diese Modellabnahme
wurde ausdrücklich eine deterministische Quelle in der echten PTY-UI freigegeben.

Reproduzierbare, gezielte Prüfung ohne Herdr-Aufrufe:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/model_labels_pty.py
```

Alle **21 Fälle bestanden**: sieben Modellfälle jeweils auf 120×24, 40×24 und
28×24. `curses.wrapper`, `tui`, Poller, Source und Rendering laufen tatsächlich;
`instr` liest nach `refresh` die gezeichneten Fensterzellen. j/k/q gelangen über
den PTY-Master zur echten Eingabeschleife. Die Prüfung verlangt beide sichtbaren
Modell-/Effortlabels (Firstmate und Worker), Wechsel der Auswahl, den Workerzähler
und natives idle; bei 120 Spalten zusätzlich bündige Model-/Live-Spalten.

| Abnahmeszenario | Beobachtete Labels in Firstmate- und Workerzeile |
| --- | --- |
| Feste Grok-/Claude-Namen | `Grok·H`, `Claude·M` |
| Bestehender Name hat Vorrang (`provider/claude-astra-5`) | `Astra·M` |
| Generischer, begrenzter Name; eingebettetes grok ohne festen Treffer | `Gemini·H`, `Long-u·XH`, `Megrok·L` |
| Keine bestätigte Runtime-Auswahl | `?·?` |
| Breite und schmale Ansicht | Alle sieben Labels vollständig bei allen drei Breiten |

**Evidenzgrenze:** echte curses-UI und PTY-Eingabe, **synthetische Quelle**.
Der testlokale Runner liefert Fleet-, Herdr- und Identity-Reader-Antworten;
Source prüft diese mit unveränderten Produktionsguards. Es werden weder echte
Firstmate-/KI-Prozesse noch OS-Owner-Erkennung oder Herdr-Client-Fokus bewiesen.
Kein Fokus wird ausgelöst, keine Flotte oder Lifecycle-Funktion angesprochen.
Die zwei gezielten bestehenden Tests
`SourceTests.test_probe_collects_exact_session_model_and_effort_only` und
`PrimaryTests.test_primary_without_unique_runtime_session_stays_unknown_model`
bestanden ebenfalls. Für diesen PTY-Nachweis wurden die Produktionsguards nicht
geändert. Zellaufnahmen und
ANSI-Mitschnitte entstehen temporär innerhalb des Worktrees und werden nach dem
Test entfernt; es wurde keine vollständige Suite ausgeführt.
