# Status-Neuerkennung: begrenzte Ursachenprüfung

## Befund und Grenze

Gemeldetes Symptom: länger `unknown`, vermeintlich erst durch Dashboard-Neustart
auflösbar. Der konkrete betroffene Endpunkt und seine damaligen autoritativen
Snapshot-/Herdr-Antworten liegen nicht vor. Die Produktionsflotte wurde nicht
abgefragt oder verändert; ein realer Nutzerfall ist damit **nicht reproduziert**.

Hypothese: TShepherd hält eine veraltete Zuordnung dauerhaft fest.
Gegenbeleg: `Source.collect` ruft bereits `snapshot`, `primary` und `probe` bei
jedem Polling erneut auf, ohne Cache-Fallback. Neustart und normales Polling
verwenden denselben Aufbau. Die Historie (d02c957, e5509e0) bestätigt diese
Trennung: `Source.current` ist ein Fokus-/Frischebeleg, kein Discovery-Cache.

`tests/test_rediscovery.py` führt das echte `Source.snapshot` über einen lokalen
Snapshot-Subprozess aus (kein Ersatz der Snapshot-Methode). Native Antworten sind
kontrollierte Testdaten, kein Live-Herdr-Beweis:

- Trigger: Shell-only-Prozessbeleg; sichtbares Ergebnis: unknown mit Grund.
- Bedingung: bei unverändertem Snapshot kommt wieder Nicht-Shell-Evidenz an.
  Der nächste normale `collect` liefert idle, ohne Neustart; eine neue Source
  liefert dieselbe physische Identität. Das widerlegt den behaupteten lokalen
  Mapping-Cache für diesen Pfad.
- Änderung der autoritativen Snapshot-Datei auf einen anderen Endpunkt bindet
  bereits beim nächsten Abruf neu. Ungültige Endpunkte bleiben unknown.
- Konkrete Sicherheitslücke: bei gleicher logischer Identität konnte eine neue
  physische Bindung die bestehende Auswahl übernehmen. `View` hält jetzt die
  bestätigte physische Auswahl über Messausfälle fest und verlangt Neuauswahl
  bei Änderung; auch Enter während eines Messausfalls behält diesen Guard.

Keine breitere Untersuchung ohne den konkreten fehlschlagenden Quellenbeleg.
Keine Behauptung, dass R eine veraltete *autoritative* Firstmate-Zuordnung repariert.

## Umsetzung

R weckt ausschließlich den vorhandenen Collector. Nach 30 s unknown fordert die
UI denselben Abruf an, mit global 60 s Cooldown und monotonic-Zeit. Laufende und
schon angeforderte Abrufe werden zusammengefasst; es gibt keine parallele zweite
Discovery, neue Konfiguration oder zusätzlichen Dienst. Normales Polling bleibt
unverändert und kann unknown schon vor der Schwelle auflösen. Single-Flight-Fokus
läuft weiterhin separat und liest auf Enter keinen Fleet-Snapshot.

Primary-Farben verwenden unverändert die Worker-Palette; Text und `>` bleiben
sichtbar. Native done-Zustände werden nicht als Arbeit interpretiert. Unlesbare
CLI-Quellen erhalten einen knappen Zugriffshinweis statt ungefiltertem stderr in
nativen Zeilen.

## Verifikation

`make check`: Quellen-Neuladen, unknown→known ohne Neustart, Vergleich mit neuer
Source, echte Snapshot-Endpunktänderung, ungültige Ziele, Physical-Rebind über
unknown hinweg, Schwelle/Cooldown/Recovery, manueller R-Key, Single-Flight-Collector,
Primary-Palette breit/schmal. Bestehende Fokus-Hotpath-, Ownership-, Generations-
und echte PTY-Tests bleiben Bestandteil des Laufs. Dies ersetzt keine opt-in
Live-Client-Fokusabnahme; diese Änderung behauptet keine neue Fokuslatenzmessung.
