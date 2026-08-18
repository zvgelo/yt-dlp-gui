; Inno Setup script for yt-dlp GUI.
;
; Driven by scripts\build_windows.ps1, which passes the version and the paths:
;
;   ISCC.exe /DAppVersion=1.0.0 /DSourceDir=...\yt-dlp-gui /DOutputDir=...\dist\windows ^
;            packaging\windows\yt-dlp-gui.iss
;
; The installer only ever writes to the installation directory and the Start
; Menu. Uninstalling removes what was installed and nothing else - not the
; download folder, not the history database, not the settings. Those belong to
; the user, who may well reinstall tomorrow.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\build\windows-stage\yt-dlp-gui"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\dist\windows"
#endif

#define AppName "yt-dlp GUI"
#define AppExeName "yt-dlp-gui.exe"

[Setup]
AppId={{8C1E4F32-6D2A-4B3C-9E7F-5A1D0C2B4E68}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\yt-dlp-gui
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=yt-dlp-gui-{#AppVersion}-setup-x86_64
SetupIconFile=..\..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The bundled Python, Qt, FFmpeg and Deno are all 64-bit
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Matches the oldest Windows the bundled components support
MinVersion=10.0
LicenseFile=..\..\LICENSE
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only files the application itself generates inside its own directory. The
; history database, the settings and every downloaded file live under the
; user's profile and are deliberately left alone.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
