# AutoApply setup for Windows: one window that installs, upgrades, repairs or removes the program.
#
#   -Mode install    started by AutoApply-Setup.exe (the package is next to this script: app.zip, version.txt, logo.png)
#   -Mode uninstall  started from Settings > Apps, or by hand from the program folder
#
# Per user: no administrator rights, nothing outside the user's profile. An upgrade never touches data\ and knowledge\.
# The window is drawn to the program's design system (docs/DESIGN_SYSTEM.md): same colours, radii, type scale, buttons.
#
# For checking without clicking:  -Silent (do the work without a window)   -NoIntegrate (no shortcuts, registry, launch)
#                                 -Shot <png> -Page <welcome|existing|progress|done|failed|uninstall> (draw one page to a file)
#                                 -Auto (open the real window, press its main button, wait for the result, save -Shot, close)
param(
  [ValidateSet('install', 'uninstall')][string]$Mode = 'install',
  [string]$Dir = '',
  [switch]$Silent, [switch]$NoIntegrate, [switch]$DeleteData, [switch]$Moved,
  [string]$Shot = '', [string]$Page = '', [switch]$Dark, [switch]$Auto,
  [ValidateSet('', 'zh', 'en')][string]$Lang = ''
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
# Language: follows the system - Chinese (Simplified or Traditional systems alike) shows Chinese, every other language English -
# and can be switched in the window. "The system is Chinese" means any of its language settings is (display language,
# regional format, system locale): many Chinese-speaking users run Windows with an English display language.
$zh = [bool](@((Get-UICulture).Name, (Get-Culture).Name, [Globalization.CultureInfo]::InstalledUICulture.Name) | Where-Object { $_ -like 'zh*' })
try { if ((Get-WinSystemLocale).Name -like 'zh*') { $zh = $true } } catch { }
if ($Lang) { $zh = ($Lang -eq 'zh') }
$script:zh = $zh
function T([string]$cn, [string]$en) { if ($script:zh) { $cn } else { $en } }
$RegKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoApply'
$DefaultDir = Join-Path $env:LOCALAPPDATA 'Programs\AutoApply'
$LogFile = Join-Path ([IO.Path]::GetTempPath()) 'autoapply-setup.log'

function Get-Version([string]$d) {
  $pp = Join-Path $d 'pyproject.toml'
  if (-not (Test-Path $pp)) { return $null }
  if (-not (Select-String -Path $pp -Pattern '^name\s*=\s*"autoapply"' -Quiet)) { return $null }
  $m = Select-String -Path $pp -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
  if ($m) { return $m.Matches[0].Groups[1].Value } else { return '?' }
}
function Get-Installed {
  # where a copy is installed, by the entry under Settings > Apps, else the usual place
  $d = $null
  try { $d = (Get-ItemProperty $RegKey -ErrorAction Stop).InstallLocation } catch { }
  foreach ($c in @($d, $DefaultDir)) { if ($c) { $v = Get-Version $c; if ($v) { return @{ Dir = $c; Version = $v } } } }
  return $null
}

# ------------------------------------------------------------------------------------------------
# The work. These run either here (-Silent) or in a second runspace while the window stays responsive;
# they talk to the window only through $s (a synchronised table): Step, Line, Done, Error.
# ------------------------------------------------------------------------------------------------
$Work = {
  param($s, $o)
  $ErrorActionPreference = 'Continue'      # tools write progress to stderr; failure is judged by exit codes
  function Note([string]$t) { $s.Line = $t; Add-Content -Path $o.Log -Value ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $t) -Encoding UTF8 }
  function Run([string]$exe, [string[]]$a, [string]$cwd) {
    Note ("> $exe " + ($a -join ' '))
    Push-Location $cwd
    try { & $exe @a 2>&1 | ForEach-Object { $t = "$_".Trim(); if ($t) { Note $t } } } finally { Pop-Location }
    return $LASTEXITCODE
  }
  function Stop-Copy([string]$dir) {
    $needle = $dir.ToLower()
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) -and $_.Name -match '^(python|pythonw|uv|autoapply|node)' } |
      ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Note "stopped $($_.Name) $($_.ProcessId)" } catch { } }
    Start-Sleep -Milliseconds 1500
  }
  try {
    Set-Content -Path $o.Log -Value ("AutoApply setup: {0} -> {1}" -f $o.Mode, $o.Target) -Encoding UTF8
    $target = $o.Target
    if ($o.Mode -eq 'uninstall') {
      $s.Step = 0; Stop-Copy $target
      $s.Step = 1
      Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'AutoApply' -ErrorAction SilentlyContinue
      foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        $lnk = Join-Path $d 'AutoApply.lnk'; if ((Test-Path $lnk) -and -not $o.NoIntegrate) { Remove-Item $lnk -Force; Note "removed $lnk" }
      }
      if (-not $o.NoIntegrate) { Remove-Item -Path $o.RegKey -Recurse -Force -ErrorAction SilentlyContinue }
      $s.Step = 2
      if ($o.DeleteData) { Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue; Note 'removed everything' }
      else {
        Get-ChildItem -Force $target | Where-Object { $_.Name -notin @('data', 'knowledge') } | ForEach-Object { Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue }
        Note 'removed the program; data and knowledge kept'
      }
      $s.Step = 3; $s.Done = $true; return
    }

    # --- install / upgrade / repair ---
    $s.Step = 0
    if (Test-Path (Join-Path $target 'pyproject.toml')) { Stop-Copy $target }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ('autoapply-setup-' + [Guid]::NewGuid().ToString('N'))
    Expand-Archive -Path $o.Zip -DestinationPath $tmp -Force
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $src -or -not (Test-Path (Join-Path $src.FullName 'pyproject.toml'))) { throw 'The package content is not what was expected.' }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($old in @('backend', 'frontend', 'scripts')) { $p = Join-Path $target $old; if (Test-Path $p) { Remove-Item -Recurse -Force $p } }   # replaced whole: no leftovers of an older version
    Copy-Item -Path (Join-Path $src.FullName '*') -Destination $target -Recurse -Force
    Remove-Item -Recurse -Force $tmp
    Note 'program files copied'

    $s.Step = 1
    $uvDir = Join-Path $env:USERPROFILE '.local\bin'
    if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $uvDir 'uv.exe'))) { $env:PATH = "$uvDir;$env:PATH" }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
      Note 'downloading uv from astral.sh'
      [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
      Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
      $env:PATH = "$uvDir;$env:PATH"
      if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv could not be installed (see the log).' }
    }
    $uv = (Get-Command uv).Source

    $s.Step = 2
    if ((Run $uv @('sync', '--inexact') $target) -ne 0) { throw 'Installing Python and the dependencies failed (usually the network). Run setup again to continue where it stopped.' }

    $s.Step = 3
    if (-not (Test-Path (Join-Path $env:LOCALAPPDATA 'ms-playwright'))) {
      if ((Run $uv @('run', 'playwright', 'install', 'chromium') $target) -ne 0) { throw 'Downloading the browser failed. Run setup again to continue.' }
    } else { Note 'the browser is already there' }

    $s.Step = 4
    $langFile = Join-Path $target 'data\ui-lang.txt'
    New-Item -ItemType Directory -Force -Path (Join-Path $target 'data') | Out-Null
    if (-not (Test-Path (Join-Path $target 'data\app.db'))) { Set-Content -Path $langFile -Value $o.Lang -Encoding ASCII }   # a first install: the program starts in the language chosen here
    $py = Join-Path $target '.venv\Scripts\python.exe'
    [void](Run $py @('-c', "from autoapply import launcher, config; launcher.make_icon('plain').save(config.DATA / 'autoapply.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])") $target)
    if (-not $o.NoIntegrate) {
      $folders = @()
      if ($o.Desktop) { $folders += [Environment]::GetFolderPath('Desktop') }
      if ($o.StartMenu) { $folders += [Environment]::GetFolderPath('Programs') }
      if ($folders.Count) { [void](Run $py (@('-c', 'import sys; from autoapply import launcher; print(launcher.create_shortcut(sys.argv[1:]))') + $folders) $target) }
      if (-not $o.Desktop) { $l = Join-Path ([Environment]::GetFolderPath('Desktop')) 'AutoApply.lnk'; if (Test-Path $l) { Remove-Item $l -Force } }
      if (-not $o.StartMenu) { $l = Join-Path ([Environment]::GetFolderPath('Programs')) 'AutoApply.lnk'; if (Test-Path $l) { Remove-Item $l -Force } }
      [void](Run $py @('-c', ('from autoapply import launcher; launcher.set_autostart({0})' -f $(if ($o.Autostart) { 'True' } else { 'False' }))) $target)
      New-Item -Path $o.RegKey -Force | Out-Null
      $un = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $target 'scripts\setup.ps1') + '" -Mode uninstall'
      $size = [int]((Get-ChildItem $target -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
      Set-ItemProperty $o.RegKey -Name DisplayName -Value 'AutoApply'
      Set-ItemProperty $o.RegKey -Name DisplayVersion -Value $o.Version
      Set-ItemProperty $o.RegKey -Name Publisher -Value 'AutoApply'
      Set-ItemProperty $o.RegKey -Name InstallLocation -Value $target
      Set-ItemProperty $o.RegKey -Name DisplayIcon -Value (Join-Path $target 'data\autoapply.ico')
      Set-ItemProperty $o.RegKey -Name UninstallString -Value $un
      Set-ItemProperty $o.RegKey -Name EstimatedSize -Value $size -Type DWord
      Set-ItemProperty $o.RegKey -Name NoModify -Value 1 -Type DWord
      Set-ItemProperty $o.RegKey -Name NoRepair -Value 1 -Type DWord
    }
    $s.Step = 5; $s.Done = $true
  } catch {
    Note ("ERROR: " + $_.Exception.Message)
    $s.Error = $_.Exception.Message
    $s.Done = $true
  }
}

