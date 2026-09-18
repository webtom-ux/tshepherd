# Anforderungen und Design

## Ziel

TShepherd is a standalone local live terminal overview for your own Firstmate workers.
It runs in a normal Herdr tab on macOS or Linux. The visual reference is the contract
for the terminal content area: compact color blocks with numbers to the left of labels,
spacing between project groups, and indented aligned worker rows. Herdr's sidebar/tab
bar is not recreated; the branding remains TShepherd, without copied marks, images, or
mascots.

Die Ansicht beantwortet: Wer arbeitet, wer wartet, wer ist nativ idle, welche
Aufgabe ist abgeschlossen und wo fehlt belastbare Information? Aufgabenname und
letzte bekannte Aktivität helfen bei der Orientierung. Eine ausdrückliche Auswahl
mit Enter wechselt zur zugehörigen Herdr-Ansicht.

## Feste Grenzen

- Firstmate bleibt alleinige Aufgaben- und Inventarquelle; keine zweite Verwaltung.
- Ein explizites Home bestimmt die Eigentumsgrenze. Kein Scan gemeinsam genutzter
  Herdr-Namespaces, keine automatische Rekursion in andere Homes.
- Native Agentaktivität und semantischer Aufgabenstatus sind unabhängige Achsen.
  Fehlende, widersprüchliche, veraltete oder unerreichbare Daten dürfen nicht als
  bestätigtes idle oder als aktueller Abschluss erscheinen.
- Es gibt ausschließlich Beobachtung und expliziten Fokus: keine Spawn-, Stop-,
  Send-, Delete-, Scheduler- oder sonstigen Steuerfunktionen.
- Keine globale Installation, Telemetrie, öffentliche Dienste oder Änderungen an
  Firstmates gemeinsamen Skripten und Konfigurationen.

## Umsetzung

Eine Python-Standardbibliotheksanwendung (`tshepherd.py`) vermeidet zusätzliche
Frameworks. `curses.wrapper` besitzt den Terminal-Lebenszyklus. Darstellung,
Zustandsprojektion, Auswahl, Datenzugriff und Polling sind getrennte Funktionen/
Klassen und ohne laufende Flotte prüfbar.

`Source.snapshot` ruft die JSON-Schnittstelle des konfigurierten Code-Roots mit
explizitem Home auf. Schema, Home und eindeutige Worker-Identitäten werden geprüft.
Nur die `tasks`-Metadaten bestimmen Worker-Zeilen. Die unterstützten, kurzen Titel-/Aktivitäts-
Felder werden verwendet, niemals Rohlogs, Berichtsinhalte oder Transkripte.

`Source.probe` ergänzt pro exakt gebundenem lokalem Herdr-Pane eine native Beobachtung.
Sie prüft Session/Kompatibilität, Pane-ID, Provider und Workspace-/Tab-/Terminal-ID.
`default` wird nur für ein ausdrücklich so geroutetes Ziel auf Herdrs beidseitiges
JSON-`null` normalisiert. Fehlende Sessionfelder und widersprüchliche Socket-
Namespaces werden abgelehnt. Öffentliche Pane-Handles verwenden Herdrs dokumentierte
Großbuchstaben-Base32-Zeichen; die physische Roundtrip-Prüfung bleibt unverändert.
Shell-only-Vordergrund oder fehlende Prozessinformationen reichen nicht aus, um
veraltete Registrierungen als live zu bestätigen. Native `idle` und `done` sind
beide eingabebereit; `done` bleibt als ungesehene Antwort sichtbar von `idle`
getrennt. Eine native Meldung ist dennoch keine semantische Aussage über laufende
Tools; die UI benennt diese Grenze.
Eine erfolgreiche Prüfung liefert die physische Bindung unabhängig von der
Aktivitätszuordnung. `Source.focus` verlangt diese Bindung, keinen bestimmten
Live-Zustand; auch der eingabebereite Zustand `done` verhindert deshalb den
Fokus nicht. Alle nachfolgenden Eigentums-, Frische- und
Identitätsprüfungen bleiben erforderlich.

