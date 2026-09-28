#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif
#ifndef PayloadRoot
  #define PayloadRoot "payload"
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef IconPath
  #define IconPath "brand-mark.ico"
#endif

[Setup]
AppId={{A9C3B3F6-4D56-4A7A-8E7D-7D8B2D39C9D4}
AppName=职航 CareerPilot
AppVersion={#AppVersion}
AppPublisher=职航 CareerPilot
DefaultDirName={localappdata}\Programs\CareerPilot
DefaultGroupName=职航 CareerPilot
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CareerPilotSetup
SetupIconFile={#IconPath}
UninstallDisplayIcon={app}\CareerPilot.exe
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
Uninstallable=yes

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Icons]
Name: "{autodesktop}\职航 CareerPilot"; Filename: "{app}\CareerPilot.exe"; WorkingDir: "{app}"; IconFilename: "{app}\brand-mark.ico"; Tasks: desktopicon
Name: "{group}\启动职航 CareerPilot"; Filename: "{app}\CareerPilot.exe"; WorkingDir: "{app}"; IconFilename: "{app}\brand-mark.ico"

[Run]
Filename: "{app}\CareerPilot.exe"; Description: "启动职航 CareerPilot"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\stop.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "StopCareerPilot"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
