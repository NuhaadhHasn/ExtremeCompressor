; Inno Setup script for ExtremeCompressor (E3). UNBUILT: see packaging\README.md.
; Build:  iscc /DAppVersion=0.1.1 packaging\installer.iss   (after PyInstaller made dist\ExtremeCompressor)

#ifndef AppVersion
  #define AppVersion "0.1.1"
#endif

[Setup]
; Keep this GUID: it is how a later installer recognises (and upgrades) this one.
AppId={{7D57A03D-876B-4BF2-9569-D11D4F586D01}
AppName=ExtremeCompressor
AppVersion={#AppVersion}
AppPublisher=NuhaadhHasn
DefaultDirName={autopf}\ExtremeCompressor
DefaultGroupName=ExtremeCompressor
; Per user, no administrator: the Explorer menu is per user too (HKCU), and nothing here needs more.
PrivilegesRequired=lowest
; No "install for all users" override: an elevating account would run `shell install` into ITS OWN HKCU, and
; Program Files is not writable by the tool downloader (toolfetch keeps its tools beside the app).
; Close a running window (Restart Manager) before replacing or removing its files.
; While a window is open (it holds the mutex checked in [Code] below, gui/singleinstance.py) neither Setup
; nor the uninstaller touches the files: an uninstall used to remove the uninstall entry and leave every
; file behind. It is checked there and not with the `AppMutex` directive because that checks once, at
; once: the in-app update starts a silent Setup and closes its window a moment later, and Setup exited 1.
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=ExtremeCompressor-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\ExtremeCompressor.exe
; The wizard and the installer file itself (assets\app.ico is made from assets\app-icon.svg by packaging\make_icon.py).
SetupIconFile=..\assets\app.ico

[Tasks]
Name: contextmenu; Description: "Add ""Compress with ExtremeCompressor"" to the Explorer right-click menu"; GroupDescription: "Explorer:"
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\ExtremeCompressor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
; The licence texts a binary release owes (PySide6 is LGPL-3.0): ours, the notices, and the LGPL/GPL texts.
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\ExtremeCompressor"; Filename: "{app}\ExtremeCompressor.exe"
Name: "{autodesktop}\ExtremeCompressor"; Filename: "{app}\ExtremeCompressor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\excmp.exe"; Parameters: "shell install"; Flags: runhidden; Tasks: contextmenu
Filename: "{app}\ExtremeCompressor.exe"; Description: "Launch ExtremeCompressor"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\excmp.exe"; Parameters: "shell uninstall"; Flags: runhidden; RunOnceId: "RemoveShellMenu"

[Code]
const
  RunningMutex = 'ExtremeCompressor-running';   // gui/singleinstance.py RUNNING_MUTEX

// A silent run (the in-app update) gives the window up to 20 s to finish closing; an interactive run
// refuses at once, as AppMutex did, and says why.
function WindowGone(const Action: String): Boolean;
var
  Waited: Integer;
begin
  Waited := 0;
  if WizardSilent() or UninstallSilent() then
    while CheckForMutexes(RunningMutex) and (Waited < 20000) do
    begin
      Sleep(250);
      Waited := Waited + 250;
    end;
  Result := not CheckForMutexes(RunningMutex);
  if not Result then
    MsgBox('ExtremeCompressor is running. Close it, then ' + Action + ' again.', mbError, MB_OK);
end;

function InitializeSetup(): Boolean;
begin
  Result := WindowGone('run Setup');
end;

function InitializeUninstall(): Boolean;
begin
  Result := WindowGone('uninstall');
end;