function New-Options([string]$target) {
  $ver = '0'
  $vf = Join-Path $here 'version.txt'
  if (Test-Path $vf) { $ver = (Get-Content $vf -Raw).Trim() } elseif (Get-Version (Split-Path -Parent $here)) { $ver = Get-Version (Split-Path -Parent $here) } elseif (Get-Version $target) { $ver = Get-Version $target }
  return @{ Mode = $Mode; Target = $target; Zip = (Join-Path $here 'app.zip'); Version = $ver; Log = $LogFile; RegKey = $RegKey; NoIntegrate = [bool]$NoIntegrate
            DeleteData = [bool]$DeleteData; Desktop = $true; StartMenu = $true; Autostart = $false; Lang = $(if ($script:zh) { 'zh' } else { 'en' }) }
}

# an uninstall cannot delete the folder its own script is running from: carry on from a copy in the temp folder
if ($Mode -eq 'uninstall' -and -not $Moved -and -not $Shot -and -not $Auto) {
  if (-not $Dir) { $Dir = Split-Path -Parent $here }
  if (-not (Get-Version $Dir)) { [Console]::Error.WriteLine("Not an AutoApply installation: $Dir"); exit 1 }
  $copy = Join-Path ([IO.Path]::GetTempPath()) 'autoapply-setup-run.ps1'
  Copy-Item $MyInvocation.MyCommand.Path $copy -Force
  $logo = Join-Path $Dir 'frontend\dist\favicon.png'
  if (Test-Path $logo) { Copy-Item $logo (Join-Path ([IO.Path]::GetTempPath()) 'logo.png') -Force }
  $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$copy`"", '-Mode', 'uninstall', '-Dir', "`"$Dir`"", '-Moved')
  if ($Silent) { $a += '-Silent' } else { $a = @('-WindowStyle', 'Hidden') + $a }
  if ($NoIntegrate) { $a += '-NoIntegrate' }
  if ($DeleteData) { $a += '-DeleteData' }
  if ($Lang) { $a += @('-Lang', $Lang) }
  $p = Start-Process powershell.exe -ArgumentList $a -PassThru -Wait:$Silent
  if ($Silent) { exit $p.ExitCode } else { exit 0 }
}

if ($Silent) {
  $target = if ($Dir) { $Dir } elseif ($Mode -eq 'install') { $DefaultDir } else { Split-Path -Parent $here }
  $s = [hashtable]::Synchronized(@{ Step = 0; Line = ''; Done = $false; Error = '' })
  & $Work $s (New-Options $target)
  if ($s.Error) { Write-Output "FAILED: $($s.Error)"; exit 1 }
  Write-Output "OK: $Mode $target (log: $LogFile)"
  exit 0
}

# ------------------------------------------------------------------------------------------------
# The window
# ------------------------------------------------------------------------------------------------
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms

$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\AutoApplySetup', [ref]$created)
if (-not $created -and -not $Shot -and -not $Auto) {
  [void][System.Windows.MessageBox]::Show((T 'AutoApply 的安装程序已经在运行了，请看任务栏。' 'AutoApply setup is already running - look at the taskbar.'), 'AutoApply')
  exit 0
}

