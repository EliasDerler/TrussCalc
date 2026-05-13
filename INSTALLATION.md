# TrussCalc installieren und starten

Diese Anleitung beschreibt den normalen Start der Windows-Version und den Start
aus dem Quellcode.

## Empfohlen: Windows-Version aus GitHub Releases

1. Öffne die aktuelle Release-Seite:
   https://github.com/EliasDerler/TrussCalc/releases/latest

2. Lade die Datei `TrussCalc-Windows-v0.2.1.zip` herunter.

3. Entpacke die ZIP-Datei in einen festen Ordner, zum Beispiel:
   `C:\Programme\TrussCalc` oder `C:\Users\<Name>\Programme\TrussCalc`

4. Starte `TrussCalc.exe` im entpackten Ordner.

Wichtig: Der Ordner `_internal` muss neben `TrussCalc.exe` liegen. Nicht nur die
EXE einzeln verschieben, sonst fehlen Programmbibliotheken.

Beim ersten Start der Windows-Version legt TrussCalc automatisch eine
Desktop-Verknüpfung und eine Startmenü-Verknüpfung mit TrussCalc-Logo an.
Windows erlaubt echtes automatisches Anheften an Start/Taskleiste nicht
zuverlässig über eine normale Anwendung; die Verknüpfungen sind deshalb der
unterstützte Startweg.

## Erster Start

Beim ersten Start legt TrussCalc die lokale Datenbank automatisch an. Die
Datenbank liegt standardmäßig unter:

`%USERPROFILE%\TrussCalc\trusscalc.db`

Die Default-Traversenbibliothek wird automatisch eingelesen, wenn die Datenbank
noch leer ist.

## Windows-Sicherheitswarnung

Windows kann beim ersten Start eine SmartScreen-Warnung anzeigen, weil die EXE
nicht digital signiert ist. In diesem Fall:

1. Auf `Weitere Informationen` klicken.
2. `Trotzdem ausführen` wählen.

## Updates

Wenn beim Start eine Internetverbindung besteht, prüft TrussCalc automatisch:

- ob eine neue Programmversion auf GitHub verfügbar ist
- ob neue Einträge in der Default-Traversenbibliothek verfügbar sind

Die aktuelle Version steht unter:

https://github.com/EliasDerler/TrussCalc/releases/latest

## Start aus dem Quellcode

Für Entwickler:

```powershell
cd C:\Claude_Projekte\TrussCalc_Codex
.venv\Scripts\python.exe main.py
```

Falls die virtuelle Umgebung fehlt:

```powershell
cd C:\Claude_Projekte\TrussCalc_Codex
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## PDF(KI)-Import

Der normale PDF-Import funktioniert ohne KI-Komponenten. Der Button `PDF(KI)`
benötigt zusätzlich PaddleOCR/PaddlePaddle und kann beim ersten Start länger
dauern, weil KI-Modelle geladen werden.

## Häufige Probleme

### Programm startet nicht nach dem Verschieben

Prüfen, ob `TrussCalc.exe` und der Ordner `_internal` weiterhin im gleichen
Ordner liegen.

### Keine Bibliothek sichtbar

Die Datenbank kann zurückgesetzt werden, indem die Datei
`%USERPROFILE%\TrussCalc\trusscalc.db` umbenannt oder gelöscht wird. Beim
nächsten Start wird sie neu angelegt und die Default-Bibliothek erneut
eingelesen.

### Updateprüfung soll deaktiviert werden

Für Tests kann die automatische Updateprüfung per Umgebungsvariable deaktiviert
werden:

```powershell
$env:TRUSSCALC_DISABLE_UPDATE_CHECK="1"
.\TrussCalc.exe
```