`Poller` besitzt einen Collector und einen separaten Single-Flight-Fokusworker.
Die ergänzende Quota-Anzeige bleibt von Snapshot-Inventar, Aktivität und
Fokusautorität getrennt. Der Collector liest sie nach dem Freigeben seines
Busy-Zustands und liefert sie als separates Ergebnis an `View`.
Provider-Auswahl, Frische und Darstellung beschreibt die
[README](../README.md#launch-with-just-tshepherd).
Enter wird auch während eines Refreshs sofort angenommen; ein zweiter Fokusauftrag
während einer laufenden Fokusprüfung wird abgelehnt, nicht später nachgeholt.
Innerhalb eines Refreshs gibt es maximal vier native Leser mit einem gemeinsamen
Zeitbudget. Fokus nutzt daneben nur seine begrenzten zielbezogenen Reads. Subprozesse besitzen eigene Gruppen,
werden zeitlich und in ihrer Ausgabe begrenzt und bei Abbruch beendet. Kein zusätzlicher
Dienst und keine dauerhaft gespeicherte Kopie des Aufgabenstatus entstehen.
R und begrenzte unknown-Retries wecken denselben Collector, ohne Agentensteuerung.
Ursachenprüfung, Schwelle/Cooldown und Grenzen: [Status-Neuerkennung](status-rediscovery.md).

`View` hält Snapshot, native Messungen, Quota-Beobachtungen, Auswahl und bestätigte Aufgabenintervalle
im Speicher. Für Worker gilt die
Kombination aus Task-ID, Spawn-Generation, Backend, Endpunkt und Provider, nicht die
Zeilennummer. Beim Dispatch wird zusätzlich die angezeigte physische Bindung
mitgegeben, sofern bestätigt. Die bestätigte physische Auswahl bleibt auch über
Messausfälle erhalten; eine abweichende neue Bindung verlangt explizite Neuauswahl. Sortieren oder Entfernen darf keinen anderen Worker
stillschweigend zum Ziel machen. Enter prüft das ausgewählte Ziel gegen das letzte
vollständig gelieferte, weiterhin frische Snapshot-Inventar. Die aktuelle lokale
Eigentumsprüfung liest ausschließlich dessen exakt gebundene Metadatendatei;
[Vertrag und Autorität](focus-latency.md#zielbezogener-eigentumsbeleg) beschränken
Felder, Größe, Dateityp und Pfad. Nach den nativen Reads werden Eigentum und
Frische erneut geprüft; anschließend bestätigt ein letzter `pane get` noch einmal
dieselbe physische Bindung vor der folgenden Mutation. Weder ein unveränderter Snapshot allein
noch ein bloß gespeicherter Pane-Handle autorisiert Fokus. Der CLI-
Aufruf erhält sichere getrennte Argumente mit expliziter Session. Nach bestätigtem
Agent-Fokus prüft `focus_target` sämtliche zielbezogenen Guards erneut und verlangt dieselbe
physische Identität, bevor deren Tab explizit fokussiert wird. Dieser zweite
CLI-Schritt projiziert Herdrs Session-Clientansichten; Agent-Fokus allein tut das
nicht. Anschließend werden Eigentum, Frische, physische Bindung und exakter
Agent-Fokus erneut bestätigt. Teilfehler behaupten keinen vollständigen Erfolg;
der Footer bestätigt Server-Zustand, kein bestimmtes OS-Fenster. Atomarer Schutz
gegen Änderungen nach dieser letzten Prüfung ist mit der verwendeten API nicht möglich.
Die eigene Auswahlidentität und Zielprüfung für Firstmate beschreibt
[Primärer Chat](#primärer-chat).

Die Ansicht zeigt Abrufalter, Datenfehler, Inventarlücken und unbekannte Zustände.
`rows_for` ergänzt bei bestätigtem nativem `done` dessen Erklärung im Anzeigegrund,
ohne die gelieferte Aufgabenaktivität zu ersetzen. Bei frischem Snapshot und
gültiger nativer Messung, aber veraltetem `current_state`, bleibt die Aufgabenachse
`unknown`; ihr Frischehinweis bleibt neben der nativen Erklärung erhalten.
Zähler sind explizit Beobachtungszahlen; `completed` gehört zur Aufgabenachse und
überlappt mit Live-Zuständen. Farbige Zahlenblöcke stehen vertikal neben dem Branding,
Projektgruppen tragen eigene Farben und eingerückte einzeilige Worker. Agent, Model, Live,
Aufgabe, Aufgabenzeit und letzte Aktivität stehen auf festen Zellspalten. Die Model-Zelle liest
bei Pi ausschließlich eine innerhalb der bestätigten Prozessgeneration eindeutige
Sessiondatei des exakten Worktrees und folgt deren aktiver Eintragskette.
Die benutzerseitige Bedeutung der Modell-/Effortlabels beschreibt die
[README](../README.md#launch-with-just-tshepherd); die Ableitung implementiert
`compact_model` in `tshepherd.py`.
Launch-/Dispatch-Metadaten sind kein Ersatz für die aktuelle Auswahl.
Die Anordnung und Bedeutung der Zeitanzeige beschreibt die
[README](../README.md#launch-with-just-tshepherd). Beide Zeitbasen
stammen aus der erneut bestätigten Prozessgeneration: Bei Workern muss derselbe
Prozess über seine selektierte Umgebung exakt an Task-ID, Spawn-Bindung und Pane
gebunden sein; beim primären Chat gilt die verifizierte Lock-Owner-Generation.
Snapshot-Beobachtungszeiten und unbestätigte Metadaten werden nicht als Startzeit
gedeutet. `rows_for` gibt den Aufgabenstart nur bei frischem, bestätigtem Outcome
`working`, `parked`, `blocked` oder `paused` frei. `View` merkt sich für diese
identitätsgleiche Worker-Zeile das zuletzt bestätigte Intervall vom Aufgabenstart
bis `Native.observed` der frischen nativen Messung. Diese Obergrenze ist kein
autoritativer Abschlusszeitpunkt; Zeit bis zur späteren Abschlussmeldung wird
nicht hinzugerechnet. Bei frischem Outcome `done` oder `failed` verwendet die
Anzeige dieses Intervall auch ohne aktuelle native Zeitmessung. Fehlende Messungen
für dieselbe Identität löschen es nicht. Eine weitere bestätigte aktive Messung
aktualisiert das Intervall; ein anderer bestätigter Aufgabenstart ersetzt dabei
den bisherigen Start. Entfernte oder geänderte Zeilenidentitäten verlieren ihr
Intervall. Die Regression
`test_terminal_task_duration_survives_missing_native_measurements` in
`tests/test_tshepherd.py` deckt Messausfall, neuen Start und Identitätswechsel ab.
Der Sessionstart hängt nicht vom Outcome ab. Beide Starts erfordern eine
frische, identitätsgleiche native Messung, bei Workern zusätzlich einen frischen
Snapshot. Die Zeitwerte beeinflussen die Sortierung nicht und werden nicht
dauerhaft gespeichert.
Quelltextfelder werden von Steuerzeichen bereinigt; Formatierungsabstände bleiben
beim Kürzen erhalten.
Unter 78 Spalten werden Zeilen gestapelt. Unicode-Breiten werden berücksichtigt. Farben sind nicht
die einzige Kodierung: Zustandswörter bleiben lesbar.

## Primärer Chat

Die feste `PrimaryRow` steht unabhängig von Worker-Sortierung und Scrollposition
über den Projektgruppen. Sie besitzt keine Task-Metadaten und keinen Outcome;
alle bestehenden Zähler bleiben ausschließlich Worker-Zähler. Native Aktivität
bleibt auch hier unabhängig von Fokusfähigkeit: natives `done` ist eingabebereit
und als ungesehene Antwort sichtbar; bei bestätigter Identität bleibt es erreichbar.
Fehlende oder veraltete Evidenz wird
sichtbar unavailable/unknown, nie durch einen anderen Endpunkt ersetzt.

Der aktuelle Fleet-Snapshot exportiert keine primäre Chat-Bindung.
`primary_identity.py` liest deshalb ausschließlich den PID-Lock des expliziten
Homes und die bestehende Firstmate-Harnessklassifikation aus
`bin/fm-session-lock-lib.sh`, ohne den Lock zu erwerben oder Dateien zu schreiben.
The bounded OS subprocess keeps the existing macOS reader (`proc_pidinfo(PROC_PIDTBSDINFO)`
for PID generation/ancestry and `sysctl(KERN_PROCARGS2)` for selected Herdr identity
fields) and adds an equivalent Linux `/proc` reader for PID/UID/generation, ancestry,
and the same selected environment fields. OS buffers are evaluated only in memory;
argv and other environment values are never emitted or stored. Unsupported platforms
and restricted process visibility remain explicitly unavailable.

Die Prozessgeneration muss vor der Lock-mtime begonnen haben; Lock-Inode,
Zeitstempel, Inhalt, Owner-Prozess und dessen eigene injizierte Identität werden
wiederholt verglichen. Fehlende/doppelte Identitätsfelder, symlinkende Locks,
ungültige PID und unlesbare Daten verweigern die Bindung. Herdr lässt beim
Default-Owner `HERDR_SESSION` weg: nur dessen kanonischer Default-Socket erlaubt
hier die explizite Route `default`; danach müssen die bekannten beidseitigen
JSON-null-/Socket-/Kompatibilitätsprüfungen bestehen. Keine Umgebungsvariable des
Dashboards und kein Label bestimmt den Kandidaten.

`Source.primary` verbindet diesen Kandidaten mit exakten nativen Session-, Pane-,
Agent- und Prozessinformationen. Pane und Agent müssen dieselbe physische
Workspace-/Tab-/Terminal-Identität liefern. Die Lock-PID muss über höchstens 24
aktuelle Elternschritte die von genau diesem Pane gemeldete Shell erreichen;
die Generationen der Kette werden nochmals geprüft. Das schließt eine fremde
Pane trotz gültiger Registrierung sowie restaurierte öffentliche IDs ohne den
alten Owner aus. Nach der OS-Prüfung wird die physische Pane-Bindung erneut gelesen.

Die Auswahl bindet Home/Lock, PID/Startgeneration, injizierten Endpunkt, Provider
und physische IDs. Ein Owner-Wechsel retargetiert keine bestehende Auswahl.
`Source.primary_target` prüft ausschließlich diesen Owner/Endpunkt neu; es löst
auf Enter keinen Fleet-Snapshot und keine Worker-Abfragen aus. Agent-/Tab-Fokus
verwenden den gemeinsamen bestehenden Navigationspfad mit erneuten Zielprüfungen
vor der zweiten Mutation und bei der Abschlussbestätigung.

Die Reads sind nicht atomar. Zwischen zwei Messungen oder nach dem letzten Check
können Prozess, Lock oder Pane wechseln. Lock-mtime ist ein konservativer
Wiederverwendungscheck, keine vom Kernel signierte Besitzgeneration; Manipulationen
durch denselben lokalen Benutzer oder veränderte Systemzeit sind keine zusätzliche
Sicherheitsgrenze. Same-PID-exec verlangt weiterhin die aktuelle Harnessprüfung.
Es gibt keinen neuen Dienst, kein gemeinsames Zustandsschema und keinen
Fallback auf eine Namenssuche oder unbewiesene Linux-Prozessinterpretation.

## Abnahmepunkte

| Bereich | Nachweis |
| --- | --- |
| Mapping, Completion/Idle-Trennung, Fehler/Stale | `tests/test_tshepherd.py` |
| Logische Projektgruppierung, Zähler, Auswahlidentität | `tests/test_tshepherd.py` |
| Fester Firstmate-Eintrag, eigene Zählergrenze, Owner-/Generations-/Frische-/Fehlerfälle | `tests/test_primary.py` |
| Primärer Chat über reale Client-Tastatur; fremder Owner und Restart | `tests/herdr-lab.sh --primary-client` auf macOS |
| Single-Flight-Fokus neben blockiertem Refresh, Ziel-Metadaten, Budget, Abbruch, sichere argv | `tests/test_tshepherd.py` |
| Rendering, schmale Fenster, Resize, Eingabe während Fetch | `tests/test_terminal.py` und Renderingtests |
| Echo, Canonical, Signals, Cursor/Altscreen, anschließende Shell | echte PTY-Tests in `tests/test_terminal.py` |
| Tatsächlicher Herdr-Fokus, echte TUI und sichtbarer Client-Wechsel im Lab | [Isolierter Live-Test und Client-Variante](verification.md#isolierter-herdr-live-test) |

Eine Mockbestätigung darf nicht als reale Herdr-Fokusbestätigung ausgegeben werden.
Der Live-Test benutzt für jeden Herdr-Befehl den benannten nicht-default Lab-Helper,
auch für Provisioning, Viewer und Teardown. Die Default-Flotte und fremde Projekte
sind keine Testziele.
