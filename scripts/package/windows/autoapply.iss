; The engine of the Windows installer, built with Inno Setup 6 by scripts/make_installer.py (which passes the /D
; values below). What people see is the window in setup\Setup.cs: it carries this installer inside itself and runs it
; with /VERYSILENT, so the wizard here is only seen by someone who asks for it.
;
; Inno Setup does what an installer tool is for: where to install, shortcuts, the entry under Settings > Apps, the
; uninstaller, the log. It copies a new version into {app}\.staged and leaves the version that is installed alone.
; What only this program needs is in [Code]:
;   - it refuses to run while AutoApply is running, and says how to quit it (nothing is killed);
;   - it runs scripts\prepare.py with the uv it brought: that puts the new files in place, gets Python, the
;     dependencies and the browser, and puts the previous version back if any of it fails or is cancelled;
;   - uninstalling keeps your data unless you say otherwise.
;
; Without a window:  AutoApply-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="..." /LANG=en /TASKS="desktopicon,startmenuicon"
;                    unins000.exe /VERYSILENT /SUPPRESSMSGBOXES [/DELETEDATA]
; The exit code is 0 only when the program is ready to start.
; /STATUSDIR="folder" is where the window reads the progress and asks for a stop (see setup\Setup.cs).

#ifndef AppVersion
  #error AppVersion, Stage, OutDir and Repo are passed by scripts/make_installer.py
#endif
#ifndef AppName
  #define AppName "AutoApply"
#endif
#ifndef AppGuid
  #define AppGuid "{B6E0E7A4-3D1C-4C7E-9A52-7F1B5A6D2C31}"
#endif
#define Launcher "{app}\.venv\Scripts\pythonw.exe"
#define AppUserModel "LiamFrost.AutoApply"

