; Installer di JobsHunter per Windows (Inno Setup 6). Installazione PER UTENTE: non chiede i permessi di amministratore.
; Si costruisce da build_windows.ps1: iscc /DAppVersion=0.4.0 /DSourceDir=<cartella JobsHunter> /DOutDir=<uscita> /DIconFile=<ico> packaging\JobsHunter.iss
; Non firmato: Windows SmartScreen mostra un avviso al primo avvio (vedi README).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #error SourceDir non indicata
#endif
#ifndef OutDir
  #define OutDir "."
#endif

[Setup]
AppId={{6F0C7F26-3D5B-4E7E-9B71-4A1C8E5D2F10}
AppName=JobsHunter
AppVersion={#AppVersion}
AppPublisher=JobsHunter
DefaultDirName={localappdata}\Programs\JobsHunter
DefaultGroupName=JobsHunter
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=JobsHunter-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
UninstallDisplayName=JobsHunter
UninstallDisplayIcon={app}\JobsHunter.exe
#ifdef IconFile
SetupIconFile={#IconFile}
#endif

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\JobsHunter"; Filename: "{app}\JobsHunter.exe"
Name: "{autodesktop}\JobsHunter"; Filename: "{app}\JobsHunter.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul desktop"; Flags: unchecked

[Run]
Filename: "{app}\JobsHunter.exe"; Description: "Avvia JobsHunter"; Flags: nowait postinstall skipifsilent

; I dati dell'utente (annunci, candidature, CV, chiavi) stanno in %LOCALAPPDATA%\JobsHunter e NON vengono toccati dalla disinstallazione.
