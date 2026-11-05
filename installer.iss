; PubDesign installer (Inno Setup 6). Built automatically by GitHub Actions.
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "PubDesign"
#define MyAppExe "PubDesign.exe"

[Setup]
AppId={{6E2B9C41-8F3A-4D5E-9B17-2C8A4F0D3E61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=Ljbutton
AppPublisherURL=https://github.com/Ljbutton/PubDesign
AppUpdatesURL=https://github.com/Ljbutton/PubDesign/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=PubDesign-Setup
SetupIconFile=assets\PubDesign.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "pubdefault"; Description: "Open &.pub files with PubDesign when double-clicked"; GroupDescription: "Files:"

[InstallDelete]
; remove the previous version's program files before copying the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\PubDesign\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Registry]
; PubDesign backup files (.pubdesign)
Root: HKCU; Subkey: "Software\Classes\.pubdesign"; ValueType: string; ValueName: ""; ValueData: "PubDesign.Document"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\PubDesign.Document"; ValueType: string; ValueName: ""; ValueData: "PubDesign Document"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\PubDesign.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKCU; Subkey: "Software\Classes\PubDesign.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""
; Publisher files: list PubDesign under "Open with"
Root: HKCU; Subkey: "Software\Classes\PubDesign.Publication"; ValueType: string; ValueName: ""; ValueData: "Publisher Publication"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\PubDesign.Publication\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExe},0"
Root: HKCU; Subkey: "Software\Classes\PubDesign.Publication\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pub\OpenWithProgids"; ValueType: string; ValueName: "PubDesign.Publication"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExe}\SupportedTypes"; ValueType: string; ValueName: ".pub"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExe}"" ""%1"""
; optional: make PubDesign the default for .pub (works when no other app has been chosen as default)
Root: HKCU; Subkey: "Software\Classes\.pub"; ValueType: string; ValueName: ""; ValueData: "PubDesign.Publication"; Flags: uninsdeletevalue; Tasks: pubdefault

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Launch PubDesign"; Flags: nowait postinstall skipifsilent
; after a silent auto-update, reopen PubDesign
Filename: "{app}\{#MyAppExe}"; Flags: nowait; Check: WizardSilent