[Setup]
AppId={{#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=AutoApply
AppPublisherURL=https://github.com/Liam-Frost/AutoApply
AppSupportURL=https://github.com/Liam-Frost/AutoApply/issues
AppUpdatesURL=https://github.com/Liam-Frost/AutoApply/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={code:DefaultDir}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutDir}
OutputBaseFilename={#OutName}
SetupIconFile={#Repo}\scripts\package\windows\autoapply.ico
UninstallDisplayIcon={app}\autoapply.ico
UninstallDisplayName={#AppName}
WizardStyle=modern dynamic
Compression=lzma2
SolidCompression=yes
; Python, the dependencies and the browser are downloaded after the files are copied
ExtraDiskSpaceRequired=1610612736
SetupLogging=yes
UninstallLogging=yes
CloseApplications=no
ShowLanguageDialog=auto
#ifdef Sign
SignTool=sign
SignedUninstaller=yes
#endif

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "zh"; MessagesFile: "{#Repo}\scripts\package\windows\ChineseSimplified.isl"

[CustomMessages]
en.TaskDesktop=Put a shortcut on the &desktop
zh.TaskDesktop=在桌面创建快捷方式(&D)
en.TaskStartMenu=Add AutoApply to the Start &menu
zh.TaskStartMenu=添加到开始菜单(&M)
en.TaskAutostart=Start AutoApply when I &sign in to this computer
zh.TaskAutostart=登录这台电脑时自动启动 AutoApply(&S)
en.Launch=Start AutoApply now
zh.Launch=现在启动 AutoApply
en.Running=AutoApply is running from this folder.%n%nQuit it first: right-click its icon in the tray and choose Quit. If an application is being filled in, let it finish.%n%nThen choose Retry.
zh.Running=这个文件夹里的 AutoApply 正在运行。%n%n请先退出它：右键点托盘里的图标，选“退出”。如果正在填写某份申请，等它填完。%n%n然后点“重试”。
en.RunningAbort=AutoApply is still running, so nothing was changed.
zh.RunningAbort=AutoApply 还在运行，所以什么都没有改动。
en.PrepTitle=Getting AutoApply ready
zh.PrepTitle=正在准备 AutoApply
en.PrepSub=The first time this takes a few minutes, most of it downloading. You can leave this window alone.
zh.PrepSub=第一次需要几分钟，主要是下载。这个窗口可以放在一边。
en.Step0=Getting Python...
zh.Step0=正在准备 Python…
en.Step1=Putting the new files in place...
zh.Step1=正在放置新版本的文件…
en.Step2=Installing the dependencies (about 300 MB the first time)...
zh.Step2=正在安装依赖（第一次约 300 MB）…
en.Step3=Getting the browser the program uses...
zh.Step3=正在准备程序用的浏览器…
en.Downloaded=%1%% downloaded
zh.Downloaded=已下载 %1%%
en.DownloadedPart=Download %2: %1%%
zh.DownloadedPart=第 %2 个下载：%1%%
en.Cancelling=Stopping, and putting things back...
zh.Cancelling=正在停止，并恢复原样…
en.CancelAsk=Stop the installation? What was there before is put back.
zh.CancelAsk=要停止安装吗？之前的版本会恢复原样。
en.NotFinished=AutoApply is not ready yet
zh.NotFinished=AutoApply 还没有准备好
en.Err_cancelled=You stopped the installation. If a version was installed before, it is back in place. Run setup again to continue; what was already downloaded is kept.
zh.Err_cancelled=你停止了安装。如果之前装有旧版本，它已经恢复原样。重新运行安装程序即可继续，已经下载的内容不会重新下载。
en.Err_bootstrap=Python could not be downloaded (usually the network). Nothing that was installed before was changed. Run setup again to continue.
zh.Err_bootstrap=Python 下载失败（多数是网络问题）。之前安装的内容没有被改动。重新运行安装程序即可继续。
en.Err_files=The new files could not be put in place (a file may be open in another program). The previous version is untouched.
zh.Err_files=新版本的文件放置失败（可能有文件被别的程序占用）。之前的版本没有被改动。
en.Err_deps=The dependencies could not be installed (usually the network). Run setup again to continue; what was already downloaded is kept.
zh.Err_deps=依赖安装失败（多数是网络问题）。重新运行安装程序即可继续，已经下载的内容不会重新下载。
en.Err_deps_restored=The dependencies of the new version could not be installed (usually the network). The previous version was put back and works. Run setup again to upgrade.
zh.Err_deps_restored=新版本的依赖安装失败（多数是网络问题）。之前的版本已经恢复，可以照常使用。重新运行安装程序即可升级。
en.Err_deps_broken=The dependencies could not be installed, and the previous version's could not be restored. Your data is untouched. Run setup again when the network works.
zh.Err_deps_broken=依赖安装失败，旧版本的依赖也没能恢复。你的数据没有被改动。请在网络正常时重新运行安装程序。
en.Err_browser=The browser the program uses could not be downloaded (usually the network). Everything else is installed. Run setup again to finish.
zh.Err_browser=程序用的浏览器下载失败（多数是网络问题）。其余部分已经装好。重新运行安装程序即可完成。
en.Err_browser_libs=The browser the program uses was downloaded but cannot start. The log has the details.
zh.Err_browser_libs=程序用的浏览器已经下载，但启动不了。详细情况在日志里。
en.SeeLog=The details are in:%n%1
zh.SeeLog=详细记录在：%n%1
en.DeleteData=Also delete your data - your profile, documents, applications and saved sign-ins?%n%nChoose No to keep them in the program folder: installing AutoApply there again finds them.
zh.DeleteData=同时删除你的数据吗？包括个人资料、文档、投递记录和保存的登录状态。%n%n选“否”会把它们留在程序文件夹里，以后重新安装到同一位置还能用。

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"
Name: "startmenuicon"; Description: "{cm:TaskStartMenu}"
Name: "autostart"; Description: "{cm:TaskAutostart}"; Flags: unchecked

[Files]
Source: "{#Stage}\app\*"; DestDir: "{app}\.staged"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Stage}\uv.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "{#Repo}\scripts\package\windows\autoapply.ico"; DestDir: "{app}"; Flags: ignoreversion
; the window without an installer inside: what Settings > Apps starts to remove the program
Source: "{#Stage}\AutoApplySetup.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#Launcher}"; Parameters: "-m autoapply.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\autoapply.ico"; AppUserModelID: "{#AppUserModel}"; Comment: "{#AppName}"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{#Launcher}"; Parameters: "-m autoapply.launcher"; WorkingDir: "{app}"; IconFilename: "{app}\autoapply.ico"; AppUserModelID: "{#AppUserModel}"; Comment: "{#AppName}"; Tasks: desktopicon

[Registry]
; the same entry the tray icon's "Start when I sign in" writes and removes
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{#Launcher}"" -m autoapply.launcher"; Tasks: autostart

[Run]
Filename: "{#Launcher}"; Parameters: "-m autoapply.launcher"; WorkingDir: "{app}"; Description: "{cm:Launch}"; Flags: nowait postinstall skipifsilent; Check: Ready

[Code]
var
  Page: TOutputMarqueeProgressWizardPage;
  Outcome, PrepLog: String;       { Outcome: '' until the second half ran, then 'ok', 'cancelled' or an error code }
  CancelFile: String;
  WasCancel: TNotifyEvent;

function DefaultDir(Param: String): String;
var
  Old: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\{#AppName}');
#ifndef TestBuild
  { versions up to 1.0.3 were registered by their own script, under this key }
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoApply', 'InstallLocation', Old) and DirExists(Old) then
    Result := Old;
#endif
end;

function Ready: Boolean;
begin
  Result := Outcome = 'ok';
end;

function Like(S: String): String;
{ a path as a WQL LIKE pattern: the backslash doubled, the pattern characters taken literally }
begin
  StringChangeEx(S, '[', '[[]', True);
  StringChangeEx(S, '_', '[_]', True);
  StringChangeEx(S, '%', '[%]', True);
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '''', '\''', True);
  Result := S;
end;

function Running(Dir: String): Boolean;
{ Is a program running out of this folder's environment? Asked of Windows; nothing is stopped. }
var
  Locator, Services, Found: Variant;
begin
  Result := False;
  if not DirExists(Dir + '\.venv') then
    exit;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('.', 'root\CIMV2');
    Found := Services.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE ExecutablePath LIKE ''' + Like(Dir + '\.venv\') + '%''');
    Result := Found.Count > 0;
  except
    Log('Could not ask Windows which programs are running: ' + GetExceptionMessage);
  end;
end;

function WaitUntilQuit(Dir: String): Boolean;
begin
  Result := True;
  while Running(Dir) do
    if SuppressibleMsgBox(CustomMessage('Running'), mbError, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then begin
      Result := False;
      exit;
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not WaitUntilQuit(ExpandConstant('{app}')) then
    Result := CustomMessage('RunningAbort');
end;

procedure InitializeWizard;
begin
  Page := CreateOutputMarqueeProgressPage(CustomMessage('PrepTitle'), CustomMessage('PrepSub'));
end;

procedure CancelClicked(Sender: TObject);
begin
  if (CancelFile <> '') and not FileExists(CancelFile) then
    if SuppressibleMsgBox(CustomMessage('CancelAsk'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then begin
      SaveStringToFile(CancelFile, 'x', False);
      Page.SetText(CustomMessage('Cancelling'), '');
    end;
end;

procedure Prepare;
{ The second half: scripts\prepare.py, started with the uv that came in this package, watched through two small files. }
var
  App, Uv, Script, Status, Done, Params: String;
  Text: AnsiString;
  Code, Step, Pct, Part, P: Integer;
  Rest: String;
begin
  App := ExpandConstant('{app}');
  Uv := App + '\tools\uv.exe';
  Script := App + '\.staged\scripts\prepare.py';
  Status := ExpandConstant('{param:STATUSDIR|{tmp}}') + '\prepare.status';
  Done := ExpandConstant('{param:STATUSDIR|{tmp}}') + '\prepare.done';
  CancelFile := ExpandConstant('{param:STATUSDIR|{tmp}}') + '\prepare.cancel';
  SaveStringToFile(Status, '0 -1 0', False);        { getting Python: prepare.py writes the rest }
  ForceDirectories(App + '\data\logs');
  PrepLog := App + '\data\logs\setup-' + GetDateTimeString('yyyymmdd-hhnnss', #0, #0) + '.log';
  { cmd only so that a uv that cannot even get Python leaves a result (prepare.py writes its own) and what uv said
    about it is kept, in a file of its own: prepare.py's log cannot be open twice }
  Params := '/d /c ""' + Uv + '" run --no-project --python 3.12 "' + Script + '" --root "' + App + '" --staged "' + App + '\.staged" --uv "' + Uv +
            '" --status "' + Status + '" --done "' + Done + '" --cancel "' + CancelFile + '" --log "' + PrepLog + '" >> "' + ChangeFileExt(PrepLog, '') + '-start.log" 2>&1 || if not exist "' + Done + '" (echo error bootstrap> "' + Done + '")"';
  Log('Starting: ' + Params);
  Page.SetText(CustomMessage('Step0'), '');
  Page.Show;
  WasCancel := WizardForm.CancelButton.OnClick;
  WizardForm.CancelButton.OnClick := @CancelClicked;
  WizardForm.CancelButton.Visible := True;
  WizardForm.CancelButton.Enabled := True;
  try
    if not Exec(ExpandConstant('{cmd}'), Params, App, SW_HIDE, ewNoWait, Code) then begin
      Outcome := 'bootstrap';
      Log('Could not start it: ' + SysErrorMessage(Code));
      exit;
    end;
    Step := 0;
    Pct := -1;
    Part := 0;
    while not FileExists(Done) do begin
      if LoadStringFromFile(Status, Text) then begin
        P := Pos(' ', Text);
        if P > 1 then begin
          Step := StrToIntDef(Copy(Text, 1, P - 1), Step);
          Rest := Trim(Copy(Text, P + 1, 20));
          P := Pos(' ', Rest);
          if P > 1 then begin
            Pct := StrToIntDef(Copy(Rest, 1, P - 1), -1);
            Part := StrToIntDef(Trim(Copy(Rest, P + 1, 8)), 0);
          end;
        end;
      end;
      if not FileExists(CancelFile) then begin
        if (Pct >= 0) and (Part > 1) then
          Page.SetText(CustomMessage('Step' + IntToStr(Step)), FmtMessage(CustomMessage('DownloadedPart'), [IntToStr(Pct), IntToStr(Part)]))
        else if Pct >= 0 then
          Page.SetText(CustomMessage('Step' + IntToStr(Step)), FmtMessage(CustomMessage('Downloaded'), [IntToStr(Pct)]))
        else
          Page.SetText(CustomMessage('Step' + IntToStr(Step)), '');
      end;
      { a percentage where the tool reports one (the browser); otherwise a moving bar: it says "working", not "how far" }
      if Pct >= 0 then begin
        Page.ProgressBar.Style := npbstNormal;
        Page.ProgressBar.Max := 100;
        Page.ProgressBar.Position := Pct;
      end else
        Page.ProgressBar.Style := npbstMarquee;
      Page.Animate;       { also lets the window answer: the Cancel button, moving it }
      Sleep(100);
    end;
    Sleep(200);
    if LoadStringFromFile(Done, Text) then begin
      Outcome := Trim(Text);
      if Pos('error ', Outcome) = 1 then
        Outcome := Copy(Outcome, 7, 40);
    end else
      Outcome := 'files';
    Log('The second half ended: ' + Outcome);
  finally
    WizardForm.CancelButton.OnClick := WasCancel;
    CancelFile := '';
    Page.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  App, Lang: String;
begin
  if CurStep <> ssPostInstall then
    exit;
  App := ExpandConstant('{app}');
  { Settings > Apps starts the window, on its remove page; a silent removal still goes to the uninstaller itself }
  RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1', 'UninstallString', '"' + App + '\AutoApplySetup.exe" /uninstall');
  { a box that was unticked takes away what an earlier installation put there }
  if not WizardIsTaskSelected('desktopicon') then DeleteFile(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
  if not WizardIsTaskSelected('startmenuicon') then DeleteFile(ExpandConstant('{autoprograms}\{#AppName}.lnk'));
  if not WizardIsTaskSelected('autostart') then RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
  Prepare;
  if Outcome = 'ok' then begin
    if not FileExists(App + '\data\app.db') then begin       { a first installation: the program starts in the language chosen here }
      if ActiveLanguage = 'zh' then Lang := 'zh' else Lang := 'en';
      SaveStringToFile(App + '\data\ui-lang.txt', Lang, False);
    end;
#ifndef TestBuild
    { the registration of versions up to 1.0.3: this installer has its own, and two entries would show under Apps }
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoApply');
#endif
  end else
    SuppressibleMsgBox(CustomMessage('Err_' + Outcome) + #13#10#13#10 + FmtMessage(CustomMessage('SeeLog'), [PrepLog]), mbError, MB_OK, IDOK);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and (Outcome <> 'ok') and (Outcome <> '') then begin
    WizardForm.FinishedHeadingLabel.Caption := CustomMessage('NotFinished');
    WizardForm.FinishedLabel.Caption := CustomMessage('Err_' + Outcome) + #13#10#13#10 + FmtMessage(CustomMessage('SeeLog'), [PrepLog]);
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if (Outcome = 'ok') or (Outcome = '') then Result := 0
  else if Outcome = 'cancelled' then Result := 2
  else Result := 1;
end;

procedure DeinitializeSetup;
var
  App: String;
begin
  { the installer's own log is written to the temporary folder, which Windows clears: keep a copy with the data }
  App := WizardDirValue;
  if (Outcome <> '') and DirExists(App + '\data\logs') then
    CopyFile(ExpandConstant('{log}'), App + '\data\logs\setup-' + GetDateTimeString('yyyymmdd-hhnnss', #0, #0) + '-installer.log', False);
end;

{ --- removing --- }

var
  DeleteData: Boolean;

function InitializeUninstall: Boolean;
begin
  Result := WaitUntilQuit(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App: String;
  Rec: TFindRec;
begin
  App := ExpandConstant('{app}');
  if CurUninstallStep = usUninstall then begin
    DeleteData := Pos('/DELETEDATA', Uppercase(GetCmdTail)) > 0;
    if not DeleteData and DirExists(App + '\data') then
      DeleteData := SuppressibleMsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  end;
  if CurUninstallStep = usPostUninstall then begin
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    { the program's files were put in place by prepare.py, not by Setup: everything goes except what is yours }
    if FindFirst(App + '\*', Rec) then
      try
        repeat
          if (Rec.Name <> '.') and (Rec.Name <> '..') and (Pos('unins', Lowercase(Rec.Name)) <> 1) and
             (DeleteData or ((CompareText(Rec.Name, 'data') <> 0) and (CompareText(Rec.Name, 'knowledge') <> 0))) then begin
            if Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then begin
              if not DelTree(App + '\' + Rec.Name, True, True, True) then
                Log('Could not remove ' + Rec.Name);
            end else if not DeleteFile(App + '\' + Rec.Name) then
              Log('Could not remove ' + Rec.Name);
          end;
        until not FindNext(Rec);
      finally
        FindClose(Rec);
      end;
    if DeleteData then
      RemoveDir(App);
  end;
end;
