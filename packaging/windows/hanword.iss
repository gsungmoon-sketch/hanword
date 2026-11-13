; hanword Windows installer (Inno Setup 6).
;
; Build (from the repository root, after `python packaging\build.py` and fetching WinSW):
;   iscc /DAppVersion=0.1.0 packaging\windows\hanword.iss
; -> dist\hanword-<ver>-windows-x64-setup.exe
;
; What it does
;   - program        : C:\Program Files\hanword\hanword.exe  (per-machine, admin)
;   - data           : %ProgramData%\hanword\documents (ACL: SYSTEM, Administrators, LOCAL SERVICE only),
;                      service logs in %ProgramData%\hanword\logs
;   - Windows service: id "hanword" via WinSW (hanword-service.exe + generated .xml), runs as
;                      NT AUTHORITY\LocalService, starts automatically,
;                      `hanword.exe serve --host 127.0.0.1 --port 8088 --data <documents>`
;   - Start menu     : "hanword 열기" (http://127.0.0.1:8088/), 제거
;   - uninstall      : removes program + service; keeps documents unless the user answers "yes"
;                      (silent: pass /PURGEDATA to delete them too)
; No firewall rule is added: the local (save/load) mode has no login and only listens on 127.0.0.1,
; so nothing from the network can reach it anyway.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef BundleDir
  #define BundleDir "..\..\dist\hanword"
#endif
#ifndef WinSWDir
  #define WinSWDir "..\..\build\winsw"
#endif
#ifndef OutDir
  #define OutDir "..\..\dist"
#endif
#define AppName "hanword"
#define SvcName "hanword"
#define Port "8088"

[Setup]
AppId={{3F1C2B7E-8D4A-4E59-9B61-5A2E7C0D9F14}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=hanword contributors
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename=hanword-{#AppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile={#BundleDir}\LICENSE.txt
UninstallDisplayIcon={app}\hanword.exe
UninstallDisplayName={#AppName} {#AppVersion}
CloseApplications=no
SetupLogging=yes

[Languages]
#if FileExists(AddBackslash(CompilerPath) + "Languages\Korean.isl")
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
OpenEditor=한워드 열기 (http://127.0.0.1:{#Port}/) / Open hanword
PurgeAsk=문서도 삭제하시겠습니까?%n%n%1%n%n저장한 문서가 모두 지워지며 되돌릴 수 없습니다. [아니요]를 누르면 문서는 남고, 다시 설치하면 그대로 이어서 씁니다.%n%nAlso delete all saved documents? This cannot be undone. Choose No to keep them.
SvcFail=서비스 시작에 실패했습니다. 로그를 확인하세요: %1%n%nThe hanword service failed to start. See the logs in: %1

[Dirs]
Name: "{commonappdata}\{#AppName}"; Flags: uninsneveruninstall
Name: "{commonappdata}\{#AppName}\documents"; Flags: uninsneveruninstall
Name: "{commonappdata}\{#AppName}\logs"; Flags: uninsneveruninstall

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WinSWDir}\WinSW.NET461.exe"; DestDir: "{app}"; DestName: "hanword-service.exe"; Flags: ignoreversion
Source: "{#WinSWDir}\LICENSE.txt"; DestDir: "{app}"; DestName: "WinSW-LICENSE.txt"; Flags: ignoreversion

[INI]
Filename: "{group}\hanword 열기.url"; Section: "InternetShortcut"; Key: "URL"; String: "http://127.0.0.1:{#Port}/"

[Icons]
Name: "{group}\설명서 (Manual)"; Filename: "{app}\manual\index.html"; Check: ManualExists
Name: "{group}\{#AppName} 제거 (Uninstall)"; Filename: "{uninstallexe}"

[Run]
Filename: "http://127.0.0.1:{#Port}/"; Description: "{cm:OpenEditor}"; Flags: shellexec postinstall nowait skipifsilent

[UninstallDelete]
Type: files; Name: "{group}\hanword 열기.url"
Type: files; Name: "{app}\hanword-service.xml"
Type: files; Name: "{app}\*.log"
Type: dirifempty; Name: "{app}"

[Code]
var
  PurgeData: Boolean;

function ManualExists: Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\manual\index.html'));
end;

function RunCmd(const FileName, Params: String): Integer;
var
  Code: Integer;
begin
  if not Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  Log(Format('exec: %s %s -> %d', [FileName, Params, Code]));
  Result := Code;
end;

function Sc(const Params: String): Integer;
begin
  Result := RunCmd(ExpandConstant('{sys}\sc.exe'), Params);
end;

function ServiceExists: Boolean;
begin
  Result := Sc('query {#SvcName}') = 0;
end;

procedure StopService;
begin
  if ServiceExists then
    RunCmd(ExpandConstant('{sys}\net.exe'), 'stop {#SvcName}');  { net stop waits until stopped }
end;

function XmlEsc(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '&', '&amp;', True);
  StringChangeEx(Result, '<', '&lt;', True);
  StringChangeEx(Result, '>', '&gt;', True);
  StringChangeEx(Result, '"', '&quot;', True);
end;

procedure WriteServiceXml;
var
  Data, Docs, Xml: String;
begin
  Data := ExpandConstant('{commonappdata}\{#AppName}');
  Docs := Data + '\documents';
  Xml :=
    '<service>' + #13#10 +
    '  <id>{#SvcName}</id>' + #13#10 +
    '  <name>hanword</name>' + #13#10 +
    '  <description>hanword web word processor, local mode on 127.0.0.1:{#Port} (documents: ' + XmlEsc(Docs) + ')</description>' + #13#10 +
    '  <executable>' + XmlEsc(ExpandConstant('{app}\hanword.exe')) + '</executable>' + #13#10 +
    '  <arguments>serve --host 127.0.0.1 --port {#Port} --data &quot;' + XmlEsc(Docs) + '&quot;</arguments>' + #13#10 +
    '  <workingdirectory>' + XmlEsc(Data) + '</workingdirectory>' + #13#10 +
    '  <env name="PYTHONIOENCODING" value="utf-8"/>' + #13#10 +
    '  <startmode>Automatic</startmode>' + #13#10 +
    '  <stoptimeout>15 sec</stoptimeout>' + #13#10 +
    '  <onfailure action="restart" delay="5 sec"/>' + #13#10 +
    '  <onfailure action="restart" delay="30 sec"/>' + #13#10 +
    '  <resetfailure>1 hour</resetfailure>' + #13#10 +
    '  <logpath>' + XmlEsc(Data + '\logs') + '</logpath>' + #13#10 +
    '  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>8</keepFiles></log>' + #13#10 +
    '</service>' + #13#10;
  if not SaveStringToFile(ExpandConstant('{app}\hanword-service.xml'), Xml, False) then
    RaiseException('cannot write service configuration');
end;

procedure LockDownDataDir;
var
  Data: String;
begin
  Data := ExpandConstant('{commonappdata}\{#AppName}');
  { SIDs, not names, so it works on every Windows display language:
    S-1-5-18 = SYSTEM, S-1-5-32-544 = Administrators, S-1-5-19 = LOCAL SERVICE }
  RunCmd(ExpandConstant('{sys}\icacls.exe'), '"' + Data + '" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F ' +
      '*S-1-5-32-544:(OI)(CI)F *S-1-5-19:(OI)(CI)M /T /C /Q');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopService;  { upgrade: release the files before they are replaced }
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Svc: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Svc := ExpandConstant('{app}\hanword-service.exe');
  WriteServiceXml;
  LockDownDataDir;
  if not ServiceExists then
    if RunCmd(Svc, 'install') <> 0 then
      RaiseException('service registration failed (see setup log)');
  { least privilege: built-in LOCAL SERVICE account instead of LocalSystem }
  Sc('config {#SvcName} obj= "NT AUTHORITY\LocalService" password= ""');
  if RunCmd(ExpandConstant('{sys}\net.exe'), 'start {#SvcName}') <> 0 then
  begin
    if not WizardSilent then
      MsgBox(FmtMessage(CustomMessage('SvcFail'), [ExpandConstant('{commonappdata}\{#AppName}\logs')]), mbError, MB_OK)
    else
      Log('service failed to start');
  end
  else
    Sleep(1500);  { give the server a moment before the browser opens }
end;

function HasParam(const P: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), P) = 0 then
      Result := True;
end;

function InitializeUninstall: Boolean;
var
  Data: String;
begin
  Data := ExpandConstant('{commonappdata}\{#AppName}');
  if UninstallSilent then
    PurgeData := HasParam('/PURGEDATA')
  else
    PurgeData := MsgBox(FmtMessage(CustomMessage('PurgeAsk'), [Data]), mbConfirmation,
                        MB_YESNO or MB_DEFBUTTON2) = IDYES;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Svc: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    StopService;
    Svc := ExpandConstant('{app}\hanword-service.exe');
    if ServiceExists then
      if RunCmd(Svc, 'uninstall') <> 0 then
        Sc('delete {#SvcName}');
  end;
  if (CurUninstallStep = usPostUninstall) and PurgeData then
    DelTree(ExpandConstant('{commonappdata}\{#AppName}'), True, True, True);
end;
