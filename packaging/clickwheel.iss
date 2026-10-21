; Inno Setup script for the Windows installer:
;   iscc /DAppVersion=1.2.3 packaging\clickwheel.iss
; Packs dist\Clickwheel\ (the PyInstaller build) into Clickwheel-windows-x64-setup.exe.
; Installs per user so the built-in updater can replace the files without admin rights.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{308A95B5-B92F-4245-BBE8-200CFE1BEC69}
AppName=Clickwheel
AppVersion={#AppVersion}
AppPublisher=Clickwheel
AppPublisherURL=https://github.com/Mortify7612/clickwheel
DefaultDirName={localappdata}\Programs\Clickwheel
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..
OutputBaseFilename=Clickwheel-windows-x64-setup
SetupIconFile=icons\clickwheel.ico
UninstallDisplayIcon={app}\Clickwheel.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Clickwheel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files left over from the previous version.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Clickwheel"; Filename: "{app}\Clickwheel.exe"
Name: "{autodesktop}\Clickwheel"; Filename: "{app}\Clickwheel.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Clickwheel.exe"; Description: "{cm:LaunchProgram,Clickwheel}"; Flags: nowait postinstall skipifsilent
