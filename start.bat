@echo off
rem AutoApply: install what is missing, then start. Safe to run every time.
rem Optional: set AUTOAPPLY_PORT=8010 before running to use another port.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem an installed copy brings its own uv
if exist "%~dp0tools\uv.exe" set "PATH=%~dp0tools;%PATH%"
if "%AUTOAPPLY_PORT%"=="" set AUTOAPPLY_PORT=8000

where uv >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if not errorlevel 1 goto have_uv
echo [AutoApply] uv is needed (a small tool from astral.sh that prepares the Python environment).
set /p ANS="[AutoApply] Download and install it now? (Y/N) "
if /i "%ANS%"=="Y" goto get_uv
echo [AutoApply] OK. Install it yourself, then run this again: https://docs.astral.sh/uv/
pause
exit /b 1
:get_uv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
:have_uv
where uv >nul 2>nul
if errorlevel 1 ( echo [AutoApply] uv could not be installed: see the messages above. & pause & exit /b 1 )

echo [AutoApply] checking dependencies (a few minutes the first time)...
rem --inexact: keep optional components that were added later (the ChatGPT sign-in component); a plain sync would remove them on every start
uv sync --inexact
if errorlevel 1 ( echo [AutoApply] the dependencies could not be installed: see the messages above. & pause & exit /b 1 )

rem Asked for every time: it returns at once when the right build is there, and a newer Playwright needs a newer build.
echo [AutoApply] checking the browser the program uses (a download the first time and after some upgrades)...
uv run playwright install chromium
if errorlevel 1 ( echo [AutoApply] the browser could not be downloaded: see the messages above. & pause & exit /b 1 )

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [AutoApply] this copy has no built interface. Download the release package ^(it includes one^), or install Node.js and run this again: https://nodejs.org/
    pause
    exit /b 1
  )
  echo [AutoApply] building the interface ^(once^)...
  pushd frontend
  call npm install
  call npm run build
  popd
)

if not "%AUTOAPPLY_NO_BROWSER%"=="" goto console
if not "%AUTOAPPLY_CONSOLE%"=="" goto console
echo.
echo [AutoApply] starting. An AutoApply icon appears in the tray at the bottom right of the screen; the page opens by itself.
echo [AutoApply] Use the icon to open the page, see the status, start at sign-in, or quit. This window can be closed.
start "" /b uv run pythonw -m autoapply.launcher --port %AUTOAPPLY_PORT%
timeout /t 4 >nul
exit /b 0

:console
rem Without the tray: the server runs in this window (closing it stops the server). Set AUTOAPPLY_CONSOLE=1 to choose this.
echo.
echo [AutoApply] starting. Open http://127.0.0.1:%AUTOAPPLY_PORT% in your browser (closing this window stops it).
echo.
uv run autoapply serve --port %AUTOAPPLY_PORT%