$dark = [bool]$Dark
if (-not $Dark -and -not $Shot) { try { $dark = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize').AppsUseLightTheme -eq 0 } catch { } }
# the tokens of frontend/src/style.css
$tok = if ($dark) {
  @{ surface = '#151d29'; surface2 = '#1c2634'; bg = '#0d131c'; border = '#273244'; borderStrong = '#3a475c'; text = '#e7ecf3'; text2 = '#a3b0c2'; text3 = '#75839a'
     primary = '#6f9bff'; primaryHover = '#8aadff'; primarySoft = '#1b2a4d'; onPrimary = '#0b1424'; ok = '#6fd3a0'; okSoft = '#14301f'; warn = '#f0c36a'; warnSoft = '#3a2e12'
     bad = '#f29b94'; badSoft = '#3d1d1b'; neutralSoft = '#222c3b'; logoTile = '#ffffff' }
} else {
  @{ surface = '#ffffff'; surface2 = '#f0f3f7'; bg = '#f5f7fa'; border = '#e1e6ee'; borderStrong = '#c9d1dd'; text = '#14233b'; text2 = '#5a6b82'; text3 = '#8b98ab'
     primary = '#1f4fd8'; primaryHover = '#1a43ba'; primarySoft = '#e8eeff'; onPrimary = '#ffffff'; ok = '#17794a'; okSoft = '#e2f4ea'; warn = '#9a5b00'; warnSoft = '#fff1d6'
     bad = '#b3261e'; badSoft = '#fde8e6'; neutralSoft = '#edf0f5'; logoTile = 'Transparent' }
}

$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="AutoApply" Width="680" Height="500" WindowStyle="None" AllowsTransparency="True" Background="Transparent" ResizeMode="NoResize"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI, Microsoft YaHei UI" FontSize="14" Foreground="{{text}}" UseLayoutRounding="True" TextOptions.TextFormattingMode="Display">
  <Window.Resources>
    <Style x:Key="Btn" TargetType="Button">
      <Setter Property="Foreground" Value="{{text}}"/><Setter Property="Background" Value="{{surface}}"/><Setter Property="BorderBrush" Value="{{borderStrong}}"/>
      <Setter Property="FontWeight" Value="SemiBold"/><Setter Property="Padding" Value="16,8"/><Setter Property="Cursor" Value="Hand"/><Setter Property="MinHeight" Value="36"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border x:Name="b" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" CornerRadius="6" Padding="{TemplateBinding Padding}">
          <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/></Border>
        <ControlTemplate.Triggers>
          <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="{{surface2}}"/></Trigger>
          <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="{{text3}}"/><Setter TargetName="b" Property="Background" Value="{{neutralSoft}}"/><Setter TargetName="b" Property="BorderBrush" Value="{{neutralSoft}}"/></Trigger>
        </ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Primary" TargetType="Button" BasedOn="{StaticResource Btn}">
      <Setter Property="Foreground" Value="{{onPrimary}}"/><Setter Property="Background" Value="{{primary}}"/><Setter Property="BorderBrush" Value="{{primary}}"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button">
        <Border x:Name="b" Background="{TemplateBinding Background}" BorderBrush="{TemplateBinding BorderBrush}" BorderThickness="1" CornerRadius="6" Padding="{TemplateBinding Padding}">
          <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/></Border>
        <ControlTemplate.Triggers>
          <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="{{primaryHover}}"/><Setter TargetName="b" Property="BorderBrush" Value="{{primaryHover}}"/></Trigger>
          <Trigger Property="IsEnabled" Value="False"><Setter Property="Foreground" Value="{{text3}}"/><Setter TargetName="b" Property="Background" Value="{{neutralSoft}}"/><Setter TargetName="b" Property="BorderBrush" Value="{{neutralSoft}}"/></Trigger>
        </ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style x:Key="Danger" TargetType="Button" BasedOn="{StaticResource Btn}"><Setter Property="Foreground" Value="{{bad}}"/></Style>
    <Style x:Key="Ghost" TargetType="Button" BasedOn="{StaticResource Btn}"><Setter Property="BorderBrush" Value="Transparent"/><Setter Property="Background" Value="Transparent"/><Setter Property="Foreground" Value="{{text2}}"/></Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="{{text}}"/><Setter Property="Cursor" Value="Hand"/><Setter Property="Margin" Value="0,0,22,0"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="CheckBox">
        <StackPanel Orientation="Horizontal" Background="Transparent">
          <Border x:Name="box" Width="18" Height="18" CornerRadius="4" BorderThickness="1.5" BorderBrush="{{borderStrong}}" Background="{{surface}}" VerticalAlignment="Center">
            <Path x:Name="tick" Data="M3.5,9 L7.5,13 L14.5,5" Stroke="{{onPrimary}}" StrokeThickness="2" StrokeStartLineCap="Round" StrokeEndLineCap="Round" StrokeLineJoin="Round" Visibility="Collapsed"/></Border>
          <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/></StackPanel>
        <ControlTemplate.Triggers><Trigger Property="IsChecked" Value="True">
          <Setter TargetName="box" Property="Background" Value="{{primary}}"/><Setter TargetName="box" Property="BorderBrush" Value="{{primary}}"/><Setter TargetName="tick" Property="Visibility" Value="Visible"/></Trigger>
        </ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style TargetType="RadioButton">
      <Setter Property="Foreground" Value="{{text}}"/><Setter Property="Cursor" Value="Hand"/><Setter Property="Margin" Value="0,0,0,10"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="RadioButton">
        <StackPanel Orientation="Horizontal" Background="Transparent">
          <Grid Width="18" Height="18" VerticalAlignment="Top" Margin="0,2,0,0"><Ellipse x:Name="ring" Stroke="{{borderStrong}}" StrokeThickness="1.5" Fill="{{surface}}"/><Ellipse x:Name="dot" Width="8" Height="8" Fill="{{primary}}" Visibility="Collapsed"/></Grid>
          <ContentPresenter Margin="8,0,0,0" VerticalAlignment="Center"/></StackPanel>
        <ControlTemplate.Triggers><Trigger Property="IsChecked" Value="True"><Setter TargetName="ring" Property="Stroke" Value="{{primary}}"/><Setter TargetName="dot" Property="Visibility" Value="Visible"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
    <Style TargetType="TextBox">
      <Setter Property="Foreground" Value="{{text}}"/><Setter Property="CaretBrush" Value="{{text}}"/><Setter Property="VerticalContentAlignment" Value="Center"/>
      <Setter Property="Template"><Setter.Value><ControlTemplate TargetType="TextBox">
        <Border x:Name="b" Background="{{surface}}" BorderBrush="{{borderStrong}}" BorderThickness="1" CornerRadius="6" Padding="9,0"><ScrollViewer x:Name="PART_ContentHost" VerticalAlignment="Center"/></Border>
        <ControlTemplate.Triggers><Trigger Property="IsKeyboardFocused" Value="True"><Setter TargetName="b" Property="BorderBrush" Value="{{primary}}"/></Trigger></ControlTemplate.Triggers>
      </ControlTemplate></Setter.Value></Setter>
    </Style>
  </Window.Resources>
  <Border x:Name="Shell" Margin="18" CornerRadius="14" Background="{{surface}}" BorderBrush="{{border}}" BorderThickness="1">
    <Border.Effect><DropShadowEffect BlurRadius="28" ShadowDepth="6" Direction="270" Opacity="0.22" Color="#102040"/></Border.Effect>
    <Grid>
      <Grid.RowDefinitions><RowDefinition Height="64"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
      <!-- header: the brand, and the close button; the whole strip drags the window -->
      <Grid x:Name="Header" Background="Transparent" Margin="24,0,12,0">
        <StackPanel Orientation="Horizontal" VerticalAlignment="Center">
          <Border Width="34" Height="34" CornerRadius="8" Background="{{logoTile}}"><Image x:Name="Logo" Width="28" Height="28"/></Border>
          <TextBlock Text="AutoApply" FontSize="16" FontWeight="Bold" VerticalAlignment="Center" Margin="10,0,0,0"/>
          <Border x:Name="VerPill" CornerRadius="10" Background="{{neutralSoft}}" Padding="9,2" Margin="10,0,0,0" VerticalAlignment="Center"><TextBlock x:Name="Ver" FontSize="12" FontWeight="SemiBold" Foreground="{{text2}}"/></Border>
        </StackPanel>
        <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" VerticalAlignment="Center">
          <Border x:Name="LangSeg" CornerRadius="8" Background="{{neutralSoft}}" Padding="3" Margin="0,0,10,0" VerticalAlignment="Center">
            <StackPanel Orientation="Horizontal">
              <Border x:Name="LangZh" CornerRadius="6" Padding="10,3" Cursor="Hand"><TextBlock x:Name="LangZhT" Text="&#x4E2D;&#x6587;" FontSize="12" FontWeight="SemiBold"/></Border>
              <Border x:Name="LangEn" CornerRadius="6" Padding="10,3" Cursor="Hand"><TextBlock x:Name="LangEnT" Text="English" FontSize="12" FontWeight="SemiBold"/></Border>
            </StackPanel></Border>
          <Button x:Name="CloseBtn" Style="{StaticResource Ghost}" Content="&#x2715;" Width="36" MinHeight="32" Padding="0" VerticalAlignment="Center" FontWeight="Normal"/>
        </StackPanel>
      </Grid>

      <!-- page: choose (install / upgrade / repair) -->
      <StackPanel x:Name="PgChoose" Grid.Row="1" Margin="28,6,28,0">
        <TextBlock x:Name="ChTitle" FontSize="20" FontWeight="Bold"/>
        <TextBlock x:Name="ChSub" Foreground="{{text2}}" TextWrapping="Wrap" Margin="0,6,0,0" LineHeight="21"/>
        <Border x:Name="ExistBox" CornerRadius="10" Background="{{primarySoft}}" Padding="14,11" Margin="0,16,0,0" Visibility="Collapsed">
          <StackPanel><TextBlock x:Name="ExistHead" FontWeight="SemiBold" TextWrapping="Wrap"/><TextBlock x:Name="ExistPath" Foreground="{{text2}}" FontSize="13" TextWrapping="Wrap" Margin="0,3,0,0"/>
            <TextBlock x:Name="ExistNote" Foreground="{{text2}}" FontSize="13" TextWrapping="Wrap" Margin="0,3,0,0"/></StackPanel></Border>
        <StackPanel x:Name="PathBox" Margin="0,18,0,0">
          <TextBlock x:Name="PathLabel" FontWeight="SemiBold" FontSize="13"/>
          <Grid Margin="0,6,0,0"><Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
            <TextBox x:Name="PathText" Height="36"/><Button x:Name="BrowseBtn" Grid.Column="1" Style="{StaticResource Btn}" Margin="8,0,0,0"/></Grid>
          <TextBlock x:Name="PathHint" Foreground="{{text3}}" FontSize="12" TextWrapping="Wrap" Margin="0,6,0,0"/>
        </StackPanel>
        <StackPanel x:Name="OptBox" Orientation="Horizontal" Margin="0,18,0,0">
          <CheckBox x:Name="OptDesktop" IsChecked="True"/><CheckBox x:Name="OptStart" IsChecked="True"/><CheckBox x:Name="OptAuto"/></StackPanel>
        <TextBlock x:Name="NetNote" Foreground="{{text3}}" FontSize="12" TextWrapping="Wrap" Margin="0,16,0,0" LineHeight="18"/>
      </StackPanel>

      <!-- page: uninstall -->
      <StackPanel x:Name="PgRemove" Grid.Row="1" Margin="28,6,28,0" Visibility="Collapsed">
        <TextBlock x:Name="RmTitle" FontSize="20" FontWeight="Bold"/>
        <TextBlock x:Name="RmSub" Foreground="{{text2}}" TextWrapping="Wrap" Margin="0,6,0,18" LineHeight="21"/>
        <RadioButton x:Name="RmKeep" GroupName="rm" IsChecked="True"><StackPanel><TextBlock x:Name="RmKeepT" FontWeight="SemiBold"/><TextBlock x:Name="RmKeepD" Foreground="{{text2}}" FontSize="13" TextWrapping="Wrap" MaxWidth="540"/></StackPanel></RadioButton>
        <RadioButton x:Name="RmAll" GroupName="rm"><StackPanel><TextBlock x:Name="RmAllT" FontWeight="SemiBold" Foreground="{{bad}}"/><TextBlock x:Name="RmAllD" Foreground="{{text2}}" FontSize="13" TextWrapping="Wrap" MaxWidth="540"/></StackPanel></RadioButton>
        <TextBlock x:Name="RmNote" Foreground="{{text3}}" FontSize="12" TextWrapping="Wrap" Margin="0,10,0,0" LineHeight="18"/>
      </StackPanel>

      <!-- page: progress -->
      <StackPanel x:Name="PgWork" Grid.Row="1" Margin="28,6,28,0" Visibility="Collapsed">
        <TextBlock x:Name="WkTitle" FontSize="20" FontWeight="Bold"/>
        <TextBlock x:Name="WkSub" Foreground="{{text2}}" TextWrapping="Wrap" Margin="0,6,0,14"/>
        <StackPanel x:Name="Steps"/>
        <Border Height="6" CornerRadius="3" Background="{{neutralSoft}}" Margin="0,14,0,0"><Border x:Name="Bar" Height="6" CornerRadius="3" Background="{{primary}}" HorizontalAlignment="Left" Width="0"/></Border>
        <TextBlock x:Name="WkLine" Foreground="{{text3}}" FontSize="12" FontFamily="Cascadia Code, Consolas" TextTrimming="CharacterEllipsis" Margin="0,8,0,0"/>
      </StackPanel>

      <!-- page: result -->
      <StackPanel x:Name="PgDone" Grid.Row="1" Margin="28,22,28,0" Visibility="Collapsed">
        <Border x:Name="DoneIcon" Width="52" Height="52" CornerRadius="26" HorizontalAlignment="Left"><Path x:Name="DoneGlyph" StrokeThickness="3" StrokeStartLineCap="Round" StrokeEndLineCap="Round" StrokeLineJoin="Round" HorizontalAlignment="Center" VerticalAlignment="Center"/></Border>
        <TextBlock x:Name="DnTitle" FontSize="20" FontWeight="Bold" Margin="0,16,0,0"/>
        <TextBlock x:Name="DnSub" Foreground="{{text2}}" TextWrapping="Wrap" Margin="0,6,0,0" LineHeight="21"/>
        <CheckBox x:Name="DnLaunch" IsChecked="True" Margin="0,18,0,0"/>
      </StackPanel>

      <!-- footer: at most one primary action -->
      <Border Grid.Row="2" BorderBrush="{{border}}" BorderThickness="0,1,0,0" Padding="24,14" Margin="0,18,0,0">
        <Grid><Button x:Name="LeftBtn" Style="{StaticResource Ghost}" HorizontalAlignment="Left" Visibility="Collapsed"/>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right"><Button x:Name="SecondBtn" Style="{StaticResource Btn}" Margin="0,0,8,0" Visibility="Collapsed"/><Button x:Name="MainBtn" Style="{StaticResource Primary}" MinWidth="120"/></StackPanel></Grid></Border>
    </Grid>
  </Border>
</Window>
'@
foreach ($k in $tok.Keys) { $xaml = $xaml.Replace("{{$k}}", $tok[$k]) }
$win = [Windows.Markup.XamlReader]::Parse($xaml)
$ui = @{}
foreach ($n in ([regex]::Matches($xaml, 'x:Name="(\w+)"') | ForEach-Object { $_.Groups[1].Value })) { $ui[$n] = $win.FindName($n) }
function Brush([string]$c) { return (New-Object Windows.Media.BrushConverter).ConvertFromString($c) }

$logoFile = @((Join-Path $here 'logo.png'), (Join-Path ([IO.Path]::GetTempPath()) 'logo.png'), (Join-Path (Split-Path -Parent $here) 'frontend\dist\favicon.png'), (Join-Path (Split-Path -Parent $here) 'frontend\public\favicon.png')) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($logoFile) {
  $bmp = New-Object Windows.Media.Imaging.BitmapImage
  $bmp.BeginInit(); $bmp.CacheOption = 'OnLoad'; $bmp.UriSource = New-Object Uri($logoFile); $bmp.EndInit()
  $ui.Logo.Source = $bmp
}

$pkgVer = (New-Options $DefaultDir).Version
$inst = Get-Installed
$script:state = 'choose'         # choose | remove | work | done | failed
$script:target = if ($Dir) { $Dir } elseif ($inst) { $inst.Dir } else { $DefaultDir }
$script:sync = $null; $script:ps = $null; $script:removing = ($Mode -eq 'uninstall')
$ui.Ver.Text = if ($Mode -eq 'uninstall' -and $inst) { $inst.Version } else { $pkgVer }

function Get-InstallSteps { return @((T '复制程序文件' 'Copy the program files'), (T '准备 uv（管理 Python 环境的小工具）' 'Get uv (the tool that prepares Python)'), (T '安装 Python 和依赖' 'Install Python and the dependencies'),
                  (T '准备程序用的浏览器' 'Get the browser the program uses'), (T '创建快捷方式、登记到“应用”' 'Shortcuts and the entry under Apps')) }
function Get-RemoveSteps { return @((T '停止正在运行的 AutoApply' 'Stop AutoApply if it is running'), (T '删除快捷方式、开机启动项和“应用”里的登记' 'Remove shortcuts, the sign-in entry and the entry under Apps'), (T '删除程序文件' 'Delete the program files')) }
function Set-LangUi {
  # the segmented switch: the chosen language on the surface colour, the other one muted
  $on = Brush $tok.surface; $off = Brush 'Transparent'
  $ui.LangZh.Background = if ($script:zh) { $on } else { $off }; $ui.LangEn.Background = if ($script:zh) { $off } else { $on }
  $ui.LangZhT.Foreground = Brush $(if ($script:zh) { $tok.text } else { $tok.text2 }); $ui.LangEnT.Foreground = Brush $(if ($script:zh) { $tok.text2 } else { $tok.text })
}
function Set-Lang([bool]$chinese) {
  if ($script:zh -eq $chinese) { return }
  $script:zh = $chinese; Set-LangUi
  switch ($script:state) {     # redraw the page that is showing, in the new language; what the user has entered stays
    'choose' { $keep = $ui.PathText.Text; Enter-Choose; if (-not $inst) { $ui.PathText.Text = $keep } }
    'remove' { $all = [bool]$ui.RmAll.IsChecked; Enter-Remove; $ui.RmAll.IsChecked = $all; $ui.RmKeep.IsChecked = -not $all }
    'work' { $keepStep = [int]$script:sync.Step; Enter-Work; Set-Steps $(if ($script:removing) { Get-RemoveSteps } else { Get-InstallSteps }) $keepStep $false }
    'done' { Enter-Done '' }
    'failed' { Enter-Done $script:lastError }
  }
}

function Show-Page([string]$name) {
  foreach ($p in 'PgChoose', 'PgRemove', 'PgWork', 'PgDone') { $ui[$p].Visibility = if ($p -eq $name) { 'Visible' } else { 'Collapsed' } }
}
function Set-Steps([string[]]$labels, [int]$current, [bool]$failed) {
  $ui.Steps.Children.Clear()
  for ($i = 0; $i -lt $labels.Count; $i++) {
    $row = New-Object Windows.Controls.StackPanel; $row.Orientation = 'Horizontal'; $row.Margin = '0,0,0,9'
    $dot = New-Object Windows.Controls.Border; $dot.Width = 20; $dot.Height = 20; $dot.CornerRadius = 10; $dot.VerticalAlignment = 'Center'
    $g = New-Object Windows.Controls.TextBlock; $g.FontSize = 12; $g.FontWeight = 'Bold'; $g.HorizontalAlignment = 'Center'; $g.VerticalAlignment = 'Center'
    $lab = New-Object Windows.Controls.TextBlock; $lab.Text = $labels[$i]; $lab.Margin = '10,0,0,0'; $lab.VerticalAlignment = 'Center'
    if ($i -lt $current) { $dot.Background = Brush $tok.okSoft; $g.Text = [string][char]0x2713; $g.Foreground = Brush $tok.ok; $lab.Foreground = Brush $tok.text2 }
    elseif ($i -eq $current -and $failed) { $dot.Background = Brush $tok.badSoft; $g.Text = [string][char]0x2715; $g.Foreground = Brush $tok.bad; $lab.FontWeight = 'SemiBold' }
    elseif ($i -eq $current) { $dot.Background = Brush $tok.primary; $g.Text = [string]($i + 1); $g.Foreground = Brush $tok.onPrimary; $lab.FontWeight = 'SemiBold' }
    else { $dot.Background = Brush $tok.neutralSoft; $g.Text = [string]($i + 1); $g.Foreground = Brush $tok.text3; $lab.Foreground = Brush $tok.text3 }
    $dot.Child = $g; [void]$row.Children.Add($dot); [void]$row.Children.Add($lab); [void]$ui.Steps.Children.Add($row)
  }
  $ui.Bar.Width = [Math]::Max(0.0, [Math]::Min(1.0, [double]$current / [double]$labels.Count)) * 584.0
}

function Enter-Choose {
  $script:state = 'choose'; Show-Page 'PgChoose'
  $ui.LeftBtn.Visibility = 'Collapsed'; $ui.SecondBtn.Visibility = 'Collapsed'; $ui.MainBtn.IsEnabled = $true; $ui.CloseBtn.Visibility = 'Visible'
  $ui.OptDesktop.Content = T '添加桌面快捷方式' 'Add a desktop shortcut'; $ui.OptStart.Content = T '添加到开始菜单' 'Add to the Start menu'; $ui.OptAuto.Content = T '开机时自动启动' 'Start when I sign in'
  $ui.NetNote.Text = T '安装过程会联网下载：uv、Python 和依赖（来自 astral.sh 和 pypi.org），以及程序自己用的浏览器（Chromium）。第一次约 600 MB，需要几分钟。只装在你的用户目录里，不需要管理员权限。' 'Setup downloads uv, Python and the dependencies (from astral.sh and pypi.org) and the browser the program uses (Chromium): about 600 MB and a few minutes the first time. Everything goes into your user folder; no administrator rights are needed.'
  if ($inst) {
    $same = ($inst.Version -eq $pkgVer)
    $ui.ChTitle.Text = if ($same) { T '已经安装了 AutoApply' 'AutoApply is already installed' } else { T '升级 AutoApply' 'Upgrade AutoApply' }
    $ui.ChSub.Text = if ($same) { T '这台电脑上已经有同一个版本。可以修复它（重新复制程序文件、补齐环境），或者卸载。' 'The same version is already on this computer. You can repair it (copy the program files again, complete the environment) or remove it.' }
                     else { T '会用这个版本替换程序文件。你的数据原样保留。' 'The program files are replaced with this version. Your data stays as it is.' }
    $ui.ExistBox.Visibility = 'Visible'
    $ui.ExistHead.Text = (T '已安装的版本：' 'Installed version: ') + $inst.Version + (T '　　这个安装包：' '      This package: ') + $pkgVer
    $ui.ExistPath.Text = (T '位置：' 'Location: ') + $inst.Dir
    $ui.ExistNote.Text = T '岗位、草案、个人资料、上传的文件（data 和 knowledge 文件夹）不会被改动。' 'Jobs, drafts, your profile and uploaded files (the data and knowledge folders) are not touched.'
    $ui.PathBox.Visibility = 'Collapsed'; $ui.OptBox.Visibility = 'Visible'
    if (-not $script:optsSeen) {
      # A copy that this setup installed before: the boxes show what is there now, so an upgrade keeps the user's earlier choice.
      # A copy that was never set up this way (unzipped and started by hand) has made no such choice: both shortcuts are offered, ticked.
      $script:optsSeen = $true
      $viaSetup = Test-Path $RegKey
      $ui.OptDesktop.IsChecked = (-not $viaSetup) -or (Test-Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'AutoApply.lnk'))
      $ui.OptStart.IsChecked = (-not $viaSetup) -or (Test-Path (Join-Path ([Environment]::GetFolderPath('Programs')) 'AutoApply.lnk'))
      try { $ui.OptAuto.IsChecked = [bool](Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'AutoApply' -ErrorAction Stop) } catch { $ui.OptAuto.IsChecked = $false }
    }
    $ui.MainBtn.Content = if ($same) { T '修复' 'Repair' } else { (T '升级到 ' 'Upgrade to ') + $pkgVer }
    $ui.SecondBtn.Visibility = 'Visible'; $ui.SecondBtn.Style = $win.FindResource('Danger'); $ui.SecondBtn.Content = T '卸载…' 'Uninstall...'
  } else {
    $ui.ChTitle.Text = T '安装 AutoApply' 'Install AutoApply'
    $ui.ChSub.Text = T '在你自己电脑上运行的求职助手：找岗位、按你的规则评分、准备申请草案，你批准后替你填表。' 'A job-search assistant that runs on your own computer: it finds postings, scores them by your rules, prepares each application as a draft and fills in the form after you approve it.'
    $ui.ExistBox.Visibility = 'Collapsed'; $ui.PathBox.Visibility = 'Visible'; $ui.OptBox.Visibility = 'Visible'
    $ui.PathLabel.Text = T '安装位置' 'Install location'; $ui.BrowseBtn.Content = T '浏览…' 'Browse...'; $ui.PathText.Text = $script:target
    $ui.PathHint.Text = T '程序和你的数据都放在这个文件夹里（数据在其中的 data 和 knowledge）。需要约 1.5 GB 空间。' 'The program and your data both live in this folder (data in its data and knowledge subfolders). About 1.5 GB is needed.'
    $ui.MainBtn.Content = T '安装' 'Install'
  }
}
function Enter-Remove {
  $script:state = 'remove'; $script:removing = $true; Show-Page 'PgRemove'
  $ui.RmTitle.Text = T '卸载 AutoApply' 'Uninstall AutoApply'
  $ui.RmSub.Text = (T '位置：' 'Location: ') + $script:target
  $ui.RmKeepT.Text = T '保留我的数据' 'Keep my data'
  $ui.RmKeepD.Text = T '只删除程序。岗位、草案、个人资料和上传的文件留在原文件夹里，以后重新安装可以接着用。' 'Only the program is removed. Jobs, drafts, your profile and uploaded files stay in the folder, and a later install picks them up again.'
  $ui.RmAllT.Text = T '连数据一起删除' 'Delete my data too'
  $ui.RmAllD.Text = T '整个文件夹都会删除，无法恢复。想留一份的话，先在程序的“设置 → 高级”里导出。' 'The whole folder is deleted and cannot be brought back. To keep a copy, export it first under Settings > Advanced in the program.'
  $ui.RmNote.Text = T '程序保存的密码和 API key 在 Windows 的“凭据管理器”里（名称含 autoapply），卸载不会动它们，需要的话请在那里删除。' 'Passwords and API keys the program stored are in the Windows Credential Manager (names containing autoapply). Uninstalling leaves them; remove them there if you wish.'
  $ui.MainBtn.Content = T '卸载' 'Uninstall'; $ui.MainBtn.Style = $win.FindResource('Primary'); $ui.MainBtn.IsEnabled = $true
  $ui.SecondBtn.Visibility = 'Collapsed'
  $ui.LeftBtn.Visibility = if ($Mode -eq 'install') { 'Visible' } else { 'Collapsed' }; $ui.LeftBtn.Content = T '← 返回' '← Back'
}
function Enter-Work {
  $script:state = 'work'; Show-Page 'PgWork'
  $labels = if ($script:removing) { Get-RemoveSteps } else { Get-InstallSteps }
  $ui.WkTitle.Text = if ($script:removing) { T '正在卸载…' 'Uninstalling...' } elseif ($inst) { T '正在更新…' 'Updating...' } else { T '正在安装…' 'Installing...' }
  $ui.WkSub.Text = if ($script:removing) { $script:target } else { T '第一次需要几分钟，主要是下载。这个窗口可以放在一边。' 'A few minutes the first time, mostly downloading. You can leave this window alone.' }
  Set-Steps $labels 0 $false; $ui.WkLine.Text = ''
  $ui.MainBtn.IsEnabled = $false; $ui.MainBtn.Content = T '请稍候' 'Please wait'; $ui.SecondBtn.Visibility = 'Collapsed'; $ui.LeftBtn.Visibility = 'Collapsed'; $ui.CloseBtn.Visibility = 'Hidden'
}
function Enter-Done([string]$err) {
  Show-Page 'PgDone'; $ui.CloseBtn.Visibility = 'Visible'; $ui.MainBtn.IsEnabled = $true; $ui.SecondBtn.Visibility = 'Collapsed'; $ui.LeftBtn.Visibility = 'Collapsed'
  $script:lastError = $err
  if ($err) {
    $script:state = 'failed'
    $ui.DoneIcon.Background = Brush $tok.badSoft; $ui.DoneGlyph.Stroke = Brush $tok.bad; $ui.DoneGlyph.Data = [Windows.Media.Geometry]::Parse('M2,2 L18,18 M18,2 L2,18')
    $ui.DnTitle.Text = if ($script:removing) { T '没有卸载完' 'The uninstall did not finish' } else { T '没有装完' 'Setup did not finish' }
    $ui.DnSub.Text = $err + "`n" + (T '已经完成的部分不会丢，再试一次会从停下的地方继续。' 'What was done is kept; trying again continues from where it stopped.')
    $ui.DnLaunch.Visibility = 'Collapsed'
    $ui.MainBtn.Content = T '再试一次' 'Try again'
    $ui.LeftBtn.Visibility = 'Visible'; $ui.LeftBtn.Content = T '查看日志' 'Show the log'
  } else {
    $script:state = 'done'
    $ui.DoneIcon.Background = Brush $tok.okSoft; $ui.DoneGlyph.Stroke = Brush $tok.ok; $ui.DoneGlyph.Data = [Windows.Media.Geometry]::Parse('M2,11 L8.5,17.5 L21,4')
    if ($script:removing) {
      $ui.DnTitle.Text = T '已卸载' 'Uninstalled'
      $ui.DnSub.Text = if ($ui.RmAll.IsChecked) { T '程序和数据都已删除。' 'The program and its data were deleted.' } else { (T '程序已删除。你的数据还在：' 'The program was removed. Your data is still in: ') + $script:target }
      $ui.DnLaunch.Visibility = 'Collapsed'
    } else {
      $ui.DnTitle.Text = if ($inst) { T '更新完成' 'Updated' } else { T '安装完成' 'Installed' }
      $ui.DnSub.Text = T '以后从桌面或开始菜单里的 AutoApply 启动。启动后屏幕右下角的托盘里会有它的图标，网页会自动打开。' 'Start it with the AutoApply shortcut on the desktop or in the Start menu. Its icon then sits in the tray and the page opens by itself.'
      $ui.DnLaunch.Visibility = 'Visible'; $ui.DnLaunch.Content = T '现在启动 AutoApply' 'Start AutoApply now'
    }
    $ui.MainBtn.Content = T '完成' 'Done'
  }
}

function Start-Work {
  Enter-Work
  $o = New-Options $script:target
  $o.Mode = if ($script:removing) { 'uninstall' } else { 'install' }
  $o.DeleteData = [bool]$ui.RmAll.IsChecked
  $o.Desktop = [bool]$ui.OptDesktop.IsChecked; $o.StartMenu = [bool]$ui.OptStart.IsChecked; $o.Autostart = [bool]$ui.OptAuto.IsChecked
  $script:sync = [hashtable]::Synchronized(@{ Step = 0; Line = ''; Done = $false; Error = '' })
  $script:ps = [powershell]::Create()
  [void]$script:ps.AddScript($Work.ToString()).AddArgument($script:sync).AddArgument($o)
  [void]$script:ps.BeginInvoke()
  $timer.Start()
}

$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(200)
$timer.Add_Tick({
  $labels = if ($script:removing) { Get-RemoveSteps } else { Get-InstallSteps }
  Set-Steps $labels ([int]$script:sync.Step) ([bool]$script:sync.Error)
  $ui.WkLine.Text = [string]$script:sync.Line
  if ($script:sync.Done) { $timer.Stop(); Enter-Done ([string]$script:sync.Error) }
})

$ui.Header.Add_MouseLeftButtonDown({ try { $win.DragMove() } catch { } })
$ui.LangZh.Add_MouseLeftButtonDown({ $_.Handled = $true; Set-Lang $true })
$ui.LangEn.Add_MouseLeftButtonDown({ $_.Handled = $true; Set-Lang $false })
$ui.CloseBtn.Add_Click({ $win.Close() })
$ui.BrowseBtn.Add_Click({
  $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
  $dlg.Description = T '选一个文件夹，AutoApply 会装到它里面的 AutoApply 子文件夹' 'Choose a folder; AutoApply goes into an AutoApply subfolder of it'
  if ($dlg.ShowDialog() -eq 'OK') { $p = $dlg.SelectedPath; if ((Split-Path -Leaf $p) -ne 'AutoApply') { $p = Join-Path $p 'AutoApply' }; $ui.PathText.Text = $p }
})
$ui.SecondBtn.Add_Click({ if ($script:state -eq 'choose') { Enter-Remove } })
$ui.LeftBtn.Add_Click({
  if ($script:state -eq 'remove') { $script:removing = $false; Enter-Choose }
  elseif ($script:state -eq 'failed') { Start-Process notepad.exe $LogFile }
})
$ui.MainBtn.Add_Click({
  switch ($script:state) {
    'choose' {
      if (-not $inst) {
        $p = $ui.PathText.Text.Trim().Trim('"')
        $bad = $null
        if (-not $p -or -not [IO.Path]::IsPathRooted($p)) { $bad = T '请填写完整的文件夹路径，例如 D:\Apps\AutoApply。' 'Give a full folder path, for example D:\Apps\AutoApply.' }
        elseif ((Test-Path $p) -and -not (Get-Version $p) -and (Get-ChildItem -Force $p | Select-Object -First 1)) { $bad = T '这个文件夹里已经有别的东西了。请选一个空文件夹，或让程序新建一个。' 'That folder already has other things in it. Choose an empty folder, or let setup create a new one.' }
        else { try { New-Item -ItemType Directory -Force -Path $p | Out-Null } catch { $bad = (T '不能在这里创建文件夹：' 'A folder cannot be created there: ') + $_.Exception.Message } }
        if ($bad) { $ui.PathHint.Text = $bad; $ui.PathHint.Foreground = Brush $tok.bad; return }
        $script:target = $p
      }
      $script:removing = $false; Start-Work
    }
    'remove' { Start-Work }
    'failed' { Start-Work }
    'done' {
      if (-not $script:removing -and $ui.DnLaunch.IsChecked) {
        $pyw = Join-Path $script:target '.venv\Scripts\pythonw.exe'
        if (Test-Path $pyw) { Start-Process -FilePath $pyw -ArgumentList '-m', 'autoapply.launcher' -WorkingDirectory $script:target }
      }
      $win.Close()
    }
  }
})
$win.Add_Closing({ if ($script:state -eq 'work') { $_.Cancel = $true } })

Set-LangUi
if ($script:removing) {
  if (-not (Get-Version $script:target) -and -not $Shot) { [void][System.Windows.MessageBox]::Show((T '没有找到已安装的 AutoApply。' 'No installed AutoApply was found.'), 'AutoApply'); exit 0 }
  Enter-Remove
} else { Enter-Choose }

function Save-Shot([string]$path) {
  $scale = 2.0
  $rtb = New-Object Windows.Media.Imaging.RenderTargetBitmap([int]($win.ActualWidth * $scale), [int]($win.ActualHeight * $scale), (96 * $scale), (96 * $scale), [Windows.Media.PixelFormats]::Pbgra32)
  $rtb.Render($win.Content)
  $enc = New-Object Windows.Media.Imaging.PngBitmapEncoder
  $enc.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($rtb))
  $fs = [IO.File]::Create($path); $enc.Save($fs); $fs.Close()
}

if ($Auto) {
  # the real window, driven the way a person would: press the main button, wait for the work to end
  $script:pressed = $false
  $driver = New-Object Windows.Threading.DispatcherTimer
  $driver.Interval = [TimeSpan]::FromMilliseconds(500)
  $driver.Add_Tick({
    if (-not $script:pressed -and $script:state -in 'choose', 'remove') {
      $script:pressed = $true
      # switch the language and back, as a person might, before going on
      $before = if ($script:state -eq 'choose') { $ui.ChTitle.Text } else { $ui.RmTitle.Text }
      Set-Lang (-not $script:zh)
      $other = if ($script:state -eq 'choose') { $ui.ChTitle.Text } else { $ui.RmTitle.Text }
      Set-Lang (-not $script:zh)
      $script:langCheck = "{0} -> {1}" -f $before, $other
      $ui.MainBtn.RaiseEvent((New-Object Windows.RoutedEventArgs([Windows.Controls.Primitives.ButtonBase]::ClickEvent)))
    } elseif ($script:state -in 'done', 'failed') {
      $driver.Stop()
      if ($Shot) { Save-Shot $Shot }
      Set-Content -Path ($LogFile + '.result') -Value ("{0}|{1}|{2}|lang: {3}" -f $script:state, $ui.DnTitle.Text, $ui.DnSub.Text, $script:langCheck) -Encoding UTF8
      $ui.DnLaunch.IsChecked = $false
      $script:state = 'closed'; $win.Close()
    }
  })
  $driver.Start()
} elseif ($Shot) {
  # draw one page to a file, for review; nothing is installed
  switch ($Page) {
    'existing' { $inst = @{ Dir = $DefaultDir; Version = '0.9.0' }; Enter-Choose }
    'same' { $inst = @{ Dir = $DefaultDir; Version = $pkgVer }; Enter-Choose }
    'progress' { Enter-Work; Set-Steps (Get-InstallSteps) 2 $false; $ui.WkLine.Text = 'Downloading cpython-3.12.7-windows-x86_64 (21.4MiB)' }
    'done' { Enter-Done '' }
    'failed' { Enter-Work; Enter-Done (T 'Installing Python and the dependencies failed (usually the network). Run setup again to continue where it stopped.' 'Installing Python and the dependencies failed (usually the network).') }
    'uninstall' { $script:removing = $true; Enter-Remove }
    default { }
  }
  $win.ShowInTaskbar = $false; $win.WindowStartupLocation = 'Manual'; $win.Left = -3000; $win.Top = -3000
  $win.Show(); $win.UpdateLayout()
  $win.Dispatcher.Invoke([Action] { }, [Windows.Threading.DispatcherPriority]::Render)
  Save-Shot $Shot
  $win.Close(); exit 0
}

[void]$win.ShowDialog()
$mutex.ReleaseMutex()
